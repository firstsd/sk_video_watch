import asyncio

import httpx
import pytest

from app.main import Catalog
from app.providers import (
    parse_frames,
    parse_fsl,
    parse_streamed,
    parse_streamfree,
    public_https,
    resolve,
)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://example.com/player",
        "https://127.0.0.1/player",
        "https://localhost/a",
        "https://192.168.1.1",
        "https://[::1]/",
        "https://test.local/a",
        "https://user:password@example.com/",
        "https://example.com:8000/",
        "//example.com",
        "https://good.com\\@127.0.0.1/",
        "https://example.com/\nscript",
        None,
    ],
)
def test_rejects_unsafe_browser_destinations(url):
    assert public_https(url) is None


def test_keeps_https_embed_query():
    url = "https://player.example.com/embed?id=abc&token=xyz"
    assert public_https(url) == url


def test_providers_normalize_seconds_and_milliseconds():
    streamed = parse_streamed([{"id": "one", "title": "Arsenal vs Chelsea", "date": 1788607800000}])
    streamfree = parse_streamfree(
        {
            "streams": [
                {
                    "stream_key": "one",
                    "name": "Arsenal vs Chelsea",
                    "category": "soccer",
                    "match_timestamp": 1788607800,
                    "sources": [],
                }
            ]
        }
    )
    assert streamed[0]["starts_at"] == streamfree[0]["starts_at"] == 1788607800
    assert streamed[0]["id"] != streamfree[0]["id"]


def test_streamed_basketball_is_labeled_for_nba_view():
    rows = parse_streamed(
        [
            {
                "id": "nba-one",
                "title": "Seattle SuperSonics vs Portland Trail Blazers",
                "category": "basketball",
                "date": 1792888200000,
                "sources": [{"source": "hotel", "id": "nba-one"}],
            }
        ],
        "basketball",
    )
    assert rows[0]["sport"] == "basketball"
    assert rows[0]["league"] == "NBA"
    assert rows[0]["page_url"] == "https://streamed.pk/category/basketball"


def test_streamfree_mixed_feed_keeps_soccer_and_basketball_separate():
    rows = parse_streamfree(
        {
            "streams": [
                {
                    "stream_key": "shared-key",
                    "name": "Arsenal vs Chelsea",
                    "category": "soccer",
                },
                {
                    "stream_key": "shared-key",
                    "name": "Miami Heat vs Atlanta Hawks",
                    "category": "basketball",
                    "match_timestamp": 1793228400,
                },
                {"stream_key": "nfl", "name": "NFL game", "category": "football"},
                {"stream_key": "nhl", "name": "NHL game", "category": "hockey"},
            ]
        }
    )
    soccer, basketball = rows
    assert soccer["sport"] == "football"
    assert soccer["page_url"] == "https://streamfree.top/player/soccer/shared-key"
    assert basketball["sport"] == "basketball"
    assert basketball["league"] == "NBA"
    assert basketball["starts_at"] == 1793228400
    assert basketball["page_url"] == "https://streamfree.top/player/basketball/shared-key"
    assert soccer["id"] != basketball["id"]


def test_catalog_loads_streamfree_basketball_and_resolves_its_player():
    key = "miami-heat-vs-atlanta-hawks"
    embed = f"https://strmfree.st/embed/basketball/{key}1080p"
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "streamed.pk":
            return httpx.Response(301, headers={"Location": "https://streamed.pk/"})
        if request.url.host == "streamfree.top":
            if request.url.path == "/api/v1/streams":
                assert not request.url.query
                return httpx.Response(
                    200,
                    json={
                        "streams": [
                            {
                                "stream_key": key,
                                "name": "Miami Heat vs Atlanta Hawks",
                                "category": "basketball",
                                "league": "NBA",
                            }
                        ]
                    },
                )
            assert request.url.path == f"/api/v1/sources/{key}"
            return httpx.Response(200, json={"sources": [embed]})
        return httpx.Response(200, text='<table><tbody id="myTable"></tbody></table>')

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            catalog = Catalog(client)
            listing = await catalog.listing()
            assert len(listing["matches"]) == 1
            match = listing["matches"][0]
            assert match["sport"] == "basketball"
            assert match["league"] == "NBA"
            assert listing["providers"][0]["error"] == "Provider returned HTTP 301"
            assert listing["providers"][1]["count"] == 1
            source = (await catalog.streams(match["id"]))["streams"][0]
            assert source["url"] == embed
            assert source["discovery_url"] == (
                f"https://streamfree.top/embed/basketball/{key}1080p?autostart=1"
            )
            assert source["discovery_referer"] == (
                f"https://streamfree.top/player/basketball/{key}"
            )
            assert len(calls) == 5

    run(scenario())


