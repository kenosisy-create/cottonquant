from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.futures_option_event_path import (
    build_cf_futures_option_event_path_research,
)


def test_event_path_builds_fixed_checkpoints_and_separates_neutral_events(
    tmp_path: Path,
) -> None:
    event_path, label_path, feature_path = _write_fixture(tmp_path)

    result = build_cf_futures_option_event_path_research(
        event_path=event_path,
        event_lifecycle_label_path=label_path,
        feature_path=feature_path,
        output_dir=tmp_path / "data" / "event_path",
        report_output_dir=tmp_path / "reports" / "event_path",
        run_id="r93p_fixture",
        min_sample_size=1,
    )

    assert result.event_row_count == 7
    assert result.checkpoint_row_count == 21
    assert result.path_row_count == 7
    assert result.warning_count >= 1
    assert result.markdown_path.exists()
    assert result.manifest_path.exists()

    path = pd.read_parquet(result.path_parquet_path)
    long_path = path.loc[path["event_id"].eq("obs_0_CALL_BREAKOUT")].iloc[0]
    assert long_path["t_plus_1_outcome"] == "CONTINUATION"
    assert long_path["t_plus_3_outcome"] == "CONTINUATION"
    assert long_path["path_label"] == "CONTINUATION_STABLE"
    assert long_path["t_plus_1_state_trend_phase"] == "S2"
    assert bool(long_path["t_plus_1_state_contract_match"]) is True

    neutral = path.loc[path["event_id"].eq("obs_5_WALL_RANGE_NARROWING")].iloc[0]
    assert neutral["path_label"] == "NO_DIRECTION_OR_UNAVAILABLE"

    summary = pd.read_parquet(result.event_summary_parquet_path)
    assert set(summary["horizon"].astype(int)) == {1, 3, 5}
    assert summary["forward_returns_are_historical_posterior_labels"].all()
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "固定检查点" in markdown
    assert "forward return只用于历史后验验证" in markdown
    assert "不构成交易指令" in markdown


def test_event_path_rejects_posterior_in_t_day_event_table(tmp_path: Path) -> None:
    event_path, label_path, feature_path = _write_fixture(tmp_path)
    events = pd.read_parquet(event_path)
    events["forward_return"] = 0.01
    invalid_event_path = tmp_path / "invalid_event.parquet"
    events.to_parquet(invalid_event_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="混入后验字段"):
        build_cf_futures_option_event_path_research(
            event_path=invalid_event_path,
            event_lifecycle_label_path=label_path,
            feature_path=feature_path,
            output_dir=tmp_path / "data" / "invalid",
            report_output_dir=tmp_path / "reports" / "invalid",
            run_id="r93p_invalid",
            min_sample_size=1,
        )


