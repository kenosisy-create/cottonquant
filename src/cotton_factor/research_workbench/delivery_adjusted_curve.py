"""CF 跨月交割成本修正曲线研究。"""

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
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
DELIVERY_ADJUSTED_CURVE_VERSION = "delivery_adjusted_curve_v1"
DEFAULT_NEAR_CONTRACT = "CF609"
DEFAULT_FAR_CONTRACT = "CF611"
DEFAULT_AGING_DISCOUNT = 248.0
DEFAULT_STORAGE_COST_PER_TON_DAY = 48.07 / 62.0
DEFAULT_ANNUAL_FINANCING_RATE = 0.025
DEFAULT_HOLDING_DAYS = 62
DEFAULT_SCENARIO_START = date(2026, 1, 9)
DEFAULT_NEAR_ZERO_BAND = 20.0
DEFAULT_MIN_HISTORY_DAYS = 30
HUMAN_REVIEW_REQUIRED = (
    "aging_discount_rule_and_effective_date",
    "warehouse_storage_fee",
    "financing_rate_and_financing_base",
    "delivery_holding_days",
    "old_receipt_delivery_eligibility",
)
RESEARCH_BOUNDARY = {
    "scenario_cost_is_not_fair_value": True,
    "residual_is_not_an_arbitrage_boundary": True,
    "uses_observable_t_day_data_only": True,
    "automatic_signal_generation": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchDeliveryAdjustedCurveResult:
    """交割成本修正曲线产物和最新状态。"""

    run_id: str
    start: date
    end: date
    row_count: int
    near_contract: str
    far_contract: str
    latest_observed_spread: float
    latest_modeled_full_carry_cost: float
    latest_delivery_adjusted_residual: float
    latest_residual_state: str
    negative_residual_ratio: float
    oi_level_residual_correlation: float | None
    oi_change_spread_change_correlation: float | None
    warning_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    monthly_parquet_path: Path
    monthly_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_quote_path: Path

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": self.row_count,
            "near_contract": self.near_contract,
            "far_contract": self.far_contract,
            "latest_observed_spread": self.latest_observed_spread,
            "latest_modeled_full_carry_cost": self.latest_modeled_full_carry_cost,
            "latest_delivery_adjusted_residual": self.latest_delivery_adjusted_residual,
            "latest_residual_state": self.latest_residual_state,
            "negative_residual_ratio": self.negative_residual_ratio,
            "oi_level_residual_correlation": self.oi_level_residual_correlation,
            "oi_change_spread_change_correlation": (
                self.oi_change_spread_change_correlation
            ),
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "monthly_parquet_path": str(self.monthly_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_delivery_adjusted_curve(
    *,
    core_quote_path: Path | None = None,
    near_contract: str = DEFAULT_NEAR_CONTRACT,
    far_contract: str = DEFAULT_FAR_CONTRACT,
    start: date | None = DEFAULT_SCENARIO_START,
    end: date | None = None,
    aging_discount: float = DEFAULT_AGING_DISCOUNT,
    storage_cost_per_ton_day: float = DEFAULT_STORAGE_COST_PER_TON_DAY,
    annual_financing_rate: float = DEFAULT_ANNUAL_FINANCING_RATE,
    holding_days: int = DEFAULT_HOLDING_DAYS,
    near_zero_band: float = DEFAULT_NEAR_ZERO_BAND,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchDeliveryAdjustedCurveResult:
    """构建跨月价差相对显式交割成本情景的残差曲线。"""
    near_code = near_contract.strip().upper()
    far_code = far_contract.strip().upper()
    if near_code == far_code:
        raise ResearchWorkbenchError("near_contract and far_contract must be different")
    if not near_code.startswith(PRODUCT_CODE) or not far_code.startswith(PRODUCT_CODE):
        raise ResearchWorkbenchError("delivery-adjusted curve currently supports CF only")
    if aging_discount < 0 or storage_cost_per_ton_day < 0:
        raise ResearchWorkbenchError("delivery cost parameters cannot be negative")
    if annual_financing_rate < 0 or holding_days < 1:
        raise ResearchWorkbenchError("financing rate and holding_days must be non-negative")
    if near_zero_band < 0 or min_history_days < 1:
        raise ResearchWorkbenchError("near_zero_band and min_history_days are invalid")

    quote_path = core_quote_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    )
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
    daily = _build_daily_curve(
        quotes=quotes,
        near_contract=near_code,
        far_contract=far_code,
        start=start,
        end=end,
        aging_discount=aging_discount,
        storage_cost_per_ton_day=storage_cost_per_ton_day,
        annual_financing_rate=annual_financing_rate,
        holding_days=holding_days,
        near_zero_band=near_zero_band,
    )
    if daily.empty:
        raise ResearchWorkbenchError(
            f"no overlapping quote dates for {near_code} and {far_code}"
        )

    start = daily["trade_date"].min()
    effective_end = daily["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("delivery_curve", effective_end)
    daily.insert(0, "run_id", active_run_id)
    monthly = _build_monthly_summary(daily=daily, run_id=active_run_id)
    correlations = _correlation_summary(daily)
    warnings = _warning_rows(
        run_id=active_run_id,
        row_count=len(daily),
        min_history_days=min_history_days,
    )
    paths = _paths(
        start=start,
        end=effective_end,
        near_contract=near_code,
        far_contract=far_code,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(monthly, paths["monthly_parquet"], paths["monthly_csv"])
    write_warning_csv(paths["warning_csv"], warnings)

    latest = daily.iloc[-1].to_dict()
    negative_ratio = float(daily["delivery_adjusted_residual"].lt(0).mean())
    result = ResearchDeliveryAdjustedCurveResult(
        run_id=active_run_id,
        start=start,
        end=effective_end,
        row_count=len(daily),
        near_contract=near_code,
        far_contract=far_code,
        latest_observed_spread=float(latest["observed_spread"]),
        latest_modeled_full_carry_cost=float(latest["modeled_full_carry_cost"]),
        latest_delivery_adjusted_residual=float(
            latest["delivery_adjusted_residual"]
        ),
        latest_residual_state=str(latest["residual_state"]),
        negative_residual_ratio=negative_ratio,
        oi_level_residual_correlation=correlations["oi_level_residual"],
        oi_change_spread_change_correlation=correlations[
            "oi_change_spread_change"
        ],
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        monthly_parquet_path=paths["monthly_parquet"],
        monthly_csv_path=paths["monthly_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
    )
    _write_markdown(
        result=result,
        latest=latest,
        daily=daily,
        monthly=monthly,
        parameters={
            "aging_discount": aging_discount,
            "storage_cost_per_ton_day": storage_cost_per_ton_day,
            "annual_financing_rate": annual_financing_rate,
            "holding_days": holding_days,
            "near_zero_band": near_zero_band,
            "scenario_start": start,
        },
    )
    write_json(
        result.json_path,
        {
            "report_type": "delivery_adjusted_curve",
            "rule_version": DELIVERY_ADJUSTED_CURVE_VERSION,
            "summary": result.to_summary(),
            "parameters": {
                "aging_discount": aging_discount,
                "storage_cost_per_ton_day": storage_cost_per_ton_day,
                "annual_financing_rate": annual_financing_rate,
                "holding_days": holding_days,
                "near_zero_band": near_zero_band,
                "scenario_start": start,
            },
            "latest_state": latest,
            "correlations": correlations,
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="delivery_adjusted_curve",
            rule_version=DELIVERY_ADJUSTED_CURVE_VERSION,
            data_asof=effective_end,
            input_paths={"core_quote_path": quote_path},
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "monthly_parquet_path": result.monthly_parquet_path,
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _build_daily_curve(
    *,
    quotes: pd.DataFrame,
    near_contract: str,
    far_contract: str,
    start: date | None,
    end: date | None,
    aging_discount: float,
    storage_cost_per_ton_day: float,
    annual_financing_rate: float,
    holding_days: int,
    near_zero_band: float,
) -> pd.DataFrame:
    working = normalize_trade_date(quotes)
    working["contract_code"] = working["contract_code"].astype(str).str.upper()
    working = working.loc[
        working["contract_code"].isin({near_contract, far_contract})
    ].copy()
    if start is not None:
        working = working.loc[working["trade_date"].ge(start)].copy()
    if end is not None:
        working = working.loc[working["trade_date"].le(end)].copy()
    for column in ("close", "settle", "volume", "open_interest"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["settle", "open_interest"])

    fields = ["settle", "close", "volume", "open_interest"]
    wide = working.pivot_table(
        index="trade_date",
        columns="contract_code",
        values=fields,
        aggfunc="last",
    )
    required_columns = [
        (field, contract)
        for field in ("settle", "open_interest")
        for contract in (near_contract, far_contract)
    ]
    if any(column not in wide.columns for column in required_columns):
        return pd.DataFrame()
    wide = wide.dropna(subset=required_columns).sort_index()
    positive_oi = (wide[("open_interest", near_contract)] > 0) & (
        wide[("open_interest", far_contract)] > 0
    )
    wide = wide.loc[positive_oi]
    daily = pd.DataFrame(index=wide.index)
    for prefix, contract in (("near", near_contract), ("far", far_contract)):
        for field in fields:
            column = (field, contract)
            daily[f"{prefix}_{field}"] = wide[column] if column in wide.columns else pd.NA
    daily = daily.reset_index()
    daily["near_contract"] = near_contract
    daily["far_contract"] = far_contract
    daily["observed_spread"] = daily["far_settle"] - daily["near_settle"]
    daily["aging_discount"] = float(aging_discount)
    daily["storage_cost"] = float(storage_cost_per_ton_day * holding_days)
    # 资金成本以近月结算价为本金；该选择必须保留在人审项中。
    daily["financing_cost"] = (
        daily["near_settle"] * annual_financing_rate * holding_days / 365.0
    )
    daily["modeled_full_carry_cost"] = (
        daily["aging_discount"] + daily["storage_cost"] + daily["financing_cost"]
    )
    daily["delivery_adjusted_residual"] = (
        daily["observed_spread"] - daily["modeled_full_carry_cost"]
    )
    daily["observed_spread_change_1d"] = daily["observed_spread"].diff()
    daily["residual_change_1d"] = daily["delivery_adjusted_residual"].diff()
    daily["near_oi_change"] = daily["near_open_interest"].diff()
    daily["far_oi_change"] = daily["far_open_interest"].diff()
    daily["pair_oi_change"] = (
        daily["near_open_interest"] + daily["far_open_interest"]
    ).diff()
    daily["residual_zscore_20"] = _rolling_zscore(
        daily["delivery_adjusted_residual"], window=20
    )
    daily["residual_zscore_60"] = _rolling_zscore(
        daily["delivery_adjusted_residual"], window=60
    )
    daily["far_oi_percentile_60"] = _rolling_current_percentile(
        daily["far_open_interest"], window=60
    )
    daily["residual_percentile_60"] = _rolling_current_percentile(
        daily["delivery_adjusted_residual"], window=60
    )
    daily["residual_state"] = daily["delivery_adjusted_residual"].map(
        lambda value: _residual_state(float(value), near_zero_band)
    )
    daily["negative_residual_streak"] = _negative_streak(
        daily["delivery_adjusted_residual"]
    )
    daily["parameter_scenario"] = "explicit_delivery_cost_scenario"
    daily["rule_version"] = DELIVERY_ADJUSTED_CURVE_VERSION
    daily["trading_instruction"] = "not_a_trading_instruction"
    return daily


def _rolling_zscore(values: pd.Series, *, window: int) -> pd.Series:
    minimum = max(5, window // 4)
    mean = values.rolling(window, min_periods=minimum).mean()
    std = values.rolling(window, min_periods=minimum).std(ddof=0)
    return (values - mean) / std.replace(0, pd.NA)


def _rolling_current_percentile(values: pd.Series, *, window: int) -> pd.Series:
    minimum = max(5, window // 4)

    def current_percentile(sample: pd.Series) -> float:
        current = sample.iloc[-1]
        return float(sample.le(current).mean())

    return values.rolling(window, min_periods=minimum).apply(
        current_percentile,
        raw=False,
    )


def _negative_streak(values: pd.Series) -> pd.Series:
    streaks: list[int] = []
    current = 0
    for value in values:
        current = current + 1 if float(value) < 0 else 0
        streaks.append(current)
    return pd.Series(streaks, index=values.index, dtype="int64")


def _residual_state(value: float, near_zero_band: float) -> str:
    if value < -near_zero_band:
        return "BELOW_SCENARIO_COST"
    if value > near_zero_band:
        return "ABOVE_SCENARIO_COST"
    return "NEAR_SCENARIO_COST"


def _build_monthly_summary(*, daily: pd.DataFrame, run_id: str) -> pd.DataFrame:
    working = daily.copy()
    working["month"] = working["trade_date"].map(lambda value: value.strftime("%Y-%m"))
    rows: list[dict[str, object]] = []
    for month, group in working.groupby("month", sort=True):
        rows.append(
            {
                "run_id": run_id,
                "month": month,
                "sample_count": len(group),
                "mean_observed_spread": float(group["observed_spread"].mean()),
                "mean_modeled_full_carry_cost": float(
                    group["modeled_full_carry_cost"].mean()
                ),
                "mean_delivery_adjusted_residual": float(
                    group["delivery_adjusted_residual"].mean()
                ),
                "median_delivery_adjusted_residual": float(
                    group["delivery_adjusted_residual"].median()
                ),
                "negative_residual_ratio": float(
                    group["delivery_adjusted_residual"].lt(0).mean()
                ),
                "far_open_interest_mean": float(group["far_open_interest"].mean()),
                "far_open_interest_end": float(group.iloc[-1]["far_open_interest"]),
                "rule_version": DELIVERY_ADJUSTED_CURVE_VERSION,
            }
        )
    return pd.DataFrame(rows)


def _correlation_summary(daily: pd.DataFrame) -> dict[str, float | None]:
    return {
        "oi_level_residual": _safe_corr(
            daily["far_open_interest"], daily["delivery_adjusted_residual"]
        ),
        "oi_change_spread_change": _safe_corr(
            daily["far_oi_change"], daily["observed_spread_change_1d"]
        ),
    }


def _safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    aligned = pd.concat([left, right], axis=1).dropna()
    if len(aligned) < 3:
        return None
    if aligned.iloc[:, 0].nunique() < 2 or aligned.iloc[:, 1].nunique() < 2:
        return None
    value = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    return None if pd.isna(value) else float(value)


def _warning_rows(
    *, run_id: str, row_count: int, min_history_days: int
) -> list[dict[str, object]]:
    return [
        {
            "run_id": run_id,
            "section": "scenario_parameters",
            "severity": "WARN",
            "warning_code": "DELIVERY_COST_SCENARIO_REVIEW",
            "warning_message": (
                "老化贴水、仓储、资金成本和持有天数均为显式研究情景，"
                "不是交易所公布的无套利边界。"
            ),
            "affected_count": row_count,
            "human_review_required": ";".join(HUMAN_REVIEW_REQUIRED),
        },
        {
            "run_id": run_id,
            "section": "history",
            "severity": "WARN" if row_count < min_history_days else "INFO",
            "warning_code": "DELIVERY_CURVE_SHORT_HISTORY",
            "warning_message": "重叠交易日不足，滚动分位和相关性只作描述。",
            "affected_count": row_count,
            "human_review_required": "delivery_holding_days",
        },
    ]


def _paths(
    *,
    start: date,
    end: date,
    near_contract: str,
    far_contract: str,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    pair = f"{near_contract}_{far_contract}"
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_{pair}_delivery_adjusted_curve"
    data_root = output_dir or (
        data_dir() / "research" / PRODUCT_CODE / "delivery_adjusted_curve"
    )
    report_root = report_output_dir or (
        reports_dir() / "research" / "delivery_adjusted_curve"
    )
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "monthly_parquet": data_root / f"{stem}_monthly.parquet",
        "monthly_csv": data_root / f"{stem}_monthly.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _write_markdown(
    *,
    result: ResearchDeliveryAdjustedCurveResult,
    latest: dict[str, object],
    daily: pd.DataFrame,
    monthly: pd.DataFrame,
    parameters: dict[str, object],
) -> None:
    recent = daily.tail(10)
    lines = [
        f"# CF {result.near_contract}/{result.far_contract}交割成本修正曲线",
        "",
        f"数据截至：`{result.end.isoformat()}`",
        "",
        "## 最新状态",
        "",
        f"- 观察价差（远月减近月）：`{fmt_number(latest['observed_spread'], 2)}` 元/吨",
        f"- 老化贴水情景：`{fmt_number(parameters['aging_discount'], 2)}` 元/吨",
        f"- 仓储成本情景：`{fmt_number(latest['storage_cost'], 2)}` 元/吨",
        f"- 资金成本情景：`{fmt_number(latest['financing_cost'], 2)}` 元/吨",
        f"- 完整持有成本情景：`{fmt_number(latest['modeled_full_carry_cost'], 2)}` 元/吨",
        f"- 交割成本修正残差：`{fmt_number(latest['delivery_adjusted_residual'], 2)}` 元/吨",
        f"- 状态：`{latest['residual_state']}`",
        f"- 连续负残差：`{fmt_number(latest['negative_residual_streak'], 0)}` 个交易日",
        "",
        "## 参数口径",
        "",
        f"- 持有天数：`{parameters['holding_days']}` 个自然日",
        f"- 情景适用起始日：`{parameters['scenario_start']}`",
        f"- 日仓储成本：`{fmt_number(parameters['storage_cost_per_ton_day'], 4)}` 元/吨",
        f"- 年化资金利率：`{fmt_percent(parameters['annual_financing_rate'])}`",
        "- 资金成本本金采用近月当日结算价。",
        "",
        "## 月度演变",
        "",
        "| 月份 | 样本 | 平均观察价差 | 平均情景成本 | 平均残差 | 负残差占比 | 远月月末OI |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in monthly.to_dict(orient="records"):
        lines.append(
            f"| {row['month']} | {row['sample_count']} | "
            f"{fmt_number(row['mean_observed_spread'], 2)} | "
            f"{fmt_number(row['mean_modeled_full_carry_cost'], 2)} | "
            f"{fmt_number(row['mean_delivery_adjusted_residual'], 2)} | "
            f"{fmt_percent(row['negative_residual_ratio'])} | "
            f"{fmt_number(row['far_open_interest_end'], 0)} |"
        )
    lines.extend(
        [
            "",
            "## 最近交易日",
            "",
            "| 日期 | 近月结算 | 远月结算 | 观察价差 | 情景成本 | 残差 | 远月OI |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in recent.to_dict(orient="records"):
        lines.append(
            f"| {row['trade_date']} | {fmt_number(row['near_settle'], 0)} | "
            f"{fmt_number(row['far_settle'], 0)} | "
            f"{fmt_number(row['observed_spread'], 2)} | "
            f"{fmt_number(row['modeled_full_carry_cost'], 2)} | "
            f"{fmt_number(row['delivery_adjusted_residual'], 2)} | "
            f"{fmt_number(row['far_open_interest'], 0)} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 本结果是显式参数下的交割选择压力测试，不是理论公允价。",
            "- 负残差只表示市场价差未覆盖全部情景成本，不构成必然回归或套利结论。",
            "- 老化贴水规则、生效日期、新棉可交割时间、仓储和资金口径均需人工复核。",
            "- 相关性只描述共变，不识别持仓主体、交易动机或因果关系。",
            "- 本模块仅使用当日及以前可观察行情，不读取 forward return。",
            "- 不改变 `composite_score`，不构成交易指令。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")
