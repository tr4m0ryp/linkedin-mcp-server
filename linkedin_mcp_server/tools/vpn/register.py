"""FastMCP registration for the VPN self-heal tools.

These tools run privileged host commands (systemctl / ip netns / wg) and exist
ONLY on the VM deployment, gated behind ``LINKEDIN_VPN_ENABLED``; they are never
present in the default local build. Unlike the scraping tools they never raise
to the caller -- each returns a structured dict, folding any failure into an
``error`` field -- so an operator or agent can read the tunnel's health and
repair it without a tool call ever throwing.
"""

import logging
from typing import Any

from fastmcp import FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS

from .config import load_vpn_settings
from .probe import collect_status, probe_egress_ip, reconnect

logger = logging.getLogger(__name__)


def register_vpn_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register the VPN status / reconnect / egress tools with the MCP server.

    Call only when :func:`linkedin_mcp_server.tools.vpn.config.vpn_enabled`
    is true; the server wires this behind the ``LINKEDIN_VPN_ENABLED`` flag.
    """

    @mcp.tool(
        timeout=tool_timeout,
        title="VPN Status",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"vpn", "ops"},
    )
    async def vpn_status() -> dict[str, Any]:
        """Report the split-tunnel VPN health for the LinkedIn browser egress.

        Returns a dict with ``enabled``, ``service_active`` (systemd unit up),
        ``handshake_age_seconds`` (age of the newest WireGuard handshake, or
        null if never connected), ``egress_ip`` (as seen through the tunnel
        proxy), ``is_university_ip`` (true for a 145.x address; a 34.x GCP
        address means the tunnel is DOWN), and ``healthy`` (service up AND
        egress is a university IP). Never raises: failures surface as
        ``service_error`` / ``egress_error`` fields.
        """
        try:
            return await collect_status(load_vpn_settings())
        except Exception as exc:  # never raise to the MCP caller
            logger.exception("vpn_status failed")
            return {"enabled": True, "healthy": False, "error": str(exc)}

    @mcp.tool(
        timeout=tool_timeout,
        title="VPN Reconnect",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"vpn", "ops"},
    )
    async def vpn_reconnect() -> dict[str, Any]:
        """Restart the VPN service once and re-check, to recover a down tunnel.

        Idempotent and bounded: performs exactly one ``systemctl restart
        linkedin-vpn``, waits for the tunnel to re-establish, then returns
        ``restarted``, ``recovered`` (post-restart status is healthy), and the
        fresh ``status`` dict. Use when ``vpn_status`` reports unhealthy (e.g.
        a 34.x GCP egress IP). Never raises: failures surface as ``error``.
        """
        try:
            return await reconnect(load_vpn_settings())
        except Exception as exc:  # never raise to the MCP caller
            logger.exception("vpn_reconnect failed")
            return {"restarted": False, "recovered": False, "error": str(exc)}

    @mcp.tool(
        timeout=tool_timeout,
        title="VPN Egress IP",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"vpn", "ops"},
    )
    async def vpn_egress_ip() -> dict[str, Any]:
        """Return the current egress IP seen through the tunnel proxy.

        Fetches ``https://ifconfig.me`` via the in-namespace HTTP proxy. Returns
        ``egress_ip`` (or null if it could not be read) and ``is_university_ip``.
        Never raises: failures surface as ``error``.
        """
        try:
            return await probe_egress_ip(load_vpn_settings())
        except Exception as exc:  # never raise to the MCP caller
            logger.exception("vpn_egress_ip failed")
            return {"egress_ip": None, "is_university_ip": False, "error": str(exc)}
