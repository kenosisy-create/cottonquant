"""Continuous chain mapping for signal objects."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cotton_factor.common.exceptions import ChainMapError
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
)
from cotton_factor.core.trading_calendar import TradingCalendar


@dataclass(frozen=True)
class ChainMapBuildResult:
    """Chain map generation output."""

    rows: list[CoreChainMapDailyRow]
    warnings: list[str]


@dataclass(frozen=True)
class _Candidate:
    quote: CoreQuoteDailyRow
    contract: CoreContractMasterRow
    is_ltd_blocked: bool
    has_liquidity: bool


def build_chain_map(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    contracts: Sequence[CoreContractMasterRow],
    calendar: TradingCalendar,
    product_code: str,
    signal_object_id: str = "CF.C1",
    roll_rule_version: str = "roll_placeholder_v1",
    ltd_buffer_days: int = 0,
    min_volume: int = 1,
) -> ChainMapBuildResult:
    """Build `core_chain_map_daily` rows from normalized daily quotes."""
    if ltd_buffer_days < 0:
        raise ChainMapError("ltd_buffer_days must be >= 0")
    if min_volume < 0:
        raise ChainMapError("min_volume must be >= 0")

    product = product_code.upper()
    contract_by_code = {
        contract.contract_code: contract
        for contract in contracts
        if contract.product_code == product
    }
    if not contract_by_code:
        raise ChainMapError(f"no contracts found for product {product}")

    quotes_by_date = _quotes_by_date(quotes=quotes, product_code=product)
    previous_contract: str | None = None
    rows: list[CoreChainMapDailyRow] = []
    warnings: list[str] = []

    for trade_date in sorted(quotes_by_date):
        candidates = _rank_candidates(
            quotes=quotes_by_date[trade_date],
            contract_by_code=contract_by_code,
            calendar=calendar,
            ltd_buffer_days=ltd_buffer_days,
            min_volume=min_volume,
        )
        if not candidates:
            warnings.append(f"{trade_date}: no known contracts in quotes")
            continue

        selected = next((candidate for candidate in candidates if _is_eligible(candidate)), None)
        if selected is None:
            raise ChainMapError(f"{trade_date}: no eligible contract after LTD/liquidity filters")

        reason = _switch_reason(
            selected=selected,
            ranked_candidates=candidates,
            previous_contract=previous_contract,
        )
        rows.append(
            CoreChainMapDailyRow(
                source_snapshot_id=selected.quote.source_snapshot_id,
                exchange=selected.quote.exchange,
                product_code=product,
                signal_object_id=signal_object_id,
                trade_date=trade_date,
                mapped_contract=selected.quote.contract_code,
                chain_rank=1,
                switch_reason=reason,
                roll_rule_version=roll_rule_version,
            )
        )
        previous_contract = selected.quote.contract_code

    if not rows:
        raise ChainMapError("chain map produced no rows")
    return ChainMapBuildResult(rows=rows, warnings=warnings)


def load_core_quote_daily_csv(fixture_path: Path) -> list[CoreQuoteDailyRow]:
    """Load normalized core quote rows from a CSV fixture."""
    if not fixture_path.exists() or not fixture_path.is_file():
        raise ChainMapError(f"quote fixture not found: {fixture_path}")

    with fixture_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "source_snapshot_id",
            "exchange",
            "product_code",
            "contract_code",
            "trade_date",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ChainMapError(f"quote fixture missing columns: {sorted(missing)}")
        return [CoreQuoteDailyRow(**_coerce_quote_row(row)) for row in reader]


def _quotes_by_date(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    product_code: str,
) -> dict[date, list[CoreQuoteDailyRow]]:
    grouped: dict[date, list[CoreQuoteDailyRow]] = {}
    for quote in quotes:
        if quote.product_code != product_code:
            continue
        grouped.setdefault(quote.trade_date, []).append(quote)
    if not grouped:
        raise ChainMapError(f"no quotes found for product {product_code}")
    return grouped


def _rank_candidates(
    *,
    quotes: Iterable[CoreQuoteDailyRow],
    contract_by_code: dict[str, CoreContractMasterRow],
    calendar: TradingCalendar,
    ltd_buffer_days: int,
    min_volume: int,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for quote in quotes:
        contract = contract_by_code.get(quote.contract_code)
        if contract is None:
            continue
        candidates.append(
            _Candidate(
                quote=quote,
                contract=contract,
                is_ltd_blocked=_is_ltd_blocked(
                    trade_date=quote.trade_date,
                    contract=contract,
                    calendar=calendar,
                    ltd_buffer_days=ltd_buffer_days,
                ),
                has_liquidity=(quote.volume or 0) >= min_volume,
            )
        )

    # 主力选择先按持仓量，再按成交量；这里不做收益判断，避免把研究逻辑混进 core mapping。
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.quote.open_interest or -1,
            candidate.quote.volume or -1,
            candidate.quote.contract_code,
        ),
        reverse=True,
    )


def _is_ltd_blocked(
    *,
    trade_date: date,
    contract: CoreContractMasterRow,
    calendar: TradingCalendar,
    ltd_buffer_days: int,
) -> bool:
    if contract.last_trade_date is None:
        return False

    threshold = contract.last_trade_date
    for _ in range(ltd_buffer_days):
        try:
            threshold = calendar.prev_trade_date(threshold)
        except Exception as exc:
            raise ChainMapError(
                f"cannot compute LTD buffer for {contract.contract_code}: {exc}"
            ) from exc
    return trade_date >= threshold


def _is_eligible(candidate: _Candidate) -> bool:
    return candidate.has_liquidity and not candidate.is_ltd_blocked


def _switch_reason(
    *,
    selected: _Candidate,
    ranked_candidates: Sequence[_Candidate],
    previous_contract: str | None,
) -> str:
    if previous_contract == selected.quote.contract_code:
        return "unchanged"

    top = ranked_candidates[0]
    if previous_contract is None and top.quote.contract_code == selected.quote.contract_code:
        return "initial_highest_open_interest"
    if top.is_ltd_blocked and top.quote.contract_code != selected.quote.contract_code:
        return "ltd_guard_fallback"
    if not top.has_liquidity and top.quote.contract_code != selected.quote.contract_code:
        return "liquidity_fallback"
    return "open_interest_roll"


def _coerce_quote_row(row: dict[str, str]) -> dict[str, object]:
    coerced: dict[str, object] = {
        "source_snapshot_id": row["source_snapshot_id"],
        "exchange": row["exchange"],
        "product_code": row["product_code"],
        "contract_code": row["contract_code"],
        "trade_date": row["trade_date"],
    }
    for field_name in ("open", "high", "low", "close", "settle", "pre_settle", "turnover"):
        value = row.get(field_name, "")
        if value != "":
            coerced[field_name] = float(value)
    for field_name in ("volume", "open_interest"):
        value = row.get(field_name, "")
        if value != "":
            coerced[field_name] = int(value)
    if row.get("quote_status"):
        coerced["quote_status"] = row["quote_status"]
    return coerced
