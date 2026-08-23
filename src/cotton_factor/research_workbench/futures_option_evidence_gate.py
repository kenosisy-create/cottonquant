"""R93R CF期货-期权统一证据门控与停止决策。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
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
RULE_VERSION = "V5.1_R93R_futures_option_evidence_gate_v1"
DEFAULT_HORIZONS = (1, 3, 5)
DEFAULT_COST_BPS_PER_SIDE = (0, 5, 10)
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_DEAD_ZONE_BPS = 10
MATURE_STAGE = "MATURE_ACTIVE"
DECISIONS = {"KEEP", "WATCH", "REJECT"}
WARN = "WARN"
INFO = "INFO"

HUMAN_REVIEW_REQUIRED = (
    "option_open_interest_long_short_ownership_unknown",
    "option_iv_and_greek_are_research_proxies",
    "event_cost_is_round_trip_bps_proxy_not_execution_backtest",
    "fdr_and_leave_one_year_out_interpretation",
    "mature_active_stage_boundary",
    "explanatory_retention_is_not_predictive_promotion",
)

RESEARCH_BOUNDARY = {
    "features_use_t_or_earlier": True,
    "forward_returns_are_historical_posterior_labels": True,
    "t_plus_one_execution": True,
    "fixed_candidates_only": True,
    "post_hoc_threshold_search": False,
    "automatic_direction_reversal": False,
    "event_cost_is_round_trip_proxy": True,
    "enters_signal_matrix": False,
    "enters_composite_score": False,
    "changes_strategy_direction_or_sizing": False,
    "trading_instruction": "not_a_trading_instruction",
}

R93N_LABEL_REQUIRED = {
    "observation_id",
    "trade_date",
    "calendar_year",
    "option_market_stage",
    "horizon",
    "execution_date",
    "exit_date",
    "long_mfe",
    "long_mae",
    "short_mfe",
    "short_mae",
    "futures_direction",
    "futures_directional_return",
    "futures_hit",
    "r48_option_direction",
    "r48_directional_return",
    "r48_hit",
    "dynamic_option_direction",
    "dynamic_directional_return",
    "dynamic_hit",
    "forward_label_available",
    "t_plus_one_execution",
    "forward_returns_are_historical_posterior_labels",
}

R93O_EVIDENCE_REQUIRED = {
    "candidate_id",
    "candidate_family",
    "comparison_mode",
    "option_market_stage",
    "horizon",
    "candidate_sample_count",
    "candidate_hit_rate",
    "candidate_mean_directional_return",
    "candidate_median_directional_return",
    "candidate_mean_mfe",
    "candidate_mean_mae",
    "primary_incremental_mean_return",
    "fdr_q_value",
    "oos_test_years",
    "oos_positive_years",
    "oos_non_partial_positive",
    "decision",
    "decision_reason",
}

R93O_POSTERIOR_REQUIRED = {
    "observation_id",
    "trade_date",
    "calendar_year",
    "option_market_stage",
    "candidate_id",
    "candidate_family",
    "horizon",
    "execution_date",
    "exit_date",
    "signal_active",
    "candidate_directional_return",
    "candidate_hit",
    "candidate_mfe",
    "candidate_mae",
    "forward_label_available",
    "t_plus_one_execution",
    "forward_returns_are_historical_posterior_labels",
}

R93P_SUMMARY_REQUIRED = {
    "event_family",
    "event_type",
    "horizon",
    "sample_count",
    "directional_count",
    "continuation_rate",
    "mean_directional_return",
    "median_directional_return",
    "mean_mfe",
    "mean_mae",
    "fdr_q_value",
    "predictive_evidence_status",
    "forward_returns_are_historical_posterior_labels",
}

R93P_RESOLUTION_REQUIRED = {
    "event_family",
    "event_type",
    "option_market_stage",
    "available_path_count",
    "mean_first_resolution_horizon",
    "median_first_resolution_horizon",
    "forward_returns_are_historical_posterior_labels",
}

R93P_OOS_REQUIRED = {
    "event_family",
    "event_type",
    "horizon",
    "test_year",
    "test_year_is_partial",
    "test_sample_count",
    "oos_status",
    "forward_returns_are_historical_posterior_labels",
}

R93Q_MAIN_REQUIRED = {
    "event_family",
    "event_direction",
    "horizon",
    "market_stage",
    "stage_sample_count",
    "stage_hit_rate",
    "stage_mean_directional_return",
    "fdr_q_value",
    "evidence_status",
    "forward_returns_are_historical_posterior_labels",
}

R93Q_PRIMARY_REQUIRED = {
    "interaction_id",
    "base_value",
    "event_direction",
    "horizon",
    "market_stage",
    "interaction_dimension",
    "interaction_level",
    "target_stage_level_sample_count",
    "target_stage_control_sample_count",
    "target_stage_level_hit_rate",
    "target_stage_level_mean_directional_return",
    "target_stage_level_median_directional_return",
    "interaction_delta_hit_rate",
    "interaction_delta_mean_return",
    "fisher_fdr_q_value",
    "permutation_fdr_q_value",
    "annual_comparable_years",
    "annual_sign_consistency_rate",
    "oos_support_count",
    "oos_contradict_count",
    "evidence_status",
    "forward_returns_are_historical_posterior_labels",
}


@dataclass(frozen=True)
class FuturesOptionEvidenceGateWarningRecord:
    """R93R输入、口径和停止决策告警。"""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: str = ""

    def to_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": self.human_review_required,
        }


@dataclass(frozen=True)
class ResearchFuturesOptionEvidenceGateResult:
    """R93R统一证据门控产物与停止结论。"""

    run_id: str
    start: date
    end: date
    status: str
    expansion_decision: str
    stop_option_factor_expansion: bool
    r94_unlocked: bool
    evidence_row_count: int
    module_count: int
    keep_count: int
    reference_keep_count: int
    predictive_keep_count: int
    watch_count: int
    reject_count: int
    promotable_candidate_count: int
    cost_sensitivity_row_count: int
    warning_records: tuple[FuturesOptionEvidenceGateWarningRecord, ...]
    r93n_label_path: Path
    r93o_evidence_path: Path
    r93o_posterior_path: Path
    r93p_summary_path: Path
    r93p_resolution_path: Path
    r93p_oos_path: Path
    r93q_main_effect_path: Path
    r93q_primary_path: Path
    evidence_parquet_path: Path
    evidence_csv_path: Path
    module_summary_parquet_path: Path
    module_summary_csv_path: Path
    cost_sensitivity_parquet_path: Path
    cost_sensitivity_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path

    @property
    def warning_count(self) -> int:
        return sum(item.severity == WARN for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "status": self.status,
            "expansion_decision": self.expansion_decision,
            "stop_option_factor_expansion": self.stop_option_factor_expansion,
            "r94_unlocked": self.r94_unlocked,
            "evidence_row_count": self.evidence_row_count,
            "module_count": self.module_count,
            "keep_count": self.keep_count,
            "reference_keep_count": self.reference_keep_count,
            "predictive_keep_count": self.predictive_keep_count,
            "watch_count": self.watch_count,
            "reject_count": self.reject_count,
            "promotable_candidate_count": self.promotable_candidate_count,
            "cost_sensitivity_row_count": self.cost_sensitivity_row_count,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "evidence_parquet_path": str(self.evidence_parquet_path),
            "module_summary_parquet_path": str(self.module_summary_parquet_path),
            "cost_sensitivity_parquet_path": str(
                self.cost_sensitivity_parquet_path
            ),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "fixed_candidates_only": True,
            "historical_returns_are_posterior_labels": True,
            "enters_signal_matrix": False,
            "enters_composite_score": False,
            "changes_strategy_direction_or_sizing": False,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_futures_option_evidence_gate(
    *,
    r93n_label_path: Path | None = None,
    r93o_evidence_path: Path | None = None,
    r93o_posterior_path: Path | None = None,
    r93p_summary_path: Path | None = None,
    r93p_resolution_path: Path | None = None,
    r93p_oos_path: Path | None = None,
    r93q_main_effect_path: Path | None = None,
    r93q_primary_path: Path | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    cost_bps_per_side: tuple[int, ...] = DEFAULT_COST_BPS_PER_SIDE,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchFuturesOptionEvidenceGateResult:
    """汇总冻结证据并裁决是否停止本轮CF期权因子扩张。"""

    normalized_horizons, normalized_costs = _validate_parameters(
        horizons=horizons,
        cost_bps_per_side=cost_bps_per_side,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        dead_zone_bps=dead_zone_bps,
    )
    inputs = _resolve_inputs(
        r93n_label_path=r93n_label_path,
        r93o_evidence_path=r93o_evidence_path,
        r93o_posterior_path=r93o_posterior_path,
        r93p_summary_path=r93p_summary_path,
        r93p_resolution_path=r93p_resolution_path,
        r93p_oos_path=r93p_oos_path,
        r93q_main_effect_path=r93q_main_effect_path,
        r93q_primary_path=r93q_primary_path,
    )
    r93n_labels = _load_posterior_table(
        inputs["r93n_label"],
        required=R93N_LABEL_REQUIRED,
        label="R93N lifecycle label",
    )
    r93o_evidence = load_table(
        inputs["r93o_evidence"],
        required=R93O_EVIDENCE_REQUIRED,
        label="R93O candidate evidence",
    )
    r93o_posterior = _load_posterior_table(
        inputs["r93o_posterior"],
        required=R93O_POSTERIOR_REQUIRED,
        label="R93O posterior label",
    )
    r93p_summary = _load_historical_summary(
        inputs["r93p_summary"],
        required=R93P_SUMMARY_REQUIRED,
        label="R93P event summary",
    )
    r93p_resolution = _load_historical_summary(
        inputs["r93p_resolution"],
        required=R93P_RESOLUTION_REQUIRED,
        label="R93P resolution timing",
    )
    r93p_oos = _load_historical_summary(
        inputs["r93p_oos"],
        required=R93P_OOS_REQUIRED,
        label="R93P purged leave-one-year-out",
    )
    r93q_main = _load_historical_summary(
        inputs["r93q_main"],
        required=R93Q_MAIN_REQUIRED,
        label="R93Q stage main effect",
    )
    r93q_primary = _load_historical_summary(
        inputs["r93q_primary"],
        required=R93Q_PRIMARY_REQUIRED,
        label="R93Q primary interaction",
    )

    r93n_labels = r93n_labels.loc[
        r93n_labels["horizon"].isin(normalized_horizons)
    ].copy()
    r93o_evidence = r93o_evidence.loc[
        r93o_evidence["horizon"].isin(normalized_horizons)
    ].copy()
    r93o_posterior = r93o_posterior.loc[
        r93o_posterior["horizon"].isin(normalized_horizons)
    ].copy()
    r93p_summary = r93p_summary.loc[
        r93p_summary["horizon"].isin(normalized_horizons)
    ].copy()
    r93p_oos = r93p_oos.loc[
        r93p_oos["horizon"].isin(normalized_horizons)
    ].copy()
    r93q_main = r93q_main.loc[
        r93q_main["horizon"].isin(normalized_horizons)
    ].copy()
    r93q_primary = r93q_primary.loc[
        r93q_primary["horizon"].isin(normalized_horizons)
    ].copy()
    if r93n_labels.empty or r93o_evidence.empty or r93o_posterior.empty:
        raise ResearchWorkbenchError("R93R固定周期过滤后缺少R93N/R93O核心证据")

    start = min(r93n_labels["trade_date"])
    end = max(r93n_labels["trade_date"])
    active_run_id = run_id or utc_timestamp_id("r93r_evidence_gate", end)
    cost_sensitivity = _build_cost_sensitivity(
        labels=r93n_labels,
        candidate_labels=r93o_posterior,
        costs=normalized_costs,
        dead_zone_bps=dead_zone_bps,
        run_id=active_run_id,
    )
    model_evidence = _build_model_evidence(
        labels=r93n_labels,
        cost_sensitivity=cost_sensitivity,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    r93o_rows = _build_r93o_evidence(
        evidence=r93o_evidence,
        cost_sensitivity=cost_sensitivity,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        run_id=active_run_id,
    )
    r93p_rows = _build_r93p_evidence(
        summary=r93p_summary,
        resolution=r93p_resolution,
        oos=r93p_oos,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        run_id=active_run_id,
    )
    r93q_rows = _build_r93q_evidence(
        primary=r93q_primary,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        run_id=active_run_id,
    )
    evidence = pd.concat(
        [model_evidence, r93o_rows, r93p_rows, r93q_rows],
        ignore_index=True,
    )
    evidence = evidence.sort_values(
        ["source_module", "horizon", "evidence_id"]
    ).reset_index(drop=True)
    if not set(evidence["decision"]).issubset(DECISIONS):
        raise ResearchWorkbenchError("R93R内部错误：统一裁决超出KEEP/WATCH/REJECT")

    promotable = evidence.loc[
        evidence["predictive_promotion_eligible"]
        & evidence["decision"].eq("KEEP")
        & ~evidence["decision_scope"].eq("REFERENCE_BASELINE")
    ]
    stop_expansion = promotable.empty
    expansion_decision = (
        "REJECT_STOP_OPTION_FACTOR_EXPANSION"
        if stop_expansion
        else "KEEP_FIXED_CANDIDATE_VALIDATION"
    )
    module_summary = _build_module_summary(
        evidence=evidence,
        r93q_main=r93q_main,
        stop_expansion=stop_expansion,
        run_id=active_run_id,
    )
    warnings = _build_warnings(
        run_id=active_run_id,
        evidence=evidence,
        stop_expansion=stop_expansion,
    )
    paths = _build_paths(
        start=start,
        end=end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(evidence, paths["evidence_parquet"], paths["evidence_csv"])
    write_frame(
        module_summary,
        paths["module_summary_parquet"],
        paths["module_summary_csv"],
    )
    write_frame(
        cost_sensitivity,
        paths["cost_sensitivity_parquet"],
        paths["cost_sensitivity_csv"],
    )
    write_warning_csv(paths["warning_csv"], (item.to_summary() for item in warnings))

    decision_counts = evidence["decision"].value_counts().to_dict()
    reference_keep_count = int(
        (
            evidence["decision"].eq("KEEP")
            & evidence["decision_scope"].eq("REFERENCE_BASELINE")
        ).sum()
    )
    result = ResearchFuturesOptionEvidenceGateResult(
        run_id=active_run_id,
        start=start,
        end=end,
        status="READY_WITH_WARNINGS" if any(w.severity == WARN for w in warnings) else "READY",
        expansion_decision=expansion_decision,
        stop_option_factor_expansion=stop_expansion,
        r94_unlocked=False,
        evidence_row_count=len(evidence),
        module_count=len(module_summary),
        keep_count=int(decision_counts.get("KEEP", 0)),
        reference_keep_count=reference_keep_count,
        predictive_keep_count=int(decision_counts.get("KEEP", 0))
        - reference_keep_count,
        watch_count=int(decision_counts.get("WATCH", 0)),
        reject_count=int(decision_counts.get("REJECT", 0)),
        promotable_candidate_count=len(promotable),
        cost_sensitivity_row_count=len(cost_sensitivity),
        warning_records=tuple(warnings),
        r93n_label_path=inputs["r93n_label"],
        r93o_evidence_path=inputs["r93o_evidence"],
        r93o_posterior_path=inputs["r93o_posterior"],
        r93p_summary_path=inputs["r93p_summary"],
        r93p_resolution_path=inputs["r93p_resolution"],
        r93p_oos_path=inputs["r93p_oos"],
        r93q_main_effect_path=inputs["r93q_main"],
        r93q_primary_path=inputs["r93q_primary"],
        evidence_parquet_path=paths["evidence_parquet"],
        evidence_csv_path=paths["evidence_csv"],
        module_summary_parquet_path=paths["module_summary_parquet"],
        module_summary_csv_path=paths["module_summary_csv"],
        cost_sensitivity_parquet_path=paths["cost_sensitivity_parquet"],
        cost_sensitivity_csv_path=paths["cost_sensitivity_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
    )
    _write_markdown(
        result=result,
        evidence=evidence,
        modules=module_summary,
        costs=cost_sensitivity,
        r93q_main=r93q_main,
    )
    parameters = {
        "horizons": list(normalized_horizons),
        "cost_bps_per_side": list(normalized_costs),
        "min_sample_size": min_sample_size,
        "fdr_level": fdr_level,
        "dead_zone_bps": dead_zone_bps,
        "mature_stage": MATURE_STAGE,
    }
    write_json(
        result.json_path,
        {
            "report_type": "cf_futures_option_evidence_gate",
            "rule_version": RULE_VERSION,
            "summary": result.to_summary(),
            "module_decisions": module_summary.to_dict(orient="records"),
            "parameters": parameters,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    manifest = artifact_manifest(
        run_id=active_run_id,
        report_type="cf_futures_option_evidence_gate",
        rule_version=RULE_VERSION,
        data_asof=end,
        input_paths={key: value for key, value in inputs.items()},
        output_paths={
            "evidence_parquet_path": result.evidence_parquet_path,
            "module_summary_parquet_path": result.module_summary_parquet_path,
            "cost_sensitivity_parquet_path": result.cost_sensitivity_parquet_path,
            "warning_csv_path": result.warning_csv_path,
            "markdown_path": result.markdown_path,
            "json_path": result.json_path,
        },
        human_review_required=HUMAN_REVIEW_REQUIRED,
        research_boundary=RESEARCH_BOUNDARY,
    )
    manifest["parameters"] = parameters
    manifest["expansion_decision"] = expansion_decision
    manifest["stop_option_factor_expansion"] = stop_expansion
    manifest["r94_unlocked"] = False
    write_json(result.manifest_path, manifest)
    return result


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    cost_bps_per_side: tuple[int, ...],
    min_sample_size: int,
    fdr_level: float,
    dead_zone_bps: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    normalized_horizons = tuple(sorted(set(int(value) for value in horizons)))
    if not normalized_horizons or not set(normalized_horizons).issubset(
        set(DEFAULT_HORIZONS)
    ):
        raise ResearchWorkbenchError("R93R horizons只允许1,3,5")
    normalized_costs = tuple(sorted(set(int(value) for value in cost_bps_per_side)))
    if not normalized_costs or normalized_costs[0] != 0 or any(
        value < 0 for value in normalized_costs
    ):
        raise ResearchWorkbenchError("R93R cost_bps_per_side必须包含0且均为非负整数")
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("R93R min_sample_size必须大于0")
    if not 0 < fdr_level < 1:
        raise ResearchWorkbenchError("R93R fdr_level必须位于0和1之间")
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("R93R dead_zone_bps不能为负")
    return normalized_horizons, normalized_costs


def _resolve_inputs(**paths: Path | None) -> dict[str, Path]:
    patterns = {
        "r93n_label_path": (
            "futures_option_dynamic_wall",
            "CF_*_futures_option_dynamic_wall_lifecycle_label_daily.parquet",
            "R93N lifecycle label",
        ),
        "r93o_evidence_path": (
            "futures_option_wall_factor_v2",
            "CF_*_futures_option_wall_factor_v2_candidate_evidence.parquet",
            "R93O candidate evidence",
        ),
        "r93o_posterior_path": (
            "futures_option_wall_factor_v2",
            "CF_*_futures_option_wall_factor_v2_posterior_label.parquet",
            "R93O posterior label",
        ),
        "r93p_summary_path": (
            "futures_option_event_path",
            "CF_*_futures_option_event_path_summary_by_event_type.parquet",
            "R93P event summary",
        ),
        "r93p_resolution_path": (
            "futures_option_event_path",
            "CF_*_futures_option_event_path_resolution_timing.parquet",
            "R93P resolution timing",
        ),
        "r93p_oos_path": (
            "futures_option_event_path",
            "CF_*_futures_option_event_path_purged_leave_one_year_out.parquet",
            "R93P purged leave-one-year-out",
        ),
        "r93q_main_effect_path": (
            "futures_option_regime_interaction",
            "CF_*_futures_option_regime_interaction_stage_main_effect.parquet",
            "R93Q stage main effect",
        ),
        "r93q_primary_path": (
            "futures_option_regime_interaction",
            "CF_*_futures_option_regime_interaction_primary_interaction.parquet",
            "R93Q primary interaction",
        ),
    }
    resolved: dict[str, Path] = {}
    for argument, (subdir, pattern, label) in patterns.items():
        value = paths.get(argument)
        key = (
            "r93q_main"
            if argument == "r93q_main_effect_path"
            else argument.removesuffix("_path")
        )
        resolved[key] = value or latest_matching_path(
            data_dir() / "research" / PRODUCT_CODE / subdir,
            pattern,
            label=label,
        )
    return resolved


def _load_posterior_table(
    path: Path, *, required: set[str], label: str
) -> pd.DataFrame:
    frame = load_table(path, required=required, label=label).copy()
    for column in ("trade_date", "execution_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    available = frame.loc[frame["forward_label_available"].fillna(False)].copy()
    if available.empty:
        raise ResearchWorkbenchError(f"{label}没有可用历史后验标签")
    if not available["t_plus_one_execution"].fillna(False).all():
        raise ResearchWorkbenchError(f"{label}违反T+1执行约束")
    if not available["forward_returns_are_historical_posterior_labels"].fillna(
        False
    ).all():
        raise ResearchWorkbenchError(f"{label}缺少历史后验标签边界")
    invalid_execution = available["execution_date"].le(available["trade_date"])
    invalid_exit = available["exit_date"].le(available["execution_date"])
    if invalid_execution.any() or invalid_exit.any():
        raise ResearchWorkbenchError(f"{label}违反T+1执行或退出日期约束")
    return frame.dropna(subset=["trade_date"])


def _load_historical_summary(
    path: Path, *, required: set[str], label: str
) -> pd.DataFrame:
    frame = load_table(path, required=required, label=label).copy()
    if not frame["forward_returns_are_historical_posterior_labels"].fillna(
        False
    ).all():
        raise ResearchWorkbenchError(f"{label}缺少历史后验标签边界")
    return frame


def _build_cost_sensitivity(
    *,
    labels: pd.DataFrame,
    candidate_labels: pd.DataFrame,
    costs: tuple[int, ...],
    dead_zone_bps: int,
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    model_specs = (
        (
            "FUTURES_BASELINE",
            "FUTURES_ONLY",
            "futures_directional_return",
        ),
        ("R48", "R48_OPTION_FACTOR", "r48_directional_return"),
        ("R93N", "R93N_DYNAMIC_WALL", "dynamic_directional_return"),
    )
    available = labels.loc[labels["forward_label_available"].fillna(False)].copy()
    for source_module, evidence_id, return_column in model_specs:
        for stage in ("ALL", MATURE_STAGE):
            stage_rows = (
                available
                if stage == "ALL"
                else available.loc[available["option_market_stage"].eq(stage)]
            )
            for horizon, group in stage_rows.groupby("horizon", sort=True):
                values = pd.to_numeric(group[return_column], errors="coerce").dropna()
                rows.extend(
                    _cost_rows_for_values(
                        run_id=run_id,
                        source_module=source_module,
                        evidence_id=evidence_id,
                        evidence_object_type="MODEL_BASELINE",
                        horizon=int(horizon),
                        market_stage=stage,
                        values=values,
                        costs=costs,
                        dead_zone_bps=dead_zone_bps,
                    )
                )

    candidate_available = candidate_labels.loc[
        candidate_labels["forward_label_available"].fillna(False)
        & candidate_labels["signal_active"].fillna(False)
        & candidate_labels["option_market_stage"].eq(MATURE_STAGE)
    ].copy()
    for (candidate_id, candidate_family, horizon), group in candidate_available.groupby(
        ["candidate_id", "candidate_family", "horizon"], sort=True
    ):
        values = pd.to_numeric(
            group["candidate_directional_return"], errors="coerce"
        ).dropna()
        rows.extend(
            _cost_rows_for_values(
                run_id=run_id,
                source_module="R93O",
                evidence_id=str(candidate_id),
                evidence_object_type=str(candidate_family),
                horizon=int(horizon),
                market_stage=MATURE_STAGE,
                values=values,
                costs=costs,
                dead_zone_bps=dead_zone_bps,
            )
        )
    return pd.DataFrame(rows).sort_values(
        ["source_module", "evidence_id", "market_stage", "horizon", "cost_bps_per_side"]
    ).reset_index(drop=True)


def _cost_rows_for_values(
    *,
    run_id: str,
    source_module: str,
    evidence_id: str,
    evidence_object_type: str,
    horizon: int,
    market_stage: str,
    values: pd.Series,
    costs: tuple[int, ...],
    dead_zone_bps: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    gross_mean = _mean(values)
    gross_median = _median(values)
    for cost in costs:
        round_trip_cost = 2.0 * cost / 10000.0
        net = values - round_trip_cost
        rows.append(
            {
                "run_id": run_id,
                "source_module": source_module,
                "evidence_id": evidence_id,
                "evidence_object_type": evidence_object_type,
                "horizon": horizon,
                "market_stage": market_stage,
                "sample_count": len(values),
                "cost_bps_per_side": cost,
                "round_trip_cost_bps": cost * 2,
                "gross_mean_directional_return": gross_mean,
                "gross_median_directional_return": gross_median,
                "net_mean_directional_return": _mean(net),
                "net_median_directional_return": _median(net),
                "net_hit_rate_after_dead_zone": _bool_mean(
                    net.gt(dead_zone_bps / 10000.0)
                ),
                "conservative_cost_survives": bool(
                    len(values) and _mean(net) is not None and _mean(net) > 0
                ),
                "cost_interpretation": (
                    "每个历史事件按入场、退出各扣一次单边bps；"
                    "不是基于真实换手的策略回测。"
                ),
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return rows


def _build_model_evidence(
    *,
    labels: pd.DataFrame,
    cost_sensitivity: pd.DataFrame,
    min_sample_size: int,
    run_id: str,
) -> pd.DataFrame:
    specs = (
        (
            "FUTURES_BASELINE",
            "FUTURES_ONLY",
            "futures_direction",
            "futures_directional_return",
            "futures_hit",
            None,
        ),
        (
            "R48",
            "R48_OPTION_FACTOR",
            "r48_option_direction",
            "r48_directional_return",
            "r48_hit",
            "futures_directional_return",
        ),
        (
            "R93N",
            "R93N_DYNAMIC_WALL",
            "dynamic_option_direction",
            "dynamic_directional_return",
            "dynamic_hit",
            "r48_directional_return",
        ),
    )
    mature = labels.loc[
        labels["forward_label_available"].fillna(False)
        & labels["option_market_stage"].eq(MATURE_STAGE)
    ].copy()
    rows: list[dict[str, object]] = []
    conservative_cost = int(cost_sensitivity["cost_bps_per_side"].max())
    for source, evidence_id, direction_col, return_col, hit_col, comparator_col in specs:
        for horizon, group in mature.groupby("horizon", sort=True):
            active = group.loc[
                group[direction_col].astype(str).str.lower().isin({"long", "short"})
            ].copy()
            returns = pd.to_numeric(active[return_col], errors="coerce")
            valid = active.loc[returns.notna()].copy()
            returns = pd.to_numeric(valid[return_col], errors="coerce")
            hit = valid[hit_col].dropna().astype(bool)
            incremental = None
            comparator = "NONE_REFERENCE"
            if comparator_col is not None and not valid.empty:
                comparator_values = pd.to_numeric(
                    valid[comparator_col], errors="coerce"
                )
                matched = returns.notna() & comparator_values.notna()
                if matched.any():
                    incremental = float(
                        (returns.loc[matched] - comparator_values.loc[matched]).mean()
                    )
                comparator = (
                    "FUTURES_ONLY"
                    if source == "R48"
                    else "R48_OPTION_FACTOR"
                )
            conservative_net = _cost_value(
                cost_sensitivity,
                source_module=source,
                evidence_id=evidence_id,
                horizon=int(horizon),
                market_stage=MATURE_STAGE,
                cost_bps=conservative_cost,
            )
            annual_status, annual_years, annual_positive = _annual_stability(
                valid,
                return_column=return_col,
            )
            if source == "FUTURES_BASELINE":
                decision = "KEEP"
                reason = "REFERENCE_BASELINE_NOT_PROMOTION_CANDIDATE"
                scope = "REFERENCE_BASELINE"
            elif (
                len(valid) >= min_sample_size
                and incremental is not None
                and incremental > 0
                and conservative_net is not None
                and conservative_net > 0
            ):
                decision = "WATCH"
                reason = "POSITIVE_INCREMENT_BUT_NO_FIXED_FDR_OOS_PROMOTION_GATE"
                scope = "MODEL_INCREMENT"
            else:
                decision = "REJECT"
                reason = "NO_COST_SURVIVING_FIXED_INCREMENT"
                scope = "MODEL_INCREMENT"
            mfe, mae = _directional_excursion(valid, direction_col)
            rows.append(
                _evidence_row(
                    run_id=run_id,
                    evidence_id=evidence_id,
                    source_module=source,
                    evidence_object_type="MODEL_BASELINE",
                    candidate_family="MODEL_BASELINE",
                    horizon=int(horizon),
                    market_stage=MATURE_STAGE,
                    decision_scope=scope,
                    comparator=comparator,
                    sample_count=len(valid),
                    hit_rate=_bool_mean(hit),
                    mean_return=_mean(returns),
                    median_return=_median(returns),
                    mean_mfe=mfe,
                    mean_mae=mae,
                    mean_resolution=None,
                    fdr_q_value=None,
                    oos_test_years=annual_years,
                    oos_support_years=annual_positive,
                    oos_contradict_years=max(annual_years - annual_positive, 0),
                    oos_stability_status=annual_status,
                    primary_incremental=incremental,
                    conservative_net=conservative_net,
                    upstream_status="REFERENCE" if source == "FUTURES_BASELINE" else "FIXED_MODEL",
                    decision=decision,
                    decision_reason=reason,
                    predictive_promotion_eligible=False,
                    retention_role=(
                        "CORE_BASELINE"
                        if source == "FUTURES_BASELINE"
                        else "EXPLANATORY_OPTION_MODEL"
                    ),
                    metrics_comparable=True,
                )
            )
    return pd.DataFrame(rows)


def _build_r93o_evidence(
    *,
    evidence: pd.DataFrame,
    cost_sensitivity: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
    run_id: str,
) -> pd.DataFrame:
    mature = evidence.loc[evidence["option_market_stage"].eq(MATURE_STAGE)].copy()
    if mature.empty:
        raise ResearchWorkbenchError("R93O evidence缺少MATURE_ACTIVE固定候选")
    conservative_cost = int(cost_sensitivity["cost_bps_per_side"].max())
    rows: list[dict[str, object]] = []
    for row in mature.itertuples(index=False):
        upstream = str(row.decision).upper()
        if upstream not in DECISIONS:
            raise ResearchWorkbenchError(f"R93O未知裁决状态: {upstream}")
        conservative_net = _cost_value(
            cost_sensitivity,
            source_module="R93O",
            evidence_id=str(row.candidate_id),
            horizon=int(row.horizon),
            market_stage=MATURE_STAGE,
            cost_bps=conservative_cost,
        )
        sample_ok = int(row.candidate_sample_count) >= min_sample_size
        fdr_ok = _number(row.fdr_q_value) is not None and float(row.fdr_q_value) <= fdr_level
        oos_ok = bool(row.oos_non_partial_positive) and int(row.oos_positive_years) > 0
        increment_ok = (
            _number(row.primary_incremental_mean_return) is not None
            and float(row.primary_incremental_mean_return) > 0
        )
        cost_ok = conservative_net is not None and conservative_net > 0
        if upstream == "KEEP" and sample_ok and fdr_ok and oos_ok and increment_ok and cost_ok:
            decision = "KEEP"
            reason = "ALL_FIXED_MATURE_FDR_OOS_COST_GATES_PASS"
            eligible = True
        elif upstream in {"KEEP", "WATCH"} and sample_ok and increment_ok and cost_ok:
            decision = "WATCH"
            failed = []
            if not fdr_ok:
                failed.append("FDR")
            if not oos_ok:
                failed.append("OOS")
            if upstream != "KEEP":
                failed.append("UPSTREAM_PROMOTION")
            reason = "GATE_INCOMPLETE_" + "_".join(failed or ["UNSPECIFIED"])
            eligible = False
        else:
            decision = "REJECT"
            failed = []
            if not sample_ok:
                failed.append("SMALL_SAMPLE")
            if not increment_ok:
                failed.append("NO_POSITIVE_INCREMENT")
            if not cost_ok:
                failed.append("CONSERVATIVE_COST_FAIL")
            if upstream == "REJECT":
                failed.append("UPSTREAM_REJECT")
            reason = "|".join(failed or [str(row.decision_reason)])
            eligible = False
        rows.append(
            _evidence_row(
                run_id=run_id,
                evidence_id=str(row.candidate_id),
                source_module="R93O",
                evidence_object_type="FIXED_FACTOR_CANDIDATE",
                candidate_family=str(row.candidate_family),
                horizon=int(row.horizon),
                market_stage=MATURE_STAGE,
                decision_scope="PREDICTIVE_INCREMENT",
                comparator=str(row.comparison_mode),
                sample_count=int(row.candidate_sample_count),
                hit_rate=_number(row.candidate_hit_rate),
                mean_return=_number(row.candidate_mean_directional_return),
                median_return=_number(row.candidate_median_directional_return),
                mean_mfe=_number(row.candidate_mean_mfe),
                mean_mae=_number(row.candidate_mean_mae),
                mean_resolution=None,
                fdr_q_value=_number(row.fdr_q_value),
                oos_test_years=int(row.oos_test_years),
                oos_support_years=int(row.oos_positive_years),
                oos_contradict_years=max(
                    int(row.oos_test_years) - int(row.oos_positive_years), 0
                ),
                oos_stability_status=(
                    "OOS_NON_PARTIAL_POSITIVE"
                    if bool(row.oos_non_partial_positive)
                    else "OOS_NOT_STABLE"
                ),
                primary_incremental=_number(row.primary_incremental_mean_return),
                conservative_net=conservative_net,
                upstream_status=upstream,
                decision=decision,
                decision_reason=reason,
                predictive_promotion_eligible=eligible,
                retention_role="FROZEN_PRE_REGISTERED_CANDIDATE",
                metrics_comparable=True,
            )
        )
    return pd.DataFrame(rows)


def _build_r93p_evidence(
    *,
    summary: pd.DataFrame,
    resolution: pd.DataFrame,
    oos: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
    run_id: str,
) -> pd.DataFrame:
    resolution_metrics = _aggregate_resolution(resolution)
    rows: list[dict[str, object]] = []
    for row in summary.itertuples(index=False):
        key = (str(row.event_family), str(row.event_type))
        resolution_row = resolution_metrics.get(key, {})
        oos_rows = oos.loc[
            oos["event_family"].astype(str).eq(key[0])
            & oos["event_type"].astype(str).eq(key[1])
            & oos["horizon"].eq(int(row.horizon))
            & ~oos["test_year_is_partial"].fillna(False)
        ].copy()
        support = int(oos_rows["oos_status"].astype(str).eq("SUPPORT").sum())
        contradict = int(oos_rows["oos_status"].astype(str).eq("CONTRADICT").sum())
        upstream = str(row.predictive_evidence_status)
        watch_like = "WATCH" in upstream or upstream.startswith("READY_")
        fdr_ok = _number(row.fdr_q_value) is not None and float(row.fdr_q_value) <= fdr_level
        sample_ok = int(row.directional_count) >= min_sample_size
        return_ok = (
            _number(row.mean_directional_return) is not None
            and float(row.mean_directional_return) > 0
        )
        oos_ok = support > 0 and contradict == 0
        if watch_like and sample_ok and fdr_ok and return_ok and oos_ok:
            decision = "WATCH"
            reason = "EVENT_PATH_EVIDENCE_REQUIRES_EXPLICIT_STRATEGY_RULE"
        else:
            decision = "REJECT"
            reason = "NO_STABLE_PREDICTIVE_EVENT_PATH"
        rows.append(
            _evidence_row(
                run_id=run_id,
                evidence_id=f"{row.event_type}_{int(row.horizon)}D",
                source_module="R93P",
                evidence_object_type="EVENT_PATH",
                candidate_family=str(row.event_family),
                horizon=int(row.horizon),
                market_stage="ALL",
                decision_scope="EVENT_PREDICTIVE_SCREEN",
                comparator="EVENT_CONTINUATION_VS_REVERSAL",
                sample_count=int(row.directional_count),
                hit_rate=_number(row.continuation_rate),
                mean_return=_number(row.mean_directional_return),
                median_return=_number(row.median_directional_return),
                mean_mfe=_number(row.mean_mfe),
                mean_mae=_number(row.mean_mae),
                mean_resolution=_number(
                    resolution_row.get("mean_first_resolution_horizon")
                ),
                fdr_q_value=_number(row.fdr_q_value),
                oos_test_years=len(oos_rows),
                oos_support_years=support,
                oos_contradict_years=contradict,
                oos_stability_status=(
                    "OOS_SUPPORT_ALL"
                    if len(oos_rows) and support == len(oos_rows)
                    else "OOS_MIXED_OR_INCOMPLETE"
                ),
                primary_incremental=None,
                conservative_net=None,
                upstream_status=upstream,
                decision=decision,
                decision_reason=reason,
                predictive_promotion_eligible=False,
                retention_role="EXPLANATORY_EVENT_LIFECYCLE",
                metrics_comparable=False,
            )
        )
    return pd.DataFrame(rows)


def _build_r93q_evidence(
    *,
    primary: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
    run_id: str,
) -> pd.DataFrame:
    mature = primary.loc[primary["market_stage"].eq(MATURE_STAGE)].copy()
    rows: list[dict[str, object]] = []
    for row in mature.itertuples(index=False):
        sample_ok = (
            int(row.target_stage_level_sample_count) >= min_sample_size
            and int(row.target_stage_control_sample_count) >= min_sample_size
        )
        fisher_q = _number(row.fisher_fdr_q_value)
        permutation_q = _number(row.permutation_fdr_q_value)
        fdr_q = max(
            value for value in (fisher_q, permutation_q) if value is not None
        ) if any(value is not None for value in (fisher_q, permutation_q)) else None
        fdr_ok = fdr_q is not None and fdr_q <= fdr_level
        increment = _number(row.interaction_delta_mean_return)
        increment_ok = increment is not None and increment > 0
        oos_ok = int(row.oos_support_count) > 0 and int(row.oos_contradict_count) == 0
        upstream = str(row.evidence_status)
        ready_like = upstream.startswith("READY_")
        if ready_like and sample_ok and fdr_ok and increment_ok and oos_ok:
            # 交互单元还不是可执行的固定候选，最多保留为下一轮预注册观察。
            decision = "WATCH"
            reason = "STABLE_INTERACTION_REQUIRES_FIXED_RULE_AND_COST_TEST"
            eligible = False
        elif (
            (ready_like or "WATCH" in upstream)
            and sample_ok
            and increment_ok
        ):
            decision = "WATCH"
            reason = "INTERACTION_GATE_INCOMPLETE"
            eligible = False
        else:
            decision = "REJECT"
            reason = "NO_STABLE_MATURE_INTERACTION"
            eligible = False
        rows.append(
            _evidence_row(
                run_id=run_id,
                evidence_id=str(row.interaction_id),
                source_module="R93Q",
                evidence_object_type="MARKET_STAGE_INTERACTION",
                candidate_family=f"{row.base_value}:{row.interaction_dimension}",
                horizon=int(row.horizon),
                market_stage=MATURE_STAGE,
                decision_scope="PRE_REGISTERED_STAGE_INTERACTION",
                comparator=str(row.interaction_level),
                sample_count=int(row.target_stage_level_sample_count),
                hit_rate=_number(row.target_stage_level_hit_rate),
                mean_return=_number(row.target_stage_level_mean_directional_return),
                median_return=_number(row.target_stage_level_median_directional_return),
                mean_mfe=None,
                mean_mae=None,
                mean_resolution=None,
                fdr_q_value=fdr_q,
                oos_test_years=int(row.annual_comparable_years),
                oos_support_years=int(row.oos_support_count),
                oos_contradict_years=int(row.oos_contradict_count),
                oos_stability_status=(
                    "OOS_SUPPORT_NO_CONTRADICTION"
                    if oos_ok
                    else "OOS_MIXED_OR_INCOMPLETE"
                ),
                primary_incremental=increment,
                conservative_net=None,
                upstream_status=upstream,
                decision=decision,
                decision_reason=reason,
                predictive_promotion_eligible=eligible,
                retention_role="EXPLANATORY_STAGE_INTERACTION",
                metrics_comparable=False,
            )
        )
    return pd.DataFrame(rows)


def _evidence_row(
    *,
    run_id: str,
    evidence_id: str,
    source_module: str,
    evidence_object_type: str,
    candidate_family: str,
    horizon: int,
    market_stage: str,
    decision_scope: str,
    comparator: str,
    sample_count: int,
    hit_rate: float | None,
    mean_return: float | None,
    median_return: float | None,
    mean_mfe: float | None,
    mean_mae: float | None,
    mean_resolution: float | None,
    fdr_q_value: float | None,
    oos_test_years: int,
    oos_support_years: int,
    oos_contradict_years: int,
    oos_stability_status: str,
    primary_incremental: float | None,
    conservative_net: float | None,
    upstream_status: str,
    decision: str,
    decision_reason: str,
    predictive_promotion_eligible: bool,
    retention_role: str,
    metrics_comparable: bool,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "evidence_id": evidence_id,
        "source_module": source_module,
        "evidence_object_type": evidence_object_type,
        "candidate_family": candidate_family,
        "horizon": horizon,
        "market_stage": market_stage,
        "decision_scope": decision_scope,
        "comparator": comparator,
        "sample_count": sample_count,
        "hit_rate": hit_rate,
        "mean_directional_return": mean_return,
        "median_directional_return": median_return,
        "mean_mfe": mean_mfe,
        "mean_mae": mean_mae,
        "mean_resolution_session": mean_resolution,
        "fdr_q_value": fdr_q_value,
        "oos_test_years": oos_test_years,
        "oos_support_years": oos_support_years,
        "oos_contradict_years": oos_contradict_years,
        "oos_stability_status": oos_stability_status,
        "primary_incremental_mean_return": primary_incremental,
        "conservative_cost_net_mean_return": conservative_net,
        "upstream_status": upstream_status,
        "decision": decision,
        "decision_reason": decision_reason,
        "predictive_promotion_eligible": predictive_promotion_eligible,
        "retention_role": retention_role,
        "metrics_comparable_to_futures_baseline": metrics_comparable,
        "forward_returns_are_historical_posterior_labels": True,
        "enters_signal_matrix": False,
        "enters_composite_score": False,
        "changes_strategy_direction_or_sizing": False,
        "trading_instruction": "not_a_trading_instruction",
    }


def _build_module_summary(
    *,
    evidence: pd.DataFrame,
    r93q_main: pd.DataFrame,
    stop_expansion: bool,
    run_id: str,
) -> pd.DataFrame:
    retention = {
        "FUTURES_BASELINE": ("KEEP", "核心期货基准继续保留。"),
        "R48": ("KEEP", "保留基础期权proxy作为解释上下文，不直接晋级。"),
        "R93N": ("KEEP", "保留动态墙与事件数据结构，不作为已验证方向因子。"),
        "R93O": ("REJECT", "停止本轮固定期权墙因子扩张和阈值深挖。"),
        "R93P": ("KEEP", "保留事件生命周期和解决节奏解释框架。"),
        "R93Q": ("KEEP", "保留市场成熟度与阶段交互的反证框架。"),
    }
    rows: list[dict[str, object]] = []
    for module, group in evidence.groupby("source_module", sort=False):
        counts = group["decision"].value_counts().to_dict()
        predictive_decision = (
            "KEEP"
            if counts.get("KEEP", 0) and module != "FUTURES_BASELINE"
            else "WATCH"
            if counts.get("WATCH", 0)
            else "KEEP"
            if module == "FUTURES_BASELINE"
            else "REJECT"
        )
        retain_decision, retain_reason = retention[module]
        rows.append(
            {
                "run_id": run_id,
                "source_module": module,
                "evidence_row_count": len(group),
                "distinct_evidence_count": group["evidence_id"].nunique(),
                "keep_count": int(counts.get("KEEP", 0)),
                "watch_count": int(counts.get("WATCH", 0)),
                "reject_count": int(counts.get("REJECT", 0)),
                "sample_count_min": int(group["sample_count"].min()),
                "sample_count_max": int(group["sample_count"].max()),
                "best_mean_directional_return": _max_number(
                    group["mean_directional_return"]
                ),
                "best_primary_incremental_mean_return": _max_number(
                    group["primary_incremental_mean_return"]
                ),
                "predictive_decision": predictive_decision,
                "retention_decision": retain_decision,
                "retention_reason": retain_reason,
                "stop_new_factor_expansion": bool(
                    stop_expansion and module in {"R93O", "R93Q"}
                ),
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    if not r93q_main.empty:
        r93q_index = next(
            (index for index, row in enumerate(rows) if row["source_module"] == "R93Q"),
            None,
        )
        if r93q_index is not None:
            rows[r93q_index]["stage_main_effect_count"] = len(r93q_main)
            rows[r93q_index]["stable_stage_main_effect_count"] = int(
                r93q_main["evidence_status"].astype(str).str.startswith("READY_").sum()
            )
    return pd.DataFrame(rows)


def _build_warnings(
    *,
    run_id: str,
    evidence: pd.DataFrame,
    stop_expansion: bool,
) -> list[FuturesOptionEvidenceGateWarningRecord]:
    warnings = [
        FuturesOptionEvidenceGateWarningRecord(
            run_id=run_id,
            section="cost_sensitivity",
            severity=INFO,
            warning_code="EVENT_COST_PROXY_ONLY",
            warning_message=(
                "0/5/10bps按每个历史事件入场和退出各扣一次，只是研究摩擦代理；"
                "没有成交、换手和持仓路径时不能解释为策略净值。"
            ),
            affected_count=int(evidence["conservative_cost_net_mean_return"].notna().sum()),
            human_review_required="event_cost_is_round_trip_bps_proxy_not_execution_backtest",
        ),
        FuturesOptionEvidenceGateWarningRecord(
            run_id=run_id,
            section="evidence_comparability",
            severity=INFO,
            warning_code="EVENT_AND_MODEL_SAMPLES_NOT_POOLED",
            warning_message=(
                "R93P事件路径和R93Q交互episode与逐日模型样本不可直接合并排名，"
                "统一表保留了可比性标记。"
            ),
            affected_count=int(
                (~evidence["metrics_comparable_to_futures_baseline"]).sum()
            ),
            human_review_required="explanatory_retention_is_not_predictive_promotion",
        ),
    ]
    if stop_expansion:
        warnings.append(
            FuturesOptionEvidenceGateWarningRecord(
                run_id=run_id,
                section="expansion_gate",
                severity=WARN,
                warning_code="NO_PROMOTABLE_OPTION_CANDIDATE",
                warning_message=(
                    "没有固定候选同时通过成熟活跃期、FDR、留一年和保守成本门槛；"
                    "停止本轮CF期权因子扩张，保留解释性结构研究。"
                ),
                affected_count=int(
                    evidence.loc[
                        ~evidence["decision_scope"].eq("REFERENCE_BASELINE")
                    ]["evidence_id"].nunique()
                ),
                human_review_required="fdr_and_leave_one_year_out_interpretation",
            )
        )
    return warnings


def _aggregate_resolution(
    resolution: pd.DataFrame,
) -> dict[tuple[str, str], dict[str, float | None]]:
    output: dict[tuple[str, str], dict[str, float | None]] = {}
    for key, group in resolution.groupby(["event_family", "event_type"], sort=False):
        weights = pd.to_numeric(group["available_path_count"], errors="coerce").fillna(0.0)
        means = pd.to_numeric(
            group["mean_first_resolution_horizon"], errors="coerce"
        )
        valid = means.notna() & weights.gt(0)
        weighted_mean = (
            float(np.average(means.loc[valid], weights=weights.loc[valid]))
            if valid.any()
            else None
        )
        output[(str(key[0]), str(key[1]))] = {
            "mean_first_resolution_horizon": weighted_mean,
        }
    return output


def _annual_stability(
    frame: pd.DataFrame, *, return_column: str
) -> tuple[str, int, int]:
    if frame.empty:
        return "NO_ANNUAL_SAMPLE", 0, 0
    max_year = int(pd.to_numeric(frame["calendar_year"], errors="coerce").max())
    # 最新年份按YTD展示，不冒充完整年度稳定性。
    full = frame.loc[pd.to_numeric(frame["calendar_year"], errors="coerce").lt(max_year)]
    means = (
        full.assign(_return=pd.to_numeric(full[return_column], errors="coerce"))
        .dropna(subset=["_return"])
        .groupby("calendar_year")["_return"]
        .mean()
    )
    years = len(means)
    positive = int(means.gt(0).sum())
    if years == 0:
        status = "NO_COMPLETE_YEAR"
    elif positive == years:
        status = "ANNUAL_ALL_POSITIVE_NO_FORMAL_LOO"
    elif positive == 0:
        status = "ANNUAL_ALL_NON_POSITIVE"
    else:
        status = "ANNUAL_MIXED"
    return status, years, positive


def _directional_excursion(
    frame: pd.DataFrame, direction_column: str
) -> tuple[float | None, float | None]:
    if frame.empty:
        return None, None
    direction = frame[direction_column].astype(str).str.lower()
    mfe = pd.Series(
        np.where(
            direction.eq("long"),
            pd.to_numeric(frame["long_mfe"], errors="coerce"),
            pd.to_numeric(frame["short_mfe"], errors="coerce"),
        ),
        index=frame.index,
        dtype="float64",
    )
    mae = pd.Series(
        np.where(
            direction.eq("long"),
            pd.to_numeric(frame["long_mae"], errors="coerce"),
            pd.to_numeric(frame["short_mae"], errors="coerce"),
        ),
        index=frame.index,
        dtype="float64",
    )
    return _mean(mfe), _mean(mae)


def _cost_value(
    costs: pd.DataFrame,
    *,
    source_module: str,
    evidence_id: str,
    horizon: int,
    market_stage: str,
    cost_bps: int,
) -> float | None:
    match = costs.loc[
        costs["source_module"].eq(source_module)
        & costs["evidence_id"].eq(evidence_id)
        & costs["horizon"].eq(horizon)
        & costs["market_stage"].eq(market_stage)
        & costs["cost_bps_per_side"].eq(cost_bps)
    ]
    if match.empty:
        return None
    return _number(match.iloc[0]["net_mean_directional_return"])


def _build_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    data_root = output_dir or (
        data_dir() / "research" / PRODUCT_CODE / "futures_option_evidence_gate"
    )
    report_root = report_output_dir or (
        reports_dir() / "research" / "futures_option_evidence_gate"
    )
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_futures_option_evidence_gate"
    return {
        "evidence_parquet": data_root / f"{stem}_decision_register.parquet",
        "evidence_csv": data_root / f"{stem}_decision_register.csv",
        "module_summary_parquet": data_root / f"{stem}_module_summary.parquet",
        "module_summary_csv": data_root / f"{stem}_module_summary.csv",
        "cost_sensitivity_parquet": data_root / f"{stem}_cost_sensitivity.parquet",
        "cost_sensitivity_csv": data_root / f"{stem}_cost_sensitivity.csv",
        "warning_csv": report_root / f"{stem}_warnings.csv",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
        "manifest": report_root / f"{stem}_manifest.json",
    }


def _write_markdown(
    *,
    result: ResearchFuturesOptionEvidenceGateResult,
    evidence: pd.DataFrame,
    modules: pd.DataFrame,
    costs: pd.DataFrame,
    r93q_main: pd.DataFrame,
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    model_rows = evidence.loc[
        evidence["source_module"].isin({"FUTURES_BASELINE", "R48", "R93N"})
    ].copy()
    r93o_rows = evidence.loc[evidence["source_module"].eq("R93O")].copy()
    r93p_rows = evidence.loc[evidence["source_module"].eq("R93P")].copy()
    r93q_rows = evidence.loc[evidence["source_module"].eq("R93Q")].copy()
    conservative_cost = int(costs["cost_bps_per_side"].max())
    cost_view = costs.loc[
        costs["market_stage"].eq(MATURE_STAGE)
        & costs["cost_bps_per_side"].eq(conservative_cost)
        & costs["source_module"].isin({"FUTURES_BASELINE", "R48", "R93N"})
    ].copy()
    lines = [
        "# CF期货-期权统一证据门控与停止决策",
        "",
        f"- 数据区间：`{result.start.isoformat()}` 至 `{result.end.isoformat()}`",
        f"- 运行编号：`{result.run_id}`",
        f"- 扩张裁决：`{result.expansion_decision}`",
        f"- 可晋级固定候选：`{result.promotable_candidate_count}`",
        (
            f"- KEEP拆分：参考基准`{result.reference_keep_count}`，"
            f"预测候选`{result.predictive_keep_count}`。"
        ),
        "- 本报告只汇总冻结证据，不重新搜索阈值，不修改方向和仓位。",
        "",
        "## 先说结论",
        "",
    ]
    if result.stop_option_factor_expansion:
        lines.extend(
            [
                "- 没有期权候选同时通过成熟活跃期、FDR、留一年和保守成本门槛。",
                "- 本轮CF期权因子扩张停止；R48、R93N、R93P和R93Q保留为解释性结构研究。",
                "- 这不是期权数据无价值，而是尚未证明其能稳定增加期货方向预测收益。",
                "- `R94-R99`未解锁，棕榈油P的独立P0评估不受本裁决自动授权。",
            ]
        )
    else:
        lines.append("- 至少一个固定候选通过门槛，仅允许进入固定规则复核，不自动进入信号。")
    lines.extend(
        [
            "",
            "## 统一口径",
            "",
            "- 期货基准、R48和R93N使用同一R93N T+1历史后验标签。",
            "- R93O只使用真实运行前已经固定的16个候选；R93R只能维持或降级上游裁决。",
            "- R93P事件路径和R93Q交互episode不是逐日模型样本，因此不与期货基准直接拼接排名。",
            f"- 成本敏感性为单边0/5/{conservative_cost}bps；每个事件按入场和退出各扣一次。",
            "",
            "## 同口径模型基准",
            "",
            "| 模型 | 周期 | 样本 | 命中率 | 平均方向收益 | MFE | MAE | 保守成本后 | 裁决 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in model_rows.itertuples(index=False):
        lines.append(
            "| "
            f"{row.evidence_id} | {row.horizon}D | {row.sample_count} | "
            f"{fmt_percent(row.hit_rate)} | {fmt_percent(row.mean_directional_return)} | "
            f"{fmt_percent(row.mean_mfe)} | {fmt_percent(row.mean_mae)} | "
            f"{fmt_percent(row.conservative_cost_net_mean_return)} | {row.decision} |"
        )
    r93o_counts = r93o_rows["decision"].value_counts().to_dict()
    r93p_counts = r93p_rows["decision"].value_counts().to_dict()
    r93q_counts = r93q_rows["decision"].value_counts().to_dict()
    lines.extend(
        [
            "",
            "## R93O固定候选门控",
            "",
            f"- 固定候选证据行：`{len(r93o_rows)}`。",
            (
                f"- `KEEP={r93o_counts.get('KEEP', 0)}` / "
                f"`WATCH={r93o_counts.get('WATCH', 0)}` / "
                f"`REJECT={r93o_counts.get('REJECT', 0)}`。"
            ),
            "- WATCH只表示仍有描述性正增量但门槛不完整，不代表可以写入信号或仓位。",
            "",
            "| 候选 | 周期 | 样本 | 增量收益 | FDR q | OOS支持/测试 | 保守成本后 | 裁决 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    decision_order = {"KEEP": 0, "WATCH": 1, "REJECT": 2}
    r93o_display = (
        r93o_rows.assign(_decision_order=r93o_rows["decision"].map(decision_order))
        .sort_values(
            ["_decision_order", "primary_incremental_mean_return"],
            ascending=[True, False],
        )
        .head(20)
    )
    for row in r93o_display.itertuples(index=False):
        lines.append(
            "| "
            f"{row.evidence_id} | {row.horizon}D | {row.sample_count} | "
            f"{fmt_percent(row.primary_incremental_mean_return)} | "
            f"{fmt_number(row.fdr_q_value, 3)} | "
            f"{row.oos_support_years}/{row.oos_test_years} | "
            f"{fmt_percent(row.conservative_cost_net_mean_return)} | {row.decision} |"
        )
    lines.extend(
        [
            "",
            "## R93P事件路径",
            "",
            (
                f"- `KEEP={r93p_counts.get('KEEP', 0)}` / "
                f"`WATCH={r93p_counts.get('WATCH', 0)}` / "
                f"`REJECT={r93p_counts.get('REJECT', 0)}`。"
            ),
            "- MFE、MAE和解决周期可用于解释事件节奏；没有固定开平仓规则时，不计算策略净成本。",
            "",
            "| 事件 | 周期 | 样本 | 延续率 | 平均收益 | MFE | MAE | 平均解决检查点 | 裁决 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    r93p_display = r93p_rows.sort_values("sample_count", ascending=False).head(10)
    for row in r93p_display.itertuples(index=False):
        lines.append(
            f"| {row.evidence_id} | {row.horizon}D | {row.sample_count} | "
            f"{fmt_percent(row.hit_rate)} | {fmt_percent(row.mean_directional_return)} | "
            f"{fmt_percent(row.mean_mfe)} | {fmt_percent(row.mean_mae)} | "
            f"{fmt_number(row.mean_resolution_session, 2)} | {row.decision} |"
        )
    lines.extend(
        [
            "",
            "## R93Q阶段交互",
            "",
            f"- 成熟活跃期预注册交互：`{len(r93q_rows)}`。",
            (
                f"- `KEEP={r93q_counts.get('KEEP', 0)}` / "
                f"`WATCH={r93q_counts.get('WATCH', 0)}` / "
                f"`REJECT={r93q_counts.get('REJECT', 0)}`。"
            ),
            f"- 阶段主效应记录：`{len(r93q_main)}`，仅用于检验市场成熟度是否改变历史关系。",
            "",
            "## 模块保留决策",
            "",
            "| 模块 | 预测裁决 | 保留裁决 | 理由 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in modules.itertuples(index=False):
        lines.append(
            f"| {row.source_module} | {row.predictive_decision} | "
            f"{row.retention_decision} | {row.retention_reason} |"
        )
    lines.extend(
        [
            "",
            "## 保守成本检查",
            "",
            "| 对象 | 周期 | 样本 | 毛收益 | 往返成本 | 净收益 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in cost_view.itertuples(index=False):
        lines.append(
            f"| {row.evidence_id} | {row.horizon}D | {row.sample_count} | "
            f"{fmt_percent(row.gross_mean_directional_return)} | "
            f"{row.round_trip_cost_bps}bps | {fmt_percent(row.net_mean_directional_return)} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- forward return仅作为历史后验验证标签，不参与最新日信号生成。",
            "- 期权IV/Greek仍是研究proxy；公开持仓不能识别多空所有权或做市商Gamma。",
            "- 解释性框架的KEEP不等于预测候选KEEP；两者已在模块表中分列。",
            "- 未重新搜索阈值，未自动反转方向，未修改signal matrix、composite score或仓位。",
            "- 研究仿真、无未来函数，不构成交易指令；本报告没有真实资金NAV。",
            "- `HUMAN_REVIEW_REQUIRED`。",
            "",
        ]
    )
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.mean())


def _median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.median())


def _bool_mean(values: pd.Series) -> float | None:
    clean = values.dropna()
    return None if clean.empty else float(clean.astype(bool).mean())


def _max_number(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.max())
