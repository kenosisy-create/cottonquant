from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_futures_option_divergence_research


def test_build_cf_futures_option_divergence_labels_winners_and_outputs(
    tmp_path: Path,
) -> None:
    validation_path = _write_validation_fixture(tmp_path)

    result = build_cf_futures_option_divergence_research(
        signal_matrix_validation_path=validation_path,
        output_dir=tmp_path / "research" / "futures_option_divergence",
        report_output_dir=tmp_path / "reports" / "futures_option_divergence",
        run_id="r69_unit",
        horizons=(1,),
        dead_zone_bps=10,
        min_sample_size=2,
    )

    assert result.event_row_count == 6
    assert result.directional_divergence_count == 3
    assert result.event_parquet_path.exists()
    assert result.summary_by_horizon_parquet_path.exists()
    assert result.summary_by_node_parquet_path.exists()
    assert result.resolution_timing_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    events = pd.read_parquet(result.event_parquet_path)
    labels = set(events["winner_label"])
    assert "FUTURES_WIN" in labels
    assert "OPTIONS_WIN" in labels
    assert "UNRESOLVED" in labels
    assert "FUTURES_FAILED" in labels
    assert "FUTURES_FOLLOW_THROUGH" in labels
    assert events["trading_instruction"].eq("not_a_trading_instruction").all()
    assert events["forward_returns_are_validation_labels"].all()

    neutral_row = events.loc[events["option_signal"].eq("option_neutral")].iloc[0]
    assert neutral_row["winner_label"] == "FUTURES_FAILED"

    node_summary = pd.read_parquet(result.summary_by_node_parquet_path)
    assert "WEAK_OR_SMALL_SAMPLE" in set(node_summary["evidence_level"])

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "不构成交易指令" in markdown
    assert "`forward_return` 仅为历史后验验证标签" in markdown
    assert "期权 PCR、ATM IV rank、skew 均为研究 proxy" in markdown

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "futures_option_divergence_research"
    assert payload["research_boundary"]["auto_reverse_allowed"] is False
    assert payload["research_boundary"]["option_iv_greek_is_proxy"] is True


def test_cli_build_cf_futures_option_divergence_research(tmp_path: Path) -> None:
    validation_path = _write_validation_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-futures-option-divergence-research",
            "--signal-matrix-validation-path",
            str(validation_path),
            "--output-dir",
            str(tmp_path / "research" / "futures_option_divergence"),
            "--report-output-dir",
            str(tmp_path / "reports" / "futures_option_divergence"),
            "--run-id",
            "r69_cli",
            "--horizons",
            "1",
            "--dead-zone-bps",
            "10",
            "--min-sample-size",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r69_cli"
    assert output["directional_divergence_count"] == 3
    assert Path(output["event_parquet_path"]).exists()
    assert output["forward_returns_are_validation_labels"] is True
    assert output["trading_instruction"] == "not_a_trading_instruction"


def test_build_cf_futures_option_divergence_requires_option_columns(
    tmp_path: Path,
) -> None:
    validation_path = _write_validation_fixture(tmp_path)
    frame = pd.read_parquet(validation_path)
    broken_path = tmp_path / "broken_validation.parquet"
    frame.drop(columns=["option_signal_direction"]).to_parquet(broken_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="missing columns"):
        build_cf_futures_option_divergence_research(
            signal_matrix_validation_path=broken_path,
            output_dir=tmp_path / "research" / "futures_option_divergence",
            report_output_dir=tmp_path / "reports" / "futures_option_divergence",
            run_id="r69_broken",
            horizons=(1,),
        )


def _write_validation_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "signal_matrix_validation_daily.parquet"
    rows = [
        _row(
            "2026-01-02",
            "long",
            "diverge_long",
            "short",
            0.020,
            "S1",
            "high",
        ),
        _row(
            "2026-01-03",
            "long",
            "diverge_long",
            "short",
            -0.030,
            "S1",
            "high",
        ),
        _row(
            "2026-01-04",
            "long",
            "diverge_long",
            "short",
            0.0005,
            "S1",
            "medium",
        ),
        _row(
            "2026-01-05",
            "long",
            "option_neutral",
            "neutral",
            -0.012,
            "S3",
            "medium",
        ),
        _row(
            "2026-01-06",
            "long",
            "option_watch",
            "unknown",
            0.015,
            "S0",
            "low",
        ),
        _row(
            "2026-01-07",
            "long",
            "confirm_long",
            "long",
            0.018,
            "S2",
            "high",
        ),
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _row(
    trade_date: str,
    direction: str,
    option_signal: str,
    option_direction: str,
    forward_return: float,
    trend_phase: str,
    confidence: str,
) -> dict[str, object]:
    return {
        "run_id": "fixture",
        "product_code": "CF",
        "trade_date": trade_date,
        "horizon": 1,
        "main_contract": "CF609",
        "direction": direction,
        "trend_phase": trend_phase,
        "confidence": confidence,
        "oi_signal": "long",
        "option_signal": option_signal,
        "option_signal_direction": option_direction,
        "option_factor_status": "READY",
        "option_atm_iv_rank": 0.20,
        "option_pcr_volume": 1.30 if option_direction == "short" else 0.70,
        "option_pcr_oi": 1.25 if option_direction == "short" else 0.75,
        "option_skew_proxy": 0.002 if option_direction == "short" else -0.002,
        "forward_return": forward_return,
        "forward_label_available": True,
        "execution_date": "2026-01-03",
        "exit_date": "2026-01-04",
        "forward_returns_are_validation_labels": True,
    }
