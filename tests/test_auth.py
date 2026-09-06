import asyncio
import base64
from types import SimpleNamespace

import httpx
import pytest

from app.auth import Credentials, access_error
from app.main import app


def authorization(user="viewer", password="test-password:with-colon"):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def configure(monkeypatch):
    monkeypatch.setenv("MATCHDAY_USERNAME", "viewer")
    monkeypatch.setenv("MATCHDAY_PASSWORD", "test-password:with-colon")
    return Credentials.from_environment()


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/app.js",
        "/api/health",
        "/api/matches",
        "/api/media/session/key",
        "/docs",
        "/openapi.json",
    ],
)
def test_unauthorized_requests_cannot_reach_any_routes(monkeypatch, path):
    app.state.credentials = configure(monkeypatch)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get(path)
            assert response.status_code == 401
            assert response.headers["www-authenticate"].startswith('Basic realm="Matchday"')
            assert response.headers["cache-control"] == "no-store"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer token",
        "Basic !!!",
        "Basic /w==",
        "Basic dmlld2Vy",
        authorization(password="wrong"),
        authorization(user="wrong"),
        "Basic " + "A" * 9000,
    ],
)
def test_invalid_credentials_are_rejected(monkeypatch, header):
    assert not configure(monkeypatch).accepts(header)


def test_valid_credentials_and_unicode(monkeypatch):
    credentials = configure(monkeypatch)
    assert credentials.accepts(authorization())
    monkeypatch.setenv("MATCHDAY_USERNAME", "観客")
    monkeypatch.setenv("MATCHDAY_PASSWORD", "unique-秘密-password")
    assert Credentials.from_environment().accepts(authorization("観客", "unique-秘密-password"))


@pytest.mark.parametrize(
    "user,password", [("", ""), ("viewer", ""), ("", "password"), ("bad:name", "password")]
)
def test_unconfigured_login_fails_closed(monkeypatch, user, password):
    monkeypatch.setenv("MATCHDAY_USERNAME", user)
    monkeypatch.setenv("MATCHDAY_PASSWORD", password)
    credentials = Credentials.from_environment()
    assert credentials is None
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(credentials=credentials)))
    assert access_error(request).status_code == 503


def test_post_requires_csrf_header_and_rejects_cross_site(monkeypatch):
    credentials = configure(monkeypatch)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(credentials=credentials)),
        method="POST",
        headers={"authorization": authorization()},
    )
    assert access_error(request).status_code == 403
    request.headers["x-matchday-request"] = "1"
    assert access_error(request) is None
    request.headers["sec-fetch-site"] = "cross-site"
    assert access_error(request).status_code == 403


def test_authenticated_health_and_unauthenticated_post(monkeypatch):
    app.state.credentials = configure(monkeypatch)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/api/health", headers={"Authorization": authorization()})
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            response = await client.post("/api/matches/match/play/source")
            assert response.status_code == 401
            response = await client.post(
                "/api/matches/match/play/source", headers={"Authorization": authorization()}
            )
            assert response.status_code == 403

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "value,enabled",
    [(None, True), ("true", True), ("1", True), ("false", False), ("0", False), (" FALSE ", False)],
)
def test_auth_switch_is_explicit_and_defaults_enabled(monkeypatch, value, enabled):
    from app.auth import auth_enabled_from_environment

    if value is None:
        monkeypatch.delenv("MATCHDAY_AUTH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("MATCHDAY_AUTH_ENABLED", value)
    assert auth_enabled_from_environment() is enabled


def test_invalid_auth_switch_does_not_disable_login(monkeypatch):
    from app.auth import auth_enabled_from_environment

    monkeypatch.setenv("MATCHDAY_AUTH_ENABLED", "flase")
    with pytest.raises(ValueError, match="MATCHDAY_AUTH_ENABLED"):
        auth_enabled_from_environment()


def test_disabled_auth_allows_local_access_but_keeps_csrf_check(monkeypatch):
    monkeypatch.setattr(app.state, "auth_enabled", False, raising=False)
    monkeypatch.setattr(app.state, "credentials", None, raising=False)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/api/health")
            assert response.status_code == 200
            assert "www-authenticate" not in response.headers
            response = await client.post("/api/matches/match/play/source")
            assert response.status_code == 403

        request = SimpleNamespace(app=app, method="POST", headers={"x-matchday-request": "1"})
        assert access_error(request) is None
        request.headers["sec-fetch-site"] = "cross-site"
        assert access_error(request).status_code == 403

    asyncio.run(scenario())
