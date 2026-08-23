"""R93M 期权市场成熟度与趋势确认检查点研究。"""

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
RULE_VERSION = "V5.1_R93M_option_maturity_confirmation_v1"
DEFAULT_HORIZONS = (5, 20)
DEFAULT_CHECKPOINTS = (0, 1, 3, 5, 10)
DEFAULT_CONFIRMATION_DAYS = 2
DEFAULT_ACTIVITY_WINDOW = 60
DEFAULT_ACTIVITY_MIN_PERIODS = 20
DEFAULT_BASELINE_YEAR = 2021
DEFAULT_EXPANSION_VOLUME_RATIO = 1.50
DEFAULT_EXPANSION_OI_RATIO = 1.25
DEFAULT_MATURE_VOLUME_RATIO = 3.00
DEFAULT_MATURE_OI_RATIO = 2.50
DEFAULT_MIN_SAMPLE_SIZE = 5
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_DEAD_ZONE_BPS = 10
INFO = "INFO"
WARN = "WARN"
RESEARCH_BOUNDARY = (
    "期权市场阶段用于分层历史证据；检查点特征只使用对应T+k日及以前轨迹，"
    "检查点后的价格只进入物理分离的历史后验验证表。R93M不修改signal matrix、"
    "composite_score、策略方向或仓位，不构成交易指令。"
)
HUMAN_REVIEW_REQUIRED = (
    "option_market_stage_boundaries",
    "activity_ratio_thresholds",
    "activity_trailing_window",
    "checkpoint_sessions",
    "option_confirmation_days",
    "option_volume_and_open_interest_units",
)
OPTION_CORE_COLUMNS = {
    "trade_date",
    "option_symbol",
    "underlying_contract",
    "volume",
    "open_interest",
    "liquidity_flag",
}
EVENT_COLUMNS = {
    "event_id",
    "event_date",
    "direction",
    "direction_episode_id",
}
TRAJECTORY_COLUMNS = {
    "event_id",
    "event_date",
    "direction",
    "relative_session",
    "state_date",
    "adjusted_price",
    "option_confirmation_flag",
    "futures_confirmation_flag",
    "option_factor_status",
    "option_liquidity_score",
}
WARNING_COLUMNS = (
    "run_id",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)


