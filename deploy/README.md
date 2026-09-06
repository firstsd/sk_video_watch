# Git and Ubuntu deployment

The repository includes `scripts/server`, which installs a systemd service called **matchday**.
It runs as the normal Ubuntu account that installed it, starts at boot, and restarts after crashes.
You can close SSH or the terminal after installation. No Docker or Node installation is needed.
Use one worker: discovered playback sessions are kept in memory.

## 1. Push the project yourself

Create an empty repository on your Git host. Do not initialize the remote with a README or license
when uploading this existing folder for the first time. For a private repository, configure your
Git host's SSH key or credential helper on each machine; do not put access tokens in remote URLs.

In your laptop's project folder, for a new repository with no existing Git history:

```bash
git init -b main
git add .
git diff --cached --stat
git status
git commit -m "Prepare Matchday for Ubuntu deployment"
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

Replace `YOUR_REPOSITORY_URL` with your actual SSH or HTTPS clone URL. If you already have a Git
repository or an `origin` remote in your own checkout, use that history and remote instead of
initializing again. If Git asks for author identity, set `git config user.name "Your Name"` and
`git config user.email "you@example.com"` in this project, then repeat the commit.

Commit `uv.lock`, `app/`, `deploy/`, `scripts/`, tests, and the documentation. `.gitignore` excludes
`.venv/`, `.runtime/`, `.env`, and Python caches. Chromium downloads and runtime libraries are installed
again on Ubuntu, not copied from the laptop. Review the staged files before pushing.

## 2. Install on Ubuntu

SSH into the server as your normal account with sudo access. Install basic tools:

```bash
sudo apt update
sudo apt install -y git curl ca-certificates
```

Install [uv using its official installer](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

Clone the project, replacing the repository URL:

```bash
mkdir -p "$HOME/apps"
git clone YOUR_REPOSITORY_URL "$HOME/apps/matchday"
cd "$HOME/apps/matchday"
./scripts/server install
```

Run the script **without sudo**. It installs locked production dependencies and Chromium under your
account, verifies the browser, and asks for sudo only to install and manage the service. Use a clone
path without spaces or `%` characters. Keep this folder in place while the service is installed.
If another copy of the app already uses port 8000, stop that copy before installing the service.

Configure login using the next section before opening the app. Then check the result on the server:

```bash
./scripts/server status
curl --fail --user YOUR_USERNAME http://127.0.0.1:8000/api/health
```

Curl prompts for the password without putting it in your command history. The health endpoint should return `{"status":"ok"}`. This verifies the web server, not the availability
of a particular sports stream. If Chromium needs extra Ubuntu libraries, run these as your normal
account and then retry installation (Playwright may ask for sudo for OS packages):

```bash
uv run --no-sync playwright install --with-deps chromium
./scripts/server install
```

## Login configuration

After initial installation, or before restarting an existing installation with this update:

```bash
sudo nano /etc/matchday.env
```

Keep your existing host/port values and add these two settings, replacing the example values:

```ini
MATCHDAY_AUTH_ENABLED=true
MATCHDAY_USERNAME=your-name
MATCHDAY_PASSWORD="your-long-unique-password"
```

Do not use the example password. Double-quote a password containing spaces or `#`; escape literal
backslashes and double quotes inside double-quoted values. Do not use a colon in the username.
Then restrict the file and restart:

```bash
sudo chmod 600 /etc/matchday.env
sudo systemctl restart matchday
```

No daemon-reload is needed for environment-file changes. The system service manager reads this
root-only file and supplies the settings to the unprivileged app. Never commit your actual credentials.
With authentication enabled, if either credential is missing, **every app route returns 503** until configured. Wrong or absent login
returns 401 and triggers the browser's built-in username/password prompt. Successful login covers
the page, API, and video resources. There is no separate account database.

Use **HTTPS or an encrypted tunnel** when logging in: Basic Auth does not encrypt credentials.
For your phone away from home, use Tailscale Serve with the server bound to localhost. It is still
best to keep the app private; Basic Auth alone does not provide MFA, rate limiting, or protection
against denial-of-service attacks. Browsers cache credentials and may not ask again on every load.
There is no reliable Basic Auth logout button; changing credentials and restarting revokes the old ones.

For a local laptop/WSL instance without login, run from your clone:

```bash
MATCHDAY_AUTH_ENABLED=false uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

This setting applies only to that process; your Ubuntu server can keep login enabled independently.
For a local systemd service, set `MATCHDAY_AUTH_ENABLED=false` in its `/etc/matchday.env` and restart.
Authentication defaults to enabled if omitted. Keep `true` on your public-network server and use
HTTPS/private encrypted access. The app does not infer trust from the OS, host binding, or client IP.

## 3. Open it from your laptop or phone

By default the service listens on **127.0.0.1:8000 on Ubuntu**, not on the laptop.
For access from a laptop over SSH, run this on the laptop and keep that SSH connection open:

```bash
ssh -N -L 8000:127.0.0.1:8000 YOUR_USER@YOUR_SERVER
```

Then open `http://127.0.0.1:8000` on the laptop. If the laptop's port 8000 is occupied, use
`-L 8001:127.0.0.1:8000` and open `http://127.0.0.1:8001` instead.

For direct home-LAN access, edit the service configuration on Ubuntu:

```bash
sudo nano /etc/matchday.env
```

Set `MATCHDAY_HOST=0.0.0.0`, keep `MATCHDAY_PORT=8000`, then run:

```bash
./scripts/server restart
```

Open `http://YOUR_SERVER_LAN_IP:8000` on the laptop or phone on the same network. If you use a firewall,
allow this port only from your home network. This listener uses plain HTTP, so Basic Auth credentials are not encrypted on the LAN.
Prefer HTTPS/private tunnels for authenticated access; do not expose it with public router port forwarding. For access away from home, keep the localhost setting and use the private
[Tailscale Serve setup in the main README](../README.md#phone-and-ubuntu).

## 4. Everyday commands

From the cloned folder:

| Action | Command |
| --- | --- |
| Start in background | `./scripts/server start` |
| Stop | `./scripts/server stop` |
| Restart | `./scripts/server restart` |
| Check status | `./scripts/server status` |
| Follow logs | `./scripts/server logs` |
| Pull and install latest commit | `./scripts/server update` |

Ctrl+C while viewing logs closes the log viewer **without stopping the app**. You can also run
`sudo systemctl start matchday`, `sudo systemctl stop matchday`, or `sudo systemctl restart matchday`
from any directory. A manual stop lasts until you start it again or reboot. To prevent startup at boot:

```bash
sudo systemctl disable --now matchday
```

To restore startup at boot:

```bash
sudo systemctl enable --now matchday
```

## 5. Send future changes to Ubuntu

On the laptop, commit and push your changes:

```bash
git add .
git commit -m "Describe your changes"
git push
```

Then on Ubuntu:

```bash
cd "$HOME/apps/matchday"
./scripts/server update
```

Update requires a clean working tree and uses `git pull --ff-only`. It then stops the service,
installs the locked dependencies and browser, refreshes the service definition, and starts it again.
Your `/etc/matchday.env` is preserved. Updating briefly interrupts playback and clears playback
sessions; reload the page/source afterward. If installation fails, the app stays stopped with an
error message. Fix the reported error and rerun update; it does not silently roll back Git commits.

After frontend changes, hard-refresh Chrome with Ctrl+Shift+R.
