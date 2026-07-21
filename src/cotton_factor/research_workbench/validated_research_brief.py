"""R43 validated research brief for CF."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.research_framework import (
    RESEARCH_FRAMEWORK_VERSION,
    build_research_framework_context,
    display_threshold_status,
    research_framework_markdown_lines,
)

PRODUCT_CODE = "CF"
VALIDATED_BRIEF_VERSION = "R43_validated_research_brief_v1"
VALIDATED_BRIEF_EVENT_CONTEXT_VERSION = "R56_validated_brief_event_context_v1"
VALIDATED_BRIEF_THRESHOLD_CONTEXT_VERSION = "R61_validated_brief_threshold_context_v1"
VALIDATED_BRIEF_FUTURES_OPTION_CONTEXT_VERSION = "R70_validated_brief_futures_option_context_v1"
VALIDATED_BRIEF_FUTURES_OPTION_PLAYBOOK_CONTEXT_VERSION = (
    "R72_validated_brief_futures_option_playbook_context_v1"
)
VALIDATED_BRIEF_WATCH_WINDOW_CONTEXT_VERSION = "R77_validated_brief_watch_window_v1"
VALIDATED_BRIEF_STATE_TRANSITION_CONTEXT_VERSION = (
    "R82_validated_brief_state_transition_context_v1"
)
VALIDATED_BRIEF_OPTION_VOLATILITY_CONTEXT_VERSION = (
    "R82_validated_brief_option_volatility_context_v1"
)
OUTPUT_DIR = "validated_brief"
HUMAN_REVIEW_REQUIRED = (
    "validated_research_interpretation",
    "historical_evidence_interpretation",
    "historical_event_interpretation",
    "event_threshold_sensitivity_review",
    "futures_option_divergence_interpretation",
    "futures_option_playbook_interpretation",
    "current_watch_window_interpretation",
    "state_transition_competing_risk_interpretation",
    "option_volatility_term_structure_interpretation",
    "factor_thresholds",
    "cost_model_parameters",
    "trend_phase_rules",
    "fundamental_observation_interpretation",
)


@dataclass(frozen=True)
class ResearchValidatedBriefResult:
    """Result of building R43 validated research brief."""

    product_code: str
    run_id: str
    data_asof: date
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    daily_markdown_path: Path | None
    latest_signal_json_path: Path
    historical_evidence_decay_path: Path
    historical_evidence_stability_path: Path
    event_summary_path: Path
    event_detail_path: Path | None
    event_threshold_summary_path: Path | None
    futures_option_divergence_json_path: Path | None
    futures_option_playbook_json_path: Path | None
    current_watch_window_json_path: Path | None
    state_transition_json_path: Path | None
    option_volatility_json_path: Path | None
    fundamental_observation_json_path: Path | None
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "data_asof": self.data_asof.isoformat(),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "daily_markdown_path": (
                None if self.daily_markdown_path is None else str(self.daily_markdown_path)
            ),
            "latest_signal_json_path": str(self.latest_signal_json_path),
            "historical_evidence_decay_path": str(self.historical_evidence_decay_path),
            "historical_evidence_stability_path": str(self.historical_evidence_stability_path),
            "event_summary_path": str(self.event_summary_path),
            "event_detail_path": (
                None if self.event_detail_path is None else str(self.event_detail_path)
            ),
            "event_threshold_summary_path": (
                None
                if self.event_threshold_summary_path is None
                else str(self.event_threshold_summary_path)
            ),
            "futures_option_divergence_json_path": (
                None
                if self.futures_option_divergence_json_path is None
                else str(self.futures_option_divergence_json_path)
            ),
            "futures_option_playbook_json_path": (
                None
                if self.futures_option_playbook_json_path is None
                else str(self.futures_option_playbook_json_path)
            ),
            "current_watch_window_json_path": (
                None
                if self.current_watch_window_json_path is None
                else str(self.current_watch_window_json_path)
            ),
            "state_transition_json_path": (
                None
                if self.state_transition_json_path is None
                else str(self.state_transition_json_path)
            ),
            "option_volatility_json_path": (
                None
                if self.option_volatility_json_path is None
                else str(self.option_volatility_json_path)
            ),
            "fundamental_observation_json_path": (
                None
                if self.fundamental_observation_json_path is None
                else str(self.fundamental_observation_json_path)
            ),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_validated_research_brief(
    *,
    latest_signal_json_path: Path | None = None,
    historical_evidence_decay_path: Path | None = None,
    historical_evidence_stability_path: Path | None = None,
    event_summary_path: Path | None = None,
    event_detail_path: Path | None = None,
    event_threshold_summary_path: Path | None = None,
    futures_option_divergence_json_path: Path | None = None,
    futures_option_playbook_json_path: Path | None = None,
    current_watch_window_json_path: Path | None = None,
    state_transition_json_path: Path | None = None,
    option_volatility_json_path: Path | None = None,
    fundamental_observation_json_path: Path | None = None,
    output_dir: Path | None = None,
    daily_output_root: Path | None = None,
    run_id: str | None = None,
) -> ResearchValidatedBriefResult:
    """Build a validated Chinese research brief from latest and historical evidence."""
    latest_path = latest_signal_json_path or _default_latest_signal_json_path()
    decay_path = historical_evidence_decay_path or _default_historical_decay_path()
    stability_path = historical_evidence_stability_path or _default_historical_stability_path()
    event_path = event_summary_path or _default_event_summary_path()

    latest = _load_latest_signal(latest_path)
    decay = _load_table(decay_path, required={"horizon", "mean_net_return_normal_cost"})
    stability = _load_table(
        stability_path,
        required={"horizon", "scheme_label_cn", "candidate_status", "stability_status"},
    )
    event_summary = _load_table(
        event_path,
        required={"event_type", "horizon", "event_count", "mean_forward_return"},
    )
    event_detail = (
        None if event_detail_path is None else _load_event_detail_table(event_detail_path)
    )
    event_threshold_summary = (
        None
        if event_threshold_summary_path is None
        else _load_event_threshold_summary(event_threshold_summary_path)
    )
    futures_option_divergence = (
        None
        if futures_option_divergence_json_path is None
        else _load_futures_option_divergence_context(futures_option_divergence_json_path)
    )
    futures_option_playbook = (
        None
        if futures_option_playbook_json_path is None
        else _load_futures_option_playbook_context(futures_option_playbook_json_path)
    )
    current_watch_window = (
        None
        if current_watch_window_json_path is None
        else _load_current_watch_window_context(current_watch_window_json_path)
    )
    state_transition = (
        None
        if state_transition_json_path is None
        else _load_state_transition_context(state_transition_json_path)
    )
    option_volatility = (
        None
        if option_volatility_json_path is None
        else _load_option_volatility_context(option_volatility_json_path)
    )
    fundamental = (
        None
        if fundamental_observation_json_path is None
        else _load_fundamental_observation(fundamental_observation_json_path)
    )
    data_asof = _parse_date(str(latest["data_asof"]))
    _validate_context_asof(
        data_asof=data_asof,
        label="R79 state transition",
        context=state_transition,
    )
    _validate_context_asof(
        data_asof=data_asof,
        label="R80/R81 option volatility",
        context=option_volatility,
    )
    brief_run_id = run_id or _default_run_id(data_asof=data_asof)
    research_framework_context = build_research_framework_context(
        latest=latest,
        decay=decay,
        stability=stability,
    )
    markdown_path = _markdown_path(data_asof=data_asof, output_dir=output_dir)
    json_path = _json_path(data_asof=data_asof, output_dir=output_dir)
    manifest_path = _manifest_path(data_asof=data_asof, output_dir=output_dir)
    daily_markdown_path = (
        None
        if daily_output_root is None
        else (
            daily_output_root
            / PRODUCT_CODE
            / data_asof.isoformat()
            / "validated_research_brief.md"
        )
    )
    result = ResearchValidatedBriefResult(
        product_code=PRODUCT_CODE,
        run_id=brief_run_id,
        data_asof=data_asof,
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=manifest_path,
        daily_markdown_path=daily_markdown_path,
        latest_signal_json_path=latest_path,
        historical_evidence_decay_path=decay_path,
        historical_evidence_stability_path=stability_path,
        event_summary_path=event_path,
        event_detail_path=event_detail_path,
        event_threshold_summary_path=event_threshold_summary_path,
        futures_option_divergence_json_path=futures_option_divergence_json_path,
        futures_option_playbook_json_path=futures_option_playbook_json_path,
        current_watch_window_json_path=current_watch_window_json_path,
        state_transition_json_path=state_transition_json_path,
        option_volatility_json_path=option_volatility_json_path,
        fundamental_observation_json_path=fundamental_observation_json_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    markdown = _render_markdown(
        result=result,
        latest=latest,
        decay=decay,
        stability=stability,
        event_summary=event_summary,
        event_detail=event_detail,
        event_threshold_summary=event_threshold_summary,
        futures_option_divergence=futures_option_divergence,
        futures_option_playbook=futures_option_playbook,
        current_watch_window=current_watch_window,
        state_transition=state_transition,
        option_volatility=option_volatility,
        fundamental=fundamental,
        research_framework_context=research_framework_context,
    )
    _write_markdown(result=result, markdown=markdown)
    _write_json(
        result=result,
        latest=latest,
        decay=decay,
        event_summary=event_summary,
        event_detail=event_detail,
        event_threshold_summary=event_threshold_summary,
        futures_option_divergence=futures_option_divergence,
        futures_option_playbook=futures_option_playbook,
        current_watch_window=current_watch_window,
        state_transition=state_transition,
        option_volatility=option_volatility,
        fundamental=fundamental,
        research_framework_context=research_framework_context,
    )
    _write_manifest(result=result)
    return result


def _load_latest_signal(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"latest signal JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_type") not in {None, "latest_signal_only"}:
        raise ResearchWorkbenchError("latest signal JSON must be latest_signal_only")
    if _contains_forward_return_label(payload):
        raise ResearchWorkbenchError("latest signal JSON must not contain forward_return labels")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ResearchWorkbenchError("latest signal JSON missing summary object")
    data_asof = payload.get("data_asof") or summary.get("data_status", {}).get("data_asof")
    if data_asof is None:
        raise ResearchWorkbenchError("latest signal JSON missing data_asof")
    return {
        "data_asof": data_asof,
        "main_contract": payload.get("main_contract"),
        "signal_direction": payload.get("signal_direction"),
        "trend_phase": payload.get("trend_phase") or summary.get("trend_phase"),
        "signal_matrix_context": payload.get("signal_matrix_context")
        or summary.get("signal_matrix_context"),
        "signal_threshold_context": payload.get("signal_threshold_context")
        or summary.get("signal_threshold_context"),
        "watch_items": summary.get("watch_items"),
        "research_boundary": summary.get("research_boundary"),
    }


def _load_fundamental_observation(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"fundamental observation JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_type") != "fundamental_observation":
        raise ResearchWorkbenchError("fundamental observation JSON must be fundamental_observation")
    if payload.get("fundamental_signal_status") != "not_connected":
        raise ResearchWorkbenchError("fundamental observation must remain not_connected")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ResearchWorkbenchError("fundamental observation JSON missing summary object")
    return payload


def _load_table(path: Path, *, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"validated brief input table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"validated brief input table missing columns: {missing}")
    return frame.copy()


def _load_event_detail_table(path: Path) -> pd.DataFrame:
    frame = _load_table(
        path,
        required={
            "event_date",
            "event_type",
            "fundamental_context_available",
            "fundamental_context_count",
            "fundamental_aligned_count",
            "fundamental_divergent_count",
            "fundamental_context_summary_cn",
            "fundamental_context_rule_version",
        },
    )
    working = frame.copy()
    working["event_date"] = pd.to_datetime(working["event_date"], errors="coerce").dt.date
    working = working.dropna(subset=["event_date"])
    if "fundamental_context_available" in working.columns:
        working["fundamental_context_available"] = _bool_series(
            working["fundamental_context_available"]
        )
    for column in (
        "fundamental_context_count",
        "fundamental_aligned_count",
        "fundamental_divergent_count",
    ):
        working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0).astype(int)
    if not working["fundamental_context_rule_version"].astype(str).str.startswith("R55").all():
        raise ResearchWorkbenchError("event detail table must contain R55 fundamental context rows")
    # R55 事件明细允许保留 forward_return_* 后验标签，但基本面解释字段本身必须来自事件日前可见数据。
    return working.sort_values(["event_date", "event_type"]).reset_index(drop=True)


def _load_event_threshold_summary(path: Path) -> pd.DataFrame:
    frame = _load_table(
        path,
        required={
            "threshold_scope",
            "event_type",
            "threshold_quantile",
            "horizon",
            "observation_count",
            "directional_hit_rate",
            "mean_forward_return",
            "review_decision_candidate",
            "forward_returns_are_validation_labels",
            "trading_instruction",
            "interpretation_status",
        },
    )
    working = frame.copy()
    # R60 可以进入 R56 的唯一前提：它仍然只是历史后验验证和人工复核材料。
    if not _bool_series(working["forward_returns_are_validation_labels"]).all():
        raise ResearchWorkbenchError(
            "event threshold summary must mark forward returns as validation labels"
        )
    if not working["trading_instruction"].astype(str).eq("not_a_trading_instruction").all():
        raise ResearchWorkbenchError(
            "event threshold summary must not contain trading instructions"
        )
    if not working["interpretation_status"].astype(str).eq("HUMAN_REVIEW_REQUIRED").all():
        raise ResearchWorkbenchError(
            "event threshold summary must remain HUMAN_REVIEW_REQUIRED"
        )
    for column in (
        "horizon",
        "observation_count",
        "directional_hit_rate",
        "mean_forward_return",
    ):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return working.reset_index(drop=True)


def _load_futures_option_divergence_context(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"R69 futures-option divergence JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_type") != "futures_option_divergence_research":
        raise ResearchWorkbenchError("R69 JSON must be futures_option_divergence_research")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ResearchWorkbenchError("R69 JSON missing result summary")
    boundary = payload.get("research_boundary")
    if isinstance(boundary, dict):
        if boundary.get("forward_returns_are_validation_labels") is not True:
            raise ResearchWorkbenchError("R69 forward returns must be validation labels")
        if boundary.get("trading_instruction") != "not_a_trading_instruction":
            raise ResearchWorkbenchError("R69 must not contain trading instructions")
    horizon_rows = _r69_rows(payload.get("horizon_summary"))
    node_rows = _r69_rows(payload.get("node_summary"))
    return {
        "connected": True,
        "source_path": str(path),
        "rule_version": VALIDATED_BRIEF_FUTURES_OPTION_CONTEXT_VERSION,
        "result": result,
        "directional_divergence_rows": _r69_directional_horizon_rows(horizon_rows),
        "ready_nodes": _r69_ready_nodes(node_rows),
        "forward_returns_are_validation_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _load_futures_option_playbook_context(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"R71 futures-option playbook JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_type") != "futures_option_divergence_playbook":
        raise ResearchWorkbenchError("R71 JSON must be futures_option_divergence_playbook")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ResearchWorkbenchError("R71 JSON missing summary")
    boundary = payload.get("research_boundary")
    if isinstance(boundary, dict):
        if boundary.get("forward_returns_are_validation_labels") is not True:
            raise ResearchWorkbenchError("R71 forward returns must be validation labels")
        if boundary.get("trading_instruction") != "not_a_trading_instruction":
            raise ResearchWorkbenchError("R71 must not contain trading instructions")
        if boundary.get("auto_reverse_allowed") is not False:
            raise ResearchWorkbenchError("R71 must not allow auto reverse")
    return {
        "connected": True,
        "source_path": str(path),
        "rule_version": VALIDATED_BRIEF_FUTURES_OPTION_PLAYBOOK_CONTEXT_VERSION,
        "summary": summary,
        "current_mapping_rows": _r69_rows(payload.get("current_mapping_rows"))[:12],
        "node_rows": _r69_rows(payload.get("node_rows"))[:12],
        "forward_returns_are_validation_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _load_current_watch_window_context(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"R77 current watch window JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_type") != "current_watch_window":
        raise ResearchWorkbenchError("R77 JSON must be current_watch_window")
    watch = payload.get("watch_window")
    if not isinstance(watch, dict):
        raise ResearchWorkbenchError("R77 JSON missing watch_window")
    boundary = payload.get("research_boundary")
    if not isinstance(boundary, dict):
        raise ResearchWorkbenchError("R77 JSON missing research_boundary")
    if boundary.get("latest_state_uses_future_data") is not False:
        raise ResearchWorkbenchError("R77 latest state must not use future data")
    if boundary.get("trading_instruction") != "not_a_trading_instruction":
        raise ResearchWorkbenchError("R77 must not contain trading instructions")
    return {
        "connected": True,
        "source_path": str(path),
        "rule_version": VALIDATED_BRIEF_WATCH_WINDOW_CONTEXT_VERSION,
        "watch_window": watch,
        "research_boundary": boundary,
    }


def _load_state_transition_context(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"R79 state transition JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    current_mapping = payload.get("current_mapping")
    overall_summary = payload.get("overall_summary")
    if not isinstance(current_mapping, dict):
        raise ResearchWorkbenchError("R79 JSON missing current_mapping")
    if not isinstance(overall_summary, list):
        raise ResearchWorkbenchError("R79 JSON missing overall_summary")
    if not str(current_mapping.get("rule_version", "")).startswith("R79"):
        raise ResearchWorkbenchError("R79 JSON has an unsupported rule_version")
    end = payload.get("end")
    if end is None:
        raise ResearchWorkbenchError("R79 JSON missing end")
    return {
        "connected": True,
        "source_path": str(path),
        "rule_version": VALIDATED_BRIEF_STATE_TRANSITION_CONTEXT_VERSION,
        "end": str(end),
        "current_mapping": current_mapping,
        "overall_summary": [
            row for row in overall_summary if isinstance(row, dict)
        ],
        "closed_event_count": payload.get("closed_event_count"),
        "censored_event_count": payload.get("censored_event_count"),
        "human_review_required": payload.get("human_review_required", []),
        "historical_probabilities_are_posterior_evidence": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _load_option_volatility_context(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"R80/R81 option volatility JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    latest_curve = payload.get("latest_curve")
    boundary = payload.get("research_boundary")
    if not isinstance(latest_curve, dict):
        raise ResearchWorkbenchError("R80/R81 JSON missing latest_curve")
    if not isinstance(boundary, dict):
        raise ResearchWorkbenchError("R80/R81 JSON missing research_boundary")
    if boundary.get("latest_state_uses_future_data") is not False:
        raise ResearchWorkbenchError("R80/R81 latest state must not use future data")
    if boundary.get("enters_composite_score") is not False:
        raise ResearchWorkbenchError("R80/R81 must not enter composite_score")
    if boundary.get("trading_instruction") != "not_a_trading_instruction":
        raise ResearchWorkbenchError("R80/R81 must not contain trading instructions")
    if not str(latest_curve.get("rule_version", "")).startswith("R81"):
        raise ResearchWorkbenchError("R80/R81 JSON must use the R81 expiry registry")
    end = payload.get("end")
    if end is None:
        raise ResearchWorkbenchError("R80/R81 JSON missing end")
    return {
        "connected": True,
        "source_path": str(path),
        "rule_version": VALIDATED_BRIEF_OPTION_VOLATILITY_CONTEXT_VERSION,
        "end": str(end),
        "latest_curve": latest_curve,
        "expiry_registry_row_count": payload.get("expiry_registry_row_count"),
        "expiry_fallback_row_count": payload.get("expiry_fallback_row_count"),
        "warning_count": payload.get("warning_count"),
        "research_boundary": boundary,
        "human_review_required": payload.get("human_review_required", []),
        "trading_instruction": "not_a_trading_instruction",
    }


def _validate_context_asof(
    *, data_asof: date, label: str, context: dict[str, object] | None
) -> None:
    if context is None:
        return
    context_end = _parse_date(str(context.get("end")))
    if context_end != data_asof:
        raise ResearchWorkbenchError(
            f"{label} end {context_end.isoformat()} does not match latest data_asof "
            f"{data_asof.isoformat()}"
        )


def _r69_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _r69_directional_horizon_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    filtered = [
        row for row in rows if row.get("divergence_type") == "directional_divergence"
    ]
    return sorted(filtered, key=lambda row: int(row.get("horizon") or 0))[:12]


def _r69_ready_nodes(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    ready = [row for row in rows if row.get("evidence_level") == "READY"]
    return sorted(ready, key=lambda row: int(row.get("sample_count") or 0), reverse=True)[:12]


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _contains_forward_return_label(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if key_text == "forward_return" or key_text.startswith("forward_return_h"):
                return True
            if _contains_forward_return_label(nested):
                return True
    if isinstance(value, list):
        return any(_contains_forward_return_label(item) for item in value)
    return False


def _render_markdown(
    *,
    result: ResearchValidatedBriefResult,
    latest: dict[str, object],
    decay: pd.DataFrame,
    stability: pd.DataFrame,
    event_summary: pd.DataFrame,
    event_detail: pd.DataFrame | None,
    event_threshold_summary: pd.DataFrame | None,
    futures_option_divergence: dict[str, object] | None,
    futures_option_playbook: dict[str, object] | None,
    current_watch_window: dict[str, object] | None,
    state_transition: dict[str, object] | None,
    option_volatility: dict[str, object] | None,
    fundamental: dict[str, object] | None,
    research_framework_context: dict[str, object],
) -> str:
    trend = latest.get("trend_phase") if isinstance(latest.get("trend_phase"), dict) else {}
    matrix = (
        latest.get("signal_matrix_context")
        if isinstance(latest.get("signal_matrix_context"), dict)
        else {}
    )
    threshold = (
        latest.get("signal_threshold_context")
        if isinstance(latest.get("signal_threshold_context"), dict)
        else {}
    )
    matrix_rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    option_rows = [row for row in matrix_rows if isinstance(row, dict)]
    primary_option = _primary_option_row(
        rows=option_rows,
        primary_horizon=matrix.get("primary_horizon"),
    )
    lines = [
        f"# CF 验证型研究报告 - {result.data_asof.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        "- 报告类型：`validated_research_brief`",
        f"- 数据截至：`{result.data_asof.isoformat()}`",
        f"- Run ID：`{result.run_id}`",
        f"- 最新观察输入：`{result.latest_signal_json_path}`",
        f"- 历史证据输入：`{result.historical_evidence_decay_path}`",
        f"- 事件解释输入：`{result.event_summary_path}`",
        "- 事件明细输入："
        f"`{result.event_detail_path or '未接入 R55 事件基本面上下文'}`",
        "- 事件阈值敏感性输入："
        f"`{result.event_threshold_summary_path or '未接入 R60'}`",
        "- 基本面观察输入："
        f"`{result.fundamental_observation_json_path or '未接入 R53'}`",
        "- 状态转移竞争风险输入："
        f"`{result.state_transition_json_path or '未接入 R79'}`",
        "- 期权波动期限结构输入："
        f"`{result.option_volatility_json_path or '未接入 R80/R81'}`",
        "",
        "## 二、当前市场事实",
        "",
        f"- 主力合约：`{latest.get('main_contract')}`",
        f"- 最新信号方向：`{latest.get('signal_direction')}`",
        f"- 趋势阶段：`{trend.get('phase_code')}` {trend.get('phase_label')}",
        f"- 阶段原因：{trend.get('reason')}",
        "",
        *research_framework_markdown_lines(research_framework_context),
        "",
        "## 三、多周期信号矩阵",
        "",
        f"- 主观察周期：`{matrix.get('primary_horizon')}`",
        f"- 主方向：`{matrix.get('primary_direction')}`",
        f"- 主置信度：`{matrix.get('primary_confidence')}`",
        f"- 阈值周期对齐：`{threshold.get('horizon_alignment_status')}`",
        f"- 阈值解释：{threshold.get('explanation_cn')}",
        "",
        "## 四、期权风险定价证据",
        "",
        f"- 期权过滤：`{primary_option.get('option_signal', 'not_connected')}`",
        f"- 期权方向：`{primary_option.get('option_signal_direction', 'unknown')}`",
        f"- 期权因子状态：`{primary_option.get('option_factor_status', 'not_connected')}`",
        f"- PCR volume：`{_fmt_number(primary_option.get('option_pcr_volume'))}`",
        f"- PCR OI：`{_fmt_number(primary_option.get('option_pcr_oi'))}`",
        f"- skew proxy：`{_fmt_number(primary_option.get('option_skew_proxy'))}`",
        "- R49 期权信号只作为期货信号过滤器和风险提示，不进入 composite_score。",
        "",
        *_futures_option_divergence_section(futures_option_divergence),
        "",
        *_futures_option_playbook_section(futures_option_playbook),
        "",
        *_current_watch_window_section(current_watch_window),
        "",
        *_state_transition_section(state_transition),
        "",
        *_option_volatility_section(option_volatility),
        "",
        "## 五、历史窗口证据",
        "",
        "| Horizon | 样本 | normal cost 后均值 | 方向命中率 | 稳定性 |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]
    for row in decay.sort_values("horizon").to_dict(orient="records"):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["horizon"]),
                    str(row["observation_count"]),
                    _fmt_percent(row.get("mean_net_return_normal_cost")),
                    _fmt_percent(row.get("directional_hit_rate")),
                    str(row.get("stability_status")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 六、多因子回测摘要",
            "",
            "- 若 10D 或 40D 显示较好候选，只能说明历史证据更值得继续研究。",
            "- 所有阈值候选在样本外验证前统一按 `WATCH_ONLY_OOS_REQUIRED` 解释。",
            "- 若 1D/3D/5D/20D 为 WEAK_OR_UNSTABLE，不应被包装成稳定交易规则。",
            "",
            "## 七、成本后稳定性",
            "",
            "| Horizon | 方案 | 样本 | 平均后验收益 | 方向命中率 | 发布解释状态 | 稳定性 |",
            "| ---: | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    stable = stability.loc[stability["stability_status"].isin(["READY", "WATCH"])].head(10)
    for row in stable.to_dict(orient="records"):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["horizon"]),
                    str(row["scheme_label_cn"]),
                    str(row["observation_count"]),
                    _fmt_percent(row.get("mean_forward_return")),
                    _fmt_percent(row.get("directional_hit_rate")),
                    display_threshold_status(row["candidate_status"]),
                    str(row["stability_status"]),
                ]
            )
            + " |"
        )
    lines.extend(_fundamental_section(fundamental))
    lines.extend(
        [
            "",
            "## 九、相似历史事件",
            "",
            "| 事件类型 | Horizon | 事件数 | 样本 | 平均后验收益 | 方向命中率 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    selected_events = event_summary.loc[event_summary["horizon"].isin([5, 10, 20])]
    for row in selected_events.head(24).to_dict(orient="records"):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["event_type"]),
                    str(row["horizon"]),
                    str(row["event_count"]),
                    str(row["observation_count"]),
                    _fmt_percent(row.get("mean_forward_return")),
                    _fmt_percent(row.get("directional_hit_rate")),
                ]
            )
            + " |"
        )
    lines.extend(_event_fundamental_context_section(event_detail))
    lines.extend(_event_threshold_sensitivity_section(event_threshold_summary))
    lines.extend(
        [
            "",
            "## 十二、趋势起点/终点判断",
            "",
            "- 当前趋势判断必须同时参考最新 S0-S4 状态、R41 历史证据和 R42 历史事件。",
            "- R56 基本面事件解释只作为历史复盘上下文，不构成自动交易信号。",
            "- 起点、衰竭、终点事件均为研究复盘标签，不构成交易指令。",
            "",
            "## 十三、明日观察清单",
            "",
            "- 观察主力价格、持仓压力、期限结构是否与当前多周期信号继续一致。",
            "- 观察基本面中的现货、库存、基差是否继续与价格结构同向或背离。",
            "- 若最新信号与历史证据分歧，优先按人工复核处理。",
            "",
            "## 十四、研究边界",
            "",
            "- latest signal-only 部分不包含 forward-return 验证。",
            "- R41/R42 的 forward return 只作为历史后验验证标签。",
            "- R55/R56 基本面事件解释不生成 `fundamental_signal`，不进入 `composite_score`。",
            "- R60 KEEP/WATCH/REVISE/REJECT 只作为阈值复核候选，不是交易规则。",
            "- R49 期权联动来自研究 proxy，不构成期权定价或交易指令。",
            "- R79 状态转移概率是历史后验竞争风险证据，不是当前行情的未来标签。",
            "- R80/R81 期权 IV 使用 Black-76 欧式近似，未覆盖到期日必须人工复核。",
            "- R53 基本面观察不生成 `fundamental_signal`，不进入 `composite_score`。",
            "- 本报告不构成交易指令。",
        ]
    )
    return "\n".join(lines) + "\n"


def _futures_option_divergence_section(context: dict[str, object] | None) -> list[str]:
    lines = ["## 期货-期权矛盾节点（R70）", ""]
    if context is None:
        return lines + [
            "- 未接入 R69 期货-期权背离胜负研究；本报告仅展示当日期权过滤状态。",
            "- R69 接入后，该章节用于观察期货量价结构与期权结构背离后由哪一方被后验价格验证。",
        ]
    result = context.get("result") if isinstance(context.get("result"), dict) else {}
    directional_rows = context.get("directional_divergence_rows")
    ready_nodes = context.get("ready_nodes")
    directional = directional_rows if isinstance(directional_rows, list) else []
    ready = ready_nodes if isinstance(ready_nodes, list) else []
    lines.extend(
        [
            f"- R69 输入：`{context.get('source_path')}`",
            f"- R69 样本区间：`{result.get('start')}` 至 `{result.get('end')}`",
            f"- 背离/确认/非确认事件行数：`{result.get('event_row_count')}`",
            f"- 有后验标签事件行数：`{result.get('labelled_event_row_count')}`",
            f"- 明确方向背离行数：`{result.get('directional_divergence_count')}`",
            f"- 主要胜方标签：`{result.get('main_winner_label')}`",
            (
                "- 平均最早解决周期："
                f"`{_fmt_number(result.get('average_resolution_horizon'))}` 个交易日"
            ),
            "- R70 只引用 R69 的历史后验证据，不修改 `composite_score`，不自动反转方向。",
            "",
            "| 周期 | 样本数 | 期货胜率 | 期权胜率 | 平均期货方向收益 | 证据等级 |",
            "| ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    if directional:
        for row in directional:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"{row.get('horizon')}D",
                        str(row.get("sample_count")),
                        _fmt_percent(row.get("futures_win_rate")),
                        _fmt_percent(row.get("options_win_rate")),
                        _fmt_percent(row.get("avg_futures_directional_forward_return")),
                        str(row.get("evidence_level")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | 0 | - | - | - | 未发现明确方向背离 |")
    lines.extend(
        [
            "",
            "### R69 READY 结构节点",
            "",
            "| 趋势阶段 | 期权信号 | IV 桶 | PCR 桶 | 样本数 | 主导标签 |",
            "| --- | --- | --- | --- | ---: | --- |",
        ]
    )
    if ready:
        for row in ready[:8]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("trend_phase")),
                        str(row.get("option_signal")),
                        str(row.get("iv_rank_bucket")),
                        str(row.get("pcr_bucket")),
                        str(row.get("sample_count")),
                        str(row.get("dominant_winner_label")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | - | - | - | 0 | 暂无 READY 节点 |")
    lines.extend(
        [
            "",
            "- R69 中的 `forward_return` 仅为历史后验验证标签，不参与最新日信号生成。",
            "- 期权 PCR、ATM IV rank、skew 均为研究 proxy；本节不构成期权交易策略。",
        ]
    )
    return lines


def _futures_option_playbook_section(context: dict[str, object] | None) -> list[str]:
    lines = ["## 期货-期权当前结构映射（R72）", ""]
    if context is None:
        return lines + [
            "- 未接入 R71 期货-期权背离节点解释表；本报告暂不展示当前结构映射。",
            "- R71 接入后，该章节用于把最新期货-期权结构映射到历史矛盾节点。",
        ]
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    current_rows = context.get("current_mapping_rows")
    rows = current_rows if isinstance(current_rows, list) else []
    lines.extend(
        [
            f"- R71 输入：`{context.get('source_path')}`",
            f"- R71 证据区间：`{summary.get('start')}` 至 `{summary.get('end')}`",
            f"- 节点总数：`{summary.get('node_count')}`",
            f"- READY 节点数：`{summary.get('ready_node_count')}`",
            f"- 当前映射行数：`{summary.get('current_mapping_count')}`",
            "- R72 只做当前结构映射，不把最新日写入 R69 胜负统计。",
            "",
            "| 周期 | 当前结构 | 阶段 | 匹配节点 | 样本 | 解释标签 | "
            "期货胜率 | 期权胜率 | 平均解决 |",
            "| ---: | --- | --- | --- | ---: | --- | ---: | ---: | ---: |",
        ]
    )
    if rows:
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"{row.get('horizon')}D",
                        str(row.get("divergence_type")),
                        str(row.get("trend_phase")),
                        str(row.get("matched_node_id")),
                        str(row.get("matched_sample_count")),
                        str(row.get("matched_playbook_label_cn")),
                        _fmt_percent(row.get("matched_futures_win_rate")),
                        _fmt_percent(row.get("matched_options_win_rate")),
                        _fmt_number(row.get("matched_average_resolution_horizon")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | - | - | - | 0 | 未匹配 | - | - | - |")
    lines.extend(
        [
            "",
            "- R71/R72 中的当前映射只回答“当前像哪个历史节点”，不回答“未来必然怎么走”。",
            "- `forward_return` 仍只作为历史后验验证标签；最新日未形成后验收益前不能进入胜负统计。",
            "- 期权 PCR、ATM IV rank、skew 仍为研究 proxy，本节不构成期权策略或交易指令。",
        ]
    )
    return lines


def _current_watch_window_section(context: dict[str, object] | None) -> list[str]:
    lines = ["## 当前确认与失效窗口（R77）", ""]
    if context is None:
        return lines + [
            "- 未接入 R77 当前观察窗口；本报告暂不展示双价格、全链持仓和 v2 阶段。",
        ]
    watch = context.get("watch_window")
    row = watch if isinstance(watch, dict) else {}
    return lines + [
        f"- R77 输入：`{context.get('source_path')}`",
        f"- v2 阶段：`{row.get('phase_v2')}` {row.get('phase_v2_label')} / "
        f"`{row.get('phase_quality')}`",
        f"- 观察状态：`{row.get('watch_status')}`",
        f"- 双价格状态：`{row.get('dual_price_state')}` / "
        f"`{row.get('close_settle_gap_state')}`",
        f"- 全链持仓状态：`{row.get('participation_state')}`，变化 "
        f"`{_fmt_number(row.get('chain_oi_change_adjusted', row.get('chain_oi_change')))}`",
        f"- 多日移仓上下文：`{row.get('roll_context')}`，承接比例 "
        f"`{_fmt_number(row.get('roll_transfer_ratio_window'))}`",
        f"- 期权确认：`{row.get('option_confirmation_state')}` / "
        f"`{row.get('option_confirmation_strength')}`",
        f"- 确认参考位：`{_fmt_number(row.get('confirmation_level'))}`",
        f"- 均线失效参考位：`{_fmt_number(row.get('invalidation_level'))}`",
        f"- 历史平均解决周期：`{_fmt_number(row.get('expected_resolution_days'))}` 个交易日",
        f"- 确认条件：{row.get('confirmation_conditions_cn')}",
        f"- 失效条件：{row.get('invalidation_conditions_cn')}",
        "- R77 最新状态不读取未来收益，暂定复核日需用官方交易日历人工确认。",
        "- 本节不自动反转方向，不构成交易指令。",
    ]


def _state_transition_section(context: dict[str, object] | None) -> list[str]:
    lines = ["## 状态转移竞争风险（R82 接入 R79）", ""]
    if context is None:
        return lines + [
            "- 未接入 R79 状态转移竞争风险；当前阶段仍只作静态 S0-S4 描述。",
        ]
    current = context.get("current_mapping")
    current_row = current if isinstance(current, dict) else {}
    summary = context.get("overall_summary")
    rows = summary if isinstance(summary, list) else []
    lines.extend(
        [
            f"- R79 输入：`{context.get('source_path')}`",
            f"- 当前阶段：`{current_row.get('phase_code')}` / "
            f"`{current_row.get('phase_direction')}`",
            f"- 当前映射状态：`{current_row.get('mapping_status')}`",
            f"- 当前主要去向：`{current_row.get('primary_outcome')}`，后验概率 "
            f"`{_fmt_percent(current_row.get('primary_outcome_probability'))}`",
            f"- 当前阶段边界：{current_row.get('research_boundary')}",
            f"- 已关闭事件：`{context.get('closed_event_count')}`；右删失事件："
            f"`{context.get('censored_event_count')}`",
            "",
            "| 起始阶段 | 后续去向 | 样本 | 后验概率 | 平均解决天数 | 证据 |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        if not isinstance(row, dict) or row.get("outcome_count") == 0:
            continue
        lines.append(
            f"| {row.get('phase_code')} | {row.get('outcome_label_cn')} | "
            f"{row.get('outcome_count')} | "
            f"{_fmt_percent(row.get('outcome_probability_closed'))} | "
            f"{_fmt_number(row.get('avg_resolution_days'), decimals=2)} | "
            f"{row.get('evidence_level')} |"
        )
    lines.extend(
        [
            "",
            "- 上表是历史已关闭事件的竞争风险后验分布，不是当前行情的未来标签。",
            "- 当前不在 S1/S3 时不得强行映射概率；本节不改变当前方向信号。",
        ]
    )
    return lines


def _option_volatility_section(context: dict[str, object] | None) -> list[str]:
    lines = ["## 期权波动率与期限结构（R82 接入 R80/R81）", ""]
    if context is None:
        return lines + [
            "- 未接入 R80/R81 期权波动率研究；当前报告只保留 PCR、skew 等 proxy。",
        ]
    latest = context.get("latest_curve")
    row = latest if isinstance(latest, dict) else {}
    return lines + [
        f"- R80/R81 输入：`{context.get('source_path')}`",
        f"- 主力合约：`{row.get('main_contract')}`；期权到期日："
        f"`{row.get('main_option_expiry_date')}`",
        f"- 到期日来源：`{row.get('main_expiry_date_source')}`；质量："
        f"`{row.get('main_expiry_quality_flag')}`",
        f"- Black-76 ATM IV 近似：`{_fmt_percent(row.get('main_atm_iv_approx'))}`",
        f"- 20日实现波动率：`{_fmt_percent(row.get('main_rv'))}`",
        f"- IV-RV：`{_fmt_percent(row.get('main_iv_rv_spread'))}`；IV/RV："
        f"`{_fmt_number(row.get('main_iv_rv_ratio'), decimals=3)}`",
        f"- 波动状态：`{row.get('volatility_state')}`；期限结构："
        f"`{row.get('term_structure_state')}`",
        f"- 登记表覆盖行：`{context.get('expiry_registry_row_count')}`；"
        f"月初代理回退行：`{context.get('expiry_fallback_row_count')}`",
        "- 棉花期权为美式，本研究使用 Black-76 欧式近似；IV/Greek 不是精确风险暴露。",
        "- 本节不进入 `composite_score`，不自动生成期权交易策略或方向反转。",
    ]


def _fundamental_section(fundamental: dict[str, object] | None) -> list[str]:
    lines = ["", "## 八、基本面观察与人工复核状态", ""]
    if fundamental is None:
        return lines + [
            "- 未接入 R53 基本面观察 JSON；本报告仅展示价格、期权和历史验证证据。",
            "- 基本面不构成自动交易信号。",
        ]
    summary = fundamental.get("summary")
    latest = fundamental.get("latest_observations")
    summary_dict = summary if isinstance(summary, dict) else {}
    latest_dict = latest if isinstance(latest, dict) else {}
    lines.extend(
        [
            f"- R53 状态：`{summary_dict.get('status')}`",
            f"- R53 数据截至：`{summary_dict.get('data_asof')}`",
            f"- 基本面信号状态：`{summary_dict.get('fundamental_signal_status')}`",
            f"- 字段元数据表：`{summary_dict.get('field_metadata_csv_path')}`",
            "- iFinD 文件已提供指标名、单位、来源、频率、指标ID和更新时间。",
            "- 仓单数量按郑商所口径处理，当前已接入 iFinD/Wind 汇总后的数量序列。",
        ]
    )
    dataset_summaries = summary_dict.get("dataset_summaries")
    if isinstance(dataset_summaries, list):
        lines.extend(
            [
                "",
                "| 数据集 | 状态 | 行数 | 日期范围 |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for row in dataset_summaries:
            if not isinstance(row, dict):
                continue
            date_range = "-"
            if row.get("date_start") and row.get("date_end"):
                date_range = f"{row.get('date_start')} 至 {row.get('date_end')}"
            lines.append(
                f"| `{row.get('dataset_type')}` | `{row.get('status')}` | "
                f"{row.get('row_count')} | {date_range} |"
            )
    lines.extend(["", "### 最新基本面读数", ""])
    lines.extend(_latest_fundamental_lines(latest_dict))
    warnings = summary_dict.get("warnings")
    if isinstance(warnings, list):
        lines.extend(["", "### 缺失与复核", ""])
        for warning in warnings:
            if not isinstance(warning, dict) or warning.get("severity") == "INFO":
                continue
            lines.append(f"- `{warning.get('warning_code')}`：{warning.get('message')}")
    return lines


def _event_fundamental_context_section(event_detail: pd.DataFrame | None) -> list[str]:
    lines = ["", "## 十、基本面事件解释链", ""]
    if event_detail is None:
        return lines + [
            "- 未接入 R55 事件明细表，本报告暂不展示历史事件的基本面上下文。",
            "- 当前报告仍保留 R42 相似历史事件和 R53 最新基本面观察。",
        ]
    if event_detail.empty:
        return lines + [
            "- R55 事件明细表为空，无法形成基本面事件解释链。",
            "- 需要人工复核 R42 事件识别和 R54 基本面上下文输入。",
        ]
    context_available = event_detail["fundamental_context_available"].astype(bool)
    total_events = int(len(event_detail))
    available_events = int(context_available.sum())
    lines.extend(
        [
            f"- R55 事件明细数：`{total_events}`",
            f"- 已匹配事件日前基本面上下文：`{available_events}`",
            f"- R56 规则版本：`{VALIDATED_BRIEF_EVENT_CONTEXT_VERSION}`",
            "- 这些基本面解释只使用事件日及以前可见的 R54 上下文，不改变 R42 后验收益标签。",
            "",
            "| 事件类型 | 事件数 | 有上下文 | 同向项合计 | 背离项合计 | 示例解释 |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in _event_fundamental_context_rows(event_detail):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["event_type"]),
                    str(row["event_count"]),
                    str(row["available_count"]),
                    str(row["aligned_count"]),
                    str(row["divergent_count"]),
                    str(row["sample_summary"]),
                ]
            )
            + " |"
        )
    return lines


def _event_fundamental_context_rows(event_detail: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event_type, group in event_detail.groupby("event_type", sort=True):
        available = group["fundamental_context_available"].astype(bool)
        sample_summary = "-"
        if available.any():
            sample_summary = str(group.loc[available, "fundamental_context_summary_cn"].iloc[-1])
        rows.append(
            {
                "event_type": event_type,
                "event_count": int(len(group)),
                "available_count": int(available.sum()),
                "aligned_count": int(group["fundamental_aligned_count"].sum()),
                "divergent_count": int(group["fundamental_divergent_count"].sum()),
                "sample_summary": sample_summary,
            }
        )
    return rows


def _event_threshold_sensitivity_section(
    event_threshold_summary: pd.DataFrame | None,
) -> list[str]:
    lines = ["", "## 十一、事件阈值敏感性复核", ""]
    if event_threshold_summary is None:
        return lines + [
            "- 未接入 R60 事件阈值敏感性汇总；本报告暂不展示阈值候选分布。",
            "- 事件阈值仍需人工复核，不能从 R42/R55 事件结果直接固化。",
        ]
    if event_threshold_summary.empty:
        return lines + [
            "- R60 汇总表为空，无法形成阈值候选分布。",
            "- 需要人工复核事件识别、样本数量和阈值分位。",
        ]
    counts = _review_decision_counts(event_threshold_summary)
    lines.extend(
        [
            f"- R60 规则版本：`{VALIDATED_BRIEF_THRESHOLD_CONTEXT_VERSION}`",
            f"- 汇总行数：`{len(event_threshold_summary)}`",
            "- 复核候选计数："
            f"`KEEP={counts.get('KEEP', 0)}` / "
            f"`WATCH={counts.get('WATCH', 0)}` / "
            f"`REVISE={counts.get('REVISE', 0)}` / "
            f"`REJECT={counts.get('REJECT', 0)}`",
            "- R60 只作为历史阈值复核底稿；KEEP/WATCH/REVISE/REJECT 不是交易规则。",
            "- forward_return 只作为历史后验验证标签。",
            "",
            "| 阈值域 | 事件类型 | 分位 | 周期 | 样本 | 命中率 | 平均后验收益 | 复核候选 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in _event_threshold_preview_rows(event_threshold_summary):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("threshold_scope")),
                    str(row.get("event_type")),
                    _fmt_quantile(row.get("threshold_quantile")),
                    str(_int_or_dash(row.get("horizon"))),
                    str(_int_or_dash(row.get("observation_count"))),
                    _fmt_percent(row.get("directional_hit_rate")),
                    _fmt_percent(row.get("mean_forward_return")),
                    str(row.get("review_decision_candidate")),
                ]
            )
            + " |"
        )
    return lines


def _event_threshold_preview_rows(summary: pd.DataFrame) -> list[dict[str, object]]:
    if summary.empty:
        return []
    preferred = summary.copy()
    preferred["_decision_rank"] = preferred["review_decision_candidate"].astype(str).map(
        {"KEEP": 0, "WATCH": 1, "REVISE": 2, "REJECT": 3}
    )
    return (
        preferred.sort_values(
            [
                "_decision_rank",
                "threshold_scope",
                "event_type",
                "threshold_quantile",
                "horizon",
            ],
            na_position="first",
        )
        .drop(columns=["_decision_rank"], errors="ignore")
        .head(16)
        .to_dict(orient="records")
    )


def _latest_fundamental_lines(latest: dict[str, object]) -> list[str]:
    lines: list[str] = []
    basis_rows = latest.get("basis")
    if isinstance(basis_rows, list) and basis_rows and isinstance(basis_rows[0], dict):
        row = basis_rows[0]
        lines.append(
            "- 最新基差："
            f"{row.get('trade_date')}，现货 {row.get('spot_price')}，"
            f"活跃合约价格 {row.get('futures_settle')}，基差 {row.get('basis')}。"
        )
    warehouse_rows = latest.get("warehouse_receipt")
    if (
        isinstance(warehouse_rows, list)
        and warehouse_rows
        and isinstance(warehouse_rows[0], dict)
    ):
        row = warehouse_rows[0]
        lines.append(
            "- 最新仓单："
            f"{row.get('trade_date')}，{row.get('indicator_name')}="
            f"{row.get('warehouse_receipt')}{row.get('unit')}。"
        )
    inventory_rows = latest.get("inventory")
    if isinstance(inventory_rows, list) and inventory_rows:
        preview = []
        for row in inventory_rows[:5]:
            if isinstance(row, dict):
                preview.append(
                    f"{row.get('indicator_name')}={row.get('inventory_value')}{row.get('unit')}"
                )
        if preview:
            lines.append("- 最新库存：" + "；".join(preview) + "。")
    spot_rows = latest.get("spot_price")
    if isinstance(spot_rows, list) and spot_rows:
        preview = []
        for row in spot_rows[:5]:
            if isinstance(row, dict):
                preview.append(
                    f"{row.get('indicator_name')}={row.get('indicator_value')}{row.get('unit')}"
                )
        if preview:
            lines.append("- 最新现货：" + "；".join(preview) + "。")
    textile_rows = latest.get("textile_chain")
    if isinstance(textile_rows, list) and textile_rows:
        preview = []
        for row in textile_rows[:8]:
            if isinstance(row, dict):
                preview.append(
                    f"{row.get('indicator_name')}/{row.get('metric_name')}="
                    f"{row.get('indicator_value')}{row.get('unit')}"
                )
        if preview:
            lines.append("- 最新纺织链：" + "；".join(preview) + "。")
    return lines or ["- 暂无可展示的最新基本面读数。"]


def _primary_option_row(
    *,
    rows: list[dict[str, object]],
    primary_horizon: object,
) -> dict[str, object]:
    if not rows:
        return {}
    primary = _int_or_none(primary_horizon)
    if primary is not None:
        for row in rows:
            if _int_or_none(row.get("horizon")) == primary:
                return row
    return rows[0]


def _write_markdown(*, result: ResearchValidatedBriefResult, markdown: str) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text(markdown, encoding="utf-8")
    if result.daily_markdown_path is not None:
        result.daily_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.markdown_path, result.daily_markdown_path)


def _write_json(
    *,
    result: ResearchValidatedBriefResult,
    latest: dict[str, object],
    decay: pd.DataFrame,
    event_summary: pd.DataFrame,
    event_detail: pd.DataFrame | None,
    event_threshold_summary: pd.DataFrame | None,
    futures_option_divergence: dict[str, object] | None,
    futures_option_playbook: dict[str, object] | None,
    current_watch_window: dict[str, object] | None,
    state_transition: dict[str, object] | None,
    option_volatility: dict[str, object] | None,
    fundamental: dict[str, object] | None,
    research_framework_context: dict[str, object],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "validated_research_brief",
        "rule_version": VALIDATED_BRIEF_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "latest_signal_only_contains_forward_return_validation": False,
        "historical_forward_returns_are_validation_labels": True,
        "latest_context": latest,
        "fundamental_observation_context": fundamental,
        "research_framework_context": research_framework_context,
        "event_fundamental_context": _event_fundamental_context_payload(event_detail),
        "event_threshold_sensitivity_context": _event_threshold_context_payload(
            event_threshold_summary
        ),
        "futures_option_divergence_context": _futures_option_context_payload(
            futures_option_divergence
        ),
        "futures_option_playbook_context": _futures_option_playbook_context_payload(
            futures_option_playbook
        ),
        "current_watch_window_context": _current_watch_window_context_payload(
            current_watch_window
        ),
        "state_transition_context": _state_transition_context_payload(
            state_transition
        ),
        "option_volatility_context": _option_volatility_context_payload(
            option_volatility
        ),
        "decay_rows": decay.to_dict(orient="records"),
        "event_summary_rows": event_summary.to_dict(orient="records"),
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _event_fundamental_context_payload(
    event_detail: pd.DataFrame | None,
) -> dict[str, object]:
    if event_detail is None:
        return {
            "connected": False,
            "rule_version": VALIDATED_BRIEF_EVENT_CONTEXT_VERSION,
            "event_count": 0,
            "context_available_count": 0,
            "rows": [],
        }
    if event_detail.empty:
        return {
            "connected": True,
            "rule_version": VALIDATED_BRIEF_EVENT_CONTEXT_VERSION,
            "event_count": 0,
            "context_available_count": 0,
            "rows": [],
        }
    available = event_detail["fundamental_context_available"].astype(bool)
    preview_columns = [
        "event_date",
        "event_type",
        "fundamental_context_available",
        "fundamental_context_count",
        "fundamental_aligned_count",
        "fundamental_divergent_count",
        "fundamental_context_asof",
        "fundamental_context_summary_cn",
    ]
    columns = [column for column in preview_columns if column in event_detail.columns]
    return {
        "connected": True,
        "rule_version": VALIDATED_BRIEF_EVENT_CONTEXT_VERSION,
        "event_count": int(len(event_detail)),
        "context_available_count": int(available.sum()),
        "rows": _event_fundamental_context_rows(event_detail),
        "sample_events": event_detail[columns].head(20).to_dict(orient="records"),
    }


def _event_threshold_context_payload(
    event_threshold_summary: pd.DataFrame | None,
) -> dict[str, object]:
    if event_threshold_summary is None:
        return {
            "connected": False,
            "rule_version": VALIDATED_BRIEF_THRESHOLD_CONTEXT_VERSION,
            "row_count": 0,
            "review_decision_counts": {},
            "sample_rows": [],
            "forward_returns_are_validation_labels": True,
            "trading_instruction": "not_a_trading_instruction",
        }
    return {
        "connected": True,
        "rule_version": VALIDATED_BRIEF_THRESHOLD_CONTEXT_VERSION,
        "row_count": int(len(event_threshold_summary)),
        "review_decision_counts": _review_decision_counts(event_threshold_summary),
        "sample_rows": _event_threshold_preview_rows(event_threshold_summary),
        "forward_returns_are_validation_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _futures_option_context_payload(
    context: dict[str, object] | None,
) -> dict[str, object]:
    if context is None:
        return {
            "connected": False,
            "rule_version": VALIDATED_BRIEF_FUTURES_OPTION_CONTEXT_VERSION,
            "forward_returns_are_validation_labels": True,
            "trading_instruction": "not_a_trading_instruction",
        }
    return {
        "connected": True,
        "rule_version": VALIDATED_BRIEF_FUTURES_OPTION_CONTEXT_VERSION,
        "source_path": context.get("source_path"),
        "result": context.get("result"),
        "directional_divergence_rows": context.get("directional_divergence_rows", []),
        "ready_nodes": context.get("ready_nodes", []),
        "forward_returns_are_validation_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _futures_option_playbook_context_payload(
    context: dict[str, object] | None,
) -> dict[str, object]:
    if context is None:
        return {
            "connected": False,
            "rule_version": VALIDATED_BRIEF_FUTURES_OPTION_PLAYBOOK_CONTEXT_VERSION,
            "forward_returns_are_validation_labels": True,
            "trading_instruction": "not_a_trading_instruction",
        }
    return {
        "connected": True,
        "rule_version": VALIDATED_BRIEF_FUTURES_OPTION_PLAYBOOK_CONTEXT_VERSION,
        "source_path": context.get("source_path"),
        "summary": context.get("summary"),
        "current_mapping_rows": context.get("current_mapping_rows", []),
        "node_rows": context.get("node_rows", []),
        "forward_returns_are_validation_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _current_watch_window_context_payload(
    context: dict[str, object] | None,
) -> dict[str, object]:
    if context is None:
        return {
            "connected": False,
            "rule_version": VALIDATED_BRIEF_WATCH_WINDOW_CONTEXT_VERSION,
            "latest_state_uses_future_data": False,
            "trading_instruction": "not_a_trading_instruction",
        }
    return {
        "connected": True,
        "rule_version": VALIDATED_BRIEF_WATCH_WINDOW_CONTEXT_VERSION,
        "source_path": context.get("source_path"),
        "watch_window": context.get("watch_window"),
        "research_boundary": context.get("research_boundary"),
        "latest_state_uses_future_data": False,
        "trading_instruction": "not_a_trading_instruction",
    }


def _state_transition_context_payload(
    context: dict[str, object] | None,
) -> dict[str, object]:
    if context is None:
        return {
            "connected": False,
            "rule_version": VALIDATED_BRIEF_STATE_TRANSITION_CONTEXT_VERSION,
            "historical_probabilities_are_posterior_evidence": True,
            "trading_instruction": "not_a_trading_instruction",
        }
    return {
        **context,
        "connected": True,
        "rule_version": VALIDATED_BRIEF_STATE_TRANSITION_CONTEXT_VERSION,
        "historical_probabilities_are_posterior_evidence": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _option_volatility_context_payload(
    context: dict[str, object] | None,
) -> dict[str, object]:
    if context is None:
        return {
            "connected": False,
            "rule_version": VALIDATED_BRIEF_OPTION_VOLATILITY_CONTEXT_VERSION,
            "latest_state_uses_future_data": False,
            "enters_composite_score": False,
            "trading_instruction": "not_a_trading_instruction",
        }
    return {
        **context,
        "connected": True,
        "rule_version": VALIDATED_BRIEF_OPTION_VOLATILITY_CONTEXT_VERSION,
        "latest_state_uses_future_data": False,
        "enters_composite_score": False,
        "trading_instruction": "not_a_trading_instruction",
    }


def _write_manifest(*, result: ResearchValidatedBriefResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "report_type": "validated_research_brief",
        "rule_version": VALIDATED_BRIEF_VERSION,
        "data_asof": result.data_asof.isoformat(),
        "generated_at": utc_now().isoformat(),
        "latest_signal_only_contains_forward_return_validation": False,
        "historical_forward_returns_are_validation_labels": True,
        "latest_signal_json_path": str(result.latest_signal_json_path),
        "historical_evidence_decay_path": str(result.historical_evidence_decay_path),
        "historical_evidence_stability_path": str(result.historical_evidence_stability_path),
        "event_summary_path": str(result.event_summary_path),
        "event_detail_path": (
            None if result.event_detail_path is None else str(result.event_detail_path)
        ),
        "event_threshold_summary_path": (
            None
            if result.event_threshold_summary_path is None
            else str(result.event_threshold_summary_path)
        ),
        "futures_option_divergence_json_path": (
            None
            if result.futures_option_divergence_json_path is None
            else str(result.futures_option_divergence_json_path)
        ),
        "futures_option_playbook_json_path": (
            None
            if result.futures_option_playbook_json_path is None
            else str(result.futures_option_playbook_json_path)
        ),
        "current_watch_window_json_path": (
            None
            if result.current_watch_window_json_path is None
            else str(result.current_watch_window_json_path)
        ),
        "state_transition_json_path": (
            None
            if result.state_transition_json_path is None
            else str(result.state_transition_json_path)
        ),
        "option_volatility_json_path": (
            None
            if result.option_volatility_json_path is None
            else str(result.option_volatility_json_path)
        ),
        "fundamental_observation_json_path": (
            None
            if result.fundamental_observation_json_path is None
            else str(result.fundamental_observation_json_path)
        ),
        "markdown_path": str(result.markdown_path),
        "json_path": str(result.json_path),
        "daily_markdown_path": (
            None if result.daily_markdown_path is None else str(result.daily_markdown_path)
        ),
        "human_review_required": list(result.human_review_required),
        "validated_brief_event_context_rule_version": VALIDATED_BRIEF_EVENT_CONTEXT_VERSION,
        "validated_brief_threshold_context_rule_version": (
            VALIDATED_BRIEF_THRESHOLD_CONTEXT_VERSION
        ),
        "validated_brief_futures_option_context_rule_version": (
            VALIDATED_BRIEF_FUTURES_OPTION_CONTEXT_VERSION
        ),
        "validated_brief_futures_option_playbook_context_rule_version": (
            VALIDATED_BRIEF_FUTURES_OPTION_PLAYBOOK_CONTEXT_VERSION
        ),
        "validated_brief_watch_window_context_rule_version": (
            VALIDATED_BRIEF_WATCH_WINDOW_CONTEXT_VERSION
        ),
        "validated_brief_state_transition_context_rule_version": (
            VALIDATED_BRIEF_STATE_TRANSITION_CONTEXT_VERSION
        ),
        "validated_brief_option_volatility_context_rule_version": (
            VALIDATED_BRIEF_OPTION_VOLATILITY_CONTEXT_VERSION
        ),
        "research_framework_rule_version": RESEARCH_FRAMEWORK_VERSION,
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _markdown_path(*, data_asof: date, output_dir: Path | None) -> Path:
    root = output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{data_asof.isoformat()}_validated_research_brief.md"


def _json_path(*, data_asof: date, output_dir: Path | None) -> Path:
    root = output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{data_asof.isoformat()}_validated_research_brief.json"


def _manifest_path(*, data_asof: date, output_dir: Path | None) -> Path:
    root = output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{data_asof.isoformat()}_validated_research_brief_manifest.json"


def _default_latest_signal_json_path() -> Path:
    root = project_root() / "runs" / "daily" / PRODUCT_CODE
    candidates = sorted(root.glob("*/latest_signal_brief.json"))
    if not candidates:
        raise ResearchWorkbenchError(f"no latest signal JSON found under {root}")
    return candidates[-1]


def _default_historical_decay_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "historical_evidence"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_historical_evidence_decay.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R41 decay parquet found under {root}")
    return candidates[-1]


def _default_historical_stability_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "historical_evidence"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_historical_evidence_stability.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R41 stability parquet found under {root}")
    return candidates[-1]


def _default_event_summary_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "event_explanation"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_event_explanation_summary.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R42 event summary parquet found under {root}")
    return candidates[-1]


def _default_run_id(*, data_asof: date) -> str:
    return f"r43_validated_brief_{PRODUCT_CODE}_{data_asof.isoformat()}_{uuid.uuid4().hex[:8]}"


def _parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _fmt_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _fmt_quantile(value: object) -> str:
    if value is None or pd.isna(value):
        return "baseline"
    return f"{float(value):.3f}"


def _fmt_number(value: object, *, decimals: int = 6) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{decimals}f}"


def _int_or_dash(value: object) -> int | str:
    if value is None or pd.isna(value):
        return "-"
    return int(float(value))


def _int_or_none(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(float(value))


def _review_decision_counts(summary: pd.DataFrame) -> dict[str, int]:
    counts = {"KEEP": 0, "WATCH": 0, "REVISE": 0, "REJECT": 0}
    if summary.empty or "review_decision_candidate" not in summary.columns:
        return counts
    observed = summary["review_decision_candidate"].astype(str).value_counts().to_dict()
    for decision in counts:
        counts[decision] = int(observed.get(decision, 0))
    return counts
