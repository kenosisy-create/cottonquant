"""Portfolio helpers for daily backtests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cotton_factor.common.exceptions import BacktestError
from cotton_factor.core.schemas import (
    BacktestTargetLotDailyRow,
    CoreTradeMappingDailyRow,
    ResearchMultifactorScoreDailyRow,
)

DEFAULT_TARGET_LOT_RULE_VERSION = "score_to_target_lot_sign_v1"
DEFAULT_STRATEGY_ID = "cf_equal_weight_v1"
DEFAULT_UNIVERSE = "CF_MAIN"


@dataclass(frozen=True)
class TargetLotBuildResult:
    """Target lot build output."""

    rows: list[BacktestTargetLotDailyRow]
    warnings: list[str]


def signal_to_target_lots(*, signal_value: float, base_lots: int) -> int:
    """Convert one scalar signal into a fixed-lot MVP target."""
    if signal_value > 0:
        return base_lots
    if signal_value < 0:
        return -base_lots
    return 0


def build_target_lots_from_scores(
    *,
    score_rows: Sequence[ResearchMultifactorScoreDailyRow],
    trade_mappings: Sequence[CoreTradeMappingDailyRow],
    run_id: str,
    product_code: str,
    strategy_id: str = DEFAULT_STRATEGY_ID,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = "CF.C1",
    base_lots: int = 1,
    target_rule_version: str = DEFAULT_TARGET_LOT_RULE_VERSION,
    use_processed_score: bool = True,
) -> TargetLotBuildResult:
    """Convert signal-object scores into real-contract target lots."""
    if base_lots <= 0:
        raise BacktestError("base_lots must be > 0")
    if not run_id:
        raise BacktestError("run_id is required for target lots")

    product = product_code.upper()
    mapping_by_date = _mapping_by_date(
        trade_mappings=trade_mappings,
        product_code=product,
        signal_object_id=signal_object_id,
    )
    rows: list[BacktestTargetLotDailyRow] = []
    warnings: list[str] = []

    for score_row in sorted(score_rows, key=lambda row: row.trade_date):
        if score_row.product_code != product or score_row.universe != universe:
            continue
        if score_row.signal_object_id != signal_object_id:
            continue

        mapping = mapping_by_date.get(score_row.trade_date)
        if mapping is None:
            warnings.append(f"{score_row.trade_date}: trade mapping missing; target skipped")
            continue

        score_value = _score_value(row=score_row, use_processed_score=use_processed_score)
        if mapping.is_blocked:
            rows.append(
                BacktestTargetLotDailyRow(
                    run_id=run_id,
                    strategy_id=strategy_id,
                    product_code=product,
                    universe=universe,
                    signal_object_id=signal_object_id,
                    trade_date=score_row.trade_date,
                    execution_date=mapping.execution_date,
                    target_contract=None,
                    target_lots=0,
                    score=score_value,
                    is_blocked=True,
                    block_reason=mapping.block_reason or "blocked_without_reason",
                    execution_eligible=False,
                    target_rule_version=target_rule_version,
                    input_snapshot_ids=_unique_snapshot_ids(
                        score_row.input_snapshot_ids,
                        [mapping.source_snapshot_id],
                    ),
                )
            )
            warnings.append(f"{score_row.trade_date}: target blocked: {mapping.block_reason}")
            continue

        if mapping.target_contract is None:
            raise BacktestError(
                f"{score_row.trade_date}: unblocked mapping missing target_contract"
            )

        # 目标手数开始进入交易对象层，因此这里只允许 D9 产出的真实 target_contract。
        rows.append(
            BacktestTargetLotDailyRow(
                run_id=run_id,
                strategy_id=strategy_id,
                product_code=product,
                universe=universe,
                signal_object_id=signal_object_id,
                trade_date=score_row.trade_date,
                execution_date=mapping.execution_date,
                target_contract=mapping.target_contract,
                target_lots=signal_to_target_lots(signal_value=score_value, base_lots=base_lots),
                score=score_value,
                is_blocked=False,
                execution_eligible=True,
                target_rule_version=target_rule_version,
                input_snapshot_ids=_unique_snapshot_ids(
                    score_row.input_snapshot_ids,
                    [mapping.source_snapshot_id],
                ),
            )
        )

    if not rows:
        warnings.append("target lot build produced no rows")
    return TargetLotBuildResult(rows=rows, warnings=_unique_warnings(warnings))


def portfolio_market_value(
    *,
    positions: Mapping[str, int],
    mark_prices: Mapping[str, float],
    multipliers: Mapping[str, float],
) -> float:
    """Mark current positions to market."""
    value = 0.0
    for contract_code, lots in positions.items():
        if lots == 0:
            continue
        value += lots * mark_prices[contract_code] * multipliers[contract_code]
    return value


def _mapping_by_date(
    *,
    trade_mappings: Sequence[CoreTradeMappingDailyRow],
    product_code: str,
    signal_object_id: str,
) -> dict[object, CoreTradeMappingDailyRow]:
    result: dict[object, CoreTradeMappingDailyRow] = {}
    duplicates: list[object] = []
    for row in trade_mappings:
        if row.product_code != product_code or row.signal_object_id != signal_object_id:
            continue
        if row.trade_date in result:
            duplicates.append(row.trade_date)
        result[row.trade_date] = row
    if duplicates:
        raise BacktestError(f"duplicate trade mappings for trade dates {duplicates}")
    return result


def _score_value(*, row: ResearchMultifactorScoreDailyRow, use_processed_score: bool) -> float:
    value = (
        row.processed_score
        if use_processed_score and row.processed_score is not None
        else row.raw_score
    )
    return float(value)


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
