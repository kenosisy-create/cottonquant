"""Research-derived layer package."""

from cotton_factor.research.continuous_price import (
    DEFAULT_CONTINUOUS_RULE_VERSION,
    ContinuousPriceBuildResult,
    build_continuous_price,
)
from cotton_factor.research.evaluator import (
    DEFAULT_EVALUATION_RULE_VERSION,
    SingleFactorEvaluationResult,
    evaluate_single_factor,
)
from cotton_factor.research.factor_base import (
    DEFAULT_FACTOR_REGISTRY_PATH,
    TODO_REQUIRES_HUMAN_REVIEW,
    FactorDefinition,
    FactorInputBundle,
    FactorObservation,
    FactorRegistry,
    FactorResult,
    FactorSpec,
    build_factor_rows,
    load_factor_registry,
    validate_factor_dependencies,
)
from cotton_factor.research.factors import (
    CARRY_FACTOR_ID,
    CURVE_SLOPE_FACTOR_ID,
    DEFAULT_MOMENTUM_LOOKBACK_PERIODS,
    MOMENTUM_FACTOR_ID,
    OI_PRESSURE_FACTOR_ID,
    compute_carry_factor,
    compute_curve_slope_factor,
    compute_momentum_factor,
    compute_oi_pressure_factor,
)
from cotton_factor.research.forward_returns import (
    DEFAULT_FORWARD_RETURN_RULE_VERSION,
    ForwardReturnBuildResult,
    build_forward_returns,
)
from cotton_factor.research.multifactor import (
    DEFAULT_EQUAL_WEIGHT_SCORE_ID,
    DEFAULT_EQUAL_WEIGHT_SCORE_RULE_VERSION,
    MultifactorScoreBuildResult,
    build_equal_weight_scores,
)
from cotton_factor.research.preprocessing import (
    rank_series,
    winsorize_series,
    zscore_series,
)

__all__ = [
    "ContinuousPriceBuildResult",
    "CARRY_FACTOR_ID",
    "CURVE_SLOPE_FACTOR_ID",
    "DEFAULT_EVALUATION_RULE_VERSION",
    "DEFAULT_EQUAL_WEIGHT_SCORE_ID",
    "DEFAULT_EQUAL_WEIGHT_SCORE_RULE_VERSION",
    "DEFAULT_FACTOR_REGISTRY_PATH",
    "DEFAULT_CONTINUOUS_RULE_VERSION",
    "DEFAULT_FORWARD_RETURN_RULE_VERSION",
    "DEFAULT_MOMENTUM_LOOKBACK_PERIODS",
    "MOMENTUM_FACTOR_ID",
    "OI_PRESSURE_FACTOR_ID",
    "TODO_REQUIRES_HUMAN_REVIEW",
    "FactorDefinition",
    "FactorInputBundle",
    "FactorObservation",
    "FactorRegistry",
    "FactorResult",
    "FactorSpec",
    "ForwardReturnBuildResult",
    "MultifactorScoreBuildResult",
    "SingleFactorEvaluationResult",
    "build_equal_weight_scores",
    "build_forward_returns",
    "compute_carry_factor",
    "compute_curve_slope_factor",
    "compute_momentum_factor",
    "compute_oi_pressure_factor",
    "evaluate_single_factor",
    "build_continuous_price",
    "build_factor_rows",
    "load_factor_registry",
    "rank_series",
    "validate_factor_dependencies",
    "winsorize_series",
    "zscore_series",
]
