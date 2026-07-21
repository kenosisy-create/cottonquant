"""R84 CF 期权行权价持仓关键点位、迁移和后验穿越研究。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.option_data_contract import (
    CORE_OPTION_QUOTE_FILE_NAME,
)
from cotton_factor.research_workbench.option_expiry_registry import (
    load_option_expiry_registry,
    resolve_option_expiry,
)
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
RULE_VERSION = "R84_option_strike_position_research_v1"
DEFAULT_HORIZONS = (1, 3, 5, 10)
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_NEAR_LEVEL_RATIO = 0.01
HUMAN_REVIEW_REQUIRED = (
    "option_open_interest_long_short_ownership_unknown",
    "call_put_wall_interpretation",
    "max_pain_static_open_interest_assumption",
    "option_expiry_registry_fallback",
    "historical_level_touch_interpretation",
)
RESEARCH_BOUNDARY = {
    "option_open_interest_ownership_is_unknown": True,
    "dealer_gamma_is_not_inferred": True,
    "key_strikes_are_structural_observation_levels": True,
    "forward_paths_are_historical_posterior_labels": True,
    "latest_state_uses_future_data": False,
    "composite_score_modified": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchOptionStrikePositionResult:
    """R84 输出路径与最新主力期权关键点位。"""

    run_id: str
    start: date
    end: date
    daily_row_count: int
    strike_row_count: int
    validation_row_count: int
    validation_summary_row_count: int
    warning_count: int
    latest_main_contract: str | None
    latest_call_wall: float | None
    latest_put_wall: float | None
    latest_max_pain: float | None
    latest_key_level_state: str
    daily_parquet_path: Path
    daily_csv_path: Path
    strike_parquet_path: Path
    strike_csv_path: Path
    validation_parquet_path: Path
    validation_csv_path: Path
    validation_summary_parquet_path: Path
    validation_summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    option_core_path: Path
    core_quote_path: Path
    option_expiry_path: Path | None

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "daily_row_count": self.daily_row_count,
            "strike_row_count": self.strike_row_count,
            "validation_row_count": self.validation_row_count,
            "validation_summary_row_count": self.validation_summary_row_count,
            "warning_count": self.warning_count,
            "latest_main_contract": self.latest_main_contract,
            "latest_call_wall": self.latest_call_wall,
            "latest_put_wall": self.latest_put_wall,
            "latest_max_pain": self.latest_max_pain,
            "latest_key_level_state": self.latest_key_level_state,
            "daily_parquet_path": str(self.daily_parquet_path),
            "strike_parquet_path": str(self.strike_parquet_path),
            "validation_parquet_path": str(self.validation_parquet_path),
            "validation_summary_parquet_path": str(
                self.validation_summary_parquet_path
            ),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "option_core_path": str(self.option_core_path),
            "core_quote_path": str(self.core_quote_path),
            "option_expiry_path": (
                None if self.option_expiry_path is None else str(self.option_expiry_path)
            ),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_option_strike_position_research(
    *,
    option_core_path: Path | None = None,
    core_quote_path: Path | None = None,
    option_expiry_path: Path | None = None,
    end: date | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    near_level_ratio: float = DEFAULT_NEAR_LEVEL_RATIO,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchOptionStrikePositionResult:
    """从期权 core 构建关键行权价结构，不推断未知的买卖方身份。"""
    normalized_horizons = tuple(sorted(set(int(value) for value in horizons)))
    if not normalized_horizons or any(value < 1 for value in normalized_horizons):
        raise ResearchWorkbenchError("horizons must contain positive values")
    if near_level_ratio <= 0 or near_level_ratio > 0.20:
        raise ResearchWorkbenchError("near_level_ratio must be within (0, 0.20]")
    if min_sample_size < 1:
        raise ResearchWorkbenchError("min_sample_size must be positive")
    option_path = option_core_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_OPTION_QUOTE_FILE_NAME
    )
    quote_path = core_quote_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    )
    options = _load_options(option_path)
    quotes = _load_quotes(quote_path)
    if end is not None:
        options = options.loc[options["trade_date"].le(end)].copy()
        quotes = quotes.loc[quotes["trade_date"].le(end)].copy()
    if options.empty:
        raise ResearchWorkbenchError("R84 has no option rows after date filter")
    start = options["trade_date"].min()
    effective_end = options["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("r84_option_strike", effective_end)
    expiry_registry = load_option_expiry_registry(option_expiry_path)

    strike = _build_strike_detail(options=options, quotes=quotes, run_id=active_run_id)
    daily = _build_daily_levels(
        strike=strike,
        quotes=quotes,
        expiry_registry=expiry_registry,
        near_level_ratio=near_level_ratio,
        run_id=active_run_id,
    )
    validation = _build_path_validation(
        daily=daily,
        quotes=quotes,
        horizons=normalized_horizons,
        run_id=active_run_id,
    )
    validation_summary = _build_validation_summary(
        validation=validation,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    warnings = _warning_rows(
        options=options,
        daily=daily,
        validation_summary=validation_summary,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    paths = _paths(
        start=start,
        end=effective_end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(strike, paths["strike_parquet"], paths["strike_csv"])
    write_frame(validation, paths["validation_parquet"], paths["validation_csv"])
    write_frame(
        validation_summary,
        paths["validation_summary_parquet"],
        paths["validation_summary_csv"],
    )
    write_warning_csv(paths["warning_csv"], warnings)
    latest = daily.loc[
        daily["trade_date"].eq(effective_end) & daily["is_main_contract"].astype(bool)
    ]
    latest_row = None if latest.empty else latest.iloc[0].to_dict()
    result = ResearchOptionStrikePositionResult(
        run_id=active_run_id,
        start=start,
        end=effective_end,
        daily_row_count=len(daily),
        strike_row_count=len(strike),
        validation_row_count=len(validation),
        validation_summary_row_count=len(validation_summary),
        warning_count=sum(1 for row in warnings if row["severity"] == "WARN"),
        latest_main_contract=(
            None if latest_row is None else str(latest_row["underlying_contract"])
        ),
        latest_call_wall=_row_float(latest_row, "call_wall_strike"),
        latest_put_wall=_row_float(latest_row, "put_wall_strike"),
        latest_max_pain=_row_float(latest_row, "max_pain_strike"),
        latest_key_level_state=(
            "not_available" if latest_row is None else str(latest_row["key_level_state"])
        ),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        strike_parquet_path=paths["strike_parquet"],
        strike_csv_path=paths["strike_csv"],
        validation_parquet_path=paths["validation_parquet"],
        validation_csv_path=paths["validation_csv"],
        validation_summary_parquet_path=paths["validation_summary_parquet"],
        validation_summary_csv_path=paths["validation_summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        option_core_path=option_path,
        core_quote_path=quote_path,
        option_expiry_path=option_expiry_path,
    )
    _write_markdown(
        result=result,
        latest_row=latest_row,
        strike=strike,
        validation_summary=validation_summary,
        warnings=warnings,
    )
    latest_strikes = strike.loc[
        strike["trade_date"].eq(effective_end)
        & strike["underlying_contract"].eq(result.latest_main_contract)
    ].to_dict(orient="records")
    write_json(
        result.json_path,
        {
            "report_type": "cf_option_strike_position_research",
            "rule_version": RULE_VERSION,
            "summary": result.to_summary(),
            "latest_main_state": latest_row,
            "latest_main_strikes": latest_strikes,
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="cf_option_strike_position_research",
            rule_version=RULE_VERSION,
            data_asof=effective_end,
            input_paths={
                "option_core_path": option_path,
                "core_quote_path": quote_path,
                "option_expiry_path": option_expiry_path,
            },
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "strike_parquet_path": result.strike_parquet_path,
                "validation_parquet_path": result.validation_parquet_path,
                "validation_summary_parquet_path": result.validation_summary_parquet_path,
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _load_options(path: Path) -> pd.DataFrame:
    frame = load_table(
        path,
        required={
            "trade_date",
            "option_symbol",
            "underlying_contract",
            "option_type",
            "strike",
            "open_interest",
            "data_quality_flag",
        },
        label="CF option core",
    )
    frame = normalize_trade_date(frame)
    for column in ("strike", "open_interest"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["option_type"] = frame["option_type"].astype(str).str.upper()
    frame["underlying_contract"] = (
        frame["underlying_contract"].astype(str).str.upper()
    )
    frame["option_symbol"] = frame["option_symbol"].astype(str).str.upper()
    frame = frame.loc[
        frame["option_type"].isin(["C", "P"])
        & frame["strike"].gt(0)
        & frame["open_interest"].notna()
        & frame["open_interest"].ge(0)
    ].copy()
    frame = frame.sort_values(["option_symbol", "trade_date"])
    frame["open_interest_change"] = frame.groupby("option_symbol")[
        "open_interest"
    ].diff()
    return frame


def _load_quotes(path: Path) -> pd.DataFrame:
    frame = load_table(
        path,
        required={
            "trade_date",
            "contract_code",
            "settle",
            "high",
            "low",
            "open_interest",
        },
        label="CF core quote",
    )
    frame = normalize_trade_date(frame)
    for column in ("settle", "high", "low", "open_interest"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["contract_code"] = frame["contract_code"].astype(str).str.upper()
    return frame.sort_values(["contract_code", "trade_date"]).reset_index(drop=True)


def _build_strike_detail(
    *, options: pd.DataFrame, quotes: pd.DataFrame, run_id: str
) -> pd.DataFrame:
    grouped = (
        options.groupby(
            ["trade_date", "underlying_contract", "strike", "option_type"],
            dropna=False,
        )
        .agg(
            open_interest=("open_interest", "sum"),
            open_interest_change=(
                "open_interest_change",
                lambda values: values.sum(min_count=1),
            ),
            option_count=("option_symbol", "nunique"),
        )
        .reset_index()
    )
    index_columns = ["trade_date", "underlying_contract", "strike"]
    value = grouped.pivot_table(
        index=index_columns,
        columns="option_type",
        values="open_interest",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    change = grouped.pivot_table(
        index=index_columns,
        columns="option_type",
        values="open_interest_change",
        aggfunc="sum",
    ).reset_index()
    value = value.rename(columns={"C": "call_open_interest", "P": "put_open_interest"})
    change = change.rename(
        columns={"C": "call_open_interest_change", "P": "put_open_interest_change"}
    )
    detail = value.merge(change, on=index_columns, how="left")
    for column in ("call_open_interest", "put_open_interest"):
        if column not in detail.columns:
            detail[column] = 0.0
        detail[column] = pd.to_numeric(detail[column], errors="coerce").fillna(0.0)
    for column in ("call_open_interest_change", "put_open_interest_change"):
        if column not in detail.columns:
            detail[column] = np.nan
    quote = quotes[
        ["trade_date", "contract_code", "settle", "open_interest"]
    ].rename(
        columns={
            "contract_code": "underlying_contract",
            "settle": "underlying_settle",
            "open_interest": "underlying_open_interest",
        }
    )
    detail = detail.merge(
        quote,
        on=["trade_date", "underlying_contract"],
        how="left",
        validate="many_to_one",
    )
    detail.insert(0, "run_id", run_id)
    detail["call_oi_share"] = detail.groupby(
        ["trade_date", "underlying_contract"]
    )["call_open_interest"].transform(
        lambda values: values / values.sum() if values.sum() > 0 else np.nan
    )
    detail["put_oi_share"] = detail.groupby(
        ["trade_date", "underlying_contract"]
    )["put_open_interest"].transform(
        lambda values: values / values.sum() if values.sum() > 0 else np.nan
    )
    detail["distance_to_underlying"] = (
        detail["strike"] - detail["underlying_settle"]
    ) / detail["underlying_settle"]
    detail["model_boundary"] = "open_interest_ownership_unknown_no_dealer_gamma_inference"
    return detail.sort_values(
        ["trade_date", "underlying_contract", "strike"]
    ).reset_index(drop=True)


def _build_daily_levels(
    *,
    strike: pd.DataFrame,
    quotes: pd.DataFrame,
    expiry_registry: pd.DataFrame,
    near_level_ratio: float,
    run_id: str,
) -> pd.DataFrame:
    main_lookup = _main_contract_lookup(quotes)
    rows: list[dict[str, object]] = []
    for (trade_date, contract), group in strike.groupby(
        ["trade_date", "underlying_contract"], sort=True
    ):
        underlying = _first_number(group["underlying_settle"])
        if underlying is None or underlying <= 0:
            continue
        call_wall = _max_oi_row(group, "call_open_interest")
        put_wall = _max_oi_row(group, "put_open_interest")
        call_build = _extreme_change_row(group, "call_open_interest_change", positive=True)
        call_unwind = _extreme_change_row(group, "call_open_interest_change", positive=False)
        put_build = _extreme_change_row(group, "put_open_interest_change", positive=True)
        put_unwind = _extreme_change_row(group, "put_open_interest_change", positive=False)
        call_total = float(group["call_open_interest"].sum())
        put_total = float(group["put_open_interest"].sum())
        call_center = _weighted_center(group, "call_open_interest")
        put_center = _weighted_center(group, "put_open_interest")
        max_pain = _max_pain_strike(group)
        expiry = resolve_option_expiry(
            underlying_contract=str(contract),
            trade_date=trade_date,
            registry=expiry_registry,
        )
        call_wall_strike = _series_number(call_wall, "strike")
        put_wall_strike = _series_number(put_wall, "strike")
        rows.append(
            {
                "run_id": run_id,
                "trade_date": trade_date,
                "underlying_contract": str(contract),
                "underlying_settle": underlying,
                "underlying_open_interest": _first_number(
                    group["underlying_open_interest"]
                ),
                "is_main_contract": main_lookup.get(trade_date) == str(contract),
                "option_expiry_date": expiry.option_expiry_date,
                "days_to_expiry": expiry.days_to_expiry,
                "expiry_date_source": expiry.expiry_date_source,
                "call_total_open_interest": call_total,
                "put_total_open_interest": put_total,
                "pcr_open_interest": _safe_ratio(put_total, call_total),
                "call_wall_strike": call_wall_strike,
                "call_wall_open_interest": _series_number(
                    call_wall, "call_open_interest"
                ),
                "call_wall_oi_change": _series_number(
                    call_wall, "call_open_interest_change"
                ),
                "put_wall_strike": put_wall_strike,
                "put_wall_open_interest": _series_number(
                    put_wall, "put_open_interest"
                ),
                "put_wall_oi_change": _series_number(
                    put_wall, "put_open_interest_change"
                ),
                "call_top1_concentration": _series_number(
                    call_wall, "call_open_interest"
                )
                / call_total
                if call_total > 0 and call_wall is not None
                else None,
                "put_top1_concentration": _series_number(
                    put_wall, "put_open_interest"
                )
                / put_total
                if put_total > 0 and put_wall is not None
                else None,
                "call_top3_concentration": _top_n_share(
                    group, "call_open_interest", 3
                ),
                "put_top3_concentration": _top_n_share(
                    group, "put_open_interest", 3
                ),
                "call_oi_center": call_center,
                "put_oi_center": put_center,
                "max_pain_strike": max_pain,
                "call_build_strike": _series_number(call_build, "strike"),
                "call_build_oi_change": _series_number(
                    call_build, "call_open_interest_change"
                ),
                "call_unwind_strike": _series_number(call_unwind, "strike"),
                "call_unwind_oi_change": _series_number(
                    call_unwind, "call_open_interest_change"
                ),
                "put_build_strike": _series_number(put_build, "strike"),
                "put_build_oi_change": _series_number(
                    put_build, "put_open_interest_change"
                ),
                "put_unwind_strike": _series_number(put_unwind, "strike"),
                "put_unwind_oi_change": _series_number(
                    put_unwind, "put_open_interest_change"
                ),
                "distance_to_call_wall": _relative_distance(
                    call_wall_strike, underlying
                ),
                "distance_to_put_wall": _relative_distance(
                    put_wall_strike, underlying
                ),
                "distance_to_max_pain": _relative_distance(max_pain, underlying),
                "key_level_state": _key_level_state(
                    underlying=underlying,
                    call_wall=call_wall_strike,
                    put_wall=put_wall_strike,
                    max_pain=max_pain,
                    near_level_ratio=near_level_ratio,
                ),
                "expiry_bucket": _expiry_bucket(expiry.days_to_expiry),
                "dealer_gamma_inference": "not_available_from_public_oi",
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    daily = pd.DataFrame(rows).sort_values(
        ["underlying_contract", "trade_date"]
    ).reset_index(drop=True)
    for column in (
        "call_wall_strike",
        "put_wall_strike",
        "max_pain_strike",
        "call_oi_center",
        "put_oi_center",
    ):
        daily[f"{column}_shift_1d"] = daily.groupby("underlying_contract")[
            column
        ].diff()
    daily["key_level_migration_state"] = daily.apply(
        lambda row: _migration_state(
            _float_or_none(row["call_wall_strike_shift_1d"]),
            _float_or_none(row["put_wall_strike_shift_1d"]),
        ),
        axis=1,
    )
    return daily.sort_values(
        ["trade_date", "days_to_expiry", "underlying_contract"]
    ).reset_index(drop=True)


def _main_contract_lookup(quotes: pd.DataFrame) -> dict[date, str]:
    lookup: dict[date, str] = {}
    for trade_date, group in quotes.groupby("trade_date"):
        valid = group.loc[group["open_interest"].notna()].sort_values(
            ["open_interest", "contract_code"], ascending=[False, True]
        )
        if not valid.empty:
            lookup[trade_date] = str(valid.iloc[0]["contract_code"])
    return lookup


def _build_path_validation(
    *, daily: pd.DataFrame, quotes: pd.DataFrame, horizons: tuple[int, ...], run_id: str
) -> pd.DataFrame:
    columns = [
        "run_id",
        "trade_date",
        "underlying_contract",
        "key_level_state",
        "expiry_bucket",
        "horizon",
        "execution_date",
        "exit_date",
        "entry_settle",
        "exit_settle",
        "forward_return",
        "call_wall_crossed",
        "put_wall_crossed",
        "max_pain_touched",
        "exit_inside_wall_range",
        "forward_label_available",
        "forward_paths_are_historical_posterior_labels",
        "trading_instruction",
    ]
    quote_groups = {
        contract: group.sort_values("trade_date").reset_index(drop=True)
        for contract, group in quotes.groupby("contract_code")
    }
    rows: list[dict[str, object]] = []
    for state in daily.loc[daily["is_main_contract"].astype(bool)].itertuples(index=False):
        contract_quotes = quote_groups.get(str(state.underlying_contract))
        if contract_quotes is None:
            continue
        index_values = contract_quotes.index[
            contract_quotes["trade_date"].eq(state.trade_date)
        ].tolist()
        if not index_values:
            continue
        signal_index = int(index_values[0])
        for horizon in horizons:
            entry_index = signal_index + 1
            exit_index = entry_index + horizon
            available = exit_index < len(contract_quotes)
            row: dict[str, object] = {
                "run_id": run_id,
                "trade_date": state.trade_date,
                "underlying_contract": str(state.underlying_contract),
                "key_level_state": str(state.key_level_state),
                "expiry_bucket": str(state.expiry_bucket),
                "horizon": horizon,
                "execution_date": None,
                "exit_date": None,
                "entry_settle": None,
                "exit_settle": None,
                "forward_return": None,
                "call_wall_crossed": None,
                "put_wall_crossed": None,
                "max_pain_touched": None,
                "exit_inside_wall_range": None,
                "forward_label_available": available,
                "forward_paths_are_historical_posterior_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
            if available:
                entry = contract_quotes.iloc[entry_index]
                exit_row = contract_quotes.iloc[exit_index]
                path = contract_quotes.iloc[entry_index : exit_index + 1]
                entry_settle = _float_or_none(entry["settle"])
                exit_settle = _float_or_none(exit_row["settle"])
                path_high = pd.to_numeric(path["high"], errors="coerce").max()
                path_low = pd.to_numeric(path["low"], errors="coerce").min()
                call_wall = _float_or_none(state.call_wall_strike)
                put_wall = _float_or_none(state.put_wall_strike)
                max_pain = _float_or_none(state.max_pain_strike)
                row.update(
                    {
                        "execution_date": entry["trade_date"],
                        "exit_date": exit_row["trade_date"],
                        "entry_settle": entry_settle,
                        "exit_settle": exit_settle,
                        "forward_return": (
                            None
                            if entry_settle is None
                            or exit_settle is None
                            or entry_settle <= 0
                            else exit_settle / entry_settle - 1.0
                        ),
                        "call_wall_crossed": (
                            None
                            if call_wall is None
                            else bool(
                                state.underlying_settle < call_wall
                                and path_high >= call_wall
                            )
                        ),
                        "put_wall_crossed": (
                            None
                            if put_wall is None
                            else bool(
                                state.underlying_settle > put_wall
                                and path_low <= put_wall
                            )
                        ),
                        "max_pain_touched": (
                            None
                            if max_pain is None
                            else bool(path_low <= max_pain <= path_high)
                        ),
                        "exit_inside_wall_range": _inside_wall_range(
                            exit_settle, call_wall, put_wall
                        ),
                    }
                )
            rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def _build_validation_summary(
    *, validation: pd.DataFrame, min_sample_size: int, run_id: str
) -> pd.DataFrame:
    columns = [
        "run_id",
        "key_level_state",
        "expiry_bucket",
        "horizon",
        "sample_count",
        "call_wall_cross_rate",
        "put_wall_cross_rate",
        "max_pain_touch_rate",
        "exit_inside_wall_rate",
        "mean_forward_return",
        "mean_absolute_forward_return",
        "evidence_level",
        "forward_paths_are_historical_posterior_labels",
        "trading_instruction",
    ]
    available = validation.loc[
        validation["forward_label_available"].fillna(False).astype(bool)
    ].copy()
    rows: list[dict[str, object]] = []
    for keys, group in available.groupby(
        ["key_level_state", "expiry_bucket", "horizon"]
    ):
        state, expiry_bucket, horizon = keys
        returns = pd.to_numeric(group["forward_return"], errors="coerce").dropna()
        sample_count = len(group)
        rows.append(
            {
                "run_id": run_id,
                "key_level_state": str(state),
                "expiry_bucket": str(expiry_bucket),
                "horizon": int(horizon),
                "sample_count": sample_count,
                "call_wall_cross_rate": _bool_mean(group["call_wall_crossed"]),
                "put_wall_cross_rate": _bool_mean(group["put_wall_crossed"]),
                "max_pain_touch_rate": _bool_mean(group["max_pain_touched"]),
                "exit_inside_wall_rate": _bool_mean(
                    group["exit_inside_wall_range"]
                ),
                "mean_forward_return": None if returns.empty else float(returns.mean()),
                "mean_absolute_forward_return": (
                    None if returns.empty else float(returns.abs().mean())
                ),
                "evidence_level": _evidence_level(sample_count, min_sample_size),
                "forward_paths_are_historical_posterior_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["horizon", "sample_count"], ascending=[True, False]
    ).reset_index(drop=True)


def _max_oi_row(group: pd.DataFrame, column: str) -> pd.Series | None:
    eligible = group.loc[pd.to_numeric(group[column], errors="coerce").gt(0)]
    if eligible.empty:
        return None
    return eligible.sort_values([column, "strike"], ascending=[False, True]).iloc[0]


def _extreme_change_row(
    group: pd.DataFrame, column: str, *, positive: bool
) -> pd.Series | None:
    values = pd.to_numeric(group[column], errors="coerce")
    eligible = group.loc[values.gt(0) if positive else values.lt(0)]
    if eligible.empty:
        return None
    return eligible.sort_values(
        [column, "strike"], ascending=[not positive, True]
    ).iloc[0]


def _weighted_center(group: pd.DataFrame, column: str) -> float | None:
    weights = pd.to_numeric(group[column], errors="coerce").fillna(0.0)
    if weights.sum() <= 0:
        return None
    return float(np.average(group["strike"], weights=weights))


def _max_pain_strike(group: pd.DataFrame) -> float | None:
    if group.empty:
        return None
    strikes = sorted(set(pd.to_numeric(group["strike"], errors="coerce").dropna()))
    if not strikes:
        return None
    call_oi = pd.to_numeric(group["call_open_interest"], errors="coerce").fillna(0.0)
    put_oi = pd.to_numeric(group["put_open_interest"], errors="coerce").fillna(0.0)
    source_strikes = pd.to_numeric(group["strike"], errors="coerce")
    payouts = {
        candidate: float(
            (call_oi * (candidate - source_strikes).clip(lower=0)).sum()
            + (put_oi * (source_strikes - candidate).clip(lower=0)).sum()
        )
        for candidate in strikes
    }
    return float(min(payouts, key=lambda value: (payouts[value], value)))


def _top_n_share(group: pd.DataFrame, column: str, top_n: int) -> float | None:
    values = pd.to_numeric(group[column], errors="coerce").dropna()
    total = values.sum()
    return None if total <= 0 else float(values.nlargest(top_n).sum() / total)


def _key_level_state(
    *,
    underlying: float,
    call_wall: float | None,
    put_wall: float | None,
    max_pain: float | None,
    near_level_ratio: float,
) -> str:
    if call_wall is None or put_wall is None:
        return "KEY_LEVEL_INCOMPLETE"
    if abs(call_wall / underlying - 1.0) <= near_level_ratio:
        return "NEAR_CALL_OI_WALL"
    if abs(put_wall / underlying - 1.0) <= near_level_ratio:
        return "NEAR_PUT_OI_WALL"
    if max_pain is not None and abs(max_pain / underlying - 1.0) <= near_level_ratio:
        return "NEAR_MAX_PAIN"
    if call_wall < put_wall:
        return "OVERLAPPING_OI_WALLS"
    if underlying >= call_wall:
        return "ABOVE_CALL_OI_WALL"
    if underlying <= put_wall:
        return "BELOW_PUT_OI_WALL"
    return "BETWEEN_OI_WALLS"


def _migration_state(call_shift: float | None, put_shift: float | None) -> str:
    if call_shift is None or put_shift is None:
        return "INITIAL_OR_INCOMPLETE"
    if call_shift > 0 and put_shift > 0:
        return "BOTH_WALLS_UP"
    if call_shift < 0 and put_shift < 0:
        return "BOTH_WALLS_DOWN"
    if call_shift > 0 > put_shift:
        return "WALL_RANGE_WIDENING"
    if call_shift < 0 < put_shift:
        return "WALL_RANGE_NARROWING"
    if call_shift == 0 and put_shift == 0:
        return "WALLS_UNCHANGED"
    return "ONE_WALL_MOVED"


def _expiry_bucket(days: int) -> str:
    if days <= 5:
        return "DTE_0_5"
    if days <= 15:
        return "DTE_6_15"
    if days <= 30:
        return "DTE_16_30"
    return "DTE_GT_30"


def _inside_wall_range(
    value: float | None, call_wall: float | None, put_wall: float | None
) -> bool | None:
    if value is None or call_wall is None or put_wall is None:
        return None
    lower, upper = sorted((call_wall, put_wall))
    return bool(lower <= value <= upper)


def _warning_rows(
    *,
    options: pd.DataFrame,
    daily: pd.DataFrame,
    validation_summary: pd.DataFrame,
    min_sample_size: int,
    run_id: str,
) -> list[dict[str, object]]:
    oi_change_missing = int(options["open_interest_change"].isna().sum())
    oi_change_missing_ratio = oi_change_missing / len(options) if len(options) else 0.0
    fallback_count = int(
        daily["expiry_date_source"].astype(str).eq("MONTH_START_PROXY_FALLBACK").sum()
    )
    small_count = int(
        validation_summary["sample_count"].lt(min_sample_size).sum()
    ) if not validation_summary.empty else 0
    return [
        {
            "run_id": run_id,
            "section": "oi_change",
            "severity": "WARN" if oi_change_missing_ratio > 0.10 else "INFO",
            "warning_code": "OPTION_OI_CHANGE_BASE_MISSING",
            "warning_message": "部分期权是序列首日，无法计算同合约持仓日变化。",
            "affected_count": oi_change_missing,
            "human_review_required": "",
        },
        {
            "run_id": run_id,
            "section": "expiry",
            "severity": "WARN" if fallback_count else "INFO",
            "warning_code": "OPTION_EXPIRY_PROXY_FALLBACK",
            "warning_message": "部分合约缺少显式到期日，临近到期解释需降级。",
            "affected_count": fallback_count,
            "human_review_required": "option_expiry_registry_fallback",
        },
        {
            "run_id": run_id,
            "section": "sample_size",
            "severity": "WARN" if small_count else "INFO",
            "warning_code": "OPTION_KEY_LEVEL_SMALL_SAMPLE",
            "warning_message": "部分关键点位后验分组样本不足，证据已降级。",
            "affected_count": small_count,
            "human_review_required": "historical_level_touch_interpretation",
        },
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "OPTION_OI_OWNERSHIP_UNKNOWN",
            "warning_message": "公开持仓不含买卖方身份，不能据此推断做市商净 Gamma。",
            "affected_count": len(options),
            "human_review_required": "option_open_interest_long_short_ownership_unknown",
        },
    ]


def _evidence_level(sample_count: int, min_sample_size: int) -> str:
    if sample_count >= max(100, min_sample_size * 3):
        return "READY"
    if sample_count >= min_sample_size:
        return "WATCH"
    return "WEAK_OR_SMALL_SAMPLE"


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_output_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_option_strike_position"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "option_strike_position"
    report_root = report_output_dir or reports_dir() / "research" / "option_strike_position"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "strike_parquet": data_root / f"{stem}_strike_detail.parquet",
        "strike_csv": data_root / f"{stem}_strike_detail.csv",
        "validation_parquet": data_root / f"{stem}_validation.parquet",
        "validation_csv": data_root / f"{stem}_validation.csv",
        "validation_summary_parquet": data_root / f"{stem}_validation_summary.parquet",
        "validation_summary_csv": data_root / f"{stem}_validation_summary.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
        "manifest": report_root / f"{stem}_manifest.json",
    }


def _write_markdown(
    *,
    result: ResearchOptionStrikePositionResult,
    latest_row: dict[str, object] | None,
    strike: pd.DataFrame,
    validation_summary: pd.DataFrame,
    warnings: list[dict[str, object]],
) -> None:
    lines = [
        "# CF 期权行权价持仓关键点位研究 R84",
        "",
        "## 数据状态",
        "",
        f"- 样本区间：`{result.start}` 至 `{result.end}`",
        f"- 最新主力：`{result.latest_main_contract or 'not_available'}`",
        f"- 关键点位状态：`{result.latest_key_level_state}`",
        "",
        "## 最新关键点位",
        "",
    ]
    if latest_row is None:
        lines.append("最新交易日没有可匹配的主力期权结构。")
    else:
        lines.extend(
            [
                f"- 标的结算价：`{fmt_number(latest_row['underlying_settle'], 0)}`。",
                f"- Call 持仓墙：`{fmt_number(latest_row['call_wall_strike'], 0)}`，"
                f"持仓 `{fmt_number(latest_row['call_wall_open_interest'], 0)}`，"
                f"日变化 `{fmt_number(latest_row['call_wall_oi_change'], 0)}`。",
                f"- Put 持仓墙：`{fmt_number(latest_row['put_wall_strike'], 0)}`，"
                f"持仓 `{fmt_number(latest_row['put_wall_open_interest'], 0)}`，"
                f"日变化 `{fmt_number(latest_row['put_wall_oi_change'], 0)}`。",
                f"- 静态最大赔付最小点：`{fmt_number(latest_row['max_pain_strike'], 0)}`。",
                f"- Call/Put 持仓重心：`{fmt_number(latest_row['call_oi_center'], 0)}` / "
                f"`{fmt_number(latest_row['put_oi_center'], 0)}`。",
                f"- 墙体迁移：`{latest_row['key_level_migration_state']}`；"
                f"距离到期 `{latest_row['days_to_expiry']}` 天。",
                f"- 标的距 Call/Put 墙：`{fmt_percent(latest_row['distance_to_call_wall'])}` / "
                f"`{fmt_percent(latest_row['distance_to_put_wall'])}`。",
            ]
        )
    lines.extend(["", "## 当日增减仓关键点", ""])
    if latest_row is None:
        lines.append("无。")
    else:
        lines.extend(
            [
                f"- Call 最大增仓：`{fmt_number(latest_row['call_build_strike'], 0)}`，"
                f"`{fmt_number(latest_row['call_build_oi_change'], 0)}` 手。",
                f"- Call 最大减仓：`{fmt_number(latest_row['call_unwind_strike'], 0)}`，"
                f"`{fmt_number(latest_row['call_unwind_oi_change'], 0)}` 手。",
                f"- Put 最大增仓：`{fmt_number(latest_row['put_build_strike'], 0)}`，"
                f"`{fmt_number(latest_row['put_build_oi_change'], 0)}` 手。",
                f"- Put 最大减仓：`{fmt_number(latest_row['put_unwind_strike'], 0)}`，"
                f"`{fmt_number(latest_row['put_unwind_oi_change'], 0)}` 手。",
            ]
        )
    lines.extend(["", "## 最新主力行权价持仓", ""])
    current = strike.loc[
        strike["trade_date"].eq(result.end)
        & strike["underlying_contract"].eq(result.latest_main_contract)
    ].copy()
    if current.empty:
        lines.append("无。")
    else:
        current["total_oi"] = current["call_open_interest"] + current["put_open_interest"]
        lines.extend(
            [
                "| 行权价 | Call OI | Call 日变 | Put OI | Put 日变 | 距标的 |",
                "| ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in current.nlargest(12, "total_oi").sort_values("strike").itertuples(
            index=False
        ):
            lines.append(
                f"| {fmt_number(row.strike, 0)} | {fmt_number(row.call_open_interest, 0)} | "
                f"{fmt_number(row.call_open_interest_change, 0)} | "
                f"{fmt_number(row.put_open_interest, 0)} | "
                f"{fmt_number(row.put_open_interest_change, 0)} | "
                f"{fmt_percent(row.distance_to_underlying)} |"
            )
    lines.extend(["", "## 历史后验穿越", ""])
    if validation_summary.empty:
        lines.append("暂无可用后验标签。")
    else:
        current_mapping = validation_summary.copy()
        if latest_row is not None:
            current_mapping = current_mapping.loc[
                current_mapping["key_level_state"].eq(latest_row["key_level_state"])
                & current_mapping["expiry_bucket"].eq(latest_row["expiry_bucket"])
            ]
        lines.extend(
            [
                "### 当前状态历史映射",
                "",
                "| 周期 | 样本 | Call 墙穿越 | Put 墙穿越 | 最大赔付点触及 | "
                "平均收益 | 平均绝对收益 | 证据 |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in current_mapping.sort_values("horizon").itertuples(index=False):
            lines.append(
                f"| {row.horizon}D | {row.sample_count} | "
                f"{fmt_percent(row.call_wall_cross_rate)} | "
                f"{fmt_percent(row.put_wall_cross_rate)} | "
                f"{fmt_percent(row.max_pain_touch_rate)} | "
                f"{fmt_percent(row.mean_forward_return)} | "
                f"{fmt_percent(row.mean_absolute_forward_return)} | "
                f"{row.evidence_level} |"
            )
        lines.extend(["", "### 全样本主要分组", ""])
        lines.extend(
            [
                "| 状态 | 到期桶 | 周期 | 样本 | Call 墙穿越 | Put 墙穿越 | "
                "最大赔付点触及 | 证据 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in validation_summary.head(18).itertuples(index=False):
            lines.append(
                f"| {row.key_level_state} | {row.expiry_bucket} | {row.horizon}D | "
                f"{row.sample_count} | {fmt_percent(row.call_wall_cross_rate)} | "
                f"{fmt_percent(row.put_wall_cross_rate)} | "
                f"{fmt_percent(row.max_pain_touch_rate)} | {row.evidence_level} |"
            )
    lines.extend(["", "## 告警", ""])
    for warning in warnings:
        if warning["severity"] == "WARN":
            lines.append(f"- `{warning['warning_code']}`：{warning['warning_message']}")
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- Call/Put 高持仓行权价是结构观察位，不自动等同压力位或支撑位。",
            "- 公开数据不含期权买卖方身份，本研究不推断做市商净 Gamma。",
            "- 最大赔付最小点使用静态未平仓量近似，不包含盘中平仓、权利金和行权行为。",
            "- T+1 之后的穿越和收益只作为历史后验标签，不进入最新日计算。",
            "- 本模块不修改 composite_score，不自动反转方向，不构成交易指令。",
            "",
            "## HUMAN_REVIEW_REQUIRED",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in HUMAN_REVIEW_REQUIRED)
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _first_number(values: pd.Series) -> float | None:
    valid = pd.to_numeric(values, errors="coerce").dropna()
    return None if valid.empty else float(valid.iloc[0])


def _series_number(row: pd.Series | None, column: str) -> float | None:
    return None if row is None else _float_or_none(row[column])


def _row_float(row: dict[str, object] | None, key: str) -> float | None:
    return None if row is None else _float_or_none(row.get(key))


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _relative_distance(level: float | None, underlying: float) -> float | None:
    return None if level is None or underlying <= 0 else level / underlying - 1.0


def _bool_mean(values: pd.Series) -> float | None:
    valid = values.dropna()
    return None if valid.empty else float(valid.astype(bool).mean())
