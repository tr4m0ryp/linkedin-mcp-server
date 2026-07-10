"""Browser lifecycle management using Patchright with persistent context."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

from linkedin_mcp_server.common_utils import (
    harden_linkedin_tree,
    secure_mkdir,
    secure_write_text,
)

from ..exceptions import NetworkError
from ._helpers import (
    _DEFAULT_USER_DATA_DIR,
    _PRIVATE_FILE_MODE,
    BRIDGE_COOKIE_PRESETS,
    build_context_options,
    close_context,
    normalize_cookie_domain,
    resolve_bridge_cookie_names,
    stop_playwright,
)

# Keep the pre-split logger name so existing logging config stays effective.
logger = logging.getLogger("linkedin_mcp_server.core.browser")


class BrowserManager:
    """Async context manager for Patchright browser with persistent profile.

    Session persistence is handled automatically by the persistent browser
    context -- all cookies, localStorage, and session state are retained in
    the ``user_data_dir`` between runs.
    """

    def __init__(
        self,
        user_data_dir: str | Path = _DEFAULT_USER_DATA_DIR,
        headless: bool = True,
        slow_mo: int = 0,
        viewport: dict[str, int] | None = None,
        user_agent: str | None = None,
        **launch_options: Any,
    ):
        self.user_data_dir = str(Path(user_data_dir).expanduser())
        self.headless = headless
        self.slow_mo = slow_mo
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.user_agent = user_agent
        self.launch_options = launch_options

        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._is_authenticated = False

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        await self.close()

    async def start(self) -> None:
        """Start Patchright and launch persistent browser context."""
        if self._context is not None:
            raise RuntimeError("Browser already started. Call close() first.")
        try:
            self._playwright = await async_playwright().start()

            secure_mkdir(Path(self.user_data_dir))
            harden_linkedin_tree(Path(self.user_data_dir))

            context_options = build_context_options(
                headless=self.headless,
                slow_mo=self.slow_mo,
                viewport=self.viewport,
                user_agent=self.user_agent,
                launch_options=self.launch_options,
            )

            self._context = await self._playwright.chromium.launch_persistent_context(
                self.user_data_dir,
                **context_options,
            )

            logger.info(
                "Persistent browser launched (headless=%s, user_data_dir=%s)",
                self.headless,
                self.user_data_dir,
            )

            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

            logger.info("Browser context and page ready")

        except Exception as e:
            await self.close()
            raise NetworkError(f"Failed to start browser: {e}") from e

    async def close(self) -> None:
        """Close persistent context and cleanup resources."""
        context = self._context
        playwright = self._playwright
        self._context = None
        self._page = None
        self._playwright = None

        if context is None and playwright is None:
            return

        # Timeout-bounded cleanup lives in _helpers; see the comment there on
        # why each step must be bounded (wedged Chromium can hang forever).
        if context is not None:
            await close_context(context)

        if playwright is not None:
            await stop_playwright(playwright)

        logger.info("Browser closed")

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError(
                "Browser not started. Use async context manager or call start()."
            )
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Browser context not initialized.")
        return self._context

    async def set_cookie(
        self, name: str, value: str, domain: str = ".linkedin.com"
    ) -> None:
        if not self._context:
            raise RuntimeError("No browser context")

        await self._context.add_cookies(
            [{"name": name, "value": value, "domain": domain, "path": "/"}]
        )
        logger.debug("Cookie set: %s", name)

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    @is_authenticated.setter
    def is_authenticated(self, value: bool) -> None:
        self._is_authenticated = value

    def _default_cookie_path(self) -> Path:
        return Path(self.user_data_dir).parent / "cookies.json"

    @staticmethod
    def _normalize_cookie_domain(cookie: Any) -> dict[str, Any]:
        """Normalize cookie domain; see :func:`_helpers.normalize_cookie_domain`."""
        return normalize_cookie_domain(cookie)

    async def export_cookies(self, cookie_path: str | Path | None = None) -> bool:
        """Export LinkedIn cookies to a portable JSON file."""
        if not self._context:
            logger.warning("Cannot export cookies: no browser context")
            return False

        path = Path(cookie_path) if cookie_path else self._default_cookie_path()
        try:
            all_cookies = await self._context.cookies()
            cookies = [
                self._normalize_cookie_domain(c)
                for c in all_cookies
                if "linkedin.com" in c.get("domain", "")
            ]
            secure_mkdir(path.parent)
            harden_linkedin_tree(path.parent)
            secure_write_text(
                path, json.dumps(cookies, indent=2), mode=_PRIVATE_FILE_MODE
            )
            logger.info("Exported %d LinkedIn cookies to %s", len(cookies), path)
            return True
        except Exception:
            logger.exception("Failed to export cookies")
            return False

    async def export_storage_state(
        self, path: str | Path, *, indexed_db: bool = True
    ) -> bool:
        """Export the current browser storage state for diagnostics and recovery."""
        if not self._context:
            logger.warning("Cannot export storage state: no browser context")
            return False

        storage_path = Path(path)
        secure_mkdir(storage_path.parent)
        harden_linkedin_tree(storage_path.parent)
        try:
            await self._context.storage_state(
                path=storage_path,
                indexed_db=indexed_db,
            )
            # Playwright writes the file with default umask; tighten it.
            if os.name != "nt" and storage_path.exists():
                storage_path.chmod(_PRIVATE_FILE_MODE)
            logger.info(
                "Exported runtime storage snapshot to %s (indexed_db=%s)",
                storage_path,
                indexed_db,
            )
            return True
        except Exception:
            logger.exception("Failed to export storage state to %s", storage_path)
            return False

    # Class attribute so subclass overrides still resolve via ``cls`` as before.
    _BRIDGE_COOKIE_PRESETS = BRIDGE_COOKIE_PRESETS

    @classmethod
    def _bridge_cookie_names(
        cls, preset_name: str | None = None
    ) -> tuple[str, frozenset[str]]:
        return resolve_bridge_cookie_names(cls._BRIDGE_COOKIE_PRESETS, preset_name)

    async def import_cookies(
        self,
        cookie_path: str | Path | None = None,
        *,
        preset_name: str | None = None,
    ) -> bool:
        """Import the portable LinkedIn bridge cookie subset.

        Fresh browser-side cookies are preserved. The imported subset is the
        smallest known set that can reconstruct a usable authenticated page in
        a fresh profile.
        """
        if not self._context:
            logger.warning("Cannot import cookies: no browser context")
            return False

        path = Path(cookie_path) if cookie_path else self._default_cookie_path()
        if not path.exists():
            logger.debug("No portable cookie file at %s", path)
            return False

        try:
            all_cookies = json.loads(path.read_text())
            if not all_cookies:
                logger.debug("Cookie file is empty")
                return False

            resolved_preset_name, bridge_cookie_names = self._bridge_cookie_names(
                preset_name
            )

            cookies = [
                self._normalize_cookie_domain(c)
                for c in all_cookies
                if "linkedin.com" in c.get("domain", "")
                and c.get("name") in bridge_cookie_names
            ]

            has_li_at = any(c.get("name") == "li_at" for c in cookies)
            if not has_li_at:
                logger.warning("No li_at cookie found in %s", path)
                return False

            await self._context.add_cookies(
                cookies  # ty: ignore[invalid-argument-type]
            )
            logger.info(
                "Imported %d LinkedIn bridge cookies from %s (preset=%s, li_at=%s): %s",
                len(cookies),
                path,
                resolved_preset_name,
                has_li_at,
                ", ".join(c["name"] for c in cookies),
            )
            return True
        except Exception:
            logger.exception("Failed to import cookies from %s", path)
            return False

    def cookie_file_exists(self, cookie_path: str | Path | None = None) -> bool:
        """Check if a portable cookie file exists."""
        path = Path(cookie_path) if cookie_path else self._default_cookie_path()
        return path.exists()
