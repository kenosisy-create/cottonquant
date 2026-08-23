"""R93P 期货-期权事件路径、解决周期与样本外研究。

本模块只消费 R93N 已冻结的 T 日事件表和物理分离的历史后验标签表。
它的职责是回答“事件发生后通常如何演变、多久出现方向性解决”，而不是
增加新的期权墙阈值或修改主信号。
"""

from __future__ import annotations

import itertools
import math
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
RULE_VERSION = "V5.1_R93P_futures_option_event_path_v1"
DEFAULT_HORIZONS = (1, 3, 5)
DEFAULT_DEAD_ZONE_BPS = 10
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_PURGE_GAP_SESSIONS = 5

EVENT_TYPES = (
    "CALL_APPROACH",
    "CALL_TOUCH",
    "CALL_BREAKOUT",
    "PUT_APPROACH",
    "PUT_TOUCH",
    "PUT_BREAKOUT",
    "LOCAL_CALL_BUILD",
    "LOCAL_CALL_UNWIND",
    "LOCAL_PUT_BUILD",
    "LOCAL_PUT_UNWIND",
    "CALL_WALL_MIGRATION",
    "PUT_WALL_MIGRATION",
    "WALL_RANGE_NARROWING",
    "WALL_RANGE_WIDENING",
    "FUTURES_OPTION_DIVERGENCE",
)

EVENT_POSTERIOR_COLUMNS = {
    "forward_return",
    "event_directional_return",
    "event_outcome",
    "event_hit",
    "event_mfe",
    "event_mae",
    "tbm_outcome",
    "tbm_first_hit_session",
    "wall_retest_flag",
    "wall_failure_flag",
    "path_event_label",
}
FEATURE_POSTERIOR_COLUMNS = {
    "forward_return",
    "event_outcome",
    "futures_outcome",
    "r48_outcome",
    "dynamic_outcome",
    "tbm_outcome_long",
    "tbm_outcome_short",
}

HUMAN_REVIEW_REQUIRED = (
    "event_direction_semantics_are_frozen_R93N_labels",
    "option_open_interest_long_short_ownership_unknown",
    "option_iv_and_greek_are_research_proxies",
    "fixed_checkpoint_is_not_intraday_resolution",
    "purged_leave_one_year_out_interpretation",
    "event_path_multiple_testing_and_fdr_interpretation",
    "contract_roll_and_expiry_bucket_interpretation",
)

