from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_rebound_lifecycle_research


def test_rebound_lifecycle_builds_prepare_trigger_confirm_and_fail(
    tmp_path: Path,
) -> None:
    paths, dates = _write_fixture(tmp_path)

    result = build_cf_rebound_lifecycle_research(
        signal_matrix_path=paths["matrix"],
        symmetric_trend_daily_path=paths["trend"],
        option_structure_path=paths["option"],
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="r93i_unit",
        min_sample_size=1,
    )

    daily = pd.read_parquet(result.daily_path).set_index("trade_date")
    episodes = pd.read_parquet(result.episode_path).sort_values("prepare_date")
    validation = pd.read_parquet(result.validation_path)
    assert daily.loc[dates[5], "lifecycle_state"] == "PREPARE"
    assert daily.loc[dates[7], "lifecycle_state"] == "TRIGGER"
    assert daily.loc[dates[8], "lifecycle_state"] == "CONFIRM"
    assert len(episodes) == 2
    assert episodes.iloc[0]["trigger_date"] == dates[7]
    assert episodes.iloc[0]["confirm_date"] == dates[8]
    assert episodes.iloc[0]["terminal_status"] == "CONFIRMED_WINDOW_COMPLETE"
    assert episodes.iloc[1]["terminal_status"] == "FAILED_PREPARE_TIMEOUT"
    first_validation = validation.loc[validation["horizon"].eq(1)].iloc[0]
    assert first_validation["entry_date"] == dates[8]
    assert first_validation["exit_date"] == dates[9]
    assert first_validation["forward_paths_are_historical_posterior_labels"]
    assert "forward_return" not in daily.columns
    assert result.prepare_to_trigger_rate == 0.5
    assert result.trigger_to_confirm_rate == 1.0
    assert result.daily_path.exists()
    assert result.episode_path.exists()
    assert result.validation_path.exists()
    assert result.summary_path.exists()
    assert result.manifest_path.exists()
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "PREPARE/TRIGGER/CONFIRM/FAIL" in report
    assert "仅为历史后验标签" in report
    assert "不构成交易指令" in report


def test_rebound_lifecycle_cli_writes_complete_bundle(tmp_path: Path) -> None:
    paths, _ = _write_fixture(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-rebound-lifecycle",
            "--signal-matrix-path",
            str(paths["matrix"]),
            "--symmetric-trend-daily-path",
            str(paths["trend"]),
            "--option-structure-path",
            str(paths["option"]),
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--min-sample-size",
            "1",
            "--run-id",
            "r93i_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["episode_count"] == 2
    assert payload["triggered_episode_count"] == 1
    assert payload["confirmed_episode_count"] == 1
    for key in (
        "daily_path",
        "episode_path",
        "validation_path",
        "summary_path",
        "markdown_path",
        "json_path",
        "manifest_path",
    ):
        assert Path(payload[key]).exists()


def _write_fixture(tmp_path: Path) -> tuple[dict[str, Path], list[object]]:
    dates = [value.date() for value in pd.bdate_range("2024-01-02", periods=45)]
    prices = [100.0 + index * 0.05 for index in range(45)]
    prices[5:9] = [98.0, 97.0, 101.0, 102.0]
    for index in range(9, 25):
        prices[index] = 102.0 + (index - 8) * 0.25
    for index in range(25, 45):
        prices[index] = 101.0 - (index - 25) * 0.05

    trend_rows: list[dict[str, object]] = []
    option_rows: list[dict[str, object]] = []
    matrix_rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        trend_rows.append(
            {
                "trade_date": trade_date,
                "main_contract": "CF405",
                "adjusted_price": prices[index],
                "realized_volatility_fast": 0.12,
                "participation_state": "LONG_BUILD" if index == 8 else "NEUTRAL",
                "roll_context": "ROLL_DOMINANT" if index == 8 else "NO_MAIN_REDUCTION",
                "trend_direction": "long" if index >= 8 else "neutral",
                "trend_stage": "SETUP" if index >= 8 else "NEUTRAL",
                "phase_v2": "S1" if index >= 8 else "S0",
            }
        )
        option_rows.append(
            {
                "trade_date": trade_date,
                "main_contract": "CF405",
                "underlying_contract": "CF409",
                "option_selection_reason": "NEXT_MAIN_CYCLE_RELAY",
                "option_relay_used": True,
                "option_tenor_gap_months": 4,
                "option_direction": "long" if index in {7, 8} else "neutral",
                "confirmation_state": (
                    "CONFIRM_LONG" if index in {7, 8} else "NEUTRAL_OR_OPTION_ONLY"
                ),
                "confirmation_strength": "medium" if index in {7, 8} else "low",
            }
        )
        for horizon in (1, 3, 5, 10, 20, 40):
            direction = "neutral"
            if index in {5, 6} or 25 <= index <= 32:
                direction = "short" if horizon in {1, 3, 5} else "long"
            elif index == 7:
                direction = "long" if horizon in {1, 3, 10, 20, 40} else "short"
            elif 8 <= index <= 24:
                direction = "long"
            matrix_rows.append(
                {
                    "trade_date": trade_date,
                    "main_contract": "CF405",
                    "horizon": horizon,
                    "direction": direction,
                }
            )

    paths = {
        "matrix": tmp_path / "matrix.parquet",
        "trend": tmp_path / "trend.parquet",
        "option": tmp_path / "option.parquet",
    }
    pd.DataFrame(matrix_rows).to_parquet(paths["matrix"], index=False)
    pd.DataFrame(trend_rows).to_parquet(paths["trend"], index=False)
    pd.DataFrame(option_rows).to_parquet(paths["option"], index=False)
    return paths, dates
