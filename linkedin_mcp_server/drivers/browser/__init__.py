"""Patchright browser management for LinkedIn scraping.

Async BrowserManager lifecycle with a persistent-context singleton reused across
tool calls. This module holds singleton state, context building, the create/close
lifecycle, and profile/headless accessors; ``feed_auth``, ``bridge``, and
``session_checks`` hold the auth probe, bridging, and session validation,
re-exported below so ``drivers.browser.<name>`` is unchanged.
"""

import asyncio
import logging
from pathlib import Path

from linkedin_mcp_server.config import get_config
from linkedin_mcp_server.core import AuthenticationError, BrowserManager
from linkedin_mcp_server.session_state import (
    get_runtime_id,
    get_source_profile_dir,
    load_runtime_state,
    load_source_state,
    portable_cookie_path,
    profile_exists as session_profile_exists,
    runtime_profile_dir,
    runtime_storage_state_path,
)

logger = logging.getLogger(__name__)


# Default persistent profile directory; singleton browser state
DEFAULT_PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"
_browser: BrowserManager | None = None
_browser_cookie_export_path: Path | None = None
_headless: bool = True
# Serializes singleton creation: the startup background login flow can resume
# into this path and race the first tool call; an unguarded check-then-create
# would launch two browsers against the same profile.
_browser_create_lock = asyncio.Lock()


def _apply_browser_settings(browser: BrowserManager) -> None:
    """Apply configuration settings to browser instance."""
    config = get_config()
    browser.page.set_default_timeout(config.browser.default_timeout)


def _launch_options() -> tuple[dict[str, str], dict[str, int]]:
    config = get_config()
    viewport = {
        "width": config.browser.viewport_width,
        "height": config.browser.viewport_height,
    }
    launch_options: dict[str, str] = {}
    if config.browser.chrome_path:
        launch_options["executable_path"] = config.browser.chrome_path
        logger.info("Using custom Chrome path: %s", config.browser.chrome_path)
    return launch_options, viewport


def _make_browser(
    profile_dir: Path,
    *,
    launch_options: dict[str, str],
    viewport: dict[str, int],
    user_agent: str | None = None,
) -> BrowserManager:
    """Build a BrowserManager. An explicit USER_AGENT (env/CLI) always wins;
    *user_agent* is the session's own UA (the source browser's, recorded at
    import time) and applies only when no override is configured."""
    config = get_config()
    return BrowserManager(
        user_data_dir=profile_dir,
        headless=_headless,
        slow_mo=config.browser.slow_mo,
        user_agent=config.browser.user_agent or user_agent,
        viewport=viewport,
        **launch_options,
    )


async def get_or_create_browser(
    headless: bool | None = None,
) -> BrowserManager:
    """
    Get existing browser or create and initialize a new one.

    Uses a singleton pattern to reuse the browser across tool calls.
    Uses persistent context for automatic profile persistence.

    Args:
        headless: Run browser in headless mode. Defaults to config value.

    Returns:
        Initialized BrowserManager instance

    Raises:
        AuthenticationError: If no valid authentication found
    """
    global _headless

    if headless is not None:
        _headless = headless

    if _browser is not None:
        return _browser

    # Double-checked: only one concurrent caller may create the singleton.
    async with _browser_create_lock:
        if _browser is not None:
            return _browser
        return await _create_browser()


