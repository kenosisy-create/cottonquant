"""R93N CF动态期权墙、事件生命周期与5D增量验证研究。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.chain_map import CF_MAIN_CYCLE_MONTHS
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.option_data_contract import (
    CORE_OPTION_QUOTE_FILE_NAME,
)
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    fmt_percent,
    latest_matching_path,
    load_table,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
RULE_VERSION = "V5.1_R93N_dynamic_option_wall_v1"
DEFAULT_HORIZONS = (1, 3, 5)
DEFAULT_LOCAL_BAND_RATIO = 0.03
DEFAULT_TOUCH_BAND_RATIO = 0.01
DEFAULT_WALL_CHANGE_BPS = 50
DEFAULT_WALL_SHIFT_BPS = 50
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_DEAD_ZONE_BPS = 10
DEFAULT_TBM_VOL_MULTIPLIER = 1.0
DEFAULT_ACTIVITY_WINDOW = 60
DEFAULT_ACTIVITY_MIN_PERIODS = 20
INFO = "INFO"
WARN = "WARN"
HUMAN_REVIEW_REQUIRED = (
    "option_open_interest_long_short_ownership_unknown",
    "dynamic_wall_direction_proxy_interpretation",
    "local_strike_band_threshold",
    "wall_change_and_migration_thresholds",
    "option_expiry_and_dte_interpretation",
    "mature_market_stage_boundaries",
    "event_lifecycle_label_interpretation",
    "oos_incremental_evidence_interpretation",
)
RESEARCH_BOUNDARY = {
    "features_use_t_or_earlier": True,
    "forward_returns_are_historical_posterior_labels": True,
    "t_plus_one_execution": True,
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
class FuturesOptionDynamicWallWarningRecord:
    """R93N告警与人工复核记录。"""

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
class ResearchFuturesOptionDynamicWallResult:
    """R93N完整研究包路径与摘要。"""

    run_id: str
    start: date
    end: date
    status: str
    feature_row_count: int
    event_row_count: int
    label_row_count: int
    event_label_row_count: int
    node_summary_row_count: int
    oos_row_count: int
    mature_feature_count: int
    ready_candidate_count: int
    watch_count: int
    latest_main_contract: str
    latest_dynamic_node: str
    latest_joint_node: str
    latest_option_pressure_direction: str
    feature_parquet_path: Path
    feature_csv_path: Path
    event_parquet_path: Path
    event_csv_path: Path
    label_parquet_path: Path
    label_csv_path: Path
    event_label_parquet_path: Path
    event_label_csv_path: Path
    summary_by_horizon_parquet_path: Path
    summary_by_horizon_csv_path: Path
    summary_by_node_parquet_path: Path
    summary_by_node_csv_path: Path
    oos_summary_parquet_path: Path
    oos_summary_csv_path: Path
    resolution_timing_parquet_path: Path
    resolution_timing_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    option_core_path: Path
    core_quote_path: Path
    option_factor_path: Path | None
    signal_matrix_path: Path | None
    trend_phase_path: Path | None
    option_strike_position_path: Path | None
    warning_records: tuple[FuturesOptionDynamicWallWarningRecord, ...]

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
            "feature_row_count": self.feature_row_count,
            "event_row_count": self.event_row_count,
            "label_row_count": self.label_row_count,
            "event_label_row_count": self.event_label_row_count,
            "node_summary_row_count": self.node_summary_row_count,
            "oos_row_count": self.oos_row_count,
            "mature_feature_count": self.mature_feature_count,
            "ready_candidate_count": self.ready_candidate_count,
            "watch_count": self.watch_count,
            "latest_main_contract": self.latest_main_contract,
            "latest_dynamic_node": self.latest_dynamic_node,
            "latest_joint_node": self.latest_joint_node,
            "latest_option_pressure_direction": self.latest_option_pressure_direction,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "feature_parquet_path": str(self.feature_parquet_path),
            "event_parquet_path": str(self.event_parquet_path),
            "label_parquet_path": str(self.label_parquet_path),
            "event_label_parquet_path": str(self.event_label_parquet_path),
            "summary_by_horizon_parquet_path": str(
                self.summary_by_horizon_parquet_path
            ),
            "summary_by_node_parquet_path": str(self.summary_by_node_parquet_path),
            "oos_summary_parquet_path": str(self.oos_summary_parquet_path),
            "resolution_timing_parquet_path": str(
                self.resolution_timing_parquet_path
            ),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "option_core_path": str(self.option_core_path),
            "core_quote_path": str(self.core_quote_path),
            "option_factor_path": (
                None if self.option_factor_path is None else str(self.option_factor_path)
            ),
            "signal_matrix_path": (
                None if self.signal_matrix_path is None else str(self.signal_matrix_path)
            ),
            "trend_phase_path": (
                None if self.trend_phase_path is None else str(self.trend_phase_path)
            ),
            "option_strike_position_path": (
                None
                if self.option_strike_position_path is None
                else str(self.option_strike_position_path)
            ),
            "features_use_t_or_earlier": True,
            "historical_returns_are_posterior_labels": True,
            "promotion_eligible": False,
            "realtime_rule_eligible": False,
            "enters_composite_score": False,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_futures_option_dynamic_wall_research(
    *,
    option_core_path: Path | None = None,
    core_quote_path: Path | None = None,
    option_factor_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    trend_phase_path: Path | None = None,
    option_strike_position_path: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    local_band_ratio: float = DEFAULT_LOCAL_BAND_RATIO,
    touch_band_ratio: float = DEFAULT_TOUCH_BAND_RATIO,
    wall_change_bps: int = DEFAULT_WALL_CHANGE_BPS,
    wall_shift_bps: int = DEFAULT_WALL_SHIFT_BPS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
    tbm_vol_multiplier: float = DEFAULT_TBM_VOL_MULTIPLIER,
    activity_window: int = DEFAULT_ACTIVITY_WINDOW,
    activity_min_periods: int = DEFAULT_ACTIVITY_MIN_PERIODS,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchFuturesOptionDynamicWallResult:
    """一次性构建R93N1-4特征、事件、增量证据和中文报告。"""
    normalized_horizons = _validate_parameters(
        horizons=horizons,
        local_band_ratio=local_band_ratio,
        touch_band_ratio=touch_band_ratio,
        wall_change_bps=wall_change_bps,
        wall_shift_bps=wall_shift_bps,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        dead_zone_bps=dead_zone_bps,
        tbm_vol_multiplier=tbm_vol_multiplier,
        activity_window=activity_window,
        activity_min_periods=activity_min_periods,
    )
    option_path = option_core_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_OPTION_QUOTE_FILE_NAME
    )
    quote_path = core_quote_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    )
    factor_path = option_factor_path or _optional_latest_path(
        data_dir() / "research" / PRODUCT_CODE / "option_factors",
        "CF_*_option_factor_proxy_daily.parquet",
    )
    matrix_path = signal_matrix_path or _optional_latest_path(
        data_dir() / "research" / PRODUCT_CODE / "signal_matrix",
        "CF_*_signal_matrix_daily.parquet",
    )
    phase_path = trend_phase_path or _optional_latest_path(
        data_dir() / "research" / PRODUCT_CODE / "trend_phase_v2",
        "CF_*_trend_phase_v2_daily.parquet",
    )
    strike_path = option_strike_position_path or _optional_latest_path(
        data_dir() / "research" / PRODUCT_CODE / "option_strike_position",
        "CF_*_option_strike_position_daily.parquet",
    )

    quote_missing_ranges: list[str] = []
    quotes = _load_quotes(quote_path, quote_missing_ranges)
    options, exclusion_counts = _load_options(option_path)
    effective_end = min(
        end or max(quotes["trade_date"]),
        max(options["trade_date"]),
        max(quotes["trade_date"]),
    )
    effective_start = max(
        start or min(options["trade_date"]),
        min(options["trade_date"]),
        min(quotes["trade_date"]),
    )
    quotes = quotes.loc[
        quotes["trade_date"].between(effective_start, effective_end)
    ].copy()
    options = options.loc[
        options["trade_date"].between(effective_start, effective_end)
    ].copy()
    if quotes.empty or options.empty:
        raise ResearchWorkbenchError("R93N日期过滤后没有可用期货或期权core数据")
    active_run_id = run_id or utc_timestamp_id("r93n_dynamic_wall", effective_end)

    main_quotes = _select_main_quotes(quotes)
    strike_detail = _build_strike_detail(options)
    features = _build_feature_daily(
        main_quotes=main_quotes,
        strike_detail=strike_detail,
        options=options,
        run_id=active_run_id,
        local_band_ratio=local_band_ratio,
        touch_band_ratio=touch_band_ratio,
        wall_change_bps=wall_change_bps,
        wall_shift_bps=wall_shift_bps,
        activity_window=activity_window,
        activity_min_periods=activity_min_periods,
    )
    features = _merge_research_sidecars(
        features=features,
        option_factor_path=factor_path,
        signal_matrix_path=matrix_path,
        trend_phase_path=phase_path,
        option_strike_position_path=strike_path,
        dead_zone_bps=dead_zone_bps,
    )
    features = _add_event_flags(
        features,
        touch_band_ratio=touch_band_ratio,
        wall_shift_bps=wall_shift_bps,
    )
    if features.empty:
        raise ResearchWorkbenchError("R93N没有可用的主力动态墙特征")

    labels = _build_posterior_labels(
        features=features,
        quotes=quotes,
        horizons=normalized_horizons,
        dead_zone_bps=dead_zone_bps,
        tbm_vol_multiplier=tbm_vol_multiplier,
        run_id=active_run_id,
    )
    events = _build_event_table(features=features, run_id=active_run_id)
    event_labels = _build_event_labels(
        events=events,
        labels=labels,
        dead_zone_bps=dead_zone_bps,
        touch_band_ratio=touch_band_ratio,
        run_id=active_run_id,
    )
    summary_by_horizon = _build_horizon_summary(
        labels=labels,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    summary_by_node = _build_node_summary(
        labels=labels,
        event_labels=event_labels,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        run_id=active_run_id,
    )
    oos_summary = _build_leave_one_year_out_summary(
        labels=labels,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    resolution_timing = _build_resolution_timing(
        event_labels=event_labels,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    warnings = _warning_records(
        run_id=active_run_id,
        quote_missing_ranges=quote_missing_ranges,
        exclusion_counts=exclusion_counts,
        features=features,
        labels=labels,
        summary_by_node=summary_by_node,
        oos_summary=oos_summary,
        factor_path=factor_path,
        matrix_path=matrix_path,
        phase_path=phase_path,
        strike_path=strike_path,
        feature_end=features["trade_date"].max(),
    )
    paths = _paths(
        start=features["trade_date"].min(),
        end=features["trade_date"].max(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_outputs(
        paths=paths,
        features=features,
        events=events,
        labels=labels,
        event_labels=event_labels,
        summary_by_horizon=summary_by_horizon,
        summary_by_node=summary_by_node,
        oos_summary=oos_summary,
        resolution_timing=resolution_timing,
        warnings=warnings,
    )

    latest = features.sort_values("trade_date").iloc[-1]
    ready_count = int(
        summary_by_node["evidence_status"].eq("READY_CANDIDATE").sum()
    )
    watch_count = int(summary_by_node["evidence_status"].eq("WATCH").sum())
    result = ResearchFuturesOptionDynamicWallResult(
        run_id=active_run_id,
        start=features["trade_date"].min(),
        end=features["trade_date"].max(),
        status="READY_WITH_WARNINGS" if any(w.severity == WARN for w in warnings) else "READY",
        feature_row_count=len(features),
        event_row_count=len(events),
        label_row_count=len(labels),
        event_label_row_count=len(event_labels),
        node_summary_row_count=len(summary_by_node),
        oos_row_count=len(oos_summary),
        mature_feature_count=int(features["option_market_stage"].eq("MATURE_ACTIVE").sum()),
        ready_candidate_count=ready_count,
        watch_count=watch_count,
        latest_main_contract=str(latest["main_contract"]),
        latest_dynamic_node=str(latest["dynamic_pressure_node"]),
        latest_joint_node=str(latest["joint_futures_option_node"]),
        latest_option_pressure_direction=str(latest["option_pressure_direction"]),
        feature_parquet_path=paths["feature_parquet"],
        feature_csv_path=paths["feature_csv"],
        event_parquet_path=paths["event_parquet"],
        event_csv_path=paths["event_csv"],
        label_parquet_path=paths["label_parquet"],
        label_csv_path=paths["label_csv"],
        event_label_parquet_path=paths["event_label_parquet"],
        event_label_csv_path=paths["event_label_csv"],
        summary_by_horizon_parquet_path=paths["horizon_parquet"],
        summary_by_horizon_csv_path=paths["horizon_csv"],
        summary_by_node_parquet_path=paths["node_parquet"],
        summary_by_node_csv_path=paths["node_csv"],
        oos_summary_parquet_path=paths["oos_parquet"],
        oos_summary_csv_path=paths["oos_csv"],
        resolution_timing_parquet_path=paths["resolution_parquet"],
        resolution_timing_csv_path=paths["resolution_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        option_core_path=option_path,
        core_quote_path=quote_path,
        option_factor_path=factor_path,
        signal_matrix_path=matrix_path,
        trend_phase_path=phase_path,
        option_strike_position_path=strike_path,
        warning_records=tuple(warnings),
    )
    _write_markdown(
        result=result,
        latest=latest.to_dict(),
        summary_by_horizon=summary_by_horizon,
        summary_by_node=summary_by_node,
        oos_summary=oos_summary,
        resolution_timing=resolution_timing,
    )
    write_json(
        result.json_path,
        {
            "report_type": "cf_futures_option_dynamic_wall_research",
            "rule_version": RULE_VERSION,
            "summary": result.to_summary(),
            "latest_state": latest.to_dict(),
            "research_boundary": RESEARCH_BOUNDARY,
            "parameters": {
                "horizons": list(normalized_horizons),
                "local_band_ratio": local_band_ratio,
                "touch_band_ratio": touch_band_ratio,
                "wall_change_bps": wall_change_bps,
                "wall_shift_bps": wall_shift_bps,
                "min_sample_size": min_sample_size,
                "fdr_level": fdr_level,
                "dead_zone_bps": dead_zone_bps,
                "tbm_vol_multiplier": tbm_vol_multiplier,
                "activity_window": activity_window,
                "activity_min_periods": activity_min_periods,
            },
        },
    )
    manifest = artifact_manifest(
        run_id=active_run_id,
        report_type="cf_futures_option_dynamic_wall_research",
        rule_version=RULE_VERSION,
        data_asof=result.end,
        input_paths={
            "option_core_path": option_path,
            "core_quote_path": quote_path,
            "option_factor_path": factor_path,
            "signal_matrix_path": matrix_path,
            "trend_phase_path": phase_path,
            "option_strike_position_path": strike_path,
        },
        output_paths={
            "feature_parquet_path": result.feature_parquet_path,
            "event_parquet_path": result.event_parquet_path,
            "label_parquet_path": result.label_parquet_path,
            "event_label_parquet_path": result.event_label_parquet_path,
            "summary_by_horizon_parquet_path": result.summary_by_horizon_parquet_path,
            "summary_by_node_parquet_path": result.summary_by_node_parquet_path,
            "oos_summary_parquet_path": result.oos_summary_parquet_path,
            "resolution_timing_parquet_path": result.resolution_timing_parquet_path,
            "markdown_path": result.markdown_path,
            "json_path": result.json_path,
            "warning_csv_path": result.warning_csv_path,
        },
        human_review_required=HUMAN_REVIEW_REQUIRED,
        research_boundary=RESEARCH_BOUNDARY,
    )
    manifest["row_counts"] = {
        "feature": len(features),
        "event": len(events),
        "label": len(labels),
        "event_label": len(event_labels),
        "summary_by_horizon": len(summary_by_horizon),
        "summary_by_node": len(summary_by_node),
        "oos_summary": len(oos_summary),
        "resolution_timing": len(resolution_timing),
    }
    manifest["r93n_delivery_status"] = {
        "r93n_1_dynamic_feature_table": "completed",
        "r93n_2_event_and_lifecycle_labels": "completed",
        "r93n_3_incremental_and_oos_validation": "completed",
        "r93n_4_chinese_report_and_weekly_contract": "completed",
    }
    write_json(result.manifest_path, manifest)
    return result


# 兼容较短的研究函数命名，公共CLI仍使用完整名称。
build_cf_dynamic_option_wall_research = build_cf_futures_option_dynamic_wall_research


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    local_band_ratio: float,
    touch_band_ratio: float,
    wall_change_bps: int,
    wall_shift_bps: int,
    min_sample_size: int,
    fdr_level: float,
    dead_zone_bps: int,
    tbm_vol_multiplier: float,
    activity_window: int,
    activity_min_periods: int,
) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in horizons)))
    if not normalized or any(value <= 0 for value in normalized):
        raise ResearchWorkbenchError("R93N horizons必须为正整数")
    if not 0 < local_band_ratio <= 0.20:
        raise ResearchWorkbenchError("R93N local_band_ratio必须位于(0,0.20]")
    if not 0 < touch_band_ratio <= local_band_ratio:
        raise ResearchWorkbenchError(
            "R93N touch_band_ratio必须大于0且不超过local_band_ratio"
        )
    if wall_change_bps < 0 or wall_shift_bps < 0:
        raise ResearchWorkbenchError("R93N墙体变化阈值不能为负")
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("R93N min_sample_size必须为正整数")
    if not 0 < fdr_level < 1:
        raise ResearchWorkbenchError("R93N fdr_level必须位于(0,1)")
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("R93N dead_zone_bps不能为负")
    if tbm_vol_multiplier <= 0:
        raise ResearchWorkbenchError("R93N tbm_vol_multiplier必须为正数")
    if activity_window <= 0 or activity_min_periods <= 0:
        raise ResearchWorkbenchError("R93N活跃度窗口参数必须为正整数")
    if activity_min_periods > activity_window:
        raise ResearchWorkbenchError("R93N activity_min_periods不能超过activity_window")
    return normalized


def _load_quotes(path: Path, missing_ranges: list[str]) -> pd.DataFrame:
    frame = load_table(
        path,
        required={"trade_date", "contract_code", "settle", "volume", "open_interest"},
        label="R93N CF core quote",
    )
    frame = normalize_trade_date(frame)
    for column in ("settle", "volume", "open_interest"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("close", "high", "low"):
        if column not in frame.columns:
            frame[column] = frame["settle"]
            missing_ranges.append(column)
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(
            frame["settle"]
        )
    frame["contract_code"] = frame["contract_code"].astype(str).str.upper()
    frame = frame.dropna(subset=["trade_date", "contract_code", "settle"])
    if frame.duplicated(["trade_date", "contract_code"]).any():
        raise ResearchWorkbenchError("R93N CF core quote存在重复trade_date-contract_code")
    return frame.sort_values(["trade_date", "contract_code"]).reset_index(drop=True)


def _load_options(path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    frame = load_table(
        path,
        required={
            "trade_date",
            "option_symbol",
            "underlying_contract",
            "option_type",
            "strike",
            "open_interest",
        },
        label="R93N CF option core",
    )
    frame = normalize_trade_date(frame)
    for column in ("strike", "open_interest"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("volume", "settle"):
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    if "liquidity_flag" not in frame.columns:
        frame["liquidity_flag"] = "unknown"
    if "data_quality_flag" not in frame.columns:
        frame["data_quality_flag"] = "unknown"
    frame["option_symbol"] = frame["option_symbol"].astype(str).str.upper()
    frame["underlying_contract"] = (
        frame["underlying_contract"].astype(str).str.upper()
    )
    frame["option_type"] = frame["option_type"].astype(str).str.upper()
    frame = frame.loc[
        frame["option_type"].isin(["C", "P"])
        & frame["strike"].gt(0)
        & frame["open_interest"].ge(0)
    ].copy()
    if frame.duplicated(["trade_date", "option_symbol"]).any():
        raise ResearchWorkbenchError("R93N option core存在重复trade_date-option_symbol")
    quality = frame["data_quality_flag"].astype(str).str.upper()
    liquidity = frame["liquidity_flag"].astype(str).str.lower()
    low_liquidity = liquidity.eq("low_liquidity") | quality.str.contains(
        "LOW_LIQUIDITY", regex=False
    )
    deep_otm = quality.str.contains("DEEP_OTM_PROXY", regex=False)
    frame["analysis_eligible"] = ~(low_liquidity | deep_otm)
    frame = frame.sort_values(["option_symbol", "trade_date"]).reset_index(drop=True)
    frame["open_interest_change"] = frame.groupby("option_symbol", sort=False)[
        "open_interest"
    ].diff()
    return frame, {
        "low_liquidity": int(low_liquidity.sum()),
        "deep_otm": int(deep_otm.sum()),
        "eligible": int(frame["analysis_eligible"].sum()),
        "total": len(frame),
    }


def _select_main_quotes(quotes: pd.DataFrame) -> pd.DataFrame:
    working = quotes.copy()
    working["delivery_month"] = working["contract_code"].map(_contract_month)
    cycle = working.loc[
        working["delivery_month"].isin(CF_MAIN_CYCLE_MONTHS)
    ].copy()
    if cycle.empty:
        raise ResearchWorkbenchError("R93N未找到CF 01/05/09主力周期合约")
    cycle = cycle.sort_values(
        ["trade_date", "open_interest", "volume", "contract_code"],
        ascending=[True, False, False, True],
    )
    selected = cycle.groupby("trade_date", sort=True, as_index=False).head(1).copy()
    selected = selected.rename(
        columns={
            "contract_code": "main_contract",
            "settle": "underlying_settle",
            "close": "underlying_close",
            "high": "underlying_high",
            "low": "underlying_low",
            "volume": "futures_volume",
            "open_interest": "futures_open_interest",
        }
    )
    selected["main_selection_rule"] = "CF_01_05_09_OI_THEN_VOLUME"
    selected["observation_id"] = selected.apply(
        lambda row: f"{row['trade_date']}_{row['main_contract']}", axis=1
    )
    return selected[
        [
            "observation_id",
            "trade_date",
            "main_contract",
            "underlying_settle",
            "underlying_close",
            "underlying_high",
            "underlying_low",
            "futures_volume",
            "futures_open_interest",
            "main_selection_rule",
        ]
    ].sort_values("trade_date").reset_index(drop=True)


def _contract_month(contract_code: object) -> int | None:
    match = re.search(r"(\d{2})$", str(contract_code).upper())
    if match is None:
        return None
    month = int(match.group(1))
    return month if 1 <= month <= 12 else None


def _build_strike_detail(options: pd.DataFrame) -> pd.DataFrame:
    keys = ["trade_date", "underlying_contract", "strike"]
    side_frames: list[pd.DataFrame] = []
    for option_type, prefix in (("C", "call"), ("P", "put")):
        side = options.loc[options["option_type"].eq(option_type)].copy()
        grouped = (
            side.groupby(keys, sort=True, dropna=False)
            .agg(
                **{
                    f"{prefix}_open_interest": ("open_interest", "sum"),
                    f"{prefix}_open_interest_change": (
                        "open_interest_change",
                        lambda values: values.sum(min_count=1),
                    ),
                    f"{prefix}_volume": ("volume", "sum"),
                    f"{prefix}_option_count": ("option_symbol", "nunique"),
                }
            )
            .reset_index()
        )
        eligible = side.loc[side["analysis_eligible"].astype(bool)]
        eligible_grouped = (
            eligible.groupby(keys, sort=True, dropna=False)
            .agg(
                **{
                    f"eligible_{prefix}_open_interest": ("open_interest", "sum"),
                    f"eligible_{prefix}_open_interest_change": (
                        "open_interest_change",
                        lambda values: values.sum(min_count=1),
                    ),
                    f"eligible_{prefix}_volume": ("volume", "sum"),
                    f"eligible_{prefix}_option_count": ("option_symbol", "nunique"),
                }
            )
            .reset_index()
        )
        side_frames.append(grouped.merge(eligible_grouped, on=keys, how="left"))
    detail = side_frames[0].merge(side_frames[1], on=keys, how="outer")
    numeric_columns = [column for column in detail.columns if column not in keys]
    for column in numeric_columns:
        detail[column] = pd.to_numeric(detail[column], errors="coerce")
        if "change" not in column:
            detail[column] = detail[column].fillna(0.0)
    return detail.sort_values(keys).reset_index(drop=True)


def _build_feature_daily(
    *,
    main_quotes: pd.DataFrame,
    strike_detail: pd.DataFrame,
    options: pd.DataFrame,
    run_id: str,
    local_band_ratio: float,
    touch_band_ratio: float,
    wall_change_bps: int,
    wall_shift_bps: int,
    activity_window: int,
    activity_min_periods: int,
) -> pd.DataFrame:
    strike_groups = {
        (trade_date, contract): group.copy()
        for (trade_date, contract), group in strike_detail.groupby(
            ["trade_date", "underlying_contract"], sort=False
        )
    }
    rows: list[dict[str, object]] = []
    for main in main_quotes.itertuples(index=False):
        group = strike_groups.get((main.trade_date, main.main_contract))
        base = {
            "run_id": run_id,
            "observation_id": main.observation_id,
            "trade_date": main.trade_date,
            "main_contract": main.main_contract,
            "underlying_settle": float(main.underlying_settle),
            "underlying_close": float(main.underlying_close),
            "underlying_high": float(main.underlying_high),
            "underlying_low": float(main.underlying_low),
            "futures_volume": _float_or_nan(main.futures_volume),
            "futures_open_interest": _float_or_nan(main.futures_open_interest),
            "main_selection_rule": main.main_selection_rule,
            "option_chain_available": group is not None and not group.empty,
            "feature_uses_t_or_earlier": True,
            "contains_posterior_outcome": False,
            "enters_composite_score": False,
            "trading_instruction": "not_a_trading_instruction",
        }
        if group is None or group.empty:
            rows.append(base)
            continue
        base.update(
            _contract_day_metrics(
                group=group,
                underlying=float(main.underlying_settle),
                futures_open_interest=_float_or_nan(main.futures_open_interest),
                local_band_ratio=local_band_ratio,
                touch_band_ratio=touch_band_ratio,
            )
        )
        rows.append(base)
    features = pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)
    features = _add_dynamic_changes(
        features,
        wall_change_bps=wall_change_bps,
        wall_shift_bps=wall_shift_bps,
    )
    activity = _build_activity_daily(
        options,
        activity_window=activity_window,
        activity_min_periods=activity_min_periods,
    )
    features = features.merge(activity, on="trade_date", how="left", validate="one_to_one")
    return features


def _contract_day_metrics(
    *,
    group: pd.DataFrame,
    underlying: float,
    futures_open_interest: float,
    local_band_ratio: float,
    touch_band_ratio: float,
) -> dict[str, object]:
    metrics: dict[str, object] = {}
    for side in ("call", "put"):
        metrics.update(
            _side_metrics(
                group=group,
                side=side,
                prefix="static",
                eligible=False,
                underlying=underlying,
                futures_open_interest=futures_open_interest,
            )
        )
        metrics.update(
            _side_metrics(
                group=group,
                side=side,
                prefix="dynamic",
                eligible=True,
                underlying=underlying,
                futures_open_interest=futures_open_interest,
            )
        )
    local = group.loc[
        (pd.to_numeric(group["strike"], errors="coerce") / underlying - 1.0).abs()
        <= local_band_ratio
    ].copy()
    tight = group.loc[
        (pd.to_numeric(group["strike"], errors="coerce") / underlying - 1.0).abs()
        <= touch_band_ratio
    ].copy()
    for side in ("call", "put"):
        metrics[f"local_{side}_open_interest"] = _sum_numeric(
            local[f"eligible_{side}_open_interest"]
        )
        metrics[f"local_{side}_open_interest_change"] = _sum_numeric_min_count(
            local[f"eligible_{side}_open_interest_change"]
        )
        metrics[f"local_{side}_volume"] = _sum_numeric(
            local[f"eligible_{side}_volume"]
        )
        metrics[f"tight_{side}_open_interest"] = _sum_numeric(
            tight[f"eligible_{side}_open_interest"]
        )
        metrics[f"tight_{side}_open_interest_change"] = _sum_numeric_min_count(
            tight[f"eligible_{side}_open_interest_change"]
        )
        metrics[f"local_{side}_oi_to_futures_oi"] = _safe_ratio(
            metrics[f"local_{side}_open_interest"], futures_open_interest
        )
    metrics["static_max_pain_strike"] = _max_pain_strike(group)
    metrics["static_key_level_state"] = _key_level_state(
        underlying=underlying,
        call_wall=_number_or_none(metrics.get("static_call_wall_strike")),
        put_wall=_number_or_none(metrics.get("static_put_wall_strike")),
        max_pain=_number_or_none(metrics.get("static_max_pain_strike")),
        near_ratio=touch_band_ratio,
    )
    metrics["dynamic_key_level_state"] = _key_level_state(
        underlying=underlying,
        call_wall=_number_or_none(metrics.get("dynamic_call_wall_strike")),
        put_wall=_number_or_none(metrics.get("dynamic_put_wall_strike")),
        max_pain=None,
        near_ratio=touch_band_ratio,
    )
    metrics["dynamic_wall_range_width"] = _difference(
        metrics.get("dynamic_call_wall_strike"),
        metrics.get("dynamic_put_wall_strike"),
    )
    metrics["dynamic_wall_range_width_ratio"] = _safe_ratio(
        metrics["dynamic_wall_range_width"], underlying
    )
    metrics["local_put_call_oi_ratio"] = _safe_ratio(
        metrics["local_put_open_interest"], metrics["local_call_open_interest"]
    )
    metrics["local_put_minus_call_oi_change"] = _difference(
        metrics["local_put_open_interest_change"],
        metrics["local_call_open_interest_change"],
    )
    return metrics


def _side_metrics(
    *,
    group: pd.DataFrame,
    side: str,
    prefix: str,
    eligible: bool,
    underlying: float,
    futures_open_interest: float,
) -> dict[str, object]:
    oi_column = f"{'eligible_' if eligible else ''}{side}_open_interest"
    change_column = f"{'eligible_' if eligible else ''}{side}_open_interest_change"
    volume_column = f"{'eligible_' if eligible else ''}{side}_volume"
    values = pd.to_numeric(group[oi_column], errors="coerce").fillna(0.0)
    total = float(values.sum())
    change_values = pd.to_numeric(group[change_column], errors="coerce")
    total_change = _sum_numeric_min_count(change_values)
    volume = _sum_numeric(group[volume_column])
    eligible_rows = group.loc[values.gt(0)].copy()
    wall = None
    if not eligible_rows.empty:
        wall = eligible_rows.sort_values(
            [oi_column, "strike"], ascending=[False, True]
        ).iloc[0]
    wall_strike = None if wall is None else _number_or_none(wall["strike"])
    wall_oi = None if wall is None else _number_or_none(wall[oi_column])
    wall_change = None if wall is None else _number_or_none(wall[change_column])
    center = None
    if total > 0:
        center = float(np.average(group["strike"], weights=values))
    top3 = None if total <= 0 else float(values.nlargest(3).sum() / total)
    return {
        f"{prefix}_{side}_total_open_interest": total,
        f"{prefix}_{side}_total_open_interest_change": total_change,
        f"{prefix}_{side}_total_volume": volume,
        f"{prefix}_{side}_wall_strike": wall_strike,
        f"{prefix}_{side}_wall_open_interest": wall_oi,
        f"{prefix}_{side}_wall_open_interest_change": wall_change,
        f"{prefix}_{side}_wall_concentration": _safe_ratio(wall_oi, total),
        f"{prefix}_{side}_top3_concentration": top3,
        f"{prefix}_{side}_oi_center": center,
        f"{prefix}_{side}_wall_distance": (
            None if wall_strike is None else wall_strike / underlying - 1.0
        ),
        f"{prefix}_{side}_wall_oi_to_futures_oi": _safe_ratio(
            wall_oi, futures_open_interest
        ),
        f"{prefix}_{side}_total_oi_to_futures_oi": _safe_ratio(
            total, futures_open_interest
        ),
    }


def _add_dynamic_changes(
    features: pd.DataFrame,
    *,
    wall_change_bps: int,
    wall_shift_bps: int,
) -> pd.DataFrame:
    working = features.sort_values(["main_contract", "trade_date"]).copy()
    grouped = working.groupby("main_contract", sort=False)
    change_columns = (
        "dynamic_call_wall_strike",
        "dynamic_put_wall_strike",
        "dynamic_call_oi_center",
        "dynamic_put_oi_center",
        "dynamic_wall_range_width",
        "dynamic_call_wall_open_interest_change",
        "dynamic_put_wall_open_interest_change",
    )
    for column in change_columns:
        if column not in working.columns:
            working[column] = math.nan
        working[f"{column}_change_1d"] = grouped[column].diff()
    for side in ("call", "put"):
        local_column = f"local_{side}_open_interest"
        prior = grouped[local_column].shift(1)
        working[f"local_{side}_oi_change_ratio"] = _safe_series_ratio(
            working[f"local_{side}_open_interest_change"], prior
        )
        wall_oi_column = f"dynamic_{side}_wall_open_interest"
        prior_wall_oi = grouped[wall_oi_column].shift(1)
        working[f"dynamic_{side}_wall_oi_change_ratio"] = _safe_series_ratio(
            working[f"dynamic_{side}_wall_open_interest_change"], prior_wall_oi
        )
        shift = working[f"dynamic_{side}_wall_strike_change_1d"]
        working[f"dynamic_{side}_wall_shift_bps"] = (
            shift / working["underlying_settle"] * 10000.0
        )
    threshold = wall_change_bps / 10000.0
    shift_threshold = float(wall_shift_bps)
    working["local_call_build_flag"] = working["local_call_oi_change_ratio"].ge(
        threshold
    )
    working["local_call_unwind_flag"] = working["local_call_oi_change_ratio"].le(
        -threshold
    )
    working["local_put_build_flag"] = working["local_put_oi_change_ratio"].ge(
        threshold
    )
    working["local_put_unwind_flag"] = working["local_put_oi_change_ratio"].le(
        -threshold
    )
    working["call_wall_up_flag"] = working["dynamic_call_wall_shift_bps"].ge(
        shift_threshold
    )
    working["call_wall_down_flag"] = working["dynamic_call_wall_shift_bps"].le(
        -shift_threshold
    )
    working["put_wall_up_flag"] = working["dynamic_put_wall_shift_bps"].ge(
        shift_threshold
    )
    working["put_wall_down_flag"] = working["dynamic_put_wall_shift_bps"].le(
        -shift_threshold
    )
    working["wall_range_change_bps"] = (
        working["dynamic_wall_range_width_change_1d"]
        / working["underlying_settle"]
        * 10000.0
    )
    working["wall_range_state"] = working["wall_range_change_bps"].map(
        lambda value: _range_state(value, shift_threshold)
    )
    pressure = working.apply(_option_pressure_proxy, axis=1, result_type="expand")
    pressure.columns = [
        "option_pressure_score",
        "option_pressure_direction",
        "option_pressure_reason",
        "dynamic_pressure_node",
    ]
    working = pd.concat([working, pressure], axis=1)
    working["dynamic_wall_rule_version"] = RULE_VERSION
    return working.sort_values("trade_date").reset_index(drop=True)


def _option_pressure_proxy(row: pd.Series) -> tuple[int, str, str, str]:
    # OI无法识别买卖方，得分仅表示结构压力组合，不代表净多空或做市商Gamma。
    score = 0
    reasons: list[str] = []
    if bool(row.get("local_put_build_flag", False)):
        score += 1
        reasons.append("LOCAL_PUT_BUILD")
    if bool(row.get("local_call_unwind_flag", False)):
        score += 1
        reasons.append("LOCAL_CALL_UNWIND")
    if bool(row.get("call_wall_up_flag", False)):
        score += 1
        reasons.append("CALL_WALL_UP")
    if bool(row.get("put_wall_up_flag", False)):
        score += 1
        reasons.append("PUT_WALL_UP")
    if bool(row.get("local_call_build_flag", False)):
        score -= 1
        reasons.append("LOCAL_CALL_BUILD")
    if bool(row.get("local_put_unwind_flag", False)):
        score -= 1
        reasons.append("LOCAL_PUT_UNWIND")
    if bool(row.get("call_wall_down_flag", False)):
        score -= 1
        reasons.append("CALL_WALL_DOWN")
    if bool(row.get("put_wall_down_flag", False)):
        score -= 1
        reasons.append("PUT_WALL_DOWN")
    direction = "long" if score >= 2 else "short" if score <= -2 else "neutral"
    if direction == "long":
        node = "DYNAMIC_LONG_PRESSURE"
    elif direction == "short":
        node = "DYNAMIC_SHORT_PRESSURE"
    elif score:
        node = "DYNAMIC_MIXED_PRESSURE"
    else:
        node = "DYNAMIC_NEUTRAL"
    return score, direction, ";".join(reasons) if reasons else "NO_DYNAMIC_PRESSURE", node


def _build_activity_daily(
    options: pd.DataFrame,
    *,
    activity_window: int,
    activity_min_periods: int,
) -> pd.DataFrame:
    activity = (
        options.groupby("trade_date", sort=True)
        .agg(
            total_option_volume=("volume", "sum"),
            total_option_open_interest=("open_interest", "sum"),
            listed_option_count=("option_symbol", "nunique"),
            underlying_contract_count=("underlying_contract", "nunique"),
        )
        .reset_index()
        .sort_values("trade_date")
    )
    activity["calendar_year"] = activity["trade_date"].map(lambda value: value.year)
    baseline = activity.loc[activity["calendar_year"].eq(2021)]
    baseline_volume = (
        float(baseline["total_option_volume"].median())
        if not baseline.empty
        else math.nan
    )
    baseline_oi = (
        float(baseline["total_option_open_interest"].median())
        if not baseline.empty
        else math.nan
    )
    activity["trailing_option_volume_median"] = activity[
        "total_option_volume"
    ].rolling(activity_window, min_periods=activity_min_periods).median()
    activity["trailing_option_oi_median"] = activity[
        "total_option_open_interest"
    ].rolling(activity_window, min_periods=activity_min_periods).median()
    activity["trailing_volume_vs_2021"] = (
        activity["trailing_option_volume_median"] / baseline_volume
        if math.isfinite(baseline_volume) and baseline_volume > 0
        else math.nan
    )
    activity["trailing_oi_vs_2021"] = (
        activity["trailing_option_oi_median"] / baseline_oi
        if math.isfinite(baseline_oi) and baseline_oi > 0
        else math.nan
    )
    activity["option_market_stage"] = activity["calendar_year"].map(
        _calendar_market_stage
    )
    activity["data_activity_state"] = activity.apply(
        lambda row: _activity_state(
            year=int(row["calendar_year"]),
            volume_ratio=_number_or_none(row["trailing_volume_vs_2021"]),
            oi_ratio=_number_or_none(row["trailing_oi_vs_2021"]),
        ),
        axis=1,
    )
    activity["activity_features_use_t_or_earlier"] = True
    activity["baseline_uses_complete_2021_history"] = True
    return activity


def _merge_research_sidecars(
    *,
    features: pd.DataFrame,
    option_factor_path: Path | None,
    signal_matrix_path: Path | None,
    trend_phase_path: Path | None,
    option_strike_position_path: Path | None,
    dead_zone_bps: int,
) -> pd.DataFrame:
    working = features.copy()
    if signal_matrix_path is not None:
        matrix = load_table(
            signal_matrix_path,
            required={
                "trade_date",
                "horizon",
                "main_contract",
                "direction",
                "option_signal",
                "option_signal_direction",
            },
            label="R93N signal matrix",
        )
        matrix = normalize_trade_date(matrix)
        matrix["horizon"] = pd.to_numeric(matrix["horizon"], errors="coerce")
        matrix = matrix.loc[matrix["horizon"].eq(5)].copy()
        matrix = matrix.drop_duplicates(["trade_date", "main_contract"], keep="last")
        columns = [
            "trade_date",
            "main_contract",
            "direction",
            "confidence",
            "composite_score",
            "option_signal",
            "option_signal_direction",
            "option_underlying_contract",
            "option_factor_status",
        ]
        for column in columns:
            if column not in matrix.columns:
                matrix[column] = None
        matrix = matrix[columns].rename(
            columns={
                "direction": "futures_direction_5d",
                "confidence": "futures_confidence_5d",
                "composite_score": "futures_composite_score_5d",
                "option_signal": "r48_option_signal_5d",
                "option_signal_direction": "r48_option_direction_5d",
                "option_underlying_contract": "r48_option_underlying_contract",
                "option_factor_status": "r48_option_factor_status_5d",
            }
        )
        working = working.merge(
            matrix,
            on=["trade_date", "main_contract"],
            how="left",
            validate="one_to_one",
        )
    for column in (
        "futures_direction_5d",
        "futures_confidence_5d",
        "futures_composite_score_5d",
        "r48_option_signal_5d",
        "r48_option_direction_5d",
        "r48_option_underlying_contract",
        "r48_option_factor_status_5d",
    ):
        if column not in working.columns:
            working[column] = None
    working["settle_return_5d"] = (
        working["underlying_settle"]
        / working.groupby("main_contract", sort=False)["underlying_settle"].shift(5)
        - 1.0
    )
    fallback_direction = working["settle_return_5d"].map(
        lambda value: _return_direction(value, dead_zone_bps)
    )
    working["futures_direction_5d"] = working["futures_direction_5d"].map(
        _normalize_direction
    )
    working["futures_direction_source"] = np.where(
        working["futures_direction_5d"].isin(["long", "short"]),
        "R35_SIGNAL_MATRIX_5D",
        "T_OR_EARLIER_5D_MOMENTUM_FALLBACK",
    )
    working["futures_direction_5d"] = working["futures_direction_5d"].where(
        working["futures_direction_5d"].isin(["long", "short"]),
        fallback_direction,
    )
    working["r48_option_direction_5d"] = working["r48_option_direction_5d"].map(
        _normalize_direction
    )

    if option_factor_path is not None:
        factors = load_table(
            option_factor_path,
            required={"trade_date", "underlying_contract", "factor_status"},
            label="R93N R48 option factor",
        )
        factors = normalize_trade_date(factors)
        factor_columns = [
            "trade_date",
            "underlying_contract",
            "atm_iv_rank",
            "pcr_volume",
            "pcr_oi",
            "skew_proxy",
            "option_liquidity_score",
            "factor_status",
            "option_signal_status",
        ]
        for column in factor_columns:
            if column not in factors.columns:
                factors[column] = None
        factors = factors[factor_columns].rename(
            columns={
                "underlying_contract": "main_contract",
                "factor_status": "r48_factor_status",
                "option_signal_status": "r48_option_signal_status",
            }
        )
        factors = factors.drop_duplicates(["trade_date", "main_contract"], keep="last")
        working = working.merge(
            factors,
            on=["trade_date", "main_contract"],
            how="left",
            validate="one_to_one",
        )
    for column in (
        "atm_iv_rank",
        "pcr_volume",
        "pcr_oi",
        "skew_proxy",
        "option_liquidity_score",
        "r48_factor_status",
        "r48_option_signal_status",
    ):
        if column not in working.columns:
            working[column] = None

    if trend_phase_path is not None:
        phase = load_table(
            trend_phase_path,
            required={"trade_date", "main_contract", "phase_v2"},
            label="R93N R76 trend phase",
        )
        phase = normalize_trade_date(phase)
        phase_columns = [
            "trade_date",
            "main_contract",
            "phase_v2",
            "phase_v2_label",
            "phase_direction",
            "phase_quality",
            "participation_state",
            "roll_context",
            "confirmation_state",
        ]
        for column in phase_columns:
            if column not in phase.columns:
                phase[column] = None
        phase = phase[phase_columns].drop_duplicates(
            ["trade_date", "main_contract"], keep="last"
        )
        working = working.merge(
            phase,
            on=["trade_date", "main_contract"],
            how="left",
            validate="one_to_one",
        )
    for column in (
        "phase_v2",
        "phase_v2_label",
        "phase_direction",
        "phase_quality",
        "participation_state",
        "roll_context",
        "confirmation_state",
    ):
        if column not in working.columns:
            working[column] = "not_connected"
        else:
            # 侧车未更新到当前交易日时，显式标记为未接入，避免NaN被误读成中性。
            working[column] = working[column].fillna("not_connected")

    if option_strike_position_path is not None:
        static = load_table(
            option_strike_position_path,
            required={"trade_date", "underlying_contract", "key_level_state"},
            label="R93N R84 strike position",
        )
        static = normalize_trade_date(static)
        static_columns = [
            "trade_date",
            "underlying_contract",
            "days_to_expiry",
            "expiry_bucket",
            "key_level_state",
            "call_wall_strike",
            "put_wall_strike",
            "max_pain_strike",
        ]
        for column in static_columns:
            if column not in static.columns:
                static[column] = None
        static = static[static_columns].rename(
            columns={
                "underlying_contract": "main_contract",
                "key_level_state": "r84_static_key_level_state",
                "call_wall_strike": "r84_call_wall_strike",
                "put_wall_strike": "r84_put_wall_strike",
                "max_pain_strike": "r84_max_pain_strike",
            }
        )
        static = static.drop_duplicates(["trade_date", "main_contract"], keep="last")
        working = working.merge(
            static,
            on=["trade_date", "main_contract"],
            how="left",
            validate="one_to_one",
        )
    if "expiry_bucket" not in working.columns:
        working["expiry_bucket"] = "UNKNOWN_DTE"
    working["expiry_bucket"] = working["expiry_bucket"].fillna("UNKNOWN_DTE")
    if "days_to_expiry" not in working.columns:
        working["days_to_expiry"] = math.nan
    if "r84_static_key_level_state" not in working.columns:
        working["r84_static_key_level_state"] = working["static_key_level_state"]
    working["r84_static_key_level_state"] = working[
        "r84_static_key_level_state"
    ].fillna(working["static_key_level_state"])
    working["joint_futures_option_node"] = working.apply(
        lambda row: _joint_node(
            _normalize_direction(row["futures_direction_5d"]),
            _normalize_direction(row["option_pressure_direction"]),
        ),
        axis=1,
    )
    return working


def _add_event_flags(
    features: pd.DataFrame,
    *,
    touch_band_ratio: float,
    wall_shift_bps: int,
) -> pd.DataFrame:
    working = features.sort_values(["main_contract", "trade_date"]).copy()
    grouped = working.groupby("main_contract", sort=False)
    working["previous_settle"] = grouped["underlying_settle"].shift(1)
    working["previous_call_wall"] = grouped["dynamic_call_wall_strike"].shift(1)
    working["previous_put_wall"] = grouped["dynamic_put_wall_strike"].shift(1)
    event_flags: list[str] = []
    primary_types: list[str] = []
    for row in working.itertuples(index=False):
        flags: list[str] = []
        price = _number_or_none(row.underlying_settle)
        previous_price = _number_or_none(row.previous_settle)
        call_wall = _number_or_none(getattr(row, "dynamic_call_wall_strike", None))
        put_wall = _number_or_none(getattr(row, "dynamic_put_wall_strike", None))
        previous_call = _number_or_none(row.previous_call_wall)
        previous_put = _number_or_none(row.previous_put_wall)
        high = _number_or_none(row.underlying_high)
        low = _number_or_none(row.underlying_low)
        if price is not None and call_wall is not None:
            if price < call_wall and call_wall / price - 1.0 <= touch_band_ratio:
                flags.append("CALL_APPROACH")
            if high is not None and high >= call_wall and price < call_wall:
                flags.append("CALL_TOUCH")
            if (
                previous_price is not None
                and previous_call is not None
                and previous_price < previous_call
                and price >= call_wall
            ):
                flags.append("CALL_BREAKOUT")
        if price is not None and put_wall is not None:
            if price > put_wall and price / put_wall - 1.0 <= touch_band_ratio:
                flags.append("PUT_APPROACH")
            if low is not None and low <= put_wall and price > put_wall:
                flags.append("PUT_TOUCH")
            if (
                previous_price is not None
                and previous_put is not None
                and previous_price > previous_put
                and price <= put_wall
            ):
                flags.append("PUT_BREAKOUT")
        if bool(getattr(row, "local_call_build_flag", False)):
            flags.append("LOCAL_CALL_BUILD")
        if bool(getattr(row, "local_call_unwind_flag", False)):
            flags.append("LOCAL_CALL_UNWIND")
        if bool(getattr(row, "local_put_build_flag", False)):
            flags.append("LOCAL_PUT_BUILD")
        if bool(getattr(row, "local_put_unwind_flag", False)):
            flags.append("LOCAL_PUT_UNWIND")
        call_shift = _number_or_none(getattr(row, "dynamic_call_wall_shift_bps", None))
        put_shift = _number_or_none(getattr(row, "dynamic_put_wall_shift_bps", None))
        if call_shift is not None and abs(call_shift) >= wall_shift_bps:
            flags.append("CALL_WALL_MIGRATION")
        if put_shift is not None and abs(put_shift) >= wall_shift_bps:
            flags.append("PUT_WALL_MIGRATION")
        if row.wall_range_state in {"WALL_RANGE_NARROWING", "WALL_RANGE_WIDENING"}:
            flags.append(str(row.wall_range_state))
        if str(row.joint_futures_option_node).endswith("DIVERGENCE"):
            flags.append("FUTURES_OPTION_DIVERGENCE")
        flags = list(dict.fromkeys(flags))
        event_flags.append(";".join(flags))
        primary_types.append(_primary_event_type(flags))
    working["event_flags"] = event_flags
    working["primary_event_type"] = primary_types
    working["event_trigger_observable_at_t"] = True
    return working.sort_values("trade_date").reset_index(drop=True)


def _build_event_table(*, features: pd.DataFrame, run_id: str) -> pd.DataFrame:
    columns = [
        "run_id",
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
        "static_key_level_state",
        "event_trigger_observable_at_t",
        "contains_posterior_outcome",
        "trading_instruction",
    ]
    rows: list[dict[str, object]] = []
    for row in features.loc[features["event_flags"].astype(str).ne("")].itertuples(
        index=False
    ):
        for event_type in str(row.event_flags).split(";"):
            rows.append(
                {
                    "run_id": run_id,
                    "event_id": f"{row.observation_id}_{event_type}",
                    "observation_id": row.observation_id,
                    "event_date": row.trade_date,
                    "main_contract": row.main_contract,
                    "event_type": event_type,
                    "event_direction": _event_direction(
                        event_type=event_type,
                        option_direction=row.option_pressure_direction,
                        futures_direction=row.futures_direction_5d,
                    ),
                    "option_market_stage": row.option_market_stage,
                    "data_activity_state": row.data_activity_state,
                    "trend_phase": row.phase_v2,
                    "expiry_bucket": row.expiry_bucket,
                    "dynamic_pressure_node": row.dynamic_pressure_node,
                    "joint_futures_option_node": row.joint_futures_option_node,
                    "futures_direction_5d": row.futures_direction_5d,
                    "option_pressure_direction": row.option_pressure_direction,
                    "static_key_level_state": row.static_key_level_state,
                    "event_trigger_observable_at_t": True,
                    "contains_posterior_outcome": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _build_posterior_labels(
    *,
    features: pd.DataFrame,
    quotes: pd.DataFrame,
    horizons: tuple[int, ...],
    dead_zone_bps: int,
    tbm_vol_multiplier: float,
    run_id: str,
) -> pd.DataFrame:
    columns = [
        "run_id",
        "observation_id",
        "trade_date",
        "main_contract",
        "calendar_year",
        "option_market_stage",
        "data_activity_state",
        "trend_phase",
        "expiry_bucket",
        "static_key_level_state",
        "dynamic_pressure_node",
        "joint_futures_option_node",
        "primary_event_type",
        "horizon",
        "execution_date",
        "exit_date",
        "entry_settle",
        "exit_settle",
        "forward_return",
        "long_mfe",
        "long_mae",
        "short_mfe",
        "short_mae",
        "call_wall_crossed",
        "put_wall_crossed",
        "futures_direction",
        "futures_directional_return",
        "futures_outcome",
        "futures_hit",
        "r48_option_direction",
        "r48_directional_return",
        "r48_outcome",
        "r48_hit",
        "dynamic_option_direction",
        "dynamic_directional_return",
        "dynamic_outcome",
        "dynamic_hit",
        "tbm_barrier_return",
        "tbm_outcome_long",
        "tbm_first_hit_session_long",
        "tbm_outcome_short",
        "tbm_first_hit_session_short",
        "forward_label_available",
        "t_plus_one_execution",
        "label_uses_post_t_prices",
        "forward_returns_are_historical_posterior_labels",
        "promotion_eligible",
        "trading_instruction",
    ]
    quote_groups: dict[str, pd.DataFrame] = {}
    quote_indexes: dict[tuple[str, date], int] = {}
    for contract, group in quotes.groupby("contract_code", sort=False):
        ordered = group.sort_values("trade_date").reset_index(drop=True).copy()
        ordered["settle_return_1d"] = ordered["settle"].pct_change()
        ordered["rolling_vol_20"] = ordered["settle_return_1d"].rolling(
            20, min_periods=5
        ).std()
        quote_groups[str(contract)] = ordered
        for index, trade_date in enumerate(ordered["trade_date"]):
            quote_indexes[(str(contract), trade_date)] = index
    dead_zone = dead_zone_bps / 10000.0
    rows: list[dict[str, object]] = []
    for feature in features.itertuples(index=False):
        contract = str(feature.main_contract)
        contract_quotes = quote_groups.get(contract)
        signal_index = quote_indexes.get((contract, feature.trade_date))
        if contract_quotes is None or signal_index is None:
            continue
        signal_vol = _number_or_none(contract_quotes.iloc[signal_index]["rolling_vol_20"])
        barrier = max(dead_zone, (signal_vol or dead_zone) * tbm_vol_multiplier)
        for horizon in horizons:
            entry_index = signal_index + 1
            exit_index = entry_index + horizon
            available = exit_index < len(contract_quotes)
            row = {
                "run_id": run_id,
                "observation_id": feature.observation_id,
                "trade_date": feature.trade_date,
                "main_contract": contract,
                "calendar_year": feature.trade_date.year,
                "option_market_stage": feature.option_market_stage,
                "data_activity_state": feature.data_activity_state,
                "trend_phase": feature.phase_v2,
                "expiry_bucket": feature.expiry_bucket,
                "static_key_level_state": feature.static_key_level_state,
                "dynamic_pressure_node": feature.dynamic_pressure_node,
                "joint_futures_option_node": feature.joint_futures_option_node,
                "primary_event_type": feature.primary_event_type,
                "horizon": horizon,
                "execution_date": None,
                "exit_date": None,
                "entry_settle": None,
                "exit_settle": None,
                "forward_return": None,
                "long_mfe": None,
                "long_mae": None,
                "short_mfe": None,
                "short_mae": None,
                "call_wall_crossed": None,
                "put_wall_crossed": None,
                "futures_direction": _normalize_direction(feature.futures_direction_5d),
                "futures_directional_return": None,
                "futures_outcome": "LABEL_UNAVAILABLE",
                "futures_hit": None,
                "r48_option_direction": _normalize_direction(
                    feature.r48_option_direction_5d
                ),
                "r48_directional_return": None,
                "r48_outcome": "LABEL_UNAVAILABLE",
                "r48_hit": None,
                "dynamic_option_direction": _normalize_direction(
                    feature.option_pressure_direction
                ),
                "dynamic_directional_return": None,
                "dynamic_outcome": "LABEL_UNAVAILABLE",
                "dynamic_hit": None,
                "tbm_barrier_return": barrier,
                "tbm_outcome_long": "LABEL_UNAVAILABLE",
                "tbm_first_hit_session_long": None,
                "tbm_outcome_short": "LABEL_UNAVAILABLE",
                "tbm_first_hit_session_short": None,
                "forward_label_available": available,
                "t_plus_one_execution": True,
                "label_uses_post_t_prices": True,
                "forward_returns_are_historical_posterior_labels": True,
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
            if available:
                entry = contract_quotes.iloc[entry_index]
                exit_row = contract_quotes.iloc[exit_index]
                path = contract_quotes.iloc[entry_index : exit_index + 1]
                entry_settle = float(entry["settle"])
                exit_settle = float(exit_row["settle"])
                forward_return = exit_settle / entry_settle - 1.0
                long_mfe, long_mae = _path_excursions(path, entry_settle, sign=1)
                short_mfe, short_mae = _path_excursions(path, entry_settle, sign=-1)
                long_tbm = _triple_barrier_path(path, entry_settle, barrier, sign=1)
                short_tbm = _triple_barrier_path(path, entry_settle, barrier, sign=-1)
                call_wall = _number_or_none(feature.dynamic_call_wall_strike)
                put_wall = _number_or_none(feature.dynamic_put_wall_strike)
                row.update(
                    {
                        "execution_date": entry["trade_date"],
                        "exit_date": exit_row["trade_date"],
                        "entry_settle": entry_settle,
                        "exit_settle": exit_settle,
                        "forward_return": forward_return,
                        "long_mfe": long_mfe,
                        "long_mae": long_mae,
                        "short_mfe": short_mfe,
                        "short_mae": short_mae,
                        "call_wall_crossed": (
                            None
                            if call_wall is None
                            else bool(
                                feature.underlying_settle < call_wall
                                and pd.to_numeric(path["high"], errors="coerce").max()
                                >= call_wall
                            )
                        ),
                        "put_wall_crossed": (
                            None
                            if put_wall is None
                            else bool(
                                feature.underlying_settle > put_wall
                                and pd.to_numeric(path["low"], errors="coerce").min()
                                <= put_wall
                            )
                        ),
                        "tbm_outcome_long": long_tbm[0],
                        "tbm_first_hit_session_long": long_tbm[1],
                        "tbm_outcome_short": short_tbm[0],
                        "tbm_first_hit_session_short": short_tbm[1],
                    }
                )
                for prefix, direction in (
                    ("futures", row["futures_direction"]),
                    ("r48", row["r48_option_direction"]),
                    ("dynamic", row["dynamic_option_direction"]),
                ):
                    directional = _directional_return(forward_return, str(direction))
                    outcome = _directional_outcome(directional, dead_zone)
                    row[f"{prefix}_directional_return"] = directional
                    row[f"{prefix}_outcome"] = outcome
                    row[f"{prefix}_hit"] = (
                        None if directional is None else bool(directional > dead_zone)
                    )
            rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def _build_event_labels(
    *,
    events: pd.DataFrame,
    labels: pd.DataFrame,
    dead_zone_bps: int,
    touch_band_ratio: float,
    run_id: str,
) -> pd.DataFrame:
    columns = [
        "run_id",
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
        "promotion_eligible",
        "trading_instruction",
    ]
    if events.empty or labels.empty:
        return pd.DataFrame(columns=columns)
    merged = events.merge(labels, on="observation_id", how="inner", suffixes=("", "_label"))
    dead_zone = dead_zone_bps / 10000.0
    rows: list[dict[str, object]] = []
    for row in merged.itertuples(index=False):
        direction = _normalize_direction(row.event_direction)
        forward_return = _number_or_none(row.forward_return)
        directional = _directional_return(forward_return, direction)
        outcome = _directional_outcome(directional, dead_zone)
        if direction == "long":
            mfe = _number_or_none(row.long_mfe)
            mae = _number_or_none(row.long_mae)
            tbm_outcome = row.tbm_outcome_long
            tbm_session = row.tbm_first_hit_session_long
        elif direction == "short":
            mfe = _number_or_none(row.short_mfe)
            mae = _number_or_none(row.short_mae)
            tbm_outcome = row.tbm_outcome_short
            tbm_session = row.tbm_first_hit_session_short
        else:
            mfe = None
            mae = None
            tbm_outcome = "NO_DIRECTION"
            tbm_session = None
        retest, failure, path_label = _event_path_label(
            event_type=str(row.event_type),
            direction=direction,
            outcome=outcome,
            mfe=mfe,
            mae=mae,
            touch_band_ratio=touch_band_ratio,
        )
        rows.append(
            {
                "run_id": run_id,
                "event_id": row.event_id,
                "observation_id": row.observation_id,
                "event_date": row.event_date,
                "main_contract": row.main_contract,
                "event_type": row.event_type,
                "event_direction": direction,
                "option_market_stage": row.option_market_stage,
                "data_activity_state": row.data_activity_state,
                "trend_phase": row.trend_phase,
                "expiry_bucket": row.expiry_bucket,
                "dynamic_pressure_node": row.dynamic_pressure_node,
                "joint_futures_option_node": row.joint_futures_option_node,
                "horizon": row.horizon,
                "execution_date": row.execution_date,
                "exit_date": row.exit_date,
                "forward_return": forward_return,
                "event_directional_return": directional,
                "event_outcome": outcome,
                "event_hit": None if directional is None else bool(directional > dead_zone),
                "event_mfe": mfe,
                "event_mae": mae,
                "tbm_outcome": tbm_outcome,
                "tbm_first_hit_session": tbm_session,
                "wall_retest_flag": retest,
                "wall_failure_flag": failure,
                "path_event_label": path_label,
                "forward_label_available": row.forward_label_available,
                "forward_returns_are_historical_posterior_labels": True,
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _build_horizon_summary(
    *, labels: pd.DataFrame, min_sample_size: int, run_id: str
) -> pd.DataFrame:
    columns = _summary_columns(prefix_columns=("option_market_stage", "horizon"))
    available = labels.loc[labels["forward_label_available"].astype(bool)].copy()
    rows: list[dict[str, object]] = []
    for stage in ["ALL", "EARLY_THIN", "EXPANSION", "MATURE_ACTIVE"]:
        stage_rows = available if stage == "ALL" else available.loc[
            available["option_market_stage"].eq(stage)
        ]
        for horizon, group in stage_rows.groupby("horizon", sort=True):
            metrics = _signal_metrics(group, min_sample_size=min_sample_size)
            rows.append(
                {
                    "run_id": run_id,
                    "option_market_stage": stage,
                    "horizon": int(horizon),
                    **metrics,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _build_node_summary(
    *,
    labels: pd.DataFrame,
    event_labels: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
    run_id: str,
) -> pd.DataFrame:
    columns = [
        "run_id",
        "node_type",
        "node_value",
        "option_market_stage",
        "horizon",
        *_summary_metric_columns(),
        "annual_comparable_years",
        "annual_positive_years",
        "annual_direction_consistency",
        "incremental_p_value",
        "fdr_q_value",
        "evidence_status",
        "promotion_eligible",
        "trading_instruction",
    ]
    available = labels.loc[labels["forward_label_available"].astype(bool)].copy()
    rows: list[dict[str, object]] = []
    node_columns = {
        "DYNAMIC_PRESSURE": "dynamic_pressure_node",
        "JOINT_FUTURES_OPTION": "joint_futures_option_node",
        "STATIC_WALL_STATE": "static_key_level_state",
        "TREND_PHASE": "trend_phase",
        "EXPIRY_BUCKET": "expiry_bucket",
    }
    for node_type, column in node_columns.items():
        for (stage, horizon, value), group in available.groupby(
            ["option_market_stage", "horizon", column], dropna=False, sort=True
        ):
            metrics = _signal_metrics(group, min_sample_size=min_sample_size)
            annual = _annual_incremental_stability(group)
            rows.append(
                {
                    "run_id": run_id,
                    "node_type": node_type,
                    "node_value": str(value),
                    "option_market_stage": str(stage),
                    "horizon": int(horizon),
                    **metrics,
                    **annual,
                    "incremental_p_value": _paired_incremental_p_value(group),
                    "fdr_q_value": math.nan,
                    "evidence_status": "PENDING_FDR",
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    if not event_labels.empty:
        available_events = event_labels.loc[
            event_labels["forward_label_available"].astype(bool)
        ].copy()
        for (stage, horizon, event_type), group in available_events.groupby(
            ["option_market_stage", "horizon", "event_type"], sort=True
        ):
            event_metrics = _event_signal_metrics(group, min_sample_size=min_sample_size)
            rows.append(
                {
                    "run_id": run_id,
                    "node_type": "EVENT_TYPE",
                    "node_value": str(event_type),
                    "option_market_stage": str(stage),
                    "horizon": int(horizon),
                    **event_metrics,
                    "annual_comparable_years": 0,
                    "annual_positive_years": 0,
                    "annual_direction_consistency": math.nan,
                    "incremental_p_value": _exact_binomial_two_sided(
                        int(pd.Series(group["event_hit"]).fillna(False).astype(bool).sum()),
                        int(pd.Series(group["event_hit"]).notna().sum()),
                    ),
                    "fdr_q_value": math.nan,
                    "evidence_status": "PENDING_FDR",
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    summary = pd.DataFrame(rows, columns=columns)
    tested = summary["incremental_p_value"].notna()
    if tested.any():
        summary.loc[tested, "fdr_q_value"] = _benjamini_hochberg(
            summary.loc[tested, "incremental_p_value"].astype(float).tolist()
        )
    summary["evidence_status"] = summary.apply(
        lambda row: _node_evidence_status(
            row=row,
            min_sample_size=min_sample_size,
            fdr_level=fdr_level,
        ),
        axis=1,
    )
    return summary.sort_values(
        ["evidence_status", "sample_count", "node_type", "horizon"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)


def _build_leave_one_year_out_summary(
    *, labels: pd.DataFrame, min_sample_size: int, run_id: str
) -> pd.DataFrame:
    columns = [
        "run_id",
        "horizon",
        "dynamic_pressure_node",
        "test_year",
        "train_years",
        "train_sample_count",
        "train_dynamic_mean_directional_return",
        "train_r48_mean_directional_return",
        "train_incremental_mean_return",
        "selected_in_train",
        "test_sample_count",
        "test_dynamic_hit_rate",
        "test_r48_hit_rate",
        "test_dynamic_mean_directional_return",
        "test_r48_mean_directional_return",
        "test_incremental_hit_rate",
        "test_incremental_mean_return",
        "oos_status",
        "test_year_is_partial",
        "promotion_eligible",
        "trading_instruction",
    ]
    mature = labels.loc[
        labels["forward_label_available"].astype(bool)
        & labels["option_market_stage"].eq("MATURE_ACTIVE")
        & labels["dynamic_option_direction"].isin(["long", "short"])
    ].copy()
    years = sorted(set(int(value) for value in mature["calendar_year"]))
    rows: list[dict[str, object]] = []
    if len(years) < 2:
        return pd.DataFrame(columns=columns)
    for (horizon, node), node_rows in mature.groupby(
        ["horizon", "dynamic_pressure_node"], sort=True
    ):
        for test_year in years:
            train = node_rows.loc[node_rows["calendar_year"].ne(test_year)]
            test = node_rows.loc[node_rows["calendar_year"].eq(test_year)]
            train_metrics = _signal_metrics(train, min_sample_size=min_sample_size)
            test_metrics = _signal_metrics(test, min_sample_size=min_sample_size)
            train_delta = _number_or_none(train_metrics["dynamic_minus_r48_mean_return"])
            selected = len(train) >= min_sample_size and train_delta is not None and train_delta > 0
            test_delta = _number_or_none(test_metrics["dynamic_minus_r48_mean_return"])
            if not selected:
                status = "NOT_SELECTED_IN_TRAIN"
            elif len(test) < max(5, min_sample_size // 3):
                status = "TEST_SMALL_SAMPLE"
            elif test_delta is not None and test_delta > 0:
                status = "OOS_POSITIVE"
            else:
                status = "OOS_NO_INCREMENT"
            rows.append(
                {
                    "run_id": run_id,
                    "horizon": int(horizon),
                    "dynamic_pressure_node": str(node),
                    "test_year": test_year,
                    "train_years": ";".join(str(value) for value in years if value != test_year),
                    "train_sample_count": len(train),
                    "train_dynamic_mean_directional_return": train_metrics[
                        "dynamic_mean_directional_return"
                    ],
                    "train_r48_mean_directional_return": train_metrics[
                        "r48_mean_directional_return"
                    ],
                    "train_incremental_mean_return": train_delta,
                    "selected_in_train": selected,
                    "test_sample_count": len(test),
                    "test_dynamic_hit_rate": test_metrics["dynamic_hit_rate"],
                    "test_r48_hit_rate": test_metrics["r48_hit_rate"],
                    "test_dynamic_mean_directional_return": test_metrics[
                        "dynamic_mean_directional_return"
                    ],
                    "test_r48_mean_directional_return": test_metrics[
                        "r48_mean_directional_return"
                    ],
                    "test_incremental_hit_rate": test_metrics[
                        "dynamic_minus_r48_hit_rate"
                    ],
                    "test_incremental_mean_return": test_delta,
                    "oos_status": status,
                    "test_year_is_partial": test_year == max(years),
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _build_resolution_timing(
    *, event_labels: pd.DataFrame, min_sample_size: int, run_id: str
) -> pd.DataFrame:
    columns = [
        "run_id",
        "event_type",
        "option_market_stage",
        "sample_count",
        "resolved_event_count",
        "follow_through_count",
        "failed_count",
        "unresolved_count",
        "mean_resolution_session",
        "median_resolution_session",
        "retest_rate",
        "failure_rate",
        "evidence_level",
        "forward_returns_are_historical_posterior_labels",
        "promotion_eligible",
        "trading_instruction",
    ]
    if event_labels.empty:
        return pd.DataFrame(columns=columns)
    five_day = event_labels.loc[
        event_labels["horizon"].eq(5)
        & event_labels["forward_label_available"].astype(bool)
    ].copy()
    rows: list[dict[str, object]] = []
    for (event_type, stage), group in five_day.groupby(
        ["event_type", "option_market_stage"], sort=True
    ):
        sessions = pd.to_numeric(group["tbm_first_hit_session"], errors="coerce").dropna()
        sample_count = len(group)
        follow = int(group["event_outcome"].eq("FOLLOW_THROUGH").sum())
        failed = int(group["event_outcome"].eq("FAILED").sum())
        unresolved = int(group["event_outcome"].eq("UNRESOLVED").sum())
        rows.append(
            {
                "run_id": run_id,
                "event_type": str(event_type),
                "option_market_stage": str(stage),
                "sample_count": sample_count,
                "resolved_event_count": int(sessions.size),
                "follow_through_count": follow,
                "failed_count": failed,
                "unresolved_count": unresolved,
                "mean_resolution_session": (
                    math.nan if sessions.empty else float(sessions.mean())
                ),
                "median_resolution_session": (
                    math.nan if sessions.empty else float(sessions.median())
                ),
                "retest_rate": _bool_mean(group["wall_retest_flag"]),
                "failure_rate": _bool_mean(group["wall_failure_flag"]),
                "evidence_level": _sample_evidence(sample_count, min_sample_size),
                "forward_returns_are_historical_posterior_labels": True,
                "promotion_eligible": False,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["sample_count", "event_type"], ascending=[False, True]
    ).reset_index(drop=True)


def _signal_metrics(group: pd.DataFrame, *, min_sample_size: int) -> dict[str, object]:
    available = group.loc[group["forward_label_available"].astype(bool)].copy()
    forward = pd.to_numeric(available["forward_return"], errors="coerce").dropna()
    futures_directional = pd.to_numeric(
        available["futures_directional_return"], errors="coerce"
    ).dropna()
    r48_directional = pd.to_numeric(
        available["r48_directional_return"], errors="coerce"
    ).dropna()
    dynamic_directional = pd.to_numeric(
        available["dynamic_directional_return"], errors="coerce"
    ).dropna()
    futures_hit = _bool_mean(available["futures_hit"])
    r48_hit = _bool_mean(available["r48_hit"])
    dynamic_hit = _bool_mean(available["dynamic_hit"])
    return {
        "sample_count": len(available),
        "futures_direction_sample_count": len(futures_directional),
        "r48_direction_sample_count": len(r48_directional),
        "dynamic_direction_sample_count": len(dynamic_directional),
        "mean_forward_return": _mean_or_nan(forward),
        "median_forward_return": _median_or_nan(forward),
        "futures_hit_rate": futures_hit,
        "r48_hit_rate": r48_hit,
        "dynamic_hit_rate": dynamic_hit,
        "futures_mean_directional_return": _mean_or_nan(futures_directional),
        "r48_mean_directional_return": _mean_or_nan(r48_directional),
        "dynamic_mean_directional_return": _mean_or_nan(dynamic_directional),
        "dynamic_minus_r48_hit_rate": _difference(dynamic_hit, r48_hit),
        "dynamic_minus_r48_mean_return": _difference(
            _mean_or_none(dynamic_directional), _mean_or_none(r48_directional)
        ),
        "mean_dynamic_mfe": _directional_excursion_mean(available, "mfe"),
        "mean_dynamic_mae": _directional_excursion_mean(available, "mae"),
        "call_wall_cross_rate": _bool_mean(available["call_wall_crossed"]),
        "put_wall_cross_rate": _bool_mean(available["put_wall_crossed"]),
        "evidence_level": _sample_evidence(len(available), min_sample_size),
    }


def _event_signal_metrics(
    group: pd.DataFrame, *, min_sample_size: int
) -> dict[str, object]:
    event_returns = pd.to_numeric(group["event_directional_return"], errors="coerce").dropna()
    event_hits = _bool_mean(group["event_hit"])
    return {
        "sample_count": len(group),
        "futures_direction_sample_count": 0,
        "r48_direction_sample_count": 0,
        "dynamic_direction_sample_count": len(event_returns),
        "mean_forward_return": _mean_or_nan(
            pd.to_numeric(group["forward_return"], errors="coerce").dropna()
        ),
        "median_forward_return": _median_or_nan(
            pd.to_numeric(group["forward_return"], errors="coerce").dropna()
        ),
        "futures_hit_rate": math.nan,
        "r48_hit_rate": math.nan,
        "dynamic_hit_rate": event_hits,
        "futures_mean_directional_return": math.nan,
        "r48_mean_directional_return": math.nan,
        "dynamic_mean_directional_return": _mean_or_nan(event_returns),
        "dynamic_minus_r48_hit_rate": math.nan,
        "dynamic_minus_r48_mean_return": math.nan,
        "mean_dynamic_mfe": _mean_or_nan(
            pd.to_numeric(group["event_mfe"], errors="coerce").dropna()
        ),
        "mean_dynamic_mae": _mean_or_nan(
            pd.to_numeric(group["event_mae"], errors="coerce").dropna()
        ),
        "call_wall_cross_rate": math.nan,
        "put_wall_cross_rate": math.nan,
        "evidence_level": _sample_evidence(len(group), min_sample_size),
    }


def _annual_incremental_stability(group: pd.DataFrame) -> dict[str, object]:
    comparable = group.loc[
        group["dynamic_directional_return"].notna()
        & group["r48_directional_return"].notna()
    ].copy()
    annual_deltas: list[float] = []
    for _year, year_rows in comparable.groupby("calendar_year", sort=True):
        dynamic_mean = pd.to_numeric(
            year_rows["dynamic_directional_return"], errors="coerce"
        ).mean()
        r48_mean = pd.to_numeric(
            year_rows["r48_directional_return"], errors="coerce"
        ).mean()
        if pd.notna(dynamic_mean) and pd.notna(r48_mean):
            annual_deltas.append(float(dynamic_mean - r48_mean))
    positive = sum(value > 0 for value in annual_deltas)
    return {
        "annual_comparable_years": len(annual_deltas),
        "annual_positive_years": positive,
        "annual_direction_consistency": (
            math.nan if not annual_deltas else positive / len(annual_deltas)
        ),
    }


def _paired_incremental_p_value(group: pd.DataFrame) -> float:
    comparable = group.loc[group["dynamic_hit"].notna() & group["r48_hit"].notna()]
    if comparable.empty:
        return math.nan
    dynamic = comparable["dynamic_hit"].astype(bool)
    r48 = comparable["r48_hit"].astype(bool)
    dynamic_only = int((dynamic & ~r48).sum())
    r48_only = int((~dynamic & r48).sum())
    discordant = dynamic_only + r48_only
    return _exact_binomial_two_sided(dynamic_only, discordant)


def _node_evidence_status(
    *, row: pd.Series, min_sample_size: int, fdr_level: float
) -> str:
    sample_count = int(row["sample_count"])
    if sample_count < min_sample_size:
        return "WEAK_OR_SMALL_SAMPLE"
    delta = _number_or_none(row["dynamic_minus_r48_mean_return"])
    q_value = _number_or_none(row["fdr_q_value"])
    annual_years = int(row["annual_comparable_years"])
    annual_consistency = _number_or_none(row["annual_direction_consistency"])
    if (
        row["node_type"] == "EVENT_TYPE"
        and q_value is not None
        and q_value <= fdr_level
        and _number_or_none(row["dynamic_mean_directional_return"]) is not None
        and float(row["dynamic_mean_directional_return"]) > 0
    ):
        return "READY_CANDIDATE"
    if (
        delta is not None
        and delta > 0
        and q_value is not None
        and q_value <= fdr_level
        and annual_years >= 2
        and annual_consistency is not None
        and annual_consistency >= 2 / 3
    ):
        return "READY_CANDIDATE"
    if delta is not None and delta > 0:
        return "WATCH"
    return "NO_INCREMENT"


def _warning_records(
    *,
    run_id: str,
    quote_missing_ranges: list[str],
    exclusion_counts: dict[str, int],
    features: pd.DataFrame,
    labels: pd.DataFrame,
    summary_by_node: pd.DataFrame,
    oos_summary: pd.DataFrame,
    factor_path: Path | None,
    matrix_path: Path | None,
    phase_path: Path | None,
    strike_path: Path | None,
    feature_end: date,
) -> list[FuturesOptionDynamicWallWarningRecord]:
    missing_chain = int((~features["option_chain_available"].fillna(False)).sum())
    unavailable_labels = int((~labels["forward_label_available"].fillna(False)).sum())
    small_nodes = int(
        summary_by_node["evidence_status"].eq("WEAK_OR_SMALL_SAMPLE").sum()
    )
    missing_sidecars = [
        name
        for name, path in (
            ("R48_OPTION_FACTOR", factor_path),
            ("R35_SIGNAL_MATRIX", matrix_path),
            ("R76_TREND_PHASE", phase_path),
            ("R84_STATIC_WALL", strike_path),
        )
        if path is None
    ]
    stale_sidecars = _stale_sidecars(
        feature_end=feature_end,
        paths=(
            ("R48_OPTION_FACTOR", factor_path),
            ("R35_SIGNAL_MATRIX", matrix_path),
            ("R76_TREND_PHASE", phase_path),
            ("R84_STATIC_WALL", strike_path),
        ),
    )
    return [
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="research_boundary",
            severity=INFO,
            warning_code="OPTION_OI_OWNERSHIP_UNKNOWN",
            warning_message="公开期权持仓无法识别买方、卖方或做市商净Gamma，动态墙方向仅为结构压力proxy。",
            affected_count=len(features),
            human_review_required="option_open_interest_long_short_ownership_unknown",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="feature_filter",
            severity=INFO,
            warning_code="OPTION_LOW_LIQUIDITY_EXCLUDED",
            warning_message="低流动性期权保留在静态墙基线，但不进入动态局部墙核心特征。",
            affected_count=exclusion_counts["low_liquidity"],
            human_review_required="dynamic_wall_direction_proxy_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="feature_filter",
            severity=INFO,
            warning_code="OPTION_DEEP_OTM_EXCLUDED",
            warning_message="深虚值proxy保留在静态结构，但不进入动态局部墙核心特征。",
            affected_count=exclusion_counts["deep_otm"],
            human_review_required="dynamic_wall_direction_proxy_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="price_range",
            severity=WARN if quote_missing_ranges else INFO,
            warning_code="FUTURES_PRICE_RANGE_FALLBACK",
            warning_message=(
                "core缺少部分high/low/close字段，相关触及路径回退到结算价。"
                if quote_missing_ranges
                else "期货high/low/close字段完整。"
            ),
            affected_count=len(quote_missing_ranges),
            human_review_required="event_lifecycle_label_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="option_chain",
            severity=WARN if missing_chain else INFO,
            warning_code="MAIN_OPTION_CHAIN_MISSING",
            warning_message="部分研究主力交易日缺少同标的期权链，动态墙特征已留空。",
            affected_count=missing_chain,
            human_review_required="option_expiry_and_dte_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="posterior_label",
            severity=INFO,
            warning_code="FORWARD_LABEL_POSTERIOR_ONLY",
            warning_message="T+1后的收益、TBM、MFE、MAE只进入物理分离的历史后验标签表。",
            affected_count=unavailable_labels,
            human_review_required="event_lifecycle_label_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="sample_size",
            severity=WARN if small_nodes else INFO,
            warning_code="DYNAMIC_WALL_SMALL_SAMPLE_NODES",
            warning_message="部分动态墙节点样本不足，证据已降级而未隐藏。",
            affected_count=small_nodes,
            human_review_required="oos_incremental_evidence_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="sidecar",
            severity=WARN if missing_sidecars else INFO,
            warning_code="OPTION_RESEARCH_SIDECAR_MISSING",
            warning_message=(
                "缺少侧车：" + ",".join(missing_sidecars)
                if missing_sidecars
                else "R35/R48/R76/R84侧车均已接入。"
            ),
            affected_count=len(missing_sidecars),
            human_review_required="dynamic_wall_direction_proxy_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="sidecar_freshness",
            severity=WARN if stale_sidecars else INFO,
            warning_code="OPTION_RESEARCH_SIDECAR_ASOF_BEHIND",
            warning_message=(
                "侧车未覆盖特征最新日，缺失日期使用not_connected或动态墙自身基线："
                + ",".join(stale_sidecars)
                if stale_sidecars
                else "R35/R48/R76/R84侧车均覆盖特征最新日。"
            ),
            affected_count=len(stale_sidecars),
            human_review_required="dynamic_wall_direction_proxy_interpretation",
        ),
        FuturesOptionDynamicWallWarningRecord(
            run_id=run_id,
            section="oos",
            severity=WARN if oos_summary.empty else INFO,
            warning_code="MATURE_MARKET_LOYO_STATUS",
            warning_message=(
                "成熟市场年份不足，无法完成逐年留一验证。"
                if oos_summary.empty
                else "2024-2026逐年留一结果为历史研究证据，2026仍为不完整年度。"
            ),
            affected_count=len(oos_summary),
            human_review_required="oos_incremental_evidence_interpretation",
        ),
    ]


def _stale_sidecars(
    *,
    feature_end: date,
    paths: tuple[tuple[str, Path | None], ...],
) -> list[str]:
    """识别未覆盖特征最新交易日的研究侧车，避免日期错位静默传播。"""
    stale: list[str] = []
    for name, path in paths:
        if path is None:
            continue
        frame = pd.read_parquet(path, columns=["trade_date"])
        if frame.empty:
            stale.append(f"{name}=EMPTY")
            continue
        dates = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date.dropna()
        latest = max(dates) if not dates.empty else None
        if latest is None or latest < feature_end:
            stale.append(f"{name}={latest or 'UNKNOWN'}<{feature_end}")
    return stale


def _write_outputs(
    *,
    paths: dict[str, Path],
    features: pd.DataFrame,
    events: pd.DataFrame,
    labels: pd.DataFrame,
    event_labels: pd.DataFrame,
    summary_by_horizon: pd.DataFrame,
    summary_by_node: pd.DataFrame,
    oos_summary: pd.DataFrame,
    resolution_timing: pd.DataFrame,
    warnings: list[FuturesOptionDynamicWallWarningRecord],
) -> None:
    write_frame(features, paths["feature_parquet"], paths["feature_csv"])
    write_frame(events, paths["event_parquet"], paths["event_csv"])
    write_frame(labels, paths["label_parquet"], paths["label_csv"])
    write_frame(
        event_labels,
        paths["event_label_parquet"],
        paths["event_label_csv"],
    )
    write_frame(
        summary_by_horizon,
        paths["horizon_parquet"],
        paths["horizon_csv"],
    )
    write_frame(summary_by_node, paths["node_parquet"], paths["node_csv"])
    write_frame(oos_summary, paths["oos_parquet"], paths["oos_csv"])
    write_frame(
        resolution_timing,
        paths["resolution_parquet"],
        paths["resolution_csv"],
    )
    write_warning_csv(paths["warning_csv"], [item.to_summary() for item in warnings])


def _paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_futures_option_dynamic_wall"
    data_root = output_dir or (
        data_dir() / "research" / PRODUCT_CODE / "futures_option_dynamic_wall"
    )
    report_root = report_output_dir or (
        reports_dir() / "research" / "futures_option_dynamic_wall"
    )
    return {
        "feature_parquet": data_root / f"{stem}_feature_daily.parquet",
        "feature_csv": data_root / f"{stem}_feature_daily.csv",
        "event_parquet": data_root / f"{stem}_event_daily.parquet",
        "event_csv": data_root / f"{stem}_event_daily.csv",
        "label_parquet": data_root / f"{stem}_lifecycle_label_daily.parquet",
        "label_csv": data_root / f"{stem}_lifecycle_label_daily.csv",
        "event_label_parquet": data_root / f"{stem}_event_lifecycle_label.parquet",
        "event_label_csv": data_root / f"{stem}_event_lifecycle_label.csv",
        "horizon_parquet": data_root / f"{stem}_summary_by_horizon.parquet",
        "horizon_csv": data_root / f"{stem}_summary_by_horizon.csv",
        "node_parquet": data_root / f"{stem}_summary_by_node.parquet",
        "node_csv": data_root / f"{stem}_summary_by_node.csv",
        "oos_parquet": data_root / f"{stem}_leave_one_year_out.parquet",
        "oos_csv": data_root / f"{stem}_leave_one_year_out.csv",
        "resolution_parquet": data_root / f"{stem}_resolution_timing.parquet",
        "resolution_csv": data_root / f"{stem}_resolution_timing.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
        "manifest": report_root / f"{stem}_manifest.json",
    }


def _write_markdown(
    *,
    result: ResearchFuturesOptionDynamicWallResult,
    latest: dict[str, object],
    summary_by_horizon: pd.DataFrame,
    summary_by_node: pd.DataFrame,
    oos_summary: pd.DataFrame,
    resolution_timing: pd.DataFrame,
) -> None:
    lines = [
        "# CF R93N 动态期权墙与5D增量研究",
        "",
        "## 数据状态",
        "",
        f"- 样本区间：`{result.start}` 至 `{result.end}`。",
        f"- T日可观察特征：`{result.feature_row_count}` 行；事件：`{result.event_row_count}` 行。",
        f"- T+1后验标签：`{result.label_row_count}` 行；"
        f"事件标签：`{result.event_label_row_count}` 行。",
        f"- 成熟市场特征样本：`{result.mature_feature_count}` 行。",
        "- 市场阶段：2021为EARLY_THIN，2022-2023为EXPANSION，2024-2026为MATURE_ACTIVE。",
        "",
        "## 研究定义",
        "",
        "- 静态墙保留全部有效持仓，用作R84基准；动态墙排除低流动性和深虚值proxy。",
        "- 动态特征包括局部行权价簇、墙体强度、1D变化、迁移、"
        "区间收窄/扩张及其与期货方向的组合节点。",
        "- 期权持仓无法识别买卖方，因此DYNAMIC_LONG/SHORT_PRESSURE"
        "只是结构压力proxy，不是净多空结论。",
        "- 评价标签使用T+1执行，绝不赚取T到T+1收益；同时输出固定1D/3D/5D、TBM、MFE和MAE。",
        "",
        "## 最新结构",
        "",
        f"- 研究主力：`{latest.get('main_contract')}`；"
        f"结算价：`{fmt_number(latest.get('underlying_settle'), 0)}`。",
        f"- 动态Call/Put墙：`{fmt_number(latest.get('dynamic_call_wall_strike'), 0)}`"
        f" / `{fmt_number(latest.get('dynamic_put_wall_strike'), 0)}`。",
        f"- 局部Call/Put OI变化："
        f"`{fmt_number(latest.get('local_call_open_interest_change'), 0)}`"
        f" / `{fmt_number(latest.get('local_put_open_interest_change'), 0)}`。",
        f"- 动态压力：`{latest.get('dynamic_pressure_node')}`，"
        f"得分 `{fmt_number(latest.get('option_pressure_score'), 0)}`。",
        f"- 期货-期权组合节点：`{latest.get('joint_futures_option_node')}`。",
        f"- 静态位置 / 到期桶：`{latest.get('static_key_level_state')}`"
        f" / `{latest.get('expiry_bucket')}`。",
        f"- 事件标记：`{latest.get('event_flags') or 'NO_EVENT'}`。",
        "",
        "## 总体1D/3D/5D证据",
        "",
        "| 阶段 | 周期 | 样本 | 期货命中 | R48命中 | 动态墙命中 | 动态-R48收益差 | 证据 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    display_horizon = summary_by_horizon.loc[
        summary_by_horizon["option_market_stage"].isin(["ALL", "MATURE_ACTIVE"])
    ]
    for row in display_horizon.itertuples(index=False):
        lines.append(
            f"| {row.option_market_stage} | {row.horizon}D | {row.sample_count} | "
            f"{fmt_percent(row.futures_hit_rate)} | {fmt_percent(row.r48_hit_rate)} | "
            f"{fmt_percent(row.dynamic_hit_rate)} | "
            f"{fmt_percent(row.dynamic_minus_r48_mean_return)} | {row.evidence_level} |"
        )
    lines.extend(
        [
            "",
            "## 动态墙节点与增量",
            "",
            "| 节点类型 | 节点 | 阶段 | 周期 | 样本 | 动态命中 | "
            "动态-R48收益差 | q值 | 年度一致性 | 结论 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    focus_nodes = summary_by_node.loc[
        summary_by_node["node_type"].isin(
            ["DYNAMIC_PRESSURE", "JOINT_FUTURES_OPTION", "EVENT_TYPE"]
        )
    ].copy()
    priority = {
        "READY_CANDIDATE": 0,
        "WATCH": 1,
        "NO_INCREMENT": 2,
        "WEAK_OR_SMALL_SAMPLE": 3,
    }
    focus_nodes["_priority"] = focus_nodes["evidence_status"].map(priority).fillna(9)
    focus_nodes = focus_nodes.sort_values(
        ["_priority", "sample_count"], ascending=[True, False]
    ).head(20)
    for row in focus_nodes.itertuples(index=False):
        lines.append(
            f"| {row.node_type} | {row.node_value} | {row.option_market_stage} | "
            f"{row.horizon}D | {row.sample_count} | {fmt_percent(row.dynamic_hit_rate)} | "
            f"{fmt_percent(row.dynamic_minus_r48_mean_return)} | "
            f"{fmt_number(row.fdr_q_value, 3)} | "
            f"{fmt_percent(row.annual_direction_consistency)} | {row.evidence_status} |"
        )
    lines.extend(
        [
            "",
            "## 事件生命周期与解决周期",
            "",
            "| 事件 | 阶段 | 样本 | 跟随 | 失败 | 未解决 | 平均解决交易日 | 回踩率 | 证据 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in resolution_timing.head(18).itertuples(index=False):
        lines.append(
            f"| {row.event_type} | {row.option_market_stage} | {row.sample_count} | "
            f"{row.follow_through_count} | {row.failed_count} | {row.unresolved_count} | "
            f"{fmt_number(row.mean_resolution_session, 2)} | {fmt_percent(row.retest_rate)} | "
            f"{row.evidence_level} |"
        )
    lines.extend(
        [
            "",
            "## 2024-2026逐年留一验证",
            "",
            "| 周期 | 节点 | 测试年 | 训练样本 | 是否入选 | 测试样本 | 测试增量收益 | 状态 |",
            "| ---: | --- | ---: | ---: | --- | ---: | ---: | --- |",
        ]
    )
    if oos_summary.empty:
        lines.append("| - | - | - | 0 | 否 | 0 | - | 年份不足 |")
    else:
        for row in oos_summary.head(24).itertuples(index=False):
            lines.append(
                f"| {row.horizon}D | {row.dynamic_pressure_node} | {row.test_year} | "
                f"{row.train_sample_count} | {'是' if row.selected_in_train else '否'} | "
                f"{row.test_sample_count} | {fmt_percent(row.test_incremental_mean_return)} | "
                f"{row.oos_status} |"
            )
    lines.extend(
        [
            "",
            "## 研究结论读取规则",
            "",
            "- READY_CANDIDATE只表示历史研究候选，不等于可交易规则，也不自动进入综合评分。",
            "- WATCH表示存在方向性线索但尚未通过显著性、年度稳定性或样本外检验。",
            "- NO_INCREMENT表示相对R48或期货基准没有观察到稳定增量，不应继续堆叠同类因子。",
            "- 静态最大持仓墙主要是结构位置；真正的5D辅助价值由局部持仓变化、"
            "迁移、触及和回踩路径共同检验。",
            "",
            "## 研究边界",
            "",
            "- forward return仅为历史后验验证标签，T日特征表不含未来收益。",
            "- 期权IV/Greek仍是研究proxy，公开数据不能识别主动买方、卖方或净Gamma。",
            "- 本模块不修改signal_matrix、composite_score、策略方向或仓位。",
            "- 所有结果均为研究仿真，不构成交易指令。",
            "",
            "## HUMAN_REVIEW_REQUIRED",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in HUMAN_REVIEW_REQUIRED)
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summary_columns(prefix_columns: tuple[str, ...]) -> list[str]:
    return ["run_id", *prefix_columns, *_summary_metric_columns()]


def _summary_metric_columns() -> list[str]:
    return [
        "sample_count",
        "futures_direction_sample_count",
        "r48_direction_sample_count",
        "dynamic_direction_sample_count",
        "mean_forward_return",
        "median_forward_return",
        "futures_hit_rate",
        "r48_hit_rate",
        "dynamic_hit_rate",
        "futures_mean_directional_return",
        "r48_mean_directional_return",
        "dynamic_mean_directional_return",
        "dynamic_minus_r48_hit_rate",
        "dynamic_minus_r48_mean_return",
        "mean_dynamic_mfe",
        "mean_dynamic_mae",
        "call_wall_cross_rate",
        "put_wall_cross_rate",
        "evidence_level",
    ]


def _directional_excursion_mean(frame: pd.DataFrame, kind: str) -> float:
    values: list[float] = []
    for row in frame.itertuples(index=False):
        direction = _normalize_direction(row.dynamic_option_direction)
        column = f"{'long' if direction == 'long' else 'short'}_{kind}"
        if direction not in {"long", "short"}:
            continue
        value = _number_or_none(getattr(row, column))
        if value is not None:
            values.append(value)
    return math.nan if not values else float(np.mean(values))


def _path_excursions(
    path: pd.DataFrame, entry_settle: float, *, sign: int
) -> tuple[float, float]:
    highs = pd.to_numeric(path["high"], errors="coerce") / entry_settle - 1.0
    lows = pd.to_numeric(path["low"], errors="coerce") / entry_settle - 1.0
    if sign == 1:
        return float(highs.max()), float(lows.min())
    return float((-lows).max()), float((-highs).min())


def _triple_barrier_path(
    path: pd.DataFrame, entry_settle: float, barrier: float, *, sign: int
) -> tuple[str, int | None]:
    for session, row in enumerate(path.itertuples(index=False)):
        high_return = float(row.high) / entry_settle - 1.0
        low_return = float(row.low) / entry_settle - 1.0
        favorable = high_return if sign == 1 else -low_return
        adverse = low_return if sign == 1 else -high_return
        upper_hit = favorable >= barrier
        lower_hit = adverse <= -barrier
        if upper_hit and lower_hit:
            return "AMBIGUOUS_SAME_SESSION", session
        if upper_hit:
            return "UPPER_BARRIER", session
        if lower_hit:
            return "LOWER_BARRIER", session
    return "TIME_BARRIER", None


def _event_path_label(
    *,
    event_type: str,
    direction: str,
    outcome: str,
    mfe: float | None,
    mae: float | None,
    touch_band_ratio: float,
) -> tuple[bool | None, bool | None, str]:
    if direction not in {"long", "short"}:
        return None, None, "NO_DIRECTIONAL_EVENT_SIDE"
    retest = (
        mae is not None
        and mae <= 0
        and abs(mae) <= max(touch_band_ratio * 1.5, 0.005)
        and mfe is not None
        and mfe > 0
    )
    failure = outcome == "FAILED"
    if "BREAKOUT" in event_type:
        if failure:
            return retest, True, "BREAKOUT_FAILURE"
        if retest and outcome == "FOLLOW_THROUGH":
            return True, False, "BREAKOUT_RETEST_HELD"
        if outcome == "FOLLOW_THROUGH":
            return False, False, "BREAKOUT_FOLLOW_THROUGH"
        return retest, False, "BREAKOUT_UNRESOLVED"
    if "APPROACH" in event_type or "TOUCH" in event_type:
        return retest, failure, f"{event_type}_{outcome}"
    return retest, failure, outcome


def _event_direction(
    *, event_type: str, option_direction: object, futures_direction: object
) -> str:
    if event_type.startswith("CALL_APPROACH") or event_type.startswith("CALL_TOUCH"):
        return "long"
    if event_type.startswith("PUT_APPROACH") or event_type.startswith("PUT_TOUCH"):
        return "short"
    if event_type == "CALL_BREAKOUT":
        return "long"
    if event_type == "PUT_BREAKOUT":
        return "short"
    option = _normalize_direction(option_direction)
    if option in {"long", "short"}:
        return option
    return _normalize_direction(futures_direction)


def _primary_event_type(flags: list[str]) -> str:
    priority = (
        "CALL_BREAKOUT",
        "PUT_BREAKOUT",
        "CALL_TOUCH",
        "PUT_TOUCH",
        "FUTURES_OPTION_DIVERGENCE",
        "CALL_APPROACH",
        "PUT_APPROACH",
        "WALL_RANGE_NARROWING",
        "WALL_RANGE_WIDENING",
        "CALL_WALL_MIGRATION",
        "PUT_WALL_MIGRATION",
        "LOCAL_CALL_BUILD",
        "LOCAL_PUT_BUILD",
        "LOCAL_CALL_UNWIND",
        "LOCAL_PUT_UNWIND",
    )
    for value in priority:
        if value in flags:
            return value
    return "NO_EVENT"


def _joint_node(futures_direction: str, option_direction: str) -> str:
    if futures_direction in {"long", "short"} and option_direction in {"long", "short"}:
        suffix = "CONFIRM" if futures_direction == option_direction else "DIVERGENCE"
        return f"FUTURES_{futures_direction.upper()}_OPTION_{option_direction.upper()}_{suffix}"
    if futures_direction in {"long", "short"}:
        return f"FUTURES_{futures_direction.upper()}_OPTION_NEUTRAL"
    if option_direction in {"long", "short"}:
        return f"FUTURES_NEUTRAL_OPTION_{option_direction.upper()}"
    return "BOTH_NEUTRAL"


def _range_state(value: object, threshold_bps: float) -> str:
    number = _number_or_none(value)
    if number is None:
        return "INITIAL_OR_INCOMPLETE"
    if number <= -threshold_bps:
        return "WALL_RANGE_NARROWING"
    if number >= threshold_bps:
        return "WALL_RANGE_WIDENING"
    return "WALL_RANGE_STABLE"


def _calendar_market_stage(year: int) -> str:
    if year <= 2021:
        return "EARLY_THIN"
    if year <= 2023:
        return "EXPANSION"
    return "MATURE_ACTIVE"


def _activity_state(
    *, year: int, volume_ratio: float | None, oi_ratio: float | None
) -> str:
    if year <= 2021:
        return "EARLY_BASELINE"
    if volume_ratio is None or oi_ratio is None:
        return "INSUFFICIENT_TRAILING_HISTORY"
    if volume_ratio >= 3.0 and oi_ratio >= 2.5:
        return "MATURE_ACTIVE"
    if volume_ratio >= 1.5 and oi_ratio >= 1.25:
        return "EXPANSION_ACTIVITY"
    return "LOW_ACTIVITY"


def _key_level_state(
    *,
    underlying: float,
    call_wall: float | None,
    put_wall: float | None,
    max_pain: float | None,
    near_ratio: float,
) -> str:
    if call_wall is None or put_wall is None:
        return "KEY_LEVEL_INCOMPLETE"
    if abs(call_wall / underlying - 1.0) <= near_ratio:
        return "NEAR_CALL_OI_WALL"
    if abs(put_wall / underlying - 1.0) <= near_ratio:
        return "NEAR_PUT_OI_WALL"
    if max_pain is not None and abs(max_pain / underlying - 1.0) <= near_ratio:
        return "NEAR_MAX_PAIN"
    if call_wall < put_wall:
        return "OVERLAPPING_OI_WALLS"
    if underlying >= call_wall:
        return "ABOVE_CALL_OI_WALL"
    if underlying <= put_wall:
        return "BELOW_PUT_OI_WALL"
    return "BETWEEN_OI_WALLS"


def _max_pain_strike(group: pd.DataFrame) -> float | None:
    strikes = sorted(set(pd.to_numeric(group["strike"], errors="coerce").dropna()))
    if not strikes:
        return None
    call_oi = pd.to_numeric(group["call_open_interest"], errors="coerce").fillna(0.0)
    put_oi = pd.to_numeric(group["put_open_interest"], errors="coerce").fillna(0.0)
    source = pd.to_numeric(group["strike"], errors="coerce")
    payouts: dict[float, float] = {}
    for candidate in strikes:
        payouts[float(candidate)] = float(
            (call_oi * (candidate - source).clip(lower=0)).sum()
            + (put_oi * (source - candidate).clip(lower=0)).sum()
        )
    return min(payouts, key=lambda value: (payouts[value], value))


def _normalize_direction(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "bullish", "偏多", "多"}:
        return "long"
    if text in {"short", "bearish", "偏空", "空"}:
        return "short"
    return "neutral"


def _return_direction(value: object, dead_zone_bps: int) -> str:
    number = _number_or_none(value)
    if number is None:
        return "neutral"
    dead_zone = dead_zone_bps / 10000.0
    return "long" if number > dead_zone else "short" if number < -dead_zone else "neutral"


def _directional_return(value: float | None, direction: str) -> float | None:
    if value is None:
        return None
    if direction == "long":
        return value
    if direction == "short":
        return -value
    return None


def _directional_outcome(value: float | None, dead_zone: float) -> str:
    if value is None:
        return "NO_DIRECTION"
    if value > dead_zone:
        return "FOLLOW_THROUGH"
    if value < -dead_zone:
        return "FAILED"
    return "UNRESOLVED"


def _sample_evidence(sample_count: int, min_sample_size: int) -> str:
    if sample_count >= max(100, min_sample_size * 3):
        return "READY"
    if sample_count >= min_sample_size:
        return "WATCH"
    return "WEAK_OR_SMALL_SAMPLE"


def _exact_binomial_two_sided(successes: int, sample_count: int) -> float:
    if sample_count <= 0:
        return math.nan
    successes = max(0, min(successes, sample_count))
    observed = math.comb(sample_count, successes) * (0.5**sample_count)
    probability = 0.0
    for value in range(sample_count + 1):
        candidate = math.comb(sample_count, value) * (0.5**sample_count)
        if candidate <= observed + 1e-15:
            probability += candidate
    return min(1.0, probability)


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    count = len(p_values)
    for rank_index in range(count - 1, -1, -1):
        index = order[rank_index]
        rank = rank_index + 1
        running = min(running, min(1.0, p_values[index] * count / rank))
        adjusted[index] = running
    return adjusted


def _optional_latest_path(directory: Path, pattern: str) -> Path | None:
    try:
        return latest_matching_path(directory, pattern, label=pattern)
    except ResearchWorkbenchError:
        return None


def _sum_numeric(values: pd.Series) -> float:
    return float(pd.to_numeric(values, errors="coerce").fillna(0.0).sum())


def _sum_numeric_min_count(values: pd.Series) -> float:
    result = pd.to_numeric(values, errors="coerce").sum(min_count=1)
    return math.nan if pd.isna(result) else float(result)


def _safe_ratio(numerator: object, denominator: object) -> float | None:
    left = _number_or_none(numerator)
    right = _number_or_none(denominator)
    return None if left is None or right is None or right == 0 else left / right


def _safe_series_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    left = pd.to_numeric(numerator, errors="coerce")
    right = pd.to_numeric(denominator, errors="coerce").replace(0, np.nan)
    return left / right


def _difference(left: object, right: object) -> float | None:
    left_number = _number_or_none(left)
    right_number = _number_or_none(right)
    if left_number is None or right_number is None:
        return None
    return left_number - right_number


def _number_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _float_or_nan(value: object) -> float:
    number = _number_or_none(value)
    return math.nan if number is None else number


def _mean_or_none(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.mean())


def _mean_or_nan(values: pd.Series) -> float:
    value = _mean_or_none(values)
    return math.nan if value is None else value


def _median_or_nan(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return math.nan if numeric.empty else float(numeric.median())


def _bool_mean(values: pd.Series) -> float:
    valid = values.dropna()
    return math.nan if valid.empty else float(valid.astype(bool).mean())
