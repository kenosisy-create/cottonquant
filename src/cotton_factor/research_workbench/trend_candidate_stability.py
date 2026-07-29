"""R93C CF 趋势候选消融、稳定性与前向预登记研究。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root, reports_dir

PRODUCT_CODE = "CF"
TREND_CANDIDATE_STABILITY_VERSION = "V5.1_R93C_trend_candidate_stability_v1"
INFO = "INFO"
WARN = "WARN"
REQUIRED_EVENT_COLUMNS = {
    "event_date",
    "event_year",
    "event_id",
    "direction",
    "direction_episode_id",
    "horizon",
    "directional_return",
    "outcome",
    "historical_posterior_label",
    "event_features_use_t_or_earlier",
    "feature_asof_date",
}
WARNING_COLUMNS = (
    "run_id",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)
HUMAN_REVIEW_REQUIRED = (
    "retrospective_hypothesis_selection_contamination",
    "practical_effect_thresholds",
    "bootstrap_interval_interpretation",
    "option_proxy_interpretation",
    "strike_wall_open_interest_interpretation",
    "forward_sample_promotion_gate_not_yet_defined",
)
RESEARCH_BOUNDARY = (
    "R93C历史结果属于候选发现后的回顾性稳定性诊断，不是样本外证明；"
    "只有生效日期后的新episode可计入前向证据。模块不修改策略、影子手数或交易方向，"
    "不构成交易指令。"
)


@dataclass(frozen=True)
class CandidateHypothesis:
    """版本化候选假设。"""

    hypothesis_id: str
    feature_column: str
    feature_value: str
    primary_horizon: int
    desired_sign: int
    desired_effect: str
    forward_role: str
    rationale: str


@dataclass(frozen=True)
class EvaluationGate:
    """回顾性稳定性判定门槛。"""

    minimum_historical_treated: int
    minimum_historical_control: int
    minimum_direction_each: int
    minimum_year_each: int
    minimum_evaluable_years: int
    minimum_year_alignment_rate: float
    practical_hit_delta: float
    practical_return_delta: float
    era_split_year: int
    bootstrap_samples: int
    bootstrap_confidence: float
    bootstrap_seed: int


@dataclass(frozen=True)
class TrendCandidateSpec:
    """R93C 预登记规格。"""

    spec_version: str
    registered_at: date
    effective_after_date: date
    selection_disclosure: str
    strategy_actions_allowed: bool
    gate: EvaluationGate
    hypotheses: tuple[CandidateHypothesis, ...]
    diagnostic_horizons: tuple[int, ...]
    forbidden_actions: tuple[str, ...]


@dataclass(frozen=True)
class TrendCandidateStabilityWarningRecord:
    """R93C warning 行。"""

    run_id: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class TrendCandidateStabilityResult:
    """R93C 结果包。"""

    run_id: str
    start: date
    end: date
    effective_after_date: date
    status: str
    hypothesis_count: int
    ready_for_forward_count: int
    forward_watch_count: int
    historical_watch_count: int
    forward_event_count: int
    decisions: tuple[tuple[str, str], ...]
    primary_evaluation_path: Path
    horizon_profile_path: Path
    stability_slice_path: Path
    leave_one_year_out_path: Path
    forward_capture_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[TrendCandidateStabilityWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        return sum(item.severity != INFO for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "effective_after_date": self.effective_after_date.isoformat(),
            "status": self.status,
            "hypothesis_count": self.hypothesis_count,
            "ready_for_forward_count": self.ready_for_forward_count,
            "forward_watch_count": self.forward_watch_count,
            "historical_watch_count": self.historical_watch_count,
            "forward_event_count": self.forward_event_count,
            "decisions": dict(self.decisions),
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "primary_evaluation_path": str(self.primary_evaluation_path),
            "horizon_profile_path": str(self.horizon_profile_path),
            "stability_slice_path": str(self.stability_slice_path),
            "leave_one_year_out_path": str(self.leave_one_year_out_path),
            "forward_capture_path": str(self.forward_capture_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "research_boundary": RESEARCH_BOUNDARY,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_trend_candidate_stability_research(
    *,
    event_feature_path: Path | None = None,
    spec_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> TrendCandidateStabilityResult:
    """构建三项固定候选的回顾性稳定性与前向隔离证据。"""
    active_event_path = event_feature_path or _latest_event_feature_path()
    active_spec_path = spec_path or _default_spec_path()
    spec = _load_spec(active_spec_path)
    events = _load_events(active_event_path, spec)
    retrospective = events.loc[
        events["event_date"].le(spec.effective_after_date)
    ].copy()
    forward = events.loc[events["event_date"].gt(spec.effective_after_date)].copy()
    if retrospective.empty:
        raise ResearchWorkbenchError("R93C has no retrospective event rows")
    start = retrospective["event_date"].min()
    end = events["event_date"].max()
    active_run_id = run_id or _default_run_id(start=start, end=end)

    primary_rows: list[dict[str, object]] = []
    horizon_rows: list[dict[str, object]] = []
    slice_rows: list[dict[str, object]] = []
    loyo_rows: list[dict[str, object]] = []
    forward_rows: list[dict[str, object]] = []
    for hypothesis_index, hypothesis in enumerate(spec.hypotheses):
        primary = retrospective.loc[
            retrospective["horizon"].eq(hypothesis.primary_horizon)
        ].copy()
        if primary.empty:
            raise ResearchWorkbenchError(
                f"R93C has no horizon {hypothesis.primary_horizon} rows for "
                f"{hypothesis.hypothesis_id}"
            )
        slices = _build_slice_rows(primary, hypothesis=hypothesis, gate=spec.gate)
        leave_one_year_out = _build_leave_one_year_out_rows(
            primary,
            hypothesis=hypothesis,
            gate=spec.gate,
        )
        primary_row = _build_primary_evaluation(
            primary,
            hypothesis=hypothesis,
            gate=spec.gate,
            slices=slices,
            leave_one_year_out=leave_one_year_out,
            seed=spec.gate.bootstrap_seed + hypothesis_index,
        )
        primary_rows.append(primary_row)
        slice_rows.extend(slices)
        loyo_rows.extend(leave_one_year_out)
        horizon_rows.extend(
            _build_horizon_profile(
                retrospective,
                hypothesis=hypothesis,
                horizons=spec.diagnostic_horizons,
            )
        )
        forward_rows.extend(
            _build_forward_rows(
                forward,
                hypothesis=hypothesis,
                effective_after_date=spec.effective_after_date,
            )
        )

    primary_frame = pd.DataFrame(primary_rows)
    horizon_frame = pd.DataFrame(horizon_rows)
    slice_frame = pd.DataFrame(slice_rows)
    loyo_frame = pd.DataFrame(loyo_rows)
    forward_frame = _forward_frame(forward_rows)
    warnings = _warning_records(
        run_id=active_run_id,
        primary=primary_frame,
        forward=forward_frame,
        spec=spec,
    )
    decisions = tuple(
        (str(row.hypothesis_id), str(row.decision_status))
        for row in primary_frame.itertuples(index=False)
    )
    ready_count = int(
        primary_frame["decision_status"].eq(
            "READY_FOR_FORWARD_PREREGISTRATION"
        ).sum()
    )
    forward_watch_count = int(
        primary_frame["decision_status"].str.startswith("FORWARD_WATCH").sum()
    )
    historical_watch_count = int(
        primary_frame["decision_status"].eq("HISTORICAL_WATCH_ONLY").sum()
    )
    status = (
        "TREND_CANDIDATE_STABILITY_READY_WITH_WARNINGS"
        if any(item.severity == WARN for item in warnings)
        else "TREND_CANDIDATE_STABILITY_READY"
    )
    paths = _output_paths(
        start=start,
        end=end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    result = TrendCandidateStabilityResult(
        run_id=active_run_id,
        start=start,
        end=end,
        effective_after_date=spec.effective_after_date,
        status=status,
        hypothesis_count=len(spec.hypotheses),
        ready_for_forward_count=ready_count,
        forward_watch_count=forward_watch_count,
        historical_watch_count=historical_watch_count,
        forward_event_count=len(forward_frame),
        decisions=decisions,
        primary_evaluation_path=paths["primary"],
        horizon_profile_path=paths["horizon"],
        stability_slice_path=paths["slices"],
        leave_one_year_out_path=paths["loyo"],
        forward_capture_path=paths["forward"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=tuple(warnings),
    )
    _write_outputs(
        result=result,
        primary=primary_frame,
        horizon=horizon_frame,
        slices=slice_frame,
        leave_one_year_out=loyo_frame,
        forward=forward_frame,
        spec=spec,
        input_paths=(active_event_path, active_spec_path),
    )
    return result


def _load_spec(path: Path) -> TrendCandidateSpec:
    if not path.exists():
        raise ResearchWorkbenchError(f"R93C spec path does not exist: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResearchWorkbenchError(f"R93C spec must be a mapping: {path}")
    if payload.get("product_code") != PRODUCT_CODE:
        raise ResearchWorkbenchError("R93C spec product_code must be CF")
    if payload.get("strategy_actions_allowed") is not False:
        raise ResearchWorkbenchError("R93C spec must forbid strategy actions")
    gate_payload = payload.get("evaluation_gate")
    hypothesis_payload = payload.get("hypotheses")
    if not isinstance(gate_payload, dict) or not isinstance(hypothesis_payload, list):
        raise ResearchWorkbenchError("R93C spec missing evaluation_gate or hypotheses")
    gate = EvaluationGate(
        minimum_historical_treated=_positive_int(
            gate_payload, "minimum_historical_treated"
        ),
        minimum_historical_control=_positive_int(
            gate_payload, "minimum_historical_control"
        ),
        minimum_direction_each=_positive_int(
            gate_payload, "minimum_direction_each"
        ),
        minimum_year_each=_positive_int(gate_payload, "minimum_year_each"),
        minimum_evaluable_years=_positive_int(
            gate_payload, "minimum_evaluable_years"
        ),
        minimum_year_alignment_rate=_unit_float(
            gate_payload, "minimum_year_alignment_rate"
        ),
        practical_hit_delta=_positive_float(gate_payload, "practical_hit_delta"),
        practical_return_delta=_positive_float(
            gate_payload, "practical_return_delta"
        ),
        era_split_year=int(gate_payload["era_split_year"]),
        bootstrap_samples=_positive_int(gate_payload, "bootstrap_samples"),
        bootstrap_confidence=_unit_float(
            gate_payload, "bootstrap_confidence"
        ),
        bootstrap_seed=int(gate_payload["bootstrap_seed"]),
    )
    hypotheses: list[CandidateHypothesis] = []
    for item in hypothesis_payload:
        if not isinstance(item, dict):
            raise ResearchWorkbenchError("R93C hypothesis must be a mapping")
        desired_effect = str(item.get("desired_effect", ""))
        if desired_effect not in {"positive", "negative"}:
            raise ResearchWorkbenchError("R93C desired_effect must be positive or negative")
        hypotheses.append(
            CandidateHypothesis(
                hypothesis_id=str(item["hypothesis_id"]),
                feature_column=str(item["feature_column"]),
                feature_value=str(item["feature_value"]),
                primary_horizon=int(item["primary_horizon"]),
                desired_sign=1 if desired_effect == "positive" else -1,
                desired_effect=desired_effect,
                forward_role=str(item["forward_role"]),
                rationale=str(item["rationale"]),
            )
        )
    hypothesis_ids = [item.hypothesis_id for item in hypotheses]
    if len(hypotheses) != 3 or len(set(hypothesis_ids)) != len(hypothesis_ids):
        raise ResearchWorkbenchError("R93C spec must contain exactly three unique hypotheses")
    horizons = tuple(int(value) for value in payload.get("diagnostic_horizons", ()))
    if not horizons or any(value <= 0 for value in horizons):
        raise ResearchWorkbenchError("R93C diagnostic_horizons must be positive")
    registered_at = _parse_date(payload.get("registered_at"), "registered_at")
    effective_after = _parse_date(
        payload.get("effective_after_date"), "effective_after_date"
    )
    if registered_at < effective_after:
        raise ResearchWorkbenchError(
            "R93C registered_at cannot be earlier than effective_after_date"
        )
    return TrendCandidateSpec(
        spec_version=str(payload["spec_version"]),
        registered_at=registered_at,
        effective_after_date=effective_after,
        selection_disclosure=str(payload["selection_disclosure"]),
        strategy_actions_allowed=False,
        gate=gate,
        hypotheses=tuple(hypotheses),
        diagnostic_horizons=tuple(sorted(set(horizons))),
        forbidden_actions=tuple(str(value) for value in payload["forbidden_actions"]),
    )


def _load_events(path: Path, spec: TrendCandidateSpec) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"R93C event path does not exist: {path}")
    frame = pd.read_parquet(path)
    required = REQUIRED_EVENT_COLUMNS | {
        hypothesis.feature_column for hypothesis in spec.hypotheses
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"R93C event input missing columns {sorted(missing)}")
    working = frame[list(sorted(required))].copy()
    for column in ("event_date", "feature_asof_date"):
        working[column] = pd.to_datetime(working[column], errors="coerce").dt.date
        if working[column].isna().any():
            raise ResearchWorkbenchError(f"R93C event input contains invalid {column}")
    working["event_year"] = pd.to_numeric(
        working["event_year"], errors="coerce"
    ).astype("Int64")
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce").astype(
        "Int64"
    )
    working["directional_return"] = pd.to_numeric(
        working["directional_return"], errors="coerce"
    )
    if working[["event_year", "horizon", "directional_return"]].isna().any().any():
        raise ResearchWorkbenchError("R93C event input contains invalid labels")
    if not working["historical_posterior_label"].eq(True).all():  # noqa: E712
        raise ResearchWorkbenchError("R93C requires explicit historical posterior labels")
    if not working["event_features_use_t_or_earlier"].eq(True).all():  # noqa: E712
        raise ResearchWorkbenchError("R93C found a non-T-day feature row")
    if working["feature_asof_date"].gt(working["event_date"]).any():
        raise ResearchWorkbenchError("R93C feature_asof_date is later than event_date")
    if working.duplicated(["direction_episode_id", "horizon"]).any():
        raise ResearchWorkbenchError(
            "R93C requires one first-breakout row per episode and horizon"
        )
    return working.sort_values(["event_date", "horizon"]).reset_index(drop=True)


def _build_primary_evaluation(
    data: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    gate: EvaluationGate,
    slices: list[dict[str, object]],
    leave_one_year_out: list[dict[str, object]],
    seed: int,
) -> dict[str, object]:
    comparison = _comparison_metrics(data, hypothesis=hypothesis)
    bootstrap = _bootstrap_intervals(
        data,
        hypothesis=hypothesis,
        gate=gate,
        seed=seed,
    )
    stratified = _stratified_effect(data, hypothesis=hypothesis, gate=gate)
    slice_frame = pd.DataFrame(slices)
    direction_rows = slice_frame.loc[slice_frame["slice_type"].eq("direction")]
    era_rows = slice_frame.loc[slice_frame["slice_type"].eq("era")]
    year_rows = slice_frame.loc[slice_frame["slice_type"].eq("event_year")]
    eligible_years = year_rows.loc[year_rows["eligible"]]
    year_alignment_rate = (
        float(eligible_years["sign_aligned"].mean())
        if not eligible_years.empty
        else math.nan
    )
    full_practical_pass = _practical_aligned(
        desired_sign=hypothesis.desired_sign,
        delta_hit=float(comparison["delta_hit_rate"]),
        delta_return=float(comparison["delta_mean_directional_return"]),
        gate=gate,
    )
    bootstrap_pass = _bootstrap_aligned(
        desired_sign=hypothesis.desired_sign,
        hit_lower=bootstrap["bootstrap_hit_delta_lower"],
        hit_upper=bootstrap["bootstrap_hit_delta_upper"],
        return_lower=bootstrap["bootstrap_return_delta_lower"],
        return_upper=bootstrap["bootstrap_return_delta_upper"],
    )
    size_pass = (
        int(comparison["treated_count"]) >= gate.minimum_historical_treated
        and int(comparison["control_count"]) >= gate.minimum_historical_control
    )
    direction_pass = (
        len(direction_rows) == 2
        and direction_rows["eligible"].all()
        and direction_rows["practical_aligned"].all()
    )
    era_pass = (
        len(era_rows) == 2
        and era_rows["eligible"].all()
        and era_rows["practical_aligned"].all()
    )
    year_pass = (
        len(eligible_years) >= gate.minimum_evaluable_years
        and year_alignment_rate >= gate.minimum_year_alignment_rate
    )
    loyo_pass = bool(leave_one_year_out) and all(
        bool(row["practical_aligned"]) for row in leave_one_year_out
    )
    decision, reasons = _decision_status(
        full_practical_pass=full_practical_pass,
        bootstrap_pass=bootstrap_pass,
        size_pass=size_pass,
        direction_pass=direction_pass,
        era_pass=era_pass,
        year_pass=year_pass,
        loyo_pass=loyo_pass,
    )
    return {
        "hypothesis_id": hypothesis.hypothesis_id,
        "feature_column": hypothesis.feature_column,
        "feature_value": hypothesis.feature_value,
        "primary_horizon": hypothesis.primary_horizon,
        "desired_effect": hypothesis.desired_effect,
        "forward_role": hypothesis.forward_role,
        "rationale": hypothesis.rationale,
        **comparison,
        **bootstrap,
        **stratified,
        "full_practical_pass": full_practical_pass,
        "bootstrap_pass": bootstrap_pass,
        "size_pass": size_pass,
        "direction_pass": direction_pass,
        "era_pass": era_pass,
        "evaluable_year_count": len(eligible_years),
        "year_alignment_rate": year_alignment_rate,
        "year_pass": year_pass,
        "loyo_pass": loyo_pass,
        "decision_status": decision,
        "decision_reasons": ";".join(reasons),
        "selection_contaminated": True,
        "historical_result_is_oos": False,
        "strategy_change_allowed": False,
        "rule_version": TREND_CANDIDATE_STABILITY_VERSION,
    }


def _build_horizon_profile(
    data: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    horizons: tuple[int, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        group = data.loc[data["horizon"].eq(horizon)]
        if group.empty:
            continue
        rows.append(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "horizon": horizon,
                "is_primary_horizon": horizon == hypothesis.primary_horizon,
                **_comparison_metrics(group, hypothesis=hypothesis),
                "diagnostic_only": horizon != hypothesis.primary_horizon,
                "historical_result_is_oos": False,
                "rule_version": TREND_CANDIDATE_STABILITY_VERSION,
            }
        )
    return rows


def _build_slice_rows(
    data: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    gate: EvaluationGate,
) -> list[dict[str, object]]:
    working = data.copy()
    working["era"] = working["event_year"].map(
        lambda value: (
            f"EARLY_TO_{gate.era_split_year}"
            if int(value) <= gate.era_split_year
            else f"LATE_AFTER_{gate.era_split_year}"
        )
    )
    rows: list[dict[str, object]] = []
    definitions = (
        ("direction", "direction", gate.minimum_direction_each),
        ("era", "era", gate.minimum_year_each),
        ("event_year", "event_year", gate.minimum_year_each),
    )
    for slice_type, column, minimum_each in definitions:
        for value, group in working.groupby(column, sort=True):
            comparison = _comparison_metrics(
                group,
                hypothesis=hypothesis,
                allow_empty=True,
            )
            eligible = (
                int(comparison["treated_count"]) >= minimum_each
                and int(comparison["control_count"]) >= minimum_each
            )
            rows.append(
                {
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "primary_horizon": hypothesis.primary_horizon,
                    "slice_type": slice_type,
                    "slice_value": str(value),
                    **comparison,
                    "minimum_each": minimum_each,
                    "eligible": eligible,
                    "sign_aligned": _sign_aligned(
                        desired_sign=hypothesis.desired_sign,
                        delta_hit=float(comparison["delta_hit_rate"]),
                        delta_return=float(
                            comparison["delta_mean_directional_return"]
                        ),
                    ),
                    "practical_aligned": eligible
                    and _practical_aligned(
                        desired_sign=hypothesis.desired_sign,
                        delta_hit=float(comparison["delta_hit_rate"]),
                        delta_return=float(
                            comparison["delta_mean_directional_return"]
                        ),
                        gate=gate,
                    ),
                    "historical_result_is_oos": False,
                    "rule_version": TREND_CANDIDATE_STABILITY_VERSION,
                }
            )
    return rows


def _build_leave_one_year_out_rows(
    data: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    gate: EvaluationGate,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for excluded_year in sorted(int(value) for value in data["event_year"].unique()):
        remaining = data.loc[data["event_year"].ne(excluded_year)]
        comparison = _comparison_metrics(remaining, hypothesis=hypothesis)
        rows.append(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "primary_horizon": hypothesis.primary_horizon,
                "excluded_year": excluded_year,
                **comparison,
                "practical_aligned": _practical_aligned(
                    desired_sign=hypothesis.desired_sign,
                    delta_hit=float(comparison["delta_hit_rate"]),
                    delta_return=float(comparison["delta_mean_directional_return"]),
                    gate=gate,
                ),
                "historical_result_is_oos": False,
                "rule_version": TREND_CANDIDATE_STABILITY_VERSION,
            }
        )
    return rows


def _comparison_metrics(
    data: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    allow_empty: bool = False,
) -> dict[str, float | int]:
    treated_mask = data[hypothesis.feature_column].astype(str).eq(
        hypothesis.feature_value
    )
    treated = data.loc[treated_mask]
    control = data.loc[~treated_mask]
    if treated.empty or control.empty:
        if not allow_empty:
            raise ResearchWorkbenchError(
                f"R93C hypothesis {hypothesis.hypothesis_id} lacks treated or control rows"
            )
        return {
            "treated_count": len(treated),
            "control_count": len(control),
            "treated_hit_rate": math.nan,
            "control_hit_rate": math.nan,
            "delta_hit_rate": math.nan,
            "treated_mean_directional_return": math.nan,
            "control_mean_directional_return": math.nan,
            "delta_mean_directional_return": math.nan,
            "fisher_exact_p_value": math.nan,
        }
    treated_hit = float(treated["outcome"].eq("FOLLOW_THROUGH").mean())
    control_hit = float(control["outcome"].eq("FOLLOW_THROUGH").mean())
    treated_return = float(treated["directional_return"].mean())
    control_return = float(control["directional_return"].mean())
    return {
        "treated_count": len(treated),
        "control_count": len(control),
        "treated_hit_rate": treated_hit,
        "control_hit_rate": control_hit,
        "delta_hit_rate": treated_hit - control_hit,
        "treated_mean_directional_return": treated_return,
        "control_mean_directional_return": control_return,
        "delta_mean_directional_return": treated_return - control_return,
        "fisher_exact_p_value": _fisher_exact_two_sided(
            group_successes=int(treated["outcome"].eq("FOLLOW_THROUGH").sum()),
            group_count=len(treated),
            comparison_successes=int(control["outcome"].eq("FOLLOW_THROUGH").sum()),
            comparison_count=len(control),
        ),
    }


def _bootstrap_intervals(
    data: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    gate: EvaluationGate,
    seed: int,
) -> dict[str, float | int]:
    treated_mask = data[hypothesis.feature_column].astype(str).eq(
        hypothesis.feature_value
    )
    treated = data.loc[treated_mask]
    control = data.loc[~treated_mask]
    treated_returns = treated["directional_return"].to_numpy(dtype=float)
    control_returns = control["directional_return"].to_numpy(dtype=float)
    treated_hits = treated["outcome"].eq("FOLLOW_THROUGH").to_numpy(dtype=float)
    control_hits = control["outcome"].eq("FOLLOW_THROUGH").to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    treated_indices = rng.integers(
        0,
        len(treated),
        size=(gate.bootstrap_samples, len(treated)),
    )
    control_indices = rng.integers(
        0,
        len(control),
        size=(gate.bootstrap_samples, len(control)),
    )
    return_delta = treated_returns[treated_indices].mean(axis=1) - control_returns[
        control_indices
    ].mean(axis=1)
    hit_delta = treated_hits[treated_indices].mean(axis=1) - control_hits[
        control_indices
    ].mean(axis=1)
    alpha = (1.0 - gate.bootstrap_confidence) / 2.0
    return {
        "bootstrap_samples": gate.bootstrap_samples,
        "bootstrap_confidence": gate.bootstrap_confidence,
        "bootstrap_hit_delta_lower": float(np.quantile(hit_delta, alpha)),
        "bootstrap_hit_delta_upper": float(np.quantile(hit_delta, 1.0 - alpha)),
        "bootstrap_return_delta_lower": float(np.quantile(return_delta, alpha)),
        "bootstrap_return_delta_upper": float(
            np.quantile(return_delta, 1.0 - alpha)
        ),
    }


def _stratified_effect(
    data: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    gate: EvaluationGate,
) -> dict[str, float | int]:
    working = data.copy()
    working["era"] = working["event_year"].map(
        lambda value: "EARLY" if int(value) <= gate.era_split_year else "LATE"
    )
    weighted_hit = 0.0
    weighted_return = 0.0
    total_weight = 0.0
    strata_count = 0
    for _, group in working.groupby(["direction", "era"], sort=True):
        treated_mask = group[hypothesis.feature_column].astype(str).eq(
            hypothesis.feature_value
        )
        treated = group.loc[treated_mask]
        control = group.loc[~treated_mask]
        if treated.empty or control.empty:
            continue
        weight = len(treated) * len(control) / (len(treated) + len(control))
        hit_delta = float(treated["outcome"].eq("FOLLOW_THROUGH").mean()) - float(
            control["outcome"].eq("FOLLOW_THROUGH").mean()
        )
        return_delta = float(treated["directional_return"].mean()) - float(
            control["directional_return"].mean()
        )
        weighted_hit += hit_delta * weight
        weighted_return += return_delta * weight
        total_weight += weight
        strata_count += 1
    return {
        "stratified_direction_era_count": strata_count,
        "stratified_delta_hit_rate": (
            weighted_hit / total_weight if total_weight else math.nan
        ),
        "stratified_delta_mean_directional_return": (
            weighted_return / total_weight if total_weight else math.nan
        ),
    }


def _build_forward_rows(
    forward: pd.DataFrame,
    *,
    hypothesis: CandidateHypothesis,
    effective_after_date: date,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    primary = forward.loc[forward["horizon"].eq(hypothesis.primary_horizon)]
    for row in primary.itertuples(index=False):
        rows.append(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "effective_after_date": effective_after_date,
                "event_date": row.event_date,
                "event_id": row.event_id,
                "direction_episode_id": row.direction_episode_id,
                "direction": row.direction,
                "horizon": hypothesis.primary_horizon,
                "feature_column": hypothesis.feature_column,
                "feature_value": hypothesis.feature_value,
                "treated": str(getattr(row, hypothesis.feature_column))
                == hypothesis.feature_value,
                "outcome": row.outcome,
                "directional_return": row.directional_return,
                "record_mode": "FORWARD_POST_REGISTRATION",
                "historical_result_is_oos": True,
                "strategy_change_allowed": False,
                "rule_version": TREND_CANDIDATE_STABILITY_VERSION,
            }
        )
    return rows


def _forward_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    columns = (
        "hypothesis_id",
        "effective_after_date",
        "event_date",
        "event_id",
        "direction_episode_id",
        "direction",
        "horizon",
        "feature_column",
        "feature_value",
        "treated",
        "outcome",
        "directional_return",
        "record_mode",
        "historical_result_is_oos",
        "strategy_change_allowed",
        "rule_version",
    )
    return pd.DataFrame(rows, columns=columns)


def _decision_status(
    *,
    full_practical_pass: bool,
    bootstrap_pass: bool,
    size_pass: bool,
    direction_pass: bool,
    era_pass: bool,
    year_pass: bool,
    loyo_pass: bool,
) -> tuple[str, tuple[str, ...]]:
    checks = {
        "full_effect": full_practical_pass,
        "bootstrap_interval": bootstrap_pass,
        "historical_size": size_pass,
        "direction_stability": direction_pass,
        "era_stability": era_pass,
        "year_stability": year_pass,
        "leave_one_year_out": loyo_pass,
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    core_without_size_direction = (
        full_practical_pass
        and bootstrap_pass
        and era_pass
        and year_pass
        and loyo_pass
    )
    if all(checks.values()):
        return "READY_FOR_FORWARD_PREREGISTRATION", ()
    if core_without_size_direction and not size_pass:
        return "FORWARD_WATCH_SMALL_SAMPLE", failed
    if core_without_size_direction and not direction_pass:
        return "FORWARD_WATCH_DIRECTIONAL_COVERAGE", failed
    if full_practical_pass:
        return "HISTORICAL_WATCH_ONLY", failed
    return "RETROSPECTIVE_REJECT", failed


def _practical_aligned(
    *,
    desired_sign: int,
    delta_hit: float,
    delta_return: float,
    gate: EvaluationGate,
) -> bool:
    return (
        desired_sign * delta_hit >= gate.practical_hit_delta
        and desired_sign * delta_return >= gate.practical_return_delta
    )


def _sign_aligned(*, desired_sign: int, delta_hit: float, delta_return: float) -> bool:
    return desired_sign * delta_hit > 0 and desired_sign * delta_return > 0


def _bootstrap_aligned(
    *,
    desired_sign: int,
    hit_lower: float,
    hit_upper: float,
    return_lower: float,
    return_upper: float,
) -> bool:
    if desired_sign > 0:
        return hit_lower > 0 and return_lower > 0
    return hit_upper < 0 and return_upper < 0


def _warning_records(
    *,
    run_id: str,
    primary: pd.DataFrame,
    forward: pd.DataFrame,
    spec: TrendCandidateSpec,
) -> list[TrendCandidateStabilityWarningRecord]:
    warnings = [
        TrendCandidateStabilityWarningRecord(
            run_id=run_id,
            severity=WARN,
            warning_code="R93C_RETROSPECTIVE_SELECTION_CONTAMINATION",
            warning_message=spec.selection_disclosure,
            affected_count=len(primary),
            human_review_required=(
                "retrospective_hypothesis_selection_contamination",
            ),
        )
    ]
    small = primary.loc[~primary["size_pass"]]
    if not small.empty:
        warnings.append(
            TrendCandidateStabilityWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93C_HISTORICAL_SAMPLE_GATE_FAILED",
                warning_message="部分候选历史触发样本不足，只允许进入前向观察名单。",
                affected_count=len(small),
                human_review_required=("practical_effect_thresholds",),
            )
        )
    direction_failed = primary.loc[~primary["direction_pass"]]
    if not direction_failed.empty:
        warnings.append(
            TrendCandidateStabilityWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93C_DIRECTION_STABILITY_FAILED",
                warning_message="部分候选未同时通过long/short方向覆盖与实际效应门槛。",
                affected_count=len(direction_failed),
                human_review_required=("option_proxy_interpretation",),
            )
        )
    bootstrap_failed = primary.loc[~primary["bootstrap_pass"]]
    if not bootstrap_failed.empty:
        warnings.append(
            TrendCandidateStabilityWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93C_BOOTSTRAP_INTERVAL_CROSSES_ZERO",
                warning_message="部分候选的命中差或收益差bootstrap区间跨零。",
                affected_count=len(bootstrap_failed),
                human_review_required=("bootstrap_interval_interpretation",),
            )
        )
    warnings.append(
        TrendCandidateStabilityWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93C_FORWARD_CAPTURE_STATUS",
            warning_message=(
                "当前尚无生效日期后的独立事件标签。"
                if forward.empty
                else "已隔离写出生效日期后的前向事件标签。"
            ),
            affected_count=len(forward),
        )
    )
    warnings.append(
        TrendCandidateStabilityWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93C_STRATEGY_ISOLATION",
            warning_message="R93C不修改CF_tsmom_v0、CF_phase_gated_v0或影子手数。",
            affected_count=0,
        )
    )
    return warnings


def _write_outputs(
    *,
    result: TrendCandidateStabilityResult,
    primary: pd.DataFrame,
    horizon: pd.DataFrame,
    slices: pd.DataFrame,
    leave_one_year_out: pd.DataFrame,
    forward: pd.DataFrame,
    spec: TrendCandidateSpec,
    input_paths: tuple[Path, ...],
) -> None:
    for path, frame in (
        (result.primary_evaluation_path, primary),
        (result.horizon_profile_path, horizon),
        (result.stability_slice_path, slices),
        (result.leave_one_year_out_path, leave_one_year_out),
        (result.forward_capture_path, forward),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    _write_warning_csv(result.warning_csv_path, result.warning_records)
    payload = {
        **result.to_summary(),
        "rule_version": TREND_CANDIDATE_STABILITY_VERSION,
        "spec": _spec_summary(spec),
        "primary_evaluation": [
            _json_safe(row) for row in primary.to_dict(orient="records")
        ],
        "historical_results_are_retrospective": True,
        "trading_instruction": "not_a_trading_instruction",
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result.markdown_path.write_text(
        _render_markdown(
            result=result,
            primary=primary,
            horizon=horizon,
            slices=slices,
            leave_one_year_out=leave_one_year_out,
            spec=spec,
        ),
        encoding="utf-8",
    )
    artifacts = (
        result.primary_evaluation_path,
        result.horizon_profile_path,
        result.stability_slice_path,
        result.leave_one_year_out_path,
        result.forward_capture_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        **result.to_summary(),
        "rule_version": TREND_CANDIDATE_STABILITY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "spec": _spec_summary(spec),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "historical_results_are_retrospective": True,
        "trading_instruction": "not_a_trading_instruction",
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: TrendCandidateStabilityResult,
    primary: pd.DataFrame,
    horizon: pd.DataFrame,
    slices: pd.DataFrame,
    leave_one_year_out: pd.DataFrame,
    spec: TrendCandidateSpec,
) -> str:
    lines = [
        f"# CF 趋势候选稳定性与前向预登记研究 - {result.end}",
        "",
        "## 数据与登记边界",
        "",
        f"- 回顾性事件区间：`{result.start}` 至 `{result.end}`",
        f"- 规格登记日：`{spec.registered_at}`",
        f"- 前向生效边界：仅 `{spec.effective_after_date}` 之后的新episode计入前向证据。",
        f"- 前向事件标签：`{result.forward_event_count}` 行",
        f"- {spec.selection_disclosure}",
        "",
        "## 候选决策",
        "",
        "| 假设 | 主周期 | 样本/对照 | 命中差 | 收益差 | bootstrap收益区间 | 决策 |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in primary.itertuples(index=False):
        lines.append(
            f"| {row.hypothesis_id} | {int(row.primary_horizon)}D | "
            f"{int(row.treated_count)}/{int(row.control_count)} | "
            f"{float(row.delta_hit_rate):+.2%} | "
            f"{float(row.delta_mean_directional_return):+.2%} | "
            f"[{float(row.bootstrap_return_delta_lower):+.2%}, "
            f"{float(row.bootstrap_return_delta_upper):+.2%}] | "
            f"{row.decision_status} |"
        )
    lines.extend(["", "## 稳定性门槛", ""])
    for row in primary.itertuples(index=False):
        lines.append(
            f"- `{row.hypothesis_id}`：全样本 `{_pass(row.full_practical_pass)}`，"
            f"bootstrap `{_pass(row.bootstrap_pass)}`，样本量 `{_pass(row.size_pass)}`，"
            f"多空方向 `{_pass(row.direction_pass)}`，早晚样本 `{_pass(row.era_pass)}`，"
            f"年度 `{_pass(row.year_pass)}`，留一年 `{_pass(row.loyo_pass)}`；"
            f"可评估年度 `{int(row.evaluable_year_count)}` 个，年度同向率 "
            f"`{float(row.year_alignment_rate):.2%}`。"
        )
    lines.extend(
        [
            "",
            "## 多空与早晚样本",
            "",
            "| 假设 | 分组 | 值 | 样本/对照 | 命中差 | 收益差 | 可评估 | 实际效应同向 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    visible_slices = slices.loc[slices["slice_type"].isin(("direction", "era"))]
    for row in visible_slices.itertuples(index=False):
        lines.append(
            f"| {row.hypothesis_id} | {row.slice_type} | {row.slice_value} | "
            f"{int(row.treated_count)}/{int(row.control_count)} | "
            f"{float(row.delta_hit_rate):+.2%} | "
            f"{float(row.delta_mean_directional_return):+.2%} | "
            f"{_pass(row.eligible)} | {_pass(row.practical_aligned)} |"
        )
    lines.extend(
        [
            "",
            "## 周期形态",
            "",
            "| 假设 | 周期 | 主检验 | 样本/对照 | 命中差 | 收益差 |",
            "| --- | ---: | --- | ---: | ---: | ---: |",
        ]
    )
    for row in horizon.itertuples(index=False):
        lines.append(
            f"| {row.hypothesis_id} | {int(row.horizon)}D | "
            f"{'PRIMARY' if row.is_primary_horizon else 'DIAGNOSTIC'} | "
            f"{int(row.treated_count)}/{int(row.control_count)} | "
            f"{float(row.delta_hit_rate):+.2%} | "
            f"{float(row.delta_mean_directional_return):+.2%} |"
        )
    lines.extend(["", "## 留一年检验", ""])
    for hypothesis_id, group in leave_one_year_out.groupby("hypothesis_id"):
        failed = group.loc[~group["practical_aligned"], "excluded_year"].tolist()
        lines.append(
            f"- `{hypothesis_id}`：剔除任一年后"
            f"{'均保持实际效应同向' if not failed else f'失败年份 {failed}'}。"
        )
    lines.extend(
        [
            "",
            "## 研究判断",
            "",
            "- `READY_FOR_FORWARD_PREREGISTRATION` 仅表示规则已冻结，"
            "可从生效边界后积累新证据，不表示历史样本外验证通过。",
            "- `FORWARD_WATCH_*` 允许记录前向事件，但不得据此调整现有策略仓位。",
            "- `HISTORICAL_WATCH_ONLY` 继续保留研究观察，不进入前向晋级候选。",
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- bootstrap与留一年检验不能消除候选由同一全历史样本发现造成的选择偏误。",
            "- 期权IV、skew、PCR与OI墙仍为研究proxy，不能推断机构净头寸或净Gamma。",
            f"- 禁止动作：`{';'.join(spec.forbidden_actions)}`",
            f"- HUMAN_REVIEW_REQUIRED：`{';'.join(HUMAN_REVIEW_REQUIRED)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _spec_summary(spec: TrendCandidateSpec) -> dict[str, object]:
    return {
        "spec_version": spec.spec_version,
        "registered_at": spec.registered_at.isoformat(),
        "effective_after_date": spec.effective_after_date.isoformat(),
        "selection_disclosure": spec.selection_disclosure,
        "strategy_actions_allowed": spec.strategy_actions_allowed,
        "diagnostic_horizons": list(spec.diagnostic_horizons),
        "forbidden_actions": list(spec.forbidden_actions),
        "hypotheses": [
            {
                "hypothesis_id": item.hypothesis_id,
                "feature_column": item.feature_column,
                "feature_value": item.feature_value,
                "primary_horizon": item.primary_horizon,
                "desired_effect": item.desired_effect,
                "forward_role": item.forward_role,
                "rationale": item.rationale,
            }
            for item in spec.hypotheses
        ],
    }


def _fisher_exact_two_sided(
    *,
    group_successes: int,
    group_count: int,
    comparison_successes: int,
    comparison_count: int,
) -> float:
    total = group_count + comparison_count
    total_successes = group_successes + comparison_successes
    observed = _hypergeometric_probability(
        group_successes=group_successes,
        group_count=group_count,
        total_successes=total_successes,
        total_count=total,
    )
    minimum = max(0, group_count - (total - total_successes))
    maximum = min(group_count, total_successes)
    probability = 0.0
    for successes in range(minimum, maximum + 1):
        candidate = _hypergeometric_probability(
            group_successes=successes,
            group_count=group_count,
            total_successes=total_successes,
            total_count=total,
        )
        if candidate <= observed + 1e-12:
            probability += candidate
    return min(1.0, probability)


def _hypergeometric_probability(
    *,
    group_successes: int,
    group_count: int,
    total_successes: int,
    total_count: int,
) -> float:
    return (
        math.comb(total_successes, group_successes)
        * math.comb(total_count - total_successes, group_count - group_successes)
        / math.comb(total_count, group_count)
    )


def _positive_int(payload: dict[str, object], key: str) -> int:
    value = int(payload[key])
    if value <= 0:
        raise ResearchWorkbenchError(f"R93C {key} must be positive")
    return value


def _positive_float(payload: dict[str, object], key: str) -> float:
    value = float(payload[key])
    if value <= 0:
        raise ResearchWorkbenchError(f"R93C {key} must be positive")
    return value


def _unit_float(payload: dict[str, object], key: str) -> float:
    value = float(payload[key])
    if not 0 < value < 1:
        raise ResearchWorkbenchError(f"R93C {key} must be within (0, 1)")
    return value


def _parse_date(value: object, label: str) -> date:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ResearchWorkbenchError(f"R93C invalid {label}: {value}") from exc
    if pd.isna(parsed):
        raise ResearchWorkbenchError(f"R93C invalid {label}: {value}")
    return parsed.date()


def _pass(value: object) -> str:
    return "PASS" if bool(value) else "FAIL"


def _json_safe(record: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
        elif value is None or value is pd.NA:
            result[key] = None
        elif isinstance(value, float) and math.isnan(value):
            result[key] = None
        elif isinstance(value, np.generic):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "trend_candidate_stability"
    report_root = report_output_dir or reports_dir() / "research" / "trend_candidate_stability"
    stem = f"CF_{start}_{end}_trend_candidate_stability"
    return {
        "primary": data_root / f"{stem}_primary_evaluation.parquet",
        "horizon": data_root / f"{stem}_horizon_profile.parquet",
        "slices": data_root / f"{stem}_stability_slice.parquet",
        "loyo": data_root / f"{stem}_leave_one_year_out.parquet",
        "forward": data_root / f"{stem}_forward_capture.parquet",
        "warnings": data_root / f"{stem}_warnings.csv",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
        "manifest": data_root / f"{stem}_manifest.json",
    }


def _write_warning_csv(
    path: Path,
    warnings: tuple[TrendCandidateStabilityWarningRecord, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for warning in warnings:
            writer.writerow(warning.to_csv_row())


def _latest_event_feature_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "trend_option_timing"
    paths = sorted(root.glob("*_trend_option_timing_independent_event_feature.parquet"))
    if not paths:
        raise ResearchWorkbenchError(f"R93B independent event feature not found under {root}")
    return paths[-1]


def _default_spec_path() -> Path:
    return project_root() / "configs" / "research" / "CF_trend_candidate_preregistration_v1.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(*, start: date, end: date) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return (
        f"cf_trend_candidate_stability_{start:%Y%m%d}_{end:%Y%m%d}_{stamp}_{suffix}"
    )
