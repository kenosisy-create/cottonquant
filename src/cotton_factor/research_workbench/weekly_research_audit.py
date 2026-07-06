"""R59 weekly audit report for the CF research workbench."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import project_root, reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
WEEKLY_RESEARCH_AUDIT_VERSION = "R59_weekly_research_audit_v1"
OUTPUT_DIR = "weekly_audit"
INFO_SEVERITY = "INFO"
WARN_SEVERITY = "WARN"
EXPECTED_STEPS = (
    "signal_matrix",
    "latest_signal_brief",
    "trend_continuity_board",
    "daily_operation_audit",
    "historical_evidence",
    "event_explanation",
    "event_threshold_sensitivity",
    "validated_brief",
    "publish_pack",
)
WEEKLY_RESEARCH_STEPS = (
    "historical_evidence",
    "event_explanation",
    "event_threshold_sensitivity",
    "validated_brief",
    "publish_pack",
)
HUMAN_REVIEW_REQUIRED = (
    "event_thresholds",
    "historical_event_interpretation",
    "fundamental_context_interpretation",
    "fundamental_release_lag",
    "publish_wording",
)
WARNING_COLUMNS = (
    "run_id",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
)


@dataclass(frozen=True)
class WeeklyResearchAuditWarningRecord:
    """Warning row for R59 weekly audit."""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable warning row."""
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV row."""
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchWeeklyAuditResult:
    """Result of building the R59 weekly audit."""

    product_code: str
    run_id: str
    data_asof: date
    weekly_manifest_path: Path
    markdown_path: Path
    json_path: Path
    warning_csv_path: Path
    manifest_path: Path
    audit_status: str
    step_statuses: dict[str, str]
    artifact_checks: list[dict[str, object]]
    event_context_coverage: dict[str, object]
    event_threshold_context: dict[str, object]
    warning_records: tuple[WeeklyResearchAuditWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    @property
    def passed(self) -> bool:
        """R59 passes when the weekly audit artifacts were generated."""
        return self.audit_status in {"WEEKLY_AUDIT_READY", "WEEKLY_AUDIT_READY_WITH_WARNINGS"}

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "status": self.audit_status,
            "passed": self.passed,
            "data_asof": self.data_asof.isoformat(),
            "weekly_manifest_path": str(self.weekly_manifest_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "warning_csv_path": str(self.warning_csv_path),
            "manifest_path": str(self.manifest_path),
            "step_statuses": self.step_statuses,
            "artifact_missing_count": sum(
                1 for check in self.artifact_checks if not bool(check.get("exists"))
            ),
            "event_context_coverage": self.event_context_coverage,
            "event_threshold_context": self.event_threshold_context,
            "warning_count": self.warning_count,
            "warnings": [warning.to_summary() for warning in self.warning_records],
            "research_boundary": _research_boundary_payload(),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_weekly_research_audit(
    *,
    weekly_manifest_path: Path,
    output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchWeeklyAuditResult:
    """Build a Chinese weekly audit from the R58 weekly run manifest."""
    manifest_path = weekly_manifest_path
    weekly_manifest = _load_weekly_manifest(manifest_path)
    data_asof = _parse_date(str(weekly_manifest.get("data_asof")))
    audit_run_id = run_id or _default_run_id(data_asof=data_asof)
    step_statuses = _step_statuses(weekly_manifest)
    artifact_checks = _artifact_checks(weekly_manifest, base_path=manifest_path)
    event_context_coverage = _event_context_coverage(weekly_manifest)
    event_threshold_context = _event_threshold_context(weekly_manifest)
    warnings = tuple(
        _warning_records(
            run_id=audit_run_id,
            step_statuses=step_statuses,
            artifact_checks=artifact_checks,
            event_context_coverage=event_context_coverage,
            event_threshold_context=event_threshold_context,
            weekly_manifest=weekly_manifest,
        )
    )
    audit_status = (
        "WEEKLY_AUDIT_READY"
        if not _has_warn(warnings)
        else "WEEKLY_AUDIT_READY_WITH_WARNINGS"
    )
    paths = _output_paths(data_asof=data_asof, output_dir=output_dir)
    result = ResearchWeeklyAuditResult(
        product_code=PRODUCT_CODE,
        run_id=audit_run_id,
        data_asof=data_asof,
        weekly_manifest_path=manifest_path,
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        warning_csv_path=paths["warning_csv"],
        manifest_path=paths["manifest"],
        audit_status=audit_status,
        step_statuses=step_statuses,
        artifact_checks=artifact_checks,
        event_context_coverage=event_context_coverage,
        event_threshold_context=event_threshold_context,
        warning_records=warnings,
        human_review_required=_human_review_required(warnings),
    )
    _write_outputs(result=result, weekly_manifest=weekly_manifest)
    return result


def _load_weekly_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ResearchWorkbenchError(f"weekly research manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ResearchWorkbenchError("weekly research manifest must be a JSON object")
    if payload.get("report_type") != "cf_weekly_research_run_manifest":
        raise ResearchWorkbenchError(
            "weekly manifest report_type must be cf_weekly_research_run_manifest"
        )
    if payload.get("product_code") != PRODUCT_CODE:
        raise ResearchWorkbenchError("weekly manifest product_code must be CF")
    boundary = payload.get("research_boundary")
    if not isinstance(boundary, dict):
        raise ResearchWorkbenchError("weekly manifest missing research_boundary")
    if boundary.get("fundamental_signal_status") != "not_connected":
        raise ResearchWorkbenchError(
            "weekly manifest fundamental_signal_status must be not_connected"
        )
    return payload


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ResearchWorkbenchError(f"invalid weekly audit data_asof: {value}") from exc


def _step_statuses(weekly_manifest: dict[str, Any]) -> dict[str, str]:
    steps = weekly_manifest.get("steps")
    if not isinstance(steps, dict):
        return {step: "missing" for step in EXPECTED_STEPS}
    statuses: dict[str, str] = {}
    for step_name in EXPECTED_STEPS:
        step = steps.get(step_name)
        if isinstance(step, dict):
            statuses[step_name] = str(step.get("status") or "unknown")
        else:
            statuses[step_name] = "missing"
    return statuses


def _artifact_checks(
    weekly_manifest: dict[str, Any],
    *,
    base_path: Path,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    steps = weekly_manifest.get("steps")
    if not isinstance(steps, dict):
        return checks
    for step_name, step_payload in steps.items():
        if not isinstance(step_payload, dict):
            continue
        for key, value in sorted(step_payload.items()):
            if not key.endswith("_path") or value in (None, ""):
                continue
            path = _resolve_artifact_path(value, base_path=base_path)
            checks.append(
                {
                    "step": str(step_name),
                    "path_key": str(key),
                    "path": str(path),
                    "exists": path.exists(),
                }
            )
    return checks


def _resolve_artifact_path(value: object, *, base_path: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    candidates = (project_root() / path, base_path.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _event_context_coverage(weekly_manifest: dict[str, Any]) -> dict[str, object]:
    steps = weekly_manifest.get("steps")
    steps_dict = steps if isinstance(steps, dict) else {}
    publish_pack = steps_dict.get("publish_pack")
    publish_dict = publish_pack if isinstance(publish_pack, dict) else {}
    context = publish_dict.get("validated_event_context")
    context_dict = context if isinstance(context, dict) else {}
    event_count = _int_or_zero(context_dict.get("r55_event_count"))
    context_count = _int_or_zero(context_dict.get("r55_context_available_count"))
    coverage_rate = None if event_count <= 0 else context_count / event_count
    return {
        "r56_event_context_connected": bool(
            context_dict.get("r56_event_context_connected")
        ),
        "r55_event_count": event_count,
        "r55_context_available_count": context_count,
        "coverage_rate": coverage_rate,
        "rule_version": context_dict.get("rule_version"),
    }


def _event_threshold_context(weekly_manifest: dict[str, Any]) -> dict[str, object]:
    steps = weekly_manifest.get("steps")
    steps_dict = steps if isinstance(steps, dict) else {}
    payload = steps_dict.get("event_threshold_sensitivity")
    step = payload if isinstance(payload, dict) else {}
    counts = step.get("review_decision_counts")
    count_dict = counts if isinstance(counts, dict) else {}
    normalized_counts = {
        "KEEP": _int_or_zero(count_dict.get("KEEP")),
        "WATCH": _int_or_zero(count_dict.get("WATCH")),
        "REVISE": _int_or_zero(count_dict.get("REVISE")),
        "REJECT": _int_or_zero(count_dict.get("REJECT")),
    }
    return {
        "connected": bool(step) and step.get("status") == "completed",
        "status": step.get("status", "missing"),
        "summary_parquet_path": step.get("summary_parquet_path"),
        "markdown_path": step.get("markdown_path"),
        "summary_row_count": _int_or_zero(step.get("summary_row_count")),
        "warning_count": _int_or_zero(step.get("warning_count")),
        "review_decision_counts": normalized_counts,
        "forward_returns_are_validation_labels": bool(
            step.get("forward_returns_are_validation_labels")
        ),
        "trading_instruction": step.get("trading_instruction"),
    }


def _warning_records(
    *,
    run_id: str,
    step_statuses: dict[str, str],
    artifact_checks: list[dict[str, object]],
    event_context_coverage: dict[str, object],
    event_threshold_context: dict[str, object],
    weekly_manifest: dict[str, Any],
) -> list[WeeklyResearchAuditWarningRecord]:
    warnings: list[WeeklyResearchAuditWarningRecord] = [
        WeeklyResearchAuditWarningRecord(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R59_RESEARCH_BOUNDARY_CONFIRMED",
            warning_message=(
                "latest signal-only 不包含 forward-return 验证；历史 forward returns "
                "只作为后验验证标签；fundamental_signal_status=not_connected。"
            ),
            human_review_required=(),
        )
    ]
    for step_name in WEEKLY_RESEARCH_STEPS:
        if step_statuses.get(step_name) != "completed":
            warnings.append(
                WeeklyResearchAuditWarningRecord(
                    run_id=run_id,
                    section="weekly_steps",
                    severity=WARN_SEVERITY,
                    warning_code="R59_WEEKLY_STEP_NOT_COMPLETED",
                    warning_message=f"{step_name} status={step_statuses.get(step_name)}",
                    human_review_required=("historical_event_interpretation",),
                )
            )
    missing = [check for check in artifact_checks if not bool(check.get("exists"))]
    if missing:
        warnings.append(
            WeeklyResearchAuditWarningRecord(
                run_id=run_id,
                section="artifacts",
                severity=WARN_SEVERITY,
                warning_code="R59_WEEKLY_ARTIFACT_MISSING",
                warning_message=f"{len(missing)} weekly artifact path(s) do not exist",
                human_review_required=("historical_event_interpretation",),
            )
        )
    if not event_context_coverage.get("r56_event_context_connected"):
        warnings.append(
            WeeklyResearchAuditWarningRecord(
                run_id=run_id,
                section="event_fundamental_context",
                severity=WARN_SEVERITY,
                warning_code="R59_EVENT_CONTEXT_NOT_CONNECTED",
                warning_message=(
                    "R56/R57 event-fundamental context was not connected in publish pack"
                ),
                human_review_required=("fundamental_context_interpretation",),
            )
        )
    event_count = _int_or_zero(event_context_coverage.get("r55_event_count"))
    context_count = _int_or_zero(event_context_coverage.get("r55_context_available_count"))
    if event_count > 0 and context_count < event_count:
        warnings.append(
            WeeklyResearchAuditWarningRecord(
                run_id=run_id,
                section="event_fundamental_context",
                severity=WARN_SEVERITY,
                warning_code="R59_EVENT_CONTEXT_COVERAGE_INCOMPLETE",
                warning_message=f"fundamental context coverage {context_count}/{event_count}",
                human_review_required=("fundamental_context_interpretation",),
            )
        )
    if event_threshold_context.get("connected"):
        counts = event_threshold_context.get("review_decision_counts")
        counts_dict = counts if isinstance(counts, dict) else {}
        if sum(_int_or_zero(value) for value in counts_dict.values()) <= 0:
            warnings.append(
                WeeklyResearchAuditWarningRecord(
                    run_id=run_id,
                    section="event_threshold_sensitivity",
                    severity=WARN_SEVERITY,
                    warning_code="R59_EVENT_THRESHOLD_COUNTS_MISSING",
                    warning_message="R60 review decision counts are missing from weekly manifest",
                    human_review_required=("event_thresholds",),
                )
            )
        if not event_threshold_context.get("forward_returns_are_validation_labels"):
            warnings.append(
                WeeklyResearchAuditWarningRecord(
                    run_id=run_id,
                    section="event_threshold_sensitivity",
                    severity=WARN_SEVERITY,
                    warning_code="R59_EVENT_THRESHOLD_BOUNDARY_MISSING",
                    warning_message="R60 forward returns boundary is not explicit",
                    human_review_required=("event_thresholds",),
                )
            )
        if event_threshold_context.get("trading_instruction") != "not_a_trading_instruction":
            warnings.append(
                WeeklyResearchAuditWarningRecord(
                    run_id=run_id,
                    section="event_threshold_sensitivity",
                    severity=WARN_SEVERITY,
                    warning_code="R59_EVENT_THRESHOLD_TRADING_BOUNDARY_MISSING",
                    warning_message="R60 trading boundary is not explicit",
                    human_review_required=("event_thresholds",),
                )
            )
    boundary = weekly_manifest.get("research_boundary")
    boundary_dict = boundary if isinstance(boundary, dict) else {}
    if boundary_dict.get("trading_instruction") != "not_a_trading_instruction":
        warnings.append(
            WeeklyResearchAuditWarningRecord(
                run_id=run_id,
                section="research_boundary",
                severity=WARN_SEVERITY,
                warning_code="R59_TRADING_BOUNDARY_MISSING",
                warning_message="weekly manifest trading boundary is not explicit",
                human_review_required=("publish_wording",),
            )
        )
    return warnings


def _write_outputs(
    *,
    result: ResearchWeeklyAuditResult,
    weekly_manifest: dict[str, Any],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text(
        _render_markdown(result=result, weekly_manifest=weekly_manifest),
        encoding="utf-8",
    )
    result.json_path.write_text(
        json.dumps(
            _json_safe(
                {
                    "report_type": "weekly_research_audit",
                    "rule_version": WEEKLY_RESEARCH_AUDIT_VERSION,
                    "generated_at": utc_now().isoformat(),
                    "summary": result.to_summary(),
                    "artifact_checks": result.artifact_checks,
                    "weekly_manifest": weekly_manifest,
                }
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_warning_csv(result)
    result.manifest_path.write_text(
        json.dumps(
            _json_safe(
                {
                    "report_type": "weekly_research_audit",
                    "rule_version": WEEKLY_RESEARCH_AUDIT_VERSION,
                    "generated_at": utc_now().isoformat(),
                    **result.to_summary(),
                }
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: ResearchWeeklyAuditResult,
    weekly_manifest: dict[str, Any],
) -> str:
    boundary = weekly_manifest.get("research_boundary")
    boundary_dict = boundary if isinstance(boundary, dict) else {}
    lines = [
        f"# CF 周更研究审计 R59 - {result.data_asof.isoformat()}",
        "",
        "## 数据状态",
        "",
        "- 报告类型：`weekly_research_audit`",
        f"- 状态：`{result.audit_status}`",
        f"- Run ID：`{result.run_id}`",
        f"- 数据截至：`{result.data_asof.isoformat()}`",
        f"- 周更 manifest：`{result.weekly_manifest_path}`",
        f"- weekly_chain_enabled：`{weekly_manifest.get('weekly_chain_enabled')}`",
        "",
        "## 周更链路完成情况",
        "",
        "| 环节 | 状态 |",
        "| --- | --- |",
    ]
    for step_name, status in result.step_statuses.items():
        lines.append(f"| `{step_name}` | `{status}` |")
    lines.extend(
        [
            "",
            "## R41 历史证据",
            "",
            *_step_lines(weekly_manifest, "historical_evidence"),
            "",
            "## R55 事件解释与基本面上下文覆盖",
            "",
            *_step_lines(weekly_manifest, "event_explanation"),
            f"- R55 事件明细数：`{result.event_context_coverage.get('r55_event_count')}`",
            "- 已匹配事件日前基本面上下文："
            f"`{result.event_context_coverage.get('r55_context_available_count')}`",
            f"- 覆盖率：`{_fmt_percent(result.event_context_coverage.get('coverage_rate'))}`",
            f"- 规则版本：`{result.event_context_coverage.get('rule_version')}`",
            "",
            "## R60 事件阈值敏感性",
            "",
            *_step_lines(weekly_manifest, "event_threshold_sensitivity"),
            "- 复核候选计数："
            f"`KEEP={_threshold_count(result.event_threshold_context, 'KEEP')}` / "
            f"`WATCH={_threshold_count(result.event_threshold_context, 'WATCH')}` / "
            f"`REVISE={_threshold_count(result.event_threshold_context, 'REVISE')}` / "
            f"`REJECT={_threshold_count(result.event_threshold_context, 'REJECT')}`",
            "- R60 只作为历史阈值复核底稿；候选动作必须人工复核。",
            "- R60 forward_return 只能作为历史后验验证标签，不得用于 latest signal-only。",
            "",
            "## R56 验证型报告",
            "",
            *_step_lines(weekly_manifest, "validated_brief"),
            "",
            "## R57 发布包",
            "",
            *_step_lines(weekly_manifest, "publish_pack"),
            "",
            "## 事件阈值人工复核",
            "",
            "- 复核对象：趋势起点/中继/衰竭/终点、主力切换、持仓异常、曲线突变。",
            "- 阈值复核：至少比较 0.90、0.95、0.975 分位阈值下的事件数、"
            "命中率、收益分布和年度分布。",
            "- 判定动作：`KEEP` / `WATCH` / `REVISE` / `REJECT`，并记录复核人、"
            "日期、理由和下次复核时间。",
            "- forward return 只能作为历史后验验证标签，不得用于 latest signal-only 当日结论。",
            "",
            "## 基本面解释人工复核",
            "",
            "- 复核字段：来源、单位、频率、统计期、发布时间、口径切换、缺失和停更。",
            "- 方向约定：库存/仓单/进口增加通常解释为供应压力，基差扩大和"
            "下游负荷改善通常解释为支撑，但必须结合指标口径确认。",
            "- 月频或周频指标不能假设为日频；未知发布日期时只能按统计期做解释观察。",
            "- 基本面上下文保持 `fundamental_signal_status=not_connected`，"
            "不进入 `composite_score`。",
            "",
            "## 警告与缺失项",
            "",
        ]
    )
    for warning in result.warning_records:
        if warning.severity == INFO_SEVERITY:
            continue
        lines.append(f"- `{warning.warning_code}`：{warning.warning_message}")
    if result.warning_count == 0:
        lines.append("- 暂无阻断性警告。")
    lines.extend(
        [
            "",
            "## 下周动作建议",
            "",
            "- 先复核 R55 事件阈值敏感性，再判断是否固化事件解释口径。",
            "- 对 R54 基本面上下文做指标级人工签核，尤其是进口、仓单、库存和纺织链。",
            "- 周更继续运行 R41 -> R55 -> R60 -> R56 -> R57 -> R59，"
            "月度再复核参数阈值和口径切换。",
            "",
            "## 研究边界",
            "",
            "- latest signal-only 不包含 forward-return 验证。",
            "- 历史 forward returns 只作为后验验证标签。",
            f"- fundamental_signal_status：`{boundary_dict.get('fundamental_signal_status')}`",
            "- 基本面解释不生成 `fundamental_signal`，不进入 `signal_matrix` 或 "
            "`composite_score`。",
            "- HUMAN_REVIEW_REQUIRED：事件阈值、基本面口径、发布时间、发布文本均需人工复核。",
            "- 本报告不构成交易指令。",
        ]
    )
    return "\n".join(lines) + "\n"


def _step_lines(weekly_manifest: dict[str, Any], step_name: str) -> list[str]:
    steps = weekly_manifest.get("steps")
    steps_dict = steps if isinstance(steps, dict) else {}
    payload = steps_dict.get(step_name)
    if not isinstance(payload, dict):
        return [f"- `{step_name}`：未在 manifest 中出现。"]
    lines = [f"- 状态：`{payload.get('status')}`"]
    for key, value in sorted(payload.items()):
        if key == "status" or isinstance(value, dict):
            continue
        lines.append(f"- {key}：`{value}`")
    return lines


def _threshold_count(context: dict[str, object], key: str) -> int:
    counts = context.get("review_decision_counts")
    counts_dict = counts if isinstance(counts, dict) else {}
    return _int_or_zero(counts_dict.get(key))


def _write_warning_csv(result: ResearchWeeklyAuditResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in result.warning_records])


def _output_paths(*, data_asof: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{data_asof.isoformat()}_weekly_research_audit"
    return {
        "markdown": root / f"{stem}.md",
        "json": root / f"{stem}.json",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _human_review_required(
    warnings: (
        tuple[WeeklyResearchAuditWarningRecord, ...]
        | list[WeeklyResearchAuditWarningRecord]
    ),
) -> tuple[str, ...]:
    values: list[str] = list(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        values.extend(warning.human_review_required)
    return tuple(dict.fromkeys(values))


def _research_boundary_payload() -> dict[str, object]:
    return {
        "latest_signal_only_contains_forward_return_validation": False,
        "historical_forward_returns_are_validation_labels": True,
        "fundamental_signal_status": "not_connected",
        "trading_instruction": "not_a_trading_instruction",
        "human_review_required": list(HUMAN_REVIEW_REQUIRED),
    }


def _default_run_id(*, data_asof: date) -> str:
    return f"r59_weekly_audit_{PRODUCT_CODE}_{data_asof.isoformat()}_{uuid.uuid4().hex[:8]}"


def _has_warn(warnings: tuple[WeeklyResearchAuditWarningRecord, ...]) -> bool:
    return any(warning.severity != INFO_SEVERITY for warning in warnings)


def _int_or_zero(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _fmt_percent(value: object) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "NA"


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
