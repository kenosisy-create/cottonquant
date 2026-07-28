"""CF strategy-accountable research package."""

from cotton_factor.strategy.baseline_tsmom import (
    StrategyBacktestResult,
    run_cf_tsmom_backtest,
)
from cotton_factor.strategy.registry import (
    StrategyRegistry,
    StrategyRegistryEntry,
    load_strategy_registry,
)
from cotton_factor.strategy.spec import (
    CostScenarioSpec,
    ExecutionSpec,
    GateRuleSpec,
    SizingSpec,
    StrategySpec,
    load_strategy_spec,
)

__all__ = [
    "CostScenarioSpec",
    "ExecutionSpec",
    "GateRuleSpec",
    "SizingSpec",
    "StrategyBacktestResult",
    "StrategyRegistry",
    "StrategyRegistryEntry",
    "StrategySpec",
    "load_strategy_registry",
    "load_strategy_spec",
    "run_cf_tsmom_backtest",
]