def test_fsl_extracts_matches_and_only_known_channel_host():
    rows = parse_fsl("""<table><tbody id="myTable"><tr id="match" data-timestamp="1788607800000">
      <td class="leaguename">FA Cup</td><td class="event-title">Arsenal vs Chelsea</td>
      <td class="buttoncontainer"><a href="/sports/">Sports</a>
      <a href="http://127.0.0.1/admin">Local</a><a href="https://unrelated.example/">Ad</a></td>
      </tr></tbody></table>""")
    assert rows[0]["league"] == "FA Cup"
    assert rows[0]["channels"] == [
        {"label": "Sports", "url": "https://freestreams-live1g.pk/sports/"}
    ]


def test_fsl_layout_change_is_an_error_not_an_empty_success():
    with pytest.raises(ValueError):
        parse_fsl("<html>Please enable JavaScript</html>")


def test_fsl_repairs_misnested_div_in_real_listing_structure():
    rows = parse_fsl("""<table><tbody id="myTable"><tr id="one">
      <td><div><span class="leaguename">Premier League</span></td></div>
      <td class="event-title">Arsenal vs Chelsea</td>
      <td class="buttoncontainer"><a href="/channel/">Channel</a></td>
      </tr></tbody></table>""")
    assert len(rows) == 1
    assert rows[0]["title"] == "Arsenal vs Chelsea"
    assert len(rows[0]["channels"]) == 1


def test_frames_excludes_outside_article_chat_and_unsafe_urls():
    html = """<iframe src="https://ads.example/ad"></iframe><article>
    <iframe src="//player.example/watch"></iframe>
    <iframe src="https://group.chatango.com/"></iframe>
    <iframe src="javascript:alert(1)"></iframe></article>"""
    assert parse_frames(html, "https://freestreams-live1g.pk/channel/", "Channel") == [
        {"label": "Channel", "url": "https://player.example/watch"}
    ]


def test_catalog_partial_failure_and_cache():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "streamed.pk":
            if request.url.path.endswith("/basketball"):
                return httpx.Response(200, json=[])
            return httpx.Response(
                200, json=[{"id": "one", "title": "Arsenal vs Chelsea", "sources": []}]
            )
        if request.url.host == "streamfree.top":
            return httpx.Response(503)
        return httpx.Response(200, text='<table><tbody id="myTable"></tbody></table>')

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            catalog = Catalog(client)
            first, second = await asyncio.gather(catalog.listing(), catalog.listing())
            assert first is second
            assert len(first["matches"]) == 1
            assert first["providers"][1]["error"] == "Provider returned HTTP 503"
            assert "sources" not in first["matches"][0]
            assert len(calls) == 4

    run(scenario())


def test_resolver_preserves_working_source_when_another_fails():
    def handler(request):
        if "/alpha/" in request.url.path:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json=[
                {"embedUrl": "https://player.example/watch", "language": "English", "hd": True},
                {"embedUrl": "javascript:alert(1)"},
            ],
        )

    async def scenario():
        match = parse_streamed(
            [
                {
                    "id": "match",
                    "title": "A vs B",
                    "sources": [{"source": "alpha", "id": "one"}, {"source": "echo", "id": "two"}],
                }
            ]
        )[0]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            data = await resolve(client, match)
        assert len(data["streams"]) == 1
        assert "English" in data["streams"][0]["label"]
        assert data["warnings"] == ["alpha: Provider returned HTTP 503"]

    run(scenario())


def test_streamfree_with_no_live_sources_does_not_invent_a_player():
    async def scenario():
        match = parse_streamfree(
            {"streams": [{"name": "Arsenal vs Chelsea", "stream_key": "one", "category": "soccer"}]}
        )[0]
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"sources": []}))
        async with httpx.AsyncClient(transport=transport) as client:
            assert (await resolve(client, match))["streams"] == []

    run(scenario())


def test_streamfree_uses_own_mirror_and_autoplay_for_discovery():
    async def scenario():
        match = parse_streamfree(
            {
                "streams": [
                    {
                        "name": "Arsenal vs Fleetwood Town",
                        "stream_key": "arsenal-vs-fleetwood-town",
                        "category": "soccer",
                    }
                ]
            }
        )[0]
        embeds = [
            "https://strmfree.st/embed/soccer/arsenal-vs-fleetwood-town1080p",
            "https://strmfree.st/embed/soccer/arsenal-vs-fleetwood-town1080p2?token=one&token=two&autostart=0",
            "https://external.example/watch",
            "https://127.0.0.1/private",
        ]
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"sources": embeds})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            data = await resolve(client, match)
        first, second, external = data["streams"]
        assert first["url"] == embeds[0]
        assert first["discovery_url"] == (
            "https://streamfree.top/embed/soccer/arsenal-vs-fleetwood-town1080p?autostart=1"
        )
        assert first["discovery_referer"] == match["page_url"]
        assert second["discovery_url"].endswith("?token=one&token=two&autostart=1")
        assert external["url"] == embeds[2]
        assert "discovery_url" not in external
        assert data["warnings"] == []

    run(scenario())
