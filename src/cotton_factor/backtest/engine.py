"""Daily backtest engine with T+1 real-contract execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from cotton_factor.backtest.cost_model import CostModel
from cotton_factor.backtest.execution import (
    ExecutionPriceMode,
    execution_price_field,
    order_side,
    quote_price,
)
from cotton_factor.backtest.portfolio import portfolio_market_value, signal_to_target_lots
from cotton_factor.common.exceptions import BacktestError
from cotton_factor.core.schemas import (
    BacktestTargetLotDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchFactorValueDailyRow,
)

DEFAULT_BACKTEST_RULE_VERSION = "daily_backtest_tplus1_fixed_lot_v1"
DEFAULT_STRATEGY_ID = "cf_single_factor_fixed_lot_v1"
DEFAULT_UNIVERSE = "CF_MAIN"


@dataclass(frozen=True)
class BacktestOrder:
    """One intended real-contract order."""

    run_id: str
    strategy_id: str
    product_code: str
    signal_object_id: str
    trade_date: date
    execution_date: date
    target_contract: str
    side: str
    order_lots: int
    target_lots: int
    previous_lots: int
    signal_value: float
    input_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True)
class BacktestFill:
    """One filled real-contract order."""

    run_id: str
    strategy_id: str
    product_code: str
    execution_date: date
    target_contract: str
    side: str
    fill_lots: int
    fill_price: float
    multiplier: float
    notional: float
    input_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True)
class BacktestCost:
    """Cost record for one fill."""

    run_id: str
    strategy_id: str
    execution_date: date
    target_contract: str
    fill_lots: int
    model_id: str
    fee: float
    slippage: float
    impact: float
    total_cost: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class BacktestPosition:
    """Position snapshot after processing an execution date."""

    run_id: str
    strategy_id: str
    execution_date: date
    target_contract: str
    lots: int
    mark_price: float
    multiplier: float
    market_value: float


@dataclass(frozen=True)
class BacktestEquityPoint:
    """Equity snapshot after processing an execution date."""

    run_id: str
    strategy_id: str
    trade_date: date
    execution_date: date
    cash: float
    market_value: float
    total_equity: float
    cumulative_cost: float


@dataclass(frozen=True)
class BacktestBlockedSignal:
    """Blocked signal state retained from trade mapping."""

    run_id: str
    strategy_id: str
    product_code: str
    signal_object_id: str
    trade_date: date
    execution_date: date
    block_reason: str
    signal_value: float
    input_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True)
class _BacktestPlan:
    trade_date: date
    execution_date: date
    signal_object_id: str
    target_contract: str | None
    target_lots: int
    signal_value: float
    is_blocked: bool
    block_reason: str | None
    input_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True)
class DailyBacktestResult:
    """Daily backtest output bundle."""

    run_id: str
    strategy_id: str
    backtest_rule_version: str
    orders: list[BacktestOrder]
    fills: list[BacktestFill]
    costs: list[BacktestCost]
    positions: list[BacktestPosition]
    equity_curve: list[BacktestEquityPoint]
    blocked_signals: list[BacktestBlockedSignal]
    warnings: list[str]

    def report_summary(self) -> dict[str, object]:
        """Return compact summary for the D15 backtest report renderer."""
        final_equity = self.equity_curve[-1].total_equity if self.equity_curve else 0.0
        total_cost = sum(cost.total_cost for cost in self.costs)
        return {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "backtest_rule_version": self.backtest_rule_version,
            "order_count": len(self.orders),
            "fill_count": len(self.fills),
            "blocked_count": len(self.blocked_signals),
            "final_equity": final_equity,
            "total_cost": total_cost,
        }

    def equity_records(self) -> list[dict[str, object]]:
        """Return equity rows suitable for D15 report rendering."""
        return [
            {
                "trade_date": row.trade_date,
                "execution_date": row.execution_date,
                "cash": row.cash,
                "market_value": row.market_value,
                "total_equity": row.total_equity,
                "cumulative_cost": row.cumulative_cost,
            }
            for row in self.equity_curve
        ]

    def trade_records(self) -> list[dict[str, object]]:
        """Return fill rows suitable for D15 report rendering."""
        return [
            {
                "execution_date": row.execution_date,
                "target_contract": row.target_contract,
                "side": row.side,
                "fill_lots": row.fill_lots,
                "fill_price": row.fill_price,
                "notional": row.notional,
            }
            for row in self.fills
        ]


def run_daily_backtest(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow] = (),
    trade_mappings: Sequence[CoreTradeMappingDailyRow] = (),
    target_lot_rows: Sequence[BacktestTargetLotDailyRow] = (),
    quotes: Sequence[CoreQuoteDailyRow],
    contracts: Sequence[CoreContractMasterRow],
    run_id: str,
    product_code: str,
    strategy_id: str = DEFAULT_STRATEGY_ID,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = "CF.C1",
    execution_price_mode: ExecutionPriceMode = "next_settle",
    base_lots: int = 1,
    cost_model: CostModel | None = None,
    backtest_rule_version: str = DEFAULT_BACKTEST_RULE_VERSION,
    use_processed_value: bool = True,
) -> DailyBacktestResult:
    """Run a fixed-lot daily backtest using T+1 trade mapping rows."""
    if base_lots <= 0:
        raise BacktestError("base_lots must be > 0")
    if not run_id:
        raise BacktestError("run_id is required")

    product = product_code.upper()
    price_field = execution_price_field(execution_price_mode)
    active_cost_model = cost_model or CostModel()
    plans = (
        _plans_from_target_lots(
            target_lot_rows=target_lot_rows,
            product_code=product,
            universe=universe,
            signal_object_id=signal_object_id,
        )
        if target_lot_rows
        else _plans_from_factor_rows(
            factor_rows=factor_rows,
            trade_mappings=trade_mappings,
            product_code=product,
            universe=universe,
            signal_object_id=signal_object_id,
            base_lots=base_lots,
            use_processed_value=use_processed_value,
        )
    )
    quote_by_key = _quote_by_contract_date(quotes=quotes, product_code=product)
    multiplier_by_contract = _multiplier_by_contract(contracts=contracts, product_code=product)

    orders: list[BacktestOrder] = []
    fills: list[BacktestFill] = []
    costs: list[BacktestCost] = []
    positions: list[BacktestPosition] = []
    equity_curve: list[BacktestEquityPoint] = []
    blocked_signals: list[BacktestBlockedSignal] = []
    warnings: list[str] = []
    current_positions: dict[str, int] = {}
    cash = 0.0
    cumulative_cost = 0.0

    for plan in sorted(plans, key=lambda item: item.trade_date):
        if plan.is_blocked:
            blocked_signals.append(
                BacktestBlockedSignal(
                    run_id=run_id,
                    strategy_id=strategy_id,
                    product_code=product,
                    signal_object_id=plan.signal_object_id,
                    trade_date=plan.trade_date,
                    execution_date=plan.execution_date,
                    block_reason=plan.block_reason or "blocked_without_reason",
                    signal_value=plan.signal_value,
                    input_snapshot_ids=plan.input_snapshot_ids,
                )
            )
            warnings.append(
                f"{plan.trade_date}: signal blocked for {plan.execution_date}: "
                f"{plan.block_reason}"
            )
            continue

        if plan.target_contract is None:
            raise BacktestError(f"{plan.trade_date}: unblocked plan missing target_contract")

        # D16 执行层只消费 D9 给出的真实合约；连续合约信号对象不能直接落到订单、成交或持仓。
        planned_orders = _orders_for_target(
            run_id=run_id,
            strategy_id=strategy_id,
            product_code=product,
            signal_object_id=plan.signal_object_id,
            trade_date=plan.trade_date,
            execution_date=plan.execution_date,
            target_contract=plan.target_contract,
            signal_value=plan.signal_value,
            target_lots=plan.target_lots,
            current_positions=current_positions,
            input_snapshot_ids=plan.input_snapshot_ids,
        )
        for order in planned_orders:
            quote = quote_by_key.get((order.target_contract, order.execution_date))
            if quote is None:
                warnings.append(
                    f"{plan.trade_date}: execution quote missing for {order.target_contract} "
                    f"on {order.execution_date}; order skipped"
                )
                continue

            fill_price = quote_price(quote=quote, price_field=price_field)
            fill_multiplier = _multiplier(order.target_contract, multiplier_by_contract)
            notional = abs(order.order_lots) * fill_price * fill_multiplier
            estimate = active_cost_model.estimate(order_lots=order.order_lots)
            cost_row = BacktestCost(
                run_id=run_id,
                strategy_id=strategy_id,
                execution_date=order.execution_date,
                target_contract=order.target_contract,
                fill_lots=order.order_lots,
                model_id=estimate.model_id,
                fee=estimate.fee,
                slippage=estimate.slippage,
                impact=estimate.impact,
                total_cost=estimate.total_cost,
                warnings=estimate.warnings,
            )
            fill = BacktestFill(
                run_id=run_id,
                strategy_id=strategy_id,
                product_code=product,
                execution_date=order.execution_date,
                target_contract=order.target_contract,
                side=order.side,
                fill_lots=order.order_lots,
                fill_price=fill_price,
                multiplier=fill_multiplier,
                notional=notional,
                input_snapshot_ids=_unique_snapshot_ids(
                    order.input_snapshot_ids,
                    [quote.source_snapshot_id],
                ),
            )
            orders.append(order)
            fills.append(fill)
            costs.append(cost_row)
            warnings.extend(estimate.warnings)

            current_positions[order.target_contract] = (
                current_positions.get(order.target_contract, 0) + order.order_lots
            )
            cash -= order.order_lots * fill_price * fill_multiplier
            cash -= estimate.total_cost
            cumulative_cost += estimate.total_cost

        mark_prices = _mark_prices(
            positions=current_positions,
            quote_by_key=quote_by_key,
            execution_date=plan.execution_date,
            price_field=price_field,
        )
        market_value = portfolio_market_value(
            positions=current_positions,
            mark_prices=mark_prices,
            multipliers=multiplier_by_contract,
        )
        equity_curve.append(
            BacktestEquityPoint(
                run_id=run_id,
                strategy_id=strategy_id,
                trade_date=plan.trade_date,
                execution_date=plan.execution_date,
                cash=cash,
                market_value=market_value,
                total_equity=cash + market_value,
                cumulative_cost=cumulative_cost,
            )
        )
        for contract_code, lots in sorted(current_positions.items()):
            if lots == 0:
                continue
            position_multiplier = _multiplier(contract_code, multiplier_by_contract)
            positions.append(
                BacktestPosition(
                    run_id=run_id,
                    strategy_id=strategy_id,
                    execution_date=plan.execution_date,
                    target_contract=contract_code,
                    lots=lots,
                    mark_price=mark_prices[contract_code],
                    multiplier=position_multiplier,
                    market_value=lots * mark_prices[contract_code] * position_multiplier,
                )
            )

    if not orders and not blocked_signals:
        warnings.append("daily backtest produced no orders or blocked signals")

    return DailyBacktestResult(
        run_id=run_id,
        strategy_id=strategy_id,
        backtest_rule_version=backtest_rule_version,
        orders=orders,
        fills=fills,
        costs=costs,
        positions=positions,
        equity_curve=equity_curve,
        blocked_signals=blocked_signals,
        warnings=_unique_warnings(warnings),
    )


def _plans_from_target_lots(
    *,
    target_lot_rows: Sequence[BacktestTargetLotDailyRow],
    product_code: str,
    universe: str,
    signal_object_id: str,
) -> list[_BacktestPlan]:
    plans: list[_BacktestPlan] = []
    duplicates: list[date] = []
    seen_dates: set[date] = set()
    for row in target_lot_rows:
        if row.product_code != product_code or row.universe != universe:
            continue
        if row.signal_object_id != signal_object_id:
            continue
        if row.trade_date in seen_dates:
            duplicates.append(row.trade_date)
        seen_dates.add(row.trade_date)
        plans.append(
            _BacktestPlan(
                trade_date=row.trade_date,
                execution_date=row.execution_date,
                signal_object_id=row.signal_object_id,
                target_contract=row.target_contract,
                target_lots=row.target_lots,
                signal_value=row.score,
                is_blocked=row.is_blocked,
                block_reason=row.block_reason,
                input_snapshot_ids=tuple(row.input_snapshot_ids),
            )
        )
    if duplicates:
        raise BacktestError(f"duplicate target lot rows for trade dates {duplicates}")
    if not plans:
        raise BacktestError("no target lot rows found for daily backtest")
    return plans


def _plans_from_factor_rows(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    trade_mappings: Sequence[CoreTradeMappingDailyRow],
    product_code: str,
    universe: str,
    signal_object_id: str,
    base_lots: int,
    use_processed_value: bool,
) -> list[_BacktestPlan]:
    factor_by_key = _factor_by_signal_date(
        factor_rows=factor_rows,
        factor_id=None,
        product_code=product_code,
        universe=universe,
        signal_object_id=signal_object_id,
    )
    mapping_by_key = _mapping_by_signal_date(
        trade_mappings=trade_mappings,
        product_code=product_code,
        signal_object_id=signal_object_id,
    )

    plans: list[_BacktestPlan] = []
    for trade_date in sorted(factor_by_key):
        factor_row = factor_by_key[trade_date]
        mapping = mapping_by_key.get(trade_date)
        if mapping is None:
            continue
        signal_value = _signal_value(factor_row=factor_row, use_processed_value=use_processed_value)
        target_lots = (
            0
            if mapping.is_blocked
            else signal_to_target_lots(signal_value=signal_value, base_lots=base_lots)
        )
        plans.append(
            _BacktestPlan(
                trade_date=trade_date,
                execution_date=mapping.execution_date,
                signal_object_id=mapping.signal_object_id,
                target_contract=mapping.target_contract,
                target_lots=target_lots,
                signal_value=signal_value,
                is_blocked=mapping.is_blocked,
                block_reason=mapping.block_reason,
                input_snapshot_ids=tuple(
                    _unique_snapshot_ids(
                        factor_row.input_snapshot_ids,
                        [mapping.source_snapshot_id],
                    )
                ),
            )
        )
    if not plans:
        raise BacktestError("no executable or blocked signal plans found for daily backtest")
    return plans


def _orders_for_target(
    *,
    run_id: str,
    strategy_id: str,
    product_code: str,
    signal_object_id: str,
    trade_date: date,
    execution_date: date,
    target_contract: str,
    signal_value: float,
    target_lots: int,
    current_positions: Mapping[str, int],
    input_snapshot_ids: Sequence[str],
) -> list[BacktestOrder]:
    orders: list[BacktestOrder] = []
    for contract_code, current_lots in sorted(current_positions.items()):
        if current_lots == 0 or contract_code == target_contract:
            continue
        orders.append(
            _order(
                run_id=run_id,
                strategy_id=strategy_id,
                product_code=product_code,
                signal_object_id=signal_object_id,
                trade_date=trade_date,
                execution_date=execution_date,
                target_contract=contract_code,
                order_lots=-current_lots,
                target_lots=0,
                previous_lots=current_lots,
                signal_value=signal_value,
                input_snapshot_ids=input_snapshot_ids,
            )
        )

    previous_target_lots = current_positions.get(target_contract, 0)
    delta_lots = target_lots - previous_target_lots
    if delta_lots != 0:
        orders.append(
            _order(
                run_id=run_id,
                strategy_id=strategy_id,
                product_code=product_code,
                signal_object_id=signal_object_id,
                trade_date=trade_date,
                execution_date=execution_date,
                target_contract=target_contract,
                order_lots=delta_lots,
                target_lots=target_lots,
                previous_lots=previous_target_lots,
                signal_value=signal_value,
                input_snapshot_ids=input_snapshot_ids,
            )
        )
    return orders


def _order(
    *,
    run_id: str,
    strategy_id: str,
    product_code: str,
    signal_object_id: str,
    trade_date: date,
    execution_date: date,
    target_contract: str,
    order_lots: int,
    target_lots: int,
    previous_lots: int,
    signal_value: float,
    input_snapshot_ids: Sequence[str],
) -> BacktestOrder:
    return BacktestOrder(
        run_id=run_id,
        strategy_id=strategy_id,
        product_code=product_code,
        signal_object_id=signal_object_id,
        trade_date=trade_date,
        execution_date=execution_date,
        target_contract=target_contract,
        side=order_side(order_lots),
        order_lots=order_lots,
        target_lots=target_lots,
        previous_lots=previous_lots,
        signal_value=signal_value,
        input_snapshot_ids=tuple(input_snapshot_ids),
    )


def _factor_by_signal_date(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    factor_id: str | None,
    product_code: str,
    universe: str,
    signal_object_id: str,
) -> dict[date, ResearchFactorValueDailyRow]:
    result: dict[date, ResearchFactorValueDailyRow] = {}
    duplicates: list[date] = []
    for row in factor_rows:
        if row.product_code != product_code or row.universe != universe:
            continue
        if row.signal_object_id != signal_object_id:
            continue
        if factor_id is not None and row.factor_id != factor_id:
            continue
        if row.trade_date in result:
            duplicates.append(row.trade_date)
        result[row.trade_date] = row
    if not result:
        raise BacktestError("no factor rows found for daily backtest")
    if duplicates:
        raise BacktestError(f"duplicate factor rows for trade dates {duplicates}")
    return result


def _mapping_by_signal_date(
    *,
    trade_mappings: Sequence[CoreTradeMappingDailyRow],
    product_code: str,
    signal_object_id: str,
) -> dict[date, CoreTradeMappingDailyRow]:
    result: dict[date, CoreTradeMappingDailyRow] = {}
    duplicates: list[date] = []
    for row in trade_mappings:
        if row.product_code != product_code or row.signal_object_id != signal_object_id:
            continue
        if row.trade_date in result:
            duplicates.append(row.trade_date)
        result[row.trade_date] = row
    if duplicates:
        raise BacktestError(f"duplicate trade mappings for trade dates {duplicates}")
    return result


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
        raise BacktestError(f"no quotes found for product {product_code}")
    if duplicates:
        raise BacktestError(f"duplicate quote rows for {duplicates}")
    return result


def _multiplier_by_contract(
    *,
    contracts: Sequence[CoreContractMasterRow],
    product_code: str,
) -> dict[str, float]:
    result = {
        contract.contract_code: contract.multiplier
        for contract in contracts
        if contract.product_code == product_code
    }
    if not result:
        raise BacktestError(f"no contract master rows found for product {product_code}")
    return result


def _mark_prices(
    *,
    positions: Mapping[str, int],
    quote_by_key: Mapping[tuple[str, date], CoreQuoteDailyRow],
    execution_date: date,
    price_field: str,
) -> dict[str, float]:
    mark_prices: dict[str, float] = {}
    for contract_code, lots in positions.items():
        if lots == 0:
            continue
        quote = quote_by_key.get((contract_code, execution_date))
        if quote is None:
            raise BacktestError(
                f"{execution_date}: mark quote missing for open position {contract_code}"
            )
        mark_prices[contract_code] = quote_price(quote=quote, price_field=price_field)
    return mark_prices


def _signal_value(
    *,
    factor_row: ResearchFactorValueDailyRow,
    use_processed_value: bool,
) -> float:
    value = (
        factor_row.processed_value
        if use_processed_value and factor_row.processed_value is not None
        else factor_row.raw_value
    )
    return float(value)


def _multiplier(contract_code: str, multiplier_by_contract: Mapping[str, float]) -> float:
    try:
        return multiplier_by_contract[contract_code]
    except KeyError as exc:
        raise BacktestError(f"contract missing from contract master: {contract_code}") from exc


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
