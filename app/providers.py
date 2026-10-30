"""Small provider adapters. Only listing/API/channel pages are fetched by Python.

The browser loads third-party players directly; this is not a video proxy.
"""

import asyncio
import hashlib
import ipaddress
import math
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

PROVIDERS = {
    "streamed": "https://streamed.pk/category/football",
    "streamfree": "https://streamfree.top/",
    "fsl": "https://freestreams-live1g.pk/football-streamz5/",
}
NAMES = {"streamed": "Streamed", "streamfree": "StreamFree", "fsl": "FSL"}


def public_https(value):
    """Validate browser destinations; never accept script URLs or local hosts."""
    if not isinstance(value, str) or any(c.isspace() for c in value) or "\\" in value:
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.scheme != "https" or not host or parts.username or parts.password:
            return None
        if parts.port not in (None, 443):
            return None
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def timestamp(value, divisor=1):
    try:
        result = float(value) / divisor
        return result if math.isfinite(result) and 0 < result < 253402300800 else None
    except (ValueError, TypeError):
        return None


def event(provider, identifier, title, starts_at, league="", sport="football", **extra):
    return {
        "id": hashlib.sha256(f"{provider}:{sport}:{identifier}".encode()).hexdigest()[:24],
        "provider": provider,
        "sport": sport,
        "title": str(title),
        "starts_at": starts_at,
        "league": str(league or "Football"),
        "page_url": PROVIDERS[provider],
        **extra,
    }


def parse_streamed(data, sport="football"):
    if not isinstance(data, list):
        raise TypeError("Unexpected match response")
    return [
        event(
            "streamed",
            row["id"],
            row["title"],
            timestamp(row.get("date"), 1000),
            "NBA" if sport == "basketball" else "Football",
            sport=sport,
            sources=row.get("sources") or [],
            page_url=f"https://streamed.pk/category/{sport}",
        )
        for row in data
        if isinstance(row, dict)
        and row.get("id")
        and row.get("title")
        and row.get("category", sport) == sport
    ]


def parse_streamfree(data):
    if not isinstance(data, dict) or not isinstance(data.get("streams"), list):
        raise TypeError("Unexpected stream listing response")
    result = []
    for row in data["streams"]:
        if not isinstance(row, dict) or not row.get("stream_key") or not row.get("name"):
            continue
        category = row.get("category")
        sport = {"soccer": "football", "basketball": "basketball"}.get(category)
        if sport is None:
            continue
        key = str(row["stream_key"])
        result.append(
            event(
                "streamfree",
                key,
                row["name"],
                timestamp(row.get("match_timestamp")),
                row.get("league") or ("NBA" if sport == "basketball" else "Football"),
                sport=sport,
                key=key,
                page_url=f"https://streamfree.top/player/{category}/{quote(key, safe='')}",
            )
        )
    return result


def parse_fsl(html):
    soup = BeautifulSoup(html, "html5lib")
    table = soup.select_one("#myTable")
    if table is None:
        raise ValueError(
            "Football table missing; the site may have changed or blocked this request"
        )
    result = []
    for row in table.select("tr"):
        title = row.select_one(".event-title")
        if not title:
            continue
        channels = []
        for link in row.select(".buttoncontainer a[href]"):
            url = public_https(urljoin(PROVIDERS["fsl"], link["href"]))
            if url and urlsplit(url).hostname == "freestreams-live1g.pk":
                channels.append({"label": link.get_text(" ", strip=True), "url": url})
        name = title.get_text(" ", strip=True)
        league = row.select_one(".leaguename")
        result.append(
            event(
                "fsl",
                row.get("id") or name,
                name,
                timestamp(row.get("data-timestamp"), 1000),
                league.get_text(" ", strip=True) if league else "Football",
                channels=channels,
            )
        )
    return result


def parse_frames(html, page_url, label):
    soup = BeautifulSoup(html, "html.parser")
    # Restrict extraction to the article, excluding sidebar/chat frames.
    article = soup.select_one(".entry-content") or soup.select_one("article")
    if article is None:
        return []
    result = []
    for frame in article.select("iframe[src], iframe[data-src]"):
        url = public_https(urljoin(page_url, frame.get("src") or frame.get("data-src", "")))
        if url and "chatango.com" not in urlsplit(url).hostname:
            result.append({"label": label, "url": url})
    return result


