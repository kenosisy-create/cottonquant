"""Path helpers for repository-local artifacts."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the repository root for the src-layout package."""
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """Return the project data directory."""
    return project_root() / "data"


def reports_dir() -> Path:
    """Return the project reports directory."""
    return project_root() / "reports"
