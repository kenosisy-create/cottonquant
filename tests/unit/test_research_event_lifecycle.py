from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_event_lifecycle_research


def test_build_cf_event_lifecycle_research_writes_episode_and_tbm_labels(
    tmp_path: Path,
) -> None:
    matrix_path = _write_signal_matrix_fixture(tmp_path)

    result = build_cf_event_lifecycle_research(
        signal_matrix_path=matrix_path,
        output_dir=tmp_path / "research" / "event_lifecycle",
        report_output_dir=tmp_path / "reports" / "event_lifecycle",
        run_id="r68_unit",
        horizon=20,
        max_holding_days=3,
        profit_barrier=0.02,
        stop_loss_barrier=0.01,
    )

    assert result.episode_count == 5
    assert result.s1_episode_count == 2
    assert result.s1_success_count == 1
    assert result.s1_failure_count == 1
    assert result.tbm_label_count == 2
    assert result.warning_count == 1
    assert result.episode_parquet_path.exists()
    assert result.transition_parquet_path.exists()
    assert result.trigger_diagnostic_parquet_path.exists()
    assert result.tbm_parquet_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    episodes = pd.read_parquet(result.episode_parquet_path)
    assert set(episodes["s1_outcome"]) >= {"success_to_s2", "failure_to_s0"}

    tbm = pd.read_parquet(result.tbm_parquet_path)
    assert set(tbm["tbm_label"]) == {"take_profit", "stop_loss"}
    assert tbm["trading_instruction"].eq("not_a_trading_instruction").all()

    triggers = pd.read_parquet(result.trigger_diagnostic_parquet_path)
    assert set(triggers["transition_code"]) >= {"S1_TO_S2", "S1_TO_S0"}
    assert "trigger_condition_cn" in triggers.columns

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "S1 生命周期摘要" in markdown
    assert "S1 转移触发条件诊断" in markdown
    assert "S1_TO_S0" in markdown
    assert "Triple Barrier" in markdown
    assert "不构成交易指令" in markdown

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "event_lifecycle_research"
    assert payload["s1_summary"]["success_to_s2_count"] == 1
    assert payload["research_boundary"]["auto_reverse_allowed"] is False


def test_cli_build_cf_event_lifecycle_research(tmp_path: Path) -> None:
    matrix_path = _write_signal_matrix_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-event-lifecycle-research",
            "--signal-matrix-path",
            str(matrix_path),
            "--output-dir",
            str(tmp_path / "research" / "event_lifecycle"),
            "--report-output-dir",
            str(tmp_path / "reports" / "event_lifecycle"),
            "--run-id",
            "r68_cli",
            "--horizon",
            "20",
            "--max-holding-days",
            "3",
            "--profit-barrier",
            "0.02",
            "--stop-loss-barrier",
            "0.01",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r68_cli"
    assert output["s1_success_count"] == 1
    assert Path(output["tbm_parquet_path"]).exists()


def _write_signal_matrix_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "signal_matrix.parquet"
    rows = [
        ("2026-01-01", "S0", "未确认", "neutral", "neutral", "low", 100.0),
        ("2026-01-02", "S1", "起点观察", "long", "long", "high", 100.0),
        ("2026-01-03", "S1", "起点观察", "long", "long", "high", 101.0),
        ("2026-01-04", "S1", "起点观察", "long", "long", "high", 103.0),
        ("2026-01-05", "S2", "趋势中", "long", "long", "high", 104.0),
        ("2026-01-06", "S1", "起点观察", "long", "long", "high", 104.0),
        ("2026-01-07", "S1", "起点观察", "long", "long", "high", 102.0),
        ("2026-01-08", "S0", "未确认", "neutral", "neutral", "low", 101.0),
    ]
    frame = pd.DataFrame(
        [
            {
                "run_id": "fixture",
                "product_code": "CF",
                "trade_date": trade_date,
                "horizon": 20,
                "horizon_label": "20D",
                "main_contract": "CF609",
                "main_settle": settle,
                "trend_phase": phase,
                "trend_phase_label": phase_label,
                "trend_phase_direction": phase_direction,
                "direction": direction,
                "confidence": confidence,
                "transition_code": "",
            }
            for (
                trade_date,
                phase,
                phase_label,
                phase_direction,
                direction,
                confidence,
                settle,
            ) in rows
        ]
    )
    frame.to_parquet(path, index=False)
    return path
