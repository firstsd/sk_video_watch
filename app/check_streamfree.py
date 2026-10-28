"""Measure StreamFree delivery from the machine hosting Matchday.

Run: uv run python -m app.check_streamfree --match Fleetwood --source 1
Only timings and counts are printed; upstream URLs and signed tokens stay private.
"""

import argparse
import asyncio
import time

import httpx
from curl_cffi.requests import RequestsError
from fastapi import HTTPException

from app.media import MediaService, RelayResponse
from app.providers import load_provider, resolve


async def check(match_text, source_number):
    service = MediaService()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            rows = await load_provider(client, "streamfree")
            matches = [row for row in rows if match_text.casefold() in row["title"].casefold()]
            if len(matches) != 1:
                raise ValueError("Match must identify exactly one currently listed game")
            match = matches[0]
            data = await resolve(client, match)
        if source_number > len(data["streams"]):
            raise ValueError("That source is not currently listed")
        source = data["streams"][source_number - 1]
        print(f"{match['title']} / {source['label']}", flush=True)
        result = await service.start(source)
        response = await service.resource(result["session"], result["url"].rsplit("/", 1)[-1])
        # Follow master playlists until we reach the playlist containing segments.
        for _ in range(4):
            if isinstance(response, RelayResponse):
                await response.aclose()
                raise TypeError("Expected an HLS playlist")
            lines = response.body.decode().splitlines()
            if any(line.startswith("#EXTINF:") for line in lines):
                break
            target = next((line for line in lines if line and not line.startswith("#")), None)
            if target is None:
                raise ValueError("No variant playlist is currently available")
            response = await service.resource(result["session"], target.rsplit("/", 1)[-1])
        segments = []
        duration = None
        for line in lines:
            if line.startswith("#EXTINF:"):
                duration = float(line.partition(":")[2].split(",")[0])
            elif line and not line.startswith("#") and duration is not None:
                segments.append((line, duration))
                duration = None
        if not segments:
            raise ValueError("No media segments in this playlist")
        print(
            f"Playlist: {len(segments)} segments / {sum(s[1] for s in segments):.1f}s available",
            flush=True,
        )
        for number, (path, duration) in enumerate(segments[-3:], 1):
            began = time.monotonic()
            response = await service.resource(result["session"], path.rsplit("/", 1)[-1])
            if not isinstance(response, RelayResponse):
                raise TypeError("Expected a video segment")
            first_byte, size = None, 0
            try:
                async for chunk in response.body_iterator:
                    if first_byte is None:
                        first_byte = time.monotonic() - began
                    size += len(chunk)
            finally:
                await response.aclose()
            total = time.monotonic() - began
            speed = "keeps up" if total < duration else "slower than playback"
            print(
                f"Segment {number}: video {duration:.2f}s; first byte {first_byte or 0:.2f}s; "
                f"download {total:.2f}s; {size / 1_000_000:.2f} MB; {speed}",
                flush=True,
            )
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match", required=True, help="Part of the listed match title")
    parser.add_argument("--source", type=int, default=1, choices=range(1, 17))
    args = parser.parse_args()
    try:
        asyncio.run(check(args.match, args.source))
    except (ValueError, TypeError) as exc:
        parser.exit(1, f"Check failed: {exc}\n")
    except HTTPException as exc:
        parser.exit(1, f"Check failed: {exc.detail}\n")
    except (httpx.HTTPError, RequestsError, OSError, TimeoutError) as exc:
        # Network exception messages may contain signed URLs; don't print them.
        parser.exit(1, f"Check failed ({type(exc).__name__}); retry while the source is live.\n")


if __name__ == "__main__":
    main()
