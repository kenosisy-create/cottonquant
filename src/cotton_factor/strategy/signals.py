"""R87 baseline signal and target-lot generation."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.core.schemas import (
    BacktestTargetLotDailyRow,
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.strategy.spec import StrategySpec

BASELINE_TARGET_RULE_VERSION = "V5.1_R87_tsmom_target_v1"


@dataclass(frozen=True)
class BaselineTargetBuildResult:
    """Daily baseline targets and observable diagnostics."""

    target_rows: tuple[BacktestTargetLotDailyRow, ...]
    diagnostics: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TsmomSignalSnapshot:
    """One latest-day baseline observation without an assumed execution date."""

    trade_date: date
    target_contract: str
    adjusted_settle: float
    momentum: float
    direction: int
    annualized_sigma: float | None
    target_lots: int
    warning_code: str
    input_snapshot_ids: tuple[str, ...]


def compute_tsmom_signal_snapshot(
    *,
    spec: StrategySpec,
    continuous_rows: list[ResearchContinuousPriceDailyRow],
    quotes: list[CoreQuoteDailyRow],
    trade_date: date,
    target_contract: str,
    multiplier: float,
) -> TsmomSignalSnapshot:
    """Compute one T-day target using only observations at or before T."""
    selected_date = trade_date
    prices = sorted(
        [row for row in continuous_rows if row.trade_date <= selected_date],
        key=lambda row: row.trade_date,
    )
    if not prices or prices[-1].trade_date != selected_date:
        raise StrategyError(f"continuous price missing for {selected_date}")
    momentum_days = int(spec.signal_windows["momentum_days"])
    vol_returns = int(spec.signal_windows["volatility_returns"])
    index = len(prices) - 1
    current = prices[index]
    warning_code = ""
    momentum = 0.0
    sigma: float | None = None
    direction = 0
    target_lots = 0
    if index < max(momentum_days, vol_returns):
        warning_code = "INSUFFICIENT_LOOKBACK"
    else:
        # 从历史序列重放零动量沿用规则，避免最新快照依赖未来或外部状态。
        previous_direction = 0
        for offset in range(momentum_days, index + 1):
            value = (
                prices[offset].adjusted_price
                / prices[offset - momentum_days].adjusted_price
                - 1.0
            )
            if value > 0:
                previous_direction = 1
            elif value < 0:
                previous_direction = -1
        momentum = current.adjusted_price / prices[index - momentum_days].adjusted_price - 1.0
        direction = 1 if momentum > 0 else -1 if momentum < 0 else previous_direction
        log_returns = [
            math.log(prices[offset].adjusted_price / prices[offset - 1].adjusted_price)
            for offset in range(index - vol_returns + 1, index + 1)
        ]
        sigma = statistics.stdev(log_returns) * math.sqrt(252)
        sigma_effective = max(sigma, spec.sizing.vol_floor)
        quote_by_key = {(row.contract_code, row.trade_date): row for row in quotes}
        quote = quote_by_key.get((target_contract, selected_date))
        if quote is None or quote.settle is None:
            raise StrategyError(
                f"signal-day settlement missing for {target_contract} on {selected_date}"
            )
        unsigned_lots = math.floor(
            spec.sizing.capital_base
            * spec.sizing.target_vol
            / sigma_effective
            / (float(quote.settle) * multiplier)
        )
        target_lots = direction * min(unsigned_lots, spec.sizing.max_lots)
    return TsmomSignalSnapshot(
        trade_date=selected_date,
        target_contract=target_contract,
        adjusted_settle=current.adjusted_price,
        momentum=momentum,
        direction=direction,
        annualized_sigma=sigma,
        target_lots=target_lots,
        warning_code=warning_code,
        input_snapshot_ids=tuple(current.input_snapshot_ids),
    )


def build_tsmom_targets(
    *,
    spec: StrategySpec,
    continuous_rows: list[ResearchContinuousPriceDailyRow],
    trade_mappings: list[CoreTradeMappingDailyRow],
    quotes: list[CoreQuoteDailyRow],
    multiplier: float,
    run_id: str,
) -> BaselineTargetBuildResult:
    """Create T-day targets without consuming any T+1 price information."""
    if spec.strategy_type != "baseline_tsmom":
        raise StrategyError("build_tsmom_targets requires a baseline_tsmom spec")
    if multiplier <= 0:
        raise StrategyError("contract multiplier must be positive")
    prices = sorted(continuous_rows, key=lambda row: row.trade_date)
    price_index = {row.trade_date: index for index, row in enumerate(prices)}
    mapping_by_date = {row.trade_date: row for row in trade_mappings}
    quote_by_key = {(row.contract_code, row.trade_date): row for row in quotes}
    if len(mapping_by_date) != len(trade_mappings):
        raise StrategyError("trade mapping contains duplicate signal dates")

    momentum_days = int(spec.signal_windows["momentum_days"])
    vol_returns = int(spec.signal_windows["volatility_returns"])
    previous_direction = 0
    targets: list[BacktestTargetLotDailyRow] = []
    diagnostics: list[dict[str, object]] = []
    warnings: list[str] = []

    for mapping in sorted(trade_mappings, key=lambda row: row.trade_date):
        index = price_index.get(mapping.trade_date)
        if index is None:
            raise StrategyError(f"continuous price missing for {mapping.trade_date}")
        current = prices[index]
        enough_history = index >= max(momentum_days, vol_returns)
        momentum = 0.0
        sigma: float | None = None
        direction = 0
        target_lots = 0
        warning_code = ""

        if not enough_history:
            warning_code = "INSUFFICIENT_LOOKBACK"
        else:
            prior = prices[index - momentum_days]
            momentum = current.adjusted_price / prior.adjusted_price - 1.0
            direction = 1 if momentum > 0 else -1 if momentum < 0 else previous_direction
            log_returns = [
                math.log(prices[offset].adjusted_price / prices[offset - 1].adjusted_price)
                for offset in range(index - vol_returns + 1, index + 1)
            ]
            sigma = statistics.stdev(log_returns) * math.sqrt(252)
            sigma_effective = max(sigma, spec.sizing.vol_floor)
            if mapping.is_blocked:
                warning_code = mapping.block_reason or "MAPPING_BLOCKED"
                direction = 0
            else:
                assert mapping.target_contract is not None
                signal_quote = quote_by_key.get((mapping.target_contract, mapping.trade_date))
                if signal_quote is None or signal_quote.settle is None:
                    raise StrategyError(
                        f"signal-day settlement missing for {mapping.target_contract} "
                        f"on {mapping.trade_date}"
                    )
                unsigned_lots = math.floor(
                    spec.sizing.capital_base
                    * spec.sizing.target_vol
                    / sigma_effective
                    / (float(signal_quote.settle) * multiplier)
                )
                unsigned_lots = min(unsigned_lots, spec.sizing.max_lots)
                target_lots = direction * unsigned_lots
            previous_direction = direction or previous_direction

        if warning_code:
            warnings.append(f"{mapping.trade_date}: {warning_code}")
        snapshot_ids = _snapshot_ids(
            current.input_snapshot_ids,
            [mapping.source_snapshot_id],
        )
        targets.append(
            BacktestTargetLotDailyRow(
                run_id=run_id,
                strategy_id=spec.spec_key,
                product_code="CF",
                universe="CF_MAIN",
                signal_object_id=spec.signal_object,
                trade_date=mapping.trade_date,
                execution_date=mapping.execution_date,
                target_contract=mapping.target_contract,
                target_lots=target_lots,
                score=momentum,
                is_blocked=mapping.is_blocked,
                block_reason=mapping.block_reason,
                execution_eligible=mapping.execution_eligible,
                target_rule_version=BASELINE_TARGET_RULE_VERSION,
                input_snapshot_ids=snapshot_ids,
            )
        )
        diagnostics.append(
            {
                "trade_date": mapping.trade_date,
                "execution_date": mapping.execution_date,
                "mapped_contract": mapping.target_contract,
                "adjusted_settle": current.adjusted_price,
                "momentum": momentum,
                "direction": direction,
                "annualized_sigma": sigma,
                "target_lots": target_lots,
                "warning_code": warning_code,
            }
        )
    return BaselineTargetBuildResult(
        target_rows=tuple(targets),
        diagnostics=tuple(diagnostics),
        warnings=tuple(sorted(set(warnings))),
    )


def _snapshot_ids(*groups: list[str]) -> list[str]:
    values: list[str] = []
    for group in groups:
        for value in group:
            if value not in values:
                values.append(value)
    if not values:
        raise StrategyError("strategy target requires input snapshot lineage")
    return values
