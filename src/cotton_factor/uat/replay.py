"""D22 UAT replay workflow."""

from __future__ import annotations

import html
import json
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from cotton_factor.archive import read_run_manifest
from cotton_factor.common.exceptions import CottonFactorError, UATError
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.time import utc_now
from cotton_factor.qa import stable_smoke_fingerprint
from cotton_factor.smoke import CfSmokeResult, run_cf_smoke

DEFAULT_UAT_SCENARIO = "cf_mvp_fixture"
DEFAULT_UAT_START = date(2024, 1, 2)
DEFAULT_UAT_END = date(2024, 2, 5)
EXPECTED_GOLDEN_PATH = (
    project_root() / "tests" / "golden" / "fixtures" / "d21_quality_expected.json"
)
SUPPORTED_SCENARIOS = {DEFAULT_UAT_SCENARIO}
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class UATCheckResult:
    """One pass/fail item in the UAT replay report."""

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
class UATReplayResult:
    """Result of a D22 UAT replay scenario."""

    scenario: str
    run_id: str
    output_dir: Path
    json_report_path: Path
    html_report_path: Path
    smoke_archive_dir: Path
    checks: list[UATCheckResult]
    warnings: list[str]

    @property
    def passed(self) -> bool:
        """Return true only when every UAT check passed."""
        return all(check.passed for check in self.checks)

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable UAT summary for CLI output."""
        failed_checks = [check.name for check in self.checks if not check.passed]
        return {
            "scenario": self.scenario,
            "run_id": self.run_id,
            "passed": self.passed,
            "output_dir": str(self.output_dir),
            "json_report_path": str(self.json_report_path),
            "html_report_path": str(self.html_report_path),
            "smoke_archive_dir": str(self.smoke_archive_dir),
            "checks": [check.to_summary() for check in self.checks],
            "failed_checks": failed_checks,
            "warnings": self.warnings,
        }


def run_uat_replay(
    *,
    scenario: str = DEFAULT_UAT_SCENARIO,
    output_root: Path | None = None,
    raw_root: Path | None = None,
    archive_root: Path | None = None,
    run_id: str | None = None,
) -> UATReplayResult:
    """Run a supported D22 UAT replay scenario and write pass/fail reports."""
    _assert_supported_scenario(scenario)
    active_run_id = _validate_run_id(run_id or _default_run_id(scenario=scenario))
    output_parent = output_root or data_dir() / "archive" / "uat"
    output_dir = _prepare_clean_output_dir(parent=output_parent, run_id=active_run_id)
    active_raw_root = raw_root or output_dir / "raw"
    active_archive_root = archive_root or output_dir / "smoke_archive"
    smoke_archive_dir = active_archive_root / active_run_id
    json_report_path = output_dir / "uat_report.json"
    html_report_path = output_dir / "uat_report.html"

    expected = _load_expected_golden(EXPECTED_GOLDEN_PATH)
    checks: list[UATCheckResult] = []
    warnings: list[str] = []

    try:
        smoke_result = run_cf_smoke(
            start=DEFAULT_UAT_START,
            end=DEFAULT_UAT_END,
            run_id=active_run_id,
            raw_root=active_raw_root,
            archive_root=active_archive_root,
        )
    except CottonFactorError as exc:
        smoke_result = None
        checks.append(
            UATCheckResult(
                name="cf_smoke_completed",
                passed=False,
                message=str(exc),
                details={
                    "start": DEFAULT_UAT_START.isoformat(),
                    "end": DEFAULT_UAT_END.isoformat(),
                },
            )
        )
    if smoke_result is not None:
        checks.extend(_build_smoke_checks(smoke_result=smoke_result, expected=expected))
        warnings = _stable_warnings(smoke_result)

    result = UATReplayResult(
        scenario=scenario,
        run_id=active_run_id,
        output_dir=output_dir,
        json_report_path=json_report_path,
        html_report_path=html_report_path,
        smoke_archive_dir=smoke_archive_dir,
        checks=checks,
        warnings=warnings,
    )
    _write_reports(result)
    return result


def _assert_supported_scenario(scenario: str) -> None:
    if scenario not in SUPPORTED_SCENARIOS:
        supported = ", ".join(sorted(SUPPORTED_SCENARIOS))
        raise UATError(f"unsupported UAT scenario {scenario!r}; supported scenarios: {supported}")


def _validate_run_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise UATError("run_id must not be empty")
    if cleaned in {".", ".."} or not RUN_ID_PATTERN.fullmatch(cleaned):
        raise UATError(
            "run_id must be one path segment using letters, numbers, dot, dash, or underscore"
        )
    return cleaned


def _default_run_id(*, scenario: str) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"uat_{scenario}_{timestamp}"


def _prepare_clean_output_dir(*, parent: Path, run_id: str) -> Path:
    parent_resolved = parent.resolve()
    output_dir = parent_resolved / run_id
    output_resolved = output_dir.resolve()
    try:
        output_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise UATError(f"UAT output dir escapes output root: {output_dir}") from exc
    if output_resolved == parent_resolved:
        raise UATError("UAT output dir must be a child of output root")

    # UAT 是发布前复放闸口，只清理本次 run 的独立目录，避免误删历史归档。
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _load_expected_golden(path: Path) -> dict[str, object]:
    if not path.exists():
        raise UATError(f"UAT golden file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise UATError(f"UAT golden file must contain a JSON object: {path}")
    return payload


def _build_smoke_checks(
    *,
    smoke_result: CfSmokeResult,
    expected: Mapping[str, object],
) -> list[UATCheckResult]:
    fingerprint = stable_smoke_fingerprint(smoke_result.to_summary())
    actual_counts = _row_counts_from_fingerprint(fingerprint)
    expected_counts = _expected_row_counts(expected)
    actual_warnings = _warnings_from_fingerprint(fingerprint)
    expected_warnings = _expected_warnings(expected)
    artifact_paths = _artifact_paths(smoke_result)

    checks = [
        UATCheckResult(
            name="cf_smoke_completed",
            passed=True,
            message="CF MVP smoke replay completed",
            details={
                "start": DEFAULT_UAT_START.isoformat(),
                "end": DEFAULT_UAT_END.isoformat(),
                "run_id": smoke_result.run_id,
            },
        )
    ]

    missing_artifacts = {
        name: str(path) for name, path in artifact_paths.items() if not path.exists()
    }
    checks.append(
        UATCheckResult(
            name="required_artifacts_exist",
            passed=not missing_artifacts,
            message=(
                "all required smoke artifacts exist"
                if not missing_artifacts
                else "required smoke artifacts are missing"
            ),
            details={
                "artifacts": {name: str(path) for name, path in artifact_paths.items()},
                "missing": missing_artifacts,
            },
        )
    )
    checks.append(_manifest_check(smoke_result))

    row_count_diff = _mapping_diff(expected=expected_counts, actual=actual_counts)
    checks.append(
        UATCheckResult(
            name="golden_row_counts_match",
            passed=not row_count_diff["missing"]
            and not row_count_diff["extra"]
            and not row_count_diff["changed"],
            message=(
                "stable row counts match golden"
                if not row_count_diff["changed"]
                and not row_count_diff["missing"]
                and not row_count_diff["extra"]
                else "stable row counts differ from golden"
            ),
            details={
                "expected": expected_counts,
                "actual": actual_counts,
                "diff": row_count_diff,
            },
        )
    )
    warning_diff = _sequence_diff(expected=expected_warnings, actual=actual_warnings)
    checks.append(
        UATCheckResult(
            name="golden_warnings_match",
            passed=not warning_diff["missing"] and not warning_diff["extra"],
            message=(
                "stable warnings match golden"
                if not warning_diff["missing"] and not warning_diff["extra"]
                else "stable warnings differ from golden"
            ),
            details={
                "expected_count": len(expected_warnings),
                "actual_count": len(actual_warnings),
                **warning_diff,
            },
        )
    )
    checks.append(_human_review_cost_warning_check(actual_warnings))
    checks.append(
        UATCheckResult(
            name="archive_bundle_exists",
            passed=smoke_result.bundle_path.exists(),
            message=(
                "archive bundle exists"
                if smoke_result.bundle_path.exists()
                else "archive bundle is missing"
            ),
            details={"bundle_path": str(smoke_result.bundle_path)},
        )
    )
    checks.append(
        UATCheckResult(
            name="html_report_exists",
            passed=smoke_result.report_path.exists(),
            message=(
                "backtest HTML report exists"
                if smoke_result.report_path.exists()
                else "backtest HTML report is missing"
            ),
            details={"report_path": str(smoke_result.report_path)},
        )
    )
    return checks


def _manifest_check(smoke_result: CfSmokeResult) -> UATCheckResult:
    try:
        manifest = read_run_manifest(smoke_result.manifest_path)
    except CottonFactorError as exc:
        return UATCheckResult(
            name="manifest_is_valid",
            passed=False,
            message=str(exc),
            details={"manifest_path": str(smoke_result.manifest_path)},
        )

    passed = (
        manifest.run_id == smoke_result.run_id
        and manifest.run_type == "cf_full_chain_smoke"
        and manifest.status == "success"
    )
    return UATCheckResult(
        name="manifest_is_valid",
        passed=passed,
        message="manifest is valid" if passed else "manifest metadata is not valid",
        details={
            "manifest_path": str(smoke_result.manifest_path),
            "run_id": manifest.run_id,
            "run_type": manifest.run_type,
            "status": manifest.status,
        },
    )


def _human_review_cost_warning_check(warnings: Sequence[str]) -> UATCheckResult:
    required_fragments = (
        "fee uses D16 placeholder cost",
        "slippage uses D16 placeholder cost",
        "impact uses D16 placeholder cost",
    )
    missing = [
        fragment
        for fragment in required_fragments
        if not any(
            "TODO_REQUIRES_HUMAN_REVIEW" in warning and fragment in warning
            for warning in warnings
        )
    ]
    # 人工复核项必须出现在报告里，UAT 不把这些不确定规则自动判定为生产可用。
    return UATCheckResult(
        name="human_review_cost_warnings_present",
        passed=not missing,
        message=(
            "cost model human-review warnings are present"
            if not missing
            else "cost model human-review warnings are missing"
        ),
        details={"missing_fragments": missing},
    )


def _artifact_paths(smoke_result: CfSmokeResult) -> dict[str, Path]:
    return {
        "manifest": smoke_result.manifest_path,
        "audit": smoke_result.audit_path,
        "checksums": smoke_result.checksums_path,
        "artifact_registry": smoke_result.registry_path,
        "backtest_report": smoke_result.report_path,
        "archive_bundle": smoke_result.bundle_path,
    }


def _row_counts_from_fingerprint(fingerprint: Mapping[str, object]) -> dict[str, int]:
    row_counts = fingerprint.get("row_counts")
    if not isinstance(row_counts, dict):
        raise UATError("stable smoke fingerprint requires row_counts")
    return {str(key): int(value) for key, value in row_counts.items()}


def _warnings_from_fingerprint(fingerprint: Mapping[str, object]) -> list[str]:
    warnings = fingerprint.get("warnings")
    if not isinstance(warnings, list):
        raise UATError("stable smoke fingerprint requires warnings")
    return [str(value) for value in warnings]


def _expected_row_counts(expected: Mapping[str, object]) -> dict[str, int]:
    row_counts = expected.get("cf_smoke_row_counts")
    if not isinstance(row_counts, dict):
        raise UATError("UAT golden requires cf_smoke_row_counts")
    return {str(key): int(value) for key, value in row_counts.items()}


def _expected_warnings(expected: Mapping[str, object]) -> list[str]:
    warnings = expected.get("cf_smoke_warnings")
    if not isinstance(warnings, list):
        raise UATError("UAT golden requires cf_smoke_warnings")
    return [str(value) for value in warnings]


def _stable_warnings(smoke_result: CfSmokeResult) -> list[str]:
    return _warnings_from_fingerprint(stable_smoke_fingerprint(smoke_result.to_summary()))


def _mapping_diff(
    *,
    expected: Mapping[str, int],
    actual: Mapping[str, int],
) -> dict[str, object]:
    expected_keys = set(expected)
    actual_keys = set(actual)
    changed = {
        key: {"expected": expected[key], "actual": actual[key]}
        for key in sorted(expected_keys & actual_keys)
        if expected[key] != actual[key]
    }
    return {
        "missing": sorted(expected_keys - actual_keys),
        "extra": sorted(actual_keys - expected_keys),
        "changed": changed,
    }


def _sequence_diff(*, expected: Sequence[str], actual: Sequence[str]) -> dict[str, list[str]]:
    expected_set = set(expected)
    actual_set = set(actual)
    return {
        "missing": sorted(expected_set - actual_set),
        "extra": sorted(actual_set - expected_set),
    }


def _write_reports(result: UATReplayResult) -> None:
    created_at = utc_now()
    _write_json_report(result=result, created_at=created_at)
    _write_html_report(result=result, created_at=created_at)


def _write_json_report(*, result: UATReplayResult, created_at: datetime) -> None:
    payload = {"created_at_utc": created_at.isoformat(), **result.to_summary()}
    result.json_report_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_html_report(*, result: UATReplayResult, created_at: datetime) -> None:
    status = "PASS" if result.passed else "FAIL"
    check_rows = "\n".join(_html_check_row(check) for check in result.checks)
    warning_items = "\n".join(
        f"<li>{html.escape(warning)}</li>" for warning in result.warnings
    )
    if not warning_items:
        warning_items = "<li>No warnings captured.</li>"

    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>D22 UAT Replay Report - {html.escape(result.run_id)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2933; }}
    h1 {{ font-size: 24px; margin-bottom: 8px; }}
    h2 {{ font-size: 18px; margin-top: 28px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #c9d1d9; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    .status {{ font-weight: 700; }}
    .pass {{ color: #116329; }}
    .fail {{ color: #b42318; }}
    code {{ background: #f6f8fa; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>D22 UAT Replay Report</h1>
  <p class="status {status.lower()}">Overall: {status}</p>
  <p>Scenario: <code>{html.escape(result.scenario)}</code></p>
  <p>Run ID: <code>{html.escape(result.run_id)}</code></p>
  <p>Created UTC: <code>{html.escape(created_at.isoformat())}</code></p>
  <p>Smoke archive: <code>{html.escape(str(result.smoke_archive_dir))}</code></p>
  <h2>Checks</h2>
  <table>
    <thead><tr><th>Name</th><th>Status</th><th>Message</th></tr></thead>
    <tbody>
{check_rows}
    </tbody>
  </table>
  <h2>Warnings</h2>
  <ul>
{warning_items}
  </ul>
</body>
</html>
"""
    result.html_report_path.write_text(body, encoding="utf-8")


def _html_check_row(check: UATCheckResult) -> str:
    status = "PASS" if check.passed else "FAIL"
    status_class = "pass" if check.passed else "fail"
    return (
        "      <tr>"
        f"<td>{html.escape(check.name)}</td>"
        f"<td class=\"{status_class}\">{status}</td>"
        f"<td>{html.escape(check.message)}</td>"
        "</tr>"
    )
