"""Shared helpers for the R73-R77 CF research-state upgrade modules."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.time import utc_now


def load_table(path: Path, *, required: set[str], label: str) -> pd.DataFrame:
    """Load an inspectable CSV/Parquet research table and validate its columns."""
    if not path.exists():
        raise ResearchWorkbenchError(f"{label} not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"{label} missing columns: {missing}")
    return frame


def normalize_trade_date(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize trade_date without mutating the caller's frame."""
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(
        working["trade_date"], errors="coerce"
    ).dt.date
    return working.dropna(subset=["trade_date"])


def latest_matching_path(directory: Path, pattern: str, *, label: str) -> Path:
    """Return the latest path by embedded end date and mtime."""
    candidates = list(directory.glob(pattern))
    if not candidates:
        raise ResearchWorkbenchError(f"no {label} found under {directory}")
    return max(candidates, key=lambda path: (embedded_end_date(path), path.stat().st_mtime))


def embedded_end_date(path: Path) -> date:
    """Extract the latest ISO date from an artifact name when present."""
    import re

    matches = re.findall(r"\d{4}-\d{2}-\d{2}", path.name)
    if not matches:
        return date.min
    return max(date.fromisoformat(value) for value in matches)


def write_frame(frame: pd.DataFrame, parquet_path: Path, csv_path: Path) -> None:
    """Write a research table in Parquet and CSV forms."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")


def write_warning_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    """Write warnings even when the collection is empty."""
    rows_list = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "run_id",
        "section",
        "severity",
        "warning_code",
        "warning_message",
        "affected_count",
        "human_review_required",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows_list:
            writer.writerow({key: row.get(key, "") for key in columns})


def write_json(path: Path, payload: dict[str, object]) -> None:
    """Write UTF-8 JSON with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=json_default)
        + "\n",
        encoding="utf-8",
    )


def json_default(value: object) -> object:
    """Convert common dataframe scalar types into JSON-safe values."""
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if pd.isna(value):
        return None
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def artifact_manifest(
    *,
    run_id: str,
    report_type: str,
    rule_version: str,
    data_asof: date,
    input_paths: dict[str, Path | None],
    output_paths: dict[str, Path],
    human_review_required: tuple[str, ...],
    research_boundary: dict[str, object],
) -> dict[str, object]:
    """Build the common manifest envelope used by R73-R77."""
    return {
        "run_id": run_id,
        "product_code": "CF",
        "report_type": report_type,
        "rule_version": rule_version,
        "data_asof": data_asof.isoformat(),
        "generated_at": utc_now().isoformat(),
        "input_paths": {
            key: None if value is None else str(value) for key, value in input_paths.items()
        },
        "output_paths": {key: str(value) for key, value in output_paths.items()},
        "human_review_required": list(human_review_required),
        "research_boundary": research_boundary,
    }


def float_or_none(value: object) -> float | None:
    """Return a finite float or None."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def fmt_number(value: object, digits: int = 4) -> str:
    """Format optional numeric values for Chinese Markdown reports."""
    number = float_or_none(value)
    return "-" if number is None else f"{number:.{digits}f}"


def fmt_percent(value: object) -> str:
    """Format an optional decimal return as percentage."""
    number = float_or_none(value)
    return "-" if number is None else f"{number:.2%}"


def main_contract_rows(quotes: pd.DataFrame) -> pd.DataFrame:
    """Select each day's main contract by OI first and volume second."""
    working = normalize_trade_date(quotes)
    for column in ("open_interest", "volume"):
        working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0.0)
    ranked = working.sort_values(
        ["trade_date", "open_interest", "volume", "contract_code"],
        ascending=[True, False, False, True],
    )
    return ranked.groupby("trade_date", as_index=False).head(1).sort_values("trade_date")


def utc_timestamp_id(prefix: str, data_asof: date) -> str:
    """Build a readable default run id."""
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{data_asof.isoformat()}_{stamp}"
