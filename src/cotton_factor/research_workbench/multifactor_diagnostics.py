"""R17 research-mode CF equal-weight multifactor score diagnostics."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import FactorError, ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    ResearchFactorDiagnosticDailyRow,
    ResearchFactorValueDailyRow,
    ResearchMultifactorScoreDailyRow,
    schema_for_table,
)
from cotton_factor.research import (
    DEFAULT_EQUAL_WEIGHT_SCORE_ID,
    DEFAULT_EQUAL_WEIGHT_SCORE_RULE_VERSION,
    build_equal_weight_scores,
)
from cotton_factor.research_workbench.output_contracts import (
    FACTOR_DIAGNOSTIC_TABLE,
    FACTOR_IDS_BY_FAMILY,
    FACTOR_OUTPUT_DIR,
)

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
MULTIFACTOR_OUTPUT_DIR = "multifactor"
MULTIFACTOR_SCORE_TABLE = "research_multifactor_score_daily"
WARNING_SEVERITY = "WARN"
EXPECTED_FACTOR_IDS = tuple(FACTOR_IDS_BY_FAMILY.values())
MULTIFACTOR_HUMAN_REVIEW_FIELDS = (
    "multifactor_weight_scheme",
    "factor_direction_alignment",
    "missing_factor_policy",
)

WARNING_COLUMNS = [
    "run_id",
    "score_id",
    "trade_date",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
    "input_snapshot_ids",
]


@dataclass(frozen=True)
class MultifactorDiagnosticWarningRecord:
    """Warning row for R17 multifactor diagnostics."""

    run_id: str
    score_id: str
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
            "score_id": self.score_id,
            "trade_date": "" if self.trade_date is None else self.trade_date.isoformat(),
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


@dataclass(frozen=True)
class ResearchMultifactorDiagnosticsResult:
    """Result of building R17 equal-weight multifactor diagnostics."""

    product_code: str
    run_id: str
    score_id: str
    start: date
    end: date
    factor_ids: tuple[str, ...]
    factor_weights: dict[str, float]
    require_all_factors: bool
    rows: tuple[ResearchMultifactorScoreDailyRow, ...]
    warning_records: tuple[MultifactorDiagnosticWarningRecord, ...]
    score_parquet_path: Path
    score_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    diagnostic_path: Path
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "score_id": self.score_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "factor_ids": list(self.factor_ids),
            "factor_weights": self.factor_weights,
            "require_all_factors": self.require_all_factors,
            "row_count": len(self.rows),
            "warning_count": len(self.warning_records),
            "score_parquet_path": str(self.score_parquet_path),
            "score_csv_path": str(self.score_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "diagnostic_path": str(self.diagnostic_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_multifactor_diagnostics(
    *,
    start: date,
    end: date,
    factor_ids: tuple[str, ...] = EXPECTED_FACTOR_IDS,
    diagnostic_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    score_id: str = DEFAULT_EQUAL_WEIGHT_SCORE_ID,
    use_processed_value: bool = True,
    require_all_factors: bool = True,
) -> ResearchMultifactorDiagnosticsResult:
    """Build R17 equal-weight multifactor scores from R14 diagnostics."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    normalized_factor_ids = _normalize_factor_ids(factor_ids)
    diag_path = diagnostic_path or _default_diagnostic_path(start=start, end=end)
    diagnostic_rows = _load_diagnostic_rows(input_path=diag_path, start=start, end=end)
    score_run_id = run_id or _default_run_id(start=start, end=end)
    factor_rows, warnings = _factor_rows_from_diagnostics(
        diagnostic_rows=diagnostic_rows,
        factor_ids=normalized_factor_ids,
        run_id=score_run_id,
        score_id=score_id,
    )
    try:
        score_result = build_equal_weight_scores(
            factor_rows=factor_rows,
            run_id=score_run_id,
            product_code=PRODUCT_CODE,
            universe=UNIVERSE,
            factor_ids=normalized_factor_ids,
            score_id=score_id,
            score_rule_version=DEFAULT_EQUAL_WEIGHT_SCORE_RULE_VERSION,
            use_processed_value=use_processed_value,
            require_all_factors=require_all_factors,
        )
    except FactorError as exc:
        score_result = None
        warnings.append(
            _warning_record(
                run_id=score_run_id,
                score_id=score_id,
                trade_date=None,
                warning_code="MULTIFACTOR_SCORE_BUILD_ERROR",
                warning_message=str(exc),
                input_snapshot_ids=_snapshot_ids_from_diagnostics(diagnostic_rows),
            )
        )

    rows = tuple(score_result.rows) if score_result is not None else ()
    if score_result is not None:
        warnings.extend(
            _warning_records_from_score_builder(
                run_id=score_run_id,
                score_id=score_id,
                warnings=score_result.warnings,
                diagnostic_rows=diagnostic_rows,
            )
        )

    rows_tuple = tuple(sorted(rows, key=lambda row: row.trade_date))
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R17 多因子分数仍是研究诊断对象，不是目标仓位；缺失因子策略必须显式写入 warning/report。
    _write_score_table(
        rows=rows_tuple,
        parquet_path=paths["score_parquet"],
        csv_path=paths["score_csv"],
    )
    _write_warning_csv(warnings=tuple(warnings), csv_path=paths["warning_csv"])
    result = ResearchMultifactorDiagnosticsResult(
        product_code=PRODUCT_CODE,
        run_id=score_run_id,
        score_id=score_id,
        start=start,
        end=end,
        factor_ids=normalized_factor_ids,
        factor_weights=_equal_weights(normalized_factor_ids),
        require_all_factors=require_all_factors,
        rows=rows_tuple,
        warning_records=tuple(warnings),
        score_parquet_path=paths["score_parquet"],
        score_csv_path=paths["score_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        diagnostic_path=diag_path,
        human_review_required=MULTIFACTOR_HUMAN_REVIEW_FIELDS,
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _normalize_factor_ids(factor_ids: tuple[str, ...]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(item.strip() for item in factor_ids if item.strip()))
    if not values:
        raise ResearchWorkbenchError("at least one factor_id is required")
    return values


def _equal_weights(factor_ids: tuple[str, ...]) -> dict[str, float]:
    weight = 1 / len(factor_ids)
    return {factor_id: weight for factor_id in factor_ids}


def _load_diagnostic_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
) -> tuple[ResearchFactorDiagnosticDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"factor diagnostic parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"factor diagnostic table missing trade_date: {input_path}")
    selected = _date_slice(frame, start=start, end=end)
    rows: list[ResearchFactorDiagnosticDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(ResearchFactorDiagnosticDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} factor diagnostic rows from {start.isoformat()} to "
            f"{end.isoformat()}"
        )
    return tuple(sorted(rows, key=lambda row: (row.trade_date, row.factor_id)))


def _factor_rows_from_diagnostics(
    *,
    diagnostic_rows: tuple[ResearchFactorDiagnosticDailyRow, ...],
    factor_ids: tuple[str, ...],
    run_id: str,
    score_id: str,
) -> tuple[tuple[ResearchFactorValueDailyRow, ...], list[MultifactorDiagnosticWarningRecord]]:
    selected = set(factor_ids)
    rows: list[ResearchFactorValueDailyRow] = []
    warnings: list[MultifactorDiagnosticWarningRecord] = []
    skipped_unknown: list[ResearchFactorDiagnosticDailyRow] = []
    for row in diagnostic_rows:
        if row.factor_id not in selected:
            continue
        if row.signal_state == "unknown" or row.raw_value is None:
            skipped_unknown.append(row)
            continue
        rows.append(
            ResearchFactorValueDailyRow(
                run_id=row.run_id,
                factor_id=row.factor_id,
                factor_version=row.factor_version,
                product_code=row.product_code,
                universe=row.universe,
                signal_object_id=row.signal_object_id,
                trade_date=row.trade_date,
                raw_value=row.raw_value,
                processed_value=row.processed_value,
                input_snapshot_ids=row.input_snapshot_ids,
            )
        )
    if skipped_unknown:
        warnings.append(
            _warning_record(
                run_id=run_id,
                score_id=score_id,
                trade_date=None,
                warning_code="MULTIFACTOR_UNKNOWN_DIAGNOSTICS_SKIPPED",
                warning_message=(
                    f"skipped {len(skipped_unknown)} unknown factor diagnostic rows"
                ),
                input_snapshot_ids=_snapshot_ids_from_diagnostics(skipped_unknown),
            )
        )
    return tuple(rows), warnings


def _warning_records_from_score_builder(
    *,
    run_id: str,
    score_id: str,
    warnings: list[str],
    diagnostic_rows: tuple[ResearchFactorDiagnosticDailyRow, ...],
) -> list[MultifactorDiagnosticWarningRecord]:
    input_snapshot_ids = _snapshot_ids_from_diagnostics(diagnostic_rows)
    return [
        _warning_record(
            run_id=run_id,
            score_id=score_id,
            trade_date=_date_prefix(warning),
            warning_code=_warning_code(warning),
            warning_message=warning,
            input_snapshot_ids=input_snapshot_ids,
        )
        for warning in warnings
    ]


def _warning_code(warning: str) -> str:
    if "missing factors" in warning:
        return "MULTIFACTOR_MISSING_REQUIRED_FACTORS"
    if "produced no rows" in warning:
        return "MULTIFACTOR_SCORE_NO_ROWS"
    return "MULTIFACTOR_SCORE_WARNING"


def _date_prefix(value: str) -> date | None:
    prefix = value.split(":", 1)[0]
    try:
        return date.fromisoformat(prefix)
    except ValueError:
        return None


def _warning_record(
    *,
    run_id: str,
    score_id: str,
    trade_date: date | None,
    warning_code: str,
    warning_message: str,
    input_snapshot_ids: tuple[str, ...],
) -> MultifactorDiagnosticWarningRecord:
    return MultifactorDiagnosticWarningRecord(
        run_id=run_id,
        score_id=score_id,
        trade_date=trade_date,
        severity=WARNING_SEVERITY,
        warning_code=warning_code,
        warning_message=warning_message,
        human_review_required=MULTIFACTOR_HUMAN_REVIEW_FIELDS,
        input_snapshot_ids=input_snapshot_ids,
    )


def _write_score_table(
    *,
    rows: tuple[ResearchMultifactorScoreDailyRow, ...],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    frame = pd.DataFrame(
        [row.model_dump(mode="json") for row in rows],
        columns=list(schema_for_table(MULTIFACTOR_SCORE_TABLE).model_fields),
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[MultifactorDiagnosticWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    markdown_path: Path,
    result: ResearchMultifactorDiagnosticsResult,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Multifactor Diagnostics - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Run ID: `{result.run_id}`",
        f"- Score ID: `{result.score_id}`",
        f"- Rows: `{len(result.rows)}`",
        f"- Warnings: `{len(result.warning_records)}`",
        f"- Require all factors: `{result.require_all_factors}`",
        f"- Score parquet: `{result.score_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Equal Weights",
        "",
    ]
    lines.extend(
        f"- `{factor_id}`: `{weight:.6f}`"
        for factor_id, weight in result.factor_weights.items()
    )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "R17 builds equal-weight research diagnostics from factor states. It does "
            "not generate target lots, orders, or production execution approvals.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _date_slice(frame: pd.DataFrame, *, start: date, end: date) -> pd.DataFrame:
    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[
        (working["_trade_date_obj"] >= start) & (working["_trade_date_obj"] <= end)
    ].drop(columns=["_trade_date_obj"])
    if selected.empty:
        raise ResearchWorkbenchError(
            f"no rows found from {start.isoformat()} to {end.isoformat()}"
        )
    return selected


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / MULTIFACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "score_parquet": root / f"{stem}_multifactor_score_daily.parquet",
        "score_csv": root / f"{stem}_multifactor_score_daily.csv",
        "warning_csv": root / f"{stem}_multifactor_warnings.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / MULTIFACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_multifactor_diagnostics"
    return root / f"{stem}.md"


def _default_diagnostic_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_{FACTOR_DIAGNOSTIC_TABLE.removeprefix('research_')}.parquet"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r17_multifactor_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if key in {"input_snapshot_ids", "warning_flags", "human_review_required"}:
            cleaned[key] = _coerce_list(value)
        elif _is_missing(value):
            cleaned[key] = None
        elif key == "trade_date":
            cleaned[key] = pd.to_datetime(value).date()
        else:
            cleaned[key] = value
    return cleaned


def _coerce_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    if hasattr(value, "tolist"):
        listed = value.tolist()  # type: ignore[attr-defined]
        if isinstance(listed, list):
            return [str(item) for item in listed]
        return [] if _is_missing(listed) else [str(listed)]
    if _is_missing(value):
        return []
    return [str(value)]


def _is_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict, set)) or hasattr(value, "tolist"):
        return False
    missing = pd.isna(value)
    if isinstance(missing, bool):
        return missing
    return False


def _snapshot_ids_from_diagnostics(
    rows: Iterable[ResearchFactorDiagnosticDailyRow],
) -> tuple[str, ...]:
    return tuple(
        _unique_values(snapshot_id for row in rows for snapshot_id in row.input_snapshot_ids)
    )


def _unique_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