async def fetch(client, url, as_json=True):
    # No automatic redirects: changed provider domains must be reviewed explicitly.
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > 4_000_000:
                raise ValueError("Provider response too large")
        import json

        return json.loads(chunks) if as_json else chunks.decode("utf-8", errors="replace")


def failure(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Provider returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "Provider timed out"
    if isinstance(exc, httpx.RequestError):
        return "Could not connect to provider"
    return "Provider format changed or response could not be read"


async def load_provider(client, provider):
    if provider == "streamed":
        results = await asyncio.gather(
            fetch(client, "https://streamed.pk/api/matches/football"),
            fetch(client, "https://streamed.pk/api/matches/basketball"),
            return_exceptions=True,
        )
        rows = []
        for sport, result in zip(("football", "basketball"), results):
            if not isinstance(result, Exception):
                rows.extend(parse_streamed(result, sport))
        if not rows and all(isinstance(result, Exception) for result in results):
            raise results[0]
        return rows
    if provider == "streamfree":
        return parse_streamfree(await fetch(client, "https://streamfree.top/api/v1/streams"))
    return parse_fsl(await fetch(client, PROVIDERS["fsl"], as_json=False))


async def resolve(client, match):
    """Resolve only source references obtained from the known providers."""
    provider = match["provider"]
    tasks = []
    labels = []
    if provider == "streamed":
        for source in match.get("sources", [])[:12]:
            if not isinstance(source, dict) or not source.get("source") or not source.get("id"):
                continue
            path = "/".join(quote(str(source[k]), safe="") for k in ("source", "id"))
            tasks.append(fetch(client, f"https://streamed.pk/api/stream/{path}"))
            labels.append(str(source["source"]))
    elif provider == "streamfree":
        key = quote(match["key"], safe="")
        tasks.append(fetch(client, f"https://streamfree.top/api/v1/sources/{key}"))
        labels.append("StreamFree")
    else:
        for channel in match.get("channels", [])[:16]:
            tasks.append(fetch(client, channel["url"], as_json=False))
            labels.append(channel)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    streams, warnings = [], []
    for label, data in zip(labels, results):
        if isinstance(data, Exception):
            warnings.append(
                f"{label['label'] if isinstance(label, dict) else label}: {failure(data)}"
            )
            continue
        if provider == "streamed" and isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                url = public_https(row.get("embedUrl"))
                if url:
                    quality = "HD" if row.get("hd") else "SD"
                    streams.append(
                        {
                            "url": url,
                            "label": f"{label} · {row.get('language') or 'Unknown language'} · {quality} · {row.get('streamNo', 1)}",
                        }
                    )
        elif (
            provider == "streamfree"
            and isinstance(data, dict)
            and isinstance(data.get("sources"), list)
        ):
            for i, source in enumerate(data["sources"], 1):
                # StreamFree now includes quality metadata; older responses used URL strings.
                url = public_https(source.get("url") if isinstance(source, dict) else source)
                if url:
                    label = f"StreamFree · Source {i}"
                    quality = source.get("quality") if isinstance(source, dict) else None
                    if isinstance(quality, str) and quality.strip():
                        label += f" · {quality.strip()}"
                    stream = {"url": url, "label": label}
                    parts = urlsplit(url)
                    page = urlsplit(match["page_url"])
                    # StreamFree's own page uses same-mirror embeds with autoplay.
                    # The API can still advertise embeds on a different mirror.
                    if parts.hostname in (
                        "strmfree.st",
                        "streamfree.top",
                    ) and parts.path.startswith("/embed/"):
                        query = [
                            item
                            for item in parse_qsl(parts.query, keep_blank_values=True)
                            if item[0] != "autostart"
                        ]
                        query.append(("autostart", "1"))
                        stream["discovery_url"] = urlunsplit(
                            (page.scheme, page.netloc, parts.path, urlencode(query), "")
                        )
                        stream["discovery_referer"] = match["page_url"]
                    streams.append(stream)
        elif provider == "fsl" and isinstance(data, str):
            for stream in parse_frames(data, label["url"], label["label"]):
                stream["discovery_url"] = label["url"]
                streams.append(stream)
        else:
            warnings.append(f"{label}: Unexpected source response")
    # The same iframe can be returned by several channels.
    unique = {stream["url"]: stream for stream in streams}
    for stream in unique.values():
        stream["id"] = hashlib.sha256(stream["url"].encode()).hexdigest()[:24]
    return {"streams": list(unique.values()), "warnings": warnings, "page_url": match["page_url"]}
