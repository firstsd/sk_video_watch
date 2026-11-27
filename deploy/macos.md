# MacBook Air deployment

Matchday runs natively as a LaunchAgent for your Mac user. Use macOS 14 (Sonoma) or newer on
Apple silicon or a compatible Intel Mac. The service starts when you log in and continues after
you close Terminal. The Mac must be awake and your account logged in while you watch.
[Playwright system requirements](https://playwright.dev/python/docs/intro#system-requirements) ·
[Apple's guide to LaunchAgents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)

## Install from Git

In Terminal, run `git --version`. On a new Mac, accept the prompt to install Apple's Command Line
Tools if it appears and wait for it to finish. If you need uv, install it once in Terminal.
[Apple Command Line Tools](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools/) ·
[uv installation](https://docs.astral.sh/uv/getting-started/installation/)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

Run the following as your normal desktop user. If you already have a clone, run the install
command from that folder. Keep the clone in a stable location such as `~/apps/matchday`.

```sh
mkdir -p "$HOME/apps"
git clone https://github.com/firstsd/sk_video_watch.git "$HOME/apps/matchday"
cd "$HOME/apps/matchday"
./scripts/server-macos install
```

The installer uses uv to set up Python 3.12 and the locked dependencies, then installs and launches
Chromium to check it before registering `~/Library/LaunchAgents/local.matchday.plist`.
Open **http://127.0.0.1:8000** in Chrome. The local profile has login turned off. To check the
service from Terminal, run `curl --fail http://127.0.0.1:8000/api/health` and look for
`{"status":"ok"}`.

## Everyday use

Run these commands from the clone.

| Action | Command |
| --- | --- |
| Stop now and stay off at future logins | `./scripts/server-macos stop` |
| Start now and at future logins | `./scripts/server-macos start` |
| Apply settings and restart | `./scripts/server-macos restart` |
| Show service status | `./scripts/server-macos status` |
| Follow the service log | `./scripts/server-macos logs` |
| Pull and install the latest Git commit | `./scripts/server-macos update` |
| Remove the LaunchAgent | `./scripts/server-macos uninstall` |

Updates use `git pull --ff-only` in a clean checkout. Updating a running service interrupts
playback. If you stopped Matchday, you can update it and start it later. Ctrl+C exits the log
viewer. The log lives at `~/Library/Logs/Matchday/matchday.log`.

If the page does not open, check `status` and `logs`. An “address already in use” entry means
another process has the configured port. Choose an unused `MATCHDAY_PORT` below, restart, and
open that port in Chrome. If Chromium fails its installation check, confirm your macOS version
with `sw_vers -productVersion` and retry `./scripts/server-macos install` after resolving the
reported browser error.

## Host, port, and optional login

Edit the private settings file, then restart the service. Reinstalling and updating preserve
this file.

```sh
nano "$HOME/Library/Application Support/Matchday/matchday.env"
./scripts/server-macos restart
```

The defaults are `MATCHDAY_HOST=127.0.0.1` and `MATCHDAY_PORT=8000`. To require login, set
`MATCHDAY_AUTH_ENABLED=true` and enter both `MATCHDAY_USERNAME` and `MATCHDAY_PASSWORD` in
the same file. Use literal values after the first `=`, including any spaces, `#`, or `$` in
a password. Omit surrounding quotes. To check the authenticated service, run
`curl --fail --user YOUR_USERNAME http://127.0.0.1:8000/api/health` and enter the password at
the prompt.

For phone access, you can keep the localhost binding and use a private HTTPS connection. If you
choose to listen on your home LAN directly, enable login before setting `MATCHDAY_HOST=0.0.0.0`.
Basic Auth needs HTTPS or an encrypted tunnel to protect the password in transit.
[Private access from a phone](../README.md#phone-and-ubuntu)
