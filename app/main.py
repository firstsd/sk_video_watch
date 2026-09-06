"""Run with: uv run uvicorn app.main:app --host 127.0.0.1 --port 8000."""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.auth import Credentials, access_error, auth_enabled_from_environment
from app.media import MediaService
from app.providers import NAMES, PROVIDERS, failure, load_provider, resolve

STATIC = Path(__file__).parent / "static"


class Catalog:
    def __init__(self, client):
        self.client = client
        self.lock = asyncio.Lock()
        self.expires = 0
        self.snapshot = None
        self.matches = {}
        self.stream_cache = {}
        self.stream_lock = asyncio.Lock()

    async def listing(self):
        async with self.lock:
            if self.snapshot is not None and time.monotonic() < self.expires:
                return self.snapshot
            results = await asyncio.gather(
                *(load_provider(self.client, name) for name in PROVIDERS),
                return_exceptions=True,
            )
            matches, statuses = [], []
            for name, result in zip(PROVIDERS, results):
                error = failure(result) if isinstance(result, Exception) else None
                rows = [] if error else result
                matches.extend(rows)
                statuses.append(
                    {
                        "id": name,
                        "name": NAMES[name],
                        "url": PROVIDERS[name],
                        "count": len(rows),
                        "error": error,
                    }
                )
            matches.sort(key=lambda m: (m["starts_at"] or float("inf"), m["title"]))
            self.matches = {match["id"]: match for match in matches}
            self.stream_cache.clear()
            self.snapshot = {
                "matches": [
                    {k: v for k, v in m.items() if k not in ("sources", "channels", "key")}
                    for m in matches
                ],
                "providers": statuses,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
            self.expires = time.monotonic() + 60
            return self.snapshot

    async def streams(self, match_id):
        await self.listing()
        match = self.matches.get(match_id)
        if match is None:
            raise HTTPException(404, "Match is no longer listed. Refresh the matches.")
        async with self.stream_lock:
            cached = self.stream_cache.get(match_id)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            data = await resolve(self.client, match)
            self.stream_cache[match_id] = (time.monotonic() + 30, data)
            return data


@asynccontextmanager
async def lifespan(app):
    app.state.auth_enabled = auth_enabled_from_environment()
    app.state.credentials = Credentials.from_environment() if app.state.auth_enabled else None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12),
        follow_redirects=False,
        headers={"User-Agent": "SKVideoWatch/0.1 (personal football viewer)"},
        limits=httpx.Limits(max_connections=20),
    ) as client:
        app.state.catalog = Catalog(client)
        app.state.media = MediaService()
        try:
            yield
        finally:
            await app.state.media.close()


app = FastAPI(title="Matchday", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def response_headers(request, call_next):
    response = access_error(request)
    if response is None:
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-src 'none'; "
        "media-src 'self' blob:; worker-src 'self' blob:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return response


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@app.get("/api/matches")
async def matches(request: Request):
    return await request.app.state.catalog.listing()


@app.get("/api/matches/{match_id}/streams")
async def streams(match_id: str, request: Request):
    return await request.app.state.catalog.streams(match_id)


@app.post("/api/matches/{match_id}/play/{source_id}")
async def play(match_id: str, source_id: str, request: Request):
    try:
        async with asyncio.timeout(20):
            data = await request.app.state.catalog.streams(match_id)
            source = next((item for item in data["streams"] if item["id"] == source_id), None)
            if not source:
                raise HTTPException(404, "Source changed. Refresh the match.")
            return await request.app.state.media.start(source)
    except TimeoutError as exc:
        raise HTTPException(
            504, "Video did not become available within 20 seconds. Try another source."
        ) from exc


@app.get("/api/media/{session}/{key}")
async def media(session: str, key: str, request: Request):
    body, content_type, status, headers = await request.app.state.media.resource(
        session, key, request.headers.get("range")
    )
    return Response(
        body,
        media_type=content_type,
        status_code=status,
        headers={**headers, "Cache-Control": "no-store"},
    )
