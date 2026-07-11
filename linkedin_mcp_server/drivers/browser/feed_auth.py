"""Feed-based authentication probing for the LinkedIn browser driver.

Proves that ``/feed/`` loads without an auth barrier, resolving remember-me
prompts and logging failure context. Kept in its own module so the singleton
lifecycle package stays under the per-file line cap; the probe's cross-cutting
dependencies (``detect_auth_barrier_quick``, ``resolve_remember_me_prompt``,
``record_page_trace``) are imported here and resolved in this namespace.
"""

import logging

from linkedin_mcp_server.core import (
    BrowserManager,
    detect_auth_barrier_quick,
    resolve_remember_me_prompt,
)
from linkedin_mcp_server.debug_trace import record_page_trace
from linkedin_mcp_server.debug_utils import stabilize_navigation

logger = logging.getLogger(__name__)


async def _log_feed_failure_context(
    browser: BrowserManager,
    reason: str,
    exc: Exception | None = None,
) -> None:
    """Log the page state when /feed/ validation fails."""
    page = browser.page

    try:
        title = await page.title()
    except Exception:
        title = ""

    try:
        remember_me = (await page.locator("#rememberme-div").count()) > 0
    except Exception:
        remember_me = False

    try:
        body_text = await page.evaluate("() => document.body?.innerText || ''")
    except Exception:
        body_text = ""

    if not isinstance(body_text, str):
        body_text = ""

    logger.warning(
        "Feed auth check failed on %s: %s title=%r remember_me=%s body_marker=%r",
        page.url,
        reason,
        title,
        remember_me,
        " ".join(body_text.split())[:200],
        exc_info=exc,
    )


async def _feed_auth_succeeds(
    browser: BrowserManager,
    *,
    allow_remember_me: bool = True,
) -> bool:
    """Validate that /feed/ loads without an auth barrier."""
    try:
        await browser.page.goto(
            "https://www.linkedin.com/feed/",
            wait_until="domcontentloaded",
        )
        await stabilize_navigation("feed navigation", logger)
        await record_page_trace(
            browser.page,
            "feed-after-goto",
            extra={"allow_remember_me": allow_remember_me},
        )
        if allow_remember_me:
            if await resolve_remember_me_prompt(browser.page):
                await stabilize_navigation("remember-me resolution", logger)
                await record_page_trace(
                    browser.page,
                    "feed-after-remember-me",
                    extra={"allow_remember_me": allow_remember_me},
                )
                return await _feed_auth_succeeds(browser, allow_remember_me=False)
        barrier = await detect_auth_barrier_quick(browser.page)
        if barrier is not None:
            await record_page_trace(
                browser.page,
                "feed-auth-barrier",
                extra={"barrier": barrier},
            )
            await _log_feed_failure_context(browser, barrier)
            return False
        return True
    except Exception as exc:
        if allow_remember_me and await resolve_remember_me_prompt(browser.page):
            await stabilize_navigation(
                "remember-me resolution after feed failure", logger
            )
            await record_page_trace(
                browser.page,
                "feed-after-remember-me-error-recovery",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return await _feed_auth_succeeds(browser, allow_remember_me=False)
        await record_page_trace(
            browser.page,
            "feed-navigation-error",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        await _log_feed_failure_context(browser, str(exc), exc)
        return False
