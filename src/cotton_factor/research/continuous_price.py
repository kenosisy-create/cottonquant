"""Continuous price builder for research signal objects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cotton_factor.common.exceptions import ContinuousPriceError
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreQuoteDailyRow,
    ResearchContinuousPriceDailyRow,
)

DEFAULT_CONTINUOUS_RULE_VERSION = "continuous_back_adjust_additive_v1"
SUPPORTED_PRICE_FIELDS = {"open", "close", "settle"}


@dataclass(frozen=True)
class ContinuousPriceBuildResult:
    """Continuous price generation output."""

    rows: list[ResearchContinuousPriceDailyRow]
    warnings: list[str]


def build_continuous_price(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    chain_rows: Sequence[CoreChainMapDailyRow],
    product_code: str,
    signal_object_id: str = "CF.C1",
    price_field: str = "settle",
    continuous_rule_version: str = DEFAULT_CONTINUOUS_RULE_VERSION,
) -> ContinuousPriceBuildResult:
    """Build research continuous prices from core quotes and chain map rows."""
    if price_field not in SUPPORTED_PRICE_FIELDS:
        allowed = ", ".join(sorted(SUPPORTED_PRICE_FIELDS))
        raise ContinuousPriceError(f"unsupported price_field {price_field!r}; expected {allowed}")

    product = product_code.upper()
    quote_by_key = {
        (quote.contract_code, quote.trade_date): quote
        for quote in quotes
        if quote.product_code == product
    }
    if not quote_by_key:
        raise ContinuousPriceError(f"no quotes found for product {product}")

    rows: list[ResearchContinuousPriceDailyRow] = []
    warnings: list[str] = []
    previous_contract: str | None = None
    cumulative_adjustment = 0.0

    for chain_row in sorted(chain_rows, key=lambda row: row.trade_date):
        if chain_row.product_code != product or chain_row.signal_object_id != signal_object_id:
            continue

        quote = quote_by_key.get((chain_row.mapped_contract, chain_row.trade_date))
        if quote is None:
            raise ContinuousPriceError(
                f"{chain_row.trade_date}: quote missing for {chain_row.mapped_contract}"
            )

        raw_price = _price_value(quote=quote, price_field=price_field)
        adjustment = 0.0
        roll_from_contract: str | None = None
        roll_to_contract: str | None = None
        roll_gap: float | None = None
        extra_input_snapshot_ids: list[str] = []
        is_roll = previous_contract is not None and previous_contract != chain_row.mapped_contract

        if is_roll:
            previous_quote = quote_by_key.get((previous_contract, chain_row.trade_date))
            if previous_quote is None:
                raise ContinuousPriceError(
                    f"{chain_row.trade_date}: previous contract quote missing for "
                    f"{previous_contract}"
                )
            previous_price = _price_value(quote=previous_quote, price_field=price_field)
            roll_gap = raw_price - previous_price
            adjustment = -roll_gap
            cumulative_adjustment += adjustment
            roll_from_contract = previous_contract
            roll_to_contract = chain_row.mapped_contract
            extra_input_snapshot_ids.append(previous_quote.source_snapshot_id)

        adjusted_price = raw_price + cumulative_adjustment
        if adjusted_price < 0:
            raise ContinuousPriceError(
                f"{chain_row.trade_date}: adjusted price is negative after roll adjustment"
            )

        # 连续价格是研究衍生信号对象，只能用于信号和因子；订单层必须继续使用 D9 trade mapping。
        rows.append(
            ResearchContinuousPriceDailyRow(
                product_code=product,
                signal_object_id=signal_object_id,
                trade_date=chain_row.trade_date,
                mapped_contract=chain_row.mapped_contract,
                price_field=price_field,
                raw_price=raw_price,
                adjusted_price=adjusted_price,
                adjustment=adjustment,
                cumulative_adjustment=cumulative_adjustment,
                is_roll=is_roll,
                roll_from_contract=roll_from_contract,
                roll_to_contract=roll_to_contract,
                roll_gap=roll_gap,
                chain_switch_reason=chain_row.switch_reason,
                continuous_rule_version=continuous_rule_version,
                input_snapshot_ids=_input_snapshot_ids(
                    chain_row=chain_row,
                    quote=quote,
                    extra_snapshot_ids=extra_input_snapshot_ids,
                ),
            )
        )
        previous_contract = chain_row.mapped_contract

    if not rows:
        raise ContinuousPriceError("continuous price produced no rows")
    return ContinuousPriceBuildResult(rows=rows, warnings=warnings)


def _price_value(*, quote: CoreQuoteDailyRow, price_field: str) -> float:
    value = getattr(quote, price_field)
    if value is None:
        raise ContinuousPriceError(
            f"{quote.trade_date}: {price_field} price missing for {quote.contract_code}"
        )
    return float(value)


def _input_snapshot_ids(
    *,
    chain_row: CoreChainMapDailyRow,
    quote: CoreQuoteDailyRow,
    extra_snapshot_ids: Sequence[str],
) -> list[str]:
    # chain row 与 quote 可能来自同一 raw snapshot；这里去重但保留稳定顺序，方便后续审计。
    values = [chain_row.source_snapshot_id, quote.source_snapshot_id, *extra_snapshot_ids]
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values
