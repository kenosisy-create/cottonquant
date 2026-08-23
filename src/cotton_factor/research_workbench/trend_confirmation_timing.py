"""R93L 趋势突破、全链持仓与期权确认时序研究。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir

PRODUCT_CODE = "CF"
RULE_VERSION = "V5.1_R93L_trend_confirmation_timing_v1"
DEFAULT_HORIZONS = (5, 20)
DEFAULT_PRE_WINDOW_SESSIONS = 10
DEFAULT_POST_WINDOW_SESSIONS = 20
DEFAULT_CONFIRMATION_DAYS = 2
DEFAULT_MIN_SAMPLE_SIZE = 15
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_MIN_ANNUAL_COVERAGE_YEARS = 3
DEFAULT_MIN_ANNUAL_GROUP_SIZE = 2
DEFAULT_MIN_ANNUAL_DIRECTION_CONSISTENCY = 0.75
DEFAULT_VOLUME_RANK_WINDOW = 252
DEFAULT_VOLUME_RANK_MIN_PERIODS = 60
DEFAULT_MIN_OPTION_LIQUIDITY_SCORE = 20.0
DEFAULT_DEAD_ZONE_BPS = 10
INFO = "INFO"
WARN = "WARN"
RESEARCH_BOUNDARY = (
    "每个趋势episode只保留首次突破；T-10至T日特征只使用当时可见数据，"
    "T+1以后轨迹和5D/20D结果仅作为历史后验研究。连续确认以完成确认的第二日为可知时点，"
    "本模块不修改signal matrix、composite_score或策略方向，不构成交易指令。"
)
HUMAN_REVIEW_REQUIRED = (
    "confirmation_days",
    "event_window_sessions",
    "option_direction_proxy_interpretation",
    "option_liquidity_threshold",
    "chain_oi_participation_interpretation",
    "waiting_cost_is_research_simulation",
    "annual_stability_thresholds",
)
WARNING_COLUMNS = (
    "run_id",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)
SYMMETRIC_DAILY_COLUMNS = {
    "trade_date",
    "main_contract",
    "adjusted_price",
}
EVENT_COLUMNS = {
    "event_id",
    "event_date",
    "direction",
    "direction_episode_id",
    "horizon",
    "directional_return",
    "label_available",
    "outcome",
    "historical_posterior_label",
}
CHAIN_COLUMNS = {
    "trade_date",
    "main_contract",
    "main_volume",
    "chain_volume",
    "chain_open_interest",
    "chain_oi_change_ratio",
    "participation_state",
    "roll_context",
}
OPTION_COLUMNS = {
    "trade_date",
    "main_contract",
    "underlying_contract",
    "option_direction",
    "option_direction_score",
    "factor_status",
    "option_liquidity_score",
    "volatility_repricing_state",
    "atm_iv_proxy",
    "atm_iv_proxy_change_1d",
    "atm_iv_rank",
    "pcr_oi",
    "pcr_oi_change_1d",
    "skew_proxy",
    "skew_proxy_change_1d",
}
TIMING_DIMENSIONS = (
    "option_timing_state",
    "participation_timing_state",
    "lead_lag_state",
)


@dataclass(frozen=True)
class TrendConfirmationTimingWarningRecord:
    """R93L警告与研究边界记录。"""

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


@dataclass(frozen=True)
class TrendConfirmationTimingResult:
    """R93L研究产物与摘要。"""

    run_id: str
    start: date
    end: date
    event_sample_start: date
    event_sample_end: date
    status: str
    event_count: int
    trajectory_row_count: int
    mature_5d_count: int
    mature_20d_count: int
    option_confirmed_by_breakout_count: int
    option_never_confirmed_count: int
    positive_candidate_count: int
    negative_filter_count: int
    latest_event_date: date
    latest_event_direction: str
    latest_option_timing_state: str
    event_index_path: Path
    trajectory_path: Path
    timing_event_path: Path
    state_summary_path: Path
    trajectory_summary_path: Path
    delay_event_path: Path
    delay_summary_path: Path
    annual_summary_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[TrendConfirmationTimingWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        return sum(item.severity == WARN for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "event_sample_start": self.event_sample_start.isoformat(),
            "event_sample_end": self.event_sample_end.isoformat(),
            "status": self.status,
            "event_count": self.event_count,
            "trajectory_row_count": self.trajectory_row_count,
            "mature_5d_count": self.mature_5d_count,
            "mature_20d_count": self.mature_20d_count,
            "option_confirmed_by_breakout_count": self.option_confirmed_by_breakout_count,
            "option_never_confirmed_count": self.option_never_confirmed_count,
            "positive_candidate_count": self.positive_candidate_count,
            "negative_filter_count": self.negative_filter_count,
            "latest_event_date": self.latest_event_date.isoformat(),
            "latest_event_direction": self.latest_event_direction,
            "latest_option_timing_state": self.latest_option_timing_state,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "event_index_path": str(self.event_index_path),
            "trajectory_path": str(self.trajectory_path),
            "timing_event_path": str(self.timing_event_path),
            "state_summary_path": str(self.state_summary_path),
            "trajectory_summary_path": str(self.trajectory_summary_path),
            "delay_event_path": str(self.delay_event_path),
            "delay_summary_path": str(self.delay_summary_path),
            "annual_summary_path": str(self.annual_summary_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "historical_returns_are_posterior_labels": True,
            "enters_composite_score": False,
            "realtime_rule_eligible": False,
            "trading_instruction": "not_a_trading_instruction",
            "research_boundary": RESEARCH_BOUNDARY,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_trend_confirmation_timing_research(
    *,
    symmetric_trend_daily_path: Path | None = None,
    breakout_event_path: Path | None = None,
    chain_oi_path: Path | None = None,
    option_structure_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    pre_window_sessions: int = DEFAULT_PRE_WINDOW_SESSIONS,
    post_window_sessions: int = DEFAULT_POST_WINDOW_SESSIONS,
    confirmation_days: int = DEFAULT_CONFIRMATION_DAYS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    min_annual_coverage_years: int = DEFAULT_MIN_ANNUAL_COVERAGE_YEARS,
    min_annual_group_size: int = DEFAULT_MIN_ANNUAL_GROUP_SIZE,
    min_annual_direction_consistency: float = DEFAULT_MIN_ANNUAL_DIRECTION_CONSISTENCY,
    volume_rank_window: int = DEFAULT_VOLUME_RANK_WINDOW,
    volume_rank_min_periods: int = DEFAULT_VOLUME_RANK_MIN_PERIODS,
    min_option_liquidity_score: float = DEFAULT_MIN_OPTION_LIQUIDITY_SCORE,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
) -> TrendConfirmationTimingResult:
    """构建趋势突破前后持仓与期权确认时序证据。"""
    normalized_horizons = _normalize_horizons(horizons)
    _validate_parameters(
        horizons=normalized_horizons,
        pre_window_sessions=pre_window_sessions,
        post_window_sessions=post_window_sessions,
        confirmation_days=confirmation_days,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        min_annual_coverage_years=min_annual_coverage_years,
        min_annual_group_size=min_annual_group_size,
        min_annual_direction_consistency=min_annual_direction_consistency,
        volume_rank_window=volume_rank_window,
        volume_rank_min_periods=volume_rank_min_periods,
        min_option_liquidity_score=min_option_liquidity_score,
        dead_zone_bps=dead_zone_bps,
    )
    daily_path = symmetric_trend_daily_path or _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "symmetric_trend",
        "*_symmetric_trend_daily.parquet",
        "R93A趋势日表",
    )
    event_path = breakout_event_path or _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "symmetric_trend",
        "*_symmetric_trend_breakout_event_horizon.parquet",
        "R93A突破事件表",
    )
    chain_path = chain_oi_path or _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "chain_oi_structure",
        "*_chain_oi_structure_daily.parquet",
        "R74全链持仓表",
    )
    option_path = option_structure_path or _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "option_structure",
        "*_option_structure_daily.parquet",
        "R75期权结构表",
    )
    daily = _load_frame(daily_path, SYMMETRIC_DAILY_COLUMNS, "R93A趋势日表")
    events = _load_frame(event_path, EVENT_COLUMNS, "R93A突破事件表")
    chain = _load_frame(chain_path, CHAIN_COLUMNS, "R74全链持仓表")
    option = _load_frame(option_path, OPTION_COLUMNS, "R75期权结构表")
    active_run_id = run_id or _default_run_id()

    event_index = _build_event_index(events, horizons=normalized_horizons, run_id=active_run_id)
    daily_base = _build_daily_base(
        daily=daily,
        chain=chain,
        option=option,
        volume_rank_window=volume_rank_window,
        volume_rank_min_periods=volume_rank_min_periods,
    )
    trajectory = _build_trajectory(
        event_index=event_index,
        daily=daily_base,
        pre_window_sessions=pre_window_sessions,
        post_window_sessions=post_window_sessions,
        min_option_liquidity_score=min_option_liquidity_score,
        run_id=active_run_id,
    )
    timing = _build_timing_events(
        event_index=event_index,
        trajectory=trajectory,
        confirmation_days=confirmation_days,
        run_id=active_run_id,
    )
    labels = _labels_long(event_index, horizons=normalized_horizons)
    annual_summary = _build_annual_summary(timing=timing, labels=labels)
    state_summary = _build_state_summary(
        timing=timing,
        labels=labels,
        annual_summary=annual_summary,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        min_annual_coverage_years=min_annual_coverage_years,
        min_annual_group_size=min_annual_group_size,
        min_annual_direction_consistency=min_annual_direction_consistency,
    )
    trajectory_summary = _build_trajectory_summary(trajectory=trajectory, labels=labels)
    delay_events = _build_delay_events(
        event_index=event_index,
        timing=timing,
        trajectory=trajectory,
        labels=labels,
        dead_zone_bps=dead_zone_bps,
        run_id=active_run_id,
    )
    delay_summary = _build_delay_summary(delay_events)
    warnings = tuple(
        _warning_records(
            run_id=active_run_id,
            event_index=event_index,
            trajectory=trajectory,
            timing=timing,
            state_summary=state_summary,
            min_sample_size=min_sample_size,
        )
    )
    paths = _output_paths(
        start=daily_base["trade_date"].min(),
        end=daily_base["trade_date"].max(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    latest = timing.sort_values(["event_date", "event_id"]).iloc[-1]
    result = TrendConfirmationTimingResult(
        run_id=active_run_id,
        start=daily_base["trade_date"].min(),
        end=daily_base["trade_date"].max(),
        event_sample_start=event_index["event_date"].min(),
        event_sample_end=event_index["event_date"].max(),
        status=(
            "TREND_CONFIRMATION_TIMING_READY_WITH_WARNINGS"
            if any(item.severity == WARN for item in warnings)
            else "TREND_CONFIRMATION_TIMING_READY"
        ),
        event_count=len(event_index),
        trajectory_row_count=len(trajectory),
        mature_5d_count=_mature_count(event_index, 5),
        mature_20d_count=_mature_count(event_index, 20),
        option_confirmed_by_breakout_count=int(
            timing["option_confirmation_session"].fillna(math.inf).le(0).sum()
        ),
        option_never_confirmed_count=int(
            timing["option_confirmation_session"].isna().sum()
        ),
        positive_candidate_count=int(
            state_summary["incremental_status"].eq("RESEARCH_CANDIDATE_POSITIVE").sum()
        ),
        negative_filter_count=int(
            state_summary["incremental_status"].eq("RESEARCH_FILTER_NEGATIVE").sum()
        ),
        latest_event_date=latest["event_date"],
        latest_event_direction=str(latest["direction"]),
        latest_option_timing_state=str(latest["option_timing_state"]),
        event_index_path=paths["event_index"],
        trajectory_path=paths["trajectory"],
        timing_event_path=paths["timing"],
        state_summary_path=paths["state_summary"],
        trajectory_summary_path=paths["trajectory_summary"],
        delay_event_path=paths["delay_events"],
        delay_summary_path=paths["delay_summary"],
        annual_summary_path=paths["annual_summary"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=warnings,
    )
    _write_outputs(
        result=result,
        event_index=event_index,
        trajectory=trajectory,
        timing=timing,
        state_summary=state_summary,
        trajectory_summary=trajectory_summary,
        delay_events=delay_events,
        delay_summary=delay_summary,
        annual_summary=annual_summary,
        input_paths=(daily_path, event_path, chain_path, option_path),
        parameters={
            "horizons": list(normalized_horizons),
            "pre_window_sessions": pre_window_sessions,
            "post_window_sessions": post_window_sessions,
            "confirmation_days": confirmation_days,
            "min_sample_size": min_sample_size,
            "fdr_level": fdr_level,
            "min_annual_coverage_years": min_annual_coverage_years,
            "min_annual_group_size": min_annual_group_size,
            "min_annual_direction_consistency": min_annual_direction_consistency,
            "volume_rank_window": volume_rank_window,
            "volume_rank_min_periods": volume_rank_min_periods,
            "min_option_liquidity_score": min_option_liquidity_score,
            "dead_zone_bps": dead_zone_bps,
        },
    )
    return result


def _build_event_index(
    events: pd.DataFrame,
    *,
    horizons: tuple[int, ...],
    run_id: str,
) -> pd.DataFrame:
    working = events.loc[events["horizon"].isin(horizons)].copy()
    if working.empty:
        raise ResearchWorkbenchError("R93L没有指定周期的突破事件")
    if not _bool_series(working["historical_posterior_label"]).all():
        raise ResearchWorkbenchError("R93L要求突破事件显式标记为历史后验标签")
    working = working.sort_values(["event_date", "event_id", "horizon"])
    # 同一episode可能多次突破；每个周期只保留首次突破，避免重复计算趋势机会。
    first = working.drop_duplicates(["direction_episode_id", "horizon"], keep="first")
    rows: list[dict[str, object]] = []
    for episode_id, group in first.groupby("direction_episode_id", sort=True):
        if group["event_date"].nunique() != 1 or group["direction"].nunique() != 1:
            raise ResearchWorkbenchError(f"R93L同一episode的首次突破锚点不一致: {episode_id}")
        anchor = group.iloc[0]
        row: dict[str, object] = {
            "run_id": run_id,
            "event_id": str(anchor["event_id"]),
            "event_date": anchor["event_date"],
            "event_year": anchor["event_date"].year,
            "direction": str(anchor["direction"]),
            "direction_episode_id": str(episode_id),
            "main_contract": str(anchor.get("main_contract") or ""),
            "historical_posterior_label": True,
            "rule_version": RULE_VERSION,
            "trading_instruction": "not_a_trading_instruction",
        }
        for horizon in horizons:
            selected = group.loc[group["horizon"].eq(horizon)]
            if selected.empty:
                row[f"label_available_{horizon}d"] = False
                row[f"outcome_{horizon}d"] = "LABEL_UNAVAILABLE"
                row[f"directional_return_{horizon}d"] = math.nan
                row[f"exit_date_{horizon}d"] = None
                continue
            item = selected.iloc[0]
            available = bool(item["label_available"])
            row[f"label_available_{horizon}d"] = available
            row[f"outcome_{horizon}d"] = (
                str(item["outcome"]) if available else "LABEL_UNAVAILABLE"
            )
            row[f"directional_return_{horizon}d"] = (
                float(item["directional_return"]) if available else math.nan
            )
            row[f"exit_date_{horizon}d"] = item.get("exit_date") if available else None
        rows.append(row)
    output = pd.DataFrame(rows).sort_values(["event_date", "event_id"]).reset_index(drop=True)
    if output["direction_episode_id"].duplicated().any():
        raise ResearchWorkbenchError("R93L事件索引存在重复episode")
    return output


def _build_daily_base(
    *,
    daily: pd.DataFrame,
    chain: pd.DataFrame,
    option: pd.DataFrame,
    volume_rank_window: int,
    volume_rank_min_periods: int,
) -> pd.DataFrame:
    for label, frame in (("R93A", daily), ("R74", chain), ("R75", option)):
        if frame["trade_date"].duplicated().any():
            raise ResearchWorkbenchError(f"{label}日表存在重复交易日")
    # 严格裁剪来源字段，避免R93A内嵌的旧上下文字段覆盖R74/R75权威研究表。
    daily_working = daily[sorted(SYMMETRIC_DAILY_COLUMNS)].copy()
    chain_working = chain[sorted(CHAIN_COLUMNS)].rename(
        columns={"main_contract": "chain_main_contract"}
    )
    option_working = option[sorted(OPTION_COLUMNS)].rename(
        columns={"main_contract": "option_main_contract"}
    )
    working = daily_working.merge(
        chain_working, on="trade_date", how="left", validate="one_to_one"
    )
    working = working.merge(option_working, on="trade_date", how="left", validate="one_to_one")
    chain_mismatch = working["chain_main_contract"].notna() & working[
        "main_contract"
    ].ne(working["chain_main_contract"])
    option_mismatch = working["option_main_contract"].notna() & working[
        "main_contract"
    ].ne(working["option_main_contract"])
    if chain_mismatch.any():
        raise ResearchWorkbenchError("R93L检测到R93A与R74主力合约映射不一致")
    if option_mismatch.any():
        raise ResearchWorkbenchError("R93L检测到R93A与R75主力合约映射不一致")
    working = working.sort_values("trade_date").reset_index(drop=True)
    working["adjusted_price"] = pd.to_numeric(working["adjusted_price"], errors="coerce")
    if working["adjusted_price"].isna().any():
        raise ResearchWorkbenchError("R93L调整连续价格存在空值")
    working["adjusted_price_return_1d"] = working["adjusted_price"].pct_change()
    working["chain_volume_rank"] = _rolling_percentile_rank(
        pd.to_numeric(working["chain_volume"], errors="coerce"),
        window=volume_rank_window,
        min_periods=volume_rank_min_periods,
    )
    return working


def _build_trajectory(
    *,
    event_index: pd.DataFrame,
    daily: pd.DataFrame,
    pre_window_sessions: int,
    post_window_sessions: int,
    min_option_liquidity_score: float,
    run_id: str,
) -> pd.DataFrame:
    positions = {value: index for index, value in enumerate(daily["trade_date"])}
    rows: list[dict[str, object]] = []
    for event in event_index.itertuples(index=False):
        if event.event_date not in positions:
            raise ResearchWorkbenchError(f"R93L事件日不在日度状态表: {event.event_date}")
        event_position = positions[event.event_date]
        left = max(0, event_position - pre_window_sessions)
        right = min(len(daily), event_position + post_window_sessions + 1)
        event_price = float(daily.iloc[event_position]["adjusted_price"])
        direction_sign = 1 if event.direction == "long" else -1
        for position in range(left, right):
            item = daily.iloc[position]
            relative_session = position - event_position
            participation_alignment = _participation_alignment(
                direction=event.direction,
                state=item.get("participation_state"),
            )
            option_alignment = _option_alignment(
                direction=event.direction,
                option_direction=item.get("option_direction"),
                factor_status=item.get("factor_status"),
                liquidity_score=item.get("option_liquidity_score"),
                min_liquidity_score=min_option_liquidity_score,
            )
            option_score = _float_or_nan(item.get("option_direction_score"))
            rows.append(
                {
                    "run_id": run_id,
                    "event_id": event.event_id,
                    "event_date": event.event_date,
                    "event_year": event.event_year,
                    "direction": event.direction,
                    "direction_episode_id": event.direction_episode_id,
                    "relative_session": relative_session,
                    "state_date": item["trade_date"],
                    "main_contract": str(item.get("main_contract") or ""),
                    "option_underlying_contract": str(
                        item.get("underlying_contract") or ""
                    ),
                    "adjusted_price": float(item["adjusted_price"]),
                    "event_adjusted_price": event_price,
                    "directional_price_vs_event": direction_sign
                    * (float(item["adjusted_price"]) / event_price - 1.0),
                    "directional_price_return_1d": direction_sign
                    * _float_or_nan(item.get("adjusted_price_return_1d")),
                    "main_volume": _float_or_nan(item.get("main_volume")),
                    "chain_volume": _float_or_nan(item.get("chain_volume")),
                    "chain_volume_rank": _float_or_nan(item.get("chain_volume_rank")),
                    "chain_open_interest": _float_or_nan(
                        item.get("chain_open_interest")
                    ),
                    "chain_oi_change_ratio": _float_or_nan(
                        item.get("chain_oi_change_ratio")
                    ),
                    "participation_state": str(item.get("participation_state") or "MISSING"),
                    "participation_alignment": participation_alignment,
                    "futures_confirmation_flag": participation_alignment == "CONFIRM",
                    "roll_context": str(item.get("roll_context") or "MISSING"),
                    "option_direction": str(item.get("option_direction") or "missing"),
                    "option_directional_score": direction_sign * option_score,
                    "option_alignment": option_alignment,
                    "option_confirmation_flag": option_alignment == "CONFIRM",
                    "option_divergence_flag": option_alignment == "DIVERGE",
                    "option_factor_status": str(item.get("factor_status") or "MISSING"),
                    "option_liquidity_score": _float_or_nan(
                        item.get("option_liquidity_score")
                    ),
                    "volatility_repricing_state": str(
                        item.get("volatility_repricing_state") or "MISSING"
                    ),
                    "volatility_repricing_flag": str(
                        item.get("volatility_repricing_state") or ""
                    )
                    in {"VOLATILITY_EXPANDING", "HIGH_VOL_RISK_REPRICING"},
                    "atm_iv_proxy": _float_or_nan(item.get("atm_iv_proxy")),
                    "atm_iv_proxy_change_1d": _float_or_nan(
                        item.get("atm_iv_proxy_change_1d")
                    ),
                    "atm_iv_rank": _float_or_nan(item.get("atm_iv_rank")),
                    "pcr_oi": _float_or_nan(item.get("pcr_oi")),
                    "pcr_oi_change_1d": _float_or_nan(item.get("pcr_oi_change_1d")),
                    "skew_proxy": _float_or_nan(item.get("skew_proxy")),
                    "skew_proxy_change_1d": _float_or_nan(
                        item.get("skew_proxy_change_1d")
                    ),
                    "window_left_complete": event_position >= pre_window_sessions,
                    "window_right_complete": (
                        event_position + post_window_sessions < len(daily)
                    ),
                    "pre_or_event_feature": relative_session <= 0,
                    "post_event_posterior_path": relative_session > 0,
                    "contains_forward_outcome_label": False,
                    "rule_version": RULE_VERSION,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    output = pd.DataFrame(rows).sort_values(
        ["event_date", "event_id", "relative_session"]
    ).reset_index(drop=True)
    if output.duplicated(["event_id", "relative_session"]).any():
        raise ResearchWorkbenchError("R93L事件轨迹存在重复相对交易日")
    return output


def _build_timing_events(
    *,
    event_index: pd.DataFrame,
    trajectory: pd.DataFrame,
    confirmation_days: int,
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event in event_index.itertuples(index=False):
        group = trajectory.loc[trajectory["event_id"].eq(event.event_id)].sort_values(
            "relative_session"
        )
        event_row = group.loc[group["relative_session"].eq(0)]
        if len(event_row) != 1:
            raise ResearchWorkbenchError(f"R93L事件轨迹缺少唯一T日: {event.event_id}")
        event_state = event_row.iloc[0]
        participation = _first_sustained_confirmation(
            group, flag_column="futures_confirmation_flag", confirmation_days=confirmation_days
        )
        option = _first_sustained_confirmation(
            group, flag_column="option_confirmation_flag", confirmation_days=confirmation_days
        )
        divergence = _first_sustained_confirmation(
            group, flag_column="option_divergence_flag", confirmation_days=confirmation_days
        )
        volatility = _first_sustained_confirmation(
            group, flag_column="volatility_repricing_flag", confirmation_days=confirmation_days
        )
        option_session = option["relative_session"]
        participation_session = participation["relative_session"]
        rows.append(
            {
                "run_id": run_id,
                "event_id": event.event_id,
                "event_date": event.event_date,
                "event_year": event.event_year,
                "direction": event.direction,
                "direction_episode_id": event.direction_episode_id,
                "participation_confirmation_session": participation_session,
                "participation_confirmation_date": participation["state_date"],
                "participation_confirmation_left_censored": participation["left_censored"],
                "participation_timing_state": _timing_state(participation_session),
                "option_confirmation_session": option_session,
                "option_confirmation_date": option["state_date"],
                "option_confirmation_left_censored": option["left_censored"],
                "option_timing_state": _timing_state(option_session),
                "option_divergence_session": divergence["relative_session"],
                "option_divergence_date": divergence["state_date"],
                "volatility_repricing_session": volatility["relative_session"],
                "volatility_repricing_date": volatility["state_date"],
                "lead_lag_state": _lead_lag_state(
                    option_session=option_session,
                    participation_session=participation_session,
                ),
                "option_minus_participation_sessions": _difference_or_nan(
                    option_session, participation_session
                ),
                "event_chain_volume_rank": event_state["chain_volume_rank"],
                "event_chain_oi_change_ratio": event_state["chain_oi_change_ratio"],
                "event_participation_alignment": event_state["participation_alignment"],
                "event_option_alignment": event_state["option_alignment"],
                "event_option_directional_score": event_state[
                    "option_directional_score"
                ],
                "event_atm_iv_rank": event_state["atm_iv_rank"],
                "event_volatility_repricing_state": event_state[
                    "volatility_repricing_state"
                ],
                "timing_path_is_posterior_research": True,
                "enters_latest_signal": False,
                "rule_version": RULE_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    output = pd.DataFrame(rows).sort_values(["event_date", "event_id"]).reset_index(drop=True)
    if output["direction_episode_id"].duplicated().any():
        raise ResearchWorkbenchError("R93L确认时序表存在重复episode")
    return output


def _labels_long(event_index: pd.DataFrame, *, horizons: tuple[int, ...]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event in event_index.itertuples(index=False):
        for horizon in horizons:
            available = bool(getattr(event, f"label_available_{horizon}d"))
            if not available:
                continue
            rows.append(
                {
                    "event_id": event.event_id,
                    "event_date": event.event_date,
                    "event_year": event.event_year,
                    "direction": event.direction,
                    "direction_episode_id": event.direction_episode_id,
                    "horizon": horizon,
                    "outcome": getattr(event, f"outcome_{horizon}d"),
                    "directional_return": getattr(
                        event, f"directional_return_{horizon}d"
                    ),
                    "historical_posterior_label": True,
                }
            )
    if not rows:
        raise ResearchWorkbenchError("R93L没有成熟的5D/20D历史后验标签")
    output = pd.DataFrame(rows)
    if output.duplicated(["event_id", "horizon"]).any():
        raise ResearchWorkbenchError("R93L历史标签存在重复事件周期")
    return output


def _build_state_summary(
    *,
    timing: pd.DataFrame,
    labels: pd.DataFrame,
    annual_summary: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
    min_annual_coverage_years: int,
    min_annual_group_size: int,
    min_annual_direction_consistency: float,
) -> pd.DataFrame:
    merged = labels.merge(
        timing,
        on=[
            "event_id",
            "event_date",
            "event_year",
            "direction",
            "direction_episode_id",
        ],
        how="inner",
        validate="many_to_one",
    )
    rows: list[dict[str, object]] = []
    for dimension in TIMING_DIMENSIONS:
        for (horizon, state), group in merged.groupby(
            ["horizon", dimension], dropna=False, sort=True
        ):
            universe = merged.loc[merged["horizon"].eq(horizon)]
            comparison = universe.loc[universe[dimension].ne(state)]
            metrics = _group_metrics(group)
            control = _group_metrics(comparison)
            annual = _annual_stability_metrics(
                annual_summary=annual_summary,
                timing_dimension=dimension,
                timing_state=str(state),
                horizon=int(horizon),
                min_annual_group_size=min_annual_group_size,
            )
            p_value = _fisher_exact_two_sided(
                group_successes=int(metrics["success_count"]),
                group_count=int(metrics["sample_count"]),
                comparison_successes=int(control["success_count"]),
                comparison_count=int(control["sample_count"]),
            )
            rows.append(
                {
                    "timing_dimension": dimension,
                    "timing_state": str(state),
                    "horizon": int(horizon),
                    **metrics,
                    "comparison_sample_count": control["sample_count"],
                    "comparison_success_count": control["success_count"],
                    "comparison_hit_rate": control["hit_rate"],
                    "comparison_mean_directional_return": control[
                        "mean_directional_return"
                    ],
                    "delta_hit_rate": metrics["hit_rate"] - control["hit_rate"],
                    "delta_mean_directional_return": (
                        metrics["mean_directional_return"]
                        - control["mean_directional_return"]
                    ),
                    "fisher_exact_p_value": p_value,
                    "fdr_q_value": math.nan,
                    **annual,
                    "incremental_status": "PENDING_FDR",
                    "posterior_hypothesis_candidate": False,
                    "promotion_eligible": False,
                    "rule_version": RULE_VERSION,
                }
            )
    summary = pd.DataFrame(rows)
    tested = summary["comparison_sample_count"].gt(0)
    for _, family in summary.loc[tested].groupby(
        ["timing_dimension", "horizon"], sort=True
    ):
        summary.loc[family.index, "fdr_q_value"] = _benjamini_hochberg(
            family["fisher_exact_p_value"].astype(float).tolist()
        )
    for index, row in summary.iterrows():
        eligible_years = int(row["annual_eligible_year_count"])
        effect = _effect_direction(
            delta_hit_rate=row["delta_hit_rate"],
            delta_mean_directional_return=row["delta_mean_directional_return"],
        )
        if effect == "POSITIVE":
            aligned_years = int(row["annual_positive_year_count"])
        elif effect == "NEGATIVE":
            aligned_years = int(row["annual_negative_year_count"])
        else:
            aligned_years = 0
        summary.at[index, "annual_aligned_year_count"] = aligned_years
        summary.at[index, "annual_direction_consistency"] = (
            aligned_years / eligible_years if eligible_years else math.nan
        )
        row = summary.loc[index]
        summary.at[index, "incremental_status"] = _incremental_status(
            row,
            min_sample_size=min_sample_size,
            fdr_level=fdr_level,
            min_annual_coverage_years=min_annual_coverage_years,
            min_annual_direction_consistency=min_annual_direction_consistency,
        )
        summary.at[index, "posterior_hypothesis_candidate"] = summary.at[
            index, "incremental_status"
        ] in {
            "RESEARCH_CANDIDATE_POSITIVE",
            "RESEARCH_FILTER_NEGATIVE",
        }
        # 时序状态使用T+1至T+20路径，不能直接晋级为突破日实时规则。
        summary.at[index, "promotion_eligible"] = False
    return summary.sort_values(
        ["horizon", "timing_dimension", "fdr_q_value", "sample_count"],
        ascending=[True, True, True, False],
        na_position="last",
    ).reset_index(drop=True)


def _build_trajectory_summary(
    *,
    trajectory: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    merged = trajectory.merge(
        labels[["event_id", "horizon", "outcome", "directional_return"]],
        on="event_id",
        how="inner",
        validate="many_to_many",
    )
    rows: list[dict[str, object]] = []
    for (horizon, outcome, relative_session), group in merged.groupby(
        ["horizon", "outcome", "relative_session"], sort=True
    ):
        rows.append(
            {
                "horizon": int(horizon),
                "outcome": str(outcome),
                "relative_session": int(relative_session),
                "event_count": int(group["event_id"].nunique()),
                "mean_directional_price_vs_event": _mean(
                    group["directional_price_vs_event"]
                ),
                "median_directional_price_vs_event": _median(
                    group["directional_price_vs_event"]
                ),
                "mean_chain_volume_rank": _mean(group["chain_volume_rank"]),
                "mean_chain_oi_change_ratio": _mean(
                    group["chain_oi_change_ratio"]
                ),
                "participation_confirmation_rate": _bool_mean(
                    group["futures_confirmation_flag"]
                ),
                "option_confirmation_rate": _bool_mean(
                    group["option_confirmation_flag"]
                ),
                "option_divergence_rate": _bool_mean(group["option_divergence_flag"]),
                "volatility_repricing_rate": _bool_mean(
                    group["volatility_repricing_flag"]
                ),
                "mean_option_directional_score": _mean(
                    group["option_directional_score"]
                ),
                "mean_atm_iv_rank": _mean(group["atm_iv_rank"]),
                "trajectory_rows_are_descriptive_not_independent": True,
                "rule_version": RULE_VERSION,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["horizon", "outcome", "relative_session"]
    ).reset_index(drop=True)


def _build_delay_events(
    *,
    event_index: pd.DataFrame,
    timing: pd.DataFrame,
    trajectory: pd.DataFrame,
    labels: pd.DataFrame,
    dead_zone_bps: int,
    run_id: str,
) -> pd.DataFrame:
    merged = labels.merge(
        timing,
        on=[
            "event_id",
            "event_date",
            "event_year",
            "direction",
            "direction_episode_id",
        ],
        how="inner",
        validate="many_to_one",
    )
    trajectory_groups = {
        event_id: group.set_index("relative_session")
        for event_id, group in trajectory.groupby("event_id", sort=False)
    }
    rows: list[dict[str, object]] = []
    dead_zone = dead_zone_bps / 10_000.0
    for item in merged.itertuples(index=False):
        path = trajectory_groups[item.event_id]
        if 0 not in path.index or item.horizon not in path.index:
            continue
        event_state = path.loc[0]
        exit_state = path.loc[item.horizon]
        direction_sign = 1 if item.direction == "long" else -1
        option_session = (
            None
            if pd.isna(item.option_confirmation_session)
            else int(item.option_confirmation_session)
        )
        if option_session is not None and option_session <= 0:
            wait_status = "CONFIRMED_BY_BREAKOUT"
            entry_session: int | None = 0
        elif option_session is not None and option_session <= item.horizon:
            wait_status = "CONFIRMED_AFTER_BREAKOUT"
            entry_session = option_session
        else:
            wait_status = "NO_CONFIRMATION_WITHIN_HORIZON"
            entry_session = None
        if entry_session is None or entry_session not in path.index:
            entry_price = math.nan
            strict_wait_return = 0.0
            move_before_confirmation = math.nan
            confirmation_delay = math.nan
        else:
            entry_state = path.loc[entry_session]
            entry_price = float(entry_state["adjusted_price"])
            strict_wait_return = direction_sign * (
                float(exit_state["adjusted_price"]) / entry_price - 1.0
            )
            move_before_confirmation = direction_sign * (
                entry_price / float(event_state["adjusted_price"]) - 1.0
            )
            confirmation_delay = max(0, entry_session)
        total_return = float(item.directional_return)
        capture_ratio = (
            strict_wait_return / total_return
            if total_return > dead_zone
            else math.nan
        )
        rows.append(
            {
                "run_id": run_id,
                "event_id": item.event_id,
                "event_date": item.event_date,
                "event_year": item.event_year,
                "direction": item.direction,
                "direction_episode_id": item.direction_episode_id,
                "horizon": int(item.horizon),
                "outcome": item.outcome,
                "directional_return": total_return,
                "option_timing_state": item.option_timing_state,
                "option_confirmation_session": option_session,
                "wait_status": wait_status,
                "effective_entry_session": entry_session,
                "confirmation_delay_sessions": confirmation_delay,
                "event_adjusted_price": float(event_state["adjusted_price"]),
                "effective_entry_adjusted_price": entry_price,
                "exit_adjusted_price": float(exit_state["adjusted_price"]),
                "move_before_confirmation": move_before_confirmation,
                "strict_wait_directional_return": strict_wait_return,
                "arithmetic_return_difference": total_return - strict_wait_return,
                "follow_through_capture_ratio": capture_ratio,
                "missed_follow_through": (
                    item.outcome == "FOLLOW_THROUGH"
                    and wait_status == "NO_CONFIRMATION_WITHIN_HORIZON"
                ),
                "historical_posterior_label": True,
                "strict_wait_is_counterfactual_research": True,
                "rule_version": RULE_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    if not rows:
        raise ResearchWorkbenchError("R93L无法构建等待期权确认的延迟成本")
    output = pd.DataFrame(rows).sort_values(
        ["event_date", "event_id", "horizon"]
    ).reset_index(drop=True)
    if output.duplicated(["event_id", "horizon"]).any():
        raise ResearchWorkbenchError("R93L延迟成本存在重复事件周期")
    return output


def _build_delay_summary(delay_events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for horizon, horizon_group in delay_events.groupby("horizon", sort=True):
        groups = [("ALL", horizon_group)] + list(
            horizon_group.groupby("wait_status", sort=True)
        )
        for wait_status, group in groups:
            rows.append(
                {
                    "horizon": int(horizon),
                    "wait_status": str(wait_status),
                    "event_count": len(group),
                    "follow_through_count": int(
                        group["outcome"].eq("FOLLOW_THROUGH").sum()
                    ),
                    "hit_rate": float(group["outcome"].eq("FOLLOW_THROUGH").mean()),
                    "mean_directional_return": _mean(group["directional_return"]),
                    "mean_strict_wait_return": _mean(
                        group["strict_wait_directional_return"]
                    ),
                    "mean_arithmetic_return_difference": _mean(
                        group["arithmetic_return_difference"]
                    ),
                    "mean_confirmation_delay_sessions": _mean(
                        group["confirmation_delay_sessions"]
                    ),
                    "mean_move_before_confirmation": _mean(
                        group["move_before_confirmation"]
                    ),
                    "median_follow_through_capture_ratio": _median(
                        group["follow_through_capture_ratio"]
                    ),
                    "missed_follow_through_count": int(
                        group["missed_follow_through"].sum()
                    ),
                    "strict_wait_is_counterfactual_research": True,
                    "rule_version": RULE_VERSION,
                }
            )
    return pd.DataFrame(rows).sort_values(["horizon", "wait_status"]).reset_index(
        drop=True
    )


def _build_annual_summary(
    *,
    timing: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    merged = labels.merge(
        timing,
        on=[
            "event_id",
            "event_date",
            "event_year",
            "direction",
            "direction_episode_id",
        ],
        how="inner",
        validate="many_to_one",
    )
    rows: list[dict[str, object]] = []
    for dimension in TIMING_DIMENSIONS:
        for (year, horizon, state), group in merged.groupby(
            ["event_year", "horizon", dimension], sort=True
        ):
            universe = merged.loc[
                merged["event_year"].eq(year) & merged["horizon"].eq(horizon)
            ]
            comparison = universe.loc[universe[dimension].ne(state)]
            metrics = _group_metrics(group)
            control = _group_metrics(comparison)
            delta_hit_rate = metrics["hit_rate"] - control["hit_rate"]
            delta_mean_return = (
                metrics["mean_directional_return"]
                - control["mean_directional_return"]
            )
            rows.append(
                {
                    "event_year": int(year),
                    "horizon": int(horizon),
                    "timing_dimension": dimension,
                    "timing_state": str(state),
                    **metrics,
                    "comparison_sample_count": control["sample_count"],
                    "comparison_success_count": control["success_count"],
                    "comparison_hit_rate": control["hit_rate"],
                    "comparison_mean_directional_return": control[
                        "mean_directional_return"
                    ],
                    "delta_hit_rate": delta_hit_rate,
                    "delta_mean_directional_return": delta_mean_return,
                    "annual_effect_direction": _effect_direction(
                        delta_hit_rate=delta_hit_rate,
                        delta_mean_directional_return=delta_mean_return,
                    ),
                    "historical_posterior_label": True,
                    "rule_version": RULE_VERSION,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["event_year", "horizon", "timing_dimension", "timing_state"]
    ).reset_index(drop=True)


def _annual_stability_metrics(
    *,
    annual_summary: pd.DataFrame,
    timing_dimension: str,
    timing_state: str,
    horizon: int,
    min_annual_group_size: int,
) -> dict[str, float | int]:
    selected = annual_summary.loc[
        annual_summary["timing_dimension"].eq(timing_dimension)
        & annual_summary["timing_state"].eq(timing_state)
        & annual_summary["horizon"].eq(horizon)
    ].copy()
    eligible = selected.loc[
        selected["sample_count"].ge(min_annual_group_size)
        & selected["comparison_sample_count"].ge(min_annual_group_size)
    ]
    positive_years = int(eligible["annual_effect_direction"].eq("POSITIVE").sum())
    negative_years = int(eligible["annual_effect_direction"].eq("NEGATIVE").sum())
    mixed_years = int(eligible["annual_effect_direction"].eq("MIXED").sum())
    coverage = len(eligible)
    dominant = max(positive_years, negative_years)
    return {
        "annual_year_count": int(selected["event_year"].nunique()),
        "annual_eligible_year_count": int(coverage),
        "annual_positive_year_count": positive_years,
        "annual_negative_year_count": negative_years,
        "annual_mixed_year_count": mixed_years,
        "annual_aligned_year_count": 0,
        "annual_direction_consistency": math.nan,
        "annual_dominant_direction_consistency": (
            dominant / coverage if coverage else math.nan
        ),
    }


def _effect_direction(
    *,
    delta_hit_rate: object,
    delta_mean_directional_return: object,
) -> str:
    hit = _float_or_nan(delta_hit_rate)
    return_delta = _float_or_nan(delta_mean_directional_return)
    if not math.isfinite(hit) or not math.isfinite(return_delta):
        return "UNAVAILABLE"
    if hit > 0 and return_delta > 0:
        return "POSITIVE"
    if hit < 0 and return_delta < 0:
        return "NEGATIVE"
    return "MIXED"


def _warning_records(
    *,
    run_id: str,
    event_index: pd.DataFrame,
    trajectory: pd.DataFrame,
    timing: pd.DataFrame,
    state_summary: pd.DataFrame,
    min_sample_size: int,
) -> list[TrendConfirmationTimingWarningRecord]:
    records: list[TrendConfirmationTimingWarningRecord] = []
    unavailable = 0
    for column in event_index.columns:
        if column.startswith("label_available_"):
            unavailable += int((~_bool_series(event_index[column])).sum())
    if unavailable:
        records.append(
            TrendConfirmationTimingWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93L_POSTERIOR_LABELS_PENDING",
                warning_message="部分最新突破尚未形成完整5D/20D后验标签。",
                affected_count=unavailable,
                human_review_required=("event_label_maturity",),
            )
        )
    incomplete = int(
        trajectory.groupby("event_id")["window_right_complete"].first().eq(False).sum()  # noqa: E712
    )
    if incomplete:
        records.append(
            TrendConfirmationTimingWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93L_RIGHT_WINDOW_INCOMPLETE",
                warning_message="部分最新事件的T+20轨迹尚未走完，不进入未成熟周期统计。",
                affected_count=incomplete,
            )
        )
    left_censored = int(
        timing[[
            "option_confirmation_left_censored",
            "participation_confirmation_left_censored",
        ]]
        .any(axis=1)
        .sum()
    )
    if left_censored:
        records.append(
            TrendConfirmationTimingWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93L_PREWINDOW_CONFIRMATION_LEFT_CENSORED",
                warning_message="部分确认在T-10窗口起点已存在，只能判断为至少提前10日附近。",
                affected_count=left_censored,
                human_review_required=("event_window_sessions",),
            )
        )
    missing_option = int(timing["event_option_alignment"].eq("OPTION_NOT_READY").sum())
    if missing_option:
        records.append(
            TrendConfirmationTimingWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93L_OPTION_NOT_READY_AT_BREAKOUT",
                warning_message="部分突破日的期权流动性或质量不足，不能判断期权确认。",
                affected_count=missing_option,
                human_review_required=("option_liquidity_threshold",),
            )
        )
    small = int(state_summary["sample_count"].lt(min_sample_size).sum())
    if small:
        records.append(
            TrendConfirmationTimingWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93L_SMALL_TIMING_GROUPS_PRESENT",
                warning_message="部分确认时序分组未达到独立episode样本门槛。",
                affected_count=small,
                human_review_required=("timing_group_sample_size",),
            )
        )
    annual_blocked = int(
        state_summary["incremental_status"].astype(str).str.contains("ANNUAL_").sum()
    )
    if annual_blocked:
        records.append(
            TrendConfirmationTimingWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93L_FDR_RESULT_FAILED_ANNUAL_STABILITY_GATE",
                warning_message=(
                    "部分FDR显著结果未达到年度覆盖或方向一致性门槛，"
                    "已降级为观察项。"
                ),
                affected_count=annual_blocked,
                human_review_required=("annual_stability_thresholds",),
            )
        )
    records.append(
        TrendConfirmationTimingWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93L_POSTERIOR_PATH_BOUNDARY",
            warning_message=(
                "事件轨迹T+1以后、结果标签和等待确认收益均为历史后验研究，"
                "不进入最新信号或策略。"
            ),
            affected_count=len(event_index),
        )
    )
    return records


def _write_outputs(
    *,
    result: TrendConfirmationTimingResult,
    event_index: pd.DataFrame,
    trajectory: pd.DataFrame,
    timing: pd.DataFrame,
    state_summary: pd.DataFrame,
    trajectory_summary: pd.DataFrame,
    delay_events: pd.DataFrame,
    delay_summary: pd.DataFrame,
    annual_summary: pd.DataFrame,
    input_paths: tuple[Path, ...],
    parameters: dict[str, object],
) -> None:
    frames = (
        (result.event_index_path, event_index),
        (result.trajectory_path, trajectory),
        (result.timing_event_path, timing),
        (result.state_summary_path, state_summary),
        (result.trajectory_summary_path, trajectory_summary),
        (result.delay_event_path, delay_events),
        (result.delay_summary_path, delay_summary),
        (result.annual_summary_path, annual_summary),
    )
    for path, frame in frames:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    _write_warnings(result)
    payload = {
        "report_type": "trend_confirmation_timing",
        "rule_version": RULE_VERSION,
        "summary": result.to_summary(),
        "parameters": parameters,
        "historical_returns_are_posterior_labels": True,
        "enters_composite_score": False,
        "realtime_rule_eligible": False,
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    _write_markdown(
        result=result,
        timing=timing,
        state_summary=state_summary,
        trajectory_summary=trajectory_summary,
        delay_summary=delay_summary,
    )
    artifacts = tuple(path for path, _ in frames) + (
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        "report_type": "trend_confirmation_timing",
        "rule_version": RULE_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "summary": result.to_summary(),
        "parameters": parameters,
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "historical_returns_are_posterior_labels": True,
        "enters_composite_score": False,
        "realtime_rule_eligible": False,
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warnings(result: TrendConfirmationTimingResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for item in result.warning_records:
            writer.writerow(
                {
                    "run_id": item.run_id,
                    "severity": item.severity,
                    "warning_code": item.warning_code,
                    "warning_message": item.warning_message,
                    "affected_count": item.affected_count,
                    "human_review_required": ";".join(item.human_review_required),
                }
            )


def _write_markdown(
    *,
    result: TrendConfirmationTimingResult,
    timing: pd.DataFrame,
    state_summary: pd.DataFrame,
    trajectory_summary: pd.DataFrame,
    delay_summary: pd.DataFrame,
) -> None:
    lines = [
        "# CF R93L 趋势突破与期货-期权确认时序研究",
        "",
        "## 数据状态",
        "",
        f"- 日度状态区间：`{result.start}` 至 `{result.end}`",
        f"- 首次突破事件区间：`{result.event_sample_start}` 至 `{result.event_sample_end}`",
        f"- 独立趋势episode：`{result.event_count}`",
        f"- 事件轨迹行：`{result.trajectory_row_count}`",
        f"- 成熟5D/20D事件：`{result.mature_5d_count}` / `{result.mature_20d_count}`",
        f"- 最新事件：`{result.latest_event_date}` / `{result.latest_event_direction}` / "
        f"`{result.latest_option_timing_state}`",
        "",
        "## 研究定义",
        "",
        "- 每个趋势episode只保留首次突破，轨迹日不作为独立统计样本。",
        "- 观察窗口为事件前后交易日；T+1以后路径只用于历史后验解释。",
        "- 全链持仓确认：多头对应LONG_BUILD，空头对应SHORT_BUILD。",
        "- 期权确认：期权方向与事件方向一致、factor_status=READY且流动性达标。",
        "- 连续确认以第二个连续交易日收盘后才视为可知，禁止回填到第一日。",
        "- FDR显著结果还必须通过年度覆盖和方向一致性门槛，避免单一年度或合并样本误导。",
        "- 通过门槛的结果仍只是后验研究假设；完整确认时序在T日不可知，不具备实时晋级资格。",
        "- 等待期权确认收益是反事实研究，不是进场或仓位规则。",
        "",
        "## 确认时点分布",
        "",
        *_timing_distribution_lines(timing),
        "",
        "## 时序状态的历史增量证据",
        "",
        *_state_summary_lines(state_summary),
        "",
        "## 等待期权确认的延迟成本",
        "",
        *_delay_summary_lines(delay_summary),
        "",
        "## 成功与失败突破的事件轨迹",
        "",
        *_trajectory_summary_lines(trajectory_summary),
        "",
        "## 当前研究结论",
        "",
        *_conclusion_lines(result=result, delay_summary=delay_summary),
        "",
        "## 研究边界",
        "",
        f"> {RESEARCH_BOUNDARY}",
        "",
        "- 期权方向、IV、PCR和skew仍为研究proxy；不代表精确美式期权风险暴露。",
        "- 公开期权持仓不能识别买卖双方，也不能直接推断dealer gamma。",
        "- 轨迹汇总中的每日行具有episode内相关性，只作描述，不进入显著性样本数。",
        "- 所有5D/20D收益和等待确认收益均为历史后验标签，不进入最新信号。",
        "- 不修改signal matrix、composite_score、策略方向或目标手数，不构成交易指令。",
        "",
        "## 人工复核项",
        "",
        *[f"- `{item}`" for item in HUMAN_REVIEW_REQUIRED],
    ]
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _timing_distribution_lines(timing: pd.DataFrame) -> list[str]:
    lines = [
        "| 确认对象 | 时序状态 | episode数 | 占比 |",
        "| --- | --- | ---: | ---: |",
    ]
    labels = {
        "option_timing_state": "期权方向确认",
        "participation_timing_state": "全链持仓确认",
        "lead_lag_state": "期权-持仓先后",
    }
    total = len(timing)
    for column, label in labels.items():
        for state, count in timing[column].value_counts().items():
            lines.append(
                f"| {label} | {state} | {count} | {_pct(count / total if total else math.nan)} |"
            )
    return lines


def _state_summary_lines(summary: pd.DataFrame) -> list[str]:
    ranked = summary.sort_values(
        ["fdr_q_value", "sample_count"], ascending=[True, False], na_position="last"
    ).head(24)
    lines = [
        "| 维度 | 状态 | 周期 | 样本/对照 | 命中差 | 收益差 | q值 | 年度覆盖 | 方向一致性 | 结论 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in ranked.itertuples(index=False):
        lines.append(
            f"| {row.timing_dimension} | {row.timing_state} | {row.horizon}D | "
            f"{row.sample_count}/{row.comparison_sample_count} | {_pct(row.delta_hit_rate)} | "
            f"{_pct(row.delta_mean_directional_return)} | {_number(row.fdr_q_value)} | "
            f"{row.annual_eligible_year_count} | "
            f"{_pct(row.annual_direction_consistency)} | "
            f"{row.incremental_status} |"
        )
    return lines


def _delay_summary_lines(summary: pd.DataFrame) -> list[str]:
    lines = [
        "| 周期 | 等待状态 | 样本 | 命中率 | 原始方向收益 | 等待后收益 | 收益差 | 漏掉成功事件 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {row.horizon}D | {row.wait_status} | {row.event_count} | "
            f"{_pct(row.hit_rate)} | {_pct(row.mean_directional_return)} | "
            f"{_pct(row.mean_strict_wait_return)} | "
            f"{_pct(row.mean_arithmetic_return_difference)} | "
            f"{row.missed_follow_through_count} |"
        )
    return lines


def _trajectory_summary_lines(summary: pd.DataFrame) -> list[str]:
    selected_sessions = {-10, -5, -3, -1, 0, 1, 3, 5, 10, 20}
    selected = summary.loc[
        summary["relative_session"].isin(selected_sessions)
        & summary["horizon"].eq(20)
        & summary["outcome"].isin(["FOLLOW_THROUGH", "FAILED_BREAKOUT"])
    ]
    lines = [
        "| 20D结果 | 相对交易日 | episode数 | 方向价格路径 | "
        "全链增仓确认率 | 期权确认率 | IV重定价率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in selected.itertuples(index=False):
        lines.append(
            f"| {row.outcome} | {row.relative_session} | {row.event_count} | "
            f"{_pct(row.mean_directional_price_vs_event)} | "
            f"{_pct(row.participation_confirmation_rate)} | "
            f"{_pct(row.option_confirmation_rate)} | "
            f"{_pct(row.volatility_repricing_rate)} |"
        )
    if len(lines) == 2:
        lines.append("| 无成熟样本 | - | 0 | - | - | - | - |")
    return lines


def _conclusion_lines(
    *,
    result: TrendConfirmationTimingResult,
    delay_summary: pd.DataFrame,
) -> list[str]:
    lines = [
        f"- 期权在突破前或当日完成连续确认：`{result.option_confirmed_by_breakout_count}` / "
        f"`{result.event_count}` 个episode。",
        f"- T+20窗口内始终未完成期权确认：`{result.option_never_confirmed_count}` 个episode。",
        f"- FDR及年度稳定性门槛后正向/负向后验研究假设：`{result.positive_candidate_count}` / "
        f"`{result.negative_filter_count}`。",
    ]
    for horizon in sorted(delay_summary["horizon"].unique()):
        all_row = delay_summary.loc[
            delay_summary["horizon"].eq(horizon)
            & delay_summary["wait_status"].eq("ALL")
        ]
        if all_row.empty:
            continue
        row = all_row.iloc[0]
        lines.append(
            f"- {horizon}D严格等待期权确认会漏掉 "
            f"`{int(row['missed_follow_through_count'])}` 个历史成功突破；"
            "该计数只用于识别过滤器机会成本。"
        )
    if result.positive_candidate_count == 0 and result.negative_filter_count == 0:
        lines.append(
            "- 当前没有同时通过FDR与年度稳定性门槛的时序规则，"
            "不能把期权确认直接升级为趋势进场条件。"
        )
    else:
        lines.append(
            "- 上述候选依赖突破后的完整确认路径，只能用于生成下一阶段可知时点假设，"
            "不得直接作为突破日实时过滤器。"
        )
    return lines


def _group_metrics(group: pd.DataFrame) -> dict[str, float | int]:
    count = len(group)
    successes = int(group["outcome"].eq("FOLLOW_THROUGH").sum())
    hit_rate = successes / count if count else math.nan
    lower, upper = _wilson_interval(successes, count)
    return {
        "sample_count": count,
        "success_count": successes,
        "hit_rate": hit_rate,
        "hit_rate_ci_lower": lower,
        "hit_rate_ci_upper": upper,
        "mean_directional_return": _mean(group["directional_return"]),
        "median_directional_return": _median(group["directional_return"]),
    }


def _incremental_status(
    row: pd.Series,
    *,
    min_sample_size: int,
    fdr_level: float,
    min_annual_coverage_years: int,
    min_annual_direction_consistency: float,
) -> str:
    comparison_floor = max(8, min_sample_size // 2)
    enough = (
        int(row["sample_count"]) >= min_sample_size
        and int(row["comparison_sample_count"]) >= comparison_floor
    )
    positive = float(row["delta_hit_rate"]) > 0 and float(
        row["delta_mean_directional_return"]
    ) > 0
    negative = float(row["delta_hit_rate"]) < 0 and float(
        row["delta_mean_directional_return"]
    ) < 0
    significant = math.isfinite(float(row["fdr_q_value"])) and float(
        row["fdr_q_value"]
    ) <= fdr_level
    annual_coverage = int(row["annual_eligible_year_count"])
    if positive:
        aligned_years = int(row["annual_positive_year_count"])
    elif negative:
        aligned_years = int(row["annual_negative_year_count"])
    else:
        aligned_years = 0
    annual_consistency = (
        aligned_years / annual_coverage if annual_coverage else math.nan
    )
    annual_coverage_ready = annual_coverage >= min_annual_coverage_years
    annual_direction_ready = (
        math.isfinite(annual_consistency)
        and annual_consistency >= min_annual_direction_consistency
    )
    if not enough:
        return "SMALL_OR_UNBALANCED_SAMPLE"
    if significant and positive:
        if not annual_coverage_ready:
            return "WATCH_POSITIVE_ANNUAL_COVERAGE"
        if not annual_direction_ready:
            return "WATCH_POSITIVE_ANNUAL_INSTABILITY"
        return "RESEARCH_CANDIDATE_POSITIVE"
    if significant and negative:
        if not annual_coverage_ready:
            return "WATCH_NEGATIVE_ANNUAL_COVERAGE"
        if not annual_direction_ready:
            return "WATCH_NEGATIVE_ANNUAL_INSTABILITY"
        return "RESEARCH_FILTER_NEGATIVE"
    if positive:
        return "WATCH_POSITIVE"
    if negative:
        return "WATCH_NEGATIVE"
    return "INCONCLUSIVE"


def _wilson_interval(successes: int, count: int) -> tuple[float, float]:
    if count <= 0:
        return math.nan, math.nan
    z = 1.959963984540054
    rate = successes / count
    denominator = 1 + z**2 / count
    centre = (rate + z**2 / (2 * count)) / denominator
    margin = (
        z
        * math.sqrt(rate * (1 - rate) / count + z**2 / (4 * count**2))
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


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
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    count = len(p_values)
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = count - reverse_rank + 1
        running = min(running, min(1.0, p_values[index] * count / rank))
        adjusted[index] = running
    return adjusted


def _first_sustained_confirmation(
    group: pd.DataFrame,
    *,
    flag_column: str,
    confirmation_days: int,
) -> dict[str, object]:
    ordered = group.sort_values("relative_session").reset_index(drop=True)
    flags = _bool_series(ordered[flag_column]).tolist()
    relative_sessions = ordered["relative_session"].astype(int).tolist()
    for start in range(len(ordered) - confirmation_days + 1):
        stop = start + confirmation_days
        candidate_sessions = relative_sessions[start:stop]
        consecutive = all(
            right - left == 1
            for left, right in zip(candidate_sessions, candidate_sessions[1:])
        )
        if consecutive and all(flags[start:stop]):
            # 连续两日只有在第二日结束后才能确认，不能回填为第一日信号。
            completion = stop - 1
            return {
                "relative_session": int(relative_sessions[completion]),
                "state_date": ordered.iloc[completion]["state_date"],
                "left_censored": start == 0,
            }
    return {
        "relative_session": None,
        "state_date": None,
        "left_censored": False,
    }


def _timing_state(value: object) -> str:
    if value is None or pd.isna(value):
        return "NO_CONFIRMATION_IN_WINDOW"
    session = int(value)
    if session <= 0:
        return "PRE_OR_AT_BREAKOUT"
    if session <= 3:
        return "POST_BREAKOUT_1_3D"
    if session <= 10:
        return "POST_BREAKOUT_4_10D"
    return "POST_BREAKOUT_GT_10D"


def _lead_lag_state(
    *,
    option_session: object,
    participation_session: object,
) -> str:
    option_missing = option_session is None or pd.isna(option_session)
    participation_missing = (
        participation_session is None or pd.isna(participation_session)
    )
    if option_missing and participation_missing:
        return "NEITHER_CONFIRMED"
    if option_missing:
        return "ONLY_PARTICIPATION_CONFIRMED"
    if participation_missing:
        return "ONLY_OPTION_CONFIRMED"
    difference = int(option_session) - int(participation_session)
    if difference <= -2:
        return "OPTION_LEADS"
    if difference >= 2:
        return "PARTICIPATION_LEADS"
    return "COINCIDENT_WITHIN_1D"


def _difference_or_nan(left: object, right: object) -> float:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return math.nan
    return float(left) - float(right)


def _participation_alignment(*, direction: str, state: object) -> str:
    observed = str(state or "")
    confirming = "LONG_BUILD" if direction == "long" else "SHORT_BUILD"
    opposing = "SHORT_BUILD" if direction == "long" else "LONG_BUILD"
    if observed == confirming:
        return "CONFIRM"
    if observed == opposing:
        return "OPPOSE"
    return "NEUTRAL_OR_ROLL"


def _option_alignment(
    *,
    direction: str,
    option_direction: object,
    factor_status: object,
    liquidity_score: object,
    min_liquidity_score: float,
) -> str:
    score = _float_or_nan(liquidity_score)
    if str(factor_status or "") != "READY" or not math.isfinite(score):
        return "OPTION_NOT_READY"
    if score < min_liquidity_score:
        return "OPTION_NOT_READY"
    observed = str(option_direction or "neutral")
    if observed == direction:
        return "CONFIRM"
    if observed in {"long", "short"}:
        return "DIVERGE"
    return "NEUTRAL"


def _rolling_percentile_rank(
    series: pd.Series,
    *,
    window: int,
    min_periods: int,
) -> pd.Series:
    def rank_last(values: pd.Series) -> float:
        clean = values.dropna()
        if clean.empty:
            return math.nan
        last = clean.iloc[-1]
        return float((clean <= last).mean())

    return series.rolling(window=window, min_periods=min_periods).apply(
        rank_last, raw=False
    )


def _load_frame(path: Path, required: set[str], label: str) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"{label}不存在: {path}")
    frame = pd.read_parquet(path)
    missing = required - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"{label}缺少字段: {sorted(missing)}")
    working = frame.copy()
    for column in ("trade_date", "event_date", "exit_date"):
        if column not in working.columns:
            continue
        parsed = pd.to_datetime(working[column], errors="coerce")
        if column in required and parsed.isna().any():
            raise ResearchWorkbenchError(f"{label}存在无效{column}")
        working[column] = parsed.dt.date
    return working


def _latest_path(root: Path, pattern: str, label: str) -> Path:
    candidates = list(root.glob(pattern))
    if not candidates:
        raise ResearchWorkbenchError(f"找不到{label}: {root / pattern}")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / "trend_confirmation_timing"
    report_root = (
        report_output_dir
        or reports_dir() / "research" / "trend_confirmation_timing"
    )
    stem = f"CF_{start}_{end}_trend_confirmation_timing"
    return {
        "event_index": root / f"{stem}_event_index.parquet",
        "trajectory": root / f"{stem}_trajectory_daily.parquet",
        "timing": root / f"{stem}_timing_event.parquet",
        "state_summary": root / f"{stem}_state_summary.parquet",
        "trajectory_summary": root / f"{stem}_trajectory_summary.parquet",
        "delay_events": root / f"{stem}_delay_event.parquet",
        "delay_summary": root / f"{stem}_delay_summary.parquet",
        "annual_summary": root / f"{stem}_annual_summary.parquet",
        "warnings": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
    }


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    pre_window_sessions: int,
    post_window_sessions: int,
    confirmation_days: int,
    min_sample_size: int,
    fdr_level: float,
    min_annual_coverage_years: int,
    min_annual_group_size: int,
    min_annual_direction_consistency: float,
    volume_rank_window: int,
    volume_rank_min_periods: int,
    min_option_liquidity_score: float,
    dead_zone_bps: int,
) -> None:
    if pre_window_sessions < 1:
        raise ResearchWorkbenchError("pre_window_sessions必须为正整数")
    if post_window_sessions < max(horizons):
        raise ResearchWorkbenchError("post_window_sessions不得小于最大研究周期")
    if confirmation_days < 1 or confirmation_days > pre_window_sessions:
        raise ResearchWorkbenchError("confirmation_days必须位于[1, pre_window_sessions]")
    if min_sample_size < 1:
        raise ResearchWorkbenchError("min_sample_size必须为正整数")
    if not 0 < fdr_level <= 1:
        raise ResearchWorkbenchError("fdr_level必须位于(0,1]")
    if min_annual_coverage_years < 1:
        raise ResearchWorkbenchError("min_annual_coverage_years必须为正整数")
    if min_annual_group_size < 1:
        raise ResearchWorkbenchError("min_annual_group_size必须为正整数")
    if not 0 < min_annual_direction_consistency <= 1:
        raise ResearchWorkbenchError(
            "min_annual_direction_consistency必须位于(0,1]"
        )
    if volume_rank_window < 2:
        raise ResearchWorkbenchError("volume_rank_window至少为2")
    if not 1 <= volume_rank_min_periods <= volume_rank_window:
        raise ResearchWorkbenchError("volume_rank_min_periods必须位于有效窗口内")
    if min_option_liquidity_score < 0:
        raise ResearchWorkbenchError("min_option_liquidity_score不得为负")
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("dead_zone_bps不得为负")


def _normalize_horizons(values: tuple[int, ...]) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in values)))
    if not normalized or any(value <= 0 for value in normalized):
        raise ResearchWorkbenchError("horizons必须包含正整数")
    return normalized


def _bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    return series.map(
        lambda value: str(value).strip().lower() in {"1", "true", "yes", "y"}
    )


def _float_or_nan(value: object) -> float:
    if value is None or pd.isna(value):
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if not values.empty else math.nan


def _median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.median()) if not values.empty else math.nan


def _bool_mean(series: pd.Series) -> float:
    return float(_bool_series(series).mean()) if len(series) else math.nan


def _mature_count(event_index: pd.DataFrame, horizon: int) -> int:
    column = f"label_available_{horizon}d"
    return int(_bool_series(event_index[column]).sum()) if column in event_index else 0


def _pct(value: object) -> str:
    number = _float_or_nan(value)
    return "-" if not math.isfinite(number) else f"{number:.2%}"


def _number(value: object) -> str:
    number = _float_or_nan(value)
    return "-" if not math.isfinite(number) else f"{number:.4f}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id() -> str:
    return f"cf_r93l_{datetime.now(tz=UTC):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}"
