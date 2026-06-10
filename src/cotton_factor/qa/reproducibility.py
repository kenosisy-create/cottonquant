"""Stable fingerprints for reproducibility checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

VOLATILE_ROW_COUNT_KEYS = {"archive_bundle_bytes"}


def stable_smoke_fingerprint(summary: Mapping[str, object]) -> dict[str, object]:
    """Return a deterministic smoke summary with volatile fields removed."""
    row_counts = summary.get("row_counts")
    warnings = summary.get("warnings")
    if not isinstance(row_counts, dict):
        raise ValueError("smoke summary requires row_counts")
    if not isinstance(warnings, list):
        raise ValueError("smoke summary requires warnings")

    # raw snapshot id、路径、时间戳会随每次运行变化；D21/D22 只比较业务行数和稳定 warning。
    return {
        "row_counts": {
            key: value
            for key, value in sorted(row_counts.items())
            if key not in VOLATILE_ROW_COUNT_KEYS
        },
        "warnings": _sorted_unique_text(warnings),
    }


def _sorted_unique_text(values: Sequence[object]) -> list[str]:
    return sorted({str(value) for value in values})
