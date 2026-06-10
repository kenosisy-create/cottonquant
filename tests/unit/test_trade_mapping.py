from __future__ import annotations

from datetime import date
from pathlib import Path

from cotton_factor.core import (
    build_chain_map,
    build_contract_master,
    build_trade_mapping,
    build_trading_calendar,
    load_core_quote_daily_csv,
)
from cotton_factor.core.schemas import CoreChainMapDailyRow, CoreSettlementParamDailyRow

QUOTE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
)


def _calendar_and_contracts():
    calendar_result = build_trading_calendar(
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        exchange="CZCE",
    )
    contract_result = build_contract_master(
        product_code="CF",
        year=2024,
        trading_dates=calendar_result.calendar.trading_dates,
    )
    return calendar_result.calendar, contract_result.contracts


def test_trade_mapping_uses_real_contracts_and_t_plus_one_execution() -> None:
    calendar, contracts = _calendar_and_contracts()
    chain_result = build_chain_map(
        quotes=load_core_quote_daily_csv(QUOTE_FIXTURE),
        contracts=contracts,
        calendar=calendar,
        product_code="CF",
        ltd_buffer_days=2,
    )

    result = build_trade_mapping(
        chain_rows=chain_result.rows,
        contracts=contracts,
        calendar=calendar,
        product_code="CF",
        ltd_buffer_days=2,
    )

    assert [row.execution_date for row in result.rows] == [
        date(2024, 1, 10),
        date(2024, 1, 11),
        date(2024, 1, 12),
        date(2024, 1, 15),
    ]
    assert [row.target_contract for row in result.rows] == [
        "CF401",
        None,
        "CF405",
        "CF405",
    ]
    assert result.rows[1].is_blocked is True
    assert result.rows[1].block_reason == "ltd_buffer_execution_block"
    assert all(row.signal_object_id == "CF.C1" for row in result.rows)
    assert all(row.target_contract != "CF.C1" for row in result.rows if row.target_contract)


def test_trade_mapping_blocks_settlement_status_on_execution_date() -> None:
    calendar, contracts = _calendar_and_contracts()
    chain_row = CoreChainMapDailyRow(
        source_snapshot_id="raw_quote_1",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=date(2024, 1, 9),
        mapped_contract="CF401",
        switch_reason="initial_highest_open_interest",
        roll_rule_version="roll_placeholder_v1",
    )
    settlement_row = CoreSettlementParamDailyRow(
        source_snapshot_id="raw_settlement_1",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=date(2024, 1, 10),
        trading_status="halted",
    )

    result = build_trade_mapping(
        chain_rows=[chain_row],
        contracts=contracts,
        calendar=calendar,
        product_code="CF",
        settlement_rows=[settlement_row],
    )

    assert result.rows[0].is_blocked is True
    assert result.rows[0].target_contract is None
    assert result.rows[0].block_reason == "settlement_status_halted"
    assert result.rows[0].execution_eligible is False


def test_trade_mapping_blocks_unknown_contract_instead_of_using_signal_object() -> None:
    calendar, contracts = _calendar_and_contracts()
    chain_row = CoreChainMapDailyRow(
        source_snapshot_id="raw_quote_1",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=date(2024, 1, 9),
        mapped_contract="CF999",
        switch_reason="fixture_unknown_contract",
        roll_rule_version="roll_placeholder_v1",
    )

    result = build_trade_mapping(
        chain_rows=[chain_row],
        contracts=contracts,
        calendar=calendar,
        product_code="CF",
    )

    assert result.rows[0].is_blocked is True
    assert result.rows[0].target_contract is None
    assert result.rows[0].block_reason == "unknown_target_contract"
    assert "not in contract master" in result.warnings[0]
