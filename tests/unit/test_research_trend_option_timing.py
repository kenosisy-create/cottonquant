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
from cotton_factor.research_workbench.trend_option_timing import (
    _benjamini_hochberg,
    _fisher_exact_two_sided,
    build_cf_trend_option_timing_research,
)


def test_trend_option_timing_keeps_first_breakout_and_t_day_features(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)

    result = build_cf_trend_option_timing_research(
        symmetric_trend_daily_path=paths["daily"],
        breakout_event_path=paths["events"],
        option_structure_path=paths["option"],
        strike_position_path=paths["strike"],
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="trend_option_fixture",
        rank_window=20,
        rank_min_periods=10,
        min_sample_size=2,
    )

    events = pd.read_parquet(result.event_feature_path)
    summary = pd.read_parquet(result.summary_path)
    source_events = pd.read_parquet(paths["events"])
    option = pd.read_parquet(paths["option"])
    assert len(events) == 12
    assert events.groupby(["direction_episode_id", "horizon"]).size().eq(1).all()
    assert events["event_id"].str.endswith("_FIRST").all()
    assert events["event_features_use_t_or_earlier"].all()
    assert events["feature_asof_date"].eq(events["event_date"]).all()
    assert events["historical_posterior_label"].all()

    expected_iv = option.set_index("trade_date")["atm_iv_proxy"].to_dict()
    for row in events.itertuples(index=False):
        assert row.atm_iv_proxy == pytest.approx(expected_iv[row.event_date])
    assert not events["directional_return"].equals(
        source_events.loc[
            source_events["event_id"].str.endswith("_SECOND"), "directional_return"
        ].reset_index(drop=True)
    )
    assert summary["fdr_q_value"].dropna().between(0.0, 1.0).all()
    assert "incremental_exact_p_value" in summary.columns
    assert result.end == date(2024, 2, 9)
    assert result.event_sample_end < result.end
    assert any(
        warning.warning_code == "R93B_STRIKE_WALL_COVERAGE_PARTIAL"
        for warning in result.warning_records
    )
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "同周期其余独立episode" in report
    assert "方向收益只作为历史后验标签" in report
    assert "不构成交易指令" in report


def test_trend_option_timing_exact_tests_are_bounded() -> None:
    p_value = _fisher_exact_two_sided(
        group_successes=8,
        group_count=10,
        comparison_successes=2,
        comparison_count=10,
    )
    q_values = _benjamini_hochberg([0.01, 0.04, 0.03, 0.20])

    assert p_value < 0.05
    assert all(0.0 <= value <= 1.0 for value in q_values)
    assert q_values[0] <= q_values[1]
    assert q_values[0] <= q_values[2]


