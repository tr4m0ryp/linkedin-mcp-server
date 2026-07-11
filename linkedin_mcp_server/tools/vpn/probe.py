"""Privileged VPN probes and self-heal actions.

Runs the host commands that read and repair the split-tunnel (systemctl,
``ip netns exec ... wg``, and a proxied curl) via ``asyncio.create_subprocess_exec``
-- argv lists only, never a shell string, so nothing is interpolated into a
shell. Each probe returns a structured dict and never raises to the caller: any
failure is captured into an ``error`` field.

The privileged argv is built from :class:`VpnSettings` but defaults to exactly
the commands granted in ``deploy/vpn/sudoers.d/linkedin-vpn``. Overriding the
service/namespace via env changes the argv and will therefore fail closed under
``sudo -n`` unless a matching sudoers rule is also installed.
"""

import asyncio
import logging
from typing import Any

from .config import (
    HANDSHAKE_STALE_SECONDS,
    IP_PATH,
    SYSTEMCTL_PATH,
    WG_INTERFACE,
    VpnSettings,
)
from .parse import (
    extract_egress_ip,
    handshake_age_seconds,
    is_university_ip,
    parse_is_active,
)

logger = logging.getLogger(__name__)

# Hard ceilings so a wedged command can never hang a tool call. curl carries its
# own --max-time; these bound the systemctl/wg reads and are a backstop for curl.
_READ_TIMEOUT_SECONDS = 20.0
_RESTART_TIMEOUT_SECONDS = 45.0
_EGRESS_TIMEOUT_SECONDS = 20.0
_CURL_MAX_TIME_SECONDS = 15


async def _run(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """Run ``argv`` with a timeout; return ``(returncode, stdout, stderr)``.

    Never raises: a missing binary, non-zero exit, or timeout is folded into the
    return tuple with a negative return code so callers branch on data, not
    exceptions. On timeout the child is killed and reaped.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        logger.warning("VPN command failed to start (%s): %s", argv[0], exc)
        return -1, "", str(exc)

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("VPN command timed out after %ss: %s", timeout, argv)
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return -1, "", f"timed out after {timeout}s"

    rc = proc.returncode if proc.returncode is not None else -1
    return (
        rc,
        stdout_b.decode("utf-8", "replace"),
        stderr_b.decode("utf-8", "replace"),
    )


def _is_active_argv(settings: VpnSettings) -> list[str]:
    return ["sudo", "-n", SYSTEMCTL_PATH, "is-active", settings.service]


def _restart_argv(settings: VpnSettings) -> list[str]:
    return ["sudo", "-n", SYSTEMCTL_PATH, "restart", settings.service]


def _handshake_argv(settings: VpnSettings) -> list[str]:
    return [
        "sudo",
        "-n",
        IP_PATH,
        "netns",
        "exec",
        settings.netns,
        "wg",
        "show",
        WG_INTERFACE,
        "latest-handshakes",
    ]


def _egress_argv(settings: VpnSettings) -> list[str]:
    return [
        "curl",
        "-4",
        "--max-time",
        str(_CURL_MAX_TIME_SECONDS),
        "-x",
        settings.proxy_url,
        "https://ifconfig.me",
    ]


async def probe_egress_ip(settings: VpnSettings) -> dict[str, Any]:
    """Return the current egress IP as seen through the in-namespace proxy."""
    rc, out, err = await _run(_egress_argv(settings), _EGRESS_TIMEOUT_SECONDS)
    ip = extract_egress_ip(out)
    result: dict[str, Any] = {
        "egress_ip": ip,
        "is_university_ip": is_university_ip(ip),
    }
    if ip is None:
        result["error"] = (
            err.strip() or out.strip() or f"curl exited {rc}"
        ) or "egress IP could not be determined"
    return result


async def collect_status(settings: VpnSettings) -> dict[str, Any]:
    """Gather the full VPN health picture into a structured dict.

    Concurrently reads the service state, the WireGuard handshake age, and the
    proxied egress IP. ``healthy`` is true when the service is active AND the
    egress is a university IP -- the two independent signals that the browser is
    actually leaving through the tunnel.
    """
    active_task = _run(_is_active_argv(settings), _READ_TIMEOUT_SECONDS)
    handshake_task = _run(_handshake_argv(settings), _READ_TIMEOUT_SECONDS)
    egress_task = probe_egress_ip(settings)

    (
        (active_rc, active_out, _active_err),
        (
            _hs_rc,
            hs_out,
            _hs_err,
        ),
        egress,
    ) = await asyncio.gather(active_task, handshake_task, egress_task)

    service_active = parse_is_active(active_out)
    age = handshake_age_seconds(hs_out)
    egress_ip = egress.get("egress_ip")
    university = bool(egress.get("is_university_ip"))
    healthy = service_active and university

    status: dict[str, Any] = {
        "enabled": True,
        "service": settings.service,
        "service_active": service_active,
        "handshake_age_seconds": age,
        "handshake_stale": age is None or age > HANDSHAKE_STALE_SECONDS,
        "egress_ip": egress_ip,
        "is_university_ip": university,
        "healthy": healthy,
    }
    if not service_active and active_rc != 0 and not active_out.strip():
        status["service_error"] = (
            "systemctl is-active could not be read (check sudoers / service name)"
        )
    if "error" in egress:
        status["egress_error"] = egress["error"]
    return status


async def reconnect(settings: VpnSettings) -> dict[str, Any]:
    """Restart the VPN service once, wait, then re-check. Idempotent, bounded.

    Runs exactly one ``systemctl restart``; on success it waits for the tunnel
    to re-establish, then returns the fresh status plus ``recovered`` (whether
    the post-restart status is healthy).
    """
    rc, _out, err = await _run(_restart_argv(settings), _RESTART_TIMEOUT_SECONDS)
    restarted = rc == 0
    if not restarted:
        return {
            "restarted": False,
            "recovered": False,
            "error": (err.strip() or f"systemctl restart exited {rc}"),
        }

    await asyncio.sleep(settings.reconnect_wait_seconds)
    status = await collect_status(settings)
    return {
        "restarted": True,
        "recovered": bool(status.get("healthy")),
        "status": status,
    }
