"""Per-profile primitives: the ``BrowserProfile`` record, profile
enumeration inside one user-data root, and Cookies-database resolution.

Internal to the ``discovery`` package; the public names are re-exported
from ``discovery/__init__.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserProfile:
    """One discoverable browser profile with a resolvable Cookies database."""

    browser: str  # canonical registry key, see SUPPORTED_BROWSERS
    browser_label: str  # human label for TTY prompts: "Google Chrome"
    safe_storage_label: str  # macOS keychain service token: "Chrome", "Brave", ...
    profile_dir_name: str  # "Default" | "Profile 1" | ...
    display_name: str  # Local State info_cache "name" (TTY only, never logged)
    user_data_root: Path  # the dir containing "Local State"
    profile_path: Path  # user_data_root / profile_dir_name
    cookies_db: Path  # resolved Cookies path (Network/Cookies preferred, else Cookies)
    local_state_path: Path  # user_data_root / "Local State"
    # Full macOS keychain service name. Empty -> the default "<safe_storage>
    # Safe Storage" pattern. Set for forks that rename it (e.g. Helium uses
    # "Helium Storage Key", not the "... Safe Storage" suffix).
    mac_keychain_service: str = ""
    # macOS keychain ACCOUNT (-a). Stays the bare product name even when a fork
    # renames the SERVICE (e.g. Helium account "Helium" but service
    # "Helium Storage Key"). Empty -> defaults to safe_storage_label. The
    # account-first lookup is the primary key; mac_keychain_service is the
    # fallback.
    mac_keychain_account: str = ""
    # On-disk profile layout. "profiles" = standard Default/Profile N subdirs;
    # "flat" = cookies at the user-data root with no Default/ subdir (Opera and
    # Opera GX, see docs/browser-import-support.md).
    layout: str = "profiles"


def _read_info_cache(local_state_path: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(local_state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        return {}
    info_cache = profile.get("info_cache")
    if not isinstance(info_cache, dict):
        return {}
    return {k: v for k, v in info_cache.items() if isinstance(v, dict)}


def _glob_profile_dirs(user_data_root: Path) -> list[str]:
    """Fallback: dir-glob ``Default`` + ``Profile *`` with a ``Preferences`` file."""
    names: list[str] = []
    for candidate in (
        user_data_root / "Default",
        *sorted(user_data_root.glob("Profile *")),
    ):
        if candidate.is_dir() and (candidate / "Preferences").is_file():
            names.append(candidate.name)
    return names


def _flat_display_name(user_data_root: Path) -> str:
    """TTY label for a flat-layout (Opera) root that holds a single profile."""
    info_cache = _read_info_cache(user_data_root / "Local State")
    # Flat browsers still write a Default entry in info_cache when present.
    default = info_cache.get("Default") if info_cache else None
    name = default.get("name") if isinstance(default, dict) else None
    return name if isinstance(name, str) and name else user_data_root.name


def enumerate_profiles(
    user_data_root: Path, *, layout: str = "profiles"
) -> list[tuple[str, str]]:
    """Return ``(profile_dir_name, display_name)`` for real sign-in profiles.

    Parses ``<root>/Local State`` ``profile.info_cache``; skips ephemeral and
    the special ``Guest``/``System Profile`` directories. Falls back to globbing
    ``Default`` + ``Profile *`` dirs that contain a ``Preferences`` file when
    ``Local State`` is missing or corrupt.

    With ``layout="flat"`` (Opera) the user-data root itself is the single
    profile: cookies live at the root with no ``Default/`` subdir, represented
    by the ``"."`` profile_dir_name so ``root / "." == root`` resolves them.
    """
    if layout == "flat":
        return [(".", _flat_display_name(user_data_root))]

    skip = {"Guest Profile", "System Profile"}
    info_cache = _read_info_cache(user_data_root / "Local State")
    profiles: list[tuple[str, str]] = []

    if info_cache:
        for dir_name, info in sorted(info_cache.items()):
            if dir_name in skip:
                continue
            if info.get("is_ephemeral"):
                continue
            if not (user_data_root / dir_name).is_dir():
                continue
            raw_name = info.get("name")
            display = raw_name if isinstance(raw_name, str) and raw_name else dir_name
            profiles.append((dir_name, display))
        if profiles:
            return profiles

    # Local State missing/corrupt or held no usable profiles: glob the disk.
    return [(name, name) for name in _glob_profile_dirs(user_data_root)]


def resolve_cookies_db(profile_path: Path) -> Path | None:
    """Prefer ``<p>/Network/Cookies``, then ``<p>/Cookies``. ``None`` when neither.

    Never branches on browser or version: the Network-first probe is correct
    regardless of which on-disk layout a Chromium build uses.
    """
    network_cookies = profile_path / "Network" / "Cookies"
    if network_cookies.is_file():
        return network_cookies
    flat_cookies = profile_path / "Cookies"
    if flat_cookies.is_file():
        return flat_cookies
    return None
