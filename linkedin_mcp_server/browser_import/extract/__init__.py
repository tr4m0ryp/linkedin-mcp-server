"""Copy a browser's Cookies database and decrypt its LinkedIn cookies.

Owns the locked-DB copy (with WAL/SHM sidecars), the SQLite read with column
drift, the version branch, OS keystore access (one injectable accessor per OS),
the PBKDF2 iteration count, and the platform-aware v20 app-bound skip.

Cryptographic constants are fixed by Chromium's cookie format:
- salt ``saltysalt``; AES-128-CBC for macOS/Linux; IV = 16 space bytes.
- PBKDF2-HMAC-SHA1, 1003 iterations on macOS, 1 iteration on Linux, dklen 16.
- v10/v11 prefixes are 3 bytes. Store version >= 24 prepends a 32-byte
  ``SHA256(host_key)`` digest inside the plaintext on every platform (decrypt
  -> unpad -> strip-32 for CBC; decrypt -> strip-32 for Windows GCM).
- Windows v10 cookies are AES-256-GCM under a DPAPI-protected master key.
- v20 is Chrome 127+ app-bound encryption and needs OS elevation; we skip it.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile

from linkedin_mcp_server.browser_import.discovery import (
    SUPPORTED_BROWSERS,
    BrowserProfile,
)
from linkedin_mcp_server.exceptions import (
    V20EncryptedError,
)

from .cookies_db import (
    _SAMESITE_MAP,
    _WINDOWS_EPOCH_OFFSET_SECONDS,
    LiAtMeta,
    LinkedInCookie,
    _chromium_utc_to_unix,
    _cookie_columns,
    _copy_cookies_db,
    _expires_to_unix,
    _meta_version,
)
from .crypto import (
    _CBC_IV,
    _HOST_KEY_PREFIX_LEN,
    _HOST_KEY_PREFIX_MIN_VERSION,
    _KEY_LENGTH,
    _LINUX_FALLBACK_PASSWORD,
    _LINUX_ITERATIONS,
    _MACOS_ITERATIONS,
    _SALT,
    _current_os,
    _decrypt_cbc,
    _decrypt_gcm_v10,
    _decrypt_value,
    _derive_cbc_key,
    _linux_safe_storage_password,
    _macos_safe_storage_password,
    _verify_host_key_prefix,
    _windows_master_key,
)

logger = logging.getLogger(__name__)


def _resolve_keystore(
    profile: BrowserProfile,
) -> tuple[bytes | None, bytes | None, bool]:
    """Return ``(cbc_key, win_master_key, is_mac_or_linux)``."""
    current = _current_os()
    if current == "macos":
        account = profile.mac_keychain_account or profile.safe_storage_label
        service = (
            profile.mac_keychain_service or f"{profile.safe_storage_label} Safe Storage"
        )
        password = _macos_safe_storage_password(account, service)
        return _derive_cbc_key(password, iterations=_MACOS_ITERATIONS), None, True
    if current == "windows":
        return None, _windows_master_key(profile.local_state_path), False
    spec = SUPPORTED_BROWSERS.get(profile.browser, {})
    app_token = (
        str(spec.get("linux_app_token", "")) or profile.safe_storage_label.lower()
    )
    password = _linux_safe_storage_password(app_token)
    return _derive_cbc_key(password, iterations=_LINUX_ITERATIONS), None, True


def extract_linkedin_cookies(profile: BrowserProfile) -> list[LinkedInCookie]:
    """Copy *profile*'s Cookies DB and return its decrypted LinkedIn cookies.

    Copies the DB (+ WAL/SHM) to a ``0o600``-hardened temp dir, opens it
    read-only (``mode=ro``, not ``immutable``, so the copied WAL is applied and a
    just-issued ``li_at`` still in the WAL is visible), reads ``meta.version`` and
    the secure/httponly columns,
    filters ``host_key`` in Python with the repo's ``"linkedin.com" in host_key``
    convention (no SQL ``LIKE`` interpolation), and decrypts each value.
    Skip-and-warn (by count) on :class:`V20EncryptedError` and on wrong-key
    ``SHA256(host_key)`` mismatch. Returns the FULL LinkedIn cookie set.

    Raises :class:`KeystoreUnavailableError` when the OS keystore is unavailable.
    """
    cbc_key, win_master_key, is_macos_or_linux = _resolve_keystore(profile)

    temp_dir, db_copy = _copy_cookies_db(profile.cookies_db)
    cookies: list[LinkedInCookie] = []
    skipped_app_bound = 0
    skipped_wrong_key = 0
    try:
        uri = f"file:{db_copy}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.row_factory = sqlite3.Row
            store_version = _meta_version(connection)
            cols = _cookie_columns(connection)
            query = (
                "SELECT host_key, name, encrypted_value, value, path, expires_utc, "
                f"{cols['secure']} AS secure_col, {cols['http_only']} AS httponly_col, "
                "samesite FROM cookies"
            )
            rows = connection.execute(query).fetchall()
        finally:
            connection.close()

        for row in rows:
            host_key = row["host_key"] or ""
            if "linkedin.com" not in host_key:
                continue
            blob = row["encrypted_value"] or b""
            plaintext_value = row["value"] or ""
            if (
                is_macos_or_linux
                and not plaintext_value
                and blob[:3] in (b"v10", b"v11")
                and store_version >= _HOST_KEY_PREFIX_MIN_VERSION
                and cbc_key is not None
                and not _verify_host_key_prefix(blob, cbc_key, host_key)
            ):
                skipped_wrong_key += 1
                continue
            try:
                value = _decrypt_value(
                    blob,
                    plaintext_value,
                    cbc_key=cbc_key,
                    win_master_key=win_master_key,
                    store_version=store_version,
                    is_macos_or_linux=is_macos_or_linux,
                )
            except V20EncryptedError:
                skipped_app_bound += 1
                continue
            except ValueError:
                # Wrong key / corrupt blob: PKCS7 unpad or GCM auth fails. On a
                # pre-v24 store the host-key precheck above does not run, so this
                # is the only guard. Skip the cookie instead of aborting.
                skipped_wrong_key += 1
                continue
            cookies.append(
                LinkedInCookie(
                    name=row["name"],
                    value=value,
                    domain=host_key,
                    path=row["path"] or "/",
                    expires=_expires_to_unix(row["expires_utc"] or 0),
                    secure=bool(row["secure_col"]),
                    http_only=bool(row["httponly_col"]),
                    same_site=_SAMESITE_MAP.get(row["samesite"], "Lax"),
                )
            )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    logger.info(
        "Extracted %d LinkedIn cookies from %s/%s (skipped %d app-bound, %d wrong-key)",
        len(cookies),
        profile.browser,
        profile.profile_dir_name,
        skipped_app_bound,
        skipped_wrong_key,
    )
    return cookies


def read_li_at_meta(profile: BrowserProfile) -> LiAtMeta | None:
    """Return *profile*'s ``li_at`` metadata, or ``None`` when there is no ``li_at``.

    Copies the Cookies DB the same way :func:`extract_linkedin_cookies` does, but
    reads only the plaintext columns (``expires_utc``, ``last_access_utc``) plus
    the encryption prefix. It never derives a key, so it works -- and stays
    silent on the keychain -- even when the keystore is unavailable.
    """
    temp_dir, db_copy = _copy_cookies_db(profile.cookies_db)
    try:
        connection = sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT host_key, name, encrypted_value, value, expires_utc, "
                "last_access_utc FROM cookies"
            ).fetchall()
        finally:
            connection.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    for row in rows:
        host_key = row["host_key"] or ""
        if "linkedin.com" not in host_key or row["name"] != "li_at":
            continue
        app_bound = not row["value"] and (row["encrypted_value"] or b"")[:3] == b"v20"
        return LiAtMeta(
            expires=_expires_to_unix(row["expires_utc"] or 0),
            last_access=_chromium_utc_to_unix(row["last_access_utc"] or 0),
            app_bound=app_bound,
        )
    return None


def has_undecryptable_li_at(profile: BrowserProfile) -> bool:
    """Return whether *profile* holds an ``li_at`` cookie that is app-bound (v20).

    Used to distinguish "logged in but undecryptable" from "no li_at".
    """
    meta = read_li_at_meta(profile)
    return meta is not None and meta.app_bound
