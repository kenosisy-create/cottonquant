"""R93A CF 多空对称趋势结构与突破节奏研究。"""

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
SYMMETRIC_TREND_VERSION = "V5.1_R93A_symmetric_trend_research_v1"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
DEFAULT_FAST_WINDOW = 20
DEFAULT_SLOW_WINDOW = 40
DEFAULT_BREAKOUT_WINDOW = 20
DEFAULT_BREAKOUT_COOLDOWN = 5
DEFAULT_DEAD_ZONE_BPS = 10
DEFAULT_MIN_SAMPLE_SIZE = 30
INFO = "INFO"
WARN = "WARN"
HUMAN_REVIEW_REQUIRED = (
    "trend_direction_vote_threshold",
    "trend_stage_thresholds",
    "breakout_window_and_cooldown",
    "option_proxy_interpretation",
    "policy_event_context_not_connected",
    "candidate_position_sizing_not_defined",
)
RESEARCH_BOUNDARY = (
    "日度趋势状态只使用T日及以前数据；突破后的收益仅作为独立历史后验标签，"
    "不回流信号，不修改现有影子策略，不构成交易指令。"
)
CONTINUOUS_COLUMNS = {
    "trade_date",
    "mapped_contract",
    "adjusted_price",
}
CONTEXT_COLUMNS = {
    "trade_date",
    "main_contract",
    "phase_v2",
    "phase_direction",
    "dual_price_state",
    "participation_state",
    "roll_context",
    "option_direction",
    "confirmation_state",
    "confirmation_strength",
    "volatility_repricing_state",
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
class SymmetricTrendWarningRecord:
    """R93A warning row."""

    run_id: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-safe warning record."""
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning record."""
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class SymmetricTrendResearchResult:
    """R93A output bundle."""

    run_id: str
    start: date
    end: date
    status: str
    daily_row_count: int
    breakout_event_count: int
    episode_count: int
    current_direction: str
    current_stage: str
    continuous_price_path: Path
    trend_context_path: Path
    daily_path: Path
    breakout_event_path: Path
    episode_path: Path
    breakout_summary_path: Path
    episode_summary_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[SymmetricTrendWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(item.severity != INFO for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        """Return compact CLI output."""
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "status": self.status,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "daily_row_count": self.daily_row_count,
            "breakout_event_count": self.breakout_event_count,
            "episode_count": self.episode_count,
            "current_direction": self.current_direction,
            "current_stage": self.current_stage,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "daily_path": str(self.daily_path),
            "breakout_event_path": str(self.breakout_event_path),
            "episode_path": str(self.episode_path),
            "breakout_summary_path": str(self.breakout_summary_path),
            "episode_summary_path": str(self.episode_summary_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "research_boundary": RESEARCH_BOUNDARY,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_symmetric_trend_research(
    *,
    continuous_price_path: Path | None = None,
    trend_context_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
    breakout_window: int = DEFAULT_BREAKOUT_WINDOW,
    breakout_cooldown: int = DEFAULT_BREAKOUT_COOLDOWN,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> SymmetricTrendResearchResult:
    """Build direction-stage separated trend and breakout evidence."""
    normalized_horizons = _normalize_horizons(horizons)
    _validate_parameters(
        fast_window=fast_window,
        slow_window=slow_window,
        breakout_window=breakout_window,
        breakout_cooldown=breakout_cooldown,
        dead_zone_bps=dead_zone_bps,
        min_sample_size=min_sample_size,
    )
    continuous_path = continuous_price_path or _latest_continuous_price_path()
    context_path = trend_context_path or _latest_trend_context_path()
    continuous = _load_frame(
        continuous_path,
        required=CONTINUOUS_COLUMNS,
        label="strategy continuous price",
    )
    context = _load_frame(
        context_path,
        required=CONTEXT_COLUMNS,
        label="trend context",
    )
    start = max(continuous["trade_date"].min(), context["trade_date"].min())
    end = min(continuous["trade_date"].max(), context["trade_date"].max())
    if start > end:
        raise ResearchWorkbenchError("continuous price and trend context do not overlap")
    active_run_id = run_id or _default_run_id(start=start, end=end)

    daily = _build_daily_state(
        continuous=continuous,
        context=context,
        run_id=active_run_id,
        fast_window=fast_window,
        slow_window=slow_window,
        breakout_window=breakout_window,
        breakout_cooldown=breakout_cooldown,
    )
    if daily.empty:
        raise ResearchWorkbenchError("symmetric trend research produced no daily rows")
    breakout_events = _build_breakout_events(
        daily=daily,
        run_id=active_run_id,
        horizons=normalized_horizons,
        dead_zone_bps=dead_zone_bps,
    )
    episodes = _build_episodes(daily=daily, run_id=active_run_id)
    breakout_summary = _build_breakout_summary(
        breakout_events,
        min_sample_size=min_sample_size,
    )
    episode_summary = _build_episode_summary(
        episodes,
        min_sample_size=min_sample_size,
    )
    warnings = _warning_records(
        daily=daily,
        breakout_summary=breakout_summary,
        episodes=episodes,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
    )
    status = (
        "SYMMETRIC_TREND_READY_WITH_WARNINGS"
        if any(item.severity == WARN for item in warnings)
        else "SYMMETRIC_TREND_READY"
    )
    paths = _output_paths(
        start=start,
        end=end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    latest = daily.iloc[-1]
    result = SymmetricTrendResearchResult(
        run_id=active_run_id,
        start=start,
        end=end,
        status=status,
        daily_row_count=len(daily),
        breakout_event_count=int(breakout_events["event_id"].nunique()),
        episode_count=len(episodes),
        current_direction=str(latest["trend_direction"]),
        current_stage=str(latest["trend_stage"]),
        continuous_price_path=continuous_path,
        trend_context_path=context_path,
        daily_path=paths["daily"],
        breakout_event_path=paths["breakout_events"],
        episode_path=paths["episodes"],
        breakout_summary_path=paths["breakout_summary"],
        episode_summary_path=paths["episode_summary"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=tuple(warnings),
    )
    _write_outputs(
        result=result,
        daily=daily,
        breakout_events=breakout_events,
        episodes=episodes,
        breakout_summary=breakout_summary,
        episode_summary=episode_summary,
        input_paths=(continuous_path, context_path),
        parameters={
            "fast_window": fast_window,
            "slow_window": slow_window,
            "breakout_window": breakout_window,
            "breakout_cooldown": breakout_cooldown,
            "horizons": list(normalized_horizons),
            "dead_zone_bps": dead_zone_bps,
            "min_sample_size": min_sample_size,
        },
    )
    return result


def _build_daily_state(
    *,
    continuous: pd.DataFrame,
    context: pd.DataFrame,
    run_id: str,
    fast_window: int,
    slow_window: int,
    breakout_window: int,
    breakout_cooldown: int,
) -> pd.DataFrame:
    price = continuous[["trade_date", "mapped_contract", "adjusted_price"]].copy()
    joined = price.merge(context, on="trade_date", how="inner", validate="one_to_one")
    joined = joined.sort_values("trade_date").reset_index(drop=True)
    joined["adjusted_price"] = pd.to_numeric(joined["adjusted_price"], errors="coerce")
    if joined["adjusted_price"].isna().any() or joined["adjusted_price"].le(0).any():
        raise ResearchWorkbenchError("continuous adjusted_price must be positive and finite")

    prices = joined["adjusted_price"]
    returns = prices.pct_change(fill_method=None)
    joined["return_5d"] = prices.pct_change(5, fill_method=None)
    joined["return_fast"] = prices.pct_change(fast_window, fill_method=None)
    joined["return_slow"] = prices.pct_change(slow_window, fill_method=None)
    joined["ma_fast"] = prices.rolling(fast_window, min_periods=fast_window).mean()
    joined["ma_slow"] = prices.rolling(slow_window, min_periods=slow_window).mean()
    joined["ma_fast_slope_5d"] = joined["ma_fast"].pct_change(5, fill_method=None)
    joined["realized_volatility_fast"] = (
        returns.rolling(fast_window, min_periods=fast_window).std(ddof=1)
        * math.sqrt(252)
    )
    path_length = prices.diff().abs().rolling(fast_window, min_periods=fast_window).sum()
    joined["efficiency_ratio"] = (
        (prices - prices.shift(fast_window)).abs() / path_length.replace(0, np.nan)
    ).clip(0, 1)
    daily_vol = returns.rolling(fast_window, min_periods=fast_window).std(ddof=1)
    joined["normalized_momentum"] = joined["return_fast"] / (
        daily_vol * math.sqrt(fast_window)
    ).replace(0, np.nan)
    joined["prior_channel_high"] = (
        prices.shift(1).rolling(breakout_window, min_periods=breakout_window).max()
    )
    joined["prior_channel_low"] = (
        prices.shift(1).rolling(breakout_window, min_periods=breakout_window).min()
    )
    joined["channel_breakout_direction"] = np.select(
        [
            prices.gt(joined["prior_channel_high"]),
            prices.lt(joined["prior_channel_low"]),
        ],
        ["long", "short"],
        default="neutral",
    )

    votes = pd.DataFrame(index=joined.index)
    votes["fast_return"] = joined["return_fast"].map(_signed_vote)
    votes["slow_return"] = joined["return_slow"].map(_signed_vote)
    votes["ma_location"] = (prices - joined["ma_fast"]).map(_signed_vote)
    votes["ma_slope"] = joined["ma_fast_slope_5d"].map(_signed_vote)
    votes["dual_price"] = joined["dual_price_state"].map(_dual_price_vote)
    joined["direction_score"] = votes.sum(axis=1).astype(int)
    lookback_ready = joined["return_slow"].notna() & joined["ma_fast_slope_5d"].notna()
    joined["lookback_ready"] = lookback_ready
    joined["trend_direction"] = np.select(
        [
            lookback_ready & joined["direction_score"].ge(3),
            lookback_ready & joined["direction_score"].le(-3),
        ],
        ["long", "short"],
        default="neutral",
    )

    direction_age: list[int] = []
    stages: list[str] = []
    breakout_events: list[bool] = []
    strengths: list[float] = []
    direction_episode_ids: list[str] = []
    previous_direction = "neutral"
    current_age = 0
    episode_number = 0
    active_episode_id = ""
    last_breakout_index = {"long": -10_000, "short": -10_000}
    for index, row in joined.iterrows():
        direction = str(row["trend_direction"])
        if direction == "neutral":
            current_age = 0
            active_episode_id = ""
        elif direction == previous_direction:
            current_age += 1
        else:
            current_age = 1
            episode_number += 1
            active_episode_id = (
                f"{row['trade_date']:%Y%m%d}_{direction}_{episode_number:04d}"
            )
        direction_age.append(current_age)
        direction_episode_ids.append(active_episode_id)

        channel_direction = str(row["channel_breakout_direction"])
        is_breakout = (
            direction in {"long", "short"}
            and channel_direction == direction
            and (
                direction != previous_direction
                or index - last_breakout_index[direction] >= breakout_cooldown
            )
        )
        if is_breakout:
            last_breakout_index[direction] = index
        breakout_events.append(is_breakout)

        efficiency = _finite_or_zero(row["efficiency_ratio"])
        normalized_momentum = min(abs(_finite_or_zero(row["normalized_momentum"])), 2.0)
        score_strength = abs(int(row["direction_score"])) / 5
        strength = 0.4 * score_strength + 0.35 * efficiency + 0.25 * (
            normalized_momentum / 2
        )
        strengths.append(round(min(max(strength, 0.0), 1.0), 6))

        signed_return_5d = _direction_sign(direction) * _finite_or_zero(row["return_5d"])
        if not bool(row["lookback_ready"]) or direction == "neutral":
            stage = "NEUTRAL"
        elif previous_direction in {"long", "short"} and direction != previous_direction:
            stage = "REVERSAL"
        elif is_breakout:
            stage = "BREAKOUT"
        elif (
            current_age >= 3
            and abs(int(row["direction_score"])) >= 4
            and efficiency >= 0.25
            and signed_return_5d > 0
        ):
            stage = "TREND"
        elif current_age >= 3 and (signed_return_5d <= 0 or efficiency < 0.15):
            stage = "DECELERATION"
        else:
            stage = "SETUP"
        stages.append(stage)
        previous_direction = direction

    joined["direction_age"] = direction_age
    joined["direction_episode_id"] = direction_episode_ids
    joined["trend_stage"] = stages
    joined["breakout_event"] = breakout_events
    joined["trend_strength"] = strengths
    joined["option_alignment"] = joined.apply(_option_alignment, axis=1)
    joined["participation_alignment"] = joined.apply(_participation_alignment, axis=1)
    joined["run_id"] = run_id
    joined["rule_version"] = SYMMETRIC_TREND_VERSION
    joined["state_uses_t_or_earlier"] = True
    joined["trading_instruction"] = "not_a_trading_instruction"
    return joined[
        [
            "run_id",
            "trade_date",
            "mapped_contract",
            "main_contract",
            "adjusted_price",
            "return_5d",
            "return_fast",
            "return_slow",
            "ma_fast",
            "ma_slow",
            "ma_fast_slope_5d",
            "realized_volatility_fast",
            "efficiency_ratio",
            "normalized_momentum",
            "prior_channel_high",
            "prior_channel_low",
            "channel_breakout_direction",
            "breakout_event",
            "direction_score",
            "trend_direction",
            "trend_stage",
            "trend_strength",
            "direction_age",
            "direction_episode_id",
            "lookback_ready",
            "dual_price_state",
            "participation_state",
            "participation_alignment",
            "roll_context",
            "option_direction",
            "confirmation_state",
            "confirmation_strength",
            "option_alignment",
            "volatility_repricing_state",
            "phase_v2",
            "phase_direction",
            "rule_version",
            "state_uses_t_or_earlier",
            "trading_instruction",
        ]
    ].copy()


def _build_breakout_events(
    *,
    daily: pd.DataFrame,
    run_id: str,
    horizons: tuple[int, ...],
    dead_zone_bps: int,
) -> pd.DataFrame:
    dead_zone = dead_zone_bps / 10_000
    rows: list[dict[str, object]] = []
    event_number = 0
    for index, row in daily.iterrows():
        if not bool(row["breakout_event"]):
            continue
        event_number += 1
        direction = str(row["trend_direction"])
        direction_sign = _direction_sign(direction)
        event_id = f"{row['trade_date']:%Y%m%d}_{direction}_{event_number:04d}"
        start_price = float(row["adjusted_price"])
        for horizon in horizons:
            exit_index = index + horizon
            label_available = exit_index < len(daily)
            exit_date: date | None = None
            raw_return: float | None = None
            directional_return: float | None = None
            outcome = "CURRENT_ONLY"
            if label_available:
                exit_row = daily.iloc[exit_index]
                exit_date = exit_row["trade_date"]
                raw_return = float(exit_row["adjusted_price"] / start_price - 1.0)
                directional_return = direction_sign * raw_return
                if directional_return > dead_zone:
                    outcome = "FOLLOW_THROUGH"
                elif directional_return < -dead_zone:
                    outcome = "FAILED_BREAKOUT"
                else:
                    outcome = "UNRESOLVED"
            rows.append(
                {
                    "run_id": run_id,
                    "event_id": event_id,
                    "event_date": row["trade_date"],
                    "event_year": row["trade_date"].year,
                    "direction": direction,
                    "direction_episode_id": row["direction_episode_id"],
                    "start_stage": row["trend_stage"],
                    "start_strength": float(row["trend_strength"]),
                    "start_price": start_price,
                    "main_contract": row["main_contract"],
                    "option_alignment": row["option_alignment"],
                    "option_direction": row["option_direction"],
                    "option_strength": row["confirmation_strength"],
                    "participation_alignment": row["participation_alignment"],
                    "roll_context": row["roll_context"],
                    "horizon": horizon,
                    "exit_date": exit_date,
                    "raw_return": raw_return,
                    "directional_return": directional_return,
                    "label_available": label_available,
                    "outcome": outcome,
                    "historical_posterior_label": True,
                    "rule_version": SYMMETRIC_TREND_VERSION,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    if not rows:
        raise ResearchWorkbenchError("no symmetric breakout event was identified")
    return pd.DataFrame(rows)


def _build_episodes(*, daily: pd.DataFrame, run_id: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start_index: int | None = None
    active_direction = "neutral"

    def close_episode(end_index: int) -> None:
        nonlocal start_index, active_direction
        if start_index is None or active_direction == "neutral" or end_index < start_index:
            return
        section = daily.iloc[start_index : end_index + 1]
        first = section.iloc[0]
        last = section.iloc[-1]
        sign = _direction_sign(active_direction)
        path = sign * (section["adjusted_price"] / float(first["adjusted_price"]) - 1.0)
        breakout_dates = section.loc[section["breakout_event"], "trade_date"]
        is_open = end_index == len(daily) - 1
        rows.append(
            {
                "run_id": run_id,
                "episode_id": first["direction_episode_id"],
                "start_date": first["trade_date"],
                "start_year": first["trade_date"].year,
                "end_date": last["trade_date"],
                "direction": active_direction,
                "start_stage": first["trend_stage"],
                "end_stage": last["trend_stage"],
                "duration_days": len(section),
                "start_price": float(first["adjusted_price"]),
                "end_price": float(last["adjusted_price"]),
                "directional_return": float(path.iloc[-1]),
                "mfe": float(path.max()),
                "mae": float(path.min()),
                "mean_strength": float(section["trend_strength"].mean()),
                "max_strength": float(section["trend_strength"].max()),
                "breakout_event_count": int(section["breakout_event"].sum()),
                "first_breakout_date": (
                    breakout_dates.iloc[0] if not breakout_dates.empty else None
                ),
                "start_option_alignment": first["option_alignment"],
                "start_participation_alignment": first["participation_alignment"],
                "is_open": is_open,
                "historical_posterior_label": not is_open,
                "rule_version": SYMMETRIC_TREND_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )

    for index, row in daily.iterrows():
        direction = str(row["trend_direction"])
        if direction == active_direction:
            continue
        if active_direction != "neutral" and start_index is not None:
            close_episode(index - 1)
        active_direction = direction
        start_index = index if direction != "neutral" else None
    if active_direction != "neutral" and start_index is not None:
        close_episode(len(daily) - 1)
    if not rows:
        raise ResearchWorkbenchError("no symmetric trend episode was identified")
    return pd.DataFrame(rows)


def _build_breakout_summary(
    events: pd.DataFrame,
    *,
    min_sample_size: int,
) -> pd.DataFrame:
    available = events.loc[events["label_available"]].copy()
    rows: list[dict[str, object]] = []
    groupings = (
        ("horizon", ["horizon"]),
        ("direction+horizon", ["direction", "horizon"]),
        ("event_year+horizon", ["event_year", "horizon"]),
        (
            "direction+event_year+horizon",
            ["direction", "event_year", "horizon"],
        ),
        ("option_alignment+horizon", ["option_alignment", "horizon"]),
        (
            "participation_alignment+horizon",
            ["participation_alignment", "horizon"],
        ),
    )
    for grouping, columns in groupings:
        for keys, group in available.groupby(columns, dropna=False, sort=True):
            key_values = keys if isinstance(keys, tuple) else (keys,)
            payload = dict(zip(columns, key_values, strict=True))
            count = len(group)
            independent_count = int(group["direction_episode_id"].nunique())
            independent = (
                group.sort_values(["event_date", "event_id"])
                .drop_duplicates("direction_episode_id", keep="first")
                .copy()
            )
            independent_successes = int(
                independent["outcome"].eq("FOLLOW_THROUGH").sum()
            )
            independent_rate = independent_successes / independent_count
            ci_lower, ci_upper = _wilson_interval(
                successes=independent_successes,
                sample_count=independent_count,
            )
            rows.append(
                {
                    "grouping": grouping,
                    **payload,
                    "sample_count": count,
                    "independent_episode_count": independent_count,
                    "independent_follow_through_rate": independent_rate,
                    "independent_mean_directional_return": float(
                        independent["directional_return"].mean()
                    ),
                    "independent_hit_rate_ci_lower": ci_lower,
                    "independent_hit_rate_ci_upper": ci_upper,
                    "follow_through_rate": float(group["outcome"].eq("FOLLOW_THROUGH").mean()),
                    "failure_rate": float(group["outcome"].eq("FAILED_BREAKOUT").mean()),
                    "unresolved_rate": float(group["outcome"].eq("UNRESOLVED").mean()),
                    "mean_directional_return": float(group["directional_return"].mean()),
                    "median_directional_return": float(group["directional_return"].median()),
                    "evidence_level": (
                        "SUFFICIENT_SAMPLE"
                        if independent_count >= min_sample_size
                        else "SMALL_SAMPLE"
                    ),
                    "edge_status": (
                        "POSITIVE_EDGE"
                        if ci_lower > 0.5
                        else "NEGATIVE_EDGE"
                        if ci_upper < 0.5
                        else "INCONCLUSIVE"
                    ),
                    "rule_version": SYMMETRIC_TREND_VERSION,
                }
            )
    return pd.DataFrame(rows)


def _build_episode_summary(
    episodes: pd.DataFrame,
    *,
    min_sample_size: int,
) -> pd.DataFrame:
    closed = episodes.loc[~episodes["is_open"]].copy()
    rows: list[dict[str, object]] = []
    groupings = (
        ("direction", ["direction"]),
        ("start_year", ["start_year"]),
        ("direction+start_year", ["direction", "start_year"]),
        ("start_stage", ["start_stage"]),
        ("start_option_alignment", ["start_option_alignment"]),
        ("direction+start_option_alignment", ["direction", "start_option_alignment"]),
    )
    for grouping, columns in groupings:
        for keys, group in closed.groupby(columns, dropna=False, sort=True):
            key_values = keys if isinstance(keys, tuple) else (keys,)
            payload = dict(zip(columns, key_values, strict=True))
            count = len(group)
            rows.append(
                {
                    "grouping": grouping,
                    **payload,
                    "sample_count": count,
                    "positive_episode_rate": float(group["directional_return"].gt(0).mean()),
                    "mean_directional_return": float(group["directional_return"].mean()),
                    "median_directional_return": float(group["directional_return"].median()),
                    "mean_duration_days": float(group["duration_days"].mean()),
                    "mean_mfe": float(group["mfe"].mean()),
                    "mean_mae": float(group["mae"].mean()),
                    "evidence_level": (
                        "SUFFICIENT_SAMPLE"
                        if count >= min_sample_size
                        else "SMALL_SAMPLE"
                    ),
                    "rule_version": SYMMETRIC_TREND_VERSION,
                }
            )
    return pd.DataFrame(rows)


def _warning_records(
    *,
    daily: pd.DataFrame,
    breakout_summary: pd.DataFrame,
    episodes: pd.DataFrame,
    run_id: str,
    min_sample_size: int,
) -> list[SymmetricTrendWarningRecord]:
    warnings: list[SymmetricTrendWarningRecord] = []
    lookback_count = int((~daily["lookback_ready"]).sum())
    if lookback_count:
        warnings.append(
            SymmetricTrendWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="SYMMETRIC_TREND_LOOKBACK_WARMUP",
                warning_message="慢窗口形成前保持中性，不进入突破方向判断。",
                affected_count=lookback_count,
            )
        )
    s4_short = int(
        (daily["phase_v2"].eq("S4") & daily["phase_direction"].eq("short")).sum()
    )
    if s4_short:
        warnings.append(
            SymmetricTrendWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="LEGACY_S4_CONFLATES_SHORT_DIRECTION_WITH_END_STAGE",
                warning_message=(
                    "旧阶段表把强空向确认编码为S4终点；R93A仅保留为对照，不参与新方向。"
                ),
                affected_count=s4_short,
                human_review_required=("trend_stage_semantics",),
            )
        )
    direction_counts = daily["trend_direction"].value_counts()
    for direction in ("long", "short"):
        if int(direction_counts.get(direction, 0)) == 0:
            warnings.append(
                SymmetricTrendWarningRecord(
                    run_id=run_id,
                    severity=WARN,
                    warning_code=f"SYMMETRIC_TREND_{direction.upper()}_SIDE_ABSENT",
                    warning_message=f"历史状态中未识别到{direction}方向，需复核对称性。",
                    affected_count=0,
                    human_review_required=("trend_direction_vote_threshold",),
                )
            )
    missing_option = int(
        (~daily["option_direction"].isin(["long", "short", "neutral"])).sum()
    )
    if missing_option:
        warnings.append(
            SymmetricTrendWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="SYMMETRIC_TREND_OPTION_CONTEXT_MISSING",
                warning_message="部分交易日缺少可解释期权方向，相关事件仅使用期货结构。",
                affected_count=missing_option,
                human_review_required=("option_proxy_interpretation",),
            )
        )
    small_groups = int(
        breakout_summary["sample_count"].lt(min_sample_size).sum()
        if not breakout_summary.empty
        else 0
    )
    if small_groups:
        warnings.append(
            SymmetricTrendWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="SYMMETRIC_TREND_SMALL_SAMPLE_GROUPS",
                warning_message="小样本分组只作观察，不允许据此确定仓位参数。",
                affected_count=small_groups,
            )
        )
    open_episodes = int(episodes["is_open"].sum())
    if open_episodes:
        warnings.append(
            SymmetricTrendWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="SYMMETRIC_TREND_OPEN_EPISODE_CURRENT_ONLY",
                warning_message="最新开放episode仅展示当前结构，不进入完整生命周期统计。",
                affected_count=open_episodes,
            )
        )
    return warnings


def _write_outputs(
    *,
    result: SymmetricTrendResearchResult,
    daily: pd.DataFrame,
    breakout_events: pd.DataFrame,
    episodes: pd.DataFrame,
    breakout_summary: pd.DataFrame,
    episode_summary: pd.DataFrame,
    input_paths: tuple[Path, ...],
    parameters: dict[str, object],
) -> None:
    for path, frame in (
        (result.daily_path, daily),
        (result.breakout_event_path, breakout_events),
        (result.episode_path, episodes),
        (result.breakout_summary_path, breakout_summary),
        (result.episode_summary_path, episode_summary),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    _write_warning_csv(result.warning_csv_path, result.warning_records)

    payload = {
        **result.to_summary(),
        "rule_version": SYMMETRIC_TREND_VERSION,
        "parameters": parameters,
        "current_state": _json_safe_record(daily.iloc[-1].to_dict()),
        "direction_counts": daily["trend_direction"].value_counts().to_dict(),
        "stage_counts": daily["trend_stage"].value_counts().to_dict(),
        "legacy_phase_counts": daily["phase_v2"].value_counts().to_dict(),
        "breakout_summary": [
            _json_safe_record(row)
            for row in breakout_summary.to_dict(orient="records")
        ],
        "episode_summary": [
            _json_safe_record(row) for row in episode_summary.to_dict(orient="records")
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
            daily=daily,
            breakout_summary=breakout_summary,
            episode_summary=episode_summary,
            parameters=parameters,
        ),
        encoding="utf-8",
    )
    artifacts = (
        result.daily_path,
        result.breakout_event_path,
        result.episode_path,
        result.breakout_summary_path,
        result.episode_summary_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        **result.to_summary(),
        "rule_version": SYMMETRIC_TREND_VERSION,
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
    result: SymmetricTrendResearchResult,
    daily: pd.DataFrame,
    breakout_summary: pd.DataFrame,
    episode_summary: pd.DataFrame,
    parameters: dict[str, object],
) -> str:
    latest = daily.iloc[-1]
    direction_counts = daily["trend_direction"].value_counts()
    stage_counts = daily["trend_stage"].value_counts()
    legacy_s4_short = int(
        (daily["phase_v2"].eq("S4") & daily["phase_direction"].eq("short")).sum()
    )
    lines = [
        f"# CF 多空对称趋势结构研究 - {result.end}",
        "",
        "## 数据状态",
        "",
        f"- 样本区间：`{result.start}` 至 `{result.end}`",
        f"- 日度状态：`{result.daily_row_count}` 行",
        f"- 突破事件：`{result.breakout_event_count}` 个",
        f"- 趋势 episode：`{result.episode_count}` 个",
        f"- 状态：`{result.status}`",
        "",
        "## 研究定义",
        "",
        "- 方向与阶段分离：方向为 long/short/neutral，阶段为 "
        "NEUTRAL/SETUP/BREAKOUT/TREND/DECELERATION/REVERSAL。",
        "- 方向采用快慢收益、均线位置、均线斜率和双价格状态的对称投票。",
        "- 期权和全链持仓只标记确认或背离，不直接决定期货方向。",
        f"- 参数：`{json.dumps(parameters, ensure_ascii=False, sort_keys=True)}`",
        "",
        "## 多空对称性",
        "",
        f"- long 状态：`{int(direction_counts.get('long', 0))}` 日",
        f"- short 状态：`{int(direction_counts.get('short', 0))}` 日",
        f"- neutral 状态：`{int(direction_counts.get('neutral', 0))}` 日",
        f"- 旧表 S4+short：`{legacy_s4_short}` 日；仅作语义错位对照。",
        "",
        "## 阶段分布",
        "",
        "| 阶段 | 交易日 |",
        "| --- | ---: |",
    ]
    for stage, count in stage_counts.items():
        lines.append(f"| {stage} | {int(count)} |")
    lines.extend(
        [
            "",
            "## 突破后节奏",
            "",
            "| 分组 | 周期 | 事件 | 独立episode | 独立延续率 | 95%区间 | "
            "独立平均收益 | 结论 |",
            "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
        ]
    )
    horizon_rows = breakout_summary.loc[breakout_summary["grouping"].eq("horizon")]
    for row in horizon_rows.itertuples(index=False):
        lines.append(
            f"| 全部突破 | {int(row.horizon)}D | {int(row.sample_count)} | "
            f"{int(row.independent_episode_count)} | "
            f"{float(row.independent_follow_through_rate):.2%} | "
            f"[{float(row.independent_hit_rate_ci_lower):.2%}, "
            f"{float(row.independent_hit_rate_ci_upper):.2%}] | "
            f"{float(row.independent_mean_directional_return):.2%} | "
            f"{row.evidence_level}/{row.edge_status} |"
        )
    lines.extend(
        [
            "",
            "## 年度稳定性",
            "",
            "| 年度 | 方向 | 周期 | 独立episode | 独立延续率 | 独立平均收益 |",
            "| ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    stability_horizon = max(parameters["horizons"])
    yearly_rows = breakout_summary.loc[
        breakout_summary["grouping"].eq("direction+event_year+horizon")
        & breakout_summary["horizon"].eq(stability_horizon)
    ]
    for row in yearly_rows.itertuples(index=False):
        lines.append(
            f"| {int(row.event_year)} | {row.direction} | {int(row.horizon)}D | "
            f"{int(row.independent_episode_count)} | "
            f"{float(row.independent_follow_through_rate):.2%} | "
            f"{float(row.independent_mean_directional_return):.2%} |"
        )
    lines.extend(
        [
            "",
            "## 期权确认与背离",
            "",
            "| 期权结构 | 周期 | 事件 | 独立episode | 独立延续率 | 95%区间 | "
            "独立平均收益 | 结论 |",
            "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
        ]
    )
    option_rows = breakout_summary.loc[
        breakout_summary["grouping"].eq("option_alignment+horizon")
    ]
    for row in option_rows.itertuples(index=False):
        lines.append(
            f"| {row.option_alignment} | {int(row.horizon)}D | "
            f"{int(row.sample_count)} | {int(row.independent_episode_count)} | "
            f"{float(row.independent_follow_through_rate):.2%} | "
            f"[{float(row.independent_hit_rate_ci_lower):.2%}, "
            f"{float(row.independent_hit_rate_ci_upper):.2%}] | "
            f"{float(row.independent_mean_directional_return):.2%} | "
            f"{row.evidence_level}/{row.edge_status} |"
        )
    lines.extend(
        [
            "",
            "## Episode 结果",
            "",
            "| 方向 | 样本 | 正收益率 | 平均持续日 | 平均MFE | 平均MAE |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    direction_rows = episode_summary.loc[episode_summary["grouping"].eq("direction")]
    for row in direction_rows.itertuples(index=False):
        lines.append(
            f"| {row.direction} | {int(row.sample_count)} | "
            f"{float(row.positive_episode_rate):.2%} | "
            f"{float(row.mean_duration_days):.2f} | {float(row.mean_mfe):.2%} | "
            f"{float(row.mean_mae):.2%} |"
        )
    lines.extend(
        [
            "",
            "## 当前结构",
            "",
            f"- 方向：`{latest['trend_direction']}`",
            f"- 阶段：`{latest['trend_stage']}`",
            f"- 强度：`{float(latest['trend_strength']):.3f}`",
            f"- 期权：`{latest['option_alignment']}`",
            f"- 持仓参与：`{latest['participation_alignment']}`",
            "- 当前行不包含未来收益标签。",
            "",
            "## 研究结论边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- 本模块尚未定义目标仓位，不得据此替换 CF_tsmom_v0。",
            "- 政策事件与宏观日历尚未接入，只能由价格、波动和期权重定价间接观察。",
            f"- HUMAN_REVIEW_REQUIRED：`{';'.join(HUMAN_REVIEW_REQUIRED)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _option_alignment(row: pd.Series) -> str:
    direction = str(row["trend_direction"])
    option_direction = str(row["option_direction"])
    strength = str(row["confirmation_strength"])
    if direction not in {"long", "short"}:
        return "NO_TREND_DIRECTION"
    if option_direction == "neutral":
        return "OPTION_NEUTRAL"
    if option_direction not in {"long", "short"}:
        return "NOT_CONNECTED"
    if strength not in {"medium", "high"}:
        return "WEAK_OPTION_CONTEXT"
    return "CONFIRM" if option_direction == direction else "DIVERGE"


def _participation_alignment(row: pd.Series) -> str:
    direction = str(row["trend_direction"])
    participation = str(row["participation_state"])
    if direction == "long":
        if participation == "LONG_BUILD":
            return "CONFIRM"
        if participation == "SHORT_BUILD":
            return "DIVERGE"
    if direction == "short":
        if participation == "SHORT_BUILD":
            return "CONFIRM"
        if participation == "LONG_BUILD":
            return "DIVERGE"
    return "NEUTRAL_OR_EXIT"


def _load_frame(path: Path, *, required: set[str], label: str) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"{label} path does not exist: {path}")
    frame = pd.read_parquet(path)
    missing = required.difference(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"{label} missing columns {sorted(missing)}: {path}")
    selected = frame[list(sorted(required))].copy()
    selected["trade_date"] = pd.to_datetime(selected["trade_date"], errors="coerce").dt.date
    if selected["trade_date"].isna().any():
        raise ResearchWorkbenchError(f"{label} contains invalid trade_date: {path}")
    if selected["trade_date"].duplicated().any():
        raise ResearchWorkbenchError(f"{label} contains duplicate trade_date: {path}")
    return selected.sort_values("trade_date").reset_index(drop=True)


def _validate_parameters(
    *,
    fast_window: int,
    slow_window: int,
    breakout_window: int,
    breakout_cooldown: int,
    dead_zone_bps: int,
    min_sample_size: int,
) -> None:
    if fast_window < 5:
        raise ResearchWorkbenchError("fast_window must be at least 5")
    if slow_window <= fast_window:
        raise ResearchWorkbenchError("slow_window must be greater than fast_window")
    if breakout_window < 5:
        raise ResearchWorkbenchError("breakout_window must be at least 5")
    if breakout_cooldown < 1:
        raise ResearchWorkbenchError("breakout_cooldown must be positive")
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("dead_zone_bps must be non-negative")
    if min_sample_size < 1:
        raise ResearchWorkbenchError("min_sample_size must be positive")


def _normalize_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    values = tuple(sorted(set(int(value) for value in horizons)))
    if not values or any(value <= 0 for value in values):
        raise ResearchWorkbenchError("horizons must contain positive integers")
    return values


def _wilson_interval(*, successes: int, sample_count: int) -> tuple[float, float]:
    """计算二项命中率的95% Wilson区间，避免把点估计当作确定优势。"""
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


def _signed_vote(value: object) -> int:
    number = _finite_or_zero(value)
    return 1 if number > 0 else -1 if number < 0 else 0


def _dual_price_vote(value: object) -> int:
    state = str(value)
    if state == "BOTH_ABOVE":
        return 1
    if state == "BOTH_BELOW":
        return -1
    return 0


def _direction_sign(direction: str) -> int:
    return 1 if direction == "long" else -1 if direction == "short" else 0


def _finite_or_zero(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "symmetric_trend"
    report_root = report_output_dir or reports_dir() / "research" / "symmetric_trend"
    stem = f"CF_{start}_{end}_symmetric_trend"
    return {
        "daily": data_root / f"{stem}_daily.parquet",
        "breakout_events": data_root / f"{stem}_breakout_event_horizon.parquet",
        "episodes": data_root / f"{stem}_episode.parquet",
        "breakout_summary": data_root / f"{stem}_breakout_summary.parquet",
        "episode_summary": data_root / f"{stem}_episode_summary.parquet",
        "warnings": data_root / f"{stem}_warnings.csv",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
        "manifest": data_root / f"{stem}_manifest.json",
    }


def _write_warning_csv(
    path: Path,
    warnings: tuple[SymmetricTrendWarningRecord, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for warning in warnings:
            writer.writerow(warning.to_csv_row())


def _json_safe_record(record: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
        elif value is None or (isinstance(value, float) and math.isnan(value)):
            result[key] = None
        elif isinstance(value, np.generic):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def _latest_continuous_price_path() -> Path:
    root = data_dir() / "strategy" / PRODUCT_CODE / "inputs"
    paths = sorted(root.glob("*_continuous_price_daily.parquet"))
    if not paths:
        raise ResearchWorkbenchError(f"strategy continuous price not found under {root}")
    return paths[-1]


def _latest_trend_context_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "trend_phase_v2"
    paths = sorted(root.glob("*_daily.parquet"))
    if not paths:
        raise ResearchWorkbenchError(f"trend phase v2 context not found under {root}")
    return paths[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(*, start: date, end: date) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cf_symmetric_trend_{start:%Y%m%d}_{end:%Y%m%d}_{stamp}_{uuid.uuid4().hex[:8]}"
