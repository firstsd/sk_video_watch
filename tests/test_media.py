import asyncio
import socket

import httpx
import pytest
from curl_cffi import CurlOpt
from fastapi import HTTPException

from app.media import MediaService, Playback, public_address, read_browser_public, read_public


def test_hls_rewrites_variants_segments_keys_and_maps():
    playback = Playback("session", {})
    result = playback.playlist(
        """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/list.m3u8"
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXT-X-MAP:URI="init.mp4"
#EXT-X-STREAM-INF:BANDWIDTH=2000000
variant/list.m3u8
#EXTINF:6,
chunk.ts?token=private
""",
        "https://video.example/live/main.m3u8",
    )
    assert "https://" not in result
    assert "token=private" not in result
    assert result.count("/api/media/session/") == 5
    assert "https://video.example/live/chunk.ts?token=private" in playback.resources.values()


@pytest.mark.parametrize(
    "text",
    [
        "<html>Advertisement</html>",
        '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"',
        '#EXTM3U\n#EXT-X-MAP:URI="http://127.0.0.1/key"',
        "#EXTM3U\nhttps://localhost/segment",
    ],
)
def test_unsupported_or_private_playlist_fails_closed(text):
    with pytest.raises(ValueError):
        Playback("session", {}).playlist(text, "https://video.example/main.m3u8")


def test_dns_results_must_all_be_public(monkeypatch):
    async def scenario():
        async def lookup(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
        with pytest.raises(ValueError):
            await public_address("https://looks-public.example/video")

    asyncio.run(scenario())


def test_relay_pins_dns_and_validates_redirects(monkeypatch):
    visited = []

    async def address(url):
        visited.append(url)
        if "internal" in url:
            raise ValueError("Private destination")
        return "93.184.215.14"

    monkeypatch.setattr("app.media.public_address", address)

    def handler(request):
        assert request.url.host == "93.184.215.14"
        assert request.headers["host"] == "video.example"
        assert request.extensions["sni_hostname"] == "video.example"
        return httpx.Response(302, headers={"location": "https://internal.example/private"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError):
                await read_public(client, "https://video.example/main.m3u8", {})
        assert visited == ["https://video.example/main.m3u8", "https://internal.example/private"]

    asyncio.run(scenario())


def test_unknown_resources_cannot_be_used_as_an_open_proxy():
    async def scenario():
        service = MediaService()
        try:
            service.playbacks["session"] = Playback("session", {})
            with pytest.raises(HTTPException) as error:
                await service.resource("session", "https://example.com/anything")
            assert error.value.status_code == 404
        finally:
            await service.close()

    asyncio.run(scenario())


def test_relay_rejects_html_in_place_of_video(monkeypatch):
    async def fake_read(*args):
        return (
            b"<html>Ad player</html>",
            "https://video.example/a",
            200,
            {"content-type": "text/html"},
        )

    monkeypatch.setattr("app.media.read_public", fake_read)

    async def scenario():
        service = MediaService()
        try:
            playback = Playback("session", {})
            key = playback.grant("https://video.example/a").rsplit("/", 1)[1]
            service.playbacks["session"] = playback
            with pytest.raises(HTTPException) as error:
                await service.resource("session", key)
            assert error.value.status_code == 502
        finally:
            await service.close()

    asyncio.run(scenario())


def test_browser_relay_pins_dns_disables_proxies_and_rechecks_redirect(monkeypatch):
    seen = []

    async def address(url):
        seen.append(url)
        if "internal" in url:
            raise ValueError("Private destination")
        return "93.184.215.14"

    class Redirect:
        status_code = 302

        def __init__(self):
            self.headers = {"location": "https://internal.example/private"}

        async def aclose(self):
            pass

    class Session:
        def __init__(self, **options):
            assert options["curl_options"][CurlOpt.RESOLVE] == ["video.example:443:93.184.215.14"]
            assert options["curl_options"][CurlOpt.PROXY] == ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **options):
            assert options["allow_redirects"] is False
            return Redirect()

    monkeypatch.setattr("app.media.public_address", address)
    monkeypatch.setattr("app.media.AsyncSession", Session)

    async def scenario():
        with pytest.raises(ValueError):
            await read_browser_public("https://video.example/main.m3u8", {})
        assert seen == ["https://video.example/main.m3u8", "https://internal.example/private"]

    asyncio.run(scenario())


def test_browser_cleanup_timeout_releases_discovery_lock(monkeypatch):
    original_timeout = asyncio.timeout

    class Response:
        status = 200
        url = "https://video.example/main.m3u8"
        request = None

        def __init__(self):
            self.headers = {"content-type": "application/vnd.apple.mpegurl"}

        async def body(self):
            return b"#EXTM3U\n#EXTINF:6,\nsegment.ts\n"

        async def all_headers(self):
            return {}

    response = Response()
    response.request = response

    class Page:
        def on(self, event, callback):
            self.callback = callback

        async def goto(self, *args, **kwargs):
            self.callback(response)

    class Context:
        async def route(self, *args):
            pass

        async def add_init_script(self, *args):
            pass

        async def new_page(self):
            return Page()

        def on(self, *args):
            pass

        async def close(self):
            await asyncio.Event().wait()

    class Browser:
        def is_connected(self):
            return True

        async def new_context(self, **kwargs):
            return Context()

        async def close(self):
            pass

    # Shorten cleanup's deadline while retaining the overall discovery deadline.
    monkeypatch.setattr(
        asyncio, "timeout", lambda delay: original_timeout(0.01 if delay == 3 else delay)
    )

    async def scenario():
        service = MediaService()
        service.browser = Browser()
        try:
            for _ in range(2):
                url, _ = await service.discover({"url": "https://video.example/player"})
                assert url == response.url
                assert not service.lock.locked()
        finally:
            await service.close()

    asyncio.run(scenario())
