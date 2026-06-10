"""Signal-object to tradable-contract mapping."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cotton_factor.common.exceptions import TradeMappingError
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreContractMasterRow,
    CoreSettlementParamDailyRow,
    CoreTradeMappingDailyRow,
)
from cotton_factor.core.trading_calendar import TradingCalendar

DEFAULT_MAPPING_RULE_VERSION = "trade_mapping_v1"
BLOCKING_TRADING_STATUSES = {"halted", "limit_only"}


@dataclass(frozen=True)
class TradeMappingBuildResult:
    """Trade mapping generation output."""

    rows: list[CoreTradeMappingDailyRow]
    warnings: list[str]


def build_trade_mapping(
    *,
    chain_rows: Sequence[CoreChainMapDailyRow],
    contracts: Sequence[CoreContractMasterRow],
    calendar: TradingCalendar,
    product_code: str,
    signal_object_id: str = "CF.C1",
    settlement_rows: Sequence[CoreSettlementParamDailyRow] | None = None,
    mapping_rule_version: str = DEFAULT_MAPPING_RULE_VERSION,
    ltd_buffer_days: int = 0,
) -> TradeMappingBuildResult:
    """Build `core_trade_mapping_daily` rows for T signal and T+1 execution."""
    if ltd_buffer_days < 0:
        raise TradeMappingError("ltd_buffer_days must be >= 0")

    product = product_code.upper()
    contract_by_code = {
        contract.contract_code: contract
        for contract in contracts
        if contract.product_code == product
    }
    if not contract_by_code:
        raise TradeMappingError(f"no contracts found for product {product}")

    settlement_by_key = _settlement_by_contract_date(settlement_rows or ())
    rows: list[CoreTradeMappingDailyRow] = []
    warnings: list[str] = []

    for chain_row in sorted(chain_rows, key=lambda row: row.trade_date):
        if chain_row.product_code != product or chain_row.signal_object_id != signal_object_id:
            continue

        try:
            execution_date = calendar.next_trade_date(chain_row.trade_date)
        except Exception as exc:
            raise TradeMappingError(
                f"{chain_row.trade_date}: no T+1 trading date for trade mapping: {exc}"
            ) from exc

        contract = contract_by_code.get(chain_row.mapped_contract)
        if contract is None:
            rows.append(
                _blocked_row(
                    chain_row=chain_row,
                    execution_date=execution_date,
                    reason="unknown_target_contract",
                    mapping_rule_version=mapping_rule_version,
                )
            )
            warnings.append(
                f"{chain_row.trade_date}: mapped contract {chain_row.mapped_contract} "
                "is not in contract master"
            )
            continue

        block_reason = _execution_block_reason(
            contract=contract,
            execution_date=execution_date,
            calendar=calendar,
            ltd_buffer_days=ltd_buffer_days,
            settlement_row=settlement_by_key.get((contract.contract_code, execution_date)),
        )
        if block_reason is not None:
            rows.append(
                _blocked_row(
                    chain_row=chain_row,
                    execution_date=execution_date,
                    reason=block_reason,
                    mapping_rule_version=mapping_rule_version,
                )
            )
            continue

        rows.append(
            CoreTradeMappingDailyRow(
                source_snapshot_id=chain_row.source_snapshot_id,
                exchange=chain_row.exchange,
                product_code=product,
                signal_object_id=chain_row.signal_object_id,
                trade_date=chain_row.trade_date,
                execution_date=execution_date,
                target_contract=contract.contract_code,
                is_blocked=False,
                execution_eligible=True,
                mapping_rule_version=mapping_rule_version,
            )
        )

    if not rows:
        raise TradeMappingError("trade mapping produced no rows")
    return TradeMappingBuildResult(rows=rows, warnings=warnings)


def load_core_chain_map_daily_csv(fixture_path: Path) -> list[CoreChainMapDailyRow]:
    """Load core chain-map rows from a CSV fixture."""
    if not fixture_path.exists() or not fixture_path.is_file():
        raise TradeMappingError(f"chain map fixture not found: {fixture_path}")

    with fixture_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "source_snapshot_id",
            "exchange",
            "product_code",
            "signal_object_id",
            "trade_date",
            "mapped_contract",
            "switch_reason",
            "roll_rule_version",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise TradeMappingError(f"chain map fixture missing columns: {sorted(missing)}")
        return [CoreChainMapDailyRow(**_coerce_chain_row(row)) for row in reader]


def load_core_settlement_param_daily_csv(
    fixture_path: Path,
) -> list[CoreSettlementParamDailyRow]:
    """Load normalized settlement parameter rows from a CSV fixture."""
    if not fixture_path.exists() or not fixture_path.is_file():
        raise TradeMappingError(f"settlement fixture not found: {fixture_path}")

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
            raise TradeMappingError(f"settlement fixture missing columns: {sorted(missing)}")
        return [CoreSettlementParamDailyRow(**_coerce_settlement_row(row)) for row in reader]


def _execution_block_reason(
    *,
    contract: CoreContractMasterRow,
    execution_date: date,
    calendar: TradingCalendar,
    ltd_buffer_days: int,
    settlement_row: CoreSettlementParamDailyRow | None,
) -> str | None:
    # D9 是订单层前的最后一道保护：即使 chain map 没切走，也不能让执行落到 LTD 缓冲区内。
    if contract.last_trade_date is not None:
        threshold = contract.last_trade_date
        for _ in range(ltd_buffer_days):
            try:
                threshold = calendar.prev_trade_date(threshold)
            except Exception as exc:
                raise TradeMappingError(
                    f"cannot compute LTD buffer for {contract.contract_code}: {exc}"
                ) from exc
        if execution_date >= threshold:
            return "ltd_buffer_execution_block"

    if settlement_row is not None and settlement_row.trading_status in BLOCKING_TRADING_STATUSES:
        # 结算/交易状态事实来自 core settlement；这里仅消费事实，不解释交易所原始字段。
        return f"settlement_status_{settlement_row.trading_status}"

    return None


def _blocked_row(
    *,
    chain_row: CoreChainMapDailyRow,
    execution_date: date,
    reason: str,
    mapping_rule_version: str,
) -> CoreTradeMappingDailyRow:
    if execution_date <= chain_row.trade_date:
        raise TradeMappingError(
            f"{chain_row.trade_date}: blocked trade mapping still requires a T+1 execution date"
        )
    return CoreTradeMappingDailyRow(
        source_snapshot_id=chain_row.source_snapshot_id,
        exchange=chain_row.exchange,
        product_code=chain_row.product_code,
        signal_object_id=chain_row.signal_object_id,
        trade_date=chain_row.trade_date,
        execution_date=execution_date,
        target_contract=None,
        is_blocked=True,
        block_reason=reason,
        execution_eligible=False,
        mapping_rule_version=mapping_rule_version,
    )


def _settlement_by_contract_date(
    settlement_rows: Sequence[CoreSettlementParamDailyRow],
) -> dict[tuple[str, date], CoreSettlementParamDailyRow]:
    grouped: dict[tuple[str, date], CoreSettlementParamDailyRow] = {}
    for row in settlement_rows:
        grouped[(row.contract_code, row.trade_date)] = row
    return grouped


def _coerce_chain_row(row: dict[str, str]) -> dict[str, object]:
    coerced: dict[str, object] = {
        "source_snapshot_id": row["source_snapshot_id"],
        "exchange": row["exchange"],
        "product_code": row["product_code"],
        "signal_object_id": row["signal_object_id"],
        "trade_date": row["trade_date"],
        "mapped_contract": row["mapped_contract"],
        "switch_reason": row["switch_reason"],
        "roll_rule_version": row["roll_rule_version"],
    }
    if row.get("chain_rank"):
        coerced["chain_rank"] = int(row["chain_rank"])
    return coerced


def _coerce_settlement_row(row: dict[str, str]) -> dict[str, object]:
    coerced: dict[str, object] = {
        "source_snapshot_id": row["source_snapshot_id"],
        "exchange": row["exchange"],
        "product_code": row["product_code"],
        "contract_code": row["contract_code"],
        "trade_date": row["trade_date"],
    }
    for field_name in ("limit_up", "limit_down", "margin_rate_long", "margin_rate_short"):
        value = row.get(field_name, "")
        if value != "":
            coerced[field_name] = float(value)
    if row.get("trading_status"):
        coerced["trading_status"] = row["trading_status"]
    if row.get("settlement_status"):
        coerced["settlement_status"] = row["settlement_status"]
    return coerced
