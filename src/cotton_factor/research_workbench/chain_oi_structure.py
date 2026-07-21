"""R74 chain-level open-interest and roll decomposition for CF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.contract_universe import _infer_czce_delivery_year
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    load_table,
    main_contract_rows,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
CHAIN_OI_STRUCTURE_VERSION = "R74_chain_oi_structure_v3"
DEFAULT_NOISE_RATIO = 0.002
DEFAULT_ROLL_TRANSFER_RATIO = 0.50
DEFAULT_ROLL_LOOKBACK_DAYS = 5
HUMAN_REVIEW_REQUIRED = (
    "open_interest_single_sided_scope",
    "roll_transfer_threshold",
    "multi_day_roll_window",
    "last_trading_day_expiry_adjustment",
    "main_contract_selection",
    "price_oi_quadrant_interpretation",
)
RESEARCH_BOUNDARY = {
    "uses_observable_t_day_data_only": True,
    "roll_transfer_is_proxy": True,
    "expiry_oi_reset_is_excluded_from_adjusted_flow": True,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchChainOiStructureResult:
    """R74 artifact paths and latest participation state."""

    run_id: str
    start: date
    end: date
    row_count: int
    latest_main_contract: str
    latest_participation_state: str
    latest_chain_oi_change: float | None
    latest_chain_oi_change_adjusted: float | None
    latest_roll_context: str
    latest_roll_transfer_ratio_window: float | None
    roll_lookback_days: int
    warning_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    contract_detail_parquet_path: Path
    contract_detail_csv_path: Path
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
            "latest_participation_state": self.latest_participation_state,
            "latest_chain_oi_change": self.latest_chain_oi_change,
            "latest_chain_oi_change_adjusted": self.latest_chain_oi_change_adjusted,
            "latest_roll_context": self.latest_roll_context,
            "latest_roll_transfer_ratio_window": self.latest_roll_transfer_ratio_window,
            "roll_lookback_days": self.roll_lookback_days,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "contract_detail_parquet_path": str(self.contract_detail_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_chain_oi_structure(
    *,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    noise_ratio: float = DEFAULT_NOISE_RATIO,
    roll_transfer_threshold: float = DEFAULT_ROLL_TRANSFER_RATIO,
    roll_lookback_days: int = DEFAULT_ROLL_LOOKBACK_DAYS,
) -> ResearchChainOiStructureResult:
    """Decompose main-contract OI changes into roll transfer and chain participation."""
    if noise_ratio < 0:
        raise ResearchWorkbenchError("noise_ratio must be non-negative")
    if roll_transfer_threshold < 0:
        raise ResearchWorkbenchError("roll_transfer_threshold must be non-negative")
    if roll_lookback_days < 1:
        raise ResearchWorkbenchError("roll_lookback_days must be positive")
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
    daily, detail = _structure_rows(
        quotes=quotes,
        noise_ratio=noise_ratio,
        roll_transfer_threshold=roll_transfer_threshold,
        roll_lookback_days=roll_lookback_days,
    )
    if daily.empty:
        raise ResearchWorkbenchError("R74 chain OI structure has no rows")
    start = daily["trade_date"].min()
    end = daily["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("r74", end)
    daily.insert(0, "run_id", active_run_id)
    detail.insert(0, "run_id", active_run_id)
    warnings = _warning_rows(daily=daily, run_id=active_run_id)
    paths = _paths(start=start, end=end, output_dir=output_dir, report_dir=report_output_dir)
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(detail, paths["detail_parquet"], paths["detail_csv"])
    write_warning_csv(paths["warning_csv"], warnings)
    latest = daily.iloc[-1].to_dict()
    result = ResearchChainOiStructureResult(
        run_id=active_run_id,
        start=start,
        end=end,
        row_count=len(daily),
        latest_main_contract=str(latest["main_contract"]),
        latest_participation_state=str(latest["participation_state"]),
        latest_chain_oi_change=(
            None if pd.isna(latest["chain_oi_change"]) else float(latest["chain_oi_change"])
        ),
        latest_chain_oi_change_adjusted=(
            None
            if pd.isna(latest["chain_oi_change_adjusted"])
            else float(latest["chain_oi_change_adjusted"])
        ),
        latest_roll_context=str(latest["roll_context"]),
        latest_roll_transfer_ratio_window=(
            None
            if pd.isna(latest["roll_transfer_ratio_window"])
            else float(latest["roll_transfer_ratio_window"])
        ),
        roll_lookback_days=roll_lookback_days,
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        contract_detail_parquet_path=paths["detail_parquet"],
        contract_detail_csv_path=paths["detail_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(result=result, latest=latest, daily=daily, detail=detail)
    write_json(
        result.json_path,
        {
            "report_type": "chain_oi_structure",
            "rule_version": CHAIN_OI_STRUCTURE_VERSION,
            "summary": result.to_summary(),
            "latest_state": latest,
            "state_counts": daily["participation_state"].value_counts().to_dict(),
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="chain_oi_structure",
            rule_version=CHAIN_OI_STRUCTURE_VERSION,
            data_asof=end,
            input_paths={"core_quote_path": quote_path},
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "contract_detail_parquet_path": result.contract_detail_parquet_path,
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _structure_rows(
    *,
    quotes: pd.DataFrame,
    noise_ratio: float,
    roll_transfer_threshold: float,
    roll_lookback_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = normalize_trade_date(quotes)
    for column in ("close", "settle", "volume", "open_interest"):
        working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0.0)
    working = working.sort_values(["contract_code", "trade_date"])
    working["contract_oi_change"] = working.groupby("contract_code")["open_interest"].diff()
    working = _add_expiry_adjustment(
        working=working,
        roll_lookback_days=roll_lookback_days,
    )
    # 单日变化用于判断当日资金参与，多日窗口用于识别主力减仓是否被其他月份承接。
    working["contract_oi_change_window"] = working.groupby("contract_code")[
        "open_interest"
    ].diff(roll_lookback_days)
    working["contract_settle_return"] = working.groupby("contract_code")["settle"].pct_change()
    main = main_contract_rows(working).rename(columns={"contract_code": "main_contract"})
    main_lookup = dict(zip(main["trade_date"], main["main_contract"], strict=False))
    working["main_contract"] = working["trade_date"].map(main_lookup)
    working["is_main_contract"] = working["contract_code"].eq(working["main_contract"])
    chain = working.groupby("trade_date", as_index=False).agg(
        chain_open_interest=("open_interest", "sum"),
        chain_volume=("volume", "sum"),
        positive_other_oi_change=(
            "contract_oi_change",
            lambda values: float(values[values > 0].sum()),
        ),
        negative_contract_oi_change=(
            "contract_oi_change",
            lambda values: float(values[values < 0].sum()),
        ),
        expiry_oi_change=("expiry_oi_change", "sum"),
        chain_oi_change_adjusted=("contract_oi_change_adjusted", "sum"),
    )
    chain["chain_oi_change"] = chain["chain_open_interest"].diff()
    chain.loc[chain["chain_oi_change"].isna(), "chain_oi_change_adjusted"] = pd.NA
    chain["chain_oi_change_window"] = chain["chain_open_interest"].diff(
        roll_lookback_days
    )
    chain["chain_oi_change_window_adjusted"] = chain[
        "chain_oi_change_adjusted"
    ].rolling(roll_lookback_days, min_periods=roll_lookback_days).sum()
    chain["chain_oi_change_ratio"] = (
        chain["chain_oi_change"] / chain["chain_open_interest"].shift(1)
    )
    main_columns = main[
        [
            "trade_date",
            "main_contract",
            "settle",
            "close",
            "open_interest",
            "volume",
            "contract_oi_change",
            "contract_oi_change_adjusted",
            "contract_oi_change_window",
            "contract_oi_change_window_adjusted",
            "contract_settle_return",
        ]
    ].rename(
        columns={
            "open_interest": "main_open_interest",
            "volume": "main_volume",
            "contract_oi_change": "main_oi_change",
            "contract_oi_change_adjusted": "main_oi_change_adjusted",
            "contract_oi_change_window": "main_oi_change_window",
            "contract_oi_change_window_adjusted": "main_oi_change_window_adjusted",
            "contract_settle_return": "main_settle_return",
        }
    )
    daily = main_columns.merge(chain, on="trade_date", how="left")
    daily["positive_other_oi_change"] = daily.apply(
        lambda row: _positive_other_change(
            working=working,
            row=row,
            change_column="contract_oi_change_adjusted",
        ),
        axis=1,
    )
    daily["roll_transfer_ratio"] = daily.apply(_roll_transfer_ratio, axis=1)
    daily["positive_other_oi_change_window"] = daily.apply(
        lambda row: _positive_other_change(
            working=working,
            row=row,
            change_column="contract_oi_change_window_adjusted",
        ),
        axis=1,
    )
    daily["roll_transfer_ratio_window"] = daily.apply(
        lambda row: _roll_transfer_ratio_values(
            main_change=row["main_oi_change_window_adjusted"],
            positive_other_change=row["positive_other_oi_change_window"],
        ),
        axis=1,
    )
    states: list[str] = []
    labels: list[str] = []
    oi_signals: list[str] = []
    for row in daily.itertuples(index=False):
        chain_threshold = max(row.chain_open_interest * noise_ratio, 1.0)
        price_up = row.main_settle_return > 0 if not pd.isna(row.main_settle_return) else False
        price_down = row.main_settle_return < 0 if not pd.isna(row.main_settle_return) else False
        chain_up = (
            row.chain_oi_change_adjusted > chain_threshold
            if not pd.isna(row.chain_oi_change_adjusted)
            else False
        )
        chain_down = (
            row.chain_oi_change_adjusted < -chain_threshold
            if not pd.isna(row.chain_oi_change_adjusted)
            else False
        )
        roll_like = (
            row.main_oi_change_adjusted < 0
            and row.roll_transfer_ratio >= roll_transfer_threshold
            and not chain_down
        ) if not pd.isna(row.main_oi_change_adjusted) else False
        if roll_like:
            state, label, oi_signal = "ROLL_TRANSFER", "主力减仓、远月承接", "neutral"
        elif price_up and chain_up:
            state, label, oi_signal = "LONG_BUILD", "价格上涨、全链增仓", "long"
        elif price_down and chain_up:
            state, label, oi_signal = "SHORT_BUILD", "价格下跌、全链增仓", "short"
        elif price_up and chain_down:
            state = "SHORT_COVER_OR_EXIT"
            label, oi_signal = "价格上涨、全链减仓", "repair_without_new_money"
        elif price_down and chain_down:
            state = "LONG_LIQUIDATION"
            label, oi_signal = "价格下跌、全链减仓", "risk_short"
        else:
            state, label, oi_signal = "NEUTRAL_OR_NOISE", "持仓变化未形成清晰结构", "neutral"
        states.append(state)
        labels.append(label)
        oi_signals.append(oi_signal)
    daily["participation_state"] = states
    daily["participation_state_cn"] = labels
    daily["oi_signal_v2"] = oi_signals
    # 多日移仓上下文不覆盖单日状态，避免把移仓和真实资金退出混为一谈。
    roll_context_rows = daily.apply(
        lambda row: _roll_window_context(
            row=row,
            noise_ratio=noise_ratio,
            roll_transfer_threshold=roll_transfer_threshold,
        ),
        axis=1,
        result_type="expand",
    )
    roll_context_rows.columns = ["roll_context", "roll_context_cn"]
    daily[["roll_context", "roll_context_cn"]] = roll_context_rows
    daily["roll_lookback_days"] = roll_lookback_days
    daily["net_exit_oi"] = (-daily["chain_oi_change_adjusted"]).clip(lower=0)
    daily["new_money_oi"] = daily["chain_oi_change_adjusted"].clip(lower=0)
    daily["rule_version"] = CHAIN_OI_STRUCTURE_VERSION
    daily["roll_transfer_is_proxy"] = True
    daily["trading_instruction"] = "not_a_trading_instruction"
    detail = working[
        [
            "trade_date",
            "contract_code",
            "main_contract",
            "is_main_contract",
            "settle",
            "close",
            "volume",
            "open_interest",
            "contract_oi_change",
            "contract_oi_change_adjusted",
            "contract_oi_change_window",
            "contract_oi_change_window_adjusted",
            "is_last_trade_date",
            "last_trade_date",
            "expiry_oi_change",
            "contract_settle_return",
        ]
    ].copy()
    detail["rule_version"] = CHAIN_OI_STRUCTURE_VERSION
    return daily.sort_values("trade_date").reset_index(drop=True), detail.reset_index(drop=True)


def _positive_other_change(
    *, working: pd.DataFrame, row: pd.Series, change_column: str
) -> float:
    day = working.loc[
        working["trade_date"].eq(row["trade_date"])
        & ~working["contract_code"].eq(row["main_contract"]),
        change_column,
    ]
    return float(day[day > 0].sum())


def _add_expiry_adjustment(
    *, working: pd.DataFrame, roll_lookback_days: int
) -> pd.DataFrame:
    adjusted = working.copy()
    # 使用已入库的官方交易日和CF“交割月第10个交易日”规则识别到期清零。
    observed_trade_dates = sorted(set(adjusted["trade_date"]))
    last_trade_dates: dict[tuple[int, int], date] = {}
    for year in sorted({value.year for value in observed_trade_dates}):
        for month in range(1, 13):
            month_dates = [
                value
                for value in observed_trade_dates
                if value.year == year and value.month == month
            ]
            if len(month_dates) >= 10:
                last_trade_dates[(year, month)] = month_dates[9]
    delivery_years: list[int] = []
    delivery_months: list[int] = []
    resolved_last_dates: list[date | None] = []
    for row in adjusted.itertuples(index=False):
        contract_code = str(row.contract_code)
        delivery_year = _infer_czce_delivery_year(
            contract_code=contract_code,
            product_code=PRODUCT_CODE,
            base_year=row.trade_date.year,
        )
        delivery_month = int(contract_code[-2:])
        delivery_years.append(delivery_year)
        delivery_months.append(delivery_month)
        resolved_last_dates.append(last_trade_dates.get((delivery_year, delivery_month)))
    adjusted["delivery_year"] = delivery_years
    adjusted["delivery_month"] = delivery_months
    adjusted["last_trade_date"] = resolved_last_dates
    adjusted["is_last_trade_date"] = adjusted["trade_date"].eq(
        adjusted["last_trade_date"]
    )
    expiry_reset = (
        adjusted["is_last_trade_date"]
        & adjusted["contract_oi_change"].lt(0)
        & adjusted["open_interest"].eq(0)
    )
    adjusted["expiry_oi_change"] = adjusted["contract_oi_change"].where(
        expiry_reset, 0.0
    )
    adjusted["contract_oi_change_adjusted"] = (
        adjusted["contract_oi_change"] - adjusted["expiry_oi_change"]
    )
    adjusted["contract_oi_change_window_adjusted"] = adjusted.groupby(
        "contract_code"
    )["contract_oi_change_adjusted"].transform(
        lambda values: values.rolling(
            roll_lookback_days,
            min_periods=roll_lookback_days,
        ).sum()
    )
    return adjusted


def _roll_transfer_ratio(row: pd.Series) -> float | None:
    return _roll_transfer_ratio_values(
        main_change=row["main_oi_change_adjusted"],
        positive_other_change=row["positive_other_oi_change"],
    )


def _roll_transfer_ratio_values(
    *, main_change: object, positive_other_change: object
) -> float | None:
    if pd.isna(main_change) or main_change >= 0:
        return None
    return float(positive_other_change / abs(main_change))


def _roll_window_context(
    *, row: pd.Series, noise_ratio: float, roll_transfer_threshold: float
) -> tuple[str, str]:
    main_change = row["main_oi_change_window_adjusted"]
    chain_change = row["chain_oi_change_window_adjusted"]
    ratio = row["roll_transfer_ratio_window"]
    if pd.isna(main_change) or pd.isna(chain_change):
        return "INSUFFICIENT_HISTORY", "多日窗口历史不足"
    if main_change >= 0:
        return "NO_MAIN_REDUCTION", "多日窗口主力未减仓"
    chain_threshold = max(float(row["chain_open_interest"]) * noise_ratio, 1.0)
    chain_down = float(chain_change) < -chain_threshold
    transfer_is_material = not pd.isna(ratio) and float(ratio) >= roll_transfer_threshold
    if transfer_is_material and chain_down:
        return "ROLL_WITH_NET_EXIT", "存在明显移仓，同时全链净退出"
    if transfer_is_material:
        return "ROLL_DOMINANT", "主力减仓主要被其他月份承接"
    if chain_down:
        return "EXIT_DOMINANT", "主力减仓以全链资金退出为主"
    return "PARTIAL_TRANSFER_OR_MIXED", "存在部分承接，但未达到移仓阈值"


def _warning_rows(*, daily: pd.DataFrame, run_id: str) -> list[dict[str, object]]:
    roll_days = daily["participation_state"].eq("ROLL_TRANSFER")
    mixed_roll_days = daily["roll_context"].eq("ROLL_WITH_NET_EXIT")
    expiry_days = daily["expiry_oi_change"].lt(0)
    return [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R74_RESEARCH_ONLY",
            "warning_message": "R74 持仓分解为研究 proxy，不代表多空净持仓。",
            "affected_count": len(daily),
            "human_review_required": "open_interest_single_sided_scope",
        },
        {
            "run_id": run_id,
            "section": "roll_transfer",
            "severity": "WARN" if roll_days.any() else "INFO",
            "warning_code": "ROLL_TRANSFER_PROXY_REVIEW",
            "warning_message": "移仓比例仅按合约持仓变化估算，需结合合约规则人工复核。",
            "affected_count": int(roll_days.sum()),
            "human_review_required": "roll_transfer_threshold;main_contract_selection",
        },
        {
            "run_id": run_id,
            "section": "multi_day_roll_context",
            "severity": "WARN" if mixed_roll_days.any() else "INFO",
            "warning_code": "ROLL_WITH_NET_EXIT_REVIEW",
            "warning_message": "多日窗口同时出现移仓与全链净退出，需分别解释承接和资金流失。",
            "affected_count": int(mixed_roll_days.sum()),
            "human_review_required": "multi_day_roll_window;roll_transfer_threshold",
        },
        {
            "run_id": run_id,
            "section": "expiry_adjustment",
            "severity": "INFO",
            "warning_code": "EXPIRY_OI_RESET_EXCLUDED",
            "warning_message": "最后交易日持仓清零已从调整后资金流中剔除，原始变化继续保留。",
            "affected_count": int(expiry_days.sum()),
            "human_review_required": "last_trading_day_expiry_adjustment",
        },
    ]


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_chain_oi_structure"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "chain_oi_structure"
    report_root = report_dir or reports_dir() / "research" / "chain_oi_structure"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "detail_parquet": data_root / f"{stem}_contract_detail.parquet",
        "detail_csv": data_root / f"{stem}_contract_detail.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _write_markdown(
    *,
    result: ResearchChainOiStructureResult,
    latest: dict[str, object],
    daily: pd.DataFrame,
    detail: pd.DataFrame,
) -> None:
    recent = daily.tail(10)
    latest_detail = detail.loc[detail["trade_date"].eq(result.end)].sort_values(
        "open_interest", ascending=False
    )
    lines = [
        f"# CF 全链持仓与移仓分解 R74 - {result.end.isoformat()}",
        "",
        "## 最新状态",
        "",
        f"- 主力合约：`{latest['main_contract']}`",
        f"- 参与状态：`{latest['participation_state']}` {latest['participation_state_cn']}",
        f"- 主力持仓变化：`{fmt_number(latest['main_oi_change'], 0)}`",
        f"- 全链持仓变化：`{fmt_number(latest['chain_oi_change'], 0)}`",
        f"- 到期清零影响：`{fmt_number(latest['expiry_oi_change'], 0)}`",
        f"- 调整后全链变化：`{fmt_number(latest['chain_oi_change_adjusted'], 0)}`",
        f"- 远月正向承接：`{fmt_number(latest['positive_other_oi_change'], 0)}`",
        f"- 移仓承接比例：`{fmt_number(latest['roll_transfer_ratio'], 3)}`",
        f"- {result.roll_lookback_days}日移仓上下文：`{latest['roll_context']}` "
        f"{latest['roll_context_cn']}",
        f"- {result.roll_lookback_days}日主力持仓变化："
        f"`{fmt_number(latest['main_oi_change_window'], 0)}`",
        f"- {result.roll_lookback_days}日其他月份正向承接："
        f"`{fmt_number(latest['positive_other_oi_change_window'], 0)}`",
        f"- {result.roll_lookback_days}日全链持仓变化："
        f"`{fmt_number(latest['chain_oi_change_window'], 0)}`",
        f"- {result.roll_lookback_days}日调整后全链变化："
        f"`{fmt_number(latest['chain_oi_change_window_adjusted'], 0)}`",
        f"- {result.roll_lookback_days}日移仓承接比例："
        f"`{fmt_number(latest['roll_transfer_ratio_window'], 3)}`",
        "",
        "## 最新交易日合约持仓变化",
        "",
        "| 合约 | 主力 | 最后交易日 | 持仓量 | 单日变化 | 调整后变化 | 多日调整 | 成交量 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in latest_detail.to_dict(orient="records"):
        lines.append(
            f"| {row['contract_code']} | {'是' if row['is_main_contract'] else '否'} | "
            f"{_fmt_date(row['last_trade_date'])} | "
            f"{fmt_number(row['open_interest'], 0)} | "
            f"{fmt_number(row['contract_oi_change'], 0)} | "
            f"{fmt_number(row['contract_oi_change_adjusted'], 0)} | "
            f"{fmt_number(row['contract_oi_change_window_adjusted'], 0)} | "
            f"{fmt_number(row['volume'], 0)} |"
        )
    lines.extend(
        [
            "",
            "## 最近状态",
            "",
            "| 日期 | 主力 | 价格变化 | 主力OI变化 | 调整后全链OI变化 | 状态 |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in recent.to_dict(orient="records"):
        lines.append(
            f"| {row['trade_date']} | {row['main_contract']} | "
            f"{fmt_percent_like(row['main_settle_return'])} | "
            f"{fmt_number(row['main_oi_change'], 0)} | "
            f"{fmt_number(row['chain_oi_change_adjusted'], 0)} | "
            f"{row['participation_state_cn']} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 郑商所持仓量为合约总持仓，不等同于净多或净空。",
            "- `roll_transfer_ratio` 只描述主力减仓是否被其他月份增仓承接。",
            "- 最后交易日持仓清零保留在原始变化中，但从调整后资金流剔除。",
            "- 单日状态回答当日资金参与；多日窗口回答主力减仓是否存在跨合约承接，"
            "两者可以同时成立。",
            "- 本模块不改变 `composite_score`，不构成交易指令。",
            "- HUMAN_REVIEW_REQUIRED：持仓单双边口径、主力切换、移仓窗口和移仓阈值。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")


def fmt_percent_like(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _fmt_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return str(value)
