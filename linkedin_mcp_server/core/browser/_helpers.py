"""Module-level helpers backing :class:`BrowserManager`.

Constants, cookie utilities, context-option building, and bounded cleanup
extracted verbatim from the former single-module ``core/browser.py`` so the
manager module stays under the per-file size cap. Behavior is unchanged.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from patchright.async_api import BrowserContext, Playwright

# Preserve the pre-split logger name so logging configuration (and log-record
# names) targeting ``linkedin_mcp_server.core.browser`` keep working unchanged.
logger = logging.getLogger("linkedin_mcp_server.core.browser")

_DEFAULT_USER_DATA_DIR = Path.home() / ".linkedin-mcp" / "profile"
_PRIVATE_FILE_MODE = 0o600
_CLEANUP_TIMEOUT_SECONDS = 10

BRIDGE_COOKIE_PRESETS: dict[str, frozenset[str]] = {
    "bridge_core": frozenset(
        {
            "li_at",
            "li_rm",
            "JSESSIONID",
            "bcookie",
            "bscookie",
            "liap",
            "lidc",
            "li_gc",
            "lang",
            "timezone",
            "li_mc",
        }
    ),
    "auth_minimal": frozenset(
        {
            "li_at",
            "JSESSIONID",
            "bcookie",
            "bscookie",
            "lidc",
        }
    ),
}


def build_proxy_options() -> dict[str, Any] | None:
    """Build Patchright/Playwright ``proxy=`` options from the environment.

    Returns ``None`` (browser connects directly) unless ``LINKEDIN_PROXY_SERVER``
    is set, e.g. ``http://host:port`` or ``socks5://host:port``. Optional
    ``LINKEDIN_PROXY_USERNAME`` / ``LINKEDIN_PROXY_PASSWORD`` add authentication.
    """
    server = os.getenv("LINKEDIN_PROXY_SERVER", "").strip()
    if not server:
        return None

    proxy: dict[str, Any] = {"server": server}
    username = os.getenv("LINKEDIN_PROXY_USERNAME", "").strip()
    password = os.getenv("LINKEDIN_PROXY_PASSWORD", "")
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password
    return proxy


def build_context_options(
    *,
    headless: bool,
    slow_mo: int,
    viewport: dict[str, int],
    user_agent: str | None,
    launch_options: dict[str, Any],
) -> dict[str, Any]:
    """Build keyword options for ``launch_persistent_context``.

    ``launch_options`` may override everything except ``locale``;
    ``user_agent`` (when set) is applied last and wins. An HTTP/SOCKS proxy is
    added from ``LINKEDIN_PROXY_SERVER`` (see :func:`build_proxy_options`) unless
    ``launch_options`` already carries an explicit ``proxy``.
    """
    context_options: dict[str, Any] = {
        "headless": headless,
        "slow_mo": slow_mo,
        "viewport": viewport,
        **launch_options,
        "locale": "en-US",
    }

    if user_agent:
        context_options["user_agent"] = user_agent

    if "proxy" not in context_options:
        proxy = build_proxy_options()
        if proxy is not None:
            context_options["proxy"] = proxy
            logger.info("Routing browser through proxy %s", proxy["server"])

    return context_options


def normalize_cookie_domain(cookie: Any) -> dict[str, Any]:
    """Normalize cookie domain for cross-platform compatibility.

    Playwright reports some LinkedIn cookies with ``.www.linkedin.com``
    domain, but Chromium's internal store uses ``.linkedin.com``.
    """
    domain = cookie.get("domain", "")
    if domain in (".www.linkedin.com", "www.linkedin.com"):
        cookie = {**cookie, "domain": ".linkedin.com"}
    return cookie


def resolve_bridge_cookie_names(
    presets: dict[str, frozenset[str]],
    preset_name: str | None = None,
) -> tuple[str, frozenset[str]]:
    """Resolve the bridge-cookie preset name and its cookie-name set."""
    preset_name = (
        preset_name
        or os.getenv(
            "LINKEDIN_DEBUG_BRIDGE_COOKIE_SET",
            "auth_minimal",
        ).strip()
        or "auth_minimal"
    )
    preset = presets.get(preset_name)
    if preset is None:
        logger.warning(
            "Unknown LINKEDIN_DEBUG_BRIDGE_COOKIE_SET=%r, falling back to auth_minimal",
            preset_name,
        )
        preset_name = "auth_minimal"
        preset = presets[preset_name]
    return preset_name, preset


# Bound each cleanup step. A wedged Chromium (stale SingletonLock, sandbox
# stall, X-less host) can hang context.close() / playwright.stop()
# indefinitely; without these timeouts a caller that cancels
# BrowserManager.close() (e.g. asyncio.wait_for on the auto-import) would
# block past its own budget while awaiting the hung cleanup.


async def close_context(context: BrowserContext) -> None:
    """Close a browser context, bounded by ``_CLEANUP_TIMEOUT_SECONDS``."""
    try:
        await asyncio.wait_for(context.close(), timeout=_CLEANUP_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.error(
            "Timed out closing browser context after %ss",
            _CLEANUP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.error("Error closing browser context: %s", exc)


async def stop_playwright(playwright: Playwright) -> None:
    """Stop the Playwright driver, bounded by ``_CLEANUP_TIMEOUT_SECONDS``."""
    try:
        await asyncio.wait_for(playwright.stop(), timeout=_CLEANUP_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.error(
            "Timed out stopping playwright after %ss",
            _CLEANUP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.error("Error stopping playwright: %s", exc)
