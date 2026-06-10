"""Schema validation helpers for CSV artifacts."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cotton_factor.common.exceptions import QAError
from cotton_factor.core import SchemaValidationError, validate_rows
from cotton_factor.core.schemas import SchemaRow


@dataclass(frozen=True)
class CsvSchemaValidationResult:
    """Result of validating one CSV file against a registered table schema."""

    table_name: str
    csv_path: Path
    row_count: int
    rows: list[SchemaRow]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "table_name": self.table_name,
            "csv_path": str(self.csv_path),
            "row_count": self.row_count,
        }


def validate_csv_table(*, table_name: str, csv_path: Path) -> CsvSchemaValidationResult:
    """Validate a CSV artifact using the registered row schema."""
    raw_rows = load_csv_dicts(csv_path)
    try:
        validated_rows = validate_rows(table_name, raw_rows)
    except SchemaValidationError as exc:
        raise QAError(f"{table_name} CSV schema validation failed: {exc}") from exc

    return CsvSchemaValidationResult(
        table_name=table_name,
        csv_path=csv_path,
        row_count=len(validated_rows),
        rows=validated_rows,
    )


def load_csv_dicts(csv_path: Path) -> list[dict[str, Any]]:
    """Load a CSV file as dictionaries with empty cells normalized to None."""
    if not csv_path.exists() or not csv_path.is_file():
        raise QAError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise QAError(f"CSV file has no header: {csv_path}")
        # CLI 校验只做结构化 schema 检查；业务解释仍然留给 core/research 层。
        return [
            {
                key: _cell_value(value)
                for key, value in row.items()
                if key is not None
            }
            for row in reader
            if any(value not in {None, ""} for value in row.values())
        ]


def _cell_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped != "" else None
