"""Forward return construction for single factor evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from cotton_factor.common.exceptions import ForwardReturnError
from cotton_factor.core.schemas import (
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchForwardReturnDailyRow,
)

DEFAULT_FORWARD_RETURN_RULE_VERSION = "forward_return_real_contract_tplus1_v1"
SUPPORTED_RETURN_PRICE_FIELDS = {"open", "close", "settle"}
DEFAULT_UNIVERSE = "CF_MAIN"


@dataclass(frozen=True)
class ForwardReturnBuildResult:
    """Forward return build output."""

    rows: list[ResearchForwardReturnDailyRow]
    warnings: list[str]


def build_forward_returns(
    *,
    trade_mappings: Sequence[CoreTradeMappingDailyRow],
    quotes: Sequence[CoreQuoteDailyRow],
    run_id: str,
    product_code: str,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = "CF.C1",
    horizon: int = 1,
    entry_price_field: str = "settle",
    exit_price_field: str = "settle",
    return_rule_version: str = DEFAULT_FORWARD_RETURN_RULE_VERSION,
) -> ForwardReturnBuildResult:
    """Build forward returns from T signals to future real-contract quote outcomes."""
    if horizon <= 0:
        raise ForwardReturnError("horizon must be >= 1")
    _validate_price_field(entry_price_field, field_name="entry_price_field")
    _validate_price_field(exit_price_field, field_name="exit_price_field")

    product = product_code.upper()
    quote_series_by_contract = _quote_series_by_contract(quotes=quotes, product_code=product)
    quote_by_contract_date = {
        (quote.contract_code, quote.trade_date): quote
        for series in quote_series_by_contract.values()
        for quote in series
    }

    rows: list[ResearchForwardReturnDailyRow] = []
    warnings: list[str] = []
    for mapping in sorted(trade_mappings, key=lambda row: row.trade_date):
        if mapping.product_code != product or mapping.signal_object_id != signal_object_id:
            continue
        if mapping.is_blocked:
            warnings.append(
                f"{mapping.trade_date}: trade mapping is blocked: {mapping.block_reason}"
            )
            continue
        if mapping.target_contract is None:
            warnings.append(f"{mapping.trade_date}: trade mapping missing target_contract")
            continue

        entry_quote = quote_by_contract_date.get(
            (mapping.target_contract, mapping.execution_date)
        )
        if entry_quote is None:
            warnings.append(
                f"{mapping.trade_date}: entry quote missing for "
                f"{mapping.target_contract} on {mapping.execution_date}"
            )
            continue

        exit_quote = _exit_quote(
            contract_series=quote_series_by_contract.get(mapping.target_contract, []),
            execution_date=mapping.execution_date,
            horizon=horizon,
        )
        if exit_quote is None:
            warnings.append(
                f"{mapping.trade_date}: exit quote missing for {mapping.target_contract} "
                f"after horizon {horizon}"
            )
            continue

        entry_price = _price_value(quote=entry_quote, price_field=entry_price_field)
        exit_price = _price_value(quote=exit_quote, price_field=exit_price_field)

        # forward return 是评估标签，不是交易回测；这里仍然坚持 T 信号、T+1 真实合约入场。
        rows.append(
            ResearchForwardReturnDailyRow(
                run_id=run_id,
                product_code=product,
                universe=universe,
                signal_object_id=mapping.signal_object_id,
                trade_date=mapping.trade_date,
                execution_date=mapping.execution_date,
                exit_date=exit_quote.trade_date,
                horizon=horizon,
                target_contract=mapping.target_contract,
                entry_price_field=entry_price_field,
                exit_price_field=exit_price_field,
                entry_price=entry_price,
                exit_price=exit_price,
                forward_return=exit_price / entry_price - 1,
                return_rule_version=return_rule_version,
                input_snapshot_ids=_unique_snapshot_ids(
                    [mapping.source_snapshot_id],
                    [entry_quote.source_snapshot_id],
                    [exit_quote.source_snapshot_id],
                ),
            )
        )

    if not rows:
        warnings.append("forward returns produced no rows")
    return ForwardReturnBuildResult(rows=rows, warnings=_unique_warnings(warnings))


def _quote_series_by_contract(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    product_code: str,
) -> dict[str, list[CoreQuoteDailyRow]]:
    grouped: dict[str, list[CoreQuoteDailyRow]] = {}
    seen_keys: set[tuple[str, date]] = set()
    duplicates: list[tuple[str, date]] = []
    for quote in quotes:
        if quote.product_code != product_code:
            continue
        key = (quote.contract_code, quote.trade_date)
        if key in seen_keys:
            duplicates.append(key)
        seen_keys.add(key)
        grouped.setdefault(quote.contract_code, []).append(quote)

    if not grouped:
        raise ForwardReturnError(f"no quotes found for product {product_code}")
    if duplicates:
        raise ForwardReturnError(f"duplicate quote rows for {duplicates}")

    return {
        contract_code: sorted(series, key=lambda row: row.trade_date)
        for contract_code, series in grouped.items()
    }


def _exit_quote(
    *,
    contract_series: Sequence[CoreQuoteDailyRow],
    execution_date: date,
    horizon: int,
) -> CoreQuoteDailyRow | None:
    for index, quote in enumerate(contract_series):
        if quote.trade_date == execution_date:
            exit_index = index + horizon
            if exit_index >= len(contract_series):
                return None
            return contract_series[exit_index]
    return None


def _price_value(*, quote: CoreQuoteDailyRow, price_field: str) -> float:
    value = getattr(quote, price_field)
    if value is None:
        raise ForwardReturnError(
            f"{quote.trade_date}: {price_field} price missing for {quote.contract_code}"
        )
    if value <= 0:
        raise ForwardReturnError(
            f"{quote.trade_date}: {price_field} price must be > 0 for {quote.contract_code}"
        )
    return float(value)


def _validate_price_field(price_field: str, *, field_name: str) -> None:
    if price_field not in SUPPORTED_RETURN_PRICE_FIELDS:
        allowed = ", ".join(sorted(SUPPORTED_RETURN_PRICE_FIELDS))
        raise ForwardReturnError(f"{field_name} {price_field!r} is unsupported; expected {allowed}")


def _unique_snapshot_ids(*snapshot_groups: Sequence[str]) -> list[str]:
    values: list[str] = []
    for group in snapshot_groups:
        for snapshot_id in group:
            if snapshot_id not in values:
                values.append(snapshot_id)
    return values


def _unique_warnings(warnings: Sequence[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values
