"""R78 multi-window OI roll and net-exit evidence research for CF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.research_workbench.chain_oi_structure import _structure_rows
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    fmt_percent,
    load_table,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
OI_ROLL_WINDOW_RESEARCH_VERSION = "R78_oi_roll_window_research_v1"
DEFAULT_WINDOWS = (3, 5, 10)
DEFAULT_NOISE_RATIO = 0.002
DEFAULT_ROLL_TRANSFER_THRESHOLD = 0.50
DEFAULT_MIN_SAMPLE_SIZE = 30
HUMAN_REVIEW_REQUIRED = (
    "multi_day_roll_window",
    "roll_transfer_threshold",
    "open_interest_single_sided_scope",
    "historical_forward_label_interpretation",
)
RESEARCH_BOUNDARY = {
    "forward_returns_are_validation_labels": True,
    "latest_state_uses_future_data": False,
    "open_interest_is_not_net_position": True,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchOiRollWindowResult:
    """R78 output paths and latest multi-window roll contexts."""

    run_id: str
    start: date
    end: date
    windows: tuple[int, ...]
    excluded_dates: tuple[date, ...]
    daily_row_count: int
    summary_row_count: int
    warning_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    summary_parquet_path: Path
    summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_quote_path: Path
    validation_daily_path: Path | None
    exclusion_path: Path | None

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "windows": list(self.windows),
            "excluded_dates": [value.isoformat() for value in self.excluded_dates],
            "daily_row_count": self.daily_row_count,
            "summary_row_count": self.summary_row_count,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "summary_parquet_path": str(self.summary_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "validation_daily_path": (
                None if self.validation_daily_path is None else str(self.validation_daily_path)
            ),
            "exclusion_path": None if self.exclusion_path is None else str(self.exclusion_path),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_oi_roll_window_research(
    *,
    core_quote_path: Path | None = None,
    validation_daily_path: Path | None = None,
    exclusion_path: Path | None = None,
    end: date | None = None,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    noise_ratio: float = DEFAULT_NOISE_RATIO,
    roll_transfer_threshold: float = DEFAULT_ROLL_TRANSFER_THRESHOLD,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchOiRollWindowResult:
    """Compare roll-transfer and net-exit evidence across several trading windows."""
    normalized_windows = tuple(sorted(set(int(value) for value in windows)))
    if not normalized_windows or any(value < 1 for value in normalized_windows):
        raise ResearchWorkbenchError("windows must contain positive trading-day values")
    if min_sample_size < 1:
        raise ResearchWorkbenchError("min_sample_size must be positive")
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = load_table(
        quote_path,
        required={
            "trade_date",
            "contract_code",
            "close",
            "settle",
            "volume",
            "open_interest",
        },
        label="CF core quote",
    )
    quotes = normalize_trade_date(quotes)
    resolved_exclusion = exclusion_path or _default_exclusion_path()
    excluded_dates = _load_excluded_dates(resolved_exclusion)
    if excluded_dates:
        quotes = quotes.loc[~quotes["trade_date"].isin(excluded_dates)].copy()
    if end is not None:
        quotes = quotes.loc[quotes["trade_date"].le(end)].copy()
    if quotes.empty:
        raise ResearchWorkbenchError("R78 has no CF quotes after date exclusions")
    effective_end = quotes["trade_date"].max()
    start = quotes["trade_date"].min()
    active_run_id = run_id or utc_timestamp_id("r78", effective_end)

    daily = _multi_window_rows(
        quotes=quotes,
        windows=normalized_windows,
        noise_ratio=noise_ratio,
        roll_transfer_threshold=roll_transfer_threshold,
        run_id=active_run_id,
    )
    resolved_validation = validation_daily_path or _optional_validation_path()
    summary = _historical_summary(
        daily=daily,
        validation_path=resolved_validation,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
        excluded_dates=excluded_dates,
        end=effective_end,
    )
    warnings = _warning_rows(
        daily=daily,
        summary=summary,
        excluded_dates=excluded_dates,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
    )
    paths = _paths(
        start=start,
        end=effective_end,
        output_dir=output_dir,
        report_dir=report_output_dir,
    )
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(summary, paths["summary_parquet"], paths["summary_csv"])
    write_warning_csv(paths["warning_csv"], warnings)
    latest_rows = daily.loc[daily["trade_date"].eq(effective_end)].to_dict(orient="records")
    result = ResearchOiRollWindowResult(
        run_id=active_run_id,
        start=start,
        end=effective_end,
        windows=normalized_windows,
        excluded_dates=tuple(sorted(excluded_dates)),
        daily_row_count=len(daily),
        summary_row_count=len(summary),
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        summary_parquet_path=paths["summary_parquet"],
        summary_csv_path=paths["summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        validation_daily_path=resolved_validation,
        exclusion_path=resolved_exclusion,
    )
    _write_markdown(result=result, latest_rows=latest_rows, summary=summary)
    write_json(
        result.json_path,
        {
            "report_type": "oi_roll_window_research",
            "rule_version": OI_ROLL_WINDOW_RESEARCH_VERSION,
            "summary": result.to_summary(),
            "latest_rows": latest_rows,
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="oi_roll_window_research",
            rule_version=OI_ROLL_WINDOW_RESEARCH_VERSION,
            data_asof=effective_end,
            input_paths={
                "core_quote_path": quote_path,
                "validation_daily_path": resolved_validation,
                "exclusion_path": resolved_exclusion,
            },
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "summary_parquet_path": result.summary_parquet_path,
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _multi_window_rows(
    *,
    quotes: pd.DataFrame,
    windows: tuple[int, ...],
    noise_ratio: float,
    roll_transfer_threshold: float,
    run_id: str,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for window in windows:
        daily, _ = _structure_rows(
            quotes=quotes,
            noise_ratio=noise_ratio,
            roll_transfer_threshold=roll_transfer_threshold,
            roll_lookback_days=window,
        )
        selected = daily[
            [
                "trade_date",
                "main_contract",
                "main_settle_return",
                "participation_state",
                "chain_oi_change",
                "chain_oi_change_adjusted",
                "expiry_oi_change",
                "roll_context",
                "roll_context_cn",
                "main_oi_change_window",
                "main_oi_change_window_adjusted",
                "positive_other_oi_change_window",
                "chain_oi_change_window",
                "chain_oi_change_window_adjusted",
                "roll_transfer_ratio_window",
            ]
        ].copy()
        selected.insert(0, "run_id", run_id)
        selected["window_days"] = window
        selected["forward_returns_are_validation_labels"] = True
        selected["trading_instruction"] = "not_a_trading_instruction"
        frames.append(selected)
    return pd.concat(frames, ignore_index=True).sort_values(
        ["trade_date", "window_days"]
    ).reset_index(drop=True)


def _historical_summary(
    *,
    daily: pd.DataFrame,
    validation_path: Path | None,
    min_sample_size: int,
    run_id: str,
    excluded_dates: set[date],
    end: date,
) -> pd.DataFrame:
    columns = [
        "run_id",
        "window_days",
        "roll_context",
        "horizon",
        "sample_count",
        "positive_return_rate",
        "directional_hit_rate",
        "mean_forward_return",
        "median_forward_return",
        "evidence_level",
        "forward_returns_are_validation_labels",
        "trading_instruction",
    ]
    if validation_path is None:
        return pd.DataFrame(columns=columns)
    validation = load_table(
        validation_path,
        required={
            "trade_date",
            "main_contract",
            "horizon",
            "forward_return",
            "forward_label_available",
            "directional_hit",
        },
        label="R36 validation daily",
    )
    validation = normalize_trade_date(validation)
    validation = validation.loc[validation["trade_date"].le(end)].copy()
    if excluded_dates:
        validation = validation.loc[~validation["trade_date"].isin(excluded_dates)].copy()
    validation = validation.loc[
        validation["forward_label_available"].fillna(False).astype(bool)
    ].copy()
    joined = validation.merge(
        daily[["trade_date", "main_contract", "window_days", "roll_context"]],
        on=["trade_date", "main_contract"],
        how="inner",
    )
    joined["forward_return"] = pd.to_numeric(joined["forward_return"], errors="coerce")
    joined["directional_hit"] = pd.to_numeric(joined["directional_hit"], errors="coerce")
    rows: list[dict[str, object]] = []
    for keys, group in joined.groupby(["window_days", "roll_context", "horizon"]):
        window, roll_context, horizon = keys
        valid_returns = group["forward_return"].dropna()
        sample_count = len(group)
        rows.append(
            {
                "run_id": run_id,
                "window_days": int(window),
                "roll_context": str(roll_context),
                "horizon": int(horizon),
                "sample_count": sample_count,
                "positive_return_rate": (
                    None if valid_returns.empty else float(valid_returns.gt(0).mean())
                ),
                "directional_hit_rate": group["directional_hit"].mean(),
                "mean_forward_return": valid_returns.mean(),
                "median_forward_return": valid_returns.median(),
                "evidence_level": _evidence_level(sample_count, min_sample_size),
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _evidence_level(sample_count: int, min_sample_size: int) -> str:
    if sample_count >= max(min_sample_size * 3, 100):
        return "READY"
    if sample_count >= min_sample_size:
        return "WATCH"
    return "WEAK_OR_SMALL_SAMPLE"


def _load_excluded_dates(path: Path | None) -> set[date]:
    if path is None or not path.exists():
        return set()
    frame = pd.read_csv(path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError("exclusion CSV missing trade_date")
    if "status" in frame.columns:
        frame = frame.loc[~frame["status"].astype(str).str.upper().eq("RESOLVED")]
    values = pd.to_datetime(frame["trade_date"], errors="coerce").dropna()
    return set(values.dt.date.tolist())


def _warning_rows(
    *,
    daily: pd.DataFrame,
    summary: pd.DataFrame,
    excluded_dates: set[date],
    run_id: str,
    min_sample_size: int,
) -> list[dict[str, object]]:
    small_count = (
        0
        if summary.empty
        else int(summary["sample_count"].lt(min_sample_size).sum())
    )
    return [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R78_RESEARCH_ONLY",
            "warning_message": "R78只研究移仓窗口与历史后验表现，不构成交易指令。",
            "affected_count": len(daily),
            "human_review_required": "historical_forward_label_interpretation",
        },
        {
            "run_id": run_id,
            "section": "manual_exclusions",
            "severity": "WARN" if excluded_dates else "INFO",
            "warning_code": "MANUAL_TRADE_DATE_EXCLUDED",
            "warning_message": "人工标记的数据异常日期已从R78研究中排除。",
            "affected_count": len(excluded_dates),
            "human_review_required": "",
        },
        {
            "run_id": run_id,
            "section": "sample_size",
            "severity": "WARN" if small_count else "INFO",
            "warning_code": "ROLL_WINDOW_SMALL_SAMPLE",
            "warning_message": "部分移仓窗口分组样本不足，证据等级已降级。",
            "affected_count": small_count,
            "human_review_required": "multi_day_roll_window",
        },
    ]


def _default_exclusion_path() -> Path | None:
    path = project_root() / "configs" / "research_exclusions" / "CF_trade_date_exclusions.csv"
    return path if path.exists() else None


def _optional_validation_path() -> Path | None:
    directory = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    candidates = list(directory.glob("CF_*_signal_matrix_validation_daily.parquet"))
    return None if not candidates else max(candidates, key=lambda path: path.stat().st_mtime)


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_oi_roll_window_research"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "oi_roll_window"
    report_root = report_dir or reports_dir() / "research" / "oi_roll_window"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "summary_parquet": data_root / f"{stem}_summary.parquet",
        "summary_csv": data_root / f"{stem}_summary.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _write_markdown(
    *,
    result: ResearchOiRollWindowResult,
    latest_rows: list[dict[str, object]],
    summary: pd.DataFrame,
) -> None:
    lines = [
        f"# CF 多窗口移仓与净退出研究 R78 - {result.end.isoformat()}",
        "",
        "## 数据边界",
        "",
        f"- 研究区间：`{result.start}` 至 `{result.end}`",
        f"- 窗口：`{','.join(str(value) for value in result.windows)}` 个交易日",
        "",
        "## 截止日多窗口状态",
        "",
        "| 窗口 | 主力 | 上下文 | 主力变化 | 其他合约承接 | 全链变化 | 承接比例 |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    if result.excluded_dates:
        lines[7:7] = [
            f"- 显式排除日期：`{','.join(value.isoformat() for value in result.excluded_dates)}`",
        ]
    for row in latest_rows:
        lines.append(
            f"| {row['window_days']}D | {row['main_contract']} | "
            f"{row['roll_context']} | "
            f"{fmt_number(row['main_oi_change_window_adjusted'], 0)} | "
            f"{fmt_number(row['positive_other_oi_change_window'], 0)} | "
            f"{fmt_number(row['chain_oi_change_window_adjusted'], 0)} | "
            f"{fmt_percent(row['roll_transfer_ratio_window'])} |"
        )
    lines.extend(
        [
            "",
            "## 历史后验摘要",
            "",
            "| 移仓窗口 | 上下文 | 收益周期 | 样本 | 上涨比例 | 方向命中 | 平均收益 | 证据 |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    if summary.empty:
        lines.append("| - | 未接入历史标签 | - | 0 | - | - | - | - |")
    else:
        selected = summary.loc[summary["horizon"].isin([5, 10, 20, 40])].copy()
        selected = selected.sort_values(
            ["window_days", "horizon", "sample_count"],
            ascending=[True, True, False],
        )
        for row in selected.to_dict(orient="records"):
            lines.append(
                f"| {row['window_days']}D | {row['roll_context']} | {row['horizon']}D | "
                f"{row['sample_count']} | {fmt_percent(row['positive_return_rate'])} | "
                f"{fmt_percent(row['directional_hit_rate'])} | "
                f"{fmt_percent(row['mean_forward_return'])} | {row['evidence_level']} |"
            )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 持仓量是合约总持仓，不代表净多或净空。",
            "- `forward_return`只作为历史后验验证标签，不进入最新状态生成。",
            "- 移仓承接不等于新增趋势资金，需同时检查全链净变化。",
            "- 本报告不修改`composite_score`，不构成交易指令。",
            "- HUMAN_REVIEW_REQUIRED：移仓窗口、阈值和持仓口径解释。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")