def test_trend_option_timing_cli_writes_complete_bundle(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_dir = tmp_path / "cli_data"
    report_dir = tmp_path / "cli_reports"

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-option-timing-research",
            "--symmetric-trend-daily-path",
            str(paths["daily"]),
            "--breakout-event-path",
            str(paths["events"]),
            "--option-structure-path",
            str(paths["option"]),
            "--strike-position-path",
            str(paths["strike"]),
            "--output-dir",
            str(output_dir),
            "--report-output-dir",
            str(report_dir),
            "--run-id",
            "trend_option_cli_fixture",
            "--rank-window",
            "20",
            "--rank-min-periods",
            "10",
            "--min-sample-size",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"].startswith("TREND_OPTION_TIMING_READY")
    assert payload["independent_event_rows"] == 12
    for key in (
        "event_feature_path",
        "summary_path",
        "ranking_path",
        "warning_csv_path",
        "json_path",
        "markdown_path",
        "manifest_path",
    ):
        assert Path(payload[key]).exists()


def test_trend_option_timing_rejects_missing_option_fields(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    option = pd.read_parquet(paths["option"]).drop(columns=["skew_proxy_change_1d"])
    option.to_parquet(paths["option"], index=False)

    with pytest.raises(ResearchWorkbenchError, match="missing columns"):
        build_cf_trend_option_timing_research(
            symmetric_trend_daily_path=paths["daily"],
            breakout_event_path=paths["events"],
            option_structure_path=paths["option"],
            strike_position_path=paths["strike"],
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
            rank_window=20,
            rank_min_periods=10,
        )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    start = date(2024, 1, 1)
    dates = [start + timedelta(days=index) for index in range(40)]
    directions = ["long"] * 10 + ["short"] * 10 + ["long"] * 10 + ["short"] * 10
    episode_ids = ["EP1"] * 10 + ["EP2"] * 10 + ["EP3"] * 10 + ["EP4"] * 10
    daily = pd.DataFrame(
        {
            "trade_date": dates,
            "main_contract": "CF401",
            "trend_direction": directions,
            "trend_stage": ["BREAKOUT" if index % 10 == 4 else "TREND" for index in range(40)],
            "trend_strength": np.linspace(0.25, 0.85, 40),
            "realized_volatility_fast": np.linspace(0.10, 0.30, 40),
            "direction_episode_id": episode_ids,
            "option_alignment": ["CONFIRM" if index % 3 else "DIVERGE" for index in range(40)],
            "participation_alignment": [
                "CONFIRM" if index % 2 else "NEUTRAL_OR_EXIT" for index in range(40)
            ],
            "roll_context": [
                "NO_MAIN_REDUCTION" if index < 30 else "MAIN_REDUCTION" for index in range(40)
            ],
        }
    )
    option = pd.DataFrame(
        {
            "trade_date": dates,
            "underlying_contract": "CF401",
            "atm_iv_proxy": np.linspace(0.08, 0.16, 40),
            "atm_iv_proxy_change_1d": np.sin(np.arange(40) / 3) * 0.002,
            "atm_iv_rank": np.linspace(0.05, 0.95, 40),
            "atm_iv_rank_change_1d": np.cos(np.arange(40) / 4) * 0.02,
            "pcr_volume": np.linspace(0.8, 1.2, 40),
            "pcr_volume_change_1d": np.sin(np.arange(40) / 5) * 0.03,
            "pcr_oi": np.linspace(0.9, 1.1, 40),
            "pcr_oi_change_1d": np.cos(np.arange(40) / 5) * 0.02,
            "skew_proxy": np.linspace(-0.01, 0.01, 40),
            "skew_proxy_change_1d": np.sin(np.arange(40) / 6) * 0.001,
            "volatility_repricing_state": "NORMAL_OR_STABLE",
            "option_liquidity_score": 0.8,
        }
    )
    strike_dates = dates[:-2]
    strike = pd.DataFrame(
        {
            "trade_date": strike_dates,
            "underlying_contract": "CF401",
            "is_main_contract": True,
            "distance_to_call_wall": 0.02,
            "distance_to_put_wall": -0.02,
            "call_wall_oi_change": [100 if index % 2 else -50 for index in range(38)],
            "put_wall_oi_change": [-60 if index % 2 else 120 for index in range(38)],
            "call_wall_strike_shift_1d": [0 if index % 3 else 100 for index in range(38)],
            "put_wall_strike_shift_1d": [0 if index % 3 else -100 for index in range(38)],
            "key_level_state": "BETWEEN_WALLS",
            "key_level_migration_state": "STABLE",
            "expiry_bucket": "MID_TENOR",
        }
    )
    event_rows: list[dict[str, object]] = []
    for episode_number, event_index in enumerate((4, 14, 24, 34), start=1):
        for horizon in (1, 3, 5):
            follow_through = (episode_number + horizon) % 2 == 0
            for suffix, date_offset in (("FIRST", 0), ("SECOND", 1)):
                event_rows.append(
                    {
                        "event_id": f"EP{episode_number}_{horizon}_{suffix}",
                        "event_date": dates[event_index + date_offset],
                        "event_year": 2024,
                        "direction": directions[event_index],
                        "direction_episode_id": f"EP{episode_number}",
                        "main_contract": "CF401",
                        "horizon": horizon,
                        "directional_return": (
                            0.01 if follow_through and suffix == "FIRST" else -0.02
                        ),
                        "label_available": True,
                        "outcome": (
                            "FOLLOW_THROUGH"
                            if follow_through and suffix == "FIRST"
                            else "FAILED_BREAKOUT"
                        ),
                        "historical_posterior_label": True,
                    }
                )
    paths = {
        "daily": tmp_path / "symmetric_daily.parquet",
        "events": tmp_path / "breakout_events.parquet",
        "option": tmp_path / "option_structure.parquet",
        "strike": tmp_path / "strike_position.parquet",
    }
    daily.to_parquet(paths["daily"], index=False)
    pd.DataFrame(event_rows).to_parquet(paths["events"], index=False)
    option.to_parquet(paths["option"], index=False)
    strike.to_parquet(paths["strike"], index=False)
    return paths
