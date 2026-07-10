"""SQLite Cookies-DB copy and plaintext row reading.

Owns the locked-DB copy (with WAL/SHM sidecars), the secure/httponly column
drift resolution, the ``meta.version`` read, the Chromium timestamp helpers, the
``LinkedInCookie``/``LiAtMeta`` dataclasses, and the SQLite samesite mapping.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

# SQLite samesite int -> Playwright string. -1 (UNSPECIFIED) maps to Chromium's
# default of Lax. Documented and unit-tested.
_SAMESITE_MAP = {-1: "Lax", 0: "None", 1: "Lax", 2: "Strict"}

# Windows epoch offset: Chromium stores expires_utc as microseconds since
# 1601-01-01; subtract this many seconds to reach the unix epoch.
_WINDOWS_EPOCH_OFFSET_SECONDS = 11_644_473_600


@dataclass(frozen=True)
class LinkedInCookie:
    """A single decrypted LinkedIn cookie ready for Playwright injection."""

    name: str
    value: str  # decrypted plaintext (NEVER logged)
    domain: str
    path: str
    expires: float  # unix seconds; -1 for session cookies (Playwright sentinel)
    secure: bool
    http_only: bool
    same_site: str  # "Strict" | "Lax" | "None"

    def to_playwright(self) -> dict[str, object]:
        """Return the Playwright ``add_cookies`` shape.

        Domain is normalized so the existing ``_normalize_cookie_domain`` pass is
        a no-op. ``sameSite`` is always one of {"Strict", "Lax", "None"};
        ``expires`` is a float (or the -1 session sentinel).
        """
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "expires": self.expires,
            "secure": self.secure,
            "httpOnly": self.http_only,
            "sameSite": self.same_site,
        }


def _cookie_columns(connection: sqlite3.Connection) -> dict[str, str]:
    """Resolve secure/httponly column names across SQLite schema drift."""
    cursor = connection.execute("PRAGMA table_info(cookies)")
    columns = {row[1] for row in cursor.fetchall()}
    secure = "is_secure" if "is_secure" in columns else "secure"
    http_only = "is_httponly" if "is_httponly" in columns else "httponly"
    return {"secure": secure, "http_only": http_only}


def _meta_version(connection: sqlite3.Connection) -> int:
    try:
        cursor = connection.execute("SELECT value FROM meta WHERE key='version'")
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except (sqlite3.Error, ValueError):
        return 0


def _chromium_utc_to_unix(value: int) -> float:
    """Convert a Chromium microseconds-since-1601 timestamp to unix seconds.

    Returns 0.0 for a 0 input (the "never" sentinel for ``last_access_utc`` and
    friends). Callers that need the session-cookie semantics for ``expires_utc``
    use :func:`_expires_to_unix` instead.
    """
    if value == 0:
        return 0.0
    return value / 1_000_000 - _WINDOWS_EPOCH_OFFSET_SECONDS


def _expires_to_unix(expires_utc: int) -> float:
    """Convert Chromium ``expires_utc`` microseconds to unix seconds.

    A value of 0 marks a session cookie -> the Playwright -1 sentinel. The 0
    value must not be run through the offset (that yields an already-expired
    cookie Playwright drops).
    """
    if expires_utc == 0:
        return -1.0
    return _chromium_utc_to_unix(expires_utc)


def _copy_cookies_db(cookies_db: Path) -> tuple[Path, Path]:
    """Copy the Cookies DB and its WAL/SHM sidecars into a hardened temp dir.

    Returns ``(temp_dir, db_copy)``. The caller removes ``temp_dir`` in a
    ``finally`` block. WAL/SHM are copied so a just-issued ``li_at`` that is
    committed but not yet checkpointed is visible. The live DB is never opened.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="linkedin-cookie-import-"))
    try:
        try:
            os.chmod(temp_dir, 0o700)
        except OSError:
            pass
        db_copy = temp_dir / "Cookies"
        shutil.copy2(cookies_db, db_copy)
        os.chmod(db_copy, 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = cookies_db.with_name(cookies_db.name + suffix)
            if sidecar.is_file():
                sidecar_copy = temp_dir / (db_copy.name + suffix)
                shutil.copy2(sidecar, sidecar_copy)
                os.chmod(sidecar_copy, 0o600)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return temp_dir, db_copy


@dataclass(frozen=True)
class LiAtMeta:
    """Keychain-free metadata about a profile's ``li_at`` cookie.

    Read from the plaintext SQLite columns only (no value decryption, so no OS
    keystore access and no keychain prompt). Used to filter expired/logged-out
    sessions and to rank live ones by recency *before* paying for decryption.
    """

    expires: float  # unix seconds; -1.0 for a session cookie (no expiry)
    last_access: float  # unix seconds; 0.0 if never sent
    app_bound: bool  # encrypted_value is v20 (undecryptable without OS elevation)
