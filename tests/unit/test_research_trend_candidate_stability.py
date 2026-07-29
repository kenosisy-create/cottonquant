from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.trend_candidate_stability import (
    build_cf_trend_candidate_stability_research,
)


def test_trend_candidate_stability_separates_forward_events(tmp_path: Path) -> None:
    event_path, spec_path = _write_fixture(tmp_path)
    first = build_cf_trend_candidate_stability_research(
        event_feature_path=event_path,
        spec_path=spec_path,
        output_dir=tmp_path / "data_first",
        report_output_dir=tmp_path / "reports_first",
        run_id="r93c_fixture_first",
    )
    first_primary = pd.read_parquet(first.primary_evaluation_path).sort_values(
        "hypothesis_id"
    )
    forward = pd.read_parquet(first.forward_capture_path)

    assert first.decisions[0] == (
        "H1_PARTICIPATION_CONFIRM_20D",
        "READY_FOR_FORWARD_PREREGISTRATION",
    )
    assert dict(first.decisions)["H2_WEAK_OPTION_CONTEXT_VETO_5D"] == (
        "FORWARD_WATCH_SMALL_SAMPLE"
    )
    assert first.forward_event_count == 36
    assert forward["event_date"].gt(date(2024, 12, 31)).all()
    assert forward["historical_result_is_oos"].all()
    assert first_primary["historical_result_is_oos"].eq(False).all()  # noqa: E712
    assert first_primary["selection_contaminated"].all()
    assert first_primary["strategy_change_allowed"].eq(False).all()  # noqa: E712

    # 前向结果即使被极端改写，也不能回流改变截止日前的历史判定。
    events = pd.read_parquet(event_path)
    future = pd.to_datetime(events["event_date"]).dt.year.eq(2025)
    events.loc[future, "directional_return"] = 0.50
    events.loc[future, "outcome"] = "FOLLOW_THROUGH"
    events.to_parquet(event_path, index=False)
    second = build_cf_trend_candidate_stability_research(
        event_feature_path=event_path,
        spec_path=spec_path,
        output_dir=tmp_path / "data_second",
        report_output_dir=tmp_path / "reports_second",
        run_id="r93c_fixture_second",
    )
    second_primary = pd.read_parquet(second.primary_evaluation_path).sort_values(
        "hypothesis_id"
    )
    stable_columns = [
        "hypothesis_id",
        "treated_count",
        "control_count",
        "delta_hit_rate",
        "delta_mean_directional_return",
        "decision_status",
    ]
    pd.testing.assert_frame_equal(
        first_primary[stable_columns].reset_index(drop=True),
        second_primary[stable_columns].reset_index(drop=True),
    )
    report = first.markdown_path.read_text(encoding="utf-8")
    assert "回顾性稳定性诊断，不属于样本外证据" in report
    assert "不构成交易指令" in report
    assert first.manifest_path.exists()


def test_trend_candidate_stability_cli_writes_bundle(tmp_path: Path) -> None:
    event_path, spec_path = _write_fixture(tmp_path)
    output_dir = tmp_path / "cli_data"
    report_dir = tmp_path / "cli_reports"
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-candidate-stability-research",
            "--event-feature-path",
            str(event_path),
            "--spec-path",
            str(spec_path),
            "--output-dir",
            str(output_dir),
            "--report-output-dir",
            str(report_dir),
            "--run-id",
            "r93c_cli_fixture",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"].startswith("TREND_CANDIDATE_STABILITY_READY")
    assert payload["hypothesis_count"] == 3
    assert payload["ready_for_forward_count"] == 1
    for key in (
        "primary_evaluation_path",
        "horizon_profile_path",
        "stability_slice_path",
        "leave_one_year_out_path",
        "forward_capture_path",
        "warning_csv_path",
        "json_path",
        "markdown_path",
        "manifest_path",
    ):
        assert Path(payload[key]).exists()


def test_trend_candidate_stability_rejects_duplicate_episode_horizon(
    tmp_path: Path,
) -> None:
    event_path, spec_path = _write_fixture(tmp_path)
    events = pd.read_parquet(event_path)
    events = pd.concat([events, events.iloc[[0]]], ignore_index=True)
    events.to_parquet(event_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="one first-breakout row"):
        build_cf_trend_candidate_stability_research(
            event_feature_path=event_path,
            spec_path=spec_path,
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
        )


