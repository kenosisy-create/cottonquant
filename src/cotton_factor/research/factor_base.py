"""Factor framework primitives for research-derived tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from cotton_factor.common.exceptions import (
    FactorDependencyError,
    FactorRegistryError,
)
from cotton_factor.common.paths import project_root
from cotton_factor.core.schemas import (
    TABLE_SCHEMAS,
    ResearchFactorValueDailyRow,
    SchemaRow,
    schema_for_table,
)

TODO_REQUIRES_HUMAN_REVIEW = "TODO_REQUIRES_HUMAN_REVIEW"
DEFAULT_FACTOR_REGISTRY_PATH = project_root() / "configs" / "factor_registry.yaml"


@dataclass(frozen=True)
class FactorDefinition:
    """Metadata and declared inputs for one registered factor."""

    factor_id: str
    family: str
    version: str
    owner: str
    status: str
    required_inputs: tuple[str, ...]

    @property
    def human_review_required(self) -> tuple[str, ...]:
        """Return config fields that still need explicit human review."""
        items: list[str] = []
        if self.owner == TODO_REQUIRES_HUMAN_REVIEW:
            items.append("owner")
        if TODO_REQUIRES_HUMAN_REVIEW in self.status:
            items.append("status")
        return tuple(items)


@dataclass(frozen=True)
class FactorRegistry:
    """Loaded factor registry keyed by factor_id."""

    factors: Mapping[str, FactorDefinition]

    def get(self, factor_id: str) -> FactorDefinition:
        """Return one factor definition or fail with known ids."""
        try:
            return self.factors[factor_id]
        except KeyError as exc:
            known = ", ".join(sorted(self.factors))
            raise FactorRegistryError(
                f"unknown factor_id {factor_id!r}; known factors: {known}"
            ) from exc


@dataclass(frozen=True)
class FactorInputBundle:
    """Normalized table bundle supplied to factor computations."""

    tables: Mapping[str, Sequence[SchemaRow]]

    @property
    def available_tables(self) -> tuple[str, ...]:
        """Return available normalized table names."""
        return tuple(sorted(self.tables))

    def rows(self, table_name: str) -> Sequence[SchemaRow]:
        """Return rows for a table after dependency validation."""
        try:
            return self.tables[table_name]
        except KeyError as exc:
            known = ", ".join(self.available_tables)
            raise FactorDependencyError(
                f"missing normalized input table {table_name!r}; available: {known}"
            ) from exc


@dataclass(frozen=True)
class FactorObservation:
    """One factor observation before row-schema wrapping."""

    signal_object_id: str
    trade_date: date
    raw_value: float
    input_snapshot_ids: tuple[str, ...]
    processed_value: float | None = None


@dataclass(frozen=True)
class FactorResult:
    """Validated factor output."""

    definition: FactorDefinition
    rows: list[ResearchFactorValueDailyRow]
    warnings: list[str]


class FactorSpec(Protocol):
    """Protocol implemented by concrete D12/D13 factor calculators."""

    definition: FactorDefinition

    def compute(
        self,
        *,
        inputs: FactorInputBundle,
        run_id: str,
        product_code: str,
        universe: str,
    ) -> FactorResult:
        """Compute a factor from normalized inputs only."""


def load_factor_registry(path: Path | None = None) -> FactorRegistry:
    """Load and validate the local factor registry."""
    registry_path = path or DEFAULT_FACTOR_REGISTRY_PATH
    raw_config = _load_factor_registry_yaml(registry_path)
    factors_config = raw_config.get("factors")
    if not isinstance(factors_config, dict) or not factors_config:
        raise FactorRegistryError(f"factor registry must define non-empty factors: {registry_path}")

    factors: dict[str, FactorDefinition] = {}
    for factor_id, payload in factors_config.items():
        if not isinstance(payload, dict):
            raise FactorRegistryError(f"{factor_id}: factor definition must be a mapping")
        definition = _coerce_factor_definition(factor_id=factor_id, payload=payload)
        _validate_required_input_names(definition)
        factors[definition.factor_id] = definition

    return FactorRegistry(factors=factors)


def validate_factor_dependencies(
    definition: FactorDefinition,
    inputs: FactorInputBundle,
    *,
    require_non_empty: bool = True,
) -> None:
    """Validate that a factor receives all declared normalized inputs."""
    missing = [
        table_name for table_name in definition.required_inputs if table_name not in inputs.tables
    ]
    if missing:
        available = ", ".join(inputs.available_tables)
        raise FactorDependencyError(
            f"{definition.factor_id}: missing required input tables {missing}; "
            f"available: {available}"
        )

    empty_tables = [
        table_name
        for table_name in definition.required_inputs
        if require_non_empty and len(inputs.tables[table_name]) == 0
    ]
    if empty_tables:
        raise FactorDependencyError(
            f"{definition.factor_id}: required input tables are empty {empty_tables}"
        )

    for table_name in definition.required_inputs:
        expected_schema = schema_for_table(table_name)
        bad_rows = [
            index
            for index, row in enumerate(inputs.tables[table_name])
            if not isinstance(row, expected_schema)
        ]
        if bad_rows:
            raise FactorDependencyError(
                f"{definition.factor_id}: {table_name} rows failed schema type check "
                f"at indexes {bad_rows}"
            )


def build_factor_rows(
    *,
    definition: FactorDefinition,
    run_id: str,
    product_code: str,
    universe: str,
    observations: Sequence[FactorObservation],
) -> list[ResearchFactorValueDailyRow]:
    """Wrap raw factor observations into validated research_factor_value_daily rows."""
    rows: list[ResearchFactorValueDailyRow] = []
    for observation in observations:
        # 因子值必须带上归因快照；这里复用 D5 schema，让空 lineage 在写入前就失败。
        try:
            rows.append(
                ResearchFactorValueDailyRow(
                    run_id=run_id,
                    factor_id=definition.factor_id,
                    factor_version=definition.version,
                    product_code=product_code.upper(),
                    universe=universe,
                    signal_object_id=observation.signal_object_id,
                    trade_date=observation.trade_date,
                    raw_value=observation.raw_value,
                    processed_value=observation.processed_value,
                    input_snapshot_ids=list(observation.input_snapshot_ids),
                )
            )
        except ValidationError as exc:
            raise FactorDependencyError(
                f"{definition.factor_id}: factor observation failed row validation"
            ) from exc
    return rows


def _coerce_factor_definition(
    *,
    factor_id: str,
    payload: Mapping[str, object],
) -> FactorDefinition:
    required_fields = {"family", "version", "owner", "status", "required_inputs"}
    missing = sorted(required_fields - set(payload))
    if missing:
        raise FactorRegistryError(f"{factor_id}: missing required fields {missing}")

    required_inputs = payload["required_inputs"]
    if not isinstance(required_inputs, list) or not required_inputs:
        raise FactorRegistryError(f"{factor_id}: required_inputs must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in required_inputs):
        raise FactorRegistryError(f"{factor_id}: required_inputs must contain non-empty strings")

    return FactorDefinition(
        factor_id=_require_non_empty_string(factor_id, field_name="factor_id"),
        family=_require_non_empty_string(payload["family"], field_name=f"{factor_id}.family"),
        version=_require_non_empty_string(payload["version"], field_name=f"{factor_id}.version"),
        owner=_require_non_empty_string(payload["owner"], field_name=f"{factor_id}.owner"),
        status=_require_non_empty_string(payload["status"], field_name=f"{factor_id}.status"),
        required_inputs=tuple(required_inputs),
    )


def _validate_required_input_names(definition: FactorDefinition) -> None:
    unknown = [
        table_name
        for table_name in definition.required_inputs
        if table_name not in TABLE_SCHEMAS
    ]
    if unknown:
        known = ", ".join(sorted(TABLE_SCHEMAS))
        raise FactorRegistryError(
            f"{definition.factor_id}: unknown required input tables {unknown}; known: {known}"
        )

    raw_like = [
        table_name
        for table_name in definition.required_inputs
        if table_name.startswith("raw_")
    ]
    if raw_like:
        # 研究层不得读取原始交易所文件；注册表只允许声明 core/research 规范化表。
        raise FactorRegistryError(
            f"{definition.factor_id}: research factors cannot depend on raw tables {raw_like}"
        )


def _require_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise FactorRegistryError(f"{field_name} must be a non-empty string")
    return value


def _load_factor_registry_yaml(path: Path) -> dict[str, object]:
    """Parse the narrow YAML subset used by configs/factor_registry.yaml."""
    if not path.exists() or not path.is_file():
        raise FactorRegistryError(f"factor registry not found: {path}")

    result: dict[str, object] = {}
    current_section: str | None = None
    current_factor_id: str | None = None
    current_list_key: str | None = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in raw_line:
            raise FactorRegistryError(f"tabs are not supported at {path}:{line_number}")

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            if stripped != "factors:":
                raise FactorRegistryError(f"unsupported top-level key at {path}:{line_number}")
            result["factors"] = {}
            current_section = "factors"
            current_factor_id = None
            current_list_key = None
            continue

        if current_section != "factors":
            raise FactorRegistryError(f"nested content before factors at {path}:{line_number}")

        factors = result["factors"]
        if not isinstance(factors, dict):
            raise FactorRegistryError(f"invalid factors section at {path}:{line_number}")

        if indent == 2 and stripped.endswith(":"):
            current_factor_id = stripped[:-1]
            if not current_factor_id:
                raise FactorRegistryError(f"empty factor id at {path}:{line_number}")
            factors[current_factor_id] = {}
            current_list_key = None
            continue

        if current_factor_id is None:
            raise FactorRegistryError(f"factor field without factor id at {path}:{line_number}")
        factor_payload = factors[current_factor_id]
        if not isinstance(factor_payload, dict):
            raise FactorRegistryError(f"invalid factor payload at {path}:{line_number}")

        if indent == 4:
            if ":" not in stripped:
                raise FactorRegistryError(f"expected key-value at {path}:{line_number}")
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            if not key:
                raise FactorRegistryError(f"empty factor field at {path}:{line_number}")
            if not value:
                factor_payload[key] = []
                current_list_key = key
            else:
                factor_payload[key] = _parse_registry_scalar(value)
                current_list_key = None
            continue

        if indent == 6 and stripped.startswith("- "):
            if current_list_key is None:
                raise FactorRegistryError(f"list item without key at {path}:{line_number}")
            target = factor_payload.get(current_list_key)
            if not isinstance(target, list):
                raise FactorRegistryError(f"list target is invalid at {path}:{line_number}")
            target.append(_parse_registry_scalar(stripped[2:].strip()))
            continue

        raise FactorRegistryError(f"unsupported indentation at {path}:{line_number}")

    return result


def _parse_registry_scalar(value: str) -> object:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_registry_scalar(part.strip()) for part in inner.split(",")]
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
