"""
Configuration loading and argument parsing for LinkedIn MCP Server.

Loads settings from CLI arguments and environment variables.
"""

import logging

from dotenv import load_dotenv

from ..schema import AppConfig, ConfigurationError
from .args import load_from_args
from .env import EnvironmentKeys, _normalize_env, load_from_env
from .parsing import (
    FALSY_VALUES,
    TRUTHY_VALUES,
    is_interactive_environment,
    non_negative_float,
    positive_float,
    positive_int,
)

# Load .env file if present
load_dotenv()

logger = logging.getLogger(__name__)


def load_config() -> AppConfig:
    """
    Load configuration with clear precedence order.

    Configuration is loaded in the following priority order:
    1. Command line arguments (highest priority)
    2. Environment variables
    3. Defaults (lowest priority)

    Returns:
        Fully configured application settings
    """
    # Start with default configuration
    config = AppConfig()

    # Set interactive mode
    config.is_interactive = is_interactive_environment()
    logger.debug(f"Interactive mode: {config.is_interactive}")

    # Override with environment variables
    config = load_from_env(config)

    # Override with command line arguments (highest priority)
    config = load_from_args(config)

    # Validate final configuration
    config.validate()

    return config


__all__ = [
    "AppConfig",
    "ConfigurationError",
    "EnvironmentKeys",
    "FALSY_VALUES",
    "TRUTHY_VALUES",
    "_normalize_env",
    "is_interactive_environment",
    "load_config",
    "load_from_args",
    "load_from_env",
    "non_negative_float",
    "positive_float",
    "positive_int",
]
