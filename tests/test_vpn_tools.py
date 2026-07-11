"""Unit tests for the VPN self-heal tools.

Covers the pure health-signal parsers, the status/reconnect/egress probes with
subprocess output mocked (so nothing here needs a real VPN), and the
``LINKEDIN_VPN_ENABLED`` registration gate.
"""

from typing import Any

from linkedin_mcp_server.tools.vpn import config as vpn_config
from linkedin_mcp_server.tools.vpn import probe as vpn_probe
from linkedin_mcp_server.tools.vpn.config import VpnSettings, vpn_enabled
from linkedin_mcp_server.tools.vpn.parse import (
    extract_egress_ip,
    handshake_age_seconds,
    is_university_ip,
    parse_is_active,
    parse_latest_handshake_epoch,
)


class TestPureParsers:
    def test_parse_is_active(self):
        assert parse_is_active("active\n") is True
        assert parse_is_active("  active  ") is True
        assert parse_is_active("inactive") is False
        assert parse_is_active("failed\n") is False
        assert parse_is_active("") is False

    def test_parse_latest_handshake_epoch_picks_newest_nonzero(self):
        output = "peerA\t1700000000\npeerB\t1700000500\n"
        assert parse_latest_handshake_epoch(output) == 1700000500

    def test_parse_latest_handshake_epoch_all_zero_is_none(self):
        assert parse_latest_handshake_epoch("peerA\t0\n") is None

    def test_parse_latest_handshake_epoch_garbage_is_none(self):
        assert parse_latest_handshake_epoch("") is None
        assert parse_latest_handshake_epoch("no numbers here") is None

    def test_handshake_age_seconds(self):
        output = "peerA\t1000\n"
        assert handshake_age_seconds(output, now=1300.0) == 300.0

    def test_handshake_age_seconds_future_clamped_to_zero(self):
        # Clock skew must never yield a negative age.
        assert handshake_age_seconds("peerA\t2000\n", now=1000.0) == 0.0

    def test_handshake_age_seconds_none_when_never_connected(self):
        assert handshake_age_seconds("peerA\t0\n", now=1300.0) is None

    def test_extract_egress_ip(self):
        assert extract_egress_ip("145.10.20.30\n") == "145.10.20.30"
        assert extract_egress_ip("  34.1.2.3 ") == "34.1.2.3"

    def test_extract_egress_ip_rejects_non_ip(self):
        assert extract_egress_ip("<html>error</html>") is None
        assert extract_egress_ip("") is None
        # An octet > 255 is not a valid IPv4 address.
        assert extract_egress_ip("999.1.1.1") is None

    def test_is_university_ip(self):
        assert is_university_ip("145.10.20.30") is True
        assert is_university_ip("34.120.1.1") is False  # GCP => tunnel down
        assert is_university_ip("8.8.8.8") is False
        assert is_university_ip(None) is False


def _fake_run(
    *,
    is_active: str = "active",
    active_rc: int = 0,
    handshakes: str | None = "peerA\t9999999999\n",
    egress: str | None = "145.10.20.30",
    egress_rc: int = 0,
    restart_rc: int = 0,
):
    """Build a fake ``_run`` that dispatches on argv, returning canned output."""

    async def fake_run(argv: list[str], timeout: float) -> tuple[int, str, str]:
        if "is-active" in argv:
            return active_rc, f"{is_active}\n", ""
        if "restart" in argv:
            return restart_rc, "", ("" if restart_rc == 0 else "Job failed")
        if "latest-handshakes" in argv:
            return (0, handshakes, "") if handshakes is not None else (0, "", "")
        if any("ifconfig.me" in a for a in argv):
            if egress is None:
                return egress_rc or 7, "", "curl: (7) failed to connect"
            return egress_rc, f"{egress}\n", ""
        raise AssertionError(f"unexpected argv: {argv}")

    return fake_run


