"""R93B CF 趋势环境与期权结构节奏增量研究。"""

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

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir

PRODUCT_CODE = "CF"
TREND_OPTION_TIMING_VERSION = "V5.1_R93B_trend_option_timing_v3_main_cycle_relay"
DEFAULT_RANK_WINDOW = 252
DEFAULT_RANK_MIN_PERIODS = 60
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_FDR_LEVEL = 0.10
INFO = "INFO"
WARN = "WARN"
HUMAN_REVIEW_REQUIRED = (
    "rolling_rank_window",
    "volatility_regime_thresholds",
    "option_change_bucket_thresholds",
    "strike_wall_distance_interpretation",
    "policy_event_context_not_connected",
    "candidate_position_sizing_not_defined",
)
RESEARCH_BOUNDARY = (
    "事件特征仅使用突破当日及以前数据；方向收益只作为历史后验标签。"
    "本模块进行多重检验校正，不修改期货主模型，不构成交易指令。"
)
DAILY_COLUMNS = {
    "trade_date",
    "main_contract",
    "trend_direction",
    "trend_stage",
    "trend_strength",
    "realized_volatility_fast",
    "direction_episode_id",
    "option_alignment",
    "participation_alignment",
    "roll_context",
}
EVENT_COLUMNS = {
    "event_id",
    "event_date",
    "event_year",
    "direction",
    "direction_episode_id",
    "main_contract",
    "horizon",
    "directional_return",
    "label_available",
    "outcome",
    "historical_posterior_label",
}
OPTION_COLUMNS = {
    "trade_date",
    "underlying_contract",
    "atm_iv_proxy",
    "atm_iv_proxy_change_1d",
    "atm_iv_rank",
    "atm_iv_rank_change_1d",
    "pcr_volume",
    "pcr_volume_change_1d",
    "pcr_oi",
    "pcr_oi_change_1d",
    "skew_proxy",
    "skew_proxy_change_1d",
    "volatility_repricing_state",
    "option_liquidity_score",
}
OPTION_RELAY_COLUMNS = {
    "main_contract",
    "option_selection_reason",
    "option_relay_used",
    "option_tenor_gap_months",
}
STRIKE_COLUMNS = {
    "trade_date",
    "underlying_contract",
    "is_main_contract",
    "distance_to_call_wall",
    "distance_to_put_wall",
    "call_wall_oi_change",
    "put_wall_oi_change",
    "call_wall_strike_shift_1d",
    "put_wall_strike_shift_1d",
    "key_level_state",
    "key_level_migration_state",
    "expiry_bucket",
}
FEATURE_COLUMNS = (
    "volatility_regime",
    "trend_strength_bucket",
    "iv_level_regime",
    "iv_change_bucket",
    "skew_trend_alignment",
    "pcr_oi_trend_alignment",
    "directional_wall_bucket",
    "directional_wall_oi_state",
    "directional_wall_migration",
    "option_alignment",
    "participation_alignment",
    "roll_context",
)
WARNING_COLUMNS = (
    "run_id",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)


