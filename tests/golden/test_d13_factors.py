from __future__ import annotations

from datetime import date

import pytest

from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
)
from cotton_factor.research import (
    FactorInputBundle,
    compute_curve_slope_factor,
    compute_oi_pressure_factor,
)


def test_curve_slope_golden_value_uses_chain_map_and_next_far_leg() -> None:
    result = compute_curve_slope_factor(
        inputs=FactorInputBundle(
            tables={
                "core_quote_daily": [
                    _quote("CF401", trade_date=date(2024, 1, 9), settle=100),
                    _quote("CF405", trade_date=date(2024, 1, 9), settle=105),
                    _quote("CF409", trade_date=date(2024, 1, 9), settle=120),
                ],
                "core_chain_map_daily": [
                    _chain_row("CF401", trade_date=date(2024, 1, 9)),
                ],
                "core_contract_master": [
                    _contract("CF401", month=1, last_trade_date=date(2024, 1, 15)),
                    _contract("CF405", month=5, last_trade_date=date(2024, 5, 15)),
                    _contract("CF409", month=9, last_trade_date=date(2024, 9, 15)),
                ],
            }
        ),
        run_id="factor_run_d13",
        product_code="CF",
    )

    assert result.definition.factor_id == "curve_slope_v1"
    assert result.warnings == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.trade_date == date(2024, 1, 9)
    assert row.signal_object_id == "CF.C1"
    assert row.raw_value == pytest.approx(0.05)
    assert row.input_snapshot_ids == ["raw_chain_20240109", "raw_quote_CF401", "raw_quote_CF405"]


def test_curve_slope_exposes_human_review_warning_when_ltd_is_missing() -> None:
    result = compute_curve_slope_factor(
        inputs=FactorInputBundle(
            tables={
                "core_quote_daily": [
                    _quote("CF401", trade_date=date(2024, 1, 9), settle=100),
                    _quote("CF405", trade_date=date(2024, 1, 9), settle=105),
                ],
                "core_chain_map_daily": [
                    _chain_row("CF401", trade_date=date(2024, 1, 9)),
                ],
                "core_contract_master": [
                    _contract("CF401", month=1, last_trade_date=None),
                    _contract("CF405", month=5, last_trade_date=None),
                ],
            }
        ),
        run_id="factor_run_d13",
        product_code="CF",
    )

    assert len(result.rows) == 1
    assert any("TODO_REQUIRES_HUMAN_REVIEW" in warning for warning in result.warnings)


def test_oi_pressure_golden_value_uses_mapped_contract_history() -> None:
    result = compute_oi_pressure_factor(
        inputs=FactorInputBundle(
            tables={
                "core_quote_daily": [
                    _quote(
                        "CF401",
                        trade_date=date(2024, 1, 9),
                        settle=100,
                        open_interest=1000,
                        snapshot_id="raw_quote_prev",
                    ),
                    _quote(
                        "CF401",
                        trade_date=date(2024, 1, 10),
                        settle=102,
                        open_interest=1100,
                        snapshot_id="raw_quote_current",
                    ),
                ],
                "core_chain_map_daily": [
                    _chain_row("CF401", trade_date=date(2024, 1, 9)),
                    _chain_row("CF401", trade_date=date(2024, 1, 10)),
                ],
            }
        ),
        run_id="factor_run_d13",
        product_code="CF",
    )

    assert result.definition.factor_id == "oi_pressure_v1"
    assert result.warnings == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.trade_date == date(2024, 1, 10)
    assert row.raw_value == pytest.approx(0.002)
    assert row.input_snapshot_ids == [
        "raw_chain_20240110",
        "raw_quote_prev",
        "raw_quote_current",
    ]


def test_oi_pressure_warns_when_prior_quote_matching_produces_no_rows() -> None:
    result = compute_oi_pressure_factor(
        inputs=FactorInputBundle(
            tables={
                "core_quote_daily": [
                    _quote("CF401", trade_date=date(2024, 1, 9), settle=100),
                ],
                "core_chain_map_daily": [
                    _chain_row("CF401", trade_date=date(2024, 1, 9)),
                ],
            }
        ),
        run_id="factor_run_d13",
        product_code="CF",
    )

    assert result.rows == []
    assert "no rows after prior-quote matching" in result.warnings[0]


def _quote(
    contract_code: str,
    *,
    trade_date: date,
    settle: float,
    open_interest: int = 1000,
    snapshot_id: str | None = None,
) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=snapshot_id or f"raw_quote_{contract_code}",
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        trade_date=trade_date,
        settle=settle,
        volume=100,
        open_interest=open_interest,
    )


def _chain_row(contract_code: str, *, trade_date: date) -> CoreChainMapDailyRow:
    return CoreChainMapDailyRow(
        source_snapshot_id=f"raw_chain_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        mapped_contract=contract_code,
        chain_rank=1,
        switch_reason="golden_fixture",
        roll_rule_version="roll_placeholder_v1",
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
