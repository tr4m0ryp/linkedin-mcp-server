"""Session validation helpers layered on the browser singleton.

These call ``get_or_create_browser`` (defined in the package root) and the
LinkedIn auth/rate-limit probes. No test patches these names at the package
namespace, so they live here to keep the package root under the line cap.
"""

from linkedin_mcp_server.core import (
    AuthenticationError,
    detect_rate_limit,
    is_logged_in,
)
from linkedin_mcp_server.drivers.browser import get_or_create_browser


async def validate_session() -> bool:
    """
    Check whether startup authentication has already succeeded for this browser.

    Mid-session expiry is detected during real LinkedIn navigations and scraper
    auth checks rather than via a fresh login probe on every tool call.

    Returns:
        True if startup authentication succeeded for the current browser
    """
    browser = await get_or_create_browser()
    if browser.is_authenticated:
        return True
    return await is_logged_in(browser.page)


async def ensure_authenticated() -> None:
    """
    Confirm that the shared browser completed startup authentication.

    Raises:
        AuthenticationError: If no authenticated browser session is available
    """
    if not await validate_session():
        raise AuthenticationError("Session expired or invalid.")


async def check_rate_limit() -> None:
    """
    Proactively check for rate limiting.

    Should be called after navigation to detect if LinkedIn is blocking requests.

    Raises:
        RateLimitError: If rate limiting is detected
    """
    browser = await get_or_create_browser()
    await detect_rate_limit(browser.page)
