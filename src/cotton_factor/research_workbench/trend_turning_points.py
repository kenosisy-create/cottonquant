"""CF trend start/end research from normalized core quotes and factor states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
TREND_OUTPUT_DIR = "trend_turning_points"
DEFAULT_MOMENTUM_LOOKBACK = 20
DEFAULT_MA_LOOKBACK = 20
DEFAULT_MIN_CONFIRM_DAYS = 2


@dataclass(frozen=True)
class ResearchTrendTurningPointResult:
    """Result of CF trend start/end research."""

    product_code: str
    start: date
    end: date
    daily_row_count: int
    segment_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    segment_parquet_path: Path
    segment_csv_path: Path
    markdown_path: Path
    warnings: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable summary."""
        return {
            "product_code": self.product_code,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "daily_row_count": self.daily_row_count,
            "segment_count": self.segment_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "daily_csv_path": str(self.daily_csv_path),
            "segment_parquet_path": str(self.segment_parquet_path),
            "segment_csv_path": str(self.segment_csv_path),
            "markdown_path": str(self.markdown_path),
            "warnings": list(self.warnings),
        }


def build_cf_trend_turning_point_analysis(
    *,
    start: date,
    end: date,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    momentum_lookback: int = DEFAULT_MOMENTUM_LOOKBACK,
    ma_lookback: int = DEFAULT_MA_LOOKBACK,
    min_confirm_days: int = DEFAULT_MIN_CONFIRM_DAYS,
) -> ResearchTrendTurningPointResult:
    """Build CF trend start/end research artifacts from normalized core quotes."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    if momentum_lookback <= 0 or ma_lookback <= 0:
        raise ResearchWorkbenchError("lookbacks must be positive")
    if min_confirm_days <= 0:
        raise ResearchWorkbenchError("min_confirm_days must be positive")

    input_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = _load_core_quotes(input_path=input_path, start=start, end=end)
    daily = _build_daily_trend_table(
        quotes=quotes,
        momentum_lookback=momentum_lookback,
        ma_lookback=ma_lookback,
    )
    segments = _build_trend_segments(daily=daily, min_confirm_days=min_confirm_days)

    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    _write_frame(frame=daily, parquet_path=paths["daily_parquet"], csv_path=paths["daily_csv"])
    _write_frame(
        frame=segments,
        parquet_path=paths["segment_parquet"],
        csv_path=paths["segment_csv"],
    )

    warnings = _warnings(daily=daily, segments=segments)
    result = ResearchTrendTurningPointResult(
        product_code=PRODUCT_CODE,
        start=start,
        end=end,
        daily_row_count=len(daily),
        segment_count=len(segments),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        segment_parquet_path=paths["segment_parquet"],
        segment_csv_path=paths["segment_csv"],
        markdown_path=markdown_path,
        warnings=warnings,
    )
    _write_markdown(
        markdown_path=markdown_path,
        result=result,
        daily=daily,
        segments=segments,
        momentum_lookback=momentum_lookback,
        ma_lookback=ma_lookback,
        min_confirm_days=min_confirm_days,
    )
    return result


def _load_core_quotes(*, input_path: Path, start: date, end: date) -> pd.DataFrame:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"core quote parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    required = {
        "trade_date",
        "product_code",
        "contract_code",
        "settle",
        "volume",
        "open_interest",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"core quote table missing columns: {missing}")

    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[
        (working["product_code"].astype(str).str.upper() == PRODUCT_CODE)
        & (working["trade_date"] >= start)
        & (working["trade_date"] <= end)
    ].copy()
    if selected.empty:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} core quote rows from {start.isoformat()} to {end.isoformat()}"
        )
    selected["settle"] = pd.to_numeric(selected["settle"], errors="coerce")
    selected["volume"] = pd.to_numeric(selected["volume"], errors="coerce")
    selected["open_interest"] = pd.to_numeric(selected["open_interest"], errors="coerce")
    selected = selected.dropna(subset=["settle", "open_interest"])
    if selected.empty:
        raise ResearchWorkbenchError("selected core quote rows have no settle/open_interest")
    return selected.sort_values(["trade_date", "contract_code"]).reset_index(drop=True)


def _build_daily_trend_table(
    *,
    quotes: pd.DataFrame,
    momentum_lookback: int,
    ma_lookback: int,
) -> pd.DataFrame:
    enriched = quotes.copy()
    enriched["delivery_year"] = [
        _infer_delivery_year(contract_code=str(row.contract_code), trade_date=row.trade_date)
        for row in enriched.itertuples(index=False)
    ]
    enriched["delivery_month"] = enriched["contract_code"].astype(str).str[-2:].astype(int)
    enriched["delivery_date"] = pd.to_datetime(
        enriched["delivery_year"].astype(str)
        + "-"
        + enriched["delivery_month"].astype(str).str.zfill(2)
        + "-01"
    ).dt.date

    main_rows = _main_contract_rows(enriched)
    main_rows["main_oi_pressure"] = _main_oi_pressure(enriched=enriched, main_rows=main_rows)
    far_rows = _far_leg_rows(enriched=enriched, main_rows=main_rows)
    daily = main_rows.merge(far_rows, on="trade_date", how="left")
    daily = daily.sort_values("trade_date").reset_index(drop=True)

    daily["ma20"] = daily["settle"].rolling(ma_lookback, min_periods=ma_lookback).mean()
    daily["momentum_20"] = daily["settle"] / daily["settle"].shift(momentum_lookback) - 1
    daily["curve_slope"] = daily["far_settle"] / daily["settle"] - 1
    tenor_days = (
        pd.to_datetime(daily["far_delivery_date"]) - pd.to_datetime(daily["delivery_date"])
    ).dt.days
    daily["carry_annualized"] = (daily["far_settle"] / daily["settle"] - 1) * (
        365 / tenor_days
    )
    daily.loc[tenor_days <= 0, "carry_annualized"] = pd.NA

    # 趋势确认不直接使用价格涨跌一个条件，而是要求价格位置、动量和结构/OI 因子共振。
    daily["factor_score"] = daily.apply(_factor_score, axis=1)
    daily["available_factor_count"] = daily.apply(_available_factor_count, axis=1)
    daily["raw_trend_state"] = daily.apply(_raw_trend_state, axis=1)
    daily["trend_rule_version"] = "cf_trend_factor_confirmation_v1"
    return daily[
        [
            "trade_date",
            "contract_code",
            "settle",
            "open_interest",
            "volume",
            "delivery_date",
            "far_contract_code",
            "far_settle",
            "far_delivery_date",
            "ma20",
            "momentum_20",
            "carry_annualized",
            "curve_slope",
            "main_oi_pressure",
            "factor_score",
            "available_factor_count",
            "raw_trend_state",
            "trend_rule_version",
        ]
    ]


def _main_contract_rows(enriched: pd.DataFrame) -> pd.DataFrame:
    ranked = enriched.sort_values(
        ["trade_date", "open_interest", "volume", "contract_code"],
        ascending=[True, False, False, True],
    )
    main = ranked.groupby("trade_date", as_index=False).head(1).copy()
    return main[
        [
            "trade_date",
            "contract_code",
            "settle",
            "open_interest",
            "volume",
            "delivery_date",
        ]
    ].reset_index(drop=True)


def _main_oi_pressure(*, enriched: pd.DataFrame, main_rows: pd.DataFrame) -> pd.Series:
    working = enriched.sort_values(["contract_code", "trade_date"]).copy()
    working["contract_oi_pressure"] = working.groupby("contract_code")["open_interest"].pct_change()
    values = main_rows[["trade_date", "contract_code"]].merge(
        working[["trade_date", "contract_code", "contract_oi_pressure"]],
        on=["trade_date", "contract_code"],
        how="left",
    )
    return values["contract_oi_pressure"]


def _far_leg_rows(*, enriched: pd.DataFrame, main_rows: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    quotes_by_date = {key: value for key, value in enriched.groupby("trade_date")}
    for row in main_rows.itertuples(index=False):
        date_quotes = quotes_by_date[row.trade_date]
        candidates = date_quotes.loc[
            (date_quotes["delivery_date"] > row.delivery_date)
            & date_quotes["settle"].notna()
        ].sort_values(["delivery_date", "contract_code"])
        if candidates.empty:
            records.append(
                {
                    "trade_date": row.trade_date,
                    "far_contract_code": None,
                    "far_settle": pd.NA,
                    "far_delivery_date": pd.NaT,
                }
            )
            continue
        far = candidates.iloc[0]
        records.append(
            {
                "trade_date": row.trade_date,
                "far_contract_code": far["contract_code"],
                "far_settle": far["settle"],
                "far_delivery_date": far["delivery_date"],
            }
        )
    return pd.DataFrame(records)


def _factor_score(row: pd.Series) -> int:
    values = [
        row.get("momentum_20"),
        row.get("carry_annualized"),
        row.get("curve_slope"),
        row.get("main_oi_pressure"),
    ]
    score = 0
    for value in values:
        if pd.isna(value):
            continue
        if float(value) > 0:
            score += 1
        elif float(value) < 0:
            score -= 1
    return score


def _available_factor_count(row: pd.Series) -> int:
    values = [
        row.get("momentum_20"),
        row.get("carry_annualized"),
        row.get("curve_slope"),
        row.get("main_oi_pressure"),
    ]
    return sum(0 if pd.isna(value) else 1 for value in values)


def _raw_trend_state(row: pd.Series) -> str:
    if row["available_factor_count"] < 3 or pd.isna(row["ma20"]) or pd.isna(row["momentum_20"]):
        return "unknown"
    if row["factor_score"] >= 2 and row["momentum_20"] > 0 and row["settle"] > row["ma20"]:
        return "uptrend_candidate"
    if row["factor_score"] <= -2 and row["momentum_20"] < 0 and row["settle"] < row["ma20"]:
        return "downtrend_candidate"
    return "neutral"


def _build_trend_segments(*, daily: pd.DataFrame, min_confirm_days: int) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    candidates = daily.loc[
        daily["raw_trend_state"].isin(["uptrend_candidate", "downtrend_candidate"])
    ].copy()
    if candidates.empty:
        return _empty_segments()

    daily_by_date = {row.trade_date: row for row in daily.itertuples(index=False)}
    current_rows: list[Any] = []
    current_state: str | None = None
    for row in daily.itertuples(index=False):
        state = row.raw_trend_state
        if state not in {"uptrend_candidate", "downtrend_candidate"}:
            _flush_segment(
                records=records,
                segment_rows=current_rows,
                daily_by_date=daily_by_date,
                min_confirm_days=min_confirm_days,
            )
            current_rows = []
            current_state = None
            continue
        if current_state is None or state == current_state:
            current_rows.append(row)
            current_state = state
            continue
        _flush_segment(
            records=records,
            segment_rows=current_rows,
            daily_by_date=daily_by_date,
            min_confirm_days=min_confirm_days,
        )
        current_rows = [row]
        current_state = state
    _flush_segment(
        records=records,
        segment_rows=current_rows,
        daily_by_date=daily_by_date,
        min_confirm_days=min_confirm_days,
    )
    if not records:
        return _empty_segments()
    return pd.DataFrame(records)


def _flush_segment(
    *,
    records: list[dict[str, Any]],
    segment_rows: list[Any],
    daily_by_date: dict[date, Any],
    min_confirm_days: int,
) -> None:
    if len(segment_rows) < min_confirm_days:
        return
    first = segment_rows[0]
    confirm = segment_rows[min_confirm_days - 1]
    last = segment_rows[-1]
    direction = "uptrend" if first.raw_trend_state == "uptrend_candidate" else "downtrend"
    prices = [float(row.settle) for row in segment_rows]
    trend_return = prices[-1] / prices[0] - 1
    if direction == "uptrend":
        max_adverse = _max_drawdown(prices)
    else:
        max_adverse = _max_runup_against_short(prices)
    records.append(
        {
            "segment_id": (
                f"{direction}_{first.trade_date.isoformat()}_"
                f"{last.trade_date.isoformat()}"
            ),
            "direction": direction,
            "start_date": first.trade_date,
            "confirmation_date": confirm.trade_date,
            "end_date": last.trade_date,
            "duration_days": len(segment_rows),
            "start_contract": first.contract_code,
            "end_contract": last.contract_code,
            "start_price": first.settle,
            "end_price": last.settle,
            "trend_return": trend_return,
            "max_adverse_move": max_adverse,
            "start_factor_score": first.factor_score,
            "confirmation_factor_score": confirm.factor_score,
            "end_factor_score": last.factor_score,
            "end_reason": _end_reason(last=last, daily_by_date=daily_by_date),
        }
    )


def _end_reason(*, last: Any, daily_by_date: dict[date, Any]) -> str:
    dates = sorted(daily_by_date)
    try:
        next_date = dates[dates.index(last.trade_date) + 1]
    except (ValueError, IndexError):
        return "sample_end"
    next_state = daily_by_date[next_date].raw_trend_state
    if next_state == "neutral":
        return "factor_confirmation_lost"
    if next_state == "unknown":
        return "factor_inputs_unknown"
    return f"reversed_or_changed_to_{next_state}"


def _max_drawdown(prices: list[float]) -> float:
    peak = prices[0]
    worst = 0.0
    for price in prices:
        peak = max(peak, price)
        worst = min(worst, price / peak - 1)
    return worst


def _max_runup_against_short(prices: list[float]) -> float:
    trough = prices[0]
    worst = 0.0
    for price in prices:
        trough = min(trough, price)
        worst = max(worst, price / trough - 1)
    return worst


def _empty_segments() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "segment_id",
            "direction",
            "start_date",
            "confirmation_date",
            "end_date",
            "duration_days",
            "start_contract",
            "end_contract",
            "start_price",
            "end_price",
            "trend_return",
            "max_adverse_move",
            "start_factor_score",
            "confirmation_factor_score",
            "end_factor_score",
            "end_reason",
        ]
    )


def _infer_delivery_year(*, contract_code: str, trade_date: date) -> int:
    suffix = contract_code.strip().upper().removeprefix(PRODUCT_CODE)
    if len(suffix) != 3 or not suffix.isdigit():
        raise ResearchWorkbenchError(f"unsupported CF contract code: {contract_code}")
    year_digit = int(suffix[0])
    candidates = [
        year
        for year in range(trade_date.year - 1, trade_date.year + 3)
        if year % 10 == year_digit
    ]
    if not candidates:
        raise ResearchWorkbenchError(
            f"cannot infer delivery year for {contract_code} near {trade_date.year}"
        )
    return min(candidates, key=lambda year: (abs(year - trade_date.year), year < trade_date.year))


def _write_frame(*, frame: pd.DataFrame, parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _warnings(*, daily: pd.DataFrame, segments: pd.DataFrame) -> tuple[str, ...]:
    values: list[str] = [
        "趋势起点/终点为研究级事后识别，confirmation_date 才代表可观察确认日期",
        "主力合约按持仓量排序选择，未替代 R08 正式链映射规则",
        "因子方向使用 MVP 符号规则，阈值和权重仍需人工复核",
    ]
    unknown_count = int((daily["raw_trend_state"] == "unknown").sum())
    if unknown_count:
        values.append(f"{unknown_count} rows are unknown because factor inputs are incomplete")
    if segments.empty:
        values.append("no trend segment met the confirmation rule")
    return tuple(values)


def _write_markdown(
    *,
    markdown_path: Path,
    result: ResearchTrendTurningPointResult,
    daily: pd.DataFrame,
    segments: pd.DataFrame,
    momentum_lookback: int,
    ma_lookback: int,
    min_confirm_days: int,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    state_counts = daily["raw_trend_state"].value_counts().to_dict()
    lines = [
        f"# CF 趋势起点与终点识别 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 研究规则",
        "",
        f"- 动量窗口：`{momentum_lookback}` 个交易日",
        f"- 均线窗口：`{ma_lookback}` 个交易日",
        f"- 最小确认天数：`{min_confirm_days}` 个交易日",
        "- 上行趋势确认：价格在均线上方，20日动量为正，四类因子至少 3 个可用且合计分数 >= 2。",
        "- 下行趋势确认：价格在均线下方，20日动量为负，四类因子至少 3 个可用且合计分数 <= -2。",
        "- start_date 是事后趋势段起点；confirmation_date 是实际研究中可确认日期。",
        "",
        "## 状态分布",
        "",
    ]
    lines.extend(f"- `{key}`: `{value}`" for key, value in state_counts.items())
    lines.extend(["", "## 趋势段", ""])
    if segments.empty:
        lines.append("- 未发现满足确认规则的趋势段。")
    else:
        lines.append(
            "| 方向 | 起点 | 确认日 | 终点 | 天数 | 起始合约 | 结束合约 | "
            "趋势收益 | 最大不利变动 | 结束原因 |"
        )
        lines.append("| --- | --- | --- | --- | ---: | --- | --- | ---: | ---: | --- |")
        for row in segments.itertuples(index=False):
            lines.append(
                "| "
                f"{row.direction} | {row.start_date} | {row.confirmation_date} | "
                f"{row.end_date} | {row.duration_days} | {row.start_contract} | "
                f"{row.end_contract} | {row.trend_return:.4%} | "
                f"{row.max_adverse_move:.4%} | {row.end_reason} |"
            )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 本报告用于确认趋势段和复盘因子共振，不生成交易指令。",
            "- 规则仍需结合更多窗口验证后，才能作为日常研究模板。",
            "",
            "## 输出文件",
            "",
            f"- Daily parquet: `{result.daily_parquet_path}`",
            f"- Segment parquet: `{result.segment_parquet_path}`",
            f"- Daily CSV: `{result.daily_csv_path}`",
            f"- Segment CSV: `{result.segment_csv_path}`",
            "",
            "## Warnings",
            "",
        ]
    )
    lines.extend(f"- {warning}" for warning in result.warnings)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / TREND_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "daily_parquet": root / f"{stem}_trend_daily.parquet",
        "daily_csv": root / f"{stem}_trend_daily.csv",
        "segment_parquet": root / f"{stem}_trend_segments.parquet",
        "segment_csv": root / f"{stem}_trend_segments.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / TREND_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_turning_points"
    return root / f"{stem}.md"
