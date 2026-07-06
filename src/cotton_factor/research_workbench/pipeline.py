"""R20 one-command CF research pipeline."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.carry import build_cf_carry_factor
from cotton_factor.research_workbench.continuous import (
    CONTINUOUS_OUTPUT_DIR,
    build_cf_research_continuous,
)
from cotton_factor.research_workbench.contract_review import build_cf_contract_rule_review
from cotton_factor.research_workbench.core_quotes import normalize_cf_core_quotes
from cotton_factor.research_workbench.cost_sensitivity import (
    COST_SENSITIVITY_OUTPUT_DIR,
    build_cf_cost_sensitivity,
)
from cotton_factor.research_workbench.daily_brief import (
    DAILY_BRIEF_REPORT_DIR,
    build_cf_daily_brief,
)
from cotton_factor.research_workbench.data_quality import (
    QUALITY_REPORT_DIR,
    check_cf_data_quality,
)
from cotton_factor.research_workbench.factor_diagnostics import (
    build_cf_factor_diagnostics,
)
from cotton_factor.research_workbench.forward_returns import (
    RETURNS_OUTPUT_DIR,
    build_cf_forward_returns,
)
from cotton_factor.research_workbench.mapping import (
    MAPPING_OUTPUT_DIR,
    build_cf_research_mapping,
)
from cotton_factor.research_workbench.momentum import build_cf_momentum_factor
from cotton_factor.research_workbench.multifactor_diagnostics import (
    MULTIFACTOR_OUTPUT_DIR,
    build_cf_multifactor_diagnostics,
)
from cotton_factor.research_workbench.output_contracts import (
    FACTOR_IDS_BY_FAMILY,
    FACTOR_OUTPUT_DIR,
    OUTPUT_CONTRACT_DIR,
    build_cf_factor_output_contract,
)
from cotton_factor.research_workbench.raw_ingest import ingest_cf_raw
from cotton_factor.research_workbench.single_factor_backtest import (
    BACKTEST_OUTPUT_DIR,
    build_cf_single_factor_backtest,
)
from cotton_factor.research_workbench.structure_factors import build_cf_structure_factors

PRODUCT_CODE = "CF"
PIPELINE_REPORT_DIR = "pipeline"
DEFAULT_FACTOR_IDS = tuple(FACTOR_IDS_BY_FAMILY.values())


@dataclass(frozen=True)
class ResearchPipelineStep:
    """One completed R20 pipeline step."""

    task_id: str
    step_id: str
    status: str
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable step summary."""
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "status": self.status,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class ResearchDailyPipelineResult:
    """Result of running the R20 one-command daily research pipeline."""

    product_code: str
    run_id: str
    trade_date: date
    start: date
    end: date
    status: str
    steps: tuple[ResearchPipelineStep, ...]
    artifacts: dict[str, str]
    markdown_path: Path
    json_path: Path
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the pipeline reached the R19 daily brief."""
        return self.status == "COMPLETED"

    def to_summary(self) -> dict[str, Any]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "status": self.status,
            "passed": self.passed,
            "step_count": len(self.steps),
            "completed_steps": [step.step_id for step in self.steps],
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "artifacts": self.artifacts,
            "human_review_required": list(self.human_review_required),
        }


def build_cf_daily_research_pipeline(
    *,
    trade_date: date,
    input_path: Path,
    start: date | None = None,
    end: date | None = None,
    raw_output_dir: Path | None = None,
    core_output_dir: Path | None = None,
    research_output_root: Path | None = None,
    report_output_root: Path | None = None,
    run_id: str | None = None,
    horizons: tuple[int, ...] = (1, 3, 5),
    factor_ids: tuple[str, ...] = DEFAULT_FACTOR_IDS,
    scenario_cost_bps: dict[str, float] | None = None,
    price_field: str = "settle",
    lookback_periods: int = 20,
    ltd_buffer_days: int = 0,
    min_volume: int = 1,
    require_all_factors: bool = True,
    use_processed_value: bool = True,
    use_processed_score: bool = True,
) -> ResearchDailyPipelineResult:
    """Run R04-R19 in order for one CF daily research brief."""
    window_start = start or trade_date
    window_end = end or trade_date
    if window_start > window_end:
        raise ResearchWorkbenchError("start must be <= end")
    if not (window_start <= trade_date <= window_end):
        raise ResearchWorkbenchError("trade_date must be inside start/end window")
    if lookback_periods <= 0:
        raise ResearchWorkbenchError("lookback_periods must be > 0")

    pipeline_run_id = run_id or _default_run_id(trade_date)
    raw_run_id = f"{pipeline_run_id}_raw"
    steps: list[ResearchPipelineStep] = []

    # R20 只负责编排 R04-R19；每一步仍调用已有研究模块，避免在流水线里重写解析或因子逻辑。
    raw_result = ingest_cf_raw(
        trade_date=trade_date,
        input_path=input_path,
        raw_output_dir=raw_output_dir,
        run_id=raw_run_id,
    )
    _append_step(steps, task_id="R04", step_id="ingest_cf_raw", result=raw_result)

    core_result = normalize_cf_core_quotes(
        trade_date=trade_date,
        raw_output_dir=raw_output_dir,
        core_output_dir=core_output_dir,
        run_id=raw_run_id,
    )
    _append_step(steps, task_id="R05", step_id="normalize_cf_core_quotes", result=core_result)

    quality_result = check_cf_data_quality(
        trade_date=trade_date,
        core_quote_path=core_result.output_path,
        report_output_dir=_report_dir(report_output_root, QUALITY_REPORT_DIR),
    )
    _append_step(steps, task_id="R06", step_id="check_cf_data_quality", result=quality_result)
    if not quality_result.passed:
        return _finalize_result(
            run_id=pipeline_run_id,
            trade_date=trade_date,
            start=window_start,
            end=window_end,
            status="DATA_QUALITY_BLOCKED",
            steps=tuple(steps),
            report_output_root=report_output_root,
        )

    contract_review_result = build_cf_contract_rule_review(
        year=trade_date.year,
        report_output_dir=_report_dir(report_output_root, "contract_rules"),
    )
    _append_step(
        steps,
        task_id="R07",
        step_id="review_cf_contract_rules",
        result=contract_review_result,
    )

    mapping_result = build_cf_research_mapping(
        start=window_start,
        end=window_end,
        core_quote_path=core_result.output_path,
        output_dir=_research_dir(research_output_root, MAPPING_OUTPUT_DIR),
        report_output_dir=_report_dir(report_output_root, MAPPING_OUTPUT_DIR),
        ltd_buffer_days=ltd_buffer_days,
        min_volume=min_volume,
    )
    _append_step(steps, task_id="R08", step_id="build_cf_research_mapping", result=mapping_result)

    continuous_result = build_cf_research_continuous(
        start=window_start,
        end=window_end,
        price_field=price_field,
        core_quote_path=core_result.output_path,
        chain_map_path=mapping_result.chain_parquet_path,
        output_dir=_research_dir(research_output_root, CONTINUOUS_OUTPUT_DIR),
        report_output_dir=_report_dir(report_output_root, CONTINUOUS_OUTPUT_DIR),
    )
    _append_step(
        steps,
        task_id="R09",
        step_id="build_cf_research_continuous",
        result=continuous_result,
    )

    output_contract_result = build_cf_factor_output_contract(
        output_dir=_research_dir(research_output_root, OUTPUT_CONTRACT_DIR),
        report_output_dir=_report_dir(report_output_root, OUTPUT_CONTRACT_DIR),
    )
    _append_step(
        steps,
        task_id="R10",
        step_id="write_cf_factor_output_contract",
        result=output_contract_result,
    )

    factor_output_dir = _research_dir(research_output_root, FACTOR_OUTPUT_DIR)
    factor_report_dir = _report_dir(report_output_root, FACTOR_OUTPUT_DIR)
    momentum_result = build_cf_momentum_factor(
        start=window_start,
        end=window_end,
        continuous_price_path=continuous_result.continuous_parquet_path,
        output_dir=factor_output_dir,
        report_output_dir=factor_report_dir,
        run_id=f"{pipeline_run_id}_r11_momentum",
        price_field=price_field,
        lookback_periods=lookback_periods,
    )
    _append_step(steps, task_id="R11", step_id="build_cf_momentum_factor", result=momentum_result)

    carry_result = build_cf_carry_factor(
        start=window_start,
        end=window_end,
        core_quote_path=core_result.output_path,
        output_dir=factor_output_dir,
        report_output_dir=factor_report_dir,
        run_id=f"{pipeline_run_id}_r12_carry",
    )
    _append_step(steps, task_id="R12", step_id="build_cf_carry_factor", result=carry_result)

    structure_result = build_cf_structure_factors(
        start=window_start,
        end=window_end,
        core_quote_path=core_result.output_path,
        chain_map_path=mapping_result.chain_parquet_path,
        output_dir=factor_output_dir,
        report_output_dir=factor_report_dir,
        run_id=f"{pipeline_run_id}_r13_structure",
    )
    _append_step(
        steps,
        task_id="R13",
        step_id="build_cf_structure_factors",
        result=structure_result,
    )

    diagnostics_result = build_cf_factor_diagnostics(
        start=window_start,
        end=window_end,
        factor_value_path=structure_result.factor_parquet_path,
        warning_csv_path=structure_result.warning_csv_path,
        output_dir=factor_output_dir,
        report_output_dir=factor_report_dir,
        run_id=f"{pipeline_run_id}_r14_diagnostics",
    )
    _append_step(
        steps,
        task_id="R14",
        step_id="build_cf_factor_diagnostics",
        result=diagnostics_result,
    )

    forward_result = build_cf_forward_returns(
        start=window_start,
        end=window_end,
        horizons=horizons,
        core_quote_path=core_result.output_path,
        trade_mapping_path=mapping_result.trade_parquet_path,
        output_dir=_research_dir(research_output_root, RETURNS_OUTPUT_DIR),
        report_output_dir=_report_dir(report_output_root, RETURNS_OUTPUT_DIR),
        run_id=f"{pipeline_run_id}_r15_forward_returns",
    )
    _append_step(steps, task_id="R15", step_id="build_cf_forward_returns", result=forward_result)

    single_factor_result = build_cf_single_factor_backtest(
        start=window_start,
        end=window_end,
        factor_ids=factor_ids,
        horizons=horizons,
        diagnostic_path=diagnostics_result.diagnostic_parquet_path,
        forward_return_path=forward_result.forward_return_parquet_path,
        output_dir=_research_dir(research_output_root, BACKTEST_OUTPUT_DIR),
        report_output_dir=_report_dir(report_output_root, BACKTEST_OUTPUT_DIR),
        run_id=f"{pipeline_run_id}_r16_single_factor",
        use_processed_value=use_processed_value,
    )
    _append_step(
        steps,
        task_id="R16",
        step_id="run_cf_single_factor_backtest",
        result=single_factor_result,
    )

    multifactor_result = build_cf_multifactor_diagnostics(
        start=window_start,
        end=window_end,
        factor_ids=factor_ids,
        diagnostic_path=diagnostics_result.diagnostic_parquet_path,
        output_dir=_research_dir(research_output_root, MULTIFACTOR_OUTPUT_DIR),
        report_output_dir=_report_dir(report_output_root, MULTIFACTOR_OUTPUT_DIR),
        run_id=f"{pipeline_run_id}_r17_multifactor",
        use_processed_value=use_processed_value,
        require_all_factors=require_all_factors,
    )
    _append_step(
        steps,
        task_id="R17",
        step_id="build_cf_multifactor_diagnostics",
        result=multifactor_result,
    )

    cost_result = build_cf_cost_sensitivity(
        start=window_start,
        end=window_end,
        horizons=horizons,
        score_path=multifactor_result.score_parquet_path,
        forward_return_path=forward_result.forward_return_parquet_path,
        scenario_cost_bps=scenario_cost_bps,
        output_dir=_research_dir(research_output_root, COST_SENSITIVITY_OUTPUT_DIR),
        report_output_dir=_report_dir(report_output_root, COST_SENSITIVITY_OUTPUT_DIR),
        run_id=f"{pipeline_run_id}_r18_cost_sensitivity",
        use_processed_score=use_processed_score,
    )
    _append_step(steps, task_id="R18", step_id="build_cf_cost_sensitivity", result=cost_result)

    # R19 只读取前面步骤已经产出的标准化研究文件，继续保持“不直接解析交易所原始文件”的边界。
    brief_result = build_cf_daily_brief(
        trade_date=trade_date,
        start=window_start,
        end=window_end,
        quality_csv_path=quality_result.csv_path,
        chain_map_path=mapping_result.chain_parquet_path,
        trade_mapping_path=mapping_result.trade_parquet_path,
        diagnostic_path=diagnostics_result.diagnostic_parquet_path,
        single_factor_evaluation_path=single_factor_result.evaluation_parquet_path,
        multifactor_score_path=multifactor_result.score_parquet_path,
        cost_sensitivity_path=cost_result.summary_parquet_path,
        report_output_dir=_report_dir(report_output_root, DAILY_BRIEF_REPORT_DIR),
        run_id=f"{pipeline_run_id}_r19_daily_brief",
    )
    _append_step(steps, task_id="R19", step_id="build_cf_daily_brief", result=brief_result)

    return _finalize_result(
        run_id=pipeline_run_id,
        trade_date=trade_date,
        start=window_start,
        end=window_end,
        status="COMPLETED",
        steps=tuple(steps),
        report_output_root=report_output_root,
    )


def _append_step(
    steps: list[ResearchPipelineStep],
    *,
    task_id: str,
    step_id: str,
    result: Any,
) -> None:
    steps.append(
        ResearchPipelineStep(
            task_id=task_id,
            step_id=step_id,
            status="COMPLETED",
            summary=result.to_summary(),
        )
    )


def _finalize_result(
    *,
    run_id: str,
    trade_date: date,
    start: date,
    end: date,
    status: str,
    steps: tuple[ResearchPipelineStep, ...],
    report_output_root: Path | None,
) -> ResearchDailyPipelineResult:
    paths = _output_paths(
        run_id=run_id,
        trade_date=trade_date,
        report_output_root=report_output_root,
    )
    result = ResearchDailyPipelineResult(
        product_code=PRODUCT_CODE,
        run_id=run_id,
        trade_date=trade_date,
        start=start,
        end=end,
        status=status,
        steps=steps,
        artifacts=_artifact_paths(steps),
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        human_review_required=_human_review_required(steps),
    )
    _write_json(result=result)
    _write_markdown(result=result)
    return result


def _artifact_paths(steps: tuple[ResearchPipelineStep, ...]) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for step in steps:
        for key, value in step.summary.items():
            if key.endswith("_path") and isinstance(value, str):
                artifacts[f"{step.step_id}.{key}"] = value
    return artifacts


def _human_review_required(steps: tuple[ResearchPipelineStep, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for step in steps:
        raw_items = step.summary.get("human_review_required", [])
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            text = str(item)
            if text and text not in values:
                values.append(text)
    return tuple(values)


def _write_json(*, result: ResearchDailyPipelineResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "steps": [step.to_dict() for step in result.steps],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(*, result: ResearchDailyPipelineResult) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Research Pipeline - {result.trade_date.isoformat()}",
        "",
        f"- Status: `{result.status}`",
        f"- Run ID: `{result.run_id}`",
        f"- Window: `{result.start.isoformat()} -> {result.end.isoformat()}`",
        f"- Step count: `{len(result.steps)}`",
        f"- Machine-readable log: `{result.json_path}`",
        "",
        "## Steps",
        "",
        "| Task | Step | Status | Key outputs |",
        "| --- | --- | --- | --- |",
    ]
    for step in result.steps:
        output_keys = [
            key
            for key, value in step.summary.items()
            if key.endswith("_path") and isinstance(value, str)
        ]
        lines.append(
            "| "
            + " | ".join(
                [
                    step.task_id,
                    step.step_id,
                    step.status,
                    "<br>".join(f"`{key}`" for key in output_keys) or "none",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "R20 is a one-command research workflow for CF daily analysis. It does not "
            "create orders, target positions, production permissions, or platform release "
            "artifacts.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    if result.human_review_required:
        lines.extend(f"- `{item}`" for item in result.human_review_required)
    else:
        lines.append("- none")
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _research_dir(root: Path | None, child: str) -> Path | None:
    if root is None:
        return None
    return root / PRODUCT_CODE / child


def _report_dir(root: Path | None, child: str) -> Path | None:
    if root is None:
        return None
    return root / child


def _output_paths(
    *,
    run_id: str,
    trade_date: date,
    report_output_root: Path | None,
) -> dict[str, Path]:
    root = _report_dir(report_output_root, PIPELINE_REPORT_DIR) or (
        reports_dir() / "research" / PIPELINE_REPORT_DIR
    )
    stem = f"{PRODUCT_CODE}_{trade_date.isoformat()}_{run_id}_pipeline"
    return {
        "markdown": root / f"{stem}.md",
        "json": root / f"{stem}.json",
    }


def _default_run_id(trade_date: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return f"r20_pipeline_{PRODUCT_CODE}_{trade_date.isoformat()}_{timestamp}_{suffix}"