RESEARCH_BOUNDARY = {
    "features_use_t_or_earlier": True,
    "forward_returns_are_historical_posterior_labels": True,
    "t_plus_one_execution": True,
    "fixed_checkpoints_are_not_intraday_path": True,
    "event_direction_is_not_reinterpreted": True,
    "option_open_interest_ownership_is_unknown": True,
    "dealer_gamma_is_not_inferred": True,
    "option_iv_and_greek_are_research_proxies": True,
    "promotion_eligible": False,
    "realtime_rule_eligible": False,
    "enters_composite_score": False,
    "changes_strategy_direction_or_sizing": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class FuturesOptionEventPathWarningRecord:
    """R93P 数据与解释边界告警。"""

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
class ResearchFuturesOptionEventPathResult:
    """R93P 研究产物路径与核心计数。"""

    run_id: str
    start: date
    end: date
    status: str
    event_row_count: int
    checkpoint_row_count: int
    path_row_count: int
    event_type_summary_row_count: int
    stratum_summary_row_count: int
    cooccurrence_row_count: int
    resolution_row_count: int
    oos_row_count: int
    latest_event_count: int
    predictive_watch_count: int
    warning_records: tuple[FuturesOptionEventPathWarningRecord, ...]
    event_path: Path
    event_lifecycle_label_path: Path
    feature_path: Path | None
    checkpoint_parquet_path: Path
    checkpoint_csv_path: Path
    path_parquet_path: Path
    path_csv_path: Path
    event_summary_parquet_path: Path
    event_summary_csv_path: Path
    stratum_summary_parquet_path: Path
    stratum_summary_csv_path: Path
    frequency_parquet_path: Path
    frequency_csv_path: Path
    cooccurrence_parquet_path: Path
    cooccurrence_csv_path: Path
    resolution_parquet_path: Path
    resolution_csv_path: Path
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
            "event_row_count": self.event_row_count,
            "checkpoint_row_count": self.checkpoint_row_count,
            "path_row_count": self.path_row_count,
            "event_type_summary_row_count": self.event_type_summary_row_count,
            "stratum_summary_row_count": self.stratum_summary_row_count,
            "frequency_row_count": self.frequency_row_count,
            "cooccurrence_row_count": self.cooccurrence_row_count,
            "resolution_row_count": self.resolution_row_count,
            "oos_row_count": self.oos_row_count,
            "latest_event_count": self.latest_event_count,
            "predictive_watch_count": self.predictive_watch_count,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "event_path": str(self.event_path),
            "event_lifecycle_label_path": str(self.event_lifecycle_label_path),
            "feature_path": None if self.feature_path is None else str(self.feature_path),
            "checkpoint_parquet_path": str(self.checkpoint_parquet_path),
            "path_parquet_path": str(self.path_parquet_path),
            "event_summary_parquet_path": str(self.event_summary_parquet_path),
            "stratum_summary_parquet_path": str(self.stratum_summary_parquet_path),
            "frequency_parquet_path": str(self.frequency_parquet_path),
            "cooccurrence_parquet_path": str(self.cooccurrence_parquet_path),
            "resolution_parquet_path": str(self.resolution_parquet_path),
            "oos_parquet_path": str(self.oos_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "features_use_t_or_earlier": True,
            "historical_returns_are_posterior_labels": True,
            "promotion_eligible": False,
            "realtime_rule_eligible": False,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }

    @property
    def frequency_row_count(self) -> int:
        """保留频率表计数为属性，避免 dataclass 字段重复维护。"""

        return _read_row_count(self.frequency_parquet_path)


def build_cf_futures_option_event_path_research(
    *,
    event_path: Path | None = None,
    event_lifecycle_label_path: Path | None = None,
    feature_path: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    purge_gap_sessions: int = DEFAULT_PURGE_GAP_SESSIONS,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchFuturesOptionEventPathResult:
    """构建 R93P 事件路径、解决时点、分层与 purged LOO 证据。"""

    normalized_horizons = _validate_parameters(
        horizons=horizons,
        dead_zone_bps=dead_zone_bps,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        purge_gap_sessions=purge_gap_sessions,
    )
    event_input = event_path or _latest_input(
        "futures_option_dynamic_wall",
        "CF_*_futures_option_dynamic_wall_event_daily.parquet",
        "R93N event table",
    )
    label_input = event_lifecycle_label_path or _latest_input(
        "futures_option_dynamic_wall",
        "CF_*_futures_option_dynamic_wall_event_lifecycle_label.parquet",
        "R93N event lifecycle label",
    )
    explicit_feature = feature_path is not None
    feature_input = feature_path or _optional_latest_input(
        "futures_option_dynamic_wall",
        "CF_*_futures_option_dynamic_wall_feature_daily.parquet",
    )

    events = _load_event_table(event_input)
    labels = _load_label_table(label_input, normalized_horizons)
    feature_frame = _load_feature_table(feature_input) if feature_input else None
    _validate_run_lineage(events, labels, feature_frame)

    effective_start = start or events["event_date"].min()
    effective_end = end or events["event_date"].max()
    if effective_start > effective_end:
        raise ResearchWorkbenchError("R93P start不能晚于end")
    events = events.loc[events["event_date"].between(effective_start, effective_end)].copy()
    if events.empty:
        raise ResearchWorkbenchError("R93P日期过滤后没有事件")
    labels = labels.loc[labels["event_id"].isin(events["event_id"])].copy()
    if feature_frame is not None:
        feature_frame = feature_frame.loc[
            feature_frame["trade_date"].between(effective_start, effective_end)
            | (feature_frame["trade_date"] > effective_end)
        ].copy()

    active_run_id = run_id or utc_timestamp_id("r93p_event_path", effective_end)
    session_dates = _session_dates(events, feature_frame)
    events = _prepare_event_context(events, session_dates)
    checkpoint = _build_checkpoint_table(
        events=events,
        labels=labels,
        horizons=normalized_horizons,
        dead_zone_bps=dead_zone_bps,
        run_id=active_run_id,
    )
    path_daily = _build_path_table(
        events=events,
        checkpoint=checkpoint,
        horizons=normalized_horizons,
        feature_frame=feature_frame,
        session_dates=session_dates,
        run_id=active_run_id,
    )
    frequency = _build_frequency_table(events, active_run_id)
    cooccurrence = _build_cooccurrence_table(events, active_run_id)
    event_summary = _build_summary_table(
        checkpoint=checkpoint,
        group_columns=("event_family", "event_type", "horizon"),
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        dead_zone_bps=dead_zone_bps,
        run_id=active_run_id,
    )
    stratum_summary = _build_summary_table(
        checkpoint=checkpoint,
        group_columns=(
            "event_family",
            "event_type",
            "horizon",
            "option_market_stage",
            "trend_phase",
            "expiry_bucket",
            "contract_cycle",
        ),
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        dead_zone_bps=dead_zone_bps,
        run_id=active_run_id,
    )
    resolution = _build_resolution_timing(
        path_daily=path_daily,
        horizons=normalized_horizons,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    oos = _build_purged_leave_one_year_out(
        checkpoint=checkpoint,
        min_sample_size=min_sample_size,
        dead_zone_bps=dead_zone_bps,
        purge_gap_sessions=purge_gap_sessions,
        run_id=active_run_id,
    )
    warnings = _build_warnings(
        run_id=active_run_id,
        events=events,
        labels=labels,
        checkpoint=checkpoint,
        path_daily=path_daily,
        event_summary=event_summary,
        stratum_summary=stratum_summary,
        oos=oos,
        feature_path=feature_input,
        explicit_feature=explicit_feature,
        horizons=normalized_horizons,
    )

    paths = _build_paths(
        start=events["event_date"].min(),
        end=events["event_date"].max(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_outputs(
        paths=paths,
        checkpoint=checkpoint,
        path_daily=path_daily,
        event_summary=event_summary,
        stratum_summary=stratum_summary,
        frequency=frequency,
        cooccurrence=cooccurrence,
        resolution=resolution,
        oos=oos,
        warnings=warnings,
    )

    latest_date = events["event_date"].max()
    latest_events = events.loc[events["event_date"].eq(latest_date)]
    predictive_watch_count = int(event_summary["predictive_evidence_status"].eq("WATCH_ONLY").sum())
    result = ResearchFuturesOptionEventPathResult(
        run_id=active_run_id,
        start=events["event_date"].min(),
        end=events["event_date"].max(),
        status="READY_WITH_WARNINGS" if any(w.severity == "WARN" for w in warnings) else "READY",
        event_row_count=len(events),
        checkpoint_row_count=len(checkpoint),
        path_row_count=len(path_daily),
        event_type_summary_row_count=len(event_summary),
        stratum_summary_row_count=len(stratum_summary),
        cooccurrence_row_count=len(cooccurrence),
        resolution_row_count=len(resolution),
        oos_row_count=len(oos),
        latest_event_count=len(latest_events),
        predictive_watch_count=predictive_watch_count,
        warning_records=tuple(warnings),
        event_path=event_input,
        event_lifecycle_label_path=label_input,
        feature_path=feature_input,
        checkpoint_parquet_path=paths["checkpoint_parquet"],
        checkpoint_csv_path=paths["checkpoint_csv"],
        path_parquet_path=paths["path_parquet"],
        path_csv_path=paths["path_csv"],
        event_summary_parquet_path=paths["event_summary_parquet"],
        event_summary_csv_path=paths["event_summary_csv"],
        stratum_summary_parquet_path=paths["stratum_summary_parquet"],
        stratum_summary_csv_path=paths["stratum_summary_csv"],
        frequency_parquet_path=paths["frequency_parquet"],
        frequency_csv_path=paths["frequency_csv"],
        cooccurrence_parquet_path=paths["cooccurrence_parquet"],
        cooccurrence_csv_path=paths["cooccurrence_csv"],
        resolution_parquet_path=paths["resolution_parquet"],
        resolution_csv_path=paths["resolution_csv"],
        oos_parquet_path=paths["oos_parquet"],
        oos_csv_path=paths["oos_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
    )
    _write_markdown(
        result=result,
        latest_events=latest_events,
        event_summary=event_summary,
        resolution=resolution,
        oos=oos,
        frequency=frequency,
        cooccurrence=cooccurrence,
    )
    write_json(
        result.json_path,
        {
            "report_type": "cf_futures_option_event_path_research",
            "rule_version": RULE_VERSION,
            "summary": result.to_summary(),
            "latest_event_mapping": _latest_event_mapping(latest_events),
            "research_boundary": RESEARCH_BOUNDARY,
            "parameters": {
                "horizons": list(normalized_horizons),
                "dead_zone_bps": dead_zone_bps,
                "min_sample_size": min_sample_size,
                "fdr_level": fdr_level,
                "purge_gap_sessions": purge_gap_sessions,
            },
        },
    )
    manifest = artifact_manifest(
        run_id=active_run_id,
        report_type="cf_futures_option_event_path_research",
        rule_version=RULE_VERSION,
        data_asof=result.end,
        input_paths={
            "event_path": event_input,
            "event_lifecycle_label_path": label_input,
            "feature_path": feature_input,
        },
        output_paths={
            "checkpoint_parquet_path": result.checkpoint_parquet_path,
            "path_parquet_path": result.path_parquet_path,
            "event_summary_parquet_path": result.event_summary_parquet_path,
            "stratum_summary_parquet_path": result.stratum_summary_parquet_path,
            "frequency_parquet_path": result.frequency_parquet_path,
            "cooccurrence_parquet_path": result.cooccurrence_parquet_path,
            "resolution_parquet_path": result.resolution_parquet_path,
            "oos_parquet_path": result.oos_parquet_path,
            "warning_csv_path": result.warning_csv_path,
            "markdown_path": result.markdown_path,
            "json_path": result.json_path,
        },
        human_review_required=HUMAN_REVIEW_REQUIRED,
        research_boundary=RESEARCH_BOUNDARY,
    )
    write_json(result.manifest_path, manifest)
    return result


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    dead_zone_bps: int,
    min_sample_size: int,
    fdr_level: float,
    purge_gap_sessions: int,
) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in horizons)))
    if normalized != DEFAULT_HORIZONS:
        raise ResearchWorkbenchError("R93P horizons固定为1,3,5，避免事后选择检查点")
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("R93P dead_zone_bps不能为负数")
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("R93P min_sample_size必须为正数")
    if not 0 < fdr_level < 1:
        raise ResearchWorkbenchError("R93P fdr_level必须位于0和1之间")
    if purge_gap_sessions < 0:
        raise ResearchWorkbenchError("R93P purge_gap_sessions不能为负数")
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


def _validate_run_lineage(
    events: pd.DataFrame,
    labels: pd.DataFrame,
    feature: pd.DataFrame | None,
) -> None:
    """防止默认路径把不同R93N运行的表静默拼接。"""

    if "run_id" in events.columns and "run_id" in labels.columns:
        event_runs = set(events["run_id"].dropna().astype(str))
        label_runs = set(labels["run_id"].dropna().astype(str))
        if event_runs and label_runs and not event_runs.intersection(label_runs):
            raise ResearchWorkbenchError("R93P event与lifecycle label不属于同一R93N运行")
    if feature is not None and "run_id" in events.columns and "run_id" in feature.columns:
        event_runs = set(events["run_id"].dropna().astype(str))
        feature_runs = set(feature["run_id"].dropna().astype(str))
        if event_runs and feature_runs and not event_runs.intersection(feature_runs):
            raise ResearchWorkbenchError("R93P event与feature不属于同一R93N运行")


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
        "dynamic_pressure_node",
        "joint_futures_option_node",
        "futures_direction_5d",
        "option_pressure_direction",
        "event_trigger_observable_at_t",
        "contains_posterior_outcome",
    }
    frame = load_table(path, required=required, label="R93P R93N event")
    working = frame.copy()
    working["event_date"] = _date_series(working["event_date"])
    working = working.dropna(subset=["event_date", "event_id"])
    if working.empty:
        raise ResearchWorkbenchError("R93P R93N event表为空")
    if working["event_id"].duplicated().any():
        raise ResearchWorkbenchError("R93P event_id存在重复，无法唯一追踪事件路径")
    if not working["event_trigger_observable_at_t"].fillna(False).astype(bool).all():
        raise ResearchWorkbenchError("R93P event表含非T日可观察事件")
    if working["contains_posterior_outcome"].fillna(False).astype(bool).any():
        raise ResearchWorkbenchError("R93P event表含后验结果标记")
    overlap = sorted(EVENT_POSTERIOR_COLUMNS.intersection(working.columns))
    if overlap:
        raise ResearchWorkbenchError(f"R93P event表混入后验字段: {overlap}")
    working["event_type"] = working["event_type"].astype(str)
    working["event_family"] = working["event_type"].map(_event_family)
    return working.sort_values(["event_date", "event_id"]).reset_index(drop=True)


def _load_label_table(path: Path, horizons: tuple[int, ...]) -> pd.DataFrame:
    required = {
        "event_id",
        "event_date",
        "event_type",
        "event_direction",
        "horizon",
        "execution_date",
        "exit_date",
        "forward_return",
        "event_directional_return",
        "event_outcome",
        "event_hit",
        "event_mfe",
        "event_mae",
        "tbm_outcome",
        "tbm_first_hit_session",
        "wall_retest_flag",
        "wall_failure_flag",
        "path_event_label",
        "forward_label_available",
        "forward_returns_are_historical_posterior_labels",
    }
    frame = load_table(path, required=required, label="R93P R93N event lifecycle label")
    working = frame.copy()
    for column in ("event_date", "execution_date", "exit_date"):
        working[column] = _date_series(working[column])
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    working = working.loc[working["horizon"].isin(horizons)].copy()
    if working.empty:
        raise ResearchWorkbenchError("R93P标签表没有1D/3D/5D记录")
    if (
        not working["forward_returns_are_historical_posterior_labels"]
        .fillna(False)
        .astype(bool)
        .all()
    ):
        raise ResearchWorkbenchError("R93P标签表未声明为历史后验标签")
    available = working["forward_label_available"].fillna(False).astype(bool)
    invalid_timing = available & (
        working["execution_date"].isna() | (working["execution_date"] <= working["event_date"])
    )
    if invalid_timing.any():
        raise ResearchWorkbenchError("R93P标签违反T+1执行约束")
    if working.duplicated(["event_id", "horizon"]).any():
        raise ResearchWorkbenchError("R93P event lifecycle label存在event_id+horizon重复")
    return working.reset_index(drop=True)


def _load_feature_table(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    required = {"trade_date", "main_contract"}
    frame = load_table(path, required=required, label="R93P R93N feature")
    overlap = sorted(FEATURE_POSTERIOR_COLUMNS.intersection(frame.columns))
    if overlap:
        raise ResearchWorkbenchError(f"R93P feature表混入后验字段: {overlap}")
    if (
        "contains_posterior_outcome" in frame.columns
        and frame["contains_posterior_outcome"].fillna(False).astype(bool).any()
    ):
        raise ResearchWorkbenchError("R93P feature表含后验结果标记")
    if (
        "feature_uses_t_or_earlier" in frame.columns
        and not frame["feature_uses_t_or_earlier"].fillna(False).astype(bool).all()
    ):
        raise ResearchWorkbenchError("R93P feature表未声明为T日可观察特征")
    if not {"trend_phase", "phase_v2"}.intersection(frame.columns):
        raise ResearchWorkbenchError("R93P feature表缺少trend_phase或phase_v2")
    working = frame.copy()
    working["trade_date"] = _date_series(working["trade_date"])
    working = working.dropna(subset=["trade_date"]).sort_values("trade_date")
    if working["trade_date"].duplicated().any():
        raise ResearchWorkbenchError("R93P feature表每个交易日必须唯一")
    return working.reset_index(drop=True)


def _session_dates(events: pd.DataFrame, feature: pd.DataFrame | None) -> list[date]:
    values = set(events["event_date"].dropna())
    if feature is not None:
        values.update(feature["trade_date"].dropna())
    return sorted(values)


def _prepare_event_context(events: pd.DataFrame, session_dates: list[date]) -> pd.DataFrame:
    working = events.copy()
    date_index = {value: index for index, value in enumerate(session_dates)}
    working["session_index"] = working["event_date"].map(date_index)
    working["calendar_year"] = pd.to_datetime(working["event_date"]).dt.year.astype(int)
    working["contract_cycle"] = working["main_contract"].map(_contract_cycle)
    grouped = working.groupby("observation_id", sort=False)
    co_types = grouped["event_type"].agg(lambda values: ";".join(sorted(set(values.astype(str)))))
    co_count = grouped["event_type"].nunique()
    working["cooccurring_event_types"] = working["observation_id"].map(co_types)
    working["cooccurring_event_count"] = working["observation_id"].map(co_count).astype(int)
    return working


def _build_checkpoint_table(
    *,
    events: pd.DataFrame,
    labels: pd.DataFrame,
    horizons: tuple[int, ...],
    dead_zone_bps: int,
    run_id: str,
) -> pd.DataFrame:
    label_columns = [
        "event_id",
        "horizon",
        "execution_date",
        "exit_date",
        "forward_return",
        "event_directional_return",
        "event_outcome",
        "event_hit",
        "event_mfe",
        "event_mae",
        "tbm_outcome",
        "tbm_first_hit_session",
        "wall_retest_flag",
        "wall_failure_flag",
        "path_event_label",
        "forward_label_available",
    ]
    available_labels = labels.loc[labels["horizon"].isin(horizons), label_columns].copy()
    rows: list[pd.DataFrame] = []
    for horizon in horizons:
        current = available_labels.loc[available_labels["horizon"].eq(horizon)].copy()
        current = current.rename(
            columns={
                column: f"label_{column}"
                for column in label_columns
                if column not in {"event_id", "horizon"}
            }
        )
        current = current.rename(columns={"label_horizon": "horizon"})
        base = events.copy()
        base["horizon"] = horizon
        merged = base.merge(current, on=["event_id", "horizon"], how="left", validate="one_to_one")
        merged["run_id"] = run_id
        merged["dead_zone_bps"] = dead_zone_bps
        merged["checkpoint_outcome"] = merged.apply(
            lambda row: _checkpoint_outcome(
                row.get("label_event_outcome"),
                row.get("event_direction"),
                row.get("label_forward_label_available"),
            ),
            axis=1,
        )
        merged["checkpoint_resolved"] = merged["checkpoint_outcome"].isin(
            ["CONTINUATION", "REVERSAL"]
        )
        rows.append(merged)
    if not rows:
        return pd.DataFrame()
    return (
        pd.concat(rows, ignore_index=True)
        .sort_values(["event_date", "event_id", "horizon"])
        .reset_index(drop=True)
    )


def _build_path_table(
    *,
    events: pd.DataFrame,
    checkpoint: pd.DataFrame,
    horizons: tuple[int, ...],
    feature_frame: pd.DataFrame | None,
    session_dates: list[date],
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event in events.itertuples(index=False):
        current = checkpoint.loc[checkpoint["event_id"].eq(event.event_id)]
        row = {column: getattr(event, column) for column in events.columns}
        state_map = _path_state_for_event(
            event_date=event.event_date,
            event_id=str(event.event_id),
            event_contract=str(event.main_contract),
            feature=feature_frame,
            session_dates=session_dates,
            horizons=horizons,
        )
        row["run_id"] = run_id
        row["contains_posterior_outcome"] = True
        row["forward_returns_are_historical_posterior_labels"] = True
        row["promotion_eligible"] = False
        row["trading_instruction"] = "not_a_trading_instruction"
        outcomes: list[str] = []
        resolution_horizon: int | None = None
        resolution_outcome: str | None = None
        for horizon in horizons:
            match = current.loc[current["horizon"].eq(horizon)]
            label = match.iloc[0] if not match.empty else None
            prefix = f"t_plus_{horizon}"
            for source, target in (
                ("label_forward_return", "forward_return"),
                ("label_event_directional_return", "directional_return"),
                ("label_event_outcome", "original_outcome"),
                ("label_event_hit", "hit"),
                ("label_event_mfe", "mfe"),
                ("label_event_mae", "mae"),
                ("label_tbm_outcome", "tbm_outcome"),
                ("label_tbm_first_hit_session", "tbm_first_hit_session"),
                ("label_wall_retest_flag", "wall_retest_flag"),
                ("label_wall_failure_flag", "wall_failure_flag"),
                ("label_forward_label_available", "forward_label_available"),
            ):
                row[f"{prefix}_{target}"] = None if label is None else label.get(source)
            outcome = (
                "UNAVAILABLE"
                if label is None
                else _checkpoint_outcome(
                    label.get("label_event_outcome"),
                    event.event_direction,
                    label.get("label_forward_label_available"),
                )
            )
            row[f"{prefix}_outcome"] = outcome
            if outcome in {"CONTINUATION", "REVERSAL"}:
                outcomes.append(outcome)
                if resolution_horizon is None:
                    resolution_horizon = horizon
                    resolution_outcome = outcome
            else:
                outcomes.append(outcome)
            for key, value in state_map.get(horizon, {}).items():
                row[f"{prefix}_{key}"] = value
        row["first_resolution_horizon"] = resolution_horizon
        row["first_resolution_outcome"] = resolution_outcome
        row["path_label"] = _path_label(outcomes, horizons)
        row["path_available_checkpoints"] = sum(value != "UNAVAILABLE" for value in outcomes)
        row["path_contract_match"] = _path_contract_match(row, horizons, event.main_contract)
        rows.append(row)
    return pd.DataFrame(rows)


def _path_state_for_event(
    *,
    event_date: date,
    event_id: str,
    event_contract: str,
    feature: pd.DataFrame | None,
    session_dates: list[date],
    horizons: tuple[int, ...],
) -> dict[int, dict[str, object]]:
    if feature is None:
        return {}
    date_index = {value: index for index, value in enumerate(session_dates)}
    base_index = date_index.get(event_date)
    if base_index is None:
        return {}
    feature_by_date = feature.set_index("trade_date", drop=False)
    output: dict[int, dict[str, object]] = {}
    for horizon in horizons:
        target_index = base_index + horizon
        if target_index >= len(session_dates):
            continue
        target_date = session_dates[target_index]
        if target_date not in feature_by_date.index:
            continue
        target = feature_by_date.loc[target_date]
        if isinstance(target, pd.DataFrame):
            target = target.iloc[0]
        output[horizon] = {
            "state_date": target_date,
            "state_main_contract": target.get("main_contract"),
            "state_trend_phase": target.get("trend_phase", target.get("phase_v2")),
            "state_dynamic_pressure_node": target.get("dynamic_pressure_node"),
            "state_option_pressure_direction": target.get("option_pressure_direction"),
            "state_primary_event_type": target.get("primary_event_type"),
            "state_contract_match": str(target.get("main_contract")) == str(event_contract),
            "state_observation_id": target.get("observation_id"),
            "state_event_id_source": event_id,
        }
    return output


def _build_frequency_table(events: pd.DataFrame, run_id: str) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=["run_id", "event_family", "event_type", "calendar_year", "event_count"]
        )
    rows: list[dict[str, object]] = []
    total_days = events["event_date"].nunique()
    for (family, event_type, year), group in events.groupby(
        ["event_family", "event_type", "calendar_year"], sort=True
    ):
        rows.append(
            {
                "run_id": run_id,
                "event_family": family,
                "event_type": event_type,
                "calendar_year": int(year),
                "event_count": len(group),
                "event_day_count": int(group["event_date"].nunique()),
                "share_of_event_days": (
                    int(group["event_date"].nunique()) / total_days if total_days else math.nan
                ),
                "option_market_stage": ";".join(
                    sorted(group["option_market_stage"].astype(str).unique())
                ),
                "forward_returns_are_historical_posterior_labels": False,
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows)


def _build_cooccurrence_table(events: pd.DataFrame, run_id: str) -> pd.DataFrame:
    columns = [
        "run_id",
        "event_type_left",
        "event_type_right",
        "event_family_left",
        "event_family_right",
        "cooccurrence_count",
        "cooccurrence_day_count",
        "share_of_event_days",
        "promotion_eligible",
        "trading_instruction",
    ]
    rows: list[dict[str, object]] = []
    total_days = events["event_date"].nunique()
    for (_observation_id, _event_date), group in events.groupby(
        ["observation_id", "event_date"], sort=False
    ):
        unique = sorted(set(group["event_type"].astype(str)))
        by_type = group.drop_duplicates("event_type").set_index("event_type")
        for left, right in itertools.combinations(unique, 2):
            rows.append(
                {
                    "run_id": run_id,
                    "event_type_left": left,
                    "event_type_right": right,
                    "event_family_left": by_type.loc[left, "event_family"],
                    "event_family_right": by_type.loc[right, "event_family"],
                    "cooccurrence_count": 1,
                    "cooccurrence_day_count": 1,
                    "share_of_event_days": 1 / total_days if total_days else math.nan,
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    if not rows:
        return pd.DataFrame(columns=columns)
    result = (
        pd.DataFrame(rows)
        .groupby(
            [
                "run_id",
                "event_type_left",
                "event_type_right",
                "event_family_left",
                "event_family_right",
            ],
            as_index=False,
        )
        .agg(
            cooccurrence_count=("cooccurrence_count", "sum"),
            cooccurrence_day_count=("cooccurrence_day_count", "sum"),
            share_of_event_days=("share_of_event_days", "sum"),
            promotion_eligible=("promotion_eligible", "min"),
            trading_instruction=("trading_instruction", "first"),
        )
    )
    return result[columns].sort_values("cooccurrence_count", ascending=False).reset_index(drop=True)


def _build_summary_table(
    *,
    checkpoint: pd.DataFrame,
    group_columns: tuple[str, ...],
    min_sample_size: int,
    fdr_level: float,
    dead_zone_bps: int,
    run_id: str,
) -> pd.DataFrame:
    columns = list(group_columns) + [
        "run_id",
        "sample_count",
        "available_count",
        "directional_count",
        "continuation_count",
        "reversal_count",
        "unresolved_count",
        "continuation_rate",
        "reversal_rate",
        "unresolved_rate",
        "resolved_count",
        "resolved_continuation_share",
        "mean_directional_return",
        "median_directional_return",
        "mean_mfe",
        "mean_mae",
        "retest_rate",
        "failure_rate",
        "mean_first_tbm_session",
        "annual_test_years",
        "annual_positive_years",
        "annual_positive_rate",
        "resolved_balance_p_value",
        "fdr_q_value",
        "evidence_level",
        "predictive_evidence_status",
        "evidence_role",
        "dead_zone_bps",
        "forward_returns_are_historical_posterior_labels",
        "promotion_eligible",
        "trading_instruction",
    ]
    if checkpoint.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for key, group in checkpoint.groupby(list(group_columns), dropna=False, sort=True):
        values = key if isinstance(key, tuple) else (key,)
        metrics = _checkpoint_metrics(group, min_sample_size=min_sample_size)
        row = dict(zip(group_columns, values, strict=True))
        row.update(metrics)
        row.update(
            {
                "run_id": run_id,
                "dead_zone_bps": dead_zone_bps,
                "forward_returns_are_historical_posterior_labels": True,
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
        rows.append(row)
    result = pd.DataFrame(rows)
    result["fdr_q_value"] = _assign_fdr(result["resolved_balance_p_value"])
    result["predictive_evidence_status"] = result.apply(
        lambda row: _predictive_status(row, min_sample_size=min_sample_size, fdr_level=fdr_level),
        axis=1,
    )
    return result.reindex(columns=columns).reset_index(drop=True)


def _checkpoint_metrics(group: pd.DataFrame, *, min_sample_size: int) -> dict[str, object]:
    available = group.loc[group["label_forward_label_available"].fillna(False).astype(bool)].copy()
    directional = pd.to_numeric(
        available["label_event_directional_return"], errors="coerce"
    ).dropna()
    outcomes = available["checkpoint_outcome"]
    continuation = int(outcomes.eq("CONTINUATION").sum())
    reversal = int(outcomes.eq("REVERSAL").sum())
    unresolved = int(outcomes.eq("UNRESOLVED").sum())
    resolved = continuation + reversal
    directional_available = continuation + reversal + unresolved
    annual_values: list[float] = []
    for _year, year_group in available.groupby("calendar_year", sort=True):
        year_returns = pd.to_numeric(
            year_group["label_event_directional_return"], errors="coerce"
        ).dropna()
        if not year_returns.empty:
            annual_values.append(float(year_returns.mean()))
    positive_years = sum(value > 0 for value in annual_values)
    first_sessions = pd.to_numeric(
        available["label_tbm_first_hit_session"], errors="coerce"
    ).dropna()
    return {
        "sample_count": len(group),
        "available_count": len(available),
        "directional_count": len(directional),
        "continuation_count": continuation,
        "reversal_count": reversal,
        "unresolved_count": unresolved,
        # 中性事件不进入方向性比例分母，避免把“无方向”误报成未解决。
        "continuation_rate": _ratio(continuation, directional_available),
        "reversal_rate": _ratio(reversal, directional_available),
        "unresolved_rate": _ratio(unresolved, directional_available),
        "resolved_count": resolved,
        "resolved_continuation_share": _ratio(continuation, resolved),
        "mean_directional_return": _mean(directional),
        "median_directional_return": _median(directional),
        "mean_mfe": _mean(pd.to_numeric(available["label_event_mfe"], errors="coerce").dropna()),
        "mean_mae": _mean(pd.to_numeric(available["label_event_mae"], errors="coerce").dropna()),
        "retest_rate": _bool_mean(available["label_wall_retest_flag"]),
        "failure_rate": _bool_mean(available["label_wall_failure_flag"]),
        "mean_first_tbm_session": _mean(first_sessions),
        "annual_test_years": len(annual_values),
        "annual_positive_years": positive_years,
        "annual_positive_rate": _ratio(positive_years, len(annual_values)),
        "resolved_balance_p_value": _binomial_two_sided(continuation, resolved),
        "evidence_level": _evidence_level(len(group), resolved, min_sample_size),
        "predictive_evidence_status": "PENDING_FDR",
        "evidence_role": "DESCRIPTIVE_EXPLANATORY_AND_PREDICTIVE_SCREEN",
    }


def _build_resolution_timing(
    *,
    path_daily: pd.DataFrame,
    horizons: tuple[int, ...],
    min_sample_size: int,
    run_id: str,
) -> pd.DataFrame:
    columns = [
        "run_id",
        "event_family",
        "event_type",
        "option_market_stage",
        "sample_count",
        "available_path_count",
        "resolved_by_1d_count",
        "resolved_by_3d_count",
        "resolved_by_5d_count",
        "resolved_by_5d_rate",
        "mean_first_resolution_horizon",
        "median_first_resolution_horizon",
        "continuation_first_count",
        "reversal_first_count",
        "unresolved_5d_count",
        "retest_rate_5d",
        "failure_rate_5d",
        "evidence_level",
        "forward_returns_are_historical_posterior_labels",
        "promotion_eligible",
        "trading_instruction",
    ]
    if path_daily.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for (family, event_type, stage), group in path_daily.groupby(
        ["event_family", "event_type", "option_market_stage"], dropna=False, sort=True
    ):
        first = pd.to_numeric(group["first_resolution_horizon"], errors="coerce").dropna()
        available = group["path_available_checkpoints"].gt(0)
        unresolved_5d = group.get("t_plus_5_outcome", pd.Series(dtype=object)).eq("UNRESOLVED")
        row = {
            "run_id": run_id,
            "event_family": family,
            "event_type": event_type,
            "option_market_stage": stage,
            "sample_count": len(group),
            "available_path_count": int(available.sum()),
            "resolved_by_1d_count": int(
                pd.to_numeric(group["first_resolution_horizon"], errors="coerce")
                .le(1)
                .fillna(False)
                .sum()
            ),
            "resolved_by_3d_count": int(
                pd.to_numeric(group["first_resolution_horizon"], errors="coerce")
                .le(3)
                .fillna(False)
                .sum()
            ),
            "resolved_by_5d_count": int(
                pd.to_numeric(group["first_resolution_horizon"], errors="coerce")
                .le(5)
                .fillna(False)
                .sum()
            ),
            "resolved_by_5d_rate": _ratio(int(first.size), len(group)),
            "mean_first_resolution_horizon": _mean(first),
            "median_first_resolution_horizon": _median(first),
            "continuation_first_count": int(
                group["first_resolution_outcome"].eq("CONTINUATION").sum()
            ),
            "reversal_first_count": int(group["first_resolution_outcome"].eq("REVERSAL").sum()),
            "unresolved_5d_count": int(unresolved_5d.sum()),
            "retest_rate_5d": _bool_mean(
                group.get("t_plus_5_wall_retest_flag", pd.Series(dtype=object))
            ),
            "failure_rate_5d": _bool_mean(
                group.get("t_plus_5_wall_failure_flag", pd.Series(dtype=object))
            ),
            "evidence_level": _evidence_level(len(group), int(first.size), min_sample_size),
            "forward_returns_are_historical_posterior_labels": True,
            "promotion_eligible": False,
            "trading_instruction": "not_a_trading_instruction",
        }
        rows.append(row)
    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values(["sample_count", "event_type"], ascending=[False, True])
        .reset_index(drop=True)
    )


def _build_purged_leave_one_year_out(
    *,
    checkpoint: pd.DataFrame,
    min_sample_size: int,
    dead_zone_bps: int,
    purge_gap_sessions: int,
    run_id: str,
) -> pd.DataFrame:
    columns = [
        "run_id",
        "event_family",
        "event_type",
        "horizon",
        "test_year",
        "test_year_is_partial",
        "train_sample_count",
        "test_sample_count",
        "purged_train_count",
        "purge_gap_sessions",
        "train_mean_directional_return",
        "test_mean_directional_return",
        "train_resolved_continuation_share",
        "test_resolved_continuation_share",
        "test_continuation_rate",
        "test_reversal_rate",
        "test_unresolved_rate",
        "train_screen_status",
        "oos_status",
        "forward_returns_are_historical_posterior_labels",
        "promotion_eligible",
        "trading_instruction",
    ]
    if checkpoint.empty:
        return pd.DataFrame(columns=columns)
    working = checkpoint.copy()
    years = sorted(
        pd.to_numeric(working["calendar_year"], errors="coerce").dropna().astype(int).unique()
    )
    rows: list[dict[str, object]] = []
    for (family, event_type, horizon), group in working.groupby(
        ["event_family", "event_type", "horizon"], sort=True
    ):
        for test_year in years:
            test = group.loc[group["calendar_year"].eq(test_year)].copy()
            if test.empty:
                continue
            test_sessions = pd.to_numeric(test["session_index"], errors="coerce").dropna()
            lower = int(test_sessions.min()) - purge_gap_sessions if not test_sessions.empty else -1
            upper = int(test_sessions.max()) + purge_gap_sessions if not test_sessions.empty else -1
            train = group.loc[~group["calendar_year"].eq(test_year)].copy()
            before_purge = len(train)
            train = train.loc[
                ~pd.to_numeric(train["session_index"], errors="coerce").between(lower, upper)
            ].copy()
            purged = before_purge - len(train)
            train_stats = _checkpoint_metrics(train, min_sample_size=min_sample_size)
            test_stats = _checkpoint_metrics(test, min_sample_size=min_sample_size)
            train_ready = (
                train_stats["directional_count"] >= min_sample_size
                and _is_finite_positive(train_stats["mean_directional_return"])
                and (
                    train_stats["resolved_continuation_share"] is not None
                    and train_stats["resolved_continuation_share"] > 0.5
                )
            )
            test_mean = test_stats["mean_directional_return"]
            train_mean = train_stats["mean_directional_return"]
            if test_stats["directional_count"] < min_sample_size:
                oos_status = "INSUFFICIENT_TEST"
            elif train_ready and _is_finite_positive(test_mean):
                oos_status = "SUPPORT"
            elif train_ready and test_mean is not None and test_mean < 0:
                oos_status = "CONTRADICT"
            else:
                oos_status = "INCONCLUSIVE"
            rows.append(
                {
                    "run_id": run_id,
                    "event_family": family,
                    "event_type": event_type,
                    "horizon": int(horizon),
                    "test_year": int(test_year),
                    "test_year_is_partial": int(test_year) == max(years),
                    "train_sample_count": int(train_stats["directional_count"]),
                    "test_sample_count": int(test_stats["directional_count"]),
                    "purged_train_count": int(purged),
                    "purge_gap_sessions": purge_gap_sessions,
                    "train_mean_directional_return": train_mean,
                    "test_mean_directional_return": test_mean,
                    "train_resolved_continuation_share": train_stats["resolved_continuation_share"],
                    "test_resolved_continuation_share": test_stats["resolved_continuation_share"],
                    "test_continuation_rate": test_stats["continuation_rate"],
                    "test_reversal_rate": test_stats["reversal_rate"],
                    "test_unresolved_rate": test_stats["unresolved_rate"],
                    "train_screen_status": "TRAIN_WATCH" if train_ready else "TRAIN_NOT_STABLE",
                    "oos_status": oos_status,
                    "forward_returns_are_historical_posterior_labels": True,
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows, columns=columns).reset_index(drop=True)


def _build_warnings(
    *,
    run_id: str,
    events: pd.DataFrame,
    labels: pd.DataFrame,
    checkpoint: pd.DataFrame,
    path_daily: pd.DataFrame,
    event_summary: pd.DataFrame,
    stratum_summary: pd.DataFrame,
    oos: pd.DataFrame,
    feature_path: Path | None,
    explicit_feature: bool,
    horizons: tuple[int, ...],
) -> list[FuturesOptionEventPathWarningRecord]:
    warnings: list[FuturesOptionEventPathWarningRecord] = []
    if feature_path is None:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "path_state",
                "WARN",
                "R93P_FEATURE_PATH_MISSING",
                "未找到R93N feature表，事件路径仍可计算收益检查点，但不输出后续状态迁移字段。",
                len(events),
                "fixed_checkpoint_is_not_intraday_resolution",
            )
        )
    elif explicit_feature and path_daily.filter(like="state_").empty:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "path_state",
                "WARN",
                "R93P_FEATURE_STATE_UNAVAILABLE",
                "指定的R93N feature表未能匹配后续交易日状态。",
                len(events),
                "fixed_checkpoint_is_not_intraday_resolution",
            )
        )
    available = checkpoint["label_forward_label_available"].fillna(False).astype(bool)
    unavailable = int((~available).sum())
    if unavailable:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "posterior_labels",
                "INFO",
                "R93P_FORWARD_LABEL_UNAVAILABLE",
                "最新事件缺少未来标签，已保留为当前结构映射，不进入历史胜负统计。",
                unavailable,
            )
        )
    unknown_types = int((~events["event_type"].isin(EVENT_TYPES)).sum())
    if unknown_types:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "event_definition",
                "WARN",
                "R93P_UNKNOWN_EVENT_TYPE",
                "事件类型不在固定R93N注册表内，已归入OTHER并单独标记。",
                unknown_types,
                "event_path_multiple_testing_and_fdr_interpretation",
            )
        )
    neutral = int((events["event_direction"].astype(str) == "neutral").sum())
    if neutral:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "directional_label",
                "INFO",
                "R93P_NEUTRAL_EVENT_SIDE",
                "中性事件不强行判定延续或反转，只进入频率和路径描述。",
                neutral,
                "event_direction_semantics_are_frozen_R93N_labels",
            )
        )
    if (
        len(event_summary)
        and not event_summary["predictive_evidence_status"].eq("WATCH_ONLY").any()
    ):
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "predictive_screen",
                "WARN",
                "R93P_NO_STABLE_PREDICTIVE_SCREEN",
                "固定事件与检查点未形成稳定的样本外预测候选；结果仍可用于历史解释。",
                len(event_summary),
                "purged_leave_one_year_out_interpretation",
            )
        )
    if oos.empty:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "oos",
                "WARN",
                "R93P_OOS_EMPTY",
                "年份不足或标签不足，无法形成purged leave-one-year-out表。",
                len(events),
                "purged_leave_one_year_out_interpretation",
            )
        )
    if len(stratum_summary) > len(event_summary) * 20:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "multiple_testing",
                "INFO",
                "R93P_STRATUM_MULTIPLE_TESTING",
                "分层组合较多，分层结果只作探索性描述，不能替代预注册主结果。",
                len(stratum_summary),
                "event_path_multiple_testing_and_fdr_interpretation",
            )
        )
    missing_horizons = [
        horizon for horizon in horizons if int(labels["horizon"].eq(horizon).sum()) == 0
    ]
    if missing_horizons:
        warnings.append(
            FuturesOptionEventPathWarningRecord(
                run_id,
                "posterior_labels",
                "WARN",
                "R93P_MISSING_HORIZON",
                f"标签表缺少检查点: {missing_horizons}",
                len(events),
                "fixed_checkpoint_is_not_intraday_resolution",
            )
        )
    return warnings


