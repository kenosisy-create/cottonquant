from __future__ import annotations

from datetime import date, timedelta

import pytest

from cotton_factor.core.schemas import (
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.research import (
    FactorInputBundle,
    compute_carry_factor,
    compute_momentum_factor,
)


def test_momentum_20_golden_value_uses_adjusted_continuous_prices() -> None:
    result = compute_momentum_factor(
        inputs=FactorInputBundle(
            tables={"research_continuous_price_daily": _continuous_price_rows()}
        ),
        run_id="factor_run_d12",
        product_code="CF",
    )

    assert result.definition.factor_id == "mom_20_v1"
    assert result.warnings == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.trade_date == date(2024, 1, 21)
    assert row.signal_object_id == "CF.C1"
    assert row.raw_value == pytest.approx(0.2)
    assert row.processed_value is None
    assert row.input_snapshot_ids == ["raw_quote_0", "raw_quote_20"]


def test_momentum_warns_when_lookback_window_is_not_available() -> None:
    result = compute_momentum_factor(
        inputs=FactorInputBundle(
            tables={"research_continuous_price_daily": _continuous_price_rows()[:20]}
        ),
        run_id="factor_run_d12",
        product_code="CF",
    )

    assert result.rows == []
    assert "need more than 20 rows" in result.warnings[0]


def test_carry_near_far_golden_value_uses_core_quotes_and_contract_master() -> None:
    result = compute_carry_factor(
        inputs=FactorInputBundle(
            tables={
                "core_quote_daily": [
                    _quote("CF401", settle=100, snapshot_id="raw_quote_near"),
                    _quote("CF405", settle=110, snapshot_id="raw_quote_far"),
                ],
                "core_contract_master": [
                    _contract("CF401", month=1, last_trade_date=date(2024, 1, 15)),
                    _contract("CF405", month=5, last_trade_date=date(2024, 5, 15)),
                ],
            }
        ),
        run_id="factor_run_d12",
        product_code="CF",
    )

    assert result.definition.factor_id == "carry_nf_v1"
    assert result.warnings == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.trade_date == date(2024, 1, 9)
    assert row.signal_object_id == "CF.C1"
    assert row.raw_value == pytest.approx((110 / 100 - 1) * (365 / 121))
    assert row.input_snapshot_ids == ["raw_quote_near", "raw_quote_far"]


def test_carry_exposes_human_review_warning_when_ltd_is_missing() -> None:
    result = compute_carry_factor(
        inputs=FactorInputBundle(
            tables={
                "core_quote_daily": [
                    _quote("CF401", settle=100, snapshot_id="raw_quote_near"),
                    _quote("CF405", settle=110, snapshot_id="raw_quote_far"),
                ],
                "core_contract_master": [
                    _contract("CF401", month=1, last_trade_date=None),
                    _contract("CF405", month=5, last_trade_date=None),
                ],
            }
        ),
        run_id="factor_run_d12",
        product_code="CF",
    )

    assert len(result.rows) == 1
    assert any("TODO_REQUIRES_HUMAN_REVIEW" in warning for warning in result.warnings)


def _continuous_price_rows() -> list[ResearchContinuousPriceDailyRow]:
    start = date(2024, 1, 1)
    rows: list[ResearchContinuousPriceDailyRow] = []
    for offset, price in enumerate(range(100, 121)):
        rows.append(
            ResearchContinuousPriceDailyRow(
                product_code="CF",
                signal_object_id="CF.C1",
                trade_date=start + timedelta(days=offset),
                mapped_contract="CF401",
                price_field="settle",
                raw_price=float(price),
                adjusted_price=float(price),
                adjustment=0,
                cumulative_adjustment=0,
                is_roll=False,
                chain_switch_reason="golden_fixture",
                continuous_rule_version="continuous_back_adjust_additive_v1",
                input_snapshot_ids=[f"raw_quote_{offset}"],
            )
        )
    return rows


def _quote(contract_code: str, *, settle: float, snapshot_id: str) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=snapshot_id,
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        trade_date=date(2024, 1, 9),
        settle=settle,
        volume=100,
        open_interest=1000,
    )


def _contract(
    contract_code: str,
    *,
    month: int,
    last_trade_date: date | None,
) -> CoreContractMasterRow:
    return CoreContractMasterRow(
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        contract_month=f"2024{month:02d}",
        delivery_year=2024,
        delivery_month=month,
        multiplier=5,
        tick_size=None,
        first_trade_date=None,
        last_trade_date=last_trade_date,
        rule_version_id="CZCE.CF.contract_rules.v1",
        source_config_version="products.v1.CF",
    )
