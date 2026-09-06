import httpx
from fastapi.testclient import TestClient

from app.main import Catalog, app


def test_pages_and_unknown_match_are_handled_without_live_network(monkeypatch):
    monkeypatch.setenv("MATCHDAY_AUTH_ENABLED", "true")
    monkeypatch.setenv("MATCHDAY_USERNAME", "test-viewer")
    monkeypatch.setenv("MATCHDAY_PASSWORD", "test-password-only")

    def handler(request):
        assert "authorization" not in request.headers
        if request.url.host == "streamed.pk":
            return httpx.Response(200, json=[])
        if request.url.host == "streamfree.top":
            return httpx.Response(200, json={"streams": []})
        return httpx.Response(200, text='<table><tbody id="myTable"></tbody></table>')

    with TestClient(app) as client:
        client.auth = ("test-viewer", "test-password-only")
        client.headers["X-Matchday-Request"] = "1"
        app.state.catalog = Catalog(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        response = client.get("/")
        assert response.status_code == 200
        assert "Matchday" in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "frame-src 'none'" in response.headers["content-security-policy"]
        assert client.get("/static/app.js").status_code == 200
        health = client.get("/api/health")
        assert health.json() == {"status": "ok"}
        assert health.headers["cache-control"] == "no-store"
        assert client.get("/api/matches").json()["matches"] == []
        assert client.get("/api/matches/not-a-real-match/streams").status_code == 404
        assert client.post("/api/matches/not-a-real-match/play/made-up-source").status_code == 404
        assert client.get("/api/media/made-up-session/made-up-resource").status_code == 410
