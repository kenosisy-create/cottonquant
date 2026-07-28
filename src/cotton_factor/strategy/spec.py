"""R86 versioned strategy specification contract."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cotton_factor.common.exceptions import StrategyError

FORBIDDEN_INPUT_TOKENS = ("forward_return", "fwd_ret", "future_")
REQUIRED_COST_SCENARIOS = ("no_cost", "normal_cost", "conservative_cost")


class StrategyChangeLogEntry(BaseModel):
    """One immutable strategy-spec change note."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    date: date
    note: str = Field(min_length=1)


class SizingSpec(BaseModel):
    """Research-only position sizing parameters."""

    model_config = ConfigDict(extra="forbid")

    model: Literal["vol_target"]
    capital_base: float = Field(gt=0)
    target_vol: float = Field(gt=0)
    vol_window: int = Field(ge=2)
    vol_floor: float = Field(gt=0)
    max_lots: int = Field(gt=0)
    multiplier_source: Literal["product_config"] = "product_config"


class ExecutionSpec(BaseModel):
    """Execution timing is fixed to the next official settlement."""

    model_config = ConfigDict(extra="forbid")

    timing: Literal["T_PLUS_1_SETTLE"]
    price_field: Literal["settle"] = "settle"


class CostScenarioSpec(BaseModel):
    """One-way notional transaction-cost scenario."""

    model_config = ConfigDict(extra="forbid")

    one_way_bps: float = Field(ge=0)


class GateRuleSpec(BaseModel):
    """Structured candidate or overlay gate rule."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class PromotionRuleSpec(BaseModel):
    """Fixed strategy comparison gate."""

    model_config = ConfigDict(extra="forbid")

    required_year_wins: int = Field(default=4, ge=1, le=5)
    evaluation_years: list[int] = Field(default_factory=lambda: list(range(2021, 2026)))
    min_active_days: int = Field(default=60, ge=1)
    min_completed_trades: int = Field(default=4, ge=1)
    min_full_period_delta_sharpe: float = 0.10
    require_positive_conservative_return: bool = True
    max_drawdown_deterioration_pp: float = Field(default=5.0, ge=0)

    @field_validator("evaluation_years")
    @classmethod
    def _years_are_five_unique_full_years(cls, value: list[int]) -> list[int]:
        if len(value) != 5 or len(set(value)) != 5:
            raise ValueError("evaluation_years must contain five unique years")
        return sorted(value)


class StrategySpec(BaseModel):
    """Decision-complete strategy configuration used by all V5.1 workflows."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    version: str = Field(pattern=r"^v[0-9]+$")
    strategy_type: Literal["baseline_tsmom", "phase_gated", "overlay"]
    status: Literal["baseline", "candidate", "frozen"]
    product: Literal["CF"]
    signal_object: Literal["CF.C1"]
    signal_horizon: int = Field(default=20, ge=1)
    signal_windows: dict[str, int]
    entry_rule: str = Field(min_length=1)
    exit_rule: str = Field(min_length=1)
    gate_rules: list[GateRuleSpec] = Field(default_factory=list)
    sizing: SizingSpec
    execution: ExecutionSpec
    costs: dict[str, CostScenarioSpec]
    data_dependencies: list[str] = Field(min_length=1)
    forbidden_inputs: list[str]
    created_at: date
    changelog: list[StrategyChangeLogEntry] = Field(min_length=1)
    base_strategy: str | None = None
    promotion_rule: PromotionRuleSpec | None = None

    @model_validator(mode="after")
    def _validate_research_boundaries(self) -> StrategySpec:
        required_forbidden = set(FORBIDDEN_INPUT_TOKENS)
        if not required_forbidden.issubset(set(self.forbidden_inputs)):
            raise ValueError(
                "forbidden_inputs must include forward_return, fwd_ret and future_"
            )
        if set(self.costs) != set(REQUIRED_COST_SCENARIOS):
            raise ValueError(
                "costs must define no_cost, normal_cost and conservative_cost"
            )
        if self.strategy_type == "baseline_tsmom" and self.gate_rules:
            raise ValueError("baseline_tsmom cannot define gate_rules")
        if self.strategy_type != "baseline_tsmom" and not self.base_strategy:
            raise ValueError("candidate and overlay specs require base_strategy")

        # 禁止项递归检查所有真实输入字段，但排除声明禁止词本身。
        payload = self.model_dump(mode="json", exclude={"forbidden_inputs"})
        violations = _find_forbidden_values(payload)
        if violations:
            raise ValueError(f"strategy spec references forbidden inputs: {violations}")
        return self

    @property
    def spec_key(self) -> str:
        """Return a stable strategy/version key."""
        return f"{self.strategy_id}/{self.version}"


def load_strategy_spec(path: Path) -> StrategySpec:
    """Load one safe YAML strategy spec."""
    if not path.exists() or not path.is_file():
        raise StrategyError(f"strategy spec not found: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise StrategyError(f"invalid strategy YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StrategyError(f"strategy spec must be a mapping: {path}")
    try:
        return StrategySpec.model_validate(payload)
    except ValueError as exc:
        raise StrategyError(f"invalid strategy spec {path}: {exc}") from exc


def _find_forbidden_values(value: object, *, path: str = "root") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            violations.extend(_find_forbidden_values(key, path=f"{path}.<key>"))
            violations.extend(_find_forbidden_values(item, path=f"{path}.{key}"))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            violations.extend(_find_forbidden_values(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        for token in FORBIDDEN_INPUT_TOKENS:
            if token in lowered:
                violations.append(f"{path}:{token}")
    return sorted(set(violations))
