import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import play


def test_play_deadline_includes_source_lookup(monkeypatch):
    original_timeout = asyncio.timeout

    def fast_timeout(seconds):
        assert seconds == 20
        return original_timeout(0.01)

    class Catalog:
        async def streams(self, match_id):
            await asyncio.Event().wait()

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(catalog=Catalog())))
    monkeypatch.setattr(asyncio, "timeout", fast_timeout)
    with pytest.raises(HTTPException) as error:
        asyncio.run(play("match", "source", request))
    assert error.value.status_code == 504
    assert "20 seconds" in error.value.detail