def test_event_path_cli_writes_json_bundle(tmp_path: Path) -> None:
    event_path, label_path, feature_path = _write_fixture(tmp_path)
    runner = CliRunner()
    invocation = runner.invoke(
        app,
        [
            "research",
            "build-cf-futures-option-event-path-research",
            "--event-path",
            str(event_path),
            "--event-lifecycle-label-path",
            str(label_path),
            "--feature-path",
            str(feature_path),
            "--output-dir",
            str(tmp_path / "data" / "cli"),
            "--report-output-dir",
            str(tmp_path / "reports" / "cli"),
            "--run-id",
            "r93p_cli",
            "--min-sample-size",
            "1",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads(invocation.stdout)
    assert payload["run_id"] == "r93p_cli"
    assert payload["promotion_eligible"] is False
    assert Path(payload["path_parquet_path"]).exists()
    assert Path(payload["markdown_path"]).exists()


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    dates = pd.date_range("2024-01-02", periods=8, freq="B").date
    events: list[dict[str, object]] = []
    labels: list[dict[str, object]] = []
    features: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates[:6]):
        event_type = "CALL_BREAKOUT" if index % 2 == 0 else "PUT_BREAKOUT"
        direction = "long" if event_type.startswith("CALL") else "short"
        event_id = f"obs_{index}_{event_type}"
        events.append(
            {
                "run_id": "r93n_fixture",
                "event_id": event_id,
                "observation_id": f"obs_{index}",
                "event_date": trade_date,
                "main_contract": "CF501",
                "event_type": event_type,
                "event_direction": direction,
                "option_market_stage": "MATURE_ACTIVE",
                "data_activity_state": "MATURE_ACTIVE",
                "trend_phase": "S2",
                "expiry_bucket": "DTE_15_30",
                "dynamic_pressure_node": "DYNAMIC_LONG_PRESSURE",
                "joint_futures_option_node": "FUTURES_LONG_OPTION_LONG_CONFIRM",
                "futures_direction_5d": direction,
                "option_pressure_direction": direction,
                "static_key_level_state": "BETWEEN_OI_WALLS",
                "event_trigger_observable_at_t": True,
                "contains_posterior_outcome": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
        for horizon in (1, 3, 5):
            available = index < 3 or horizon <= 3
            outcome = "FOLLOW_THROUGH" if direction == "long" else "FAILED"
            signed_return = 0.02 if direction == "long" else -0.02
            if index == 1 and horizon == 3:
                outcome = "FAILED"
                signed_return = -0.02
            labels.append(
                {
                    "run_id": "r93n_fixture",
                    "event_id": event_id,
                    "observation_id": f"obs_{index}",
                    "event_date": trade_date,
                    "main_contract": "CF501",
                    "event_type": event_type,
                    "event_direction": direction,
                    "option_market_stage": "MATURE_ACTIVE",
                    "data_activity_state": "MATURE_ACTIVE",
                    "trend_phase": "S2",
                    "expiry_bucket": "DTE_15_30",
                    "dynamic_pressure_node": "DYNAMIC_LONG_PRESSURE",
                    "joint_futures_option_node": "FUTURES_LONG_OPTION_LONG_CONFIRM",
                    "horizon": horizon,
                    "execution_date": trade_date + timedelta(days=1) if available else None,
                    "exit_date": trade_date + timedelta(days=horizon + 1) if available else None,
                    "forward_return": signed_return if available else None,
                    "event_directional_return": signed_return if available else None,
                    "event_outcome": outcome if available else "LABEL_UNAVAILABLE",
                    "event_hit": bool(signed_return > 0) if available else None,
                    "event_mfe": 0.03 if available else None,
                    "event_mae": -0.01 if available else None,
                    "tbm_outcome": "UPPER_BARRIER" if available else "LABEL_UNAVAILABLE",
                    "tbm_first_hit_session": 1 if available else None,
                    "wall_retest_flag": False if available else None,
                    "wall_failure_flag": outcome == "FAILED" if available else None,
                    "path_event_label": (
                        "BREAKOUT_FOLLOW_THROUGH" if available else "LABEL_UNAVAILABLE"
                    ),
                    "forward_label_available": available,
                    "forward_returns_are_historical_posterior_labels": True,
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
        features.append(
            {
                "run_id": "r93n_fixture",
                "observation_id": f"obs_{index}",
                "trade_date": trade_date,
                "main_contract": "CF501",
                "feature_uses_t_or_earlier": True,
                "contains_posterior_outcome": False,
                "trend_phase": "S2",
                "phase_v2": "S2",
                "dynamic_pressure_node": "DYNAMIC_LONG_PRESSURE",
                "option_pressure_direction": direction,
                "primary_event_type": event_type,
            }
        )
    # 中性事件用于验证不会强行产生方向性路径。
    events.append(
        {
            "run_id": "r93n_fixture",
            "event_id": "obs_5_WALL_RANGE_NARROWING",
            "observation_id": "obs_5",
            "event_date": dates[5],
            "main_contract": "CF501",
            "event_type": "WALL_RANGE_NARROWING",
            "event_direction": "neutral",
            "option_market_stage": "MATURE_ACTIVE",
            "data_activity_state": "MATURE_ACTIVE",
            "trend_phase": "S0",
            "expiry_bucket": "DTE_15_30",
            "dynamic_pressure_node": "DYNAMIC_MIXED_PRESSURE",
            "joint_futures_option_node": "BOTH_NEUTRAL",
            "futures_direction_5d": "neutral",
            "option_pressure_direction": "neutral",
            "static_key_level_state": "BETWEEN_OI_WALLS",
            "event_trigger_observable_at_t": True,
            "contains_posterior_outcome": False,
            "trading_instruction": "not_a_trading_instruction",
        }
    )
    for horizon in (1, 3, 5):
        labels.append(
            {
                "run_id": "r93n_fixture",
                "event_id": "obs_5_WALL_RANGE_NARROWING",
                "observation_id": "obs_5",
                "event_date": dates[5],
                "main_contract": "CF501",
                "event_type": "WALL_RANGE_NARROWING",
                "event_direction": "neutral",
                "horizon": horizon,
                "execution_date": dates[6],
                "exit_date": dates[7],
                "forward_return": 0.0,
                "event_directional_return": None,
                "event_outcome": "UNRESOLVED",
                "event_hit": False,
                "event_mfe": 0.01,
                "event_mae": -0.01,
                "tbm_outcome": "TIME_BARRIER",
                "tbm_first_hit_session": None,
                "wall_retest_flag": False,
                "wall_failure_flag": False,
                "path_event_label": "UNRESOLVED",
                "forward_label_available": True,
                "forward_returns_are_historical_posterior_labels": True,
            }
        )
    event_file = tmp_path / "events.parquet"
    label_file = tmp_path / "labels.parquet"
    feature_file = tmp_path / "features.parquet"
    pd.DataFrame(events).to_parquet(event_file, index=False)
    pd.DataFrame(labels).to_parquet(label_file, index=False)
    pd.DataFrame(features).to_parquet(feature_file, index=False)
    return event_file, label_file, feature_file
