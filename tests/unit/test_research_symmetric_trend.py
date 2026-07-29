from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.symmetric_trend_research import (
    build_cf_symmetric_trend_research,
)


def test_symmetric_trend_keeps_long_and_short_direction_separate(tmp_path: Path) -> None:
    continuous_path, context_path = _write_fixture(tmp_path)

    result = build_cf_symmetric_trend_research(
        continuous_price_path=continuous_path,
        trend_context_path=context_path,
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="symmetric_fixture",
        fast_window=5,
        slow_window=10,
        breakout_window=5,
        breakout_cooldown=3,
        horizons=(1, 3, 5),
        min_sample_size=2,
    )

    daily = pd.read_parquet(result.daily_path)
    events = pd.read_parquet(result.breakout_event_path)
    summary = pd.read_parquet(result.breakout_summary_path)
    assert {"long", "short"}.issubset(set(daily["trend_direction"]))
    assert {"long", "short"}.issubset(set(events["direction"]))
    assert not any("forward" in column.lower() for column in daily.columns)
    assert not any("future" in column.lower() for column in daily.columns)
    assert daily["state_uses_t_or_earlier"].all()
    assert events["historical_posterior_label"].all()
    assert summary["independent_episode_count"].le(summary["sample_count"]).all()
    assert summary["independent_hit_rate_ci_lower"].le(
        summary["independent_hit_rate_ci_upper"]
    ).all()
    assert set(events["outcome"]).issubset(
        {"FOLLOW_THROUGH", "FAILED_BREAKOUT", "UNRESOLVED", "CURRENT_ONLY"}
    )
    assert result.current_direction == "short"
    assert result.breakout_event_count > 0
    assert result.episode_count > 0
    assert any(
        warning.warning_code == "LEGACY_S4_CONFLATES_SHORT_DIRECTION_WITH_END_STAGE"
        for warning in result.warning_records
    )
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "方向与阶段分离" in report
    assert "不修改现有影子策略" in report
    assert "不构成交易指令" in report
    assert result.manifest_path.exists()


def test_symmetric_trend_cli_writes_inspectable_bundle(tmp_path: Path) -> None:
    continuous_path, context_path = _write_fixture(tmp_path)
    output_dir = tmp_path / "cli_data"
    report_dir = tmp_path / "cli_reports"

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-symmetric-trend-research",
            "--continuous-price-path",
            str(continuous_path),
            "--trend-context-path",
            str(context_path),
            "--output-dir",
            str(output_dir),
            "--report-output-dir",
            str(report_dir),
            "--run-id",
            "symmetric_cli_fixture",
            "--fast-window",
            "5",
            "--slow-window",
            "10",
            "--breakout-window",
            "5",
            "--breakout-cooldown",
            "3",
            "--horizons",
            "1,3,5",
            "--min-sample-size",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"].startswith("SYMMETRIC_TREND_READY")
    assert payload["current_direction"] == "short"
    assert Path(payload["daily_path"]).exists()
    assert Path(payload["breakout_event_path"]).exists()
    assert Path(payload["markdown_path"]).exists()


def test_symmetric_trend_rejects_missing_context_columns(tmp_path: Path) -> None:
    continuous_path, context_path = _write_fixture(tmp_path)
    context = pd.read_parquet(context_path).drop(columns=["option_direction"])
    context.to_parquet(context_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="missing columns"):
        build_cf_symmetric_trend_research(
            continuous_price_path=continuous_path,
            trend_context_path=context_path,
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
            fast_window=5,
            slow_window=10,
            breakout_window=5,
        )


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    start = date(2024, 1, 1)
    dates = [start + timedelta(days=index) for index in range(120)]
    rising = np.linspace(100.0, 160.0, 60, endpoint=False)
    falling = np.linspace(160.0, 70.0, 60)
    prices = np.concatenate([rising, falling])
    continuous = pd.DataFrame(
        {
            "trade_date": [value.isoformat() for value in dates],
            "mapped_contract": "CF401",
            "adjusted_price": prices,
        }
    )
    context_rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        direction = "long" if index < 60 else "short"
        context_rows.append(
            {
                "trade_date": trade_date,
                "main_contract": "CF401",
                "phase_v2": "S2" if direction == "long" else "S4",
                "phase_direction": direction,
                "dual_price_state": "BOTH_ABOVE" if direction == "long" else "BOTH_BELOW",
                "participation_state": "LONG_BUILD" if direction == "long" else "SHORT_BUILD",
                "roll_context": "NO_DOMINANT_ROLL",
                "option_direction": direction,
                "confirmation_state": (
                    "CONFIRM_LONG" if direction == "long" else "CONFIRM_SHORT"
                ),
                "confirmation_strength": "high",
                "volatility_repricing_state": "NORMAL_OR_STABLE",
            }
        )
    continuous_path = tmp_path / "continuous.parquet"
    context_path = tmp_path / "context.parquet"
    continuous.to_parquet(continuous_path, index=False)
    pd.DataFrame(context_rows).to_parquet(context_path, index=False)
    return continuous_path, context_path
