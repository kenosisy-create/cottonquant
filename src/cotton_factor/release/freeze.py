"""D23 release freeze workflow."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cotton_factor import __version__ as PACKAGE_VERSION
from cotton_factor.archive import (
    AuditLogWriter,
    build_archive_bundle,
    build_run_manifest,
    current_git_sha,
    register_artifact,
    write_artifact_registry,
    write_run_manifest,
)
from cotton_factor.archive.artifact_registry import ArtifactRecord
from cotton_factor.common.exceptions import CottonFactorError, ReleaseError
from cotton_factor.common.hashing import sha256_bytes, sha256_file
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.time import utc_now
from cotton_factor.smoke import run_product_config_smoke
from cotton_factor.uat import run_uat_replay

BLOCKS_PRODUCTION = "blocks production"
ACCEPTABLE_FOR_MVP = "acceptable for MVP"
FUTURE_ENHANCEMENT = "future enhancement"
TODO_CLASSIFICATIONS = (BLOCKS_PRODUCTION, ACCEPTABLE_FOR_MVP, FUTURE_ENHANCEMENT)
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
RELEASE_BUNDLE_NAME = "release_bundle.zip"
TODO_TOKEN = "TODO_REQUIRES_HUMAN_REVIEW"


@dataclass(frozen=True)
class ReleaseCheckResult:
    """One release freeze pass/fail check."""

    name: str
    passed: bool
    message: str
    details: dict[str, object]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable check summary."""
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class KnownTodoItem:
    """One classified human-review TODO occurrence."""

    path: str
    line: int
    text: str
    classification: str
    reason: str

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable TODO item."""
        return {
            "path": self.path,
            "line": self.line,
            "text": self.text,
            "classification": self.classification,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReleaseFreezeResult:
    """Result of the D23 release freeze workflow."""

    version: str
    run_id: str
    release_dir: Path
    release_manifest_path: Path
    run_manifest_path: Path
    audit_path: Path
    checksums_path: Path
    registry_path: Path
    todo_inventory_path: Path
    todo_inventory_markdown_path: Path
    test_summary_path: Path
    bundle_path: Path
    checks: list[ReleaseCheckResult]
    todo_summary: dict[str, int]
    warnings: list[str]

    @property
    def passed(self) -> bool:
        """Return true when release-candidate checks passed."""
        return all(check.passed for check in self.checks) and self.bundle_path.exists()

    @property
    def production_ready(self) -> bool:
        """Return true only when no TODO is classified as production-blocking."""
        return self.todo_summary.get(BLOCKS_PRODUCTION, 0) == 0

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable release freeze summary."""
        failed_checks = [check.name for check in self.checks if not check.passed]
        return {
            "version": self.version,
            "run_id": self.run_id,
            "passed": self.passed,
            "production_ready": self.production_ready,
            "release_dir": str(self.release_dir),
            "release_manifest_path": str(self.release_manifest_path),
            "run_manifest_path": str(self.run_manifest_path),
            "audit_path": str(self.audit_path),
            "checksums_path": str(self.checksums_path),
            "registry_path": str(self.registry_path),
            "todo_inventory_path": str(self.todo_inventory_path),
            "todo_inventory_markdown_path": str(self.todo_inventory_markdown_path),
            "test_summary_path": str(self.test_summary_path),
            "bundle_path": str(self.bundle_path),
            "checks": [check.to_summary() for check in self.checks],
            "failed_checks": failed_checks,
            "todo_summary": self.todo_summary,
            "warnings": self.warnings,
        }


