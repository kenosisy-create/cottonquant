"""Product config loading and futures contract master generation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cotton_factor.common.exceptions import ConfigError, ContractMasterError
from cotton_factor.common.paths import project_root
from cotton_factor.common.simple_yaml import load_simple_yaml
from cotton_factor.core.schemas import CoreContractMasterRow, CoreContractRuleVersionRow

TODO_REQUIRES_HUMAN_REVIEW = "TODO_REQUIRES_HUMAN_REVIEW"
PRODUCT_CONFIG_VERSION = "products.v1"
CONTRACT_CODE_FORMAT_ZZCE_YMM = "czce_yymm_last_digit"


class ProductConfig(BaseModel):
    """Validated product configuration loaded from configs/products/*.yaml."""

    model_config = ConfigDict(extra="forbid")

    # 产品配置是合约主数据的唯一规则入口；后续不要在生成逻辑里散落品种特例。
    product_code: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    instrument_type: Literal["futures"]
    status: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    multiplier: float | str
    tick_size: float | str
    delivery_months: list[int] | str
    last_trade_day_rule: str = Field(min_length=1)
    option_style: str | None = None
    human_review_required: list[str] = Field(default_factory=list)
    contract_code_format: str = CONTRACT_CODE_FORMAT_ZZCE_YMM

    @field_validator("product_code", "exchange", "currency", mode="before")
    @classmethod
    def _uppercase(cls, value: object) -> object:
        if isinstance(value, str) and value != TODO_REQUIRES_HUMAN_REVIEW:
            return value.upper()
        return value

    @field_validator("delivery_months")
    @classmethod
    def _validate_delivery_months(cls, value: list[int] | str) -> list[int] | str:
        if value == TODO_REQUIRES_HUMAN_REVIEW:
            return value
        if not isinstance(value, list) or not value:
            raise ValueError("delivery_months must be a non-empty month list or TODO")
        invalid = [month for month in value if month < 1 or month > 12]
        if invalid:
            raise ValueError(f"invalid delivery_months: {invalid}")
        if len(set(value)) != len(value):
            raise ValueError("delivery_months must not contain duplicates")
        return sorted(value)

    @model_validator(mode="after")
    def _todo_fields_are_declared(self) -> ProductConfig:
        # 任何未确认字段都必须进入人工复核清单，避免 TODO 被静默当成正式规则。
        todo_fields = [
            field_name
            for field_name in (
                "exchange",
                "multiplier",
                "tick_size",
                "delivery_months",
                "last_trade_day_rule",
                "option_style",
            )
            if getattr(self, field_name) == TODO_REQUIRES_HUMAN_REVIEW
        ]
        missing = [
            field_name
            for field_name in todo_fields
            if field_name not in self.human_review_required
        ]
        if missing:
            raise ValueError(f"TODO fields must be listed in human_review_required: {missing}")
        return self

    @property
    def source_config_version(self) -> str:
        """Stable source version id for schema lineage."""
        return f"{PRODUCT_CONFIG_VERSION}.{self.product_code}"

    @property
    def rule_version_id(self) -> str:
        """Stable contract rule id generated from product config version."""
        return f"{self.exchange}.{self.product_code}.contract_rules.v1"

    def is_generation_ready(self) -> bool:
        """Return whether this config has enough confirmed fields to generate contracts."""
        # 只有生成合约必需的字段确认后，才允许产出 contract_master。
        # tick_size 可暂为空，因为 D6 明确允许它保留人工复核风险。
        return (
            self.exchange != TODO_REQUIRES_HUMAN_REVIEW
            and self.multiplier != TODO_REQUIRES_HUMAN_REVIEW
            and self.delivery_months != TODO_REQUIRES_HUMAN_REVIEW
            and self.last_trade_day_rule != TODO_REQUIRES_HUMAN_REVIEW
        )


@dataclass(frozen=True)
class ContractMasterBuildResult:
    """Contract master generation output."""

    product_config: ProductConfig
    rule_version: CoreContractRuleVersionRow
    contracts: list[CoreContractMasterRow]
    warnings: list[str]


def load_product_config(product_code: str, config_dir: Path | None = None) -> ProductConfig:
    """Load one product config from configs/products."""
    product = _safe_product_code(product_code)
    product_dir = config_dir or project_root() / "configs" / "products"
    config_path = product_dir / f"{product}.yaml"
    if not config_path.exists():
        raise ConfigError(f"product config not found: {config_path}")

    try:
        return ProductConfig.model_validate(load_simple_yaml(config_path))
    except ValueError as exc:
        raise ConfigError(f"invalid product config {config_path}: {exc}") from exc


def load_all_product_configs(config_dir: Path | None = None) -> list[ProductConfig]:
    """Load all product configs from configs/products."""
    product_dir = config_dir or project_root() / "configs" / "products"
    return [
        load_product_config(path.stem, product_dir)
        for path in sorted(product_dir.glob("*.yaml"))
    ]


def build_contract_master(
    *,
    product_code: str,
    year: int,
    config_dir: Path | None = None,
    trading_dates: Sequence[date] | None = None,
) -> ContractMasterBuildResult:
    """Generate contract master rows for a product/year from product config."""
    config = load_product_config(product_code, config_dir)
    return build_contract_master_from_config(config=config, year=year, trading_dates=trading_dates)


def build_contract_master_from_config(
    *,
    config: ProductConfig,
    year: int,
    trading_dates: Sequence[date] | None = None,
) -> ContractMasterBuildResult:
    """Generate contract master rows for one validated product config."""
    _validate_year(year)
    # SR/AP/M/C/Y 目前主要用于配置 smoke；带 TODO 的配置不能误生成正式合约行。
    if not config.is_generation_ready():
        raise ContractMasterError(
            f"{config.product_code} config has TODO_REQUIRES_HUMAN_REVIEW fields; "
            "contract generation is blocked"
        )
    if config.instrument_type != "futures":
        raise ContractMasterError(f"unsupported instrument_type: {config.instrument_type}")

    assert isinstance(config.delivery_months, list)
    assert isinstance(config.multiplier, int | float)

    # 规则版本先按配置版本固化，后续若官方规则修订，再增加新的 rule_version_id。
    effective_from = date(year, 1, 1)
    rule = CoreContractRuleVersionRow(
        rule_version_id=config.rule_version_id,
        exchange=config.exchange,
        product_code=config.product_code,
        effective_from=effective_from,
        delivery_months=config.delivery_months,
        last_trade_day_rule=config.last_trade_day_rule,
        source_config_version=config.source_config_version,
        human_review_required=config.human_review_required,
        notes="D6 generated from product config; human review gates remain explicit.",
    )

    warnings = _generation_warnings(config=config, trading_dates=trading_dates)
    contracts = [
        CoreContractMasterRow(
            exchange=config.exchange,
            product_code=config.product_code,
            contract_code=_contract_code(config=config, year=year, month=month),
            contract_month=f"{year}{month:02d}",
            delivery_year=year,
            delivery_month=month,
            instrument_type="futures",
            multiplier=float(config.multiplier),
            tick_size=_optional_float(config.tick_size),
            first_trade_date=None,
            last_trade_date=_last_trade_date(
                rule=config.last_trade_day_rule,
                year=year,
                month=month,
                trading_dates=trading_dates,
            ),
            rule_version_id=rule.rule_version_id,
            source_config_version=config.source_config_version,
        )
        for month in config.delivery_months
    ]

    return ContractMasterBuildResult(
        product_config=config,
        rule_version=rule,
        contracts=contracts,
        warnings=warnings,
    )


def _safe_product_code(product_code: str) -> str:
    product = product_code.strip().upper()
    if not product.isalnum():
        raise ConfigError(f"unsafe product code: {product_code!r}")
    return product


def _validate_year(year: int) -> None:
    if year < 1990 or year > 2100:
        raise ContractMasterError(f"year out of supported range: {year}")


def _contract_code(*, config: ProductConfig, year: int, month: int) -> str:
    if config.contract_code_format != CONTRACT_CODE_FORMAT_ZZCE_YMM:
        raise ContractMasterError(
            f"unsupported contract_code_format: {config.contract_code_format}"
        )
    return f"{config.product_code}{year % 10}{month:02d}"


def _optional_float(value: float | str | None) -> float | None:
    if value in {None, TODO_REQUIRES_HUMAN_REVIEW}:
        return None
    return float(value)


def _last_trade_date(
    *,
    rule: str,
    year: int,
    month: int,
    trading_dates: Sequence[date] | None,
) -> date | None:
    if rule != "delivery_month_10th_trading_day":
        raise ContractMasterError(f"unsupported last_trade_day_rule: {rule}")
    if trading_dates is None:
        # D6 不能凭周末日历推断最后交易日；没有交易日历时显式留空并输出 warning。
        return None

    matching_dates = sorted(
        trade_date
        for trade_date in trading_dates
        if trade_date.year == year and trade_date.month == month
    )
    if len(matching_dates) < 10:
        raise ContractMasterError(
            f"not enough trading dates to compute 10th trading day for {year}-{month:02d}"
        )
    return matching_dates[9]


def _generation_warnings(
    *,
    config: ProductConfig,
    trading_dates: Sequence[date] | None,
) -> list[str]:
    warnings: list[str] = []
    if config.tick_size == TODO_REQUIRES_HUMAN_REVIEW:
        warnings.append("tick_size is TODO_REQUIRES_HUMAN_REVIEW; emitted as null")
    if "last_trade_day_rule" in config.human_review_required:
        warnings.append("last_trade_day_rule requires human review before production use")
    if trading_dates is None:
        warnings.append("last_trade_date omitted because no trading calendar was supplied")
    warnings.extend(
        f"{field_name} requires human review" for field_name in config.human_review_required
    )
    return sorted(set(warnings))
