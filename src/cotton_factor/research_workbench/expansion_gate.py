"""R52 expansion gate for non-CF research workbench scope."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
EXPANSION_GATE_REPORT_DIR = "expansion_gate"
R22_GATE_VERSION = "R22"
R52_GATE_VERSION = "R52"
SUPPORTED_GATE_VERSIONS = (R22_GATE_VERSION, R52_GATE_VERSION)
HUMAN_REVIEW_FIELDS = (
    "candidate_contract_rules",
    "candidate_raw_source_convention",
    "candidate_field_mapping",
    "candidate_data_quality_rules",
    "candidate_execution_boundary",
    "candidate_cost_and_slippage_assumptions",
    "cf_mainline_evidence_interpretation",
    "option_signal_filter_rules_before_expansion",
    "fundamental_data_source_and_signal_rules",
    "publish_pack_readability_and_compliance",
    "product_expansion_go_no_go",
)


@dataclass(frozen=True)
class ExpansionGateRequirement:
    """One expansion gate requirement."""

    requirement_id: str
    status: str
    message: str
    evidence: dict[str, Any]

    @property
    def blocking(self) -> bool:
        """Return whether this requirement blocks expansion."""
        return self.status == "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable requirement row."""
        return {
            "requirement_id": self.requirement_id,
            "status": self.status,
            "blocking": self.blocking,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ResearchExpansionGateResult:
    """Result of writing the expansion gate report."""

    product_code: str
    run_id: str
    gate_version: str
    candidate_scope: str
    status: str
    requirements: tuple[ExpansionGateRequirement, ...]
    markdown_path: Path
    json_path: Path
    pipeline_json_path: Path | None
    replay_json_path: Path | None
    historical_evidence_manifest_path: Path | None
    event_explanation_manifest_path: Path | None
    signal_matrix_manifest_path: Path | None
    publish_pack_manifest_path: Path | None
    product_registry_manifest_path: Path | None
    fundamental_contract_manifest_path: Path | None
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether CF validation evidence clears hard blockers."""
        return not any(requirement.blocking for requirement in self.requirements)

    def to_summary(self) -> dict[str, Any]:
        """Return a compact CLI summary."""
        blocked = [
            requirement.requirement_id
            for requirement in self.requirements
            if requirement.blocking
        ]
        pipeline_path = (
            None if self.pipeline_json_path is None else str(self.pipeline_json_path)
        )
        replay_path = None if self.replay_json_path is None else str(self.replay_json_path)
        r52_paths = {
            "historical_evidence_manifest_path": _optional_path(
                self.historical_evidence_manifest_path
            ),
            "event_explanation_manifest_path": _optional_path(
                self.event_explanation_manifest_path
            ),
            "signal_matrix_manifest_path": _optional_path(self.signal_matrix_manifest_path),
            "publish_pack_manifest_path": _optional_path(self.publish_pack_manifest_path),
            "product_registry_manifest_path": _optional_path(
                self.product_registry_manifest_path
            ),
            "fundamental_contract_manifest_path": _optional_path(
                self.fundamental_contract_manifest_path
            ),
        }
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "gate_version": self.gate_version,
            "candidate_scope": self.candidate_scope,
            "status": self.status,
            "passed": self.passed,
            "blocked_requirements": blocked,
            "requirement_count": len(self.requirements),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "pipeline_json_path": pipeline_path,
            "replay_json_path": replay_path,
            "r52_evidence_paths": r52_paths,
            "human_review_required": list(self.human_review_required),
        }


def build_cf_expansion_gate(
    *,
    candidate_scope: str = "SR_AP_OR_EXTERNAL_DATA",
    pipeline_json_path: Path | None = None,
    replay_json_path: Path | None = None,
    historical_evidence_manifest_path: Path | None = None,
    event_explanation_manifest_path: Path | None = None,
    signal_matrix_manifest_path: Path | None = None,
    publish_pack_manifest_path: Path | None = None,
    product_registry_manifest_path: Path | None = None,
    fundamental_contract_manifest_path: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    gate_version: str = R52_GATE_VERSION,
) -> ResearchExpansionGateResult:
    """Define and evaluate the gate before non-CF research expansion."""
    cleaned_scope = candidate_scope.strip()
    if not cleaned_scope:
        raise ResearchWorkbenchError("candidate_scope must not be empty")
    cleaned_gate_version = gate_version.strip().upper()
    if cleaned_gate_version not in SUPPORTED_GATE_VERSIONS:
        raise ResearchWorkbenchError(
            f"gate_version must be one of {SUPPORTED_GATE_VERSIONS}, got {gate_version!r}"
        )
    active_run_id = run_id or _default_run_id(cleaned_scope, cleaned_gate_version)
    pipeline_payload = (
        _load_json_object(pipeline_json_path, context="R20 pipeline JSON")
        if pipeline_json_path is not None
        else None
    )
    replay_payload = (
        _load_json_object(replay_json_path, context="R21 replay JSON")
        if replay_json_path is not None
        else None
    )
    r52_payloads = _load_r52_payloads(
        gate_version=cleaned_gate_version,
        historical_evidence_manifest_path=historical_evidence_manifest_path,
        event_explanation_manifest_path=event_explanation_manifest_path,
        signal_matrix_manifest_path=signal_matrix_manifest_path,
        publish_pack_manifest_path=publish_pack_manifest_path,
        product_registry_manifest_path=product_registry_manifest_path,
        fundamental_contract_manifest_path=fundamental_contract_manifest_path,
    )
    requirements = tuple(
        _requirements(
            gate_version=cleaned_gate_version,
            candidate_scope=cleaned_scope,
            pipeline_json_path=pipeline_json_path,
            pipeline_payload=pipeline_payload,
            replay_json_path=replay_json_path,
            replay_payload=replay_payload,
            historical_evidence_manifest_path=historical_evidence_manifest_path,
            historical_evidence_payload=r52_payloads["historical_evidence"],
            event_explanation_manifest_path=event_explanation_manifest_path,
            event_explanation_payload=r52_payloads["event_explanation"],
            signal_matrix_manifest_path=signal_matrix_manifest_path,
            signal_matrix_payload=r52_payloads["signal_matrix"],
            publish_pack_manifest_path=publish_pack_manifest_path,
            publish_pack_payload=r52_payloads["publish_pack"],
            product_registry_manifest_path=product_registry_manifest_path,
            product_registry_payload=r52_payloads["product_registry"],
            fundamental_contract_manifest_path=fundamental_contract_manifest_path,
            fundamental_contract_payload=r52_payloads["fundamental_contract"],
        )
    )
    status = _gate_status(requirements)
    paths = _output_paths(
        run_id=active_run_id,
        candidate_scope=cleaned_scope,
        report_output_dir=report_output_dir,
    )

    # R52 只检查 CF 主线证据；不会读取或接入 SR/AP/外部数据，避免绕过 CF-first 路径。
    result = ResearchExpansionGateResult(
        product_code=PRODUCT_CODE,
        run_id=active_run_id,
        gate_version=cleaned_gate_version,
        candidate_scope=cleaned_scope,
        status=status,
        requirements=requirements,
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        pipeline_json_path=pipeline_json_path,
        replay_json_path=replay_json_path,
        historical_evidence_manifest_path=historical_evidence_manifest_path,
        event_explanation_manifest_path=event_explanation_manifest_path,
        signal_matrix_manifest_path=signal_matrix_manifest_path,
        publish_pack_manifest_path=publish_pack_manifest_path,
        product_registry_manifest_path=product_registry_manifest_path,
        fundamental_contract_manifest_path=fundamental_contract_manifest_path,
        human_review_required=HUMAN_REVIEW_FIELDS,
    )
    _write_json(result=result)
    _write_markdown(result=result)
    return result


def _requirements(
    *,
    gate_version: str,
    candidate_scope: str,
    pipeline_json_path: Path | None,
    pipeline_payload: dict[str, Any] | None,
    replay_json_path: Path | None,
    replay_payload: dict[str, Any] | None,
    historical_evidence_manifest_path: Path | None,
    historical_evidence_payload: dict[str, Any] | None,
    event_explanation_manifest_path: Path | None,
    event_explanation_payload: dict[str, Any] | None,
    signal_matrix_manifest_path: Path | None,
    signal_matrix_payload: dict[str, Any] | None,
    publish_pack_manifest_path: Path | None,
    publish_pack_payload: dict[str, Any] | None,
    product_registry_manifest_path: Path | None,
    product_registry_payload: dict[str, Any] | None,
    fundamental_contract_manifest_path: Path | None,
    fundamental_contract_payload: dict[str, Any] | None,
) -> list[ExpansionGateRequirement]:
    requirements = [
        _candidate_scope_requirement(candidate_scope),
        _pipeline_evidence_requirement(pipeline_json_path, pipeline_payload),
        _replay_evidence_requirement(replay_json_path, replay_payload),
        _pipeline_replay_match_requirement(
            pipeline_json_path=pipeline_json_path,
            replay_payload=replay_payload,
        ),
    ]
    if gate_version == R52_GATE_VERSION:
        requirements.extend(
            [
                _historical_evidence_requirement(
                    historical_evidence_manifest_path,
                    historical_evidence_payload,
                ),
                _event_explanation_requirement(
                    event_explanation_manifest_path,
                    event_explanation_payload,
                ),
                _option_linkage_requirement(
                    signal_matrix_manifest_path,
                    signal_matrix_payload,
                ),
                _publish_pack_requirement(
                    publish_pack_manifest_path,
                    publish_pack_payload,
                ),
                _product_registry_requirement(
                    product_registry_manifest_path,
                    product_registry_payload,
                ),
                _fundamental_contract_requirement(
                    fundamental_contract_manifest_path,
                    fundamental_contract_payload,
                ),
            ]
        )
    requirements.append(_human_review_requirement(gate_version))
    return requirements


def _candidate_scope_requirement(candidate_scope: str) -> ExpansionGateRequirement:
    return ExpansionGateRequirement(
        requirement_id="candidate_scope_declared",
        status="PASS",
        message="candidate expansion scope is explicitly declared",
        evidence={"candidate_scope": candidate_scope},
    )


def _historical_evidence_requirement(
    manifest_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    return _manifest_requirement(
        requirement_id="cf_r41_historical_evidence_ready",
        manifest_path=manifest_path,
        payload=payload,
        expected_report_type="historical_evidence_pack",
        pass_message="R41 historical multi-factor evidence is present",
        validators=(
            _payload_field_is_true(
                "forward_returns_are_validation_labels",
                "R41 forward returns must be marked as historical validation labels",
            ),
        ),
    )


def _event_explanation_requirement(
    manifest_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    return _manifest_requirement(
        requirement_id="cf_r42_event_explanation_ready",
        manifest_path=manifest_path,
        payload=payload,
        expected_report_type="historical_event_explanation",
        pass_message="R42 historical event explanation is present",
        validators=(
            _payload_field_is_true(
                "forward_returns_are_event_labels",
                "R42 event returns must be marked as after-the-fact labels",
            ),
        ),
    )


def _option_linkage_requirement(
    manifest_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    return _manifest_requirement(
        requirement_id="cf_r49_option_linkage_ready",
        manifest_path=manifest_path,
        payload=payload,
        expected_report_type="signal_matrix",
        pass_message="R49 option linkage is present in the signal matrix",
        validators=(
            _payload_field_is_false(
                "contains_forward_return_validation",
                "signal matrix must not contain forward-return validation labels",
            ),
            _payload_field_is_present(
                "option_factor_path",
                "signal matrix must reference the R48 option factor proxy path",
            ),
        ),
    )


def _publish_pack_requirement(
    manifest_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    return _manifest_requirement(
        requirement_id="cf_r45_publish_pack_ready",
        manifest_path=manifest_path,
        payload=payload,
        expected_report_type="publish_pack",
        pass_message="R45 publish pack is present",
        validators=(
            _payload_field_is_present(
                "chart_pack_zip_path",
                "publish pack must contain a chart_pack.zip path",
            ),
            _payload_path_exists(
                "chart_pack_zip_path",
                "publish pack chart_pack.zip must exist",
            ),
            _payload_field_is_present(
                "wechat_article_path",
                "publish pack must contain a WeChat article path",
            ),
        ),
    )


def _product_registry_requirement(
    manifest_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    return _manifest_requirement(
        requirement_id="cf_r50_product_registry_ready",
        manifest_path=manifest_path,
        payload=payload,
        expected_report_type="cf_product_research_registry",
        pass_message="R50 CF product registry is present",
        validators=(
            _payload_number_at_least(
                "futures_factor_count",
                4,
                "product registry must include the four core futures factors",
            ),
            _payload_number_at_least(
                "option_proxy_factor_count",
                6,
                "product registry must include the six option proxy factors",
            ),
        ),
    )


def _fundamental_contract_requirement(
    manifest_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    return _manifest_requirement(
        requirement_id="cf_r51_fundamental_contract_ready",
        manifest_path=manifest_path,
        payload=payload,
        expected_report_type="fundamental_data_contract",
        pass_message="R51 fundamental manual-input contract is present",
        validators=(
            _payload_field_equals(
                "fundamental_signal_status",
                "not_connected",
                "R51 fundamental inputs must remain not_connected before review",
            ),
            _payload_field_in(
                "status",
                {"MISSING_FUNDAMENTAL_INPUT", "FUNDAMENTAL_INPUT_PRESENT_CONTRACT_ONLY"},
                "R51 status must be an explicit contract state",
            ),
        ),
    )


def _pipeline_evidence_requirement(
    pipeline_json_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    if pipeline_json_path is None:
        return _blocked(
            "cf_r20_pipeline_completed",
            "R20 pipeline JSON is required before expansion",
            {"pipeline_json_path": None},
        )
    if payload is None:
        return _blocked(
            "cf_r20_pipeline_completed",
            "R20 pipeline JSON could not be loaded",
            {"pipeline_json_path": str(pipeline_json_path)},
        )
    status = payload.get("status")
    trade_date = payload.get("trade_date")
    if status != "COMPLETED":
        return _blocked(
            "cf_r20_pipeline_completed",
            f"R20 pipeline status is {status!r}, not COMPLETED",
            {"pipeline_json_path": str(pipeline_json_path), "status": status},
        )
    return ExpansionGateRequirement(
        requirement_id="cf_r20_pipeline_completed",
        status="PASS",
        message="R20 CF pipeline completed",
        evidence={
            "pipeline_json_path": str(pipeline_json_path),
            "run_id": payload.get("run_id"),
            "trade_date": trade_date,
        },
    )


def _manifest_requirement(
    *,
    requirement_id: str,
    manifest_path: Path | None,
    payload: dict[str, Any] | None,
    expected_report_type: str,
    pass_message: str,
    validators: tuple[Any, ...] = (),
) -> ExpansionGateRequirement:
    if manifest_path is None:
        return _blocked(
            requirement_id,
            f"{expected_report_type} manifest is required before expansion",
            {"manifest_path": None},
        )
    if payload is None:
        return _blocked(
            requirement_id,
            f"{expected_report_type} manifest could not be loaded",
            {"manifest_path": str(manifest_path)},
        )
    evidence = _manifest_evidence(manifest_path=manifest_path, payload=payload)
    if payload.get("product_code") != PRODUCT_CODE:
        return _blocked(
            requirement_id,
            f"{expected_report_type} product_code is not CF",
            evidence,
        )
    if payload.get("report_type") != expected_report_type:
        return _blocked(
            requirement_id,
            (
                f"manifest report_type is {payload.get('report_type')!r}, "
                f"not {expected_report_type!r}"
            ),
            evidence,
        )
    for validator in validators:
        problem = validator(payload)
        if problem is not None:
            return _blocked(requirement_id, problem, evidence)
    return ExpansionGateRequirement(
        requirement_id=requirement_id,
        status="PASS",
        message=pass_message,
        evidence=evidence,
    )


def _manifest_evidence(
    *,
    manifest_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "manifest_path": str(manifest_path),
        "report_type": payload.get("report_type"),
        "rule_version": payload.get("rule_version"),
        "run_id": payload.get("run_id"),
        "data_start": payload.get("data_start") or payload.get("start"),
        "data_end": (
            payload.get("data_end")
            or payload.get("end")
            or payload.get("latest_trade_date")
            or payload.get("data_asof")
        ),
        "status": payload.get("status"),
    }


def _payload_field_is_true(key: str, message: str) -> Any:
    def validate(payload: dict[str, Any]) -> str | None:
        if payload.get(key) is not True:
            return message
        return None

    return validate


def _payload_field_is_false(key: str, message: str) -> Any:
    def validate(payload: dict[str, Any]) -> str | None:
        if payload.get(key) is not False:
            return message
        return None

    return validate


def _payload_field_is_present(key: str, message: str) -> Any:
    def validate(payload: dict[str, Any]) -> str | None:
        value = payload.get(key)
        if value is None or value == "":
            return message
        return None

    return validate


def _payload_field_equals(key: str, expected: Any, message: str) -> Any:
    def validate(payload: dict[str, Any]) -> str | None:
        if payload.get(key) != expected:
            return message
        return None

    return validate


def _payload_field_in(key: str, expected: set[Any], message: str) -> Any:
    def validate(payload: dict[str, Any]) -> str | None:
        if payload.get(key) not in expected:
            return message
        return None

    return validate


def _payload_number_at_least(key: str, minimum: int | float, message: str) -> Any:
    def validate(payload: dict[str, Any]) -> str | None:
        try:
            value = float(payload.get(key))
        except (TypeError, ValueError):
            return message
        if value < minimum:
            return message
        return None

    return validate


def _payload_path_exists(key: str, message: str) -> Any:
    def validate(payload: dict[str, Any]) -> str | None:
        raw_path = payload.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            return message
        if not _manifest_referenced_path_exists(raw_path):
            return message
        return None

    return validate


def _replay_evidence_requirement(
    replay_json_path: Path | None,
    payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    if replay_json_path is None:
        return _blocked(
            "cf_r21_replay_passed",
            "R21 replay JSON is required before expansion",
            {"replay_json_path": None},
        )
    if payload is None:
        return _blocked(
            "cf_r21_replay_passed",
            "R21 replay JSON could not be loaded",
            {"replay_json_path": str(replay_json_path)},
        )
    if payload.get("passed") is not True:
        return _blocked(
            "cf_r21_replay_passed",
            "R21 replay did not pass",
            {
                "replay_json_path": str(replay_json_path),
                "passed": payload.get("passed"),
                "failed_checks": payload.get("failed_checks", []),
            },
        )
    if int(payload.get("missing_artifact_count", 0)) != 0:
        return _blocked(
            "cf_r21_replay_passed",
            "R21 replay has missing artifacts",
            {
                "replay_json_path": str(replay_json_path),
                "missing_artifact_count": payload.get("missing_artifact_count"),
            },
        )
    return ExpansionGateRequirement(
        requirement_id="cf_r21_replay_passed",
        status="PASS",
        message="R21 replay passed with preserved artifacts",
        evidence={
            "replay_json_path": str(replay_json_path),
            "run_id": payload.get("run_id"),
            "artifact_count": payload.get("artifact_count"),
        },
    )


def _pipeline_replay_match_requirement(
    *,
    pipeline_json_path: Path | None,
    replay_payload: dict[str, Any] | None,
) -> ExpansionGateRequirement:
    if pipeline_json_path is None or replay_payload is None:
        pipeline_path = None if pipeline_json_path is None else str(pipeline_json_path)
        return _blocked(
            "cf_r20_r21_evidence_linked",
            "R20 and R21 evidence must both be present",
            {
                "pipeline_json_path": pipeline_path,
                "replay_present": replay_payload is not None,
            },
        )
    replay_source = replay_payload.get("source_pipeline_json_path")
    if not isinstance(replay_source, str) or not replay_source:
        return _blocked(
            "cf_r20_r21_evidence_linked",
            "R21 replay JSON does not identify its source R20 pipeline JSON",
            {"source_pipeline_json_path": replay_source},
        )
    if _resolved_path(replay_source) != _resolved_path(str(pipeline_json_path)):
        return _blocked(
            "cf_r20_r21_evidence_linked",
            "R21 replay source does not match the provided R20 pipeline JSON",
            {
                "pipeline_json_path": str(pipeline_json_path),
                "replay_source_pipeline_json_path": replay_source,
            },
        )
    return ExpansionGateRequirement(
        requirement_id="cf_r20_r21_evidence_linked",
        status="PASS",
        message="R21 replay is linked to the provided R20 pipeline log",
        evidence={"source_pipeline_json_path": replay_source},
    )


def _human_review_requirement(gate_version: str) -> ExpansionGateRequirement:
    return ExpansionGateRequirement(
        requirement_id="candidate_rules_require_human_review",
        status="HUMAN_REVIEW_REQUIRED",
        message=(
            "candidate product or external data rules must be documented and reviewed "
            "before any real ingest begins"
        ),
        evidence={
            "gate_version": gate_version,
            "human_review_required": list(HUMAN_REVIEW_FIELDS),
        },
    )


def _blocked(
    requirement_id: str,
    message: str,
    evidence: dict[str, Any],
) -> ExpansionGateRequirement:
    return ExpansionGateRequirement(
        requirement_id=requirement_id,
        status="BLOCKED",
        message=message,
        evidence=evidence,
    )


def _gate_status(requirements: tuple[ExpansionGateRequirement, ...]) -> str:
    if any(requirement.blocking for requirement in requirements):
        return "BLOCKED_MISSING_CF_MAINLINE_EVIDENCE"
    if any(requirement.status == "HUMAN_REVIEW_REQUIRED" for requirement in requirements):
        return "HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION"
    return "READY_FOR_RESEARCH_PROTOTYPE"


def _load_r52_payloads(
    *,
    gate_version: str,
    historical_evidence_manifest_path: Path | None,
    event_explanation_manifest_path: Path | None,
    signal_matrix_manifest_path: Path | None,
    publish_pack_manifest_path: Path | None,
    product_registry_manifest_path: Path | None,
    fundamental_contract_manifest_path: Path | None,
) -> dict[str, dict[str, Any] | None]:
    if gate_version == R22_GATE_VERSION:
        return {
            "historical_evidence": None,
            "event_explanation": None,
            "signal_matrix": None,
            "publish_pack": None,
            "product_registry": None,
            "fundamental_contract": None,
        }
    return {
        "historical_evidence": _load_optional_json_object(
            historical_evidence_manifest_path,
            context="R41 historical evidence manifest",
        ),
        "event_explanation": _load_optional_json_object(
            event_explanation_manifest_path,
            context="R42 event explanation manifest",
        ),
        "signal_matrix": _load_optional_json_object(
            signal_matrix_manifest_path,
            context="R49 signal matrix manifest",
        ),
        "publish_pack": _load_optional_json_object(
            publish_pack_manifest_path,
            context="R45 publish pack manifest",
        ),
        "product_registry": _load_optional_json_object(
            product_registry_manifest_path,
            context="R50 product registry manifest",
        ),
        "fundamental_contract": _load_optional_json_object(
            fundamental_contract_manifest_path,
            context="R51 fundamental contract manifest",
        ),
    }


def _load_json_object(path: Path | None, *, context: str) -> dict[str, Any]:
    if path is None:
        raise ResearchWorkbenchError(f"{context} path is required")
    if not path.exists():
        raise ResearchWorkbenchError(f"{context} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResearchWorkbenchError(f"{context} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ResearchWorkbenchError(f"{context} must contain a JSON object: {path}")
    return payload


def _load_optional_json_object(path: Path | None, *, context: str) -> dict[str, Any] | None:
    if path is None:
        return None
    return _load_json_object(path, context=context)


def _resolved_path(raw_path: str) -> str:
    return str(Path(raw_path).resolve())


def _optional_path(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)


def _manifest_referenced_path_exists(raw_path: str) -> bool:
    path = Path(raw_path)
    if path.is_absolute():
        return path.exists()
    return (Path.cwd() / path).exists()


def _write_json(*, result: ResearchExpansionGateResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": utc_now().isoformat(),
        **result.to_summary(),
        "requirements": [requirement.to_dict() for requirement in result.requirements],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(*, result: ResearchExpansionGateResult) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Research Expansion Gate - {result.candidate_scope}",
        "",
        f"- Gate version: `{result.gate_version}`",
        f"- Status: `{result.status}`",
        f"- Run ID: `{result.run_id}`",
        f"- Product anchor: `{result.product_code}`",
        f"- Pipeline evidence: `{result.pipeline_json_path}`",
        f"- Replay evidence: `{result.replay_json_path}`",
        f"- Machine-readable gate: `{result.json_path}`",
        "",
        "## Requirements",
        "",
        "| Requirement | Status | Message |",
        "| --- | --- | --- |",
    ]
    for requirement in result.requirements:
        lines.append(
            "| "
            + " | ".join(
                [
                    requirement.requirement_id,
                    requirement.status,
                    requirement.message.replace("|", "\\|"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "R52 does not start SR/AP, AP/SR, or external-data ingestion. Expansion "
            "can only move to a research prototype after CF R20/R21 evidence and the "
            "R41-R51 mainline evidence are present, and candidate-specific rules, "
            "fields, quality checks, and execution boundaries are reviewed.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _output_paths(
    *,
    run_id: str,
    candidate_scope: str,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = report_output_dir or reports_dir() / "research" / EXPANSION_GATE_REPORT_DIR
    safe_scope = _safe_scope(candidate_scope)
    stem = f"{PRODUCT_CODE}_{safe_scope}_{run_id}_expansion_gate"
    return {"markdown": root / f"{stem}.md", "json": root / f"{stem}.json"}


def _safe_scope(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")


def _default_run_id(candidate_scope: str, gate_version: str) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{gate_version.lower()}_gate_{_safe_scope(candidate_scope)}_{timestamp}_{suffix}"
