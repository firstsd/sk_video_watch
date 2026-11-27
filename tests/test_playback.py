import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.media import MediaService
from app.playback import playback_settings_from_environment


@pytest.mark.parametrize("backup", [False, True])
def test_play_sends_configured_settings_to_player(monkeypatch, backup):
    monkeypatch.setenv("MATCHDAY_AUTH_ENABLED", "false")
    monkeypatch.setenv("MATCHDAY_LIVE_TARGET_SECONDS", "100")
    monkeypatch.setenv("MATCHDAY_LIVE_MAX_SECONDS", "130")
    monkeypatch.setenv("MATCHDAY_FORWARD_BUFFER_SECONDS", "110")
    monkeypatch.setenv("MATCHDAY_BACK_BUFFER_SECONDS", "0")

    async def streams(match_id):
        return {"streams": [{"id": "s1"}]}

    async def start(self, source):
        return {"url": "/api/media/session/playlist"}

    monkeypatch.setattr(MediaService, "start", start)
    with TestClient(app) as client:
        catalog = app.state.backup_catalog if backup else app.state.catalog
        monkeypatch.setattr(catalog, "streams", streams)
        response = client.post(
            f"/api/matches/m1/play/s1?backup={str(backup).lower()}",
            headers={"X-Matchday-Request": "1"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "url": "/api/media/session/playlist",
            "playback_settings": {
                "live_target_seconds": 100,
                "live_max_seconds": 130,
                "forward_buffer_seconds": 110,
                "back_buffer_seconds": 0,
            },
        }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MATCHDAY_LIVE_MAX_SECONDS", "150"),
        ("MATCHDAY_FORWARD_BUFFER_SECONDS", "0"),
        ("MATCHDAY_BACK_BUFFER_SECONDS", "1.5"),
    ],
)
def test_invalid_settings_name_the_setting_to_fix(monkeypatch, name, value):
    monkeypatch.setenv("MATCHDAY_LIVE_TARGET_SECONDS", "150")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        playback_settings_from_environment()
