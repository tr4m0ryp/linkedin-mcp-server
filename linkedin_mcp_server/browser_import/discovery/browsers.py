"""Supported-browser registry and per-OS user-data path logic.

Internal to the ``discovery`` package. The traversal entry points
(``browser_roots``/``discover_profiles``) live in ``discovery/__init__.py``
so that monkeypatching ``discovery._os_base_dirs`` keeps working.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

# canonical_key -> per-OS layout. ``safe_storage`` is the macOS keychain service
# token (``<safe_storage> Safe Storage``); it is a distinct token from both the
# canonical key and the human label. Subpaths are relative to the per-OS base
# directory resolved in ``_os_base_dirs``.
#
# ``chromium_versioned`` marks browsers whose on-disk version string leads with
# the Chromium engine major (Chrome/Chromium/Edge/Arc report it directly, Brave
# prefixes it, Helium tracks upstream) — the input user_agent.py needs to
# synthesize the frozen UA for an imported session. Browsers that version
# independently of the engine (Opera, Vivaldi, Yandex, Whale, Cốc Cốc) omit it
# and get no synthesized UA. ``ua_brand_suffix`` is the extra brand token some
# forks append to the frozen UA (Edge: ``Edg/<major>.0.0.0``).
SUPPORTED_BROWSERS: dict[str, dict[str, object]] = {
    "chrome": {
        "label": "Google Chrome",
        "safe_storage": "Chrome",
        "mac_subpath": "Google/Chrome",
        "linux_subpaths": ("google-chrome",),
        "linux_app_token": "chrome",
        "win_subpath": "Google/Chrome/User Data",
        "chromium_versioned": True,
    },
    "chromium": {
        "label": "Chromium",
        "safe_storage": "Chromium",
        "mac_subpath": "Chromium",
        "linux_subpaths": ("chromium",),
        "linux_app_token": "chromium",
        "win_subpath": "Chromium/User Data",
        "chromium_versioned": True,
    },
    "brave": {
        "label": "Brave",
        "safe_storage": "Brave",
        "mac_subpath": "BraveSoftware/Brave-Browser",
        "linux_subpaths": ("BraveSoftware/Brave-Browser",),
        "linux_app_token": "brave",
        "win_subpath": "BraveSoftware/Brave-Browser/User Data",
        "chromium_versioned": True,
    },
    "edge": {
        "label": "Microsoft Edge",
        "safe_storage": "Microsoft Edge",
        "mac_subpath": "Microsoft Edge",
        "linux_subpaths": ("microsoft-edge",),
        "linux_app_token": "microsoft-edge",
        "win_subpath": "Microsoft/Edge/User Data",
        "chromium_versioned": True,
        "ua_brand_suffix": "Edg",
    },
    "arc": {
        "label": "Arc",
        "safe_storage": "Arc",
        "mac_subpath": "Arc/User Data",
        # Arc has no stable Linux build; omit on Linux.
        "linux_subpaths": (),
        "win_subpath": "Arc/User Data",
        "chromium_versioned": True,
    },
    "vivaldi": {
        "label": "Vivaldi",
        "safe_storage": "Vivaldi",
        "mac_subpath": "Vivaldi",
        "linux_subpaths": ("vivaldi",),
        "linux_app_token": "vivaldi",
        "win_subpath": "Vivaldi/User Data",
    },
    # Helium (imput.net): standard Chromium layout verified on macOS
    # (~/Library/Application Support/net.imput.helium, flat Default/Cookies,
    # multiple profiles). The keychain token is created on first cookie
    # encryption; "Helium" is the product name. No Linux build today.
    "helium": {
        "label": "Helium",
        "safe_storage": "Helium",
        # Helium renames the keychain item via change-keychain-name.patch:
        # service "Helium Storage Key" (NOT "Helium Safe Storage"), account
        # "Helium". Verified against imputnet/helium-macos.
        "mac_keychain_service": "Helium Storage Key",
        "mac_subpath": "net.imput.helium",
        "linux_subpaths": (),
        "win_subpath": "net.imput.helium/User Data",
        "chromium_versioned": True,
    },
    # Standard-Chromium browsers. Paths and keychain labels cross-checked against
    # yt-dlp (yt_dlp/cookies.py) and HackBrowserData (browser/browser_darwin.go):
    # both use the standard "<label> Safe Storage" service. A wrong token still
    # fails closed (KeystoreUnavailableError -> "undecryptable"), and a root
    # without a Local State file is never treated as installed.
    # See docs/browser-import-support.md.
    "yandex": {
        "label": "Yandex",
        "safe_storage": "Yandex",
        "mac_subpath": "Yandex/YandexBrowser",
        "linux_subpaths": ("yandex-browser",),
        "linux_app_token": "yandex-browser",
        "win_subpath": "Yandex/YandexBrowser/User Data",
    },
    "whale": {
        "label": "Naver Whale",
        "safe_storage": "Whale",
        "mac_subpath": "Naver/Whale",
        "linux_subpaths": ("naver-whale",),
        "linux_app_token": "naver-whale",
        "win_subpath": "Naver/Naver Whale/User Data",
    },
    "coccoc": {
        "label": "Cốc Cốc",
        "safe_storage": "CocCoc",  # macOS keychain service is "CocCoc Safe Storage"
        # dir leaf "Coccoc" (lowercase c's) vs keychain label "CocCoc" (camel) is
        # intentional; cross-checked against HackBrowserData browser_darwin.go.
        "mac_subpath": "Coccoc",
        "linux_subpaths": (),  # no verified Linux build in the sources
        "linux_app_token": "",  # unused (no Linux build)
        "win_subpath": "CocCoc/Browser/User Data",
    },
    # Opera / Opera GX: flat layout (cookies at the user-data ROOT, no Default/
    # subdir). Local State still sits at the root, so the install gate is
    # unchanged. macOS keychain account "Opera" for BOTH (cross-checked:
    # HackBrowserData browser_darwin.go KeychainLabel "Opera", yt-dlp
    # cookies.py keyring_name "Opera"). Windows path is under %APPDATA%
    # (Roaming), which _os_base_dirs already searches. No Opera GX Linux build.
    "opera": {
        "label": "Opera",
        "safe_storage": "Opera",
        "mac_subpath": "com.operasoftware.Opera",
        "linux_subpaths": ("opera",),
        "linux_app_token": "opera",
        "win_subpath": "Opera Software/Opera Stable",
        "layout": "flat",
    },
    "opera_gx": {
        "label": "Opera GX",
        "safe_storage": "Opera",  # GX shares the "Opera" keychain account/label
        "mac_subpath": "com.operasoftware.OperaGX",
        "linux_subpaths": (),  # no Opera GX build on Linux
        "linux_app_token": "",
        "win_subpath": "Opera Software/Opera GX Stable",
        "layout": "flat",
    },
}


def _os_base_dirs() -> tuple[str, list[Path]]:
    """Return the current OS key and the base directories browsers live under."""
    if sys.platform == "darwin":
        return "mac", [Path.home() / "Library" / "Application Support"]
    if os.name == "nt":
        bases: list[Path] = []
        for env_var in ("LOCALAPPDATA", "APPDATA"):
            value = os.environ.get(env_var)
            if value:
                bases.append(Path(value))
        return "win", bases
    # Default to Linux/XDG layout.
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return "linux", [base]


def _subpaths_for(browser: str, os_key: str) -> tuple[str, ...]:
    spec = SUPPORTED_BROWSERS[browser]
    if os_key == "mac":
        return (str(spec["mac_subpath"]),)
    if os_key == "win":
        return (str(spec["win_subpath"]),)
    linux_subpaths = cast("tuple[str, ...]", spec["linux_subpaths"])
    return tuple(str(p) for p in linux_subpaths)


def _has_local_state(root: Path) -> bool:
    return (root / "Local State").is_file()
