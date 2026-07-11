# VM HTTPS exposure (Caddy + GCP firewall)

How to expose the LinkedIn MCP server to the **claude.ai web connector** over
HTTPS. Unlike the sibling connectors (`finding_house_mcp`, `enrichment-mcp`)
which run on Cloud Run, this server needs a **real browser with a persistent
Chromium profile**, so it runs on a long-lived **GCE VM** instead of an
ephemeral container. The auth layer is identical (WorkOS AuthKit + static
bearer, see [`../linkedin_mcp_server/auth.py`](../linkedin_mcp_server/auth.py));
only the exposure differs: a **Caddy** reverse proxy on the VM terminates TLS
and forwards to the FastMCP server on loopback.

> These are configuration + instructions only. Nothing here is applied
> automatically — do not run the firewall command, deploy, or restart the VM
> as part of merging this. A public hostname / DNS record is required and is
> **yours to provide** (point an `A` record at the VM's external IP first).

## Target VM

| Field       | Value                          |
| ----------- | ------------------------------ |
| Instance    | `linkedin-mcp`                 |
| Zone        | `europe-west4-a`               |
| Project     | `shor-x-sinas`                 |
| Network tag | `linkedin-mcp`                 |
| MCP service | `127.0.0.1:8000` (loopback)    |

The FastMCP server binds loopback only; Caddy is the sole process listening on
the public interface. Keep it that way — the server never needs a public bind.

## 1. Run the server (on the VM)

Bind to loopback and enable auth. Reuse the **same** AuthKit tenant as the
other MCP connectors (do not create a new one). Either credential is accepted,
so you can set the bearer for Claude Code / curl and AuthKit for the web
connector at the same time:

```bash
# ~/.linkedin-mcp env (systemd unit, .env, or exported before launch)
TRANSPORT=streamable-http
HOST=127.0.0.1
PORT=8000
HTTP_PATH=/mcp

# Auth (see .env.example). Set MCP_API_KEY, WORKOS_AUTHKIT_DOMAIN, or both.
MCP_API_KEY=<long-random-string>
WORKOS_AUTHKIT_DOMAIN=https://<same-tenant>.authkit.app
MCP_BASE_URL=https://linkedin-mcp.example.com   # public hostname, no /mcp
```

## 2. Caddyfile (TLS terminator)

Install Caddy on the VM, then use this `/etc/caddy/Caddyfile`. Caddy
auto-provisions and renews a Let's Encrypt certificate for the hostname:

```caddy
# /etc/caddy/Caddyfile
# Replace linkedin-mcp.example.com with the hostname whose A record points at
# the VM's external IP. Caddy obtains the TLS cert automatically.
linkedin-mcp.example.com {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8000
}
```

Reload after editing: `sudo systemctl reload caddy` (do this yourself on the
VM; it is not part of this change).

The claude.ai connector URL is then `https://linkedin-mcp.example.com/mcp`.

## 3. GCP firewall rule (open 443 for the tag)

Mirror the existing `allow-gmail-mcp-web` rule, retargeted at the `linkedin-mcp`
tag. **Do not run this now** — it is provided for the operator to apply once DNS
is in place:

```bash
gcloud compute firewall-rules create allow-linkedin-mcp-web \
  --project=shor-x-sinas \
  --network=default \
  --direction=INGRESS \
  --action=ALLOW \
  --rules=tcp:443 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=linkedin-mcp \
  --description="Public HTTPS (443) to the linkedin-mcp VM; Caddy terminates TLS in front of the FastMCP server on 127.0.0.1:8000."
```

Caddy's automatic-HTTPS also needs inbound **80** for the ACME HTTP-01
challenge and the HTTP→HTTPS redirect. If port 80 is not already open for the
tag, add a matching rule (same shape, `--rules=tcp:80`,
`allow-linkedin-mcp-acme`). (Caddy can fall back to the TLS-ALPN-01 challenge on
443 alone, but opening 80 is the reliable default.)

## 4. Verify

From your workstation, once DNS + firewall + Caddy are live:

```bash
# Rejected without a credential (401):
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  https://linkedin-mcp.example.com/mcp

# Accepted with the static bearer:
curl -sS -X POST https://linkedin-mcp.example.com/mcp \
  -H "Authorization: Bearer $MCP_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"curl","version":"0"}}}'
```

For the web connector, add `https://linkedin-mcp.example.com/mcp` in
claude.ai → Settings → Connectors and complete the AuthKit OAuth flow.
