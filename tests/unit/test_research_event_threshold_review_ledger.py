from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_event_threshold_review_ledger


def test_build_cf_event_threshold_review_ledger_writes_traceable_outputs(
    tmp_path: Path,
) -> None:
    paths = _write_r62_inputs(tmp_path)

    result = build_cf_event_threshold_review_ledger(
        threshold_summary_path=paths["summary"],
        threshold_detail_path=paths["detail"],
        event_detail_path=paths["events"],
        output_dir=tmp_path / "research" / "event_threshold_review",
        report_output_dir=tmp_path / "reports" / "event_threshold_review",
        run_id="r62_unit",
        example_event_count=2,
    )

    assert result.status == "EVENT_THRESHOLD_REVIEW_READY"
    assert result.passed is True
    assert result.candidate_count == 4
    assert result.evidence_row_count == 8
    assert result.review_action_counts == {
        "KEEP_REVIEW": 1,
        "WATCH_REVIEW": 1,
        "REVISE_REVIEW": 1,
        "REJECT_REVIEW": 1,
    }
    assert result.ledger_parquet_path.exists()
    assert result.ledger_csv_path.exists()
    assert result.evidence_parquet_path.exists()
    assert result.evidence_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    ledger = pd.read_parquet(result.ledger_parquet_path)
    assert ledger["candidate_id"].is_unique
    assert set(ledger["suggested_review_action"]) == {
        "KEEP_REVIEW",
        "WATCH_REVIEW",
        "REVISE_REVIEW",
        "REJECT_REVIEW",
    }
    assert set(ledger["forward_returns_are_validation_labels"]) == {True}
    assert set(ledger["interpretation_status"]) == {"HUMAN_REVIEW_REQUIRED"}
    assert set(ledger["trading_instruction"]) == {"not_a_trading_instruction"}
    assert ledger.loc[
        ledger["review_decision_candidate"].eq("KEEP"),
        "human_review_question_cn",
    ].str.contains("validated brief").all()

    evidence = pd.read_parquet(result.evidence_parquet_path)
    assert set(evidence["event_detail_trace_status"]) == {"EVENT_DETAIL_MATCHED"}
    assert "factor_contribution_cn" in evidence.columns
    assert set(evidence["trading_instruction"]) == {"not_a_trading_instruction"}

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 事件阈值候选复核台账 R62" in markdown
    assert "R60 候选总览" in markdown
    assert "KEEP 候选复核台账" in markdown
    assert "事件样本追溯" in markdown
    assert "forward_return 只作为历史后验验证标签" in markdown
    assert "本报告不构成交易指令" in markdown

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "event_threshold_review_ledger"
    assert payload["summary"]["forward_returns_are_validation_labels"] is True
    assert payload["summary"]["trading_instruction"] == "not_a_trading_instruction"