def test_trend_candidate_stability_rejects_strategy_actions(tmp_path: Path) -> None:
    event_path, spec_path = _write_fixture(tmp_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    spec["strategy_actions_allowed"] = True
    spec_path.write_text(
        yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ResearchWorkbenchError, match="forbid strategy actions"):
        build_cf_trend_candidate_stability_research(
            event_feature_path=event_path,
            spec_path=spec_path,
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
        )


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    rows: list[dict[str, object]] = []
    episode_number = 0
    for event_year in (2021, 2022, 2023, 2024, 2025):
        for year_index in range(12):
            episode_number += 1
            event_date = date(event_year, 1 + year_index // 4, 1 + year_index % 4)
            direction = "long" if year_index % 2 == 0 else "short"
            participation = "CONFIRM" if year_index < 8 else "NEUTRAL_OR_EXIT"
            option_alignment = (
                "WEAK_OPTION_CONTEXT" if year_index < 2 else "CONFIRM"
            )
            wall_state = "WALL_OI_BUILDING" if year_index < 8 else "WALL_OI_UNWINDING"
            for horizon in (1, 3, 5, 10, 20):
                directional_return, outcome = _fixture_outcome(
                    horizon=horizon,
                    year_index=year_index,
                    participation=participation,
                    option_alignment=option_alignment,
                )
                rows.append(
                    {
                        "event_date": event_date,
                        "event_year": event_year,
                        "event_id": f"E{episode_number:03d}_{horizon}",
                        "direction": direction,
                        "direction_episode_id": f"EP{episode_number:03d}",
                        "horizon": horizon,
                        "directional_return": directional_return,
                        "outcome": outcome,
                        "historical_posterior_label": True,
                        "event_features_use_t_or_earlier": True,
                        "feature_asof_date": event_date,
                        "participation_alignment": participation,
                        "option_alignment": option_alignment,
                        "directional_wall_oi_state": wall_state,
                    }
                )
    event_path = tmp_path / "event_feature.parquet"
    spec_path = tmp_path / "r93c_spec.yaml"
    pd.DataFrame(rows).to_parquet(event_path, index=False)
    spec_path.write_text(
        yaml.safe_dump(_fixture_spec(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return event_path, spec_path


def _fixture_outcome(
    *,
    horizon: int,
    year_index: int,
    participation: str,
    option_alignment: str,
) -> tuple[float, str]:
    if horizon == 20:
        value = 0.02 if participation == "CONFIRM" else -0.01
    elif horizon == 5:
        value = -0.02 if option_alignment == "WEAK_OPTION_CONTEXT" else 0.01
    elif horizon == 3:
        value = 0.005 if year_index % 2 == 0 else -0.005
    else:
        value = 0.002 if year_index % 2 == 0 else -0.002
    return value, "FOLLOW_THROUGH" if value > 0 else "FAILED_BREAKOUT"


def _fixture_spec() -> dict[str, object]:
    return {
        "spec_version": "R93C_TEST_V1",
        "product_code": "CF",
        "status": "frozen_for_forward_research",
        "registered_at": "2025-01-01",
        "effective_after_date": "2024-12-31",
        "selection_disclosure": "回顾性稳定性诊断，不属于样本外证据",
        "strategy_actions_allowed": False,
        "evaluation_gate": {
            "minimum_historical_treated": 20,
            "minimum_historical_control": 8,
            "minimum_direction_each": 3,
            "minimum_year_each": 2,
            "minimum_evaluable_years": 3,
            "minimum_year_alignment_rate": 0.60,
            "practical_hit_delta": 0.05,
            "practical_return_delta": 0.001,
            "era_split_year": 2022,
            "bootstrap_samples": 500,
            "bootstrap_confidence": 0.95,
            "bootstrap_seed": 9303,
        },
        "hypotheses": [
            {
                "hypothesis_id": "H1_PARTICIPATION_CONFIRM_20D",
                "feature_column": "participation_alignment",
                "feature_value": "CONFIRM",
                "primary_horizon": 20,
                "desired_effect": "positive",
                "forward_role": "confirmation",
                "rationale": "fixture",
            },
            {
                "hypothesis_id": "H2_WEAK_OPTION_CONTEXT_VETO_5D",
                "feature_column": "option_alignment",
                "feature_value": "WEAK_OPTION_CONTEXT",
                "primary_horizon": 5,
                "desired_effect": "negative",
                "forward_role": "veto",
                "rationale": "fixture",
            },
            {
                "hypothesis_id": "H3_DIRECTIONAL_WALL_OI_BUILD_3D",
                "feature_column": "directional_wall_oi_state",
                "feature_value": "WALL_OI_BUILDING",
                "primary_horizon": 3,
                "desired_effect": "positive",
                "forward_role": "wall",
                "rationale": "fixture",
            },
        ],
        "diagnostic_horizons": [1, 3, 5, 10, 20],
        "forbidden_actions": ["modify_strategy"],
    }
