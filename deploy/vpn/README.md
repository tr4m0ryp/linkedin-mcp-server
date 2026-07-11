# Split-tunnel eduVPN for the LinkedIn MCP

The LinkedIn MCP runs on a GCE VM, but LinkedIn must see traffic coming from a
**university IP (145.x)**, not the VM's GCP IP (34.x). This directory codifies
the split-tunnel that makes the browser -- and only the browser -- egress
through a university [eduVPN](https://www.eduvpn.org/) WireGuard tunnel, while
the rest of the VM (SSH, package updates, systemd) keeps using the normal GCP
network.

## Why a namespace, and why a proxy

A plain `wg-quick up` would route the **whole VM** through the university, which
we do not want (it would tunnel SSH, break GCP metadata, and put all VM traffic
on the university's network). So the tunnel is isolated:

- **Network namespace `lkvpn`** holds the WireGuard interface `wg0`. Only
  processes run with `ip netns exec lkvpn` use it. The root namespace is
  untouched.
- **The WireGuard-in-a-namespace trick:** `wg0` is created in the *root*
  namespace and then *moved* into `lkvpn`. The kernel keeps the UDP transport
  socket in the namespace where the device was created, so the **encrypted**
  packets still leave via the VM's normal GCP NIC (no "tunnel the tunnel"
  deadlock), while the **decrypted** side lives in `lkvpn` and routes out
  `wg0` to the university.
- **A veth pair** bridges the two namespaces: `10.200.0.1/24` in root ↔
  `10.200.0.2/24` in `lkvpn`. It carries *only* proxy control traffic.
- **`tinyproxy` inside `lkvpn`** listens on `10.200.0.2:8888`. Chromium (which
  runs in the root namespace, managed by the MCP) is pointed at that proxy via
  `LINKEDIN_PROXY_SERVER=http://10.200.0.2:8888`. The proxy accepts the request
  over the veth, then makes its own upstream fetch, which -- being inside
  `lkvpn` -- egresses through `wg0` and exits at the university IP. The
  `10.200.0.0/24` on-link route is more specific than `wg0`'s default route, so
  proxy replies return over the veth instead of vanishing into the tunnel.

Net effect: every LinkedIn page load exits at `145.x`; everything else on the
VM exits at `34.x`.

## Files

| File | Installs to | Purpose |
| --- | --- | --- |
| `linkedin-vpn-up.sh` | `/usr/local/sbin/linkedin-vpn-up.sh` | Idempotent bring-up: builds `lkvpn`, the veth pair, `wg0` (from `/etc/wireguard/eduvpn.conf`), per-ns DNS, and starts `tinyproxy`. |
| `linkedin-vpn.service` | `/etc/systemd/system/linkedin-vpn.service` | `oneshot` + `RemainAfterExit`, `Before=linkedin-mcp.service`. Runs the up-script; `restart` re-runs it to reconnect. |
| `tinyproxy-lkvpn.conf` | `/etc/tinyproxy/tinyproxy-lkvpn.conf` | Proxy config: `Port 8888`, `Listen 10.200.0.2`, `Allow 10.200.0.0/24`. |
| `linkedin-mcp.service.d/vpn.conf` | `/etc/systemd/system/linkedin-mcp.service.d/vpn.conf` | Drop-in: `Requires`/`After` the VPN unit and sets `LINKEDIN_PROXY_SERVER` (+ `LINKEDIN_VPN_ENABLED`). |
| `sudoers.d/linkedin-vpn` | `/etc/sudoers.d/linkedin-vpn` (0440) | Grants the `linkedin` user passwordless sudo on exactly the three self-heal commands. |

## Install

```sh
sudo install -m 0755 linkedin-vpn-up.sh          /usr/local/sbin/linkedin-vpn-up.sh
sudo install -m 0644 linkedin-vpn.service        /etc/systemd/system/linkedin-vpn.service
sudo install -m 0644 tinyproxy-lkvpn.conf        /etc/tinyproxy/tinyproxy-lkvpn.conf
sudo install -m 0440 -o root -g root sudoers.d/linkedin-vpn /etc/sudoers.d/linkedin-vpn
sudo visudo -cf /etc/sudoers.d/linkedin-vpn      # validate before trusting
sudo install -D -m 0644 linkedin-mcp.service.d/vpn.conf \
    /etc/systemd/system/linkedin-mcp.service.d/vpn.conf

# WireGuard config from the university eduVPN portal:
sudo install -m 0600 eduvpn.conf /etc/wireguard/eduvpn.conf

sudo systemctl daemon-reload
sudo systemctl enable --now linkedin-vpn
sudo systemctl restart linkedin-mcp
```

## Health signals

| Signal | Command | Healthy |
| --- | --- | --- |
| Service up | `systemctl is-active linkedin-vpn` | `active` |
| Handshake | `sudo ip netns exec lkvpn wg show wg0 latest-handshakes` | recent non-zero epoch |
| Egress IP | `curl -4 -x http://10.200.0.2:8888 https://ifconfig.me` | `145.x` (a `34.x` GCP IP = tunnel DOWN) |

## The ~monthly eduVPN key refresh

eduVPN issues **short-lived** WireGuard keys (typically valid ~1 month). When
they expire the handshake stops renewing and the egress silently falls back to
the VM's `34.x` GCP IP -- the fail state. To refresh:

1. Download a fresh `eduvpn.conf` from the university portal.
2. `sudo install -m 0600 eduvpn.conf /etc/wireguard/eduvpn.conf`
3. `sudo systemctl restart linkedin-vpn`

The bring-up script re-reads the config's `Address`/`DNS`/peer keys on every
run, so a restart is all that is needed after replacing the file.

## How the self-heal MCP tools map to this

The VM build enables three MCP tools (`LINKEDIN_VPN_ENABLED=1`,
`linkedin_mcp_server/tools/vpn/`) that expose these same signals to an operator
or agent so a down tunnel can be noticed and repaired without shell access:

| Tool | Runs | Maps to |
| --- | --- | --- |
| `vpn_status` | `systemctl is-active` + `wg ... latest-handshakes` + proxied `ifconfig.me` | Full health table above; `healthy` = service active AND egress is `145.x`. |
| `vpn_egress_ip` | proxied `curl ... ifconfig.me` | The egress-IP row -- the quickest "is the tunnel up?" check. |
| `vpn_reconnect` | `systemctl restart linkedin-vpn`, wait, re-check | The key-refresh / dropped-tunnel recovery step. Idempotent: one restart, then reports whether it `recovered`. |

The three privileged commands are exactly what `sudoers.d/linkedin-vpn` grants
(passwordless, path-pinned), so the unprivileged `linkedin` service user can run
the tools but nothing broader.
