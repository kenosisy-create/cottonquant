"""R93I CF反弹准备、触发、确认与失败生命周期研究。"""

from __future__ import annotations

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
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
REBOUND_LIFECYCLE_VERSION = "R93I_rebound_lifecycle_v2_main_cycle_relay"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
DEFAULT_PREPARE_MAX_DAYS = 7
DEFAULT_CONFIRM_MAX_DAYS = 3
DEFAULT_FOLLOW_MAX_DAYS = 10
DEFAULT_BREAK_BUFFER_BPS = 10
DEFAULT_MIN_SAMPLE_SIZE = 30
REQUIRED_SIGNAL_HORIZONS = (1, 3, 5, 10, 20, 40)
HUMAN_REVIEW_REQUIRED = (
    "rebound_prepare_definition",
    "rebound_trigger_definition",
    "rebound_confirmation_definition",
    "rebound_failure_definition",
    "volatility_barrier_multipliers",
    "option_tenor_relay_interpretation",
)
RESEARCH_BOUNDARY = {
    "daily_state_uses_t_or_earlier": True,
    "future_paths_are_historical_posterior_labels": True,
    "enters_composite_score": False,
    "changes_existing_trend_model": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ReboundLifecycleResult:
    """R93I输出路径与生命周期摘要。"""

    run_id: str
    start: date
    end: date
    row_count: int
    episode_count: int
    triggered_episode_count: int
    confirmed_episode_count: int
    current_state: str
    current_episode_id: str | None
    current_handoff_state: str
    stability_status: str
    prepare_to_trigger_rate: float | None
    trigger_to_confirm_rate: float | None
    warning_count: int
    daily_path: Path
    episode_path: Path
    validation_path: Path
    summary_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    signal_matrix_path: Path
    symmetric_trend_daily_path: Path
    option_structure_path: Path

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": self.row_count,
            "episode_count": self.episode_count,
            "triggered_episode_count": self.triggered_episode_count,
            "confirmed_episode_count": self.confirmed_episode_count,
            "current_state": self.current_state,
            "current_episode_id": self.current_episode_id,
            "current_handoff_state": self.current_handoff_state,
            "stability_status": self.stability_status,
            "prepare_to_trigger_rate": self.prepare_to_trigger_rate,
            "trigger_to_confirm_rate": self.trigger_to_confirm_rate,
            "warning_count": self.warning_count,
            "daily_path": str(self.daily_path),
            "episode_path": str(self.episode_path),
            "validation_path": str(self.validation_path),
            "summary_path": str(self.summary_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "signal_matrix_path": str(self.signal_matrix_path),
            "symmetric_trend_daily_path": str(self.symmetric_trend_daily_path),
            "option_structure_path": str(self.option_structure_path),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
            "research_boundary": RESEARCH_BOUNDARY,
        }


def build_cf_rebound_lifecycle_research(
    *,
    signal_matrix_path: Path | None = None,
    symmetric_trend_daily_path: Path | None = None,
    option_structure_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    prepare_max_days: int = DEFAULT_PREPARE_MAX_DAYS,
    confirm_max_days: int = DEFAULT_CONFIRM_MAX_DAYS,
    follow_max_days: int = DEFAULT_FOLLOW_MAX_DAYS,
    break_buffer_bps: int = DEFAULT_BREAK_BUFFER_BPS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> ReboundLifecycleResult:
    """构建不含未来函数的反弹状态机，并单独生成历史后验路径标签。"""
    normalized_horizons = _validate_parameters(
        horizons=horizons,
        prepare_max_days=prepare_max_days,
        confirm_max_days=confirm_max_days,
        follow_max_days=follow_max_days,
        break_buffer_bps=break_buffer_bps,
        min_sample_size=min_sample_size,
    )
    matrix_path = signal_matrix_path or _latest_signal_matrix_path()
    trend_path = symmetric_trend_daily_path or _latest_symmetric_trend_path()
    option_path = option_structure_path or _latest_option_structure_path()
    matrix = load_table(
        matrix_path,
        required={"trade_date", "horizon", "main_contract", "direction"},
        label="R35 signal matrix",
    )
    trend = load_table(
        trend_path,
        required={
            "trade_date",
            "main_contract",
            "adjusted_price",
            "realized_volatility_fast",
            "participation_state",
            "roll_context",
            "trend_direction",
            "trend_stage",
            "phase_v2",
        },
        label="R93A symmetric trend daily",
    )
    option = load_table(
        option_path,
        required={
            "trade_date",
            "underlying_contract",
            "option_direction",
            "confirmation_state",
            "confirmation_strength",
        },
        label="R75 option structure daily",
    )
    features = _build_features(matrix=matrix, trend=trend, option=option)
    start = features["trade_date"].min()
    end = features["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("r93i", end)
    daily, episodes = _build_lifecycle_rows(
        features=features,
        run_id=active_run_id,
        prepare_max_days=prepare_max_days,
        confirm_max_days=confirm_max_days,
        follow_max_days=follow_max_days,
        break_buffer_bps=break_buffer_bps,
    )
    validation = _build_validation_rows(
        features=features,
        episodes=episodes,
        run_id=active_run_id,
        horizons=normalized_horizons,
        follow_max_days=follow_max_days,
    )
    summary = _build_summary_rows(
        validation=validation,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
    )
    transition = _transition_summary(episodes)
    stability_status = _stability_status(summary)
    warnings = _warning_rows(
        run_id=active_run_id,
        episodes=episodes,
        validation=validation,
        min_sample_size=min_sample_size,
        stability_status=stability_status,
    )
    paths = _paths(
        start=start,
        end=end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(episodes, paths["episode_parquet"], paths["episode_csv"])
    write_frame(validation, paths["validation_parquet"], paths["validation_csv"])
    write_frame(summary, paths["summary_parquet"], paths["summary_csv"])
    write_warning_csv(paths["warnings"], warnings)
    latest = daily.iloc[-1].to_dict()
    result = ReboundLifecycleResult(
        run_id=active_run_id,
        start=start,
        end=end,
        row_count=len(daily),
        episode_count=len(episodes),
        triggered_episode_count=int(episodes["trigger_date"].notna().sum()),
        confirmed_episode_count=int(episodes["confirm_date"].notna().sum()),
        current_state=str(latest["lifecycle_state"]),
        current_episode_id=_text_or_none(latest.get("episode_id")),
        current_handoff_state=str(latest["trend_handoff_state"]),
        stability_status=stability_status,
        prepare_to_trigger_rate=transition["prepare_to_trigger_rate"],
        trigger_to_confirm_rate=transition["trigger_to_confirm_rate"],
        warning_count=sum(1 for row in warnings if row["severity"] == "WARN"),
        daily_path=paths["daily_parquet"],
        episode_path=paths["episode_parquet"],
        validation_path=paths["validation_parquet"],
        summary_path=paths["summary_parquet"],
        warning_csv_path=paths["warnings"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        signal_matrix_path=matrix_path,
        symmetric_trend_daily_path=trend_path,
        option_structure_path=option_path,
    )
    _write_markdown(
        result=result,
        latest=latest,
        transition=transition,
        episodes=episodes,
        summary=summary,
    )
    write_json(
        result.json_path,
        {
            "report_type": "cf_rebound_lifecycle_research",
            "rule_version": REBOUND_LIFECYCLE_VERSION,
            "summary": result.to_summary(),
            "current_state": _json_record(latest),
            "transition_summary": transition,
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="cf_rebound_lifecycle_research",
            rule_version=REBOUND_LIFECYCLE_VERSION,
            data_asof=end,
            input_paths={
                "signal_matrix_path": matrix_path,
                "symmetric_trend_daily_path": trend_path,
                "option_structure_path": option_path,
            },
            output_paths={
                "daily_path": result.daily_path,
                "episode_path": result.episode_path,
                "validation_path": result.validation_path,
                "summary_path": result.summary_path,
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _build_features(
    *, matrix: pd.DataFrame, trend: pd.DataFrame, option: pd.DataFrame
) -> pd.DataFrame:
    matrix_working = normalize_trade_date(matrix)
    matrix_working["horizon"] = pd.to_numeric(
        matrix_working["horizon"], errors="coerce"
    )
    matrix_working = matrix_working.dropna(subset=["horizon"])
    matrix_working["horizon"] = matrix_working["horizon"].astype(int)
    available_horizons = set(matrix_working["horizon"])
    missing_horizons = sorted(set(REQUIRED_SIGNAL_HORIZONS) - available_horizons)
    if missing_horizons:
        raise ResearchWorkbenchError(
            f"R93I signal matrix missing horizons: {missing_horizons}"
        )
    if matrix_working.duplicated(["trade_date", "main_contract", "horizon"]).any():
        raise ResearchWorkbenchError("R93I signal matrix has duplicate date/contract/horizon")
    direction = matrix_working.pivot(
        index=["trade_date", "main_contract"],
        columns="horizon",
        values="direction",
    ).reset_index()
    direction.columns = [
        str(column)
        if str(column) in {"trade_date", "main_contract"}
        else f"direction_{int(column)}d"
        for column in direction.columns
    ]

    trend_working = normalize_trade_date(trend)
    if trend_working.duplicated(["trade_date", "main_contract"]).any():
        raise ResearchWorkbenchError("R93I symmetric trend has duplicate date/contract")
    option_working = normalize_trade_date(option)
    if "main_contract" not in option_working.columns:
        option_working["main_contract"] = option_working["underlying_contract"]
    option_working = option_working.rename(
        columns={
            "underlying_contract": "option_underlying_contract",
            "option_direction": "selected_option_direction",
            "confirmation_state": "selected_option_confirmation_state",
            "confirmation_strength": "selected_option_confirmation_strength",
        }
    )
    for column, default in (
        ("option_selection_reason", "LEGACY_MAIN_CONTRACT_FALLBACK"),
        ("option_relay_used", False),
        ("option_tenor_gap_months", 0),
    ):
        if column not in option_working.columns:
            option_working[column] = default
    option_columns = [
        "trade_date",
        "main_contract",
        "option_underlying_contract",
        "option_selection_reason",
        "option_relay_used",
        "option_tenor_gap_months",
        "selected_option_direction",
        "selected_option_confirmation_state",
        "selected_option_confirmation_strength",
    ]
    if option_working.duplicated(["trade_date", "main_contract"]).any():
        raise ResearchWorkbenchError("R93I option structure has duplicate date/contract")

    working = trend_working.merge(
        direction,
        on=["trade_date", "main_contract"],
        how="inner",
        validate="one_to_one",
    ).merge(
        option_working[option_columns],
        on=["trade_date", "main_contract"],
        how="left",
        validate="one_to_one",
    )
    working = working.sort_values("trade_date").reset_index(drop=True)
    working["adjusted_price"] = pd.to_numeric(
        working["adjusted_price"], errors="coerce"
    )
    working["realized_volatility_fast"] = pd.to_numeric(
        working["realized_volatility_fast"], errors="coerce"
    )
    if working["adjusted_price"].isna().any():
        raise ResearchWorkbenchError("R93I adjusted price contains missing values")
    working["price_return_1d"] = working["adjusted_price"].pct_change(fill_method=None)
    working["price_ma_5d"] = working["adjusted_price"].rolling(5, min_periods=5).mean()
    working["price_above_ma_5d"] = working["adjusted_price"] > working["price_ma_5d"]
    short_columns = ["direction_1d", "direction_3d", "direction_5d"]
    medium_columns = ["direction_10d", "direction_20d", "direction_40d"]
    working["short_bullish_count"] = working[short_columns].eq("long").sum(axis=1)
    working["short_bearish_count"] = working[short_columns].eq("short").sum(axis=1)
    working["medium_bullish_count"] = working[medium_columns].eq("long").sum(axis=1)
    working["option_long_confirmation"] = (
        working["selected_option_confirmation_state"].eq("CONFIRM_LONG")
        & working["selected_option_confirmation_strength"].isin(["medium", "high"])
    )
    working["participation_confirmation"] = (
        working["participation_state"].isin(["LONG_BUILD", "ROLL_TRANSFER"])
        & working["roll_context"].eq("ROLL_DOMINANT")
    )
    # 准备阶段刻画“中长期仍有多头结构、短周期完成向下挤压”，不要求价格已经反转。
    working["prepare_condition"] = (
        working["medium_bullish_count"].ge(2)
        & working["short_bearish_count"].ge(2)
        & working["price_return_1d"].notna()
    )
    # 触发与确认均只使用当日收盘后可见状态；确认至少需要期权或全链持仓之一支持。
    working["trigger_condition"] = (
        working["short_bullish_count"].ge(2)
        & working["price_return_1d"].gt(0)
        & working["price_above_ma_5d"]
    )
    working["confirm_condition"] = (
        working["short_bullish_count"].eq(3)
        & working["price_above_ma_5d"]
        & (
            working["option_long_confirmation"]
            | working["participation_confirmation"]
        )
    )
    return working


def _build_lifecycle_rows(
    *,
    features: pd.DataFrame,
    run_id: str,
    prepare_max_days: int,
    confirm_max_days: int,
    follow_max_days: int,
    break_buffer_bps: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_rows: list[dict[str, object]] = []
    episode_rows: list[dict[str, object]] = []
    active: dict[str, object] | None = None
    sequence = 0
    break_buffer = break_buffer_bps / 10_000.0

    for index, row in features.iterrows():
        trade_date = row["trade_date"]
        price = float(row["adjusted_price"])
        state = "IDLE"
        reason = "未满足反弹准备条件。"
        closed_episode: dict[str, object] | None = None

        if active is None and bool(row["prepare_condition"]):
            sequence += 1
            active = _new_episode(
                row=row,
                row_index=index,
                sequence=sequence,
                run_id=run_id,
            )
            state = "PREPARE"
            reason = "中长期至少两项偏多，1D/3D/5D至少两项偏空，进入反弹准备。"
        elif active is not None:
            active["latest_date"] = trade_date
            active_state = str(active["state"])
            if active_state == "PREPARE":
                # 触发前允许准备低点继续下移；触发后低点冻结，作为失败边界。
                active["setup_low"] = min(float(active["setup_low"]), price)
                if bool(row["trigger_condition"]):
                    active["state"] = "TRIGGER"
                    active["trigger_date"] = trade_date
                    active["trigger_index"] = index
                    active["trigger_price"] = price
                    active["option_confirmation_at_trigger"] = bool(
                        row["option_long_confirmation"]
                    )
                    active["option_relay_at_trigger"] = bool(
                        row.get("option_relay_used", False)
                    )
                    state = "TRIGGER"
                    reason = "1D与3D为主的短周期翻多，且价格收复5日均线。"
                elif index - int(active["prepare_index"]) >= prepare_max_days:
                    state = "FAIL"
                    reason = "准备后未在规定交易日内形成触发。"
                    active["terminal_status"] = "FAILED_PREPARE_TIMEOUT"
                    active["terminal_reason"] = reason
                    active["terminal_date"] = trade_date
                    closed_episode = active
                    active = None
                else:
                    state = "PREPARE"
                    reason = "准备条件已出现，等待短周期翻多并收复5日均线。"
            elif active_state == "TRIGGER":
                failed, failure_reason = _failure_condition(
                    row=row,
                    setup_low=float(active["setup_low"]),
                    break_buffer=break_buffer,
                )
                if failed:
                    state = "FAIL"
                    reason = failure_reason
                    active["terminal_status"] = "FAILED_AFTER_TRIGGER"
                    active["terminal_reason"] = reason
                    active["terminal_date"] = trade_date
                    closed_episode = active
                    active = None
                elif bool(row["confirm_condition"]):
                    active["state"] = "CONFIRM"
                    active["confirm_date"] = trade_date
                    active["confirm_index"] = index
                    active["confirm_price"] = price
                    active["option_confirmation_at_confirm"] = bool(
                        row["option_long_confirmation"]
                    )
                    active["participation_confirmation_at_confirm"] = bool(
                        row["participation_confirmation"]
                    )
                    state = "CONFIRM"
                    reason = "1D/3D/5D全部翻多，且期权或全链持仓至少一项确认。"
                elif index - int(active["trigger_index"]) >= confirm_max_days:
                    state = "FAIL"
                    reason = "触发后未在规定交易日内获得确认。"
                    active["terminal_status"] = "FAILED_CONFIRM_TIMEOUT"
                    active["terminal_reason"] = reason
                    active["terminal_date"] = trade_date
                    closed_episode = active
                    active = None
                else:
                    state = "TRIGGER"
                    reason = "反弹已触发，等待5D方向与期权/持仓确认。"
            else:
                failed, failure_reason = _failure_condition(
                    row=row,
                    setup_low=float(active["setup_low"]),
                    break_buffer=break_buffer,
                )
                if failed:
                    state = "FAIL"
                    reason = failure_reason
                    active["terminal_status"] = "CONFIRMED_THEN_FAILED"
                    active["terminal_reason"] = reason
                    active["terminal_date"] = trade_date
                    closed_episode = active
                    active = None
                elif index - int(active["confirm_index"]) >= follow_max_days:
                    state = "CONFIRM"
                    reason = "确认后的观察窗口已完成。"
                    active["terminal_status"] = "CONFIRMED_WINDOW_COMPLETE"
                    active["terminal_reason"] = reason
                    active["terminal_date"] = trade_date
                    closed_episode = active
                    active = None
                else:
                    state = "CONFIRM"
                    reason = "反弹保持确认，继续观察趋势接管或结构破坏。"

        current_episode = closed_episode or active
        if closed_episode is not None:
            episode_rows.append(_episode_record(closed_episode))
        daily_rows.append(
            _daily_record(
                row=row,
                run_id=run_id,
                state=state,
                reason=reason,
                episode=current_episode,
            )
        )

    if active is not None:
        state = str(active["state"])
        active["terminal_status"] = f"OPEN_{state}"
        active["terminal_reason"] = "样本截止日仍在观察，禁止提前写入后验结论。"
        active["terminal_date"] = None
        episode_rows.append(_episode_record(active))
    daily = pd.DataFrame(daily_rows)
    episodes = pd.DataFrame(episode_rows)
    if episodes.empty:
        raise ResearchWorkbenchError("R93I found no rebound preparation episodes")
    return daily, episodes


def _new_episode(
    *, row: pd.Series, row_index: int, sequence: int, run_id: str
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "episode_id": f"R93I_{row['trade_date']:%Y%m%d}_{sequence:04d}",
        "prepare_date": row["trade_date"],
        "prepare_index": row_index,
        "prepare_price": float(row["adjusted_price"]),
        "setup_low": float(row["adjusted_price"]),
        "trigger_date": None,
        "trigger_index": None,
        "trigger_price": None,
        "confirm_date": None,
        "confirm_index": None,
        "confirm_price": None,
        "latest_date": row["trade_date"],
        "terminal_date": None,
        "terminal_status": "OPEN_PREPARE",
        "terminal_reason": "",
        "state": "PREPARE",
        "main_contract_at_prepare": str(row["main_contract"]),
        "medium_bullish_count_at_prepare": int(row["medium_bullish_count"]),
        "short_bearish_count_at_prepare": int(row["short_bearish_count"]),
        "option_confirmation_at_trigger": False,
        "option_relay_at_trigger": False,
        "option_confirmation_at_confirm": False,
        "participation_confirmation_at_confirm": False,
    }


def _failure_condition(
    *, row: pd.Series, setup_low: float, break_buffer: float
) -> tuple[bool, str]:
    price = float(row["adjusted_price"])
    if price < setup_low * (1.0 - break_buffer):
        return True, "价格跌破准备阶段低点及缓冲边界，反弹结构失效。"
    reversal = int(row["short_bearish_count"]) >= 2 and not bool(
        row["price_above_ma_5d"]
    )
    risk_confirmation = (
        str(row.get("selected_option_direction")) == "short"
        or str(row.get("roll_context")) in {"EXIT_DOMINANT", "ROLL_WITH_NET_EXIT"}
    )
    if reversal and risk_confirmation:
        return True, "短周期重新共振转空，且期权或全链持仓风险同步。"
    return False, ""


def _daily_record(
    *,
    row: pd.Series,
    run_id: str,
    state: str,
    reason: str,
    episode: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "trade_date": row["trade_date"],
        "main_contract": row["main_contract"],
        "adjusted_price": row["adjusted_price"],
        "price_return_1d": row["price_return_1d"],
        "price_ma_5d": row["price_ma_5d"],
        "price_above_ma_5d": bool(row["price_above_ma_5d"]),
        "direction_1d": row["direction_1d"],
        "direction_3d": row["direction_3d"],
        "direction_5d": row["direction_5d"],
        "direction_10d": row["direction_10d"],
        "direction_20d": row["direction_20d"],
        "direction_40d": row["direction_40d"],
        "short_bullish_count": int(row["short_bullish_count"]),
        "short_bearish_count": int(row["short_bearish_count"]),
        "medium_bullish_count": int(row["medium_bullish_count"]),
        "prepare_condition": bool(row["prepare_condition"]),
        "trigger_condition": bool(row["trigger_condition"]),
        "confirm_condition": bool(row["confirm_condition"]),
        "lifecycle_state": state,
        "lifecycle_reason_cn": reason,
        "trend_handoff_state": _trend_handoff_state(state=state, row=row),
        "episode_id": None if episode is None else episode["episode_id"],
        "episode_setup_low": None if episode is None else episode["setup_low"],
        "option_underlying_contract": row.get("option_underlying_contract"),
        "option_selection_reason": row.get("option_selection_reason"),
        "option_relay_used": bool(row.get("option_relay_used", False)),
        "option_direction": row.get("selected_option_direction"),
        "option_confirmation_state": row.get("selected_option_confirmation_state"),
        "option_confirmation_strength": row.get(
            "selected_option_confirmation_strength"
        ),
        "option_long_confirmation": bool(row["option_long_confirmation"]),
        "participation_state": row["participation_state"],
        "participation_confirmation": bool(row["participation_confirmation"]),
        "roll_context": row["roll_context"],
        "trend_direction": row["trend_direction"],
        "trend_stage": row["trend_stage"],
        "phase_v2": row["phase_v2"],
        "rule_version": REBOUND_LIFECYCLE_VERSION,
        "state_uses_t_or_earlier": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _episode_record(episode: dict[str, object]) -> dict[str, object]:
    prepare_index = int(episode["prepare_index"])
    trigger_index = episode.get("trigger_index")
    confirm_index = episode.get("confirm_index")
    return {
        "run_id": episode["run_id"],
        "episode_id": episode["episode_id"],
        "prepare_date": episode["prepare_date"],
        "trigger_date": episode.get("trigger_date"),
        "confirm_date": episode.get("confirm_date"),
        "terminal_date": episode.get("terminal_date"),
        "terminal_status": episode["terminal_status"],
        "terminal_reason_cn": episode["terminal_reason"],
        "main_contract_at_prepare": episode["main_contract_at_prepare"],
        "prepare_price": episode["prepare_price"],
        "trigger_price": episode.get("trigger_price"),
        "confirm_price": episode.get("confirm_price"),
        "setup_low": episode["setup_low"],
        "prepare_to_trigger_days": (
            None if trigger_index is None else int(trigger_index) - prepare_index
        ),
        "trigger_to_confirm_days": (
            None
            if trigger_index is None or confirm_index is None
            else int(confirm_index) - int(trigger_index)
        ),
        "medium_bullish_count_at_prepare": episode[
            "medium_bullish_count_at_prepare"
        ],
        "short_bearish_count_at_prepare": episode[
            "short_bearish_count_at_prepare"
        ],
        "option_confirmation_at_trigger": episode[
            "option_confirmation_at_trigger"
        ],
        "option_relay_at_trigger": episode["option_relay_at_trigger"],
        "option_confirmation_at_confirm": episode[
            "option_confirmation_at_confirm"
        ],
        "participation_confirmation_at_confirm": episode[
            "participation_confirmation_at_confirm"
        ],
        "rule_version": REBOUND_LIFECYCLE_VERSION,
        "trading_instruction": "not_a_trading_instruction",
    }


def _trend_handoff_state(*, state: str, row: pd.Series) -> str:
    if state != "CONFIRM":
        return "NOT_APPLICABLE"
    if (
        str(row["trend_direction"]) == "long"
        and str(row["trend_stage"]) in {"BREAKOUT", "TREND"}
        and str(row["phase_v2"]) == "S2"
    ):
        return "TREND_HANDOFF_CONFIRMED"
    return "REBOUND_CONFIRMED_TREND_HANDOFF_NOT_CONFIRMED"


def _build_validation_rows(
    *,
    features: pd.DataFrame,
    episodes: pd.DataFrame,
    run_id: str,
    horizons: tuple[int, ...],
    follow_max_days: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    date_to_index = {
        trade_date: index for index, trade_date in enumerate(features["trade_date"])
    }
    prices = features["adjusted_price"].astype(float).reset_index(drop=True)
    volatility = features["realized_volatility_fast"].reset_index(drop=True)
    for episode in episodes.itertuples(index=False):
        if pd.isna(episode.trigger_date):
            continue
        trigger_index = date_to_index.get(episode.trigger_date)
        if trigger_index is None:
            continue
        entry_index = trigger_index + 1
        if entry_index >= len(features):
            continue
        entry_price = float(prices.iloc[entry_index])
        annual_vol = _float_or_none(volatility.iloc[trigger_index])
        daily_vol = 0.0 if annual_vol is None else max(annual_vol, 0.0) / math.sqrt(252)
        upper_barrier = max(0.008, 1.5 * daily_vol)
        lower_barrier = max(0.006, 1.0 * daily_vol)
        barrier = _barrier_label(
            prices=prices,
            entry_index=entry_index,
            entry_price=entry_price,
            upper_barrier=upper_barrier,
            lower_barrier=lower_barrier,
            max_days=follow_max_days,
        )
        for horizon in horizons:
            exit_index = entry_index + horizon
            if exit_index >= len(features):
                continue
            path = prices.iloc[entry_index + 1 : exit_index + 1] / entry_price - 1.0
            forward_return = float(prices.iloc[exit_index] / entry_price - 1.0)
            rows.append(
                {
                    "run_id": run_id,
                    "episode_id": episode.episode_id,
                    "prepare_date": episode.prepare_date,
                    "trigger_date": episode.trigger_date,
                    "trigger_year": episode.trigger_date.year,
                    "confirm_date": episode.confirm_date,
                    "entry_date": features.iloc[entry_index]["trade_date"],
                    "exit_date": features.iloc[exit_index]["trade_date"],
                    "horizon": horizon,
                    "forward_return": forward_return,
                    "directional_hit": forward_return > 0,
                    "mfe": None if path.empty else float(path.max()),
                    "mae": None if path.empty else float(path.min()),
                    "upper_barrier": upper_barrier,
                    "lower_barrier": lower_barrier,
                    "barrier_label": barrier["label"],
                    "barrier_resolution_days": barrier["resolution_days"],
                    "terminal_status": episode.terminal_status,
                    "option_confirmation_at_trigger": bool(
                        episode.option_confirmation_at_trigger
                    ),
                    "option_relay_at_trigger": bool(episode.option_relay_at_trigger),
                    "forward_paths_are_historical_posterior_labels": True,
                    "execution_timing": "T+1_adjusted_price_observation",
                    "rule_version": REBOUND_LIFECYCLE_VERSION,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    columns = [
        "run_id",
        "episode_id",
        "prepare_date",
        "trigger_date",
        "trigger_year",
        "confirm_date",
        "entry_date",
        "exit_date",
        "horizon",
        "forward_return",
        "directional_hit",
        "mfe",
        "mae",
        "upper_barrier",
        "lower_barrier",
        "barrier_label",
        "barrier_resolution_days",
        "terminal_status",
        "option_confirmation_at_trigger",
        "option_relay_at_trigger",
        "forward_paths_are_historical_posterior_labels",
        "execution_timing",
        "rule_version",
        "trading_instruction",
    ]
    return pd.DataFrame(rows, columns=columns)


def _barrier_label(
    *,
    prices: pd.Series,
    entry_index: int,
    entry_price: float,
    upper_barrier: float,
    lower_barrier: float,
    max_days: int,
) -> dict[str, object]:
    end_index = min(entry_index + max_days, len(prices) - 1)
    for index in range(entry_index + 1, end_index + 1):
        value = float(prices.iloc[index] / entry_price - 1.0)
        if value >= upper_barrier:
            return {"label": "UPPER_BARRIER", "resolution_days": index - entry_index}
        if value <= -lower_barrier:
            return {"label": "LOWER_BARRIER", "resolution_days": index - entry_index}
    if end_index - entry_index < max_days:
        return {"label": "NO_COMPLETE_FORWARD_WINDOW", "resolution_days": None}
    return {"label": "VERTICAL_BARRIER", "resolution_days": max_days}


def _build_summary_rows(
    *, validation: pd.DataFrame, run_id: str, min_sample_size: int
) -> pd.DataFrame:
    columns = [
        "run_id",
        "grouping",
        "group_value",
        "horizon",
        "sample_count",
        "hit_rate",
        "mean_forward_return",
        "median_forward_return",
        "mean_mfe",
        "mean_mae",
        "upper_barrier_rate",
        "lower_barrier_rate",
        "evidence_level",
        "rule_version",
    ]
    if validation.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    groups = [("ALL", "ALL", validation)]
    for value, group in validation.groupby("option_confirmation_at_trigger"):
        groups.append(("option_confirmation_at_trigger", str(bool(value)), group))
    for value, group in validation.groupby("trigger_year"):
        groups.append(("trigger_year", str(int(value)), group))
    for grouping, value, frame in groups:
        for horizon, group in frame.groupby("horizon"):
            count = len(group)
            rows.append(
                {
                    "run_id": run_id,
                    "grouping": grouping,
                    "group_value": value,
                    "horizon": int(horizon),
                    "sample_count": count,
                    "hit_rate": float(group["directional_hit"].mean()),
                    "mean_forward_return": float(group["forward_return"].mean()),
                    "median_forward_return": float(group["forward_return"].median()),
                    "mean_mfe": float(group["mfe"].mean()),
                    "mean_mae": float(group["mae"].mean()),
                    "upper_barrier_rate": float(
                        group["barrier_label"].eq("UPPER_BARRIER").mean()
                    ),
                    "lower_barrier_rate": float(
                        group["barrier_label"].eq("LOWER_BARRIER").mean()
                    ),
                    "evidence_level": (
                        "WATCH" if count >= min_sample_size else "WEAK_OR_SMALL_SAMPLE"
                    ),
                    "rule_version": REBOUND_LIFECYCLE_VERSION,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _transition_summary(episodes: pd.DataFrame) -> dict[str, object]:
    prepare_count = len(episodes)
    trigger_count = int(episodes["trigger_date"].notna().sum())
    confirm_count = int(episodes["confirm_date"].notna().sum())
    triggered = episodes.loc[episodes["trigger_date"].notna()]
    confirmed = episodes.loc[episodes["confirm_date"].notna()]
    return {
        "prepare_episode_count": prepare_count,
        "triggered_episode_count": trigger_count,
        "confirmed_episode_count": confirm_count,
        "prepare_to_trigger_rate": _safe_ratio(trigger_count, prepare_count),
        "trigger_to_confirm_rate": _safe_ratio(confirm_count, trigger_count),
        "median_prepare_to_trigger_days": _median_or_none(
            triggered["prepare_to_trigger_days"]
        ),
        "median_trigger_to_confirm_days": _median_or_none(
            confirmed["trigger_to_confirm_days"]
        ),
    }


def _stability_status(summary: pd.DataFrame) -> str:
    annual = summary.loc[
        summary["grouping"].eq("trigger_year")
        & summary["horizon"].isin([5, 10, 20])
        & summary["sample_count"].ge(3)
    ].copy()
    if annual.empty:
        return "WATCH_INSUFFICIENT_ANNUAL_EVIDENCE"
    severe_failure = (
        annual["hit_rate"].lt(0.40) & annual["mean_forward_return"].lt(0)
    ).any()
    if severe_failure:
        return "WEAK_OR_UNSTABLE"
    year_count = annual["group_value"].nunique()
    positive_year_ratio = float(annual["mean_forward_return"].gt(0).mean())
    if year_count >= 4 and positive_year_ratio >= 0.75:
        return "WATCH"
    return "WATCH_INSUFFICIENT_ANNUAL_EVIDENCE"


def _warning_rows(
    *,
    run_id: str,
    episodes: pd.DataFrame,
    validation: pd.DataFrame,
    min_sample_size: int,
    stability_status: str,
) -> list[dict[str, object]]:
    triggered_count = int(episodes["trigger_date"].notna().sum())
    open_count = int(episodes["terminal_status"].astype(str).str.startswith("OPEN_").sum())
    relay_count = int(episodes["option_relay_at_trigger"].fillna(False).astype(bool).sum())
    return [
        {
            "run_id": run_id,
            "section": "annual_stability",
            "severity": "WARN" if stability_status == "WEAK_OR_UNSTABLE" else "INFO",
            "warning_code": "R93I_ANNUAL_STABILITY_STATUS",
            "warning_message": (
                "年度窗口存在显著失效时，整体命中率不得解释为稳定优势。"
            ),
            "affected_count": int(stability_status == "WEAK_OR_UNSTABLE"),
            "human_review_required": "rebound_rule_annual_stability",
        },
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R93I_EVENT_LABELS_SEPARATED",
            "warning_message": (
                "日度状态只使用T日及以前信息；T+1收益、MFE、MAE和障碍标签"
                "仅存在于历史后验验证表。"
            ),
            "affected_count": len(validation),
            "human_review_required": "rebound_lifecycle_interpretation",
        },
        {
            "run_id": run_id,
            "section": "sample_size",
            "severity": "WARN" if triggered_count < min_sample_size else "INFO",
            "warning_code": "R93I_TRIGGER_SAMPLE_SIZE",
            "warning_message": "触发episode不足门槛时，命中率与障碍结果只能作为观察。",
            "affected_count": triggered_count,
            "human_review_required": "rebound_trigger_definition",
        },
        {
            "run_id": run_id,
            "section": "current_episode",
            "severity": "INFO",
            "warning_code": "R93I_OPEN_EPISODE_CURRENT_ONLY",
            "warning_message": "开放episode只展示当前状态，不提前写入结果。",
            "affected_count": open_count,
            "human_review_required": "",
        },
        {
            "run_id": run_id,
            "section": "option_tenor",
            "severity": "INFO",
            "warning_code": "R93I_OPTION_RELAY_EPISODES",
            "warning_message": "期权接力只修复观察期限，不改变反弹主状态规则。",
            "affected_count": relay_count,
            "human_review_required": "option_tenor_relay_interpretation",
        },
    ]


def _write_markdown(
    *,
    result: ReboundLifecycleResult,
    latest: dict[str, object],
    transition: dict[str, object],
    episodes: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    lines = [
        f"# CF反弹生命周期研究 R93I - {result.end.isoformat()}",
        "",
        "## 当前状态",
        "",
        f"- 生命周期：`{latest['lifecycle_state']}`；episode："
        f"`{latest.get('episode_id') or '-'}`",
        f"- 历史稳定性：`{result.stability_status}`",
        f"- 趋势接管：`{latest['trend_handoff_state']}`",
        f"- 规则解释：{latest['lifecycle_reason_cn']}",
        f"- 期货主力 / 期权采用标的：`{latest['main_contract']}` / "
        f"`{latest.get('option_underlying_contract') or '-'}`",
        f"- 1D/3D/5D方向：`{latest['direction_1d']}` / "
        f"`{latest['direction_3d']}` / `{latest['direction_5d']}`",
        f"- 10D/20D/40D方向：`{latest['direction_10d']}` / "
        f"`{latest['direction_20d']}` / `{latest['direction_40d']}`",
        f"- 期权确认：`{latest.get('option_confirmation_state')}` / "
        f"`{latest.get('option_confirmation_strength')}`；全链持仓："
        f"`{latest.get('participation_state')}` / `{latest.get('roll_context')}`",
        "",
        "## 状态转移",
        "",
        f"- PREPARE episode：`{transition['prepare_episode_count']}`",
        f"- PREPARE -> TRIGGER：`{transition['triggered_episode_count']}` / "
        f"`{fmt_percent(transition['prepare_to_trigger_rate'])}`",
        f"- TRIGGER -> CONFIRM：`{transition['confirmed_episode_count']}` / "
        f"`{fmt_percent(transition['trigger_to_confirm_rate'])}`",
        f"- 中位准备至触发：`{fmt_number(transition['median_prepare_to_trigger_days'], 1)}`"
        "个交易日；中位触发至确认："
        f"`{fmt_number(transition['median_trigger_to_confirm_days'], 1)}`个交易日",
        "",
        "## 历史后验路径",
        "",
        "| 分组 | 周期 | 样本 | 命中率 | 平均收益 | 平均MFE | 平均MAE | 上障碍 | 下障碍 | 证据 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    all_rows = summary.loc[summary["grouping"].eq("ALL")].sort_values("horizon")
    for row in all_rows.to_dict(orient="records"):
        lines.append(
            f"| 全部触发 | {row['horizon']}D | {row['sample_count']} | "
            f"{fmt_percent(row['hit_rate'])} | {fmt_percent(row['mean_forward_return'])} | "
            f"{fmt_percent(row['mean_mfe'])} | {fmt_percent(row['mean_mae'])} | "
            f"{fmt_percent(row['upper_barrier_rate'])} | "
            f"{fmt_percent(row['lower_barrier_rate'])} | {row['evidence_level']} |"
        )
    annual = summary.loc[
        summary["grouping"].eq("trigger_year")
        & summary["horizon"].isin([5, 10, 20])
    ].sort_values(["group_value", "horizon"])
    lines.extend(
        [
            "",
            "## 年度稳定性",
            "",
            "| 年度 | 周期 | 样本 | 命中率 | 平均收益 | 证据 |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in annual.to_dict(orient="records"):
        lines.append(
            f"| {row['group_value']} | {row['horizon']}D | {row['sample_count']} | "
            f"{fmt_percent(row['hit_rate'])} | "
            f"{fmt_percent(row['mean_forward_return'])} | {row['evidence_level']} |"
        )
    recent = episodes.sort_values("prepare_date").tail(8)
    lines.extend(
        [
            "",
            "## 最近episode",
            "",
            "| 准备日 | 触发日 | 确认日 | 状态 | 说明 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in recent.to_dict(orient="records"):
        lines.append(
            f"| {row['prepare_date']} | {row.get('trigger_date') or '-'} | "
            f"{row.get('confirm_date') or '-'} | {row['terminal_status']} | "
            f"{row['terminal_reason_cn']} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- PREPARE/TRIGGER/CONFIRM/FAIL是研究状态，不是开平仓指令。",
            "- `CONFIRM`只表示反弹路径确认；只有趋势方向、阶段与R76同时满足时，"
            "才标记趋势接管确认。",
            "- 日度状态不读取未来数据；T+1收益、MFE、MAE和波动率障碍仅为历史后验标签。",
            "- 期权期限接力只恢复有效结构观察，不进入`composite_score`。",
            "- 本版本先冻结规则并检验年度稳定性，不根据本轮反弹结果反向调参。",
            "- 研究仿真不构成交易指令。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_output_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_rebound_lifecycle"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "rebound_lifecycle"
    report_root = report_output_dir or reports_dir() / "research" / "rebound_lifecycle"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "episode_parquet": data_root / f"{stem}_episodes.parquet",
        "episode_csv": data_root / f"{stem}_episodes.csv",
        "validation_parquet": data_root / f"{stem}_validation.parquet",
        "validation_csv": data_root / f"{stem}_validation.csv",
        "summary_parquet": data_root / f"{stem}_summary.parquet",
        "summary_csv": data_root / f"{stem}_summary.csv",
        "warnings": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _latest_signal_matrix_path() -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "signal_matrix",
        "*_signal_matrix_daily.parquet",
        label="R35 signal matrix",
    )


def _latest_symmetric_trend_path() -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "symmetric_trend",
        "*_symmetric_trend_daily.parquet",
        label="R93A symmetric trend daily",
    )


def _latest_option_structure_path() -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "option_structure",
        "*_option_structure_daily.parquet",
        label="R75 option structure daily",
    )


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    prepare_max_days: int,
    confirm_max_days: int,
    follow_max_days: int,
    break_buffer_bps: int,
    min_sample_size: int,
) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in horizons)))
    if not normalized or any(value <= 0 for value in normalized):
        raise ResearchWorkbenchError("R93I horizons must contain positive integers")
    for name, value in (
        ("prepare_max_days", prepare_max_days),
        ("confirm_max_days", confirm_max_days),
        ("follow_max_days", follow_max_days),
        ("min_sample_size", min_sample_size),
    ):
        if value <= 0:
            raise ResearchWorkbenchError(f"R93I {name} must be positive")
    if break_buffer_bps < 0:
        raise ResearchWorkbenchError("R93I break_buffer_bps must be non-negative")
    return normalized


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _median_or_none(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.median())


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _text_or_none(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value)
    return text if text else None


def _json_record(record: dict[str, object]) -> dict[str, object]:
    return {
        key: None if value is None or _is_scalar_missing(value) else value
        for key, value in record.items()
    }


def _is_scalar_missing(value: object) -> bool:
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(missing, bool):
        return missing
    if hasattr(missing, "item"):
        try:
            return bool(missing.item())
        except (TypeError, ValueError):
            return False
    return False
