from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.futures_option_regime_interaction import (
    build_cf_futures_option_regime_interaction_research,
)


def test_regime_interaction_deduplicates_episode_and_separates_context(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)

    result = build_cf_futures_option_regime_interaction_research(
        event_path=paths["event"],
        checkpoint_path=paths["checkpoint"],
        path_path=paths["path"],
        feature_path=paths["feature"],
        policy_context_path=paths["policy"],
        fundamental_context_path=paths["fundamental"],
        min_sample_size=100,
        min_cell_size=1,
        permutation_count=20,
        output_dir=tmp_path / "data" / "r93q",
        report_output_dir=tmp_path / "reports" / "r93q",
        run_id="r93q_fixture",
    )

    assert result.source_event_count == 19
    assert result.episode_count == 18
    assert result.episode_validation_count == 54
    assert result.primary_interaction_count > 0
    assert result.exploratory_interaction_count > 0
    assert result.markdown_path.exists()
    assert result.manifest_path.exists()

    episodes = pd.read_parquet(result.episode_feature_parquet_path)
    assert not POSTERIOR_COLUMNS.intersection(episodes.columns)
    assert set(episodes["market_stage"]) == {
        "EARLY_THIN",
        "EXPANSION",
        "MATURE_ACTIVE",
    }
    assert {"JAN_CYCLE", "MAY_CYCLE", "SEP_CYCLE"} <= set(
        episodes["contract_cycle"]
    )
    duplicate = episodes.loc[episodes["episode_member_event_count"].eq(2)]
    assert len(duplicate) == 1
    assert duplicate.iloc[0]["chain_path_label"] in {
        "SINGLE_EVENT_TYPE",
        "MIXED_OR_PARTIAL_CHAIN",
    }

    validation = pd.read_parquet(result.episode_validation_parquet_path)
    assert validation["forward_returns_are_historical_posterior_labels"].all()
    assert validation["t_plus_one_execution"].all()
    assert set(validation["horizon"].astype(int)) == {1, 3, 5}

    context = pd.read_parquet(result.named_context_parquet_path)
    assert not context.empty
    assert not context["used_in_direction_test"].any()
    primary = pd.read_parquet(result.primary_interaction_parquet_path)
    assert "context_name" not in primary.columns
    assert set(primary["interaction_dimension"]) == {
        "contract_cycle",
        "expiry_bucket",
        "roll_context",
        "cotton_year",
        "trend_phase",
    }
    exploratory = pd.read_parquet(result.exploratory_interaction_parquet_path)
    assert not exploratory["evidence_status"].str.startswith("READY_").any()

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "只有首次事件作为统计锚点" in markdown
    assert "基本面和政策只进入具名上下文表" in markdown
    assert "forward return只用于历史后验验证" in markdown
    assert "不构成交易指令" in markdown


