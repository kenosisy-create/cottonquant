from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.core.schemas import (
    ResearchForwardReturnDailyRow,
    ResearchMultifactorScoreDailyRow,
)
from cotton_factor.research_workbench import build_cf_cost_sensitivity


def test_build_cf_cost_sensitivity_writes_scenario_summaries(tmp_path: Path) -> None:
    score_path = _write_scores(
        tmp_path,
        [
            _score(date(2024, 1, 1), raw_score=0.5, snapshot_id="score_long"),
            _score(date(2024, 1, 2), raw_score=-0.2, snapshot_id="score_short"),
            _score(date(2024, 1, 3), raw_score=0.0, snapshot_id="score_flat"),
        ],
    )
    forward_path = _write_forward_returns(
        tmp_path,
        [
            _forward_return(date(2024, 1, 1), forward_return=0.02, snapshot_id="ret_long"),
            _forward_return(date(2024, 1, 2), forward_return=-0.01, snapshot_id="ret_short"),
            _forward_return(date(2024, 1, 3), forward_return=0.03, snapshot_id="ret_flat"),
        ],
    )

    result = build_cf_cost_sensitivity(
        start=date(2024, 1, 1),
        end=date(2024, 1, 3),
        horizons=(1,),
        score_path=score_path,
        forward_return_path=forward_path,
        scenario_cost_bps={"no_cost": 0.0, "normal_cost": 5.0},
        output_dir=tmp_path / "costs",
        report_output_dir=tmp_path / "reports",
        run_id="r18_cost_test",
    )

    assert len(result.rows) == 2
    assert result.row_count_by_scenario == {"no_cost": 1, "normal_cost": 1}
    no_cost = next(row for row in result.rows if row.scenario_id == "no_cost")
    normal_cost = next(row for row in result.rows if row.scenario_id == "normal_cost")
    assert no_cost.observation_count == 3
    assert no_cost.signal_count == 2
    assert no_cost.long_count == 1
    assert no_cost.short_count == 1
    assert no_cost.flat_count == 1
    assert no_cost.gross_mean_return == pytest.approx(0.01)
    assert no_cost.net_mean_return == pytest.approx(0.01)
    assert normal_cost.round_turn_cost_bps == pytest.approx(5.0)
    assert normal_cost.net_mean_return == pytest.approx((0.0195 + 0.0095 + 0.0) / 3)
    assert {warning.warning_code for warning in result.warning_records} == {
        "COST_SCENARIO_ASSUMPTION_REQUIRES_REVIEW"
    }
    assert result.summary_parquet_path.exists()
    assert result.summary_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()

    written = pd.read_parquet(result.summary_parquet_path)
    assert set(written["scenario_id"]) == {"no_cost", "normal_cost"}


def test_build_cf_cost_sensitivity_rejects_negative_cost(tmp_path: Path) -> None:
    score_path = _write_scores(
        tmp_path,
        [_score(date(2024, 1, 1), raw_score=0.5, snapshot_id="score_long")],
    )
    forward_path = _write_forward_returns(
        tmp_path,
        [_forward_return(date(2024, 1, 1), forward_return=0.02, snapshot_id="ret_long")],
    )

    with pytest.raises(ResearchWorkbenchError, match="non-negative"):
        build_cf_cost_sensitivity(
            start=date(2024, 1, 1),
            end=date(2024, 1, 1),
            horizons=(1,),
            score_path=score_path,
            forward_return_path=forward_path,
            scenario_cost_bps={"bad_cost": -1.0},
            output_dir=tmp_path / "costs",
            report_output_dir=tmp_path / "reports",
        )


def _write_scores(tmp_path: Path, rows: list[ResearchMultifactorScoreDailyRow]) -> Path:
    path = tmp_path / "scores" / "CF_2024-01-01_2024-01-03_multifactor_score_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_forward_returns(tmp_path: Path, rows: list[ResearchForwardReturnDailyRow]) -> Path:
    path = tmp_path / "returns" / "CF_2024-01-01_2024-01-03_forward_return_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _score(
    trade_date: date,
    *,
    raw_score: float,
    snapshot_id: str,
) -> ResearchMultifactorScoreDailyRow:
    return ResearchMultifactorScoreDailyRow(
        run_id="r17_score_test",
        score_id="cf_equal_weight_v1",
        score_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_score=raw_score,
        processed_score=None,
        factor_count=2,
        input_factor_ids=["mom_20_v1", "carry_nf_v1"],
        score_rule_version="equal_weight_multifactor_v1",
        input_snapshot_ids=[snapshot_id],
    )


def _forward_return(
    trade_date: date,
    *,
    forward_return: float,
    snapshot_id: str,
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
        input_snapshot_ids=[snapshot_id],
    )