def test_cli_build_cf_event_threshold_review_ledger(tmp_path: Path) -> None:
    paths = _write_r62_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-event-threshold-review-ledger",
            "--threshold-summary-path",
            str(paths["summary"]),
            "--threshold-detail-path",
            str(paths["detail"]),
            "--event-detail-path",
            str(paths["events"]),
            "--output-dir",
            str(tmp_path / "research" / "event_threshold_review"),
            "--report-output-dir",
            str(tmp_path / "reports" / "event_threshold_review"),
            "--run-id",
            "r62_cli",
            "--example-event-count",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r62_cli"
    assert output["passed"] is True
    assert output["candidate_count"] == 4
    assert output["evidence_row_count"] == 8
    assert Path(output["ledger_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def _write_r62_inputs(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "inputs"
    root.mkdir(parents=True)
    summary_path = root / "threshold_summary.parquet"
    detail_path = root / "threshold_detail.parquet"
    event_path = root / "event_detail.parquet"

    summary_rows = [
        _summary_row("baseline_r55", "trend_start", "趋势起点", None, None, 5, "KEEP", 0.62),
        _summary_row("oi_anomaly", "oi_anomaly", "持仓异常变化", 0.90, 2.5, 5, "WATCH", 0.55),
        _summary_row("curve_shock", "curve_shock", "曲线结构突变", 0.95, 0.2, 5, "REJECT", 0.35),
        _summary_row("oi_anomaly", "oi_anomaly", "持仓异常变化", 0.95, 3.0, 1, "REVISE", 0.50),
    ]
    pd.DataFrame(summary_rows).to_parquet(summary_path, index=False)

    event_dates = _business_dates(date(2024, 1, 2), count=8)
    detail_rows: list[dict[str, object]] = []
    detail_rows.extend(
        _detail_rows("baseline_r55", "trend_start", "趋势起点", None, 5, event_dates[:2])
    )
    detail_rows.extend(
        _detail_rows("oi_anomaly", "oi_anomaly", "持仓异常变化", 0.90, 5, event_dates[2:4])
    )
    detail_rows.extend(
        _detail_rows("curve_shock", "curve_shock", "曲线结构突变", 0.95, 5, event_dates[4:6])
    )
    detail_rows.extend(
        _detail_rows("oi_anomaly", "oi_anomaly", "持仓异常变化", 0.95, 1, event_dates[6:8])
    )
    pd.DataFrame(detail_rows).to_parquet(detail_path, index=False)

    event_rows = [
        {
            "run_id": "r55_fixture",
            "product_code": "CF",
            "event_date": row["event_date"],
            "event_category": row["event_category"],
            "event_type": row["event_type"],
            "main_contract": "CF405",
            "direction": "long",
            "confidence": "medium",
            "composite_score": 4.0,
            "factor_contribution_cn": "动量=long；carry=long；曲线=neutral；持仓=long",
            "event_reason": "fixture event",
            "fundamental_context_available": True,
            "fundamental_aligned_count": 2,
            "fundamental_divergent_count": 1,
            "fundamental_context_summary_cn": "fixture 基本面上下文，用于解释而非信号。",
        }
        for row in detail_rows
    ]
    pd.DataFrame(event_rows).to_parquet(event_path, index=False)
    return {"summary": summary_path, "detail": detail_path, "events": event_path}


def _summary_row(
    threshold_scope: str,
    event_category: str,
    event_type: str,
    threshold_quantile: float | None,
    threshold_value: float | None,
    horizon: int,
    decision: str,
    hit_rate: float,
) -> dict[str, object]:
    return {
        "product_code": "CF",
        "threshold_scope": threshold_scope,
        "event_category": event_category,
        "event_type": event_type,
        "threshold_quantile": threshold_quantile,
        "threshold_value": threshold_value,
        "horizon": horizon,
        "event_count": 24,
        "observation_count": 24,
        "mean_forward_return": 0.012 if decision != "REJECT" else -0.006,
        "median_forward_return": 0.008 if decision != "REJECT" else -0.004,
        "directional_hit_rate": hit_rate,
        "positive_return_rate": hit_rate,
        "year_count": 4,
        "min_annual_observation_count": 3,
        "year_distribution": '{"2021": 6, "2022": 6, "2023": 6, "2024": 6}',
        "review_decision_candidate": decision,
        "interpretation_status": "HUMAN_REVIEW_REQUIRED",
        "forward_returns_are_validation_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _detail_rows(
    threshold_scope: str,
    event_category: str,
    event_type: str,
    threshold_quantile: float | None,
    horizon: int,
    event_dates: list[date],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, event_date in enumerate(event_dates):
        rows.append(
            {
                "run_id": "r60_fixture",
                "product_code": "CF",
                "threshold_scope": threshold_scope,
                "event_category": event_category,
                "event_type": event_type,
                "threshold_quantile": threshold_quantile,
                "threshold_value": None,
                "event_intensity": 1.0 + index,
                "event_date": event_date,
                "event_year": event_date.year,
                "horizon": horizon,
                "forward_return": 0.01 * (index + 1),
                "forward_label_available": True,
                "directional_hit": index % 2 == 0,
                "execution_date": event_date + timedelta(days=1),
                "exit_date": event_date + timedelta(days=1 + horizon),
                "source_event_id": f"{threshold_scope}:{horizon}:{index}",
                "forward_returns_are_validation_labels": True,
                "interpretation_status": "HUMAN_REVIEW_REQUIRED",
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return rows


def _business_dates(start: date, *, count: int) -> list[date]:
    dates: list[date] = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates
