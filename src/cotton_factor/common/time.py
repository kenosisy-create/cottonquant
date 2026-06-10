"""Time helpers with explicit timezone handling."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)
