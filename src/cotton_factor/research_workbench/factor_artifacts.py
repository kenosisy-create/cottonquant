"""Shared factor artifact writers for the research workbench."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.core.schemas import ResearchFactorValueDailyRow, schema_for_table
from cotton_factor.research_workbench.output_contracts import FACTOR_VALUE_TABLE

WARNING_COLUMNS = [
    "run_id",
    "factor_id",
    "trade_date",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
    "input_snapshot_ids",
]


@dataclass(frozen=True)
class FactorWarningRecord:
    """Warning row written under the R10 warning-log contract."""

    run_id: str
    factor_id: str
    trade_date: date | None
    severity: str
    warning_code: str
    warning_message: str
    human_review_required: tuple[str, ...]
    input_snapshot_ids: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "factor_id": self.factor_id,
            "trade_date": "" if self.trade_date is None else self.trade_date.isoformat(),
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


def write_factor_value_artifact(
    *,
    rows: tuple[ResearchFactorValueDailyRow, ...],
    parquet_path: Path,
    csv_path: Path,
    replace_factor_ids: tuple[str, ...],
    start: date,
    end: date,
) -> None:
    """Write factor rows while preserving other factors in the shared R10 artifact."""
    new_frame = pd.DataFrame(
        [row.model_dump(mode="json") for row in rows],
        columns=_factor_value_columns(),
    )
    existing_frame = _read_existing_factor_frame(parquet_path=parquet_path)
    if existing_frame is not None:
        existing_frame = _drop_replaced_factor_rows(
            frame=existing_frame,
            replace_factor_ids=replace_factor_ids,
            start=start,
            end=end,
        )
        frame = pd.concat([existing_frame, new_frame], ignore_index=True)
    else:
        frame = new_frame
    frame = _sort_factor_frame(frame)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def write_factor_warning_log(
    *,
    warnings: tuple[FactorWarningRecord, ...],
    csv_path: Path,
    replace_factor_id: str | None = None,
    replace_factor_ids: tuple[str, ...] = (),
    run_id: str,
) -> None:
    """Write warning rows while preserving warnings from other factor runs."""
    new_rows = [warning.to_csv_row() for warning in warnings]
    existing_rows = _read_existing_warning_rows(csv_path=csv_path)
    replaced_ids = tuple(
        [
            *(replace_factor_ids or ()),
            *([replace_factor_id] if replace_factor_id else []),
        ]
    )
    kept_rows = [
        row
        for row in existing_rows
        if not (row.get("factor_id") in replaced_ids and row.get("run_id") == run_id)
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([*kept_rows, *new_rows])


def _factor_value_columns() -> list[str]:
    return list(schema_for_table(FACTOR_VALUE_TABLE).model_fields)


def _read_existing_factor_frame(*, parquet_path: Path) -> pd.DataFrame | None:
    if not parquet_path.exists():
        return None
    frame = pd.read_parquet(parquet_path)
    for column in _factor_value_columns():
        if column not in frame.columns:
            frame[column] = None
    return frame[_factor_value_columns()]


def _drop_replaced_factor_rows(
    *,
    frame: pd.DataFrame,
    replace_factor_ids: tuple[str, ...],
    start: date,
    end: date,
) -> pd.DataFrame:
    if frame.empty or "factor_id" not in frame.columns or "trade_date" not in frame.columns:
        return frame
    trade_dates = pd.to_datetime(frame["trade_date"]).dt.date
    replaced = (
        frame["factor_id"].isin(replace_factor_ids)
        & (trade_dates >= start)
        & (trade_dates <= end)
    )
    return frame.loc[~replaced].copy()


def _sort_factor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    sort_columns = [
        column
        for column in ("trade_date", "factor_id", "run_id", "signal_object_id")
        if column in frame.columns
    ]
    if not sort_columns:
        return frame
    return frame.sort_values(sort_columns).reset_index(drop=True)


def _read_existing_warning_rows(*, csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {column: (row.get(column) or "") for column in WARNING_COLUMNS}
            for row in reader
        ]
