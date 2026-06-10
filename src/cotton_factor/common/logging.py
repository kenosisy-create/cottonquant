"""Logging setup helpers."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure a compact default logger for CLI entrypoints."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