def _build_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_futures_option_event_path"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "futures_option_event_path"
    report_root = report_output_dir or reports_dir() / "research" / "futures_option_event_path"
    return {
        "checkpoint_parquet": data_root / f"{stem}_checkpoint_daily.parquet",
        "checkpoint_csv": data_root / f"{stem}_checkpoint_daily.csv",
        "path_parquet": data_root / f"{stem}_path_daily.parquet",
        "path_csv": data_root / f"{stem}_path_daily.csv",
        "event_summary_parquet": data_root / f"{stem}_summary_by_event_type.parquet",
        "event_summary_csv": data_root / f"{stem}_summary_by_event_type.csv",
        "stratum_summary_parquet": data_root / f"{stem}_summary_by_stratum.parquet",
        "stratum_summary_csv": data_root / f"{stem}_summary_by_stratum.csv",
        "frequency_parquet": data_root / f"{stem}_frequency.parquet",
        "frequency_csv": data_root / f"{stem}_frequency.csv",
        "cooccurrence_parquet": data_root / f"{stem}_cooccurrence.parquet",
        "cooccurrence_csv": data_root / f"{stem}_cooccurrence.csv",
        "resolution_parquet": data_root / f"{stem}_resolution_timing.parquet",
        "resolution_csv": data_root / f"{stem}_resolution_timing.csv",
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
    checkpoint: pd.DataFrame,
    path_daily: pd.DataFrame,
    event_summary: pd.DataFrame,
    stratum_summary: pd.DataFrame,
    frequency: pd.DataFrame,
    cooccurrence: pd.DataFrame,
    resolution: pd.DataFrame,
    oos: pd.DataFrame,
    warnings: list[FuturesOptionEventPathWarningRecord],
) -> None:
    write_frame(checkpoint, paths["checkpoint_parquet"], paths["checkpoint_csv"])
    write_frame(path_daily, paths["path_parquet"], paths["path_csv"])
    write_frame(event_summary, paths["event_summary_parquet"], paths["event_summary_csv"])
    write_frame(stratum_summary, paths["stratum_summary_parquet"], paths["stratum_summary_csv"])
    write_frame(frequency, paths["frequency_parquet"], paths["frequency_csv"])
    write_frame(cooccurrence, paths["cooccurrence_parquet"], paths["cooccurrence_csv"])
    write_frame(resolution, paths["resolution_parquet"], paths["resolution_csv"])
    write_frame(oos, paths["oos_parquet"], paths["oos_csv"])
    write_warning_csv(paths["warning_csv"], [item.to_summary() for item in warnings])