class TestProbes:
    async def test_collect_status_healthy(self, monkeypatch):
        monkeypatch.setattr(vpn_probe, "_run", _fake_run(egress="145.10.20.30"))
        status = await vpn_probe.collect_status(VpnSettings())
        assert status["enabled"] is True
        assert status["service_active"] is True
        assert status["egress_ip"] == "145.10.20.30"
        assert status["is_university_ip"] is True
        assert status["healthy"] is True
        assert status["handshake_age_seconds"] is not None

    async def test_collect_status_tunnel_down_gcp_ip(self, monkeypatch):
        # Service is up but egress leaked onto the bare GCP IP => not healthy.
        monkeypatch.setattr(vpn_probe, "_run", _fake_run(egress="34.120.1.1"))
        status = await vpn_probe.collect_status(VpnSettings())
        assert status["service_active"] is True
        assert status["is_university_ip"] is False
        assert status["healthy"] is False

    async def test_collect_status_service_inactive(self, monkeypatch):
        monkeypatch.setattr(
            vpn_probe, "_run", _fake_run(is_active="inactive", active_rc=3)
        )
        status = await vpn_probe.collect_status(VpnSettings())
        assert status["service_active"] is False
        assert status["healthy"] is False

    async def test_probe_egress_ip_failure_sets_error(self, monkeypatch):
        monkeypatch.setattr(vpn_probe, "_run", _fake_run(egress=None))
        result = await vpn_probe.probe_egress_ip(VpnSettings())
        assert result["egress_ip"] is None
        assert result["is_university_ip"] is False
        assert "error" in result

    async def test_reconnect_recovers(self, monkeypatch):
        monkeypatch.setattr(vpn_probe, "_run", _fake_run(egress="145.10.20.30"))
        result = await vpn_probe.reconnect(VpnSettings(reconnect_wait_seconds=0.0))
        assert result["restarted"] is True
        assert result["recovered"] is True
        assert result["status"]["healthy"] is True

    async def test_reconnect_restart_failure(self, monkeypatch):
        monkeypatch.setattr(vpn_probe, "_run", _fake_run(restart_rc=1))
        result = await vpn_probe.reconnect(VpnSettings(reconnect_wait_seconds=0.0))
        assert result["restarted"] is False
        assert result["recovered"] is False
        assert "error" in result


class TestEnvGate:
    def test_vpn_enabled_truthy(self, monkeypatch):
        for value in ("1", "true", "yes", "on", "TRUE"):
            monkeypatch.setenv(vpn_config.VpnEnvironmentKeys.ENABLED, value)
            assert vpn_enabled() is True

    def test_vpn_enabled_falsy_or_unset(self, monkeypatch):
        monkeypatch.delenv(vpn_config.VpnEnvironmentKeys.ENABLED, raising=False)
        assert vpn_enabled() is False
        for value in ("0", "false", "", "no"):
            monkeypatch.setenv(vpn_config.VpnEnvironmentKeys.ENABLED, value)
            assert vpn_enabled() is False

    def test_load_vpn_settings_defaults_and_overrides(self, monkeypatch):
        for key in (
            vpn_config.VpnEnvironmentKeys.PROXY_URL,
            vpn_config.VpnEnvironmentKeys.SERVICE,
            vpn_config.VpnEnvironmentKeys.NETNS,
            vpn_config.VpnEnvironmentKeys.RECONNECT_WAIT,
        ):
            monkeypatch.delenv(key, raising=False)
        defaults = vpn_config.load_vpn_settings()
        assert defaults.proxy_url == "http://10.200.0.2:8888"
        assert defaults.service == "linkedin-vpn"
        assert defaults.netns == "lkvpn"

        monkeypatch.setenv(vpn_config.VpnEnvironmentKeys.NETNS, "othervpn")
        monkeypatch.setenv(vpn_config.VpnEnvironmentKeys.RECONNECT_WAIT, "-5")
        overridden = vpn_config.load_vpn_settings()
        assert overridden.netns == "othervpn"
        # A non-positive wait falls back to the default rather than being used.
        assert overridden.reconnect_wait_seconds == 8.0


class TestRegistrationGate:
    async def test_vpn_tools_registered_when_enabled(self, monkeypatch):
        monkeypatch.setenv(vpn_config.VpnEnvironmentKeys.ENABLED, "1")
        # Any invocation is mocked, but registration itself runs no subprocess.
        monkeypatch.setattr(vpn_probe, "_run", _fake_run())

        from linkedin_mcp_server.server import create_mcp_server

        mcp = create_mcp_server()
        for name in ("vpn_status", "vpn_reconnect", "vpn_egress_ip"):
            assert await mcp.get_tool(name) is not None

    async def test_vpn_tools_absent_when_disabled(self, monkeypatch):
        monkeypatch.delenv(vpn_config.VpnEnvironmentKeys.ENABLED, raising=False)

        from linkedin_mcp_server.server import create_mcp_server

        mcp = create_mcp_server()
        for name in ("vpn_status", "vpn_reconnect", "vpn_egress_ip"):
            assert await mcp.get_tool(name) is None

    async def test_registered_vpn_status_returns_structured_dict(self, monkeypatch):
        monkeypatch.setenv(vpn_config.VpnEnvironmentKeys.ENABLED, "1")
        monkeypatch.setattr(vpn_probe, "_run", _fake_run(egress="145.10.20.30"))

        from fastmcp import FastMCP

        from linkedin_mcp_server.tools.vpn import register_vpn_tools

        mcp = FastMCP("test")
        register_vpn_tools(mcp)
        result = await mcp.call_tool("vpn_status", {})
        structured: dict[str, Any] = result.structured_content
        assert structured["healthy"] is True
        assert structured["is_university_ip"] is True
