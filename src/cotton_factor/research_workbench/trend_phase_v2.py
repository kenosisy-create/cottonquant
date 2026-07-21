"""R76 evidence-aware trend phase engine v2 for CF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
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
TREND_PHASE_V2_VERSION = "R76_trend_phase_v2_v2"
DEFAULT_PRIMARY_HORIZON = 20
HUMAN_REVIEW_REQUIRED = (
    "trend_phase_v2_rules",
    "dual_price_state_interpretation",
    "chain_oi_participation_interpretation",
    "multi_day_roll_context_interpretation",
    "option_confirmation_interpretation",
    "historical_forward_label_interpretation",
)
RESEARCH_BOUNDARY = {
    "forward_returns_are_validation_labels": True,
    "latest_state_uses_future_data": False,
    "auto_reverse_allowed": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchTrendPhaseV2Result:
    """R76 output paths and latest phase state."""

    run_id: str
    start: date
    end: date
    row_count: int
    latest_phase: str
    latest_phase_quality: str
    latest_direction: str
    warning_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    transition_parquet_path: Path
    transition_csv_path: Path
    validation_parquet_path: Path
    validation_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    dual_price_path: Path
    chain_oi_path: Path
    option_structure_path: Path
    signal_matrix_path: Path
    validation_daily_path: Path | None
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": self.row_count,
            "latest_phase": self.latest_phase,
            "latest_phase_quality": self.latest_phase_quality,
            "latest_direction": self.latest_direction,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "transition_parquet_path": str(self.transition_parquet_path),
            "validation_parquet_path": str(self.validation_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_trend_phase_v2(
    *,
    dual_price_path: Path | None = None,
    chain_oi_path: Path | None = None,
    option_structure_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    validation_daily_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    primary_horizon: int = DEFAULT_PRIMARY_HORIZON,
) -> ResearchTrendPhaseV2Result:
    """Combine R73-R75 states into an evidence-aware S0-S4 phase engine."""
    if primary_horizon <= 0:
        raise ResearchWorkbenchError("primary_horizon must be positive")
    resolved_dual = dual_price_path or _default_path("dual_price_state", "*_daily.parquet")
    resolved_oi = chain_oi_path or _default_path("chain_oi_structure", "*_daily.parquet")
    resolved_option = option_structure_path or _default_path("option_structure", "*_daily.parquet")
    resolved_matrix = signal_matrix_path or _default_path(
        "signal_matrix", "*_signal_matrix_daily.parquet"
    )
    resolved_validation = validation_daily_path or _optional_validation_path()
    dual = load_table(
        resolved_dual,
        required={"trade_date", "main_contract", "dual_price_state", "close", "settle"},
        label="R73 dual price daily",
    )
    oi = load_table(
        resolved_oi,
        required={"trade_date", "main_contract", "participation_state", "oi_signal_v2"},
        label="R74 chain OI daily",
    )
    option = load_table(
        resolved_option,
        required={
            "trade_date",
            "underlying_contract",
            "option_direction",
            "confirmation_state",
            "confirmation_strength",
            "volatility_repricing_state",
        },
        label="R75 option structure daily",
    )
    matrix = load_table(
        resolved_matrix,
        required={
            "trade_date",
            "horizon",
            "main_contract",
            "direction",
            "momentum_signal",
            "trend_phase",
        },
        label="R35 signal matrix",
    )
    daily = _phase_rows(
        dual=dual,
        oi=oi,
        option=option,
        matrix=matrix,
        primary_horizon=primary_horizon,
    )
    if daily.empty:
        raise ResearchWorkbenchError("R76 trend phase v2 has no rows")
    start = daily["trade_date"].min()
    end = daily["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("r76", end)
    daily.insert(0, "run_id", active_run_id)
    transitions = _transition_rows(daily=daily, run_id=active_run_id)
    validation = _validation_rows(
        daily=daily,
        validation_path=resolved_validation,
        run_id=active_run_id,
    )
    warnings = _warning_rows(daily=daily, validation=validation, run_id=active_run_id)
    paths = _paths(start=start, end=end, output_dir=output_dir, report_dir=report_output_dir)
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(transitions, paths["transition_parquet"], paths["transition_csv"])
    write_frame(validation, paths["validation_parquet"], paths["validation_csv"])
    write_warning_csv(paths["warning_csv"], warnings)
    latest = daily.iloc[-1].to_dict()
    result = ResearchTrendPhaseV2Result(
        run_id=active_run_id,
        start=start,
        end=end,
        row_count=len(daily),
        latest_phase=str(latest["phase_v2"]),
        latest_phase_quality=str(latest["phase_quality"]),
        latest_direction=str(latest["phase_direction"]),
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        transition_parquet_path=paths["transition_parquet"],
        transition_csv_path=paths["transition_csv"],
        validation_parquet_path=paths["validation_parquet"],
        validation_csv_path=paths["validation_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        dual_price_path=resolved_dual,
        chain_oi_path=resolved_oi,
        option_structure_path=resolved_option,
        signal_matrix_path=resolved_matrix,
        validation_daily_path=resolved_validation,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(result=result, latest=latest, validation=validation, transitions=transitions)
    write_json(
        result.json_path,
        {
            "report_type": "trend_phase_v2",
            "rule_version": TREND_PHASE_V2_VERSION,
            "summary": result.to_summary(),
            "latest_state": latest,
            "transition_rows": transitions.tail(20).to_dict(orient="records"),
            "validation_rows": validation.to_dict(orient="records"),
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="trend_phase_v2",
            rule_version=TREND_PHASE_V2_VERSION,
            data_asof=end,
            input_paths={
                "dual_price_path": resolved_dual,
                "chain_oi_path": resolved_oi,
                "option_structure_path": resolved_option,
                "signal_matrix_path": resolved_matrix,
                "validation_daily_path": resolved_validation,
            },
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "transition_parquet_path": result.transition_parquet_path,
                "validation_parquet_path": result.validation_parquet_path,
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _phase_rows(
    *, dual: pd.DataFrame, oi: pd.DataFrame, option: pd.DataFrame, matrix: pd.DataFrame,
    primary_horizon: int
) -> pd.DataFrame:
    dual_working = normalize_trade_date(dual)
    oi_working = normalize_trade_date(oi)
    # 兼容旧版R74产物；新版优先使用多日移仓上下文区分合约迁移和真实退出。
    oi_defaults: dict[str, object] = {
        "roll_context": "NOT_CONNECTED",
        "roll_context_cn": "未接入多日移仓上下文",
        "roll_lookback_days": None,
        "main_oi_change_window": None,
        "main_oi_change_window_adjusted": None,
        "chain_oi_change_window": None,
        "chain_oi_change_window_adjusted": None,
        "chain_oi_change_adjusted": None,
        "expiry_oi_change": 0.0,
        "positive_other_oi_change_window": None,
        "roll_transfer_ratio_window": None,
    }
    for column, default in oi_defaults.items():
        if column not in oi_working.columns:
            oi_working[column] = default
    option_working = normalize_trade_date(option)
    matrix_working = normalize_trade_date(matrix)
    matrix_working["horizon"] = pd.to_numeric(matrix_working["horizon"], errors="coerce")
    primary = matrix_working.loc[matrix_working["horizon"].eq(primary_horizon)].copy()
    primary = primary[
        [
            "trade_date",
            "main_contract",
            "direction",
            "momentum_signal",
            "trend_phase",
        ]
    ].rename(
        columns={
            "direction": "futures_direction",
            "trend_phase": "phase_v1",
        }
    )
    joined = primary.merge(dual_working, on=["trade_date", "main_contract"], how="inner")
    joined = joined.merge(
        oi_working,
        on=["trade_date", "main_contract"],
        how="inner",
        suffixes=("", "_oi"),
    )
    option_columns = [
        "trade_date",
        "underlying_contract",
        "option_direction",
        "confirmation_state",
        "confirmation_strength",
        "volatility_repricing_state",
    ]
    joined = joined.merge(
        option_working[option_columns],
        left_on=["trade_date", "main_contract"],
        right_on=["trade_date", "underlying_contract"],
        how="left",
    )
    phases: list[str] = []
    labels: list[str] = []
    directions: list[str] = []
    qualities: list[str] = []
    reasons: list[str] = []
    flags_list: list[str] = []
    confirm_counts: list[int] = []
    for row in joined.itertuples(index=False):
        phase, label, direction, quality, reason, flags, count = _classify(row)
        phases.append(phase)
        labels.append(label)
        directions.append(direction)
        qualities.append(quality)
        reasons.append(reason)
        flags_list.append(";".join(flags))
        confirm_counts.append(count)
    joined["phase_v2"] = phases
    joined["phase_v2_label"] = labels
    joined["phase_direction"] = directions
    joined["phase_quality"] = qualities
    joined["phase_reason_cn"] = reasons
    joined["risk_flags"] = flags_list
    joined["confirmation_count"] = confirm_counts
    joined["transition_code_v2"] = (
        joined["phase_v2"].shift(1).fillna("START") + "_TO_" + joined["phase_v2"]
    )
    joined["rule_version"] = TREND_PHASE_V2_VERSION
    joined["forward_returns_are_validation_labels"] = True
    joined["trading_instruction"] = "not_a_trading_instruction"
    columns = [
        "trade_date",
        "main_contract",
        "phase_v1",
        "phase_v2",
        "phase_v2_label",
        "phase_direction",
        "phase_quality",
        "phase_reason_cn",
        "risk_flags",
        "confirmation_count",
        "transition_code_v2",
        "futures_direction",
        "momentum_signal",
        "dual_price_state",
        "close_settle_gap_state",
        "close",
        "settle",
        "close_ma",
        "settle_ma",
        "participation_state",
        "oi_signal_v2",
        "chain_oi_change",
        "chain_oi_change_adjusted",
        "expiry_oi_change",
        "roll_transfer_ratio",
        "roll_context",
        "roll_context_cn",
        "roll_lookback_days",
        "main_oi_change_window",
        "main_oi_change_window_adjusted",
        "chain_oi_change_window",
        "chain_oi_change_window_adjusted",
        "positive_other_oi_change_window",
        "roll_transfer_ratio_window",
        "option_direction",
        "confirmation_state",
        "confirmation_strength",
        "volatility_repricing_state",
        "rule_version",
        "forward_returns_are_validation_labels",
        "trading_instruction",
    ]
    return joined[columns].sort_values("trade_date").reset_index(drop=True)


def _classify(row: object) -> tuple[str, str, str, str, str, list[str], int]:
    futures_direction = str(getattr(row, "futures_direction"))
    momentum = str(getattr(row, "momentum_signal"))
    dual_state = str(getattr(row, "dual_price_state"))
    participation = str(getattr(row, "participation_state"))
    roll_context = str(getattr(row, "roll_context", "NOT_CONNECTED"))
    option_direction = str(getattr(row, "option_direction"))
    option_strength = str(getattr(row, "confirmation_strength"))
    flags: list[str] = []
    if dual_state in {"BOTH_BELOW", "CLOSE_BREAK_SETTLE_HOLD"}:
        flags.append("PRICE_BREAK_RISK")
    if roll_context == "ROLL_DOMINANT":
        flags.append("ROLL_TRANSFER_CONTEXT")
    elif roll_context == "ROLL_WITH_NET_EXIT":
        flags.append("ROLL_WITH_NET_EXIT")
    elif roll_context == "EXIT_DOMINANT":
        flags.append("CHAIN_OI_EXIT")
    elif participation in {"LONG_LIQUIDATION", "SHORT_COVER_OR_EXIT"}:
        flags.append("CHAIN_OI_EXIT")
    if participation == "SHORT_BUILD":
        flags.append("SHORT_BUILD")
    if option_direction not in {futures_direction, "neutral", "nan"}:
        flags.append("OPTION_DIVERGENCE")
    if str(getattr(row, "volatility_repricing_state")) == "LOW_VOL_UNPRICED":
        flags.append("LOW_VOL_UNPRICED")
    long_confirmations = sum(
        [
            futures_direction == "long",
            momentum == "long",
            dual_state == "BOTH_ABOVE",
            participation in {"LONG_BUILD", "ROLL_TRANSFER"}
            or roll_context == "ROLL_DOMINANT",
            option_direction == "long" and option_strength in {"medium", "high"},
        ]
    )
    short_confirmations = sum(
        [
            futures_direction == "short",
            momentum == "short",
            dual_state == "BOTH_BELOW",
            participation == "SHORT_BUILD",
            option_direction == "short" and option_strength in {"medium", "high"},
        ]
    )
    # 多日全链退出优先于单日移仓标签，不能被价格或期权确认数量覆盖。
    funding_exit_blocks_trend = (
        roll_context in {"EXIT_DOMINANT", "ROLL_WITH_NET_EXIT"}
        or (
            participation in {"LONG_LIQUIDATION", "SHORT_COVER_OR_EXIT"}
            and roll_context != "ROLL_DOMINANT"
        )
        or participation == "SHORT_BUILD"
    )
    if short_confirmations >= 4 and dual_state == "BOTH_BELOW":
        return (
            "S4",
            "终点确认",
            "short",
            "strong",
            "双价格破位，短向动量、持仓或期权结构形成多数确认。",
            flags,
            short_confirmations,
        )
    if (
        futures_direction == "long"
        and dual_state == "BOTH_ABOVE"
        and long_confirmations >= 4
        and not funding_exit_blocks_trend
    ):
        quality = "strong" if participation == "LONG_BUILD" else "medium"
        return (
            "S2",
            "趋势中",
            "long",
            quality,
            "双价格站稳，中周期方向、动量及资金/期权多数确认。",
            flags,
            long_confirmations,
        )
    if futures_direction == "long" and (
        dual_state != "BOTH_ABOVE"
        or roll_context in {"EXIT_DOMINANT", "ROLL_WITH_NET_EXIT"}
        or (
            participation in {"LONG_LIQUIDATION", "SHORT_COVER_OR_EXIT"}
            and roll_context != "ROLL_DOMINANT"
        )
        or momentum == "short"
    ):
        if roll_context == "ROLL_WITH_NET_EXIT":
            reason = "中周期仍偏多，主力移仓承接明显但全链仍净退出，趋势资金质量不足。"
        elif roll_context == "EXIT_DOMINANT":
            reason = "中周期仍偏多，但主力减仓主要表现为全链资金退出。"
        else:
            reason = "中周期仍偏多，但价格、短周期动量或全链持仓存在破坏。"
        return (
            "S3",
            "衰竭观察",
            "long",
            "weak",
            reason,
            flags,
            long_confirmations,
        )
    if futures_direction == "long" and long_confirmations >= 2:
        quality = "medium" if long_confirmations >= 3 else "weak"
        return (
            "S1",
            "起点观察",
            "long",
            quality,
            "多头结构正在修复，但尚未形成双价格、资金与期权完整共振。",
            flags,
            long_confirmations,
        )
    if short_confirmations >= 2:
        return (
            "S3",
            "反向风险观察",
            "short",
            "weak",
            "空向确认增加，但尚未满足终点确认条件。",
            flags,
            short_confirmations,
        )
    return (
        "S0",
        "未确认",
        "neutral",
        "weak",
        "多层证据分歧，无法确认趋势阶段。",
        flags,
        max(long_confirmations, short_confirmations),
    )


def _transition_rows(*, daily: pd.DataFrame, run_id: str) -> pd.DataFrame:
    changed = daily["phase_v2"].ne(daily["phase_v2"].shift(1))
    rows = daily.loc[
        changed,
        [
            "trade_date",
            "main_contract",
            "phase_v1",
            "phase_v2",
            "phase_quality",
            "transition_code_v2",
            "phase_reason_cn",
            "risk_flags",
        ],
    ].copy()
    rows.insert(0, "run_id", run_id)
    rows["trading_instruction"] = "not_a_trading_instruction"
    return rows.reset_index(drop=True)


def _validation_rows(
    *, daily: pd.DataFrame, validation_path: Path | None, run_id: str
) -> pd.DataFrame:
    columns = [
        "run_id",
        "phase_v2",
        "phase_quality",
        "roll_context",
        "horizon",
        "sample_count",
        "directional_hit_rate",
        "mean_forward_return",
        "median_forward_return",
        "forward_returns_are_validation_labels",
        "trading_instruction",
    ]
    if validation_path is None:
        return pd.DataFrame(columns=columns)
    validation = load_table(
        validation_path,
        required={
            "trade_date",
            "horizon",
            "main_contract",
            "forward_return",
            "forward_label_available",
            "directional_hit",
        },
        label="R36 validation daily",
    )
    validation = normalize_trade_date(validation)
    joined = validation.merge(
        daily[
            [
                "trade_date",
                "main_contract",
                "phase_v2",
                "phase_quality",
                "roll_context",
            ]
        ],
        on=["trade_date", "main_contract"],
        how="inner",
    )
    joined = joined.loc[joined["forward_label_available"].fillna(False).astype(bool)].copy()
    joined["forward_return"] = pd.to_numeric(joined["forward_return"], errors="coerce")
    joined["directional_hit"] = pd.to_numeric(joined["directional_hit"], errors="coerce")
    rows: list[dict[str, object]] = []
    for keys, group in joined.groupby(
        ["phase_v2", "phase_quality", "roll_context", "horizon"]
    ):
        phase, quality, roll_context, horizon = keys
        rows.append(
            {
                "run_id": run_id,
                "phase_v2": phase,
                "phase_quality": quality,
                "roll_context": roll_context,
                "horizon": int(horizon),
                "sample_count": len(group),
                "directional_hit_rate": group["directional_hit"].mean(),
                "mean_forward_return": group["forward_return"].mean(),
                "median_forward_return": group["forward_return"].median(),
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _warning_rows(
    *, daily: pd.DataFrame, validation: pd.DataFrame, run_id: str
) -> list[dict[str, object]]:
    changed = daily["phase_v1"].ne(daily["phase_v2"])
    return [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R76_RESEARCH_ONLY",
            "warning_message": "R76 阶段 v2 为研究状态，不自动反转方向。",
            "affected_count": len(daily),
            "human_review_required": "trend_phase_v2_rules",
        },
        {
            "run_id": run_id,
            "section": "phase_comparison",
            "severity": "WARN" if changed.any() else "INFO",
            "warning_code": "PHASE_V1_V2_DIFFERENCE",
            "warning_message": "部分交易日 v2 与原阶段不同，需结合双价格和全链持仓复核。",
            "affected_count": int(changed.sum()),
            "human_review_required": "trend_phase_v2_rules",
        },
        {
            "run_id": run_id,
            "section": "historical_validation",
            "severity": "WARN" if validation.empty else "INFO",
            "warning_code": "PHASE_V2_VALIDATION_STATUS",
            "warning_message": "forward return 只用于历史后验验证。",
            "affected_count": len(validation),
            "human_review_required": "historical_forward_label_interpretation",
        },
    ]


def _default_path(directory_name: str, pattern: str) -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / directory_name,
        pattern,
        label=directory_name,
    )


def _optional_validation_path() -> Path | None:
    directory = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    candidates = list(directory.glob("CF_*_signal_matrix_validation_daily.parquet"))
    return None if not candidates else max(candidates, key=lambda path: path.stat().st_mtime)


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_trend_phase_v2"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "trend_phase_v2"
    report_root = report_dir or reports_dir() / "research" / "trend_phase_v2"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "transition_parquet": data_root / f"{stem}_transitions.parquet",
        "transition_csv": data_root / f"{stem}_transitions.csv",
        "validation_parquet": data_root / f"{stem}_validation.parquet",
        "validation_csv": data_root / f"{stem}_validation.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _write_markdown(
    *, result: ResearchTrendPhaseV2Result, latest: dict[str, object],
    validation: pd.DataFrame, transitions: pd.DataFrame
) -> None:
    lines = [
        f"# CF 趋势阶段引擎 v2 R76 - {result.end.isoformat()}",
        "",
        "## 最新阶段",
        "",
        f"- 原阶段：`{latest['phase_v1']}`",
        f"- v2 阶段：`{latest['phase_v2']}` {latest['phase_v2_label']}",
        f"- 方向 / 质量：`{latest['phase_direction']}` / `{latest['phase_quality']}`",
        f"- 确认项：`{latest['confirmation_count']}`",
        f"- 风险标记：`{latest['risk_flags'] or '-'}`",
        f"- 多日移仓上下文：`{latest['roll_context']}` {latest['roll_context_cn']}",
        f"- 多日移仓承接比例：`{fmt_percent(latest['roll_transfer_ratio_window'])}`",
        f"- 原因：{latest['phase_reason_cn']}",
        "",
        "## 最近阶段切换",
        "",
        "| 日期 | 切换 | 质量 | 原因 |",
        "| --- | --- | --- | --- |",
    ]
    for row in transitions.tail(12).to_dict(orient="records"):
        lines.append(
            f"| {row['trade_date']} | {row['transition_code_v2']} | "
            f"{row['phase_quality']} | {row['phase_reason_cn']} |"
        )
    lines.extend(
        [
            "",
            "## 历史后验验证摘要",
            "",
            "| 阶段 | 质量 | 移仓上下文 | 周期 | 样本 | 命中率 | 平均收益 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    if validation.empty:
        lines.append("| 未接入 | - | - | - | 0 | - | - |")
    else:
        sorted_rows = validation.sort_values(
            ["horizon", "sample_count"], ascending=[True, False]
        ).to_dict(orient="records")
        for row in sorted_rows[:35]:
            lines.append(
                f"| {row['phase_v2']} | {row['phase_quality']} | "
                f"{row['roll_context']} | {row['horizon']}D | "
                f"{row['sample_count']} | {fmt_percent(row['directional_hit_rate'])} | "
                f"{fmt_percent(row['mean_forward_return'])} |"
            )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- v2 使用 R73 双价格、R74 全链持仓和 R75 期权结构，不使用未来数据。",
            "- forward return 只作为历史后验验证标签。",
            "- 阶段变化不会自动反转信号，也不构成交易指令。",
            "- HUMAN_REVIEW_REQUIRED：阶段规则、资金参与和期权 proxy 解释。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")
