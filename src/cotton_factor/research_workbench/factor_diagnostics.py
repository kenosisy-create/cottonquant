"""R14 daily CF factor diagnostic state table."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    ResearchFactorDiagnosticDailyRow,
    ResearchFactorValueDailyRow,
    schema_for_table,
)
from cotton_factor.research import load_factor_registry
from cotton_factor.research_workbench.factor_artifacts import (
    WARNING_COLUMNS,
    FactorWarningRecord,
    write_factor_warning_log,
)
from cotton_factor.research_workbench.output_contracts import (
    FACTOR_DIAGNOSTIC_TABLE,
    FACTOR_IDS_BY_FAMILY,
    FACTOR_OUTPUT_DIR,
    FACTOR_VALUE_TABLE,
)

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
SIGNAL_OBJECT_ID = "CF.C1"
DIAGNOSTIC_RULE_VERSION = "r14_sign_state_heuristic_v1"
WARNING_SEVERITY = "WARN"
FACTOR_THRESHOLD_REVIEW_FIELDS = ("factor_thresholds",)
EXPECTED_FACTOR_IDS = tuple(FACTOR_IDS_BY_FAMILY.values())


@dataclass(frozen=True)
class ResearchFactorDiagnosticsBuildResult:
    """Result of building R14 factor diagnostic artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    rows: tuple[ResearchFactorDiagnosticDailyRow, ...]
    warning_records: tuple[FactorWarningRecord, ...]
    diagnostic_parquet_path: Path
    diagnostic_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    factor_value_path: Path
    state_counts: dict[str, int]
    missing_factor_count: int
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": len(self.rows),
            "state_counts": self.state_counts,
            "unknown_count": self.state_counts.get("unknown", 0),
            "missing_factor_count": self.missing_factor_count,
            "warning_count": len(self.warning_records),
            "factor_value_path": str(self.factor_value_path),
            "diagnostic_parquet_path": str(self.diagnostic_parquet_path),
            "diagnostic_csv_path": str(self.diagnostic_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "human_review_required": list(self.human_review_required),
        }


@dataclass(frozen=True)
class _WarningContext:
    warning_code: str
    human_review_required: tuple[str, ...]
    input_snapshot_ids: tuple[str, ...]


