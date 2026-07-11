"""Configuration for the VPN self-heal tools.

The LinkedIn browser egresses through a university eduVPN held in an isolated
network namespace (``lkvpn``) with an in-namespace HTTP proxy. These settings
describe how the VPN self-heal tools reach that machinery. All values default
to the production VM layout and can be overridden by environment variables for
non-standard deployments or tests.

Only ``LINKEDIN_VPN_ENABLED`` gates registration. The remaining knobs let a
deployment relocate the proxy, service, or namespace; note that the sudoers
grant shipped in ``deploy/vpn/`` is scoped to the DEFAULT service/namespace, so
overriding them also requires a matching sudoers file.
"""

import os
from dataclasses import dataclass

from linkedin_mcp_server.config.loaders.parsing import TRUTHY_VALUES

# Absolute paths of the privileged binaries. Kept as constants (not env-driven)
# because the sudoers rules match on the exact command path; changing them here
# without updating sudoers would only produce password prompts that fail under
# ``sudo -n``. These match a merged-usr Debian/Ubuntu GCE image.
SYSTEMCTL_PATH = "/bin/systemctl"
IP_PATH = "/usr/sbin/ip"
WG_INTERFACE = "wg0"

# Handshakes older than this (seconds) are treated as stale for diagnostics.
# WireGuard renews roughly every ~2 minutes while traffic flows, so a fresh
# tunnel stays well under this ceiling.
HANDSHAKE_STALE_SECONDS = 300.0


class VpnEnvironmentKeys:
    """Environment variable names for the VPN self-heal tools."""

    ENABLED = "LINKEDIN_VPN_ENABLED"
    PROXY_URL = "LINKEDIN_VPN_PROXY_URL"
    SERVICE = "LINKEDIN_VPN_SERVICE"
    NETNS = "LINKEDIN_VPN_NETNS"
    RECONNECT_WAIT = "LINKEDIN_VPN_RECONNECT_WAIT_SECONDS"


DEFAULT_PROXY_URL = "http://10.200.0.2:8888"
DEFAULT_SERVICE = "linkedin-vpn"
DEFAULT_NETNS = "lkvpn"
DEFAULT_RECONNECT_WAIT_SECONDS = 8.0


@dataclass(frozen=True)
class VpnSettings:
    """Resolved VPN tool settings."""

    proxy_url: str = DEFAULT_PROXY_URL
    service: str = DEFAULT_SERVICE
    netns: str = DEFAULT_NETNS
    reconnect_wait_seconds: float = DEFAULT_RECONNECT_WAIT_SECONDS


def vpn_enabled() -> bool:
    """Return whether the VPN self-heal tools should be registered.

    Truthy values mirror the rest of the app's env parsing (1/true/yes/on).
    """
    raw = os.getenv(VpnEnvironmentKeys.ENABLED, "").strip().lower()
    return raw in TRUTHY_VALUES


def _positive_float(raw: str, fallback: float) -> float:
    """Parse a positive finite float, falling back on any bad input."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    if value <= 0 or value != value or value in (float("inf"), float("-inf")):
        return fallback
    return value


def load_vpn_settings() -> VpnSettings:
    """Build :class:`VpnSettings` from the environment, applying defaults."""
    proxy_url = os.getenv(VpnEnvironmentKeys.PROXY_URL, "").strip() or DEFAULT_PROXY_URL
    service = os.getenv(VpnEnvironmentKeys.SERVICE, "").strip() or DEFAULT_SERVICE
    netns = os.getenv(VpnEnvironmentKeys.NETNS, "").strip() or DEFAULT_NETNS
    wait_raw = os.getenv(VpnEnvironmentKeys.RECONNECT_WAIT, "").strip()
    reconnect_wait = (
        _positive_float(wait_raw, DEFAULT_RECONNECT_WAIT_SECONDS)
        if wait_raw
        else DEFAULT_RECONNECT_WAIT_SECONDS
    )
    return VpnSettings(
        proxy_url=proxy_url,
        service=service,
        netns=netns,
        reconnect_wait_seconds=reconnect_wait,
    )
