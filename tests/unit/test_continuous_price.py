from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import ContinuousPriceError
from cotton_factor.core import (
    build_chain_map,
    build_contract_master,
    build_trading_calendar,
    load_core_quote_daily_csv,
)
from cotton_factor.core.schemas import CoreChainMapDailyRow
from cotton_factor.research import build_continuous_price

QUOTE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
)


def _quotes_chain_and_contracts():
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
    quotes = load_core_quote_daily_csv(QUOTE_FIXTURE)
    chain_result = build_chain_map(
        quotes=quotes,
        contracts=contract_result.contracts,
        calendar=calendar_result.calendar,
        product_code="CF",
        ltd_buffer_days=2,
    )
    return quotes, chain_result.rows


def test_continuous_price_back_adjusts_roll_gap_and_keeps_trace() -> None:
    quotes, chain_rows = _quotes_chain_and_contracts()

    result = build_continuous_price(
        quotes=quotes,
        chain_rows=chain_rows,
        product_code="CF",
    )

    assert [row.mapped_contract for row in result.rows] == [
        "CF401",
        "CF401",
        "CF405",
        "CF405",
    ]
    assert [row.raw_price for row in result.rows] == [15540, 15550, 15760, 15770]
    assert [row.adjusted_price for row in result.rows] == [15540, 15550, 15560, 15570]
    assert [row.cumulative_adjustment for row in result.rows] == [0, 0, -200, -200]

    roll_row = result.rows[2]
    assert roll_row.is_roll is True
    assert roll_row.roll_from_contract == "CF401"
    assert roll_row.roll_to_contract == "CF405"
    assert roll_row.roll_gap == 200
    assert roll_row.chain_switch_reason == "ltd_guard_fallback"
    assert roll_row.input_snapshot_ids == ["raw_quote_chain_1"]


def test_continuous_price_can_use_close_field() -> None:
    quotes, chain_rows = _quotes_chain_and_contracts()

    result = build_continuous_price(
        quotes=quotes,
        chain_rows=chain_rows,
        product_code="CF",
        price_field="close",
    )

    assert result.rows[0].price_field == "close"
    assert [row.adjusted_price for row in result.rows] == [15550, 15560, 15570, 15580]


def test_continuous_price_fails_when_mapped_quote_is_missing() -> None:
    quotes, _chain_rows = _quotes_chain_and_contracts()
    bad_chain_row = CoreChainMapDailyRow(
        source_snapshot_id="raw_quote_1",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=date(2024, 1, 9),
        mapped_contract="CF999",
        switch_reason="fixture_missing_quote",
        roll_rule_version="roll_placeholder_v1",
    )

    with pytest.raises(ContinuousPriceError, match="quote missing"):
        build_continuous_price(
            quotes=quotes,
            chain_rows=[bad_chain_row],
            product_code="CF",
        )
