"""Key derivation, OS keystore accessors, and AES-CBC/GCM cookie decryption.

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

import base64
import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from linkedin_mcp_server.exceptions import (
    KeystoreUnavailableError,
    V20EncryptedError,
)

logger = logging.getLogger(__name__)

_SALT = b"saltysalt"
_CBC_IV = b" " * 16
_KEY_LENGTH = 16
_MACOS_ITERATIONS = 1003
_LINUX_ITERATIONS = 1
_HOST_KEY_PREFIX_LEN = 32  # SHA256(host_key) prepended for store version >= 24
_HOST_KEY_PREFIX_MIN_VERSION = 24
_LINUX_FALLBACK_PASSWORD = b"peanuts"


def _derive_cbc_key(password: bytes, *, iterations: int) -> bytes:
    """PBKDF2-HMAC-SHA1(password, salt='saltysalt', iterations, dklen=16).

    macOS callers pass ``iterations=1003``; Linux callers pass ``iterations=1``.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=_KEY_LENGTH,
        salt=_SALT,
        iterations=iterations,
    )
    return kdf.derive(password)


def _macos_safe_storage_password(account: str, service: str) -> bytes:
    """Read the macOS Safe Storage password from the login keychain.

    Queries by ACCOUNT first (``-a <account>``): the account stays the bare
    product name even when a Chromium fork renames the keychain SERVICE (Helium's
    account is "Helium" but its service is "Helium Storage Key"). Falls back to
    the precise account+service pair when the account-only match is absent. The
    returned base64-looking string is used VERBATIM as the PBKDF2 password (it is
    NOT base64-decoded). Raises :class:`KeystoreUnavailableError` only when both
    queries fail. Logs only the tokens, never the password.
    """
    queries = (
        ["security", "find-generic-password", "-a", account, "-w"],
        ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
    )
    last_returncode: int | None = None
    for argv in queries:
        try:
            result = subprocess.run(
                argv, capture_output=True, check=False, timeout=10.0
            )
        except subprocess.TimeoutExpired as exc:
            # macOS Tahoe can hang the keychain CLI indefinitely when the process
            # lost SecurityAgent context; check=False guards a non-zero exit, not
            # a hang. Bound it so the server never stalls on the first tool call.
            raise KeystoreUnavailableError(
                f"macOS keychain read for account {account!r} timed out"
            ) from exc
        except OSError as exc:
            raise KeystoreUnavailableError(
                f"Could not run the macOS security tool for {account!r}: {exc}"
            ) from exc
        if result.returncode == 0:
            # The keychain value is the base64 string itself, used as-is.
            return result.stdout.rstrip(b"\n")
        last_returncode = result.returncode
    raise KeystoreUnavailableError(
        f"macOS keychain has no Safe Storage key for account {account!r} / "
        f"service {service!r} (exit {last_returncode}; the browser may not have "
        "created it yet)."
    )


def _linux_safe_storage_password(app_token: str) -> bytes:
    """Read the Linux Secret Service password for ``app_token``, else ``peanuts``.

    ``app_token`` is the registry ``linux_app_token`` (e.g. "chrome", "chromium",
    "microsoft-edge"). A real keyring value yields v11 blobs; the ``peanuts``
    fallback yields v10.
    """
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "application", app_token],
            capture_output=True,
            check=False,
            timeout=10.0,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except subprocess.TimeoutExpired:
        # An absent gnome-keyring or an unresponsive D-Bus session can hang
        # secret-tool forever; bound it like the macOS keychain read so the
        # import never stalls the server, then fall back to peanuts.
        logger.debug("secret-tool timed out; using peanuts fallback")
    except OSError:
        logger.debug("secret-tool unavailable; using peanuts fallback")
    return _LINUX_FALLBACK_PASSWORD


def _windows_master_key(local_state_path: Path) -> bytes:  # pragma: no cover
    """Decrypt the Windows DPAPI-protected AES-256 master key from Local State.

    Reads ``os_crypt.encrypted_key`` (base64), strips the 5-byte ``DPAPI``
    prefix, then ``CryptUnprotectData`` via ctypes. Untested on CI (the dev/CI
    host is macOS); see the module docstring. Exercised only via mocked unit
    tests (constraint 6).
    """
    import ctypes
    import ctypes.wintypes
    import json

    payload = json.loads(local_state_path.read_text())
    encrypted_key = base64.b64decode(payload["os_crypt"]["encrypted_key"])
    if encrypted_key[:5] != b"DPAPI":
        raise KeystoreUnavailableError("Local State key lacks the DPAPI prefix")
    blob_in = encrypted_key[5:]

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buffer_in = ctypes.create_string_buffer(blob_in, len(blob_in))
    blob_in_struct = DATA_BLOB(len(blob_in), buffer_in)
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32  # ty: ignore[unresolved-attribute]
    kernel32 = ctypes.windll.kernel32  # ty: ignore[unresolved-attribute]
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in_struct),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise KeystoreUnavailableError("CryptUnprotectData failed for the master key")
    try:
        key = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
    return key


