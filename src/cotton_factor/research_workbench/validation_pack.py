"""Post-R22 runnable validation pack for the CF research workbench."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import project_root
from cotton_factor.common.time import utc_now
from cotton_factor.core import official_calendar_path
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.research_workbench.expansion_gate import build_cf_expansion_gate
from cotton_factor.research_workbench.pipeline import build_cf_daily_research_pipeline
from cotton_factor.research_workbench.replay import replay_cf_research_pipeline_outputs

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
DEFAULT_START = date(2024, 1, 22)
DEFAULT_TRADE_DATE = date(2024, 1, 31)
DEFAULT_END = date(2024, 1, 31)
DEFAULT_HORIZONS = (1,)
DEFAULT_LOOKBACK_PERIODS = 3
DEFAULT_SCENARIO_COST_BPS = {
    "no_cost": 0.0,
    "normal_cost": 5.0,
    "conservative_cost": 10.0,
}
VALIDATION_DIR_NAME = "post_r22_cf_validation"


@dataclass(frozen=True)
class PostR22ValidationPackResult:
    """Result of a post-R22 runnable validation pack."""

    product_code: str
    run_id: str
    status: str
    trade_date: date
    start: date
    end: date
    run_root: Path
    input_path: Path
    preloaded_core_quote_path: Path
    pipeline_json_path: Path
    pipeline_markdown_path: Path
    replay_json_path: Path
    replay_markdown_path: Path
    expansion_gate_json_path: Path
    expansion_gate_markdown_path: Path
    summary_json_path: Path
    summary_markdown_path: Path
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the validation pack reached all post-R22 checks."""
        return self.status == "PASSED_WITH_HUMAN_REVIEW"

    def to_summary(self) -> dict[str, object]:
        """Return a compact JSON-serializable summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "trade_date": self.trade_date.isoformat(),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "run_root": str(self.run_root),
            "input_path": str(self.input_path),
            "preloaded_core_quote_path": str(self.preloaded_core_quote_path),
            "pipeline_json_path": str(self.pipeline_json_path),
            "pipeline_markdown_path": str(self.pipeline_markdown_path),
            "replay_json_path": str(self.replay_json_path),
            "replay_markdown_path": str(self.replay_markdown_path),
            "expansion_gate_json_path": str(self.expansion_gate_json_path),
            "expansion_gate_markdown_path": str(self.expansion_gate_markdown_path),
            "summary_json_path": str(self.summary_json_path),
            "summary_markdown_path": str(self.summary_markdown_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_post_r22_validation_pack(
    *,
    trade_date: date = DEFAULT_TRADE_DATE,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
    output_root: Path | None = None,
    run_id: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    lookback_periods: int = DEFAULT_LOOKBACK_PERIODS,
    candidate_scope: str = "POST_R22_CF_VALIDATION",
) -> PostR22ValidationPackResult:
    """Run an isolated post-R22 pack that proves the CF workbench can produce outputs."""
    _validate_window(trade_date=trade_date, start=start, end=end)
    validation_run_id = run_id or _default_run_id(trade_date)
    run_root = _run_root(output_root=output_root, run_id=validation_run_id)
    if run_root.exists():
        raise ResearchWorkbenchError(f"validation run already exists: {run_root}")
    run_root.mkdir(parents=True)

    raw_root = run_root / "raw"
    core_root = run_root / "core"
    research_root = run_root / "research"
    report_root = run_root / "reports"
    input_path = run_root / "incoming" / PRODUCT_CODE / trade_date.isoformat() / "cf_daily.csv"
    summary_dir = run_root / "reports" / VALIDATION_DIR_NAME
    summary_stem = f"{PRODUCT_CODE}_{trade_date.isoformat()}_{validation_run_id}"
    summary_json_path = summary_dir / f"{summary_stem}.json"
    summary_markdown_path = summary_dir / f"{summary_stem}.md"

    quote_rows = _validation_quote_rows(
        start=start,
        end=end,
        horizons=horizons,
        lookback_periods=lookback_periods,
    )
    current_rows = [row for row in quote_rows if row.trade_date == trade_date]
    if not current_rows:
        raise ResearchWorkbenchError(f"validation fixture has no rows for {trade_date.isoformat()}")

    # 验证包预置历史 core 行，用于模拟已有日频生产数据积累；当天数据仍必须经过 R04/R05。
    preloaded_core_path = _write_preloaded_core_history(
        core_root=core_root,
        rows=[row for row in quote_rows if row.trade_date != trade_date],
    )
    _write_daily_input_csv(input_path=input_path, rows=current_rows)

    pipeline = build_cf_daily_research_pipeline(
        trade_date=trade_date,
        input_path=input_path,
        start=start,
        end=end,
        raw_output_dir=raw_root,
        core_output_dir=core_root,
        research_output_root=research_root,
        report_output_root=report_root,
        run_id=f"{validation_run_id}_r20_pipeline",
        horizons=horizons,
        scenario_cost_bps=DEFAULT_SCENARIO_COST_BPS,
        lookback_periods=lookback_periods,
    )
    replay = replay_cf_research_pipeline_outputs(
        pipeline_json_path=pipeline.json_path,
        report_output_dir=report_root / "replay",
        run_id=f"{validation_run_id}_r21_replay",
    )
    gate = build_cf_expansion_gate(
        candidate_scope=candidate_scope,
        pipeline_json_path=pipeline.json_path,
        replay_json_path=replay.json_path,
        report_output_dir=report_root / "expansion_gate",
        run_id=f"{validation_run_id}_r22_gate",
        gate_version="R22",
    )

    status = (
        "PASSED_WITH_HUMAN_REVIEW"
        if pipeline.passed and replay.passed and gate.passed
        else "FAILED"
    )
    result = PostR22ValidationPackResult(
        product_code=PRODUCT_CODE,
        run_id=validation_run_id,
        status=status,
        trade_date=trade_date,
        start=start,
        end=end,
        run_root=run_root,
        input_path=input_path,
        preloaded_core_quote_path=preloaded_core_path,
        pipeline_json_path=pipeline.json_path,
        pipeline_markdown_path=pipeline.markdown_path,
        replay_json_path=replay.json_path,
        replay_markdown_path=replay.markdown_path,
        expansion_gate_json_path=gate.json_path,
        expansion_gate_markdown_path=gate.markdown_path,
        summary_json_path=summary_json_path,
        summary_markdown_path=summary_markdown_path,
        human_review_required=_human_review_required(
            list(pipeline.human_review_required)
            + list(gate.human_review_required)
            + ["real_cf_data_source_permission", "official_exchange_field_interpretation"]
        ),
    )
    _write_summary_json(result=result)
    _write_summary_markdown(result=result)
    return result


def _validate_window(*, trade_date: date, start: date, end: date) -> None:
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    if not (start <= trade_date <= end):
        raise ResearchWorkbenchError("trade_date must be inside start/end window")
    if start.year != end.year:
        raise ResearchWorkbenchError("post-R22 validation pack currently supports one year")


def _run_root(*, output_root: Path | None, run_id: str) -> Path:
    root = output_root or project_root() / "runs" / "codex" / VALIDATION_DIR_NAME
    return root / run_id


def _validation_quote_rows(
    *,
    start: date,
    end: date,
    horizons: tuple[int, ...],
    lookback_periods: int,
) -> list[CoreQuoteDailyRow]:
    if lookback_periods <= 0:
        raise ResearchWorkbenchError("lookback_periods must be > 0")
    horizon_tail_days = max(horizons or (1,)) + 3
    calendar_start = start - timedelta(days=max(lookback_periods * 3, 10))
    calendar_end = end + timedelta(days=horizon_tail_days * 3)
    trading_dates = _official_trading_dates(start=calendar_start, end=calendar_end)
    rows: list[CoreQuoteDailyRow] = []
    for index, trade_date in enumerate(trading_dates):
        rows.extend(_quote_rows_for_date(trade_date=trade_date, index=index))
    return rows


def _official_trading_dates(*, start: date, end: date) -> list[date]:
    calendar_path = official_calendar_path(exchange=EXCHANGE, year=start.year)
    if start.year != end.year:
        raise ResearchWorkbenchError("validation calendar window must stay in one year")
    if not calendar_path.exists():
        raise ResearchWorkbenchError(f"official calendar not found: {calendar_path}")
    dates: list[date] = []
    with calendar_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            trade_date = date.fromisoformat(str(row["trade_date"]))
            if start <= trade_date <= end and str(row["is_trading_day"]).lower() == "true":
                dates.append(trade_date)
    if not dates:
        raise ResearchWorkbenchError(f"no official trading dates from {start} to {end}")
    return dates


def _quote_rows_for_date(*, trade_date: date, index: int) -> list[CoreQuoteDailyRow]:
    main_settle = 15100.0 + index * 12.0
    far_settle = 15320.0 + index * 8.0
    return [
        _quote_row(
            trade_date=trade_date,
            contract_code="CF405",
            settle=main_settle,
            pre_settle=main_settle - 10.0,
            volume=2200 + index * 20,
            open_interest=7200 + index * 30,
            snapshot_suffix="main",
        ),
        _quote_row(
            trade_date=trade_date,
            contract_code="CF409",
            settle=far_settle,
            pre_settle=far_settle - 8.0,
            volume=1300 + index * 12,
            open_interest=5100 + index * 36,
            snapshot_suffix="far",
        ),
    ]


def _quote_row(
    *,
    trade_date: date,
    contract_code: str,
    settle: float,
    pre_settle: float,
    volume: int,
    open_interest: int,
    snapshot_suffix: str,
) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"post_r22_validation:{trade_date.isoformat()}:{snapshot_suffix}",
        exchange=EXCHANGE,
        product_code=PRODUCT_CODE,
        contract_code=contract_code,
        trade_date=trade_date,
        open=settle - 30.0,
        high=settle + 60.0,
        low=settle - 80.0,
        close=settle + 12.0,
        settle=settle,
        pre_settle=pre_settle,
        volume=volume,
        open_interest=open_interest,
        turnover=volume * settle * 5.0,
        quote_status="normal",
    )


def _write_preloaded_core_history(*, core_root: Path, rows: list[CoreQuoteDailyRow]) -> Path:
    path = core_root / PRODUCT_CODE / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row.model_dump(mode="json") for row in rows])
    frame.to_parquet(path, index=False)
    return path


def _write_daily_input_csv(*, input_path: Path, rows: list[CoreQuoteDailyRow]) -> None:
    input_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trade_date",
        "exchange",
        "product_code",
        "contract_id",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "pre_settle",
        "volume",
        "open_interest",
        "turnover",
        "quote_status",
    ]
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = row.model_dump(mode="json")
            writer.writerow(
                {
                    "trade_date": payload["trade_date"],
                    "exchange": payload["exchange"],
                    "product_code": payload["product_code"],
                    "contract_id": payload["contract_code"],
                    "open": payload["open"],
                    "high": payload["high"],
                    "low": payload["low"],
                    "close": payload["close"],
                    "settle": payload["settle"],
                    "pre_settle": payload["pre_settle"],
                    "volume": payload["volume"],
                    "open_interest": payload["open_interest"],
                    "turnover": payload["turnover"],
                    "quote_status": payload["quote_status"],
                }
            )


def _human_review_required(items: list[str]) -> tuple[str, ...]:
    values: list[str] = []
    for item in items:
        if item and item not in values:
            values.append(item)
    return tuple(values)


def _write_summary_json(*, result: PostR22ValidationPackResult) -> None:
    result.summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    result.summary_json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_summary_markdown(*, result: PostR22ValidationPackResult) -> None:
    result.summary_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Post-R22 CF Validation Pack - {result.trade_date.isoformat()}",
        "",
        f"- Status: `{result.status}`",
        f"- Run ID: `{result.run_id}`",
        f"- Window: `{result.start.isoformat()} -> {result.end.isoformat()}`",
        f"- Run root: `{result.run_root}`",
        "",
        "## Evidence",
        "",
        f"- Daily input CSV: `{result.input_path}`",
        f"- Preloaded core history: `{result.preloaded_core_quote_path}`",
        f"- R20 pipeline JSON: `{result.pipeline_json_path}`",
        f"- R21 replay JSON: `{result.replay_json_path}`",
        f"- R22 expansion gate JSON: `{result.expansion_gate_json_path}`",
        "",
        "## Boundary",
        "",
        "This pack proves the local CF research workbench can run and produce "
        "inspectable artifacts in an isolated folder. It uses generated "
        "production-like sample data; it is not proof that a real exchange data "
        "source has been permissioned or reviewed.",
        "",
        "## Human Review Required",
        "",
    ]
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.summary_markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _default_run_id(trade_date: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    return f"post_r22_cf_{trade_date.isoformat()}_{timestamp}_{uuid.uuid4().hex[:8]}"
