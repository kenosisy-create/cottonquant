"""Research mode configuration loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cotton_factor.common.exceptions import ConfigError
from cotton_factor.common.paths import project_root
from cotton_factor.common.simple_yaml import load_simple_yaml

DEFAULT_RESEARCH_MODE_CONFIG = project_root() / "configs" / "research_mode.yaml"
SUPPORTED_PRODUCTS = {"CF"}
SUPPORTED_FREQUENCIES = {"daily"}
SUPPORTED_EXECUTION_RULES = {"T_SIGNAL_T_PLUS_1_EXECUTION"}
REQUIRED_ACTIVE_FACTORS = {"momentum", "carry", "curve_slope", "oi_pressure"}
REQUIRED_PAUSED_FEATURES = {
    "release_freeze",
    "gray_deployment",
    "full_ci_cd",
    "oms_integration",
    "minute_execution",
    "sr_ap_production_ingest",
}


@dataclass(frozen=True)
class ResearchModeConfig:
    """Validated lightweight research workbench configuration."""

    product: str
    exchange: str
    frequency: str
    data_input_dir: Path
    raw_output_dir: Path
    core_output_dir: Path
    research_output_dir: Path
    report_output_dir: Path
    active_factors: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    execution_rule: str
    platform_features_paused: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable summary for reports and tests."""
        return {
            "product": self.product,
            "exchange": self.exchange,
            "frequency": self.frequency,
            "data_input_dir": str(self.data_input_dir),
            "raw_output_dir": str(self.raw_output_dir),
            "core_output_dir": str(self.core_output_dir),
            "research_output_dir": str(self.research_output_dir),
            "report_output_dir": str(self.report_output_dir),
            "active_factors": list(self.active_factors),
            "cost_scenarios": list(self.cost_scenarios),
            "execution_rule": self.execution_rule,
            "platform_features_paused": list(self.platform_features_paused),
        }


def load_research_mode_config(
    path: Path | None = None,
    *,
    allow_unknown_product: bool = False,
) -> ResearchModeConfig:
    """Load and validate research mode config without triggering platform flows."""
    config_path = path or DEFAULT_RESEARCH_MODE_CONFIG
    payload = load_simple_yaml(config_path)
    return _build_config(
        payload=payload,
        config_path=config_path,
        allow_unknown_product=allow_unknown_product,
    )


def _build_config(
    *,
    payload: dict[str, object],
    config_path: Path,
    allow_unknown_product: bool,
) -> ResearchModeConfig:
    product = _required_str(payload, "product", config_path=config_path).upper()
    if product not in SUPPORTED_PRODUCTS and not allow_unknown_product:
        raise ConfigError(f"unsupported research product: {product}")

    frequency = _required_str(payload, "frequency", config_path=config_path)
    if frequency not in SUPPORTED_FREQUENCIES:
        raise ConfigError(f"unsupported research frequency: {frequency}")

    execution_rule = _required_str(payload, "execution_rule", config_path=config_path)
    if execution_rule not in SUPPORTED_EXECUTION_RULES:
        raise ConfigError(f"unsupported execution_rule: {execution_rule}")

    active_factors = _required_str_tuple(payload, "active_factors", config_path=config_path)
    missing_factors = sorted(REQUIRED_ACTIVE_FACTORS - set(active_factors))
    if missing_factors:
        raise ConfigError(f"research_mode missing active_factors: {missing_factors}")

    cost_scenarios = _required_str_tuple(payload, "cost_scenarios", config_path=config_path)
    if not cost_scenarios:
        raise ConfigError("research_mode cost_scenarios must not be empty")

    paused_features = _required_str_tuple(
        payload,
        "platform_features_paused",
        config_path=config_path,
    )
    missing_paused = sorted(REQUIRED_PAUSED_FEATURES - set(paused_features))
    if missing_paused:
        raise ConfigError(f"research_mode missing paused platform features: {missing_paused}")

    # research mode 只声明平台功能暂停，不在加载配置时触发 release/UAT/灰度等平台流程。
    return ResearchModeConfig(
        product=product,
        exchange=_required_str(payload, "exchange", config_path=config_path),
        frequency=frequency,
        data_input_dir=_required_path(payload, "data_input_dir", config_path=config_path),
        raw_output_dir=_required_path(payload, "raw_output_dir", config_path=config_path),
        core_output_dir=_required_path(payload, "core_output_dir", config_path=config_path),
        research_output_dir=_required_path(
            payload,
            "research_output_dir",
            config_path=config_path,
        ),
        report_output_dir=_required_path(payload, "report_output_dir", config_path=config_path),
        active_factors=active_factors,
        cost_scenarios=cost_scenarios,
        execution_rule=execution_rule,
        platform_features_paused=paused_features,
    )


def _required_str(
    payload: dict[str, object],
    key: str,
    *,
    config_path: Path,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{config_path}: {key} must be a non-empty string")
    return value.strip()


def _required_path(
    payload: dict[str, object],
    key: str,
    *,
    config_path: Path,
) -> Path:
    return Path(_required_str(payload, key, config_path=config_path))


def _required_str_tuple(
    payload: dict[str, object],
    key: str,
    *,
    config_path: Path,
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{config_path}: {key} must be a non-empty list")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{config_path}: {key} contains a non-string item")
        values.append(item.strip())
    return tuple(values)
