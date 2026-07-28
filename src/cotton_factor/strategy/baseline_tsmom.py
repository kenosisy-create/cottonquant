"""R87 baseline TSMOM backtest orchestration and artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.backtest import (
    DailyBacktestResult,
    NotionalBpsCostModel,
    run_daily_backtest,
)
from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.contract_master import load_product_config
from cotton_factor.core.schemas import (
    BacktestTargetLotDailyRow,
    CoreTradeMappingDailyRow,
    ResearchContinuousPriceDailyRow,
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

BACKTEST_RULE_VERSION = "V5.1_R87_baseline_backtest_v1"
RESEARCH_BOUNDARY = (
    "研究仿真、无未来函数，不构成交易指令；NAV为研究记账值，非真实资金。"
)


@dataclass(frozen=True)
class StrategyBacktestResult:
    """R87 multi-cost historical backtest artifacts."""

    run_id: str
    strategy_key: str
    start: date
    end: date
    spec_path: Path
    target_path: Path
    diagnostic_path: Path
    daily_path: Path
    fill_path: Path
    order_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    target_row_count: int
    daily_row_count: int
    fill_count: int
    metrics_by_scenario: dict[str, dict[str, float | int]]
    warning_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "run_id": self.run_id,
            "strategy_key": self.strategy_key,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "spec_path": str(self.spec_path),
            "target_path": str(self.target_path),
            "diagnostic_path": str(self.diagnostic_path),
            "daily_path": str(self.daily_path),
            "fill_path": str(self.fill_path),
            "order_path": str(self.order_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "target_row_count": self.target_row_count,
            "daily_row_count": self.daily_row_count,
            "fill_count": self.fill_count,
            "metrics_by_scenario": self.metrics_by_scenario,
            "warning_count": self.warning_count,
        }


def run_cf_tsmom_backtest(
    *,
    spec_path: Path,
    start: date | None = None,
    end: date | None = None,
    continuous_price_path: Path | None = None,
    trade_mapping_path: Path | None = None,
    core_quote_path: Path | None = None,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> StrategyBacktestResult:
    """Run the fixed V5.1 CF baseline through the existing D16 engine."""
    spec = load_strategy_spec(spec_path)
    if spec.strategy_type != "baseline_tsmom":
        raise StrategyError("R87 run-backtest currently requires baseline_tsmom")
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
        raise StrategyError("CF multiplier must be confirmed before strategy backtest")

    available_dates = sorted(row.trade_date for row in mappings)
    selected_start = start or available_dates[0]
    selected_end = end or available_dates[-1]
    if selected_start > selected_end:
        raise StrategyError("backtest start must be <= end")
    if selected_start < available_dates[0] or selected_end > available_dates[-1]:
        raise StrategyError(
            f"backtest range must stay within mapping coverage {available_dates[0]} "
            f"to {available_dates[-1]}"
        )

    active_run_id = run_id or _default_run_id(spec)
    targets = build_tsmom_targets(
        spec=spec,
        continuous_rows=continuous,
        trade_mappings=mappings,
        quotes=quotes,
        multiplier=float(config.multiplier),
        run_id=active_run_id,
    )
    selected_targets = tuple(
        row
        for row in targets.target_rows
        if selected_start <= row.trade_date <= selected_end
    )
    selected_diagnostics = tuple(
        row
        for row in targets.diagnostics
        if selected_start <= row["trade_date"] <= selected_end
    )
    if not selected_targets:
        raise StrategyError("selected backtest range contains no target rows")

    contracts = engine_contracts_from_quotes(quotes)
    daily_frames: list[pd.DataFrame] = []
    fills: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    warnings = list(targets.warnings)
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
            backtest_rule_version=BACKTEST_RULE_VERSION,
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
    _write_model_rows(paths["targets"], selected_targets)
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
    _write_json(result=result, spec=spec, daily=daily)
    _write_markdown(result=result, spec=spec, daily=daily)
    _write_manifest(
        result=result,
        input_paths=(spec_path, continuous_path, mapping_path, quote_path),
    )
    return result


def _daily_frame(
    *,
    engine_result: DailyBacktestResult,
    scenario: str,
    one_way_bps: float,
    capital_base: float,
    diagnostics: tuple[dict[str, object], ...],
) -> pd.DataFrame:
    diagnostic_by_date = {row["trade_date"]: row for row in diagnostics}
    positions_by_date: dict[date, list[object]] = {}
    for position in engine_result.positions:
        positions_by_date.setdefault(position.execution_date, []).append(position)
    fills_by_date: dict[date, list[object]] = {}
    for fill in engine_result.fills:
        fills_by_date.setdefault(fill.execution_date, []).append(fill)

    rows: list[dict[str, object]] = []
    previous_equity = 0.0
    previous_cost = 0.0
    high_watermark = capital_base
    for point in engine_result.equity_curve:
        positions = positions_by_date.get(point.execution_date, [])
        day_fills = fills_by_date.get(point.execution_date, [])
        held_lots = sum(position.lots for position in positions)
        held_contract = ";".join(
            sorted(position.target_contract for position in positions if position.lots)
        )
        daily_net_pnl = point.total_equity - previous_equity
        daily_cost = point.cumulative_cost - previous_cost
        nav = capital_base + point.total_equity
        high_watermark = max(high_watermark, nav)
        diagnostic = diagnostic_by_date[point.trade_date]
        rows.append(
            {
                "cost_scenario": scenario,
                "one_way_bps": one_way_bps,
                "signal_date": point.trade_date,
                "execution_date": point.execution_date,
                "mapped_contract": diagnostic["mapped_contract"],
                "held_contract": held_contract,
                "held_lots": held_lots,
                "target_lots": diagnostic["target_lots"],
                "direction": diagnostic["direction"],
                "momentum": diagnostic["momentum"],
                "annualized_sigma": diagnostic["annualized_sigma"],
                "daily_gross_pnl": daily_net_pnl + daily_cost,
                "daily_cost": daily_cost,
                "daily_net_pnl": daily_net_pnl,
                "cumulative_cost": point.cumulative_cost,
                "trading_equity": point.total_equity,
                "nav": nav,
                "high_watermark": high_watermark,
                "drawdown": nav / high_watermark - 1.0,
                "turnover_lots": sum(abs(fill.fill_lots) for fill in day_fills),
                "turnover_notional": sum(fill.notional for fill in day_fills),
                "warning_code": diagnostic["warning_code"],
            }
        )
        previous_equity = point.total_equity
        previous_cost = point.cumulative_cost
    return pd.DataFrame(rows)


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


def _write_model_rows(path: Path, rows: tuple[BacktestTargetLotDailyRow, ...]) -> None:
    _write_records(path, [row.model_dump(mode="json") for row in rows])


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


def _write_json(
    *,
    result: StrategyBacktestResult,
    spec: StrategySpec,
    daily: pd.DataFrame,
) -> None:
    yearly = _yearly_metrics(daily=daily, spec=spec)
    payload = {
        **result.to_summary(),
        "backtest_rule_version": BACKTEST_RULE_VERSION,
        "yearly_metrics": yearly,
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(
    *,
    result: StrategyBacktestResult,
    spec: StrategySpec,
    daily: pd.DataFrame,
) -> None:
    lines = [
        f"# CF 基准策略回测：{result.strategy_key}",
        "",
        f"- 区间：`{result.start}` 至 `{result.end}`",
        f"- 目标行数：`{result.target_row_count}`",
        f"- 成交记录数（三成本档合计）：`{result.fill_count}`",
        "- 执行：`T日结算后生成目标，T+1真实合约结算成交`",
        "",
        "## 全历史结果",
        "",
        "| 成本档 | 累计收益 | 年化收益 | 年化波动 | Sharpe | 最大回撤 | 换手手数 | 总成本 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for scenario, metrics in result.metrics_by_scenario.items():
        lines.append(
            f"| {scenario} | {_pct(metrics['cumulative_return'])} | "
            f"{_pct(metrics['annualized_return'])} | "
            f"{_pct(metrics['annualized_volatility'])} | "
            f"{float(metrics['sharpe']):.3f} | {_pct(metrics['max_drawdown'])} | "
            f"{float(metrics['turnover_lots']):.0f} | {float(metrics['total_cost']):.2f} |"
        )
    lines.extend(
        [
            "",
            "## 逐年结果（normal cost）",
            "",
            "| 年度 | 观察数 | 累计收益 | Sharpe | 最大回撤 | 在场日 | 完成持仓事件 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in _yearly_metrics(daily=daily, spec=spec):
        lines.append(
            f"| {row['year']} | {row['observation_count']} | "
            f"{_pct(row['cumulative_return'])} | {row['sharpe']:.3f} | "
            f"{_pct(row['max_drawdown'])} | {row['active_days']} | "
            f"{row['completed_trades']} |"
        )
    lines.extend(["", "## 研究边界", "", f"- {RESEARCH_BOUNDARY}"])
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(
    *,
    result: StrategyBacktestResult,
    input_paths: tuple[Path, ...],
) -> None:
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
    payload = {
        **result.to_summary(),
        "backtest_rule_version": BACKTEST_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _yearly_metrics(*, daily: pd.DataFrame, spec: StrategySpec) -> list[dict[str, object]]:
    normal = daily.loc[daily["cost_scenario"].eq("normal_cost")].copy()
    normal["year"] = pd.to_datetime(normal["execution_date"]).dt.year
    rows: list[dict[str, object]] = []
    for year, frame in normal.groupby("year", sort=True):
        ordered = frame.sort_values("execution_date")
        starting_nav = float(ordered.iloc[0]["nav"] - ordered.iloc[0]["daily_net_pnl"])
        metrics = strategy_metrics(
            ordered,
            capital_base=spec.sizing.capital_base,
            starting_nav=starting_nav,
        )
        rows.append({"year": int(year), **metrics})
    return rows


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


def _pct(value: object) -> str:
    return f"{float(value):.2%}"


def _default_run_id(spec: StrategySpec) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{spec.strategy_id}_{spec.version}_{stamp}_{uuid.uuid4().hex[:8]}"
