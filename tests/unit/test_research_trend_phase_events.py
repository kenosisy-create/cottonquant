from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_trend_phase_events


def test_build_cf_trend_phase_events_writes_events_summary_and_report(
    tmp_path: Path,
) -> None:
    daily_path = _write_trend_phase_daily_rows(tmp_path)

    result = build_cf_trend_phase_events(
        start=date(2024, 1, 1),
        end=date(2024, 1, 9),
        horizons=(1,),
        trend_phase_daily_path=daily_path,
        output_dir=tmp_path / "events",
        report_output_dir=tmp_path / "reports",
        run_id="r26_unit_events",
    )

    assert result.event_count == 5
    assert result.key_event_count == 5
    assert result.summary_row_count == 5
    assert result.warning_count == 0
    assert result.event_parquet_path.exists()
    assert result.event_csv_path.exists()
    assert result.summary_parquet_path.exists()
    assert result.summary_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.manifest_path.exists()

    events = pd.read_parquet(result.event_parquet_path)
    assert events["transition_code"].to_list() == [
        "S0_TO_S1",
        "S1_TO_S2",
        "S2_TO_S3",
        "S3_TO_S4",
        "S4_TO_S0",
    ]
    s1_to_s2 = events.loc[events["transition_code"].eq("S1_TO_S2")].iloc[0]
    assert s1_to_s2["event_type"] == "趋势起点确认"
    assert s1_to_s2["event_direction_hit_h1"] is True
    s3_to_s4 = events.loc[events["transition_code"].eq("S3_TO_S4")].iloc[0]
    assert s3_to_s4["event_type"] == "趋势终点确认"
    assert s3_to_s4["event_direction_hit_h1"] is True

    summary = pd.read_parquet(result.summary_parquet_path)
    s2_summary = summary.loc[summary["transition_code"].eq("S1_TO_S2")].iloc[0]
    assert s2_summary["directional_hit_rate"] == pytest.approx(1.0)
    assert s2_summary["mean_forward_return"] == pytest.approx(0.03)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "阶段切换事件只来自 R25 逐日阶段表" in markdown
    assert "forward_return_* 是事件后的后验验证标签" in markdown
    assert "本报告不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["event_no_lookahead"] is True
    assert manifest["forward_returns_are_validation_labels"] is True


def test_build_cf_trend_phase_events_marks_r30_s0_s3_switches_as_key(
    tmp_path: Path,
) -> None:
    daily_path = _write_r30_transition_daily_rows(tmp_path)

    result = build_cf_trend_phase_events(
        start=date(2024, 2, 1),
        end=date(2024, 2, 5),
        horizons=(1,),
        trend_phase_daily_path=daily_path,
        output_dir=tmp_path / "events",
        report_output_dir=tmp_path / "reports",
        run_id="r30_unit_events",
    )

    assert result.event_count == 2
    assert result.key_event_count == 2

    events = pd.read_parquet(result.event_parquet_path)
    s0_to_s3 = events.loc[events["transition_code"].eq("S0_TO_S3")].iloc[0]
    assert s0_to_s3["event_type"] == "未确认转衰竭观察"
    assert bool(s0_to_s3["is_key_transition"]) is True
    assert "震荡修复" in s0_to_s3["event_reason"]
    s3_to_s0 = events.loc[events["transition_code"].eq("S3_TO_S0")].iloc[0]
    assert s3_to_s0["event_type"] == "衰竭观察降级未确认"
    assert bool(s3_to_s0["is_key_transition"]) is True
    assert "趋势解释失效" in s3_to_s0["event_reason"]


def test_build_cf_trend_phase_events_requires_existing_daily_path(tmp_path: Path) -> None:
    with pytest.raises(ResearchWorkbenchError, match="trend phase daily parquet not found"):
        build_cf_trend_phase_events(
            start=date(2024, 1, 1),
            end=date(2024, 1, 9),
            horizons=(1,),
            trend_phase_daily_path=tmp_path / "missing.parquet",
            output_dir=tmp_path / "events",
            report_output_dir=tmp_path / "reports",
        )


def _write_trend_phase_daily_rows(tmp_path: Path) -> Path:
    path = tmp_path / "trend_phase" / "daily.parquet"
    path.parent.mkdir(parents=True)
    rows = [
        _daily("2024-01-01", "S0", "未确认", "neutral", 0, 0.01),
        _daily("2024-01-02", "S1", "起点观察", "long", 1, 0.02),
        _daily("2024-01-03", "S2", "趋势中", "long", 3, 0.03),
        _daily("2024-01-04", "S2", "趋势中", "long", 3, 0.01),
        _daily("2024-01-05", "S3", "衰竭观察", "long", 2, -0.01),
        _daily("2024-01-08", "S4", "终点确认", "short", -3, -0.02),
        _daily("2024-01-09", "S0", "未确认", "neutral", 0, 0.0),
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_r30_transition_daily_rows(tmp_path: Path) -> Path:
    path = tmp_path / "trend_phase_r30" / "daily.parquet"
    path.parent.mkdir(parents=True)
    rows = [
        _daily("2024-02-01", "S0", "未确认", "neutral", 0, 0.01),
        _daily("2024-02-02", "S3", "衰竭观察", "long", 2, -0.01),
        _daily("2024-02-05", "S0", "未确认", "neutral", 0, 0.0),
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _daily(
    trade_date: str,
    phase_code: str,
    phase_label: str,
    direction: str,
    score: int,
    forward_return: float,
) -> dict[str, object]:
    return {
        "run_id": "r25_fixture",
        "product_code": "CF",
        "trade_date": trade_date,
        "main_contract": "CF405",
        "trend_phase_code": phase_code,
        "trend_phase_label": phase_label,
        "trend_phase_direction": direction,
        "multi_factor_direction": direction,
        "multi_factor_score": score,
        "main_settle": 100 + score,
        "return_20d": 0.02 * score,
        "main_oi_pressure": 0.01 * score,
        "curve_slope": 0.001 * score,
        "carry_annualized": 0.01 * score,
        "forward_return_h1": forward_return,
        "forward_label_available_h1": True,
        "execution_date_h1": trade_date,
        "exit_date_h1": trade_date,
        "validation_rule_version": "R25_trend_phase_validation_v1",
    }
