"""T+1 execution helpers for daily backtests."""

from __future__ import annotations

from typing import Literal

from cotton_factor.common.exceptions import BacktestError
from cotton_factor.core.schemas import CoreQuoteDailyRow

ExecutionPriceMode = Literal["next_open", "next_settle"]

EXECUTION_PRICE_FIELD_BY_MODE: dict[ExecutionPriceMode, str] = {
    "next_open": "open",
    "next_settle": "settle",
}


def execution_price_field(mode: ExecutionPriceMode) -> str:
    """Return quote field used by an execution price mode."""
    try:
        return EXECUTION_PRICE_FIELD_BY_MODE[mode]
    except KeyError as exc:
        allowed = ", ".join(sorted(EXECUTION_PRICE_FIELD_BY_MODE))
        raise BacktestError(
            f"unsupported execution_price_mode {mode!r}; expected {allowed}"
        ) from exc


def quote_price(*, quote: CoreQuoteDailyRow, price_field: str) -> float:
    """Read a positive price from a normalized quote row."""
    value = getattr(quote, price_field)
    if value is None:
        raise BacktestError(
            f"{quote.trade_date}: {price_field} price missing for {quote.contract_code}"
        )
    if value <= 0:
        raise BacktestError(
            f"{quote.trade_date}: {price_field} price must be > 0 for {quote.contract_code}"
        )
    return float(value)


def order_side(order_lots: int) -> str:
    """Return side label for a signed lot delta."""
    if order_lots > 0:
        return "buy"
    if order_lots < 0:
        return "sell"
    return "flat"
