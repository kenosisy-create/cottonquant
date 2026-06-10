"""Near/far carry factor implementation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import cast

from cotton_factor.common.exceptions import FactorError
from cotton_factor.core.schemas import CoreContractMasterRow, CoreQuoteDailyRow
from cotton_factor.research.factor_base import (
    TODO_REQUIRES_HUMAN_REVIEW,
    FactorDefinition,
    FactorInputBundle,
    FactorObservation,
    FactorResult,
    build_factor_rows,
    load_factor_registry,
    validate_factor_dependencies,
)

CARRY_FACTOR_ID = "carry_nf_v1"
DEFAULT_SIGNAL_OBJECT_ID = "CF.C1"
DEFAULT_UNIVERSE = "CF_MAIN"


@dataclass(frozen=True)
class _CarryCandidate:
    quote: CoreQuoteDailyRow
    contract: CoreContractMasterRow
    tenor_date: date


def compute_carry_factor(
    *,
    inputs: FactorInputBundle,
    run_id: str,
    product_code: str,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = DEFAULT_SIGNAL_OBJECT_ID,
    definition: FactorDefinition | None = None,
) -> FactorResult:
    """Compute annualized near/far settlement carry from normalized core rows."""
    factor_definition = definition or load_factor_registry().get(CARRY_FACTOR_ID)
    validate_factor_dependencies(factor_definition, inputs)

    quotes = cast(Sequence[CoreQuoteDailyRow], inputs.rows("core_quote_daily"))
    contracts = cast(Sequence[CoreContractMasterRow], inputs.rows("core_contract_master"))
    product = product_code.upper()
    contract_by_code = {
        contract.contract_code: contract
        for contract in contracts
        if contract.product_code == product
    }
    if not contract_by_code:
        raise FactorError(f"{factor_definition.factor_id}: no contracts for {product}")

    warnings: list[str] = []
    observations: list[FactorObservation] = []
    quotes_by_date = _quotes_by_date(quotes=quotes, product_code=product)
    for trade_date, date_quotes in sorted(quotes_by_date.items()):
        candidates = _carry_candidates(
            trade_date=trade_date,
            quotes=date_quotes,
            contract_by_code=contract_by_code,
            warnings=warnings,
        )
        if len(candidates) < 2:
            warnings.append(
                f"{factor_definition.factor_id}: {trade_date} has fewer than two carry legs"
            )
            continue

        near, far = candidates[0], candidates[1]
        assert near.quote.settle is not None
        assert far.quote.settle is not None
        if near.quote.settle <= 0:
            raise FactorError(f"{trade_date}: near settle must be > 0 for carry")
        tenor_days = (far.tenor_date - near.tenor_date).days
        if tenor_days <= 0:
            raise FactorError(
                f"{trade_date}: far tenor must be after near tenor for carry"
            )

        # D12 MVP 口径：carry = 远月/近月结算价差收益按合约期限差年化；该口径仍保留人审标记。
        raw_value = (far.quote.settle / near.quote.settle - 1) * (365 / tenor_days)
        observations.append(
            FactorObservation(
                signal_object_id=signal_object_id,
                trade_date=trade_date,
                raw_value=raw_value,
                processed_value=None,
                input_snapshot_ids=_unique_snapshot_ids(
                    [near.quote.source_snapshot_id],
                    [far.quote.source_snapshot_id],
                ),
            )
        )

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


def _quotes_by_date(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    product_code: str,
) -> dict[date, list[CoreQuoteDailyRow]]:
    grouped: dict[date, list[CoreQuoteDailyRow]] = {}
    for quote in quotes:
        if quote.product_code == product_code:
            grouped.setdefault(quote.trade_date, []).append(quote)
    if not grouped:
        raise FactorError(f"no quotes found for product {product_code}")
    return grouped


def _carry_candidates(
    *,
    trade_date: date,
    quotes: Sequence[CoreQuoteDailyRow],
    contract_by_code: dict[str, CoreContractMasterRow],
    warnings: list[str],
) -> list[_CarryCandidate]:
    candidates: list[_CarryCandidate] = []
    for quote in quotes:
        contract = contract_by_code.get(quote.contract_code)
        if contract is None:
            warnings.append(f"{trade_date}: quote contract not in master {quote.contract_code}")
            continue
        if quote.settle is None:
            warnings.append(f"{trade_date}: settle missing for {quote.contract_code}")
            continue
        if not _is_contract_active(contract=contract, trade_date=trade_date):
            continue
        candidates.append(
            _CarryCandidate(
                quote=quote,
                contract=contract,
                tenor_date=_tenor_date(contract=contract, warnings=warnings),
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.tenor_date,
            candidate.contract.contract_month,
            candidate.contract.contract_code,
        ),
    )


def _is_contract_active(*, contract: CoreContractMasterRow, trade_date: date) -> bool:
    if contract.first_trade_date is not None and trade_date < contract.first_trade_date:
        return False
    if contract.last_trade_date is not None and trade_date > contract.last_trade_date:
        return False
    return True


def _tenor_date(*, contract: CoreContractMasterRow, warnings: list[str]) -> date:
    if contract.last_trade_date is not None:
        return contract.last_trade_date

    warnings.append(
        f"{TODO_REQUIRES_HUMAN_REVIEW}: {contract.contract_code} carry tenor uses "
        "delivery-month fallback because last_trade_date is missing"
    )
    return date(contract.delivery_year, contract.delivery_month, 1)


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
