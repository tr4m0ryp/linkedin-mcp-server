"""
Environment variable configuration loading.
"""

import math
import os
from typing import Literal, cast

from ..schema import AppConfig, ConfigurationError
from .parsing import FALSY_VALUES, TRUTHY_VALUES


def _normalize_env(value: str) -> str:
    """Normalize environment variable values for tolerant parsing."""
    return value.strip().lower()


class EnvironmentKeys:
    """Environment variable names used by the application."""

    HEADLESS = "HEADLESS"
    LOG_LEVEL = "LOG_LEVEL"
    TRANSPORT = "TRANSPORT"
    TIMEOUT = "TIMEOUT"
    USER_AGENT = "USER_AGENT"
    HOST = "HOST"
    PORT = "PORT"
    HTTP_PATH = "HTTP_PATH"
    SLOW_MO = "SLOW_MO"
    VIEWPORT = "VIEWPORT"
    CHROME_PATH = "CHROME_PATH"
    USER_DATA_DIR = "USER_DATA_DIR"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    LOGIN_TIMEOUT = "LOGIN_TIMEOUT"
    LOGIN_INLINE_WAIT = "LOGIN_INLINE_WAIT"
    IMPORT_FROM_BROWSER = "IMPORT_FROM_BROWSER"
    AUTO_IMPORT_FROM_BROWSER = "AUTO_IMPORT_FROM_BROWSER"
    EAGER_FULL_CHROMIUM = "EAGER_FULL_CHROMIUM"
    # Auth for the streamable-http transport (see linkedin_mcp_server.auth).
    MCP_API_KEY = "MCP_API_KEY"
    WORKOS_AUTHKIT_DOMAIN = "WORKOS_AUTHKIT_DOMAIN"
    MCP_BASE_URL = "MCP_BASE_URL"


