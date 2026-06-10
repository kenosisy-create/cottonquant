from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.archive import render_backtest_report, render_single_factor_report
from cotton_factor.common.exceptions import ReportRenderError
from cotton_factor.core.schemas import (
    ResearchFactorEvaluationRow,
    ResearchFactorValueDailyRow,
    ResearchForwardReturnDailyRow,
)


def test_render_single_factor_report_writes_html_with_metrics_and_lineage(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "single_factor.html"

    result = render_single_factor_report(
        evaluation_rows=[
            _evaluation_row("pearson_ic", 0.75),
            _evaluation_row("observation_count", 3),
        ],
        factor_rows=[_factor_row()],
        forward_return_rows=[_forward_return_row()],
        output_path=output_path,
        title="Factor <Momentum>",
        warnings=["review <lineage>"],
    )

    html = output_path.read_text(encoding="utf-8")
    assert result.report_type == "single_factor"
    assert result.row_count == 2
    assert result.input_snapshot_ids == [
        "raw_eval_1",
        "raw_factor_1",
        "raw_return_1",
    ]
    assert "pearson_ic" in html
    assert "0.75" in html
    assert "raw_factor_1" in html
    assert "Factor &lt;Momentum&gt;" in html
    assert "review &lt;lineage&gt;" in html
    assert "<Momentum>" not in html


def test_render_single_factor_report_rejects_mixed_run_ids(tmp_path: Path) -> None:
    with pytest.raises(ReportRenderError, match="mixed run_id"):
        render_single_factor_report(
            evaluation_rows=[
                _evaluation_row("pearson_ic", 0.75),
                _evaluation_row("spearman_rank_ic", 0.5, run_id="other_run"),
            ],
            output_path=tmp_path / "bad.html",
        )


def test_render_backtest_report_writes_summary_equity_trades_and_warnings(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "backtest.html"

    result = render_backtest_report(
        run_id="backtest_run_1",
        summary={"total_return": 0.123456, "blocked_count": 1},
        equity_curve=[
            {"trade_date": date(2024, 1, 2), "nav": 1.0},
            {"trade_date": date(2024, 1, 3), "nav": 1.1},
        ],
        trades=[
            {"trade_date": date(2024, 1, 2), "target_contract": "CF401", "lots": 1}
        ],
        output_path=output_path,
        warnings=["blocked execution retained"],
        input_snapshot_ids=["raw_bt_1", "raw_bt_1", "raw_bt_2"],
    )

    html = output_path.read_text(encoding="utf-8")
    assert result.report_type == "backtest"
    assert result.row_count == 3
    assert result.input_snapshot_ids == ["raw_bt_1", "raw_bt_2"]
    assert "total_return" in html
    assert "0.123456" in html
    assert "CF401" in html
    assert "blocked execution retained" in html
    assert "raw_bt_2" in html


def test_render_backtest_report_requires_summary(tmp_path: Path) -> None:
    with pytest.raises(ReportRenderError, match="summary"):
        render_backtest_report(
            run_id="backtest_run_1",
            summary={},
            output_path=tmp_path / "bad_backtest.html",
        )


def _evaluation_row(
    metric_name: str,
    metric_value: float,
    *,
    run_id: str = "eval_run_1",
) -> ResearchFactorEvaluationRow:
    return ResearchFactorEvaluationRow(
        run_id=run_id,
        factor_id="mom_20_v1",
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        horizon=1,
        metric_name=metric_name,
        metric_value=metric_value,
        observation_count=3,
        evaluation_rule_version="single_factor_eval_v1",
        input_snapshot_ids=["raw_eval_1"],
    )


def _factor_row() -> ResearchFactorValueDailyRow:
    return ResearchFactorValueDailyRow(
        run_id="factor_run_1",
        factor_id="mom_20_v1",
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=date(2024, 1, 1),
        raw_value=1.0,
        processed_value=None,
        input_snapshot_ids=["raw_factor_1"],
    )


def _forward_return_row() -> ResearchForwardReturnDailyRow:
    return ResearchForwardReturnDailyRow(
        run_id="forward_run_1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=date(2024, 1, 1),
        execution_date=date(2024, 1, 2),
        exit_date=date(2024, 1, 3),
        horizon=1,
        target_contract="CF401",
        entry_price_field="settle",
        exit_price_field="settle",
        entry_price=100,
        exit_price=110,
        forward_return=0.1,
        return_rule_version="forward_return_real_contract_tplus1_v1",
        input_snapshot_ids=["raw_return_1"],
    )