@dataclass(frozen=True)
class OptionMaturityConfirmationWarningRecord:
    """R93M警告与人工复核记录。"""

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
class OptionMaturityConfirmationResult:
    """R93M产物与阶段研究摘要。"""

    run_id: str
    start: date
    end: date
    event_sample_start: date
    event_sample_end: date
    status: str
    event_count: int
    checkpoint_feature_count: int
    checkpoint_validation_count: int
    early_event_count: int
    expansion_event_count: int
    mature_event_count: int
    significant_positive_count: int
    significant_negative_count: int
    latest_event_stage: str
    latest_event_activity_state: str
    activity_daily_path: Path
    activity_annual_path: Path
    checkpoint_feature_path: Path
    checkpoint_validation_path: Path
    stage_summary_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[OptionMaturityConfirmationWarningRecord, ...]

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
            "checkpoint_feature_count": self.checkpoint_feature_count,
            "checkpoint_validation_count": self.checkpoint_validation_count,
            "early_event_count": self.early_event_count,
            "expansion_event_count": self.expansion_event_count,
            "mature_event_count": self.mature_event_count,
            "significant_positive_count": self.significant_positive_count,
            "significant_negative_count": self.significant_negative_count,
            "latest_event_stage": self.latest_event_stage,
            "latest_event_activity_state": self.latest_event_activity_state,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "activity_daily_path": str(self.activity_daily_path),
            "activity_annual_path": str(self.activity_annual_path),
            "checkpoint_feature_path": str(self.checkpoint_feature_path),
            "checkpoint_validation_path": str(self.checkpoint_validation_path),
            "stage_summary_path": str(self.stage_summary_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "historical_returns_are_posterior_labels": True,
            "checkpoint_features_are_asof_safe": True,
            "promotion_eligible": False,
            "realtime_rule_eligible": False,
            "enters_composite_score": False,
            "trading_instruction": "not_a_trading_instruction",
            "research_boundary": RESEARCH_BOUNDARY,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_option_maturity_confirmation_research(
    *,
    option_core_path: Path | None = None,
    trend_confirmation_event_path: Path | None = None,
    trend_confirmation_trajectory_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    checkpoints: tuple[int, ...] = DEFAULT_CHECKPOINTS,
    confirmation_days: int = DEFAULT_CONFIRMATION_DAYS,
    activity_window: int = DEFAULT_ACTIVITY_WINDOW,
    activity_min_periods: int = DEFAULT_ACTIVITY_MIN_PERIODS,
    baseline_year: int = DEFAULT_BASELINE_YEAR,
    expansion_volume_ratio: float = DEFAULT_EXPANSION_VOLUME_RATIO,
    expansion_oi_ratio: float = DEFAULT_EXPANSION_OI_RATIO,
    mature_volume_ratio: float = DEFAULT_MATURE_VOLUME_RATIO,
    mature_oi_ratio: float = DEFAULT_MATURE_OI_RATIO,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
) -> OptionMaturityConfirmationResult:
    """构建期权市场阶段及可知检查点的趋势确认研究。"""
    normalized_horizons = _positive_int_tuple(horizons, "horizons")
    normalized_checkpoints = _nonnegative_int_tuple(checkpoints, "checkpoints")
    _validate_parameters(
        horizons=normalized_horizons,
        checkpoints=normalized_checkpoints,
        confirmation_days=confirmation_days,
        activity_window=activity_window,
        activity_min_periods=activity_min_periods,
        expansion_volume_ratio=expansion_volume_ratio,
        expansion_oi_ratio=expansion_oi_ratio,
        mature_volume_ratio=mature_volume_ratio,
        mature_oi_ratio=mature_oi_ratio,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        dead_zone_bps=dead_zone_bps,
    )
    core_path = (
        option_core_path
        or data_dir() / "core" / PRODUCT_CODE / "core_option_quote_daily.parquet"
    )
    event_path = trend_confirmation_event_path or _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "trend_confirmation_timing",
        "*_trend_confirmation_timing_event_index.parquet",
        "R93L事件索引",
    )
    trajectory_path = trend_confirmation_trajectory_path or _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "trend_confirmation_timing",
        "*_trend_confirmation_timing_trajectory_daily.parquet",
        "R93L事件轨迹",
    )
    option_core = _load_frame(core_path, OPTION_CORE_COLUMNS, "CF期权core")
    events = _load_frame(event_path, EVENT_COLUMNS, "R93L事件索引")
    trajectory = _load_frame(trajectory_path, TRAJECTORY_COLUMNS, "R93L事件轨迹")
    _validate_label_columns(events, normalized_horizons)
    active_run_id = run_id or _default_run_id()

    activity_daily, baseline = _build_activity_daily(
        option_core,
        activity_window=activity_window,
        activity_min_periods=activity_min_periods,
        baseline_year=baseline_year,
        expansion_volume_ratio=expansion_volume_ratio,
        expansion_oi_ratio=expansion_oi_ratio,
        mature_volume_ratio=mature_volume_ratio,
        mature_oi_ratio=mature_oi_ratio,
        run_id=active_run_id,
    )
    activity_annual = _build_activity_annual(
        activity_daily=activity_daily,
        baseline=baseline,
        run_id=active_run_id,
    )
    checkpoint_features = _build_checkpoint_features(
        events=events,
        trajectory=trajectory,
        activity_daily=activity_daily,
        checkpoints=normalized_checkpoints,
        confirmation_days=confirmation_days,
        run_id=active_run_id,
    )
    checkpoint_validation = _build_checkpoint_validation(
        events=events,
        trajectory=trajectory,
        features=checkpoint_features,
        horizons=normalized_horizons,
        dead_zone_bps=dead_zone_bps,
        run_id=active_run_id,
    )
    stage_summary = _build_stage_summary(
        checkpoint_validation,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
    )
    warnings = tuple(
        _warning_records(
            run_id=active_run_id,
            activity_daily=activity_daily,
            features=checkpoint_features,
            summary=stage_summary,
            baseline_year=baseline_year,
            min_sample_size=min_sample_size,
        )
    )
    paths = _output_paths(
        start=activity_daily["trade_date"].min(),
        end=activity_daily["trade_date"].max(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    event_stage = checkpoint_features.loc[
        checkpoint_features["checkpoint_session"].eq(0),
        ["event_id", "event_date", "option_market_stage", "data_activity_state"],
    ].drop_duplicates("event_id")
    latest = event_stage.sort_values(["event_date", "event_id"]).iloc[-1]
    stage_counts = event_stage["option_market_stage"].value_counts()
    result = OptionMaturityConfirmationResult(
        run_id=active_run_id,
        start=activity_daily["trade_date"].min(),
        end=activity_daily["trade_date"].max(),
        event_sample_start=event_stage["event_date"].min(),
        event_sample_end=event_stage["event_date"].max(),
        status=(
            "OPTION_MATURITY_CONFIRMATION_READY_WITH_WARNINGS"
            if any(item.severity == WARN for item in warnings)
            else "OPTION_MATURITY_CONFIRMATION_READY"
        ),
        event_count=len(event_stage),
        checkpoint_feature_count=len(checkpoint_features),
        checkpoint_validation_count=len(checkpoint_validation),
        early_event_count=int(stage_counts.get("EARLY_THIN", 0)),
        expansion_event_count=int(stage_counts.get("EXPANSION", 0)),
        mature_event_count=int(stage_counts.get("MATURE_ACTIVE", 0)),
        significant_positive_count=int(
            stage_summary["evidence_status"].eq("STAGE_HYPOTHESIS_POSITIVE").sum()
        ),
        significant_negative_count=int(
            stage_summary["evidence_status"].eq("STAGE_HYPOTHESIS_NEGATIVE").sum()
        ),
        latest_event_stage=str(latest["option_market_stage"]),
        latest_event_activity_state=str(latest["data_activity_state"]),
        activity_daily_path=paths["activity_daily"],
        activity_annual_path=paths["activity_annual"],
        checkpoint_feature_path=paths["checkpoint_feature"],
        checkpoint_validation_path=paths["checkpoint_validation"],
        stage_summary_path=paths["stage_summary"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=warnings,
    )
    _write_outputs(
        result=result,
        activity_daily=activity_daily,
        activity_annual=activity_annual,
        checkpoint_features=checkpoint_features,
        checkpoint_validation=checkpoint_validation,
        stage_summary=stage_summary,
        input_paths=(core_path, event_path, trajectory_path),
        parameters={
            "horizons": list(normalized_horizons),
            "checkpoints": list(normalized_checkpoints),
            "confirmation_days": confirmation_days,
            "activity_window": activity_window,
            "activity_min_periods": activity_min_periods,
            "baseline_year": baseline_year,
            "expansion_volume_ratio": expansion_volume_ratio,
            "expansion_oi_ratio": expansion_oi_ratio,
            "mature_volume_ratio": mature_volume_ratio,
            "mature_oi_ratio": mature_oi_ratio,
            "min_sample_size": min_sample_size,
            "fdr_level": fdr_level,
            "dead_zone_bps": dead_zone_bps,
        },
    )
    return result


def _build_activity_daily(
    option_core: pd.DataFrame,
    *,
    activity_window: int,
    activity_min_periods: int,
    baseline_year: int,
    expansion_volume_ratio: float,
    expansion_oi_ratio: float,
    mature_volume_ratio: float,
    mature_oi_ratio: float,
    run_id: str,
) -> tuple[pd.DataFrame, dict[str, float]]:
    working = option_core.copy()
    if working.duplicated(["trade_date", "option_symbol"]).any():
        raise ResearchWorkbenchError("CF期权core存在重复交易日-合约记录")
    working["volume"] = pd.to_numeric(working["volume"], errors="coerce")
    working["open_interest"] = pd.to_numeric(
        working["open_interest"], errors="coerce"
    )
    if working[["volume", "open_interest"]].isna().any().any():
        raise ResearchWorkbenchError("CF期权core成交量或持仓量存在空值")
    if (working[["volume", "open_interest"]] < 0).any().any():
        raise ResearchWorkbenchError("CF期权core成交量或持仓量存在负值")
    working["active_volume_flag"] = working["volume"].gt(0)
    working["active_oi_flag"] = working["open_interest"].gt(0)
    working["normal_liquidity_flag"] = working["liquidity_flag"].eq(
        "normal_liquidity"
    )
    daily = (
        working.groupby("trade_date", sort=True)
        .agg(
            total_option_volume=("volume", "sum"),
            total_option_open_interest=("open_interest", "sum"),
            listed_option_count=("option_symbol", "nunique"),
            active_volume_contract_count=("active_volume_flag", "sum"),
            active_oi_contract_count=("active_oi_flag", "sum"),
            normal_liquidity_contract_count=("normal_liquidity_flag", "sum"),
            underlying_contract_count=("underlying_contract", "nunique"),
        )
        .reset_index()
        .sort_values("trade_date")
        .reset_index(drop=True)
    )
    daily["calendar_year"] = daily["trade_date"].map(lambda value: value.year)
    baseline_rows = daily.loc[daily["calendar_year"].eq(baseline_year)]
    if len(baseline_rows) < activity_min_periods:
        raise ResearchWorkbenchError(
            f"R93M基准年度{baseline_year}期权交易日不足: {len(baseline_rows)}"
        )
    baseline = {
        "median_daily_volume": float(baseline_rows["total_option_volume"].median()),
        "median_daily_open_interest": float(
            baseline_rows["total_option_open_interest"].median()
        ),
        "median_active_volume_contracts": float(
            baseline_rows["active_volume_contract_count"].median()
        ),
        "median_active_oi_contracts": float(
            baseline_rows["active_oi_contract_count"].median()
        ),
    }
    if baseline["median_daily_volume"] <= 0 or baseline["median_daily_open_interest"] <= 0:
        raise ResearchWorkbenchError("R93M基准年度期权成交或持仓中位数无效")

    # 所有活跃度特征只使用截至T日的尾部窗口，不使用未来交易日。
    daily["trailing_volume_median"] = daily["total_option_volume"].rolling(
        activity_window, min_periods=activity_min_periods
    ).median()
    daily["trailing_open_interest_median"] = daily[
        "total_option_open_interest"
    ].rolling(activity_window, min_periods=activity_min_periods).median()
    daily["trailing_active_volume_contract_median"] = daily[
        "active_volume_contract_count"
    ].rolling(activity_window, min_periods=activity_min_periods).median()
    daily["trailing_active_oi_contract_median"] = daily[
        "active_oi_contract_count"
    ].rolling(activity_window, min_periods=activity_min_periods).median()
    daily["trailing_volume_vs_2021"] = (
        daily["trailing_volume_median"] / baseline["median_daily_volume"]
    )
    daily["trailing_oi_vs_2021"] = (
        daily["trailing_open_interest_median"]
        / baseline["median_daily_open_interest"]
    )
    daily["option_market_stage"] = daily["trade_date"].map(_calendar_market_stage)
    daily["data_activity_state"] = daily.apply(
        lambda row: _activity_state(
            year=int(row["calendar_year"]),
            baseline_year=baseline_year,
            volume_ratio=row["trailing_volume_vs_2021"],
            oi_ratio=row["trailing_oi_vs_2021"],
            expansion_volume_ratio=expansion_volume_ratio,
            expansion_oi_ratio=expansion_oi_ratio,
            mature_volume_ratio=mature_volume_ratio,
            mature_oi_ratio=mature_oi_ratio,
        ),
        axis=1,
    )
    daily["stage_activity_alignment"] = daily.apply(
        lambda row: _stage_activity_alignment(
            market_stage=str(row["option_market_stage"]),
            activity_state=str(row["data_activity_state"]),
        ),
        axis=1,
    )
    daily["activity_features_use_t_or_earlier"] = True
    daily["baseline_uses_complete_2021_history"] = daily["calendar_year"].eq(
        baseline_year
    )
    daily["run_id"] = run_id
    daily["rule_version"] = RULE_VERSION
    daily["enters_composite_score"] = False
    daily["trading_instruction"] = "not_a_trading_instruction"
    return daily, baseline


def _build_activity_annual(
    *,
    activity_daily: pd.DataFrame,
    baseline: dict[str, float],
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, group in activity_daily.groupby("calendar_year", sort=True):
        median_volume = float(group["total_option_volume"].median())
        median_oi = float(group["total_option_open_interest"].median())
        rows.append(
            {
                "run_id": run_id,
                "calendar_year": int(year),
                "option_market_stage": _calendar_market_stage(
                    date(int(year), 1, 1)
                ),
                "trading_day_count": len(group),
                "median_daily_volume": median_volume,
                "mean_daily_volume": float(group["total_option_volume"].mean()),
                "median_daily_open_interest": median_oi,
                "mean_daily_open_interest": float(
                    group["total_option_open_interest"].mean()
                ),
                "median_listed_option_count": float(
                    group["listed_option_count"].median()
                ),
                "median_active_volume_contract_count": float(
                    group["active_volume_contract_count"].median()
                ),
                "median_active_oi_contract_count": float(
                    group["active_oi_contract_count"].median()
                ),
                "median_daily_volume_vs_2021": (
                    median_volume / baseline["median_daily_volume"]
                ),
                "median_daily_oi_vs_2021": (
                    median_oi / baseline["median_daily_open_interest"]
                ),
                "mature_activity_day_rate": float(
                    group["data_activity_state"].eq("MATURE_ACTIVE").mean()
                ),
                "expansion_activity_day_rate": float(
                    group["data_activity_state"].eq("EXPANSION").mean()
                ),
                "rule_version": RULE_VERSION,
            }
        )
    return pd.DataFrame(rows).sort_values("calendar_year").reset_index(drop=True)


def _build_checkpoint_features(
    *,
    events: pd.DataFrame,
    trajectory: pd.DataFrame,
    activity_daily: pd.DataFrame,
    checkpoints: tuple[int, ...],
    confirmation_days: int,
    run_id: str,
) -> pd.DataFrame:
    if events["event_id"].duplicated().any():
        raise ResearchWorkbenchError("R93M要求R93L事件索引每个episode唯一")
    activity = activity_daily.set_index("trade_date")
    trajectory_groups = {
        str(event_id): group.sort_values("relative_session")
        for event_id, group in trajectory.groupby("event_id", sort=False)
    }
    rows: list[dict[str, object]] = []
    for event in events.itertuples(index=False):
        event_id = str(event.event_id)
        if event_id not in trajectory_groups:
            raise ResearchWorkbenchError(f"R93M缺少事件轨迹: {event_id}")
        if event.event_date not in activity.index:
            raise ResearchWorkbenchError(f"R93M事件日缺少期权活跃度: {event.event_date}")
        market = activity.loc[event.event_date]
        path = trajectory_groups[event_id]
        if path["relative_session"].duplicated().any():
            raise ResearchWorkbenchError(f"R93M事件轨迹相对交易日重复: {event_id}")
        for checkpoint in checkpoints:
            checkpoint_row = path.loc[path["relative_session"].eq(checkpoint)]
            if checkpoint_row.empty:
                continue
            visible = path.loc[path["relative_session"].le(checkpoint)]
            option_completion = _first_confirmation_session(
                visible,
                flag_column="option_confirmation_flag",
                confirmation_days=confirmation_days,
            )
            participation_completion = _first_confirmation_session(
                visible,
                flag_column="futures_confirmation_flag",
                confirmation_days=confirmation_days,
            )
            current = checkpoint_row.iloc[0]
            rows.append(
                {
                    "run_id": run_id,
                    "event_id": event_id,
                    "event_date": event.event_date,
                    "event_year": event.event_date.year,
                    "direction": str(event.direction),
                    "direction_episode_id": str(event.direction_episode_id),
                    "checkpoint_session": checkpoint,
                    "feature_asof_date": current["state_date"],
                    "option_market_stage": market["option_market_stage"],
                    "data_activity_state": market["data_activity_state"],
                    "stage_activity_alignment": market["stage_activity_alignment"],
                    "event_total_option_volume": market["total_option_volume"],
                    "event_total_option_open_interest": market[
                        "total_option_open_interest"
                    ],
                    "event_trailing_volume_vs_2021": market[
                        "trailing_volume_vs_2021"
                    ],
                    "event_trailing_oi_vs_2021": market["trailing_oi_vs_2021"],
                    "option_confirmed_by_checkpoint": option_completion is not None,
                    "option_confirmation_session": option_completion,
                    "participation_confirmed_by_checkpoint": (
                        participation_completion is not None
                    ),
                    "participation_confirmation_session": participation_completion,
                    "joint_confirmed_by_checkpoint": (
                        option_completion is not None
                        and participation_completion is not None
                    ),
                    "option_current_streak": _trailing_true_streak(
                        visible["option_confirmation_flag"]
                    ),
                    "participation_current_streak": _trailing_true_streak(
                        visible["futures_confirmation_flag"]
                    ),
                    "checkpoint_adjusted_price": float(current["adjusted_price"]),
                    "checkpoint_option_factor_status": str(
                        current["option_factor_status"]
                    ),
                    "checkpoint_option_liquidity_score": _float_or_nan(
                        current["option_liquidity_score"]
                    ),
                    "features_use_checkpoint_or_earlier": True,
                    "contains_posterior_outcome": False,
                    "promotion_eligible": False,
                    "rule_version": RULE_VERSION,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    if not rows:
        raise ResearchWorkbenchError("R93M没有可用的事件检查点特征")
    output = pd.DataFrame(rows).sort_values(
        ["event_date", "event_id", "checkpoint_session"]
    ).reset_index(drop=True)
    if output.duplicated(["event_id", "checkpoint_session"]).any():
        raise ResearchWorkbenchError("R93M检查点特征存在重复episode-检查点")
    return output


def _build_checkpoint_validation(
    *,
    events: pd.DataFrame,
    trajectory: pd.DataFrame,
    features: pd.DataFrame,
    horizons: tuple[int, ...],
    dead_zone_bps: int,
    run_id: str,
) -> pd.DataFrame:
    event_lookup = events.set_index("event_id")
    path_lookup = {
        str(event_id): group.set_index("relative_session")
        for event_id, group in trajectory.groupby("event_id", sort=False)
    }
    dead_zone = dead_zone_bps / 10_000.0
    rows: list[dict[str, object]] = []
    for feature in features.itertuples(index=False):
        event = event_lookup.loc[feature.event_id]
        path = path_lookup[feature.event_id]
        for horizon in horizons:
            if feature.checkpoint_session >= horizon:
                continue
            available_column = f"label_available_{horizon}d"
            if not _bool_value(event[available_column]):
                continue
            if feature.checkpoint_session not in path.index or horizon not in path.index:
                continue
            checkpoint_price = float(path.loc[feature.checkpoint_session, "adjusted_price"])
            exit_price = float(path.loc[horizon, "adjusted_price"])
            direction_sign = 1 if feature.direction == "long" else -1
            remaining_return = direction_sign * (exit_price / checkpoint_price - 1.0)
            if remaining_return > dead_zone:
                remaining_outcome = "FOLLOW_THROUGH"
            elif remaining_return < -dead_zone:
                remaining_outcome = "FAILED_BREAKOUT"
            else:
                remaining_outcome = "UNRESOLVED"
            rows.append(
                {
                    "run_id": run_id,
                    "event_id": feature.event_id,
                    "event_date": feature.event_date,
                    "event_year": feature.event_year,
                    "direction": feature.direction,
                    "direction_episode_id": feature.direction_episode_id,
                    "checkpoint_session": feature.checkpoint_session,
                    "feature_asof_date": feature.feature_asof_date,
                    "horizon": horizon,
                    "option_market_stage": feature.option_market_stage,
                    "data_activity_state": feature.data_activity_state,
                    "stage_activity_alignment": feature.stage_activity_alignment,
                    "option_confirmed_by_checkpoint": (
                        feature.option_confirmed_by_checkpoint
                    ),
                    "participation_confirmed_by_checkpoint": (
                        feature.participation_confirmed_by_checkpoint
                    ),
                    "joint_confirmed_by_checkpoint": (
                        feature.joint_confirmed_by_checkpoint
                    ),
                    "option_confirmation_group": (
                        "CONFIRMED_BY_CHECKPOINT"
                        if feature.option_confirmed_by_checkpoint
                        else "NOT_CONFIRMED_BY_CHECKPOINT"
                    ),
                    "checkpoint_adjusted_price": checkpoint_price,
                    "exit_adjusted_price": exit_price,
                    "remaining_directional_return": remaining_return,
                    "remaining_outcome": remaining_outcome,
                    "anchor_directional_return": _float_or_nan(
                        event[f"directional_return_{horizon}d"]
                    ),
                    "anchor_outcome": str(event[f"outcome_{horizon}d"]),
                    "historical_posterior_label": True,
                    "features_use_checkpoint_or_earlier": True,
                    "validation_uses_post_checkpoint_prices": True,
                    "promotion_eligible": False,
                    "rule_version": RULE_VERSION,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    if not rows:
        raise ResearchWorkbenchError("R93M没有成熟的检查点后验标签")
    output = pd.DataFrame(rows).sort_values(
        ["event_date", "event_id", "horizon", "checkpoint_session"]
    ).reset_index(drop=True)
    if output.duplicated(["event_id", "checkpoint_session", "horizon"]).any():
        raise ResearchWorkbenchError("R93M检查点验证存在重复episode-检查点-周期")
    return output


def _build_stage_summary(
    validation: pd.DataFrame,
    *,
    min_sample_size: int,
    fdr_level: float,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dimensions = (
        ("option_market_stage", "CALENDAR_STAGE"),
        ("data_activity_state", "TRAILING_ACTIVITY_STATE"),
    )
    for column, dimension in dimensions:
        for (segment, horizon, checkpoint), universe in validation.groupby(
            [column, "horizon", "checkpoint_session"], sort=True
        ):
            confirmed = universe.loc[universe["option_confirmed_by_checkpoint"]]
            not_confirmed = universe.loc[
                ~universe["option_confirmed_by_checkpoint"]
            ]
            confirmed_metrics = _validation_metrics(confirmed)
            control_metrics = _validation_metrics(not_confirmed)
            p_value = _fisher_exact_two_sided(
                group_successes=int(confirmed_metrics["success_count"]),
                group_count=int(confirmed_metrics["sample_count"]),
                comparison_successes=int(control_metrics["success_count"]),
                comparison_count=int(control_metrics["sample_count"]),
            )
            rows.append(
                {
                    "segmentation_dimension": dimension,
                    "market_segment": str(segment),
                    "horizon": int(horizon),
                    "checkpoint_session": int(checkpoint),
                    "confirmed_sample_count": confirmed_metrics["sample_count"],
                    "confirmed_success_count": confirmed_metrics["success_count"],
                    "confirmed_hit_rate": confirmed_metrics["hit_rate"],
                    "confirmed_mean_remaining_return": confirmed_metrics[
                        "mean_remaining_return"
                    ],
                    "not_confirmed_sample_count": control_metrics["sample_count"],
                    "not_confirmed_success_count": control_metrics["success_count"],
                    "not_confirmed_hit_rate": control_metrics["hit_rate"],
                    "not_confirmed_mean_remaining_return": control_metrics[
                        "mean_remaining_return"
                    ],
                    "delta_hit_rate": (
                        confirmed_metrics["hit_rate"] - control_metrics["hit_rate"]
                    ),
                    "delta_mean_remaining_return": (
                        confirmed_metrics["mean_remaining_return"]
                        - control_metrics["mean_remaining_return"]
                    ),
                    "event_year_count": int(universe["event_year"].nunique()),
                    "fisher_exact_p_value": p_value,
                    "fdr_q_value": math.nan,
                    "evidence_status": "PENDING_FDR",
                    "posterior_hypothesis_only": True,
                    "promotion_eligible": False,
                    "rule_version": RULE_VERSION,
                }
            )
    summary = pd.DataFrame(rows)
    valid = summary["confirmed_sample_count"].gt(0) & summary[
        "not_confirmed_sample_count"
    ].gt(0)
    # 检查点共享同一episode，FDR按分层口径和周期分别校正，不把检查点当新增样本。
    for _, family in summary.loc[valid].groupby(
        ["segmentation_dimension", "horizon"], sort=True
    ):
        summary.loc[family.index, "fdr_q_value"] = _benjamini_hochberg(
            family["fisher_exact_p_value"].astype(float).tolist()
        )
    for index, row in summary.iterrows():
        summary.at[index, "evidence_status"] = _stage_evidence_status(
            row,
            min_sample_size=min_sample_size,
            fdr_level=fdr_level,
        )
    return summary.sort_values(
        ["segmentation_dimension", "horizon", "checkpoint_session", "market_segment"]
    ).reset_index(drop=True)


def _validation_metrics(group: pd.DataFrame) -> dict[str, float | int]:
    count = len(group)
    successes = int(group["remaining_outcome"].eq("FOLLOW_THROUGH").sum())
    return {
        "sample_count": count,
        "success_count": successes,
        "hit_rate": successes / count if count else math.nan,
        "mean_remaining_return": _mean(group["remaining_directional_return"]),
    }


def _stage_evidence_status(
    row: pd.Series,
    *,
    min_sample_size: int,
    fdr_level: float,
) -> str:
    enough = (
        int(row["confirmed_sample_count"]) >= min_sample_size
        and int(row["not_confirmed_sample_count"]) >= min_sample_size
    )
    delta_hit = _float_or_nan(row["delta_hit_rate"])
    delta_return = _float_or_nan(row["delta_mean_remaining_return"])
    positive = delta_hit > 0 and delta_return > 0
    negative = delta_hit < 0 and delta_return < 0
    significant = (
        math.isfinite(_float_or_nan(row["fdr_q_value"]))
        and _float_or_nan(row["fdr_q_value"]) <= fdr_level
    )
    if not enough:
        return "SMALL_OR_UNBALANCED_SAMPLE"
    if significant and positive:
        return "STAGE_HYPOTHESIS_POSITIVE"
    if significant and negative:
        return "STAGE_HYPOTHESIS_NEGATIVE"
    if positive:
        return "WATCH_POSITIVE"
    if negative:
        return "WATCH_NEGATIVE"
    return "INCONCLUSIVE"


def _warning_records(
    *,
    run_id: str,
    activity_daily: pd.DataFrame,
    features: pd.DataFrame,
    summary: pd.DataFrame,
    baseline_year: int,
    min_sample_size: int,
) -> list[OptionMaturityConfirmationWarningRecord]:
    records = [
        OptionMaturityConfirmationWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93M_COMPLETE_2021_BASELINE_IS_HISTORICAL_CONTEXT",
            warning_message=(
                "2021全年中位数只用于冻结历史活跃度基准；2021年内比例不具备"
                "当时实时可得性，因此所有阶段结果均不自动晋级。"
            ),
            affected_count=int(
                activity_daily["calendar_year"].eq(baseline_year).sum()
            ),
            human_review_required=("option_market_stage_boundaries",),
        )
    ]
    misaligned = int(
        features.loc[
            features["stage_activity_alignment"].eq("DIVERGENT"), "event_id"
        ].nunique()
    )
    if misaligned:
        records.append(
            OptionMaturityConfirmationWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93M_CALENDAR_AND_ACTIVITY_STAGE_DIVERGENCE",
                warning_message=(
                    "部分事件的年份阶段与滚动成交持仓活跃状态不一致，报告将两套"
                    "分层分别展示，不强行覆盖。"
                ),
                affected_count=misaligned,
                human_review_required=("activity_ratio_thresholds",),
            )
        )
    small = int(
        (
            summary["confirmed_sample_count"].lt(min_sample_size)
            | summary["not_confirmed_sample_count"].lt(min_sample_size)
        ).sum()
    )
    if small:
        records.append(
            OptionMaturityConfirmationWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93M_STAGE_CHECKPOINT_SMALL_SAMPLES",
                warning_message="部分阶段-检查点的确认组或未确认组样本不足。",
                affected_count=small,
                human_review_required=("checkpoint_sessions",),
            )
        )
    records.append(
        OptionMaturityConfirmationWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93M_POST_CHECKPOINT_LABEL_BOUNDARY",
            warning_message=(
                "检查点特征与检查点后收益已物理分离；后续收益只作历史后验验证。"
            ),
            affected_count=len(features),
        )
    )
    return records


def _write_outputs(
    *,
    result: OptionMaturityConfirmationResult,
    activity_daily: pd.DataFrame,
    activity_annual: pd.DataFrame,
    checkpoint_features: pd.DataFrame,
    checkpoint_validation: pd.DataFrame,
    stage_summary: pd.DataFrame,
    input_paths: tuple[Path, ...],
    parameters: dict[str, object],
) -> None:
    frames = (
        (result.activity_daily_path, activity_daily),
        (result.activity_annual_path, activity_annual),
        (result.checkpoint_feature_path, checkpoint_features),
        (result.checkpoint_validation_path, checkpoint_validation),
        (result.stage_summary_path, stage_summary),
    )
    for path, frame in frames:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    _write_warnings(result)
    payload = {
        "report_type": "option_maturity_confirmation",
        "rule_version": RULE_VERSION,
        "summary": result.to_summary(),
        "parameters": parameters,
        "historical_returns_are_posterior_labels": True,
        "checkpoint_features_are_asof_safe": True,
        "promotion_eligible": False,
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
        activity_annual=activity_annual,
        stage_summary=stage_summary,
    )
    artifacts = tuple(path for path, _ in frames) + (
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        "report_type": "option_maturity_confirmation",
        "rule_version": RULE_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "summary": result.to_summary(),
        "parameters": parameters,
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "historical_returns_are_posterior_labels": True,
        "checkpoint_features_are_asof_safe": True,
        "promotion_eligible": False,
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warnings(result: OptionMaturityConfirmationResult) -> None:
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
    result: OptionMaturityConfirmationResult,
    activity_annual: pd.DataFrame,
    stage_summary: pd.DataFrame,
) -> None:
    lines = [
        "# CF R93M 期权市场成熟度与趋势确认检查点研究",
        "",
        "## 数据状态",
        "",
        f"- 期权core区间：`{result.start}` 至 `{result.end}`",
        f"- 趋势事件区间：`{result.event_sample_start}` 至 `{result.event_sample_end}`",
        f"- 独立趋势episode：`{result.event_count}`",
        f"- 检查点特征/后验验证行：`{result.checkpoint_feature_count}` / "
        f"`{result.checkpoint_validation_count}`",
        f"- 早期薄弱/扩张/成熟活跃事件：`{result.early_event_count}` / "
        f"`{result.expansion_event_count}` / `{result.mature_event_count}`",
        f"- 最新事件阶段：`{result.latest_event_stage}` / "
        f"`{result.latest_event_activity_state}`",
        "",
        "## 市场阶段定义",
        "",
        "- 年份阶段：2021为EARLY_THIN，2022-2023为EXPANSION，2024年起为MATURE_ACTIVE。",
        "- 数据阶段：使用截至当日60个交易日成交量与持仓量中位数，相对冻结的2021基准判断。",
        "- 2023成交已显著活跃，但持仓深度尚未达到2024以后水平，因此仍归入扩张期。",
        "- 两套阶段分别统计；出现分歧时不强行覆盖，也不写入当前方向信号。",
        "",
        "## 年度成交与持仓演进",
        "",
        *_annual_lines(activity_annual),
        "",
        "## 年份阶段检查点证据",
        "",
        *_stage_summary_lines(
            stage_summary,
            dimension="CALENDAR_STAGE",
            segment_heading="年份阶段",
        ),
        "",
        "## 滚动活跃状态检查点证据",
        "",
        *_stage_summary_lines(
            stage_summary,
            dimension="TRAILING_ACTIVITY_STATE",
            segment_heading="滚动活跃状态",
        ),
        "",
        "## 当前研究结论",
        "",
        *_conclusion_lines(result=result, summary=stage_summary),
        "",
        "## 研究边界",
        "",
        f"> {RESEARCH_BOUNDARY}",
        "",
        "- T、T+1、T+3、T+5、T+10检查点只使用当时已经发生的确认轨迹。",
        "- 检查点至5D/20D退出日的收益只在后验验证表中出现，不进入特征表。",
        "- 公开期权成交与持仓不能识别买卖方、产业身份或dealer gamma。",
        "- 阶段样本仍有限，任何显著项都只是后验假设，promotion_eligible固定为false。",
        "- 不修改signal matrix、composite_score、策略方向或目标手数，不构成交易指令。",
        "",
        "## 人工复核项",
        "",
        *[f"- `{item}`" for item in HUMAN_REVIEW_REQUIRED],
    ]
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _annual_lines(summary: pd.DataFrame) -> list[str]:
    lines = [
        "| 年度 | 阶段 | 交易日 | 日成交中位数 | 日持仓中位数 | 成交/2021 | 持仓/2021 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {row.calendar_year} | {row.option_market_stage} | "
            f"{row.trading_day_count} | {row.median_daily_volume:,.0f} | "
            f"{row.median_daily_open_interest:,.0f} | "
            f"{row.median_daily_volume_vs_2021:.2f}x | "
            f"{row.median_daily_oi_vs_2021:.2f}x |"
        )
    return lines


def _stage_summary_lines(
    summary: pd.DataFrame,
    *,
    dimension: str,
    segment_heading: str,
) -> list[str]:
    primary = summary.loc[summary["segmentation_dimension"].eq(dimension)]
    ranked = primary.sort_values(
        ["horizon", "checkpoint_session", "market_segment"]
    )
    lines = [
        f"| {segment_heading} | 周期 | 检查点 | 已确认/未确认样本 | "
        "命中率差 | 检查点后收益差 | q值 | 结论 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in ranked.itertuples(index=False):
        lines.append(
            f"| {row.market_segment} | {row.horizon}D | T+{row.checkpoint_session} | "
            f"{row.confirmed_sample_count}/{row.not_confirmed_sample_count} | "
            f"{_pct(row.delta_hit_rate)} | {_pct(row.delta_mean_remaining_return)} | "
            f"{_number(row.fdr_q_value)} | {row.evidence_status} |"
        )
    return lines


def _conclusion_lines(
    *,
    result: OptionMaturityConfirmationResult,
    summary: pd.DataFrame,
) -> list[str]:
    lines = [
        f"- FDR后分阶段正向/负向后验假设：`{result.significant_positive_count}` / "
        f"`{result.significant_negative_count}`。",
        "- 同一个期权确认条件在不同市场成熟阶段可能出现方向相反的历史效果，"
        "因此不再使用2021-2026合并样本直接判断确认有效性。",
    ]
    mature = summary.loc[
        summary["segmentation_dimension"].eq("CALENDAR_STAGE")
        & summary["market_segment"].eq("MATURE_ACTIVE")
        & summary["horizon"].eq(20)
    ].sort_values("checkpoint_session")
    for row in mature.itertuples(index=False):
        lines.append(
            f"- 成熟活跃期20D在T+{row.checkpoint_session}检查点：确认组相对未确认组"
            f"命中差 `{_pct(row.delta_hit_rate)}`，检查点后收益差 "
            f"`{_pct(row.delta_mean_remaining_return)}`，结论 `{row.evidence_status}`。"
        )
    lines.append(
        "- 只有在某一检查点之后形成的证据，最早也只能用于下一交易日研究判断；"
        "本模块不自动生成过滤器。"
    )
    lines.append(
        "- `WATCH_NEGATIVE`只表示当前分层样本中的负向差异尚待验证，"
        "不代表存在可交易的反向Alpha，也不得据此自动反转方向。"
    )
    return lines


def _calendar_market_stage(value: date) -> str:
    if value.year <= 2021:
        return "EARLY_THIN"
    if value.year <= 2023:
        return "EXPANSION"
    return "MATURE_ACTIVE"


def _activity_state(
    *,
    year: int,
    baseline_year: int,
    volume_ratio: object,
    oi_ratio: object,
    expansion_volume_ratio: float,
    expansion_oi_ratio: float,
    mature_volume_ratio: float,
    mature_oi_ratio: float,
) -> str:
    if year == baseline_year:
        return "EARLY_BASELINE"
    volume = _float_or_nan(volume_ratio)
    oi = _float_or_nan(oi_ratio)
    if not math.isfinite(volume) or not math.isfinite(oi):
        return "INSUFFICIENT_LOOKBACK"
    if volume >= mature_volume_ratio and oi >= mature_oi_ratio:
        return "MATURE_ACTIVE"
    if volume >= expansion_volume_ratio and oi >= expansion_oi_ratio:
        return "EXPANSION"
    return "THIN_OR_COOLING"


def _stage_activity_alignment(*, market_stage: str, activity_state: str) -> str:
    expected = {
        "EARLY_THIN": {"EARLY_BASELINE", "THIN_OR_COOLING"},
        "EXPANSION": {"EXPANSION"},
        "MATURE_ACTIVE": {"MATURE_ACTIVE"},
    }
    if activity_state == "INSUFFICIENT_LOOKBACK":
        return "INSUFFICIENT_LOOKBACK"
    return "ALIGNED" if activity_state in expected[market_stage] else "DIVERGENT"


def _first_confirmation_session(
    group: pd.DataFrame,
    *,
    flag_column: str,
    confirmation_days: int,
) -> int | None:
    ordered = group.sort_values("relative_session")
    flags = ordered[flag_column].map(_bool_value).tolist()
    sessions = ordered["relative_session"].astype(int).tolist()
    for start in range(len(ordered) - confirmation_days + 1):
        stop = start + confirmation_days
        candidate_sessions = sessions[start:stop]
        consecutive = all(
            right - left == 1
            for left, right in zip(candidate_sessions, candidate_sessions[1:])
        )
        if consecutive and all(flags[start:stop]):
            # 连续确认只能在最后一日结束后才可知。
            return int(candidate_sessions[-1])
    return None


def _trailing_true_streak(series: pd.Series) -> int:
    count = 0
    for value in reversed(series.map(_bool_value).tolist()):
        if not value:
            break
        count += 1
    return count


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


def _load_frame(path: Path, required: set[str], label: str) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"{label}不存在: {path}")
    frame = pd.read_parquet(path)
    missing = required - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"{label}缺少字段: {sorted(missing)}")
    working = frame.copy()
    for column in ("trade_date", "event_date", "state_date"):
        if column not in working.columns:
            continue
        parsed = pd.to_datetime(working[column], errors="coerce")
        if column in required and parsed.isna().any():
            raise ResearchWorkbenchError(f"{label}存在无效{column}")
        working[column] = parsed.dt.date
    return working


def _validate_label_columns(events: pd.DataFrame, horizons: tuple[int, ...]) -> None:
    required: set[str] = set()
    for horizon in horizons:
        required.update(
            {
                f"label_available_{horizon}d",
                f"directional_return_{horizon}d",
                f"outcome_{horizon}d",
            }
        )
    missing = required - set(events.columns)
    if missing:
        raise ResearchWorkbenchError(f"R93L事件索引缺少周期标签字段: {sorted(missing)}")


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
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / "option_maturity_confirmation"
    report_root = (
        report_output_dir
        or reports_dir() / "research" / "option_maturity_confirmation"
    )
    stem = f"CF_{start}_{end}_option_maturity_confirmation"
    return {
        "activity_daily": root / f"{stem}_activity_daily.parquet",
        "activity_annual": root / f"{stem}_activity_annual.parquet",
        "checkpoint_feature": root / f"{stem}_checkpoint_feature.parquet",
        "checkpoint_validation": root / f"{stem}_checkpoint_validation.parquet",
        "stage_summary": root / f"{stem}_stage_summary.parquet",
        "warnings": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
    }


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    checkpoints: tuple[int, ...],
    confirmation_days: int,
    activity_window: int,
    activity_min_periods: int,
    expansion_volume_ratio: float,
    expansion_oi_ratio: float,
    mature_volume_ratio: float,
    mature_oi_ratio: float,
    min_sample_size: int,
    fdr_level: float,
    dead_zone_bps: int,
) -> None:
    if confirmation_days < 1:
        raise ResearchWorkbenchError("confirmation_days必须为正整数")
    if activity_window < 2:
        raise ResearchWorkbenchError("activity_window至少为2")
    if not 1 <= activity_min_periods <= activity_window:
        raise ResearchWorkbenchError("activity_min_periods必须位于有效窗口内")
    if max(checkpoints) >= max(horizons):
        # 较长检查点可用于20D，但至少必须存在一个更长研究周期。
        if not any(checkpoint < horizon for checkpoint in checkpoints for horizon in horizons):
            raise ResearchWorkbenchError("所有checkpoints都不得晚于全部研究周期")
    if expansion_volume_ratio <= 0 or expansion_oi_ratio <= 0:
        raise ResearchWorkbenchError("扩张期活跃度比例必须为正数")
    if mature_volume_ratio <= expansion_volume_ratio:
        raise ResearchWorkbenchError("成熟期成交比例必须高于扩张期")
    if mature_oi_ratio <= expansion_oi_ratio:
        raise ResearchWorkbenchError("成熟期持仓比例必须高于扩张期")
    if min_sample_size < 1:
        raise ResearchWorkbenchError("min_sample_size必须为正整数")
    if not 0 < fdr_level <= 1:
        raise ResearchWorkbenchError("fdr_level必须位于(0,1]")
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("dead_zone_bps不得为负")


def _positive_int_tuple(values: tuple[int, ...], label: str) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in values)))
    if not normalized or any(value <= 0 for value in normalized):
        raise ResearchWorkbenchError(f"{label}必须包含正整数")
    return normalized


def _nonnegative_int_tuple(values: tuple[int, ...], label: str) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in values)))
    if not normalized or any(value < 0 for value in normalized):
        raise ResearchWorkbenchError(f"{label}必须包含非负整数")
    return normalized


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


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
    return f"cf_r93m_{datetime.now(tz=UTC):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}"