async def _create_browser() -> BrowserManager:
    """Create and initialize the singleton (caller holds _browser_create_lock)."""
    global _browser, _browser_cookie_export_path

    launch_options, viewport = _launch_options()
    source_profile_dir = get_profile_dir()
    cookie_path = portable_cookie_path(source_profile_dir)
    source_state = load_source_state(source_profile_dir)
    if (
        not source_state
        or not profile_exists(source_profile_dir)
        or not cookie_path.exists()
    ):
        raise AuthenticationError(
            "No source authentication found. Run with --login to create a profile."
        )

    current_runtime_id = get_runtime_id()

    if current_runtime_id == source_state.source_runtime_id:
        logger.info(
            "Using source profile for runtime %s (profile=%s)",
            current_runtime_id,
            source_profile_dir,
        )
        browser = await _authenticate_existing_profile(
            source_profile_dir,
            launch_options=launch_options,
            viewport=viewport,
            user_agent=source_state.user_agent,
        )
        _apply_browser_settings(browser)
        _browser = browser
        _browser_cookie_export_path = cookie_path
        return _browser

    persist_runtime = experimental_persist_derived_runtime()
    force_bridge = _debug_bridge_every_startup()

    if not persist_runtime:
        logger.info(
            "Using fresh bridge for foreign runtime %s "
            "(derived runtime persistence disabled by default)",
            current_runtime_id,
        )
        browser = await _bridge_runtime_profile(
            runtime_profile_dir(current_runtime_id, source_profile_dir),
            cookie_path=cookie_path,
            source_state=source_state,
            runtime_id=current_runtime_id,
            launch_options=launch_options,
            viewport=viewport,
            persist_runtime=False,
        )
        _apply_browser_settings(browser)
        _browser = browser
        _browser_cookie_export_path = None
        return _browser

    runtime_state = load_runtime_state(current_runtime_id, source_profile_dir)
    derived_profile_dir = runtime_profile_dir(current_runtime_id, source_profile_dir)
    storage_state_path = runtime_storage_state_path(
        current_runtime_id, source_profile_dir
    )
    generation_matches = (
        runtime_state is not None
        and runtime_state.source_login_generation == source_state.login_generation
    )
    if (
        not force_bridge
        and generation_matches
        and profile_exists(derived_profile_dir)
        and storage_state_path.exists()
    ):
        logger.info(
            "Using derived runtime profile for %s (profile=%s)",
            current_runtime_id,
            derived_profile_dir,
        )
        try:
            browser = await _authenticate_existing_profile(
                derived_profile_dir,
                launch_options=launch_options,
                viewport=viewport,
                user_agent=source_state.user_agent,
            )
            _apply_browser_settings(browser)
            _browser = browser
            _browser_cookie_export_path = None
            return _browser
        except AuthenticationError:
            logger.warning(
                "Derived runtime profile auth failed for %s; re-bridging from source cookies",
                current_runtime_id,
            )

    if force_bridge:
        logger.warning(
            "Forcing a fresh bridge for %s on every startup "
            "(LINKEDIN_DEBUG_BRIDGE_EVERY_STARTUP enabled)",
            current_runtime_id,
        )
    logger.info(
        "Deriving runtime profile for %s from source generation %s",
        current_runtime_id,
        source_state.login_generation,
    )
    browser = await _bridge_runtime_profile(
        derived_profile_dir,
        cookie_path=cookie_path,
        source_state=source_state,
        runtime_id=current_runtime_id,
        launch_options=launch_options,
        viewport=viewport,
        persist_runtime=True,
    )
    _apply_browser_settings(browser)
    _browser = browser
    _browser_cookie_export_path = None
    return _browser


async def close_browser() -> None:
    """Close the browser and cleanup resources."""
    global _browser, _browser_cookie_export_path

    browser = _browser
    cookie_export_path = _browser_cookie_export_path
    _browser = None
    _browser_cookie_export_path = None

    if browser is None:
        return

    logger.info("Closing browser...")
    if cookie_export_path is not None:
        try:
            await browser.export_cookies(cookie_export_path)
        except Exception:
            logger.debug("Cookie export on close skipped", exc_info=True)
    await browser.close()
    logger.info("Browser closed")


def get_profile_dir() -> Path:
    """Get the resolved profile directory from config."""
    return get_source_profile_dir()


def profile_exists(profile_dir: Path | None = None) -> bool:
    """Check if a persistent browser profile exists and is non-empty."""
    return session_profile_exists(profile_dir or get_profile_dir())


def set_headless(headless: bool) -> None:
    """Set headless mode for future browser creation."""
    global _headless
    _headless = headless


def current_headless() -> bool:
    """Return the headless mode future browser creation will use."""
    return _headless


def reset_browser_for_testing() -> None:
    """Reset global browser state for test isolation."""
    global _browser, _browser_cookie_export_path, _headless
    _browser = None
    _browser_cookie_export_path = None
    _headless = True


# Imported last: bridge imports _make_browser/_launch_options defined above.
from linkedin_mcp_server.drivers.browser.feed_auth import _feed_auth_succeeds  # noqa: E402
from linkedin_mcp_server.drivers.browser.bridge import (  # noqa: E402
    _authenticate_existing_profile,
    _bridge_runtime_profile,
    _debug_bridge_every_startup,
    experimental_persist_derived_runtime,
    validate_imported_cookies,
)
from linkedin_mcp_server.drivers.browser.session_checks import (  # noqa: E402
    check_rate_limit,
    ensure_authenticated,
    validate_session,
)