def _decrypt_cbc(blob: bytes, key: bytes, *, store_version: int) -> str:
    """Decrypt a v10/v11 macOS/Linux cookie blob.

    Strips the 3-byte tag, AES-128-CBC decrypts (IV = 16 spaces), PKCS7-unpads,
    then strips the leading 32-byte ``SHA256(host_key)`` digest when
    ``store_version >= 24`` (verified ordering: decrypt -> unpad -> strip-32).
    """
    ciphertext = blob[3:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(_CBC_IV)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    if store_version >= _HOST_KEY_PREFIX_MIN_VERSION:
        plaintext = plaintext[_HOST_KEY_PREFIX_LEN:]
    return plaintext.decode("utf-8", errors="replace")


def _decrypt_gcm_v10(blob: bytes, master_key: bytes, *, store_version: int) -> str:
    """Decrypt a Windows v10 AES-256-GCM cookie blob.

    Layout: ``b'v10' || nonce(12) || ciphertext || tag(16)``. Store version >= 24
    (Chrome ~130+) prepends a 32-byte ``SHA256(host_key)`` digest inside the
    decrypted plaintext on Windows too, so strip it like the CBC path does.
    Untested on CI (macOS host); mocked-only.
    """
    nonce = blob[3:15]
    ciphertext = blob[15:]
    plaintext = AESGCM(master_key).decrypt(nonce, ciphertext, None)
    if store_version >= _HOST_KEY_PREFIX_MIN_VERSION:
        plaintext = plaintext[_HOST_KEY_PREFIX_LEN:]
    return plaintext.decode("utf-8", errors="replace")


def _verify_host_key_prefix(blob: bytes, key: bytes, host_key: str) -> bool:
    """Return whether a v10/v11 CBC blob decrypts to the expected host-key digest.

    Used to detect a wrong Safe Storage password (e.g. the Linux ``peanuts``
    fallback against a keyring-encrypted store): on mismatch the caller skips
    the cookie instead of emitting garbage.
    """
    try:
        ciphertext = blob[3:]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(_CBC_IV)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
    except ValueError:
        return False
    expected = hashlib.sha256(host_key.encode("utf-8")).digest()
    return plaintext[:_HOST_KEY_PREFIX_LEN] == expected


def _decrypt_value(
    blob: bytes,
    plaintext_value: str,
    *,
    cbc_key: bytes | None,
    win_master_key: bytes | None,
    store_version: int,
    is_macos_or_linux: bool,
) -> str:
    """Decrypt one cookie value, branching on the 3-byte prefix.

    If ``plaintext_value`` is non-empty the cookie was never encrypted; return
    it. Otherwise: ``v10``/``v11`` -> CBC (mac/linux) or GCM (windows); ``v20``
    -> raise :class:`V20EncryptedError`. The v20 message is platform-aware and
    never asserts "Windows" on a macOS/Linux blob.
    """
    if plaintext_value:
        return plaintext_value
    if not blob:
        return ""
    prefix = blob[:3]
    if prefix == b"v20":
        if is_macos_or_linux:
            raise V20EncryptedError(
                "Cookie uses app-bound encryption (v20); decryption requires OS "
                "elevation and is not supported."
            )
        raise V20EncryptedError(
            "Cookie uses Chrome 127+ app-bound encryption (v20); decryption "
            "requires OS elevation and is not supported."
        )
    if prefix in (b"v10", b"v11"):
        if is_macos_or_linux:
            if cbc_key is None:
                raise KeystoreUnavailableError(
                    "No Safe Storage key available for CBC decryption"
                )
            return _decrypt_cbc(blob, cbc_key, store_version=store_version)
        if win_master_key is None:
            raise KeystoreUnavailableError(
                "No DPAPI master key available for GCM decryption"
            )
        return _decrypt_gcm_v10(blob, win_master_key, store_version=store_version)
    # Unknown prefix: treat as undecryptable rather than emit garbage.
    raise V20EncryptedError(f"Cookie uses an unsupported encryption prefix {prefix!r}")


def _current_os() -> str:
    """Return ``"macos"``, ``"windows"`` or ``"linux"`` for the running host.

    Single OS-detection seam so tests can select a decryption path without
    monkeypatching ``os.name`` (which would break ``pathlib`` on the dev host).
    """
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"
