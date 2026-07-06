from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.core.schemas import (
    ResearchFactorDiagnosticDailyRow,
    ResearchForwardReturnDailyRow,
)
from cotton_factor.research_workbench import build_cf_single_factor_backtest


def test_build_cf_single_factor_backtest_writes_evaluation_metrics(tmp_path: Path) -> None:
    diagnostic_path = _write_diagnostics(
        tmp_path,
        [
            _diagnostic(date(2024, 1, 1), raw_value=1.0, state="long"),
            _diagnostic(date(2024, 1, 2), raw_value=2.0, state="long"),
            _diagnostic(date(2024, 1, 3), raw_value=None, state="unknown"),
        ],
    )
    forward_path = _write_forward_returns(
        tmp_path,
        [
            _forward_return(date(2024, 1, 1), forward_return=0.1),
            _forward_return(date(2024, 1, 2), forward_return=0.2),
        ],
    )

    result = build_cf_single_factor_backtest(
        start=date(2024, 1, 1),
        end=date(2024, 1, 3),
        factor_ids=("mom_20_v1",),
        horizons=(1,),
        diagnostic_path=diagnostic_path,
        forward_return_path=forward_path,
        output_dir=tmp_path / "backtests",
        report_output_dir=tmp_path / "reports",
        run_id="r16_single_factor_test",
    )

    metrics = {row.metric_name: row.metric_value for row in result.rows}
    assert metrics["observation_count"] == 2
    assert metrics["mean_factor_value"] == pytest.approx(1.5)
    assert metrics["mean_forward_return"] == pytest.approx(0.15)
    assert metrics["pearson_ic"] == pytest.approx(1)
    assert metrics["spearman_rank_ic"] == pytest.approx(1)
    assert metrics["directional_accuracy"] == pytest.approx(1)
    assert result.evaluation_parquet_path.exists()
    assert result.evaluation_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()

    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "SINGLE_FACTOR_UNKNOWN_DIAGNOSTICS_SKIPPED" in warning_codes
    written = pd.read_parquet(result.evaluation_parquet_path)
    assert set(written["metric_name"]) >= {
        "observation_count",
        "mean_factor_value",
        "mean_forward_return",
        "pearson_ic",
    }


def test_build_cf_single_factor_backtest_requires_positive_horizons(tmp_path: Path) -> None:
    diagnostic_path = _write_diagnostics(
        tmp_path,
        [_diagnostic(date(2024, 1, 1), raw_value=1.0, state="long")],
    )
    forward_path = _write_forward_returns(
        tmp_path,
        [_forward_return(date(2024, 1, 1), forward_return=0.1)],
    )

    with pytest.raises(ResearchWorkbenchError, match="positive integers"):
        build_cf_single_factor_backtest(
            start=date(2024, 1, 1),
            end=date(2024, 1, 1),
            factor_ids=("mom_20_v1",),
            horizons=(0,),
            diagnostic_path=diagnostic_path,
            forward_return_path=forward_path,
            output_dir=tmp_path / "backtests",
            report_output_dir=tmp_path / "reports",
        )


def _write_diagnostics(tmp_path: Path, rows: list[ResearchFactorDiagnosticDailyRow]) -> Path:
    path = tmp_path / "factors" / "CF_2024-01-01_2024-01-03_factor_diagnostic_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_forward_returns(tmp_path: Path, rows: list[ResearchForwardReturnDailyRow]) -> Path:
    path = tmp_path / "returns" / "CF_2024-01-01_2024-01-03_forward_return_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _diagnostic(
    trade_date: date,
    *,
    raw_value: float | None,
    state: str,
) -> ResearchFactorDiagnosticDailyRow:
    warning_flags = ["missing_factor"] if state == "unknown" else []
    return ResearchFactorDiagnosticDailyRow(
        run_id="r14_diag_test",
        factor_id="mom_20_v1",
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        signal_state=state,
        diagnostic_reason=f"fixture {state}",
        warning_flags=warning_flags,
        human_review_required=["factor_thresholds"],
        diagnostic_rule_version="r14_sign_state_heuristic_v1",
        input_snapshot_ids=[f"diag_{trade_date:%Y%m%d}"],
    )


def _forward_return(
    trade_date: date,
    *,
    forward_return: float,
) -> ResearchForwardReturnDailyRow:
    return ResearchForwardReturnDailyRow(
        run_id="r15_forward_test",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        execution_date=date(2024, 1, trade_date.day + 1),
        exit_date=date(2024, 1, trade_date.day + 2),
        horizon=1,
        target_contract="CF401",
        entry_price_field="settle",
        exit_price_field="settle",
        entry_price=100,
        exit_price=100 * (1 + forward_return),
        forward_return=forward_return,
        return_rule_version="forward_return_real_contract_tplus1_v1",
        input_snapshot_ids=[f"forward_{trade_date:%Y%m%d}"],
    )
