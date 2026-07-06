"""R21 lightweight replay checks for preserved CF research outputs."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_file
from cotton_factor.common.paths import project_root, reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
REPLAY_REPORT_DIR = "replay"


@dataclass(frozen=True)
class ResearchReplayArtifact:
    """One R20 artifact fingerprint captured by R21 replay."""

    artifact_id: str
    path: Path
    exists: bool
    byte_size: int | None
    sha256: str | None
    row_count: int | None
    row_count_status: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable artifact fingerprint."""
        return {
            "artifact_id": self.artifact_id,
            "path": str(self.path),
            "exists": self.exists,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "row_count": self.row_count,
            "row_count_status": self.row_count_status,
        }


@dataclass(frozen=True)
class ResearchReplayCheck:
    """One pass/fail replay check."""

    check_id: str
    passed: bool
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable check row."""
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class ResearchPipelineReplayResult:
    """R21 replay result for one preserved R20 pipeline JSON log."""

    product_code: str
    run_id: str
    source_pipeline_json_path: Path
    pipeline_run_id: str
    trade_date: date
    start: date
    end: date
    pipeline_status: str
    artifacts: tuple[ResearchReplayArtifact, ...]
    checks: tuple[ResearchReplayCheck, ...]
    markdown_path: Path
    json_path: Path
    baseline_json_path: Path | None
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return true only when every R21 replay check passes."""
        return all(check.passed for check in self.checks)

    def to_summary(self) -> dict[str, Any]:
        """Return a compact CLI summary."""
        failed_checks = [check.check_id for check in self.checks if not check.passed]
        missing_artifacts = [
            artifact.artifact_id for artifact in self.artifacts if not artifact.exists
        ]
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "passed": self.passed,
            "source_pipeline_json_path": str(self.source_pipeline_json_path),
            "pipeline_run_id": self.pipeline_run_id,
            "trade_date": self.trade_date.isoformat(),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "pipeline_status": self.pipeline_status,
            "artifact_count": len(self.artifacts),
            "missing_artifact_count": len(missing_artifacts),
            "missing_artifacts": missing_artifacts,
            "failed_checks": failed_checks,
            "baseline_json_path": (
                None if self.baseline_json_path is None else str(self.baseline_json_path)
            ),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "human_review_required": list(self.human_review_required),
        }


def replay_cf_research_pipeline_outputs(
    *,
    pipeline_json_path: Path,
    baseline_json_path: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    require_completed_pipeline: bool = True,
) -> ResearchPipelineReplayResult:
    """Verify preserved R20 output artifacts without rerunning the pipeline."""
    pipeline_payload = _load_json_object(pipeline_json_path, context="R20 pipeline JSON")
    pipeline_run_id = _required_str(pipeline_payload, "run_id")
    trade_date = _required_date(pipeline_payload, "trade_date")
    start = _required_date(pipeline_payload, "start")
    end = _required_date(pipeline_payload, "end")
    pipeline_status = _required_str(pipeline_payload, "status")
    active_run_id = run_id or _default_run_id(trade_date=trade_date)
    artifacts = tuple(
        _fingerprint_artifact(artifact_id=artifact_id, raw_path=raw_path)
        for artifact_id, raw_path in _artifact_paths(pipeline_payload).items()
    )
    baseline_payload = (
        _load_json_object(baseline_json_path, context="R21 replay baseline JSON")
        if baseline_json_path is not None
        else None
    )
    checks = tuple(
        _build_checks(
            pipeline_status=pipeline_status,
            require_completed_pipeline=require_completed_pipeline,
            artifacts=artifacts,
            baseline_payload=baseline_payload,
        )
    )
    paths = _output_paths(
        trade_date=trade_date,
        run_id=active_run_id,
        report_output_dir=report_output_dir,
    )

    # R21 只复核 R20 已保存产物的存在性和指纹；不重跑 R04-R19，也不直接读取 incoming/raw 业务字段。
    result = ResearchPipelineReplayResult(
        product_code=PRODUCT_CODE,
        run_id=active_run_id,
        source_pipeline_json_path=pipeline_json_path,
        pipeline_run_id=pipeline_run_id,
        trade_date=trade_date,
        start=start,
        end=end,
        pipeline_status=pipeline_status,
        artifacts=artifacts,
        checks=checks,
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        baseline_json_path=baseline_json_path,
        human_review_required=_human_review_required(pipeline_payload),
    )
    _write_json(result=result)
    _write_markdown(result=result)
    return result


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


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ResearchWorkbenchError(f"R20 pipeline JSON missing string field: {key}")
    return value


