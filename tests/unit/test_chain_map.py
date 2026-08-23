from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import ChainMapError
from cotton_factor.core import (
    build_chain_map,
    build_contract_master,
    build_trading_calendar,
    load_core_quote_daily_csv,
)
from cotton_factor.core.schemas import CoreQuoteDailyRow

QUOTE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
)


def test_chain_map_uses_official_calendar_and_ltd_guard_fallback() -> None:
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

    result = build_chain_map(
        quotes=load_core_quote_daily_csv(QUOTE_FIXTURE),
        contracts=contract_result.contracts,
        calendar=calendar_result.calendar,
        product_code="CF",
        ltd_buffer_days=2,
    )

    assert [row.mapped_contract for row in result.rows] == [
        "CF401",
        "CF401",
        "CF405",
        "CF405",
    ]
    assert [row.switch_reason for row in result.rows] == [
        "initial_highest_open_interest",
        "unchanged",
        "ltd_guard_fallback",
        "unchanged",
    ]
    assert all(row.signal_object_id == "CF.C1" for row in result.rows)
    assert all(row.roll_rule_version == "roll_placeholder_v1" for row in result.rows)


def test_chain_map_liquidity_fallback_is_explicit() -> None:
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
    quotes = [
        CoreQuoteDailyRow(
            source_snapshot_id="raw_quote_1",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 9),
            volume=0,
            open_interest=3000,
        ),
        CoreQuoteDailyRow(
            source_snapshot_id="raw_quote_1",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF405",
            trade_date=date(2024, 1, 9),
            volume=1,
            open_interest=1000,
        ),
    ]

    result = build_chain_map(
        quotes=quotes,
        contracts=contract_result.contracts,
        calendar=calendar_result.calendar,
        product_code="CF",
        min_volume=1,
    )

    assert result.rows[0].mapped_contract == "CF405"
    assert result.rows[0].switch_reason == "liquidity_fallback"


def test_chain_map_fails_when_all_candidates_blocked() -> None:
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
    quotes = [
        CoreQuoteDailyRow(
            source_snapshot_id="raw_quote_1",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 9),
            volume=0,
            open_interest=3000,
        )
    ]

    with pytest.raises(ChainMapError, match="no eligible contract"):
        build_chain_map(
            quotes=quotes,
            contracts=contract_result.contracts,
            calendar=calendar_result.calendar,
            product_code="CF",
            min_volume=1,
        )


def test_chain_map_can_restrict_cf_to_010509_main_cycle() -> None:
    calendar_result = build_trading_calendar(
        start=date(2024, 1, 1),
        end=date(2025, 12, 31),
        exchange="CZCE",
    )
    contracts = []
    for year in (2024, 2025):
        contracts.extend(
            build_contract_master(
                product_code="CF",
                year=year,
                trading_dates=calendar_result.calendar.trading_dates,
            ).contracts
        )
    trade_date = date(2024, 8, 6)
    quotes = [
        CoreQuoteDailyRow(
            source_snapshot_id=f"raw_{contract}",
            exchange="CZCE",
            product_code="CF",
            contract_code=contract,
            trade_date=trade_date,
            volume=volume,
            open_interest=open_interest,
        )
        for contract, volume, open_interest in (
            ("CF409", 100, 1_000),
            ("CF411", 500, 10_000),
            ("CF501", 300, 5_000),
        )
    ]

    result = build_chain_map(
        quotes=quotes,
        contracts=contracts,
        calendar=calendar_result.calendar,
        product_code="CF",
        eligible_delivery_months=(1, 5, 9),
        roll_rule_version="cf_main_cycle_010509_oi_v1",
    )

    assert result.rows[0].mapped_contract == "CF501"
    assert result.rows[0].mapped_contract != "CF411"
    assert result.rows[0].roll_rule_version == "cf_main_cycle_010509_oi_v1"
