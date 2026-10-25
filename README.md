# Matchday

A personal football and NBA viewer using Python, FastAPI, uv, and a native HTML video player.
Provider pages are never embedded in the viewing browser. Python discovers an HLS stream in an
isolated Chromium session, then relays its playlists and video data to the local player.

## Deploy from Git and run in the background

See [the complete Ubuntu deployment guide](deploy/README.md) for pushing your repository, cloning
on Ubuntu, and installing the systemd service with `./scripts/server install`. Start, stop, status,
logs, and updates are available through the same script.

## Run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from this folder:

```sh
uv sync
uv run python -m app.setup_browser
# Local laptop/WSL only: no login, listening on localhost.
export MATCHDAY_AUTH_ENABLED=false
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** in Chrome. Python 3.12+ is required; uv can install Python if needed.
The browser setup is a one-time step for video discovery. It also verifies that Chromium can launch.
On minimal Debian/Ubuntu hosts it can extract commonly missing libraries into `.runtime/` without
sudo. These files stay on the Python host, are ignored by Git, and are used only by the discovery
browser. It is separate from the browser you use to watch. If your host needs additional system libraries:

```sh
uv run playwright install --with-deps chromium
```

If upgrading an older running copy, stop and restart uvicorn after `uv sync`, then hard-refresh
Chrome (Ctrl+Shift+R). The server now blocks all frames with its content security policy.

## Login

Login is configurable per machine; it is **enabled by default**. Set `MATCHDAY_AUTH_ENABLED=false`
for a local laptop/WSL instance bound to `127.0.0.1`. No username or password is needed in that mode.
Set `MATCHDAY_AUTH_ENABLED=true` on Ubuntu and configure `MATCHDAY_USERNAME` and `MATCHDAY_PASSWORD`.
Changes take effect after restarting the app. Accepted switch values are `true`/`false` or `1`/`0`
(case-insensitive). An invalid value prevents startup rather than silently disabling protection.

When enabled, every route requires the browser's HTTP Basic login, including static files, APIs,
video playlists/segments, and API documentation. Missing credentials return 503 without serving the
app. Username must not contain a colon. Use a long, unique password. For systemd, configure these
values in `/etc/matchday.env`, restrict the file with `sudo chmod 600 /etc/matchday.env`, and restart.
See [the setup steps](deploy/README.md#login-configuration). The service template defaults to login
being enabled; an explicit environment-file setting overrides it. Do not disable login on a public
listener. Cross-site playback-request checks remain active in both modes.
Credentials are checked locally and never forwarded to streaming providers.

Basic Auth is a small single-account gate, not a complete defense against attacks or brute force.
Use HTTPS (for example Tailscale Serve) or an SSH tunnel: plain HTTP exposes the reusable credentials.
Browsers can remember Basic credentials, so it may not prompt on every reload and there is no
reliable in-app logout button. Use a private window for a separate session; changing the password
and restarting the server revokes the old credentials. See [MDN's authentication guide](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Authentication).

## Watching

The home page shows the schedule first. Select Arsenal, All football, or NBA, choose Watch on a
match card to reveal the player, and select a source. NBA listings come from Streamed's basketball
category. Source lookup has a 20-second request limit, with a live countdown while resolving,
followed by video loading. Use the native play/fullscreen/volume controls.
Reload obtains a fresh media URL; Next source tries a different provider source. The provider and
selected source remain visible in the Watch Room. Stop ends playback in the viewing browser.
Playback uses adaptive quality and starts from hls.js's bandwidth estimate. The player keeps up to
60 seconds buffered and runs a few segments behind the live edge to absorb short delivery slowdowns.

The app does not load third-party player scripts, overlays, or popup code in your browser. An
unsupported source displays an error; it never falls back to an embedded ad player. The explicitly
labeled provider-website link opens that external site only if you choose it. Ads already encoded
inside the broadcast can remain; this app does not identify or remove those video segments.

Streamed and StreamFree provide source APIs. FSL's match listing and channel pages are parsed as
HTML. An isolated browser on the Python host observes normal media requests behind these sources.
Discovery has a timeout, blocks downloads and window.open, and closes its browsing context when
finished. It does not reuse your Chrome profile or browser login. Some providers require browser
sessions, cookies, DRM, or other formats that this implementation cannot independently play.
Those sources remain unsupported. One discovery runs at a time. Switching sources waits for the
current check to finish and then checks your latest selection. Another viewing tab can still occupy
discovery; in that case, wait briefly before reloading. There is no guarantee of every source or
competition working.

Listings come from the providers and may be incomplete, duplicated, stale, or mislabeled. They
are not an authoritative fixture calendar. Arsenal is a text filter, including women's/youth
matches and other teams named Arsenal. Times use America/Los_Angeles with daylight saving time.
Competition filtering works where providers supply competition names. Listings are cached for
60 seconds and source lists for 30 seconds; video discovery runs afresh on reload.

## Video health

Readings beneath the video update every second from the actual media player. Colors and text labels
are guides: buffer under 2 seconds is red, 2–5 seconds amber, and 5+ seconds green during playback.
Chunk downloads are compared with their video duration (under half is green, half to full is amber,
full or longer is red). Live delay stays neutral. Error colors use the last 30 seconds; frame-drop
colors use recent samples (above 1% amber, above 5% red). Pause, startup, and seeking suppress
low-buffer alerts. These are playback indicators, not measurements of your ISP speed.


| Reading | Meaning |
| --- | --- |
| Buffer ahead | Seconds of downloaded video available beyond the playhead |
| Behind stream live edge | Estimated delay behind the provider's live playlist; not stadium-to-screen delay |
| Last video segment download | Time to download an actual video fragment through the Python relay |
| Stalls / time stalled | Playback interruptions and their duration, excluding initial startup, pause, and seeking |
| Dropped / total frames | Frames the browser could not present compared with total video frames |
| Video request errors | Media/playlist network request errors reported by hls.js, including retried errors |

A shrinking buffer followed by stalls indicates the player is running out of video. Dropped frames
with a healthy buffer can point to decoding/rendering trouble on the device. These observations do
not uniquely identify ISP vs provider problems, and cannot detect every frozen picture already
encoded in the upstream broadcast. Video request errors are not IP packet loss; no ICMP ping or
website response timings are presented as video health.

Native HLS playback (for browsers without Media Source support) does not expose the same fragment
and live-edge measurements; unavailable values remain blank. The locally hosted hls.js library is
pinned at 1.6.15; its license is in `app/static/vendor/HLS-LICENSE.txt`.

## Phone and Ubuntu

For a phone on the same home Wi-Fi:

```sh
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://YOUR-LAPTOP-LAN-IP:8000`. Allow port 8000 on your private network if the firewall asks.
The laptop must stay awake. Enable login and set credentials before sharing this listener beyond your trusted local setup.
Use HTTPS or an encrypted private tunnel to protect your Basic Auth credentials.

