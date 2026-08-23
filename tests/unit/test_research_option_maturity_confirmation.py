from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.option_maturity_confirmation import (
    build_cf_option_maturity_confirmation_research,
)


def test_option_maturity_confirmation_separates_stages_and_checkpoints(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)

    result = build_cf_option_maturity_confirmation_research(
        option_core_path=paths["core"],
        trend_confirmation_event_path=paths["events"],
        trend_confirmation_trajectory_path=paths["trajectory"],
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="option_maturity_fixture",
        horizons=(5,),
        checkpoints=(0, 1, 3),
        activity_window=5,
        activity_min_periods=3,
        min_sample_size=2,
    )

    annual = pd.read_parquet(result.activity_annual_path).set_index("calendar_year")
    features = pd.read_parquet(result.checkpoint_feature_path)
    validation = pd.read_parquet(result.checkpoint_validation_path)
    summary = pd.read_parquet(result.stage_summary_path)

    assert annual.loc[2021, "option_market_stage"] == "EARLY_THIN"
    assert annual.loc[2022, "option_market_stage"] == "EXPANSION"
    assert annual.loc[2024, "option_market_stage"] == "MATURE_ACTIVE"
    assert annual.loc[2022, "median_daily_volume_vs_2021"] == pytest.approx(3.0)
    assert annual.loc[2024, "median_daily_oi_vs_2021"] == pytest.approx(3.0)
    assert set(features["option_market_stage"]) == {
        "EARLY_THIN",
        "EXPANSION",
        "MATURE_ACTIVE",
    }
    assert features["features_use_checkpoint_or_earlier"].all()
    assert features["contains_posterior_outcome"].eq(False).all()  # noqa: E712
    assert "remaining_outcome" not in features.columns
    assert "remaining_directional_return" not in features.columns
    assert validation["historical_posterior_label"].all()
    assert validation["validation_uses_post_checkpoint_prices"].all()
    assert not validation["promotion_eligible"].any()
    assert not summary["promotion_eligible"].any()

    t0 = features.loc[features["checkpoint_session"].eq(0)].set_index("event_id")
    t3 = features.loc[features["checkpoint_session"].eq(3)].set_index("event_id")
    assert t0.loc["EP2021_0", "option_confirmed_by_checkpoint"]
    assert not t0.loc["EP2021_1", "option_confirmed_by_checkpoint"]
    assert t3.loc["EP2021_1", "option_confirmed_by_checkpoint"]

    report = result.markdown_path.read_text(encoding="utf-8")
    assert "2022-2023为EXPANSION" in report
    assert "## 年份阶段检查点证据" in report
    assert "## 滚动活跃状态检查点证据" in report
    assert "EARLY_BASELINE" in report
    assert "不代表存在可交易的反向Alpha" in report
    assert "检查点后的价格只进入" in report
    assert "不构成交易指令" in report
    for path in (
        result.activity_daily_path,
        result.activity_annual_path,
        result.checkpoint_feature_path,
        result.checkpoint_validation_path,
        result.stage_summary_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
        result.manifest_path,
    ):
        assert path.exists() and path.stat().st_size > 0


def test_option_maturity_confirmation_cli_writes_bundle(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    invocation = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-option-maturity-confirmation-research",
            "--option-core-path",
            str(paths["core"]),
            "--trend-confirmation-event-path",
            str(paths["events"]),
            "--trend-confirmation-trajectory-path",
            str(paths["trajectory"]),
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "option_maturity_cli_fixture",
            "--horizons",
            "5",
            "--checkpoints",
            "0,1,3",
            "--activity-window",
            "5",
            "--activity-min-periods",
            "3",
            "--min-sample-size",
            "2",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads(invocation.stdout)
    assert payload["event_count"] == 12
    assert payload["early_event_count"] == 4
    assert payload["expansion_event_count"] == 4
    assert payload["mature_event_count"] == 4
    assert payload["checkpoint_features_are_asof_safe"] is True
    assert payload["promotion_eligible"] is False
    assert Path(payload["markdown_path"]).exists()
    assert Path(payload["manifest_path"]).exists()


def test_option_maturity_confirmation_rejects_missing_core_field(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)
    core = pd.read_parquet(paths["core"]).drop(columns=["open_interest"])
    core.to_parquet(paths["core"], index=False)

    with pytest.raises(ResearchWorkbenchError, match="缺少字段"):
        build_cf_option_maturity_confirmation_research(
            option_core_path=paths["core"],
            trend_confirmation_event_path=paths["events"],
            trend_confirmation_trajectory_path=paths["trajectory"],
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
            horizons=(5,),
            checkpoints=(0, 1, 3),
            activity_window=5,
            activity_min_periods=3,
        )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    yearly_dates = {
        year: [date(year, 1, 1) + timedelta(days=index) for index in range(30)]
        for year in (2021, 2022, 2024)
    }
    scale = {
        2021: (10, 100),
        2022: (30, 170),
        2024: (50, 300),
    }
    core_rows: list[dict[str, object]] = []
    for year, dates in yearly_dates.items():
        volume, open_interest = scale[year]
        for trade_date in dates:
            for option_index in range(4):
                core_rows.append(
                    {
                        "trade_date": trade_date,
                        "option_symbol": f"CF{year % 100:02d}01C{14000 + option_index * 100}",
                        "underlying_contract": f"CF{year % 100:02d}01",
                        "volume": volume,
                        "open_interest": open_interest,
                        "liquidity_flag": "normal_liquidity",
                    }
                )

    event_rows: list[dict[str, object]] = []
    trajectory_rows: list[dict[str, object]] = []
    for year, dates in yearly_dates.items():
        for event_index, position in enumerate((8, 13, 18, 23)):
            event_id = f"EP{year}_{event_index}"
            successful = event_index % 2 == 0
            event_date = dates[position]
            event_rows.append(
                {
                    "event_id": event_id,
                    "event_date": event_date,
                    "direction": "long",
                    "direction_episode_id": event_id,
                    "label_available_5d": True,
                    "directional_return_5d": 0.05 if successful else -0.05,
                    "outcome_5d": (
                        "FOLLOW_THROUGH" if successful else "FAILED_BREAKOUT"
                    ),
                }
            )
            for relative_session in range(-2, 6):
                if event_index % 2 == 0:
                    option_confirm = relative_session in {-1, 0, 1, 2, 3, 4, 5}
                else:
                    option_confirm = relative_session in {1, 2, 3, 4, 5}
                price_move = 0.01 * max(relative_session, 0)
                price = 100.0 * (
                    1 + price_move if successful else 1 - price_move
                )
                trajectory_rows.append(
                    {
                        "event_id": event_id,
                        "event_date": event_date,
                        "direction": "long",
                        "relative_session": relative_session,
                        "state_date": event_date + timedelta(days=relative_session),
                        "adjusted_price": price,
                        "option_confirmation_flag": option_confirm,
                        "futures_confirmation_flag": successful,
                        "option_factor_status": "READY",
                        "option_liquidity_score": 50.0,
                    }
                )

    paths = {
        "core": tmp_path / "option_core.parquet",
        "events": tmp_path / "event_index.parquet",
        "trajectory": tmp_path / "trajectory.parquet",
    }
    pd.DataFrame(core_rows).to_parquet(paths["core"], index=False)
    pd.DataFrame(event_rows).to_parquet(paths["events"], index=False)
    pd.DataFrame(trajectory_rows).to_parquet(paths["trajectory"], index=False)
    return paths
