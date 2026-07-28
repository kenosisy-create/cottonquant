from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.strategy.comparison import promotion_decision
from cotton_factor.strategy.evaluation import evaluate_cf_strategy
from cotton_factor.strategy.spec import load_strategy_spec


def test_strategy_evaluation_separates_year_and_rolling_windows(tmp_path: Path) -> None:
    daily_path = tmp_path / "daily.parquet"
    phase_path = tmp_path / "phase.parquet"
    rows = _daily_rows()
    pd.DataFrame(rows).to_parquet(daily_path, index=False)
    pd.DataFrame(
        {
            "trade_date": [row["signal_date"] for row in rows[:4]],
            "phase_v2": ["S1", "S2", "S2", "S3"],
        }
    ).to_parquet(phase_path, index=False)

    result = evaluate_cf_strategy(
        spec_path=Path("configs/strategy/CF_tsmom_v0.yaml"),
        backtest_daily_path=daily_path,
        trend_phase_path=phase_path,
        output_dir=tmp_path / "evaluation",
        report_output_dir=tmp_path / "reports",
        run_id="r88_fixture",
    )

    windows = pd.read_parquet(result.window_path)
    phases = pd.read_parquet(result.phase_attribution_path)
    assert set(windows["window_id"]) == {
        "YEAR_2021",
        "YEAR_2022",
        "ROLL_2021_2022",
        "FULL_2021_2022",
    }
    assert set(phases["phase"]) == {"S1", "S2", "S3"}
    full = windows.loc[windows["window_id"].eq("FULL_2021_2022")].iloc[0]
    phase_total = phases.loc[
        phases["window_id"].eq("FULL_2021_2022"), "net_pnl"
    ].sum()
    assert phase_total == pytest.approx(full["net_return"] * 1_000_000)
    assert "后验描述" in result.markdown_path.read_text(encoding="utf-8")


def test_promotion_decision_passes_only_with_all_fixed_gates() -> None:
    spec = load_strategy_spec(Path("configs/strategy/CF_phase_gated_v0.yaml"))
    assert spec.promotion_rule is not None
    baseline = _evaluation_rows(sharpe=0.2, full_sharpe=0.3)
    candidate = _evaluation_rows(sharpe=0.3, full_sharpe=0.5)

    rows, decision = promotion_decision(
        baseline=baseline,
        candidate=candidate,
        rule=spec.promotion_rule,
    )

    assert len(rows) == 5
    assert decision["decision"] == "PASS"
    assert decision["year_win_count"] == 5

    candidate.loc[candidate["window_id"].eq("YEAR_2021"), "active_days"] = 20
    candidate.loc[candidate["window_id"].eq("YEAR_2022"), "active_days"] = 20
    _, frozen = promotion_decision(
        baseline=baseline,
        candidate=candidate,
        rule=spec.promotion_rule,
    )
    assert frozen["decision"] == "FROZEN"


def _daily_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    nav = 1_000_000.0
    for signal_date, pnl in (
        (date(2021, 1, 4), 1000.0),
        (date(2021, 1, 5), -500.0),
        (date(2022, 1, 4), 1500.0),
        (date(2022, 1, 5), 500.0),
    ):
        nav += pnl
        rows.append(
            {
                "cost_scenario": "conservative_cost",
                "signal_date": signal_date,
                "execution_date": signal_date,
                "held_lots": 1,
                "daily_gross_pnl": pnl + 10.0,
                "daily_cost": 10.0,
                "daily_net_pnl": pnl,
                "nav": nav,
                "turnover_lots": 1,
                "turnover_notional": 50_000.0,
            }
        )
    return rows


def _evaluation_rows(*, sharpe: float, full_sharpe: float) -> pd.DataFrame:
    rows = [
        {
            "window_id": f"YEAR_{year}",
            "window_type": "calendar_year",
            "cost_scenario": "conservative_cost",
            "sharpe": sharpe,
            "max_drawdown": -0.10,
            "net_return": 0.05,
            "active_days": 100,
            "completed_trades": 6,
        }
        for year in range(2021, 2026)
    ]
    rows.append(
        {
            "window_id": "FULL_2021_2026",
            "window_type": "full_period",
            "cost_scenario": "conservative_cost",
            "sharpe": full_sharpe,
            "max_drawdown": -0.11,
            "net_return": 0.10,
            "active_days": 500,
            "completed_trades": 30,
        }
    )
    return pd.DataFrame(rows)
