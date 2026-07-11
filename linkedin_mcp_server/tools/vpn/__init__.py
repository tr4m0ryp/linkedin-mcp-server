"""VPN self-heal tools for the LinkedIn MCP server.

Optional, VM-only tools that observe and repair the split-tunnel eduVPN the
browser egresses through. Registered only when ``LINKEDIN_VPN_ENABLED`` is
truthy (see :func:`vpn_enabled`); absent from the default local build.
"""

from .config import load_vpn_settings, vpn_enabled
from .register import register_vpn_tools

__all__ = [
    "load_vpn_settings",
    "register_vpn_tools",
    "vpn_enabled",
]
