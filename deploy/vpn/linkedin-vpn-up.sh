#!/usr/bin/env bash
#
# linkedin-vpn-up.sh -- bring up the split-tunnel eduVPN for the LinkedIn MCP.
#
# Builds an isolated network namespace (lkvpn) holding a WireGuard interface
# (wg0) whose DECRYPTED traffic egresses via the university (145.x), while the
# ENCRYPTED transport still leaves through the VM's normal GCP NIC. A veth pair
# bridges the root namespace to lkvpn so an in-namespace HTTP proxy (tinyproxy
# on 10.200.0.2:8888) is reachable from the MCP's Chromium in the root ns; the
# proxy's own upstream fetches route through wg0 -> university IP.
#
# The WireGuard-in-a-namespace trick: create wg0 in the ROOT ns, then MOVE it
# into lkvpn. The kernel keeps its UDP transport socket in the namespace where
# the device was created, so encrypted packets use the root ns default route
# (no "tunnel the tunnel" deadlock), while wg0's decrypted side lives in lkvpn.
#
# Idempotent: safe to re-run; `systemctl restart linkedin-vpn` re-runs it to
# reconnect after an eduVPN key refresh or a dropped tunnel.
set -euo pipefail

NETNS="${LINKEDIN_VPN_NETNS:-lkvpn}"
WG_IFACE="${LINKEDIN_VPN_WG_IFACE:-wg0}"
WG_CONF="${LINKEDIN_VPN_WG_CONF:-/etc/wireguard/eduvpn.conf}"
VETH_HOST="${LINKEDIN_VPN_VETH_HOST:-lkvpn-host}"
VETH_NS="${LINKEDIN_VPN_VETH_NS:-lkvpn-ns}"
HOST_ADDR="${LINKEDIN_VPN_HOST_ADDR:-10.200.0.1/24}"
NS_ADDR="${LINKEDIN_VPN_NS_ADDR:-10.200.0.2/24}"
NS_IP="${NS_ADDR%/*}"
TINYPROXY_CONF="${LINKEDIN_VPN_TINYPROXY_CONF:-/etc/tinyproxy/tinyproxy-lkvpn.conf}"

log() { printf '[linkedin-vpn-up] %s\n' "$*"; }

require_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        echo "must run as root" >&2
        exit 1
    fi
}

require_root

if [[ ! -r "$WG_CONF" ]]; then
    echo "WireGuard config not found or unreadable: $WG_CONF" >&2
    exit 1
fi

# --- 1. Network namespace + loopback ----------------------------------------
if ! ip netns list | grep -qw "$NETNS"; then
    log "creating netns $NETNS"
    ip netns add "$NETNS"
fi
ip netns exec "$NETNS" ip link set lo up

# --- 2. veth pair: root (10.200.0.1) <-> lkvpn (10.200.0.2) ------------------
# The pair carries ONLY proxy control traffic (Chromium -> tinyproxy). The
# 10.200.0.0/24 on-link route inside lkvpn is more specific than the wg0 default
# route, so proxy replies return over the veth instead of into the tunnel.
if ! ip link show "$VETH_HOST" >/dev/null 2>&1 &&
    ! ip -n "$NETNS" link show "$VETH_NS" >/dev/null 2>&1; then
    log "creating veth pair $VETH_HOST <-> $VETH_NS"
    ip link add "$VETH_HOST" type veth peer name "$VETH_NS"
fi
# Move the ns end into lkvpn only if it is still in the root ns.
if ip link show "$VETH_NS" >/dev/null 2>&1; then
    ip link set "$VETH_NS" netns "$NETNS"
fi
ip addr replace "$HOST_ADDR" dev "$VETH_HOST"
ip link set "$VETH_HOST" up
ip -n "$NETNS" addr replace "$NS_ADDR" dev "$VETH_NS"
ip -n "$NETNS" link set "$VETH_NS" up

# --- 3. WireGuard interface: create in root ns, then move into lkvpn ---------
if ip -n "$NETNS" link show "$WG_IFACE" >/dev/null 2>&1; then
    log "resetting existing $WG_IFACE in $NETNS"
    ip -n "$NETNS" link del "$WG_IFACE"
fi
ip link show "$WG_IFACE" >/dev/null 2>&1 && ip link del "$WG_IFACE"
log "creating $WG_IFACE in root ns and moving into $NETNS"
ip link add "$WG_IFACE" type wireguard
ip link set "$WG_IFACE" netns "$NETNS"

# Apply the peer/key config (wg-quick strip drops Address/DNS so `wg setconf`
# accepts it), then assign the tunnel address parsed from the same conf.
ip netns exec "$NETNS" wg setconf "$WG_IFACE" <(wg-quick strip "$WG_CONF")

WG_ADDR="$(awk -F'=' 'tolower($1) ~ /^[[:space:]]*address[[:space:]]*$/ {
    gsub(/[[:space:]]/, "", $2); split($2, a, ","); print a[1]; exit }' "$WG_CONF")"
if [[ -z "$WG_ADDR" ]]; then
    echo "no Address in $WG_CONF" >&2
    exit 1
fi
ip -n "$NETNS" addr replace "$WG_ADDR" dev "$WG_IFACE"
ip -n "$NETNS" link set "$WG_IFACE" up
ip -n "$NETNS" route replace default dev "$WG_IFACE"

# --- 4. Per-namespace DNS (read by `ip netns exec`) -------------------------
WG_DNS="$(awk -F'=' 'tolower($1) ~ /^[[:space:]]*dns[[:space:]]*$/ {
    gsub(/[[:space:]]/, "", $2); split($2, a, ","); print a[1]; exit }' "$WG_CONF")"
mkdir -p "/etc/netns/$NETNS"
printf 'nameserver %s\n' "${WG_DNS:-1.1.1.1}" >"/etc/netns/$NETNS/resolv.conf"

# --- 5. tinyproxy inside the namespace --------------------------------------
# Kill any prior instance bound to this conf, then start fresh (tinyproxy
# daemonizes, so the oneshot unit's RemainAfterExit keeps the state).
pkill -f "tinyproxy -c $TINYPROXY_CONF" 2>/dev/null || true
log "starting tinyproxy in $NETNS on $NS_IP:8888"
ip netns exec "$NETNS" tinyproxy -c "$TINYPROXY_CONF"

log "up: $NETNS ready, egress via $WG_IFACE, proxy on $NS_IP:8888"
