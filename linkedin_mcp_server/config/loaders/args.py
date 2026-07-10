"""
Command line argument configuration loading.
"""

import argparse

from ..schema import AppConfig, ConfigurationError
from .parsing import non_negative_float, positive_float, positive_int


def load_from_args(config: AppConfig) -> AppConfig:
    """Load configuration from command line arguments."""
    parser = argparse.ArgumentParser(
        description="LinkedIn MCP Server - A Model Context Protocol server for LinkedIn integration"
    )

    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser with a visible window (useful for login and debugging)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level (default: WARNING)",
    )

    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Specify the transport mode (stdio or streamable-http)",
    )

    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="HTTP server host (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP server port (default: 8000)",
    )

    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="HTTP server path (default: /mcp)",
    )

    # Browser configuration
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        metavar="MS",
        help="Slow down browser actions by N milliseconds (debugging)",
    )

    parser.add_argument(
        "--user-agent",
        type=str,
        default=None,
        help="Custom browser user agent",
    )

    parser.add_argument(
        "--viewport",
        type=str,
        default=None,
        metavar="WxH",
        help="Browser viewport size (default: 1280x720)",
    )

    parser.add_argument(
        "--timeout",
        type=positive_int,
        default=None,
        metavar="MS",
        help="Browser timeout for page operations in milliseconds (default: 5000)",
    )

    parser.add_argument(
        "--tool-timeout",
        type=positive_float,
        default=None,
        metavar="SECONDS",
        help="Per-tool MCP execution timeout in seconds (default: 180.0)",
    )

    parser.add_argument(
        "--login-timeout",
        type=non_negative_float,
        default=None,
        metavar="SECONDS",
        help="Manual login wait timeout in seconds (default: 1800; 0 = no limit)",
    )

    parser.add_argument(
        "--login-inline-wait",
        type=non_negative_float,
        default=None,
        metavar="SECONDS",
        help=(
            "Bounded inline wait for a tool call to resume after login completes, "
            "in seconds (default: 25, max 45; 0 = return immediately)"
        ),
    )

    parser.add_argument(
        "--chrome-path",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to Chrome/Chromium executable (for custom browser installations)",
    )

    # Session management
    parser.add_argument(
        "--login",
        action="store_true",
        help="Login interactively via browser and save persistent profile",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Check if current session is valid and exit",
    )

    parser.add_argument(
        "--logout",
        action="store_true",
        help="Clear stored LinkedIn browser profile",
    )

    parser.add_argument(
        "--user-data-dir",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to persistent browser profile directory (default: ~/.linkedin-mcp/profile)",
    )

    parser.add_argument(
        "--import-from-browser",
        nargs="?",
        const="auto",
        default=None,
        metavar="BROWSER",
        help=(
            "Import a LinkedIn session from a locally logged-in Chromium browser "
            "(chrome, chromium, brave, edge, arc, vivaldi, helium, yandex, whale, "
            "coccoc, opera, opera_gx, or auto). Bare flag = auto (most recently "
            "used live session). On macOS the OS keychain may prompt for access "
            "to the browser's Safe Storage."
        ),
    )

    auto_import_group = parser.add_mutually_exclusive_group()
    auto_import_group.add_argument(
        "--auto-import",
        dest="auto_import",
        action="store_true",
        default=None,
        help=(
            "Auto-import a session from a locally logged-in browser on first "
            "use (the default). Provided for explicitness; it cannot override "
            "the Docker or non-loopback-HTTP gates."
        ),
    )
    auto_import_group.add_argument(
        "--no-auto-import",
        dest="auto_import",
        action="store_false",
        default=None,
        help=(
            "Disable auto-import of a session from a browser on first use; "
            "require --login or --import-from-browser instead."
        ),
    )

    eager_full_group = parser.add_mutually_exclusive_group()
    eager_full_group.add_argument(
        "--eager-full-chromium",
        dest="eager_full_chromium",
        action="store_true",
        default=None,
        help=(
            "Install full Chrome for Testing up front during browser setup "
            "instead of lazily on the first headed login (pre-warms the headed "
            "login fallback at the cost of a larger initial download)"
        ),
    )
    eager_full_group.add_argument(
        "--no-eager-full-chromium",
        dest="eager_full_chromium",
        action="store_false",
        default=None,
        help=(
            "Install full Chrome for Testing lazily on the first headed login "
            "(default; overrides EAGER_FULL_CHROMIUM=true)."
        ),
    )

    args = parser.parse_args()

    # Update configuration with parsed arguments
    if args.no_headless:
        config.browser.headless = False

    if args.log_level:
        config.server.log_level = args.log_level

    if args.transport:
        config.server.transport = args.transport
        config.server.transport_explicitly_set = True

    if args.host:
        config.server.host = args.host

    if args.port:
        config.server.port = args.port

    if args.path:
        config.server.path = args.path

    # Browser configuration
    if args.slow_mo:
        config.browser.slow_mo = args.slow_mo

    if args.user_agent:
        config.browser.user_agent = args.user_agent

    # Viewport (validated in BrowserConfig.validate())
    if args.viewport:
        try:
            width, height = args.viewport.lower().split("x")
            config.browser.viewport_width = int(width)
            config.browser.viewport_height = int(height)
        except ValueError:
            raise ConfigurationError(
                f"Invalid --viewport: '{args.viewport}'. Must be in format WxH (e.g., 1280x720)."
            )

    if args.timeout is not None:
        config.browser.default_timeout = args.timeout

    if args.tool_timeout is not None:
        config.server.tool_timeout_seconds = args.tool_timeout

    if args.login_timeout is not None:
        config.browser.login_timeout_seconds = args.login_timeout

    if args.login_inline_wait is not None:
        config.browser.login_inline_wait_seconds = args.login_inline_wait

    if args.chrome_path:
        config.browser.chrome_path = args.chrome_path

    # Session management
    if args.login:
        config.server.login = True

    if args.status:
        config.server.status = True

    if args.logout:
        config.server.logout = True

    if args.user_data_dir:
        config.browser.user_data_dir = args.user_data_dir

    if args.import_from_browser is not None:
        value = args.import_from_browser.strip().lower()
        config.server.import_from_browser = value or "auto"

    if args.auto_import is not None:
        config.browser.auto_import_from_browser = args.auto_import

    if args.eager_full_chromium is not None:
        config.browser.eager_full_chromium = args.eager_full_chromium

    return config
