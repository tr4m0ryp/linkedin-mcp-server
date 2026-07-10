"""Runtime-aware authentication state for cross-platform profile reuse.

This package re-exports the full session-state public surface so that
``linkedin_mcp_server.session_state`` stays a stable import path.

Patch seams honored here:

* ``platform`` and ``Path`` are imported into this namespace so that
  ``session_state.platform.<attr>`` and ``session_state.Path.<attr>`` resolve.
  Both are shared singletons, so patching an attribute on them affects every
  submodule that uses them.
* ``get_runtime_id`` is patched at ``session_state.get_runtime_id``. Its only
  in-package caller, ``write_source_state``, is defined here so that its
  name lookup resolves against this (patched) namespace at call time.
"""

from __future__ import annotations

from dataclasses import asdict
import platform  # noqa: F401 -- patch seam for session_state.platform.<attr>
from pathlib import Path
from uuid import uuid4

from linkedin_mcp_server.common_utils import utcnow_iso

from .io import (
    _write_json,
    clear_auth_state,
    clear_runtime_profile,
    load_runtime_state,
    load_source_state,
    write_runtime_state,
)
from .paths import (
    RuntimeState,
    SourceState,
    auth_root_dir,
    get_source_profile_dir,
    portable_cookie_path,
    profile_exists,
    runtime_dir,
    runtime_profile_dir,
    runtime_profiles_root,
    runtime_state_path,
    runtime_storage_state_path,
    source_state_path,
)
from .runtime import get_runtime_id

__all__ = [
    "SourceState",
    "RuntimeState",
    "get_source_profile_dir",
    "auth_root_dir",
    "portable_cookie_path",
    "source_state_path",
    "runtime_profiles_root",
    "runtime_dir",
    "runtime_profile_dir",
    "runtime_state_path",
    "runtime_storage_state_path",
    "profile_exists",
    "get_runtime_id",
    "load_source_state",
    "write_source_state",
    "load_runtime_state",
    "write_runtime_state",
    "clear_runtime_profile",
    "clear_auth_state",
]


def write_source_state(
    source_profile_dir: Path | None = None,
    *,
    user_agent: str | None = None,
) -> SourceState:
    """Write a fresh source session generation after successful login."""
    profile_dir = (
        (source_profile_dir or get_source_profile_dir()).expanduser().resolve()
    )
    state = SourceState(
        version=1,
        source_runtime_id=get_runtime_id(),
        login_generation=str(uuid4()),
        created_at=utcnow_iso(),
        profile_path=str(profile_dir),
        cookies_path=str(portable_cookie_path(profile_dir)),
        user_agent=user_agent,
    )
    _write_json(source_state_path(profile_dir), asdict(state))
    return state
