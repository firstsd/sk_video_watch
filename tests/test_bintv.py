import httpx
from fastapi.testclient import TestClient

from app.main import Catalog, app
from app.providers import BINTV_FEED


def test_backup_does_not_require_or_replace_primary_catalog(monkeypatch):
    monkeypatch.setenv("MATCHDAY_AUTH_ENABLED", "false")
    calls = []
    url = "https://bintv-sources.pages.dev/?id=example"
    soccer = {
        "Name": "Arsenal vs Chelsea",
        "ID": "e1",
        "Category": "Soccer",
        "Date": "2026-11-27 03:10 UTC",
        "Streams": [
            {"Name": "Alt", "Iframe": url},
            {"Iframe": url},
            {"Iframe": "https://127.0.0.1/private"},
            {"Iframe": "https://unrelated.example/"},
            None,
        ],
    }
    nba = dict(soccer, ID="e2", Name="LA Clippers @ Boston Celtics", Category="Basketball")
    feed = {
        "Live Events": [soccer, None],
        "Upcoming Events": [
            dict(soccer, Streams=[]),
            nba,
            dict(nba, ID="e3", Name="Kansas vs Villanova"),
            dict(soccer, ID="e4", Category="American Football"),
        ],
        "24/7 Channels": [soccer],
    }

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == BINTV_FEED:
            return httpx.Response(200, json=feed)
        return httpx.Response(503)

    with TestClient(app) as client:
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.state.catalog = Catalog(upstream)
        app.state.backup_catalog = Catalog(upstream, ("bintv",))
        listing = client.get("/api/matches?backup=true").json()
        assert calls == [BINTV_FEED]
        assert [(m["title"], m["league"]) for m in listing["matches"]] == [
            (soccer["Name"], "Football"),
            (nba["Name"], "NBA"),
        ]
        match = listing["matches"][0]
        assert match["starts_at"] == 1795749000
        assert "sources" not in match
        path = f"/api/matches/{match['id']}/streams"
        result = client.get(path + "?backup=true").json()
        assert [(s["label"], s["url"]) for s in result["streams"]] == [("BinTV · Alt", url)]
        assert client.get(path).status_code == 404
        assert client.get("/api/matches").json()["matches"] == []
        assert calls.count(BINTV_FEED) == 1
        assert client.get(path + "?backup=true").json() == result