def run_release_freeze(
    *,
    version: str,
    output_root: Path | None = None,
    run_id: str | None = None,
) -> ReleaseFreezeResult:
    """Create a D23 release freeze package under data/archive."""
    active_version = _validate_segment(version, field_name="version")
    active_run_id = _validate_segment(run_id or f"release_{active_version}", field_name="run_id")
    release_dir = _prepare_release_dir(
        output_root=output_root or data_dir() / "archive",
        version=active_version,
    )

    audit_path = release_dir / "audit.jsonl"
    audit = AuditLogWriter(audit_path)
    started_at = utc_now()
    audit.record(
        run_id=active_run_id,
        event_type="release_freeze_started",
        message="D23 release freeze started",
        payload={"version": active_version},
        created_at_utc=started_at,
    )

    warnings: list[str] = []
    versions = _collect_versions(active_version)
    version_check = _version_check(versions)
    dependency_summary = _dependency_lock_summary()
    warnings.extend(str(item) for item in dependency_summary.get("warnings", []))
    config_summary = _config_hash_summary()
    git_summary = _git_summary()
    known_todos = collect_known_todos()
    todo_summary = _todo_summary(known_todos)

    uat_summary, uat_check, uat_artifacts = _run_uat_check(
        release_dir=release_dir,
        run_id=f"{active_run_id}_uat",
    )
    product_summary, product_check = _run_product_smoke_check()
    test_summary = {
        "uat_replay": uat_summary,
        "product_config_smoke": product_summary,
        "external_verification_commands": [
            "py -3.12 -m pytest",
            "py -3.12 -m ruff check src tests",
        ],
    }
    checks = [
        version_check,
        uat_check,
        product_check,
        _todo_classification_check(known_todos),
    ]

    release_manifest_path = release_dir / "release_manifest.json"
    run_manifest_path = release_dir / "run_manifest.json"
    checksums_path = release_dir / "checksums.json"
    registry_path = release_dir / "artifact_registry.json"
    todo_inventory_path = release_dir / "known_todos.json"
    todo_inventory_markdown_path = release_dir / "known_todos.md"
    test_summary_path = release_dir / "test_summary.json"
    config_hashes_path = release_dir / "config_hashes.json"
    dependency_lock_path = release_dir / "dependency_lock.json"
    changelog_copy_path = release_dir / "CHANGELOG.md"
    checklist_copy_path = release_dir / "RELEASE_CHECKLIST.md"
    bundle_path = release_dir / RELEASE_BUNDLE_NAME

    _write_json(config_hashes_path, config_summary)
    _write_json(dependency_lock_path, dependency_summary)
    _write_json(test_summary_path, test_summary)
    _write_json(todo_inventory_path, [item.to_summary() for item in known_todos])
    _write_todo_markdown(known_todos, todo_inventory_markdown_path)
    _copy_release_doc(project_root() / "CHANGELOG.md", changelog_copy_path)
    _copy_release_doc(project_root() / "docs" / "RELEASE_CHECKLIST.md", checklist_copy_path)

    release_manifest = _release_manifest_payload(
        version=active_version,
        run_id=active_run_id,
        versions=versions,
        git_summary=git_summary,
        dependency_summary=dependency_summary,
        config_summary=config_summary,
        test_summary=test_summary,
        todo_summary=todo_summary,
        checks=checks,
        warnings=warnings,
        release_dir=release_dir,
        bundle_path=bundle_path,
    )
    _write_json(release_manifest_path, release_manifest)

    artifact_paths = [
        release_manifest_path,
        audit_path,
        config_hashes_path,
        dependency_lock_path,
        test_summary_path,
        todo_inventory_path,
        todo_inventory_markdown_path,
        changelog_copy_path,
        checklist_copy_path,
        *uat_artifacts,
        checksums_path,
        registry_path,
    ]
    run_manifest = build_run_manifest(
        run_id=active_run_id,
        run_type="release_freeze",
        row_counts={
            "known_todos": len(known_todos),
            "todo_blocks_production": todo_summary.get(BLOCKS_PRODUCTION, 0),
            "todo_acceptable_for_mvp": todo_summary.get(ACCEPTABLE_FOR_MVP, 0),
            "todo_future_enhancement": todo_summary.get(FUTURE_ENHANCEMENT, 0),
        },
        artifact_paths=[_relative_path(path=path, root=release_dir) for path in artifact_paths],
        warnings=warnings,
        git_sha=str(git_summary["git_sha"]),
        started_at_utc=started_at,
        ended_at_utc=utc_now(),
    )
    write_run_manifest(run_manifest, run_manifest_path)

    audit.record(
        run_id=active_run_id,
        event_type="known_todos_classified",
        message="known TODOs classified for MVP release candidate",
        severity="human_review",
        payload=todo_summary,
    )
    audit.record(
        run_id=active_run_id,
        event_type="release_artifacts_ready",
        message="release manifest, TODO inventory, and test summary written",
        payload={"release_dir": str(release_dir)},
    )

    primary_artifacts = [
        run_manifest_path,
        release_manifest_path,
        audit_path,
        config_hashes_path,
        dependency_lock_path,
        test_summary_path,
        todo_inventory_path,
        todo_inventory_markdown_path,
        changelog_copy_path,
        checklist_copy_path,
        *uat_artifacts,
    ]
    primary_records = [
        register_artifact(path=path, artifact_type=_artifact_type(path), root=release_dir)
        for path in primary_artifacts
    ]
    _write_checksums(records=primary_records, path=checksums_path)
    all_records = [
        *primary_records,
        register_artifact(path=checksums_path, artifact_type="checksums", root=release_dir),
    ]
    write_artifact_registry(all_records, registry_path)
    bundle_result = build_archive_bundle(
        bundle_path=bundle_path,
        artifact_paths=[*primary_artifacts, checksums_path, registry_path],
        root=release_dir,
    )

    result = ReleaseFreezeResult(
        version=active_version,
        run_id=active_run_id,
        release_dir=release_dir,
        release_manifest_path=release_manifest_path,
        run_manifest_path=run_manifest_path,
        audit_path=audit_path,
        checksums_path=checksums_path,
        registry_path=registry_path,
        todo_inventory_path=todo_inventory_path,
        todo_inventory_markdown_path=todo_inventory_markdown_path,
        test_summary_path=test_summary_path,
        bundle_path=bundle_result.bundle_path,
        checks=checks,
        todo_summary=todo_summary,
        warnings=warnings,
    )
    return result


