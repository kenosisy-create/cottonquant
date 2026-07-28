"""R86 strategy registry loading and validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import project_root
from cotton_factor.strategy.spec import StrategySpec, load_strategy_spec


class StrategyRegistryEntry(BaseModel):
    """One strategy specification registered for research workflows."""

    model_config = ConfigDict(extra="forbid")

    spec_path: str = Field(min_length=1)
    enabled: bool = True


class StrategyRegistryConfig(BaseModel):
    """On-disk registry schema."""

    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(min_length=1)
    product_scope: str = "CF_ONLY"
    entries: list[StrategyRegistryEntry] = Field(min_length=1)


class StrategyRegistry(BaseModel):
    """Loaded registry with validated strategy specs."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    registry_version: str
    product_scope: str
    registry_path: Path
    specs: list[StrategySpec]

    def to_summary(self) -> dict[str, object]:
        """Return a machine-readable validation summary."""
        return {
            "registry_version": self.registry_version,
            "product_scope": self.product_scope,
            "registry_path": str(self.registry_path),
            "strategy_count": len(self.specs),
            "strategies": [
                {
                    "strategy_key": spec.spec_key,
                    "strategy_type": spec.strategy_type,
                    "status": spec.status,
                    "product": spec.product,
                }
                for spec in self.specs
            ],
        }

    def find(self, strategy_ref: str) -> StrategySpec:
        """Resolve `strategy_id` or `strategy_id/version` without ambiguity."""
        matches = [
            spec
            for spec in self.specs
            if strategy_ref in {spec.strategy_id, spec.spec_key}
        ]
        if len(matches) != 1:
            raise StrategyError(
                f"strategy reference must resolve exactly once: {strategy_ref!r}"
            )
        return matches[0]


def load_strategy_registry(path: Path | None = None) -> StrategyRegistry:
    """Load the CF-only strategy registry and every enabled spec."""
    registry_path = path or project_root() / "configs" / "strategy" / "strategy_registry.yaml"
    if not registry_path.exists() or not registry_path.is_file():
        raise StrategyError(f"strategy registry not found: {registry_path}")
    try:
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        config = StrategyRegistryConfig.model_validate(payload)
    except (yaml.YAMLError, ValueError) as exc:
        raise StrategyError(f"invalid strategy registry {registry_path}: {exc}") from exc
    if config.product_scope != "CF_ONLY":
        raise StrategyError("V5.1 phase one registry must use product_scope=CF_ONLY")

    specs: list[StrategySpec] = []
    seen: set[str] = set()
    for entry in config.entries:
        if not entry.enabled:
            continue
        spec_path = _resolve_spec_path(registry_path=registry_path, value=entry.spec_path)
        spec = load_strategy_spec(spec_path)
        if spec.spec_key in seen:
            raise StrategyError(f"duplicate strategy spec key: {spec.spec_key}")
        seen.add(spec.spec_key)
        specs.append(spec)
    if not specs:
        raise StrategyError("strategy registry has no enabled specs")
    return StrategyRegistry(
        registry_version=config.registry_version,
        product_scope=config.product_scope,
        registry_path=registry_path,
        specs=specs,
    )


def _resolve_spec_path(*, registry_path: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project_root() / candidate
    resolved = candidate.resolve()
    root = project_root().resolve()
    if root not in resolved.parents:
        raise StrategyError(f"strategy spec path escapes repository: {value}")
    if resolved == registry_path.resolve():
        raise StrategyError("strategy registry cannot register itself")
    return resolved
