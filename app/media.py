"""Discover media away from the viewer, then relay only granted HLS resources.

No provider page or script is ever sent to the viewing browser. A fresh isolated
Chromium context observes the provider's normal playback requests. The relay pins
public DNS results and preserves only the media request's Origin/Referer/User-Agent.
"""

import asyncio
import hashlib
import ipaddress
import os
import re
import secrets
import socket
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession, RequestsError
from fastapi import HTTPException
from playwright.async_api import Error as BrowserError
from playwright.async_api import async_playwright

from app.providers import public_https


def browser_environment():
    """Use optional project-local runtime libraries installed without sudo."""
    env = os.environ.copy()
    root = Path(__file__).resolve().parent.parent / ".runtime" / "chromium-libs"
    directories = sorted(
        path for path in (root / "usr" / "lib").glob("*-linux-gnu") if path.is_dir()
    )
    if directories:
        entries = [str(path) for path in directories]
        if env.get("LD_LIBRARY_PATH"):
            entries.append(env["LD_LIBRARY_PATH"])
        env["LD_LIBRARY_PATH"] = os.pathsep.join(entries)
    return env


async def public_address(url):
    if not public_https(url):
        raise ValueError("Only public HTTPS media destinations are supported")
    host = urlsplit(url).hostname
    addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Private network destinations are not allowed")
    return next((ip for ip in ips if ":" not in ip), ips[0])


async def read_public(client, url, headers, byte_range=None):
    """Validate every redirect and pin DNS to the checked IP (including TLS SNI)."""
    for _ in range(5):
        ip = await public_address(url)
        original = httpx.URL(url)
        outbound = {**headers, "Host": original.host}
        if byte_range:
            if not re.fullmatch(r"bytes=\d*-\d*", byte_range):
                raise ValueError("Unsupported byte range")
            outbound["Range"] = byte_range
        async with client.stream(
            "GET",
            original.copy_with(host=ip),
            headers=outbound,
            extensions={"sni_hostname": original.host},
        ) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            data = bytearray()
            async for part in response.aiter_bytes():
                data.extend(part)
                if len(data) > 16_000_000:
                    raise ValueError("Media resource exceeded size limit")
            return bytes(data), url, response.status_code, response.headers
    raise ValueError("Too many media redirects")


async def read_browser_public(url, headers, byte_range=None, sessions=None):
    """Browser-compatible TLS for media hosts that reject the standard client.

    Each request pins its checked DNS address and disables proxy/environment
    routing; redirects are followed only after validating their destination.
    """
    outbound = dict(headers)
    if byte_range:
        if not re.fullmatch(r"bytes=\d*-\d*", byte_range):
            raise ValueError("Unsupported byte range")
        outbound["Range"] = byte_range
    owned_sessions = {} if sessions is None else None
    pool = sessions if sessions is not None else owned_sessions
    try:
        for _ in range(5):
            ip = await public_address(url)
            host = urlsplit(url).hostname
            address = f"[{ip}]" if ":" in ip else ip
            key = (host, ip)
            client = pool.get(key)
            if client is None:
                client = AsyncSession(
                    impersonate="chrome",
                    max_clients=12,
                    curl_options={
                        CurlOpt.RESOLVE: [f"{host}:443:{address}"],
                        CurlOpt.PROXY: "",
                    },
                )
                pool[key] = client
            response = await client.get(
                url, headers=outbound, timeout=15, allow_redirects=False, stream=True
            )
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_content():
                    data.extend(chunk)
                    if len(data) > 16_000_000:
                        raise ValueError("Media resource exceeded size limit")
                return bytes(data), url, response.status_code, response.headers
            finally:
                await response.aclose()
        raise ValueError("Too many media redirects")
    finally:
        if owned_sessions:
            await asyncio.gather(
                *(client.close() for client in owned_sessions.values()), return_exceptions=True
            )


@dataclass
class Playback:
    id: str
    headers: dict
    browser_http: bool = False
    expires: float = field(default_factory=lambda: time.monotonic() + 4 * 3600)
    resources: dict = field(default_factory=dict)

    def grant(self, url):
        if not public_https(url):
            raise ValueError("Unsupported media URL")
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        if len(self.resources) >= 8192 and key not in self.resources:
            raise ValueError("Playback resource limit reached; reload the source")
        self.resources[key] = url
        return f"/api/media/{self.id}/{key}"

    def playlist(self, text, base):
        if not text.lstrip().startswith("#EXTM3U"):
            raise ValueError("The provider did not return an HLS playlist")
        if "#EXT-X-DEFINE" in text or "SAMPLE-AES" in text:
            raise ValueError("This playlist format is not supported")
        lines = []
        for line in text.splitlines():
            if line.startswith("#"):
                line = re.sub(
                    r'URI="([^"\r\n]+)"',
                    lambda match: f'URI="{self.grant(urljoin(base, match[1]))}"',
                    line,
                )
            elif line.strip():
                line = self.grant(urljoin(base, line.strip()))
            lines.append(line)
        return "\n".join(lines) + "\n"


