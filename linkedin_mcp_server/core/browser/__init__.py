"""Browser lifecycle management using Patchright with persistent context.

This package replaces the former single-module ``core/browser.py``. The
public surface -- ``BrowserManager`` and the module-level constants -- is
re-exported here unchanged, so ``linkedin_mcp_server.core.browser`` keeps
resolving exactly as before.
"""

from ._helpers import (
    _CLEANUP_TIMEOUT_SECONDS,
    _DEFAULT_USER_DATA_DIR,
    _PRIVATE_FILE_MODE,
)
from .manager import BrowserManager

__all__ = [
    "BrowserManager",
    "_CLEANUP_TIMEOUT_SECONDS",
    "_DEFAULT_USER_DATA_DIR",
    "_PRIVATE_FILE_MODE",
]
