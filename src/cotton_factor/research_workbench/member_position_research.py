"""R83 CF 会员持仓集中度、多空变化、背离与移仓研究。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.member_position_ingest import (
    CORE_MEMBER_POSITION_FILE_NAME,
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
MEMBER_POSITION_RESEARCH_VERSION = "R83_member_position_research_v1"
DEFAULT_TOP_NS = (5, 10, 20)
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_MIN_HISTORY_DAYS = 60
DEFAULT_POSITION_CHANGE_DEAD_ZONE = 0.002
DEFAULT_PRICE_DEAD_ZONE = 0.001
HUMAN_REVIEW_REQUIRED = (
    "member_position_is_member_level_not_customer_identity",
    "top_rank_concentration_denominator",
    "member_position_change_threshold",
    "roll_migration_member_interpretation",
    "historical_forward_label_interpretation",
)
RESEARCH_BOUNDARY = {
    "member_ranking_is_not_customer_net_exposure": True,
    "aggregate_open_interest_is_not_long_short_direction": True,
    "forward_returns_are_historical_posterior_labels": True,
    "latest_state_uses_future_data": False,
    "automatic_signal_reversal": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchMemberPositionResult:
    """R83 研究产物和样本覆盖摘要。"""

    run_id: str
    start: date
    end: date
    history_date_count: int
    daily_row_count: int
    member_detail_row_count: int
    roll_row_count: int
    validation_row_count: int
    warning_count: int
    latest_main_contract: str | None
    latest_member_direction: str
    daily_parquet_path: Path
    daily_csv_path: Path
    member_detail_parquet_path: Path
    member_detail_csv_path: Path
    roll_parquet_path: Path
    roll_csv_path: Path
    validation_parquet_path: Path
    validation_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_member_position_path: Path
    core_quote_path: Path
    validation_daily_path: Path | None

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "history_date_count": self.history_date_count,
            "daily_row_count": self.daily_row_count,
            "member_detail_row_count": self.member_detail_row_count,
            "roll_row_count": self.roll_row_count,
            "validation_row_count": self.validation_row_count,
            "warning_count": self.warning_count,
            "latest_main_contract": self.latest_main_contract,
            "latest_member_direction": self.latest_member_direction,
            "daily_parquet_path": str(self.daily_parquet_path),
            "member_detail_parquet_path": str(self.member_detail_parquet_path),
            "roll_parquet_path": str(self.roll_parquet_path),
            "validation_parquet_path": str(self.validation_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_member_position_path": str(self.core_member_position_path),
            "core_quote_path": str(self.core_quote_path),
            "validation_daily_path": (
                None if self.validation_daily_path is None else str(self.validation_daily_path)
            ),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_member_position_research(
    *,
    member_position_path: Path | None = None,
    core_quote_path: Path | None = None,
    validation_daily_path: Path | None = None,
    end: date | None = None,
    top_ns: tuple[int, ...] = DEFAULT_TOP_NS,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    position_change_dead_zone: float = DEFAULT_POSITION_CHANGE_DEAD_ZONE,
    price_dead_zone: float = DEFAULT_PRICE_DEAD_ZONE,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchMemberPositionResult:
    """构建会员排名集中度、席位变化和后验验证，不改写主信号。"""
    normalized_top_ns = tuple(sorted(set(int(value) for value in top_ns)))
    normalized_horizons = tuple(sorted(set(int(value) for value in horizons)))
    if not normalized_top_ns or any(value < 1 or value > 20 for value in normalized_top_ns):
        raise ResearchWorkbenchError("top_ns must be within 1..20")
    if not normalized_horizons or any(value < 1 for value in normalized_horizons):
        raise ResearchWorkbenchError("horizons must contain positive trading-day values")
    if position_change_dead_zone < 0 or price_dead_zone < 0:
        raise ResearchWorkbenchError("dead-zone values cannot be negative")
    if min_sample_size < 1 or min_history_days < 1:
        raise ResearchWorkbenchError("sample and history thresholds must be positive")

    member_path = member_position_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_MEMBER_POSITION_FILE_NAME
    )
    quote_path = core_quote_path or (
        data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    )
    member = load_table(
        member_path,
        required={
            "trade_date",
            "scope_type",
            "scope_code",
            "contract_code",
            "position_side",
            "rank",
            "member_name",
            "position_value",
            "position_change",
            "data_quality_flag",
        },
        label="CF member-position core",
    )
    quotes = load_table(
        quote_path,
        required={
            "trade_date",
            "contract_code",
            "settle",
            "close",
            "open_interest",
        },
        label="CF core quote",
    )
    member = normalize_trade_date(member)
    quotes = normalize_trade_date(quotes)
    if end is not None:
        member = member.loc[member["trade_date"].le(end)].copy()
        quotes = quotes.loc[quotes["trade_date"].le(end)].copy()
    if member.empty:
        raise ResearchWorkbenchError("R83 has no member-position rows after date filter")
    if not set(member["position_side"].astype(str)).issubset({"volume", "long", "short"}):
        raise ResearchWorkbenchError("member-position core contains unknown position_side")

    start = member["trade_date"].min()
    effective_end = member["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("r83_member_position", effective_end)
    quote_contract, quote_product = _quote_context(quotes)
    daily = _build_daily_summary(
        member=member,
        quote_contract=quote_contract,
        quote_product=quote_product,
        top_ns=normalized_top_ns,
        position_change_dead_zone=position_change_dead_zone,
        price_dead_zone=price_dead_zone,
        run_id=active_run_id,
    )
    member_detail = _build_member_detail(member=member, run_id=active_run_id)
    roll = _build_roll_migration(
        daily=daily,
        quote_contract=quote_contract,
        run_id=active_run_id,
    )
    resolved_validation = validation_daily_path or _optional_validation_path()
    validation = _build_historical_validation(
        daily=daily,
        validation_path=resolved_validation,
        horizons=normalized_horizons,
        min_sample_size=min_sample_size,
        end=effective_end,
        run_id=active_run_id,
    )
    history_date_count = int(member["trade_date"].nunique())
    warnings = _warning_rows(
        member=member,
        daily=daily,
        validation=validation,
        history_date_count=history_date_count,
        min_history_days=min_history_days,
        run_id=active_run_id,
    )
    paths = _paths(
        start=start,
        end=effective_end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(
        member_detail,
        paths["member_detail_parquet"],
        paths["member_detail_csv"],
    )
    write_frame(roll, paths["roll_parquet"], paths["roll_csv"])
    write_frame(validation, paths["validation_parquet"], paths["validation_csv"])
    write_warning_csv(paths["warning_csv"], warnings)

    latest_main = _latest_main_summary(daily, quote_product, effective_end)
    latest_main_contract = (
        None if latest_main is None else str(latest_main["scope_code"])
    )
    latest_direction = (
        "not_available" if latest_main is None else str(latest_main["member_direction"])
    )
    result = ResearchMemberPositionResult(
        run_id=active_run_id,
        start=start,
        end=effective_end,
        history_date_count=history_date_count,
        daily_row_count=len(daily),
        member_detail_row_count=len(member_detail),
        roll_row_count=len(roll),
        validation_row_count=len(validation),
        warning_count=sum(1 for row in warnings if row["severity"] == "WARN"),
        latest_main_contract=latest_main_contract,
        latest_member_direction=latest_direction,
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        member_detail_parquet_path=paths["member_detail_parquet"],
        member_detail_csv_path=paths["member_detail_csv"],
        roll_parquet_path=paths["roll_parquet"],
        roll_csv_path=paths["roll_csv"],
        validation_parquet_path=paths["validation_parquet"],
        validation_csv_path=paths["validation_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        core_member_position_path=member_path,
        core_quote_path=quote_path,
        validation_daily_path=resolved_validation,
    )
    _write_markdown(
        result=result,
        daily=daily,
        member_detail=member_detail,
        roll=roll,
        validation=validation,
        warnings=warnings,
    )
    latest_rows = daily.loc[daily["trade_date"].eq(effective_end)].to_dict(orient="records")
    latest_members = member_detail.loc[
        member_detail["trade_date"].eq(effective_end)
    ].to_dict(orient="records")
    write_json(
        result.json_path,
        {
            "report_type": "cf_member_position_research",
            "rule_version": MEMBER_POSITION_RESEARCH_VERSION,
            "summary": result.to_summary(),
            "latest_rows": latest_rows,
            "latest_member_decomposition": latest_members,
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="cf_member_position_research",
            rule_version=MEMBER_POSITION_RESEARCH_VERSION,
            data_asof=effective_end,
            input_paths={
                "core_member_position_path": member_path,
                "core_quote_path": quote_path,
                "validation_daily_path": resolved_validation,
            },
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "member_detail_parquet_path": result.member_detail_parquet_path,
                "roll_parquet_path": result.roll_parquet_path,
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


def _quote_context(quotes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = quotes.copy()
    frame["settle"] = pd.to_numeric(frame["settle"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["open_interest"] = pd.to_numeric(frame["open_interest"], errors="coerce")
    frame = frame.sort_values(["contract_code", "trade_date"])
    frame["settle_return"] = frame.groupby("contract_code")["settle"].pct_change(
        fill_method=None
    )
    frame["close_return"] = frame.groupby("contract_code")["close"].pct_change(
        fill_method=None
    )
    frame["open_interest_change"] = frame.groupby("contract_code")[
        "open_interest"
    ].diff()
    contract = frame[
        [
            "trade_date",
            "contract_code",
            "settle_return",
            "close_return",
            "open_interest",
            "open_interest_change",
        ]
    ].copy()
    product_rows: list[dict[str, object]] = []
    for trade_date, group in frame.groupby("trade_date"):
        valid = group.loc[group["open_interest"].notna()].copy()
        if valid.empty:
            continue
        main = valid.sort_values(
            ["open_interest", "contract_code"], ascending=[False, True]
        ).iloc[0]
        product_rows.append(
            {
                "trade_date": trade_date,
                "main_contract": str(main["contract_code"]),
                "settle_return": main["settle_return"],
                "close_return": main["close_return"],
                "open_interest": valid["open_interest"].sum(),
                "open_interest_change": valid["open_interest_change"].sum(min_count=1),
            }
        )
    return contract, pd.DataFrame(product_rows)


def _build_daily_summary(
    *,
    member: pd.DataFrame,
    quote_contract: pd.DataFrame,
    quote_product: pd.DataFrame,
    top_ns: tuple[int, ...],
    position_change_dead_zone: float,
    price_dead_zone: float,
    run_id: str,
) -> pd.DataFrame:
    contract_lookup = {
        (row.trade_date, str(row.contract_code)): row
        for row in quote_contract.itertuples(index=False)
    }
    product_lookup = {
        row.trade_date: row for row in quote_product.itertuples(index=False)
    }
    rows: list[dict[str, object]] = []
    group_columns = ["trade_date", "scope_type", "scope_code", "contract_code"]
    for keys, group in member.groupby(group_columns, dropna=False):
        trade_date, scope_type, scope_code, contract_code = keys
        quote_row = (
            product_lookup.get(trade_date)
            if scope_type == "product"
            else contract_lookup.get((trade_date, str(scope_code)))
        )
        denominator = None if quote_row is None else _float_or_none(quote_row.open_interest)
        settle_return = None if quote_row is None else _float_or_none(quote_row.settle_return)
        close_return = None if quote_row is None else _float_or_none(quote_row.close_return)
        oi_change = (
            None if quote_row is None else _float_or_none(quote_row.open_interest_change)
        )
        main_contract = (
            None
            if quote_row is None
            else (
                str(quote_row.main_contract)
                if scope_type == "product"
                else str(scope_code)
            )
        )
        for top_n in top_ns:
            selected = group.loc[pd.to_numeric(group["rank"], errors="coerce").le(top_n)]
            aggregates: dict[str, float] = {}
            rank_counts: dict[str, int] = {}
            for side in ("volume", "long", "short"):
                side_rows = selected.loc[selected["position_side"].astype(str).eq(side)]
                aggregates[f"{side}_position"] = float(
                    pd.to_numeric(side_rows["position_value"], errors="coerce").sum()
                )
                aggregates[f"{side}_change"] = float(
                    pd.to_numeric(side_rows["position_change"], errors="coerce").sum()
                )
                rank_counts[side] = int(side_rows["rank"].nunique())
            top_net_position = aggregates["long_position"] - aggregates["short_position"]
            top_net_change = aggregates["long_change"] - aggregates["short_change"]
            direction = _member_direction(
                top_net_change=top_net_change,
                denominator=denominator,
                dead_zone=position_change_dead_zone,
            )
            flow_state = _member_flow_state(
                long_change=aggregates["long_change"],
                short_change=aggregates["short_change"],
                denominator=denominator,
                dead_zone=position_change_dead_zone,
            )
            rows.append(
                {
                    "run_id": run_id,
                    "trade_date": trade_date,
                    "scope_type": str(scope_type),
                    "scope_code": str(scope_code),
                    "contract_code": (
                        None if pd.isna(contract_code) else str(contract_code)
                    ),
                    "main_contract": main_contract,
                    "top_n": top_n,
                    **aggregates,
                    "top_net_position": top_net_position,
                    "top_net_change": top_net_change,
                    "open_interest_denominator": denominator,
                    "open_interest_change": oi_change,
                    "long_concentration": _safe_ratio(
                        aggregates["long_position"], denominator
                    ),
                    "short_concentration": _safe_ratio(
                        aggregates["short_position"], denominator
                    ),
                    "net_concentration": _safe_ratio(top_net_position, denominator),
                    "net_change_ratio": _safe_ratio(top_net_change, denominator),
                    "settle_return": settle_return,
                    "close_return": close_return,
                    "member_direction": direction,
                    "member_flow_state": flow_state,
                    "price_member_relation": _price_member_relation(
                        settle_return=settle_return,
                        member_direction=direction,
                        price_dead_zone=price_dead_zone,
                    ),
                    "oi_member_relation": _oi_member_relation(
                        oi_change=oi_change,
                        long_change=aggregates["long_change"],
                        short_change=aggregates["short_change"],
                    ),
                    "volume_rank_count": rank_counts["volume"],
                    "long_rank_count": rank_counts["long"],
                    "short_rank_count": rank_counts["short"],
                    "data_quality_flag": ";".join(
                        sorted(set(selected["data_quality_flag"].astype(str)))
                    ),
                    "forward_returns_are_historical_posterior_labels": True,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["trade_date", "scope_type", "scope_code", "top_n"]
    ).reset_index(drop=True)


def _build_member_detail(*, member: pd.DataFrame, run_id: str) -> pd.DataFrame:
    selected = member.loc[member["position_side"].isin(["long", "short"])].copy()
    grouped = (
        selected.groupby(
            [
                "trade_date",
                "scope_type",
                "scope_code",
                "contract_code",
                "member_name",
                "position_side",
            ],
            dropna=False,
        )[["position_value", "position_change"]]
        .sum()
        .reset_index()
    )
    value = grouped.pivot_table(
        index=["trade_date", "scope_type", "scope_code", "contract_code", "member_name"],
        columns="position_side",
        values="position_value",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    change = grouped.pivot_table(
        index=["trade_date", "scope_type", "scope_code", "contract_code", "member_name"],
        columns="position_side",
        values="position_change",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    value = value.rename(columns={"long": "long_position", "short": "short_position"})
    change = change.rename(columns={"long": "long_change", "short": "short_change"})
    keys = ["trade_date", "scope_type", "scope_code", "contract_code", "member_name"]
    result = value.merge(change, on=keys, how="outer").fillna(0)
    for column in ("long_position", "short_position", "long_change", "short_change"):
        if column not in result.columns:
            result[column] = 0
    result["net_position"] = result["long_position"] - result["short_position"]
    result["net_change"] = result["long_change"] - result["short_change"]
    result.insert(0, "run_id", run_id)
    result["member_scope_boundary"] = "member_ranking_not_customer_identity"
    return result.sort_values(
        ["trade_date", "scope_type", "scope_code", "net_position"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)


def _build_roll_migration(
    *, daily: pd.DataFrame, quote_contract: pd.DataFrame, run_id: str
) -> pd.DataFrame:
    top20 = daily.loc[
        daily["scope_type"].eq("contract") & daily["top_n"].eq(20)
    ].copy()
    rows: list[dict[str, object]] = []
    for trade_date, quotes in quote_contract.groupby("trade_date"):
        date_contracts = top20.loc[
            top20["trade_date"].eq(trade_date), "scope_code"
        ]
        available = quotes.loc[
            quotes["contract_code"].isin(date_contracts)
            & quotes["open_interest"].notna()
        ].sort_values(["open_interest", "contract_code"], ascending=[False, True])
        if len(available) < 2:
            continue
        main_quote = available.iloc[0]
        receiving_quote = available.iloc[1]
        main = top20.loc[
            top20["trade_date"].eq(trade_date)
            & top20["scope_code"].eq(str(main_quote["contract_code"]))
        ].iloc[0]
        receiving = top20.loc[
            top20["trade_date"].eq(trade_date)
            & top20["scope_code"].eq(str(receiving_quote["contract_code"]))
        ].iloc[0]
        main_total_change = float(main["long_change"] + main["short_change"])
        receiving_total_change = float(
            receiving["long_change"] + receiving["short_change"]
        )
        rows.append(
            {
                "run_id": run_id,
                "trade_date": trade_date,
                "main_contract": str(main_quote["contract_code"]),
                "receiving_contract": str(receiving_quote["contract_code"]),
                "main_open_interest": main_quote["open_interest"],
                "receiving_open_interest": receiving_quote["open_interest"],
                "main_open_interest_change": main_quote["open_interest_change"],
                "receiving_open_interest_change": receiving_quote["open_interest_change"],
                "main_long_change": main["long_change"],
                "main_short_change": main["short_change"],
                "receiving_long_change": receiving["long_change"],
                "receiving_short_change": receiving["short_change"],
                "main_ranked_total_change": main_total_change,
                "receiving_ranked_total_change": receiving_total_change,
                "ranked_transfer_ratio": (
                    receiving_total_change / abs(main_total_change)
                    if main_total_change < 0 and receiving_total_change > 0
                    else None
                ),
                "roll_migration_state": _roll_state(
                    main_total_change, receiving_total_change
                ),
                "long_migration_state": _side_migration_state(
                    float(main["long_change"]), float(receiving["long_change"])
                ),
                "short_migration_state": _side_migration_state(
                    float(main["short_change"]), float(receiving["short_change"])
                ),
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    columns = [
        "run_id",
        "trade_date",
        "main_contract",
        "receiving_contract",
        "main_open_interest",
        "receiving_open_interest",
        "main_open_interest_change",
        "receiving_open_interest_change",
        "main_long_change",
        "main_short_change",
        "receiving_long_change",
        "receiving_short_change",
        "main_ranked_total_change",
        "receiving_ranked_total_change",
        "ranked_transfer_ratio",
        "roll_migration_state",
        "long_migration_state",
        "short_migration_state",
        "trading_instruction",
    ]
    return pd.DataFrame(rows, columns=columns)


def _build_historical_validation(
    *,
    daily: pd.DataFrame,
    validation_path: Path | None,
    horizons: tuple[int, ...],
    min_sample_size: int,
    end: date,
    run_id: str,
) -> pd.DataFrame:
    columns = [
        "run_id",
        "member_flow_state",
        "price_member_relation",
        "horizon",
        "sample_count",
        "directional_hit_rate",
        "mean_directional_forward_return",
        "median_directional_forward_return",
        "evidence_level",
        "forward_returns_are_historical_posterior_labels",
        "trading_instruction",
    ]
    if validation_path is None or not validation_path.exists():
        return pd.DataFrame(columns=columns)
    validation = load_table(
        validation_path,
        required={
            "trade_date",
            "main_contract",
            "horizon",
            "forward_return",
            "forward_label_available",
        },
        label="R36 validation daily",
    )
    validation = normalize_trade_date(validation)
    validation = validation.loc[
        validation["trade_date"].le(end)
        & validation["horizon"].isin(horizons)
        & validation["forward_label_available"].fillna(False).astype(bool)
    ].copy()
    main = daily.loc[
        daily["scope_type"].eq("contract")
        & daily["top_n"].eq(20)
        & daily["member_direction"].isin(["long", "short"])
    ].copy()
    joined = validation.merge(
        main[
            [
                "trade_date",
                "scope_code",
                "member_direction",
                "member_flow_state",
                "price_member_relation",
            ]
        ],
        left_on=["trade_date", "main_contract"],
        right_on=["trade_date", "scope_code"],
        how="inner",
    )
    if joined.empty:
        return pd.DataFrame(columns=columns)
    joined["forward_return"] = pd.to_numeric(joined["forward_return"], errors="coerce")
    joined["direction_sign"] = joined["member_direction"].map({"long": 1.0, "short": -1.0})
    joined["directional_forward_return"] = (
        joined["forward_return"] * joined["direction_sign"]
    )
    rows: list[dict[str, object]] = []
    for keys, group in joined.groupby(
        ["member_flow_state", "price_member_relation", "horizon"]
    ):
        flow_state, relation, horizon = keys
        values = group["directional_forward_return"].dropna()
        sample_count = len(values)
        rows.append(
            {
                "run_id": run_id,
                "member_flow_state": str(flow_state),
                "price_member_relation": str(relation),
                "horizon": int(horizon),
                "sample_count": sample_count,
                "directional_hit_rate": None if values.empty else float(values.gt(0).mean()),
                "mean_directional_forward_return": None if values.empty else float(values.mean()),
                "median_directional_forward_return": (
                    None if values.empty else float(values.median())
                ),
                "evidence_level": _evidence_level(sample_count, min_sample_size),
                "forward_returns_are_historical_posterior_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["horizon", "sample_count"], ascending=[True, False]
    ).reset_index(drop=True)


def _member_direction(
    *, top_net_change: float, denominator: float | None, dead_zone: float
) -> str:
    threshold = max(1.0, (denominator or 0.0) * dead_zone)
    if top_net_change > threshold:
        return "long"
    if top_net_change < -threshold:
        return "short"
    return "neutral"


def _member_flow_state(
    *, long_change: float, short_change: float, denominator: float | None, dead_zone: float
) -> str:
    threshold = max(1.0, (denominator or 0.0) * dead_zone)
    long_sign = 1 if long_change > threshold else -1 if long_change < -threshold else 0
    short_sign = 1 if short_change > threshold else -1 if short_change < -threshold else 0
    mapping = {
        (1, -1): "LONG_STRENGTHENING",
        (-1, 1): "SHORT_STRENGTHENING",
        (1, 1): "DUAL_BUILD",
        (-1, -1): "DUAL_REDUCTION",
        (0, 0): "FLOW_NEUTRAL",
    }
    return mapping.get((long_sign, short_sign), "ONE_SIDE_CHANGE")


def _price_member_relation(
    *, settle_return: float | None, member_direction: str, price_dead_zone: float
) -> str:
    if settle_return is None or abs(settle_return) <= price_dead_zone:
        return "PRICE_NEUTRAL"
    price_direction = "long" if settle_return > 0 else "short"
    if member_direction == "neutral":
        return f"PRICE_{price_direction.upper()}_MEMBER_NEUTRAL"
    if price_direction == member_direction:
        return f"ALIGNED_{price_direction.upper()}"
    return f"DIVERGENCE_PRICE_{price_direction.upper()}_MEMBER_{member_direction.upper()}"


def _oi_member_relation(
    *, oi_change: float | None, long_change: float, short_change: float
) -> str:
    if oi_change is None:
        return "OI_CHANGE_UNAVAILABLE"
    ranked_total_change = long_change + short_change
    if oi_change > 0 and ranked_total_change > 0:
        return "OI_AND_RANKED_POSITION_BUILD"
    if oi_change < 0 and ranked_total_change < 0:
        return "OI_AND_RANKED_POSITION_REDUCE"
    if oi_change > 0 and ranked_total_change < 0:
        return "DIVERGENCE_OI_BUILD_RANKED_REDUCE"
    if oi_change < 0 and ranked_total_change > 0:
        return "DIVERGENCE_OI_REDUCE_RANKED_BUILD"
    return "OI_MEMBER_MIXED"


def _roll_state(main_change: float, receiving_change: float) -> str:
    if main_change < 0 < receiving_change:
        return "ROLL_MIGRATION"
    if main_change < 0 and receiving_change <= 0:
        return "ROLL_WITH_NET_EXIT"
    if main_change >= 0 and receiving_change > 0:
        return "DUAL_CONTRACT_BUILD"
    return "MIXED_OR_REVERSE_MIGRATION"


def _side_migration_state(main_change: float, receiving_change: float) -> str:
    if main_change < 0 < receiving_change:
        return "MIGRATING"
    if main_change < 0 and receiving_change <= 0:
        return "NET_REDUCTION"
    if main_change >= 0 and receiving_change > 0:
        return "DUAL_BUILD"
    return "MIXED"


def _evidence_level(sample_count: int, min_sample_size: int) -> str:
    if sample_count >= max(100, min_sample_size * 3):
        return "READY"
    if sample_count >= min_sample_size:
        return "WATCH"
    return "WEAK_OR_SMALL_SAMPLE"


def _safe_ratio(numerator: float, denominator: float | None) -> float | None:
    if denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _warning_rows(
    *,
    member: pd.DataFrame,
    daily: pd.DataFrame,
    validation: pd.DataFrame,
    history_date_count: int,
    min_history_days: int,
    run_id: str,
) -> list[dict[str, object]]:
    partial_count = int(
        member["data_quality_flag"].astype(str).ne("normal").sum()
    )
    contract_count = int(daily.loc[daily["scope_type"].eq("contract"), "scope_code"].nunique())
    return [
        {
            "run_id": run_id,
            "section": "history_coverage",
            "severity": "WARN" if history_date_count < min_history_days else "INFO",
            "warning_code": (
                "MISSING_MEMBER_POSITION_HISTORY"
                if history_date_count < min_history_days
                else "MEMBER_POSITION_HISTORY_READY"
            ),
            "warning_message": "会员持仓历史交易日不足，当前结果只能作为结构观察。",
            "affected_count": max(0, min_history_days - history_date_count),
            "human_review_required": "historical_member_position_coverage",
        },
        {
            "run_id": run_id,
            "section": "contract_scope",
            "severity": "WARN" if contract_count == 0 else "INFO",
            "warning_code": "MISSING_CONTRACT_MEMBER_POSITION",
            "warning_message": "未识别到 CF 分合约会员排名，不能研究移仓迁移。",
            "affected_count": 1 if contract_count == 0 else 0,
            "human_review_required": "official_member_position_field_interpretation",
        },
        {
            "run_id": run_id,
            "section": "ranking_coverage",
            "severity": "WARN" if partial_count else "INFO",
            "warning_code": "PARTIAL_MEMBER_RANKING",
            "warning_message": "部分区块不足 Top20，集中度已保留质量标记。",
            "affected_count": partial_count,
            "human_review_required": "",
        },
        {
            "run_id": run_id,
            "section": "historical_validation",
            "severity": "WARN" if validation.empty else "INFO",
            "warning_code": "MEMBER_POSITION_FORWARD_LABEL_MISSING",
            "warning_message": "尚无可匹配的历史后验收益标签，不能声明方向有效性。",
            "affected_count": 1 if validation.empty else 0,
            "human_review_required": "historical_forward_label_interpretation",
        },
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "MEMBER_RANKING_NOT_CUSTOMER_NET_EXPOSURE",
            "warning_message": "会员排名可能包含代客汇总，不等同于客户或机构真实净敞口。",
            "affected_count": len(member),
            "human_review_required": "member_position_is_member_level_not_customer_identity",
        },
    ]


def _optional_validation_path() -> Path | None:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    candidates = list(root.glob("CF_*_signal_matrix_validation_daily.parquet"))
    return None if not candidates else max(candidates, key=lambda path: path.stat().st_mtime)


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_output_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_member_position"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "member_position"
    report_root = report_output_dir or reports_dir() / "research" / "member_position"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "member_detail_parquet": data_root / f"{stem}_member_detail.parquet",
        "member_detail_csv": data_root / f"{stem}_member_detail.csv",
        "roll_parquet": data_root / f"{stem}_roll_migration.parquet",
        "roll_csv": data_root / f"{stem}_roll_migration.csv",
        "validation_parquet": data_root / f"{stem}_validation.parquet",
        "validation_csv": data_root / f"{stem}_validation.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
        "manifest": report_root / f"{stem}_manifest.json",
    }


def _latest_main_summary(
    daily: pd.DataFrame, quote_product: pd.DataFrame, end: date
) -> dict[str, object] | None:
    product = quote_product.loc[quote_product["trade_date"].eq(end)]
    if product.empty:
        return None
    main_contract = str(product.iloc[0]["main_contract"])
    selected = daily.loc[
        daily["trade_date"].eq(end)
        & daily["scope_type"].eq("contract")
        & daily["scope_code"].eq(main_contract)
        & daily["top_n"].eq(20)
    ]
    return None if selected.empty else selected.iloc[0].to_dict()


def _write_markdown(
    *,
    result: ResearchMemberPositionResult,
    daily: pd.DataFrame,
    member_detail: pd.DataFrame,
    roll: pd.DataFrame,
    validation: pd.DataFrame,
    warnings: list[dict[str, object]],
) -> None:
    latest = daily.loc[daily["trade_date"].eq(result.end)].copy()
    main = latest.loc[
        latest["scope_type"].eq("contract")
        & latest["scope_code"].eq(result.latest_main_contract)
        & latest["top_n"].eq(20)
    ]
    lines = [
        "# CF 会员持仓集中度与多空变化研究",
        "",
        "## 数据状态",
        "",
        f"- 样本区间：`{result.start}` 至 `{result.end}`",
        f"- 会员持仓交易日：`{result.history_date_count}`",
        f"- 最新主力合约：`{result.latest_main_contract or 'not_available'}`",
        f"- 最新 Top20 席位方向：`{result.latest_member_direction}`",
        f"- 历史后验分组：`{result.validation_row_count}`",
        "",
        "## 最新主力结构",
        "",
    ]
    if main.empty:
        lines.append("当前没有可匹配的主力合约会员持仓结构。")
    else:
        row = main.iloc[0]
        lines.extend(
            [
                f"- Top20 持买仓：`{fmt_number(row['long_position'], 0)}`，"
                f"日变化 `{fmt_number(row['long_change'], 0)}`。",
                f"- Top20 持卖仓：`{fmt_number(row['short_position'], 0)}`，"
                f"日变化 `{fmt_number(row['short_change'], 0)}`。",
                f"- Top20 净持仓：`{fmt_number(row['top_net_position'], 0)}`，"
                f"净变化 `{fmt_number(row['top_net_change'], 0)}`。",
                f"- 多头集中度：`{fmt_percent(row['long_concentration'])}`；"
                f"空头集中度：`{fmt_percent(row['short_concentration'])}`。",
                f"- 席位变化状态：`{row['member_flow_state']}`；"
                f"价格关系：`{row['price_member_relation']}`。",
                f"- OI 关系：`{row['oi_member_relation']}`。",
            ]
        )
    lines.extend(["", "## 主要会员变化", ""])
    current_members = member_detail.loc[
        member_detail["trade_date"].eq(result.end)
        & member_detail["scope_code"].eq(result.latest_main_contract)
    ].copy()
    if current_members.empty:
        lines.append("无可用的主力合约会员明细。")
    else:
        current_members["abs_net_change"] = current_members["net_change"].abs()
        lines.extend(
            [
                "| 会员 | 多仓 | 空仓 | 净持仓 | 净变化 |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in current_members.nlargest(10, "abs_net_change").itertuples(index=False):
            lines.append(
                f"| {row.member_name} | {fmt_number(row.long_position, 0)} | "
                f"{fmt_number(row.short_position, 0)} | {fmt_number(row.net_position, 0)} | "
                f"{fmt_number(row.net_change, 0)} |"
            )
    lines.extend(["", "## 移仓迁移", ""])
    current_roll = roll.loc[roll["trade_date"].eq(result.end)]
    if current_roll.empty:
        lines.append("当前不足两个可比较合约，暂不能分解移仓。")
    else:
        row = current_roll.iloc[0]
        lines.extend(
            [
                f"- 比较合约：`{row['main_contract']}` -> `{row['receiving_contract']}`。",
                f"- 总体状态：`{row['roll_migration_state']}`。",
                f"- 多头迁移：`{row['long_migration_state']}`；"
                f"空头迁移：`{row['short_migration_state']}`。",
                f"- 排名持仓转移比例：`{fmt_percent(row['ranked_transfer_ratio'])}`。",
            ]
        )
    lines.extend(["", "## 历史后验验证", ""])
    if validation.empty:
        lines.append(
            "当前会员持仓历史不足，或尚未匹配到 forward return；不能用单日结构声明历史有效性。"
        )
    else:
        lines.extend(
            [
                "| 席位变化 | 价格关系 | 周期 | 样本 | 命中率 | 平均方向收益 | 证据 |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in validation.head(15).itertuples(index=False):
            lines.append(
                f"| {row.member_flow_state} | {row.price_member_relation} | {row.horizon}D | "
                f"{row.sample_count} | {fmt_percent(row.directional_hit_rate)} | "
                f"{fmt_percent(row.mean_directional_forward_return)} | {row.evidence_level} |"
            )
    lines.extend(["", "## 告警与缺口", ""])
    for warning in warnings:
        if warning["severity"] == "WARN":
            lines.append(
                f"- `{warning['warning_code']}`：{warning['warning_message']}"
            )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 会员排名可能包含代客汇总，不等同于客户或机构真实净敞口。",
            "- 总持仓量本身没有多空方向；方向来自持买/持卖排名变化的研究口径。",
            "- forward return 仅作为历史后验验证标签，不进入最新日结构计算。",
            "- 本模块不修改 composite_score，不自动反转方向，不构成交易指令。",
            "- `HUMAN_REVIEW_REQUIRED` 保留，但不阻断格式稳定时的正常日常提取。",
            "",
            "## HUMAN_REVIEW_REQUIRED",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in HUMAN_REVIEW_REQUIRED)
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
