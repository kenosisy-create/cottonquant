from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_event_threshold_sensitivity


def test_build_cf_event_threshold_sensitivity_writes_review_tables(
    tmp_path: Path,
) -> None:
    paths = _write_r60_inputs(tmp_path)

    result = build_cf_event_threshold_sensitivity(
        validation_daily_path=paths["validation"],
        event_path=paths["events"],
        output_dir=tmp_path / "research" / "event_threshold_sensitivity",
        report_output_dir=tmp_path / "reports" / "event_threshold_sensitivity",
        run_id="r60_unit",
        primary_horizon=5,
        horizons=(1, 3, 5),
        threshold_quantiles=(0.80, 0.90),
        min_observation_count=3,
    )

    assert result.status == "EVENT_THRESHOLD_SENSITIVITY_READY_WITH_WARNINGS"
    assert result.passed is True
    assert result.detail_row_count > 0
    assert result.summary_row_count > 0
    assert result.annual_row_count > 0
    assert result.to_summary()["forward_returns_are_validation_labels"] is True
    assert result.to_summary()["review_decision_counts"]["KEEP"] >= 0

    detail = pd.read_parquet(result.detail_parquet_path)
    assert {"baseline_r55", "oi_anomaly", "curve_shock"} <= set(
        detail["threshold_scope"]
    )
    assert set(detail["interpretation_status"]) == {"HUMAN_REVIEW_REQUIRED"}
    assert set(detail["trading_instruction"]) == {"not_a_trading_instruction"}

    summary = pd.read_parquet(result.summary_parquet_path)
    assert {0.8, 0.9} <= set(
        summary.loc[summary["threshold_scope"].ne("baseline_r55"), "threshold_quantile"]
    )
    assert {
        "review_decision_candidate",
        "year_distribution",
        "forward_returns_are_validation_labels",
    } <= set(summary.columns)
    assert set(summary["review_decision_candidate"]) <= {
        "KEEP",
        "WATCH",
        "REVISE",
        "REJECT",
    }

    annual = pd.read_parquet(result.annual_parquet_path)
    assert {"event_year", "observation_count", "directional_hit_rate"} <= set(
        annual.columns
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "event_threshold_sensitivity"
    assert payload["summary"]["trading_instruction"] == "not_a_trading_instruction"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 事件阈值敏感性复核 R60" in markdown
    assert "阈值敏感性总览" in markdown
    assert "forward_return 只作为历史后验验证标签" in markdown
    assert "本报告不构成交易指令" in markdown


def test_cli_build_cf_event_threshold_sensitivity(tmp_path: Path) -> None:
    paths = _write_r60_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-event-threshold-sensitivity",
            "--validation-daily-path",
            str(paths["validation"]),
            "--event-path",
            str(paths["events"]),
            "--output-dir",
            str(tmp_path / "research" / "event_threshold_sensitivity"),
            "--report-output-dir",
            str(tmp_path / "reports" / "event_threshold_sensitivity"),
            "--run-id",
            "r60_cli",
            "--primary-horizon",
            "5",
            "--horizons",
            "1,3,5",
            "--threshold-quantiles",
            "0.8,0.9",
            "--min-observation-count",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r60_cli"
    assert output["passed"] is True
    assert output["threshold_quantiles"] == [0.8, 0.9]
    assert set(output["review_decision_counts"]) == {"KEEP", "WATCH", "REVISE", "REJECT"}
    assert Path(output["summary_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def _write_r60_inputs(tmp_path: Path) -> dict[str, Path]:
    validation_path = tmp_path / "validation" / "validation_daily.parquet"
    event_path = tmp_path / "events" / "event_explanation_events.parquet"
    validation_path.parent.mkdir(parents=True)
    event_path.parent.mkdir(parents=True)

    trade_dates = _business_dates(date(2024, 1, 2), count=12)
    rows: list[dict[str, object]] = []
    for idx, trade_date in enumerate(trade_dates):
        for horizon in (1, 3, 5):
            rows.append(
                {
                    "run_id": "r36_threshold_fixture",
                    "product_code": "CF",
                    "trade_date": trade_date,
                    "horizon": horizon,
                    "main_contract": "CF405",
                    "direction": "long" if idx % 2 == 0 else "short",
                    "confidence": "medium",
                    "trend_phase": ["S1", "S2", "S2", "S3"][idx % 4],
                    "trend_phase_label": "fixture",
                    "composite_score": 4 + idx % 3,
                    "return_20d": 0.01 * idx,
                    "main_oi_pressure": [0.1, 0.2, 0.3, 2.5, 0.4, 3.0][idx % 6],
                    "curve_slope": [0.01, 0.02, 0.03, 0.30, 0.31, 0.10][idx % 6],
                    "carry_annualized": 0.02,
                    "forward_return": 0.01 * horizon if idx % 3 else -0.005 * horizon,
                    "forward_label_available": True,
                    "execution_date": trade_date + timedelta(days=1),
                    "exit_date": trade_date + timedelta(days=1 + horizon),
                    "directional_hit": idx % 3 != 0,
                    "validation_rule_version": "R36_signal_matrix_rolling_validation_v1",
                    "forward_returns_are_validation_labels": True,
                }
            )
    pd.DataFrame(rows).to_parquet(validation_path, index=False)

    event_rows: list[dict[str, object]] = []
    for idx, trade_date in enumerate(trade_dates[:6]):
        event_row: dict[str, object] = {
            "run_id": "r55_fixture",
            "product_code": "CF",
            "event_date": trade_date,
            "event_category": "trend_start" if idx % 2 == 0 else "oi_anomaly",
            "event_type": "趋势起点" if idx % 2 == 0 else "持仓异常变化",
            "event_oi_pressure": 1.5 + idx,
            "event_curve_slope": 0.1 * idx,
        }
        for horizon in (1, 3, 5):
            event_row[f"forward_return_h{horizon}"] = (
                0.01 * horizon if idx % 3 else -0.005 * horizon
            )
            event_row[f"forward_label_available_h{horizon}"] = True
            event_row[f"event_direction_hit_h{horizon}"] = idx % 3 != 0
            event_row[f"execution_date_h{horizon}"] = (
                trade_date + timedelta(days=1)
            ).isoformat()
            event_row[f"exit_date_h{horizon}"] = (
                trade_date + timedelta(days=1 + horizon)
            ).isoformat()
        event_rows.append(event_row)
    pd.DataFrame(event_rows).to_parquet(event_path, index=False)
    return {"validation": validation_path, "events": event_path}


def _business_dates(start: date, *, count: int) -> list[date]:
    dates: list[date] = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates
