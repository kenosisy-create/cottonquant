"""R73 close/settlement dual-price state research for CF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    fmt_percent,
    load_table,
    main_contract_rows,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
DUAL_PRICE_STATE_VERSION = "R73_dual_price_state_v1"
DEFAULT_MA_WINDOW = 20
DEFAULT_GAP_ALERT_BPS = 25.0
HUMAN_REVIEW_REQUIRED = (
    "close_settlement_field_interpretation",
    "dual_price_breakout_threshold",
    "main_contract_selection",
    "historical_forward_label_interpretation",
)
RESEARCH_BOUNDARY = {
    "forward_returns_are_validation_labels": True,
    "latest_state_uses_future_data": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchDualPriceStateResult:
    """R73 artifact paths and latest state summary."""

    run_id: str
    start: date
    end: date
    row_count: int
    latest_main_contract: str
    latest_dual_price_state: str
    warning_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    validation_parquet_path: Path
    validation_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_quote_path: Path
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": self.row_count,
            "latest_main_contract": self.latest_main_contract,
            "latest_dual_price_state": self.latest_dual_price_state,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "validation_parquet_path": str(self.validation_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_dual_price_state(
    *,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    ma_window: int = DEFAULT_MA_WINDOW,
    gap_alert_bps: float = DEFAULT_GAP_ALERT_BPS,
) -> ResearchDualPriceStateResult:
    """Build close/settlement state and historical posterior validation tables."""
    if ma_window <= 1:
        raise ResearchWorkbenchError("ma_window must be greater than 1")
    if gap_alert_bps < 0:
        raise ResearchWorkbenchError("gap_alert_bps must be non-negative")
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
    daily = _daily_rows(quotes=quotes, ma_window=ma_window, gap_alert_bps=gap_alert_bps)
    if daily.empty:
        raise ResearchWorkbenchError("R73 dual-price state has no rows")
    start = daily["trade_date"].min()
    end = daily["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("r73", end)
    daily.insert(0, "run_id", active_run_id)
    validation = _validation_rows(daily=daily, run_id=active_run_id)
    warnings = _warning_rows(daily=daily, run_id=active_run_id)
    paths = _paths(start=start, end=end, output_dir=output_dir, report_dir=report_output_dir)
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(validation, paths["validation_parquet"], paths["validation_csv"])
    write_warning_csv(paths["warning_csv"], warnings)
    latest = daily.iloc[-1].to_dict()
    result = ResearchDualPriceStateResult(
        run_id=active_run_id,
        start=start,
        end=end,
        row_count=len(daily),
        latest_main_contract=str(latest["main_contract"]),
        latest_dual_price_state=str(latest["dual_price_state"]),
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        validation_parquet_path=paths["validation_parquet"],
        validation_csv_path=paths["validation_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(result=result, latest=latest, validation=validation, ma_window=ma_window)
    write_json(
        result.json_path,
        {
            "report_type": "dual_price_state",
            "rule_version": DUAL_PRICE_STATE_VERSION,
            "summary": result.to_summary(),
            "latest_state": latest,
            "validation_rows": validation.to_dict(orient="records"),
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="dual_price_state",
            rule_version=DUAL_PRICE_STATE_VERSION,
            data_asof=end,
            input_paths={"core_quote_path": quote_path},
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
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


def _daily_rows(
    *, quotes: pd.DataFrame, ma_window: int, gap_alert_bps: float
) -> pd.DataFrame:
    working = normalize_trade_date(quotes)
    for column in ("close", "settle", "volume", "open_interest"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["close", "settle"])
    working = working.sort_values(["contract_code", "trade_date"])
    working["close_ma"] = working.groupby("contract_code")["close"].transform(
        lambda values: values.rolling(ma_window, min_periods=ma_window).mean()
    )
    working["settle_ma"] = working.groupby("contract_code")["settle"].transform(
        lambda values: values.rolling(ma_window, min_periods=ma_window).mean()
    )
    working["close_return_1d"] = working.groupby("contract_code")["close"].pct_change()
    working["settle_return_1d"] = working.groupby("contract_code")["settle"].pct_change()
    main = main_contract_rows(working).copy()
    main = main.rename(columns={"contract_code": "main_contract"})
    main["close_gap_to_ma_bps"] = (main["close"] / main["close_ma"] - 1.0) * 10000
    main["settle_gap_to_ma_bps"] = (main["settle"] / main["settle_ma"] - 1.0) * 10000
    main["close_settle_gap_bps"] = (main["close"] / main["settle"] - 1.0) * 10000
    states: list[str] = []
    labels: list[str] = []
    gap_states: list[str] = []
    severities: list[str] = []
    for row in main.itertuples(index=False):
        if pd.isna(row.close_ma) or pd.isna(row.settle_ma):
            state, label, severity = "INSUFFICIENT_HISTORY", "历史不足", "INFO"
        else:
            close_above = row.close >= row.close_ma
            settle_above = row.settle >= row.settle_ma
            if close_above and settle_above:
                state, label, severity = "BOTH_ABOVE", "收盘与结算均在线上", "NONE"
            elif not close_above and not settle_above:
                state, label, severity = "BOTH_BELOW", "收盘与结算双破位", "HIGH"
            elif not close_above and settle_above:
                state = "CLOSE_BREAK_SETTLE_HOLD"
                label, severity = "收盘破位、结算未确认", "MEDIUM"
            else:
                state = "CLOSE_RECLAIM_SETTLE_BELOW"
                label, severity = "收盘收复、结算未确认", "MEDIUM"
        gap = row.close_settle_gap_bps
        if pd.isna(gap) or abs(gap) < gap_alert_bps:
            gap_state = "ALIGNED"
        elif gap > 0:
            gap_state = "CLOSE_STRONGER"
        else:
            gap_state = "SETTLE_STRONGER"
        states.append(state)
        labels.append(label)
        gap_states.append(gap_state)
        severities.append(severity)
    main["dual_price_state"] = states
    main["dual_price_state_cn"] = labels
    main["close_settle_gap_state"] = gap_states
    main["alert_severity"] = severities
    main["rule_version"] = DUAL_PRICE_STATE_VERSION
    main["forward_returns_are_validation_labels"] = True
    main["trading_instruction"] = "not_a_trading_instruction"
    columns = [
        "trade_date",
        "main_contract",
        "close",
        "settle",
        "close_ma",
        "settle_ma",
        "close_return_1d",
        "settle_return_1d",
        "close_gap_to_ma_bps",
        "settle_gap_to_ma_bps",
        "close_settle_gap_bps",
        "dual_price_state",
        "dual_price_state_cn",
        "close_settle_gap_state",
        "alert_severity",
        "volume",
        "open_interest",
        "rule_version",
        "forward_returns_are_validation_labels",
        "trading_instruction",
    ]
    return main[columns].sort_values("trade_date").reset_index(drop=True)


def _validation_rows(*, daily: pd.DataFrame, run_id: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    working = daily.copy()
    for horizon in (1, 3, 5):
        working[f"forward_settle_{horizon}d"] = (
            working["settle"].shift(-horizon) / working["settle"] - 1.0
        )
    for state, group in working.groupby("dual_price_state"):
        for horizon in (1, 3, 5):
            values = group[f"forward_settle_{horizon}d"].dropna()
            rows.append(
                {
                    "run_id": run_id,
                    "dual_price_state": state,
                    "horizon": horizon,
                    "sample_count": len(values),
                    "mean_forward_settle_return": values.mean() if len(values) else None,
                    "median_forward_settle_return": values.median() if len(values) else None,
                    "positive_rate": (values > 0).mean() if len(values) else None,
                    "forward_returns_are_validation_labels": True,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows)


def _warning_rows(*, daily: pd.DataFrame, run_id: str) -> list[dict[str, object]]:
    conflicts = daily["dual_price_state"].isin(
        {"CLOSE_BREAK_SETTLE_HOLD", "CLOSE_RECLAIM_SETTLE_BELOW"}
    )
    return [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R73_RESEARCH_ONLY",
            "warning_message": "R73 双价格状态只用于研究预警，不构成交易指令。",
            "affected_count": len(daily),
            "human_review_required": "close_settlement_field_interpretation",
        },
        {
            "run_id": run_id,
            "section": "dual_price_conflict",
            "severity": "WARN" if conflicts.any() else "INFO",
            "warning_code": "CLOSE_SETTLEMENT_STATE_DIVERGENCE",
            "warning_message": "部分交易日收盘与结算对均线给出不同状态，需双口径复核。",
            "affected_count": int(conflicts.sum()),
            "human_review_required": "dual_price_breakout_threshold",
        },
    ]


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_dual_price_state"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "dual_price_state"
    report_root = report_dir or reports_dir() / "research" / "dual_price_state"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "validation_parquet": data_root / f"{stem}_validation.parquet",
        "validation_csv": data_root / f"{stem}_validation.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _write_markdown(
    *, result: ResearchDualPriceStateResult, latest: dict[str, object], validation: pd.DataFrame,
    ma_window: int
) -> None:
    lines = [
        f"# CF 收盘/结算双价格状态研究 R73 - {result.end.isoformat()}",
        "",
        "## 最新状态",
        "",
        f"- 主力合约：`{latest['main_contract']}`",
        f"- 双价格状态：`{latest['dual_price_state']}` {latest['dual_price_state_cn']}",
        f"- 收盘价 / {ma_window}日均线：`{fmt_number(latest['close'], 2)}` / "
        f"`{fmt_number(latest['close_ma'], 2)}`",
        f"- 结算价 / {ma_window}日均线：`{fmt_number(latest['settle'], 2)}` / "
        f"`{fmt_number(latest['settle_ma'], 2)}`",
        f"- 收盘相对结算偏离：`{fmt_number(latest['close_settle_gap_bps'], 2)}` bps",
        "",
        "## 历史后验对比",
        "",
        "| 状态 | 周期 | 样本 | 平均后验收益 | 正收益比例 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in validation.to_dict(orient="records"):
        lines.append(
            f"| {row['dual_price_state']} | {row['horizon']}D | {row['sample_count']} | "
            f"{fmt_percent(row['mean_forward_settle_return'])} | "
            f"{fmt_percent(row['positive_rate'])} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 收盘价用于盘面破位和尾盘强弱观察；结算价继续用于官方结算及历史验证。",
            "- 历史 forward return 仅为后验验证标签，不进入最新日状态生成。",
            "- 未修改 `composite_score`，不构成交易指令。",
            "- HUMAN_REVIEW_REQUIRED：收盘/结算字段口径、均线窗口和破位阈值。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")
