"""Path derivation and session-state dataclasses for auth artifacts."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

from linkedin_mcp_server.config import get_config

_SOURCE_STATE_FILE = "source-state.json"
_RUNTIME_STATE_FILE = "runtime-state.json"
_RUNTIME_PROFILES_DIR = "runtime-profiles"


@dataclass
class SourceState:
    version: int
    source_runtime_id: str
    login_generation: str
    created_at: str
    profile_path: str
    cookies_path: str
    # The user agent the session's cookies were minted under (synthesized from
    # the source browser during import, see browser_import/user_agent.py). None
    # for manual logins (the cookie is minted in the runtime browser itself, so
    # its default UA already matches) and for pre-existing state files.
    user_agent: str | None = None


@dataclass
class RuntimeState:
    version: int
    runtime_id: str
    source_runtime_id: str
    source_login_generation: str
    created_at: str
    committed_at: str
    profile_path: str
    storage_state_path: str
    commit_method: str


_SOURCE_STATE_FIELDS = frozenset(field.name for field in fields(SourceState))
_RUNTIME_STATE_FIELDS = frozenset(field.name for field in fields(RuntimeState))


def get_source_profile_dir() -> Path:
    """Return the configured source profile directory."""
    return Path(get_config().browser.user_data_dir).expanduser()


def auth_root_dir(source_profile_dir: Path | None = None) -> Path:
    """Return the root directory containing auth artifacts."""
    profile_dir = source_profile_dir or get_source_profile_dir()
    return profile_dir.expanduser().resolve().parent


def portable_cookie_path(source_profile_dir: Path | None = None) -> Path:
    """Return the portable cookie export path."""
    return auth_root_dir(source_profile_dir) / "cookies.json"


def source_state_path(source_profile_dir: Path | None = None) -> Path:
    """Return the source session metadata path."""
    return auth_root_dir(source_profile_dir) / _SOURCE_STATE_FILE


def runtime_profiles_root(source_profile_dir: Path | None = None) -> Path:
    """Return the root directory for derived runtime profiles."""
    return auth_root_dir(source_profile_dir) / _RUNTIME_PROFILES_DIR


def runtime_dir(runtime_id: str, source_profile_dir: Path | None = None) -> Path:
    """Return the directory for one runtime's derived session."""
    return runtime_profiles_root(source_profile_dir) / runtime_id


def runtime_profile_dir(
    runtime_id: str, source_profile_dir: Path | None = None
) -> Path:
    """Return the profile directory for one runtime's derived session."""
    return runtime_dir(runtime_id, source_profile_dir) / "profile"


def runtime_state_path(runtime_id: str, source_profile_dir: Path | None = None) -> Path:
    """Return the metadata path for one runtime's derived session."""
    return runtime_dir(runtime_id, source_profile_dir) / _RUNTIME_STATE_FILE


def runtime_storage_state_path(
    runtime_id: str, source_profile_dir: Path | None = None
) -> Path:
    """Return the storage-state snapshot path for one runtime's derived session."""
    return runtime_dir(runtime_id, source_profile_dir) / "storage-state.json"


def profile_exists(profile_dir: Path | None = None) -> bool:
    """Check if a browser profile directory exists and is non-empty."""
    profile_dir = (profile_dir or get_source_profile_dir()).expanduser()
    return profile_dir.is_dir() and any(profile_dir.iterdir())
