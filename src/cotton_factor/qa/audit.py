"""Row-count and null-ratio QA checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cotton_factor.common.exceptions import QAError
from cotton_factor.core.schemas import SchemaRow
from cotton_factor.qa.schema_validation import validate_csv_table


@dataclass(frozen=True)
class TableAuditResult:
    """Audit summary for one validated table artifact."""

    table_name: str
    row_count: int
    null_ratios: dict[str, float]
    warnings: list[str]

    @property
    def passed(self) -> bool:
        """Return whether the audit has no warnings."""
        return not self.warnings

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "table_name": self.table_name,
            "row_count": self.row_count,
            "null_ratios": self.null_ratios,
            "warnings": self.warnings,
            "passed": self.passed,
        }


def audit_csv_table(
    *,
    table_name: str,
    csv_path: Path,
    min_row_count: int = 1,
    max_null_ratio_by_field: Mapping[str, float] | None = None,
) -> TableAuditResult:
    """Validate and audit one CSV table artifact."""
    validation = validate_csv_table(table_name=table_name, csv_path=csv_path)
    return audit_rows(
        table_name=table_name,
        rows=validation.rows,
        min_row_count=min_row_count,
        max_null_ratio_by_field=max_null_ratio_by_field,
    )


def audit_rows(
    *,
    table_name: str,
    rows: Sequence[SchemaRow],
    min_row_count: int = 1,
    max_null_ratio_by_field: Mapping[str, float] | None = None,
) -> TableAuditResult:
    """Audit row count and field null ratios for validated rows."""
    if min_row_count < 0:
        raise QAError("min_row_count must be >= 0")

    row_count = len(rows)
    null_ratios = _null_ratios(rows)
    warnings: list[str] = []
    if row_count < min_row_count:
        warnings.append(f"{table_name}: row_count {row_count} < minimum {min_row_count}")

    thresholds = dict(max_null_ratio_by_field or {})
    for field_name, max_ratio in thresholds.items():
        if max_ratio < 0 or max_ratio > 1:
            raise QAError(f"null-ratio threshold must be between 0 and 1: {field_name}")
        actual_ratio = null_ratios.get(field_name)
        if actual_ratio is None:
            warnings.append(f"{table_name}: null-ratio field not present: {field_name}")
            continue
        if actual_ratio > max_ratio:
            warnings.append(
                f"{table_name}: {field_name} null ratio {actual_ratio:.6g} > {max_ratio:.6g}"
            )

    return TableAuditResult(
        table_name=table_name,
        row_count=row_count,
        null_ratios=null_ratios,
        warnings=warnings,
    )


def parse_null_ratio_thresholds(values: Sequence[str]) -> dict[str, float]:
    """Parse CLI values formatted as field=max_ratio."""
    thresholds: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise QAError(f"null ratio threshold must be field=value: {value!r}")
        field_name, raw_ratio = value.split("=", 1)
        field = field_name.strip()
        if not field:
            raise QAError(f"null ratio threshold has empty field: {value!r}")
        try:
            ratio = float(raw_ratio)
        except ValueError as exc:
            raise QAError(f"null ratio threshold is not numeric: {value!r}") from exc
        thresholds[field] = ratio
    return thresholds


def _null_ratios(rows: Sequence[SchemaRow]) -> dict[str, float]:
    if not rows:
        return {}
    fields = rows[0].__class__.model_fields.keys()
    ratios: dict[str, float] = {}
    for field_name in fields:
        null_count = sum(
            1
            for row in rows
            if row.model_dump(mode="python").get(field_name) is None
        )
        ratios[field_name] = null_count / len(rows)
    return ratios
