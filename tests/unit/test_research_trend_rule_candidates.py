from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_trend_rule_candidates


def test_build_cf_trend_rule_candidates_filters_ready_and_insufficient_rules(
    tmp_path: Path,
) -> None:
    summary_path, event_path = _write_r26_event_inputs(tmp_path)

    result = build_cf_trend_rule_candidates(
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        event_summary_path=summary_path,
        event_path=event_path,
        output_dir=tmp_path / "candidates",
        report_output_dir=tmp_path / "reports",
        run_id="r27_unit_candidates",
        min_event_count=3,
        min_observation_count=3,
        min_directional_hit_rate=0.60,
    )

    assert result.candidate_count == 7
    assert result.ready_candidate_count == 2
    assert result.watch_candidate_count == 1
    assert result.insufficient_candidate_count == 4
    assert result.candidate_parquet_path.exists()
    assert result.candidate_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.manifest_path.exists()

    candidates = pd.read_parquet(result.candidate_parquet_path)
    ready = candidates.loc[candidates["transition_code"].eq("S1_TO_S2")].iloc[0]
    assert ready["candidate_status"] == "READY_CANDIDATE"
    assert ready["daily_brief_action"] == "ALLOW_DAILY_EXPLANATION_CANDIDATE"
    assert ready["selected_horizon"] == 3
    assert ready["directional_hit_rate"] == pytest.approx(2 / 3)

    s0_to_s3 = candidates.loc[candidates["transition_code"].eq("S0_TO_S3")].iloc[0]
    assert s0_to_s3["event_type"] == "未确认转衰竭观察"
    assert s0_to_s3["candidate_status"] == "READY_CANDIDATE"
    assert s0_to_s3["daily_brief_action"] == "ALLOW_DAILY_EXPLANATION_CANDIDATE"

    s3_to_s0 = candidates.loc[candidates["transition_code"].eq("S3_TO_S0")].iloc[0]
    assert s3_to_s0["event_type"] == "衰竭观察降级未确认"
    assert s3_to_s0["candidate_status"] == "WATCH_CANDIDATE"
    assert s3_to_s0["daily_brief_action"] == "WATCH_ONLY"

    no_sample = candidates.loc[candidates["transition_code"].eq("S3_TO_S4")].iloc[0]
    assert no_sample["candidate_status"] == "NO_SAMPLE"
    assert no_sample["daily_brief_action"] == "ACCUMULATE_SAMPLE"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "R27 只输出日报解释候选" in markdown
    assert "S3->S4 若无样本，不允许进入正式日报判断规则" in markdown
    assert "本报告不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["candidate_rules_only"] is True
    assert manifest["not_trading_instruction"] is True


def test_build_cf_trend_rule_candidates_validates_thresholds(tmp_path: Path) -> None:
    summary_path, _ = _write_r26_event_inputs(tmp_path)

    with pytest.raises(ResearchWorkbenchError, match="min_event_count must be positive"):
        build_cf_trend_rule_candidates(
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            event_summary_path=summary_path,
            output_dir=tmp_path / "candidates",
            report_output_dir=tmp_path / "reports",
            min_event_count=0,
        )


def _write_r26_event_inputs(tmp_path: Path) -> tuple[Path, Path]:
    summary_path = tmp_path / "events" / "summary.parquet"
    event_path = tmp_path / "events" / "events.parquet"
    summary_path.parent.mkdir(parents=True)
    summary_rows = [
        _summary("S0_TO_S3", "未确认转衰竭观察", "long", 3, 3, 3, 0.02, 2 / 3),
        _summary("S1_TO_S2", "趋势起点确认", "long", 1, 3, 3, -0.01, 0.0),
        _summary("S1_TO_S2", "趋势起点确认", "long", 3, 3, 3, 0.01, 2 / 3),
        _summary("S2_TO_S3", "衰竭观察出现", "long", 3, 1, 1, 0.02, 1.0),
        _summary("S3_TO_S0", "衰竭观察降级未确认", "neutral", 3, 3, 3, 0.0, None),
        _summary("S4_TO_S0", "终点后重置观察", "neutral", 1, 1, 1, 0.0, None),
    ]
    event_rows = [
        {"transition_code": "S0_TO_S3", "event_date": "2024-01-08"},
        {"transition_code": "S1_TO_S2", "event_date": "2024-01-10"},
        {"transition_code": "S1_TO_S2", "event_date": "2024-01-15"},
        {"transition_code": "S2_TO_S3", "event_date": "2024-01-20"},
        {"transition_code": "S3_TO_S0", "event_date": "2024-01-25"},
    ]
    pd.DataFrame(summary_rows).to_parquet(summary_path, index=False)
    pd.DataFrame(event_rows).to_parquet(event_path, index=False)
    return summary_path, event_path


def _summary(
    transition_code: str,
    event_type: str,
    direction: str,
    horizon: int,
    event_count: int,
    observation_count: int,
    mean_return: float,
    hit_rate: float | None,
) -> dict[str, object]:
    return {
        "transition_code": transition_code,
        "event_type": event_type,
        "new_phase_direction": direction,
        "horizon": horizon,
        "event_count": event_count,
        "observation_count": observation_count,
        "mean_forward_return": mean_return,
        "median_forward_return": mean_return,
        "positive_rate": None if hit_rate is None else hit_rate,
        "negative_rate": None if hit_rate is None else 1 - hit_rate,
        "directional_hit_rate": hit_rate,
        "event_rule_version": "R26_trend_phase_transition_events_v1",
    }