def _write_markdown(
    *,
    result: ResearchFuturesOptionEventPathResult,
    latest_events: pd.DataFrame,
    event_summary: pd.DataFrame,
    resolution: pd.DataFrame,
    oos: pd.DataFrame,
    frequency: pd.DataFrame,
    cooccurrence: pd.DataFrame,
) -> None:
    lines = [
        "# CF期货-期权事件路径研究 R93P",
        "",
        "## 数据状态",
        "",
        (
            f"- 样本区间：`{result.start}` 至 `{result.end}`；"
            f"R93N事件：`{result.event_row_count}` 条。"
        ),
        (
            f"- 固定检查点：`T+1/T+3/T+5`；"
            f"检查点记录：`{result.checkpoint_row_count}` 条。"
        ),
        (
            f"- 事件路径记录：`{result.path_row_count}` 条；"
            f"purged LOO记录：`{result.oos_row_count}` 条。"
        ),
        "- 输入只包括R93N T日事件表、R93N事件生命周期后验表和可选T日feature表，不读取交易所raw。",
        "",
        "## 研究定义",
        "",
        (
            "- 延续/反转/未解决均相对于R93N冻结的`event_direction`定义；"
            "本研究不重新解释Call/Put墙的多空所有权。"
        ),
        "- 收益标签采用R93N的T+1执行约束；forward return只用于历史后验验证，不进入T日特征。",
        (
            "- `first_resolution_horizon`表示在1D/3D/5D固定检查点中首次出现方向性结果，"
            "不等同于盘中首次解决时间；方向性解决使用固定死区。"
        ),
        "- TBM首触会话单独保留为路径证据，不把它解释为真实成交或期权持有人行为。",
        "",
        "## 事件频率与共现",
        "",
        "| 事件类型 | 年份 | 事件数 | 事件日数 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in (
        frequency.sort_values("event_count", ascending=False).head(20).itertuples(index=False)
    ):
        lines.append(
            f"| {row.event_type} | {row.calendar_year} | {row.event_count} | "
            f"{row.event_day_count} |"
        )
    lines.extend(["", "高频共现组合：", ""])
    if cooccurrence.empty:
        lines.append("- 没有同时发生的事件组合。")
    else:
        for row in cooccurrence.head(10).itertuples(index=False):
            lines.append(
                f"- `{row.event_type_left} + {row.event_type_right}`：{row.cooccurrence_count}次，"
                f"占事件日{fmt_percent(row.share_of_event_days)}。"
            )
    lines.extend(["", "## 总体路径结果", ""])
    overall = _overall_path_summary(result, event_summary)
    lines.extend(
        [
            f"- 当前结果中可形成方向性检查的样本为`{overall['directional_count']}`；"
            f"延续率`{fmt_percent(overall['continuation_rate'])}`，"
            f"反转率`{fmt_percent(overall['reversal_rate'])}`，"
            f"未解决率`{fmt_percent(overall['unresolved_rate'])}`。",
            "- 这些比例是历史事件条件统计，不是未来行情概率承诺；中性事件不进入方向性分母。",
            "",
            "## 事件类型路径",
            "",
            (
                "| 事件 | 周期 | 样本 | 延续率 | 反转率 | 未解决率 | "
                "方向收益均值 | 首次解决 | 预测筛选状态 |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    focus = event_summary.sort_values(
        ["sample_count", "event_type", "horizon"], ascending=[False, True, True]
    ).head(30)
    for row in focus.itertuples(index=False):
        lines.append(
            f"| {row.event_type} | {row.horizon}D | {row.available_count} | "
            f"{fmt_percent(row.continuation_rate)} | {fmt_percent(row.reversal_rate)} | "
            f"{fmt_percent(row.unresolved_rate)} | {fmt_percent(row.mean_directional_return)} | "
            f"{fmt_number(row.mean_first_tbm_session, 2)} | {row.predictive_evidence_status} |"
        )
    lines.extend(["", "## 解决周期与路径标签", ""])
    for row in resolution.head(18).itertuples(index=False):
        lines.append(
            f"- `{row.event_type}` / `{row.option_market_stage}`：样本{row.sample_count}，"
            f"5D内方向性解决率{fmt_percent(row.resolved_by_5d_rate)}，"
            f"平均首次检查点{fmt_number(row.mean_first_resolution_horizon, 2)}，"
            f"5D重测率{fmt_percent(row.retest_rate_5d)}，失败率{fmt_percent(row.failure_rate_5d)}。"
        )
    lines.extend(["", "## Purged Leave-One-Year-Out", ""])
    if oos.empty:
        lines.append("- 当前没有可用的留一年验证记录。")
    else:
        lines.extend(
            [
                "| 事件 | 周期 | 测试年 | 训练样本 | 测试样本 | 训练均值 | 测试均值 | OOS状态 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in (
            oos.sort_values(["test_sample_count", "test_year"], ascending=[False, True])
            .head(30)
            .itertuples(index=False)
        ):
            lines.append(
                f"| {row.event_type} | {row.horizon}D | {row.test_year} | "
                f"{row.train_sample_count} | "
                f"{row.test_sample_count} | "
                f"{fmt_percent(row.train_mean_directional_return)} | "
                f"{fmt_percent(row.test_mean_directional_return)} | "
                f"{row.oos_status} |"
            )
    latest_event_date = latest_events["event_date"].max() if not latest_events.empty else "-"
    latest_event_types = (
        "; ".join(sorted(latest_events["event_type"].astype(str).unique()))
        if not latest_events.empty
        else "无"
    )
    lines.extend(
        [
            "",
            "## 当前样本映射",
            "",
            f"- 最新事件日：`{latest_event_date}`；事件数：`{len(latest_events)}`。",
            f"- 最新事件类型：`{latest_event_types}`。",
            "- 最新事件只用于展示当前结构；没有未来标签时不会进入胜负或预测筛选结论。",
            "",
            "## 解释边界与人审项",
            "",
            (
                "- R93P把解释性证据（频率、共现、路径分布）与预测性筛选"
                "（FDR、年度稳定性、purged LOO）分栏呈现；筛选状态仍不构成晋级。"
            ),
            "- 期权持仓的多空归属、做市商Gamma、墙位支撑/阻力含义均未知；IV/Greek仍是研究proxy。",
            "- 本报告不构成交易指令，不自动反转方向、不修改综合得分、不调整仓位。",
            "- `HUMAN_REVIEW_REQUIRED`：事件方向语义、合约换月/到期分层、FDR与样本外解释。",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _overall_path_summary(
    result: ResearchFuturesOptionEventPathResult, summary: pd.DataFrame
) -> dict[str, object]:
    if summary.empty:
        return {
            "directional_count": 0,
            "continuation_rate": math.nan,
            "reversal_rate": math.nan,
            "unresolved_rate": math.nan,
        }
    weighted = summary.copy()
    total = weighted["directional_count"].sum()
    return {
        "directional_count": int(weighted["directional_count"].sum()),
        "continuation_rate": _ratio(int(weighted["continuation_count"].sum()), int(total)),
        "reversal_rate": _ratio(int(weighted["reversal_count"].sum()), int(total)),
        "unresolved_rate": _ratio(int(weighted["unresolved_count"].sum()), int(total)),
    }


def _latest_event_mapping(events: pd.DataFrame) -> dict[str, object]:
    if events.empty:
        return {"event_count": 0, "event_types": []}
    return {
        "event_date": events["event_date"].max(),
        "event_count": len(events),
        "event_types": sorted(events["event_type"].astype(str).unique()),
        "main_contracts": sorted(events["main_contract"].astype(str).unique()),
        "contains_future_label": False,
    }


def _event_family(event_type: object) -> str:
    value = str(event_type)
    if value.startswith("CALL_"):
        return "CALL_WALL_PATH"
    if value.startswith("PUT_"):
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
    if len(text) < 2 or not text[-2:].isdigit():
        return "UNKNOWN_CYCLE"
    month = int(text[-2:])
    return {1: "JAN_CYCLE", 5: "MAY_CYCLE", 9: "SEP_CYCLE"}.get(month, "OTHER_MONTH")


def _checkpoint_outcome(value: object, direction: object, available: object) -> str:
    if not bool(available):
        return "UNAVAILABLE"
    if str(direction) not in {"long", "short"}:
        return "NO_DIRECTION"
    normalized = str(value).upper()
    if normalized in {"FOLLOW_THROUGH", "CONTINUATION"}:
        return "CONTINUATION"
    if normalized in {"FAILED", "REVERSAL"}:
        return "REVERSAL"
    return "UNRESOLVED"


def _path_label(outcomes: list[str], horizons: tuple[int, ...]) -> str:
    usable = [value for value in outcomes if value not in {"UNAVAILABLE", "NO_DIRECTION"}]
    if not usable:
        return "NO_DIRECTION_OR_UNAVAILABLE"
    resolved = [value for value in usable if value in {"CONTINUATION", "REVERSAL"}]
    if not resolved:
        return "UNRESOLVED_5D"
    first = resolved[0]
    if len(resolved) == len(usable) and len(set(resolved)) == 1:
        return f"{first}_STABLE"
    if len(set(resolved)) > 1:
        return "DIRECTION_FLIP"
    first_index = next(index for index, value in enumerate(outcomes) if value == first)
    if first_index > 0:
        return f"LATE_{first}"
    return f"EARLY_{first}"


def _path_contract_match(
    row: dict[str, object], horizons: tuple[int, ...], event_contract: object
) -> bool | None:
    values = [row.get(f"t_plus_{h}_state_contract_match") for h in horizons]
    values = [value for value in values if value is not None and not pd.isna(value)]
    if not values:
        return None
    return bool(all(bool(value) for value in values))


def _evidence_level(sample_count: int, resolved_count: int, min_sample_size: int) -> str:
    if sample_count < min_sample_size or resolved_count < max(10, min_sample_size // 2):
        return "WEAK_OR_SMALL_SAMPLE"
    return "ADEQUATE_DESCRIPTIVE_SAMPLE"


def _predictive_status(row: pd.Series, *, min_sample_size: int, fdr_level: float) -> str:
    if int(row["directional_count"]) < min_sample_size:
        return "WEAK_OR_SMALL_SAMPLE"
    q_value = _number(row["fdr_q_value"])
    annual_rate = _number(row["annual_positive_rate"])
    mean_return = _number(row["mean_directional_return"])
    share = _number(row["resolved_continuation_share"])
    if (
        q_value is not None
        and q_value <= fdr_level
        and mean_return is not None
        and mean_return > 0
        and share is not None
        and share > 0.5
        and annual_rate is not None
        and annual_rate >= 2 / 3
    ):
        return "WATCH_ONLY"
    return "NO_STABLE_PREDICTIVE_EVIDENCE"


def _assign_fdr(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    output = pd.Series(math.nan, index=values.index, dtype=float)
    valid = numeric.dropna().sort_values()
    count = len(valid)
    if not count:
        return output
    adjusted: dict[object, float] = {}
    running = 1.0
    for rank, (index, value) in enumerate(list(valid.items())[::-1], start=1):
        original_rank = count - rank + 1
        candidate = min(running, float(value) * count / original_rank)
        running = candidate
        adjusted[index] = candidate
    for index, value in adjusted.items():
        output.loc[index] = value
    return output


def _binomial_two_sided(successes: int, trials: int) -> float:
    if trials <= 0:
        return math.nan
    probability = 0.0
    observed = successes / trials
    for k in range(trials + 1):
        mass = math.comb(trials, k) / (2**trials)
        if abs(k / trials - 0.5) >= abs(observed - 0.5) - 1e-12:
            probability += mass
    return min(1.0, probability)


def _date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def _ratio(numerator: int, denominator: int) -> float:
    return math.nan if denominator <= 0 else numerator / denominator


def _mean(values: pd.Series) -> float:
    return math.nan if values.empty else float(values.mean())


def _median(values: pd.Series) -> float:
    return math.nan if values.empty else float(values.median())


def _bool_mean(values: pd.Series) -> float:
    if values is None or values.empty:
        return math.nan
    normalized = values.dropna()
    if normalized.empty:
        return math.nan
    return float(normalized.astype(bool).mean())


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_finite_positive(value: object) -> bool:
    number = _number(value)
    return number is not None and number > 0


def _read_row_count(path: Path) -> int:
    try:
        return len(pd.read_parquet(path))
    except (IndexError, OSError, ValueError):
        return 0