def _required_date(payload: dict[str, Any], key: str) -> date:
    value = _required_str(payload, key)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ResearchWorkbenchError(f"R20 pipeline JSON has invalid date field: {key}") from exc


def _artifact_paths(payload: dict[str, Any]) -> dict[str, Path]:
    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, dict) or not raw_artifacts:
        raise ResearchWorkbenchError("R20 pipeline JSON must contain non-empty artifacts")
    artifacts: dict[str, Path] = {}
    for artifact_id, raw_path in sorted(raw_artifacts.items()):
        if not isinstance(artifact_id, str) or not isinstance(raw_path, str) or not raw_path:
            raise ResearchWorkbenchError("R20 pipeline artifact entries must be string paths")
        artifacts[artifact_id] = _resolve_artifact_path(raw_path)
    return artifacts


def _resolve_artifact_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return project_root() / path


def _fingerprint_artifact(*, artifact_id: str, raw_path: Path) -> ResearchReplayArtifact:
    if not raw_path.exists():
        return ResearchReplayArtifact(
            artifact_id=artifact_id,
            path=raw_path,
            exists=False,
            byte_size=None,
            sha256=None,
            row_count=None,
            row_count_status="missing",
        )
    return ResearchReplayArtifact(
        artifact_id=artifact_id,
        path=raw_path,
        exists=True,
        byte_size=raw_path.stat().st_size,
        sha256=sha256_file(raw_path),
        row_count=_row_count(raw_path),
        row_count_status=_row_count_status(raw_path),
    )


def _row_count(path: Path) -> int | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".parquet":
            return int(len(pd.read_parquet(path)))
        if suffix == ".csv":
            return int(len(pd.read_csv(path)))
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return len(payload)
            if isinstance(payload, dict) and isinstance(payload.get("steps"), list):
                return len(payload["steps"])
    except Exception as exc:  # pragma: no cover - message captured by status.
        raise ResearchWorkbenchError(f"cannot inspect replay artifact row count: {path}") from exc
    return None


def _row_count_status(path: Path) -> str:
    if path.suffix.lower() in {".parquet", ".csv", ".json"}:
        return "inspected"
    return "not_applicable"


def _build_checks(
    *,
    pipeline_status: str,
    require_completed_pipeline: bool,
    artifacts: tuple[ResearchReplayArtifact, ...],
    baseline_payload: dict[str, Any] | None,
) -> list[ResearchReplayCheck]:
    checks = [
        ResearchReplayCheck(
            check_id="pipeline_completed",
            passed=(not require_completed_pipeline) or pipeline_status == "COMPLETED",
            message=(
                "R20 pipeline status is completed"
                if pipeline_status == "COMPLETED"
                else f"R20 pipeline status is {pipeline_status}"
            ),
            details={"pipeline_status": pipeline_status},
        ),
        _artifact_presence_check(artifacts),
    ]
    if baseline_payload is not None:
        checks.append(_baseline_check(artifacts=artifacts, baseline_payload=baseline_payload))
    return checks


def _artifact_presence_check(
    artifacts: tuple[ResearchReplayArtifact, ...],
) -> ResearchReplayCheck:
    missing = [artifact.artifact_id for artifact in artifacts if not artifact.exists]
    return ResearchReplayCheck(
        check_id="all_pipeline_artifacts_exist",
        passed=not missing,
        message=(
            "all R20 artifact paths exist"
            if not missing
            else "some R20 artifact paths are missing"
        ),
        details={
            "artifact_count": len(artifacts),
            "missing_artifacts": missing,
        },
    )


