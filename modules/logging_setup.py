"""Logging configuration shared across the app.

Calling `configure_logging()` once from the entry point gives every module a
consistent format. Stage modules should `logging.getLogger(__name__)` and never
configure handlers themselves.
"""

from __future__ import annotations

import logging
import sys


_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s — %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(level: int = logging.INFO, *, verbose: bool = False) -> None:
    """Install a single stderr handler with a consistent format.

    Args:
        level: Default log level (logging.INFO unless overridden).
        verbose: If True, drop to DEBUG and show full module paths.
    """
    if verbose:
        level = logging.DEBUG

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down noisy third-party libraries unless we're explicitly debugging.
    if not verbose:
        for noisy in ("httpx", "httpcore", "urllib3", "PIL", "openai"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
