"""
Argparse type validators, boolean value constants, and TTY detection for
configuration loading.
"""

import argparse
import math
import sys

# Boolean value mappings for environment variable parsing
TRUTHY_VALUES = ("1", "true", "yes", "on")
FALSY_VALUES = ("0", "false", "no", "off")


def positive_int(value: str) -> int:
    """Argparse type for positive integers."""
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"must be positive, got {value}")
    return ivalue


def positive_float(value: str) -> float:
    """Argparse type for positive finite floats."""
    fvalue = float(value)
    if not (math.isfinite(fvalue) and fvalue > 0):
        raise argparse.ArgumentTypeError(
            f"must be a positive finite number, got {value}"
        )
    return fvalue


def non_negative_float(value: str) -> float:
    """Argparse type for non-negative finite floats (0 allowed as a sentinel)."""
    fvalue = float(value)
    if not (math.isfinite(fvalue) and fvalue >= 0):
        raise argparse.ArgumentTypeError(
            f"must be a non-negative finite number, got {value}"
        )
    return fvalue


def is_interactive_environment() -> bool:
    """
    Detect if running in an interactive environment (TTY).

    Returns:
        True if both stdin and stdout are TTY devices
    """
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, OSError):
        return False
