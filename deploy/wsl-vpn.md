# WSL, laptop availability, and Windows OpenVPN

Matchday is available only while the machine running it is awake and its Linux/WSL environment is
running. A background service removes the need to keep uvicorn in a foreground console; it cannot
serve video from a powered-off laptop. If you only watch when a laptop is on, an on-demand deployment
is enough. Use the start/stop commands for your deployment model.

## OpenVPN runs on Windows in this setup

WSL 2 normally reaches the network through Windows. With a Windows OpenVPN connection, the effective
Windows VPN routes and filtering determine where WSL's public traffic goes. A separate Ubuntu/Alma
distribution, Podman, a `0.0.0.0` listening address, or mirrored networking is not a per-application
VPN exclusion. Changing the listener selects who can connect to Matchday; it does not choose the
outbound internet connection used by Python or Chromium.

There is no Matchday setting that can reliably force the home Wi-Fi connection around a full-tunnel
Windows VPN. The deployment scripts do not edit Windows routes, OpenVPN profiles, DNS, or firewalls.

The suitable configuration, when supported by your workplace, is **split tunneling**:

- Work network destinations use OpenVPN.
- Public internet destinations, including the stream provider, use the normal home connection.
- Work DNS continues resolving the internal names required for your job.

Ask the VPN administrator whether the connection already uses split tunneling and whether this
separation is supported. Exact routes depend on your work subnets, client, server-pushed settings,
and endpoint policy. Do not add `route-nopull`, replace the default gateway, or copy arbitrary route
commands: they can break work access and bypass required routing. Container installation does not
resolve that policy or routing configuration.

If full-tunnel routing is required, use a separate personal machine at home for the Matchday server.
Its requests to the provider then use that machine's home connection. A work laptop used as a viewer
can still send its browser traffic through the work VPN; private access to a home server does not
guarantee a VPN exclusion on the viewer either.

## Read-only checks

With the VPN in its normal disconnected state, record the public IP from Windows PowerShell:

```powershell
Invoke-RestMethod https://api.ipify.org
Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0','0.0.0.0/1','128.0.0.0/1' |
    Format-Table DestinationPrefix,InterfaceAlias,NextHop,RouteMetric
```

Inside the WSL distribution, record:

```bash
curl --fail --silent --show-error --max-time 15 https://api.ipify.org
ip route
```

Repeat when the VPN is connected. These commands only inspect state and contact a public-IP lookup
service. They do not change routing. A VPN can use two `/1` routes while leaving the original default
route visible, so the default route alone is not proof that traffic avoids the VPN.

If you deploy the Podman model, check the running container too:

```bash
podman exec matchday /app/.venv/bin/python -c "import httpx; print(httpx.get('https://api.ipify.org', timeout=15, trust_env=False).text)"
```

If the WSL/container public IP changes to the work VPN's public IP, its traffic is using that egress.
An unchanged IP is useful evidence but does not prove every destination or IPv6 traffic follows the
same path. Use the stream timing diagnostic for the actual source as well. Browsers, enterprise
proxies, VPN filters, and DNS can affect individual connections; a route/IP check is not a guarantee
that all Matchday traffic bypasses the work network.

## Laptop and WSL lifetime

Enabling systemd in `/etc/wsl.conf` enables the Linux service manager. It does not launch WSL whenever
Windows starts, prevent Windows sleep, or keep WSL alive indefinitely. `wsl --shutdown` stops all WSL
instances and their services. The deployment scripts do not install a Windows startup task or change
power settings. If a stopped WSL distribution needs an active session, keep it open while watching.

References: [Microsoft WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking),
[Microsoft WSL systemd](https://learn.microsoft.com/en-us/windows/wsl/systemd),
[Microsoft's WSL service-lifetime explanation](https://devblogs.microsoft.com/commandline/systemd-support-is-now-available-in-wsl/),
[OpenVPN routing options](https://openvpn.net/community-docs/community-articles/openvpn-2-6-manual/).
