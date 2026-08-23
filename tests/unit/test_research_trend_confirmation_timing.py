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
from cotton_factor.research_workbench.trend_confirmation_timing import (
    _first_sustained_confirmation,
    _incremental_status,
    build_cf_trend_confirmation_timing_research,
)


def test_trend_confirmation_timing_separates_path_and_posterior_labels(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)

    result = build_cf_trend_confirmation_timing_research(
        symmetric_trend_daily_path=paths["daily"],
        breakout_event_path=paths["events"],
        chain_oi_path=paths["chain"],
        option_structure_path=paths["option"],
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="trend_confirmation_fixture",
        volume_rank_window=20,
        volume_rank_min_periods=5,
        min_sample_size=2,
        min_annual_coverage_years=1,
        min_annual_group_size=1,
    )

    event_index = pd.read_parquet(result.event_index_path)
    trajectory = pd.read_parquet(result.trajectory_path)
    timing = pd.read_parquet(result.timing_event_path).set_index("event_id")
    delay = pd.read_parquet(result.delay_event_path)
    annual = pd.read_parquet(result.annual_summary_path)
    state_summary = pd.read_parquet(result.state_summary_path)

    assert len(event_index) == 4
    assert event_index["direction_episode_id"].is_unique
    assert event_index["event_id"].str.endswith("_FIRST").all()
    assert trajectory["contains_forward_outcome_label"].eq(False).all()  # noqa: E712
    assert "outcome" not in trajectory.columns
    assert "directional_return" not in trajectory.columns
    assert not any(column.startswith("directional_return_") for column in trajectory.columns)
    assert timing.loc["EP1_FIRST", "option_confirmation_session"] == 0
    assert timing.loc["EP2_FIRST", "option_confirmation_session"] == 2
    assert pd.isna(timing.loc["EP3_FIRST", "option_confirmation_session"])
    assert timing.loc["EP1_FIRST", "participation_confirmation_session"] == -1
    assert timing.loc["EP2_FIRST", "participation_confirmation_session"] == 2
    assert delay["historical_posterior_label"].all()
    assert delay["strict_wait_is_counterfactual_research"].all()
    assert delay.loc[
        delay["event_id"].eq("EP3_FIRST")
        & delay["horizon"].eq(5),
        "missed_follow_through",
    ].item()
    assert {
        "comparison_sample_count",
        "delta_hit_rate",
        "delta_mean_directional_return",
        "annual_effect_direction",
    }.issubset(annual.columns)
    assert not state_summary["promotion_eligible"].any()

    for path in (
        result.event_index_path,
        result.trajectory_path,
        result.timing_event_path,
        result.state_summary_path,
        result.trajectory_summary_path,
        result.delay_event_path,
        result.delay_summary_path,
        result.annual_summary_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
        result.manifest_path,
    ):
        assert path.exists() and path.stat().st_size > 0
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "连续确认以第二个连续交易日" in report
    assert "历史后验标签" in report
    assert "不构成交易指令" in report


def test_confirmation_is_known_on_second_consecutive_session() -> None:
    group = pd.DataFrame(
        {
            "relative_session": [-2, -1, 0, 1, 2],
            "state_date": [date(2024, 1, 1) + timedelta(days=i) for i in range(5)],
            "flag": [False, False, False, True, True],
        }
    )

    result = _first_sustained_confirmation(
        group,
        flag_column="flag",
        confirmation_days=2,
    )

    assert result["relative_session"] == 2
    assert result["state_date"] == date(2024, 1, 5)


def test_fdr_result_requires_annual_direction_consistency() -> None:
    base = {
        "sample_count": 20,
        "comparison_sample_count": 30,
        "delta_hit_rate": -0.20,
        "delta_mean_directional_return": -0.03,
        "fdr_q_value": 0.04,
        "annual_eligible_year_count": 3,
        "annual_positive_year_count": 1,
        "annual_negative_year_count": 2,
    }

    unstable = _incremental_status(
        pd.Series(base),
        min_sample_size=15,
        fdr_level=0.10,
        min_annual_coverage_years=3,
        min_annual_direction_consistency=0.75,
    )
    stable = _incremental_status(
        pd.Series({**base, "annual_positive_year_count": 0, "annual_negative_year_count": 3}),
        min_sample_size=15,
        fdr_level=0.10,
        min_annual_coverage_years=3,
        min_annual_direction_consistency=0.75,
    )

    assert unstable == "WATCH_NEGATIVE_ANNUAL_INSTABILITY"
    assert stable == "RESEARCH_FILTER_NEGATIVE"


