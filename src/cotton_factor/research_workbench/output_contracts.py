"""R10 downstream factor diagnostic output contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import schema_for_table, table_contract

PRODUCT_CODE = "CF"
CONTRACT_VERSION = "R10.factor_diagnostics_output_contract.v1"
OUTPUT_CONTRACT_DIR = "output_contracts"
FACTOR_OUTPUT_DIR = "factors"
FACTOR_VALUE_TABLE = "research_factor_value_daily"
FACTOR_DIAGNOSTIC_TABLE = "research_factor_diagnostic_daily"
FACTOR_IDS_BY_FAMILY = {
    "momentum": "mom_20_v1",
    "carry": "carry_nf_v1",
    "curve_slope": "curve_slope_v1",
    "oi_pressure": "oi_pressure_v1",
}
SIGNAL_STATES = ("long", "short", "neutral", "unknown")


@dataclass(frozen=True)
class FactorOutputArtifactContract:
    """One stable artifact contract for downstream factor diagnostics."""

    artifact_id: str
    table_name: str | None
    producer_tasks: tuple[str, ...]
    consumer_tasks: tuple[str, ...]
    path_templates: tuple[str, ...]
    required: bool
    description: str
    schema: dict[str, object] | None = None
    fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable artifact contract."""
        return {
            "artifact_id": self.artifact_id,
            "table_name": self.table_name,
            "producer_tasks": list(self.producer_tasks),
            "consumer_tasks": list(self.consumer_tasks),
            "path_templates": list(self.path_templates),
            "required": self.required,
            "description": self.description,
            "schema": self.schema,
            "fields": list(self.fields),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class FactorOutputContractResult:
    """Result of writing the R10 output contract files."""

    product_code: str
    contract_version: str
    json_path: Path
    markdown_path: Path
    artifacts: tuple[FactorOutputArtifactContract, ...]
    factor_ids: tuple[str, ...]
    signal_states: tuple[str, ...]
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "contract_version": self.contract_version,
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "artifact_count": len(self.artifacts),
            "artifact_ids": [artifact.artifact_id for artifact in self.artifacts],
            "factor_ids": list(self.factor_ids),
            "signal_states": list(self.signal_states),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_factor_output_contract(
    *,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
) -> FactorOutputContractResult:
    """Write the R10 CF factor diagnostic output contract."""
    artifacts = factor_output_artifact_contracts()
    json_path = _json_path(output_dir=output_dir)
    markdown_path = _markdown_path(report_output_dir=report_output_dir)
    result = FactorOutputContractResult(
        product_code=PRODUCT_CODE,
        contract_version=CONTRACT_VERSION,
        json_path=json_path,
        markdown_path=markdown_path,
        artifacts=artifacts,
        factor_ids=tuple(FACTOR_IDS_BY_FAMILY.values()),
        signal_states=SIGNAL_STATES,
        human_review_required=(
            "factor_thresholds",
            "carry_tenor_rule",
            "curve_slope_far_leg_rule",
            "oi_pressure_prior_contract_matching",
        ),
    )
    _write_json(json_path=json_path, result=result)
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def factor_output_artifact_contracts() -> tuple[FactorOutputArtifactContract, ...]:
    """Return stable artifact contracts for R11-R14 without computing factors."""
    # R10 只定义后续输出契约，不读取原始交易所文件，也不计算任何因子值。
    factor_value_schema = _schema_contract(FACTOR_VALUE_TABLE)
    diagnostic_schema = _schema_contract(FACTOR_DIAGNOSTIC_TABLE)
    return (
        FactorOutputArtifactContract(
            artifact_id="cf_factor_value_daily",
            table_name=FACTOR_VALUE_TABLE,
            producer_tasks=("R11", "R12", "R13"),
            consumer_tasks=("R14", "R15", "R16", "R17", "R19"),
            path_templates=(
                "data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet",
                "data/research/CF/factors/CF_{start}_{end}_factor_value_daily.csv",
            ),
            required=True,
            description=(
                "Per-factor daily values for momentum, carry, curve slope, and OI pressure."
            ),
            schema=factor_value_schema,
            notes=(
                "Rows must carry non-empty input_snapshot_ids.",
                (
                    "Continuous-price factors may use signal objects; "
                    "execution/backtest outputs must not."
                ),
            ),
        ),
        FactorOutputArtifactContract(
            artifact_id="cf_factor_diagnostic_daily",
            table_name=FACTOR_DIAGNOSTIC_TABLE,
            producer_tasks=("R14",),
            consumer_tasks=("R16", "R17", "R19"),
            path_templates=(
                "data/research/CF/factors/CF_{start}_{end}_factor_diagnostic_daily.parquet",
                "data/research/CF/factors/CF_{start}_{end}_factor_diagnostic_daily.csv",
            ),
            required=True,
            description=(
                "Daily diagnostic state table that turns factor values into "
                "long, short, neutral, or unknown research states."
            ),
            schema=diagnostic_schema,
            notes=(
                "Unknown is a first-class state and must not be silently converted to neutral.",
                "Human-review flags stay visible until business thresholds are approved.",
            ),
        ),
        FactorOutputArtifactContract(
            artifact_id="cf_factor_diagnostic_report",
            table_name=None,
            producer_tasks=("R14",),
            consumer_tasks=("R19",),
            path_templates=(
                "reports/research/factors/CF_{start}_{end}_factor_diagnostics.md",
            ),
            required=True,
            description="Human-readable factor diagnostic report for analyst review.",
            fields=(
                "run_id",
                "date_range",
                "factor_summary",
                "unknown_state_rows",
                "warning_flags",
                "human_review_required",
            ),
            notes=("The report is an analyst-facing view, not an execution instruction.",),
        ),
        FactorOutputArtifactContract(
            artifact_id="cf_factor_warning_log",
            table_name=None,
            producer_tasks=("R11", "R12", "R13", "R14"),
            consumer_tasks=("R14", "R19"),
            path_templates=(
                "data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv",
            ),
            required=True,
            description="Warning log for missing inputs, skipped rows, and review gates.",
            fields=(
                "run_id",
                "factor_id",
                "trade_date",
                "severity",
                "warning_code",
                "warning_message",
                "human_review_required",
                "input_snapshot_ids",
            ),
            notes=(
                "Missing inputs must produce warning rows instead of silent zero values.",
                "Warnings with unknown business rules must use HUMAN_REVIEW_REQUIRED.",
            ),
        ),
    )


def _schema_contract(table_name: str) -> dict[str, object]:
    contract = table_contract(table_name)
    schema = schema_for_table(table_name)
    # 字段顺序跟 schema 保持一致，便于人工核对 CSV/Parquet 输出。
    return {
        **contract,
        "all_fields": list(schema.model_fields),
    }


def _write_json(*, json_path: Path, result: FactorOutputContractResult) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "product_code": result.product_code,
        "contract_version": result.contract_version,
        "frequency": "daily",
        "factor_ids": list(result.factor_ids),
        "signal_states": list(result.signal_states),
        "artifacts": [artifact.to_dict() for artifact in result.artifacts],
        "human_review_required": list(result.human_review_required),
        "research_rules": [
            "Research functions must read normalized core/research artifacts only.",
            "T-day post-settlement factor diagnostics are research signals for T+1 or later use.",
            "Continuous contracts are signal objects only.",
            "Missing inputs must surface as warning or unknown states.",
        ],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(*, markdown_path: Path, result: FactorOutputContractResult) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CF Factor Diagnostic Output Contract",
        "",
        f"- Product: `{result.product_code}`",
        f"- Contract version: `{result.contract_version}`",
        "- Frequency: `daily`",
        f"- Machine-readable contract: `{result.json_path}`",
        f"- Factor IDs: `{', '.join(result.factor_ids)}`",
        f"- Signal states: `{', '.join(result.signal_states)}`",
        "",
        "## Artifacts",
        "",
        "| Artifact | Table | Producers | Consumers | Required | Paths |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for artifact in result.artifacts:
        lines.append(
            "| "
            + " | ".join(
                [
                    artifact.artifact_id,
                    artifact.table_name or "",
                    ", ".join(artifact.producer_tasks),
                    ", ".join(artifact.consumer_tasks),
                    str(artifact.required),
                    "<br>".join(f"`{path}`" for path in artifact.path_templates),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Schema Highlights", ""])
    for artifact in result.artifacts:
        if artifact.schema is None:
            lines.append(f"- `{artifact.artifact_id}` fields: `{', '.join(artifact.fields)}`")
            continue
        all_fields = artifact.schema["all_fields"]
        primary_key = artifact.schema["primary_key"]
        lineage_fields = artifact.schema["lineage_fields"]
        lines.append(
            f"- `{artifact.table_name}` primary key `{', '.join(primary_key)}`, "
            f"lineage `{', '.join(lineage_fields)}`, fields `{', '.join(all_fields)}`."
        )

    lines.extend(["", "## Research Rules", ""])
    lines.extend(
        [
            "- Research functions must read normalized core/research artifacts only.",
            "- T-day post-settlement factor diagnostics are research signals for T+1 or later use.",
            "- Continuous contracts are signal objects only.",
            "- Missing inputs must surface as warning or unknown states.",
            "- Unknown business rules must stay marked as `HUMAN_REVIEW_REQUIRED`.",
        ]
    )
    lines.extend(["", "## Human Review Required", ""])
    for item in result.human_review_required:
        lines.append(f"- `{item}`")

    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _json_path(*, output_dir: Path | None) -> Path:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_CONTRACT_DIR
    return root / "CF_factor_diagnostics_output_contract.json"


def _markdown_path(*, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_CONTRACT_DIR
    return root / "CF_factor_diagnostics_output_contract.md"
