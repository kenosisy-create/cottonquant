"""R65 CF stage decision pack before non-CF expansion review."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
STAGE_DECISION_PACK_VERSION = "R65_cf_stage_decision_pack_v1"
OUTPUT_DIR = "stage_decision"
HUMAN_REVIEW_REQUIRED = (
    "cf_mainline_evidence_interpretation",
    "option_signal_filter_rules_before_expansion",
    "event_thresholds",
    "fundamental_data_source_and_signal_rules",
    "publish_pack_readability_and_compliance",
    "product_expansion_go_no_go",
)


@dataclass(frozen=True)
class ResearchStageDecisionPackResult:
    """Result of building the R65 stage decision pack."""

    product_code: str
    run_id: str
    data_asof: date
    decision_status: str
    recommended_next_step: str
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    daily_markdown_path: Path | None
    weekly_audit_json_path: Path
    expansion_gate_json_path: Path
    latest_signal_json_path: Path | None
    option_factor_json_path: Path | None
    event_threshold_json_path: Path | None
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "data_asof": self.data_asof.isoformat(),
            "decision_status": self.decision_status,
            "recommended_next_step": self.recommended_next_step,
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "daily_markdown_path": (
                None if self.daily_markdown_path is None else str(self.daily_markdown_path)
            ),
            "weekly_audit_json_path": str(self.weekly_audit_json_path),
            "expansion_gate_json_path": str(self.expansion_gate_json_path),
            "latest_signal_json_path": (
                None if self.latest_signal_json_path is None else str(self.latest_signal_json_path)
            ),
            "option_factor_json_path": (
                None if self.option_factor_json_path is None else str(self.option_factor_json_path)
            ),
            "event_threshold_json_path": (
                None
                if self.event_threshold_json_path is None
                else str(self.event_threshold_json_path)
            ),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_stage_decision_pack(
    *,
    weekly_audit_json_path: Path,
    expansion_gate_json_path: Path,
    latest_signal_json_path: Path | None = None,
    option_factor_json_path: Path | None = None,
    event_threshold_json_path: Path | None = None,
    output_dir: Path | None = None,
    daily_output_root: Path | None = None,
    run_id: str | None = None,
) -> ResearchStageDecisionPackResult:
    """Build a Chinese stage decision pack from the refreshed CF evidence chain.

    R65 只汇总已经生成的研究证据和扩展门结果，不接入新品种数据，
    也不会把历史后验标签写成交易结论。
    """
    weekly = _load_weekly_audit(weekly_audit_json_path)
    gate = _load_expansion_gate(expansion_gate_json_path)
    latest = _load_optional_json(latest_signal_json_path, context="latest signal JSON")
    option = _load_optional_json(option_factor_json_path, context="option factor JSON")
    threshold = _load_optional_json(
        event_threshold_json_path,
        context="event threshold sensitivity JSON",
    )

    data_asof = _resolve_data_asof(weekly=weekly, latest=latest, gate=gate)
    decision_status = _decision_status(weekly=weekly, gate=gate)
    recommended_next_step = _recommended_next_step(decision_status)
    pack_run_id = run_id or _default_run_id(data_asof)
    markdown_path = _markdown_path(data_asof=data_asof, output_dir=output_dir)
    json_path = _json_path(data_asof=data_asof, output_dir=output_dir)
    manifest_path = _manifest_path(data_asof=data_asof, output_dir=output_dir)
    daily_markdown_path = (
        None
        if daily_output_root is None
        else daily_output_root / PRODUCT_CODE / data_asof.isoformat() / "stage_decision_pack.md"
    )
    human_review = _human_review_required(weekly=weekly, gate=gate, latest=latest, option=option)
    result = ResearchStageDecisionPackResult(
        product_code=PRODUCT_CODE,
        run_id=pack_run_id,
        data_asof=data_asof,
        decision_status=decision_status,
        recommended_next_step=recommended_next_step,
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=manifest_path,
        daily_markdown_path=daily_markdown_path,
        weekly_audit_json_path=weekly_audit_json_path,
        expansion_gate_json_path=expansion_gate_json_path,
        latest_signal_json_path=latest_signal_json_path,
        option_factor_json_path=option_factor_json_path,
        event_threshold_json_path=event_threshold_json_path,
        human_review_required=human_review,
    )
    context = _context_payload(
        result=result,
        weekly=weekly,
        gate=gate,
        latest=latest,
        option=option,
        threshold=threshold,
    )
    markdown = _render_markdown(context)
    _write_outputs(result=result, context=context, markdown=markdown)
    return result


def _load_weekly_audit(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, context="weekly audit JSON")
    if payload.get("report_type") != "weekly_research_audit":
        raise ResearchWorkbenchError("weekly audit JSON must be weekly_research_audit")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ResearchWorkbenchError("weekly audit JSON missing summary")
    if summary.get("data_asof") is None:
        raise ResearchWorkbenchError("weekly audit JSON missing summary.data_asof")
    return payload


def _load_expansion_gate(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, context="expansion gate JSON")
    if payload.get("product_code") != PRODUCT_CODE:
        raise ResearchWorkbenchError("expansion gate JSON product_code must be CF")
    if payload.get("gate_version") != "R52":
        raise ResearchWorkbenchError("expansion gate JSON must be R52")
    return payload


def _load_optional_json(path: Path | None, *, context: str) -> dict[str, Any] | None:
    if path is None:
        return None
    return _load_json_object(path, context=context)


def _load_json_object(path: Path, *, context: str) -> dict[str, Any]:
    if not path.exists():
        raise ResearchWorkbenchError(f"{context} not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ResearchWorkbenchError(f"{context} must be a JSON object")
    return payload


def _resolve_data_asof(
    *,
    weekly: dict[str, Any],
    latest: dict[str, Any] | None,
    gate: dict[str, Any],
) -> date:
    weekly_summary = _dict_value(weekly, "summary")
    data_asof = weekly_summary.get("data_asof") or weekly.get("data_asof")
    if latest is not None:
        latest_asof = latest.get("data_asof") or latest.get("trade_date")
        if latest_asof is not None and str(latest_asof) != str(data_asof):
            raise ResearchWorkbenchError(
                f"latest signal data_asof {latest_asof} does not match weekly data_asof {data_asof}"
            )
    if gate.get("passed") is None:
        raise ResearchWorkbenchError("expansion gate JSON missing passed field")
    return date.fromisoformat(str(data_asof))


def _decision_status(*, weekly: dict[str, Any], gate: dict[str, Any]) -> str:
    weekly_summary = _dict_value(weekly, "summary")
    missing_count = int(weekly_summary.get("artifact_missing_count") or 0)
    blocked = gate.get("blocked_requirements")
    blocked_requirements = blocked if isinstance(blocked, list) else []
    gate_passed = bool(gate.get("passed"))
    if missing_count > 0:
        return "NOT_READY_MISSING_ARTIFACTS"
    if blocked_requirements or not gate_passed:
        return "NOT_READY_GATE_BLOCKED"
    if str(gate.get("status")) == "HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION":
        return "READY_FOR_HUMAN_REVIEW"
    return "READY_FOR_STAGE_REVIEW"


def _recommended_next_step(decision_status: str) -> str:
    if decision_status == "READY_FOR_HUMAN_REVIEW":
        return "先完成人工复核，再决定是否启动一个同交易所、同数据结构的非 CF 试点。"
    if decision_status == "READY_FOR_STAGE_REVIEW":
        return "可以进入阶段评审；仍需保留不构成交易指令和人工复核边界。"
    if decision_status == "NOT_READY_MISSING_ARTIFACTS":
        return "先补齐缺失研究产物，再重新生成周审计和扩展门。"
    return "先解决 R52 扩展门阻断项，不启动新品种接入。"


def _context_payload(
    *,
    result: ResearchStageDecisionPackResult,
    weekly: dict[str, Any],
    gate: dict[str, Any],
    latest: dict[str, Any] | None,
    option: dict[str, Any] | None,
    threshold: dict[str, Any] | None,
) -> dict[str, Any]:
    weekly_summary = _dict_value(weekly, "summary")
    latest_summary = _latest_summary(latest)
    option_summary = _option_summary(option, main_contract=latest_summary.get("main_contract"))
    threshold_summary = _threshold_summary(threshold, weekly_summary=weekly_summary)
    gate_summary = _gate_summary(gate)
    return {
        **result.to_summary(),
        "report_type": "cf_stage_decision_pack",
        "rule_version": STAGE_DECISION_PACK_VERSION,
        "generated_at": utc_now().isoformat(),
        "weekly_summary": weekly_summary,
        "latest_summary": latest_summary,
        "option_summary": option_summary,
        "threshold_summary": threshold_summary,
        "expansion_gate_summary": gate_summary,
        "research_boundary": {
            "latest_signal_only_contains_forward_return_validation": False,
            "historical_forward_returns_are_validation_labels": True,
            "fundamental_signal_status": "not_connected",
            "trading_instruction": "not_a_trading_instruction",
            "does_not_start_non_cf_ingest": True,
        },
    }


def _latest_summary(latest: dict[str, Any] | None) -> dict[str, Any]:
    if latest is None:
        return {"provided": False}
    trend = _dict_value(latest, "trend_phase")
    matrix = _dict_value(latest, "signal_matrix_context")
    primary_row = _primary_matrix_row(matrix)
    return {
        "provided": True,
        "data_asof": latest.get("data_asof") or latest.get("trade_date"),
        "main_contract": latest.get("main_contract"),
        "signal_direction": latest.get("signal_direction"),
        "trend_phase_code": trend.get("phase_code"),
        "trend_phase_label": trend.get("phase_label"),
        "trend_direction": trend.get("direction"),
        "primary_horizon": matrix.get("primary_horizon"),
        "primary_direction": matrix.get("primary_direction"),
        "primary_confidence": matrix.get("primary_confidence"),
        "primary_option_signal": primary_row.get("option_signal"),
        "primary_option_signal_direction": primary_row.get("option_signal_direction"),
        "primary_evidence_level": primary_row.get("evidence_level"),
    }


def _primary_matrix_row(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = matrix.get("rows")
    primary_horizon = matrix.get("primary_horizon")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("horizon") == primary_horizon:
            return row
    for row in rows:
        if isinstance(row, dict):
            return row
    return {}


def _option_summary(
    option: dict[str, Any] | None,
    *,
    main_contract: object,
) -> dict[str, Any]:
    if option is None:
        return {"provided": False}
    latest_rows = option.get("latest_rows")
    selected = _select_option_row(latest_rows, main_contract=main_contract)
    return {
        "provided": True,
        "status": option.get("status"),
        "passed": option.get("passed"),
        "option_row_count": option.get("option_row_count"),
        "eligible_option_row_count": option.get("eligible_option_row_count"),
        "excluded_option_row_count": option.get("excluded_option_row_count"),
        "factor_row_count": option.get("factor_row_count"),
        "warning_count": option.get("warning_count"),
        "selected_underlying_contract": selected.get("underlying_contract"),
        "selected_factor_status": selected.get("factor_status"),
        "selected_atm_iv_rank": selected.get("atm_iv_rank"),
        "selected_pcr_oi": selected.get("pcr_oi"),
        "selected_pcr_volume": selected.get("pcr_volume"),
        "selected_skew_proxy": selected.get("skew_proxy"),
        "model_boundary": selected.get("model_boundary"),
    }


def _select_option_row(rows: object, *, main_contract: object) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    main_text = str(main_contract or "")
    for row in rows:
        if isinstance(row, dict) and str(row.get("underlying_contract")) == main_text:
            return row
    for row in rows:
        if isinstance(row, dict):
            return row
    return {}


def _threshold_summary(
    threshold: dict[str, Any] | None,
    *,
    weekly_summary: dict[str, Any],
) -> dict[str, Any]:
    if threshold is not None:
        threshold_summary = _dict_value(threshold, "summary") or threshold
        return {
            "provided": True,
            "status": threshold_summary.get("status"),
            "passed": threshold_summary.get("passed"),
            "summary_row_count": threshold_summary.get("summary_row_count"),
            "detail_row_count": threshold_summary.get("detail_row_count"),
            "review_decision_counts": threshold_summary.get("review_decision_counts"),
            "warning_count": threshold_summary.get("warning_count"),
            "forward_returns_are_validation_labels": threshold_summary.get(
                "forward_returns_are_validation_labels"
            ),
        }
    event_context = _dict_value(weekly_summary, "event_threshold_context")
    return {
        "provided": False,
        "status": event_context.get("status"),
        "summary_row_count": event_context.get("summary_row_count"),
        "review_decision_counts": event_context.get("review_decision_counts"),
        "forward_returns_are_validation_labels": event_context.get(
            "forward_returns_are_validation_labels"
        ),
    }


def _gate_summary(gate: dict[str, Any]) -> dict[str, Any]:
    requirements = gate.get("requirements")
    pass_count = 0
    human_review_count = 0
    blocked_count = 0
    if isinstance(requirements, list):
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            status = str(requirement.get("status") or "")
            if status == "PASS":
                pass_count += 1
            elif status == "HUMAN_REVIEW_REQUIRED":
                human_review_count += 1
            elif bool(requirement.get("blocking")):
                blocked_count += 1
    return {
        "status": gate.get("status"),
        "passed": gate.get("passed"),
        "candidate_scope": gate.get("candidate_scope"),
        "blocked_requirements": gate.get("blocked_requirements") or [],
        "requirement_count": gate.get("requirement_count"),
        "pass_count": pass_count,
        "human_review_count": human_review_count,
        "blocked_count": blocked_count,
        "human_review_required": gate.get("human_review_required") or [],
    }


def _human_review_required(
    *,
    weekly: dict[str, Any],
    gate: dict[str, Any],
    latest: dict[str, Any] | None,
    option: dict[str, Any] | None,
) -> tuple[str, ...]:
    values: list[str] = list(HUMAN_REVIEW_REQUIRED)
    weekly_summary = _dict_value(weekly, "summary")
    for source in (
        weekly_summary.get("human_review_required"),
        gate.get("human_review_required"),
        None if latest is None else latest.get("human_review_required"),
        None if option is None else option.get("human_review_required"),
    ):
        if isinstance(source, list):
            values.extend(str(value) for value in source)
    return tuple(dict.fromkeys(value for value in values if value))


def _render_markdown(context: dict[str, Any]) -> str:
    latest = _dict_value(context, "latest_summary")
    option = _dict_value(context, "option_summary")
    threshold = _dict_value(context, "threshold_summary")
    weekly = _dict_value(context, "weekly_summary")
    event_context = _dict_value(weekly, "event_context_coverage")
    gate = _dict_value(context, "expansion_gate_summary")
    lines = [
        f"# CF 阶段决策包 R65 - {context['data_asof']}",
        "",
        "## 一、阶段结论",
        "",
        f"- 决策状态：`{context['decision_status']}`",
        f"- 建议下一步：{context['recommended_next_step']}",
        f"- R52 扩展门状态：`{gate.get('status')}`",
        f"- R52 技术门槛通过：`{gate.get('passed')}`",
        f"- 周更产物缺失数：`{weekly.get('artifact_missing_count')}`",
        "",
        "## 二、当前 CF 市场状态",
        "",
        f"- 主力合约：`{latest.get('main_contract', '未提供')}`",
        f"- 最新方向：`{latest.get('signal_direction', '未提供')}`",
        f"- 趋势阶段：`{latest.get('trend_phase_code', '未提供')}` "
        f"{latest.get('trend_phase_label', '')}",
        f"- 主周期：`{latest.get('primary_horizon', '未提供')}D`；"
        f"方向：`{latest.get('primary_direction', '未提供')}`；"
        f"置信度：`{latest.get('primary_confidence', '未提供')}`",
        f"- 期权过滤：`{latest.get('primary_option_signal', '未提供')}`",
        "",
        "## 三、历史证据链",
        "",
        f"- 周更审计状态：`{weekly.get('status')}`",
        f"- 事件基本面上下文覆盖率：`{event_context.get('coverage_rate')}`",
        f"- R55 事件数：`{event_context.get('r55_event_count')}`",
        f"- R55 已覆盖基本面上下文：`{event_context.get('r55_context_available_count')}`",
        "",
        "## 四、事件阈值复核",
        "",
        f"- R60 状态：`{threshold.get('status')}`",
        f"- 阈值摘要行数：`{threshold.get('summary_row_count')}`",
        f"- 阈值决策分布：`{_json_inline(threshold.get('review_decision_counts'))}`",
        f"- forward return 属性：历史后验验证标签 = "
        f"`{threshold.get('forward_returns_are_validation_labels')}`",
        "",
        "## 五、期权联动",
        "",
        f"- 期权因子状态：`{option.get('status', '未提供')}`",
        f"- 期权因子行数：`{option.get('factor_row_count', '未提供')}`",
        f"- 可用期权行：`{option.get('eligible_option_row_count', '未提供')}`",
        f"- 被过滤期权行：`{option.get('excluded_option_row_count', '未提供')}`",
        f"- 主力标的期权状态：`{option.get('selected_factor_status', '未提供')}`",
        f"- ATM IV rank：`{option.get('selected_atm_iv_rank', '未提供')}`",
        f"- PCR OI：`{option.get('selected_pcr_oi', '未提供')}`",
        f"- PCR volume：`{option.get('selected_pcr_volume', '未提供')}`",
        f"- 模型边界：{option.get('model_boundary', '期权数据未提供')}",
        "",
        "## 六、扩展门结论",
        "",
        f"- 候选范围：`{gate.get('candidate_scope')}`",
        f"- 需求总数：`{gate.get('requirement_count')}`",
        f"- PASS 数：`{gate.get('pass_count')}`",
        f"- 人工复核数：`{gate.get('human_review_count')}`",
        f"- 阻断项：`{_json_inline(gate.get('blocked_requirements'))}`",
        "",
        "## 七、人工复核清单",
        "",
    ]
    for item in context["human_review_required"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 八、研究边界",
            "",
            "- 本决策包只汇总既有 CF 证据，不启动非 CF 数据接入。",
            "- latest signal-only 不包含 forward-return 验证。",
            "- 历史 forward returns 只作为后验验证标签。",
            "- 基本面上下文目前为解释层，`fundamental_signal_status=not_connected`。",
            "- 期权 IV/Greek 为研究 proxy，不作为精确风险暴露。",
            "- 不构成交易指令。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_outputs(
    *,
    result: ResearchStageDecisionPackResult,
    context: dict[str, Any],
    markdown: str,
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text(markdown, encoding="utf-8")
    if result.daily_markdown_path is not None:
        result.daily_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.markdown_path, result.daily_markdown_path)
    result.json_path.write_text(
        json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "run_id": result.run_id,
        "product_code": result.product_code,
        "report_type": "cf_stage_decision_pack",
        "rule_version": STAGE_DECISION_PACK_VERSION,
        "data_asof": result.data_asof.isoformat(),
        "generated_at": utc_now().isoformat(),
        "decision_status": result.decision_status,
        "recommended_next_step": result.recommended_next_step,
        "markdown_path": str(result.markdown_path),
        "json_path": str(result.json_path),
        "daily_markdown_path": (
            None if result.daily_markdown_path is None else str(result.daily_markdown_path)
        ),
        "weekly_audit_json_path": str(result.weekly_audit_json_path),
        "expansion_gate_json_path": str(result.expansion_gate_json_path),
        "latest_signal_json_path": (
            None if result.latest_signal_json_path is None else str(result.latest_signal_json_path)
        ),
        "option_factor_json_path": (
            None if result.option_factor_json_path is None else str(result.option_factor_json_path)
        ),
        "event_threshold_json_path": (
            None
            if result.event_threshold_json_path is None
            else str(result.event_threshold_json_path)
        ),
        "human_review_required": list(result.human_review_required),
        "research_boundary": context["research_boundary"],
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _json_inline(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _markdown_path(*, data_asof: date, output_dir: Path | None) -> Path:
    root = output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{data_asof.isoformat()}_stage_decision_pack.md"


def _json_path(*, data_asof: date, output_dir: Path | None) -> Path:
    root = output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{data_asof.isoformat()}_stage_decision_pack.json"


def _manifest_path(*, data_asof: date, output_dir: Path | None) -> Path:
    root = output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{data_asof.isoformat()}_stage_decision_pack_manifest.json"


def _default_run_id(data_asof: date) -> str:
    return f"r65_stage_decision_{PRODUCT_CODE}_{data_asof.isoformat()}_{uuid.uuid4().hex[:8]}"
