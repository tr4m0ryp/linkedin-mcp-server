"""Load, write, and clear source/runtime auth state on disk."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import shutil
from typing import Any

from linkedin_mcp_server.common_utils import secure_write_text, utcnow_iso

from .paths import (
    _RUNTIME_STATE_FIELDS,
    _SOURCE_STATE_FIELDS,
    RuntimeState,
    SourceState,
    get_source_profile_dir,
    portable_cookie_path,
    runtime_dir,
    runtime_profile_dir,
    runtime_profiles_root,
    runtime_state_path,
    source_state_path,
)

logger = logging.getLogger(__name__)


def load_source_state(source_profile_dir: Path | None = None) -> SourceState | None:
    """Load the source session metadata if present."""
    data = _load_json(source_state_path(source_profile_dir))
    if not data:
        return None
    try:
        return SourceState(
            **{key: value for key, value in data.items() if key in _SOURCE_STATE_FIELDS}
        )
    except TypeError:
        logger.warning("Ignoring invalid source-state.json")
        return None


def load_runtime_state(
    runtime_id: str, source_profile_dir: Path | None = None
) -> RuntimeState | None:
    """Load one derived runtime's metadata if present."""
    data = _load_json(runtime_state_path(runtime_id, source_profile_dir))
    if not data:
        return None
    try:
        return RuntimeState(
            **{
                key: value
                for key, value in data.items()
                if key in _RUNTIME_STATE_FIELDS
            }
        )
    except TypeError:
        logger.warning("Ignoring invalid runtime-state.json for %s", runtime_id)
        return None


def write_runtime_state(
    runtime_id: str,
    source_state: SourceState,
    storage_state_path: Path,
    source_profile_dir: Path | None = None,
    *,
    created_at: str | None = None,
    commit_method: str = "checkpoint_restart",
) -> RuntimeState:
    """Write metadata for a derived runtime session."""
    profile_dir = runtime_profile_dir(runtime_id, source_profile_dir).resolve()
    committed_at = utcnow_iso()
    state = RuntimeState(
        version=1,
        runtime_id=runtime_id,
        source_runtime_id=source_state.source_runtime_id,
        source_login_generation=source_state.login_generation,
        created_at=created_at or committed_at,
        committed_at=committed_at,
        profile_path=str(profile_dir),
        storage_state_path=str(storage_state_path.resolve()),
        commit_method=commit_method,
    )
    _write_json(runtime_state_path(runtime_id, source_profile_dir), asdict(state))
    return state


def clear_runtime_profile(
    runtime_id: str, source_profile_dir: Path | None = None
) -> bool:
    """Remove one derived runtime profile and its metadata."""
    target = runtime_dir(runtime_id, source_profile_dir)
    if not target.exists():
        return True
    try:
        shutil.rmtree(target)
        return True
    except OSError as exc:
        logger.warning("Could not clear runtime profile %s: %s", target, exc)
        return False


def clear_auth_state(source_profile_dir: Path | None = None) -> bool:
    """Remove source auth artifacts and all derived runtime profiles."""
    profile_dir = (source_profile_dir or get_source_profile_dir()).expanduser()
    targets = [
        profile_dir,
        portable_cookie_path(profile_dir),
        source_state_path(profile_dir),
        runtime_profiles_root(profile_dir),
    ]

    success = True
    for target in targets:
        if not target.exists():
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            logger.warning("Could not clear auth artifact %s: %s", target, exc)
            success = False
    return success


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Ignoring unreadable auth state file: %s", path)
        return None
    if not isinstance(data, dict):
        logger.warning("Ignoring malformed auth state file: %s", path)
        return None
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    secure_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