def collect_known_todos() -> list[KnownTodoItem]:
    """Collect and classify TODO_REQUIRES_HUMAN_REVIEW occurrences."""
    items: list[KnownTodoItem] = []
    for path in _todo_scan_paths():
        relative_path = _relative_path(path=path, root=project_root())
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if TODO_TOKEN not in line:
                continue
            classification, reason = _classify_todo(
                relative_path=relative_path,
                text=line.strip(),
            )
            items.append(
                KnownTodoItem(
                    path=relative_path,
                    line=line_number,
                    text=line.strip(),
                    classification=classification,
                    reason=reason,
                )
            )
    return sorted(items, key=lambda item: (item.classification, item.path, item.line))


def _validate_segment(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned or cleaned in {".", ".."} or not VERSION_PATTERN.fullmatch(cleaned):
        raise ReleaseError(
            f"{field_name} must be one path segment using letters, numbers, "
            "dot, dash, or underscore"
        )
    return cleaned


def _prepare_release_dir(*, output_root: Path, version: str) -> Path:
    root = output_root.resolve()
    release_dir = root / f"release-{version}"
    release_resolved = release_dir.resolve()
    try:
        release_resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseError(f"release dir escapes output root: {release_dir}") from exc
    if release_resolved == root:
        raise ReleaseError("release dir must be a child of output root")

    # D23 冻结包是可重建产物；只清理当前版本目录，避免影响其他归档。
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)
    return release_dir


