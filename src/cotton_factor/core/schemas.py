"""Row-level schemas for core facts, research outputs, and archive manifests."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1)]
SnapshotId = Annotated[str, Field(min_length=1)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class SchemaValidationError(ValueError):
    """Raised when rows do not satisfy a registered schema."""


class SchemaRow(BaseModel):
    """Base for strict row-level table schemas."""

    model_config = ConfigDict(extra="forbid")

    table_name: ClassVar[str]
    primary_key: ClassVar[tuple[str, ...]]
    version_fields: ClassVar[tuple[str, ...]] = ("schema_version",)
    lineage_fields: ClassVar[tuple[str, ...]] = ()


class CoreContractMasterRow(SchemaRow):
    """core_contract_master row."""

    table_name: ClassVar[str] = "core_contract_master"
    primary_key: ClassVar[tuple[str, ...]] = ("exchange", "product_code", "contract_code")
    lineage_fields: ClassVar[tuple[str, ...]] = ("source_config_version",)

    schema_version: Literal["core_contract_master.v1"] = "core_contract_master.v1"
    exchange: NonEmptyStr
    product_code: NonEmptyStr
    contract_code: NonEmptyStr
    contract_month: Annotated[str, Field(pattern=r"^\d{4}(0[1-9]|1[0-2])$")]
    delivery_year: Annotated[int, Field(ge=1990, le=2100)]
    delivery_month: Annotated[int, Field(ge=1, le=12)]
    instrument_type: Literal["futures"] = "futures"
    multiplier: PositiveFloat
    tick_size: PositiveFloat | None = None
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    rule_version_id: NonEmptyStr
    source_config_version: NonEmptyStr

    @model_validator(mode="after")
    def _dates_are_ordered(self) -> CoreContractMasterRow:
        if (
            self.first_trade_date is not None
            and self.last_trade_date is not None
            and self.first_trade_date > self.last_trade_date
        ):
            raise ValueError("first_trade_date must be <= last_trade_date")
        return self


class CoreContractRuleVersionRow(SchemaRow):
    """core_contract_rule_version row."""

    table_name: ClassVar[str] = "core_contract_rule_version"
    primary_key: ClassVar[tuple[str, ...]] = ("rule_version_id",)
    lineage_fields: ClassVar[tuple[str, ...]] = ("source_config_version",)

    schema_version: Literal["core_contract_rule_version.v1"] = (
        "core_contract_rule_version.v1"
    )
    rule_version_id: NonEmptyStr
    exchange: NonEmptyStr
    product_code: NonEmptyStr
    effective_from: date
    effective_to: date | None = None
    delivery_months: list[Annotated[int, Field(ge=1, le=12)]]
    last_trade_day_rule: NonEmptyStr
    source_config_version: NonEmptyStr
    human_review_required: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("delivery_months")
    @classmethod
    def _delivery_months_not_empty(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("delivery_months must not be empty")
        return value

    @model_validator(mode="after")
    def _effective_dates_are_ordered(self) -> CoreContractRuleVersionRow:
        if self.effective_to is not None and self.effective_from > self.effective_to:
            raise ValueError("effective_from must be <= effective_to")
        return self


class CoreTradingCalendarRow(SchemaRow):
    """core_trading_calendar row."""

    table_name: ClassVar[str] = "core_trading_calendar"
    primary_key: ClassVar[tuple[str, ...]] = ("exchange", "trade_date", "calendar_version")
    lineage_fields: ClassVar[tuple[str, ...]] = ("calendar_version", "source_snapshot_id")

    schema_version: Literal["core_trading_calendar.v1"] = "core_trading_calendar.v1"
    exchange: NonEmptyStr
    trade_date: date
    is_trading_day: bool
    calendar_version: NonEmptyStr
    source_snapshot_id: SnapshotId | None = None


class CoreQuoteDailyRow(SchemaRow):
    """core_quote_daily row."""

    table_name: ClassVar[str] = "core_quote_daily"
    primary_key: ClassVar[tuple[str, ...]] = ("exchange", "contract_code", "trade_date")
    lineage_fields: ClassVar[tuple[str, ...]] = ("source_snapshot_id",)

    schema_version: Literal["core_quote_daily.v1"] = "core_quote_daily.v1"
    source_snapshot_id: SnapshotId
    exchange: NonEmptyStr
    product_code: NonEmptyStr
    contract_code: NonEmptyStr
    trade_date: date
    open: NonNegativeFloat | None = None
    high: NonNegativeFloat | None = None
    low: NonNegativeFloat | None = None
    close: NonNegativeFloat | None = None
    settle: NonNegativeFloat | None = None
    pre_settle: NonNegativeFloat | None = None
    volume: NonNegativeInt | None = None
    open_interest: NonNegativeInt | None = None
    turnover: NonNegativeFloat | None = None
    quote_status: Literal["normal", "suspended", "missing", "corrected"] = "normal"

    @model_validator(mode="after")
    def _high_low_are_ordered(self) -> CoreQuoteDailyRow:
        if self.high is not None and self.low is not None and self.high < self.low:
            raise ValueError("high must be >= low")
        return self


class CoreOptionQuoteDailyRow(SchemaRow):
    """core_option_quote_daily row."""

    table_name: ClassVar[str] = "core_option_quote_daily"
    primary_key: ClassVar[tuple[str, ...]] = ("exchange", "option_symbol", "trade_date")
    lineage_fields: ClassVar[tuple[str, ...]] = ("source_snapshot_id",)

    schema_version: Literal["core_option_quote_daily.v1"] = "core_option_quote_daily.v1"
    source_snapshot_id: SnapshotId
    exchange: NonEmptyStr
    product_code: NonEmptyStr
    trade_date: date
    option_symbol: NonEmptyStr
    underlying_contract: NonEmptyStr
    option_type: Literal["C", "P"]
    strike: PositiveFloat
    settle: NonNegativeFloat | None = None
    volume: NonNegativeInt | None = None
    open_interest: NonNegativeInt | None = None
    moneyness: NonNegativeFloat | None = None
    liquidity_flag: NonEmptyStr
    data_quality_flag: NonEmptyStr

    @model_validator(mode="after")
    def _missing_market_fields_are_flagged(self) -> CoreOptionQuoteDailyRow:
        if (
            self.settle is None
            and self.volume is None
            and self.open_interest is None
            and self.data_quality_flag == "normal"
        ):
            raise ValueError("missing option market fields cannot be flagged as normal")
        return self


class CoreSettlementParamDailyRow(SchemaRow):
    """core_settlement_param_daily row."""

    table_name: ClassVar[str] = "core_settlement_param_daily"
    primary_key: ClassVar[tuple[str, ...]] = ("exchange", "contract_code", "trade_date")
    lineage_fields: ClassVar[tuple[str, ...]] = ("source_snapshot_id",)

    schema_version: Literal["core_settlement_param_daily.v1"] = (
        "core_settlement_param_daily.v1"
    )
    source_snapshot_id: SnapshotId
    exchange: NonEmptyStr
    product_code: NonEmptyStr
    contract_code: NonEmptyStr
    trade_date: date
    limit_up: NonNegativeFloat | None = None
    limit_down: NonNegativeFloat | None = None
    margin_rate_long: NonNegativeFloat | None = None
    margin_rate_short: NonNegativeFloat | None = None
    trading_status: Literal["normal", "halted", "limit_only", "unknown"] = "unknown"
    settlement_status: Literal["official", "provisional", "corrected"] = "official"

    @model_validator(mode="after")
    def _limits_are_ordered(self) -> CoreSettlementParamDailyRow:
        if self.limit_up is not None and self.limit_down is not None:
            if self.limit_up < self.limit_down:
                raise ValueError("limit_up must be >= limit_down")
        return self


class CoreChainMapDailyRow(SchemaRow):
    """core_chain_map_daily row."""

    table_name: ClassVar[str] = "core_chain_map_daily"
    primary_key: ClassVar[tuple[str, ...]] = ("product_code", "signal_object_id", "trade_date")
    lineage_fields: ClassVar[tuple[str, ...]] = ("source_snapshot_id",)

    schema_version: Literal["core_chain_map_daily.v1"] = "core_chain_map_daily.v1"
    source_snapshot_id: SnapshotId
    exchange: NonEmptyStr
    product_code: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    mapped_contract: NonEmptyStr
    chain_rank: Annotated[int, Field(ge=1)] = 1
    switch_reason: NonEmptyStr
    roll_rule_version: NonEmptyStr


class CoreTradeMappingDailyRow(SchemaRow):
    """core_trade_mapping_daily row."""

    table_name: ClassVar[str] = "core_trade_mapping_daily"
    primary_key: ClassVar[tuple[str, ...]] = ("product_code", "signal_object_id", "trade_date")
    lineage_fields: ClassVar[tuple[str, ...]] = ("source_snapshot_id",)

    schema_version: Literal["core_trade_mapping_daily.v1"] = (
        "core_trade_mapping_daily.v1"
    )
    source_snapshot_id: SnapshotId
    exchange: NonEmptyStr
    product_code: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    execution_date: date
    target_contract: NonEmptyStr | None = None
    is_blocked: bool = False
    block_reason: str | None = None
    execution_eligible: bool = True
    mapping_rule_version: NonEmptyStr

    @model_validator(mode="after")
    def _blocked_rows_are_explicit(self) -> CoreTradeMappingDailyRow:
        if self.execution_date <= self.trade_date:
            raise ValueError("execution_date must be after trade_date")
        if self.is_blocked and not self.block_reason:
            raise ValueError("blocked trade mapping rows must include block_reason")
        if not self.is_blocked and not self.target_contract:
            raise ValueError("unblocked trade mapping rows must include target_contract")
        if self.is_blocked and self.execution_eligible:
            raise ValueError("blocked trade mapping rows cannot be execution_eligible")
        return self


class ResearchContinuousPriceDailyRow(SchemaRow):
    """research_continuous_price_daily row."""

    table_name: ClassVar[str] = "research_continuous_price_daily"
    primary_key: ClassVar[tuple[str, ...]] = (
        "product_code",
        "signal_object_id",
        "trade_date",
        "price_field",
    )
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["research_continuous_price_daily.v1"] = (
        "research_continuous_price_daily.v1"
    )
    product_code: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    mapped_contract: NonEmptyStr
    price_field: Literal["open", "close", "settle"]
    raw_price: NonNegativeFloat
    adjusted_price: NonNegativeFloat
    adjustment: float
    cumulative_adjustment: float
    is_roll: bool = False
    roll_from_contract: NonEmptyStr | None = None
    roll_to_contract: NonEmptyStr | None = None
    roll_gap: float | None = None
    chain_switch_reason: NonEmptyStr
    continuous_rule_version: NonEmptyStr
    input_snapshot_ids: Annotated[list[SnapshotId], Field(min_length=1)]

    @model_validator(mode="after")
    def _roll_rows_are_traceable(self) -> ResearchContinuousPriceDailyRow:
        if self.is_roll and (not self.roll_from_contract or not self.roll_to_contract):
            raise ValueError("roll rows must include roll_from_contract and roll_to_contract")
        return self


class ResearchFactorValueDailyRow(SchemaRow):
    """research_factor_value_daily row."""

    table_name: ClassVar[str] = "research_factor_value_daily"
    primary_key: ClassVar[tuple[str, ...]] = (
        "run_id",
        "factor_id",
        "signal_object_id",
        "trade_date",
    )
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["research_factor_value_daily.v1"] = (
        "research_factor_value_daily.v1"
    )
    run_id: NonEmptyStr
    factor_id: NonEmptyStr
    factor_version: NonEmptyStr
    product_code: NonEmptyStr
    universe: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    raw_value: float
    processed_value: float | None = None
    input_snapshot_ids: Annotated[list[SnapshotId], Field(min_length=1)]


class ResearchFactorDiagnosticDailyRow(SchemaRow):
    """research_factor_diagnostic_daily row."""

    table_name: ClassVar[str] = "research_factor_diagnostic_daily"
    primary_key: ClassVar[tuple[str, ...]] = (
        "run_id",
        "factor_id",
        "signal_object_id",
        "trade_date",
    )
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["research_factor_diagnostic_daily.v1"] = (
        "research_factor_diagnostic_daily.v1"
    )
    run_id: NonEmptyStr
    factor_id: NonEmptyStr
    factor_version: NonEmptyStr
    product_code: NonEmptyStr
    universe: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    raw_value: float | None = None
    processed_value: float | None = None
    signal_state: Literal["long", "short", "neutral", "unknown"]
    diagnostic_reason: NonEmptyStr
    warning_flags: list[NonEmptyStr] = Field(default_factory=list)
    human_review_required: list[NonEmptyStr] = Field(default_factory=list)
    diagnostic_rule_version: NonEmptyStr
    input_snapshot_ids: Annotated[list[SnapshotId], Field(min_length=1)]

    @model_validator(mode="after")
    def _unknown_state_requires_context(self) -> ResearchFactorDiagnosticDailyRow:
        if self.signal_state == "unknown" and not (
            self.warning_flags or self.human_review_required
        ):
            raise ValueError("unknown diagnostic rows must include warning or review context")
        return self


class ResearchForwardReturnDailyRow(SchemaRow):
    """research_forward_return_daily row."""

    table_name: ClassVar[str] = "research_forward_return_daily"
    primary_key: ClassVar[tuple[str, ...]] = (
        "run_id",
        "product_code",
        "signal_object_id",
        "trade_date",
        "horizon",
    )
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["research_forward_return_daily.v1"] = (
        "research_forward_return_daily.v1"
    )
    run_id: NonEmptyStr
    product_code: NonEmptyStr
    universe: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    execution_date: date
    exit_date: date
    horizon: Annotated[int, Field(ge=1)]
    target_contract: NonEmptyStr
    entry_price_field: Literal["open", "close", "settle"]
    exit_price_field: Literal["open", "close", "settle"]
    entry_price: PositiveFloat
    exit_price: PositiveFloat
    forward_return: float
    return_rule_version: NonEmptyStr
    input_snapshot_ids: Annotated[list[SnapshotId], Field(min_length=1)]

    @model_validator(mode="after")
    def _return_dates_are_ordered(self) -> ResearchForwardReturnDailyRow:
        if self.execution_date <= self.trade_date:
            raise ValueError("execution_date must be after trade_date")
        if self.exit_date <= self.execution_date:
            raise ValueError("exit_date must be after execution_date")
        return self


class ResearchFactorEvaluationRow(SchemaRow):
    """research_factor_evaluation row."""

    table_name: ClassVar[str] = "research_factor_evaluation"
    primary_key: ClassVar[tuple[str, ...]] = (
        "run_id",
        "factor_id",
        "horizon",
        "metric_name",
    )
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["research_factor_evaluation.v1"] = (
        "research_factor_evaluation.v1"
    )
    run_id: NonEmptyStr
    factor_id: NonEmptyStr
    factor_version: NonEmptyStr
    product_code: NonEmptyStr
    universe: NonEmptyStr
    horizon: Annotated[int, Field(ge=1)]
    metric_name: NonEmptyStr
    metric_value: float
    observation_count: NonNegativeInt
    evaluation_rule_version: NonEmptyStr
    input_snapshot_ids: Annotated[list[SnapshotId], Field(min_length=1)]


class ResearchMultifactorScoreDailyRow(SchemaRow):
    """research_multifactor_score_daily row."""

    table_name: ClassVar[str] = "research_multifactor_score_daily"
    primary_key: ClassVar[tuple[str, ...]] = (
        "run_id",
        "score_id",
        "signal_object_id",
        "trade_date",
    )
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["research_multifactor_score_daily.v1"] = (
        "research_multifactor_score_daily.v1"
    )
    run_id: NonEmptyStr
    score_id: NonEmptyStr
    score_version: NonEmptyStr
    product_code: NonEmptyStr
    universe: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    raw_score: float
    processed_score: float | None = None
    factor_count: Annotated[int, Field(ge=1)]
    input_factor_ids: Annotated[list[NonEmptyStr], Field(min_length=1)]
    score_rule_version: NonEmptyStr
    input_snapshot_ids: Annotated[list[SnapshotId], Field(min_length=1)]


class BacktestTargetLotDailyRow(SchemaRow):
    """backtest_target_lot_daily row."""

    table_name: ClassVar[str] = "backtest_target_lot_daily"
    primary_key: ClassVar[tuple[str, ...]] = (
        "run_id",
        "strategy_id",
        "signal_object_id",
        "trade_date",
    )
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["backtest_target_lot_daily.v1"] = (
        "backtest_target_lot_daily.v1"
    )
    run_id: NonEmptyStr
    strategy_id: NonEmptyStr
    product_code: NonEmptyStr
    universe: NonEmptyStr
    signal_object_id: NonEmptyStr
    trade_date: date
    execution_date: date
    target_contract: NonEmptyStr | None = None
    target_lots: int
    score: float
    is_blocked: bool = False
    block_reason: str | None = None
    execution_eligible: bool = True
    target_rule_version: NonEmptyStr
    input_snapshot_ids: Annotated[list[SnapshotId], Field(min_length=1)]

    @model_validator(mode="after")
    def _target_lot_row_is_explicit(self) -> BacktestTargetLotDailyRow:
        if self.execution_date <= self.trade_date:
            raise ValueError("execution_date must be after trade_date")
        if self.is_blocked and not self.block_reason:
            raise ValueError("blocked target lot rows must include block_reason")
        if self.is_blocked and self.execution_eligible:
            raise ValueError("blocked target lot rows cannot be execution_eligible")
        if not self.is_blocked and not self.target_contract:
            raise ValueError("unblocked target lot rows must include target_contract")
        return self


class ArchiveRunManifestRow(SchemaRow):
    """archive_run_manifest row."""

    table_name: ClassVar[str] = "archive_run_manifest"
    primary_key: ClassVar[tuple[str, ...]] = ("run_id",)
    lineage_fields: ClassVar[tuple[str, ...]] = ("input_snapshot_ids",)

    schema_version: Literal["archive_run_manifest.v1"] = "archive_run_manifest.v1"
    run_id: NonEmptyStr
    parent_run_id: str | None = None
    run_type: NonEmptyStr
    git_sha: NonEmptyStr
    config_hash: NonEmptyStr
    env_hash: NonEmptyStr
    input_snapshot_ids: list[SnapshotId] = Field(default_factory=list)
    started_at_utc: datetime
    ended_at_utc: datetime | None = None
    status: Literal["pending", "running", "success", "failed", "partial"]
    row_counts: dict[str, NonNegativeInt] = Field(default_factory=dict)
    artifact_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ended_after_started(self) -> ArchiveRunManifestRow:
        if self.ended_at_utc is not None and self.ended_at_utc < self.started_at_utc:
            raise ValueError("ended_at_utc must be >= started_at_utc")
        return self


TABLE_SCHEMAS: dict[str, type[SchemaRow]] = {
    schema.table_name: schema
    for schema in (
        CoreContractMasterRow,
        CoreContractRuleVersionRow,
        CoreTradingCalendarRow,
        CoreQuoteDailyRow,
        CoreOptionQuoteDailyRow,
        CoreSettlementParamDailyRow,
        CoreChainMapDailyRow,
        CoreTradeMappingDailyRow,
        ResearchContinuousPriceDailyRow,
        ResearchFactorValueDailyRow,
        ResearchFactorDiagnosticDailyRow,
        ResearchForwardReturnDailyRow,
        ResearchFactorEvaluationRow,
        ResearchMultifactorScoreDailyRow,
        BacktestTargetLotDailyRow,
        ArchiveRunManifestRow,
    )
}


def schema_for_table(table_name: str) -> type[SchemaRow]:
    """Return the registered schema class for a table name."""
    try:
        return TABLE_SCHEMAS[table_name]
    except KeyError as exc:
        known = ", ".join(sorted(TABLE_SCHEMAS))
        raise SchemaValidationError(f"unknown table schema {table_name!r}; known: {known}") from exc


def validate_row(table_name: str, row: dict[str, Any]) -> SchemaRow:
    """Validate one mapping against a registered row schema."""
    schema = schema_for_table(table_name)
    try:
        return schema.model_validate(row)
    except ValidationError as exc:
        raise SchemaValidationError(f"{table_name} row failed validation: {exc}") from exc


def validate_rows(table_name: str, rows: Iterable[dict[str, Any]]) -> list[SchemaRow]:
    """Validate several mappings against a registered row schema."""
    return [validate_row(table_name, row) for row in rows]


def table_contract(table_name: str) -> dict[str, object]:
    """Return compact metadata for a registered table contract."""
    schema = schema_for_table(table_name)
    return {
        "table_name": schema.table_name,
        "primary_key": list(schema.primary_key),
        "required_fields": sorted(_required_fields(schema)),
        "version_fields": list(schema.version_fields),
        "lineage_fields": list(schema.lineage_fields),
    }


def _required_fields(schema: type[SchemaRow]) -> set[str]:
    return {
        name
        for name, field in schema.model_fields.items()
        if field.is_required() and name not in {"schema_version"}
    }
