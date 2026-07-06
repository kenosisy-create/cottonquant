"""R16 research-mode CF single-factor backtest summaries."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import FactorEvaluationError, ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    ResearchFactorDiagnosticDailyRow,
    ResearchFactorEvaluationRow,
    ResearchFactorValueDailyRow,
    ResearchForwardReturnDailyRow,
    schema_for_table,
)
from cotton_factor.research import evaluate_single_factor
from cotton_factor.research_workbench.forward_returns import RETURNS_OUTPUT_DIR
from cotton_factor.research_workbench.output_contracts import (
    FACTOR_DIAGNOSTIC_TABLE,
    FACTOR_IDS_BY_FAMILY,
    FACTOR_OUTPUT_DIR,
)

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
BACKTEST_OUTPUT_DIR = "backtests"
EVALUATION_TABLE = "research_factor_evaluation"
WARNING_SEVERITY = "WARN"
EXPECTED_FACTOR_IDS = tuple(FACTOR_IDS_BY_FAMILY.values())
SINGLE_FACTOR_HUMAN_REVIEW_FIELDS = (
    "single_factor_metric_set",
    "minimum_observation_count",
)

WARNING_COLUMNS = [
    "run_id",
    "factor_id",
    "horizon",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
    "input_snapshot_ids",
]


@dataclass(frozen=True)
class SingleFactorBacktestWarningRecord:
    """Warning row for R16 single-factor research summaries."""

    run_id: str
    factor_id: str
    horizon: int
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
            "horizon": str(self.horizon),
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


@dataclass(frozen=True)
class ResearchSingleFactorBacktestResult:
    """Result of building R16 single-factor research backtest artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    factor_ids: tuple[str, ...]
    horizons: tuple[int, ...]
    rows: tuple[ResearchFactorEvaluationRow, ...]
    warning_records: tuple[SingleFactorBacktestWarningRecord, ...]
    evaluation_parquet_path: Path
    evaluation_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    diagnostic_path: Path
    forward_return_path: Path
    human_review_required: tuple[str, ...]

    @property
    def metric_count_by_factor_horizon(self) -> dict[str, int]:
        """Return metric row counts keyed by factor and horizon."""
        counts = {
            f"{factor_id}:{horizon}": 0
            for factor_id in self.factor_ids
            for horizon in self.horizons
        }
        for row in self.rows:
            key = f"{row.factor_id}:{row.horizon}"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "factor_ids": list(self.factor_ids),
            "horizons": list(self.horizons),
            "row_count": len(self.rows),
            "metric_count_by_factor_horizon": self.metric_count_by_factor_horizon,
            "warning_count": len(self.warning_records),
            "evaluation_parquet_path": str(self.evaluation_parquet_path),
            "evaluation_csv_path": str(self.evaluation_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "diagnostic_path": str(self.diagnostic_path),
            "forward_return_path": str(self.forward_return_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_single_factor_backtest(
    *,
    start: date,
    end: date,
    factor_ids: tuple[str, ...] = EXPECTED_FACTOR_IDS,
    horizons: tuple[int, ...] = (1, 3, 5),
    diagnostic_path: Path | None = None,
    forward_return_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    use_processed_value: bool = True,
) -> ResearchSingleFactorBacktestResult:
    """Build R16 single-factor research metrics from R14 diagnostics and R15 labels."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    normalized_factor_ids = _normalize_factor_ids(factor_ids)
    normalized_horizons = _normalize_horizons(horizons)

    diag_path = diagnostic_path or _default_diagnostic_path(start=start, end=end)
    forward_path = forward_return_path or _default_forward_return_path(start=start, end=end)
    diagnostic_rows = _load_diagnostic_rows(input_path=diag_path, start=start, end=end)
    forward_rows = _load_forward_return_rows(
        input_path=forward_path,
        start=start,
        end=end,
        horizons=normalized_horizons,
    )
    backtest_run_id = run_id or _default_run_id(start=start, end=end)

    rows: list[ResearchFactorEvaluationRow] = []
    warnings: list[SingleFactorBacktestWarningRecord] = []
    for factor_id in normalized_factor_ids:
        factor_rows, skipped_rows = _factor_rows_from_diagnostics(
            diagnostic_rows=diagnostic_rows,
            factor_id=factor_id,
        )
        if skipped_rows:
            warnings.append(
                _warning_record(
                    run_id=backtest_run_id,
                    factor_id=factor_id,
                    horizon=0,
                    warning_code="SINGLE_FACTOR_UNKNOWN_DIAGNOSTICS_SKIPPED",
                    warning_message=(
                        f"{factor_id} skipped {len(skipped_rows)} unknown diagnostic rows"
                    ),
                    input_snapshot_ids=_snapshot_ids_from_diagnostics(skipped_rows),
                )
            )
        for horizon in normalized_horizons:
            if not factor_rows:
                warnings.append(
                    _warning_record(
                        run_id=backtest_run_id,
                        factor_id=factor_id,
                        horizon=horizon,
                        warning_code="SINGLE_FACTOR_NO_DIAGNOSTIC_ROWS",
                        warning_message=f"{factor_id} has no usable diagnostic rows",
                        input_snapshot_ids=_snapshot_ids_from_diagnostics(diagnostic_rows),
                    )
                )
                continue
            try:
                result = evaluate_single_factor(
                    factor_rows=factor_rows,
                    forward_returns=forward_rows,
                    run_id=backtest_run_id,
                    factor_id=factor_id,
                    product_code=PRODUCT_CODE,
                    universe=UNIVERSE,
                    horizon=horizon,
                    use_processed_value=use_processed_value,
                )
            except FactorEvaluationError as exc:
                warnings.append(
                    _warning_record(
                        run_id=backtest_run_id,
                        factor_id=factor_id,
                        horizon=horizon,
                        warning_code="SINGLE_FACTOR_EVALUATION_ERROR",
                        warning_message=str(exc),
                        input_snapshot_ids=_snapshot_ids_from_factor_rows(factor_rows),
                    )
                )
                continue
            rows.extend(result.rows)
            warnings.extend(
                _warning_records_from_evaluator(
                    run_id=backtest_run_id,
                    factor_id=factor_id,
                    horizon=horizon,
                    warnings=result.warnings,
                    input_snapshot_ids=_snapshot_ids_from_factor_rows(factor_rows),
                )
            )

    rows_tuple = tuple(sorted(rows, key=lambda row: (row.factor_id, row.horizon, row.metric_name)))
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R16 只做研究摘要，不代表交易批准；真实执行边界仍由 R08/R15 产物约束。
    _write_evaluation_table(
        rows=rows_tuple,
        parquet_path=paths["evaluation_parquet"],
        csv_path=paths["evaluation_csv"],
    )
    _write_warning_csv(warnings=tuple(warnings), csv_path=paths["warning_csv"])
    result = ResearchSingleFactorBacktestResult(
        product_code=PRODUCT_CODE,
        run_id=backtest_run_id,
        start=start,
        end=end,
        factor_ids=normalized_factor_ids,
        horizons=normalized_horizons,
        rows=rows_tuple,
        warning_records=tuple(warnings),
        evaluation_parquet_path=paths["evaluation_parquet"],
        evaluation_csv_path=paths["evaluation_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        diagnostic_path=diag_path,
        forward_return_path=forward_path,
        human_review_required=SINGLE_FACTOR_HUMAN_REVIEW_FIELDS,
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _normalize_factor_ids(factor_ids: tuple[str, ...]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(item.strip() for item in factor_ids if item.strip()))
    if not values:
        raise ResearchWorkbenchError("at least one factor_id is required")
    return values


def _normalize_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    if not horizons:
        raise ResearchWorkbenchError("at least one horizon is required")
    values = tuple(sorted(set(horizons)))
    invalid = [horizon for horizon in values if horizon <= 0]
    if invalid:
        raise ResearchWorkbenchError(f"horizons must be positive integers: {invalid}")
    return values


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


def _load_forward_return_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
    horizons: tuple[int, ...],
) -> tuple[ResearchForwardReturnDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"forward return parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"forward return table missing trade_date: {input_path}")
    selected = _date_slice(frame, start=start, end=end)
    rows: list[ResearchForwardReturnDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if (
            str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE
            and int(cleaned.get("horizon", 0)) in horizons
        ):
            rows.append(ResearchForwardReturnDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} forward return rows from {start.isoformat()} to "
            f"{end.isoformat()}"
        )
    return tuple(sorted(rows, key=lambda row: (row.trade_date, row.horizon)))


def _factor_rows_from_diagnostics(
    *,
    diagnostic_rows: tuple[ResearchFactorDiagnosticDailyRow, ...],
    factor_id: str,
) -> tuple[tuple[ResearchFactorValueDailyRow, ...], tuple[ResearchFactorDiagnosticDailyRow, ...]]:
    rows: list[ResearchFactorValueDailyRow] = []
    skipped: list[ResearchFactorDiagnosticDailyRow] = []
    for row in diagnostic_rows:
        if row.factor_id != factor_id:
            continue
        if row.signal_state == "unknown" or row.raw_value is None:
            skipped.append(row)
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
    return tuple(rows), tuple(skipped)


def _warning_records_from_evaluator(
    *,
    run_id: str,
    factor_id: str,
    horizon: int,
    warnings: list[str],
    input_snapshot_ids: tuple[str, ...],
) -> list[SingleFactorBacktestWarningRecord]:
    return [
        _warning_record(
            run_id=run_id,
            factor_id=factor_id,
            horizon=horizon,
            warning_code=_warning_code(warning),
            warning_message=warning,
            input_snapshot_ids=input_snapshot_ids,
        )
        for warning in warnings
    ]


def _warning_code(warning: str) -> str:
    if "joined no observations" in warning:
        return "SINGLE_FACTOR_JOINED_NO_OBSERVATIONS"
    if "not computable" in warning:
        return "SINGLE_FACTOR_METRIC_NOT_COMPUTABLE"
    if "no non-zero sign pairs" in warning:
        return "SINGLE_FACTOR_METRIC_NOT_COMPUTABLE"
    return "SINGLE_FACTOR_WARNING"


def _warning_record(
    *,
    run_id: str,
    factor_id: str,
    horizon: int,
    warning_code: str,
    warning_message: str,
    input_snapshot_ids: tuple[str, ...],
) -> SingleFactorBacktestWarningRecord:
    return SingleFactorBacktestWarningRecord(
        run_id=run_id,
        factor_id=factor_id,
        horizon=horizon,
        severity=WARNING_SEVERITY,
        warning_code=warning_code,
        warning_message=warning_message,
        human_review_required=SINGLE_FACTOR_HUMAN_REVIEW_FIELDS,
        input_snapshot_ids=input_snapshot_ids,
    )


def _write_evaluation_table(
    *,
    rows: tuple[ResearchFactorEvaluationRow, ...],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    frame = pd.DataFrame(
        [row.model_dump(mode="json") for row in rows],
        columns=list(schema_for_table(EVALUATION_TABLE).model_fields),
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[SingleFactorBacktestWarningRecord, ...],
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
    result: ResearchSingleFactorBacktestResult,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Single-Factor Backtest - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Run ID: `{result.run_id}`",
        f"- Factors: `{', '.join(result.factor_ids)}`",
        f"- Horizons: `{', '.join(str(horizon) for horizon in result.horizons)}`",
        f"- Metric rows: `{len(result.rows)}`",
        f"- Warnings: `{len(result.warning_records)}`",
        f"- Evaluation parquet: `{result.evaluation_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Metric Counts",
        "",
    ]
    lines.extend(
        f"- `{key}`: `{count}`"
        for key, count in result.metric_count_by_factor_horizon.items()
    )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "R16 summarizes historical factor evidence from R14 diagnostics and R15 "
            "forward-return labels. It is research support only and does not approve "
            "trades, orders, positions, or production execution.",
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
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / BACKTEST_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "evaluation_parquet": root / f"{stem}_single_factor_evaluation.parquet",
        "evaluation_csv": root / f"{stem}_single_factor_evaluation.csv",
        "warning_csv": root / f"{stem}_single_factor_backtest_warnings.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / BACKTEST_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_single_factor_backtest"
    return root / f"{stem}.md"


def _default_diagnostic_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_{FACTOR_DIAGNOSTIC_TABLE.removeprefix('research_')}.parquet"


def _default_forward_return_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / RETURNS_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_forward_return_daily.parquet"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r16_single_factor_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if key in {"input_snapshot_ids", "warning_flags", "human_review_required"}:
            cleaned[key] = _coerce_list(value)
        elif _is_missing(value):
            cleaned[key] = None
        elif key in {"trade_date", "execution_date", "exit_date"}:
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


def _snapshot_ids_from_factor_rows(rows: Iterable[ResearchFactorValueDailyRow]) -> tuple[str, ...]:
    return tuple(
        _unique_values(snapshot_id for row in rows for snapshot_id in row.input_snapshot_ids)
    )


def _unique_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