On Ubuntu, copy this folder including `uv.lock` but excluding `.venv`, run `uv sync --locked --no-dev`,
install Chromium and its dependencies as above, then run uvicorn on `127.0.0.1:8000`.
For access away from home, install Tailscale on the server and phone and use
[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve):

```sh
tailscale serve --bg http://127.0.0.1:8000
```

Open the printed HTTPS address with Tailscale connected. Do not use public Funnel or router port
forwarding for this private app. For automatic startup and background operation, follow the [Git and systemd deployment guide](deploy/README.md).

**Video now passes through the Python host.** When watching remotely, your server's download and
upload connections both matter. The fragment timing measures the complete path through that host;
it is not a direct phone-to-CDN ping. Keep a single uvicorn worker because playback sessions are in
memory. Sessions expire after four hours; Reload obtains a new one. At most eight sessions are kept.

## Learn uv

uv manages dependencies and the Python environment; FastAPI serves the page and API. There is no
React project, Node service, database, or separate frontend build step.

| Command/file | Purpose |
| --- | --- |
| `uv sync` | Creates `.venv` and installs dependencies |
| `uv run ...` | Runs a command in that environment without manual activation |
| `uv add package-name` | Adds a dependency and updates the lockfile |
| `uv add --dev package-name` | Adds a development dependency |
| `pyproject.toml` | Project metadata and dependency/tool settings |
| `uv.lock` | Exact dependency versions; keep this in Git |

## Implementation and checks

- `app/providers.py`: provider listings and source references.
- `app/media.py`: isolated video discovery, short-lived resource grants, and HLS relay.
- `app/main.py`: routes, listing cache, and application lifecycle.
- `app/static/player.js`: native video controls and actual playback measurements.
- `app/static/app.js`: match selection and source switching.

Only server-discovered source IDs can start playback. Relay URLs refer to granted resources in a
random playback session, not arbitrary user-supplied destinations. Each outbound relay request
validates public DNS addresses, pins the checked IP with the original TLS server name, and validates
redirects. HLS variant, segment, key, and initialization URLs are rewritten to session URLs. HTML
responses are rejected rather than forwarded as media. The relay preserves only the media request's
Origin, Referer, and User-Agent; it does not forward login cookies or authorization credentials.
If a media host rejects the standard HTTP client with 403, the relay retries using curl-cffi's
browser-compatible TLS/HTTP profile. The same destination validation and IP pinning apply, and
the viewing browser still receives only same-origin media. Browser-compatible connections are
reused between HLS chunks from the same validated host and IP instead of repeating a TLS handshake
for every chunk. No DRM or login-session support is added.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests cover provider parsing, partial failures, cache behavior, HLS rewriting, private-address
rejection, DNS pinning/redirect checks, unknown resource rejection, and refusal to relay HTML.
Live playback requires a separate browser check; successful listing retrieval is not evidence
that a stream works. No Arsenal broadcast or full-match reliability claim is implied by unit tests.

References: [Streamed API](https://streamed.pk/docs), [StreamFree API](https://streamfree.top/api),
[hls.js](https://github.com/video-dev/hls.js), [uv projects](https://docs.astral.sh/uv/guides/projects/).
