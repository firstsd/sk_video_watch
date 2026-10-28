# AlmaLinux/RHEL 9: rootless Podman and systemd

This model runs on an updated AlmaLinux 9 or compatible RHEL-family host, including AlmaLinux WSL 2.
It packages Matchday, Python, and the matching Chromium in a Debian-based container. Playwright's
native Linux support covers Debian/Ubuntu, not AlmaLinux/RHEL. This avoids installing Debian browser
libraries on your AlmaLinux host or relying on an unverified system Chromium build.

There is one application container, managed by your normal user's systemd instance through Quadlet.
No host Python/uv installation or Docker daemon is needed. Container networking follows the host's
routes; this model does not keep traffic outside a Windows VPN.

## 1. WSL prerequisite

Inside AlmaLinux, check:

```bash
ps -p 1 -o comm=
```

If PID 1 is not systemd, merge this into `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

Save your other WSL work, run `wsl --shutdown` in Windows PowerShell, and reopen AlmaLinux.
This stops all WSL distributions. The laptop must remain awake and WSL running while serving video.
On a normal AlmaLinux installation, systemd is already the default.

## 2. Install host tools

As a normal user with sudo access:

```bash
sudo dnf install -y podman git curl ca-certificates shadow-utils fuse-overlayfs
podman --version
podman info --format '{{.Host.CgroupsVersion}}'
```

Use a current AlmaLinux 9 Podman package with Quadlet support. The cgroup output must be `v2`.
If Podman is old, update the Podman packages through your normal distro update process first.
Podman must work rootlessly: `podman info` should succeed without sudo. If it reports missing
subordinate IDs, your Linux account needs unused ranges assigned in `/etc/subuid` and `/etc/subgid`.
Have the system administrator choose non-overlapping ranges rather than copying someone else's.

Enable your user service manager in the background:

```bash
sudo loginctl enable-linger "$(id -un)"
systemctl --user show-environment
```

If the latter reports no user bus, reopen your AlmaLinux session. Lingering supports background user
services; it does not keep Windows or WSL alive after shutdown.

## 3. Clone and install

```bash
mkdir -p "$HOME/apps"
git clone YOUR_REPOSITORY_URL "$HOME/apps/matchday"
cd "$HOME/apps/matchday"
bash scripts/server-podman install
```

Use an existing clone if you have one. Run the script without sudo. The first build downloads Python,
the locked packages, Chromium, and its libraries. It verifies that full Chromium launches as the
container's non-root application user before the build succeeds.

The host remains AlmaLinux; the browser's compatible userspace is contained in the image. The image
does not mount your host home directory or project at runtime. SELinux remains enabled, and no
privileged container or host networking is requested.

## 4. Configure login

The private settings file is `~/.config/matchday/matchday.env`, owned by you with mode `0600`.
For local laptop use through `http://127.0.0.1:8000` without login:

```ini
MATCHDAY_AUTH_ENABLED=false
```

To require login:

```ini
MATCHDAY_AUTH_ENABLED=true
MATCHDAY_USERNAME=your-name
MATCHDAY_PASSWORD=your-long-unique-password
```

**Podman env files use literal values. Do not put quotes around the password** unless you intend
those quote characters to be part of the password. This differs from native Ubuntu's systemd
environment file. Do not copy a quoted `/etc/matchday.env` into this file without adapting it.
Never commit this file. Authentication defaults to enabled, and missing credentials deny access.

Restart after editing:

```bash
bash scripts/server-podman restart
curl --fail --user YOUR_USERNAME http://127.0.0.1:8000/api/health
```

Curl asks for the password. Omit `--user YOUR_USERNAME` when login is disabled.
The health result is `{"status":"ok"}`. Open the same address in Windows Chrome when using WSL.

## 5. Everyday commands

| Action | Command |
| --- | --- |
| Start | `bash scripts/server-podman start` |
| Stop | `bash scripts/server-podman stop` |
| Restart | `bash scripts/server-podman restart` |
| Status | `bash scripts/server-podman status` |
| Follow logs | `bash scripts/server-podman logs` |
| Pull and build latest Git commit | `bash scripts/server-podman update` |
| Build current local changes | `bash scripts/server-podman build` |
| Measure the server's stream delivery | `bash scripts/server-podman check --match Fleetwood --source 1` |

Ctrl+C leaves the log viewer without stopping Matchday. Updates require a clean checkout and use
`git pull --ff-only`. The image builds while the old container keeps running; a failed build does not
stop it. A successful update restarts playback sessions. Your settings and existing Quadlet file are
preserved. Rebuilding local changes requires a restart afterward to use the new image.

## Host address, port, and automatic startup

The installed Quadlet is `~/.config/containers/systemd/matchday.container`. Its default mapping is:

```ini
PublishPort=127.0.0.1:8000:8000
```

That means host localhost port 8000 forwards to port 8000 inside the container. The internal app
listens on `0.0.0.0:8000`; host exposure is controlled by `PublishPort`, not the app's internal bind.
For a different host port, change the middle number, for example `127.0.0.1:8001:8000`. Keep the
internal port at 8000. After changing the Quadlet, run:

```bash
systemctl --user daemon-reload
bash scripts/server-podman restart
```

For private phone access, keep the localhost mapping and use Tailscale on the host. WSL networking
adds a Windows layer; read [the WSL/VPN guide](wsl-vpn.md) before changing exposure or routes.

Quadlet's `[Install]` section starts Matchday when the user systemd manager starts. Do not run
`systemctl --user enable matchday`: generated Quadlet units are enabled through that section.
To make startup manual, remove `[Install]` and `WantedBy=default.target` from your installed Quadlet,
then run `systemctl --user daemon-reload`. Start/stop commands still work. Add the section back to
restore automatic user-manager startup.

## Troubleshooting

- `matchday.service not found`: verify systemd, the user bus, cgroup v2, and a Podman version with
  Quadlet support. Check `journalctl --user -b` for generator errors.
- Container startup failure: inspect `bash scripts/server-podman logs`; do not disable SELinux or
  enable privileged mode as a generic fix.
- Port already in use: stop the other Matchday instance or choose a different host `PublishPort`.
- Browser startup failure during build: the build fails rather than installing a service whose
  discovery browser is known not to launch. Read the failing package/browser build step.
- VPN/public IP differs from home: containers do not override Windows VPN routing. Use the checks
  in [wsl-vpn.md](wsl-vpn.md).

References: [Podman Quadlet](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html),
[Playwright system requirements](https://playwright.dev/python/docs/intro#system-requirements),
[Microsoft WSL systemd](https://learn.microsoft.com/en-us/windows/wsl/systemd).
