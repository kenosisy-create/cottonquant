from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import (
    build_cf_state_transition_competing_risk_research,
)


def test_r79_builds_competing_risk_and_duration_outputs(tmp_path: Path) -> None:
    episode_path = _write_episode_fixture(tmp_path)
    result = build_cf_state_transition_competing_risk_research(
        event_lifecycle_episode_path=episode_path,
        output_dir=tmp_path / "data" / "state_transition",
        report_output_dir=tmp_path / "reports" / "state_transition",
        run_id="r79_unit",
        max_age_days=5,
        min_sample_size=2,
    )

    assert result.event_count == 7
    assert result.closed_event_count == 6
    assert result.censored_event_count == 1
    assert result.current_phase == "S1"
    assert result.current_age_days == 3
    assert result.event_parquet_path.exists()
    assert result.summary_parquet_path.exists()
    assert result.age_risk_parquet_path.exists()
    assert result.node_parquet_path.exists()
    assert result.current_parquet_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    summary = pd.read_parquet(result.summary_parquet_path)
    s1_success = summary.loc[
        (summary["phase_code"] == "S1")
        & (summary["outcome_code"] == "SUCCESS_TO_S2")
    ].iloc[0]
    assert s1_success["all_episode_count"] == 4
    assert s1_success["closed_episode_count"] == 3
    assert s1_success["outcome_count"] == 2
    assert s1_success["outcome_probability_closed"] == pytest.approx(2 / 3)
    assert s1_success["outcome_share_all"] == pytest.approx(0.5)

    age_risk = pd.read_parquet(result.age_risk_parquet_path)
    s1_failure_day_1 = age_risk.loc[
        (age_risk["phase_code"] == "S1")
        & (age_risk["age_day"] == 1)
        & (age_risk["outcome_code"] == "FAILURE_TO_S0")
    ].iloc[0]
    assert s1_failure_day_1["at_risk_count"] == 4
    assert s1_failure_day_1["event_count_at_age"] == 1
    assert s1_failure_day_1["cause_specific_hazard"] == pytest.approx(0.25)
    assert s1_failure_day_1["survival_probability_after_age"] == pytest.approx(0.75)

    current = pd.read_parquet(result.current_parquet_path).iloc[0]
    assert current["mapping_status"] == "MATCHED_OPEN_EPISODE"
    assert current["phase_code"] == "S1"
    assert current["research_boundary"] == "历史后验概率，不是最新交易指令"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "状态转移与竞争风险研究" in markdown
    assert "开放episode按右删失处理" in markdown
    assert "已解决条件概率" in markdown
    assert "不修改 `composite_score`" in markdown
    assert "不构成交易指令" in markdown


def test_r79_cli_writes_json_summary(tmp_path: Path) -> None:
    episode_path = _write_episode_fixture(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-state-transition-competing-risk",
            "--event-lifecycle-episode-path",
            str(episode_path),
            "--output-dir",
            str(tmp_path / "data"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r79_cli",
            "--max-age-days",
            "5",
            "--min-sample-size",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r79_cli"
    assert output["event_count"] == 7
    assert Path(output["markdown_path"]).exists()


def test_r79_rejects_missing_episode_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.parquet"
    pd.DataFrame([{"phase_code": "S1"}]).to_parquet(path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="missing columns"):
        build_cf_state_transition_competing_risk_research(
            event_lifecycle_episode_path=path,
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
        )


def test_r79_marks_current_non_target_phase_without_probability(tmp_path: Path) -> None:
    episode_path = _write_episode_fixture(tmp_path)
    frame = pd.read_parquet(episode_path)
    frame.loc[frame["episode_id"] == "ep7", "next_phase"] = "S0"
    frame.loc[frame["episode_id"] == "ep7", "transition_code"] = "S1_TO_S0"
    current_s0 = _episode(
        "ep8", "S0", "2024-01-30", 2, None, "low", 0.0, -0.01
    )
    pd.concat([frame, pd.DataFrame([current_s0])], ignore_index=True).to_parquet(
        episode_path, index=False
    )

    result = build_cf_state_transition_competing_risk_research(
        event_lifecycle_episode_path=episode_path,
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="r79_s0_current",
        max_age_days=5,
        min_sample_size=2,
    )

    assert result.current_phase == "S0"
    assert result.current_primary_outcome is None
    current = pd.read_parquet(result.current_parquet_path).iloc[0]
    assert current["mapping_status"] == "CURRENT_PHASE_OUTSIDE_TARGET"
    assert current["research_boundary"] == "当前不在S1/S3，暂不映射竞争风险概率"
    assert "当前不属于S1/S3竞争风险目标阶段" in result.markdown_path.read_text(
        encoding="utf-8"
    )


def _write_episode_fixture(tmp_path: Path) -> Path:
    rows = [
        _episode("ep1", "S1", "2024-01-02", 2, "S2", "high", 0.04, -0.01),
        _episode("ep2", "S1", "2024-01-05", 4, "S2", "high", 0.05, -0.02),
        _episode("ep3", "S1", "2024-01-11", 1, "S0", "low", 0.01, -0.03),
        _episode("ep4", "S3", "2024-01-15", 2, "S4", "medium", 0.02, -0.04),
        _episode("ep5", "S3", "2024-01-18", 3, "S2", "medium", 0.03, -0.01),
        _episode("ep6", "S3", "2024-01-23", 1, "S0", "low", 0.01, -0.02),
        _episode("ep7", "S1", "2024-01-25", 3, None, "high", 0.02, -0.01),
    ]
    path = tmp_path / "event_lifecycle_episodes.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _episode(
    episode_id: str,
    phase_code: str,
    start_date: str,
    duration: int,
    next_phase: str | None,
    confidence: str,
    mfe: float,
    mae: float,
) -> dict[str, object]:
    start = pd.Timestamp(start_date)
    end = start + pd.offsets.BDay(duration - 1)
    return {
        "run_id": "r68_fixture",
        "episode_id": episode_id,
        "phase_code": phase_code,
        "phase_direction": "long",
        "model_direction": "long",
        "confidence": confidence,
        "start_date": start.date(),
        "end_date": end.date(),
        "duration_trading_days": duration,
        "next_phase": next_phase,
        "transition_code": None if next_phase is None else f"{phase_code}_TO_{next_phase}",
        "mfe": mfe,
        "mae": mae,
    }
