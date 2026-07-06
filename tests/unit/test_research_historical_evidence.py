from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_historical_evidence_pack


def test_build_cf_historical_evidence_pack_writes_history_outputs(tmp_path: Path) -> None:
    paths = _write_r41_inputs(tmp_path)

    result = build_cf_historical_evidence_pack(
        core_quote_path=paths["core"],
        signal_matrix_path=paths["matrix"],
        validation_daily_path=paths["validation"],
        validation_window_summary_path=paths["window"],
        threshold_weighting_path=paths["threshold"],
        output_dir=tmp_path / "historical_evidence",
        report_output_dir=tmp_path / "historical_reports",
        run_id="r41_unit",
    )

    assert result.evidence_summary_row_count > 0
    assert result.decay_row_count == 3
    assert result.stability_row_count == 3
    assert result.evidence_summary_parquet_path.exists()
    assert result.decay_parquet_path.exists()
    assert result.stability_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    summary = pd.read_parquet(result.evidence_summary_parquet_path)
    assert {"group_type", "horizon", "cost_scenario", "mean_net_return"} <= set(
        summary.columns
    )
    normal = summary.loc[
        summary["group_type"].eq("overall")
        & summary["horizon"].eq(1)
        & summary["cost_scenario"].eq("normal_cost")
    ].iloc[0]
    no_cost = summary.loc[
        summary["group_type"].eq("overall")
        & summary["horizon"].eq(1)
        & summary["cost_scenario"].eq("no_cost")
    ].iloc[0]
    assert normal["mean_net_return"] < no_cost["mean_net_return"]
    assert normal["mean_forward_return"] == pytest.approx(no_cost["mean_forward_return"])

    decay = pd.read_parquet(result.decay_parquet_path)
    assert set(decay["horizon"]) == {1, 3, 5}
    assert "mean_net_return_normal_cost" in decay.columns

    stability = pd.read_parquet(result.stability_parquet_path)
    assert "READY" in set(stability["stability_status"])

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "historical_evidence_pack"
    assert payload["forward_returns_are_validation_labels"] is True
    assert payload["no_latest_signal_dependency"] is True

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["contains_latest_signal_only_inputs"] is False

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 历史多因子证据包" in markdown
    assert "forward_return 只作为历史后验验证标签" in markdown
    assert "本报告不进入 latest signal-only brief" in markdown


def test_build_cf_historical_evidence_pack_rejects_t0_execution(
    tmp_path: Path,
) -> None:
    paths = _write_r41_inputs(tmp_path)
    validation = pd.read_parquet(paths["validation"])
    validation.loc[0, "execution_date"] = validation.loc[0, "trade_date"]
    validation.to_parquet(paths["validation"], index=False)

    with pytest.raises(ResearchWorkbenchError, match="T\\+1 execution timing"):
        build_cf_historical_evidence_pack(
            core_quote_path=paths["core"],
            signal_matrix_path=paths["matrix"],
            validation_daily_path=paths["validation"],
            validation_window_summary_path=paths["window"],
            threshold_weighting_path=paths["threshold"],
            output_dir=tmp_path / "historical_evidence",
            report_output_dir=tmp_path / "historical_reports",
            run_id="r41_bad_t0",
        )


