"""R13 research-mode CF curve slope and OI pressure factor artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import (
    FactorError,
    ResearchWorkbenchError,
)
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    ResearchFactorValueDailyRow,
)
from cotton_factor.research import (
    FactorInputBundle,
    compute_curve_slope_factor,
    compute_oi_pressure_factor,
)
from cotton_factor.research.factors.curve_slope import CURVE_SLOPE_FACTOR_ID
from cotton_factor.research.factors.oi_pressure import OI_PRESSURE_FACTOR_ID
from cotton_factor.research_workbench.contract_universe import build_research_contract_universe
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.factor_artifacts import (
    FactorWarningRecord,
    write_factor_value_artifact,
    write_factor_warning_log,
)
from cotton_factor.research_workbench.mapping import EXCHANGE, MAPPING_OUTPUT_DIR, SIGNAL_OBJECT_ID
from cotton_factor.research_workbench.output_contracts import FACTOR_OUTPUT_DIR

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
WARNING_SEVERITY = "WARN"
CURVE_HUMAN_REVIEW_FIELDS = ("curve_slope_far_leg_rule",)
OI_HUMAN_REVIEW_FIELDS = ("oi_pressure_prior_contract_matching",)
R13_FACTOR_IDS = (CURVE_SLOPE_FACTOR_ID, OI_PRESSURE_FACTOR_ID)


@dataclass(frozen=True)
class ResearchStructureFactorsBuildResult:
    """Result of building R13 curve slope and OI pressure artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    rows: tuple[ResearchFactorValueDailyRow, ...]
    warning_records: tuple[FactorWarningRecord, ...]
    factor_parquet_path: Path
    factor_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    human_review_required: tuple[str, ...]
    curve_row_count: int
    oi_pressure_row_count: int
    chain_row_count: int
    contract_row_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": len(self.rows),
            "curve_row_count": self.curve_row_count,
            "oi_pressure_row_count": self.oi_pressure_row_count,
            "warning_count": len(self.warning_records),
            "chain_row_count": self.chain_row_count,
            "contract_row_count": self.contract_row_count,
            "factor_parquet_path": str(self.factor_parquet_path),
            "factor_csv_path": str(self.factor_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_structure_factors(
    *,
    start: date,
    end: date,
    core_output_dir: Path | None = None,
    core_quote_path: Path | None = None,
    chain_map_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    calendar_path: Path | None = None,
    run_id: str | None = None,
    signal_object_id: str = SIGNAL_OBJECT_ID,
) -> ResearchStructureFactorsBuildResult:
    """Build R13 curve slope and OI pressure rows from normalized artifacts."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    if start.year != end.year:
        raise ResearchWorkbenchError("R13 structure factors support one calendar year at a time")
    if signal_object_id != SIGNAL_OBJECT_ID:
        raise ResearchWorkbenchError(
            f"unsupported signal_object_id for CF research: {signal_object_id}"
        )

    quote_path = core_quote_path or _default_core_quote_path(core_output_dir)
    chain_path = chain_map_path or _default_chain_map_path(start=start, end=end)
    quotes = _load_core_quotes(input_path=quote_path, end=end)
    chain_rows = _load_chain_rows(input_path=chain_path, start=start, end=end)
    contracts, contract_warnings = _build_contract_rows(
        start=start,
        quotes=tuple(quote for quote in quotes if start <= quote.trade_date <= end),
        calendar_path=calendar_path,
    )
    factor_run_id = run_id or _default_run_id(start=start, end=end)

    try:
        curve_result = compute_curve_slope_factor(
            inputs=FactorInputBundle(
                tables={
                    "core_quote_daily": quotes,
                    "core_chain_map_daily": chain_rows,
                    "core_contract_master": contracts,
                }
            ),
            run_id=factor_run_id,
            product_code=PRODUCT_CODE,
            universe=UNIVERSE,
            signal_object_id=signal_object_id,
        )
        oi_result = compute_oi_pressure_factor(
            inputs=FactorInputBundle(
                tables={
                    "core_quote_daily": quotes,
                    "core_chain_map_daily": chain_rows,
                }
            ),
            run_id=factor_run_id,
            product_code=PRODUCT_CODE,
            universe=UNIVERSE,
            signal_object_id=signal_object_id,
        )
    except FactorError as exc:
        raise ResearchWorkbenchError(f"cannot build R13 structure factor artifacts: {exc}") from exc

    curve_rows = tuple(row for row in curve_result.rows if start <= row.trade_date <= end)
    oi_rows = tuple(row for row in oi_result.rows if start <= row.trade_date <= end)
    rows = (*curve_rows, *oi_rows)
    human_review_required = _human_review_required(
        curve_result.definition.human_review_required,
        oi_result.definition.human_review_required,
    )
    warning_records = tuple(
        _warning_records(
            run_id=factor_run_id,
            contract_warnings=contract_warnings,
            curve_warnings=curve_result.warnings,
            oi_warnings=oi_result.warnings,
            human_review_required=human_review_required,
            rows=rows,
            quotes=quotes,
            chain_rows=chain_rows,
            start=start,
            end=end,
        )
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R13 只接入两个结构类因子输出；缺失输入必须进入 warning，不能静默补 0。
    write_factor_value_artifact(
        rows=rows,
        parquet_path=paths["factor_parquet"],
        csv_path=paths["factor_csv"],
        replace_factor_ids=R13_FACTOR_IDS,
        start=start,
        end=end,
    )
    write_factor_warning_log(
        warnings=warning_records,
        csv_path=paths["warning_csv"],
        replace_factor_ids=R13_FACTOR_IDS,
        run_id=factor_run_id,
    )
    result = ResearchStructureFactorsBuildResult(
        product_code=PRODUCT_CODE,
        run_id=factor_run_id,
        start=start,
        end=end,
        rows=tuple(rows),
        warning_records=warning_records,
        factor_parquet_path=paths["factor_parquet"],
        factor_csv_path=paths["factor_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        human_review_required=human_review_required,
        curve_row_count=len(curve_rows),
        oi_pressure_row_count=len(oi_rows),
        chain_row_count=len(chain_rows),
        contract_row_count=len(contracts),
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _load_core_quotes(*, input_path: Path, end: date) -> tuple[CoreQuoteDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"core quote parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"core quote table missing trade_date: {input_path}")
    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[working["_trade_date_obj"] <= end].drop(columns=["_trade_date_obj"])
    if selected.empty:
        raise ResearchWorkbenchError(f"no CF core quote rows found up to {end.isoformat()}")

    rows: list[CoreQuoteDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreQuoteDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} rows found in selected core quotes")
    return tuple(sorted(rows, key=lambda row: (row.trade_date, row.contract_code)))


def _load_chain_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
) -> tuple[CoreChainMapDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"chain map parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"chain map table missing trade_date: {input_path}")
    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[
        (working["_trade_date_obj"] >= start) & (working["_trade_date_obj"] <= end)
    ].drop(columns=["_trade_date_obj"])
    if selected.empty:
        raise ResearchWorkbenchError(
            f"no CF chain map rows found from {start.isoformat()} to {end.isoformat()}"
        )

    rows: list[CoreChainMapDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreChainMapDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} rows found in selected chain map")
    return tuple(sorted(rows, key=lambda row: row.trade_date))


def _build_contract_rows(
    *,
    start: date,
    quotes: tuple[CoreQuoteDailyRow, ...],
    calendar_path: Path | None,
) -> tuple[tuple[CoreContractMasterRow, ...], tuple[str, ...]]:
    result = build_research_contract_universe(
        start=start,
        product_code=PRODUCT_CODE,
        exchange=EXCHANGE,
        quotes=quotes,
        calendar_path=calendar_path,
        context_name="R13 structure factors",
    )
    return result.contracts, result.warnings


def _warning_records(
    *,
    run_id: str,
    contract_warnings: tuple[str, ...],
    curve_warnings: list[str],
    oi_warnings: list[str],
    human_review_required: tuple[str, ...],
    rows: tuple[ResearchFactorValueDailyRow, ...],
    quotes: tuple[CoreQuoteDailyRow, ...],
    chain_rows: tuple[CoreChainMapDailyRow, ...],
    start: date,
    end: date,
) -> list[FactorWarningRecord]:
    records: list[FactorWarningRecord] = []
    input_snapshot_ids = _input_snapshot_ids(quotes=quotes, chain_rows=chain_rows)
    factor_rows_by_id = _factor_rows_by_id(rows)
    for factor_id, code, message in (
        (
            CURVE_SLOPE_FACTOR_ID,
            "CURVE_SLOPE_HUMAN_REVIEW_REQUIRED",
            "curve slope factor still has human-review fields",
        ),
        (
            OI_PRESSURE_FACTOR_ID,
            "OI_PRESSURE_HUMAN_REVIEW_REQUIRED",
            "OI pressure factor still has human-review fields",
        ),
    ):
        records.append(
            FactorWarningRecord(
                run_id=run_id,
                factor_id=factor_id,
                trade_date=None,
                severity=WARNING_SEVERITY,
                warning_code=code,
                warning_message=message,
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    for warning in [*contract_warnings, *curve_warnings]:
        records.append(
            _warning_record(
                run_id=run_id,
                factor_id=CURVE_SLOPE_FACTOR_ID,
                warning=warning,
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    for warning in oi_warnings:
        records.append(
            _warning_record(
                run_id=run_id,
                factor_id=OI_PRESSURE_FACTOR_ID,
                warning=warning,
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    for factor_id, factor_name in (
        (CURVE_SLOPE_FACTOR_ID, "curve slope"),
        (OI_PRESSURE_FACTOR_ID, "OI pressure"),
    ):
        if not factor_rows_by_id.get(factor_id):
            records.append(
                FactorWarningRecord(
                    run_id=run_id,
                    factor_id=factor_id,
                    trade_date=None,
                    severity=WARNING_SEVERITY,
                    warning_code=_no_rows_code(factor_id),
                    warning_message=(
                        f"no {factor_name} rows from {start.isoformat()} to {end.isoformat()}"
                    ),
                    human_review_required=human_review_required,
                    input_snapshot_ids=input_snapshot_ids,
                )
            )
    return _unique_warning_records(records)


def _warning_record(
    *,
    run_id: str,
    factor_id: str,
    warning: str,
    human_review_required: tuple[str, ...],
    input_snapshot_ids: tuple[str, ...],
) -> FactorWarningRecord:
    return FactorWarningRecord(
        run_id=run_id,
        factor_id=factor_id,
        trade_date=None,
        severity=WARNING_SEVERITY,
        warning_code=_warning_code(factor_id=factor_id, warning=warning),
        warning_message=warning,
        human_review_required=human_review_required,
        input_snapshot_ids=input_snapshot_ids,
    )


def _warning_code(*, factor_id: str, warning: str) -> str:
    if factor_id == CURVE_SLOPE_FACTOR_ID:
        if "mapped quote missing" in warning:
            return "CURVE_SLOPE_MAPPED_QUOTE_MISSING"
        if "mapped contract missing" in warning:
            return "CURVE_SLOPE_CONTRACT_NOT_IN_MASTER"
        if "no farther curve leg" in warning:
            return "CURVE_SLOPE_NO_FAR_LEG"
        if "TODO_REQUIRES_HUMAN_REVIEW" in warning or "human review" in warning:
            return "CURVE_SLOPE_RULE_HUMAN_REVIEW_REQUIRED"
        return "CURVE_SLOPE_FACTOR_WARNING"
    if "mapped quote missing" in warning:
        return "OI_PRESSURE_MAPPED_QUOTE_MISSING"
    if "prior-quote matching" in warning:
        return "OI_PRESSURE_NO_PRIOR_MATCH"
    return "OI_PRESSURE_FACTOR_WARNING"


def _no_rows_code(factor_id: str) -> str:
    if factor_id == CURVE_SLOPE_FACTOR_ID:
        return "CURVE_SLOPE_NO_ROWS_IN_RANGE"
    return "OI_PRESSURE_NO_ROWS_IN_RANGE"


def _human_review_required(
    curve_items: tuple[str, ...],
    oi_items: tuple[str, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    for item in [
        *curve_items,
        *oi_items,
        *CURVE_HUMAN_REVIEW_FIELDS,
        *OI_HUMAN_REVIEW_FIELDS,
    ]:
        if item not in values:
            values.append(item)
    return tuple(values)


def _input_snapshot_ids(
    *,
    quotes: tuple[CoreQuoteDailyRow, ...],
    chain_rows: tuple[CoreChainMapDailyRow, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    for chain_row in chain_rows:
        if chain_row.source_snapshot_id not in values:
            values.append(chain_row.source_snapshot_id)
    for quote in quotes:
        if quote.source_snapshot_id not in values:
            values.append(quote.source_snapshot_id)
    return tuple(values)


def _factor_rows_by_id(
    rows: tuple[ResearchFactorValueDailyRow, ...],
) -> dict[str, list[ResearchFactorValueDailyRow]]:
    grouped: dict[str, list[ResearchFactorValueDailyRow]] = {}
    for row in rows:
        grouped.setdefault(row.factor_id, []).append(row)
    return grouped


def _unique_warning_records(records: list[FactorWarningRecord]) -> list[FactorWarningRecord]:
    values: list[FactorWarningRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (record.factor_id, record.warning_code, record.warning_message)
        if key not in seen:
            values.append(record)
            seen.add(key)
    return values


def _write_markdown(
    *,
    markdown_path: Path,
    result: ResearchStructureFactorsBuildResult,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Structure Factors - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Run ID: `{result.run_id}`",
        f"- Curve slope rows: `{result.curve_row_count}`",
        f"- OI pressure rows: `{result.oi_pressure_row_count}`",
        f"- Warnings: `{len(result.warning_records)}`",
        f"- Chain rows: `{result.chain_row_count}`",
        f"- Contract rows: `{result.contract_row_count}`",
        f"- Factor parquet: `{result.factor_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Research Boundary",
        "",
        "Curve slope and OI pressure use normalized core quotes plus R08 chain mapping. "
        "Missing far-leg or prior-contract inputs remain warnings and must not be "
        "converted into zero factor values.",
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
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_structure_factors"
    return root / f"{stem}.md"


def _default_core_quote_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME


def _default_chain_map_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / MAPPING_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_chain_map_daily.parquet"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r13_structure_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"


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
