from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_historical_event_explanation


def test_build_cf_historical_event_explanation_writes_events(
    tmp_path: Path,
) -> None:
    validation_path = _write_r42_validation(tmp_path)

    result = build_cf_historical_event_explanation(
        validation_daily_path=validation_path,
        output_dir=tmp_path / "events",
        report_output_dir=tmp_path / "event_reports",
        run_id="r42_unit",
        primary_horizon=5,
        horizons=(1, 3, 5),
        oi_anomaly_quantile=0.80,
        curve_shock_quantile=0.80,
    )

    assert result.event_row_count >= 7
    assert result.summary_row_count > 0
    assert result.event_parquet_path.exists()
    assert result.summary_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    events = pd.read_parquet(result.event_parquet_path)
    assert {
        "趋势起点",
        "趋势中继",
        "衰竭观察",
        "终点确认",
        "主力切换",
        "持仓异常变化",
        "曲线结构突变",
    } <= set(events["event_type"])
    assert events["explainable_historical_sample"].all()
    assert {"forward_return_h1", "forward_return_h3", "forward_return_h5"} <= set(
        events.columns
    )

    summary = pd.read_parquet(result.summary_parquet_path)
    assert set(summary["horizon"]) == {1, 3, 5}
    assert {"event_type", "mean_forward_return", "directional_hit_rate"} <= set(
        summary.columns
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "historical_event_explanation"
    assert payload["forward_returns_are_event_labels"] is True

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["forward_returns_are_event_labels"] is True

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 全历史事件解释包" in markdown
    assert "forward_return_* 只作为历史事件后的后验验证标签" in markdown
    assert "事件解释用于研究复盘，不构成交易指令" in markdown


def test_build_cf_historical_event_explanation_connects_fundamental_context(
    tmp_path: Path,
) -> None:
    validation_path = _write_r42_validation(tmp_path)
    fundamental_context_path = _write_r55_fundamental_context(tmp_path)

    result = build_cf_historical_event_explanation(
        validation_daily_path=validation_path,
        fundamental_context_path=fundamental_context_path,
        output_dir=tmp_path / "events",
        report_output_dir=tmp_path / "event_reports",
        run_id="r55_unit",
        primary_horizon=5,
        horizons=(1, 3, 5),
        oi_anomaly_quantile=0.80,
        curve_shock_quantile=0.80,
    )

    events = pd.read_parquet(result.event_parquet_path)
    assert {
        "fundamental_context_available",
        "fundamental_context_count",
        "fundamental_aligned_count",
        "fundamental_divergent_count",
        "fundamental_context_summary_cn",
    } <= set(events.columns)
    assert events["fundamental_context_available"].any()

    first_event = events.loc[
        pd.to_datetime(events["event_date"]).dt.date.eq(date(2024, 1, 3))
    ].iloc[0]
    assert first_event["fundamental_context_asof"] == "2024-01-02"
    assert "未来行不应进入" not in first_event["fundamental_context_summary_cn"]
    assert first_event["fundamental_context_rule_version"] == (
        "R55_event_fundamental_context_v1"
    )

    summary = pd.read_parquet(result.summary_parquet_path)
    assert {
        "fundamental_context_event_count",
        "fundamental_aligned_count",
        "fundamental_divergent_count",
    } <= set(summary.columns)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["fundamental_context_connected"] is True
    assert payload["summary"]["fundamental_context_path"] == str(fundamental_context_path)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "基本面事件解释" in markdown
    assert "R55 基本面上下文只使用事件日及以前可见数据" in markdown


def test_cli_build_cf_historical_event_explanation(tmp_path: Path) -> None:
    validation_path = _write_r42_validation(tmp_path)
    fundamental_context_path = _write_r55_fundamental_context(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-historical-event-explanation",
            "--validation-daily-path",
            str(validation_path),
            "--output-dir",
            str(tmp_path / "events"),
            "--report-output-dir",
            str(tmp_path / "event_reports"),
            "--run-id",
            "r42_cli",
            "--primary-horizon",
            "5",
            "--horizons",
            "1,3,5",
            "--fundamental-context-path",
            str(fundamental_context_path),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["event_row_count"] > 0
    assert output["fundamental_context_path"] == str(fundamental_context_path)
    assert Path(output["event_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def _write_r42_validation(tmp_path: Path) -> Path:
    path = tmp_path / "validation" / "validation_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=6)
    phases = ["S1", "S2", "S2", "S3", "S0", "S2"]
    contracts = ["CF405", "CF405", "CF409", "CF409", "CF409", "CF409"]
    oi_values = [0.1, 0.2, 0.3, 3.0, 0.2, 0.1]
    curve_values = [0.01, 0.02, 0.03, 0.04, 0.30, 0.31]
    rows: list[dict[str, object]] = []
    for idx, trade_date in enumerate(trade_dates):
        for horizon in (1, 3, 5):
            rows.append(
                {
                    "run_id": "r36_event_fixture",
                    "product_code": "CF",
                    "trade_date": trade_date,
                    "horizon": horizon,
                    "main_contract": contracts[idx],
                    "direction": "long",
                    "confidence": "medium",
                    "confidence_score": 60,
                    "trend_phase": phases[idx],
                    "trend_phase_label": phases[idx],
                    "price_signal": "long",
                    "momentum_signal": "long",
                    "carry_signal": "long",
                    "curve_signal": "long",
                    "oi_signal": "long",
                    "composite_score": 5 + idx,
                    "return_20d": 0.01 * idx,
                    "main_oi_pressure": oi_values[idx],
                    "curve_slope": curve_values[idx],
                    "carry_annualized": 0.02,
                    "forward_return": 0.01 * horizon,
                    "forward_label_available": True,
                    "execution_date": trade_date + timedelta(days=1),
                    "exit_date": trade_date + timedelta(days=1 + horizon),
                    "directional_hit": True,
                    "validation_rule_version": "R36_signal_matrix_rolling_validation_v1",
                    "forward_returns_are_validation_labels": True,
                }
            )
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_r55_fundamental_context(tmp_path: Path) -> Path:
    path = tmp_path / "fundamental_context" / "context_daily.parquet"
    path.parent.mkdir(parents=True)
    rows = [
        {
            "trade_date": date(2024, 1, 2),
            "dataset_type": "warehouse_receipt",
            "indicator_name": "仓单数量:一号棉",
            "raw_indicator_name": "仓单数量:一号棉",
            "metric_name": "warehouse_receipt",
            "indicator_value": 1200,
            "explanation_relation_4_vs_price20": "aligned_trailing_context",
            "context_label_4": "注册仓单下降，交割供应压力缓和",
            "fundamental_signal_status": "not_connected",
        },
        {
            "trade_date": date(2024, 1, 4),
            "dataset_type": "textile_chain",
            "indicator_name": "纺企棉纱库存",
            "raw_indicator_name": "纱线综合库存",
            "metric_name": "周均",
            "indicator_value": 25.1,
            "explanation_relation_4_vs_price20": "divergent_trailing_context",
            "context_label_4": "未来行不应进入 2024-01-03 事件解释",
            "fundamental_signal_status": "not_connected",
        },
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _business_dates(start: date, *, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values