def _baseline_check(
    *,
    artifacts: tuple[ResearchReplayArtifact, ...],
    baseline_payload: dict[str, Any],
) -> ResearchReplayCheck:
    baseline = _baseline_artifacts(baseline_payload)
    current = {artifact.artifact_id: artifact.to_dict() for artifact in artifacts}
    current_ids = set(current)
    baseline_ids = set(baseline)
    changed = {
        artifact_id: {
            "baseline_sha256": baseline[artifact_id].get("sha256"),
            "current_sha256": current[artifact_id].get("sha256"),
            "baseline_byte_size": baseline[artifact_id].get("byte_size"),
            "current_byte_size": current[artifact_id].get("byte_size"),
            "baseline_row_count": baseline[artifact_id].get("row_count"),
            "current_row_count": current[artifact_id].get("row_count"),
        }
        for artifact_id in sorted(current_ids & baseline_ids)
        if (
            baseline[artifact_id].get("sha256") != current[artifact_id].get("sha256")
            or baseline[artifact_id].get("row_count") != current[artifact_id].get("row_count")
        )
    }
    missing = sorted(baseline_ids - current_ids)
    extra = sorted(current_ids - baseline_ids)
    passed = not missing and not extra and not changed
    return ResearchReplayCheck(
        check_id="baseline_artifacts_match",
        passed=passed,
        message=(
            "current R20 artifact fingerprints match baseline"
            if passed
            else "current R20 artifact fingerprints differ from baseline"
        ),
        details={"missing": missing, "extra": extra, "changed": changed},
    )


def _baseline_artifacts(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_artifacts = payload.get("artifact_fingerprints")
    if not isinstance(raw_artifacts, list):
        raise ResearchWorkbenchError("R21 baseline JSON missing artifact_fingerprints list")
    result: dict[str, dict[str, Any]] = {}
    for item in raw_artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("artifact_id"), str):
            raise ResearchWorkbenchError("R21 baseline artifact entries must have artifact_id")
        result[str(item["artifact_id"])] = item
    return result


def _human_review_required(payload: dict[str, Any]) -> tuple[str, ...]:
    raw_items = payload.get("human_review_required", [])
    if not isinstance(raw_items, list):
        return ()
    values: list[str] = []
    for item in raw_items:
        text = str(item)
        if text and text not in values:
            values.append(text)
    return tuple(values)


def _write_json(*, result: ResearchPipelineReplayResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": utc_now().isoformat(),
        **result.to_summary(),
        "checks": [check.to_dict() for check in result.checks],
        "artifact_fingerprints": [artifact.to_dict() for artifact in result.artifacts],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(*, result: ResearchPipelineReplayResult) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Research Replay - {result.trade_date.isoformat()}",
        "",
        f"- Status: `{'PASS' if result.passed else 'FAIL'}`",
        f"- Run ID: `{result.run_id}`",
        f"- Source R20 log: `{result.source_pipeline_json_path}`",
        f"- Pipeline status: `{result.pipeline_status}`",
        f"- Window: `{result.start.isoformat()} -> {result.end.isoformat()}`",
        f"- Artifacts checked: `{len(result.artifacts)}`",
        f"- Machine-readable replay: `{result.json_path}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Message |",
        "| --- | --- | --- |",
    ]
    for check in result.checks:
        lines.append(
            "| "
            + " | ".join(
                [
                    check.check_id,
                    "PASS" if check.passed else "FAIL",
                    check.message.replace("|", "\\|"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Artifact Fingerprints",
            "",
            "| Artifact | Exists | Rows | SHA256 | Path |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for artifact in result.artifacts:
        sha = "" if artifact.sha256 is None else artifact.sha256[:16]
        rows = "" if artifact.row_count is None else str(artifact.row_count)
        lines.append(
            "| "
            + " | ".join(
                [
                    artifact.artifact_id,
                    str(artifact.exists),
                    rows,
                    sha,
                    str(artifact.path).replace("|", "\\|"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "R21 replay checks preserved R20 output files and optional baseline "
            "fingerprints. It does not rerun R04-R19, parse exchange raw files, or "
            "approve trades.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    if result.human_review_required:
        lines.extend(f"- `{item}`" for item in result.human_review_required)
    else:
        lines.append("- none")
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _output_paths(
    *,
    trade_date: date,
    run_id: str,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = report_output_dir or reports_dir() / "research" / REPLAY_REPORT_DIR
    stem = f"{PRODUCT_CODE}_{trade_date.isoformat()}_{run_id}_replay"
    return {"markdown": root / f"{stem}.md", "json": root / f"{stem}.json"}


def _default_run_id(*, trade_date: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return f"r21_replay_{PRODUCT_CODE}_{trade_date.isoformat()}_{timestamp}_{suffix}"
