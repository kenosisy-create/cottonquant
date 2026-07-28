"""CF strategy-accountable research package."""

from cotton_factor.strategy.baseline_tsmom import (
    StrategyBacktestResult,
    run_cf_tsmom_backtest,
)
from cotton_factor.strategy.comparison import (
    StrategyComparisonResult,
    compare_cf_strategies,
    promotion_decision,
)
from cotton_factor.strategy.evaluation import (
    StrategyEvaluationResult,
    evaluate_cf_strategy,
)
from cotton_factor.strategy.phase_gated import (
    build_phase_gated_targets,
    run_cf_phase_gated_backtest,
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
    "StrategyComparisonResult",
    "StrategyEvaluationResult",
    "StrategyRegistry",
    "StrategyRegistryEntry",
    "StrategySpec",
    "build_phase_gated_targets",
    "compare_cf_strategies",
    "evaluate_cf_strategy",
    "load_strategy_registry",
    "load_strategy_spec",
    "promotion_decision",
    "run_cf_phase_gated_backtest",
    "run_cf_tsmom_backtest",
]