def load_from_env(config: AppConfig) -> AppConfig:
    """Load configuration from environment variables."""

    # Log level
    if log_level_env := os.environ.get(EnvironmentKeys.LOG_LEVEL):
        log_level_upper = log_level_env.strip().upper()
        if log_level_upper in ("DEBUG", "INFO", "WARNING", "ERROR"):
            config.server.log_level = cast(
                Literal["DEBUG", "INFO", "WARNING", "ERROR"], log_level_upper
            )

    # Headless mode
    if headless_env := os.environ.get(EnvironmentKeys.HEADLESS):
        headless_value = _normalize_env(headless_env)
        if headless_value in FALSY_VALUES:
            config.browser.headless = False
        elif headless_value in TRUTHY_VALUES:
            config.browser.headless = True

    # Transport mode
    if transport_env := os.environ.get(EnvironmentKeys.TRANSPORT):
        config.server.transport_explicitly_set = True
        transport_value = _normalize_env(transport_env)
        if transport_value == "stdio":
            config.server.transport = "stdio"
        elif transport_value == "streamable-http":
            config.server.transport = "streamable-http"
        else:
            raise ConfigurationError(
                f"Invalid TRANSPORT: '{transport_env}'. Must be 'stdio' or 'streamable-http'."
            )

    # Persistent browser profile directory
    if user_data_dir := os.environ.get(EnvironmentKeys.USER_DATA_DIR):
        config.browser.user_data_dir = user_data_dir

    # Timeout for page operations (validated in BrowserConfig.validate())
    if timeout_env := os.environ.get(EnvironmentKeys.TIMEOUT):
        try:
            config.browser.default_timeout = int(timeout_env)
        except ValueError:
            raise ConfigurationError(
                f"Invalid TIMEOUT: '{timeout_env}'. Must be an integer."
            )

    # Per-tool MCP execution timeout in seconds (also validated in ServerConfig.validate())
    if tool_timeout_env := os.environ.get(EnvironmentKeys.TOOL_TIMEOUT):
        try:
            tool_timeout_value = float(tool_timeout_env)
        except ValueError:
            raise ConfigurationError(
                f"Invalid TOOL_TIMEOUT: '{tool_timeout_env}'. Must be a number."
            )
        if not (math.isfinite(tool_timeout_value) and tool_timeout_value > 0):
            raise ConfigurationError(
                f"Invalid TOOL_TIMEOUT: '{tool_timeout_env}'. Must be a positive finite number."
            )
        config.server.tool_timeout_seconds = tool_timeout_value

    # Manual-login wait timeout in seconds; 0 = no limit (validated in
    # BrowserConfig.validate())
    if login_timeout_env := os.environ.get(EnvironmentKeys.LOGIN_TIMEOUT):
        try:
            login_timeout_value = float(login_timeout_env)
        except ValueError:
            raise ConfigurationError(
                f"Invalid LOGIN_TIMEOUT: '{login_timeout_env}'. Must be a number."
            )
        if not (math.isfinite(login_timeout_value) and login_timeout_value >= 0):
            raise ConfigurationError(
                f"Invalid LOGIN_TIMEOUT: '{login_timeout_env}'. Must be a non-negative finite number (0 = no limit)."
            )
        config.browser.login_timeout_seconds = login_timeout_value

    # Bounded inline wait before the pending signal; 0 = immediate return
    # (validated and clamped in BrowserConfig.validate())
    if login_inline_wait_env := os.environ.get(EnvironmentKeys.LOGIN_INLINE_WAIT):
        try:
            login_inline_wait_value = float(login_inline_wait_env)
        except ValueError:
            raise ConfigurationError(
                f"Invalid LOGIN_INLINE_WAIT: '{login_inline_wait_env}'. Must be a number."
            )
        if not (
            math.isfinite(login_inline_wait_value) and login_inline_wait_value >= 0
        ):
            raise ConfigurationError(
                f"Invalid LOGIN_INLINE_WAIT: '{login_inline_wait_env}'. Must be a non-negative finite number (0 = no inline wait)."
            )
        config.browser.login_inline_wait_seconds = login_inline_wait_value

    # Custom user agent
    if user_agent_env := os.environ.get(EnvironmentKeys.USER_AGENT):
        config.browser.user_agent = user_agent_env

    # HTTP server host
    if host_env := os.environ.get(EnvironmentKeys.HOST):
        config.server.host = host_env

    # HTTP server port (validated in AppConfig.validate())
    if port_env := os.environ.get(EnvironmentKeys.PORT):
        try:
            config.server.port = int(port_env)
        except ValueError:
            raise ConfigurationError(f"Invalid PORT: '{port_env}'. Must be an integer.")

    # HTTP server path
    if path_env := os.environ.get(EnvironmentKeys.HTTP_PATH):
        config.server.path = path_env

    # Slow motion delay for debugging (validated in BrowserConfig.validate())
    if slow_mo_env := os.environ.get(EnvironmentKeys.SLOW_MO):
        try:
            config.browser.slow_mo = int(slow_mo_env)
        except ValueError:
            raise ConfigurationError(
                f"Invalid SLOW_MO: '{slow_mo_env}'. Must be an integer."
            )

    # Browser viewport (validated in BrowserConfig.validate())
    if viewport_env := os.environ.get(EnvironmentKeys.VIEWPORT):
        try:
            width, height = viewport_env.lower().split("x")
            config.browser.viewport_width = int(width)
            config.browser.viewport_height = int(height)
        except ValueError:
            raise ConfigurationError(
                f"Invalid VIEWPORT: '{viewport_env}'. Must be in format WxH (e.g., 1280x720)."
            )

    # Custom Chrome/Chromium executable path
    if chrome_path_env := os.environ.get(EnvironmentKeys.CHROME_PATH):
        config.browser.chrome_path = chrome_path_env

    # Import a LinkedIn session from a locally logged-in browser (validated in
    # ServerConfig.validate())
    if import_browser_env := os.environ.get(EnvironmentKeys.IMPORT_FROM_BROWSER):
        config.server.import_from_browser = _normalize_env(import_browser_env) or "auto"

    # Auto-import a session from a logged-in browser on first no-session tool
    # call. Unset = on by default (interactive and non-interactive desktop);
    # false disables it. No effect under Docker or a non-loopback HTTP bind.
    if auto_import_env := os.environ.get(EnvironmentKeys.AUTO_IMPORT_FROM_BROWSER):
        auto_import_value = _normalize_env(auto_import_env)
        if auto_import_value in FALSY_VALUES:
            config.browser.auto_import_from_browser = False
        elif auto_import_value in TRUTHY_VALUES:
            config.browser.auto_import_from_browser = True

    # Install full chromium up front instead of lazily on the first headed login.
    if eager_full_env := os.environ.get(EnvironmentKeys.EAGER_FULL_CHROMIUM):
        eager_full_value = _normalize_env(eager_full_env)
        if eager_full_value in FALSY_VALUES:
            config.browser.eager_full_chromium = False
        elif eager_full_value in TRUTHY_VALUES:
            config.browser.eager_full_chromium = True

    return config
