"""R12 research-mode CF carry factor artifacts."""

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
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    ResearchFactorValueDailyRow,
)
from cotton_factor.research import FactorInputBundle, compute_carry_factor
from cotton_factor.research.factors.carry import CARRY_FACTOR_ID
from cotton_factor.research_workbench.contract_universe import build_research_contract_universe
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.factor_artifacts import (
    FactorWarningRecord,
    write_factor_value_artifact,
    write_factor_warning_log,
)
from cotton_factor.research_workbench.mapping import EXCHANGE, SIGNAL_OBJECT_ID
from cotton_factor.research_workbench.output_contracts import FACTOR_OUTPUT_DIR

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
WARNING_SEVERITY = "WARN"
CARRY_HUMAN_REVIEW_FIELDS = ("carry_tenor_rule",)


@dataclass(frozen=True)
class ResearchCarryBuildResult:
    """Result of building R12 carry factor artifacts."""

    product_code: str
    factor_id: str
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
    contract_row_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "factor_id": self.factor_id,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": len(self.rows),
            "warning_count": len(self.warning_records),
            "contract_row_count": self.contract_row_count,
            "factor_parquet_path": str(self.factor_parquet_path),
            "factor_csv_path": str(self.factor_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_carry_factor(
    *,
    start: date,
    end: date,
    core_output_dir: Path | None = None,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    calendar_path: Path | None = None,
    run_id: str | None = None,
    signal_object_id: str = SIGNAL_OBJECT_ID,
) -> ResearchCarryBuildResult:
    """Build R12 carry factor rows and warnings from normalized core quotes."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    if start.year != end.year:
        raise ResearchWorkbenchError("R12 carry currently supports one calendar year at a time")
    if signal_object_id != SIGNAL_OBJECT_ID:
        raise ResearchWorkbenchError(
            f"unsupported signal_object_id for CF research: {signal_object_id}"
        )

    quote_path = core_quote_path or _default_core_quote_path(core_output_dir)
    quotes = _load_core_quotes(input_path=quote_path, start=start, end=end)
    contracts, contract_warnings = _build_contract_rows(
        start=start,
        quotes=quotes,
        calendar_path=calendar_path,
    )
    factor_run_id = run_id or _default_run_id(start=start, end=end)

    try:
        factor_result = compute_carry_factor(
            inputs=FactorInputBundle(
                tables={
                    "core_quote_daily": quotes,
                    "core_contract_master": contracts,
                }
            ),
            run_id=factor_run_id,
            product_code=PRODUCT_CODE,
            universe=UNIVERSE,
            signal_object_id=signal_object_id,
        )
    except FactorError as exc:
        raise ResearchWorkbenchError(f"cannot build R12 carry artifacts: {exc}") from exc

    rows = tuple(row for row in factor_result.rows if start <= row.trade_date <= end)
    human_review_required = _human_review_required(factor_result.definition.human_review_required)
    warning_records = tuple(
        _warning_records(
            run_id=factor_run_id,
            factor_warnings=factor_result.warnings,
            contract_warnings=contract_warnings,
            human_review_required=human_review_required,
            rows=rows,
            quotes=quotes,
            start=start,
            end=end,
        )
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R12 只负责 carry 因子研究输出；期限和近远月规则仍然保留人审 warning。
    write_factor_value_artifact(
        rows=rows,
        parquet_path=paths["factor_parquet"],
        csv_path=paths["factor_csv"],
        replace_factor_ids=(CARRY_FACTOR_ID,),
        start=start,
        end=end,
    )
    write_factor_warning_log(
        warnings=warning_records,
        csv_path=paths["warning_csv"],
        replace_factor_id=CARRY_FACTOR_ID,
        run_id=factor_run_id,
    )
    result = ResearchCarryBuildResult(
        product_code=PRODUCT_CODE,
        factor_id=CARRY_FACTOR_ID,
        run_id=factor_run_id,
        start=start,
        end=end,
        rows=rows,
        warning_records=warning_records,
        factor_parquet_path=paths["factor_parquet"],
        factor_csv_path=paths["factor_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        human_review_required=human_review_required,
        contract_row_count=len(contracts),
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _load_core_quotes(*, input_path: Path, start: date, end: date) -> tuple[CoreQuoteDailyRow, ...]:
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
    return tuple(sorted(rows, key=lambda row: (row.trade_date, row.contract_code)))


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
        context_name="R12 carry",
    )
    return result.contracts, result.warnings


def _warning_records(
    *,
    run_id: str,
    factor_warnings: list[str],
    contract_warnings: tuple[str, ...],
    human_review_required: tuple[str, ...],
    rows: tuple[ResearchFactorValueDailyRow, ...],
    quotes: tuple[CoreQuoteDailyRow, ...],
    start: date,
    end: date,
) -> list[FactorWarningRecord]:
    records: list[FactorWarningRecord] = []
    input_snapshot_ids = _input_snapshot_ids(quotes)
    if human_review_required:
        records.append(
            FactorWarningRecord(
                run_id=run_id,
                factor_id=CARRY_FACTOR_ID,
                trade_date=None,
                severity=WARNING_SEVERITY,
                warning_code="CARRY_HUMAN_REVIEW_REQUIRED",
                warning_message="carry factor still has human-review fields",
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    for warning in [*contract_warnings, *factor_warnings]:
        records.append(
            FactorWarningRecord(
                run_id=run_id,
                factor_id=CARRY_FACTOR_ID,
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
                factor_id=CARRY_FACTOR_ID,
                trade_date=None,
                severity=WARNING_SEVERITY,
                warning_code="CARRY_NO_ROWS_IN_RANGE",
                warning_message=f"no carry rows from {start.isoformat()} to {end.isoformat()}",
                human_review_required=human_review_required,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    return _unique_warning_records(records)


def _warning_code(warning: str) -> str:
    if "fewer than two carry legs" in warning:
        return "CARRY_FEWER_THAN_TWO_LEGS"
    if "TODO_REQUIRES_HUMAN_REVIEW" in warning or "human review" in warning:
        return "CARRY_RULE_HUMAN_REVIEW_REQUIRED"
    if "not in master" in warning:
        return "CARRY_CONTRACT_NOT_IN_MASTER"
    if "settle missing" in warning:
        return "CARRY_SETTLE_MISSING"
    return "CARRY_FACTOR_WARNING"


def _human_review_required(items: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for item in [*items, *CARRY_HUMAN_REVIEW_FIELDS]:
        if item not in values:
            values.append(item)
    return tuple(values)


def _input_snapshot_ids(quotes: tuple[CoreQuoteDailyRow, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for quote in quotes:
        if quote.source_snapshot_id not in values:
            values.append(quote.source_snapshot_id)
    return tuple(values)


def _unique_warning_records(records: list[FactorWarningRecord]) -> list[FactorWarningRecord]:
    values: list[FactorWarningRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (record.factor_id, record.warning_code, record.warning_message)
        if key not in seen:
            values.append(record)
            seen.add(key)
    return values


def _write_markdown(*, markdown_path: Path, result: ResearchCarryBuildResult) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Carry Factor - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Factor: `{result.factor_id}`",
        f"- Run ID: `{result.run_id}`",
        f"- Rows: `{len(result.rows)}`",
        f"- Warnings: `{len(result.warning_records)}`",
        f"- Contract rows: `{result.contract_row_count}`",
        f"- Factor parquet: `{result.factor_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Research Boundary",
        "",
        "Carry uses normalized core quote rows and contract master rows. "
        "The near/far tenor convention is still a research assumption and "
        "must remain visible until human review closes it.",
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
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_carry_factor"
    return root / f"{stem}.md"


def _default_core_quote_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME


def _default_run_id(*, start: date, end: date) -> str:
    return f"r12_carry_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"


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