@dataclass(frozen=True)
class TrendOptionTimingWarningRecord:
    """R93B warning row."""

    run_id: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-safe warning row."""
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class TrendOptionTimingResult:
    """R93B result bundle."""

    run_id: str
    start: date
    end: date
    event_sample_start: date
    event_sample_end: date
    status: str
    independent_event_rows: int
    independent_episode_count: int
    tested_group_count: int
    positive_candidate_count: int
    negative_filter_count: int
    current_direction: str
    current_stage: str
    event_feature_path: Path
    summary_path: Path
    ranking_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[TrendOptionTimingWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(item.severity != INFO for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        """Return compact CLI output."""
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "event_sample_start": self.event_sample_start.isoformat(),
            "event_sample_end": self.event_sample_end.isoformat(),
            "status": self.status,
            "independent_event_rows": self.independent_event_rows,
            "independent_episode_count": self.independent_episode_count,
            "tested_group_count": self.tested_group_count,
            "positive_candidate_count": self.positive_candidate_count,
            "negative_filter_count": self.negative_filter_count,
            "current_direction": self.current_direction,
            "current_stage": self.current_stage,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "event_feature_path": str(self.event_feature_path),
            "summary_path": str(self.summary_path),
            "ranking_path": str(self.ranking_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "research_boundary": RESEARCH_BOUNDARY,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_trend_option_timing_research(
    *,
    symmetric_trend_daily_path: Path | None = None,
    breakout_event_path: Path | None = None,
    option_structure_path: Path | None = None,
    strike_position_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    rank_window: int = DEFAULT_RANK_WINDOW,
    rank_min_periods: int = DEFAULT_RANK_MIN_PERIODS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
) -> TrendOptionTimingResult:
    """Build independent trend-event timing evidence with option and wall features."""
    _validate_parameters(
        rank_window=rank_window,
        rank_min_periods=rank_min_periods,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
    )
    daily_path = symmetric_trend_daily_path or _latest_symmetric_trend_daily_path()
    event_path = breakout_event_path or _latest_breakout_event_path()
    option_path = option_structure_path or _latest_option_structure_path()
    strike_path = strike_position_path or _latest_strike_position_path()
    daily = _load_frame(daily_path, DAILY_COLUMNS, "R93A symmetric trend daily")
    events = _load_frame(event_path, EVENT_COLUMNS, "R93A breakout events")
    option = _load_frame(option_path, OPTION_COLUMNS, "R75 option structure")
    strike = _load_frame(strike_path, STRIKE_COLUMNS, "R84 strike position")
    # 状态区间以 R93A 日度状态为准；历史事件标签区间单独披露，避免报告截止日回退。
    start = daily["trade_date"].min()
    end = daily["trade_date"].max()
    active_run_id = run_id or _default_run_id(start=start, end=end)

    daily_features = _build_daily_features(
        daily=daily,
        option=option,
        strike=strike,
        rank_window=rank_window,
        rank_min_periods=rank_min_periods,
    )
    independent_events = _build_independent_events(
        events=events,
        daily_features=daily_features,
        run_id=active_run_id,
    )
    event_sample_start = independent_events["event_date"].min()
    event_sample_end = independent_events["event_date"].max()
    summary = _build_summary(
        independent_events,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
    )
    ranking = _build_ranking(summary)
    warnings = _warning_records(
        run_id=active_run_id,
        daily_features=daily_features,
        independent_events=independent_events,
        summary=summary,
        strike_path=strike_path,
        min_sample_size=min_sample_size,
    )
    positive_count = int(summary["incremental_status"].eq("POSITIVE_CANDIDATE").sum())
    negative_count = int(summary["incremental_status"].eq("NEGATIVE_FILTER").sum())
    status = (
        "TREND_OPTION_TIMING_READY_WITH_WARNINGS"
        if any(item.severity == WARN for item in warnings)
        else "TREND_OPTION_TIMING_READY"
    )
    paths = _output_paths(
        start=start,
        end=end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    latest = daily_features.iloc[-1]
    result = TrendOptionTimingResult(
        run_id=active_run_id,
        start=start,
        end=end,
        event_sample_start=event_sample_start,
        event_sample_end=event_sample_end,
        status=status,
        independent_event_rows=len(independent_events),
        independent_episode_count=int(
            independent_events["direction_episode_id"].nunique()
        ),
        tested_group_count=int(summary["fdr_q_value"].notna().sum()),
        positive_candidate_count=positive_count,
        negative_filter_count=negative_count,
        current_direction=str(latest["trend_direction"]),
        current_stage=str(latest["trend_stage"]),
        event_feature_path=paths["events"],
        summary_path=paths["summary"],
        ranking_path=paths["ranking"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=tuple(warnings),
    )
    _write_outputs(
        result=result,
        independent_events=independent_events,
        summary=summary,
        ranking=ranking,
        current_context=_current_context(latest),
        input_paths=(daily_path, event_path, option_path, strike_path),
        parameters={
            "rank_window": rank_window,
            "rank_min_periods": rank_min_periods,
            "min_sample_size": min_sample_size,
            "comparison_sample_floor": _comparison_sample_floor(min_sample_size),
            "fdr_level": fdr_level,
        },
    )
    return result


def _build_daily_features(
    *,
    daily: pd.DataFrame,
    option: pd.DataFrame,
    strike: pd.DataFrame,
    rank_window: int,
    rank_min_periods: int,
) -> pd.DataFrame:
    option_working = option.copy()
    if "main_contract" not in option_working.columns:
        option_working["main_contract"] = option_working["underlying_contract"]
    option_working = option_working.rename(
        columns={"underlying_contract": "option_underlying_contract"}
    )
    if "option_selection_reason" not in option_working.columns:
        option_working["option_selection_reason"] = "LEGACY_MAIN_CONTRACT_FALLBACK"
    if "option_relay_used" not in option_working.columns:
        option_working["option_relay_used"] = False
    if "option_tenor_gap_months" not in option_working.columns:
        option_working["option_tenor_gap_months"] = 0
    strike_working = strike.rename(
        columns={"underlying_contract": "strike_underlying_contract"}
    )
    if option_working.duplicated(["trade_date", "main_contract"]).any():
        raise ResearchWorkbenchError("option structure has duplicate date/contract rows")
    if strike_working.duplicated(["trade_date", "strike_underlying_contract"]).any():
        raise ResearchWorkbenchError("strike position has duplicate date/contract rows")
    working = daily.merge(
        option_working,
        on=["trade_date", "main_contract"],
        how="left",
        validate="one_to_one",
    )
    working["strike_join_contract"] = working["option_underlying_contract"].fillna(
        working["main_contract"]
    )
    working = working.merge(
        strike_working,
        left_on=["trade_date", "strike_join_contract"],
        right_on=["trade_date", "strike_underlying_contract"],
        how="left",
        validate="one_to_one",
    )
    working = working.sort_values("trade_date").reset_index(drop=True)

    rank_inputs = {
        "volatility_rank": "realized_volatility_fast",
        "iv_change_rank": "atm_iv_proxy_change_1d",
        "skew_change_rank": "skew_proxy_change_1d",
        "pcr_oi_change_rank": "pcr_oi_change_1d",
    }
    for output_column, source_column in rank_inputs.items():
        working[output_column] = _rolling_percentile_rank(
            pd.to_numeric(working[source_column], errors="coerce"),
            window=rank_window,
            min_periods=rank_min_periods,
        )
    working["volatility_regime"] = working["volatility_rank"].map(
        lambda value: _three_way_rank_bucket(value, "LOW_VOL", "MID_VOL", "HIGH_VOL")
    )
    working["trend_strength_bucket"] = working["trend_strength"].map(
        _strength_bucket
    )
    working["iv_level_regime"] = working["atm_iv_rank"].map(_iv_level_bucket)
    working["iv_change_bucket"] = working["iv_change_rank"].map(
        lambda value: _three_way_rank_bucket(
            value,
            "IV_CONTRACTING",
            "IV_STABLE",
            "IV_EXPANDING",
        )
    )
    working["skew_change_bucket"] = working["skew_change_rank"].map(
        lambda value: _three_way_rank_bucket(value, "SKEW_DOWN", "SKEW_STABLE", "SKEW_UP")
    )
    working["pcr_oi_change_bucket"] = working["pcr_oi_change_rank"].map(
        lambda value: _three_way_rank_bucket(value, "PCR_OI_DOWN", "PCR_OI_STABLE", "PCR_OI_UP")
    )
    # skew/PCR 的原始升降对多空含义相反，先转换成相对趋势方向的支持或背离。
    working["skew_trend_alignment"] = working.apply(
        lambda row: _directional_change_alignment(
            direction=row["trend_direction"],
            bucket=row["skew_change_bucket"],
            down_bucket="SKEW_DOWN",
            stable_bucket="SKEW_STABLE",
            up_bucket="SKEW_UP",
        ),
        axis=1,
    )
    working["pcr_oi_trend_alignment"] = working.apply(
        lambda row: _directional_change_alignment(
            direction=row["trend_direction"],
            bucket=row["pcr_oi_change_bucket"],
            down_bucket="PCR_OI_DOWN",
            stable_bucket="PCR_OI_STABLE",
            up_bucket="PCR_OI_UP",
        ),
        axis=1,
    )
    wall_metrics = working.apply(_directional_wall_metrics, axis=1, result_type="expand")
    working[[
        "directional_wall_distance",
        "directional_wall_oi_change",
        "directional_wall_shift",
    ]] = wall_metrics
    working["directional_wall_bucket"] = working["directional_wall_distance"].map(
        _wall_distance_bucket
    )
    working["directional_wall_oi_state"] = working[
        "directional_wall_oi_change"
    ].map(_wall_oi_state)
    working["directional_wall_migration"] = working["directional_wall_shift"].map(
        _wall_migration_bucket
    )
    working["event_features_use_t_or_earlier"] = True
    return working


def _build_independent_events(
    *,
    events: pd.DataFrame,
    daily_features: pd.DataFrame,
    run_id: str,
) -> pd.DataFrame:
    available = events.loc[events["label_available"].astype(bool)].copy()
    if available.empty:
        raise ResearchWorkbenchError("R93B has no available historical event labels")
    available = available.sort_values(["event_date", "event_id"])
    independent = available.drop_duplicates(
        ["direction_episode_id", "horizon"],
        keep="first",
    ).copy()
    feature_columns = [
        "trade_date",
        "main_contract",
        "option_underlying_contract",
        "option_selection_reason",
        "option_relay_used",
        "option_tenor_gap_months",
        "trend_direction",
        "trend_stage",
        "trend_strength",
        "realized_volatility_fast",
        "volatility_rank",
        "volatility_regime",
        "trend_strength_bucket",
        "atm_iv_proxy",
        "atm_iv_proxy_change_1d",
        "atm_iv_rank",
        "atm_iv_rank_change_1d",
        "iv_level_regime",
        "iv_change_rank",
        "iv_change_bucket",
        "skew_proxy",
        "skew_proxy_change_1d",
        "skew_change_rank",
        "skew_change_bucket",
        "skew_trend_alignment",
        "pcr_volume",
        "pcr_volume_change_1d",
        "pcr_oi",
        "pcr_oi_change_1d",
        "pcr_oi_change_rank",
        "pcr_oi_change_bucket",
        "pcr_oi_trend_alignment",
        "directional_wall_bucket",
        "directional_wall_oi_state",
        "directional_wall_migration",
        "directional_wall_distance",
        "directional_wall_oi_change",
        "directional_wall_shift",
        "option_liquidity_score",
        "option_alignment",
        "participation_alignment",
        "roll_context",
        "volatility_repricing_state",
        "key_level_state",
        "key_level_migration_state",
        "expiry_bucket",
        "event_features_use_t_or_earlier",
    ]
    features = daily_features[feature_columns].rename(columns={"trade_date": "event_date"})
    merged = independent.merge(
        features,
        on=["event_date", "main_contract"],
        how="left",
        validate="many_to_one",
        suffixes=("", "_feature"),
    )
    if merged["event_features_use_t_or_earlier"].isna().any():
        raise ResearchWorkbenchError("R93B cannot resolve T-day features for every event")
    merged["feature_asof_date"] = merged["event_date"]
    merged["run_id"] = run_id
    merged["rule_version"] = TREND_OPTION_TIMING_VERSION
    merged["historical_posterior_label"] = True
    merged["trading_instruction"] = "not_a_trading_instruction"
    return merged.sort_values(["event_date", "horizon"]).reset_index(drop=True)


def _build_summary(
    events: pd.DataFrame,
    *,
    min_sample_size: int,
    fdr_level: float,
) -> pd.DataFrame:
    baseline: dict[int, dict[str, float | int]] = {}
    rows: list[dict[str, object]] = []
    for horizon, group in events.groupby("horizon", sort=True):
        metrics = _group_metrics(group)
        baseline[int(horizon)] = metrics
        rows.append(
            {
                "feature_name": "ALL",
                "feature_value": "ALL",
                "horizon": int(horizon),
                **metrics,
                "baseline_hit_rate": metrics["hit_rate"],
                "baseline_mean_directional_return": metrics["mean_directional_return"],
                "comparison_sample_count": 0,
                "comparison_success_count": 0,
                "comparison_hit_rate": math.nan,
                "comparison_mean_directional_return": math.nan,
                "delta_hit_rate": 0.0,
                "delta_mean_directional_return": 0.0,
                "incremental_exact_p_value": math.nan,
                "evidence_level": "BASELINE",
                "incremental_status": "BASELINE",
            }
        )
    for feature in FEATURE_COLUMNS:
        working = events.copy()
        working[feature] = working[feature].fillna("MISSING").astype(str)
        for (value, horizon), group in working.groupby([feature, "horizon"], sort=True):
            metrics = _group_metrics(group)
            base = baseline[int(horizon)]
            comparison = working.loc[
                working["horizon"].eq(horizon) & working[feature].ne(value)
            ]
            comparison_metrics = _group_metrics(comparison)
            exact_p_value = _fisher_exact_two_sided(
                group_successes=int(metrics["success_count"]),
                group_count=int(metrics["sample_count"]),
                comparison_successes=int(comparison_metrics["success_count"]),
                comparison_count=int(comparison_metrics["sample_count"]),
            )
            comparison_count = int(comparison_metrics["sample_count"])
            comparison_floor = _comparison_sample_floor(min_sample_size)
            sufficient_comparison = (
                int(metrics["sample_count"]) >= min_sample_size
                and comparison_count >= comparison_floor
            )
            rows.append(
                {
                    "feature_name": feature,
                    "feature_value": value,
                    "horizon": int(horizon),
                    **metrics,
                    "baseline_hit_rate": base["hit_rate"],
                    "baseline_mean_directional_return": base[
                        "mean_directional_return"
                    ],
                    "comparison_sample_count": comparison_count,
                    "comparison_success_count": comparison_metrics["success_count"],
                    "comparison_hit_rate": comparison_metrics["hit_rate"],
                    "comparison_mean_directional_return": comparison_metrics[
                        "mean_directional_return"
                    ],
                    "delta_hit_rate": (
                        metrics["hit_rate"] - comparison_metrics["hit_rate"]
                    ),
                    "delta_mean_directional_return": (
                        metrics["mean_directional_return"]
                        - comparison_metrics["mean_directional_return"]
                    ),
                    "incremental_exact_p_value": exact_p_value,
                    "evidence_level": (
                        "SUFFICIENT_COMPARISON"
                        if sufficient_comparison
                        else "SMALL_OR_UNBALANCED_SAMPLE"
                    ),
                    "incremental_status": "PENDING_FDR",
                }
            )
    summary = pd.DataFrame(rows)
    summary["fdr_q_value"] = math.nan
    data_gap = summary["feature_name"].ne("ALL") & summary["feature_value"].eq(
        "MISSING"
    )
    summary.loc[data_gap, "evidence_level"] = "DATA_GAP"
    summary.loc[data_gap, "incremental_status"] = "DATA_GAP_NOT_TESTED"
    tested = summary["feature_name"].ne("ALL") & ~data_gap
    summary.loc[tested, "fdr_q_value"] = _benjamini_hochberg(
        summary.loc[tested, "incremental_exact_p_value"].astype(float).tolist()
    )
    for index in summary.index[tested]:
        row = summary.loc[index]
        summary.at[index, "incremental_status"] = _incremental_status(
            row,
            min_sample_size=min_sample_size,
            fdr_level=fdr_level,
        )
    summary["rule_version"] = TREND_OPTION_TIMING_VERSION
    return summary.sort_values(
        ["horizon", "feature_name", "feature_value"]
    ).reset_index(drop=True)


def _group_metrics(group: pd.DataFrame) -> dict[str, float | int]:
    count = len(group)
    successes = int(group["outcome"].eq("FOLLOW_THROUGH").sum())
    hit_rate = successes / count if count else math.nan
    ci_lower, ci_upper = _wilson_interval(successes=successes, sample_count=count)
    return {
        "sample_count": count,
        "success_count": successes,
        "hit_rate": hit_rate,
        "hit_rate_ci_lower": ci_lower,
        "hit_rate_ci_upper": ci_upper,
        "mean_directional_return": (
            float(group["directional_return"].mean()) if count else math.nan
        ),
        "median_directional_return": (
            float(group["directional_return"].median()) if count else math.nan
        ),
        "binomial_p_value": (
            _exact_binomial_two_sided(successes, count) if count else math.nan
        ),
    }


def _incremental_status(
    row: pd.Series,
    *,
    min_sample_size: int,
    fdr_level: float,
) -> str:
    count = int(row["sample_count"])
    comparison_count = int(row["comparison_sample_count"])
    delta_hit = float(row["delta_hit_rate"])
    delta_return = float(row["delta_mean_directional_return"])
    q_value = float(row["fdr_q_value"])
    comparison_floor = _comparison_sample_floor(min_sample_size)
    if (
        count >= min_sample_size
        and comparison_count >= comparison_floor
        and q_value <= fdr_level
    ):
        if delta_hit > 0 and delta_return > 0:
            return "POSITIVE_CANDIDATE"
        if delta_hit < 0 and delta_return < 0:
            return "NEGATIVE_FILTER"
    watch_threshold = max(10, min_sample_size // 2)
    if (
        count >= watch_threshold
        and comparison_count >= comparison_floor
        and delta_hit > 0
        and delta_return > 0
    ):
        return "WATCH_POSITIVE"
    if (
        count >= watch_threshold
        and comparison_count >= comparison_floor
        and delta_hit < 0
        and delta_return < 0
    ):
        return "WATCH_NEGATIVE"
    if count < min_sample_size or comparison_count < comparison_floor:
        return "SMALL_OR_UNBALANCED_SAMPLE"
    return "INCONCLUSIVE"


def _build_ranking(summary: pd.DataFrame) -> pd.DataFrame:
    tested = summary.loc[summary["fdr_q_value"].notna()].copy()
    priority = {
        "POSITIVE_CANDIDATE": 0,
        "NEGATIVE_FILTER": 1,
        "WATCH_POSITIVE": 2,
        "WATCH_NEGATIVE": 3,
        "INCONCLUSIVE": 4,
        "SMALL_OR_UNBALANCED_SAMPLE": 5,
    }
    tested["status_priority"] = tested["incremental_status"].map(priority).fillna(9)
    return tested.sort_values(
        ["status_priority", "fdr_q_value", "sample_count"],
        ascending=[True, True, False],
    ).drop(columns=["status_priority"])


def _warning_records(
    *,
    run_id: str,
    daily_features: pd.DataFrame,
    independent_events: pd.DataFrame,
    summary: pd.DataFrame,
    strike_path: Path,
    min_sample_size: int,
) -> list[TrendOptionTimingWarningRecord]:
    warnings: list[TrendOptionTimingWarningRecord] = []
    option_missing = int(independent_events["atm_iv_proxy"].isna().sum())
    if option_missing:
        warnings.append(
            TrendOptionTimingWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93B_OPTION_FEATURE_MISSING",
                warning_message="部分独立突破缺少期权动态特征，相关分组标记为MISSING。",
                affected_count=option_missing,
                human_review_required=("option_proxy_interpretation",),
            )
        )
    event_wall_missing = int(
        independent_events["directional_wall_bucket"].eq("MISSING").sum()
    )
    directional_daily = daily_features["trend_direction"].isin(("long", "short"))
    daily_wall_missing = int(
        (
            directional_daily
            & daily_features["directional_wall_bucket"].eq("MISSING")
        ).sum()
    )
    current_wall_missing = bool(
        daily_features.iloc[-1]["directional_wall_bucket"] == "MISSING"
    )
    if event_wall_missing or current_wall_missing:
        strike_latest = daily_features.loc[
            daily_features["directional_wall_distance"].notna(), "trade_date"
        ].max()
        warnings.append(
            TrendOptionTimingWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93B_STRIKE_WALL_COVERAGE_PARTIAL",
                warning_message=(
                    f"行权价OI墙覆盖不完整，当前可用最新日为{strike_latest}；"
                    f"输入为{strike_path}。"
                ),
                affected_count=max(event_wall_missing, daily_wall_missing),
                human_review_required=("strike_wall_distance_interpretation",),
            )
        )
    tested = summary["fdr_q_value"].notna()
    small_groups = int(
        (
            summary.loc[tested, "sample_count"].lt(min_sample_size)
            | summary.loc[tested, "comparison_sample_count"].lt(
                _comparison_sample_floor(min_sample_size)
            )
        ).sum()
    )
    warnings.append(
        TrendOptionTimingWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93B_MULTIPLE_TESTING_FDR_APPLIED",
            warning_message=(
                "所有非基准分组先与同周期其余独立episode做Fisher精确检验，"
                "再统一使用Benjamini-Hochberg校正。"
            ),
            affected_count=int(tested.sum()),
        )
    )
    if small_groups:
        warnings.append(
            TrendOptionTimingWarningRecord(
                run_id=run_id,
            severity=INFO,
            warning_code="R93B_SMALL_SAMPLE_GROUPS",
            warning_message="小样本或对照样本不足的分组仅作观察，不允许据此定义仓位。",
                affected_count=small_groups,
            )
        )
    positive_count = int(summary["incremental_status"].eq("POSITIVE_CANDIDATE").sum())
    if positive_count == 0:
        warnings.append(
            TrendOptionTimingWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93B_NO_FDR_SIGNIFICANT_POSITIVE_CANDIDATE",
                warning_message="当前没有通过FDR校正的正向节奏候选。",
                affected_count=0,
            )
        )
    warnings.append(
        TrendOptionTimingWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93B_POLICY_CONTEXT_NOT_CONNECTED",
            warning_message="政策与宏观事件日历尚未接入，本轮只使用波动环境代理。",
            affected_count=0,
            human_review_required=("policy_event_context_not_connected",),
        )
    )
    return warnings


def _write_outputs(
    *,
    result: TrendOptionTimingResult,
    independent_events: pd.DataFrame,
    summary: pd.DataFrame,
    ranking: pd.DataFrame,
    current_context: dict[str, object],
    input_paths: tuple[Path, ...],
    parameters: dict[str, object],
) -> None:
    for path, frame in (
        (result.event_feature_path, independent_events),
        (result.summary_path, summary),
        (result.ranking_path, ranking),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    _write_warning_csv(result.warning_csv_path, result.warning_records)
    payload = {
        **result.to_summary(),
        "rule_version": TREND_OPTION_TIMING_VERSION,
        "parameters": parameters,
        "current_context": current_context,
        "baseline_summary": [
            _json_safe(row)
            for row in summary.loc[summary["feature_name"].eq("ALL")].to_dict(
                orient="records"
            )
        ],
        "top_ranked_groups": [
            _json_safe(row) for row in ranking.head(30).to_dict(orient="records")
        ],
        "historical_returns_are_posterior_labels": True,
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
            summary=summary,
            ranking=ranking,
            current_context=current_context,
            parameters=parameters,
        ),
        encoding="utf-8",
    )
    artifacts = (
        result.event_feature_path,
        result.summary_path,
        result.ranking_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        **result.to_summary(),
        "rule_version": TREND_OPTION_TIMING_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "parameters": parameters,
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "historical_returns_are_posterior_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: TrendOptionTimingResult,
    summary: pd.DataFrame,
    ranking: pd.DataFrame,
    current_context: dict[str, object],
    parameters: dict[str, object],
) -> str:
    lines = [
        f"# CF 趋势环境与期权节奏增量研究 - {result.end}",
        "",
        "## 数据状态",
        "",
        f"- 日度状态区间：`{result.start}` 至 `{result.end}`",
        f"- 可用事件标签区间：`{result.event_sample_start}` 至 "
        f"`{result.event_sample_end}`",
        f"- 独立事件-周期行：`{result.independent_event_rows}`",
        f"- 独立趋势episode：`{result.independent_episode_count}`",
        f"- 检验分组：`{result.tested_group_count}`",
        f"- FDR正向候选：`{result.positive_candidate_count}`",
        f"- FDR负向过滤项：`{result.negative_filter_count}`",
        f"- 参数：`{json.dumps(parameters, ensure_ascii=False, sort_keys=True)}`",
        "",
        "## 数据告警",
        "",
    ]
    material_warnings = [
        warning for warning in result.warning_records if warning.severity == WARN
    ]
    if material_warnings:
        for warning in material_warnings:
            lines.append(
                f"- `{warning.warning_code}`：{warning.warning_message}"
                f"（影响 `{warning.affected_count}` 行）"
            )
    else:
        lines.append("- 无 WARN 级数据告警。")
    lines.extend(
        [
            "",
            "## 检验口径",
            "",
            "- 每个趋势episode、每个周期只保留首次突破，避免同一趋势重复突破伪增样本。",
            "- 每个结构分组与同周期其余独立episode比较，使用Fisher精确检验；"
            "全部分组统一做Benjamini-Hochberg FDR校正。",
            "- 二项检验仅描述绝对延续率是否偏离50%，不再冒充结构增量证据。",
            "",
            "## 基准突破表现",
            "",
            "| 周期 | 独立episode | 延续率 | 95%区间 | 平均方向收益 |",
            "| ---: | ---: | ---: | --- | ---: |",
        ]
    )
    baseline = summary.loc[summary["feature_name"].eq("ALL")]
    for row in baseline.itertuples(index=False):
        lines.append(
            f"| {int(row.horizon)}D | {int(row.sample_count)} | "
            f"{float(row.hit_rate):.2%} | [{float(row.hit_rate_ci_lower):.2%}, "
            f"{float(row.hit_rate_ci_upper):.2%}] | "
            f"{float(row.mean_directional_return):.2%} |"
        )
    lines.extend(["", "## 研究判断", ""])
    lines.extend(_research_conclusion_lines(summary))
    lines.extend(
        [
            "",
            "## 最强未校正线索",
            "",
            "| 特征 | 状态 | 周期 | 分组/对照 | 命中差 | 收益差 | 原始p值 | q值 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    raw_leads = (
        ranking.loc[
            ranking["sample_count"].ge(10)
            & ranking["comparison_sample_count"].ge(10)
        ]
        .sort_values(["incremental_exact_p_value", "feature_name", "feature_value"])
        .head(12)
    )
    for row in raw_leads.itertuples(index=False):
        lines.append(
            f"| {row.feature_name} | {row.feature_value} | {int(row.horizon)}D | "
            f"{int(row.sample_count)}/{int(row.comparison_sample_count)} | "
            f"{float(row.delta_hit_rate):+.2%} | "
            f"{float(row.delta_mean_directional_return):+.2%} | "
            f"{float(row.incremental_exact_p_value):.3f} | "
            f"{float(row.fdr_q_value):.3f} |"
        )
    lines.extend(
        [
            "",
            "## 增量检验排名",
            "",
            "| 特征 | 状态 | 周期 | 分组/对照 | 分组命中 | 命中差 | 收益差 | q值 | 结论 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    visible = ranking.loc[ranking["sample_count"].ge(10)].head(30)
    for row in visible.itertuples(index=False):
        lines.append(
            f"| {row.feature_name} | {row.feature_value} | {int(row.horizon)}D | "
            f"{int(row.sample_count)}/{int(row.comparison_sample_count)} | "
            f"{float(row.hit_rate):.2%} | {float(row.delta_hit_rate):+.2%} | "
            f"{float(row.delta_mean_directional_return):+.2%} | "
            f"{float(row.fdr_q_value):.3f} | {row.incremental_status} |"
        )
    lines.extend(
        [
            "",
            "## 当前结构",
            "",
            f"- 日期：`{current_context.get('trade_date')}`",
            f"- 方向/阶段：`{current_context.get('trend_direction')}` / "
            f"`{current_context.get('trend_stage')}`",
            f"- 波动环境：`{current_context.get('volatility_regime')}`",
            f"- 趋势力度：`{current_context.get('trend_strength_bucket')}`",
            f"- IV变化：`{current_context.get('iv_change_bucket')}`",
            f"- skew相对趋势：`{current_context.get('skew_trend_alignment')}`",
            f"- PCR OI相对趋势：`{current_context.get('pcr_oi_trend_alignment')}`",
            f"- 方向侧OI墙：`{current_context.get('directional_wall_bucket')}`",
            f"- OI墙持仓变化：`{current_context.get('directional_wall_oi_state')}`",
            f"- OI墙迁移：`{current_context.get('directional_wall_migration')}`",
            "- 当前结构不读取事件后收益。",
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- q值通过只代表候选研究线索，仍需年度稳定性、消融和滚动样本外验证。",
            "- OI墙是公开持仓聚合代理，不能据此推断做市商净Gamma方向。",
            "- 本模块不定义仓位，不替换CF_tsmom_v0，不解锁R94-R99。",
            f"- HUMAN_REVIEW_REQUIRED：`{';'.join(HUMAN_REVIEW_REQUIRED)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _research_conclusion_lines(summary: pd.DataFrame) -> list[str]:
    tested = summary.loc[summary["fdr_q_value"].notna()].copy()
    positive_count = int(tested["incremental_status"].eq("POSITIVE_CANDIDATE").sum())
    negative_count = int(tested["incremental_status"].eq("NEGATIVE_FILTER").sum())
    minimum_q = float(tested["fdr_q_value"].min())
    lines = [
        f"- FDR校正后正向候选 `{positive_count}` 个、负向过滤项 `{negative_count}` 个；"
        f"最小 q 值为 `{minimum_q:.3f}`。",
    ]
    if positive_count == 0 and negative_count == 0:
        lines.append(
            "- 当前没有证据支持把任何期权或OI墙结构直接升级为趋势仓位规则。"
        )

    lead_specs: tuple[tuple[str, set[str], str | None], ...] = (
        (
            "期权方向与波动",
            {
                "iv_level_regime",
                "iv_change_bucket",
                "skew_trend_alignment",
                "pcr_oi_trend_alignment",
                "option_alignment",
            },
            None,
        ),
        ("持仓参与确认", {"participation_alignment"}, "positive"),
        (
            "OI墙动态",
            {"directional_wall_oi_state", "directional_wall_migration"},
            None,
        ),
    )
    for label, features, preferred_sign in lead_specs:
        candidates = tested.loc[
            tested["feature_name"].isin(features)
            & tested["sample_count"].ge(10)
            & tested["comparison_sample_count"].ge(10)
            & (
                tested["delta_hit_rate"]
                * tested["delta_mean_directional_return"]
            ).gt(0)
        ].copy()
        if preferred_sign == "positive":
            candidates = candidates.loc[candidates["delta_hit_rate"].gt(0)]
        if candidates.empty:
            continue
        row = candidates.sort_values(
            ["incremental_exact_p_value", "feature_name", "feature_value"]
        ).iloc[0]
        sign_label = "正向" if float(row["delta_hit_rate"]) > 0 else "负向"
        lines.append(
            f"- {label}最强原始线索为 `{row['feature_name']}="
            f"{row['feature_value']}` 的 {int(row['horizon'])}D {sign_label}差异："
            f"样本/对照 `{int(row['sample_count'])}/"
            f"{int(row['comparison_sample_count'])}`，命中差 "
            f"`{float(row['delta_hit_rate']):+.2%}`，收益差 "
            f"`{float(row['delta_mean_directional_return']):+.2%}`，"
            f"原始 p=`{float(row['incremental_exact_p_value']):.3f}`、"
            f"q=`{float(row['fdr_q_value']):.3f}`。"
        )
    lines.append(
        "- 上述原始线索只能用于下一轮预登记消融和滚动样本外检验，不能回写当前策略。"
    )
    return lines


def _rolling_percentile_rank(
    series: pd.Series,
    *,
    window: int,
    min_periods: int,
) -> pd.Series:
    def rank_last(values: np.ndarray) -> float:
        current = values[-1]
        valid = values[np.isfinite(values)]
        if not math.isfinite(current) or len(valid) < min_periods:
            return math.nan
        return float((valid <= current).mean())

    return series.rolling(window, min_periods=min_periods).apply(rank_last, raw=True)


def _three_way_rank_bucket(
    value: object,
    low_label: str,
    mid_label: str,
    high_label: str,
) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "MISSING"
    if number <= 0.25:
        return low_label
    if number >= 0.75:
        return high_label
    return mid_label


def _strength_bucket(value: object) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "MISSING"
    if number < 0.4:
        return "LOW_STRENGTH"
    if number >= 0.6:
        return "HIGH_STRENGTH"
    return "MID_STRENGTH"


def _iv_level_bucket(value: object) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "MISSING"
    if number <= 0.2:
        return "LOW_IV_RANK"
    if number >= 0.8:
        return "HIGH_IV_RANK"
    return "MID_IV_RANK"


def _directional_change_alignment(
    *,
    direction: object,
    bucket: object,
    down_bucket: str,
    stable_bucket: str,
    up_bucket: str,
) -> str:
    direction_value = str(direction)
    bucket_value = str(bucket)
    if direction_value not in {"long", "short"} or bucket_value == "MISSING":
        return "MISSING"
    if bucket_value == stable_bucket:
        return "NEUTRAL_TO_TREND"
    supports = (
        direction_value == "long" and bucket_value == down_bucket
    ) or (
        direction_value == "short" and bucket_value == up_bucket
    )
    if bucket_value not in {down_bucket, up_bucket}:
        return "MISSING"
    return "SUPPORTS_TREND" if supports else "OPPOSES_TREND"


def _directional_wall_metrics(row: pd.Series) -> pd.Series:
    direction = str(row["trend_direction"])
    if direction == "long":
        distance = _finite_or_none(row.get("distance_to_call_wall"))
        oi_change = _finite_or_none(row.get("call_wall_oi_change"))
        shift = _finite_or_none(row.get("call_wall_strike_shift_1d"))
    elif direction == "short":
        raw_distance = _finite_or_none(row.get("distance_to_put_wall"))
        distance = None if raw_distance is None else -raw_distance
        oi_change = _finite_or_none(row.get("put_wall_oi_change"))
        raw_shift = _finite_or_none(row.get("put_wall_strike_shift_1d"))
        shift = None if raw_shift is None else -raw_shift
    else:
        distance = oi_change = shift = None
    return pd.Series([distance, oi_change, shift])


def _wall_distance_bucket(value: object) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "MISSING"
    if number < 0:
        return "CROSSED_DIRECTIONAL_WALL"
    if number <= 0.01:
        return "WITHIN_1PCT_WALL"
    if number <= 0.03:
        return "WITHIN_1_3PCT_WALL"
    return "BEYOND_3PCT_WALL"


def _wall_oi_state(value: object) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "MISSING"
    if number > 0:
        return "WALL_OI_BUILDING"
    if number < 0:
        return "WALL_OI_UNWINDING"
    return "WALL_OI_UNCHANGED"


def _wall_migration_bucket(value: object) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "MISSING"
    if number > 0:
        return "WALL_MOVED_WITH_TREND"
    if number < 0:
        return "WALL_MOVED_AGAINST_TREND"
    return "WALL_UNCHANGED"


def _wilson_interval(*, successes: int, sample_count: int) -> tuple[float, float]:
    if sample_count <= 0:
        return math.nan, math.nan
    z = 1.959963984540054
    rate = successes / sample_count
    denominator = 1 + z**2 / sample_count
    centre = (rate + z**2 / (2 * sample_count)) / denominator
    margin = (
        z
        * math.sqrt(
            rate * (1 - rate) / sample_count + z**2 / (4 * sample_count**2)
        )
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _exact_binomial_two_sided(successes: int, sample_count: int) -> float:
    lower_tail = min(successes, sample_count - successes)
    probability = sum(
        math.comb(sample_count, value) for value in range(lower_tail + 1)
    ) / (2**sample_count)
    return min(1.0, 2 * probability)


def _fisher_exact_two_sided(
    *,
    group_successes: int,
    group_count: int,
    comparison_successes: int,
    comparison_count: int,
) -> float:
    """比较结构分组与其余独立样本，避免把偏离50%误写成增量证据。"""
    if group_count <= 0 or comparison_count <= 0:
        return 1.0
    total = group_count + comparison_count
    total_successes = group_successes + comparison_successes
    observed_probability = _hypergeometric_probability(
        group_successes=group_successes,
        group_count=group_count,
        total_successes=total_successes,
        total_count=total,
    )
    minimum = max(0, group_count - (total - total_successes))
    maximum = min(group_count, total_successes)
    tolerance = 1e-12
    probability = 0.0
    for successes in range(minimum, maximum + 1):
        candidate = _hypergeometric_probability(
            group_successes=successes,
            group_count=group_count,
            total_successes=total_successes,
            total_count=total,
        )
        if candidate <= observed_probability + tolerance:
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


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    count = len(p_values)
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = count - reverse_rank + 1
        candidate = min(1.0, p_values[index] * count / rank)
        running = min(running, candidate)
        adjusted[index] = running
    return adjusted


def _current_context(latest: pd.Series) -> dict[str, object]:
    columns = (
        "trade_date",
        "main_contract",
        "option_underlying_contract",
        "option_selection_reason",
        "option_relay_used",
        "option_tenor_gap_months",
        "trend_direction",
        "trend_stage",
        "trend_strength",
        "volatility_regime",
        "trend_strength_bucket",
        "iv_level_regime",
        "iv_change_bucket",
        "skew_trend_alignment",
        "pcr_oi_trend_alignment",
        "directional_wall_bucket",
        "directional_wall_oi_state",
        "directional_wall_migration",
        "option_alignment",
        "participation_alignment",
        "roll_context",
    )
    return _json_safe({column: latest.get(column) for column in columns})


def _load_frame(path: Path, required: set[str], label: str) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"{label} path does not exist: {path}")
    frame = pd.read_parquet(path)
    missing = required.difference(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"{label} missing columns {sorted(missing)}: {path}")
    selected_columns = required | (OPTION_RELAY_COLUMNS & set(frame.columns))
    selected = frame[list(sorted(selected_columns))].copy()
    date_column = "event_date" if "event_date" in selected.columns else "trade_date"
    selected[date_column] = pd.to_datetime(
        selected[date_column], errors="coerce"
    ).dt.date
    if selected[date_column].isna().any():
        raise ResearchWorkbenchError(f"{label} contains invalid {date_column}: {path}")
    return selected


def _validate_parameters(
    *,
    rank_window: int,
    rank_min_periods: int,
    min_sample_size: int,
    fdr_level: float,
) -> None:
    if rank_window < 20:
        raise ResearchWorkbenchError("rank_window must be at least 20")
    if rank_min_periods < 10 or rank_min_periods > rank_window:
        raise ResearchWorkbenchError("rank_min_periods must be within [10, rank_window]")
    if min_sample_size < 1:
        raise ResearchWorkbenchError("min_sample_size must be positive")
    if not 0 < fdr_level < 1:
        raise ResearchWorkbenchError("fdr_level must be within (0, 1)")


def _comparison_sample_floor(min_sample_size: int) -> int:
    # 对照组使用精确检验，可小于候选组门槛，但至少保留10个独立episode。
    return max(10, min_sample_size // 3)


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "trend_option_timing"
    report_root = report_output_dir or reports_dir() / "research" / "trend_option_timing"
    stem = f"CF_{start}_{end}_trend_option_timing"
    return {
        "events": data_root / f"{stem}_independent_event_feature.parquet",
        "summary": data_root / f"{stem}_incremental_summary.parquet",
        "ranking": data_root / f"{stem}_incremental_ranking.parquet",
        "warnings": data_root / f"{stem}_warnings.csv",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
        "manifest": data_root / f"{stem}_manifest.json",
    }


def _write_warning_csv(
    path: Path,
    warnings: tuple[TrendOptionTimingWarningRecord, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for warning in warnings:
            writer.writerow(warning.to_csv_row())


def _latest_symmetric_trend_daily_path() -> Path:
    return _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "symmetric_trend",
        "*_symmetric_trend_daily.parquet",
        "R93A symmetric trend daily",
    )


def _latest_breakout_event_path() -> Path:
    return _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "symmetric_trend",
        "*_symmetric_trend_breakout_event_horizon.parquet",
        "R93A breakout event",
    )


def _latest_option_structure_path() -> Path:
    return _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "option_structure",
        "*_option_structure_daily.parquet",
        "R75 option structure",
    )


def _latest_strike_position_path() -> Path:
    return _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "option_strike_position",
        "*_option_strike_position_daily.parquet",
        "R84 strike position",
    )


def _latest_path(root: Path, pattern: str, label: str) -> Path:
    paths = sorted(root.glob(pattern))
    if not paths:
        raise ResearchWorkbenchError(f"{label} not found under {root}")
    return paths[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(*, start: date, end: date) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cf_trend_option_timing_{start:%Y%m%d}_{end:%Y%m%d}_{stamp}_{uuid.uuid4().hex[:8]}"
