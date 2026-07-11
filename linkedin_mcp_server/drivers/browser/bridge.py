"""Runtime-profile bridging and imported-cookie validation.

Splits the Docker-style foreign-runtime bridge, the existing-profile
re-authentication path, and the browser-import cookie validator out of the
package root to keep each file under the line cap. ``_make_browser`` and
``_launch_options`` live in the package root (they resolve the test-patched
``BrowserManager``/``get_config`` bindings there); ``_feed_auth_succeeds``
lives in the sibling ``feed_auth`` module. Both are imported here so the moved
functions can call them by bare name with byte-identical bodies.
"""

import logging
import os
from pathlib import Path

from linkedin_mcp_server.common_utils import (
    harden_linkedin_tree,
    secure_mkdir,
    utcnow_iso,
)
from linkedin_mcp_server.core import AuthenticationError, BrowserManager
from linkedin_mcp_server.debug_trace import record_page_trace
from linkedin_mcp_server.debug_utils import stabilize_navigation
from linkedin_mcp_server.drivers.browser import _launch_options, _make_browser
from linkedin_mcp_server.drivers.browser.feed_auth import _feed_auth_succeeds
from linkedin_mcp_server.session_state import (
    SourceState,
    clear_runtime_profile,
    get_source_profile_dir,
    runtime_storage_state_path,
    write_runtime_state,
)

logger = logging.getLogger(__name__)