def build_cf_factor_diagnostics(
    *,
    start: date,
    end: date,
    factor_value_path: Path | None = None,
    warning_csv_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchFactorDiagnosticsBuildResult:
    """Build R14 daily long/short/neutral/unknown diagnostic rows."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")

    value_path = factor_value_path or _default_factor_value_path(start=start, end=end)
    warning_path = warning_csv_path or _default_warning_csv_path(start=start, end=end)
    diagnostic_run_id = run_id or _default_run_id(start=start, end=end)
    factor_rows = _load_factor_rows(input_path=value_path, start=start, end=end)
    warning_contexts = _load_warning_contexts(csv_path=warning_path)
    rows, r14_warnings = _build_diagnostic_rows(
        factor_rows=factor_rows,
        warning_contexts=warning_contexts,
        start=start,
        end=end,
        run_id=diagnostic_run_id,
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R14 只解释 R10 因子值产物；缺失的因子/日期必须显式写成 unknown，不能补零或当作 neutral。
    _write_diagnostic_artifacts(
        rows=rows,
        parquet_path=paths["diagnostic_parquet"],
        csv_path=paths["diagnostic_csv"],
    )
    write_factor_warning_log(
        warnings=r14_warnings,
        csv_path=warning_path,
        replace_factor_ids=EXPECTED_FACTOR_IDS,
        run_id=diagnostic_run_id,
    )

    result = ResearchFactorDiagnosticsBuildResult(
        product_code=PRODUCT_CODE,
        run_id=diagnostic_run_id,
        start=start,
        end=end,
        rows=rows,
        warning_records=r14_warnings,
        diagnostic_parquet_path=paths["diagnostic_parquet"],
        diagnostic_csv_path=paths["diagnostic_csv"],
        warning_csv_path=warning_path,
        markdown_path=markdown_path,
        factor_value_path=value_path,
        state_counts=_state_counts(rows),
        missing_factor_count=sum(
            1 for row in rows if "R14_MISSING_FACTOR_VALUE" in row.warning_flags
        ),
        human_review_required=_human_review_required(rows),
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _load_factor_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
) -> tuple[ResearchFactorValueDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"factor value parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"factor value table missing trade_date: {input_path}")
    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[
        (working["_trade_date_obj"] >= start) & (working["_trade_date_obj"] <= end)
    ].drop(columns=["_trade_date_obj"])
    if selected.empty:
        raise ResearchWorkbenchError(
            f"no factor value rows found from {start.isoformat()} to {end.isoformat()}"
        )

    rows: list[ResearchFactorValueDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(ResearchFactorValueDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} factor rows in selected value table")
    return tuple(sorted(rows, key=lambda row: (row.trade_date, row.factor_id)))


def _build_diagnostic_rows(
    *,
    factor_rows: tuple[ResearchFactorValueDailyRow, ...],
    warning_contexts: dict[tuple[str, date | None], tuple[_WarningContext, ...]],
    start: date,
    end: date,
    run_id: str,
) -> tuple[tuple[ResearchFactorDiagnosticDailyRow, ...], tuple[FactorWarningRecord, ...]]:
    rows_by_key = _rows_by_key(factor_rows)
    rows_by_date = _rows_by_date(factor_rows)
    factor_versions = _factor_versions()
    diagnostic_rows: list[ResearchFactorDiagnosticDailyRow] = []
    warning_records: list[FactorWarningRecord] = []
    for trade_date, date_rows in rows_by_date.items():
        date_snapshot_ids = _unique_snapshot_ids(
            snapshot_id
            for row in date_rows
            for snapshot_id in row.input_snapshot_ids
        )
        for factor_id in EXPECTED_FACTOR_IDS:
            factor_row = rows_by_key.get((factor_id, SIGNAL_OBJECT_ID, trade_date))
            contexts = _contexts_for(
                warning_contexts=warning_contexts,
                factor_id=factor_id,
                trade_date=trade_date,
            )
            if factor_row is None:
                diagnostic_rows.append(
                    _missing_factor_row(
                        factor_id=factor_id,
                        factor_version=factor_versions[factor_id],
                        trade_date=trade_date,
                        run_id=run_id,
                        contexts=contexts,
                        input_snapshot_ids=date_snapshot_ids,
                    )
                )
                warning_records.append(
                    FactorWarningRecord(
                        run_id=run_id,
                        factor_id=factor_id,
                        trade_date=trade_date,
                        severity=WARNING_SEVERITY,
                        warning_code="R14_MISSING_FACTOR_VALUE",
                        warning_message=(
                            f"{factor_id} has no R10 factor value row on "
                            f"{trade_date.isoformat()}"
                        ),
                        human_review_required=FACTOR_THRESHOLD_REVIEW_FIELDS,
                        input_snapshot_ids=date_snapshot_ids,
                    )
                )
                continue
            diagnostic_rows.append(
                _value_diagnostic_row(
                    factor_row=factor_row,
                    run_id=run_id,
                    contexts=contexts,
                )
            )
    if not diagnostic_rows:
        raise ResearchWorkbenchError(
            f"no R14 diagnostic rows built from {start.isoformat()} to {end.isoformat()}"
        )
    return tuple(diagnostic_rows), tuple(warning_records)


def _rows_by_key(
    rows: tuple[ResearchFactorValueDailyRow, ...],
) -> dict[tuple[str, str, date], ResearchFactorValueDailyRow]:
    grouped: dict[tuple[str, str, date], ResearchFactorValueDailyRow] = {}
    duplicate_keys: list[tuple[str, str, date]] = []
    for row in rows:
        key = (row.factor_id, row.signal_object_id, row.trade_date)
        if key in grouped:
            duplicate_keys.append(key)
        grouped[key] = row
    if duplicate_keys:
        raise ResearchWorkbenchError(f"duplicate R10 factor rows for keys {duplicate_keys}")
    return grouped


def _rows_by_date(
    rows: tuple[ResearchFactorValueDailyRow, ...],
) -> dict[date, tuple[ResearchFactorValueDailyRow, ...]]:
    grouped: dict[date, list[ResearchFactorValueDailyRow]] = {}
    for row in rows:
        grouped.setdefault(row.trade_date, []).append(row)
    return {key: tuple(value) for key, value in sorted(grouped.items())}


def _value_diagnostic_row(
    *,
    factor_row: ResearchFactorValueDailyRow,
    run_id: str,
    contexts: tuple[_WarningContext, ...],
) -> ResearchFactorDiagnosticDailyRow:
    value = (
        factor_row.processed_value
        if factor_row.processed_value is not None
        else factor_row.raw_value
    )
    state = _signal_state(value)
    return ResearchFactorDiagnosticDailyRow(
        run_id=run_id,
        factor_id=factor_row.factor_id,
        factor_version=factor_row.factor_version,
        product_code=factor_row.product_code,
        universe=factor_row.universe,
        signal_object_id=factor_row.signal_object_id,
        trade_date=factor_row.trade_date,
        raw_value=factor_row.raw_value,
        processed_value=factor_row.processed_value,
        signal_state=state,
        diagnostic_reason=_diagnostic_reason(state=state, value=value),
        warning_flags=_warning_flags(contexts),
        human_review_required=_review_fields(contexts),
        diagnostic_rule_version=DIAGNOSTIC_RULE_VERSION,
        input_snapshot_ids=factor_row.input_snapshot_ids,
    )


def _missing_factor_row(
    *,
    factor_id: str,
    factor_version: str,
    trade_date: date,
    run_id: str,
    contexts: tuple[_WarningContext, ...],
    input_snapshot_ids: tuple[str, ...],
) -> ResearchFactorDiagnosticDailyRow:
    warning_flags = _unique_values(["R14_MISSING_FACTOR_VALUE", *_warning_flags(contexts)])
    return ResearchFactorDiagnosticDailyRow(
        run_id=run_id,
        factor_id=factor_id,
        factor_version=factor_version,
        product_code=PRODUCT_CODE,
        universe=UNIVERSE,
        signal_object_id=SIGNAL_OBJECT_ID,
        trade_date=trade_date,
        raw_value=None,
        processed_value=None,
        signal_state="unknown",
        diagnostic_reason=f"{factor_id} missing R10 factor value; state kept unknown",
        warning_flags=warning_flags,
        human_review_required=_review_fields(contexts),
        diagnostic_rule_version=DIAGNOSTIC_RULE_VERSION,
        input_snapshot_ids=list(input_snapshot_ids),
    )


def _signal_state(value: float) -> str:
    if value > 0:
        return "long"
    if value < 0:
        return "short"
    return "neutral"


def _diagnostic_reason(*, state: str, value: float) -> str:
    if state == "long":
        return (
            f"factor value {value:.12g} is positive under R14 sign heuristic; "
            "thresholds require human review"
        )
    if state == "short":
        return (
            f"factor value {value:.12g} is negative under R14 sign heuristic; "
            "thresholds require human review"
        )
    return (
        f"factor value {value:.12g} is zero under R14 sign heuristic; "
        "thresholds require human review"
    )


def _factor_versions() -> dict[str, str]:
    registry = load_factor_registry()
    return {factor_id: registry.get(factor_id).version for factor_id in EXPECTED_FACTOR_IDS}


def _load_warning_contexts(
    *,
    csv_path: Path,
) -> dict[tuple[str, date | None], tuple[_WarningContext, ...]]:
    if not csv_path.exists():
        return {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        grouped: dict[tuple[str, date | None], list[_WarningContext]] = {}
        for row in reader:
            normalized = {column: row.get(column, "") or "" for column in WARNING_COLUMNS}
            factor_id = normalized["factor_id"]
            if not factor_id:
                continue
            trade_date = (
                date.fromisoformat(normalized["trade_date"])
                if normalized["trade_date"]
                else None
            )
            key = (factor_id, trade_date)
            grouped.setdefault(key, []).append(
                _WarningContext(
                    warning_code=normalized["warning_code"],
                    human_review_required=_split_semicolon(
                        normalized["human_review_required"]
                    ),
                    input_snapshot_ids=_split_semicolon(normalized["input_snapshot_ids"]),
                )
            )
    return {key: tuple(value) for key, value in grouped.items()}


def _contexts_for(
    *,
    warning_contexts: dict[tuple[str, date | None], tuple[_WarningContext, ...]],
    factor_id: str,
    trade_date: date,
) -> tuple[_WarningContext, ...]:
    return (
        *warning_contexts.get((factor_id, None), ()),
        *warning_contexts.get((factor_id, trade_date), ()),
    )


def _warning_flags(contexts: tuple[_WarningContext, ...]) -> list[str]:
    return _unique_values(context.warning_code for context in contexts if context.warning_code)


def _review_fields(contexts: tuple[_WarningContext, ...]) -> list[str]:
    fields = [
        *FACTOR_THRESHOLD_REVIEW_FIELDS,
        *(
            item
            for context in contexts
            for item in context.human_review_required
            if item
        ),
    ]
    return _unique_values(fields)


def _human_review_required(rows: tuple[ResearchFactorDiagnosticDailyRow, ...]) -> tuple[str, ...]:
    return tuple(
        _unique_values(
            item for row in rows for item in row.human_review_required if item
        )
    )


def _state_counts(rows: tuple[ResearchFactorDiagnosticDailyRow, ...]) -> dict[str, int]:
    counts = {"long": 0, "short": 0, "neutral": 0, "unknown": 0}
    for row in rows:
        counts[row.signal_state] += 1
    return counts


def _write_diagnostic_artifacts(
    *,
    rows: tuple[ResearchFactorDiagnosticDailyRow, ...],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    frame = pd.DataFrame(
        [row.model_dump(mode="json") for row in rows],
        columns=list(schema_for_table(FACTOR_DIAGNOSTIC_TABLE).model_fields),
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_markdown(
    *,
    markdown_path: Path,
    result: ResearchFactorDiagnosticsBuildResult,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Factor Diagnostics - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Run ID: `{result.run_id}`",
        f"- Rows: `{len(result.rows)}`",
        f"- State counts: `{result.state_counts}`",
        f"- Missing factor rows: `{result.missing_factor_count}`",
        f"- Diagnostic parquet: `{result.diagnostic_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Research Boundary",
        "",
        "R14 maps signed factor values into daily diagnostic states using an MVP "
        "sign heuristic. The rows are research diagnostics for analyst review, "
        "not execution instructions. Final thresholds and direction mapping remain "
        "human-review items.",
        "",
        "## Human Review Required",
        "",
    ]
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    lines.extend(["", "## State Counts", ""])
    for state, count in result.state_counts.items():
        lines.append(f"- `{state}`: `{count}`")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "diagnostic_parquet": root / f"{stem}_factor_diagnostic_daily.parquet",
        "diagnostic_csv": root / f"{stem}_factor_diagnostic_daily.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_factor_diagnostics"
    return root / f"{stem}.md"


def _default_factor_value_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_{FACTOR_VALUE_TABLE.removeprefix('research_')}.parquet"


def _default_warning_csv_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_factor_warnings.csv"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r14_diagnostics_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if key == "input_snapshot_ids" and value is not None:
            cleaned[key] = _coerce_snapshot_ids(value)
        elif _is_missing(value):
            cleaned[key] = None
        elif key == "trade_date":
            cleaned[key] = pd.to_datetime(value).date()
        else:
            cleaned[key] = value
    return cleaned


def _coerce_snapshot_ids(value: object) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    return [str(item) for item in value]  # type: ignore[union-attr]


def _is_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict)):
        return False
    return bool(pd.isna(value))


def _split_semicolon(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split(";") if item)


def _unique_snapshot_ids(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(_unique_values(str(item) for item in values))


def _unique_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
