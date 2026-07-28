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
from cotton_factor.strategy.overlay_test import (
    OverlayTestResult,
    build_overlay_targets,
    overlay_decision,
    resolve_strategy_spec_path,
    run_cf_overlay_backtest,
    test_cf_overlay,
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
from cotton_factor.strategy.shadow_ledger import ShadowRunResult, run_cf_strategy_shadow
from cotton_factor.strategy.spec import (
    CostScenarioSpec,
    ExecutionSpec,
    GateRuleSpec,
    SizingSpec,
    StrategySpec,
    load_strategy_spec,
)
from cotton_factor.strategy.weekly_audit import (
    WeeklyStrategyAuditResult,
    build_cf_weekly_strategy_audit,
)

__all__ = [
    "CostScenarioSpec",
    "ExecutionSpec",
    "GateRuleSpec",
    "OverlayTestResult",
    "SizingSpec",
    "StrategyBacktestResult",
    "StrategyComparisonResult",
    "StrategyEvaluationResult",
    "StrategyRegistry",
    "StrategyRegistryEntry",
    "StrategySpec",
    "ShadowRunResult",
    "WeeklyStrategyAuditResult",
    "build_phase_gated_targets",
    "build_cf_weekly_strategy_audit",
    "build_overlay_targets",
    "compare_cf_strategies",
    "evaluate_cf_strategy",
    "load_strategy_registry",
    "load_strategy_spec",
    "overlay_decision",
    "promotion_decision",
    "run_cf_phase_gated_backtest",
    "run_cf_overlay_backtest",
    "run_cf_strategy_shadow",
    "run_cf_tsmom_backtest",
    "resolve_strategy_spec_path",
    "test_cf_overlay",
]
