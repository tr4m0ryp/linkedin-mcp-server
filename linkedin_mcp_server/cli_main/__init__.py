"""LinkedIn MCP Server main CLI application entry point.

``main`` and the ``*_and_exit`` handlers below call names imported into this
package namespace. Tests monkeypatch those names at
``linkedin_mcp_server.cli_main.<name>``; keeping the callers here ensures the
patched bindings are the ones resolved at call time. Leaf helpers that call no
patched name live in sibling submodules and are re-exported below.
"""

import asyncio
import logging
import sys

from linkedin_mcp_server.bootstrap import (
    configure_browser_environment,
    ensure_browser_installed,
)
from linkedin_mcp_server.core import AuthenticationError
from linkedin_mcp_server.authentication import clear_auth_state
from linkedin_mcp_server.config import get_config
from linkedin_mcp_server.drivers.browser import (
    close_browser,
    get_profile_dir,
    profile_exists,
    set_headless,
)
from linkedin_mcp_server.debug_trace import should_keep_traces
from linkedin_mcp_server.logging_config import configure_logging, teardown_trace_logging
from linkedin_mcp_server.session_state import (
    portable_cookie_path,
    source_state_path,
)
from linkedin_mcp_server.server import create_mcp_server

from .session_commands import get_profile_and_exit, profile_info_and_exit
from .transport import choose_transport_interactive
from .version import get_version

logger = logging.getLogger(__name__)

__all__ = [
    "choose_transport_interactive",
    "clear_profile_and_exit",
    "exit_gracefully",
    "get_profile_and_exit",
    "get_version",
    "import_from_browser_and_exit",
    "main",
    "profile_info_and_exit",
]


def clear_profile_and_exit() -> None:
    """Clear LinkedIn browser profile and exit."""
    config = get_config()

    configure_logging(
        log_level=config.server.log_level,
        json_format=not config.is_interactive and config.server.log_level != "DEBUG",
    )

    version = get_version()
    logger.info(f"LinkedIn MCP Server v{version} - Profile Clear mode")

    auth_root = get_profile_dir().parent

    if not (
        profile_exists(get_profile_dir())
        or portable_cookie_path(get_profile_dir()).exists()
        or source_state_path(get_profile_dir()).exists()
    ):
        print("ℹ️  No authentication state found")
        print("Nothing to clear.")
        sys.exit(0)

    print(f"🔑 Clear LinkedIn authentication state from {auth_root}?")

    try:
        confirmation = (
            input("Are you sure you want to clear the profile? (y/N): ").strip().lower()
        )
        if confirmation not in ("y", "yes"):
            print("❌ Operation cancelled")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled")
        sys.exit(0)

    if clear_auth_state(get_profile_dir()):
        print("✅ LinkedIn authentication state cleared successfully!")
    else:
        print("❌ Failed to clear authentication state")
        sys.exit(1)

    sys.exit(0)


def import_from_browser_and_exit() -> None:
    """Import a LinkedIn session from a local browser, validate, persist, exit."""
    config = get_config()
    configure_logging(
        log_level=config.server.log_level,
        json_format=not config.is_interactive and config.server.log_level != "DEBUG",
    )
    logger.info("LinkedIn MCP Server v%s - Browser Import mode", get_version())

    configure_browser_environment()
    set_headless(True)  # validation runs headless
    user_data_dir = get_profile_dir()
    selector = (
        None
        if config.server.import_from_browser == "auto"
        else config.server.import_from_browser
    )

    from linkedin_mcp_server.browser_import.orchestrate import (
        import_session_from_browser,
    )
    from linkedin_mcp_server.exceptions import (
        CookieDecryptionError,
        NoLinkedInSessionFoundError,
    )

    if config.is_interactive:
        print(
            "ℹ️  macOS may prompt to allow keychain access to the browser's "
            "Safe Storage."
        )
    try:
        ok = asyncio.run(
            import_session_from_browser(selector, user_data_dir=user_data_dir)
        )
    except NoLinkedInSessionFoundError as e:
        print(f"❌ {e}")
        print("   Log into LinkedIn in your browser first, or run with --login.")
        sys.exit(1)
    except (CookieDecryptionError, AuthenticationError) as e:
        print(f"❌ Could not import session: {e}")
        sys.exit(1)

    if ok:
        print(f"✅ Imported and validated LinkedIn session into {user_data_dir}")
        sys.exit(0)
    print("❌ Imported cookies did not produce a valid session.")
    print("   The browser session may be expired. Re-login there or use --login.")
    sys.exit(1)


def main() -> None:
    """Main application entry point."""
    config = get_config()

    # Configure logging
    configure_logging(
        log_level=config.server.log_level,
        json_format=not config.is_interactive and config.server.log_level != "DEBUG",
    )

    version = get_version()

    # Print banner in interactive mode
    if config.is_interactive:
        print(f"🔗 LinkedIn MCP Server v{version} 🔗")
        print("=" * 40)

    logger.info(f"LinkedIn MCP Server v{version}")

    try:
        configure_browser_environment()

        # Set headless mode from config
        set_headless(config.browser.headless)

        # Handle --logout flag
        if config.server.logout:
            clear_profile_and_exit()

        # Ensure browser is installed for CLI modes that launch it.
        # Normal server startup uses async background setup instead. --login is
        # headed and needs full chromium; --status and --import-from-browser run
        # headless and need only the shell.
        if (
            config.server.login
            or config.server.status
            or config.server.import_from_browser
        ):
            ensure_browser_installed(full=config.server.login)

        # Handle --import-from-browser flag
        if config.server.import_from_browser:
            import_from_browser_and_exit()

        # Handle --login flag
        if config.server.login:
            get_profile_and_exit()

        # Handle --status flag
        if config.server.status:
            profile_info_and_exit()

        logger.debug(f"Server configuration: {config}")

        # Phase 1: Server Runtime
        try:
            transport = config.server.transport

            # Prompt for transport in interactive mode if not explicitly set
            if config.is_interactive and not config.server.transport_explicitly_set:
                print("\n🚀 Server ready! Choose transport mode:")
                transport = choose_transport_interactive()

            # Create and run the MCP server
            mcp = create_mcp_server(
                tool_timeout=config.server.tool_timeout_seconds,
                server_config=config.server,
            )

            if transport == "streamable-http":
                mcp.run(
                    transport=transport,
                    host=config.server.host,
                    port=config.server.port,
                    path=config.server.path,
                )
            else:
                mcp.run(transport=transport)

        except KeyboardInterrupt:
            exit_gracefully(0)

        except Exception as e:
            logger.exception(f"Server runtime error: {e}")
            if config.is_interactive:
                print(f"\n❌ Server error: {e}")
            exit_gracefully(1)
    finally:
        teardown_trace_logging(keep_traces=should_keep_traces())


def exit_gracefully(exit_code: int = 0) -> None:
    """Exit the application gracefully with browser cleanup."""
    try:
        asyncio.run(close_browser())
    except Exception:
        pass  # Best effort cleanup
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exit_gracefully(0)
    except Exception as e:
        logger.exception(
            f"Error running MCP server: {e}",
            extra={"exception_type": type(e).__name__, "exception_message": str(e)},
        )
        exit_gracefully(1)
