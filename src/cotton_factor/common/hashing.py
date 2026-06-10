"""Hashing helpers used by raw snapshots and archive bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(payload: bytes) -> str:
    """Return the SHA256 hex digest for bytes."""
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA256 hex digest for a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
