from __future__ import annotations

from datetime import date

from cotton_factor.backtest import run_daily_backtest
from cotton_factor.core.schemas import (
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchFactorValueDailyRow,
)


def test_daily_backtest_uses_t_plus_one_real_contract_fills_and_blocked_records() -> None:
    result = run_daily_backtest(
        factor_rows=[
            _factor_row(date(2024, 1, 1), raw_value=1),
            _factor_row(date(2024, 1, 2), raw_value=-1),
            _factor_row(date(2024, 1, 3), raw_value=1),
        ],
        trade_mappings=[
            _mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2)),
            _mapping(date(2024, 1, 2), execution_date=date(2024, 1, 3)),
            _mapping(
                date(2024, 1, 3),
                execution_date=date(2024, 1, 4),
                is_blocked=True,
                target_contract=None,
            ),
        ],
        quotes=[
            _quote(date(2024, 1, 2), settle=100),
            _quote(date(2024, 1, 3), settle=110),
            _quote(date(2024, 1, 4), settle=120),
        ],
        contracts=[_contract("CF401")],
        run_id="backtest_run_d16",
        product_code="CF",
    )

    assert [order.target_contract for order in result.orders] == ["CF401", "CF401"]
    assert [order.signal_object_id for order in result.orders] == ["CF.C1", "CF.C1"]
    assert [order.order_lots for order in result.orders] == [1, -2]
    assert [fill.fill_price for fill in result.fills] == [100, 110]
    assert [fill.notional for fill in result.fills] == [500, 1100]
    assert all(fill.target_contract != "CF.C1" for fill in result.fills)

    assert len(result.costs) == 2
    assert all(cost.model_id == "cost_placeholder_v1" for cost in result.costs)
    assert all(cost.total_cost == 0 for cost in result.costs)
    assert any("TODO_REQUIRES_HUMAN_REVIEW" in warning for warning in result.warnings)

    assert len(result.blocked_signals) == 1
    assert result.blocked_signals[0].block_reason == "golden_block"
    assert "signal blocked" in result.warnings[-1]

    assert [point.execution_date for point in result.equity_curve] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    assert [point.total_equity for point in result.equity_curve] == [0, 50]
    assert result.positions[-1].target_contract == "CF401"
    assert result.positions[-1].lots == -1
    assert result.report_summary()["final_equity"] == 50


def test_daily_backtest_next_open_mode_uses_execution_open_price() -> None:
    result = run_daily_backtest(
        factor_rows=[_factor_row(date(2024, 1, 1), raw_value=1)],
        trade_mappings=[_mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2))],
        quotes=[_quote(date(2024, 1, 2), open_price=101, settle=100)],
        contracts=[_contract("CF401")],
        run_id="backtest_run_d16",
        product_code="CF",
        execution_price_mode="next_open",
    )

    assert result.fills[0].fill_price == 101
    assert result.equity_curve[0].total_equity == 0


def test_daily_backtest_is_reproducible_for_same_inputs() -> None:
    kwargs = {
        "factor_rows": [_factor_row(date(2024, 1, 1), raw_value=1)],
        "trade_mappings": [_mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2))],
        "quotes": [_quote(date(2024, 1, 2), settle=100)],
        "contracts": [_contract("CF401")],
        "run_id": "backtest_run_d16",
        "product_code": "CF",
    }

    assert run_daily_backtest(**kwargs) == run_daily_backtest(**kwargs)


def _factor_row(trade_date: date, *, raw_value: float) -> ResearchFactorValueDailyRow:
    return ResearchFactorValueDailyRow(
        run_id="factor_run_d16",
        factor_id="mom_20_v1",
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        input_snapshot_ids=[f"raw_factor_{trade_date:%Y%m%d}"],
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


def _quote(
    trade_date: date,
    *,
    settle: float,
    open_price: float | None = None,
) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"raw_quote_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=trade_date,
        open=open_price,
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
