"""R09 research-mode CF continuous price artifacts."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ContinuousPriceError, ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreQuoteDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.research import build_continuous_price
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
SIGNAL_OBJECT_ID = "CF.C1"
CONTINUOUS_OUTPUT_DIR = "continuous"
MAPPING_OUTPUT_DIR = "mapping"


@dataclass(frozen=True)
class ResearchContinuousBuildResult:
    """Result of building R09 continuous price artifacts."""

    product_code: str
    signal_object_id: str
    start: date
    end: date
    price_field: str
    rows: tuple[ResearchContinuousPriceDailyRow, ...]
    continuous_parquet_path: Path
    continuous_csv_path: Path
    roll_diagnostics_csv_path: Path
    markdown_path: Path
    warnings: tuple[str, ...]

    @property
    def roll_count(self) -> int:
        """Return how many continuous rows are roll rows."""
        return sum(1 for row in self.rows if row.is_roll)

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "signal_object_id": self.signal_object_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "price_field": self.price_field,
            "row_count": len(self.rows),
            "roll_count": self.roll_count,
            "continuous_parquet_path": str(self.continuous_parquet_path),
            "continuous_csv_path": str(self.continuous_csv_path),
            "roll_diagnostics_csv_path": str(self.roll_diagnostics_csv_path),
            "markdown_path": str(self.markdown_path),
            "warnings": list(self.warnings),
        }


def build_cf_research_continuous(
    *,
    start: date,
    end: date,
    price_field: str = "settle",
    core_output_dir: Path | None = None,
    core_quote_path: Path | None = None,
    chain_map_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    signal_object_id: str = SIGNAL_OBJECT_ID,
) -> ResearchContinuousBuildResult:
    """Build research-mode CF continuous prices and roll diagnostics."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    if signal_object_id != SIGNAL_OBJECT_ID:
        raise ResearchWorkbenchError(
            f"unsupported signal_object_id for CF research: {signal_object_id}"
        )

    quote_path = core_quote_path or _default_core_quote_path(core_output_dir)
    chain_path = chain_map_path or _default_chain_map_path(start=start, end=end)
    quotes = _load_core_quotes(input_path=quote_path, start=start, end=end)
    chain_rows = _load_chain_rows(input_path=chain_path, start=start, end=end)

    try:
        continuous_result = build_continuous_price(
            quotes=quotes,
            chain_rows=chain_rows,
            product_code=PRODUCT_CODE,
            signal_object_id=signal_object_id,
            price_field=price_field,
        )
    except ContinuousPriceError as exc:
        raise ResearchWorkbenchError(f"cannot build R09 continuous artifacts: {exc}") from exc

    paths = _output_paths(start=start, end=end, price_field=price_field, output_dir=output_dir)
    markdown_path = _markdown_path(
        start=start,
        end=end,
        price_field=price_field,
        report_output_dir=report_output_dir,
    )
    rows = tuple(continuous_result.rows)

    # R09 连续价格仍然是 signal object 产物；真实执行继续使用 R08 trade mapping。
    _write_continuous_table(
        rows=rows,
        parquet_path=paths["continuous_parquet"],
        csv_path=paths["continuous_csv"],
    )
    _write_roll_diagnostics(rows=rows, csv_path=paths["roll_csv"])
    result = ResearchContinuousBuildResult(
        product_code=PRODUCT_CODE,
        signal_object_id=signal_object_id,
        start=start,
        end=end,
        price_field=price_field,
        rows=rows,
        continuous_parquet_path=paths["continuous_parquet"],
        continuous_csv_path=paths["continuous_csv"],
        roll_diagnostics_csv_path=paths["roll_csv"],
        markdown_path=markdown_path,
        warnings=tuple(continuous_result.warnings),
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _load_core_quotes(*, input_path: Path, start: date, end: date) -> list[CoreQuoteDailyRow]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"core quote parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"core quote table missing trade_date: {input_path}")
    selected = _date_slice(frame, start=start, end=end)
    rows: list[CoreQuoteDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreQuoteDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core quote rows for continuous build")
    return sorted(rows, key=lambda row: (row.trade_date, row.contract_code))


def _load_chain_rows(*, input_path: Path, start: date, end: date) -> list[CoreChainMapDailyRow]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"chain map parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"chain map table missing trade_date: {input_path}")
    selected = _date_slice(frame, start=start, end=end)
    rows: list[CoreChainMapDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreChainMapDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} chain map rows for continuous build")
    return sorted(rows, key=lambda row: row.trade_date)


def _write_continuous_table(
    *,
    rows: tuple[ResearchContinuousPriceDailyRow, ...],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    records = [row.model_dump(mode="json") for row in rows]
    frame = pd.DataFrame(records)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_roll_diagnostics(
    *,
    rows: tuple[ResearchContinuousPriceDailyRow, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trade_date",
        "signal_object_id",
        "roll_from_contract",
        "roll_to_contract",
        "roll_gap",
        "adjustment",
        "cumulative_adjustment",
        "chain_switch_reason",
        "input_snapshot_ids",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            if not row.is_roll:
                continue
            writer.writerow(
                {
                    "trade_date": row.trade_date.isoformat(),
                    "signal_object_id": row.signal_object_id,
                    "roll_from_contract": row.roll_from_contract or "",
                    "roll_to_contract": row.roll_to_contract or "",
                    "roll_gap": "" if row.roll_gap is None else str(row.roll_gap),
                    "adjustment": str(row.adjustment),
                    "cumulative_adjustment": str(row.cumulative_adjustment),
                    "chain_switch_reason": row.chain_switch_reason,
                    "input_snapshot_ids": ";".join(row.input_snapshot_ids),
                }
            )


def _write_markdown(*, markdown_path: Path, result: ResearchContinuousBuildResult) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    roll_rows = [row for row in result.rows if row.is_roll]
    lines = [
        f"# CF Continuous Price - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Signal object: `{result.signal_object_id}`",
        f"- Price field: `{result.price_field}`",
        f"- Rows: `{len(result.rows)}`",
        f"- Roll rows: `{result.roll_count}`",
        f"- Continuous parquet: `{result.continuous_parquet_path}`",
        f"- Roll diagnostics CSV: `{result.roll_diagnostics_csv_path}`",
        "",
        "## Roll Diagnostics",
        "",
        "| Trade Date | From | To | Roll Gap | Adjustment | Cumulative | Switch Reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if roll_rows:
        for row in roll_rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        row.trade_date.isoformat(),
                        row.roll_from_contract or "",
                        row.roll_to_contract or "",
                        "" if row.roll_gap is None else str(row.roll_gap),
                        str(row.adjustment),
                        str(row.cumulative_adjustment),
                        row.chain_switch_reason,
                    ]
                )
                + " |"
            )
    else:
        lines.append("|  |  |  |  |  |  | no roll rows |")

    lines.extend(["", "## Signal Object Boundary", ""])
    lines.append(
        "Continuous prices are signal objects only. Execution, backtest target "
        "contracts, orders, fills, and positions must continue to use R08 trade mapping."
    )
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


def _output_paths(
    *,
    start: date,
    end: date,
    price_field: str,
    output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / CONTINUOUS_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_{price_field}"
    return {
        "continuous_parquet": root / f"{stem}_continuous_price_daily.parquet",
        "continuous_csv": root / f"{stem}_continuous_price_daily.csv",
        "roll_csv": root / f"{stem}_roll_diagnostics.csv",
    }


def _markdown_path(
    *,
    start: date,
    end: date,
    price_field: str,
    report_output_dir: Path | None,
) -> Path:
    root = report_output_dir or reports_dir() / "research" / CONTINUOUS_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_{price_field}_continuous"
    return root / f"{stem}.md"


def _default_core_quote_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME


def _default_chain_map_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / MAPPING_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_chain_map_daily.parquet"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if pd.isna(value):
            cleaned[key] = None
        elif key == "trade_date":
            cleaned[key] = pd.to_datetime(value).date()
        else:
            cleaned[key] = value
    return cleaned
