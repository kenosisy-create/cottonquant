"""R92 fixed overlay backtests and incremental-value decisions."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.backtest import NotionalBpsCostModel, run_daily_backtest
from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.core.contract_master import load_product_config
from cotton_factor.core.schemas import (
    BacktestTargetLotDailyRow,
    CoreTradeMappingDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.strategy.baseline_tsmom import (
    StrategyBacktestResult,
    _daily_frame,
    run_cf_tsmom_backtest,
)
from cotton_factor.strategy.comparison import promotion_decision
from cotton_factor.strategy.evaluation import evaluate_cf_strategy
from cotton_factor.strategy.io import (
    default_core_quote_path,
    engine_contracts_from_quotes,
    latest_strategy_input_paths,
    load_core_quotes,
    load_typed_parquet,
)
from cotton_factor.strategy.metrics import strategy_metrics
from cotton_factor.strategy.phase_gated import _option_multiplier
from cotton_factor.strategy.signals import build_tsmom_targets
from cotton_factor.strategy.spec import GateRuleSpec, StrategySpec, load_strategy_spec

OVERLAY_TARGET_RULE_VERSION = "V5.1_R92_overlay_target_v1"
OVERLAY_BACKTEST_RULE_VERSION = "V5.1_R92_overlay_backtest_v1"
OVERLAY_DECISION_RULE_VERSION = "V5.1_R92_overlay_incremental_value_v1"
SUPPORTED_OVERLAYS = {"option_veto", "member_position", "strike_wall"}
RESEARCH_BOUNDARY = (
    "研究仿真、前向记录、无未来函数，不构成交易指令；"
    "NAV 为研究记账值，非真实资金。"
)


@dataclass(frozen=True)
class OverlayTestResult:
    """R92 backtest, evaluation and KEEP/WATCH/REJECT artifacts."""

    run_id: str
    base_key: str
    overlay_key: str
    decision: str
    eligible_year_count: int
    year_win_count: int
    full_delta_sharpe: float
    conservative_net_return: float
    drawdown_deterioration_pp: float
    backtest_daily_path: Path
    evaluation_path: Path
    comparison_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a machine-readable CLI summary."""
        return {
            "run_id": self.run_id,
            "base_key": self.base_key,
            "overlay_key": self.overlay_key,
            "decision": self.decision,
            "eligible_year_count": self.eligible_year_count,
            "year_win_count": self.year_win_count,
            "full_delta_sharpe": self.full_delta_sharpe,
            "conservative_net_return": self.conservative_net_return,
            "drawdown_deterioration_pp": self.drawdown_deterioration_pp,
            "backtest_daily_path": str(self.backtest_daily_path),
            "evaluation_path": str(self.evaluation_path),
            "comparison_path": str(self.comparison_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "warning_count": self.warning_count,
        }


def run_cf_overlay_backtest(
    *,
    spec_path: Path,
    base_spec_path: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    continuous_price_path: Path | None = None,
    trade_mapping_path: Path | None = None,
    core_quote_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    member_position_path: Path | None = None,
    strike_position_path: Path | None = None,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> StrategyBacktestResult:
    """Run one frozen overlay through the existing real-contract D16 engine."""
    spec = load_strategy_spec(spec_path)
    if spec.strategy_type != "overlay":
        raise StrategyError("R92 requires an overlay strategy spec")
    base_path = base_spec_path or project_root() / "configs/strategy/CF_tsmom_v0.yaml"
    base_spec = load_strategy_spec(base_path)
    if base_spec.spec_key != spec.base_strategy or base_spec.strategy_type != "baseline_tsmom":
        raise StrategyError("R92 overlay base_strategy must resolve to CF_tsmom/v0")
    rule = _single_overlay_rule(spec)
    bundle = (
        latest_strategy_input_paths(input_dir)
        if continuous_price_path is None or trade_mapping_path is None
        else {}
    )
    continuous_path = continuous_price_path or bundle["continuous"]
    mapping_path = trade_mapping_path or bundle["trade"]
    quote_path = core_quote_path or default_core_quote_path()
    continuous = load_typed_parquet(continuous_path, ResearchContinuousPriceDailyRow)
    mappings = load_typed_parquet(mapping_path, CoreTradeMappingDailyRow)
    quotes = load_core_quotes(quote_path)
    config = load_product_config("CF")
    if not isinstance(config.multiplier, int | float):
        raise StrategyError("CF multiplier must be confirmed before overlay backtest")

    active_run_id = run_id or _default_run_id(spec)
    base_targets = build_tsmom_targets(
        spec=base_spec,
        continuous_rows=continuous,
        trade_mappings=mappings,
        quotes=quotes,
        multiplier=float(config.multiplier),
        run_id=f"{active_run_id}_base",
    )
    source_frame, source_path = _load_overlay_source(
        rule=rule,
        horizon=spec.signal_horizon,
        signal_matrix_path=signal_matrix_path,
        member_position_path=member_position_path,
        strike_position_path=strike_position_path,
    )
    overlay_targets, diagnostics, overlay_warnings = build_overlay_targets(
        spec=spec,
        base_rows=list(base_targets.target_rows),
        base_diagnostics=list(base_targets.diagnostics),
        source_frame=source_frame,
        run_id=active_run_id,
    )
    available_dates = sorted(row.trade_date for row in overlay_targets)
    selected_start = start or available_dates[0]
    selected_end = end or available_dates[-1]
    if selected_start > selected_end:
        raise StrategyError("overlay backtest start must be <= end")
    if selected_start < available_dates[0] or selected_end > available_dates[-1]:
        raise StrategyError(
            f"overlay range must stay within {available_dates[0]} to {available_dates[-1]}"
        )
    selected_targets = tuple(
        row for row in overlay_targets if selected_start <= row.trade_date <= selected_end
    )
    selected_diagnostics = tuple(
        row for row in diagnostics if selected_start <= row["trade_date"] <= selected_end
    )
    if not selected_targets:
        raise StrategyError("selected overlay range contains no target rows")

    contracts = engine_contracts_from_quotes(quotes)
    daily_frames: list[pd.DataFrame] = []
    fills: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    warnings = [*base_targets.warnings, *overlay_warnings]
    for scenario, cost_spec in spec.costs.items():
        engine_result = run_daily_backtest(
            target_lot_rows=selected_targets,
            quotes=quotes,
            contracts=contracts,
            run_id=f"{active_run_id}_{scenario}",
            product_code="CF",
            strategy_id=spec.spec_key,
            signal_object_id=spec.signal_object,
            execution_price_mode="next_settle",
            cost_model=NotionalBpsCostModel(
                one_way_bps=cost_spec.one_way_bps,
                model_id=f"notional_one_way_bps_v1:{scenario}",
            ),
            backtest_rule_version=OVERLAY_BACKTEST_RULE_VERSION,
        )
        daily_frames.append(
            _daily_frame(
                engine_result=engine_result,
                scenario=scenario,
                one_way_bps=cost_spec.one_way_bps,
                capital_base=spec.sizing.capital_base,
                diagnostics=selected_diagnostics,
            )
        )
        fills.extend(
            {"cost_scenario": scenario, **_json_safe(asdict(row))}
            for row in engine_result.fills
        )
        orders.extend(
            {"cost_scenario": scenario, **_json_safe(asdict(row))}
            for row in engine_result.orders
        )
        warnings.extend(engine_result.warnings)
    daily = pd.concat(daily_frames, ignore_index=True)
    metrics = {
        scenario: strategy_metrics(
            daily.loc[daily["cost_scenario"].eq(scenario)].copy(),
            capital_base=spec.sizing.capital_base,
        )
        for scenario in spec.costs
    }
    paths = _backtest_output_paths(
        spec=spec,
        start=selected_start,
        end=selected_end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_records(paths["targets"], [row.model_dump(mode="json") for row in selected_targets])
    _write_records(paths["diagnostics"], list(selected_diagnostics))
    _write_records(paths["daily"], daily.to_dict(orient="records"))
    _write_records(paths["fills"], fills)
    _write_records(paths["orders"], orders)
    unique_warnings = sorted(set(warnings))
    _write_warnings(paths["warnings"], run_id=active_run_id, warnings=unique_warnings)
    result = StrategyBacktestResult(
        run_id=active_run_id,
        strategy_key=spec.spec_key,
        start=selected_start,
        end=selected_end,
        spec_path=spec_path,
        target_path=paths["targets"],
        diagnostic_path=paths["diagnostics"],
        daily_path=paths["daily"],
        fill_path=paths["fills"],
        order_path=paths["orders"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        target_row_count=len(selected_targets),
        daily_row_count=len(daily),
        fill_count=len(fills),
        metrics_by_scenario=metrics,
        warning_count=len(unique_warnings),
    )
    _write_backtest_outputs(
        result=result,
        rule=rule,
        diagnostics=pd.DataFrame(selected_diagnostics),
        input_paths=(
            spec_path,
            base_path,
            continuous_path,
            mapping_path,
            quote_path,
            source_path,
        ),
    )
    return result


def build_overlay_targets(
    *,
    spec: StrategySpec,
    base_rows: list[BacktestTargetLotDailyRow],
    base_diagnostics: list[dict[str, object]],
    source_frame: pd.DataFrame,
    run_id: str,
) -> tuple[
    tuple[BacktestTargetLotDailyRow, ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    """Apply exactly one pre-registered T-day overlay without changing direction."""
    if spec.strategy_type != "overlay":
        raise StrategyError("overlay target builder received another strategy type")
    rule = _single_overlay_rule(spec)
    source_by_date = {
        row["trade_date"]: row for row in source_frame.to_dict(orient="records")
    }
    base_diag_by_date = {row["trade_date"]: row for row in base_diagnostics}
    targets: list[BacktestTargetLotDailyRow] = []
    diagnostics: list[dict[str, object]] = []
    warning_dates: dict[str, list[date]] = defaultdict(list)
    previous_base_target = 0

    for base in sorted(base_rows, key=lambda row: row.trade_date):
        base_diag = base_diag_by_date[base.trade_date]
        direction = int(base_diag["direction"])
        source_row = source_by_date.get(base.trade_date)
        multiplier, state, warning_code = _overlay_multiplier(
            rule=rule,
            row=source_row,
            direction=direction,
            base_target=base.target_lots,
            previous_base_target=previous_base_target,
        )
        if warning_code:
            warning_dates[warning_code].append(base.trade_date)
        target_lots = int(round(base.target_lots * multiplier))
        if base.is_blocked:
            target_lots = 0
        snapshots = list(base.input_snapshot_ids)
        source_snapshot = _source_snapshot_id(source_row)
        if source_snapshot and source_snapshot not in snapshots:
            snapshots.append(source_snapshot)
        base_warning = str(base_diag.get("warning_code", "")).strip()
        diagnostic_warning = ";".join(
            value for value in (base_warning, warning_code) if value
        )
        targets.append(
            BacktestTargetLotDailyRow(
                run_id=run_id,
                strategy_id=spec.spec_key,
                product_code=base.product_code,
                universe=base.universe,
                signal_object_id=base.signal_object_id,
                trade_date=base.trade_date,
                execution_date=base.execution_date,
                target_contract=base.target_contract,
                target_lots=target_lots,
                score=base.score,
                is_blocked=base.is_blocked,
                block_reason=base.block_reason,
                execution_eligible=base.execution_eligible,
                target_rule_version=OVERLAY_TARGET_RULE_VERSION,
                input_snapshot_ids=snapshots,
            )
        )
        diagnostics.append(
            {
                **base_diag,
                "base_target_lots": base.target_lots,
                "target_lots": target_lots,
                "overlay_rule": rule.name,
                "overlay_state": state,
                "g_overlay": multiplier,
                "overlay_source_available": source_row is not None,
                "warning_code": diagnostic_warning,
            }
        )
        previous_base_target = base.target_lots
    warnings = tuple(
        f"{code}: {len(values)} date(s), {min(values)} to {max(values)}"
        for code, values in sorted(warning_dates.items())
    )
    return tuple(targets), tuple(diagnostics), warnings


def test_cf_overlay(
    *,
    overlay_spec_path: Path,
    base_spec_path: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    continuous_price_path: Path | None = None,
    trade_mapping_path: Path | None = None,
    core_quote_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    member_position_path: Path | None = None,
    strike_position_path: Path | None = None,
    trend_phase_path: Path | None = None,
    input_dir: Path | None = None,
    output_root: Path | None = None,
    report_output_dir: Path | None = None,
    baseline_evaluation_path: Path | None = None,
    run_id: str | None = None,
) -> OverlayTestResult:
    """Run one overlay and map the unchanged promotion gate to KEEP/WATCH/REJECT."""
    overlay = load_strategy_spec(overlay_spec_path)
    base_path = base_spec_path or project_root() / "configs/strategy/CF_tsmom_v0.yaml"
    base = load_strategy_spec(base_path)
    active_run_id = run_id or _default_run_id(overlay)
    overlay_output = output_root / overlay.strategy_id if output_root else None
    base_output = output_root / base.strategy_id if output_root else None

    # 默认重新生成同窗基准，避免拿过期基准与最新 overlay 进行伪比较。
    if baseline_evaluation_path is None:
        base_backtest = run_cf_tsmom_backtest(
            spec_path=base_path,
            start=start,
            end=end,
            continuous_price_path=continuous_price_path,
            trade_mapping_path=trade_mapping_path,
            core_quote_path=core_quote_path,
            input_dir=input_dir,
            output_dir=base_output,
            report_output_dir=report_output_dir,
            run_id=f"{active_run_id}_base",
        )
        base_evaluation = evaluate_cf_strategy(
            spec_path=base_path,
            backtest_daily_path=base_backtest.daily_path,
            trend_phase_path=trend_phase_path,
            output_dir=base_output,
            report_output_dir=report_output_dir,
            run_id=f"{active_run_id}_base_eval",
        )
        baseline_evaluation_path = base_evaluation.window_path
    overlay_backtest = run_cf_overlay_backtest(
        spec_path=overlay_spec_path,
        base_spec_path=base_path,
        start=start,
        end=end,
        continuous_price_path=continuous_price_path,
        trade_mapping_path=trade_mapping_path,
        core_quote_path=core_quote_path,
        signal_matrix_path=signal_matrix_path,
        member_position_path=member_position_path,
        strike_position_path=strike_position_path,
        input_dir=input_dir,
        output_dir=overlay_output,
        report_output_dir=report_output_dir,
        run_id=f"{active_run_id}_overlay",
    )
    overlay_evaluation = evaluate_cf_strategy(
        spec_path=overlay_spec_path,
        backtest_daily_path=overlay_backtest.daily_path,
        trend_phase_path=trend_phase_path,
        output_dir=overlay_output,
        report_output_dir=report_output_dir,
        run_id=f"{active_run_id}_overlay_eval",
    )
    baseline_frame = pd.read_parquet(baseline_evaluation_path)
    overlay_frame = pd.read_parquet(overlay_evaluation.window_path)
    _assert_aligned_windows(baseline_frame, overlay_frame)
    if overlay.promotion_rule is None:
        raise StrategyError("overlay spec must define promotion_rule")
    comparison_rows, metrics = promotion_decision(
        baseline=baseline_frame,
        candidate=overlay_frame,
        rule=overlay.promotion_rule,
    )
    decision = overlay_decision(metrics)
    paths = _test_output_paths(
        spec=overlay,
        output_dir=overlay_output,
        report_output_dir=report_output_dir,
    )
    paths["comparison"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(comparison_rows).to_parquet(paths["comparison"], index=False)
    result = OverlayTestResult(
        run_id=active_run_id,
        base_key=base.spec_key,
        overlay_key=overlay.spec_key,
        decision=decision,
        eligible_year_count=int(metrics["eligible_year_count"]),
        year_win_count=int(metrics["year_win_count"]),
        full_delta_sharpe=float(metrics["full_delta_sharpe"]),
        conservative_net_return=float(metrics["conservative_net_return"]),
        drawdown_deterioration_pp=float(metrics["drawdown_deterioration_pp"]),
        backtest_daily_path=overlay_backtest.daily_path,
        evaluation_path=overlay_evaluation.window_path,
        comparison_path=paths["comparison"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_count=overlay_backtest.warning_count + overlay_evaluation.warning_count,
    )
    _write_test_outputs(
        result=result,
        comparison_rows=comparison_rows,
        conditions=dict(metrics["conditions"]),
        input_paths=(
            overlay_spec_path,
            base_path,
            baseline_evaluation_path,
            overlay_evaluation.window_path,
            overlay_backtest.manifest_path,
        ),
    )
    return result


def overlay_decision(metrics: dict[str, object]) -> str:
    """Map the unchanged candidate gate to the R92 three-level decision."""
    if metrics.get("decision") == "PASS":
        return "KEEP"
    if float(metrics["full_delta_sharpe"]) > 0:
        return "WATCH"
    return "REJECT"


def resolve_strategy_spec_path(value: str) -> Path:
    """Resolve a CLI strategy name or YAML path inside the repository."""
    candidate = Path(value)
    if candidate.exists():
        return candidate
    config_root = project_root() / "configs/strategy"
    names = [value] if value.endswith(".yaml") else [f"{value}.yaml", f"{value}_v0.yaml"]
    matches = [config_root / name for name in names if (config_root / name).exists()]
    if len(matches) != 1:
        raise StrategyError(f"strategy spec not found for reference: {value}")
    return matches[0]


def _single_overlay_rule(spec: StrategySpec) -> GateRuleSpec:
    if len(spec.gate_rules) != 1:
        raise StrategyError("R92 overlay spec must define exactly one gate rule")
    rule = spec.gate_rules[0]
    if rule.name not in SUPPORTED_OVERLAYS:
        raise StrategyError(f"unsupported R92 overlay rule: {rule.name}")
    return rule


def _load_overlay_source(
    *,
    rule: GateRuleSpec,
    horizon: int,
    signal_matrix_path: Path | None,
    member_position_path: Path | None,
    strike_position_path: Path | None,
) -> tuple[pd.DataFrame, Path]:
    if rule.name == "option_veto":
        path = signal_matrix_path or _latest_signal_matrix_path()
        return _load_option_source(path, horizon=horizon), path
    if rule.name == "member_position":
        path = member_position_path or data_dir() / "core/CF/core_member_position_daily.parquet"
        return _load_member_source(path, rank_max=int(rule.parameters["rank_max"])), path
    path = strike_position_path or _latest_strike_position_path()
    return _load_strike_source(path), path


def _load_option_source(path: Path, *, horizon: int) -> pd.DataFrame:
    frame = _read_safe_research_table(path)
    required = {
        "trade_date",
        "horizon",
        "option_signal",
        "option_signal_direction",
        "source_snapshot_ids",
    }
    _require_columns(frame, required, context="option overlay")
    selected = frame.loc[frame["horizon"].eq(horizon), list(required)].copy()
    if selected.empty:
        raise StrategyError(f"signal matrix has no {horizon}D rows: {path}")
    selected["trade_date"] = pd.to_datetime(selected["trade_date"]).dt.date
    _assert_unique_dates(selected, context="option overlay")
    return selected


def _load_member_source(path: Path, *, rank_max: int) -> pd.DataFrame:
    frame = _read_safe_research_table(path)
    required = {
        "trade_date",
        "product_code",
        "scope_type",
        "scope_code",
        "position_side",
        "rank",
        "position_change",
        "source_snapshot_id",
    }
    _require_columns(frame, required, context="member-position overlay")
    selected = frame.loc[
        frame["product_code"].eq("CF")
        & frame["scope_type"].eq("product")
        & frame["scope_code"].eq("CF")
        & pd.to_numeric(frame["rank"], errors="coerce").le(rank_max)
        & frame["position_side"].isin(["long", "short"])
    ].copy()
    if selected.empty:
        raise StrategyError(f"member-position overlay has no CF Top{rank_max} rows: {path}")
    selected["trade_date"] = pd.to_datetime(selected["trade_date"]).dt.date
    selected["position_change"] = pd.to_numeric(
        selected["position_change"], errors="coerce"
    ).fillna(0.0)
    grouped = (
        selected.groupby(["trade_date", "position_side"], as_index=False)
        .agg(
            position_change=("position_change", "sum"),
            rank_count=("rank", "count"),
            source_snapshot_ids=(
                "source_snapshot_id",
                lambda values: ";".join(sorted(set(map(str, values)))),
            ),
        )
    )
    rows: list[dict[str, object]] = []
    for trade_date, day in grouped.groupby("trade_date", sort=True):
        by_side = day.set_index("position_side")
        has_both = {"long", "short"}.issubset(by_side.index)
        long_change = (
            float(by_side.loc["long", "position_change"])
            if "long" in by_side.index
            else 0.0
        )
        short_change = (
            float(by_side.loc["short", "position_change"]) if "short" in by_side.index else 0.0
        )
        # 固定口径：净多变化等于多头变化减空头变化，不读取会员身份或客户穿透信息。
        net_change = long_change - short_change
        member_direction = "long" if net_change > 0 else "short" if net_change < 0 else "neutral"
        snapshots = ";".join(
            sorted(set(";".join(day["source_snapshot_ids"].astype(str)).split(";")))
        )
        rows.append(
            {
                "trade_date": trade_date,
                "member_direction": member_direction,
                "member_net_change": net_change,
                "member_source_complete": has_both,
                "source_snapshot_ids": snapshots,
            }
        )
    return pd.DataFrame(rows)


def _load_strike_source(path: Path) -> pd.DataFrame:
    frame = _read_safe_research_table(path)
    required = {
        "trade_date",
        "is_main_contract",
        "distance_to_call_wall",
        "distance_to_put_wall",
        "run_id",
    }
    _require_columns(frame, required, context="strike-wall overlay")
    selected = frame.loc[frame["is_main_contract"].eq(True), list(required)].copy()
    if selected.empty:
        raise StrategyError(f"strike-wall overlay has no main-contract rows: {path}")
    selected["trade_date"] = pd.to_datetime(selected["trade_date"]).dt.date
    _assert_unique_dates(selected, context="strike-wall overlay")
    return selected


def _overlay_multiplier(
    *,
    rule: GateRuleSpec,
    row: dict[str, object] | None,
    direction: int,
    base_target: int,
    previous_base_target: int,
) -> tuple[float, str, str]:
    if rule.name == "option_veto":
        if row is None:
            return (
                float(rule.parameters["missing_or_not_connected"]),
                "MISSING",
                "MISSING_OPTION_OVERLAY_INPUT",
            )
        # 背离标签必须与显式期权方向相互印证，不能只凭标签字符串降权。
        multiplier, warning = _option_multiplier(
            row=row,
            direction=direction,
            parameters=rule.parameters,
        )
        return multiplier, str(row.get("option_signal", "not_connected")), warning
    if rule.name == "member_position":
        if row is None or not bool(row.get("member_source_complete", False)):
            return float(rule.parameters["missing"]), "MISSING", "MISSING_MEMBER_POSITION_INPUT"
        member_direction = str(row.get("member_direction", "neutral"))
        direction_label = "long" if direction > 0 else "short" if direction < 0 else "neutral"
        # 会员方向只改变仓位幅度，不得反转基准动量方向。
        if member_direction == direction_label and direction_label != "neutral":
            return float(rule.parameters["agree"]), "AGREE", ""
        if member_direction in {"long", "short"} and direction_label in {"long", "short"}:
            return float(rule.parameters["disagree"]), "DISAGREE", ""
        return float(rule.parameters["missing"]), "NEUTRAL", ""
    if row is None:
        return float(rule.parameters["missing"]), "MISSING", "MISSING_STRIKE_WALL_INPUT"
    distance_key = "distance_to_call_wall" if direction > 0 else "distance_to_put_wall"
    distance = _optional_float(row.get(distance_key))
    # OI 墙只压缩从空仓开仓或反手形成的新方向，存量持仓与退出不受阻挡。
    is_new_entry = base_target != 0 and (
        previous_base_target == 0 or (base_target > 0) != (previous_base_target > 0)
    )
    near_wall = distance is not None and abs(distance) < float(
        rule.parameters["distance_threshold"]
    )
    if is_new_entry and near_wall:
        return float(rule.parameters["new_entry_multiplier"]), "NEAR_SAME_SIDE_WALL_NEW_ENTRY", ""
    if near_wall:
        return 1.0, "NEAR_SAME_SIDE_WALL_EXISTING", ""
    return float(rule.parameters["missing"]), "CLEAR_OR_MISSING_DISTANCE", ""


def _source_snapshot_id(row: dict[str, object] | None) -> str:
    if row is None:
        return ""
    for key in ("source_snapshot_ids", "run_id"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _read_safe_research_table(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise StrategyError(f"overlay source parquet not found: {path}")
    frame = pd.read_parquet(path)
    forbidden = [
        column
        for column in frame.columns
        if "forward_return" in column.lower()
        or "fwd_ret" in column.lower()
        or column.lower().startswith("future_")
    ]
    if forbidden:
        raise StrategyError(f"overlay source contains forbidden columns: {sorted(forbidden)}")
    return frame


def _require_columns(frame: pd.DataFrame, required: set[str], *, context: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise StrategyError(f"{context} missing columns: {sorted(missing)}")


def _assert_unique_dates(frame: pd.DataFrame, *, context: str) -> None:
    if frame["trade_date"].duplicated().any():
        raise StrategyError(f"{context} contains duplicate dates")


def _assert_aligned_windows(baseline: pd.DataFrame, overlay: pd.DataFrame) -> None:
    required = {"window_id", "cost_scenario", "observation_count"}
    for name, frame in (("baseline", baseline), ("overlay", overlay)):
        missing = required.difference(frame.columns)
        if missing:
            raise StrategyError(f"{name} evaluation missing alignment columns: {sorted(missing)}")
    left = baseline[list(required)].rename(columns={"observation_count": "base_count"})
    right = overlay[list(required)].rename(columns={"observation_count": "overlay_count"})
    merged = left.merge(right, on=["window_id", "cost_scenario"], how="outer", indicator=True)
    if not merged["_merge"].eq("both").all() or not merged["base_count"].eq(
        merged["overlay_count"]
    ).all():
        raise StrategyError("baseline and overlay evaluation windows are not aligned")


def _latest_signal_matrix_path() -> Path:
    root = data_dir() / "research/CF/signal_matrix"
    paths = sorted(root.glob("*_signal_matrix_daily.parquet"))
    if not paths:
        raise StrategyError(f"signal matrix daily artifact not found under {root}")
    return paths[-1]


def _latest_strike_position_path() -> Path:
    root = data_dir() / "research/CF/option_strike_position"
    paths = sorted(root.glob("*_option_strike_position_daily.parquet"))
    if not paths:
        raise StrategyError(f"option strike-position daily artifact not found under {root}")
    return paths[-1]


def _backtest_output_paths(
    *,
    spec: StrategySpec,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "strategy/CF" / spec.strategy_id
    report_root = report_output_dir or reports_dir() / "strategy"
    stem = f"{spec.strategy_id}_{spec.version}_{start}_{end}"
    return {
        "targets": root / f"{stem}_target_lot_daily.parquet",
        "diagnostics": root / f"{stem}_signal_diagnostic_daily.parquet",
        "daily": root / f"{stem}_backtest_daily.parquet",
        "fills": root / f"{stem}_fills.parquet",
        "orders": root / f"{stem}_orders.parquet",
        "warnings": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}_backtest.json",
        "markdown": report_root / f"{stem}_backtest.md",
    }


def _test_output_paths(
    *,
    spec: StrategySpec,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "strategy/CF" / spec.strategy_id
    report_root = report_output_dir or reports_dir() / "strategy"
    stem = f"overlay_{spec.strategy_id}_{spec.version}"
    return {
        "comparison": root / f"{stem}_comparison.parquet",
        "manifest": root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
    }


def _write_backtest_outputs(
    *,
    result: StrategyBacktestResult,
    rule: GateRuleSpec,
    diagnostics: pd.DataFrame,
    input_paths: tuple[Path, ...],
) -> None:
    gate_counts = {
        column: {
            str(key): int(value)
            for key, value in diagnostics[column].value_counts(dropna=False).items()
        }
        for column in ("overlay_state", "g_overlay")
    }
    payload = {
        **result.to_summary(),
        "backtest_rule_version": OVERLAY_BACKTEST_RULE_VERSION,
        "overlay_rule": rule.model_dump(mode="json"),
        "gate_counts": gate_counts,
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# CF 单规则 overlay 回测：{result.strategy_key}",
        "",
        f"- 区间：`{result.start}` 至 `{result.end}`",
        f"- 唯一规则：`{rule.name}`",
        "- 执行：`T日收盘后生成目标，T+1真实合约结算成交`",
        "",
        "| 成本档 | 累计收益 | Sharpe | 最大回撤 | 总成本 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for scenario, metrics in result.metrics_by_scenario.items():
        lines.append(
            f"| {scenario} | {float(metrics['cumulative_return']):.2%} | "
            f"{float(metrics['sharpe']):.3f} | {float(metrics['max_drawdown']):.2%} | "
            f"{float(metrics['total_cost']):.2f} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- overlay 不修改 composite_score，不自动进入影子策略。",
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifacts = (
        result.target_path,
        result.diagnostic_path,
        result.daily_path,
        result.fill_path,
        result.order_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        **result.to_summary(),
        "backtest_rule_version": OVERLAY_BACKTEST_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_test_outputs(
    *,
    result: OverlayTestResult,
    comparison_rows: list[dict[str, object]],
    conditions: dict[str, object],
    input_paths: tuple[Path, ...],
) -> None:
    payload = {
        **result.to_summary(),
        "decision_rule_version": OVERLAY_DECISION_RULE_VERSION,
        "conditions": conditions,
        "yearly_comparison": comparison_rows,
        "research_boundary": RESEARCH_BOUNDARY,
        "composite_score_modified": False,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# CF overlay 增量价值检验：{result.overlay_key}",
        "",
        f"- 基准：`{result.base_key}`",
        f"- 机械结论：`{result.decision}`",
        f"- 合格年度：`{result.eligible_year_count}/5`",
        f"- 年度胜出：`{result.year_win_count}/5`",
        f"- 全历史 conservative cost Delta Sharpe：`{result.full_delta_sharpe:.3f}`",
        f"- conservative cost 净收益：`{result.conservative_net_return:.2%}`",
        f"- 最大回撤恶化：`{result.drawdown_deterioration_pp:.2f}` 个百分点",
        "",
        "| 年度 | 合格 | 胜出 | 基准 Sharpe | overlay Sharpe | Delta Sharpe |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in comparison_rows:
        lines.append(
            f"| {row['year']} | {row['eligible']} | {row['win']} | "
            f"{row['baseline_sharpe']:.3f} | {row['candidate_sharpe']:.3f} | "
            f"{row['delta_sharpe']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## 判定口径",
            "",
            "- KEEP：完整沿用 V5.1 候选晋级门槛并全部通过。",
            "- WATCH：未完全晋级，但全历史 conservative cost Delta Sharpe 大于 0。",
            "- REJECT：其余；上游数据可保留，研究深挖继续冻结。",
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- 本检验不修改 composite_score，不自动反转方向，不触发交易指令。",
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifacts = (result.comparison_path, result.json_path, result.markdown_path)
    manifest = {
        **result.to_summary(),
        "decision_rule_version": OVERLAY_DECISION_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_records(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_warnings(path: Path, *, run_id: str, warnings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("run_id", "warning"))
        writer.writeheader()
        for warning in warnings:
            writer.writerow({"run_id": run_id, "warning": warning})


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _json_safe(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item.isoformat() if isinstance(item, date) else item
        for key, item in value.items()
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(spec: StrategySpec) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{spec.strategy_id}_{spec.version}_{stamp}_{uuid.uuid4().hex[:8]}"
