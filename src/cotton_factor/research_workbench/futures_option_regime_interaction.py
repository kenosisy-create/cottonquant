"""R93Q 期货-期权市场阶段与结构情境交互研究。

本模块只消费 R93N 的 T 日事件/特征表与 R93P 的历史后验检查点。
它先把连续重复事件压缩为独立 episode，再检验市场阶段与合约周期、
到期桶、移仓上下文、棉花年度和趋势阶段之间是否存在稳定增量。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.cotton_year_policy import cotton_year_label
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
RULE_VERSION = "V5.1_R93Q_futures_option_regime_interaction_v1"
DEFAULT_HORIZONS = (1, 3, 5)
DEFAULT_EPISODE_GAP_SESSIONS = 1
DEFAULT_CHAIN_WINDOW_SESSIONS = 5
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_MIN_CELL_SIZE = 5
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_PERMUTATION_COUNT = 1000
DEFAULT_PURGE_GAP_SESSIONS = 5
DEFAULT_RANDOM_SEED = 93

INTERACTION_DIMENSIONS = (
    "contract_cycle",
    "expiry_bucket",
    "roll_context",
    "cotton_year",
    "trend_phase",
)
MARKET_STAGES = ("EARLY_THIN", "EXPANSION", "MATURE_ACTIVE")
POSTERIOR_COLUMNS = {
    "forward_return",
    "directional_return",
    "event_outcome",
    "event_hit",
    "event_mfe",
    "event_mae",
    "execution_date",
    "exit_date",
    "future_return",
    "fwd_ret",
}

HUMAN_REVIEW_REQUIRED = (
    "frozen_calendar_market_stage_boundaries",
    "episode_deduplication_and_chain_window",
    "contract_cycle_and_roll_context_interpretation",
    "option_expiry_bucket_interpretation",
    "option_open_interest_long_short_ownership_unknown",
    "option_iv_and_greek_are_research_proxies",
    "fundamental_observation_date_and_unit",
    "interaction_multiple_testing_and_fdr_interpretation",
    "purged_leave_one_year_out_interpretation",
)

RESEARCH_BOUNDARY = {
    "r93n_event_features_use_t_or_earlier": True,
    "r93p_forward_returns_are_historical_posterior_labels": True,
    "t_plus_one_execution": True,
    "episode_anchor_is_first_observable_event": True,
    "fundamental_and_policy_are_named_context_only": True,
    "calendar_stage_is_frozen_not_optimized": True,
    "post_hoc_threshold_search": False,
    "automatic_direction_reversal": False,
    "enters_signal_matrix": False,
    "enters_composite_score": False,
    "changes_strategy_direction_or_sizing": False,
    "promotion_eligible": False,
    "realtime_rule_eligible": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class FuturesOptionRegimeInteractionWarningRecord:
    """R93Q 数据、样本和解释边界告警。"""

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
class ResearchFuturesOptionRegimeInteractionResult:
    """R93Q 产物路径与核心计数。"""

    run_id: str
    start: date
    end: date
    status: str
    source_event_count: int
    episode_count: int
    episode_validation_count: int
    named_context_count: int
    main_effect_count: int
    primary_interaction_count: int
    exploratory_interaction_count: int
    annual_stability_count: int
    oos_count: int
    stable_interaction_count: int
    latest_episode_count: int
    warning_records: tuple[FuturesOptionRegimeInteractionWarningRecord, ...]
    event_path: Path
    checkpoint_path: Path
    path_path: Path
    feature_path: Path
    policy_context_path: Path | None
    fundamental_context_path: Path | None
    episode_feature_parquet_path: Path
    episode_feature_csv_path: Path
    episode_validation_parquet_path: Path
    episode_validation_csv_path: Path
    named_context_parquet_path: Path
    named_context_csv_path: Path
    main_effect_parquet_path: Path
    main_effect_csv_path: Path
    primary_interaction_parquet_path: Path
    primary_interaction_csv_path: Path
    exploratory_interaction_parquet_path: Path
    exploratory_interaction_csv_path: Path
    annual_stability_parquet_path: Path
    annual_stability_csv_path: Path
    oos_parquet_path: Path
    oos_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "WARN" for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "status": self.status,
            "source_event_count": self.source_event_count,
            "episode_count": self.episode_count,
            "episode_validation_count": self.episode_validation_count,
            "named_context_count": self.named_context_count,
            "main_effect_count": self.main_effect_count,
            "primary_interaction_count": self.primary_interaction_count,
            "exploratory_interaction_count": self.exploratory_interaction_count,
            "annual_stability_count": self.annual_stability_count,
            "oos_count": self.oos_count,
            "stable_interaction_count": self.stable_interaction_count,
            "latest_episode_count": self.latest_episode_count,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "event_path": str(self.event_path),
            "checkpoint_path": str(self.checkpoint_path),
            "path_path": str(self.path_path),
            "feature_path": str(self.feature_path),
            "policy_context_path": (
                None if self.policy_context_path is None else str(self.policy_context_path)
            ),
            "fundamental_context_path": (
                None
                if self.fundamental_context_path is None
                else str(self.fundamental_context_path)
            ),
            "episode_feature_parquet_path": str(self.episode_feature_parquet_path),
            "episode_validation_parquet_path": str(self.episode_validation_parquet_path),
            "named_context_parquet_path": str(self.named_context_parquet_path),
            "main_effect_parquet_path": str(self.main_effect_parquet_path),
            "primary_interaction_parquet_path": str(self.primary_interaction_parquet_path),
            "exploratory_interaction_parquet_path": str(
                self.exploratory_interaction_parquet_path
            ),
            "annual_stability_parquet_path": str(self.annual_stability_parquet_path),
            "oos_parquet_path": str(self.oos_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "features_use_t_or_earlier": True,
            "historical_returns_are_posterior_labels": True,
            "fundamental_and_policy_are_named_context_only": True,
            "promotion_eligible": False,
            "realtime_rule_eligible": False,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_futures_option_regime_interaction_research(
    *,
    event_path: Path | None = None,
    checkpoint_path: Path | None = None,
    path_path: Path | None = None,
    feature_path: Path | None = None,
    policy_context_path: Path | None = None,
    fundamental_context_path: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    episode_gap_sessions: int = DEFAULT_EPISODE_GAP_SESSIONS,
    chain_window_sessions: int = DEFAULT_CHAIN_WINDOW_SESSIONS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    min_cell_size: int = DEFAULT_MIN_CELL_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    permutation_count: int = DEFAULT_PERMUTATION_COUNT,
    purge_gap_sessions: int = DEFAULT_PURGE_GAP_SESSIONS,
    random_seed: int = DEFAULT_RANDOM_SEED,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchFuturesOptionRegimeInteractionResult:
    """构建 R93Q episode、阶段主效应、交互增量和 purged LOO 证据。"""

    normalized_horizons = _validate_parameters(
        horizons=horizons,
        episode_gap_sessions=episode_gap_sessions,
        chain_window_sessions=chain_window_sessions,
        min_sample_size=min_sample_size,
        min_cell_size=min_cell_size,
        fdr_level=fdr_level,
        permutation_count=permutation_count,
        purge_gap_sessions=purge_gap_sessions,
    )
    event_input = event_path or _latest_input(
        "futures_option_dynamic_wall",
        "CF_*_futures_option_dynamic_wall_event_daily.parquet",
        "R93N event table",
    )
    checkpoint_input = checkpoint_path or _latest_input(
        "futures_option_event_path",
        "CF_*_futures_option_event_path_checkpoint_daily.parquet",
        "R93P checkpoint table",
    )
    path_input = path_path or _latest_input(
        "futures_option_event_path",
        "CF_*_futures_option_event_path_path_daily.parquet",
        "R93P path table",
    )
    feature_input = feature_path or _latest_input(
        "futures_option_dynamic_wall",
        "CF_*_futures_option_dynamic_wall_feature_daily.parquet",
        "R93N feature table",
    )
    policy_input = policy_context_path or _optional_latest_input(
        "cotton_year_policy",
        "CF_*_policy_reference_daily.parquet",
    )
    fundamental_input = fundamental_context_path or _optional_fixed_input(
        data_dir()
        / "research"
        / PRODUCT_CODE
        / "fundamental_context"
        / "CF_fundamental_context_daily.parquet"
    )

    events = _load_event_table(event_input)
    checkpoint = _load_checkpoint_table(checkpoint_input, normalized_horizons)
    path_daily = _load_path_table(path_input)
    feature = _load_feature_table(feature_input)
    _validate_input_lineage(events, checkpoint, path_daily)

    effective_start = start or events["event_date"].min()
    effective_end = end or events["event_date"].max()
    if effective_start > effective_end:
        raise ResearchWorkbenchError("R93Q start不能晚于end")
    events = events.loc[events["event_date"].between(effective_start, effective_end)].copy()
    if events.empty:
        raise ResearchWorkbenchError("R93Q日期过滤后没有事件")
    event_ids = set(events["event_id"].astype(str))
    checkpoint = checkpoint.loc[checkpoint["event_id"].astype(str).isin(event_ids)].copy()
    path_daily = path_daily.loc[path_daily["event_id"].astype(str).isin(event_ids)].copy()

    active_run_id = run_id or utc_timestamp_id("r93q_regime_interaction", effective_end)
    prepared_events = _prepare_event_context(events=events, feature=feature)
    episodes = _build_episode_features(
        events=prepared_events,
        episode_gap_sessions=episode_gap_sessions,
        chain_window_sessions=chain_window_sessions,
        run_id=active_run_id,
    )
    policy = _load_policy_context(policy_input)
    fundamental = _load_fundamental_context(fundamental_input)
    episodes, named_context = _attach_named_context(
        episodes=episodes,
        policy=policy,
        fundamental=fundamental,
        run_id=active_run_id,
    )
    validation = _build_episode_validation(
        episodes=episodes,
        checkpoint=checkpoint,
        path_daily=path_daily,
        horizons=normalized_horizons,
        run_id=active_run_id,
    )
    main_effect = _build_stage_main_effects(
        validation=validation,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        run_id=active_run_id,
    )
    primary, primary_annual = _build_interaction_table(
        validation=validation,
        base_column="event_family",
        analysis_scope="PRIMARY_EVENT_FAMILY",
        min_sample_size=min_sample_size,
        min_cell_size=min_cell_size,
        fdr_level=fdr_level,
        permutation_count=permutation_count,
        random_seed=random_seed,
        run_id=active_run_id,
    )
    exploratory, exploratory_annual = _build_interaction_table(
        validation=validation,
        base_column="event_type",
        analysis_scope="EXPLORATORY_EVENT_TYPE",
        min_sample_size=min_sample_size,
        min_cell_size=min_cell_size,
        fdr_level=fdr_level,
        permutation_count=permutation_count,
        random_seed=random_seed + 1,
        run_id=active_run_id,
    )
    annual = pd.concat([primary_annual, exploratory_annual], ignore_index=True)
    oos = _build_purged_leave_one_year_out(
        validation=validation,
        interactions=primary,
        min_sample_size=min_sample_size,
        min_cell_size=min_cell_size,
        purge_gap_sessions=purge_gap_sessions,
        run_id=active_run_id,
    )
    primary = _attach_oos_and_finalize_status(
        interactions=primary,
        oos=oos,
        min_sample_size=min_sample_size,
        min_cell_size=min_cell_size,
        fdr_level=fdr_level,
    )
    exploratory = _finalize_interaction_status(
        interactions=exploratory,
        min_sample_size=min_sample_size,
        min_cell_size=min_cell_size,
        fdr_level=fdr_level,
        require_oos=False,
    )
    warnings = _build_warnings(
        run_id=active_run_id,
        prepared_events=prepared_events,
        episodes=episodes,
        validation=validation,
        primary=primary,
        exploratory=exploratory,
        policy_path=policy_input,
        fundamental_path=fundamental_input,
        min_sample_size=min_sample_size,
    )

    paths = _build_paths(
        start=episodes["episode_start_date"].min(),
        end=episodes["episode_end_date"].max(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_outputs(
        paths=paths,
        episodes=episodes,
        validation=validation,
        named_context=named_context,
        main_effect=main_effect,
        primary=primary,
        exploratory=exploratory,
        annual=annual,
        oos=oos,
        warnings=warnings,
    )
    stable_count = int(primary["evidence_status"].str.startswith("READY_").sum())
    latest_date = episodes["episode_end_date"].max()
    latest_episodes = episodes.loc[episodes["episode_end_date"].eq(latest_date)].copy()
    result = ResearchFuturesOptionRegimeInteractionResult(
        run_id=active_run_id,
        start=episodes["episode_start_date"].min(),
        end=episodes["episode_end_date"].max(),
        status="READY_WITH_WARNINGS" if any(w.severity == "WARN" for w in warnings) else "READY",
        source_event_count=len(events),
        episode_count=len(episodes),
        episode_validation_count=len(validation),
        named_context_count=len(named_context),
        main_effect_count=len(main_effect),
        primary_interaction_count=len(primary),
        exploratory_interaction_count=len(exploratory),
        annual_stability_count=len(annual),
        oos_count=len(oos),
        stable_interaction_count=stable_count,
        latest_episode_count=len(latest_episodes),
        warning_records=tuple(warnings),
        event_path=event_input,
        checkpoint_path=checkpoint_input,
        path_path=path_input,
        feature_path=feature_input,
        policy_context_path=policy_input,
        fundamental_context_path=fundamental_input,
        episode_feature_parquet_path=paths["episode_feature_parquet"],
        episode_feature_csv_path=paths["episode_feature_csv"],
        episode_validation_parquet_path=paths["episode_validation_parquet"],
        episode_validation_csv_path=paths["episode_validation_csv"],
        named_context_parquet_path=paths["named_context_parquet"],
        named_context_csv_path=paths["named_context_csv"],
        main_effect_parquet_path=paths["main_effect_parquet"],
        main_effect_csv_path=paths["main_effect_csv"],
        primary_interaction_parquet_path=paths["primary_interaction_parquet"],
        primary_interaction_csv_path=paths["primary_interaction_csv"],
        exploratory_interaction_parquet_path=paths["exploratory_interaction_parquet"],
        exploratory_interaction_csv_path=paths["exploratory_interaction_csv"],
        annual_stability_parquet_path=paths["annual_stability_parquet"],
        annual_stability_csv_path=paths["annual_stability_csv"],
        oos_parquet_path=paths["oos_parquet"],
        oos_csv_path=paths["oos_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
    )
    _write_markdown(
        result=result,
        episodes=episodes,
        main_effect=main_effect,
        primary=primary,
        exploratory=exploratory,
        oos=oos,
        latest_episodes=latest_episodes,
    )
    parameters = {
        "horizons": list(normalized_horizons),
        "episode_gap_sessions": episode_gap_sessions,
        "chain_window_sessions": chain_window_sessions,
        "min_sample_size": min_sample_size,
        "min_cell_size": min_cell_size,
        "fdr_level": fdr_level,
        "permutation_count": permutation_count,
        "purge_gap_sessions": purge_gap_sessions,
        "random_seed": random_seed,
        "market_stages": list(MARKET_STAGES),
        "interaction_dimensions": list(INTERACTION_DIMENSIONS),
    }
    write_json(
        result.json_path,
        {
            "report_type": "cf_futures_option_regime_interaction_research",
            "rule_version": RULE_VERSION,
            "summary": result.to_summary(),
            "latest_episode_mapping": _latest_episode_mapping(latest_episodes),
            "parameters": parameters,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    manifest = artifact_manifest(
        run_id=active_run_id,
        report_type="cf_futures_option_regime_interaction_research",
        rule_version=RULE_VERSION,
        data_asof=result.end,
        input_paths={
            "event_path": event_input,
            "checkpoint_path": checkpoint_input,
            "path_path": path_input,
            "feature_path": feature_input,
            "policy_context_path": policy_input,
            "fundamental_context_path": fundamental_input,
        },
        output_paths={
            "episode_feature_parquet_path": result.episode_feature_parquet_path,
            "episode_validation_parquet_path": result.episode_validation_parquet_path,
            "named_context_parquet_path": result.named_context_parquet_path,
            "main_effect_parquet_path": result.main_effect_parquet_path,
            "primary_interaction_parquet_path": result.primary_interaction_parquet_path,
            "exploratory_interaction_parquet_path": (
                result.exploratory_interaction_parquet_path
            ),
            "annual_stability_parquet_path": result.annual_stability_parquet_path,
            "oos_parquet_path": result.oos_parquet_path,
            "warning_csv_path": result.warning_csv_path,
            "markdown_path": result.markdown_path,
            "json_path": result.json_path,
        },
        human_review_required=HUMAN_REVIEW_REQUIRED,
        research_boundary=RESEARCH_BOUNDARY,
    )
    manifest["parameters"] = parameters
    write_json(result.manifest_path, manifest)
    return result


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    episode_gap_sessions: int,
    chain_window_sessions: int,
    min_sample_size: int,
    min_cell_size: int,
    fdr_level: float,
    permutation_count: int,
    purge_gap_sessions: int,
) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in horizons)))
    if normalized != DEFAULT_HORIZONS:
        raise ResearchWorkbenchError("R93Q horizons固定为1,3,5，避免事后选择周期")
    if episode_gap_sessions < 0:
        raise ResearchWorkbenchError("R93Q episode_gap_sessions不能为负数")
    if chain_window_sessions < 1:
        raise ResearchWorkbenchError("R93Q chain_window_sessions必须为正数")
    if min_sample_size < 1 or min_cell_size < 1:
        raise ResearchWorkbenchError("R93Q样本门槛必须为正数")
    if min_cell_size > min_sample_size:
        raise ResearchWorkbenchError("R93Q min_cell_size不能大于min_sample_size")
    if not 0 < fdr_level < 1:
        raise ResearchWorkbenchError("R93Q fdr_level必须位于0和1之间")
    if permutation_count < 10:
        raise ResearchWorkbenchError("R93Q permutation_count至少为10")
    if purge_gap_sessions < 0:
        raise ResearchWorkbenchError("R93Q purge_gap_sessions不能为负数")
    return normalized


def _latest_input(subdir: str, pattern: str, label: str) -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / subdir,
        pattern,
        label=label,
    )


def _optional_latest_input(subdir: str, pattern: str) -> Path | None:
    directory = data_dir() / "research" / PRODUCT_CODE / subdir
    if not directory.exists():
        return None
    try:
        return latest_matching_path(directory, pattern, label=pattern)
    except ResearchWorkbenchError:
        return None


def _optional_fixed_input(path: Path) -> Path | None:
    return path if path.exists() and path.is_file() else None


def _load_event_table(path: Path) -> pd.DataFrame:
    required = {
        "event_id",
        "observation_id",
        "event_date",
        "main_contract",
        "event_type",
        "event_direction",
        "option_market_stage",
        "data_activity_state",
        "trend_phase",
        "expiry_bucket",
        "event_trigger_observable_at_t",
        "contains_posterior_outcome",
    }
    frame = load_table(path, required=required, label="R93Q R93N event")
    overlap = sorted(POSTERIOR_COLUMNS.intersection(frame.columns))
    if overlap:
        raise ResearchWorkbenchError(f"R93Q T日事件表混入后验字段: {overlap}")
    working = frame.copy()
    working["event_date"] = _date_series(working["event_date"])
    working = working.dropna(subset=["event_id", "event_date"])
    if working.empty:
        raise ResearchWorkbenchError("R93Q R93N事件表为空")
    if working["event_id"].duplicated().any():
        raise ResearchWorkbenchError("R93Q event_id存在重复")
    if not working["event_trigger_observable_at_t"].fillna(False).astype(bool).all():
        raise ResearchWorkbenchError("R93Q事件表含非T日可观察事件")
    if working["contains_posterior_outcome"].fillna(False).astype(bool).any():
        raise ResearchWorkbenchError("R93Q事件表含后验结果标记")
    working["event_family"] = working["event_type"].map(_event_family)
    return working.sort_values(["event_date", "event_id"]).reset_index(drop=True)


def _load_checkpoint_table(path: Path, horizons: tuple[int, ...]) -> pd.DataFrame:
    required = {
        "event_id",
        "event_date",
        "event_type",
        "event_direction",
        "horizon",
        "label_execution_date",
        "label_exit_date",
        "label_forward_return",
        "label_event_directional_return",
        "label_event_outcome",
        "label_event_hit",
        "label_event_mfe",
        "label_event_mae",
        "label_forward_label_available",
        "checkpoint_outcome",
    }
    frame = load_table(path, required=required, label="R93Q R93P checkpoint")
    working = frame.copy()
    for column in ("event_date", "label_execution_date", "label_exit_date"):
        working[column] = _date_series(working[column])
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    working = working.loc[working["horizon"].isin(horizons)].copy()
    if working.empty:
        raise ResearchWorkbenchError("R93Q checkpoint没有1D/3D/5D记录")
    if working.duplicated(["event_id", "horizon"]).any():
        raise ResearchWorkbenchError("R93Q checkpoint存在event_id+horizon重复")
    available = working["label_forward_label_available"].fillna(False).astype(bool)
    invalid = available & (
        working["label_execution_date"].isna()
        | (working["label_execution_date"] <= working["event_date"])
    )
    if invalid.any():
        raise ResearchWorkbenchError("R93Q checkpoint违反T+1执行约束")
    return working.reset_index(drop=True)


def _load_path_table(path: Path) -> pd.DataFrame:
    required = {
        "event_id",
        "first_resolution_horizon",
        "first_resolution_outcome",
        "path_label",
        "path_available_checkpoints",
    }
    frame = load_table(path, required=required, label="R93Q R93P path")
    if frame["event_id"].duplicated().any():
        raise ResearchWorkbenchError("R93Q R93P path的event_id存在重复")
    return frame.copy()


def _load_feature_table(path: Path) -> pd.DataFrame:
    required = {
        "observation_id",
        "trade_date",
        "main_contract",
        "roll_context",
        "phase_v2",
        "expiry_bucket",
        "feature_uses_t_or_earlier",
        "contains_posterior_outcome",
    }
    frame = load_table(path, required=required, label="R93Q R93N feature")
    overlap = sorted(POSTERIOR_COLUMNS.intersection(frame.columns))
    if overlap:
        raise ResearchWorkbenchError(f"R93Q feature表混入后验字段: {overlap}")
    if not frame["feature_uses_t_or_earlier"].fillna(False).astype(bool).all():
        raise ResearchWorkbenchError("R93Q feature表未声明为T日可观察")
    if frame["contains_posterior_outcome"].fillna(False).astype(bool).any():
        raise ResearchWorkbenchError("R93Q feature表含后验结果标记")
    working = frame.copy()
    working["trade_date"] = _date_series(working["trade_date"])
    working = working.dropna(subset=["trade_date", "observation_id"])
    if working["observation_id"].duplicated().any():
        raise ResearchWorkbenchError("R93Q feature的observation_id必须唯一")
    return working.sort_values("trade_date").reset_index(drop=True)


def _load_policy_context(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    required = {
        "trade_date",
        "cotton_year",
        "futures_reference_bucket",
        "spot_reference_bucket",
        "relative_configuration",
        "contains_forward_label",
    }
    frame = load_table(path, required=required, label="R93Q R93G policy context")
    if frame["contains_forward_label"].fillna(False).astype(bool).any():
        raise ResearchWorkbenchError("R93Q政策上下文混入后验标签")
    working = frame.copy()
    working["trade_date"] = _date_series(working["trade_date"])
    return working.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last")


def _load_fundamental_context(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    required = {
        "market_trade_date",
        "dataset_type",
        "indicator_name",
        "metric_name",
        "indicator_value",
        "unit",
        "source_name",
        "fundamental_signal_status",
    }
    frame = load_table(path, required=required, label="R93Q fundamental context")
    working = frame.copy()
    working["market_trade_date"] = _date_series(working["market_trade_date"])
    return working.dropna(subset=["market_trade_date"]).reset_index(drop=True)


def _validate_input_lineage(
    events: pd.DataFrame,
    checkpoint: pd.DataFrame,
    path_daily: pd.DataFrame,
) -> None:
    event_ids = set(events["event_id"].astype(str))
    checkpoint_ids = set(checkpoint["event_id"].astype(str))
    path_ids = set(path_daily["event_id"].astype(str))
    if not event_ids.intersection(checkpoint_ids):
        raise ResearchWorkbenchError("R93Q R93N事件与R93P checkpoint没有共同event_id")
    if not event_ids.intersection(path_ids):
        raise ResearchWorkbenchError("R93Q R93N事件与R93P path没有共同event_id")


def _prepare_event_context(events: pd.DataFrame, feature: pd.DataFrame) -> pd.DataFrame:
    selected = [
        "observation_id",
        "trade_date",
        "main_contract",
        "roll_context",
        "phase_v2",
        "expiry_bucket",
    ]
    optional = [
        "participation_state",
        "confirmation_state",
        "days_to_expiry",
        "option_pressure_direction",
    ]
    selected.extend(column for column in optional if column in feature.columns)
    context = feature[selected].copy().rename(
        columns={
            "trade_date": "feature_trade_date",
            "main_contract": "feature_main_contract",
            "expiry_bucket": "feature_expiry_bucket",
        }
    )
    working = events.merge(context, on="observation_id", how="left", validate="many_to_one")
    missing = working["feature_trade_date"].isna()
    if missing.any():
        raise ResearchWorkbenchError(
            f"R93Q有{int(missing.sum())}条事件无法连接R93N feature"
        )
    contract_mismatch = working["main_contract"].astype(str).ne(
        working["feature_main_contract"].astype(str)
    )
    if contract_mismatch.any():
        raise ResearchWorkbenchError("R93Q事件与feature的主力合约不一致")
    working["session_index"] = working["event_date"].map(
        {value: index for index, value in enumerate(sorted(feature["trade_date"].unique()))}
    )
    if working["session_index"].isna().any():
        raise ResearchWorkbenchError("R93Q事件日期不在R93N feature交易日集合中")
    working["session_index"] = working["session_index"].astype(int)
    working["market_stage"] = working["event_date"].map(_calendar_market_stage)
    working["source_market_stage"] = working["option_market_stage"].astype(str)
    working["market_stage_mismatch"] = working["market_stage"].ne(
        working["source_market_stage"]
    )
    working["contract_cycle"] = working["main_contract"].map(_contract_cycle)
    working["cotton_year"] = working["event_date"].map(cotton_year_label)
    working["roll_context"] = working["roll_context"].fillna("UNKNOWN_ROLL_CONTEXT")
    working["trend_phase"] = working["phase_v2"].fillna(working["trend_phase"])
    working["expiry_bucket"] = working["feature_expiry_bucket"].fillna(
        working["expiry_bucket"]
    )
    return working.sort_values(["event_date", "event_id"]).reset_index(drop=True)


def _build_episode_features(
    *,
    events: pd.DataFrame,
    episode_gap_sessions: int,
    chain_window_sessions: int,
    run_id: str,
) -> pd.DataFrame:
    signature = ["event_family", "event_type", "event_direction", "main_contract"]
    rows: list[dict[str, object]] = []
    for _key, group in events.groupby(signature, dropna=False, sort=True):
        ordered = group.sort_values(["session_index", "event_id"]).copy()
        starts = ordered["session_index"].diff().fillna(episode_gap_sessions + 1).gt(
            episode_gap_sessions
        )
        ordered["episode_sequence"] = starts.cumsum().astype(int)
        for _sequence, members in ordered.groupby("episode_sequence", sort=True):
            members = members.sort_values(["session_index", "event_id"])
            anchor = members.iloc[0]
            start_index = int(anchor["session_index"])
            chain = events.loc[
                events["main_contract"].astype(str).eq(str(anchor["main_contract"]))
                & events["event_direction"].astype(str).eq(str(anchor["event_direction"]))
                & events["session_index"].between(
                    start_index, start_index + chain_window_sessions
                )
            ].sort_values(["session_index", "event_id"])
            chain_types = chain["event_type"].astype(str).tolist()
            episode_id = f"EP_{anchor['event_id']}"
            rows.append(
                {
                    "run_id": run_id,
                    "episode_id": episode_id,
                    "anchor_event_id": str(anchor["event_id"]),
                    "anchor_observation_id": str(anchor["observation_id"]),
                    "episode_start_date": anchor["event_date"],
                    "episode_end_date": members["event_date"].max(),
                    "episode_start_session_index": start_index,
                    "episode_end_session_index": int(members["session_index"].max()),
                    "episode_duration_sessions": (
                        int(members["session_index"].max()) - start_index + 1
                    ),
                    "episode_member_event_count": len(members),
                    "episode_member_event_ids": ";".join(members["event_id"].astype(str)),
                    "event_family": str(anchor["event_family"]),
                    "event_type": str(anchor["event_type"]),
                    "event_direction": str(anchor["event_direction"]),
                    "main_contract": str(anchor["main_contract"]),
                    "market_stage": str(anchor["market_stage"]),
                    "source_market_stage": str(anchor["source_market_stage"]),
                    "market_stage_mismatch": bool(anchor["market_stage_mismatch"]),
                    "data_activity_state": str(anchor["data_activity_state"]),
                    "contract_cycle": str(anchor["contract_cycle"]),
                    "expiry_bucket": str(anchor["expiry_bucket"]),
                    "roll_context": str(anchor["roll_context"]),
                    "cotton_year": str(anchor["cotton_year"]),
                    "trend_phase": str(anchor["trend_phase"]),
                    "chain_window_sessions": chain_window_sessions,
                    "chain_event_count": len(chain),
                    "chain_event_types": ";".join(chain_types),
                    "chain_event_families": ";".join(
                        _ordered_unique(chain["event_family"].astype(str).tolist())
                    ),
                    "chain_path_label": _chain_path_label(chain_types),
                    "named_context_count": 0,
                    "feature_uses_t_or_earlier": True,
                    "contains_posterior_outcome": False,
                    "fundamental_signal_status": "not_connected",
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["episode_start_date", "episode_id"]
    ).reset_index(drop=True)


def _attach_named_context(
    *,
    episodes: pd.DataFrame,
    policy: pd.DataFrame,
    fundamental: pd.DataFrame,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    context_rows: list[dict[str, object]] = []
    policy_by_date = (
        {} if policy.empty else {row.trade_date: row for row in policy.itertuples(index=False)}
    )
    fundamental_groups = (
        {} if fundamental.empty else dict(tuple(fundamental.groupby("market_trade_date")))
    )
    for episode in episodes.itertuples(index=False):
        event_date = episode.episode_start_date
        policy_row = policy_by_date.get(event_date)
        if policy_row is not None:
            context_rows.append(
                _context_record(
                    run_id=run_id,
                    episode_id=episode.episode_id,
                    event_date=event_date,
                    context_source="R93G_POLICY_REFERENCE",
                    context_name="policy_reference_configuration",
                    context_value=(
                        f"futures={policy_row.futures_reference_bucket};"
                        f"spot={policy_row.spot_reference_bucket};"
                        f"relative={policy_row.relative_configuration}"
                    ),
                    context_unit="categorical",
                    source_name="R93G",
                    knowledge_quality="T_DAY_OBSERVABLE_RESEARCH_CONTEXT",
                )
            )
        date_context = fundamental_groups.get(event_date)
        if date_context is not None:
            for item in date_context.itertuples(index=False):
                label = getattr(item, "context_label_4", "")
                value = f"{item.indicator_value}"
                if label and not pd.isna(label):
                    value = f"{value};context={label}"
                context_rows.append(
                    _context_record(
                        run_id=run_id,
                        episode_id=episode.episode_id,
                        event_date=event_date,
                        context_source="R53_FUNDAMENTAL_CONTEXT",
                        context_name=(
                            f"{item.dataset_type}:{item.indicator_name}:{item.metric_name}"
                        ),
                        context_value=value,
                        context_unit=str(item.unit),
                        source_name=str(item.source_name),
                        knowledge_quality="OBSERVATION_DATE_PROXY",
                    )
                )
    columns = [
        "run_id",
        "episode_id",
        "event_date",
        "context_source",
        "context_name",
        "context_value",
        "context_unit",
        "source_name",
        "knowledge_quality",
        "used_in_direction_test",
        "promotion_eligible",
        "trading_instruction",
    ]
    named = pd.DataFrame(context_rows, columns=columns)
    working = episodes.copy()
    if not named.empty:
        counts = named.groupby("episode_id").size()
        working["named_context_count"] = working["episode_id"].map(counts).fillna(0).astype(int)
    working["fundamental_signal_status"] = "named_context_only"
    return working, named


def _context_record(
    *,
    run_id: str,
    episode_id: str,
    event_date: date,
    context_source: str,
    context_name: str,
    context_value: str,
    context_unit: str,
    source_name: str,
    knowledge_quality: str,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "episode_id": episode_id,
        "event_date": event_date,
        "context_source": context_source,
        "context_name": context_name,
        "context_value": context_value,
        "context_unit": context_unit,
        "source_name": source_name,
        "knowledge_quality": knowledge_quality,
        "used_in_direction_test": False,
        "promotion_eligible": False,
        "trading_instruction": "not_a_trading_instruction",
    }


def _build_episode_validation(
    *,
    episodes: pd.DataFrame,
    checkpoint: pd.DataFrame,
    path_daily: pd.DataFrame,
    horizons: tuple[int, ...],
    run_id: str,
) -> pd.DataFrame:
    anchors = episodes[
        [
            "episode_id",
            "anchor_event_id",
            "episode_start_date",
            "episode_start_session_index",
            "event_family",
            "event_type",
            "event_direction",
            "main_contract",
            "market_stage",
            "data_activity_state",
            "contract_cycle",
            "expiry_bucket",
            "roll_context",
            "cotton_year",
            "trend_phase",
            "chain_path_label",
        ]
    ].copy()
    label_columns = [
        "event_id",
        "horizon",
        "label_execution_date",
        "label_exit_date",
        "label_forward_return",
        "label_event_directional_return",
        "label_event_outcome",
        "label_event_hit",
        "label_event_mfe",
        "label_event_mae",
        "label_forward_label_available",
        "checkpoint_outcome",
    ]
    labels = checkpoint[label_columns].rename(columns={"event_id": "anchor_event_id"})
    merged = anchors.merge(labels, on="anchor_event_id", how="left", validate="one_to_many")
    missing = merged["horizon"].isna()
    if missing.any():
        missing_count = int(merged.loc[missing, "episode_id"].nunique())
        raise ResearchWorkbenchError(f"R93Q有{missing_count}个episode缺少R93P checkpoint")
    merged = merged.loc[merged["horizon"].isin(horizons)].copy()
    path_columns = [
        "event_id",
        "first_resolution_horizon",
        "first_resolution_outcome",
        "path_label",
        "path_available_checkpoints",
    ]
    path_context = path_daily[path_columns].rename(columns={"event_id": "anchor_event_id"})
    merged = merged.merge(path_context, on="anchor_event_id", how="left", validate="many_to_one")
    columns = {
        "label_execution_date": "execution_date",
        "label_exit_date": "exit_date",
        "label_forward_return": "forward_return",
        "label_event_directional_return": "directional_return",
        "label_event_outcome": "event_outcome",
        "label_event_hit": "event_hit",
        "label_event_mfe": "event_mfe",
        "label_event_mae": "event_mae",
        "label_forward_label_available": "forward_label_available",
    }
    merged = merged.rename(columns=columns)
    merged["run_id"] = run_id
    merged["calendar_year"] = merged["episode_start_date"].map(lambda value: value.year)
    merged["forward_returns_are_historical_posterior_labels"] = True
    merged["t_plus_one_execution"] = (
        merged["execution_date"].isna()
        | (merged["execution_date"] > merged["episode_start_date"])
    )
    merged["promotion_eligible"] = False
    merged["trading_instruction"] = "not_a_trading_instruction"
    keep = [
        "run_id",
        "episode_id",
        "anchor_event_id",
        "episode_start_date",
        "episode_start_session_index",
        "calendar_year",
        "event_family",
        "event_type",
        "event_direction",
        "main_contract",
        "market_stage",
        "data_activity_state",
        "contract_cycle",
        "expiry_bucket",
        "roll_context",
        "cotton_year",
        "trend_phase",
        "chain_path_label",
        "horizon",
        "execution_date",
        "exit_date",
        "forward_return",
        "directional_return",
        "event_outcome",
        "event_hit",
        "event_mfe",
        "event_mae",
        "checkpoint_outcome",
        "forward_label_available",
        "first_resolution_horizon",
        "first_resolution_outcome",
        "path_label",
        "path_available_checkpoints",
        "forward_returns_are_historical_posterior_labels",
        "t_plus_one_execution",
        "promotion_eligible",
        "trading_instruction",
    ]
    return merged.reindex(columns=keep).sort_values(
        ["episode_start_date", "episode_id", "horizon"]
    ).reset_index(drop=True)


def _build_stage_main_effects(
    *,
    validation: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
    run_id: str,
) -> pd.DataFrame:
    usable = _usable_directional(validation)
    rows: list[dict[str, object]] = []
    base_columns = ["event_family", "event_direction", "horizon"]
    for keys, universe in usable.groupby(base_columns, dropna=False, sort=True):
        family, direction, horizon = keys
        for stage in MARKET_STAGES:
            group = universe.loc[universe["market_stage"].eq(stage)]
            control = universe.loc[~universe["market_stage"].eq(stage)]
            metrics = _binary_metrics(group)
            comparison = _binary_metrics(control)
            rows.append(
                {
                    "run_id": run_id,
                    "event_family": family,
                    "event_direction": direction,
                    "horizon": int(horizon),
                    "market_stage": stage,
                    **_prefixed(metrics, "stage"),
                    **_prefixed(comparison, "other_stage"),
                    "delta_hit_rate": metrics["hit_rate"] - comparison["hit_rate"],
                    "delta_mean_directional_return": (
                        metrics["mean_directional_return"]
                        - comparison["mean_directional_return"]
                    ),
                    "fisher_exact_p_value": _fisher_exact_two_sided(
                        group_successes=int(metrics["success_count"]),
                        group_count=int(metrics["sample_count"]),
                        comparison_successes=int(comparison["success_count"]),
                        comparison_count=int(comparison["sample_count"]),
                    ),
                    "fdr_q_value": math.nan,
                    "evidence_status": "PENDING_FDR",
                    "forward_returns_are_historical_posterior_labels": True,
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    for _horizon, family in result.groupby("horizon", sort=True):
        result.loc[family.index, "fdr_q_value"] = _benjamini_hochberg(
            family["fisher_exact_p_value"].astype(float).tolist()
        )
    result["evidence_status"] = result.apply(
        lambda row: _main_effect_status(
            row,
            min_sample_size=min_sample_size,
            fdr_level=fdr_level,
        ),
        axis=1,
    )
    return result.reset_index(drop=True)


def _build_interaction_table(
    *,
    validation: pd.DataFrame,
    base_column: str,
    analysis_scope: str,
    min_sample_size: int,
    min_cell_size: int,
    fdr_level: float,
    permutation_count: int,
    random_seed: int,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    usable = _usable_directional(validation)
    rows: list[dict[str, object]] = []
    annual_rows: list[dict[str, object]] = []
    base_columns = [base_column, "event_direction", "horizon"]
    for keys, universe in usable.groupby(base_columns, dropna=False, sort=True):
        base_value, direction, horizon = keys
        for dimension in INTERACTION_DIMENSIONS:
            levels = sorted(universe[dimension].dropna().astype(str).unique())
            for stage in MARKET_STAGES:
                for level in levels:
                    interaction_key = (
                        f"{analysis_scope}|{base_value}|{direction}|{int(horizon)}|"
                        f"{stage}|{dimension}|{level}"
                    )
                    interaction_id = "INT_" + hashlib.sha256(
                        interaction_key.encode("utf-8")
                    ).hexdigest()[:16]
                    cells = _interaction_cells(
                        universe=universe,
                        stage=stage,
                        dimension=dimension,
                        level=level,
                    )
                    metrics = {name: _binary_metrics(cell) for name, cell in cells.items()}
                    target_delta_hit = (
                        metrics["target_level"]["hit_rate"]
                        - metrics["target_other"]["hit_rate"]
                    )
                    other_delta_hit = (
                        metrics["other_level"]["hit_rate"]
                        - metrics["other_other"]["hit_rate"]
                    )
                    target_delta_return = (
                        metrics["target_level"]["mean_directional_return"]
                        - metrics["target_other"]["mean_directional_return"]
                    )
                    other_delta_return = (
                        metrics["other_level"]["mean_directional_return"]
                        - metrics["other_other"]["mean_directional_return"]
                    )
                    permutation_ready = (
                        metrics["target_level"]["sample_count"] >= min_sample_size
                        and metrics["target_other"]["sample_count"] >= min_sample_size
                        and metrics["other_level"]["sample_count"] >= min_cell_size
                        and metrics["other_other"]["sample_count"] >= min_cell_size
                    )
                    permutation_p = (
                        _interaction_permutation_p_value(
                            universe=universe,
                            stage=stage,
                            dimension=dimension,
                            level=level,
                            permutation_count=permutation_count,
                            random_seed=_stable_seed(random_seed, interaction_key),
                            min_cell_size=min_cell_size,
                        )
                        if permutation_ready
                        else math.nan
                    )
                    annual = _annual_interaction_rows(
                        universe=universe,
                        interaction_id=interaction_id,
                        analysis_scope=analysis_scope,
                        base_column=base_column,
                        base_value=str(base_value),
                        direction=str(direction),
                        horizon=int(horizon),
                        stage=stage,
                        dimension=dimension,
                        level=level,
                        run_id=run_id,
                    )
                    annual_rows.extend(annual)
                    annual_summary = _annual_summary(annual, target_delta_return)
                    row = {
                        "run_id": run_id,
                        "interaction_id": interaction_id,
                        "analysis_scope": analysis_scope,
                        "base_dimension": base_column,
                        "base_value": str(base_value),
                        "event_direction": str(direction),
                        "horizon": int(horizon),
                        "market_stage": stage,
                        "interaction_dimension": dimension,
                        "interaction_level": level,
                        **_prefixed(metrics["target_level"], "target_stage_level"),
                        **_prefixed(metrics["target_other"], "target_stage_control"),
                        **_prefixed(metrics["other_level"], "other_stage_level"),
                        **_prefixed(metrics["other_other"], "other_stage_control"),
                        "target_stage_delta_hit_rate": target_delta_hit,
                        "other_stage_delta_hit_rate": other_delta_hit,
                        "interaction_delta_hit_rate": target_delta_hit - other_delta_hit,
                        "target_stage_delta_mean_return": target_delta_return,
                        "other_stage_delta_mean_return": other_delta_return,
                        "interaction_delta_mean_return": (
                            target_delta_return - other_delta_return
                        ),
                        "fisher_exact_p_value": _fisher_exact_two_sided(
                            group_successes=int(
                                metrics["target_level"]["success_count"]
                            ),
                            group_count=int(metrics["target_level"]["sample_count"]),
                            comparison_successes=int(
                                metrics["target_other"]["success_count"]
                            ),
                            comparison_count=int(metrics["target_other"]["sample_count"]),
                        ),
                        "permutation_p_value": permutation_p,
                        "fisher_fdr_q_value": math.nan,
                        "permutation_fdr_q_value": math.nan,
                        **annual_summary,
                        "oos_support_count": 0,
                        "oos_contradict_count": 0,
                        "oos_inconclusive_count": 0,
                        "evidence_status": "PENDING_FDR",
                        "evidence_role": (
                            "PRE_REGISTERED_PRIMARY_INTERACTION"
                            if analysis_scope == "PRIMARY_EVENT_FAMILY"
                            else "EXPLORATORY_PHYSICALLY_SEPARATED"
                        ),
                        "fundamental_context_used_in_test": False,
                        "forward_returns_are_historical_posterior_labels": True,
                        "promotion_eligible": False,
                        "realtime_rule_eligible": False,
                        "trading_instruction": "not_a_trading_instruction",
                    }
                    rows.append(row)
    result = pd.DataFrame(rows)
    annual_frame = pd.DataFrame(annual_rows)
    if result.empty:
        return result, annual_frame
    fdr_groups = ["analysis_scope", "horizon", "interaction_dimension"]
    for _key, family in result.groupby(fdr_groups, sort=True):
        result.loc[family.index, "fisher_fdr_q_value"] = _benjamini_hochberg(
            family["fisher_exact_p_value"].astype(float).tolist()
        )
        result.loc[family.index, "permutation_fdr_q_value"] = _benjamini_hochberg(
            family["permutation_p_value"].fillna(1.0).astype(float).tolist()
        )
    # 初步状态只供构建OOS候选，最终状态在OOS合并后统一生成。
    result["evidence_status"] = result.apply(
        lambda row: _interaction_status(
            row,
            min_sample_size=min_sample_size,
            min_cell_size=min_cell_size,
            fdr_level=fdr_level,
            require_oos=False,
        ),
        axis=1,
    )
    return result.reset_index(drop=True), annual_frame.reset_index(drop=True)


def _build_purged_leave_one_year_out(
    *,
    validation: pd.DataFrame,
    interactions: pd.DataFrame,
    min_sample_size: int,
    min_cell_size: int,
    purge_gap_sessions: int,
    run_id: str,
) -> pd.DataFrame:
    usable = _usable_directional(validation)
    rows: list[dict[str, object]] = []
    if interactions.empty:
        return pd.DataFrame()
    for item in interactions.itertuples(index=False):
        universe = usable.loc[
            usable["event_family"].astype(str).eq(str(item.base_value))
            & usable["event_direction"].astype(str).eq(str(item.event_direction))
            & usable["horizon"].eq(int(item.horizon))
            & usable["market_stage"].eq(str(item.market_stage))
        ].copy()
        years = sorted(universe["calendar_year"].dropna().astype(int).unique())
        for test_year in years:
            test = universe.loc[universe["calendar_year"].eq(test_year)].copy()
            train = universe.loc[~universe["calendar_year"].eq(test_year)].copy()
            test_sessions = pd.to_numeric(
                test["episode_start_session_index"], errors="coerce"
            ).dropna()
            before_purge = len(train)
            if not test_sessions.empty:
                lower = int(test_sessions.min()) - purge_gap_sessions
                upper = int(test_sessions.max()) + purge_gap_sessions
                train = train.loc[
                    ~pd.to_numeric(
                        train["episode_start_session_index"], errors="coerce"
                    ).between(lower, upper)
                ].copy()
            train_group, train_control = _level_and_control(
                train,
                dimension=str(item.interaction_dimension),
                level=str(item.interaction_level),
            )
            test_group, test_control = _level_and_control(
                test,
                dimension=str(item.interaction_dimension),
                level=str(item.interaction_level),
            )
            train_group_metrics = _binary_metrics(train_group)
            train_control_metrics = _binary_metrics(train_control)
            test_group_metrics = _binary_metrics(test_group)
            test_control_metrics = _binary_metrics(test_control)
            train_delta = (
                train_group_metrics["mean_directional_return"]
                - train_control_metrics["mean_directional_return"]
            )
            test_delta = (
                test_group_metrics["mean_directional_return"]
                - test_control_metrics["mean_directional_return"]
            )
            train_ready = (
                train_group_metrics["sample_count"] >= min_sample_size
                and train_control_metrics["sample_count"] >= min_sample_size
            )
            test_ready = (
                test_group_metrics["sample_count"] >= min_cell_size
                and test_control_metrics["sample_count"] >= min_cell_size
            )
            if not train_ready or not test_ready:
                status = "INSUFFICIENT_SAMPLE"
            elif _same_nonzero_sign(train_delta, test_delta):
                status = "SUPPORT"
            elif _opposite_nonzero_sign(train_delta, test_delta):
                status = "CONTRADICT"
            else:
                status = "INCONCLUSIVE"
            rows.append(
                {
                    "run_id": run_id,
                    "interaction_id": item.interaction_id,
                    "base_value": item.base_value,
                    "event_direction": item.event_direction,
                    "horizon": int(item.horizon),
                    "market_stage": item.market_stage,
                    "interaction_dimension": item.interaction_dimension,
                    "interaction_level": item.interaction_level,
                    "test_year": int(test_year),
                    "test_year_is_partial": int(test_year) == max(years),
                    "purge_gap_sessions": purge_gap_sessions,
                    "purged_train_count": before_purge - len(train),
                    "train_group_count": train_group_metrics["sample_count"],
                    "train_control_count": train_control_metrics["sample_count"],
                    "test_group_count": test_group_metrics["sample_count"],
                    "test_control_count": test_control_metrics["sample_count"],
                    "train_delta_hit_rate": (
                        train_group_metrics["hit_rate"]
                        - train_control_metrics["hit_rate"]
                    ),
                    "test_delta_hit_rate": (
                        test_group_metrics["hit_rate"]
                        - test_control_metrics["hit_rate"]
                    ),
                    "train_delta_mean_directional_return": train_delta,
                    "test_delta_mean_directional_return": test_delta,
                    "oos_status": status,
                    "forward_returns_are_historical_posterior_labels": True,
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows).reset_index(drop=True)


def _attach_oos_and_finalize_status(
    *,
    interactions: pd.DataFrame,
    oos: pd.DataFrame,
    min_sample_size: int,
    min_cell_size: int,
    fdr_level: float,
) -> pd.DataFrame:
    working = interactions.copy()
    if not oos.empty:
        counts = (
            oos.groupby(["interaction_id", "oos_status"]).size().unstack(fill_value=0)
        )
        for status, column in (
            ("SUPPORT", "oos_support_count"),
            ("CONTRADICT", "oos_contradict_count"),
            ("INCONCLUSIVE", "oos_inconclusive_count"),
        ):
            values = counts.get(status, pd.Series(dtype=int))
            working[column] = working["interaction_id"].map(values).fillna(0).astype(int)
    return _finalize_interaction_status(
        interactions=working,
        min_sample_size=min_sample_size,
        min_cell_size=min_cell_size,
        fdr_level=fdr_level,
        require_oos=True,
    )


def _finalize_interaction_status(
    *,
    interactions: pd.DataFrame,
    min_sample_size: int,
    min_cell_size: int,
    fdr_level: float,
    require_oos: bool,
) -> pd.DataFrame:
    working = interactions.copy()
    if working.empty:
        return working
    working["evidence_status"] = working.apply(
        lambda row: _interaction_status(
            row,
            min_sample_size=min_sample_size,
            min_cell_size=min_cell_size,
            fdr_level=fdr_level,
            require_oos=require_oos,
        ),
        axis=1,
    )
    exploratory = working["analysis_scope"].eq("EXPLORATORY_EVENT_TYPE")
    if exploratory.any():
        working.loc[exploratory, "evidence_status"] = working.loc[
            exploratory, "evidence_status"
        ].map(_exploratory_status)
    return working.sort_values(
        ["evidence_status", "horizon", "base_value", "interaction_dimension"]
    ).reset_index(drop=True)


def _exploratory_status(value: object) -> str:
    """探索表不使用READY字样，防止事后细分被误认作预注册裁决。"""

    status = str(value)
    if status == "READY_POSITIVE_INTERACTION":
        return "EXPLORATORY_POSITIVE_SIGNAL"
    if status == "READY_NEGATIVE_INTERACTION":
        return "EXPLORATORY_NEGATIVE_SIGNAL"
    if status.startswith("WATCH_"):
        return f"EXPLORATORY_{status}"
    if status.startswith("DESCRIPTIVE_"):
        return f"EXPLORATORY_{status}"
    return status


def _build_warnings(
    *,
    run_id: str,
    prepared_events: pd.DataFrame,
    episodes: pd.DataFrame,
    validation: pd.DataFrame,
    primary: pd.DataFrame,
    exploratory: pd.DataFrame,
    policy_path: Path | None,
    fundamental_path: Path | None,
    min_sample_size: int,
) -> list[FuturesOptionRegimeInteractionWarningRecord]:
    warnings: list[FuturesOptionRegimeInteractionWarningRecord] = []
    mismatch = int(prepared_events["market_stage_mismatch"].sum())
    if mismatch:
        warnings.append(
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "market_stage",
                "WARN",
                "R93Q_FROZEN_STAGE_SOURCE_MISMATCH",
                "冻结年份阶段与R93N来源阶段存在不一致，R93Q保留两列并使用冻结口径检验。",
                mismatch,
                "frozen_calendar_market_stage_boundaries",
            )
        )
    deduplicated = len(prepared_events) - len(episodes)
    warnings.append(
        FuturesOptionRegimeInteractionWarningRecord(
            run_id,
            "episode",
            "INFO",
            "R93Q_REPEATED_EVENTS_DEDUPLICATED",
            "连续重复事件已压缩为episode，只有首次可观察事件进入预测研究单位。",
            deduplicated,
            "episode_deduplication_and_chain_window",
        )
    )
    small = int(primary["evidence_status"].eq("WEAK_OR_SMALL_SAMPLE").sum())
    if small:
        warnings.append(
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "interaction",
                "WARN",
                "R93Q_PRIMARY_SMALL_OR_UNBALANCED_CELLS",
                f"部分预注册交互未达到独立episode样本门槛{min_sample_size}。",
                small,
                "interaction_multiple_testing_and_fdr_interpretation",
            )
        )
    collinear = int(primary["evidence_status"].eq("COLLINEAR_OR_NO_OVERLAP").sum())
    if collinear:
        warnings.append(
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "interaction",
                "WARN",
                "R93Q_COLLINEAR_OR_NO_OVERLAP",
                "部分阶段交互缺少四格重叠；棉花年度与冻结年份阶段尤其可能共线。",
                collinear,
                "frozen_calendar_market_stage_boundaries",
            )
        )
    if policy_path is None:
        warnings.append(
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "named_context",
                "WARN",
                "R93Q_POLICY_CONTEXT_NOT_CONNECTED",
                "未连接R93G政策参考上下文；不影响交互检验。",
                len(episodes),
                "fundamental_observation_date_and_unit",
            )
        )
    if fundamental_path is None:
        warnings.append(
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "named_context",
                "WARN",
                "R93Q_FUNDAMENTAL_CONTEXT_NOT_CONNECTED",
                "未连接基本面观察上下文；不影响交互检验。",
                len(episodes),
                "fundamental_observation_date_and_unit",
            )
        )
    if primary["evidence_status"].str.startswith("READY_").sum() == 0:
        warnings.append(
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "conclusion",
                "WARN",
                "R93Q_NO_STABLE_PRIMARY_INTERACTION",
                "没有预注册主交互同时通过样本、FDR、年度稳定性和OOS门槛。",
                len(primary),
                "interaction_multiple_testing_and_fdr_interpretation",
            )
        )
    warnings.extend(
        [
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "boundary",
                "INFO",
                "R93Q_EXPLORATORY_RESULTS_SEPARATED",
                "事件类型级探索分层与预注册事件族主结果物理分表。",
                len(exploratory),
            ),
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "boundary",
                "INFO",
                "R93Q_POSTERIOR_LABEL_BOUNDARY",
                "forward return只作为历史后验验证标签，不进入episode特征。",
                len(validation),
            ),
            FuturesOptionRegimeInteractionWarningRecord(
                run_id,
                "boundary",
                "INFO",
                "R93Q_OPTION_OWNERSHIP_UNKNOWN",
                "公开期权持仓无法识别买卖方或dealer gamma，交互结果不改变方向和仓位。",
                len(episodes),
                "option_open_interest_long_short_ownership_unknown",
            ),
        ]
    )
    return warnings


def _build_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_futures_option_regime_interaction"
    data_root = output_dir or (
        data_dir() / "research" / PRODUCT_CODE / "futures_option_regime_interaction"
    )
    report_root = report_output_dir or (
        reports_dir() / "research" / "futures_option_regime_interaction"
    )
    return {
        "episode_feature_parquet": data_root / f"{stem}_episode_feature.parquet",
        "episode_feature_csv": data_root / f"{stem}_episode_feature.csv",
        "episode_validation_parquet": data_root / f"{stem}_episode_validation.parquet",
        "episode_validation_csv": data_root / f"{stem}_episode_validation.csv",
        "named_context_parquet": data_root / f"{stem}_named_context.parquet",
        "named_context_csv": data_root / f"{stem}_named_context.csv",
        "main_effect_parquet": data_root / f"{stem}_stage_main_effect.parquet",
        "main_effect_csv": data_root / f"{stem}_stage_main_effect.csv",
        "primary_interaction_parquet": data_root / f"{stem}_primary_interaction.parquet",
        "primary_interaction_csv": data_root / f"{stem}_primary_interaction.csv",
        "exploratory_interaction_parquet": (
            data_root / f"{stem}_exploratory_interaction.parquet"
        ),
        "exploratory_interaction_csv": data_root / f"{stem}_exploratory_interaction.csv",
        "annual_stability_parquet": data_root / f"{stem}_annual_stability.parquet",
        "annual_stability_csv": data_root / f"{stem}_annual_stability.csv",
        "oos_parquet": data_root / f"{stem}_purged_leave_one_year_out.parquet",
        "oos_csv": data_root / f"{stem}_purged_leave_one_year_out.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
        "manifest": report_root / f"{stem}_manifest.json",
    }


def _write_outputs(
    *,
    paths: dict[str, Path],
    episodes: pd.DataFrame,
    validation: pd.DataFrame,
    named_context: pd.DataFrame,
    main_effect: pd.DataFrame,
    primary: pd.DataFrame,
    exploratory: pd.DataFrame,
    annual: pd.DataFrame,
    oos: pd.DataFrame,
    warnings: list[FuturesOptionRegimeInteractionWarningRecord],
) -> None:
    write_frame(
        episodes, paths["episode_feature_parquet"], paths["episode_feature_csv"]
    )
    write_frame(
        validation,
        paths["episode_validation_parquet"],
        paths["episode_validation_csv"],
    )
    write_frame(named_context, paths["named_context_parquet"], paths["named_context_csv"])
    write_frame(main_effect, paths["main_effect_parquet"], paths["main_effect_csv"])
    write_frame(
        primary,
        paths["primary_interaction_parquet"],
        paths["primary_interaction_csv"],
    )
    write_frame(
        exploratory,
        paths["exploratory_interaction_parquet"],
        paths["exploratory_interaction_csv"],
    )
    write_frame(
        annual,
        paths["annual_stability_parquet"],
        paths["annual_stability_csv"],
    )
    write_frame(oos, paths["oos_parquet"], paths["oos_csv"])
    write_warning_csv(paths["warning_csv"], [item.to_summary() for item in warnings])


def _write_markdown(
    *,
    result: ResearchFuturesOptionRegimeInteractionResult,
    episodes: pd.DataFrame,
    main_effect: pd.DataFrame,
    primary: pd.DataFrame,
    exploratory: pd.DataFrame,
    oos: pd.DataFrame,
    latest_episodes: pd.DataFrame,
) -> None:
    stage_counts = episodes["market_stage"].value_counts()
    ready = primary.loc[primary["evidence_status"].str.startswith("READY_")]
    watch = primary.loc[primary["evidence_status"].str.startswith("WATCH_")]
    main_ranked = main_effect.assign(
        status_rank=main_effect["evidence_status"].map(
            {
                "STAGE_MAIN_EFFECT_POSITIVE": 0,
                "STAGE_MAIN_EFFECT_NEGATIVE": 0,
                "NO_STABLE_STAGE_MAIN_EFFECT": 1,
                "WEAK_OR_SMALL_SAMPLE": 2,
            }
        ).fillna(3)
    ).sort_values(
        ["status_rank", "stage_sample_count", "horizon"],
        ascending=[True, False, True],
    )
    lines = [
        "# CF期货-期权市场阶段交互研究 R93Q",
        "",
        "## 数据状态",
        "",
        f"- 样本区间：`{result.start}` 至 `{result.end}`。",
        f"- R93N原始事件：`{result.source_event_count}`；去重episode：`{result.episode_count}`。",
        (
            f"- episode后验记录：`{result.episode_validation_count}`；"
            f"具名观察上下文：`{result.named_context_count}`。"
        ),
        (
            "- 冻结阶段episode："
            f"EARLY_THIN `{int(stage_counts.get('EARLY_THIN', 0))}`，"
            f"EXPANSION `{int(stage_counts.get('EXPANSION', 0))}`，"
            f"MATURE_ACTIVE `{int(stage_counts.get('MATURE_ACTIVE', 0))}`。"
        ),
        "- 输入只来自R93N/R93P和已规范化研究上下文，不读取交易所raw。",
        "",
        "## Episode与交互定义",
        "",
        (
            "- 同合约、同方向、同事件类型在相邻交易会话连续出现时合并为一个episode；"
            "只有首次事件作为统计锚点，避免日度重复放大样本。"
        ),
        (
            "- 事件链保留锚点后5个交易会话内的接近、触及、突破、迁移、"
            "建仓/撤仓和区间变化，仅用于解释。"
        ),
        "- 市场阶段固定为2021 EARLY_THIN、2022-2023 EXPANSION、2024-2026 MATURE_ACTIVE。",
        (
            "- 主结果按事件族检验阶段×合约周期/到期桶/roll context/棉花年度/趋势阶段；"
            "事件类型细分单独列为探索结果。"
        ),
        "- 交互增量使用四格差中差；命中差使用Fisher检验，方向收益差使用分阶段置换检验。",
        "",
        "## 市场阶段主效应",
        "",
        "| 事件族 | 方向 | 周期 | 阶段 | 阶段样本 | 命中差 | 收益差 | q值 | 结论 |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in main_ranked.head(24).itertuples(index=False):
        lines.append(
            f"| {row.event_family} | {row.event_direction} | {row.horizon}D | "
            f"{row.market_stage} | {row.stage_sample_count} | "
            f"{fmt_percent(row.delta_hit_rate)} | "
            f"{fmt_percent(row.delta_mean_directional_return)} | "
            f"{fmt_number(row.fdr_q_value, 3)} | {row.evidence_status} |"
        )
    lines.extend(
        [
            "",
            "## 预注册交互增量",
            "",
            f"- READY交互：`{len(ready)}`；WATCH交互：`{len(watch)}`。",
            "",
            (
                "| 事件族 | 方向 | 周期 | 阶段×维度 | 水平 | 四格样本 | "
                "阶段内命中差 | 交互收益差 | Fisher q | 置换 q | 年度一致性 | OOS | 结论 |"
            ),
            "| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    ranked = primary.assign(
        status_rank=primary["evidence_status"].map(
            {
                "READY_POSITIVE_INTERACTION": 0,
                "READY_NEGATIVE_INTERACTION": 0,
                "WATCH_POSITIVE_INTERACTION": 1,
                "WATCH_NEGATIVE_INTERACTION": 1,
                "DESCRIPTIVE_POSITIVE_PATTERN": 2,
                "DESCRIPTIVE_NEGATIVE_PATTERN": 2,
                "INCONCLUSIVE": 3,
                "WEAK_OR_SMALL_SAMPLE": 4,
                "COLLINEAR_OR_NO_OVERLAP": 5,
            }
        ).fillna(5)
    ).sort_values(
        ["status_rank", "target_stage_level_sample_count"], ascending=[True, False]
    )
    for row in ranked.head(36).itertuples(index=False):
        cells = (
            f"{row.target_stage_level_sample_count}/"
            f"{row.target_stage_control_sample_count}/"
            f"{row.other_stage_level_sample_count}/"
            f"{row.other_stage_control_sample_count}"
        )
        lines.append(
            f"| {row.base_value} | {row.event_direction} | {row.horizon}D | "
            f"{row.market_stage}×{row.interaction_dimension} | {row.interaction_level} | "
            f"{cells} | {fmt_percent(row.target_stage_delta_hit_rate)} | "
            f"{fmt_percent(row.interaction_delta_mean_return)} | "
            f"{fmt_number(row.fisher_fdr_q_value, 3)} | "
            f"{fmt_number(row.permutation_fdr_q_value, 3)} | "
            f"{fmt_percent(row.annual_sign_consistency_rate)} | "
            f"{row.oos_support_count}/{row.oos_contradict_count} | "
            f"{row.evidence_status} |"
        )
    lines.extend(
        [
            "",
            "## 样本外与停止条件",
            "",
            f"- purged leave-one-year-out记录：`{len(oos)}`。",
            (
                "- OOS只检验目标阶段内部该情境相对同阶段其他情境的增量；"
                "年份阶段本身与时间共线，不能被误写成可随机重复的regime。"
            ),
            (
                "- 若没有主交互同时通过四格样本、两类FDR、年度一致性和OOS，"
                "结论就是没有稳定交互证据，不继续搜索阈值。"
            ),
            "",
            "## 探索性分层",
            "",
            f"- 事件类型级探索交互：`{len(exploratory)}`条，物理存放于独立表。",
            "- 探索结果不参与READY裁决，也不得在看过结果后改写为预注册主假设。",
            "",
            "## 当前样本映射",
            "",
        ]
    )
    if latest_episodes.empty:
        lines.append("- 当前没有可映射episode。")
    else:
        for row in latest_episodes.itertuples(index=False):
            lines.append(
                f"- `{row.episode_start_date}`至`{row.episode_end_date}` "
                f"`{row.main_contract}` `{row.event_type}`/"
                f"`{row.event_direction}`：阶段`{row.market_stage}`，周期`{row.contract_cycle}`，"
                f"到期桶`{row.expiry_bucket}`，移仓`{row.roll_context}`，"
                f"棉花年度`{row.cotton_year}`，趋势阶段`{row.trend_phase}`。"
            )
    lines.extend(
        [
            "- 当前样本没有成熟forward label时，只作结构映射，不进入胜负统计。",
            "",
            "## 研究边界与人审项",
            "",
            "- forward return只用于历史后验验证；episode特征表不含未来收益、执行日或退出日。",
            "- 基本面和政策只进入具名上下文表，`used_in_direction_test=false`，不生成方向信号。",
            "- 公开期权OI不能识别多空所有权、产业身份或dealer gamma；IV/Greek仍是研究proxy。",
            "- 本报告不构成交易指令，不自动反转方向，不修改signal matrix、composite_score或仓位。",
            "- `HUMAN_REVIEW_REQUIRED`：阶段边界、episode去重、到期/移仓解释、FDR和OOS解释。",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _usable_directional(validation: pd.DataFrame) -> pd.DataFrame:
    available = validation["forward_label_available"].fillna(False).astype(bool)
    direction = validation["event_direction"].isin(["long", "short"])
    returns = pd.to_numeric(validation["directional_return"], errors="coerce").notna()
    working = validation.loc[available & direction & returns].copy()
    working["posterior_hit"] = working["checkpoint_outcome"].eq("CONTINUATION")
    return working


def _interaction_cells(
    *,
    universe: pd.DataFrame,
    stage: str,
    dimension: str,
    level: str,
) -> dict[str, pd.DataFrame]:
    stage_mask = universe["market_stage"].eq(stage)
    level_mask = universe[dimension].astype(str).eq(level)
    return {
        "target_level": universe.loc[stage_mask & level_mask],
        "target_other": universe.loc[stage_mask & ~level_mask],
        "other_level": universe.loc[~stage_mask & level_mask],
        "other_other": universe.loc[~stage_mask & ~level_mask],
    }


def _level_and_control(
    frame: pd.DataFrame, *, dimension: str, level: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = frame[dimension].astype(str).eq(level)
    return frame.loc[mask], frame.loc[~mask]


def _binary_metrics(group: pd.DataFrame) -> dict[str, float | int]:
    count = len(group)
    successes = int(group.get("posterior_hit", pd.Series(dtype=bool)).fillna(False).sum())
    directional = pd.to_numeric(
        group.get("directional_return", pd.Series(dtype=float)), errors="coerce"
    ).dropna()
    return {
        "sample_count": count,
        "success_count": successes,
        "hit_rate": _ratio(successes, count),
        "mean_directional_return": _mean(directional),
        "median_directional_return": _median(directional),
    }


def _prefixed(values: dict[str, object], prefix: str) -> dict[str, object]:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def _interaction_permutation_p_value(
    *,
    universe: pd.DataFrame,
    stage: str,
    dimension: str,
    level: str,
    permutation_count: int,
    random_seed: int,
    min_cell_size: int,
) -> float:
    working = universe[["market_stage", dimension, "directional_return"]].copy()
    working = working.dropna(subset=["directional_return"])
    working["stage_flag"] = working["market_stage"].eq(stage)
    working["level_flag"] = working[dimension].astype(str).eq(level)
    counts = working.groupby(["stage_flag", "level_flag"]).size()
    cell_keys = (
        (stage_flag, level_flag)
        for stage_flag in (False, True)
        for level_flag in (False, True)
    )
    if any(int(counts.get(key, 0)) < min_cell_size for key in cell_keys):
        return math.nan
    observed = _did_mean(
        pd.to_numeric(working["directional_return"], errors="coerce").to_numpy(float),
        working["stage_flag"].to_numpy(bool),
        working["level_flag"].to_numpy(bool),
    )
    if not math.isfinite(observed):
        return math.nan
    rng = np.random.default_rng(random_seed)
    values = pd.to_numeric(working["directional_return"], errors="coerce").to_numpy(float)
    stage_flags = working["stage_flag"].to_numpy(bool)
    original_levels = working["level_flag"].to_numpy(bool)
    extreme = 0
    for _ in range(permutation_count):
        shuffled = original_levels.copy()
        for stage_flag in (False, True):
            positions = np.flatnonzero(stage_flags == stage_flag)
            shuffled[positions] = rng.permutation(shuffled[positions])
        candidate = _did_mean(values, stage_flags, shuffled)
        if math.isfinite(candidate) and abs(candidate) >= abs(observed) - 1e-15:
            extreme += 1
    return (extreme + 1) / (permutation_count + 1)


def _did_mean(values: np.ndarray, stages: np.ndarray, levels: np.ndarray) -> float:
    means: dict[tuple[bool, bool], float] = {}
    for stage in (False, True):
        for level in (False, True):
            cell = values[(stages == stage) & (levels == level)]
            if not len(cell):
                return math.nan
            means[(stage, level)] = float(np.mean(cell))
    target = means[(True, True)] - means[(True, False)]
    other = means[(False, True)] - means[(False, False)]
    return target - other


def _annual_interaction_rows(
    *,
    universe: pd.DataFrame,
    interaction_id: str,
    analysis_scope: str,
    base_column: str,
    base_value: str,
    direction: str,
    horizon: int,
    stage: str,
    dimension: str,
    level: str,
    run_id: str,
) -> list[dict[str, object]]:
    target = universe.loc[universe["market_stage"].eq(stage)]
    rows: list[dict[str, object]] = []
    for year, year_frame in target.groupby("calendar_year", sort=True):
        group, control = _level_and_control(year_frame, dimension=dimension, level=level)
        metrics = _binary_metrics(group)
        comparison = _binary_metrics(control)
        rows.append(
            {
                "run_id": run_id,
                "interaction_id": interaction_id,
                "analysis_scope": analysis_scope,
                "base_dimension": base_column,
                "base_value": base_value,
                "event_direction": direction,
                "horizon": horizon,
                "market_stage": stage,
                "interaction_dimension": dimension,
                "interaction_level": level,
                "calendar_year": int(year),
                "group_sample_count": metrics["sample_count"],
                "control_sample_count": comparison["sample_count"],
                "group_hit_rate": metrics["hit_rate"],
                "control_hit_rate": comparison["hit_rate"],
                "delta_hit_rate": metrics["hit_rate"] - comparison["hit_rate"],
                "group_mean_directional_return": metrics["mean_directional_return"],
                "control_mean_directional_return": comparison["mean_directional_return"],
                "delta_mean_directional_return": (
                    metrics["mean_directional_return"]
                    - comparison["mean_directional_return"]
                ),
                "forward_returns_are_historical_posterior_labels": True,
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return rows


def _annual_summary(
    annual_rows: list[dict[str, object]], overall_delta: float
) -> dict[str, object]:
    comparable = [
        row
        for row in annual_rows
        if int(row["group_sample_count"]) >= 2
        and int(row["control_sample_count"]) >= 2
        and math.isfinite(float(row["delta_mean_directional_return"]))
    ]
    consistent = sum(
        _same_nonzero_sign(float(row["delta_mean_directional_return"]), overall_delta)
        for row in comparable
    )
    return {
        "annual_comparable_years": len(comparable),
        "annual_consistent_years": consistent,
        "annual_sign_consistency_rate": _ratio(consistent, len(comparable)),
    }


def _main_effect_status(
    row: pd.Series, *, min_sample_size: int, fdr_level: float
) -> str:
    if (
        int(row["stage_sample_count"]) < min_sample_size
        or int(row["other_stage_sample_count"]) < min_sample_size
    ):
        return "WEAK_OR_SMALL_SAMPLE"
    hit_delta = _float(row["delta_hit_rate"])
    return_delta = _float(row["delta_mean_directional_return"])
    significant = _float(row["fdr_q_value"]) <= fdr_level
    if significant and hit_delta > 0 and return_delta > 0:
        return "STAGE_MAIN_EFFECT_POSITIVE"
    if significant and hit_delta < 0 and return_delta < 0:
        return "STAGE_MAIN_EFFECT_NEGATIVE"
    return "NO_STABLE_STAGE_MAIN_EFFECT"


def _interaction_status(
    row: pd.Series,
    *,
    min_sample_size: int,
    min_cell_size: int,
    fdr_level: float,
    require_oos: bool,
) -> str:
    counts = [
        int(row["target_stage_level_sample_count"]),
        int(row["target_stage_control_sample_count"]),
        int(row["other_stage_level_sample_count"]),
        int(row["other_stage_control_sample_count"]),
    ]
    if any(value == 0 for value in counts):
        return "COLLINEAR_OR_NO_OVERLAP"
    enough = (
        counts[0] >= min_sample_size
        and counts[1] >= min_sample_size
        and counts[2] >= min_cell_size
        and counts[3] >= min_cell_size
    )
    if not enough:
        return "WEAK_OR_SMALL_SAMPLE"
    target_hit = _float(row["target_stage_delta_hit_rate"])
    target_return = _float(row["target_stage_delta_mean_return"])
    interaction_hit = _float(row["interaction_delta_hit_rate"])
    interaction_return = _float(row["interaction_delta_mean_return"])
    effects = (target_hit, target_return, interaction_hit, interaction_return)
    positive = all(value > 0 for value in effects)
    negative = all(value < 0 for value in effects)
    fdr_pass = (
        _float(row["fisher_fdr_q_value"]) <= fdr_level
        and _float(row["permutation_fdr_q_value"]) <= fdr_level
    )
    annual_pass = (
        int(row["annual_comparable_years"]) >= 2
        and _float(row["annual_sign_consistency_rate"]) >= 0.75
    )
    oos_pass = (
        not require_oos
        or (
            int(row.get("oos_support_count", 0)) >= 2
            and int(row.get("oos_contradict_count", 0)) == 0
        )
    )
    if fdr_pass and annual_pass and oos_pass and positive:
        return "READY_POSITIVE_INTERACTION"
    if fdr_pass and annual_pass and oos_pass and negative:
        return "READY_NEGATIVE_INTERACTION"
    watch_fdr = min(
        _float(row["fisher_fdr_q_value"]),
        _float(row["permutation_fdr_q_value"]),
    ) <= 0.25
    watch_oos = (
        not require_oos
        or (
            int(row.get("oos_support_count", 0)) >= 1
            and int(row.get("oos_contradict_count", 0)) == 0
        )
    )
    if positive and watch_fdr and annual_pass and watch_oos:
        return "WATCH_POSITIVE_INTERACTION"
    if negative and watch_fdr and annual_pass and watch_oos:
        return "WATCH_NEGATIVE_INTERACTION"
    if positive:
        return "DESCRIPTIVE_POSITIVE_PATTERN"
    if negative:
        return "DESCRIPTIVE_NEGATIVE_PATTERN"
    return "INCONCLUSIVE"


def _calendar_market_stage(value: date) -> str:
    if value.year <= 2021:
        return "EARLY_THIN"
    if value.year <= 2023:
        return "EXPANSION"
    return "MATURE_ACTIVE"


def _event_family(event_type: object) -> str:
    value = str(event_type)
    if value in {"CALL_APPROACH", "CALL_TOUCH", "CALL_BREAKOUT", "CALL_WALL_MIGRATION"}:
        return "CALL_WALL_PATH"
    if value in {"PUT_APPROACH", "PUT_TOUCH", "PUT_BREAKOUT", "PUT_WALL_MIGRATION"}:
        return "PUT_WALL_PATH"
    if value.startswith("LOCAL_CALL_"):
        return "CALL_OI_CHANGE"
    if value.startswith("LOCAL_PUT_"):
        return "PUT_OI_CHANGE"
    if value.startswith("WALL_RANGE_"):
        return "WALL_RANGE"
    if value == "FUTURES_OPTION_DIVERGENCE":
        return "FUTURES_OPTION_DIVERGENCE"
    return "OTHER"


def _contract_cycle(value: object) -> str:
    text = str(value).upper()
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) < 2:
        return "UNKNOWN_CYCLE"
    month = int(digits[-2:])
    return {1: "JAN_CYCLE", 5: "MAY_CYCLE", 9: "SEP_CYCLE"}.get(
        month, "OTHER_MONTH"
    )


def _chain_path_label(event_types: list[str]) -> str:
    unique = _ordered_unique(event_types)
    if _ordered_contains(unique, ["CALL_APPROACH", "CALL_TOUCH", "CALL_BREAKOUT"]):
        return "CALL_APPROACH_TOUCH_BREAKOUT"
    if _ordered_contains(unique, ["PUT_APPROACH", "PUT_TOUCH", "PUT_BREAKOUT"]):
        return "PUT_APPROACH_TOUCH_BREAKOUT"
    if any(value.endswith("BUILD") for value in unique) and any(
        "MIGRATION" in value for value in unique
    ) and any(value.endswith("UNWIND") for value in unique):
        return "BUILD_MIGRATION_UNWIND"
    if "WALL_RANGE_NARROWING" in unique and "WALL_RANGE_WIDENING" in unique:
        return "RANGE_NARROW_TO_WIDEN"
    if len(unique) == 1:
        return "SINGLE_EVENT_TYPE"
    return "MIXED_OR_PARTIAL_CHAIN"


def _ordered_contains(values: list[str], expected: list[str]) -> bool:
    position = -1
    for item in expected:
        try:
            position = values.index(item, position + 1)
        except ValueError:
            return False
    return True


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _latest_episode_mapping(episodes: pd.DataFrame) -> dict[str, object]:
    if episodes.empty:
        return {"episode_count": 0, "contains_future_label": False}
    return {
        "event_date": episodes["episode_end_date"].max(),
        "episode_count": len(episodes),
        "event_types": sorted(episodes["event_type"].astype(str).unique()),
        "main_contracts": sorted(episodes["main_contract"].astype(str).unique()),
        "market_stages": sorted(episodes["market_stage"].astype(str).unique()),
        "contains_future_label": False,
    }


def _fisher_exact_two_sided(
    *,
    group_successes: int,
    group_count: int,
    comparison_successes: int,
    comparison_count: int,
) -> float:
    if group_count <= 0 or comparison_count <= 0:
        return 1.0
    total = group_count + comparison_count
    total_successes = group_successes + comparison_successes
    observed = _hypergeometric_probability(
        group_successes, group_count, total_successes, total
    )
    minimum = max(0, group_count - (total - total_successes))
    maximum = min(group_count, total_successes)
    probability = 0.0
    for successes in range(minimum, maximum + 1):
        candidate = _hypergeometric_probability(
            successes, group_count, total_successes, total
        )
        if candidate <= observed + 1e-12:
            probability += candidate
    return min(1.0, probability)


def _hypergeometric_probability(
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


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    normalized = [value if math.isfinite(value) else 1.0 for value in p_values]
    order = sorted(range(len(normalized)), key=normalized.__getitem__)
    adjusted = [1.0] * len(normalized)
    running = 1.0
    count = len(normalized)
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = count - reverse_rank + 1
        running = min(running, normalized[index] * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _stable_seed(base_seed: int, value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return (base_seed + int(digest[:8], 16)) % (2**32 - 1)


def _date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def _ratio(numerator: int, denominator: int) -> float:
    return math.nan if denominator <= 0 else numerator / denominator


def _mean(values: pd.Series) -> float:
    return math.nan if values.empty else float(values.mean())


def _median(values: pd.Series) -> float:
    return math.nan if values.empty else float(values.median())


def _float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _same_nonzero_sign(left: float, right: float) -> bool:
    return (
        math.isfinite(left)
        and math.isfinite(right)
        and left != 0
        and right != 0
        and left * right > 0
    )


def _opposite_nonzero_sign(left: float, right: float) -> bool:
    return (
        math.isfinite(left)
        and math.isfinite(right)
        and left != 0
        and right != 0
        and left * right < 0
    )