def test_regime_interaction_rejects_non_t_plus_one_checkpoint(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    checkpoint = pd.read_parquet(paths["checkpoint"])
    checkpoint.loc[0, "label_execution_date"] = checkpoint.loc[0, "event_date"]
    invalid = tmp_path / "invalid_checkpoint.parquet"
    checkpoint.to_parquet(invalid, index=False)

    with pytest.raises(ResearchWorkbenchError, match=r"T\+1执行约束"):
        build_cf_futures_option_regime_interaction_research(
            event_path=paths["event"],
            checkpoint_path=invalid,
            path_path=paths["path"],
            feature_path=paths["feature"],
            min_sample_size=1,
            min_cell_size=1,
            permutation_count=10,
            output_dir=tmp_path / "data" / "invalid",
            report_output_dir=tmp_path / "reports" / "invalid",
            run_id="r93q_invalid",
        )


def test_regime_interaction_cli_writes_bundle(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    runner = CliRunner()
    invocation = runner.invoke(
        app,
        [
            "research",
            "build-cf-futures-option-regime-interaction-research",
            "--event-path",
            str(paths["event"]),
            "--checkpoint-path",
            str(paths["checkpoint"]),
            "--path-path",
            str(paths["path"]),
            "--feature-path",
            str(paths["feature"]),
            "--policy-context-path",
            str(paths["policy"]),
            "--fundamental-context-path",
            str(paths["fundamental"]),
            "--min-sample-size",
            "100",
            "--min-cell-size",
            "1",
            "--permutation-count",
            "10",
            "--output-dir",
            str(tmp_path / "data" / "cli"),
            "--report-output-dir",
            str(tmp_path / "reports" / "cli"),
            "--run-id",
            "r93q_cli",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads(invocation.stdout)
    assert payload["run_id"] == "r93q_cli"
    assert payload["promotion_eligible"] is False
    assert payload["fundamental_and_policy_are_named_context_only"] is True
    assert Path(payload["episode_feature_parquet_path"]).exists()
    assert Path(payload["markdown_path"]).exists()


POSTERIOR_COLUMNS = {
    "forward_return",
    "directional_return",
    "event_outcome",
    "event_hit",
    "event_mfe",
    "event_mae",
    "execution_date",
    "exit_date",
}


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    events: list[dict[str, object]] = []
    checkpoints: list[dict[str, object]] = []
    paths: list[dict[str, object]] = []
    features: list[dict[str, object]] = []
    policy: list[dict[str, object]] = []
    fundamental: list[dict[str, object]] = []
    contracts_by_cycle = {1: "01", 5: "05", 9: "09"}
    event_index = 0
    for year in range(2021, 2027):
        stage = (
            "EARLY_THIN"
            if year == 2021
            else "EXPANSION"
            if year <= 2023
            else "MATURE_ACTIVE"
        )
        for local_index in range(3):
            event_date = date(year, 1, 4) + timedelta(days=local_index)
            cycle = (1, 5, 9)[local_index % 3]
            contract = f"CF{str(year)[-1]}{contracts_by_cycle[cycle]}"
            event_type = "CALL_BREAKOUT"
            observation_id = f"obs_{event_index}"
            event_id = f"{observation_id}_{event_type}"
            event = _event_row(
                event_id=event_id,
                observation_id=observation_id,
                event_date=event_date,
                contract=contract,
                event_type=event_type,
                stage=stage,
                local_index=local_index,
            )
            events.append(event)
            feature = _feature_row(
                observation_id=observation_id,
                event_date=event_date,
                contract=contract,
                local_index=local_index,
            )
            features.append(feature)
            paths.append(_path_row(event_id))
            checkpoints.extend(_checkpoint_rows(event, event_index))
            policy.append(_policy_row(event_date))
            fundamental.append(_fundamental_row(event_date, event_index))
            event_index += 1

    # 同合约、同方向、同类型且相邻会话的重复事件必须压成同一episode。
    duplicate_source = events[0].copy()
    duplicate_source["event_id"] = "obs_duplicate_CALL_BREAKOUT"
    duplicate_source["observation_id"] = "obs_duplicate"
    duplicate_source["event_date"] = date(2021, 1, 5)
    events.append(duplicate_source)
    duplicate_feature = features[0].copy()
    duplicate_feature["observation_id"] = "obs_duplicate"
    duplicate_feature["trade_date"] = date(2021, 1, 5)
    features.append(duplicate_feature)
    paths.append(_path_row(str(duplicate_source["event_id"])))
    checkpoints.extend(_checkpoint_rows(duplicate_source, event_index))

    output = {
        "event": tmp_path / "event.parquet",
        "checkpoint": tmp_path / "checkpoint.parquet",
        "path": tmp_path / "path.parquet",
        "feature": tmp_path / "feature.parquet",
        "policy": tmp_path / "policy.parquet",
        "fundamental": tmp_path / "fundamental.parquet",
    }
    pd.DataFrame(events).to_parquet(output["event"], index=False)
    pd.DataFrame(checkpoints).to_parquet(output["checkpoint"], index=False)
    pd.DataFrame(paths).to_parquet(output["path"], index=False)
    pd.DataFrame(features).drop_duplicates("observation_id").to_parquet(
        output["feature"], index=False
    )
    pd.DataFrame(policy).drop_duplicates("trade_date").to_parquet(
        output["policy"], index=False
    )
    pd.DataFrame(fundamental).to_parquet(output["fundamental"], index=False)
    return output


def _event_row(
    *,
    event_id: str,
    observation_id: str,
    event_date: date,
    contract: str,
    event_type: str,
    stage: str,
    local_index: int,
) -> dict[str, object]:
    return {
        "run_id": "r93n_fixture",
        "event_id": event_id,
        "observation_id": observation_id,
        "event_date": event_date,
        "main_contract": contract,
        "event_type": event_type,
        "event_direction": "long",
        "option_market_stage": stage,
        "data_activity_state": stage,
        "trend_phase": "S2" if local_index % 2 == 0 else "S0",
        "expiry_bucket": "DTE_GT_30" if local_index % 2 == 0 else "DTE_16_30",
        "dynamic_pressure_node": "DYNAMIC_LONG_PRESSURE",
        "joint_futures_option_node": "FUTURES_LONG_OPTION_LONG_CONFIRM",
        "futures_direction_5d": "long",
        "option_pressure_direction": "long",
        "static_key_level_state": "BETWEEN_OI_WALLS",
        "event_trigger_observable_at_t": True,
        "contains_posterior_outcome": False,
        "trading_instruction": "not_a_trading_instruction",
    }


def _feature_row(
    *, observation_id: str, event_date: date, contract: str, local_index: int
) -> dict[str, object]:
    return {
        "run_id": "r93n_fixture",
        "observation_id": observation_id,
        "trade_date": event_date,
        "main_contract": contract,
        "roll_context": (
            "NO_MAIN_REDUCTION" if local_index % 2 == 0 else "ROLL_DOMINANT"
        ),
        "phase_v2": "S2" if local_index % 2 == 0 else "S0",
        "expiry_bucket": "DTE_GT_30" if local_index % 2 == 0 else "DTE_16_30",
        "feature_uses_t_or_earlier": True,
        "contains_posterior_outcome": False,
    }


def _checkpoint_rows(event: dict[str, object], index: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    event_date = event["event_date"]
    assert isinstance(event_date, date)
    for horizon in (1, 3, 5):
        continuation = (index + horizon) % 3 != 0
        directional_return = 0.01 if continuation else -0.01
        rows.append(
            {
                "run_id": "r93p_fixture",
                "event_id": event["event_id"],
                "event_date": event_date,
                "event_type": event["event_type"],
                "event_direction": event["event_direction"],
                "horizon": horizon,
                "label_execution_date": event_date + timedelta(days=1),
                "label_exit_date": event_date + timedelta(days=horizon + 1),
                "label_forward_return": directional_return,
                "label_event_directional_return": directional_return,
                "label_event_outcome": (
                    "FOLLOW_THROUGH" if continuation else "FAILED"
                ),
                "label_event_hit": continuation,
                "label_event_mfe": 0.02,
                "label_event_mae": -0.01,
                "label_forward_label_available": True,
                "checkpoint_outcome": (
                    "CONTINUATION" if continuation else "REVERSAL"
                ),
            }
        )
    return rows


def _path_row(event_id: str) -> dict[str, object]:
    return {
        "run_id": "r93p_fixture",
        "event_id": event_id,
        "first_resolution_horizon": 1,
        "first_resolution_outcome": "CONTINUATION",
        "path_label": "CONTINUATION_STABLE",
        "path_available_checkpoints": 3,
    }


def _policy_row(event_date: date) -> dict[str, object]:
    cotton_year = (
        f"{event_date.year - 1}/{str(event_date.year)[-2:]}"
        if event_date.month < 9
        else f"{event_date.year}/{str(event_date.year + 1)[-2:]}"
    )
    return {
        "trade_date": event_date,
        "cotton_year": cotton_year,
        "futures_reference_bucket": "BELOW_REFERENCE",
        "spot_reference_bucket": "BELOW_REFERENCE",
        "relative_configuration": "BOTH_BELOW_REFERENCE",
        "contains_forward_label": False,
    }


def _fundamental_row(event_date: date, index: int) -> dict[str, object]:
    return {
        "market_trade_date": event_date,
        "dataset_type": "inventory",
        "indicator_name": "仓单数量",
        "metric_name": "warehouse_receipt",
        "indicator_value": float(index),
        "unit": "lot",
        "source_name": "fixture",
        "context_label_4": "UP",
        "fundamental_signal_status": "not_connected",
    }
