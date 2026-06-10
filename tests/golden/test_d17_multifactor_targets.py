from __future__ import annotations

from datetime import date

import pytest

from cotton_factor.backtest import build_target_lots_from_scores, run_daily_backtest
from cotton_factor.core.schemas import (
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchFactorValueDailyRow,
)
from cotton_factor.research import build_equal_weight_scores


def test_equal_weight_scores_and_target_lots_golden_path() -> None:
    score_result = build_equal_weight_scores(
        factor_rows=[
            _factor_row("mom_20_v1", date(2024, 1, 1), raw_value=0.4),
            _factor_row("carry_nf_v1", date(2024, 1, 1), raw_value=0.2),
            _factor_row("mom_20_v1", date(2024, 1, 2), raw_value=-0.6),
            _factor_row("carry_nf_v1", date(2024, 1, 2), raw_value=-0.2),
        ],
        run_id="score_run_d17",
        product_code="CF",
        factor_ids=["carry_nf_v1", "mom_20_v1"],
    )

    assert score_result.warnings == []
    assert [row.raw_score for row in score_result.rows] == pytest.approx([0.3, -0.4])
    assert score_result.rows[0].input_factor_ids == ["carry_nf_v1", "mom_20_v1"]
    assert score_result.rows[0].input_snapshot_ids == [
        "raw_carry_nf_v1_20240101",
        "raw_mom_20_v1_20240101",
    ]

    target_result = build_target_lots_from_scores(
        score_rows=score_result.rows,
        trade_mappings=[
            _mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2)),
            _mapping(
                date(2024, 1, 2),
                execution_date=date(2024, 1, 3),
                is_blocked=True,
                target_contract=None,
            ),
        ],
        run_id="target_run_d17",
        product_code="CF",
        base_lots=2,
    )

    assert [row.target_lots for row in target_result.rows] == [2, 0]
    assert target_result.rows[0].target_contract == "CF401"
    assert target_result.rows[1].is_blocked is True
    assert target_result.rows[1].block_reason == "golden_block"
    assert "target blocked" in target_result.warnings[0]

    backtest_result = run_daily_backtest(
        target_lot_rows=target_result.rows,
        quotes=[_quote(date(2024, 1, 2), settle=100), _quote(date(2024, 1, 3), settle=110)],
        contracts=[_contract("CF401")],
        run_id="backtest_run_d17",
        product_code="CF",
    )

    assert [order.order_lots for order in backtest_result.orders] == [2]
    assert backtest_result.fills[0].target_contract == "CF401"
    assert backtest_result.blocked_signals[0].trade_date == date(2024, 1, 2)
    assert backtest_result.equity_curve[0].total_equity == 0


def test_equal_weight_scores_skip_dates_with_missing_required_factors() -> None:
    result = build_equal_weight_scores(
        factor_rows=[
            _factor_row("mom_20_v1", date(2024, 1, 1), raw_value=0.4),
            _factor_row("carry_nf_v1", date(2024, 1, 2), raw_value=0.2),
            _factor_row("mom_20_v1", date(2024, 1, 2), raw_value=0.6),
        ],
        run_id="score_run_d17",
        product_code="CF",
        factor_ids=["carry_nf_v1", "mom_20_v1"],
    )

    assert len(result.rows) == 1
    assert result.rows[0].trade_date == date(2024, 1, 2)
    assert "missing factors" in result.warnings[0]


def test_equal_weight_scores_can_average_available_factors_when_allowed() -> None:
    result = build_equal_weight_scores(
        factor_rows=[
            _factor_row("mom_20_v1", date(2024, 1, 1), raw_value=0.4),
        ],
        run_id="score_run_d17",
        product_code="CF",
        factor_ids=["carry_nf_v1", "mom_20_v1"],
        require_all_factors=False,
    )

    assert len(result.rows) == 1
    assert result.rows[0].factor_count == 1
    assert result.rows[0].raw_score == pytest.approx(0.4)


def _factor_row(
    factor_id: str,
    trade_date: date,
    *,
    raw_value: float,
) -> ResearchFactorValueDailyRow:
    return ResearchFactorValueDailyRow(
        run_id="factor_run_d17",
        factor_id=factor_id,
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        input_snapshot_ids=[f"raw_{factor_id}_{trade_date:%Y%m%d}"],
    )


def _mapping(
    trade_date: date,
    *,
    execution_date: date,
    is_blocked: bool = False,
    target_contract: str | None = "CF401",
) -> CoreTradeMappingDailyRow:
    return CoreTradeMappingDailyRow(
        source_snapshot_id=f"raw_mapping_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        execution_date=execution_date,
        target_contract=target_contract,
        is_blocked=is_blocked,
        block_reason="golden_block" if is_blocked else None,
        execution_eligible=not is_blocked,
        mapping_rule_version="trade_mapping_v1",
    )


def _quote(trade_date: date, *, settle: float) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"raw_quote_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=trade_date,
        settle=settle,
        volume=100,
        open_interest=1000,
    )


def _contract(contract_code: str) -> CoreContractMasterRow:
    return CoreContractMasterRow(
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        contract_month="202401",
        delivery_year=2024,
        delivery_month=1,
        multiplier=5,
        tick_size=None,
        first_trade_date=None,
        last_trade_date=date(2024, 1, 15),
        rule_version_id="CZCE.CF.contract_rules.v1",
        source_config_version="products.v1.CF",
    )
