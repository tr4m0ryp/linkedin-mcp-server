"""Session lifecycle CLI subcommands: create a profile and inspect it.

These handlers are patched-name-heavy: tests monkeypatch the imported bindings
(e.g. ``get_config``, ``get_profile_dir``, ``get_or_create_browser``) at
``linkedin_mcp_server.cli_main.session_commands.<name>`` so the callers below
resolve the patched objects at call time.
"""

import asyncio
import logging
import sys

from linkedin_mcp_server.core import AuthenticationError
from linkedin_mcp_server.config import get_config
from linkedin_mcp_server.drivers.browser import (
    experimental_persist_derived_runtime,
    close_browser,
    get_or_create_browser,
    get_profile_dir,
    profile_exists,
    set_headless,
)
from linkedin_mcp_server.logging_config import configure_logging
from linkedin_mcp_server.session_state import (
    get_runtime_id,
    load_runtime_state,
    load_source_state,
    portable_cookie_path,
    runtime_profile_dir,
    runtime_storage_state_path,
)
from linkedin_mcp_server.setup import run_profile_creation

from .version import get_version

logger = logging.getLogger(__name__)


def get_profile_and_exit() -> None:
    """Create profile interactively and exit."""
    config = get_config()

    configure_logging(
        log_level=config.server.log_level,
        json_format=not config.is_interactive and config.server.log_level != "DEBUG",
    )

    version = get_version()
    logger.info(f"LinkedIn MCP Server v{version} - Session Creation mode")

    user_data_dir = config.browser.user_data_dir
    success = run_profile_creation(user_data_dir)

    sys.exit(0 if success else 1)


def profile_info_and_exit() -> None:
    """Check profile validity and display info, then exit."""
    config = get_config()

    configure_logging(
        log_level=config.server.log_level,
        json_format=not config.is_interactive and config.server.log_level != "DEBUG",
    )

    version = get_version()
    logger.info(f"LinkedIn MCP Server v{version} - Session Info mode")

    profile_dir = get_profile_dir()
    cookies_path = portable_cookie_path(profile_dir)
    source_state = load_source_state(profile_dir)
    current_runtime = get_runtime_id()

    if not source_state or not profile_exists(profile_dir) or not cookies_path.exists():
        print(f"❌ No valid source session found at {profile_dir}")
        print("   Run with --login to create a source session")
        sys.exit(1)

    print(f"Current runtime: {current_runtime}")
    print(f"Source runtime: {source_state.source_runtime_id}")
    print(f"Login generation: {source_state.login_generation}")

    runtime_state = None
    runtime_profile = None
    runtime_storage_state = None
    bridge_required = False

    if current_runtime == source_state.source_runtime_id:
        print(f"Profile mode: source ({profile_dir})")
    else:
        runtime_state = load_runtime_state(current_runtime, profile_dir)
        runtime_profile = runtime_profile_dir(current_runtime, profile_dir)
        runtime_storage_state = runtime_storage_state_path(current_runtime, profile_dir)
        if not experimental_persist_derived_runtime():
            bridge_required = True
            print("Profile mode: foreign runtime (fresh bridge each startup)")
            if runtime_profile.exists():
                print(
                    f"Derived runtime cache present but ignored by default: {runtime_profile}"
                )
        else:
            if (
                runtime_state
                and runtime_state.source_login_generation
                == source_state.login_generation
                and profile_exists(runtime_profile)
                and runtime_storage_state.exists()
            ):
                print(
                    f"Profile mode: derived (committed, current generation) ({runtime_profile})"
                )
            else:
                bridge_required = True
                state = "stale generation" if runtime_state else "missing"
                print(f"Profile mode: derived ({state})")
            print(
                "Storage snapshot: "
                f"{runtime_storage_state if runtime_storage_state and runtime_storage_state.exists() else 'missing'}"
            )

    async def check_session() -> bool:
        try:
            set_headless(True)  # Always check headless
            browser = await get_or_create_browser()
            return browser.is_authenticated
        except AuthenticationError:
            return False
        except Exception as e:
            logger.exception(f"Unexpected error checking session: {e}")
            raise
        finally:
            await close_browser()

    if bridge_required:
        if experimental_persist_derived_runtime():
            print(
                "ℹ️  A derived runtime profile will be created and checkpoint-committed on the next server startup."
            )
        else:
            print(
                "ℹ️  A fresh bridged foreign-runtime session will be created on the next server startup."
            )
        print(
            "ℹ️  Source cookie validity is not verified in this mode. Run the server to test the bridge end-to-end."
        )
        sys.exit(0)

    try:
        valid = asyncio.run(check_session())
    except Exception as e:
        print(f"❌ Could not validate session: {e}")
        print("   Check logs and browser configuration.")
        sys.exit(1)

    active_profile = profile_dir if runtime_profile is None else runtime_profile
    if valid:
        print(f"✅ Session is valid (profile: {active_profile})")
        sys.exit(0)

    print(f"❌ Session expired or invalid (profile: {active_profile})")
    print("   Run with --login to re-authenticate")
    sys.exit(1)
