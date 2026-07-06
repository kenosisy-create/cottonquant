"""R15 research-mode CF forward return artifacts."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ForwardReturnError, ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchForwardReturnDailyRow,
    schema_for_table,
)
from cotton_factor.research import build_forward_returns
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.mapping import MAPPING_OUTPUT_DIR, SIGNAL_OBJECT_ID

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
RETURNS_OUTPUT_DIR = "returns"
FORWARD_RETURN_TABLE = "research_forward_return_daily"
WARNING_SEVERITY = "WARN"
FORWARD_RETURN_HUMAN_REVIEW_FIELDS = (
    "forward_return_horizon_set",
    "forward_return_price_basis",
)

WARNING_COLUMNS = [
    "run_id",
    "horizon",
    "trade_date",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
    "input_snapshot_ids",
]


@dataclass(frozen=True)
class ForwardReturnWarningRecord:
    """Warning row for R15 forward-return artifacts."""

    run_id: str
    horizon: int
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
            "horizon": str(self.horizon),
            "trade_date": "" if self.trade_date is None else self.trade_date.isoformat(),
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


@dataclass(frozen=True)
class ResearchForwardReturnsBuildResult:
    """Result of building R15 forward return artifacts."""

    product_code: str
    signal_object_id: str
    run_id: str
    start: date
    end: date
    horizons: tuple[int, ...]
    entry_price_field: str
    exit_price_field: str
    rows: tuple[ResearchForwardReturnDailyRow, ...]
    warning_records: tuple[ForwardReturnWarningRecord, ...]
    forward_return_parquet_path: Path
    forward_return_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    trade_mapping_path: Path
    core_quote_path: Path
    human_review_required: tuple[str, ...]

    @property
    def row_count_by_horizon(self) -> dict[int, int]:
        """Return output row counts by horizon."""
        counts = {horizon: 0 for horizon in self.horizons}
        for row in self.rows:
            counts[row.horizon] = counts.get(row.horizon, 0) + 1
        return counts

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "signal_object_id": self.signal_object_id,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "horizons": list(self.horizons),
            "entry_price_field": self.entry_price_field,
            "exit_price_field": self.exit_price_field,
            "row_count": len(self.rows),
            "row_count_by_horizon": {
                str(horizon): count for horizon, count in self.row_count_by_horizon.items()
            },
            "warning_count": len(self.warning_records),
            "forward_return_parquet_path": str(self.forward_return_parquet_path),
            "forward_return_csv_path": str(self.forward_return_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "trade_mapping_path": str(self.trade_mapping_path),
            "core_quote_path": str(self.core_quote_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_forward_returns(
    *,
    start: date,
    end: date,
    horizons: tuple[int, ...] = (1, 3, 5),
    core_output_dir: Path | None = None,
    core_quote_path: Path | None = None,
    trade_mapping_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    signal_object_id: str = SIGNAL_OBJECT_ID,
    entry_price_field: str = "settle",
    exit_price_field: str = "settle",
) -> ResearchForwardReturnsBuildResult:
    """Build R15 forward-return labels from R08 trade mapping and core quotes."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    normalized_horizons = _normalize_horizons(horizons)
    if signal_object_id != SIGNAL_OBJECT_ID:
        raise ResearchWorkbenchError(
            f"unsupported signal_object_id for CF research: {signal_object_id}"
        )

    quote_path = core_quote_path or _default_core_quote_path(core_output_dir)
    mapping_path = trade_mapping_path or _default_trade_mapping_path(start=start, end=end)
    trade_rows = _load_trade_mapping_rows(input_path=mapping_path, start=start, end=end)
    quote_rows = _load_core_quote_rows(input_path=quote_path, start=start)
    forward_run_id = run_id or _default_run_id(start=start, end=end)

    rows: list[ResearchForwardReturnDailyRow] = []
    warnings: list[ForwardReturnWarningRecord] = []
    for horizon in normalized_horizons:
        try:
            result = build_forward_returns(
                trade_mappings=trade_rows,
                quotes=quote_rows,
                run_id=forward_run_id,
                product_code=PRODUCT_CODE,
                universe=UNIVERSE,
                signal_object_id=signal_object_id,
                horizon=horizon,
                entry_price_field=entry_price_field,
                exit_price_field=exit_price_field,
            )
        except ForwardReturnError as exc:
            raise ResearchWorkbenchError(
                f"cannot build R15 forward returns for horizon {horizon}: {exc}"
            ) from exc
        rows.extend(result.rows)
        warnings.extend(
            _warning_records(
                run_id=forward_run_id,
                horizon=horizon,
                warnings=result.warnings,
                trade_rows=trade_rows,
            )
        )

    rows_tuple = tuple(sorted(rows, key=lambda row: (row.trade_date, row.horizon)))
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R15 forward return 是历史评估标签，不是信号，也不是交易指令；
    # 入口必须来自 R08 真实合约 trade mapping。
    _write_forward_return_table(
        rows=rows_tuple,
        parquet_path=paths["forward_parquet"],
        csv_path=paths["forward_csv"],
    )
    _write_warning_csv(warnings=tuple(warnings), csv_path=paths["warning_csv"])
    result = ResearchForwardReturnsBuildResult(
        product_code=PRODUCT_CODE,
        signal_object_id=signal_object_id,
        run_id=forward_run_id,
        start=start,
        end=end,
        horizons=normalized_horizons,
        entry_price_field=entry_price_field,
        exit_price_field=exit_price_field,
        rows=rows_tuple,
        warning_records=tuple(warnings),
        forward_return_parquet_path=paths["forward_parquet"],
        forward_return_csv_path=paths["forward_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        trade_mapping_path=mapping_path,
        core_quote_path=quote_path,
        human_review_required=FORWARD_RETURN_HUMAN_REVIEW_FIELDS,
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _normalize_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    if not horizons:
        raise ResearchWorkbenchError("at least one horizon is required")
    values = tuple(sorted(set(horizons)))
    invalid = [horizon for horizon in values if horizon <= 0]
    if invalid:
        raise ResearchWorkbenchError(f"horizons must be positive integers: {invalid}")
    return values


def _load_trade_mapping_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
) -> tuple[CoreTradeMappingDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"trade mapping parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"trade mapping table missing trade_date: {input_path}")
    selected = _date_slice(frame, start=start, end=end, date_column="trade_date")
    rows: list[CoreTradeMappingDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreTradeMappingDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} trade mapping rows from {start.isoformat()} to "
            f"{end.isoformat()}"
        )
    return tuple(sorted(rows, key=lambda row: row.trade_date))


def _load_core_quote_rows(
    *,
    input_path: Path,
    start: date,
) -> tuple[CoreQuoteDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"core quote parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"core quote table missing trade_date: {input_path}")
    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[working["_trade_date_obj"] >= start].drop(columns=["_trade_date_obj"])
    rows: list[CoreQuoteDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreQuoteDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core quote rows from {start.isoformat()}")
    return tuple(sorted(rows, key=lambda row: (row.trade_date, row.contract_code)))


def _warning_records(
    *,
    run_id: str,
    horizon: int,
    warnings: list[str],
    trade_rows: tuple[CoreTradeMappingDailyRow, ...],
) -> list[ForwardReturnWarningRecord]:
    records: list[ForwardReturnWarningRecord] = []
    snapshot_ids_by_date = {
        row.trade_date: (row.source_snapshot_id,)
        for row in trade_rows
        if row.source_snapshot_id
    }
    all_mapping_snapshot_ids = _unique_values(
        row.source_snapshot_id for row in trade_rows if row.source_snapshot_id
    )
    for warning in warnings:
        warning_date = _date_prefix(warning)
        records.append(
            ForwardReturnWarningRecord(
                run_id=run_id,
                horizon=horizon,
                trade_date=warning_date,
                severity=WARNING_SEVERITY,
                warning_code=_warning_code(warning),
                warning_message=warning,
                human_review_required=FORWARD_RETURN_HUMAN_REVIEW_FIELDS,
                input_snapshot_ids=tuple(
                    snapshot_ids_by_date.get(warning_date, tuple(all_mapping_snapshot_ids))
                ),
            )
        )
    return _unique_warning_records(records)


def _warning_code(warning: str) -> str:
    if "trade mapping is blocked" in warning:
        return "FORWARD_RETURN_BLOCKED_MAPPING"
    if "missing target_contract" in warning:
        return "FORWARD_RETURN_TARGET_CONTRACT_MISSING"
    if "entry quote missing" in warning:
        return "FORWARD_RETURN_ENTRY_QUOTE_MISSING"
    if "exit quote missing" in warning:
        return "FORWARD_RETURN_EXIT_QUOTE_MISSING"
    if "produced no rows" in warning:
        return "FORWARD_RETURN_NO_ROWS"
    return "FORWARD_RETURN_WARNING"


def _date_prefix(value: str) -> date | None:
    prefix = value.split(":", 1)[0]
    try:
        return date.fromisoformat(prefix)
    except ValueError:
        return None


def _write_forward_return_table(
    *,
    rows: tuple[ResearchForwardReturnDailyRow, ...],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    frame = pd.DataFrame(
        [row.model_dump(mode="json") for row in rows],
        columns=list(schema_for_table(FORWARD_RETURN_TABLE).model_fields),
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[ForwardReturnWarningRecord, ...],
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
    result: ResearchForwardReturnsBuildResult,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Forward Returns - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Signal object: `{result.signal_object_id}`",
        f"- Run ID: `{result.run_id}`",
        f"- Horizons: `{', '.join(str(horizon) for horizon in result.horizons)}`",
        f"- Entry price field: `{result.entry_price_field}`",
        f"- Exit price field: `{result.exit_price_field}`",
        f"- Rows: `{len(result.rows)}`",
        f"- Warnings: `{len(result.warning_records)}`",
        f"- Forward return parquet: `{result.forward_return_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Row Counts By Horizon",
        "",
    ]
    lines.extend(
        f"- `{horizon}`: `{count}`"
        for horizon, count in result.row_count_by_horizon.items()
    )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "Forward returns are historical evaluation labels. They are built from R08 "
            "trade mapping so entry contracts are real tradable contracts and "
            "execution dates stay after the signal date. They must not be used as "
            "same-day signal inputs.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _date_slice(
    frame: pd.DataFrame,
    *,
    start: date,
    end: date,
    date_column: str,
) -> pd.DataFrame:
    working = frame.copy()
    working["_date_obj"] = pd.to_datetime(working[date_column]).dt.date
    selected = working.loc[
        (working["_date_obj"] >= start) & (working["_date_obj"] <= end)
    ].drop(columns=["_date_obj"])
    if selected.empty:
        raise ResearchWorkbenchError(
            f"no rows found from {start.isoformat()} to {end.isoformat()}"
        )
    return selected


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / RETURNS_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "forward_parquet": root / f"{stem}_forward_return_daily.parquet",
        "forward_csv": root / f"{stem}_forward_return_daily.csv",
        "warning_csv": root / f"{stem}_forward_return_warnings.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / RETURNS_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_forward_returns"
    return root / f"{stem}.md"


def _default_core_quote_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME


def _default_trade_mapping_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / MAPPING_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_trade_mapping_daily.parquet"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r15_forward_returns_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if _is_missing(value):
            cleaned[key] = None
        elif key in {"trade_date", "execution_date", "exit_date"}:
            cleaned[key] = pd.to_datetime(value).date()
        else:
            cleaned[key] = value
    return cleaned


def _is_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict)):
        return False
    return bool(pd.isna(value))


def _unique_warning_records(
    records: list[ForwardReturnWarningRecord],
) -> list[ForwardReturnWarningRecord]:
    values: list[ForwardReturnWarningRecord] = []
    seen: set[tuple[int, date | None, str, str]] = set()
    for record in records:
        key = (record.horizon, record.trade_date, record.warning_code, record.warning_message)
        if key not in seen:
            values.append(record)
            seen.add(key)
    return values


def _unique_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
