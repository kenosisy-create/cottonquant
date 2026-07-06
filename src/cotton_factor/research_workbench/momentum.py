"""R11 research-mode CF momentum factor artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import FactorError, ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import ResearchContinuousPriceDailyRow, ResearchFactorValueDailyRow
from cotton_factor.research import FactorInputBundle, compute_momentum_factor
from cotton_factor.research.factors.momentum import (
    DEFAULT_MOMENTUM_LOOKBACK_PERIODS,
    MOMENTUM_FACTOR_ID,
)
from cotton_factor.research_workbench.continuous import (
    CONTINUOUS_OUTPUT_DIR,
    SIGNAL_OBJECT_ID,
)
from cotton_factor.research_workbench.factor_artifacts import (
    FactorWarningRecord,
    write_factor_value_artifact,
    write_factor_warning_log,
)
from cotton_factor.research_workbench.output_contracts import (
    FACTOR_OUTPUT_DIR,
)

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
WARNING_SEVERITY = "WARN"


@dataclass(frozen=True)
class ResearchMomentumBuildResult:
    """Result of building R11 momentum factor artifacts."""

    product_code: str
    factor_id: str
    run_id: str
    start: date
    end: date
    price_field: str
    lookback_periods: int
    rows: tuple[ResearchFactorValueDailyRow, ...]
    warning_records: tuple[FactorWarningRecord, ...]
    factor_parquet_path: Path
    factor_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "factor_id": self.factor_id,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "price_field": self.price_field,
            "lookback_periods": self.lookback_periods,
            "row_count": len(self.rows),
            "warning_count": len(self.warning_records),
            "factor_parquet_path": str(self.factor_parquet_path),
            "factor_csv_path": str(self.factor_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_momentum_factor(
    *,
    start: date,
    end: date,
    continuous_price_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    price_field: str = "settle",
    lookback_periods: int = DEFAULT_MOMENTUM_LOOKBACK_PERIODS,
    signal_object_id: str = SIGNAL_OBJECT_ID,
) -> ResearchMomentumBuildResult:
    """Build R11 momentum factor rows and warnings from R09 continuous prices."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    if lookback_periods <= 0:
        raise ResearchWorkbenchError("lookback_periods must be > 0")
    if signal_object_id != SIGNAL_OBJECT_ID:
        raise ResearchWorkbenchError(
            f"unsupported signal_object_id for CF research: {signal_object_id}"
        )

    input_path = continuous_price_path or _default_continuous_price_path(
        start=start,
        end=end,
        price_field=price_field,
    )
    continuous_rows = _load_continuous_rows(
        input_path=input_path,
        end=end,
        price_field=price_field,
        signal_object_id=signal_object_id,
    )
    factor_run_id = run_id or _default_run_id(start=start, end=end, price_field=price_field)

    try:
        factor_result = compute_momentum_factor(
            inputs=FactorInputBundle(tables={"research_continuous_price_daily": continuous_rows}),
            run_id=factor_run_id,
            product_code=PRODUCT_CODE,
            universe=UNIVERSE,
            signal_object_id=signal_object_id,
            price_field=price_field,
            lookback_periods=lookback_periods,
        )
    except FactorError as exc:
        raise ResearchWorkbenchError(f"cannot build R11 momentum artifacts: {exc}") from exc

    rows = tuple(row for row in factor_result.rows if start <= row.trade_date <= end)
    human_review_required = tuple(factor_result.definition.human_review_required)
    warning_records = tuple(
        _warning_records(
            run_id=factor_run_id,
            warnings=factor_result.warnings,
            human_review_required=human_review_required,
            rows=rows,
        start=start,
        end=end,
        continuous_rows=continuous_rows,
        lookback_periods=lookback_periods,
    )
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R11 只把 momentum 因子接入 R10 契约；连续价格仍是信号对象，不可当成可交易合约。
    write_factor_value_artifact(
        rows=rows,
        parquet_path=paths["factor_parquet"],
        csv_path=paths["factor_csv"],
        replace_factor_ids=(MOMENTUM_FACTOR_ID,),
        start=start,
        end=end,
    )
    write_factor_warning_log(
        warnings=warning_records,
        csv_path=paths["warning_csv"],
        replace_factor_id=MOMENTUM_FACTOR_ID,
        run_id=factor_run_id,
    )
    result = ResearchMomentumBuildResult(
        product_code=PRODUCT_CODE,
        factor_id=MOMENTUM_FACTOR_ID,
        run_id=factor_run_id,
        start=start,
        end=end,
        price_field=price_field,
        lookback_periods=lookback_periods,
        rows=rows,
        warning_records=warning_records,
        factor_parquet_path=paths["factor_parquet"],
        factor_csv_path=paths["factor_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        human_review_required=human_review_required,
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _load_continuous_rows(
    *,
    input_path: Path,
    end: date,
    price_field: str,
    signal_object_id: str,
) -> tuple[ResearchContinuousPriceDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"continuous price parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"continuous price table missing trade_date: {input_path}")
    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[working["_trade_date_obj"] <= end].drop(columns=["_trade_date_obj"])

    rows: list[ResearchContinuousPriceDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if (
            str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE
            and cleaned.get("signal_object_id") == signal_object_id
            and cleaned.get("price_field") == price_field
        ):
            rows.append(ResearchContinuousPriceDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} continuous price rows for momentum")
    return tuple(sorted(rows, key=lambda row: row.trade_date))


def _warning_records(
    *,
    run_id: str,
    warnings: list[str],
    human_review_required: tuple[str, ...],
    rows: tuple[ResearchFactorValueDailyRow, ...],
    start: date,
    end: date,
    continuous_rows: tuple[ResearchContinuousPriceDailyRow, ...],
    lookback_periods: int,
) -> list[FactorWarningRecord]:
    records: list[FactorWarningRecord] = []
    input_snapshot_ids = _input_snapshot_ids(
        continuous_rows=continuous_rows,
        start=start,
        end=end,
        lookback_periods=lookback_periods,
    )
    if human_review_required:
        records.append(
            FactorWarningRecord(
                run_id=run_id,
                factor_id=MOMENTUM_FACTOR_ID,
                trade_date=None,
                severity=WARNING_SEVERITY,
                warning_code="MOMENTUM_HUMAN_REVIEW_REQUIRED",
                warning_message="momentum factor registry still has human-review fields",
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    for warning in warnings:
        records.append(
            FactorWarningRecord(
                run_id=run_id,
                factor_id=MOMENTUM_FACTOR_ID,
                trade_date=None,
                severity=WARNING_SEVERITY,
                warning_code=_warning_code(warning),
                warning_message=warning,
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    if not rows:
        records.append(
            FactorWarningRecord(
                run_id=run_id,
                factor_id=MOMENTUM_FACTOR_ID,
                trade_date=None,
                severity=WARNING_SEVERITY,
                warning_code="MOMENTUM_NO_ROWS_IN_RANGE",
                warning_message=f"no momentum rows from {start.isoformat()} to {end.isoformat()}",
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    return records


def _warning_code(warning: str) -> str:
    if "need more than" in warning:
        return "MOMENTUM_LOOKBACK_INSUFFICIENT"
    return "MOMENTUM_FACTOR_WARNING"


def _input_snapshot_ids(
    *,
    continuous_rows: tuple[ResearchContinuousPriceDailyRow, ...],
    start: date,
    end: date,
    lookback_periods: int,
) -> tuple[str, ...]:
    values: list[str] = []
    pre_start_rows = [row for row in continuous_rows if row.trade_date < start][-lookback_periods:]
    range_rows = [row for row in continuous_rows if start <= row.trade_date <= end]
    for row in [*pre_start_rows, *range_rows]:
        for snapshot_id in row.input_snapshot_ids:
            if snapshot_id not in values:
                values.append(snapshot_id)
    return tuple(values)


def _write_markdown(*, markdown_path: Path, result: ResearchMomentumBuildResult) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Momentum Factor - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Factor: `{result.factor_id}`",
        f"- Run ID: `{result.run_id}`",
        f"- Price field: `{result.price_field}`",
        f"- Lookback periods: `{result.lookback_periods}`",
        f"- Rows: `{len(result.rows)}`",
        f"- Warnings: `{len(result.warning_records)}`",
        f"- Factor parquet: `{result.factor_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Research Boundary",
        "",
        "Momentum uses adjusted continuous prices as signal objects only. "
        "Execution, target contracts, costs, and positions must continue to use "
        "real tradable contracts from mapping/backtest stages.",
        "",
        "## Human Review Required",
        "",
    ]
    if result.human_review_required:
        lines.extend(f"- `{item}`" for item in result.human_review_required)
    else:
        lines.append("- none")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "factor_parquet": root / f"{stem}_factor_value_daily.parquet",
        "factor_csv": root / f"{stem}_factor_value_daily.csv",
        "warning_csv": root / f"{stem}_factor_warnings.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / FACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_momentum_factor"
    return root / f"{stem}.md"


def _default_continuous_price_path(*, start: date, end: date, price_field: str) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / CONTINUOUS_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_{price_field}"
    return root / f"{stem}_continuous_price_daily.parquet"


def _default_run_id(*, start: date, end: date, price_field: str) -> str:
    return f"r11_momentum_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_{price_field}"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if key == "input_snapshot_ids" and value is not None:
            if isinstance(value, str):
                cleaned[key] = [item for item in value.split(";") if item]
            else:
                cleaned[key] = list(value)  # type: ignore[arg-type]
        elif pd.isna(value):
            cleaned[key] = None
        elif key == "trade_date":
            cleaned[key] = pd.to_datetime(value).date()
        else:
            cleaned[key] = value
    return cleaned