def test_trend_confirmation_timing_cli_writes_bundle(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    invocation = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-confirmation-timing-research",
            "--symmetric-trend-daily-path",
            str(paths["daily"]),
            "--breakout-event-path",
            str(paths["events"]),
            "--chain-oi-path",
            str(paths["chain"]),
            "--option-structure-path",
            str(paths["option"]),
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "trend_confirmation_cli_fixture",
            "--volume-rank-window",
            "20",
            "--volume-rank-min-periods",
            "5",
            "--min-sample-size",
            "2",
            "--min-annual-coverage-years",
            "1",
            "--min-annual-group-size",
            "1",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads(invocation.stdout)
    assert payload["status"].startswith("TREND_CONFIRMATION_TIMING_READY")
    assert payload["event_count"] == 4
    assert payload["trajectory_row_count"] > 0
    assert payload["historical_returns_are_posterior_labels"] is True
    assert payload["realtime_rule_eligible"] is False
    assert Path(payload["markdown_path"]).exists()
    assert Path(payload["manifest_path"]).exists()


def test_trend_confirmation_timing_rejects_missing_option_field(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)
    option = pd.read_parquet(paths["option"]).drop(columns=["option_direction"])
    option.to_parquet(paths["option"], index=False)

    with pytest.raises(ResearchWorkbenchError, match="缺少字段"):
        build_cf_trend_confirmation_timing_research(
            symmetric_trend_daily_path=paths["daily"],
            breakout_event_path=paths["events"],
            chain_oi_path=paths["chain"],
            option_structure_path=paths["option"],
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
        )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    dates = [date(2024, 1, 1) + timedelta(days=index) for index in range(130)]
    prices = 15_000 + np.arange(130) * 2.0
    daily = pd.DataFrame(
        {
            "trade_date": dates,
            "main_contract": "CF405",
            "adjusted_price": prices,
        }
    )
    chain = pd.DataFrame(
        {
            "trade_date": dates,
            "main_contract": "CF405",
            "main_volume": 100_000 + np.arange(130) * 10,
            "chain_volume": 200_000 + np.arange(130) * 20,
            "chain_open_interest": 500_000 + np.arange(130) * 30,
            "chain_oi_change_ratio": np.sin(np.arange(130) / 8) * 0.01,
            "participation_state": "NEUTRAL",
            "roll_context": "NO_MAIN_REDUCTION",
        }
    )
    option = pd.DataFrame(
        {
            "trade_date": dates,
            "main_contract": "CF405",
            "underlying_contract": "CF405",
            "option_direction": "neutral",
            "option_direction_score": 0.0,
            "factor_status": "READY",
            "option_liquidity_score": 50.0,
            "volatility_repricing_state": "NORMAL_OR_STABLE",
            "atm_iv_proxy": 0.15,
            "atm_iv_proxy_change_1d": 0.0,
            "atm_iv_rank": 0.50,
            "pcr_oi": 1.0,
            "pcr_oi_change_1d": 0.0,
            "skew_proxy": 0.0,
            "skew_proxy_change_1d": 0.0,
        }
    )
    event_positions = (15, 45, 75, 105)
    for position in (14, 15):
        option.loc[position, "option_direction"] = "long"
    for position in (46, 47):
        option.loc[position, "option_direction"] = "long"
    for position in (13, 14):
        chain.loc[position, "participation_state"] = "LONG_BUILD"
    for position in (46, 47):
        chain.loc[position, "participation_state"] = "LONG_BUILD"
    for position in (79, 80):
        chain.loc[position, "participation_state"] = "LONG_BUILD"
    for position in (109, 110):
        option.loc[position, "option_direction"] = "long"

    event_rows: list[dict[str, object]] = []
    for number, position in enumerate(event_positions, start=1):
        for suffix, offset in (("FIRST", 0), ("SECOND", 1)):
            for horizon in (5, 20):
                follow_through = number in {1, 3}
                event_rows.append(
                    {
                        "event_id": f"EP{number}_{suffix}",
                        "event_date": dates[position + offset],
                        "direction": "long",
                        "direction_episode_id": f"EP{number}",
                        "main_contract": "CF405",
                        "horizon": horizon,
                        "directional_return": 0.02 if follow_through else -0.02,
                        "label_available": True,
                        "outcome": (
                            "FOLLOW_THROUGH" if follow_through else "FAILED_BREAKOUT"
                        ),
                        "historical_posterior_label": True,
                        "exit_date": dates[position + offset + horizon],
                    }
                )

    paths = {
        "daily": tmp_path / "symmetric_daily.parquet",
        "events": tmp_path / "breakout_events.parquet",
        "chain": tmp_path / "chain_oi.parquet",
        "option": tmp_path / "option_structure.parquet",
    }
    daily.to_parquet(paths["daily"], index=False)
    pd.DataFrame(event_rows).to_parquet(paths["events"], index=False)
    chain.to_parquet(paths["chain"], index=False)
    option.to_parquet(paths["option"], index=False)
    return paths