def _debug_skip_checkpoint_restart() -> bool:
    """Return whether to keep the fresh bridged browser alive for this run."""
    return os.getenv("LINKEDIN_DEBUG_SKIP_CHECKPOINT_RESTART", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _debug_bridge_every_startup() -> bool:
    """Return whether to force a fresh bridge on every foreign-runtime startup."""
    return os.getenv("LINKEDIN_DEBUG_BRIDGE_EVERY_STARTUP", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def experimental_persist_derived_runtime() -> bool:
    """Return whether Docker-style foreign runtimes should reuse derived profiles."""
    return os.getenv(
        "LINKEDIN_EXPERIMENTAL_PERSIST_DERIVED_SESSION", ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _authenticate_existing_profile(
    profile_dir: Path,
    *,
    launch_options: dict[str, str],
    viewport: dict[str, int],
    user_agent: str | None = None,
) -> "BrowserManager":
    browser = _make_browser(
        profile_dir,
        launch_options=launch_options,
        viewport=viewport,
        user_agent=user_agent,
    )
    try:
        await browser.start()
        if not await _feed_auth_succeeds(browser):
            raise AuthenticationError(
                f"Stored runtime profile is invalid: {profile_dir}. Run with --login to refresh the source session."
            )
        browser.is_authenticated = True
        return browser
    except Exception:
        await browser.close()
        raise


async def validate_imported_cookies(
    cookie_path: Path, profile_dir: Path, *, user_agent: str | None = None
) -> bool:
    """Validate freshly imported cookies against /feed/ before persisting.

    Starts a headless browser on *profile_dir*, injects the LinkedIn cookies
    from *cookie_path*, and proves /feed/ with the same validator login and the
    Docker bridge use (``_feed_auth_succeeds``: remember-me resolution plus
    auth-barrier detection). Used only by the browser-import CLI path.
    *user_agent* is the source browser's synthesized UA — validating under the
    same UA the runtime will use keeps the proof representative.

    A local :class:`BrowserManager` is used (never the singleton), so
    ``close_browser()``'s export-on-close is not involved and cannot shrink
    ``cookies.json``. Injection routes through the existing ``import_cookies``
    with ``preset_name="bridge_core"`` (the largest existing preset); the
    on-disk ``cookies.json`` still holds the full superset for the Docker
    bridge. Always closes the browser in ``finally``.
    """
    launch_options, viewport = _launch_options()
    secure_mkdir(profile_dir)
    harden_linkedin_tree(profile_dir)
    browser = _make_browser(
        profile_dir,
        launch_options=launch_options,
        viewport=viewport,
        user_agent=user_agent,
    )
    try:
        await browser.start()
        await browser.page.goto(
            "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
        )
        await stabilize_navigation("import pre-validate feed navigation", logger)
        if not await browser.import_cookies(cookie_path, preset_name="bridge_core"):
            return False
        await stabilize_navigation("import cookie injection", logger)
        return await _feed_auth_succeeds(browser)
    finally:
        await browser.close()


async def _bridge_runtime_profile(
    profile_dir: Path,
    *,
    cookie_path: Path,
    source_state: SourceState,
    runtime_id: str,
    launch_options: dict[str, str],
    viewport: dict[str, int],
    persist_runtime: bool,
) -> "BrowserManager":
    source_profile_dir = get_source_profile_dir()
    bridge_started_at = utcnow_iso()
    clear_runtime_profile(runtime_id, source_profile_dir)
    secure_mkdir(profile_dir.parent)
    storage_state_path = runtime_storage_state_path(runtime_id, source_profile_dir)
    browser = _make_browser(
        profile_dir,
        launch_options=launch_options,
        viewport=viewport,
        user_agent=source_state.user_agent,
    )
    try:
        await browser.start()
        await record_page_trace(
            browser.page,
            "bridge-browser-started",
            extra={"profile_dir": str(profile_dir)},
        )
        await browser.page.goto(
            "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
        )
        await stabilize_navigation("pre-import feed navigation", logger)
        await record_page_trace(browser.page, "bridge-after-pre-import-feed")
        if not await browser.import_cookies(cookie_path):
            raise AuthenticationError(
                "Portable authentication could not be imported. Run with --login to create a fresh source session."
            )
        await stabilize_navigation("bridge cookie import", logger)
        await record_page_trace(
            browser.page,
            "bridge-after-cookie-import",
            extra={"cookie_path": str(cookie_path)},
        )
        if not await _feed_auth_succeeds(browser):
            raise AuthenticationError(
                "No authentication found. Run with --login to create a profile."
            )
        await stabilize_navigation("post-import feed validation", logger)
        await record_page_trace(browser.page, "bridge-after-feed-validation")
        if not persist_runtime:
            logger.info(
                "Foreign runtime %s authenticated via fresh bridge "
                "(derived runtime persistence disabled)",
                runtime_id,
            )
            browser.is_authenticated = True
            return browser
        if _debug_skip_checkpoint_restart():
            logger.warning(
                "Skipping checkpoint restart for derived runtime profile %s "
                "(LINKEDIN_DEBUG_SKIP_CHECKPOINT_RESTART enabled)",
                profile_dir,
            )
            browser.is_authenticated = True
            return browser
        if not await browser.export_storage_state(storage_state_path, indexed_db=True):
            raise AuthenticationError(
                "Derived runtime session could not be checkpointed. Run with --login to create a fresh source session."
            )
        await stabilize_navigation("runtime storage-state export", logger)
        logger.info("Checkpoint-restarting derived runtime profile %s", profile_dir)
        await browser.close()
        reopened = _make_browser(
            profile_dir,
            launch_options=launch_options,
            viewport=viewport,
            user_agent=source_state.user_agent,
        )
        try:
            await reopened.start()
            await stabilize_navigation("derived profile reopen", logger)
            await record_page_trace(
                reopened.page,
                "bridge-after-profile-reopen",
                extra={"profile_dir": str(profile_dir)},
            )
            if not await _feed_auth_succeeds(reopened):
                logger.warning(
                    "Stored derived runtime profile failed post-commit validation"
                )
                raise AuthenticationError(
                    "Derived runtime validation failed; no automatic re-bridge will be attempted. Run with --login to create a fresh source session."
                )
            await stabilize_navigation("post-reopen feed validation", logger)
            await record_page_trace(reopened.page, "bridge-after-reopen-validation")
            write_runtime_state(
                runtime_id,
                source_state,
                storage_state_path,
                source_profile_dir,
                created_at=bridge_started_at,
            )
            logger.info("Derived runtime profile committed for %s", runtime_id)
            reopened.is_authenticated = True
            return reopened
        except Exception:
            await reopened.close()
            raise
    except Exception:
        await browser.close()
        clear_runtime_profile(runtime_id, source_profile_dir)
        raise
