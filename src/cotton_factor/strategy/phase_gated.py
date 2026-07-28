"""R89 fixed phase/carry/option gated candidate strategy."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.backtest import NotionalBpsCostModel, run_daily_backtest
from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.contract_master import load_product_config
from cotton_factor.core.schemas import (
    BacktestTargetLotDailyRow,
    CoreTradeMappingDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.strategy.baseline_tsmom import (
    StrategyBacktestResult,
    _daily_frame,
)
from cotton_factor.strategy.io import (
    default_core_quote_path,
    engine_contracts_from_quotes,
    latest_strategy_input_paths,
    load_core_quotes,
    load_typed_parquet,
)
from cotton_factor.strategy.metrics import strategy_metrics
from cotton_factor.strategy.signals import build_tsmom_targets
from cotton_factor.strategy.spec import StrategySpec, load_strategy_spec

PHASE_GATED_TARGET_RULE_VERSION = "V5.1_R89_phase_gated_target_v1"
PHASE_GATED_BACKTEST_RULE_VERSION = "V5.1_R89_phase_gated_backtest_v1"
RESEARCH_BOUNDARY = "研究仿真、无未来函数，不构成交易指令；期权只作门控研究。"


def run_cf_phase_gated_backtest(
    *,
    spec_path: Path,
    start: date | None = None,
    end: date | None = None,
    continuous_price_path: Path | None = None,
    trade_mapping_path: Path | None = None,
    core_quote_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    trend_phase_path: Path | None = None,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> StrategyBacktestResult:
    """Run the ex-ante fixed candidate through the shared D16 engine."""
    spec = load_strategy_spec(spec_path)
    if spec.strategy_type != "phase_gated":
        raise StrategyError("R89 requires a phase_gated strategy spec")
    bundle = (
        latest_strategy_input_paths(input_dir)
        if continuous_price_path is None or trade_mapping_path is None
        else {}
    )
    continuous_path = continuous_price_path or bundle["continuous"]
    mapping_path = trade_mapping_path or bundle["trade"]
    quote_path = core_quote_path or default_core_quote_path()
    matrix_path = signal_matrix_path or _latest_signal_matrix_path()
    phase_path = trend_phase_path or _latest_trend_phase_path()

    continuous = load_typed_parquet(continuous_path, ResearchContinuousPriceDailyRow)
    mappings = load_typed_parquet(mapping_path, CoreTradeMappingDailyRow)
    quotes = load_core_quotes(quote_path)
    config = load_product_config("CF")
    if not isinstance(config.multiplier, int | float):
        raise StrategyError("CF multiplier must be confirmed before strategy backtest")
    base_spec_path = Path("configs/strategy/CF_tsmom_v0.yaml")
    base_spec = load_strategy_spec(base_spec_path)
    active_run_id = run_id or _default_run_id(spec)
    base_targets = build_tsmom_targets(
        spec=base_spec,
        continuous_rows=continuous,
        trade_mappings=mappings,
        quotes=quotes,
        multiplier=float(config.multiplier),
        run_id=f"{active_run_id}_base",
    )
    matrix = _load_signal_matrix(matrix_path, horizon=spec.signal_horizon)
    phases = _load_trend_phase(phase_path)
    candidate_targets, diagnostics, gate_warnings = build_phase_gated_targets(
        spec=spec,
        base_rows=list(base_targets.target_rows),
        base_diagnostics=list(base_targets.diagnostics),
        signal_matrix=matrix,
        trend_phase=phases,
        run_id=active_run_id,
    )

    available_dates = sorted(row.trade_date for row in candidate_targets)
    selected_start = start or available_dates[0]
    selected_end = end or available_dates[-1]
    if selected_start > selected_end:
        raise StrategyError("candidate backtest start must be <= end")
    if selected_start < available_dates[0] or selected_end > available_dates[-1]:
        raise StrategyError(
            f"candidate range must stay within {available_dates[0]} to {available_dates[-1]}"
        )
    selected_targets = tuple(
        row for row in candidate_targets if selected_start <= row.trade_date <= selected_end
    )
    selected_diagnostics = tuple(
        row for row in diagnostics if selected_start <= row["trade_date"] <= selected_end
    )
    contracts = engine_contracts_from_quotes(quotes)
    daily_frames: list[pd.DataFrame] = []
    fills: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    warnings = [*base_targets.warnings, *gate_warnings]
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
            backtest_rule_version=PHASE_GATED_BACKTEST_RULE_VERSION,
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
    paths = _output_paths(
        spec=spec,
        start=selected_start,
        end=selected_end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_parquet(paths["targets"], [row.model_dump(mode="json") for row in selected_targets])
    _write_parquet(paths["diagnostics"], list(selected_diagnostics))
    _write_parquet(paths["daily"], daily.to_dict(orient="records"))
    _write_parquet(paths["fills"], fills)
    _write_parquet(paths["orders"], orders)
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
    _write_result_files(
        result=result,
        diagnostics=pd.DataFrame(selected_diagnostics),
        input_paths=(spec_path, continuous_path, mapping_path, quote_path, matrix_path, phase_path),
    )
    return result


def build_phase_gated_targets(
    *,
    spec: StrategySpec,
    base_rows: list[BacktestTargetLotDailyRow],
    base_diagnostics: list[dict[str, object]],
    signal_matrix: pd.DataFrame,
    trend_phase: pd.DataFrame,
    run_id: str,
) -> tuple[
    tuple[BacktestTargetLotDailyRow, ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    """Apply only T-day phase, carry and explicit option-direction gates."""
    if spec.strategy_type != "phase_gated":
        raise StrategyError("phase-gated target builder received another strategy type")
    matrix_by_date = _rows_by_date(signal_matrix)
    phase_by_date = _rows_by_date(trend_phase)
    base_diag_by_date = {row["trade_date"]: row for row in base_diagnostics}
    phase_rule = _gate(spec, "phase").parameters
    carry_rule = _gate(spec, "carry_tilt").parameters
    option_rule = _gate(spec, "option_veto").parameters
    targets: list[BacktestTargetLotDailyRow] = []
    diagnostics: list[dict[str, object]] = []
    warnings: list[str] = []
    previous_target = 0

    for base in sorted(base_rows, key=lambda row: row.trade_date):
        base_diag = base_diag_by_date[base.trade_date]
        direction = int(base_diag["direction"])
        phase_row = phase_by_date.get(base.trade_date)
        matrix_row = matrix_by_date.get(base.trade_date)
        g_phase, phase_code, phase_warning = _phase_multiplier(
            row=phase_row,
            direction=direction,
            parameters=phase_rule,
        )
        g_carry = _carry_multiplier(
            row=matrix_row,
            direction=direction,
            parameters=carry_rule,
        )
        g_option, option_warning = _option_multiplier(
            row=matrix_row,
            direction=direction,
            parameters=option_rule,
        )
        raw_target = int(round(base.target_lots * g_phase * g_carry * g_option))
        if phase_code == "S3":
            raw_target = _s3_no_add(raw_target=raw_target, previous_target=previous_target)
        target_lots = 0 if base.is_blocked else raw_target
        warning_codes = [value for value in (phase_warning, option_warning) if value]
        warnings.extend(f"{base.trade_date}: {value}" for value in warning_codes)
        snapshots = list(base.input_snapshot_ids)
        if matrix_row is not None:
            source = str(matrix_row.get("source_snapshot_ids", "")).strip()
            if source and source not in snapshots:
                snapshots.append(source)
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
                target_rule_version=PHASE_GATED_TARGET_RULE_VERSION,
                input_snapshot_ids=snapshots,
            )
        )
        diagnostics.append(
            {
                **base_diag,
                "base_target_lots": base.target_lots,
                "target_lots": target_lots,
                "phase_code": phase_code,
                "g_phase": g_phase,
                "g_carry": g_carry,
                "g_option": g_option,
                "gate_warning": ";".join(warning_codes),
            }
        )
        previous_target = target_lots
    return tuple(targets), tuple(diagnostics), tuple(sorted(set(warnings)))


def _phase_multiplier(
    *,
    row: dict[str, object] | None,
    direction: int,
    parameters: dict[str, object],
) -> tuple[float, str, str]:
    if row is None:
        return float(parameters["missing_multiplier"]), "MISSING", "MISSING_TREND_PHASE"
    phase_code = str(row["phase_v2"])
    multiplier = float(parameters.get(phase_code, parameters["missing_multiplier"]))
    phase_direction = str(row.get("phase_direction", "neutral"))
    direction_label = "long" if direction > 0 else "short" if direction < 0 else "neutral"
    if direction and phase_direction in {"long", "short"} and phase_direction != direction_label:
        return float(parameters["conflict_multiplier"]), phase_code, ""
    return multiplier, phase_code, ""


def _carry_multiplier(
    *,
    row: dict[str, object] | None,
    direction: int,
    parameters: dict[str, object],
) -> float:
    if row is None or direction == 0:
        return float(parameters["missing"])
    carry = str(row.get("carry_signal", "neutral"))
    direction_label = "long" if direction > 0 else "short"
    if carry == direction_label:
        return float(parameters["agree"])
    if carry in {"long", "short"}:
        return float(parameters["disagree"])
    return float(parameters["missing"])


def _option_multiplier(
    *,
    row: dict[str, object] | None,
    direction: int,
    parameters: dict[str, object],
) -> tuple[float, str]:
    if row is None or direction == 0:
        return float(parameters["missing_or_not_connected"]), ""
    signal = str(row.get("option_signal", "not_connected"))
    option_direction = str(row.get("option_signal_direction", "unknown"))
    if signal == "volatility_risk":
        return float(parameters["volatility_risk_multiplier"]), ""
    if signal not in {"diverge_long", "diverge_short"}:
        return float(parameters["missing_or_not_connected"]), ""
    direction_label = "long" if direction > 0 else "short"
    expected_option_direction = "short" if signal == "diverge_long" else "long"
    if option_direction != expected_option_direction:
        return 1.0, "OPTION_DIVERGENCE_SEMANTIC_CONFLICT"
    if option_direction != direction_label:
        return float(parameters["divergence_multiplier"]), ""
    return 1.0, ""


def _s3_no_add(*, raw_target: int, previous_target: int) -> int:
    if raw_target == 0 or previous_target == 0:
        return 0
    if (raw_target > 0) != (previous_target > 0):
        return 0
    magnitude = min(abs(raw_target), abs(previous_target))
    return magnitude if raw_target > 0 else -magnitude


def _gate(spec: StrategySpec, name: str) -> object:
    matches = [rule for rule in spec.gate_rules if rule.name == name]
    if len(matches) != 1:
        raise StrategyError(f"phase-gated spec requires exactly one {name} rule")
    return matches[0]


def _load_signal_matrix(path: Path, *, horizon: int) -> pd.DataFrame:
    required = [
        "trade_date",
        "horizon",
        "carry_signal",
        "option_signal",
        "option_signal_direction",
        "source_snapshot_ids",
    ]
    frame = pd.read_parquet(path, columns=required)
    selected = frame.loc[frame["horizon"].eq(horizon)].copy()
    if selected.empty:
        raise StrategyError(f"signal matrix has no {horizon}D rows: {path}")
    selected["trade_date"] = pd.to_datetime(selected["trade_date"]).dt.date
    if selected["trade_date"].duplicated().any():
        raise StrategyError("signal matrix contains duplicate horizon/date rows")
    return selected


def _load_trend_phase(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=["trade_date", "phase_v2", "phase_direction"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    if frame["trade_date"].duplicated().any():
        raise StrategyError("trend phase table contains duplicate dates")
    return frame


def _rows_by_date(frame: pd.DataFrame) -> dict[date, dict[str, object]]:
    return {
        row["trade_date"]: row
        for row in frame.to_dict(orient="records")
    }


def _latest_signal_matrix_path() -> Path:
    root = data_dir() / "research" / "CF" / "signal_matrix"
    paths = sorted(root.glob("*_signal_matrix_daily.parquet"))
    if not paths:
        raise StrategyError(f"signal matrix daily artifact not found under {root}")
    return paths[-1]


def _latest_trend_phase_path() -> Path:
    root = data_dir() / "research" / "CF" / "trend_phase_v2"
    paths = sorted(root.glob("*_trend_phase_v2_daily.parquet"))
    if not paths:
        raise StrategyError(f"trend phase v2 artifact not found under {root}")
    return paths[-1]


def _output_paths(
    *,
    spec: StrategySpec,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "strategy" / "CF" / spec.strategy_id
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


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_warnings(path: Path, *, run_id: str, warnings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("run_id", "warning"))
        writer.writeheader()
        for warning in warnings:
            writer.writerow({"run_id": run_id, "warning": warning})


def _write_result_files(
    *,
    result: StrategyBacktestResult,
    diagnostics: pd.DataFrame,
    input_paths: tuple[Path, ...],
) -> None:
    payload = {
        **result.to_summary(),
        "backtest_rule_version": PHASE_GATED_BACKTEST_RULE_VERSION,
        "gate_counts": {
            column: diagnostics[column].value_counts(dropna=False).to_dict()
            for column in ("phase_code", "g_phase", "g_carry", "g_option")
        },
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# CF 门控候选策略回测：{result.strategy_key}",
        "",
        f"- 区间：`{result.start}` 至 `{result.end}`",
        "- 输入：20D signal_matrix_daily + trend_phase_v2_daily",
        "- 期权背离只有在标签与显式方向同时成立时才生效。",
        "",
        "| 成本档 | 累计收益 | Sharpe | 最大回撤 | 总成本 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for scenario, metrics in result.metrics_by_scenario.items():
        lines.append(
            f"| {scenario} | {float(metrics['cumulative_return']):.2%} | "
            f"{float(metrics['sharpe']):.3f} | "
            f"{float(metrics['max_drawdown']):.2%} | "
            f"{float(metrics['total_cost']):.2f} |"
        )
    lines.extend(["", "## 研究边界", "", f"- {RESEARCH_BOUNDARY}"])
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
        "backtest_rule_version": PHASE_GATED_BACKTEST_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
