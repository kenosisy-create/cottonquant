"""R88 strategy-level historical evaluation and phase attribution."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.strategy.metrics import strategy_metrics
from cotton_factor.strategy.spec import StrategySpec, load_strategy_spec

EVALUATION_RULE_VERSION = "V5.1_R88_strategy_evaluation_v1"
RESEARCH_BOUNDARY = "阶段归因属于历史后验描述，不回流信号；不构成交易指令。"


@dataclass(frozen=True)
class StrategyEvaluationResult:
    """R88 window and phase evaluation artifacts."""

    run_id: str
    strategy_key: str
    backtest_daily_path: Path
    window_path: Path
    phase_attribution_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    window_row_count: int
    phase_row_count: int
    warning_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a machine-readable CLI summary."""
        return {
            "run_id": self.run_id,
            "strategy_key": self.strategy_key,
            "backtest_daily_path": str(self.backtest_daily_path),
            "window_path": str(self.window_path),
            "phase_attribution_path": str(self.phase_attribution_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "window_row_count": self.window_row_count,
            "phase_row_count": self.phase_row_count,
            "warning_count": self.warning_count,
        }


def evaluate_cf_strategy(
    *,
    spec_path: Path,
    backtest_daily_path: Path | None = None,
    trend_phase_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> StrategyEvaluationResult:
    """Evaluate one fixed strategy without parameter selection."""
    spec = load_strategy_spec(spec_path)
    daily_path = backtest_daily_path or _latest_backtest_path(spec)
    daily = _load_daily(daily_path)
    phase_path = trend_phase_path or _latest_phase_path(required=False)
    phase_by_date = _load_phase_by_date(phase_path) if phase_path else {}
    windows = _window_definitions(daily)
    warnings: list[str] = []
    window_rows: list[dict[str, object]] = []
    phase_rows: list[dict[str, object]] = []

    for window_id, window_type, start_year, end_year in windows:
        window = daily.loc[
            pd.to_datetime(daily["execution_date"]).dt.year.between(start_year, end_year)
        ].copy()
        if window.empty:
            warnings.append(f"{window_id}: EMPTY_WINDOW")
            continue
        for scenario, scenario_frame in window.groupby("cost_scenario", sort=True):
            ordered = scenario_frame.sort_values("execution_date").reset_index(drop=True)
            starting_nav = float(ordered.iloc[0]["nav"] - ordered.iloc[0]["daily_net_pnl"])
            metrics = strategy_metrics(
                ordered,
                capital_base=spec.sizing.capital_base,
                starting_nav=starting_nav,
            )
            metrics.update(_extended_metrics(ordered, starting_nav=starting_nav))
            window_rows.append(
                {
                    "strategy_key": spec.spec_key,
                    "window_id": window_id,
                    "window_type": window_type,
                    "start_year": start_year,
                    "end_year": end_year,
                    "cost_scenario": scenario,
                    **metrics,
                }
            )
            phase_rows.extend(
                _phase_attribution_rows(
                    frame=ordered,
                    phase_by_date=phase_by_date,
                    strategy_key=spec.spec_key,
                    window_id=window_id,
                    scenario=str(scenario),
                )
            )
    if not window_rows:
        raise StrategyError("strategy evaluation produced no window rows")
    _assert_phase_reconciliation(window_rows=window_rows, phase_rows=phase_rows)

    active_run_id = run_id or _default_run_id(spec)
    paths = _output_paths(
        spec=spec,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    window_frame = pd.DataFrame(window_rows)
    phase_frame = pd.DataFrame(phase_rows)
    paths["window"].parent.mkdir(parents=True, exist_ok=True)
    window_frame.to_parquet(paths["window"], index=False)
    phase_frame.to_parquet(paths["phase"], index=False)
    _write_warnings(paths["warnings"], run_id=active_run_id, warnings=warnings)
    result = StrategyEvaluationResult(
        run_id=active_run_id,
        strategy_key=spec.spec_key,
        backtest_daily_path=daily_path,
        window_path=paths["window"],
        phase_attribution_path=paths["phase"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        window_row_count=len(window_frame),
        phase_row_count=len(phase_frame),
        warning_count=len(warnings),
    )
    _write_json(result=result, window_frame=window_frame)
    _write_markdown(result=result, window_frame=window_frame)
    _write_manifest(
        result=result,
        input_paths=tuple(path for path in (spec_path, daily_path, phase_path) if path),
    )
    return result


def _load_daily(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise StrategyError(f"strategy backtest daily path not found: {path}")
    frame = pd.read_parquet(path)
    required = {
        "cost_scenario",
        "signal_date",
        "execution_date",
        "held_lots",
        "daily_gross_pnl",
        "daily_cost",
        "daily_net_pnl",
        "nav",
        "turnover_lots",
        "turnover_notional",
    }
    missing = required - set(frame.columns)
    if missing:
        raise StrategyError(f"strategy daily table missing columns: {sorted(missing)}")
    return frame.copy()


def _window_definitions(daily: pd.DataFrame) -> list[tuple[str, str, int, int]]:
    years = sorted(set(pd.to_datetime(daily["execution_date"]).dt.year.astype(int)))
    windows: list[tuple[str, str, int, int]] = [
        (f"YEAR_{year}", "calendar_year", year, year) for year in years
    ]
    windows.extend(
        (f"ROLL_{year}_{year + 1}", "rolling_two_year", year, year + 1)
        for year in years
        if year + 1 in years
    )
    windows.append((f"FULL_{years[0]}_{years[-1]}", "full_period", years[0], years[-1]))
    return windows


def _extended_metrics(frame: pd.DataFrame, *, starting_nav: float) -> dict[str, float]:
    count = len(frame)
    gross_pnl = float(frame["daily_gross_pnl"].sum())
    net_pnl = float(frame["daily_net_pnl"].sum())
    trade_win_rate = _episode_win_rate(frame)
    return {
        "gross_return": gross_pnl / starting_nav,
        "net_return": net_pnl / starting_nav,
        "cost_drag_return": (gross_pnl - net_pnl) / starting_nav,
        "annual_turnover_lots": float(frame["turnover_lots"].sum() * 252 / count),
        "annual_turnover_notional": float(frame["turnover_notional"].sum() * 252 / count),
        "trade_win_rate": trade_win_rate,
    }


def _episode_win_rate(frame: pd.DataFrame) -> float:
    completed_pnl: list[float] = []
    current_sign = 0
    current_pnl = 0.0
    for row in frame.sort_values("execution_date").itertuples(index=False):
        sign = 1 if row.held_lots > 0 else -1 if row.held_lots < 0 else 0
        if current_sign == 0:
            current_sign = sign
            current_pnl = float(row.daily_net_pnl) if sign != 0 else 0.0
            continue
        current_pnl += float(row.daily_net_pnl)
        if sign != current_sign:
            completed_pnl.append(current_pnl)
            current_sign = sign
            current_pnl = 0.0
    return (
        float(sum(value > 0 for value in completed_pnl) / len(completed_pnl))
        if completed_pnl
        else 0.0
    )


def _load_phase_by_date(path: Path) -> dict[date, str]:
    frame = pd.read_parquet(path, columns=["trade_date", "phase_v2"])
    return {
        pd.to_datetime(row.trade_date).date(): str(row.phase_v2)
        for row in frame.itertuples(index=False)
    }


def _phase_attribution_rows(
    *,
    frame: pd.DataFrame,
    phase_by_date: dict[date, str],
    strategy_key: str,
    window_id: str,
    scenario: str,
) -> list[dict[str, object]]:
    working = frame.copy()
    working["phase"] = [
        phase_by_date.get(pd.to_datetime(value).date(), "UNKNOWN")
        for value in working["signal_date"]
    ]
    return [
        {
            "strategy_key": strategy_key,
            "window_id": window_id,
            "cost_scenario": scenario,
            "phase": phase,
            "observation_count": len(group),
            "net_pnl": float(group["daily_net_pnl"].sum()),
            "gross_pnl": float(group["daily_gross_pnl"].sum()),
            "cost": float(group["daily_cost"].sum()),
        }
        for phase, group in working.groupby("phase", sort=True)
    ]


def _assert_phase_reconciliation(
    *,
    window_rows: list[dict[str, object]],
    phase_rows: list[dict[str, object]],
) -> None:
    phase_frame = pd.DataFrame(phase_rows)
    for row in window_rows:
        selected = phase_frame.loc[
            phase_frame["window_id"].eq(row["window_id"])
            & phase_frame["cost_scenario"].eq(row["cost_scenario"])
        ]
        phase_net = float(selected["net_pnl"].sum())
        expected_net = float(row["net_return"]) * (
            float(row["final_nav"]) / (1.0 + float(row["cumulative_return"]))
        )
        if abs(phase_net - expected_net) > 1e-6:
            raise StrategyError(
                f"phase PnL does not reconcile for {row['window_id']} "
                f"{row['cost_scenario']}"
            )


def _latest_backtest_path(spec: StrategySpec) -> Path:
    root = data_dir() / "strategy" / "CF" / spec.strategy_id
    paths = sorted(root.glob(f"{spec.strategy_id}_{spec.version}_*_backtest_daily.parquet"))
    if not paths:
        raise StrategyError(f"no backtest daily artifact found for {spec.spec_key}")
    return paths[-1]


def _latest_phase_path(*, required: bool) -> Path | None:
    root = data_dir() / "research" / "CF" / "trend_phase_v2"
    paths = sorted(root.glob("*_trend_phase_v2_daily.parquet"))
    if paths:
        return paths[-1]
    if required:
        raise StrategyError(f"trend phase v2 artifact not found under {root}")
    return None


def _output_paths(
    *,
    spec: StrategySpec,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "strategy" / "CF" / spec.strategy_id
    report_root = report_output_dir or reports_dir() / "strategy"
    stem = f"{spec.strategy_id}_{spec.version}_evaluation"
    return {
        "window": root / f"{stem}_window.parquet",
        "phase": root / f"{stem}_phase_attribution.parquet",
        "warnings": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
    }


def _write_warnings(path: Path, *, run_id: str, warnings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("run_id", "warning"))
        writer.writeheader()
        for warning in warnings:
            writer.writerow({"run_id": run_id, "warning": warning})


def _write_json(
    *,
    result: StrategyEvaluationResult,
    window_frame: pd.DataFrame,
) -> None:
    payload = {
        **result.to_summary(),
        "rule_version": EVALUATION_RULE_VERSION,
        "windows": _records_json_safe(window_frame),
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(
    *,
    result: StrategyEvaluationResult,
    window_frame: pd.DataFrame,
) -> None:
    selected = window_frame.loc[
        window_frame["cost_scenario"].eq("conservative_cost")
        & window_frame["window_type"].isin(["calendar_year", "full_period"])
    ]
    lines = [
        f"# CF 策略级验证：{result.strategy_key}",
        "",
        "| 窗口 | 类型 | 观察数 | 净收益 | Sharpe | 最大回撤 | 在场日 | 完成持仓事件 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in selected.itertuples(index=False):
        lines.append(
            f"| {row.window_id} | {row.window_type} | {row.observation_count} | "
            f"{row.net_return:.2%} | {row.sharpe:.3f} | {row.max_drawdown:.2%} | "
            f"{row.active_days} | {row.completed_trades} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- 两年滚动窗口只用于稳定性诊断，不作为独立晋级样本。",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(
    *,
    result: StrategyEvaluationResult,
    input_paths: tuple[Path, ...],
) -> None:
    artifacts = (
        result.window_path,
        result.phase_attribution_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    payload = {
        **result.to_summary(),
        "rule_version": EVALUATION_RULE_VERSION,
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


def _records_json_safe(frame: pd.DataFrame) -> list[dict[str, object]]:
    return json.loads(frame.to_json(orient="records"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(spec: StrategySpec) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{spec.strategy_id}_{spec.version}_evaluation_{stamp}_{uuid.uuid4().hex[:8]}"
