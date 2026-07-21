"""R79 CF state-transition competing-risk research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    fmt_percent,
    latest_matching_path,
    load_table,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
RULE_VERSION = "R79_state_transition_competing_risk_v1"
DEFAULT_MAX_AGE_DAYS = 20
DEFAULT_MIN_SAMPLE_SIZE = 30
TARGET_PHASES = ("S1", "S3")
RESEARCH_BOUNDARY = {
    "forward_returns_are_validation_labels": True,
    "latest_signal_uses_future_data": False,
    "probabilities_are_historical_posterior_evidence": True,
    "modifies_composite_score": False,
    "automatic_direction_reversal": False,
    "trading_instruction": "not_a_trading_instruction",
}
HUMAN_REVIEW_REQUIRED = (
    "phase_transition_definition",
    "episode_censoring_interpretation",
    "competing_risk_duration_interpretation",
    "minimum_sample_size",
    "current_episode_mapping",
)
OUTCOME_LABELS_CN = {
    "SUCCESS_TO_S2": "进入S2趋势中",
    "FAILURE_TO_S0": "退回S0未确认",
    "EXHAUSTION_TO_S3": "转入S3衰竭观察",
    "DIRECT_END_TO_S4": "直接进入S4终点确认",
    "END_TO_S4": "进入S4终点确认",
    "RECOVERY_TO_S2": "恢复到S2趋势中",
    "REPAIR_TO_S1": "修复到S1起点观察",
    "NEUTRALIZE_TO_S0": "回到S0未确认",
    "OTHER_TRANSITION": "其他状态转移",
    "CENSORED": "右删失/尚未解决",
}
PHASE_OUTCOMES = {
    "S1": (
        "SUCCESS_TO_S2",
        "FAILURE_TO_S0",
        "EXHAUSTION_TO_S3",
        "DIRECT_END_TO_S4",
        "OTHER_TRANSITION",
    ),
    "S3": (
        "END_TO_S4",
        "RECOVERY_TO_S2",
        "REPAIR_TO_S1",
        "NEUTRALIZE_TO_S0",
        "OTHER_TRANSITION",
    ),
}


@dataclass(frozen=True)
class ResearchStateTransitionCompetingRiskResult:
    """R79 output contract."""

    run_id: str
    start: date
    end: date
    event_count: int
    closed_event_count: int
    censored_event_count: int
    current_phase: str | None
    current_age_days: int | None
    current_primary_outcome: str | None
    current_primary_probability: float | None
    warning_count: int
    event_parquet_path: Path
    summary_parquet_path: Path
    age_risk_parquet_path: Path
    node_parquet_path: Path
    current_parquet_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI payload."""
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "event_count": self.event_count,
            "closed_event_count": self.closed_event_count,
            "censored_event_count": self.censored_event_count,
            "current_phase": self.current_phase,
            "current_age_days": self.current_age_days,
            "current_primary_outcome": self.current_primary_outcome,
            "current_primary_probability": self.current_primary_probability,
            "warning_count": self.warning_count,
            "event_parquet_path": str(self.event_parquet_path),
            "summary_parquet_path": str(self.summary_parquet_path),
            "age_risk_parquet_path": str(self.age_risk_parquet_path),
            "node_parquet_path": str(self.node_parquet_path),
            "current_parquet_path": str(self.current_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_state_transition_competing_risk_research(
    *,
    event_lifecycle_episode_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> ResearchStateTransitionCompetingRiskResult:
    """Build R79 competing-risk and duration-conditioned transition evidence."""
    if max_age_days <= 0:
        raise ResearchWorkbenchError("max_age_days must be positive")
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("min_sample_size must be positive")
    episode_path = event_lifecycle_episode_path or latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "event_lifecycle",
        "*_event_lifecycle_episodes.parquet",
        label="R68 event lifecycle episode table",
    )
    episodes = load_table(
        episode_path,
        required={
            "episode_id",
            "phase_code",
            "phase_direction",
            "model_direction",
            "confidence",
            "start_date",
            "end_date",
            "duration_trading_days",
            "next_phase",
            "transition_code",
            "mfe",
            "mae",
        },
        label="R68 event lifecycle episode table",
    )
    latest_episode_context = _latest_episode_context(episodes)
    events = _prepare_events(episodes)
    if events.empty:
        raise ResearchWorkbenchError("R79 has no S1/S3 lifecycle episodes")
    start = min(events["start_date"])
    end = latest_episode_context["end_date"]
    active_run_id = run_id or utc_timestamp_id("r79", end)
    if "run_id" in events.columns:
        events["source_run_id"] = events["run_id"]
        events["run_id"] = active_run_id
        ordered_columns = ["run_id", "source_run_id"] + [
            column
            for column in events.columns
            if column not in {"run_id", "source_run_id"}
        ]
        events = events[ordered_columns]
    else:
        events.insert(0, "run_id", active_run_id)
    summary = _overall_summary(
        events=events,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
    )
    age_risk = _age_risk_rows(
        events=events,
        run_id=active_run_id,
        max_age_days=max_age_days,
    )
    nodes = _node_summary(
        events=events,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
    )
    current = _current_mapping(
        events=events,
        summary=summary,
        age_risk=age_risk,
        nodes=nodes,
        run_id=active_run_id,
        max_age_days=max_age_days,
        latest_episode_context=latest_episode_context,
    )
    warnings = _warning_rows(
        events=events,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
        current=current,
    )
    paths = _output_paths(
        start=start,
        end=end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(events, paths["event_parquet"], paths["event_csv"])
    write_frame(summary, paths["summary_parquet"], paths["summary_csv"])
    write_frame(age_risk, paths["age_risk_parquet"], paths["age_risk_csv"])
    write_frame(nodes, paths["node_parquet"], paths["node_csv"])
    write_frame(current, paths["current_parquet"], paths["current_csv"])
    write_warning_csv(paths["warning_csv"], warnings)
    _write_markdown(
        path=paths["markdown"],
        start=start,
        end=end,
        summary=summary,
        age_risk=age_risk,
        nodes=nodes,
        current=current,
        min_sample_size=min_sample_size,
    )
    current_row = current.iloc[0].to_dict() if not current.empty else {}
    warning_count = sum(1 for row in warnings if row["severity"] == "WARN")
    result = ResearchStateTransitionCompetingRiskResult(
        run_id=active_run_id,
        start=start,
        end=end,
        event_count=len(events),
        closed_event_count=int(events["is_closed"].sum()),
        censored_event_count=int(events["is_censored"].sum()),
        current_phase=_str_or_none(current_row.get("phase_code")),
        current_age_days=_int_or_none(current_row.get("current_age_days")),
        current_primary_outcome=_str_or_none(current_row.get("primary_outcome")),
        current_primary_probability=_float_or_none(
            current_row.get("primary_outcome_probability")
        ),
        warning_count=warning_count,
        event_parquet_path=paths["event_parquet"],
        summary_parquet_path=paths["summary_parquet"],
        age_risk_parquet_path=paths["age_risk_parquet"],
        node_parquet_path=paths["node_parquet"],
        current_parquet_path=paths["current_parquet"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
    )
    write_json(
        paths["json"],
        {
            **result.to_summary(),
            "current_mapping": current_row or None,
            "overall_summary": summary.to_dict("records"),
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        paths["manifest"],
        artifact_manifest(
            run_id=active_run_id,
            report_type="state_transition_competing_risk",
            rule_version=RULE_VERSION,
            data_asof=end,
            input_paths={"event_lifecycle_episode_path": episode_path},
            output_paths={
                "event_parquet_path": paths["event_parquet"],
                "summary_parquet_path": paths["summary_parquet"],
                "age_risk_parquet_path": paths["age_risk_parquet"],
                "node_parquet_path": paths["node_parquet"],
                "current_parquet_path": paths["current_parquet"],
                "warning_csv_path": paths["warning_csv"],
                "markdown_path": paths["markdown"],
                "json_path": paths["json"],
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _prepare_events(episodes: pd.DataFrame) -> pd.DataFrame:
    working = episodes.copy()
    for column in ("start_date", "end_date"):
        working[column] = pd.to_datetime(working[column], errors="coerce").dt.date
    working["duration_trading_days"] = pd.to_numeric(
        working["duration_trading_days"], errors="coerce"
    )
    working = working.dropna(subset=["start_date", "end_date", "duration_trading_days"])
    working = working.loc[working["phase_code"].astype(str).isin(TARGET_PHASES)].copy()
    working["duration_trading_days"] = working["duration_trading_days"].astype(int)
    working["next_phase"] = working["next_phase"].where(working["next_phase"].notna(), None)
    working["is_closed"] = working["next_phase"].notna()
    working["is_censored"] = ~working["is_closed"]
    working["outcome_code"] = [
        _outcome_code(str(row.phase_code), None if row.next_phase is None else str(row.next_phase))
        for row in working.itertuples(index=False)
    ]
    working["outcome_label_cn"] = working["outcome_code"].map(OUTCOME_LABELS_CN)
    working["resolution_days"] = working["duration_trading_days"].where(
        working["is_closed"], pd.NA
    )
    working["confidence"] = working["confidence"].fillna("unknown").astype(str)
    working["phase_direction"] = working["phase_direction"].fillna("neutral").astype(str)
    return working.sort_values(["start_date", "episode_id"]).reset_index(drop=True)


def _latest_episode_context(episodes: pd.DataFrame) -> dict[str, object]:
    working = episodes.copy()
    for column in ("start_date", "end_date"):
        working[column] = pd.to_datetime(working[column], errors="coerce").dt.date
    working["duration_trading_days"] = pd.to_numeric(
        working["duration_trading_days"], errors="coerce"
    )
    working = working.dropna(subset=["start_date", "end_date", "duration_trading_days"])
    if working.empty:
        raise ResearchWorkbenchError("R68 episode table has no valid dated rows")
    latest = working.sort_values(["end_date", "start_date", "episode_id"]).iloc[-1]
    return latest.to_dict()


def _outcome_code(phase_code: str, next_phase: str | None) -> str:
    if next_phase is None or next_phase in {"", "nan", "None"}:
        return "CENSORED"
    mapping = {
        ("S1", "S2"): "SUCCESS_TO_S2",
        ("S1", "S0"): "FAILURE_TO_S0",
        ("S1", "S3"): "EXHAUSTION_TO_S3",
        ("S1", "S4"): "DIRECT_END_TO_S4",
        ("S3", "S4"): "END_TO_S4",
        ("S3", "S2"): "RECOVERY_TO_S2",
        ("S3", "S1"): "REPAIR_TO_S1",
        ("S3", "S0"): "NEUTRALIZE_TO_S0",
    }
    return mapping.get((phase_code, next_phase), "OTHER_TRANSITION")


def _overall_summary(
    *, events: pd.DataFrame, run_id: str, min_sample_size: int
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for phase_code in TARGET_PHASES:
        phase_rows = events.loc[events["phase_code"] == phase_code]
        closed = phase_rows.loc[phase_rows["is_closed"]]
        for outcome_code in PHASE_OUTCOMES[phase_code]:
            outcome = closed.loc[closed["outcome_code"] == outcome_code]
            rows.append(
                {
                    "run_id": run_id,
                    "product_code": PRODUCT_CODE,
                    "phase_code": phase_code,
                    "outcome_code": outcome_code,
                    "outcome_label_cn": OUTCOME_LABELS_CN[outcome_code],
                    "all_episode_count": len(phase_rows),
                    "closed_episode_count": len(closed),
                    "censored_episode_count": int(phase_rows["is_censored"].sum()),
                    "outcome_count": len(outcome),
                    "outcome_probability_closed": _safe_ratio(len(outcome), len(closed)),
                    "outcome_share_all": _safe_ratio(len(outcome), len(phase_rows)),
                    "avg_resolution_days": _mean(outcome["duration_trading_days"]),
                    "median_resolution_days": _median(outcome["duration_trading_days"]),
                    "avg_mfe": _mean(outcome["mfe"]),
                    "avg_mae": _mean(outcome["mae"]),
                    "evidence_level": _evidence_level(len(outcome), min_sample_size),
                    "rule_version": RULE_VERSION,
                }
            )
    return pd.DataFrame(rows)


def _age_risk_rows(
    *, events: pd.DataFrame, run_id: str, max_age_days: int
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for phase_code in TARGET_PHASES:
        phase_rows = events.loc[events["phase_code"] == phase_code]
        survival_probability = 1.0
        cumulative_incidence = {outcome: 0.0 for outcome in PHASE_OUTCOMES[phase_code]}
        for age_day in range(1, max_age_days + 1):
            at_risk = phase_rows.loc[phase_rows["duration_trading_days"] >= age_day]
            closed_at_age = at_risk.loc[
                at_risk["is_closed"] & (at_risk["duration_trading_days"] == age_day)
            ]
            future_closed = phase_rows.loc[
                phase_rows["is_closed"] & (phase_rows["duration_trading_days"] >= age_day)
            ]
            survival_before = survival_probability
            total_hazard = _safe_ratio(len(closed_at_age), len(at_risk)) or 0.0
            for outcome_code in PHASE_OUTCOMES[phase_code]:
                event_count = int((closed_at_age["outcome_code"] == outcome_code).sum())
                hazard = _safe_ratio(event_count, len(at_risk)) or 0.0
                cumulative_incidence[outcome_code] += survival_before * hazard
                future_count = int((future_closed["outcome_code"] == outcome_code).sum())
                rows.append(
                    {
                        "run_id": run_id,
                        "product_code": PRODUCT_CODE,
                        "phase_code": phase_code,
                        "age_day": age_day,
                        "outcome_code": outcome_code,
                        "outcome_label_cn": OUTCOME_LABELS_CN[outcome_code],
                        "at_risk_count": len(at_risk),
                        "event_count_at_age": event_count,
                        "cause_specific_hazard": hazard,
                        "cumulative_incidence": cumulative_incidence[outcome_code],
                        "survival_probability_after_age": survival_before
                        * (1.0 - total_hazard),
                        "future_closed_count_from_age": len(future_closed),
                        "future_outcome_count_from_age": future_count,
                        "conditional_outcome_probability_from_age": _safe_ratio(
                            future_count, len(future_closed)
                        ),
                        "rule_version": RULE_VERSION,
                    }
                )
            survival_probability = survival_before * (1.0 - total_hazard)
    return pd.DataFrame(rows)


def _node_summary(
    *, events: pd.DataFrame, run_id: str, min_sample_size: int
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_columns = ["phase_code", "confidence", "phase_direction"]
    for keys, group in events.groupby(group_columns, dropna=False, sort=True):
        phase_code, confidence, phase_direction = keys
        closed = group.loc[group["is_closed"]]
        row: dict[str, object] = {
            "run_id": run_id,
            "product_code": PRODUCT_CODE,
            "phase_code": phase_code,
            "confidence": confidence,
            "phase_direction": phase_direction,
            "all_episode_count": len(group),
            "closed_episode_count": len(closed),
            "censored_episode_count": int(group["is_censored"].sum()),
            "avg_resolution_days": _mean(closed["duration_trading_days"]),
            "median_resolution_days": _median(closed["duration_trading_days"]),
            "evidence_level": _evidence_level(len(closed), min_sample_size),
            "rule_version": RULE_VERSION,
        }
        for outcome_code in PHASE_OUTCOMES[str(phase_code)]:
            count = int((closed["outcome_code"] == outcome_code).sum())
            row[f"{outcome_code.lower()}_count"] = count
            row[f"{outcome_code.lower()}_probability"] = _safe_ratio(count, len(closed))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["closed_episode_count", "phase_code"], ascending=[False, True]
    )


def _current_mapping(
    *,
    events: pd.DataFrame,
    summary: pd.DataFrame,
    age_risk: pd.DataFrame,
    nodes: pd.DataFrame,
    run_id: str,
    max_age_days: int,
    latest_episode_context: dict[str, object],
) -> pd.DataFrame:
    open_events = events.loc[events["is_censored"]]
    if open_events.empty:
        return pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "product_code": PRODUCT_CODE,
                    "mapping_status": "CURRENT_PHASE_OUTSIDE_TARGET",
                    "episode_id": latest_episode_context.get("episode_id"),
                    "phase_code": latest_episode_context.get("phase_code"),
                    "phase_direction": latest_episode_context.get("phase_direction"),
                    "confidence": latest_episode_context.get("confidence"),
                    "start_date": latest_episode_context.get("start_date"),
                    "data_asof": latest_episode_context.get("end_date"),
                    "current_age_days": latest_episode_context.get(
                        "duration_trading_days"
                    ),
                    "node_closed_sample_count": None,
                    "node_evidence_level": None,
                    "primary_outcome": None,
                    "primary_outcome_label_cn": None,
                    "primary_outcome_probability": None,
                    "age_conditioned_primary_outcome": None,
                    "age_conditioned_primary_probability": None,
                    "survival_probability_after_current_age": None,
                    "research_boundary": "当前不在S1/S3，暂不映射竞争风险概率",
                    "rule_version": RULE_VERSION,
                }
            ]
        )
    current = open_events.sort_values(["end_date", "start_date"]).iloc[-1]
    phase_code = str(current["phase_code"])
    age_day = min(int(current["duration_trading_days"]), max_age_days)
    node = nodes.loc[
        (nodes["phase_code"] == phase_code)
        & (nodes["confidence"] == current["confidence"])
        & (nodes["phase_direction"] == current["phase_direction"])
    ]
    phase_summary = summary.loc[summary["phase_code"] == phase_code].sort_values(
        "outcome_probability_closed", ascending=False
    )
    primary = phase_summary.iloc[0] if not phase_summary.empty else None
    age_rows = age_risk.loc[
        (age_risk["phase_code"] == phase_code) & (age_risk["age_day"] == age_day)
    ].sort_values("conditional_outcome_probability_from_age", ascending=False)
    age_primary = age_rows.iloc[0] if not age_rows.empty else None
    return pd.DataFrame(
        [
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "mapping_status": "MATCHED_OPEN_EPISODE",
                "episode_id": current["episode_id"],
                "phase_code": phase_code,
                "phase_direction": current["phase_direction"],
                "confidence": current["confidence"],
                "start_date": current["start_date"],
                "data_asof": current["end_date"],
                "current_age_days": int(current["duration_trading_days"]),
                "node_closed_sample_count": (
                    None if node.empty else int(node.iloc[0]["closed_episode_count"])
                ),
                "node_evidence_level": None if node.empty else node.iloc[0]["evidence_level"],
                "primary_outcome": None if primary is None else primary["outcome_code"],
                "primary_outcome_label_cn": (
                    None if primary is None else primary["outcome_label_cn"]
                ),
                "primary_outcome_probability": (
                    None if primary is None else primary["outcome_probability_closed"]
                ),
                "age_conditioned_primary_outcome": (
                    None if age_primary is None else age_primary["outcome_code"]
                ),
                "age_conditioned_primary_probability": (
                    None
                    if age_primary is None
                    else age_primary["conditional_outcome_probability_from_age"]
                ),
                "survival_probability_after_current_age": (
                    None
                    if age_primary is None
                    else age_primary["survival_probability_after_age"]
                ),
                "research_boundary": "历史后验概率，不是最新交易指令",
                "rule_version": RULE_VERSION,
            }
        ]
    )


def _warning_rows(
    *,
    events: pd.DataFrame,
    run_id: str,
    min_sample_size: int,
    current: pd.DataFrame,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    for phase_code in TARGET_PHASES:
        closed_count = int(
            ((events["phase_code"] == phase_code) & events["is_closed"]).sum()
        )
        if closed_count < min_sample_size:
            warnings.append(
                _warning(
                    run_id,
                    "sample_size",
                    "WARN",
                    f"{phase_code}_CLOSED_SAMPLE_SMALL",
                    f"{phase_code} 已解决episode仅{closed_count}条，条件概率只能作为弱证据。",
                    closed_count,
                    "minimum_sample_size",
                )
            )
    censored_count = int(events["is_censored"].sum())
    if censored_count:
        warnings.append(
            _warning(
                run_id,
                "censoring",
                "INFO",
                "OPEN_EPISODES_RIGHT_CENSORED",
                "开放episode按右删失处理，不计入已解决转移概率分母。",
                censored_count,
                "episode_censoring_interpretation",
            )
        )
    if current.empty:
        warnings.append(
            _warning(
                run_id,
                "current_mapping",
                "INFO",
                "NO_OPEN_EPISODE",
                "当前没有开放的S1/S3 episode，未生成当前概率映射。",
                0,
                "current_episode_mapping",
            )
        )
    elif current.iloc[0]["mapping_status"] == "CURRENT_PHASE_OUTSIDE_TARGET":
        warnings.append(
            _warning(
                run_id,
                "current_mapping",
                "INFO",
                "CURRENT_PHASE_OUTSIDE_S1_S3",
                "当前阶段不属于S1/S3，不生成当前竞争风险概率。",
                1,
                "current_episode_mapping",
            )
        )
    return warnings


def _warning(
    run_id: str,
    section: str,
    severity: str,
    code: str,
    message: str,
    affected_count: int,
    human_review: str,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "section": section,
        "severity": severity,
        "warning_code": code,
        "warning_message": message,
        "affected_count": affected_count,
        "human_review_required": human_review,
    }


def _write_markdown(
    *,
    path: Path,
    start: date,
    end: date,
    summary: pd.DataFrame,
    age_risk: pd.DataFrame,
    nodes: pd.DataFrame,
    current: pd.DataFrame,
    min_sample_size: int,
) -> None:
    lines = [
        f"# CF 状态转移与竞争风险研究 R79 - {end.isoformat()}",
        "",
        "## 数据状态",
        "",
        f"- 研究区间：`{start.isoformat()}` 至 `{end.isoformat()}`",
        "- 研究对象：R68 的 S1、S3 episode。",
        "- 开放episode按右删失处理，不进入已解决转移概率分母。",
        f"- 证据样本阈值：`{min_sample_size}`。",
        "",
        "## 研究定义",
        "",
        "- S1竞争结果：进入S2、退回S0、转入S3、直接进入S4。",
        "- S3竞争结果：进入S4、恢复S2、修复S1、回到S0。",
        "- `outcome_probability_closed`以已解决episode为分母。",
        "- `outcome_share_all`以全部episode为分母，因此包含右删失影响。",
        "",
        "## 总体竞争风险",
        "",
        (
            "| 起始阶段 | 结果 | 全部样本 | 已解决 | 结果数 | 已解决条件概率 | "
            "全样本占比 | 中位解决日 | 证据 |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary.itertuples(index=False):
        if int(row.outcome_count) == 0:
            continue
        lines.append(
            f"| {row.phase_code} | {row.outcome_label_cn} | {row.all_episode_count} | "
            f"{row.closed_episode_count} | {row.outcome_count} | "
            f"{fmt_percent(row.outcome_probability_closed)} | "
            f"{fmt_percent(row.outcome_share_all)} | "
            f"{fmt_number(row.median_resolution_days, 1)} | {row.evidence_level} |"
        )
    lines.extend(
        [
            "",
            "## 持续时间条件概率",
            "",
            "下表回答：episode已经持续到指定天数后，在后续已解决样本中各结果的比例。",
            "",
            "| 阶段 | 已持续 | 风险集 | 结果 | 后续条件概率 | 累计发生率 | 存活概率 |",
            "| --- | ---: | ---: | --- | ---: | ---: | ---: |",
        ]
    )
    selected_ages = {1, 3, 5, 10, 20}
    age_view = age_risk.loc[age_risk["age_day"].isin(selected_ages)].copy()
    age_view = age_view.loc[age_view["future_outcome_count_from_age"] > 0]
    for row in age_view.itertuples(index=False):
        lines.append(
            f"| {row.phase_code} | {row.age_day}D | {row.at_risk_count} | "
            f"{row.outcome_label_cn} | "
            f"{fmt_percent(row.conditional_outcome_probability_from_age)} | "
            f"{fmt_percent(row.cumulative_incidence)} | "
            f"{fmt_percent(row.survival_probability_after_age)} |"
        )
    lines.extend(
        [
            "",
            "## 条件节点",
            "",
            "| 阶段 | 置信度 | 方向 | 已解决样本 | 中位解决日 | 证据 |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in nodes.head(12).itertuples(index=False):
        lines.append(
            f"| {row.phase_code} | {row.confidence} | {row.phase_direction} | "
            f"{row.closed_episode_count} | {fmt_number(row.median_resolution_days, 1)} | "
            f"{row.evidence_level} |"
        )
    lines.extend(["", "## 当前开放episode映射", ""])
    if current.empty:
        lines.append("- 当前没有开放的S1/S3 episode。")
    elif current.iloc[0]["mapping_status"] == "CURRENT_PHASE_OUTSIDE_TARGET":
        row = current.iloc[0]
        lines.extend(
            [
                f"- 当前阶段：`{row['phase_code']}` / `{row['phase_direction']}` / "
                f"`{row['confidence']}`",
                f"- 数据截至：`{row['data_asof']}`",
                "- 当前不属于S1/S3竞争风险目标阶段，不生成当前概率映射。",
            ]
        )
    else:
        row = current.iloc[0]
        lines.extend(
            [
                f"- 当前阶段：`{row['phase_code']}` / `{row['phase_direction']}` / "
                f"`{row['confidence']}`",
                f"- 已持续：`{row['current_age_days']}` 个交易日",
                f"- 同节点已解决样本：`{row['node_closed_sample_count']}`，证据："
                f"`{row['node_evidence_level']}`",
                f"- 总体主要历史结果：`{row['primary_outcome_label_cn']}`，概率 "
                f"`{fmt_percent(row['primary_outcome_probability'])}`",
                "- 持续时间条件下主要结果："
                f"`{OUTCOME_LABELS_CN.get(str(row['age_conditioned_primary_outcome']), '-')}`，"
                "概率 "
                f"`{fmt_percent(row['age_conditioned_primary_probability'])}`",
            ]
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 本模块输出历史后验条件概率，不把概率直接写入最新方向信号。",
            "- 不自动反转方向，不修改 `composite_score`，不构成交易指令。",
            "- 小样本节点保留但降级，不因高命中率自动升级为可交易规则。",
            "- 当前开放episode没有未来结果，只用于映射历史分布。",
            "- HUMAN_REVIEW_REQUIRED：状态定义、删失、持续时间和当前节点解释。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _output_paths(
    *, start: date, end: date, output_dir: Path | None, report_output_dir: Path | None
) -> dict[str, Path]:
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "state_transition"
    report_root = report_output_dir or reports_dir() / "research" / "state_transition"
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_state_transition_competing_risk"
    return {
        "event_parquet": data_root / f"{stem}_events.parquet",
        "event_csv": data_root / f"{stem}_events.csv",
        "summary_parquet": data_root / f"{stem}_summary.parquet",
        "summary_csv": data_root / f"{stem}_summary.csv",
        "age_risk_parquet": data_root / f"{stem}_age_risk.parquet",
        "age_risk_csv": data_root / f"{stem}_age_risk.csv",
        "node_parquet": data_root / f"{stem}_nodes.parquet",
        "node_csv": data_root / f"{stem}_nodes.csv",
        "current_parquet": data_root / f"{stem}_current.parquet",
        "current_csv": data_root / f"{stem}_current.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _evidence_level(sample_count: int, min_sample_size: int) -> str:
    if sample_count >= min_sample_size:
        return "READY"
    if sample_count >= max(10, min_sample_size // 2):
        return "WATCH"
    return "WEAK_OR_SMALL_SAMPLE"


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.mean())


def _median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.median())


def _str_or_none(value: object) -> str | None:
    return None if value is None or pd.isna(value) else str(value)


def _int_or_none(value: object) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def _float_or_none(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)