def _collect_versions(expected_version: str) -> dict[str, object]:
    version_file = project_root() / "VERSION"
    version_file_value = (
        version_file.read_text(encoding="utf-8").strip() if version_file.exists() else None
    )
    pyproject = tomllib.loads((project_root() / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = str(pyproject.get("project", {}).get("version", ""))
    return {
        "requested_version": expected_version,
        "package_version": PACKAGE_VERSION,
        "pyproject_version": pyproject_version,
        "version_file": version_file_value,
    }


def _version_check(versions: Mapping[str, object]) -> ReleaseCheckResult:
    expected = versions["requested_version"]
    mismatches = {
        key: value
        for key, value in versions.items()
        if key != "requested_version" and value != expected
    }
    return ReleaseCheckResult(
        name="version_sources_match",
        passed=not mismatches,
        message="version sources match requested version" if not mismatches else "version mismatch",
        details={"versions": dict(versions), "mismatches": mismatches},
    )


def _dependency_lock_summary() -> dict[str, object]:
    candidates = [
        project_root() / "uv.lock",
        project_root() / "poetry.lock",
        project_root() / "requirements.lock",
        project_root() / "requirements.txt",
    ]
    found = [path for path in candidates if path.exists() and path.is_file()]
    warnings: list[str] = []
    source_paths = found or [project_root() / "pyproject.toml"]
    if not found:
        warnings.append(
            "No dedicated dependency lock file found; pyproject.toml dependency hash used."
        )
    entries = [
        {
            "path": _relative_path(path=path, root=project_root()),
            "sha256": sha256_file(path),
        }
        for path in sorted(source_paths)
    ]
    lock_hash = sha256_bytes(
        json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return {
        "dependency_lock_hash": lock_hash,
        "source_paths": [entry["path"] for entry in entries],
        "lock_files_found": bool(found),
        "warnings": warnings,
    }


def _config_hash_summary() -> dict[str, object]:
    config_dir = project_root() / "configs"
    entries = [
        {
            "path": _relative_path(path=path, root=project_root()),
            "sha256": sha256_file(path),
        }
        for path in sorted(config_dir.rglob("*"))
        if path.is_file()
    ]
    aggregate_hash = sha256_bytes(
        json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return {
        "config_hash": aggregate_hash,
        "files": entries,
    }


def _git_summary() -> dict[str, object]:
    status_lines = _git_status_lines()
    return {
        "git_sha": current_git_sha(),
        "working_tree_dirty": bool(status_lines),
        "status_short": status_lines,
    }


def _git_status_lines() -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_root(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ["UNKNOWN_GIT_STATUS"]
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _run_uat_check(
    *,
    release_dir: Path,
    run_id: str,
) -> tuple[dict[str, object], ReleaseCheckResult, list[Path]]:
    try:
        result = run_uat_replay(
            scenario="cf_mvp_fixture",
            output_root=release_dir / "uat",
            run_id=run_id,
        )
    except CottonFactorError as exc:
        summary: dict[str, object] = {"passed": False, "error": str(exc)}
        return (
            summary,
            ReleaseCheckResult(
                name="uat_replay_passed",
                passed=False,
                message=str(exc),
                details=summary,
            ),
            [],
        )
    summary = result.to_summary()
    return (
        summary,
        ReleaseCheckResult(
            name="uat_replay_passed",
            passed=result.passed,
            message="UAT replay passed" if result.passed else "UAT replay failed",
            details={
                "json_report_path": str(result.json_report_path),
                "html_report_path": str(result.html_report_path),
                "failed_checks": summary["failed_checks"],
            },
        ),
        [result.json_report_path, result.html_report_path],
    )


def _run_product_smoke_check() -> tuple[dict[str, object], ReleaseCheckResult]:
    try:
        result = run_product_config_smoke(product_codes=("SR", "AP"), year=2024)
    except CottonFactorError as exc:
        summary: dict[str, object] = {"passed": False, "error": str(exc)}
        return (
            summary,
            ReleaseCheckResult(
                name="sr_ap_config_smoke_passed",
                passed=False,
                message=str(exc),
                details=summary,
            ),
        )
    summary = result.to_summary()
    contract_counts = {
        item["product_code"]: item["contract_count"]
        for item in summary["products"]  # type: ignore[index]
    }
    passed = contract_counts == {"SR": 6, "AP": 7}
    return (
        summary,
        ReleaseCheckResult(
            name="sr_ap_config_smoke_passed",
            passed=passed,
            message="SR/AP config smoke passed" if passed else "SR/AP config smoke mismatch",
            details={"contract_counts": contract_counts},
        ),
    )


def _todo_classification_check(items: Sequence[KnownTodoItem]) -> ReleaseCheckResult:
    unclassified = [
        item.to_summary()
        for item in items
        if item.classification not in TODO_CLASSIFICATIONS
    ]
    return ReleaseCheckResult(
        name="known_todos_classified",
        passed=not unclassified,
        message="known TODOs are classified" if not unclassified else "unclassified TODOs found",
        details={
            "todo_count": len(items),
            "summary": _todo_summary(items),
            "unclassified": unclassified,
        },
    )


def _todo_summary(items: Sequence[KnownTodoItem]) -> dict[str, int]:
    summary = {classification: 0 for classification in TODO_CLASSIFICATIONS}
    for item in items:
        summary[item.classification] = summary.get(item.classification, 0) + 1
    return summary


def _todo_scan_paths() -> list[Path]:
    roots = [
        project_root() / "configs",
        project_root() / "src",
        project_root() / "docs",
        project_root() / "prompts",
        project_root() / ".codex" / "agents",
    ]
    single_files = [
        project_root() / "AGENTS.md",
        project_root() / "README.md",
        project_root() / "CHANGELOG.md",
    ]
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    paths.extend(path for path in single_files if path.exists())
    return sorted(path for path in paths if path.suffix in {".md", ".py", ".toml", ".yaml", ".yml"})


def _classify_todo(*, relative_path: str, text: str) -> tuple[str, str]:
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("configs/data_sources") or "live_endpoint" in text:
        return BLOCKS_PRODUCTION, "live exchange endpoint must be reviewed before production use"
    if normalized.startswith("configs/cost_model") or normalized.startswith("configs/backtest"):
        return (
            BLOCKS_PRODUCTION,
            "cost and capital parameters must be reviewed before production use",
        )
    if normalized.startswith("configs/roll_rules"):
        return BLOCKS_PRODUCTION, "roll thresholds are human-review gates"
    if normalized.startswith("configs/products/CF"):
        return BLOCKS_PRODUCTION, "CF contract-rule uncertainty blocks production trading"
    if normalized.startswith("configs/products/") and any(
        marker in normalized for marker in ("M.yaml", "C.yaml", "Y.yaml")
    ):
        return FUTURE_ENHANCEMENT, "non-CF product config is outside Month 1 MVP execution scope"
    if normalized.startswith("configs/products/"):
        return ACCEPTABLE_FOR_MVP, "SR/AP config-only smoke allows TODO fields when disclosed"
    if normalized.startswith("configs/factor_registry"):
        return ACCEPTABLE_FOR_MVP, "factor owner assignment is not required for fixture MVP"
    if normalized.startswith("src/"):
        return ACCEPTABLE_FOR_MVP, "runtime code surfaces the human-review warning explicitly"
    if (
        normalized.startswith("docs/")
        or normalized.startswith("prompts/")
        or normalized == "AGENTS.md"
    ):
        return ACCEPTABLE_FOR_MVP, "documentation records the required human-review boundary"
    if normalized.startswith(".codex/agents"):
        return ACCEPTABLE_FOR_MVP, "agent instruction guardrail, not an unresolved runtime rule"
    return FUTURE_ENHANCEMENT, "tracked for later review"


def _release_manifest_payload(
    *,
    version: str,
    run_id: str,
    versions: Mapping[str, object],
    git_summary: Mapping[str, object],
    dependency_summary: Mapping[str, object],
    config_summary: Mapping[str, object],
    test_summary: Mapping[str, object],
    todo_summary: Mapping[str, int],
    checks: Sequence[ReleaseCheckResult],
    warnings: Sequence[str],
    release_dir: Path,
    bundle_path: Path,
) -> dict[str, object]:
    passed = all(check.passed for check in checks)
    return {
        "schema_version": "release_manifest_v1",
        "version": version,
        "run_id": run_id,
        "created_at_utc": utc_now().isoformat(),
        "mvp_release_candidate": passed,
        "production_ready": todo_summary.get(BLOCKS_PRODUCTION, 0) == 0,
        "release_dir": str(release_dir),
        "bundle_path": str(bundle_path),
        "git": dict(git_summary),
        "versions": dict(versions),
        "dependency_lock": dict(dependency_summary),
        "config_hash": config_summary["config_hash"],
        "config_file_count": len(config_summary["files"]),  # type: ignore[arg-type]
        "test_summary": dict(test_summary),
        "todo_summary": dict(todo_summary),
        "checks": [check.to_summary() for check in checks],
        "warnings": list(warnings),
    }


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _write_todo_markdown(items: Sequence[KnownTodoItem], path: Path) -> Path:
    lines = [
        "# Known TODO Classification",
        "",
        "| Classification | File | Line | Reason | Text |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in items:
        lines.append(
            "| "
            f"{_escape_md(item.classification)} | "
            f"{_escape_md(item.path)} | "
            f"{item.line} | "
            f"{_escape_md(item.reason)} | "
            f"{_escape_md(item.text)} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _copy_release_doc(source: Path, destination: Path) -> Path:
    if not source.exists():
        raise ReleaseError(f"release document not found: {source}")
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def _write_checksums(*, records: Sequence[ArtifactRecord], path: Path) -> Path:
    payload = [
        {
            "artifact_id": record.artifact_id,
            "artifact_type": record.artifact_type,
            "path": record.path,
            "sha256": record.sha256,
            "byte_size": record.byte_size,
        }
        for record in sorted(records, key=lambda item: item.path)
    ]
    return _write_json(path, payload)


def _artifact_type(path: Path) -> str:
    name = path.name
    mapping = {
        "run_manifest.json": "run_manifest",
        "release_manifest.json": "release_manifest",
        "audit.jsonl": "audit_log",
        "config_hashes.json": "config_hashes",
        "dependency_lock.json": "dependency_lock",
        "test_summary.json": "test_summary",
        "known_todos.json": "known_todos",
        "known_todos.md": "known_todos_markdown",
        "CHANGELOG.md": "changelog",
        "RELEASE_CHECKLIST.md": "release_checklist",
        "uat_report.json": "uat_report_json",
        "uat_report.html": "uat_report_html",
    }
    return mapping.get(name, "release_artifact")


def _relative_path(*, path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _escape_md(value: object) -> str:
    return str(value).replace("|", "\\|")