def test_cli_build_cf_historical_evidence_pack(tmp_path: Path) -> None:
    paths = _write_r41_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-historical-evidence-pack",
            "--core-quote-path",
            str(paths["core"]),
            "--signal-matrix-path",
            str(paths["matrix"]),
            "--validation-daily-path",
            str(paths["validation"]),
            "--validation-window-summary-path",
            str(paths["window"]),
            "--threshold-weighting-path",
            str(paths["threshold"]),
            "--output-dir",
            str(tmp_path / "historical_evidence"),
            "--report-output-dir",
            str(tmp_path / "historical_reports"),
            "--run-id",
            "r41_cli",
            "--cost-scenarios",
            "no_cost=0,normal_cost=5,conservative_cost=10",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["evidence_summary_row_count"] > 0
    assert Path(output["evidence_summary_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def _write_r41_inputs(tmp_path: Path) -> dict[str, Path]:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    matrix_path = tmp_path / "signal_matrix" / "matrix.parquet"
    validation_path = tmp_path / "validation" / "validation_daily.parquet"
    window_path = tmp_path / "validation" / "window_summary.parquet"
    threshold_path = tmp_path / "threshold" / "weighting.parquet"
    for path in (core_path, matrix_path, validation_path, window_path, threshold_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=10)
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "contract_code": "CF405",
                "settle": 100 + offset,
                "open_interest": 10_000 + offset,
            }
            for offset, trade_date in enumerate(trade_dates)
        ]
    ).to_parquet(core_path, index=False)
    pd.DataFrame(
        [
            {
                "trade_date": item["trade_date"],
                "horizon": item["horizon"],
                "direction": item["direction"],
                "confidence": item["confidence"],
                "trend_phase": item["trend_phase"],
            }
            for item in _validation_rows(trade_dates)
        ]
    ).to_parquet(matrix_path, index=False)
    pd.DataFrame(_validation_rows(trade_dates)).to_parquet(validation_path, index=False)
    pd.DataFrame(
        [
            {
                "window_id": "2024",
                "horizon": horizon,
                "observation_count": 2,
                "mean_forward_return": 0.01,
            }
            for horizon in (1, 3, 5)
        ]
    ).to_parquet(window_path, index=False)
    pd.DataFrame(
        [
            _threshold_row(1, "confidence_ge_70", "置信度 >=70", "READY_CANDIDATE", 0.62),
            _threshold_row(3, "confidence_ge_55", "置信度 >=55", "WATCH_CANDIDATE", 0.54),
            _threshold_row(5, "matrix_all", "矩阵全样本", "WEAK_OR_UNSTABLE", 0.49),
        ]
    ).to_parquet(threshold_path, index=False)
    return {
        "core": core_path,
        "matrix": matrix_path,
        "validation": validation_path,
        "window": window_path,
        "threshold": threshold_path,
    }


def _validation_rows(trade_dates: list[date]) -> list[dict[str, object]]:
    rows = [
        _validation_row(trade_dates[0], 1, "long", 0.02, True, "high", "S2"),
        _validation_row(trade_dates[1], 1, "short", -0.01, True, "medium", "S2"),
        _validation_row(trade_dates[2], 3, "long", -0.02, False, "medium", "S3"),
        _validation_row(trade_dates[3], 3, "neutral", 0.01, False, "low", "S0"),
        _validation_row(trade_dates[4], 5, "long", 0.03, True, "high", "S1"),
        _validation_row(trade_dates[5], 5, "short", 0.04, False, "low", "S3"),
    ]
    rows.append(
        {
            **_validation_row(trade_dates[6], 5, "long", 0.0, False, "low", "S0"),
            "forward_return": None,
            "forward_label_available": False,
            "execution_date": None,
            "exit_date": None,
        }
    )
    return rows


def _validation_row(
    trade_date: date,
    horizon: int,
    direction: str,
    forward_return: float,
    hit: bool,
    confidence: str,
    trend_phase: str,
) -> dict[str, object]:
    return {
        "run_id": "r36_fixture",
        "product_code": "CF",
        "trade_date": trade_date,
        "horizon": horizon,
        "horizon_label": f"{horizon}D",
        "main_contract": "CF405",
        "direction": direction,
        "confidence": confidence,
        "confidence_score": 70,
        "trend_phase": trend_phase,
        "trend_phase_label": trend_phase,
        "evidence_level": "moderate",
        "window_id": "2024",
        "window_start": date(2024, 1, 1),
        "window_end": date(2024, 12, 31),
        "forward_return": forward_return,
        "forward_label_available": True,
        "execution_date": trade_date + timedelta(days=1),
        "exit_date": trade_date + timedelta(days=1 + horizon),
        "directional_hit": hit,
        "validation_rule_version": "R36_signal_matrix_rolling_validation_v1",
        "forward_returns_are_validation_labels": True,
    }


def _threshold_row(
    horizon: int,
    scheme_id: str,
    label: str,
    status: str,
    hit_rate: float,
) -> dict[str, object]:
    return {
        "scheme_id": scheme_id,
        "scheme_label_cn": label,
        "horizon": horizon,
        "active_row_count": 10,
        "total_row_count": 20,
        "coverage_rate": 0.5,
        "observation_count": 40,
        "mean_forward_return": 0.015,
        "median_forward_return": 0.01,
        "directional_hit_rate": hit_rate,
        "candidate_status": status,
        "threshold_rule_version": "R37_signal_threshold_weight_research_v1",
    }


def _business_dates(start: date, *, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values
