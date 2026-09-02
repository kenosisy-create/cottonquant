"""可测试的 CF 轻量日更编排器。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError

PRODUCT_CODE = "CF"
CORE_QUOTE_PATH = Path("data/core/CF/core_quote_daily.parquet")
OPTION_CORE_PATH = Path("data/core/CF/core_option_quote_daily.parquet")


class CommandExecutor(Protocol):
    """日更步骤使用的命令执行协议，测试可替换为无副作用实现。"""

    def run(self, args: Sequence[str]) -> dict[str, Any]:
        """执行现有公共 CLI 并返回 JSON 摘要。"""


@dataclass(frozen=True)
class PythonCliExecutor:
    """通过当前 Python 解释器调用现有 cotton-factor CLI。"""

    repo_root: Path

    def run(self, args: Sequence[str]) -> dict[str, Any]:
        env = os.environ.copy()
        source_root = str(self.repo_root / "src")
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            source_root
            if not existing_pythonpath
            else os.pathsep.join((source_root, existing_pythonpath))
        )
        env["PYTHONIOENCODING"] = "utf-8"
        command = [sys.executable, "-m", "cotton_factor.cli.main", *args]
        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ResearchWorkbenchError(
                f"CLI步骤失败({completed.returncode}): {' '.join(args)}\n{detail}"
            )
        return _parse_cli_json(completed.stdout, args=args)


@dataclass(frozen=True)
class CfDailyUpdateConfig:
    """CF 轻量日更参数；重型历史研究不属于本编排器。"""

    trade_date: date
    year: int
    run_id: str
    repo_root: Path = Path(".")
    futures_source_dir: Path = Path("data/incoming/CF/history")
    options_source_dir: Path = Path("data/incoming/CF/options/history")
    core_quote_path: Path = CORE_QUOTE_PATH
    option_core_path: Path = OPTION_CORE_PATH
    output_root: Path = Path("runs/daily")
    download_official: bool = False
    include_options: bool = True
    overwrite_official: bool = False
    refresh_option_core: bool = False
    refresh_option_factors: bool = False
    run_continuity_audit: bool = True
    run_state_upgrade: bool = True
    run_daily_operation_audit: bool = False
    trend_board_lookback_days: int = 20
    build_studio_dashboard: bool = True
    build_forward_ledger: bool = True
    strategy_inputs_start: str = "2021-01-04"
    trend_rule_candidate_path: Path | None = None
    trend_quality_calibration_manifest_path: Path | None = None
    signal_threshold_research_path: Path | None = None
    option_factor_path: Path | None = None

    def __post_init__(self) -> None:
        if self.year != self.trade_date.year:
            raise ResearchWorkbenchError("year必须与trade_date年份一致")
        if not self.run_id.strip():
            raise ResearchWorkbenchError("run_id不能为空")
        if self.trend_board_lookback_days <= 0:
            raise ResearchWorkbenchError("trend_board_lookback_days必须大于0")


@dataclass(frozen=True)
class DailyUpdateStep:
    """一个有序日更步骤。"""

    step_id: str
    depends_on: tuple[str, ...]
    blocking: bool
    enabled: Callable[[DailyUpdateContext], bool]
    action: Callable[[DailyUpdateContext], dict[str, Any]]


@dataclass(frozen=True)
class DailyUpdateStepResult:
    """一个日更步骤的执行结果。"""

    step_id: str
    status: str
    blocking: bool
    depends_on: tuple[str, ...]
    elapsed_seconds: float
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "blocking": self.blocking,
            "depends_on": list(self.depends_on),
            "elapsed_seconds": self.elapsed_seconds,
            "summary": self.summary,
            "error": self.error,
        }


@dataclass
class DailyUpdateContext:
    """步骤间只通过显式上下文交换产物路径。"""

    config: CfDailyUpdateConfig
    executor: CommandExecutor
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CfDailyUpdateResult:
    """CF 轻量日更汇总。"""

    product_code: str
    run_id: str
    requested_date: date
    data_asof: date | None
    status: str
    elapsed_seconds: float
    steps: tuple[DailyUpdateStepResult, ...]
    json_path: Path
    markdown_path: Path

    @property
    def passed(self) -> bool:
        return self.status in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}

    def to_summary(self) -> dict[str, Any]:
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "requested_date": self.requested_date.isoformat(),
            "data_asof": None if self.data_asof is None else self.data_asof.isoformat(),
            "status": self.status,
            "passed": self.passed,
            "elapsed_seconds": self.elapsed_seconds,
            "step_count": len(self.steps),
            "completed_steps": [
                step.step_id for step in self.steps if step.status == "COMPLETED"
            ],
            "warning_steps": [
                step.step_id for step in self.steps if step.status == "WARNING"
            ],
            "failed_steps": [
                step.step_id for step in self.steps if step.status == "FAILED"
            ],
            "steps": [step.to_dict() for step in self.steps],
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "research_boundary": {
                "latest_signal_only_contains_forward_return_validation": False,
                "continuous_contract_is_signal_object_only": True,
                "trading_instruction": "not_a_trading_instruction",
                "human_review_required": True,
            },
        }


def run_cf_daily_update(
    config: CfDailyUpdateConfig,
    *,
    executor: CommandExecutor | None = None,
) -> CfDailyUpdateResult:
    """按依赖顺序运行 CF 默认轻量日更，并始终写出运行摘要。"""
    repo_root = config.repo_root.resolve()
    active_executor = executor or PythonCliExecutor(repo_root=repo_root)
    context = DailyUpdateContext(config=config, executor=active_executor)
    started = time.perf_counter()
    step_results = _run_ordered_steps(_daily_steps(), context)
    data_asof = _context_date(context.values.get("data_asof"))
    status = _pipeline_status(step_results)
    report_date = data_asof or config.trade_date
    report_dir = (
        _resolve_from_repo(config.output_root, repo_root)
        / PRODUCT_CODE
        / report_date.isoformat()
    )
    json_path = report_dir / "daily_update_pipeline.json"
    markdown_path = report_dir / "daily_update_pipeline.md"
    result = CfDailyUpdateResult(
        product_code=PRODUCT_CODE,
        run_id=config.run_id,
        requested_date=config.trade_date,
        data_asof=data_asof,
        status=status,
        elapsed_seconds=round(time.perf_counter() - started, 3),
        steps=tuple(step_results),
        json_path=json_path,
        markdown_path=markdown_path,
    )
    _write_pipeline_reports(result)
    return result


def _daily_steps() -> tuple[DailyUpdateStep, ...]:
    return (
        DailyUpdateStep("official_daily_fetch", (), True, _download_enabled, _fetch_official),
        DailyUpdateStep(
            "futures_core_connect", (), True, _always_enabled, _connect_futures
        ),
        DailyUpdateStep(
            "refresh_calendar_metadata",
            ("futures_core_connect",),
            True,
            _always_enabled,
            _refresh_calendar_metadata,
        ),
        DailyUpdateStep(
            "option_core_connect",
            ("refresh_calendar_metadata",),
            True,
            _option_core_enabled,
            _connect_options,
        ),
        DailyUpdateStep(
            "data_continuity_audit",
            ("refresh_calendar_metadata",),
            True,
            _continuity_enabled,
            _run_continuity_audit,
        ),
        DailyUpdateStep(
            "option_factor_proxy",
            ("refresh_calendar_metadata",),
            True,
            _option_factor_enabled,
            _build_option_factor,
        ),
        DailyUpdateStep(
            "signal_matrix",
            ("refresh_calendar_metadata",),
            True,
            _always_enabled,
            _build_signal_matrix,
        ),
        DailyUpdateStep(
            "dual_price_state",
            ("signal_matrix",),
            True,
            _state_upgrade_enabled,
            _build_dual_price_state,
        ),
        DailyUpdateStep(
            "chain_oi_structure",
            ("signal_matrix",),
            True,
            _state_upgrade_enabled,
            _build_chain_oi_structure,
        ),
        DailyUpdateStep(
            "option_structure",
            ("signal_matrix", "dual_price_state", "chain_oi_structure"),
            True,
            _option_state_upgrade_enabled,
            _build_option_structure,
        ),
        DailyUpdateStep(
            "trend_phase_v2",
            ("option_structure",),
            True,
            _option_state_upgrade_enabled,
            _build_trend_phase_v2,
        ),
        DailyUpdateStep(
            "latest_signal_brief",
            ("signal_matrix",),
            True,
            _always_enabled,
            _build_latest_signal_brief,
        ),
        DailyUpdateStep(
            "fundamental_data_status",
            ("refresh_calendar_metadata",),
            False,
            _always_enabled,
            _build_fundamental_data_status,
        ),
        DailyUpdateStep(
            "trend_continuity_board",
            ("latest_signal_brief",),
            True,
            _always_enabled,
            _build_trend_board,
        ),
        DailyUpdateStep(
            "daily_operation_audit",
            ("latest_signal_brief", "trend_continuity_board"),
            True,
            _daily_audit_enabled,
            _build_daily_audit,
        ),
        DailyUpdateStep(
            "studio_dashboard",
            ("trend_continuity_board",),
            False,
            _studio_dashboard_enabled,
            _build_studio_dashboard,
        ),
        DailyUpdateStep(
            "strategy_inputs",
            ("data_continuity_audit",),
            False,
            _forward_ledger_enabled,
            _build_strategy_inputs,
        ),
        DailyUpdateStep(
            "trend_forward_ledger",
            ("strategy_inputs",),
            False,
            _forward_ledger_enabled,
            _build_trend_forward_ledger,
        ),
    )


def _run_ordered_steps(
    steps: Sequence[DailyUpdateStep],
    context: DailyUpdateContext,
) -> list[DailyUpdateStepResult]:
    """执行有序步骤；阻断失败后不再启动后续步骤。"""
    _validate_step_graph(steps)
    results: list[DailyUpdateStepResult] = []
    statuses: dict[str, str] = {}
    pipeline_blocked = False
    for step in steps:
        if pipeline_blocked:
            result = DailyUpdateStepResult(
                step_id=step.step_id,
                status="SKIPPED_BLOCKED",
                blocking=step.blocking,
                depends_on=step.depends_on,
                elapsed_seconds=0.0,
            )
        elif not step.enabled(context):
            result = DailyUpdateStepResult(
                step_id=step.step_id,
                status="SKIPPED",
                blocking=step.blocking,
                depends_on=step.depends_on,
                elapsed_seconds=0.0,
            )
        elif any(
            not _step_succeeded(statuses.get(dependency))
            for dependency in step.depends_on
        ):
            result = DailyUpdateStepResult(
                step_id=step.step_id,
                status="SKIPPED_DEPENDENCY",
                blocking=step.blocking,
                depends_on=step.depends_on,
                elapsed_seconds=0.0,
                error="依赖步骤未完成",
            )
        else:
            started = time.perf_counter()
            try:
                summary = step.action(context)
                context.values[step.step_id] = summary
                step_status = "WARNING" if _summary_warning_count(summary) > 0 else "COMPLETED"
                result = DailyUpdateStepResult(
                    step_id=step.step_id,
                    status=step_status,
                    blocking=step.blocking,
                    depends_on=step.depends_on,
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    summary=summary,
                )
            except Exception as exc:  # noqa: BLE001 - 编排层必须固化失败摘要
                result = DailyUpdateStepResult(
                    step_id=step.step_id,
                    status="FAILED" if step.blocking else "WARNING",
                    blocking=step.blocking,
                    depends_on=step.depends_on,
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    error=str(exc),
                )
                pipeline_blocked = step.blocking
        results.append(result)
        statuses[step.step_id] = result.status
    return results


def _validate_step_graph(steps: Sequence[DailyUpdateStep]) -> None:
    seen: set[str] = set()
    for step in steps:
        if step.step_id in seen:
            raise ResearchWorkbenchError(f"重复日更步骤: {step.step_id}")
        missing = [dependency for dependency in step.depends_on if dependency not in seen]
        if missing:
            raise ResearchWorkbenchError(
                f"步骤{step.step_id}依赖尚未注册的前置步骤: {', '.join(missing)}"
            )
        seen.add(step.step_id)


def _fetch_official(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    args = [
        "research",
        "fetch-cf-official-daily-files",
        "--date",
        config.trade_date.isoformat(),
        "--futures-source-dir",
        str(config.futures_source_dir),
        "--options-source-dir",
        str(config.options_source_dir),
        "--report-output-dir",
        "reports/research/official_daily_files",
        "--run-id",
        config.run_id,
    ]
    if not config.include_options:
        args.append("--skip-options")
    if config.overwrite_official:
        args.append("--overwrite")
    summary = context.executor.run(args)
    context.values["effective_futures_source_dir"] = summary["futures_connect_source_dir"]
    context.values["effective_options_source_dir"] = summary["options_connect_source_dir"]
    context.values["official_fetch_json_path"] = summary.get("json_path")
    return summary


def _connect_futures(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    source_dir = context.values.get("effective_futures_source_dir", config.futures_source_dir)
    return context.executor.run(
        [
            "research",
            "connect-cf-official-history",
            "--years",
            str(config.year),
            "--source-dir",
            str(source_dir),
            "--report-output-dir",
            f"reports/research/official_history_{config.year}",
            "--run-id",
            config.run_id,
        ]
    )


def _refresh_calendar_metadata(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    core_path = _resolve_from_repo(config.core_quote_path, config.repo_root.resolve())
    if not core_path.exists():
        raise ResearchWorkbenchError(f"core quote table不存在: {core_path}")
    frame = pd.read_parquet(core_path, columns=["trade_date"])
    normalized_dates = pd.to_datetime(frame["trade_date"], errors="coerce").dropna()
    year_dates = normalized_dates.loc[normalized_dates.dt.year == config.year]
    trade_dates = sorted({value.date() for value in year_dates})
    if not trade_dates:
        raise ResearchWorkbenchError(f"core中没有{config.year}年CF数据")
    data_asof = trade_dates[-1]
    if config.download_official and data_asof != config.trade_date:
        raise ResearchWorkbenchError(
            f"下载接入后core最新日期为{data_asof}，不等于请求日期{config.trade_date}"
        )
    calendar_path = (
        config.repo_root.resolve()
        / "configs/calendars"
        / f"CZCE_{config.year}_OFFICIAL.csv"
    )
    _write_calendar(calendar_path=calendar_path, year=config.year, trade_dates=trade_dates)
    context.values["data_asof"] = data_asof
    context.values["calendar_path"] = str(calendar_path)
    return {
        "core_path": str(core_path),
        "calendar_path": str(calendar_path),
        "max_trade_date": data_asof.isoformat(),
        "trading_day_count": len(trade_dates),
        "row_count": int(len(year_dates)),
    }


def _connect_options(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    source_dir = context.values.get("effective_options_source_dir", config.options_source_dir)
    return context.executor.run(
        [
            "research",
            "connect-cf-option-history",
            "--source-dir",
            str(source_dir),
            "--raw-root",
            "data/raw",
            "--core-output-dir",
            "data/core",
            "--core-quote-path",
            str(config.core_quote_path),
            "--report-output-dir",
            "reports/research/option_core_ingest",
            "--run-id",
            config.run_id,
        ]
    )


def _run_continuity_audit(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    args = [
        "research",
        "build-cf-data-continuity-audit",
        "--date",
        _data_asof(context).isoformat(),
        "--core-quote-path",
        str(config.core_quote_path),
        "--calendar-path",
        str(context.values["calendar_path"]),
        "--raw-root",
        "data/raw",
        "--output-root",
        str(config.output_root),
        "--run-id",
        config.run_id,
    ]
    if _option_core_enabled(context):
        args.extend(("--option-core-path", str(config.option_core_path)))
    else:
        args.append("--no-require-options")
    fetch_json_path = context.values.get("official_fetch_json_path")
    if fetch_json_path:
        args.extend(("--official-daily-fetch-json-path", str(fetch_json_path)))
    return context.executor.run(args)


def _build_option_factor(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    option_core_summary = context.values.get("option_core_connect", {})
    option_core_path = option_core_summary.get("core_option_quote_path", config.option_core_path)
    summary = context.executor.run(
        [
            "research",
            "build-cf-option-factor-proxy",
            "--option-core-path",
            str(option_core_path),
            "--core-quote-path",
            str(config.core_quote_path),
            "--output-dir",
            "data/research/CF/option_factors",
            "--report-output-dir",
            "reports/research/option_factors",
            "--run-id",
            config.run_id,
            "--incremental",
        ]
    )
    context.values["effective_option_factor_path"] = summary["factor_parquet_path"]
    return summary


def _build_signal_matrix(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    option_factor_path = _effective_option_factor_path(context)
    args = [
        "research",
        "build-cf-signal-matrix",
        "--end",
        _data_asof(context).isoformat(),
        "--horizons",
        "1,3,5,10,20,40",
        "--core-quote-path",
        str(config.core_quote_path),
        "--output-dir",
        "data/research/CF/signal_matrix",
        "--report-output-dir",
        "reports/research/signal_matrix",
        "--run-id",
        config.run_id,
    ]
    _append_path_option(args, "--trend-rule-candidate-path", config.trend_rule_candidate_path)
    _append_path_option(args, "--option-factor-path", option_factor_path)
    return context.executor.run(args)


def _build_dual_price_state(context: DailyUpdateContext) -> dict[str, Any]:
    return context.executor.run(
        _simple_research_command(
            context,
            "build-cf-dual-price-state",
            "--core-quote-path",
            str(context.config.core_quote_path),
            "--output-dir",
            "data/research/CF/dual_price_state",
            "--report-output-dir",
            "reports/research/dual_price_state",
        )
    )


def _build_chain_oi_structure(context: DailyUpdateContext) -> dict[str, Any]:
    return context.executor.run(
        _simple_research_command(
            context,
            "build-cf-chain-oi-structure",
            "--core-quote-path",
            str(context.config.core_quote_path),
            "--output-dir",
            "data/research/CF/chain_oi_structure",
            "--report-output-dir",
            "reports/research/chain_oi_structure",
        )
    )


def _build_option_structure(context: DailyUpdateContext) -> dict[str, Any]:
    return context.executor.run(
        _simple_research_command(
            context,
            "build-cf-option-structure-research",
            "--option-factor-path",
            str(_effective_option_factor_path(context)),
            "--signal-matrix-path",
            str(context.values["signal_matrix"]["matrix_parquet_path"]),
            "--output-dir",
            "data/research/CF/option_structure",
            "--report-output-dir",
            "reports/research/option_structure",
        )
    )


def _build_trend_phase_v2(context: DailyUpdateContext) -> dict[str, Any]:
    return context.executor.run(
        _simple_research_command(
            context,
            "build-cf-trend-phase-v2",
            "--dual-price-path",
            str(context.values["dual_price_state"]["daily_parquet_path"]),
            "--chain-oi-path",
            str(context.values["chain_oi_structure"]["daily_parquet_path"]),
            "--option-structure-path",
            str(context.values["option_structure"]["daily_parquet_path"]),
            "--signal-matrix-path",
            str(context.values["signal_matrix"]["matrix_parquet_path"]),
            "--output-dir",
            "data/research/CF/trend_phase_v2",
            "--report-output-dir",
            "reports/research/trend_phase_v2",
        )
    )


def _build_latest_signal_brief(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    args = [
        "research",
        "build-cf-latest-signal-brief",
        "--date",
        _data_asof(context).isoformat(),
        "--core-quote-path",
        str(config.core_quote_path),
        "--output-root",
        str(config.output_root),
        "--run-id",
        config.run_id,
        "--signal-matrix-path",
        str(context.values["signal_matrix"]["latest_snapshot_json_path"]),
    ]
    _append_path_option(args, "--trend-rule-candidate-path", config.trend_rule_candidate_path)
    _append_path_option(
        args,
        "--signal-threshold-research-path",
        config.signal_threshold_research_path,
    )
    return context.executor.run(args)


def _build_fundamental_data_status(context: DailyUpdateContext) -> dict[str, Any]:
    return context.executor.run(
        _simple_research_command(
            context,
            "build-cf-fundamental-data-status",
            "--as-of-date",
            _data_asof(context).isoformat(),
            "--core-quote-path",
            str(context.config.core_quote_path),
        )
    )


def _build_trend_board(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    args = [
        "research",
        "build-cf-trend-continuity-board",
        "--date",
        _data_asof(context).isoformat(),
        "--core-quote-path",
        str(config.core_quote_path),
        "--output-root",
        str(config.output_root),
        "--run-id",
        config.run_id,
        "--lookback-trading-days",
        str(config.trend_board_lookback_days),
    ]
    _append_path_option(args, "--trend-rule-candidate-path", config.trend_rule_candidate_path)
    _append_path_option(
        args,
        "--trend-quality-calibration-manifest-path",
        config.trend_quality_calibration_manifest_path,
    )
    return context.executor.run(args)


def _build_daily_audit(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    return context.executor.run(
        [
            "research",
            "build-cf-daily-operation-audit",
            "--latest-signal-json-path",
            str(context.values["latest_signal_brief"]["json_path"]),
            "--trend-board-json-path",
            str(context.values["trend_continuity_board"]["json_path"]),
            "--core-quote-path",
            str(config.core_quote_path),
            "--output-root",
            str(config.output_root),
            "--run-id",
            config.run_id,
        ]
    )


def _forward_ledger_enabled(context: DailyUpdateContext) -> bool:
    return context.config.build_forward_ledger


def _build_strategy_inputs(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    start_date = config.strategy_inputs_start
    return context.executor.run(
        [
            "strategy",
            "prepare-inputs",
            "--start",
            start_date,
        ]
    )


def _build_trend_forward_ledger(context: DailyUpdateContext) -> dict[str, Any]:
    inputs = context.values["strategy_inputs"]
    config = context.config
    args = [
        "research",
        "build-cf-symmetric-trend-research",
        "--continuous-price-path",
        str(inputs["continuous_price_path"]),
        "--run-id",
        f"{config.run_id}_r93a",
    ]
    symmetric = context.executor.run(args)
    context.values["symmetric_trend"] = symmetric
    ledger = context.executor.run(
        [
            "research",
            "build-cf-trend-candidate-forward-ledger",
            "--symmetric-trend-daily-path",
            str(symmetric["daily_path"]),
            "--breakout-event-path",
            str(symmetric["breakout_event_path"]),
            "--as-of-date",
            _data_asof(context).isoformat(),
            "--run-id",
            f"{config.run_id}_r93d",
        ]
    )
    return {
        "status": "COMPLETED",
        "capture_appended_count": ledger.get("capture_appended_count"),
        "outcome_appended_count": ledger.get("outcome_appended_count"),
        "ledger_row_count": ledger.get("ledger_row_count"),
        "strict_forward_count": ledger.get("strict_forward_count"),
    }


def _build_studio_dashboard(context: DailyUpdateContext) -> dict[str, Any]:
    config = context.config
    script_path = (
        config.repo_root.resolve() / "scripts" / "build_cf_studio_dashboard.py"
    )
    if not script_path.is_file():
        raise ResearchWorkbenchError(f"Studio生成脚本不存在: {script_path}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, str(script_path), "--v3"],
        cwd=config.repo_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ResearchWorkbenchError(f"Studio仪表盘生成失败: {detail}")
    lines = [line for line in completed.stdout.splitlines() if line.startswith("[OK]")]
    return {
        "status": "COMPLETED",
        "script": str(script_path),
        "outputs": lines,
    }


def _write_calendar(*, calendar_path: Path, year: int, trade_dates: Sequence[date]) -> None:
    # 先写临时文件再替换，避免日更中断留下半张交易日历。
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = calendar_path.with_suffix(".csv.tmp")
    trading_date_set = set(trade_dates)
    current = date(year, 1, 1)
    last = date(year, 12, 31)
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "exchange",
                "trade_date",
                "is_trading_day",
                "calendar_version",
                "source_snapshot_id",
            ],
        )
        writer.writeheader()
        while current <= last:
            writer.writerow(
                {
                    "exchange": "CZCE",
                    "trade_date": current.isoformat(),
                    "is_trading_day": "true" if current in trading_date_set else "false",
                    "calendar_version": f"CZCE_OFFICIAL_{year}_CF_HISTORY_TO_DATE",
                    "source_snapshot_id": f"czce_{year}_official_cf_history_to_date",
                }
            )
            current += timedelta(days=1)
    temporary_path.replace(calendar_path)


def _write_pipeline_reports(result: CfDailyUpdateResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_summary()
    temporary_json = result.json_path.with_suffix(".json.tmp")
    temporary_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary_json.replace(result.json_path)

    lines = [
        "# CF 轻量日更编排摘要",
        "",
        f"- 请求日期：{result.requested_date.isoformat()}",
        f"- 数据截至：{result.data_asof.isoformat() if result.data_asof else '未确定'}",
        f"- 运行状态：{result.status}",
        f"- 总耗时：{result.elapsed_seconds:.3f} 秒",
        "",
        "## 步骤",
        "",
        "| 步骤 | 状态 | 阻断 | 耗时（秒） | 错误 |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for step in result.steps:
        error = (step.error or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {step.step_id} | {step.status} | {str(step.blocking).lower()} | "
            f"{step.elapsed_seconds:.3f} | {error} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 最新简报不包含 forward return 历史后验标签。",
            "- 连续合约只作为信号对象，真实交易映射边界保持不变。",
            "- 本结果为研究观察，不构成交易指令。",
            "- HUMAN_REVIEW_REQUIRED。",
            "",
        ]
    )
    temporary_markdown = result.markdown_path.with_suffix(".md.tmp")
    temporary_markdown.write_text("\n".join(lines), encoding="utf-8")
    temporary_markdown.replace(result.markdown_path)


def _parse_cli_json(stdout: str, *, args: Sequence[str]) -> dict[str, Any]:
    payload = stdout.strip()
    if not payload:
        raise ResearchWorkbenchError(f"CLI步骤未返回JSON: {' '.join(args)}")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ResearchWorkbenchError(
            f"CLI步骤返回无法解析的JSON: {' '.join(args)}\n{payload[-1000:]}"
        ) from exc
    if not isinstance(value, dict):
        raise ResearchWorkbenchError(f"CLI步骤JSON不是对象: {' '.join(args)}")
    return value


def _simple_research_command(
    context: DailyUpdateContext,
    command: str,
    *args: str,
) -> list[str]:
    return ["research", command, *args, "--run-id", context.config.run_id]


def _effective_option_factor_path(context: DailyUpdateContext) -> Path | None:
    explicit = (
        context.values.get("effective_option_factor_path")
        or context.config.option_factor_path
    )
    if explicit:
        return Path(explicit)
    latest = _latest_path(
        _resolve_from_repo(
            Path("data/research/CF/option_factors"),
            context.config.repo_root.resolve(),
        ),
        "CF_*_option_factor_proxy_daily.parquet",
    )
    if latest is not None:
        context.values["effective_option_factor_path"] = str(latest)
    return latest


def _latest_path(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    candidates = [path for path in directory.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _resolve_from_repo(path: Path, repo_root: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _append_path_option(args: list[str], option: str, path: Path | None) -> None:
    if path is not None:
        args.extend((option, str(path)))


def _data_asof(context: DailyUpdateContext) -> date:
    value = _context_date(context.values.get("data_asof"))
    if value is None:
        raise ResearchWorkbenchError("日更数据截至日期尚未建立")
    return value


def _context_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return None


def _download_enabled(context: DailyUpdateContext) -> bool:
    return context.config.download_official


def _always_enabled(_context: DailyUpdateContext) -> bool:
    return True


def _option_core_enabled(context: DailyUpdateContext) -> bool:
    config = context.config
    return config.refresh_option_core or (config.download_official and config.include_options)


def _option_factor_enabled(context: DailyUpdateContext) -> bool:
    return context.config.refresh_option_factors or _option_core_enabled(context)


def _continuity_enabled(context: DailyUpdateContext) -> bool:
    return context.config.run_continuity_audit


def _state_upgrade_enabled(context: DailyUpdateContext) -> bool:
    return context.config.run_state_upgrade


def _option_state_upgrade_enabled(context: DailyUpdateContext) -> bool:
    return context.config.run_state_upgrade and _effective_option_factor_path(context) is not None


def _daily_audit_enabled(context: DailyUpdateContext) -> bool:
    return context.config.run_daily_operation_audit


def _studio_dashboard_enabled(context: DailyUpdateContext) -> bool:
    return context.config.build_studio_dashboard


def _pipeline_status(steps: Sequence[DailyUpdateStepResult]) -> str:
    if any(step.status == "FAILED" for step in steps):
        return "FAILED"
    if any(step.status == "WARNING" for step in steps):
        return "COMPLETED_WITH_WARNINGS"
    return "COMPLETED"


def _step_succeeded(status: str | None) -> bool:
    return status in {"COMPLETED", "WARNING"}


def _summary_warning_count(summary: dict[str, Any]) -> int:
    value = summary.get("warning_count", 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def default_run_id(trade_date: date) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cf_daily_update_{trade_date:%Y%m%d}_{timestamp}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行可测试的CF轻量日更编排器")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--year", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--futures-source-dir", type=Path, default=Path("data/incoming/CF/history"))
    parser.add_argument(
        "--options-source-dir",
        type=Path,
        default=Path("data/incoming/CF/options/history"),
    )
    parser.add_argument("--download-official", action="store_true")
    parser.add_argument("--skip-options", action="store_true")
    parser.add_argument("--overwrite-official", action="store_true")
    parser.add_argument("--refresh-option-core", action="store_true")
    parser.add_argument("--refresh-option-factors", action="store_true")
    parser.add_argument("--skip-continuity-audit", action="store_true")
    parser.add_argument("--skip-state-upgrade", action="store_true")
    parser.add_argument("--run-daily-operation-audit", action="store_true")
    parser.add_argument("--trend-board-lookback-days", type=int, default=20)
    parser.add_argument("--skip-studio-dashboard", action="store_true")
    parser.add_argument("--skip-forward-ledger", action="store_true")
    parser.add_argument("--trend-rule-candidate-path", type=Path)
    parser.add_argument("--trend-quality-calibration-manifest-path", type=Path)
    parser.add_argument("--signal-threshold-research-path", type=Path)
    parser.add_argument("--option-factor-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    active_date: date = args.date
    config = CfDailyUpdateConfig(
        trade_date=active_date,
        year=args.year or active_date.year,
        run_id=args.run_id or default_run_id(active_date),
        repo_root=Path.cwd(),
        futures_source_dir=args.futures_source_dir,
        options_source_dir=args.options_source_dir,
        download_official=args.download_official,
        include_options=not args.skip_options,
        overwrite_official=args.overwrite_official,
        refresh_option_core=args.refresh_option_core,
        refresh_option_factors=args.refresh_option_factors,
        run_continuity_audit=not args.skip_continuity_audit,
        run_state_upgrade=not args.skip_state_upgrade,
        run_daily_operation_audit=args.run_daily_operation_audit,
        trend_board_lookback_days=args.trend_board_lookback_days,
        build_studio_dashboard=not args.skip_studio_dashboard,
        build_forward_ledger=not args.skip_forward_ledger,
        trend_rule_candidate_path=args.trend_rule_candidate_path,
        trend_quality_calibration_manifest_path=args.trend_quality_calibration_manifest_path,
        signal_threshold_research_path=args.signal_threshold_research_path,
        option_factor_path=args.option_factor_path,
    )
    result = run_cf_daily_update(config)
    print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
