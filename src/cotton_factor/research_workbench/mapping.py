"""R08 research-mode CF chain and trade mapping outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import (
    ChainMapError,
    ResearchWorkbenchError,
    TradeMappingError,
)
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core import build_chain_map, build_trade_mapping
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
)
from cotton_factor.research_workbench.contract_universe import build_research_contract_universe
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
SIGNAL_OBJECT_ID = "CF.C1"
MAPPING_OUTPUT_DIR = "mapping"


@dataclass(frozen=True)
class ResearchMappingBuildResult:
    """Result of building R08 research-mode mapping artifacts."""

    product_code: str
    signal_object_id: str
    start: date
    end: date
    chain_rows: tuple[CoreChainMapDailyRow, ...]
    trade_rows: tuple[CoreTradeMappingDailyRow, ...]
    chain_parquet_path: Path
    chain_csv_path: Path
    trade_parquet_path: Path
    trade_csv_path: Path
    markdown_path: Path
    warnings: tuple[str, ...]

    @property
    def blocked_trade_count(self) -> int:
        """Return how many trade rows are explicitly blocked."""
        return sum(1 for row in self.trade_rows if row.is_blocked)

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "signal_object_id": self.signal_object_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "chain_row_count": len(self.chain_rows),
            "trade_row_count": len(self.trade_rows),
            "blocked_trade_count": self.blocked_trade_count,
            "chain_parquet_path": str(self.chain_parquet_path),
            "chain_csv_path": str(self.chain_csv_path),
            "trade_parquet_path": str(self.trade_parquet_path),
            "trade_csv_path": str(self.trade_csv_path),
            "markdown_path": str(self.markdown_path),
            "warnings": list(self.warnings),
        }


def build_cf_research_mapping(
    *,
    start: date,
    end: date,
    core_output_dir: Path | None = None,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    calendar_path: Path | None = None,
    signal_object_id: str = SIGNAL_OBJECT_ID,
    ltd_buffer_days: int = 0,
    min_volume: int = 1,
) -> ResearchMappingBuildResult:
    """Build research-mode CF chain map and trade mapping files."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    if start.year != end.year:
        raise ResearchWorkbenchError("R08 mapping currently supports one calendar year at a time")
    if signal_object_id != SIGNAL_OBJECT_ID:
        raise ResearchWorkbenchError(
            f"unsupported signal_object_id for CF research: {signal_object_id}"
        )

    input_path = core_quote_path or _default_core_quote_path(core_output_dir)
    quotes = _load_core_quotes(input_path=input_path, start=start, end=end)
    try:
        contract_universe = build_research_contract_universe(
            start=start,
            product_code=PRODUCT_CODE,
            exchange=EXCHANGE,
            quotes=quotes,
            calendar_path=calendar_path,
            context_name="R08 mapping",
        )
        chain_result = build_chain_map(
            quotes=quotes,
            contracts=contract_universe.contracts,
            calendar=contract_universe.calendar,
            product_code=PRODUCT_CODE,
            signal_object_id=signal_object_id,
            ltd_buffer_days=ltd_buffer_days,
            min_volume=min_volume,
        )
        trade_result = build_trade_mapping(
            chain_rows=chain_result.rows,
            contracts=contract_universe.contracts,
            calendar=contract_universe.calendar,
            product_code=PRODUCT_CODE,
            signal_object_id=signal_object_id,
            ltd_buffer_days=ltd_buffer_days,
        )
    except (ChainMapError, TradeMappingError) as exc:
        raise ResearchWorkbenchError(f"cannot build R08 mapping artifacts: {exc}") from exc

    output_paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    chain_rows = tuple(chain_result.rows)
    trade_rows = tuple(trade_result.rows)
    warnings = tuple(
        sorted(
            set(
                list(contract_universe.warnings)
                + chain_result.warnings
                + trade_result.warnings
                + ["settlement status blocks skipped because R08 has no settlement table input"]
            )
        )
    )

    # R08 输出的是 research-mode 文件，不改变 core 层 schema，也不生成订单。
    _write_table(
        rows=chain_rows,
        parquet_path=output_paths["chain_parquet"],
        csv_path=output_paths["chain_csv"],
    )
    _write_table(
        rows=trade_rows,
        parquet_path=output_paths["trade_parquet"],
        csv_path=output_paths["trade_csv"],
    )
    result = ResearchMappingBuildResult(
        product_code=PRODUCT_CODE,
        signal_object_id=signal_object_id,
        start=start,
        end=end,
        chain_rows=chain_rows,
        trade_rows=trade_rows,
        chain_parquet_path=output_paths["chain_parquet"],
        chain_csv_path=output_paths["chain_csv"],
        trade_parquet_path=output_paths["trade_parquet"],
        trade_csv_path=output_paths["trade_csv"],
        markdown_path=markdown_path,
        warnings=warnings,
    )
    _write_mapping_markdown(markdown_path=markdown_path, result=result)
    return result


def _load_core_quotes(*, input_path: Path, start: date, end: date) -> list[CoreQuoteDailyRow]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"core quote parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"core quote table missing trade_date: {input_path}")

    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[
        (working["_trade_date_obj"] >= start) & (working["_trade_date_obj"] <= end)
    ].drop(columns=["_trade_date_obj"])
    if selected.empty:
        raise ResearchWorkbenchError(
            f"no CF core quote rows found from {start.isoformat()} to {end.isoformat()}"
        )

    rows: list[CoreQuoteDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreQuoteDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} rows found in selected core quotes")
    return sorted(rows, key=lambda row: (row.trade_date, row.contract_code))


def _write_table(
    *,
    rows: tuple[CoreChainMapDailyRow, ...] | tuple[CoreTradeMappingDailyRow, ...],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    records = [row.model_dump(mode="json") for row in rows]
    frame = pd.DataFrame(records)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_mapping_markdown(*, markdown_path: Path, result: ResearchMappingBuildResult) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    switch_counts = _value_counts(row.switch_reason for row in result.chain_rows)
    block_counts = _value_counts(row.block_reason or "not_blocked" for row in result.trade_rows)
    lines = [
        f"# CF Research Mapping - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Signal object: `{result.signal_object_id}`",
        f"- Chain rows: `{len(result.chain_rows)}`",
        f"- Trade rows: `{len(result.trade_rows)}`",
        f"- Blocked trade rows: `{result.blocked_trade_count}`",
        f"- Chain parquet: `{result.chain_parquet_path}`",
        f"- Trade parquet: `{result.trade_parquet_path}`",
        "",
        "## Switch Reasons",
        "",
    ]
    lines.extend(f"- `{key}`: `{value}`" for key, value in switch_counts.items())
    lines.extend(["", "## Trade Block Reasons", ""])
    lines.extend(f"- `{key}`: `{value}`" for key, value in block_counts.items())
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in result.warnings)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / MAPPING_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "chain_parquet": root / f"{stem}_chain_map_daily.parquet",
        "chain_csv": root / f"{stem}_chain_map_daily.csv",
        "trade_parquet": root / f"{stem}_trade_mapping_daily.parquet",
        "trade_csv": root / f"{stem}_trade_mapping_daily.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / MAPPING_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_mapping"
    return root / f"{stem}.md"


def _default_core_quote_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME


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


def _value_counts(values: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
