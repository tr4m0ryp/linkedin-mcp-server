"""Locate Chromium-family browsers and their profiles (pure file I/O).

No cryptography and no Playwright here: this module only finds where a
browser's user-data root lives, which profiles it holds, and where each
profile's Cookies database is. Classification is locale-independent --
it keys off directory names (``Default`` / ``Profile N`` are never localized)
and ``Local State`` JSON structure, never display strings.

Package layout (300-line file cap): ``browsers`` holds the
``SUPPORTED_BROWSERS`` registry and per-OS path helpers; ``profiles`` holds
``BrowserProfile`` plus profile enumeration and Cookies-DB resolution. The
traversal entry points ``browser_roots`` and ``discover_profiles`` are
defined HERE so that tests monkeypatching ``discovery._os_base_dirs`` and
``discovery.browser_roots`` keep affecting them.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .browsers import (
    SUPPORTED_BROWSERS,
    _has_local_state,
    _os_base_dirs,
    _subpaths_for,
)
from .profiles import (
    BrowserProfile,
    enumerate_profiles,
    resolve_cookies_db,
)

__all__ = [
    "SUPPORTED_BROWSERS",
    "BrowserProfile",
    "browser_roots",
    "discover_profiles",
    "enumerate_profiles",
    "resolve_cookies_db",
]

logger = logging.getLogger(__name__)


def browser_roots(browser: str | None = None) -> list[tuple[str, Path]]:
    """Return ``(browser_key, user_data_root)`` for installed roots on this OS.

    Restricts to *browser* when given. Globs sibling channel dirs (e.g.
    ``Chrome Beta``, ``Brave-Browser-Nightly``). Only returns roots that exist
    and contain a ``Local State`` file (so a stray empty dir is not treated as
    an install).
    """
    os_key, base_dirs = _os_base_dirs()
    keys = [browser] if browser else list(SUPPORTED_BROWSERS)
    roots: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    for key in keys:
        if key not in SUPPORTED_BROWSERS:
            continue
        for subpath in _subpaths_for(key, os_key):
            for base in base_dirs:
                exact = base / subpath
                candidates = [exact]
                # Sibling channels share the parent dir and a name prefix.
                parent = exact.parent
                if parent.is_dir():
                    prefix = exact.name
                    candidates.extend(
                        sorted(
                            p
                            for p in parent.glob(f"{prefix}*")
                            if p.is_dir() and p != exact
                        )
                    )
                for root in candidates:
                    resolved = root.resolve() if root.exists() else root
                    if resolved in seen:
                        continue
                    if root.is_dir() and _has_local_state(root):
                        seen.add(resolved)
                        roots.append((key, root))
    return roots


def discover_profiles(browser: str | None = None) -> list[BrowserProfile]:
    """Cross-product ``browser_roots()`` x ``enumerate_profiles()``.

    Keeps only profiles with a resolvable Cookies DB. Does not decrypt; ``li_at``
    candidacy is decided later during extraction.
    """
    discovered: list[BrowserProfile] = []
    for browser_key, root in browser_roots(browser):
        spec = SUPPORTED_BROWSERS[browser_key]
        layout = str(spec.get("layout", "profiles"))
        for dir_name, display_name in enumerate_profiles(root, layout=layout):
            profile_path = root / dir_name  # root / "." == root for flat layout
            cookies_db = resolve_cookies_db(profile_path)
            if cookies_db is None:
                continue
            discovered.append(
                BrowserProfile(
                    browser=browser_key,
                    browser_label=str(spec["label"]),
                    safe_storage_label=str(spec["safe_storage"]),
                    profile_dir_name=dir_name,
                    display_name=display_name,
                    user_data_root=root,
                    profile_path=profile_path,
                    cookies_db=cookies_db,
                    local_state_path=root / "Local State",
                    mac_keychain_service=str(spec.get("mac_keychain_service", "")),
                    mac_keychain_account=str(spec.get("mac_keychain_account", "")),
                    layout=layout,
                )
            )
    logger.debug(
        "Discovered %d browser profile(s)%s",
        len(discovered),
        f" for {browser}" if browser else "",
    )
    return discovered
