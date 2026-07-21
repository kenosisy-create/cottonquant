"""R77 current CF watch window from R73-R76 evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    latest_matching_path,
    load_table,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
CURRENT_WATCH_WINDOW_VERSION = "R77_current_watch_window_v2"
HUMAN_REVIEW_REQUIRED = (
    "watch_level_interpretation",
    "provisional_follow_up_dates",
    "trend_phase_v2_interpretation",
    "chain_oi_participation_interpretation",
    "multi_day_roll_context_interpretation",
    "option_confirmation_interpretation",
    "publish_wording",
)
RESEARCH_BOUNDARY = {
    "forward_returns_are_validation_labels": True,
    "latest_state_uses_future_data": False,
    "follow_up_dates_are_provisional_business_days": True,
    "auto_reverse_allowed": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchCurrentWatchWindowResult:
    """R77 daily watch-window outputs."""

    run_id: str
    data_asof: date
    main_contract: str
    phase_v2: str
    watch_status: str
    expected_resolution_days: float | None
    warning_count: int
    watch_parquet_path: Path
    watch_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    daily_markdown_path: Path
    json_path: Path
    manifest_path: Path
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "data_asof": self.data_asof.isoformat(),
            "main_contract": self.main_contract,
            "phase_v2": self.phase_v2,
            "watch_status": self.watch_status,
            "expected_resolution_days": self.expected_resolution_days,
            "warning_count": self.warning_count,
            "watch_parquet_path": str(self.watch_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "daily_markdown_path": str(self.daily_markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_current_watch_window(
    *,
    latest_signal_json_path: Path | None = None,
    dual_price_path: Path | None = None,
    chain_oi_path: Path | None = None,
    option_structure_path: Path | None = None,
    trend_phase_v2_path: Path | None = None,
    playbook_json_path: Path | None = None,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    daily_output_root: Path | None = None,
    run_id: str | None = None,
) -> ResearchCurrentWatchWindowResult:
    """Build the current confirmation, invalidation and follow-up watch window."""
    latest_path = latest_signal_json_path or _default_latest_signal_path()
    resolved_dual = dual_price_path or _default_data_path("dual_price_state", "*_daily.parquet")
    resolved_oi = chain_oi_path or _default_data_path("chain_oi_structure", "*_daily.parquet")
    resolved_option = option_structure_path or _default_data_path(
        "option_structure", "*_daily.parquet"
    )
    resolved_phase = trend_phase_v2_path or _default_data_path("trend_phase_v2", "*_daily.parquet")
    resolved_core = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    latest_signal = _load_latest_signal(latest_path)
    dual = _latest_row(resolved_dual, "R73 dual price")
    oi = _latest_row(resolved_oi, "R74 chain OI")
    option = _latest_row(resolved_option, "R75 option structure")
    phase = _latest_row(resolved_phase, "R76 trend phase v2")
    data_asof = date.fromisoformat(str(latest_signal["data_asof"]))
    for label, row in (("R73", dual), ("R74", oi), ("R75", option), ("R76", phase)):
        if row["trade_date"] != data_asof:
            raise ResearchWorkbenchError(
                f"{label} latest date {row['trade_date']} does not match latest signal {data_asof}"
            )
    quotes = load_table(
        resolved_core,
        required={"trade_date", "contract_code", "high", "low", "close", "settle"},
        label="CF core quote",
    )
    playbook = _load_playbook(playbook_json_path)
    watch_row = _watch_row(
        data_asof=data_asof,
        latest_signal=latest_signal,
        dual=dual,
        oi=oi,
        option=option,
        phase=phase,
        quotes=quotes,
        playbook=playbook,
    )
    active_run_id = run_id or utc_timestamp_id("r77", data_asof)
    watch_row["run_id"] = active_run_id
    watch = pd.DataFrame([watch_row])
    warnings = _warning_rows(watch_row=watch_row, run_id=active_run_id)
    paths = _paths(
        data_asof=data_asof,
        output_dir=output_dir,
        report_dir=report_output_dir,
        daily_root=daily_output_root,
    )
    write_frame(watch, paths["watch_parquet"], paths["watch_csv"])
    write_warning_csv(paths["warning_csv"], warnings)
    _write_markdown(path=paths["markdown"], row=watch_row)
    paths["daily_markdown"].parent.mkdir(parents=True, exist_ok=True)
    paths["daily_markdown"].write_text(
        paths["markdown"].read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = ResearchCurrentWatchWindowResult(
        run_id=active_run_id,
        data_asof=data_asof,
        main_contract=str(watch_row["main_contract"]),
        phase_v2=str(watch_row["phase_v2"]),
        watch_status=str(watch_row["watch_status"]),
        expected_resolution_days=(
            None
            if watch_row["expected_resolution_days"] is None
            else float(watch_row["expected_resolution_days"])
        ),
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        watch_parquet_path=paths["watch_parquet"],
        watch_csv_path=paths["watch_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        daily_markdown_path=paths["daily_markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    write_json(
        result.json_path,
        {
            "report_type": "current_watch_window",
            "rule_version": CURRENT_WATCH_WINDOW_VERSION,
            "summary": result.to_summary(),
            "watch_window": watch_row,
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="current_watch_window",
            rule_version=CURRENT_WATCH_WINDOW_VERSION,
            data_asof=data_asof,
            input_paths={
                "latest_signal_json_path": latest_path,
                "dual_price_path": resolved_dual,
                "chain_oi_path": resolved_oi,
                "option_structure_path": resolved_option,
                "trend_phase_v2_path": resolved_phase,
                "playbook_json_path": playbook_json_path,
                "core_quote_path": resolved_core,
            },
            output_paths={
                "watch_parquet_path": result.watch_parquet_path,
                "markdown_path": result.markdown_path,
                "daily_markdown_path": result.daily_markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _watch_row(
    *, data_asof: date, latest_signal: dict[str, object], dual: dict[str, object],
    oi: dict[str, object], option: dict[str, object], phase: dict[str, object],
    quotes: pd.DataFrame, playbook: dict[str, object] | None
) -> dict[str, object]:
    main_contract = str(phase["main_contract"])
    quote_working = normalize_trade_date(quotes)
    quote_working = quote_working.loc[
        quote_working["contract_code"].astype(str).eq(main_contract)
        & quote_working["trade_date"].le(data_asof)
    ].sort_values("trade_date")
    recent = quote_working.tail(6)
    previous = recent.iloc[:-1] if len(recent) > 1 else recent
    previous_high = (
        float(pd.to_numeric(previous["high"], errors="coerce").max())
        if not previous.empty
        else None
    )
    previous_low = (
        float(pd.to_numeric(previous["low"], errors="coerce").min())
        if not previous.empty
        else None
    )
    ma_values = [dual.get("close_ma"), dual.get("settle_ma")]
    available_ma = [float(value) for value in ma_values if value is not None and not pd.isna(value)]
    mapping = _playbook_mapping(playbook, horizon=20, data_asof=data_asof)
    expected_resolution = mapping.get("matched_average_resolution_horizon")
    if expected_resolution is None:
        expected_resolution = 5.0
    follow_up_dates = {
        f"t_plus_{horizon}": (
            pd.Timestamp(data_asof) + pd.offsets.BDay(horizon)
        ).date().isoformat()
        for horizon in (1, 3, 5)
    }
    phase_v2 = str(phase["phase_v2"])
    quality = str(phase["phase_quality"])
    phase_direction = str(phase.get("phase_direction", "neutral"))
    if phase_direction not in {"long", "short"}:
        latest_direction = str(latest_signal.get("signal_direction", "long"))
        phase_direction = latest_direction if latest_direction in {"long", "short"} else "long"
    if phase_v2 == "S2" and quality in {"strong", "medium"}:
        watch_status = "TREND_CONFIRMATION_WATCH"
    elif phase_v2 == "S3":
        watch_status = "EXHAUSTION_OR_FAILURE_WATCH"
    elif phase_v2 == "S4":
        watch_status = "END_CONFIRMATION_REVIEW"
    else:
        watch_status = "START_OR_REPAIR_WATCH"
    if phase_direction == "short":
        confirmation_level = previous_low
        invalidation_level = max(available_ma) if available_ma else None
        strong_invalidation_level = previous_high
        confirmation_conditions = [
            "收盘与结算同步跌破并维持在各自20日均线下方（BOTH_BELOW）",
            "价格跌破近期确认位，且全链持仓转为 SHORT_BUILD 或继续有效增仓",
            "期权转为或维持 CONFIRM_SHORT，且强度不低于 medium",
            "3D/5D 动量维持 short",
        ]
        invalidation_conditions = [
            "收盘与结算同步站回各自20日均线上方（BOTH_ABOVE）",
            "全链持仓不再支持空向参与，或多日移仓上下文转为 ROLL_DOMINANT",
            "10D/20D 方向翻多或期权结构转为明确 long",
        ]
    else:
        confirmation_level = previous_high
        invalidation_level = min(available_ma) if available_ma else None
        strong_invalidation_level = previous_low
        confirmation_conditions = [
            "收盘与结算同步站回并维持在各自20日均线上方（BOTH_ABOVE）",
            "价格突破近期确认位，且全链持仓不再下降或多日移仓转为 ROLL_DOMINANT",
            "期权转为或维持 CONFIRM_LONG，且强度不低于 medium",
            "3D/5D 动量由 neutral/short 恢复为 long",
        ]
        invalidation_conditions = [
            "收盘与结算同步跌破各自20日均线（BOTH_BELOW）",
            "全链持仓状态恶化为 SHORT_BUILD/LONG_LIQUIDATION，或多日移仓上下文转为 "
            f"EXIT_DOMINANT（当前 {oi.get('participation_state')} / {oi.get('roll_context')}）",
            "10D/20D 方向翻空或期权结构转为明确 short",
        ]
    latest_summary = latest_signal.get("summary")
    latest_summary_dict = latest_summary if isinstance(latest_summary, dict) else {}
    return {
        "product_code": PRODUCT_CODE,
        "trade_date": data_asof,
        "main_contract": main_contract,
        "phase_v2": phase_v2,
        "phase_v2_label": phase.get("phase_v2_label"),
        "phase_quality": quality,
        "phase_direction": phase_direction,
        "watch_status": watch_status,
        "confirmation_level": confirmation_level,
        "invalidation_level": invalidation_level,
        "strong_invalidation_level": strong_invalidation_level,
        "dual_price_state": dual.get("dual_price_state"),
        "close_settle_gap_state": dual.get("close_settle_gap_state"),
        "participation_state": oi.get("participation_state"),
        "chain_oi_change": oi.get("chain_oi_change"),
        "chain_oi_change_adjusted": oi.get(
            "chain_oi_change_adjusted", oi.get("chain_oi_change")
        ),
        "expiry_oi_change": oi.get("expiry_oi_change"),
        "roll_context": oi.get("roll_context"),
        "roll_context_cn": oi.get("roll_context_cn"),
        "roll_lookback_days": oi.get("roll_lookback_days"),
        "main_oi_change_window": oi.get("main_oi_change_window"),
        "main_oi_change_window_adjusted": oi.get("main_oi_change_window_adjusted"),
        "chain_oi_change_window": oi.get("chain_oi_change_window"),
        "chain_oi_change_window_adjusted": oi.get(
            "chain_oi_change_window_adjusted"
        ),
        "positive_other_oi_change_window": oi.get("positive_other_oi_change_window"),
        "roll_transfer_ratio_window": oi.get("roll_transfer_ratio_window"),
        "option_direction": option.get("option_direction"),
        "option_confirmation_state": option.get("confirmation_state"),
        "option_confirmation_strength": option.get("confirmation_strength"),
        "volatility_repricing_state": option.get("volatility_repricing_state"),
        "matched_playbook_node": mapping.get("matched_node_id"),
        "matched_playbook_label_cn": mapping.get("matched_playbook_label_cn"),
        "matched_playbook_sample_count": mapping.get("matched_sample_count"),
        "expected_resolution_days": expected_resolution,
        "follow_up_t_plus_1": follow_up_dates["t_plus_1"],
        "follow_up_t_plus_3": follow_up_dates["t_plus_3"],
        "follow_up_t_plus_5": follow_up_dates["t_plus_5"],
        "follow_up_dates_are_provisional": True,
        "confirmation_conditions_cn": "；".join(confirmation_conditions),
        "invalidation_conditions_cn": "；".join(invalidation_conditions),
        "latest_signal_direction": latest_signal.get("signal_direction"),
        "latest_signal_summary_present": bool(latest_summary_dict),
        "rule_version": CURRENT_WATCH_WINDOW_VERSION,
        "forward_returns_are_validation_labels": True,
        "trading_instruction": "not_a_trading_instruction",
    }


def _load_latest_signal(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"latest signal JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("data_asof") is None:
        raise ResearchWorkbenchError("latest signal JSON missing data_asof")
    return payload


def _latest_row(path: Path, label: str) -> dict[str, object]:
    frame = load_table(path, required={"trade_date"}, label=label)
    frame = normalize_trade_date(frame).sort_values("trade_date")
    if frame.empty:
        raise ResearchWorkbenchError(f"{label} is empty")
    return frame.iloc[-1].to_dict()


def _load_playbook(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    if not path.exists():
        raise ResearchWorkbenchError(f"R71 playbook JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_type") != "futures_option_divergence_playbook":
        raise ResearchWorkbenchError("playbook JSON must be futures_option_divergence_playbook")
    return payload


def _playbook_mapping(
    playbook: dict[str, object] | None, *, horizon: int, data_asof: date
) -> dict[str, object]:
    if playbook is None:
        return {}
    rows = playbook.get("current_mapping_rows")
    if not isinstance(rows, list):
        return {}
    valid = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("data_asof")) == data_asof.isoformat()
    ]
    exact = [row for row in valid if int(row.get("horizon", -1)) == horizon]
    return exact[0] if exact else valid[0] if valid else {}


def _warning_rows(
    *, watch_row: dict[str, object], run_id: str
) -> list[dict[str, object]]:
    return [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R77_RESEARCH_ONLY",
            "warning_message": "观察窗口用于研究复核，不构成交易指令。",
            "affected_count": 1,
            "human_review_required": "watch_level_interpretation;publish_wording",
        },
        {
            "run_id": run_id,
            "section": "follow_up_dates",
            "severity": "WARN",
            "warning_code": "PROVISIONAL_BUSINESS_DAY_FOLLOW_UP",
            "warning_message": "后续日期按工作日推算，需用官方交易日历人工确认。",
            "affected_count": 3,
            "human_review_required": "provisional_follow_up_dates",
        },
        {
            "run_id": run_id,
            "section": "historical_playbook",
            "severity": "WARN" if watch_row.get("matched_playbook_node") is None else "INFO",
            "warning_code": "PLAYBOOK_MAPPING_STATUS",
            "warning_message": (
                "未接入同一数据日的 R71 映射时，预计解决周期使用默认5个交易日观察窗口。"
            ),
            "affected_count": 1 if watch_row.get("matched_playbook_node") is None else 0,
            "human_review_required": "trend_phase_v2_interpretation",
        },
    ]


def _default_latest_signal_path() -> Path:
    directory = project_root() / "runs" / "daily" / PRODUCT_CODE
    candidates = list(directory.glob("*/latest_signal_brief.json"))
    if not candidates:
        raise ResearchWorkbenchError("no latest signal brief JSON found")
    return max(candidates, key=lambda path: date.fromisoformat(path.parent.name))


def _default_data_path(directory_name: str, pattern: str) -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / directory_name,
        pattern,
        label=directory_name,
    )


def _paths(
    *, data_asof: date, output_dir: Path | None, report_dir: Path | None,
    daily_root: Path | None
) -> dict[str, Path]:
    stem = f"CF_{data_asof.isoformat()}_current_watch_window"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "current_watch_window"
    report_root = report_dir or reports_dir() / "research" / "current_watch_window"
    daily_base = daily_root or project_root() / "runs" / "daily"
    return {
        "watch_parquet": data_root / f"{stem}.parquet",
        "watch_csv": data_root / f"{stem}.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
        "daily_markdown": (
            daily_base / PRODUCT_CODE / data_asof.isoformat() / "current_watch_window.md"
        ),
    }


def _write_markdown(*, path: Path, row: dict[str, object]) -> None:
    confirmation_lines = str(row["confirmation_conditions_cn"]).replace("；", "；\n- ")
    invalidation_lines = str(row["invalidation_conditions_cn"]).replace("；", "；\n- ")
    lines = [
        f"# CF 当前观察窗口 R77 - {row['trade_date']}",
        "",
        "## 当前判断",
        "",
        f"- 主力合约：`{row['main_contract']}`",
        f"- v2 阶段：`{row['phase_v2']}` {row['phase_v2_label']} / `{row['phase_quality']}`",
        f"- 观察状态：`{row['watch_status']}`",
        f"- 双价格状态：`{row['dual_price_state']}` / `{row['close_settle_gap_state']}`",
        f"- 全链持仓：`{row['participation_state']}`，原始变化 "
        f"`{fmt_number(row['chain_oi_change'], 0)}`，剔除到期清零后 "
        f"`{fmt_number(row['chain_oi_change_adjusted'], 0)}`",
        f"- 多日移仓：`{row['roll_context']}` {row['roll_context_cn']}，承接比例 "
        f"`{fmt_number(row['roll_transfer_ratio_window'], 3)}`",
        f"- 期权结构：`{row['option_confirmation_state']}` / "
        f"`{row['option_confirmation_strength']}`，波动状态 "
        f"`{row['volatility_repricing_state']}`",
        "",
        "## 价格窗口",
        "",
        f"- 确认参考位：`{fmt_number(row['confirmation_level'], 2)}`",
        f"- 均线失效参考位：`{fmt_number(row['invalidation_level'], 2)}`",
        f"- 强失效参考位：`{fmt_number(row['strong_invalidation_level'], 2)}`",
        "",
        "## 结构确认条件",
        "",
        f"- {confirmation_lines}",
        "",
        "## 结构失效条件",
        "",
        f"- {invalidation_lines}",
        "",
        "## 复核窗口",
        "",
        f"- 历史节点：`{row['matched_playbook_node'] or '-'}` "
        f"{row['matched_playbook_label_cn'] or ''}",
        f"- 历史平均解决周期：`{fmt_number(row['expected_resolution_days'], 2)}` 个交易日",
        f"- T+1 / T+3 / T+5 暂定复核日：`{row['follow_up_t_plus_1']}` / "
        f"`{row['follow_up_t_plus_3']}` / `{row['follow_up_t_plus_5']}`",
        "",
        "## 研究边界",
        "",
        "- 后续日期按工作日暂定，必须用官方交易日历复核。",
        "- 最新状态不读取未来收益；forward return 仅用于历史后验验证。",
        "- 本模块不自动反转方向，不构成交易指令。",
        "- HUMAN_REVIEW_REQUIRED：价位、持仓、期权 proxy 和发布措辞。",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
