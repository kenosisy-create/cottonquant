"""CF611 结构性持仓来源、交割供给与期权节点归因研究。"""

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
    latest_matching_path,
    load_table,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
STRUCTURAL_POSITION_ATTRIBUTION_VERSION = "structural_position_attribution_v1"
DEFAULT_TARGET_CONTRACT = "CF611"
DEFAULT_SOURCE_CONTRACT = "CF609"
DEFAULT_NEXT_CONTRACT = "CF701"
DEFAULT_FOCUS_START = date(2026, 5, 15)
DEFAULT_OPTION_HORIZONS = (1, 3, 5, 10)
DEFAULT_WALL_DISTANCE = 0.01
DEFAULT_OPTION_OI_NOISE_RATIO = 0.005
DEFAULT_CONTRACT_TONS = 5.0
DEFAULT_RECEIPT_TONS = 40.0
HUMAN_REVIEW_REQUIRED = (
    "member_ranking_is_not_customer_identity",
    "member_top20_pairing_is_visible_proxy_only",
    "warehouse_receipt_unit_and_scope",
    "option_oi_does_not_identify_buyer_or_seller",
    "option_expiry_and_liquidity_filter",
    "contract_multiplier_and_receipt_tonnage",
)
RESEARCH_BOUNDARY = {
    "member_pairing_is_not_actual_roll_volume": True,
    "option_oi_does_not_identify_trade_side": True,
    "warehouse_receipt_is_aggregate_supply_context": True,
    "forward_returns_are_historical_posterior_labels": True,
    "latest_state_uses_future_data": False,
    "automatic_signal_generation": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchStructuralPositionAttributionResult:
    """结构性持仓归因产物和最新覆盖状态。"""

    run_id: str
    start: date
    end: date
    focus_start: date
    focus_end: date
    target_contract: str
    source_contract: str
    next_contract: str
    daily_row_count: int
    member_flow_row_count: int
    option_event_row_count: int
    latest_target_open_interest: float
    latest_target_settle: float
    latest_structure_state: str
    member_data_asof: date | None
    warehouse_data_asof: date | None
    option_data_asof: date | None
    warning_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    member_flow_parquet_path: Path
    member_flow_csv_path: Path
    window_summary_parquet_path: Path
    window_summary_csv_path: Path
    option_event_parquet_path: Path
    option_event_csv_path: Path
    option_event_summary_parquet_path: Path
    option_event_summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_quote_path: Path
    member_detail_path: Path | None
    warehouse_receipt_path: Path | None
    option_strike_position_path: Path | None
    option_factor_path: Path | None
    delivery_adjusted_curve_path: Path | None

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "focus_start": self.focus_start.isoformat(),
            "focus_end": self.focus_end.isoformat(),
            "target_contract": self.target_contract,
            "source_contract": self.source_contract,
            "next_contract": self.next_contract,
            "daily_row_count": self.daily_row_count,
            "member_flow_row_count": self.member_flow_row_count,
            "option_event_row_count": self.option_event_row_count,
            "latest_target_open_interest": self.latest_target_open_interest,
            "latest_target_settle": self.latest_target_settle,
            "latest_structure_state": self.latest_structure_state,
            "member_data_asof": _date_text(self.member_data_asof),
            "warehouse_data_asof": _date_text(self.warehouse_data_asof),
            "option_data_asof": _date_text(self.option_data_asof),
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "member_flow_parquet_path": str(self.member_flow_parquet_path),
            "window_summary_parquet_path": str(self.window_summary_parquet_path),
            "option_event_parquet_path": str(self.option_event_parquet_path),
            "option_event_summary_parquet_path": str(
                self.option_event_summary_parquet_path
            ),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_structural_position_attribution(
    *,
    core_quote_path: Path | None = None,
    member_detail_path: Path | None = None,
    warehouse_receipt_path: Path | None = None,
    option_strike_position_path: Path | None = None,
    option_factor_path: Path | None = None,
    delivery_adjusted_curve_path: Path | None = None,
    target_contract: str = DEFAULT_TARGET_CONTRACT,
    source_contract: str = DEFAULT_SOURCE_CONTRACT,
    next_contract: str = DEFAULT_NEXT_CONTRACT,
    focus_start: date | None = DEFAULT_FOCUS_START,
    focus_end: date | None = None,
    option_horizons: tuple[int, ...] = DEFAULT_OPTION_HORIZONS,
    wall_distance: float = DEFAULT_WALL_DISTANCE,
    option_oi_noise_ratio: float = DEFAULT_OPTION_OI_NOISE_RATIO,
    contract_tons: float = DEFAULT_CONTRACT_TONS,
    receipt_tons: float = DEFAULT_RECEIPT_TONS,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchStructuralPositionAttributionResult:
    """构建可见移仓、链级增仓、仓单和期权结构的分层证据。"""
    target_code, source_code, next_code = _validate_contracts(
        target_contract, source_contract, next_contract
    )
    horizons = tuple(sorted(set(int(value) for value in option_horizons)))
    if not horizons or any(value < 1 for value in horizons):
        raise ResearchWorkbenchError("option_horizons must contain positive values")
    if wall_distance < 0 or option_oi_noise_ratio < 0:
        raise ResearchWorkbenchError("option thresholds cannot be negative")
    if contract_tons <= 0 or receipt_tons <= 0:
        raise ResearchWorkbenchError("tonnage parameters must be positive")

    quote_path = core_quote_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    )
    quotes = load_table(
        quote_path,
        required={
            "trade_date",
            "contract_code",
            "settle",
            "close",
            "volume",
            "open_interest",
        },
        label="CF core quote",
    )
    daily = _build_contract_daily(
        quotes=quotes,
        target_contract=target_code,
        source_contract=source_code,
        next_contract=next_code,
        focus_end=focus_end,
        contract_tons=contract_tons,
    )
    if daily.empty:
        raise ResearchWorkbenchError(f"no active quote rows for {target_code}")
    start = daily["trade_date"].min()
    effective_end = daily["trade_date"].max()
    effective_focus_start = max(focus_start or start, start)
    effective_focus_end = min(focus_end or effective_end, effective_end)
    if effective_focus_start > effective_focus_end:
        raise ResearchWorkbenchError("focus_start must not be later than focus_end")
    active_run_id = run_id or utc_timestamp_id("structural_attribution", effective_end)

    resolved_member_path = member_detail_path or _latest_optional(
        data_dir() / "research" / PRODUCT_CODE / "member_position",
        "*_member_position_member_detail.parquet",
        "member detail",
    )
    resolved_warehouse_path = warehouse_receipt_path or _existing_optional(
        data_dir()
        / "research"
        / PRODUCT_CODE
        / "fundamentals"
        / "CF_fundamental_warehouse_receipt_daily.parquet"
    )
    resolved_strike_path = option_strike_position_path or _latest_optional(
        data_dir() / "research" / PRODUCT_CODE / "option_strike_position",
        "*_option_strike_position_daily.parquet",
        "option strike-position",
    )
    resolved_option_factor_path = option_factor_path or _latest_optional(
        data_dir() / "research" / PRODUCT_CODE / "option_factors",
        "*_option_factor_proxy_daily.parquet",
        "option factor",
    )
    resolved_curve_path = delivery_adjusted_curve_path or _latest_optional(
        data_dir() / "research" / PRODUCT_CODE / "delivery_adjusted_curve",
        f"*_{source_code}_{target_code}_delivery_adjusted_curve_daily.parquet",
        "delivery-adjusted curve",
    )

    member_flow = _load_member_flow(
        path=resolved_member_path,
        source_contract=source_code,
        target_contract=target_code,
        next_contract=next_code,
        run_id=active_run_id,
    )
    warehouse = _load_warehouse(path=resolved_warehouse_path)
    strike = _load_option_strike(path=resolved_strike_path, target_contract=target_code)
    option_factor = _load_option_factor(
        path=resolved_option_factor_path, target_contract=target_code
    )
    curve = _load_delivery_curve(path=resolved_curve_path)
    daily = _merge_context(
        daily=daily,
        member_flow=member_flow,
        warehouse=warehouse,
        strike=strike,
        option_factor=option_factor,
        curve=curve,
        option_oi_noise_ratio=option_oi_noise_ratio,
        receipt_tons=receipt_tons,
    )
    daily.insert(0, "run_id", active_run_id)

    option_events = _build_option_event_validation(
        daily=daily,
        horizons=horizons,
        wall_distance=wall_distance,
        option_oi_noise_ratio=option_oi_noise_ratio,
        run_id=active_run_id,
    )
    option_event_summary = _build_option_event_summary(
        events=option_events,
        run_id=active_run_id,
    )
    window_summary = _build_window_summaries(
        daily=daily,
        member_flow=member_flow,
        focus_start=effective_focus_start,
        focus_end=effective_focus_end,
        contract_tons=contract_tons,
        receipt_tons=receipt_tons,
        run_id=active_run_id,
    )
    member_asof = _max_date(member_flow)
    warehouse_asof = _max_date(warehouse)
    option_asof = _max_date(strike)
    warnings = _warning_rows(
        run_id=active_run_id,
        effective_end=effective_end,
        member_path=resolved_member_path,
        member_asof=member_asof,
        warehouse_path=resolved_warehouse_path,
        warehouse_asof=warehouse_asof,
        strike_path=resolved_strike_path,
        option_asof=option_asof,
        option_event_summary=option_event_summary,
    )
    paths = _paths(
        start=start,
        end=effective_end,
        target_contract=target_code,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(
        member_flow,
        paths["member_flow_parquet"],
        paths["member_flow_csv"],
    )
    write_frame(
        window_summary,
        paths["window_summary_parquet"],
        paths["window_summary_csv"],
    )
    write_frame(
        option_events,
        paths["option_event_parquet"],
        paths["option_event_csv"],
    )
    write_frame(
        option_event_summary,
        paths["option_summary_parquet"],
        paths["option_summary_csv"],
    )
    write_warning_csv(paths["warning_csv"], warnings)

    latest = daily.iloc[-1].to_dict()
    result = ResearchStructuralPositionAttributionResult(
        run_id=active_run_id,
        start=start,
        end=effective_end,
        focus_start=effective_focus_start,
        focus_end=effective_focus_end,
        target_contract=target_code,
        source_contract=source_code,
        next_contract=next_code,
        daily_row_count=len(daily),
        member_flow_row_count=len(member_flow),
        option_event_row_count=len(option_events),
        latest_target_open_interest=float(latest["target_open_interest"]),
        latest_target_settle=float(latest["target_settle"]),
        latest_structure_state=str(latest["target_oi_structure_state"]),
        member_data_asof=member_asof,
        warehouse_data_asof=warehouse_asof,
        option_data_asof=option_asof,
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        member_flow_parquet_path=paths["member_flow_parquet"],
        member_flow_csv_path=paths["member_flow_csv"],
        window_summary_parquet_path=paths["window_summary_parquet"],
        window_summary_csv_path=paths["window_summary_csv"],
        option_event_parquet_path=paths["option_event_parquet"],
        option_event_csv_path=paths["option_event_csv"],
        option_event_summary_parquet_path=paths["option_summary_parquet"],
        option_event_summary_csv_path=paths["option_summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        member_detail_path=resolved_member_path,
        warehouse_receipt_path=resolved_warehouse_path,
        option_strike_position_path=resolved_strike_path,
        option_factor_path=resolved_option_factor_path,
        delivery_adjusted_curve_path=resolved_curve_path,
    )
    _write_markdown(
        result=result,
        daily=daily,
        window_summary=window_summary,
        option_event_summary=option_event_summary,
        wall_distance=wall_distance,
    )
    write_json(
        result.json_path,
        {
            "report_type": "structural_position_attribution",
            "rule_version": STRUCTURAL_POSITION_ATTRIBUTION_VERSION,
            "summary": result.to_summary(),
            "latest_state": latest,
            "focus_window": window_summary.loc[
                window_summary["window_type"].eq("FOCUS_WINDOW")
            ].to_dict(orient="records"),
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="structural_position_attribution",
            rule_version=STRUCTURAL_POSITION_ATTRIBUTION_VERSION,
            data_asof=effective_end,
            input_paths={
                "core_quote_path": quote_path,
                "member_detail_path": resolved_member_path,
                "warehouse_receipt_path": resolved_warehouse_path,
                "option_strike_position_path": resolved_strike_path,
                "option_factor_path": resolved_option_factor_path,
                "delivery_adjusted_curve_path": resolved_curve_path,
            },
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "member_flow_parquet_path": result.member_flow_parquet_path,
                "window_summary_parquet_path": result.window_summary_parquet_path,
                "option_event_parquet_path": result.option_event_parquet_path,
                "option_event_summary_parquet_path": (
                    result.option_event_summary_parquet_path
                ),
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _validate_contracts(target: str, source: str, next_contract: str) -> tuple[str, str, str]:
    values = tuple(value.strip().upper() for value in (target, source, next_contract))
    if len(set(values)) != 3:
        raise ResearchWorkbenchError("target/source/next contracts must be different")
    if any(not value.startswith(PRODUCT_CODE) for value in values):
        raise ResearchWorkbenchError("structural attribution currently supports CF only")
    return values


def _build_contract_daily(
    *,
    quotes: pd.DataFrame,
    target_contract: str,
    source_contract: str,
    next_contract: str,
    focus_end: date | None,
    contract_tons: float,
) -> pd.DataFrame:
    working = normalize_trade_date(quotes)
    working["contract_code"] = working["contract_code"].astype(str).str.upper()
    if focus_end is not None:
        working = working.loc[working["trade_date"].le(focus_end)].copy()
    for column in ("settle", "close", "volume", "open_interest"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    chain = working.groupby("trade_date", as_index=False).agg(
        chain_open_interest=("open_interest", "sum"),
        chain_volume=("volume", "sum"),
    )
    chain["chain_oi_change"] = chain["chain_open_interest"].diff()
    selected = working.loc[
        working["contract_code"].isin(
            {target_contract, source_contract, next_contract}
        )
    ].copy()
    fields = ["settle", "close", "volume", "open_interest"]
    wide = selected.pivot_table(
        index="trade_date",
        columns="contract_code",
        values=fields,
        aggfunc="last",
    )
    if ("open_interest", target_contract) not in wide.columns:
        return pd.DataFrame()
    target_active = wide[("open_interest", target_contract)].fillna(0).gt(0)
    wide = wide.loc[target_active].sort_index()
    daily = pd.DataFrame(index=wide.index)
    for prefix, contract in (
        ("target", target_contract),
        ("source", source_contract),
        ("next", next_contract),
    ):
        for field in fields:
            column = (field, contract)
            daily[f"{prefix}_{field}"] = wide[column] if column in wide.columns else pd.NA
    daily = daily.reset_index().merge(chain, on="trade_date", how="left")
    for prefix in ("target", "source", "next"):
        daily[f"{prefix}_oi_change"] = daily[f"{prefix}_open_interest"].diff()
        daily[f"{prefix}_settle_return"] = daily[f"{prefix}_settle"].pct_change()
    daily["source_to_target_oi_transfer_proxy"] = daily.apply(
        lambda row: min(
            max(-_number(row["source_oi_change"]), 0.0),
            max(_number(row["target_oi_change"]), 0.0),
        ),
        axis=1,
    )
    daily["target_to_next_oi_transfer_proxy"] = daily.apply(
        lambda row: min(
            max(-_number(row["target_oi_change"]), 0.0),
            max(_number(row["next_oi_change"]), 0.0),
        ),
        axis=1,
    )
    daily["target_notional_tons"] = daily["target_open_interest"] * contract_tons
    daily["target_oi_structure_state"] = daily.apply(_target_oi_state, axis=1)
    daily["target_contract"] = target_contract
    daily["source_contract"] = source_contract
    daily["next_contract"] = next_contract
    daily["rule_version"] = STRUCTURAL_POSITION_ATTRIBUTION_VERSION
    daily["trading_instruction"] = "not_a_trading_instruction"
    return daily


def _target_oi_state(row: pd.Series) -> str:
    target_change = _number(row["target_oi_change"])
    source_change = _number(row["source_oi_change"])
    chain_change = _number(row["chain_oi_change"])
    if target_change > 0 and source_change < 0 and chain_change > 0:
        return "ROLL_AND_NEW_CHAIN_BUILD"
    if target_change > 0 and source_change < 0:
        return "SOURCE_TO_TARGET_TRANSFER"
    if target_change > 0 and chain_change > 0:
        return "TARGET_BUILD_WITH_CHAIN_GROWTH"
    if target_change > 0:
        return "TARGET_BUILD_WITHOUT_CHAIN_CONFIRMATION"
    if target_change < 0 and chain_change < 0:
        return "TARGET_AND_CHAIN_EXIT"
    if target_change < 0:
        return "TARGET_REDUCTION_OR_ROLL"
    return "NEUTRAL_OR_FIRST_OBSERVATION"


def _load_member_flow(
    *,
    path: Path | None,
    source_contract: str,
    target_contract: str,
    next_contract: str,
    run_id: str,
) -> pd.DataFrame:
    columns = _member_flow_columns()
    if path is None:
        return pd.DataFrame(columns=columns)
    frame = load_table(
        path,
        required={
            "trade_date",
            "scope_type",
            "contract_code",
            "member_name",
            "long_change",
            "short_change",
            "net_position",
            "net_change",
        },
        label="CF member detail",
    )
    working = normalize_trade_date(frame)
    working["contract_code"] = working["contract_code"].astype(str).str.upper()
    working = working.loc[
        working["scope_type"].astype(str).eq("contract")
        & working["contract_code"].isin(
            {source_contract, target_contract, next_contract}
        )
    ].copy()
    if working.empty:
        return pd.DataFrame(columns=columns)
    for column in ("long_change", "short_change", "net_position", "net_change"):
        working[column] = (
            pd.to_numeric(working[column], errors="coerce").fillna(0.0).astype(float)
        )
    grouped = working.groupby(
        ["trade_date", "member_name", "contract_code"], as_index=False
    ).agg(
        long_change=("long_change", "sum"),
        short_change=("short_change", "sum"),
        net_position=("net_position", "sum"),
        net_change=("net_change", "sum"),
    )
    rows: list[dict[str, object]] = []
    for trade_date, day in grouped.groupby("trade_date", sort=True):
        long_pivot = day.pivot_table(
            index="member_name",
            columns="contract_code",
            values="long_change",
            aggfunc="sum",
            fill_value=0.0,
        )
        short_pivot = day.pivot_table(
            index="member_name",
            columns="contract_code",
            values="short_change",
            aggfunc="sum",
            fill_value=0.0,
        )
        long_roll = _paired_sum(
            -_pivot_series(long_pivot, source_contract),
            _pivot_series(long_pivot, target_contract),
        )
        short_roll = _paired_sum(
            -_pivot_series(short_pivot, source_contract),
            _pivot_series(short_pivot, target_contract),
        )
        target_long_next_short = _paired_sum(
            _pivot_series(long_pivot, target_contract),
            _pivot_series(short_pivot, next_contract),
        )
        target_short_next_long = _paired_sum(
            _pivot_series(short_pivot, target_contract),
            _pivot_series(long_pivot, next_contract),
        )
        target_day = day.loc[day["contract_code"].eq(target_contract)]
        rows.append(
            {
                "run_id": run_id,
                "trade_date": trade_date,
                "source_contract": source_contract,
                "target_contract": target_contract,
                "next_contract": next_contract,
                "source_to_target_long_roll_proxy": long_roll,
                "source_to_target_short_roll_proxy": short_roll,
                "source_to_target_gross_roll_proxy": long_roll + short_roll,
                "target_long_next_short_pair_proxy": target_long_next_short,
                "target_short_next_long_pair_proxy": target_short_next_long,
                "target_next_gross_pair_proxy": (
                    target_long_next_short + target_short_next_long
                ),
                "target_visible_top_net_position": float(
                    target_day["net_position"].sum()
                ),
                "target_visible_top_net_change": float(target_day["net_change"].sum()),
                "member_count": int(day["member_name"].nunique()),
                "member_scope_boundary": "top_rank_member_not_customer_identity",
                "rule_version": STRUCTURAL_POSITION_ATTRIBUTION_VERSION,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _member_flow_columns() -> list[str]:
    return [
        "run_id",
        "trade_date",
        "source_contract",
        "target_contract",
        "next_contract",
        "source_to_target_long_roll_proxy",
        "source_to_target_short_roll_proxy",
        "source_to_target_gross_roll_proxy",
        "target_long_next_short_pair_proxy",
        "target_short_next_long_pair_proxy",
        "target_next_gross_pair_proxy",
        "target_visible_top_net_position",
        "target_visible_top_net_change",
        "member_count",
        "member_scope_boundary",
        "rule_version",
    ]


def _pivot_series(frame: pd.DataFrame, contract: str) -> pd.Series:
    if contract in frame.columns:
        return frame[contract].astype(float)
    return pd.Series(0.0, index=frame.index)


def _paired_sum(left: pd.Series, right: pd.Series) -> float:
    aligned = pd.concat([left, right], axis=1).fillna(0.0)
    positive_left = aligned.iloc[:, 0].clip(lower=0)
    positive_right = aligned.iloc[:, 1].clip(lower=0)
    return float(pd.concat([positive_left, positive_right], axis=1).min(axis=1).sum())


def _load_warehouse(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(
            columns=[
                "trade_date",
                "warehouse_receipt",
                "warehouse_receipt_change",
                "warehouse_source_name",
            ]
        )
    frame = load_table(
        path,
        required={"trade_date", "warehouse_receipt"},
        label="CF warehouse receipt",
    )
    working = normalize_trade_date(frame)
    working["warehouse_receipt"] = pd.to_numeric(
        working["warehouse_receipt"], errors="coerce"
    )
    working = working.dropna(subset=["warehouse_receipt"])
    source_column = (
        working["source_name"].astype(str)
        if "source_name" in working.columns
        else pd.Series("unknown", index=working.index)
    )
    working["warehouse_source_name"] = source_column
    daily = working.sort_values("trade_date").groupby("trade_date", as_index=False).agg(
        warehouse_receipt=("warehouse_receipt", "last"),
        warehouse_source_name=("warehouse_source_name", "last"),
    )
    daily["warehouse_receipt_change"] = daily["warehouse_receipt"].diff()
    return daily


def _load_option_strike(path: Path | None, *, target_contract: str) -> pd.DataFrame:
    columns = [
        "trade_date",
        "call_total_open_interest",
        "put_total_open_interest",
        "pcr_open_interest",
        "call_wall_strike",
        "call_wall_open_interest",
        "call_wall_oi_change",
        "call_build_strike",
        "call_build_oi_change",
        "call_unwind_strike",
        "call_unwind_oi_change",
        "put_wall_strike",
        "put_wall_open_interest",
        "put_wall_oi_change",
        "put_build_strike",
        "put_build_oi_change",
        "put_unwind_strike",
        "put_unwind_oi_change",
        "max_pain_strike",
        "distance_to_call_wall",
        "distance_to_put_wall",
        "distance_to_max_pain",
        "key_level_state",
        "key_level_migration_state",
    ]
    if path is None:
        return pd.DataFrame(columns=columns)
    frame = load_table(
        path,
        required={
            "trade_date",
            "underlying_contract",
            "call_total_open_interest",
            "put_total_open_interest",
            "call_wall_strike",
            "call_wall_oi_change",
            "put_wall_strike",
            "put_wall_oi_change",
            "distance_to_call_wall",
            "distance_to_put_wall",
        },
        label="CF option strike-position",
    )
    working = normalize_trade_date(frame)
    working = working.loc[
        working["underlying_contract"].astype(str).str.upper().eq(target_contract)
    ].copy()
    for column in columns:
        if column not in working.columns:
            working[column] = pd.NA
    for column in (
        "call_total_open_interest",
        "put_total_open_interest",
        "call_wall_oi_change",
        "put_wall_oi_change",
    ):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    working["call_total_oi_change"] = working["call_total_open_interest"].diff()
    working["put_total_oi_change"] = working["put_total_open_interest"].diff()
    return working[columns + ["call_total_oi_change", "put_total_oi_change"]]


def _load_option_factor(path: Path | None, *, target_contract: str) -> pd.DataFrame:
    columns = [
        "trade_date",
        "atm_iv_proxy",
        "atm_iv_rank",
        "pcr_volume",
        "pcr_oi",
        "skew_proxy",
        "call_volume",
        "put_volume",
        "call_open_interest",
        "put_open_interest",
        "option_liquidity_score",
        "factor_status",
    ]
    if path is None:
        return pd.DataFrame(columns=columns)
    frame = load_table(
        path,
        required={
            "trade_date",
            "underlying_contract",
            "atm_iv_proxy",
            "pcr_volume",
            "pcr_oi",
            "skew_proxy",
        },
        label="CF option factor",
    )
    working = normalize_trade_date(frame)
    working = working.loc[
        working["underlying_contract"].astype(str).str.upper().eq(target_contract)
    ].copy()
    for column in columns:
        if column not in working.columns:
            working[column] = pd.NA
    return working.sort_values("trade_date").drop_duplicates("trade_date", keep="last")[
        columns
    ]


def _load_delivery_curve(path: Path | None) -> pd.DataFrame:
    columns = [
        "trade_date",
        "observed_spread",
        "modeled_full_carry_cost",
        "delivery_adjusted_residual",
        "residual_state",
    ]
    if path is None:
        return pd.DataFrame(columns=columns)
    frame = load_table(
        path,
        required={
            "trade_date",
            "observed_spread",
            "modeled_full_carry_cost",
            "delivery_adjusted_residual",
        },
        label="CF delivery-adjusted curve",
    )
    working = normalize_trade_date(frame)
    if "residual_state" not in working.columns:
        working["residual_state"] = "UNCLASSIFIED"
    return working.sort_values("trade_date").drop_duplicates("trade_date", keep="last")[
        columns
    ]


def _merge_context(
    *,
    daily: pd.DataFrame,
    member_flow: pd.DataFrame,
    warehouse: pd.DataFrame,
    strike: pd.DataFrame,
    option_factor: pd.DataFrame,
    curve: pd.DataFrame,
    option_oi_noise_ratio: float,
    receipt_tons: float,
) -> pd.DataFrame:
    working = daily.copy()
    if not member_flow.empty:
        member_columns = [
            column
            for column in member_flow.columns
            if column
            not in {
                "run_id",
                "source_contract",
                "target_contract",
                "next_contract",
                "rule_version",
            }
        ]
        working = working.merge(
            member_flow[member_columns], on="trade_date", how="left"
        )
    working["member_data_available"] = working.get(
        "member_count", pd.Series(pd.NA, index=working.index)
    ).notna()
    working = _merge_warehouse_asof(working, warehouse)
    if not strike.empty:
        working = working.merge(strike, on="trade_date", how="left")
    if not option_factor.empty:
        working = working.merge(option_factor, on="trade_date", how="left")
    if not curve.empty:
        working = working.merge(curve, on="trade_date", how="left")
    working["option_data_available"] = working.get(
        "call_total_open_interest", pd.Series(pd.NA, index=working.index)
    ).notna()
    call_change = (
        pd.to_numeric(working["call_total_oi_change"], errors="coerce")
        if "call_total_oi_change" in working.columns
        else pd.Series(pd.NA, index=working.index, dtype="Float64")
    )
    put_change = (
        pd.to_numeric(working["put_total_oi_change"], errors="coerce")
        if "put_total_oi_change" in working.columns
        else pd.Series(pd.NA, index=working.index, dtype="Float64")
    )
    working["option_oi_imbalance_change"] = put_change - call_change
    working["option_structure_state"] = working.apply(
        lambda row: _option_structure_state(row, option_oi_noise_ratio), axis=1
    )
    if "warehouse_receipt" in working.columns:
        working["warehouse_receipt_tons"] = (
            working["warehouse_receipt"] * receipt_tons
        )
        working["target_oi_to_receipt_tonnage_ratio"] = (
            working["target_notional_tons"] / working["warehouse_receipt_tons"]
        )
    else:
        working["warehouse_receipt_tons"] = pd.NA
        working["target_oi_to_receipt_tonnage_ratio"] = pd.NA
    return working


def _merge_warehouse_asof(daily: pd.DataFrame, warehouse: pd.DataFrame) -> pd.DataFrame:
    if warehouse.empty:
        working = daily.copy()
        working["warehouse_observation_date"] = pd.NaT
        working["warehouse_receipt"] = pd.NA
        working["warehouse_receipt_change"] = pd.NA
        working["warehouse_source_name"] = pd.NA
        working["warehouse_staleness_days"] = pd.NA
        return working
    left = daily.copy()
    left["_merge_date"] = pd.to_datetime(left["trade_date"])
    right = warehouse.copy().rename(columns={"trade_date": "warehouse_observation_date"})
    right["_merge_date"] = pd.to_datetime(right["warehouse_observation_date"])
    merged = pd.merge_asof(
        left.sort_values("_merge_date"),
        right.sort_values("_merge_date"),
        on="_merge_date",
        direction="backward",
    )
    merged["warehouse_staleness_days"] = (
        merged["_merge_date"]
        - pd.to_datetime(merged["warehouse_observation_date"], errors="coerce")
    ).dt.days
    return merged.drop(columns=["_merge_date"])


def _option_structure_state(row: pd.Series, noise_ratio: float) -> str:
    if pd.isna(row.get("call_total_open_interest")):
        return "OPTION_NOT_AVAILABLE"
    call_change = _number(row.get("call_total_oi_change"))
    put_change = _number(row.get("put_total_oi_change"))
    call_level = max(_number(row.get("call_total_open_interest")), 1.0)
    put_level = max(_number(row.get("put_total_open_interest")), 1.0)
    call_material = abs(call_change) >= call_level * noise_ratio
    put_material = abs(put_change) >= put_level * noise_ratio
    price_return = _number(row.get("target_settle_return"))
    if price_return > 0 and put_change > 0 and put_material and put_change > call_change:
        return "PRICE_UP_PUT_OI_DOMINANT_BUILD"
    if price_return > 0 and call_change > 0 and call_material:
        return "PRICE_UP_CALL_OI_BUILD"
    if price_return < 0 and put_change > 0 and put_material:
        return "PRICE_DOWN_PUT_OI_BUILD"
    if price_return < 0 and call_change > 0 and call_material:
        return "PRICE_DOWN_CALL_OI_BUILD"
    if call_change < 0 and put_change < 0 and (call_material or put_material):
        return "BOTH_SIDES_OI_REDUCTION"
    return "MIXED_OR_LOW_CHANGE"


def _build_option_event_validation(
    *,
    daily: pd.DataFrame,
    horizons: tuple[int, ...],
    wall_distance: float,
    option_oi_noise_ratio: float,
    run_id: str,
) -> pd.DataFrame:
    columns = [
        "run_id",
        "event_date",
        "event_type",
        "horizon",
        "execution_date",
        "exit_date",
        "execution_settle",
        "exit_settle",
        "forward_return",
        "posterior_direction",
        "is_resolved",
        "rule_version",
        "trading_instruction",
    ]
    if "call_total_open_interest" not in daily.columns:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    ordered = daily.sort_values("trade_date").reset_index(drop=True)
    for index, row in ordered.iterrows():
        event_types = _option_event_types(
            row,
            wall_distance=wall_distance,
            option_oi_noise_ratio=option_oi_noise_ratio,
        )
        for event_type in event_types:
            for horizon in horizons:
                execution_index = index + 1
                exit_index = execution_index + horizon
                resolved = exit_index < len(ordered)
                execution = (
                    ordered.iloc[execution_index]
                    if execution_index < len(ordered)
                    else None
                )
                exit_row = ordered.iloc[exit_index] if resolved else None
                forward_return = (
                    float(exit_row["target_settle"] / execution["target_settle"] - 1.0)
                    if resolved and execution is not None
                    else None
                )
                rows.append(
                    {
                        "run_id": run_id,
                        "event_date": row["trade_date"],
                        "event_type": event_type,
                        "horizon": horizon,
                        "execution_date": (
                            execution["trade_date"] if execution is not None else None
                        ),
                        "exit_date": exit_row["trade_date"] if exit_row is not None else None,
                        "execution_settle": (
                            float(execution["target_settle"])
                            if execution is not None
                            else None
                        ),
                        "exit_settle": (
                            float(exit_row["target_settle"])
                            if exit_row is not None
                            else None
                        ),
                        "forward_return": forward_return,
                        "posterior_direction": _posterior_direction(forward_return),
                        "is_resolved": resolved,
                        "rule_version": STRUCTURAL_POSITION_ATTRIBUTION_VERSION,
                        "trading_instruction": "not_a_trading_instruction",
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def _option_event_types(
    row: pd.Series, *, wall_distance: float, option_oi_noise_ratio: float
) -> list[str]:
    if pd.isna(row.get("call_total_open_interest")):
        return []
    events: list[str] = []
    call_distance = row.get("distance_to_call_wall")
    put_distance = row.get("distance_to_put_wall")
    if not pd.isna(call_distance) and abs(float(call_distance)) <= wall_distance:
        events.append("NEAR_CALL_WALL")
    if not pd.isna(put_distance) and abs(float(put_distance)) <= wall_distance:
        events.append("NEAR_PUT_WALL")
    call_level = max(_number(row.get("call_total_open_interest")), 1.0)
    put_level = max(_number(row.get("put_total_open_interest")), 1.0)
    call_change = _number(row.get("call_total_oi_change"))
    put_change = _number(row.get("put_total_oi_change"))
    if call_change <= -call_level * option_oi_noise_ratio:
        events.append("CALL_TOTAL_OI_UNWIND")
    if put_change >= put_level * option_oi_noise_ratio:
        events.append("PUT_TOTAL_OI_BUILD")
    if _number(row.get("call_wall_oi_change")) < 0:
        events.append("CALL_WALL_OI_UNWIND")
    if _number(row.get("put_wall_oi_change")) > 0:
        events.append("PUT_WALL_OI_BUILD")
    if row.get("option_structure_state") == "PRICE_UP_PUT_OI_DOMINANT_BUILD":
        events.append("PRICE_UP_PUT_OI_DOMINANT_BUILD")
    return sorted(set(events))


def _posterior_direction(value: float | None) -> str:
    if value is None:
        return "UNRESOLVED"
    if value > 0:
        return "UP"
    if value < 0:
        return "DOWN"
    return "FLAT"


def _build_option_event_summary(
    *, events: pd.DataFrame, run_id: str
) -> pd.DataFrame:
    columns = [
        "run_id",
        "event_type",
        "horizon",
        "sample_count",
        "mean_forward_return",
        "median_forward_return",
        "up_ratio",
        "down_ratio",
        "evidence_level",
        "rule_version",
    ]
    if events.empty:
        return pd.DataFrame(columns=columns)
    resolved = events.loc[events["is_resolved"]].dropna(subset=["forward_return"])
    rows: list[dict[str, object]] = []
    for (event_type, horizon), group in resolved.groupby(
        ["event_type", "horizon"], sort=True
    ):
        count = len(group)
        rows.append(
            {
                "run_id": run_id,
                "event_type": event_type,
                "horizon": int(horizon),
                "sample_count": count,
                "mean_forward_return": float(group["forward_return"].mean()),
                "median_forward_return": float(group["forward_return"].median()),
                "up_ratio": float(group["forward_return"].gt(0).mean()),
                "down_ratio": float(group["forward_return"].lt(0).mean()),
                "evidence_level": "WATCH" if count >= 30 else "WEAK_OR_SMALL_SAMPLE",
                "rule_version": STRUCTURAL_POSITION_ATTRIBUTION_VERSION,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _build_window_summaries(
    *,
    daily: pd.DataFrame,
    member_flow: pd.DataFrame,
    focus_start: date,
    focus_end: date,
    contract_tons: float,
    receipt_tons: float,
    run_id: str,
) -> pd.DataFrame:
    windows: list[tuple[str, date, date]] = [
        ("FULL_ACTIVE_WINDOW", daily["trade_date"].min(), daily["trade_date"].max()),
        ("FOCUS_WINDOW", focus_start, focus_end),
    ]
    if not member_flow.empty:
        member_start = max(focus_start, member_flow["trade_date"].min())
        member_end = min(focus_end, member_flow["trade_date"].max())
        if member_start <= member_end:
            windows.append(("COMMON_MEMBER_WINDOW", member_start, member_end))
    if "warehouse_observation_date" in daily.columns:
        observed_warehouse_dates = daily["warehouse_observation_date"].dropna()
        if not observed_warehouse_dates.empty:
            warehouse_end = min(focus_end, observed_warehouse_dates.max())
            if focus_start <= warehouse_end:
                windows.append(
                    ("COMMON_WAREHOUSE_WINDOW", focus_start, warehouse_end)
                )
    focus = daily.loc[daily["trade_date"].between(focus_start, focus_end)].copy()
    if not focus.empty:
        focus["month"] = focus["trade_date"].map(lambda value: value.strftime("%Y-%m"))
        for month, group in focus.groupby("month", sort=True):
            windows.append((f"MONTH_{month}", group["trade_date"].min(), group["trade_date"].max()))
    rows = [
        _window_summary_row(
            window_type=window_type,
            start=start,
            end=end,
            daily=daily,
            member_flow=member_flow,
            contract_tons=contract_tons,
            receipt_tons=receipt_tons,
            run_id=run_id,
        )
        for window_type, start, end in windows
    ]
    return pd.DataFrame(rows)


def _window_summary_row(
    *,
    window_type: str,
    start: date,
    end: date,
    daily: pd.DataFrame,
    member_flow: pd.DataFrame,
    contract_tons: float,
    receipt_tons: float,
    run_id: str,
) -> dict[str, object]:
    market = daily.loc[daily["trade_date"].between(start, end)].sort_values("trade_date")
    member = member_flow.loc[
        member_flow["trade_date"].between(start, end)
    ] if not member_flow.empty else member_flow
    if market.empty:
        raise ResearchWorkbenchError(f"window {window_type} has no market rows")
    first = market.iloc[0]
    last = market.iloc[-1]
    target_change = float(last["target_open_interest"] - first["target_open_interest"])
    positive_target_change = max(target_change, 0.0)
    visible_roll = _sum(member, "source_to_target_gross_roll_proxy")
    market_dates = set(market["trade_date"])
    member_dates = set(member["trade_date"]) if not member.empty else set()
    member_coverage_complete = market_dates.issubset(member_dates)
    warehouse_values = market.dropna(subset=["warehouse_receipt"])
    warehouse_change = None
    warehouse_observation_end = (
        warehouse_values["warehouse_observation_date"].max()
        if not warehouse_values.empty
        else None
    )
    warehouse_coverage_complete = (
        warehouse_observation_end is not None
        and warehouse_observation_end >= last["trade_date"]
    )
    if warehouse_coverage_complete:
        warehouse_change = float(
            warehouse_values.iloc[-1]["warehouse_receipt"]
            - warehouse_values.iloc[0]["warehouse_receipt"]
        )
    receipt_tonnage = (
        float(last["warehouse_receipt"] * receipt_tons)
        if warehouse_coverage_complete and not pd.isna(last["warehouse_receipt"])
        else None
    )
    return {
        "run_id": run_id,
        "window_type": window_type,
        "start": first["trade_date"],
        "end": last["trade_date"],
        "market_day_count": len(market),
        "member_day_count": len(member),
        "member_coverage_complete": member_coverage_complete,
        "option_day_count": int(market["option_data_available"].sum()),
        "warehouse_coverage_complete": warehouse_coverage_complete,
        "target_oi_start": float(first["target_open_interest"]),
        "target_oi_end": float(last["target_open_interest"]),
        "target_oi_change": target_change,
        "target_notional_tonnage_change": target_change * contract_tons,
        "source_oi_change": _difference(first, last, "source_open_interest"),
        "next_oi_change": _difference(first, last, "next_open_interest"),
        "chain_oi_change": _difference(first, last, "chain_open_interest"),
        "source_to_target_long_roll_proxy": _sum(
            member, "source_to_target_long_roll_proxy"
        ),
        "source_to_target_short_roll_proxy": _sum(
            member, "source_to_target_short_roll_proxy"
        ),
        "source_to_target_gross_roll_proxy": visible_roll,
        "visible_roll_to_positive_target_change_ratio": (
            visible_roll / positive_target_change
            if member_coverage_complete and positive_target_change > 0
            else None
        ),
        "arithmetic_residual_after_capped_visible_roll": (
            max(positive_target_change - visible_roll, 0.0)
            if member_coverage_complete
            else None
        ),
        "target_long_next_short_pair_proxy": _sum(
            member, "target_long_next_short_pair_proxy"
        ),
        "target_short_next_long_pair_proxy": _sum(
            member, "target_short_next_long_pair_proxy"
        ),
        "target_next_gross_pair_proxy": _sum(member, "target_next_gross_pair_proxy"),
        "warehouse_receipt_change": warehouse_change,
        "warehouse_receipt_tonnage_end": receipt_tonnage,
        "target_oi_to_receipt_tonnage_ratio_end": (
            float(last["target_notional_tons"] / receipt_tonnage)
            if receipt_tonnage not in (None, 0)
            else None
        ),
        "mean_delivery_adjusted_residual": _mean(
            market, "delivery_adjusted_residual"
        ),
        "latest_delivery_adjusted_residual": _last_value(
            market, "delivery_adjusted_residual"
        ),
        "rule_version": STRUCTURAL_POSITION_ATTRIBUTION_VERSION,
    }


def _warning_rows(
    *,
    run_id: str,
    effective_end: date,
    member_path: Path | None,
    member_asof: date | None,
    warehouse_path: Path | None,
    warehouse_asof: date | None,
    strike_path: Path | None,
    option_asof: date | None,
    option_event_summary: pd.DataFrame,
) -> list[dict[str, object]]:
    warnings = [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "WARN",
            "warning_code": "STRUCTURAL_ATTRIBUTION_IS_PROXY",
            "warning_message": (
                "席位配对、仓单和期权持仓只能形成结构代理，不能识别客户或主动买卖方。"
            ),
            "affected_count": 1,
            "human_review_required": ";".join(HUMAN_REVIEW_REQUIRED),
        }
    ]
    for section, path, asof, code in (
        ("member", member_path, member_asof, "MEMBER_DATA_STALE_OR_MISSING"),
        ("warehouse", warehouse_path, warehouse_asof, "WAREHOUSE_DATA_STALE_OR_MISSING"),
        ("option", strike_path, option_asof, "OPTION_DATA_STALE_OR_MISSING"),
    ):
        stale = asof is None or asof < effective_end
        warnings.append(
            {
                "run_id": run_id,
                "section": section,
                "severity": "WARN" if stale else "INFO",
                "warning_code": code,
                "warning_message": (
                    f"{section} 数据路径或覆盖日未到行情截止日；报告保留独立 as-of。"
                    if stale
                    else f"{section} 数据已覆盖行情截止日。"
                ),
                "affected_count": 1 if path is None else 0,
                "human_review_required": section,
            }
        )
    small = (
        option_event_summary["evidence_level"].eq("WEAK_OR_SMALL_SAMPLE")
        if not option_event_summary.empty
        else pd.Series(dtype=bool)
    )
    warnings.append(
        {
            "run_id": run_id,
            "section": "option_posterior",
            "severity": "WARN" if small.any() else "INFO",
            "warning_code": "OPTION_EVENT_SMALL_SAMPLE",
            "warning_message": "期权节点后验样本不足30时只允许作WATCH观察。",
            "affected_count": int(small.sum()),
            "human_review_required": "option_expiry_and_liquidity_filter",
        }
    )
    return warnings


def _paths(
    *,
    start: date,
    end: date,
    target_contract: str,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    stem = (
        f"CF_{start.isoformat()}_{end.isoformat()}_"
        f"{target_contract}_structural_position_attribution"
    )
    data_root = output_dir or (
        data_dir() / "research" / PRODUCT_CODE / "structural_position_attribution"
    )
    report_root = report_output_dir or (
        reports_dir() / "research" / "structural_position_attribution"
    )
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "member_flow_parquet": data_root / f"{stem}_member_flow.parquet",
        "member_flow_csv": data_root / f"{stem}_member_flow.csv",
        "window_summary_parquet": data_root / f"{stem}_window_summary.parquet",
        "window_summary_csv": data_root / f"{stem}_window_summary.csv",
        "option_event_parquet": data_root / f"{stem}_option_event.parquet",
        "option_event_csv": data_root / f"{stem}_option_event.csv",
        "option_summary_parquet": data_root / f"{stem}_option_event_summary.parquet",
        "option_summary_csv": data_root / f"{stem}_option_event_summary.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _write_markdown(
    *,
    result: ResearchStructuralPositionAttributionResult,
    daily: pd.DataFrame,
    window_summary: pd.DataFrame,
    option_event_summary: pd.DataFrame,
    wall_distance: float,
) -> None:
    latest = daily.iloc[-1]
    focus = window_summary.loc[
        window_summary["window_type"].eq("FOCUS_WINDOW")
    ].iloc[0]
    member_candidates = window_summary.loc[
        window_summary["window_type"].eq("COMMON_MEMBER_WINDOW")
    ]
    warehouse_candidates = window_summary.loc[
        window_summary["window_type"].eq("COMMON_WAREHOUSE_WINDOW")
    ]
    member_window = None if member_candidates.empty else member_candidates.iloc[0]
    warehouse_window = (
        None if warehouse_candidates.empty else warehouse_candidates.iloc[0]
    )
    member_summary = (
        "- 会员席位数据未形成共同覆盖窗口，不能计算可见移仓与净增仓比值。"
        if member_window is None
        else (
            f"- 在会员共同覆盖窗口{member_window['start']}至{member_window['end']}，"
            f"Top20席位可见的{result.source_contract}->{result.target_contract}同侧gross"
            f"移仓代理累计"
            f"`{fmt_number(member_window['source_to_target_gross_roll_proxy'], 0)}`手，"
            f"与目标合约正向净增仓的比值为"
            f"`{fmt_percent(member_window['visible_roll_to_positive_target_change_ratio'])}`。"
        )
    )
    warehouse_summary = (
        "- 仓单数据未形成共同覆盖窗口，不能与目标合约增仓作同窗比较。"
        if warehouse_window is None
        else (
            f"- 在仓单共同覆盖窗口{warehouse_window['start']}至"
            f"{warehouse_window['end']}，目标合约增仓"
            f"`{fmt_number(warehouse_window['target_oi_change'], 0)}`手，仓单变化"
            f"`{fmt_number(warehouse_window['warehouse_receipt_change'], 0)}`张；"
            "两者量级和方向均不能支持静态仓单单独解释异常持仓。"
        )
    )
    near_call = option_event_summary.loc[
        option_event_summary["event_type"].eq("NEAR_CALL_WALL")
    ].sort_values("horizon")
    lines = [
        f"# {result.target_contract}结构性持仓归因研究",
        "",
        f"行情截至：`{result.end}`",
        f"会员席位截至：`{_date_text(result.member_data_asof)}`",
        f"仓单序列截至：`{_date_text(result.warehouse_data_asof)}`",
        f"期权结构截至：`{_date_text(result.option_data_asof)}`",
        "",
        "## 核心结论",
        "",
        f"- 最新结算价：`{fmt_number(latest['target_settle'], 0)}`，"
        f"持仓：`{fmt_number(latest['target_open_interest'], 0)}`，"
        f"结构状态：`{latest['target_oi_structure_state']}`。",
        f"- 研究窗口{result.focus_start}至{result.focus_end}，目标合约净增仓"
        f"`{fmt_number(focus['target_oi_change'], 0)}`手。",
        member_summary,
        warehouse_summary,
        f"- 最新期权结构：`{latest['option_structure_state']}`；"
        "期权OI变化不能识别主动买方或卖方。",
        "",
        "## 窗口归因",
        "",
        "| 窗口 | 日期 | 会员覆盖 | 611 OI变化 | 可见609->611 gross移仓 | "
        "gross/净增仓 | 611多/701空 | 611空/701多 | 仓单变化 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in window_summary.to_dict(orient="records"):
        lines.append(
            f"| {row['window_type']} | {row['start']}至{row['end']} | "
            f"{'完整' if row['member_coverage_complete'] else '不完整'} | "
            f"{fmt_number(row['target_oi_change'], 0)} | "
            f"{fmt_number(row['source_to_target_gross_roll_proxy'], 0)} | "
            f"{fmt_percent(row['visible_roll_to_positive_target_change_ratio'])} | "
            f"{fmt_number(row['target_long_next_short_pair_proxy'], 0)} | "
            f"{fmt_number(row['target_short_next_long_pair_proxy'], 0)} | "
            f"{fmt_number(row['warehouse_receipt_change'], 0)} |"
        )
    lines.extend(
        [
            "",
            "## 期权关键点位后验",
            "",
            f"接近Call墙定义为结算价距Call墙不超过`{wall_distance:.2%}`。"
            "事件在T日识别，T+1结算执行，T+1+horizon结算退出。",
            "",
            "| 事件 | 周期 | 样本 | 平均后验收益 | 上涨比例 | 下跌比例 | 证据 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in near_call.to_dict(orient="records"):
        lines.append(
            f"| NEAR_CALL_WALL | {row['horizon']}D | {row['sample_count']} | "
            f"{fmt_percent(row['mean_forward_return'])} | "
            f"{fmt_percent(row['up_ratio'])} | {fmt_percent(row['down_ratio'])} | "
            f"{row['evidence_level']} |"
        )
    if near_call.empty:
        lines.append("| NEAR_CALL_WALL | - | 0 | - | - | - | 无样本 |")
    lines.extend(
        [
            "",
            "## 最新期权事实",
            "",
            f"- Call总OI：`{fmt_number(latest.get('call_total_open_interest'), 0)}`，"
            f"单日变化：`{fmt_number(latest.get('call_total_oi_change'), 0)}`。",
            f"- Put总OI：`{fmt_number(latest.get('put_total_open_interest'), 0)}`，"
            f"单日变化：`{fmt_number(latest.get('put_total_oi_change'), 0)}`。",
            f"- PCR成交：`{fmt_number(latest.get('pcr_volume'), 3)}`，"
            f"PCR持仓：`{fmt_number(latest.get('pcr_oi'), 3)}`。",
            f"- Call墙：`{fmt_number(latest.get('call_wall_strike'), 0)}`，"
            f"墙体变化：`{fmt_number(latest.get('call_wall_oi_change'), 0)}`。",
            f"- Put墙：`{fmt_number(latest.get('put_wall_strike'), 0)}`，"
            f"墙体变化：`{fmt_number(latest.get('put_wall_oi_change'), 0)}`。",
            f"- 当日Call最大增仓行权价："
            f"`{fmt_number(latest.get('call_build_strike'), 0)}`，"
            f"变化`{fmt_number(latest.get('call_build_oi_change'), 0)}`。",
            f"- 当日Put最大增仓行权价："
            f"`{fmt_number(latest.get('put_build_strike'), 0)}`，"
            f"变化`{fmt_number(latest.get('put_build_oi_change'), 0)}`。",
            "",
            "## 研究边界",
            "",
            "- 会员排名是席位层Top20，不是客户级持仓；同日配对只是不完全可见代理。",
            "- gross roll与跨期pair可能重叠，禁止相加后称为实际套利规模。",
            "- gross/净增仓比值可能超过100%，表示窗口内存在重复换手或净额抵消，"
            "不表示移仓解释度超过100%。",
            "- 仓单总量不能替代逐仓单质量、仓库、注册日和注销日的CTD排序。",
            "- 期权OI无法判断新增来自买方还是卖方，IV/Greek仍为研究proxy。",
            "- forward return仅作为历史后验验证标签，不进入最新日判断。",
            "- 不改变`composite_score`，不构成交易指令。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")


def _latest_optional(directory: Path, pattern: str, label: str) -> Path | None:
    if not directory.exists():
        return None
    try:
        return latest_matching_path(directory, pattern, label=label)
    except ResearchWorkbenchError:
        return None


def _existing_optional(path: Path) -> Path | None:
    return path if path.exists() else None


def _max_date(frame: pd.DataFrame) -> date | None:
    if frame.empty or "trade_date" not in frame.columns:
        return None
    value = frame["trade_date"].max()
    return None if pd.isna(value) else value


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _number(value: object) -> float:
    return 0.0 if value is None or pd.isna(value) else float(value)


def _sum(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum())


def _difference(first: pd.Series, last: pd.Series, column: str) -> float | None:
    if column not in first.index or pd.isna(first[column]) or pd.isna(last[column]):
        return None
    return float(last[column] - first[column])


def _mean(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return None if values.empty else float(values.mean())


def _last_value(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return None if values.empty else float(values.iloc[-1])
