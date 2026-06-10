"""Curve slope factor implementation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import cast

from cotton_factor.common.exceptions import FactorError
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
)
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

CURVE_SLOPE_FACTOR_ID = "curve_slope_v1"
DEFAULT_SIGNAL_OBJECT_ID = "CF.C1"
DEFAULT_UNIVERSE = "CF_MAIN"


@dataclass(frozen=True)
class _CurveCandidate:
    quote: CoreQuoteDailyRow
    contract: CoreContractMasterRow
    tenor_date: date


def compute_curve_slope_factor(
    *,
    inputs: FactorInputBundle,
    run_id: str,
    product_code: str,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = DEFAULT_SIGNAL_OBJECT_ID,
    definition: FactorDefinition | None = None,
) -> FactorResult:
    """Compute near/next curve slope for the mapped signal object."""
    factor_definition = definition or load_factor_registry().get(CURVE_SLOPE_FACTOR_ID)
    validate_factor_dependencies(factor_definition, inputs)

    quotes = cast(Sequence[CoreQuoteDailyRow], inputs.rows("core_quote_daily"))
    chain_rows = cast(Sequence[CoreChainMapDailyRow], inputs.rows("core_chain_map_daily"))
    contracts = cast(Sequence[CoreContractMasterRow], inputs.rows("core_contract_master"))
    product = product_code.upper()

    quote_by_key = _quote_by_contract_date(quotes=quotes, product_code=product)
    contract_by_code = {
        contract.contract_code: contract
        for contract in contracts
        if contract.product_code == product
    }
    if not contract_by_code:
        raise FactorError(f"{factor_definition.factor_id}: no contracts for {product}")

    warnings: list[str] = []
    observations: list[FactorObservation] = []
    for chain_row in sorted(chain_rows, key=lambda row: row.trade_date):
        if chain_row.product_code != product or chain_row.signal_object_id != signal_object_id:
            continue

        near_quote = quote_by_key.get((chain_row.mapped_contract, chain_row.trade_date))
        if near_quote is None:
            warnings.append(
                f"{chain_row.trade_date}: mapped quote missing for {chain_row.mapped_contract}"
            )
            continue
        near_contract = contract_by_code.get(chain_row.mapped_contract)
        if near_contract is None:
            warnings.append(
                f"{chain_row.trade_date}: mapped contract missing from master "
                f"{chain_row.mapped_contract}"
            )
            continue

        near_candidate = _CurveCandidate(
            quote=near_quote,
            contract=near_contract,
            tenor_date=_tenor_date(contract=near_contract, warnings=warnings),
        )
        far_candidate = _next_far_candidate(
            trade_date=chain_row.trade_date,
            near_candidate=near_candidate,
            quote_by_key=quote_by_key,
            contract_by_code=contract_by_code,
            warnings=warnings,
        )
        if far_candidate is None:
            warnings.append(
                f"{chain_row.trade_date}: no farther curve leg after "
                f"{chain_row.mapped_contract}"
            )
            continue

        assert near_candidate.quote.settle is not None
        assert far_candidate.quote.settle is not None
        if near_candidate.quote.settle <= 0:
            raise FactorError(f"{chain_row.trade_date}: near settle must be > 0")

        # 曲线斜率是信号对象的研究特征，不能被订单层当作真实可交易合约使用。
        raw_value = far_candidate.quote.settle / near_candidate.quote.settle - 1
        observations.append(
            FactorObservation(
                signal_object_id=chain_row.signal_object_id,
                trade_date=chain_row.trade_date,
                raw_value=raw_value,
                processed_value=None,
                input_snapshot_ids=_unique_snapshot_ids(
                    [chain_row.source_snapshot_id],
                    [near_candidate.quote.source_snapshot_id],
                    [far_candidate.quote.source_snapshot_id],
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


def _next_far_candidate(
    *,
    trade_date: date,
    near_candidate: _CurveCandidate,
    quote_by_key: dict[tuple[str, date], CoreQuoteDailyRow],
    contract_by_code: dict[str, CoreContractMasterRow],
    warnings: list[str],
) -> _CurveCandidate | None:
    candidates: list[_CurveCandidate] = []
    for contract in contract_by_code.values():
        if contract.contract_code == near_candidate.contract.contract_code:
            continue
        tenor_date = _tenor_date(contract=contract, warnings=warnings)
        if tenor_date <= near_candidate.tenor_date:
            continue
        quote = quote_by_key.get((contract.contract_code, trade_date))
        if quote is None or quote.settle is None:
            continue
        candidates.append(
            _CurveCandidate(
                quote=quote,
                contract=contract,
                tenor_date=tenor_date,
            )
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.tenor_date,
            candidate.contract.contract_month,
            candidate.contract.contract_code,
        ),
    )[0]


def _tenor_date(*, contract: CoreContractMasterRow, warnings: list[str]) -> date:
    if contract.last_trade_date is not None:
        return contract.last_trade_date

    warnings.append(
        f"{TODO_REQUIRES_HUMAN_REVIEW}: {contract.contract_code} curve tenor uses "
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
