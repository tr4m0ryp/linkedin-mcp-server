"""Pure parsers for VPN health signals.

Kept free of I/O so the parsing logic can be unit-tested against captured
command output without a real VPN. Every function is defensive: malformed or
empty input yields a safe ``None``/``False`` rather than raising.
"""

import re
import time

# A bare IPv4 address as printed by ``ifconfig.me`` (no port, no path). We do
# not accept anything that is not four dotted octets so an HTML error page or a
# proxy failure message can never masquerade as an egress IP.
_IPV4_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")

# University eduVPN egress lives in 145.0.0.0/8; a 34.x address means Chromium
# leaked onto the bare GCP egress (tunnel down).
_UNIVERSITY_PREFIX = "145."
_GCP_PREFIX = "34."


def parse_is_active(output: str) -> bool:
    """Return True only when ``systemctl is-active`` printed exactly ``active``.

    ``systemctl is-active`` prints ``inactive``/``failed``/``activating`` (and
    exits non-zero) for every non-running state, and prints nothing when the
    privileged call itself failed, so a strict equality check is the signal.
    """
    return output.strip() == "active"


def parse_latest_handshake_epoch(output: str) -> int | None:
    """Return the newest handshake epoch from ``wg ... latest-handshakes``.

    Each line is ``<pubkey>\\t<epoch_seconds>``; a peer that has never completed
    a handshake reports ``0``. Returns the largest non-zero epoch, or ``None``
    when no peer has ever handshaked (or the output is unparseable).
    """
    best: int | None = None
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        try:
            epoch = int(fields[-1])
        except ValueError:
            continue
        if epoch <= 0:
            continue
        if best is None or epoch > best:
            best = epoch
    return best


def handshake_age_seconds(output: str, now: float | None = None) -> float | None:
    """Age in seconds of the most recent WireGuard handshake, or ``None``.

    ``None`` means no handshake has ever completed (never connected) or the
    output could not be parsed. A future-dated epoch (clock skew) is clamped to
    ``0.0`` rather than returned negative.
    """
    epoch = parse_latest_handshake_epoch(output)
    if epoch is None:
        return None
    reference = time.time() if now is None else now
    return max(0.0, reference - float(epoch))


def extract_egress_ip(output: str) -> str | None:
    """Return a bare IPv4 egress address from proxied ``ifconfig.me`` output.

    Anything that is not a single dotted-quad with octets in 0-255 (an error
    page, an empty body, a proxy failure) yields ``None``.
    """
    candidate = output.strip()
    match = _IPV4_RE.match(candidate)
    if match is None:
        return None
    if any(int(octet) > 255 for octet in match.groups()):
        return None
    return candidate


def is_university_ip(ip: str | None) -> bool:
    """True when the egress IP is a university (145.x) address, not GCP (34.x).

    A missing IP is not a university IP. The explicit GCP guard documents the
    fail state even though a 34.x address can never also start with 145.
    """
    if not ip:
        return False
    if ip.startswith(_GCP_PREFIX):
        return False
    return ip.startswith(_UNIVERSITY_PREFIX)
