"""Open-interest pressure factor implementation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import cast

from cotton_factor.common.exceptions import FactorError
from cotton_factor.core.schemas import CoreChainMapDailyRow, CoreQuoteDailyRow
from cotton_factor.research.factor_base import (
    FactorDefinition,
    FactorInputBundle,
    FactorObservation,
    FactorResult,
    build_factor_rows,
    load_factor_registry,
    validate_factor_dependencies,
)

OI_PRESSURE_FACTOR_ID = "oi_pressure_v1"
DEFAULT_SIGNAL_OBJECT_ID = "CF.C1"
DEFAULT_UNIVERSE = "CF_MAIN"


def compute_oi_pressure_factor(
    *,
    inputs: FactorInputBundle,
    run_id: str,
    product_code: str,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = DEFAULT_SIGNAL_OBJECT_ID,
    definition: FactorDefinition | None = None,
) -> FactorResult:
    """Compute price-return-weighted open-interest pressure."""
    factor_definition = definition or load_factor_registry().get(OI_PRESSURE_FACTOR_ID)
    validate_factor_dependencies(factor_definition, inputs)

    quotes = cast(Sequence[CoreQuoteDailyRow], inputs.rows("core_quote_daily"))
    chain_rows = cast(Sequence[CoreChainMapDailyRow], inputs.rows("core_chain_map_daily"))
    product = product_code.upper()
    quote_by_key = _quote_by_contract_date(quotes=quotes, product_code=product)
    previous_quote_by_key = _previous_quote_by_contract_date(
        quotes=quotes,
        product_code=product,
    )

    warnings: list[str] = []
    observations: list[FactorObservation] = []
    for chain_row in sorted(chain_rows, key=lambda row: row.trade_date):
        if chain_row.product_code != product or chain_row.signal_object_id != signal_object_id:
            continue

        current_quote = quote_by_key.get((chain_row.mapped_contract, chain_row.trade_date))
        if current_quote is None:
            warnings.append(
                f"{chain_row.trade_date}: mapped quote missing for {chain_row.mapped_contract}"
            )
            continue
        previous_quote = previous_quote_by_key.get(
            (chain_row.mapped_contract, chain_row.trade_date)
        )
        if previous_quote is None:
            continue
        _validate_quote_values(current=current_quote, previous=previous_quote)

        assert current_quote.settle is not None
        assert current_quote.open_interest is not None
        assert previous_quote.settle is not None
        assert previous_quote.open_interest is not None

        settle_return = current_quote.settle / previous_quote.settle - 1
        oi_change_ratio = (
            current_quote.open_interest - previous_quote.open_interest
        ) / previous_quote.open_interest

        # OI pressure 只用 T 日及历史同合约 quote；换月时没有历史腿则跳过，避免拼接未来信息。
        observations.append(
            FactorObservation(
                signal_object_id=chain_row.signal_object_id,
                trade_date=chain_row.trade_date,
                raw_value=settle_return * oi_change_ratio,
                processed_value=None,
                input_snapshot_ids=_unique_snapshot_ids(
                    [chain_row.source_snapshot_id],
                    [previous_quote.source_snapshot_id],
                    [current_quote.source_snapshot_id],
                ),
            )
        )

    if not observations:
        warnings.append(f"{factor_definition.factor_id}: no rows after prior-quote matching")

    return FactorResult(
        definition=factor_definition,
        rows=build_factor_rows(
            definition=factor_definition,
            run_id=run_id,
            product_code=product,
            universe=universe,
            observations=observations,
        ),
        warnings=_unique_warnings(warnings),
    )


def _quote_by_contract_date(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    product_code: str,
) -> dict[tuple[str, date], CoreQuoteDailyRow]:
    result: dict[tuple[str, date], CoreQuoteDailyRow] = {}
    duplicates: list[tuple[str, date]] = []
    for quote in quotes:
        if quote.product_code != product_code:
            continue
        key = (quote.contract_code, quote.trade_date)
        if key in result:
            duplicates.append(key)
        result[key] = quote
    if not result:
        raise FactorError(f"no quotes found for product {product_code}")
    if duplicates:
        raise FactorError(f"duplicate quote rows for {duplicates}")
    return result


def _previous_quote_by_contract_date(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    product_code: str,
) -> dict[tuple[str, date], CoreQuoteDailyRow]:
    grouped: dict[str, list[CoreQuoteDailyRow]] = {}
    for quote in quotes:
        if quote.product_code == product_code:
            grouped.setdefault(quote.contract_code, []).append(quote)

    result: dict[tuple[str, date], CoreQuoteDailyRow] = {}
    for contract_code, contract_quotes in grouped.items():
        previous: CoreQuoteDailyRow | None = None
        for quote in sorted(contract_quotes, key=lambda row: row.trade_date):
            if previous is not None:
                result[(contract_code, quote.trade_date)] = previous
            previous = quote
    return result


def _validate_quote_values(
    *,
    current: CoreQuoteDailyRow,
    previous: CoreQuoteDailyRow,
) -> None:
    if current.settle is None:
        raise FactorError(f"{current.trade_date}: current settle missing for OI pressure")
    if current.open_interest is None:
        raise FactorError(f"{current.trade_date}: current open_interest missing")
    if previous.settle is None or previous.settle <= 0:
        raise FactorError(f"{current.trade_date}: previous settle must be > 0")
    if previous.open_interest is None or previous.open_interest <= 0:
        raise FactorError(f"{current.trade_date}: previous open_interest must be > 0")


def _unique_snapshot_ids(*snapshot_groups: Sequence[str]) -> tuple[str, ...]:
    values: list[str] = []
    for group in snapshot_groups:
        for snapshot_id in group:
            if snapshot_id not in values:
                values.append(snapshot_id)
    return tuple(values)


def _unique_warnings(warnings: Sequence[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values