class MediaService:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.playbacks = {}
        self.automation = None
        self.browser = None
        self.browser_clients = {}
        self.client = httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False)

    async def close(self):
        if self.browser:
            with suppress(Exception):
                await self.browser.close()
        if self.automation:
            with suppress(Exception):
                await self.automation.stop()
        if self.browser_clients:
            await asyncio.gather(
                *(client.close() for client in self.browser_clients.values()),
                return_exceptions=True,
            )
        await self.client.aclose()

    async def discover(self, source):
        try:
            async with asyncio.timeout(17):
                return await self._discover(source)
        except TimeoutError as exc:
            raise HTTPException(
                422, "Video discovery timed out. Try another source or reload."
            ) from exc

    async def _discover(self, source):
        if self.lock.locked():
            raise HTTPException(
                409, "Another source is still resolving. Wait a moment, then reload this source."
            )
        async with self.lock:
            try:
                if not self.browser or not self.browser.is_connected():
                    if not self.automation:
                        self.automation = await async_playwright().start()
                    self.browser = await self.automation.chromium.launch(
                        channel="chromium", headless=True, env=browser_environment()
                    )
            except BrowserError as exc:
                raise HTTPException(
                    503,
                    "The video discovery browser could not start. Run: uv run python -m app.setup_browser, then restart the app.",
                ) from exc
            context = await self.browser.new_context(
                accept_downloads=False, service_workers="block"
            )
            found = asyncio.get_running_loop().create_future()
            tasks = set()
            checked_hosts = set()

            async def restrict(route):
                try:
                    url = route.request.url
                    if not public_https(url):
                        await route.abort()
                        return
                    destination = urlsplit(url)
                    host = destination.hostname
                    if route.request.resource_type in ("image", "font") or (
                        host in ("streamfree.top", "strmfree.st")
                        and destination.path in ("/analytics.js", "/ad.html")
                    ):
                        await route.abort()
                        return
                    if host not in checked_hosts:
                        await public_address(url)
                        checked_hosts.add(host)
                    await route.continue_()
                except (ValueError, OSError, BrowserError):
                    try:
                        await route.abort()
                    except BrowserError:
                        pass

            async def observe(response):
                if found.done() or response.status != 200:
                    return
                mime = response.headers.get("content-type", "").lower()
                if ".m3u8" not in response.url and "mpegurl" not in mime:
                    return
                try:
                    body = await response.body()
                    if len(body) > 1_000_000 or not body.lstrip().startswith(b"#EXTM3U"):
                        return
                    headers = await response.request.all_headers()
                    # No cookies, authorization, or arbitrary browser headers are persisted.
                    headers = {
                        k: v for k, v in headers.items() if k in ("origin", "referer", "user-agent")
                    }
                    if not found.done():
                        found.set_result((response.url, headers))
                except BrowserError:
                    pass

            def on_response(response):
                task = asyncio.create_task(observe(response))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

            try:
                await context.route("**/*", restrict)
                await context.add_init_script("window.open = () => null;")
                page = await context.new_page()
                page.on("response", on_response)
                # Any unexpected popup stays away from the viewer and is closed immediately.
                context.on(
                    "page",
                    lambda popup: asyncio.create_task(popup.close()) if popup != page else None,
                )
                url = source.get("discovery_url", source["url"])
                try:
                    await page.goto(
                        url,
                        referer=source.get("discovery_referer"),
                        wait_until="commit",
                        timeout=12000,
                    )
                except BrowserError:
                    pass
                try:
                    return await asyncio.wait_for(found, timeout=18)
                except TimeoutError as exc:
                    raise HTTPException(
                        422,
                        "No usable direct video found for this source. Try another source; the ad player will not be loaded.",
                    ) from exc
            finally:
                for task in list(tasks):
                    task.cancel()
                # A stalled browser must not hold the discovery lock indefinitely.
                with suppress(BrowserError, TimeoutError):
                    async with asyncio.timeout(3):
                        await context.close()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self, source):
        url, headers = await self.discover(source)
        try:
            browser_http = False
            try:
                body, final_url, _, _ = await read_public(self.client, url, headers)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 403:
                    raise
                body, final_url, _, _ = await read_browser_public(
                    url, headers, sessions=self.browser_clients
                )
                browser_http = True
            playback = Playback(secrets.token_urlsafe(24), headers, browser_http=browser_http)
            playback.playlist(body.decode("utf-8-sig"), final_url)
        except (ValueError, OSError, httpx.HTTPError, RequestsError) as exc:
            raise HTTPException(
                422, "The provider's video could not be played independently. Try another source."
            ) from exc
        self.playbacks = {
            key: item for key, item in self.playbacks.items() if item.expires > time.monotonic()
        }
        if len(self.playbacks) >= 8:
            del self.playbacks[next(iter(self.playbacks))]
        self.playbacks[playback.id] = playback
        return {"url": playback.grant(final_url), "session": playback.id, "label": source["label"]}

    async def resource(self, session, key, byte_range=None):
        playback = self.playbacks.get(session)
        if not playback or playback.expires <= time.monotonic():
            self.playbacks.pop(session, None)
            raise HTTPException(410, "Playback expired. Reload the source.")
        url = playback.resources.get(key)
        if not url:
            raise HTTPException(404, "Unknown media resource")
        try:
            if playback.browser_http:
                body, final_url, status, headers = await read_browser_public(
                    url, playback.headers, byte_range, self.browser_clients
                )
            else:
                body, final_url, status, headers = await read_public(
                    self.client, url, playback.headers, byte_range
                )
            if body.lstrip().startswith(b"#EXTM3U"):
                return (
                    playback.playlist(body.decode("utf-8-sig"), final_url).encode(),
                    "application/vnd.apple.mpegurl",
                    200,
                    {},
                )
            if "text/html" in headers.get("content-type", "") or body.lstrip().lower().startswith(
                (b"<!doctype", b"<html")
            ):
                raise ValueError("Received a webpage instead of video")
            extra = {
                key: headers[key] for key in ("content-range", "accept-ranges") if key in headers
            }
            return body, "application/octet-stream", status, extra
        except (ValueError, OSError, httpx.HTTPError, RequestsError) as exc:
            raise HTTPException(502, "Video data unavailable from provider") from exc
