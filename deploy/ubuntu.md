# Ubuntu: native uv and systemd

Use this model on Ubuntu 22.04, 24.04, or 26.04, including Ubuntu WSL 2 with systemd.
Matchday runs as your normal Linux user. Python dependencies and Chromium stay in your clone/user
cache. No container engine is needed. The laptop must be awake and WSL running while you watch.

## Install

```bash
sudo apt update
sudo apt install -y git curl ca-certificates
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
mkdir -p "$HOME/apps"
git clone YOUR_REPOSITORY_URL "$HOME/apps/matchday"
cd "$HOME/apps/matchday"
./scripts/server install
```

Run the installer without sudo; it requests sudo for systemd management. If you already have a
clone, use it instead of cloning again. Do not put Git passwords/tokens in the clone URL.

Configure `/etc/matchday.env` using [the login instructions](README.md#login-configuration).
For an instance used only locally on your trusted laptop:

```ini
MATCHDAY_HOST=127.0.0.1
MATCHDAY_PORT=8000
MATCHDAY_AUTH_ENABLED=false
```

For login, set `MATCHDAY_AUTH_ENABLED=true` and supply your username/password. This file uses
systemd environment-file syntax; quote values containing spaces or `#`. After editing:

```bash
./scripts/server restart
./scripts/server status
```

Open `http://127.0.0.1:8000` in Windows Chrome when running under WSL, or in the Ubuntu desktop
browser. On a different Ubuntu machine, use the SSH/private-network access instructions in the
[complete guide](README.md#3-open-it-from-your-laptop-or-phone).

## Start and stop when needed

```bash
./scripts/server start
./scripts/server stop
./scripts/server logs
```

Installation enables startup at Linux boot. If you prefer starting manually:

```bash
sudo systemctl disable matchday
```

This does not stop a currently running service; use the stop command above. Start it manually
whenever you want to watch. `sudo systemctl enable matchday` restores automatic Linux startup.

Push future changes yourself, then run `./scripts/server update` in the server's clean checkout.

## Ubuntu WSL

Check `ps -p 1 -o comm=` inside WSL. If it is not `systemd`, merge this into `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

Save your other WSL work, then run `wsl --shutdown` in Windows PowerShell and reopen Ubuntu.
That command stops all WSL distributions. Run `./scripts/server install` after reopening.

Services run in the background, but systemd cannot keep the physical laptop awake or make the
app available after Windows/WSL has shut down. No Windows startup/sleep settings are changed by
this repository. See [WSL and the Windows OpenVPN connection](wsl-vpn.md).

## Browser dependencies

The installer runs `app.setup_browser`, which installs Chromium matching the locked Playwright
version and checks full Chromium startup. On a minimal Ubuntu host, if additional OS libraries
are required, run as your normal user:

```bash
uv run --no-sync playwright install --with-deps chromium
./scripts/server install
```

References: [Playwright supported systems](https://playwright.dev/python/docs/intro#system-requirements),
[Microsoft's WSL systemd setup](https://learn.microsoft.com/en-us/windows/wsl/systemd).
