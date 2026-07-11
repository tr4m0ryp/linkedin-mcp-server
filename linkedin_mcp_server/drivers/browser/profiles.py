"""Profile-directory accessors for the LinkedIn browser driver.

Thin wrappers over ``session_state`` profile resolution. Re-exported from the
package root so ``drivers.browser.get_profile_dir`` / ``.profile_exists`` resolve
unchanged (conftest patches the former on the package root).
"""

from pathlib import Path

from linkedin_mcp_server.session_state import (
    get_source_profile_dir,
    profile_exists as session_profile_exists,
)


def get_profile_dir() -> Path:
    """Get the resolved profile directory from config."""
    return get_source_profile_dir()


def profile_exists(profile_dir: Path | None = None) -> bool:
    """Check if a persistent browser profile exists and is non-empty."""
    return session_profile_exists(profile_dir or get_profile_dir())
