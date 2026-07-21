"""R80/R81 CF option volatility, term structure and expiry quality research."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.option_expiry_registry import (
    OFFICIAL_RULE_TEXT_CN,
    default_option_expiry_registry_path,
    load_option_expiry_registry,
    resolve_option_expiry,
)
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    fmt_percent,
    latest_matching_path,
    load_table,
    main_contract_rows,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
RULE_VERSION = "R81_official_option_expiry_registry_v1"
DEFAULT_RISK_FREE_RATE = 0.02
DEFAULT_RV_WINDOW = 20
DEFAULT_IV_RANK_WINDOW = 252
DEFAULT_HORIZONS = (5, 10, 20)
DEFAULT_MIN_SAMPLE_SIZE = 30
RESEARCH_BOUNDARY = {
    "american_option_model": "Black-76 European approximation",
    "expiry_date_rule": (
        "explicit official expiry registry with visible month-start fallback"
    ),
    "forward_labels_are_historical_posterior_only": True,
    "latest_state_uses_future_data": False,
    "enters_composite_score": False,
    "trading_instruction": "not_a_trading_instruction",
}
HUMAN_REVIEW_REQUIRED = (
    "american_option_early_exercise_premium",
    "option_expiry_registry_coverage_and_future_calendar",
    "risk_free_rate_assumption",
    "realized_volatility_window",
    "iv_rv_state_thresholds",
    "option_liquidity_and_parity_filters",
)
FACTOR_REQUIRED_COLUMNS = {
    "trade_date",
    "underlying_contract",
    "underlying_settle",
    "atm_strike",
    "atm_call_settle",
    "atm_put_settle",
    "atm_iv_rank",
    "pcr_volume",
    "pcr_oi",
    "skew_proxy",
    "option_liquidity_score",
    "factor_status",
}
CORE_REQUIRED_COLUMNS = {
    "trade_date",
    "contract_code",
    "settle",
    "open_interest",
    "volume",
}


@dataclass(frozen=True)
class ResearchOptionVolatilityTermStructureResult:
    """R80/R81 output contract."""

    run_id: str
    start: date
    end: date
    contract_row_count: int
    curve_row_count: int
    validation_row_count: int
    latest_main_contract: str | None
    latest_atm_iv: float | None
    latest_rv: float | None
    latest_iv_rv_spread: float | None
    latest_volatility_state: str | None
    latest_term_structure_state: str | None
    latest_option_expiry_date: date | None
    latest_expiry_date_source: str | None
    expiry_registry_row_count: int
    expiry_fallback_row_count: int
    warning_count: int
    option_expiry_path: Path
    contract_parquet_path: Path
    curve_parquet_path: Path
    validation_parquet_path: Path
    validation_summary_parquet_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path

    def to_summary(self) -> dict[str, object]:
        """Return compact CLI output."""
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "contract_row_count": self.contract_row_count,
            "curve_row_count": self.curve_row_count,
            "validation_row_count": self.validation_row_count,
            "latest_main_contract": self.latest_main_contract,
            "latest_atm_iv": self.latest_atm_iv,
            "latest_rv": self.latest_rv,
            "latest_iv_rv_spread": self.latest_iv_rv_spread,
            "latest_volatility_state": self.latest_volatility_state,
            "latest_term_structure_state": self.latest_term_structure_state,
            "latest_option_expiry_date": (
                None
                if self.latest_option_expiry_date is None
                else self.latest_option_expiry_date.isoformat()
            ),
            "latest_expiry_date_source": self.latest_expiry_date_source,
            "expiry_registry_row_count": self.expiry_registry_row_count,
            "expiry_fallback_row_count": self.expiry_fallback_row_count,
            "warning_count": self.warning_count,
            "option_expiry_path": str(self.option_expiry_path),
            "contract_parquet_path": str(self.contract_parquet_path),
            "curve_parquet_path": str(self.curve_parquet_path),
            "validation_parquet_path": str(self.validation_parquet_path),
            "validation_summary_parquet_path": str(
                self.validation_summary_parquet_path
            ),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_option_volatility_term_structure_research(
    *,
    option_factor_path: Path | None = None,
    core_quote_path: Path | None = None,
    option_expiry_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    rv_window: int = DEFAULT_RV_WINDOW,
    iv_rank_window: int = DEFAULT_IV_RANK_WINDOW,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> ResearchOptionVolatilityTermStructureResult:
    """Build expiry-aware IV/RV, term structure and posterior volatility evidence."""
    if risk_free_rate < 0:
        raise ResearchWorkbenchError("risk_free_rate must be non-negative")
    if rv_window < 2 or iv_rank_window < 2:
        raise ResearchWorkbenchError("rv_window and iv_rank_window must be at least 2")
    if not horizons or any(value <= 0 for value in horizons):
        raise ResearchWorkbenchError("horizons must contain positive integers")
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("min_sample_size must be positive")
    factor_path = option_factor_path or latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "option_factors",
        "*_option_factor_proxy_daily.parquet",
        label="R48 option factor table",
    )
    quote_path = (
        core_quote_path
        or data_dir() / "core" / PRODUCT_CODE / "core_quote_daily.parquet"
    )
    expiry_path = option_expiry_path or default_option_expiry_registry_path()
    factors = load_table(
        factor_path,
        required=FACTOR_REQUIRED_COLUMNS,
        label="R48 option factor table",
    )
    quotes = load_table(
        quote_path,
        required=CORE_REQUIRED_COLUMNS,
        label="CF core quote table",
    )
    factors = normalize_trade_date(factors)
    quotes = normalize_trade_date(quotes)
    expiry_registry = load_option_expiry_registry(expiry_path)
    start = min(factors["trade_date"])
    end = max(factors["trade_date"])
    active_run_id = run_id or utc_timestamp_id("r80", end)
    rv = _realized_volatility(quotes=quotes, rv_window=rv_window)
    contract_daily = _contract_volatility_rows(
        factors=factors,
        rv=rv,
        run_id=active_run_id,
        risk_free_rate=risk_free_rate,
        iv_rank_window=iv_rank_window,
        expiry_registry=expiry_registry,
    )
    curve_daily = _curve_rows(
        contract_daily=contract_daily,
        quotes=quotes,
        run_id=active_run_id,
    )
    validation = _validation_rows(
        curve_daily=curve_daily,
        quotes=quotes,
        horizons=tuple(sorted(set(horizons))),
        run_id=active_run_id,
    )
    validation_summary = _validation_summary(
        validation=validation,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
    )
    warnings = _warning_rows(
        contract_daily=contract_daily,
        curve_daily=curve_daily,
        validation_summary=validation_summary,
        run_id=active_run_id,
        min_sample_size=min_sample_size,
    )
    paths = _output_paths(
        start=start,
        end=end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    write_frame(contract_daily, paths["contract_parquet"], paths["contract_csv"])
    write_frame(curve_daily, paths["curve_parquet"], paths["curve_csv"])
    write_frame(validation, paths["validation_parquet"], paths["validation_csv"])
    write_frame(
        validation_summary,
        paths["validation_summary_parquet"],
        paths["validation_summary_csv"],
    )
    write_warning_csv(paths["warning_csv"], warnings)
    latest = curve_daily.sort_values("trade_date").iloc[-1].to_dict()
    warning_count = sum(1 for row in warnings if row["severity"] == "WARN")
    result = ResearchOptionVolatilityTermStructureResult(
        run_id=active_run_id,
        start=start,
        end=end,
        contract_row_count=len(contract_daily),
        curve_row_count=len(curve_daily),
        validation_row_count=len(validation),
        latest_main_contract=_str_or_none(latest.get("main_contract")),
        latest_atm_iv=_float_or_none(latest.get("main_atm_iv_approx")),
        latest_rv=_float_or_none(latest.get("main_rv")),
        latest_iv_rv_spread=_float_or_none(latest.get("main_iv_rv_spread")),
        latest_volatility_state=_str_or_none(latest.get("volatility_state")),
        latest_term_structure_state=_str_or_none(latest.get("term_structure_state")),
        latest_option_expiry_date=_date_or_none(
            latest.get("main_option_expiry_date")
        ),
        latest_expiry_date_source=_str_or_none(
            latest.get("main_expiry_date_source")
        ),
        expiry_registry_row_count=int(
            (contract_daily["expiry_date_source"] == "EXPLICIT_EXPIRY_REGISTRY").sum()
        ),
        expiry_fallback_row_count=int(
            (
                contract_daily["expiry_date_source"]
                == "MONTH_START_PROXY_FALLBACK"
            ).sum()
        ),
        warning_count=warning_count,
        option_expiry_path=expiry_path,
        contract_parquet_path=paths["contract_parquet"],
        curve_parquet_path=paths["curve_parquet"],
        validation_parquet_path=paths["validation_parquet"],
        validation_summary_parquet_path=paths["validation_summary_parquet"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
    )
    _write_markdown(
        path=paths["markdown"],
        result=result,
        latest=latest,
        contract_daily=contract_daily,
        validation_summary=validation_summary,
    )
    write_json(
        paths["json"],
        {
            **result.to_summary(),
            "latest_curve": latest,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        paths["manifest"],
        artifact_manifest(
            run_id=active_run_id,
            report_type="option_volatility_term_structure",
            rule_version=RULE_VERSION,
            data_asof=end,
            input_paths={
                "option_factor_path": factor_path,
                "core_quote_path": quote_path,
                "option_expiry_path": expiry_path,
            },
            output_paths={
                "contract_parquet_path": paths["contract_parquet"],
                "curve_parquet_path": paths["curve_parquet"],
                "validation_parquet_path": paths["validation_parquet"],
                "validation_summary_parquet_path": paths[
                    "validation_summary_parquet"
                ],
                "warning_csv_path": paths["warning_csv"],
                "markdown_path": paths["markdown"],
                "json_path": paths["json"],
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _realized_volatility(*, quotes: pd.DataFrame, rv_window: int) -> pd.DataFrame:
    working = quotes[["trade_date", "contract_code", "settle"]].copy()
    working["settle"] = pd.to_numeric(working["settle"], errors="coerce")
    working = working.dropna(subset=["settle"]).sort_values(
        ["contract_code", "trade_date"]
    )
    working["log_return"] = working.groupby("contract_code")["settle"].transform(
        lambda values: values.map(math.log).diff()
    )
    min_periods = max(5, rv_window // 2)
    working["realized_volatility"] = working.groupby("contract_code")[
        "log_return"
    ].transform(
        lambda values: values.rolling(rv_window, min_periods=min_periods).std()
        * math.sqrt(252.0)
    )
    return working.rename(columns={"contract_code": "underlying_contract"})[
        ["trade_date", "underlying_contract", "realized_volatility"]
    ]


def _contract_volatility_rows(
    *,
    factors: pd.DataFrame,
    rv: pd.DataFrame,
    run_id: str,
    risk_free_rate: float,
    iv_rank_window: int,
    expiry_registry: pd.DataFrame,
) -> pd.DataFrame:
    merged = factors.merge(
        rv,
        how="left",
        on=["trade_date", "underlying_contract"],
        validate="one_to_one",
    )
    rows: list[dict[str, object]] = []
    for row in merged.itertuples(index=False):
        futures_price = _float_or_none(row.underlying_settle)
        strike = _float_or_none(row.atm_strike)
        call_price = _float_or_none(row.atm_call_settle)
        put_price = _float_or_none(row.atm_put_settle)
        expiry = resolve_option_expiry(
            underlying_contract=str(row.underlying_contract),
            trade_date=row.trade_date,
            registry=expiry_registry,
        )
        days_to_expiry = expiry.days_to_expiry
        time_to_expiry = days_to_expiry / 365.0
        call_iv = _implied_volatility_bisection(
            option_price=call_price,
            futures_price=futures_price,
            strike=strike,
            time_to_expiry=time_to_expiry,
            risk_free_rate=risk_free_rate,
            option_type="C",
        )
        put_iv = _implied_volatility_bisection(
            option_price=put_price,
            futures_price=futures_price,
            strike=strike,
            time_to_expiry=time_to_expiry,
            risk_free_rate=risk_free_rate,
            option_type="P",
        )
        valid_ivs = [value for value in (call_iv, put_iv) if value is not None]
        atm_iv = None if not valid_ivs else sum(valid_ivs) / len(valid_ivs)
        rv_value = _float_or_none(row.realized_volatility)
        iv_rv_spread = None if atm_iv is None or rv_value is None else atm_iv - rv_value
        iv_rv_ratio = _safe_ratio(atm_iv, rv_value)
        parity_residual = _parity_residual(
            call_price=call_price,
            put_price=put_price,
            futures_price=futures_price,
            strike=strike,
            time_to_expiry=time_to_expiry,
            risk_free_rate=risk_free_rate,
        )
        parity_residual_bps = _safe_ratio(parity_residual, futures_price)
        if parity_residual_bps is not None:
            parity_residual_bps *= 10000.0
        flags = ["AMERICAN_OPTION_BLACK76_APPROX", *expiry.risk_flags]
        if atm_iv is None:
            flags.append("IV_SOLVE_FAILED")
        if rv_value is None:
            flags.append("RV_HISTORY_INSUFFICIENT")
        if parity_residual_bps is not None and abs(parity_residual_bps) > 100:
            flags.append("PUT_CALL_PARITY_DEVIATION")
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "trade_date": row.trade_date,
                "underlying_contract": str(row.underlying_contract),
                "underlying_settle": futures_price,
                "atm_strike": strike,
                "atm_call_settle": call_price,
                "atm_put_settle": put_price,
                "option_expiry_date": expiry.option_expiry_date,
                "days_to_expiry": days_to_expiry,
                "expiry_date_source": expiry.expiry_date_source,
                "expiry_rule_code": expiry.expiry_rule_code,
                "expiry_quality_flag": expiry.expiry_quality_flag,
                "expiry_source_name": expiry.expiry_source_name,
                "expiry_source_url": expiry.expiry_source_url,
                "expiry_human_review_required": (
                    expiry.expiry_human_review_required
                ),
                # 兼容 R80 既有产物字段；值已切换为实际解析结果，不再必然是代理。
                "expiry_date_proxy": expiry.option_expiry_date,
                "days_to_expiry_proxy": days_to_expiry,
                "time_to_expiry_years": time_to_expiry,
                "risk_free_rate": risk_free_rate,
                "black76_call_iv_approx": call_iv,
                "black76_put_iv_approx": put_iv,
                "atm_iv_approx": atm_iv,
                "atm_iv_rank_approx": None,
                "legacy_atm_iv_rank": _float_or_none(row.atm_iv_rank),
                "realized_volatility": rv_value,
                "iv_rv_spread": iv_rv_spread,
                "iv_rv_ratio": iv_rv_ratio,
                "put_call_parity_residual": parity_residual,
                "put_call_parity_residual_bps": parity_residual_bps,
                "pcr_volume": _float_or_none(row.pcr_volume),
                "pcr_oi": _float_or_none(row.pcr_oi),
                "skew_proxy": _float_or_none(row.skew_proxy),
                "option_liquidity_score": _float_or_none(row.option_liquidity_score),
                "factor_status": str(row.factor_status),
                "pricing_status": "READY" if atm_iv is not None else "NOT_PRICED",
                "risk_flags": ";".join(flags),
                "rule_version": RULE_VERSION,
            }
        )
    frame = pd.DataFrame(rows).sort_values(["underlying_contract", "trade_date"])
    frame["atm_iv_rank_approx"] = _rolling_rank(
        frame=frame,
        value_column="atm_iv_approx",
        group_column="underlying_contract",
        window=iv_rank_window,
    )
    return frame.sort_values(["trade_date", "days_to_expiry", "underlying_contract"])


def _curve_rows(
    *, contract_daily: pd.DataFrame, quotes: pd.DataFrame, run_id: str
) -> pd.DataFrame:
    main = main_contract_rows(quotes)[["trade_date", "contract_code"]].rename(
        columns={"contract_code": "main_contract"}
    )
    rows: list[dict[str, object]] = []
    main_by_date = dict(zip(main["trade_date"], main["main_contract"], strict=False))
    for trade_date_value, group in contract_daily.groupby("trade_date", sort=True):
        valid = group.loc[group["atm_iv_approx"].notna()].sort_values(
            ["days_to_expiry", "underlying_contract"]
        )
        front = valid.iloc[0] if not valid.empty else None
        second = valid.iloc[1] if len(valid) > 1 else None
        main_contract = str(main_by_date.get(trade_date_value, ""))
        main_match = group.loc[group["underlying_contract"] == main_contract]
        main_row = main_match.iloc[0] if not main_match.empty else None
        main_iv = None if main_row is None else _float_or_none(main_row["atm_iv_approx"])
        main_rv = (
            None if main_row is None else _float_or_none(main_row["realized_volatility"])
        )
        main_rank = (
            None if main_row is None else _float_or_none(main_row["atm_iv_rank_approx"])
        )
        main_spread = None if main_row is None else _float_or_none(main_row["iv_rv_spread"])
        front_iv = None if front is None else _float_or_none(front["atm_iv_approx"])
        second_iv = None if second is None else _float_or_none(second["atm_iv_approx"])
        term_spread = None if front_iv is None or second_iv is None else front_iv - second_iv
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "trade_date": trade_date_value,
                "main_contract": main_contract,
                "main_atm_iv_approx": main_iv,
                "main_atm_iv_rank_approx": main_rank,
                "main_rv": main_rv,
                "main_iv_rv_spread": main_spread,
                "main_iv_rv_ratio": _safe_ratio(main_iv, main_rv),
                "main_days_to_expiry_proxy": (
                    None if main_row is None else main_row["days_to_expiry_proxy"]
                ),
                "main_option_expiry_date": (
                    None if main_row is None else main_row["option_expiry_date"]
                ),
                "main_days_to_expiry": (
                    None if main_row is None else main_row["days_to_expiry"]
                ),
                "main_expiry_date_source": (
                    None if main_row is None else main_row["expiry_date_source"]
                ),
                "main_expiry_quality_flag": (
                    None if main_row is None else main_row["expiry_quality_flag"]
                ),
                "main_expiry_human_review_required": (
                    None
                    if main_row is None
                    else bool(main_row["expiry_human_review_required"])
                ),
                "front_contract": None if front is None else front["underlying_contract"],
                "front_atm_iv_approx": front_iv,
                "front_days_to_expiry_proxy": (
                    None if front is None else front["days_to_expiry_proxy"]
                ),
                "second_contract": None if second is None else second["underlying_contract"],
                "second_atm_iv_approx": second_iv,
                "second_days_to_expiry_proxy": (
                    None if second is None else second["days_to_expiry_proxy"]
                ),
                "front_second_iv_spread": term_spread,
                "volatility_state": _volatility_state(
                    iv_rank=main_rank,
                    iv_rv_spread=main_spread,
                ),
                "term_structure_state": _term_structure_state(term_spread),
                "rule_version": RULE_VERSION,
            }
        )
    return pd.DataFrame(rows)


def _validation_rows(
    *,
    curve_daily: pd.DataFrame,
    quotes: pd.DataFrame,
    horizons: tuple[int, ...],
    run_id: str,
) -> pd.DataFrame:
    series_by_contract: dict[str, pd.DataFrame] = {}
    working = quotes[["trade_date", "contract_code", "settle"]].copy()
    working["settle"] = pd.to_numeric(working["settle"], errors="coerce")
    for contract, group in working.dropna(subset=["settle"]).groupby("contract_code"):
        series_by_contract[str(contract)] = group.sort_values("trade_date").reset_index(drop=True)
    rows: list[dict[str, object]] = []
    for curve in curve_daily.itertuples(index=False):
        contract = str(curve.main_contract)
        series = series_by_contract.get(contract)
        if series is None:
            continue
        matches = series.index[series["trade_date"] == curve.trade_date].tolist()
        if not matches:
            continue
        signal_index = matches[0]
        for horizon in horizons:
            execution_index = signal_index + 1
            exit_index = execution_index + horizon
            execution_date = None
            exit_date = None
            future_abs_return = None
            future_realized_volatility = None
            if exit_index < len(series):
                execution_price = float(series.iloc[execution_index]["settle"])
                exit_price = float(series.iloc[exit_index]["settle"])
                execution_date = series.iloc[execution_index]["trade_date"]
                exit_date = series.iloc[exit_index]["trade_date"]
                future_abs_return = abs(exit_price / execution_price - 1.0)
                window = series.iloc[execution_index : exit_index + 1]["settle"].astype(float)
                log_returns = window.map(math.log).diff().dropna()
                if len(log_returns) >= 2:
                    future_realized_volatility = float(
                        log_returns.std() * math.sqrt(252.0)
                    )
            rows.append(
                {
                    "run_id": run_id,
                    "product_code": PRODUCT_CODE,
                    "trade_date": curve.trade_date,
                    "main_contract": contract,
                    "horizon": horizon,
                    "execution_date": execution_date,
                    "exit_date": exit_date,
                    "volatility_state": curve.volatility_state,
                    "term_structure_state": curve.term_structure_state,
                    "main_atm_iv_approx": curve.main_atm_iv_approx,
                    "main_rv": curve.main_rv,
                    "main_iv_rv_spread": curve.main_iv_rv_spread,
                    "future_abs_return": future_abs_return,
                    "future_realized_volatility": future_realized_volatility,
                    "is_posterior_label_available": future_abs_return is not None,
                    "label_boundary": "T+1 execution; historical posterior only",
                    "rule_version": RULE_VERSION,
                }
            )
    return pd.DataFrame(rows)


def _validation_summary(
    *, validation: pd.DataFrame, run_id: str, min_sample_size: int
) -> pd.DataFrame:
    usable = validation.loc[validation["is_posterior_label_available"]].copy()
    rows: list[dict[str, object]] = []
    for keys, group in usable.groupby(
        ["volatility_state", "term_structure_state", "horizon"],
        dropna=False,
        sort=True,
    ):
        volatility_state, term_structure_state, horizon = keys
        sample_count = len(group)
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "volatility_state": volatility_state,
                "term_structure_state": term_structure_state,
                "horizon": int(horizon),
                "sample_count": sample_count,
                "avg_future_abs_return": _mean(group["future_abs_return"]),
                "median_future_abs_return": _median(group["future_abs_return"]),
                "avg_future_realized_volatility": _mean(
                    group["future_realized_volatility"]
                ),
                "median_future_realized_volatility": _median(
                    group["future_realized_volatility"]
                ),
                "evidence_level": _evidence_level(sample_count, min_sample_size),
                "rule_version": RULE_VERSION,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["horizon", "sample_count"], ascending=[True, False]
    )


def _warning_rows(
    *,
    contract_daily: pd.DataFrame,
    curve_daily: pd.DataFrame,
    validation_summary: pd.DataFrame,
    run_id: str,
    min_sample_size: int,
) -> list[dict[str, object]]:
    warnings = [
        _warning(
            run_id,
            "model_boundary",
            "INFO",
            "AMERICAN_OPTION_BLACK76_APPROX",
            "棉花期权为美式，本模块使用Black-76欧式近似生成可比IV序列。",
            len(contract_daily),
            "american_option_early_exercise_premium",
        ),
        _warning(
            run_id,
            "expiry_boundary",
            "INFO",
            "OFFICIAL_OPTION_EXPIRY_REGISTRY_ACTIVE",
            f"已按郑商所规则读取显式到期日登记表：{OFFICIAL_RULE_TEXT_CN}。",
            int(
                (
                    contract_daily["expiry_date_source"]
                    == "EXPLICIT_EXPIRY_REGISTRY"
                ).sum()
            ),
            "option_expiry_registry_coverage_and_future_calendar",
        ),
    ]
    fallback_rows = contract_daily.loc[
        contract_daily["expiry_date_source"] == "MONTH_START_PROXY_FALLBACK"
    ]
    if not fallback_rows.empty:
        fallback_contracts = ", ".join(
            sorted(fallback_rows["underlying_contract"].astype(str).unique())
        )
        warnings.append(
            _warning(
                run_id,
                "expiry_boundary",
                "WARN",
                "EXPIRY_DATE_MONTH_START_FALLBACK",
                "未被到期登记表覆盖的合约继续使用月初代理："
                f"{fallback_contracts}；不得视为官方到期日。",
                len(fallback_rows),
                "option_expiry_registry_coverage_and_future_calendar",
            )
        )
    failed_count = int((contract_daily["pricing_status"] != "READY").sum())
    if failed_count:
        warnings.append(
            _warning(
                run_id,
                "pricing",
                "WARN",
                "OPTION_IV_SOLVE_FAILED",
                "部分合约日无法得到Black-76近似IV。",
                failed_count,
                "option_liquidity_and_parity_filters",
            )
        )
    if curve_daily.iloc[-1]["main_atm_iv_approx"] is None or pd.isna(
        curve_daily.iloc[-1]["main_atm_iv_approx"]
    ):
        warnings.append(
            _warning(
                run_id,
                "latest_state",
                "WARN",
                "LATEST_MAIN_OPTION_IV_MISSING",
                "最新主力合约缺少可用近似IV。",
                1,
                "option_liquidity_and_parity_filters",
            )
        )
    small_groups = int(
        (validation_summary["sample_count"] < min_sample_size).sum()
    ) if not validation_summary.empty else 0
    if small_groups:
        warnings.append(
            _warning(
                run_id,
                "posterior_validation",
                "INFO",
                "SMALL_OPTION_VOLATILITY_NODES",
                "部分IV/RV与期限结构节点样本不足，只能作为弱证据。",
                small_groups,
                "iv_rv_state_thresholds",
            )
        )
    return warnings


def _warning(
    run_id: str,
    section: str,
    severity: str,
    code: str,
    message: str,
    count: int,
    review: str,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "section": section,
        "severity": severity,
        "warning_code": code,
        "warning_message": message,
        "affected_count": count,
        "human_review_required": review,
    }


def _write_markdown(
    *,
    path: Path,
    result: ResearchOptionVolatilityTermStructureResult,
    latest: dict[str, object],
    contract_daily: pd.DataFrame,
    validation_summary: pd.DataFrame,
) -> None:
    latest_contracts = contract_daily.loc[
        contract_daily["trade_date"] == result.end
    ].sort_values("days_to_expiry")
    lines = [
        f"# CF 期权波动率与期限结构研究 R80/R81 - {result.end.isoformat()}",
        "",
        "## 模型边界",
        "",
        "- 棉花期权为美式；本模块使用Black-76欧式近似，不是精确美式IV/Greek。",
        f"- 到期日优先读取显式登记表；郑商所规则为：{OFFICIAL_RULE_TEXT_CN}。",
        "- 未覆盖合约才使用月初代理，报告与 warning CSV 会强制标记回退。",
        "- 最新状态不读取未来收益；历史forward标签只用于后验波动验证。",
        "",
        "## 最新主力波动状态",
        "",
        f"- 主力合约：`{latest.get('main_contract')}`",
        f"- Black-76 ATM IV近似：`{fmt_percent(latest.get('main_atm_iv_approx'))}`",
        f"- ATM IV历史分位：`{fmt_percent(latest.get('main_atm_iv_rank_approx'))}`",
        f"- {DEFAULT_RV_WINDOW}日实现波动率：`{fmt_percent(latest.get('main_rv'))}`",
        f"- IV-RV差：`{fmt_percent(latest.get('main_iv_rv_spread'))}`",
        f"- IV/RV：`{fmt_number(latest.get('main_iv_rv_ratio'), 3)}`",
        f"- 波动状态：`{latest.get('volatility_state')}`",
        f"- 期限结构：`{latest.get('term_structure_state')}`",
        f"- 主力期权到期日：`{latest.get('main_option_expiry_date')}`",
        f"- 到期日来源：`{latest.get('main_expiry_date_source')}`",
        "",
        "## 最新合约月份",
        "",
        "| 标的 | 到期日 | 剩余天数 | 到期来源 | ATM IV近似 | IV分位 | RV | IV-RV | 状态 |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in latest_contracts.head(8).itertuples(index=False):
        lines.append(
            f"| {row.underlying_contract} | {row.option_expiry_date} | "
            f"{row.days_to_expiry} | {row.expiry_date_source} | "
            f"{fmt_percent(row.atm_iv_approx)} | {fmt_percent(row.atm_iv_rank_approx)} | "
            f"{fmt_percent(row.realized_volatility)} | {fmt_percent(row.iv_rv_spread)} | "
            f"{row.pricing_status} |"
        )
    lines.extend(
        [
            "",
            "## 历史后验验证",
            "",
            "| 波动状态 | 期限结构 | 周期 | 样本 | 平均绝对收益 | 未来实现波动 | 证据 |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in validation_summary.head(24).itertuples(index=False):
        lines.append(
            f"| {row.volatility_state} | {row.term_structure_state} | {row.horizon}D | "
            f"{row.sample_count} | {fmt_percent(row.avg_future_abs_return)} | "
            f"{fmt_percent(row.avg_future_realized_volatility)} | {row.evidence_level} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 近似IV用于横向比较和状态研究，不作为精确风险暴露。",
            "- IV低不自动等于即将突破，IV高也不自动等于方向反转。",
            "- 本模块不进入 `composite_score`，不自动生成期权交易策略。",
            "- T+1后验标签不进入最新日状态，不构成交易指令。",
            "- HUMAN_REVIEW_REQUIRED：美式溢价、未覆盖的未来到期日、利率、阈值和流动性。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _black76_price(
    *,
    futures_price: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,
) -> float:
    """Price a European futures option with Black-76."""
    discount = math.exp(-risk_free_rate * time_to_expiry)
    if time_to_expiry <= 0 or volatility <= 0:
        intrinsic = max(futures_price - strike, 0.0)
        if option_type == "P":
            intrinsic = max(strike - futures_price, 0.0)
        return discount * intrinsic
    sigma_sqrt_t = volatility * math.sqrt(time_to_expiry)
    d1 = (
        math.log(futures_price / strike)
        + 0.5 * volatility * volatility * time_to_expiry
    ) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    if option_type == "C":
        return discount * (
            futures_price * _normal_cdf(d1) - strike * _normal_cdf(d2)
        )
    return discount * (
        strike * _normal_cdf(-d2) - futures_price * _normal_cdf(-d1)
    )


def _implied_volatility_bisection(
    *,
    option_price: float | None,
    futures_price: float | None,
    strike: float | None,
    time_to_expiry: float,
    risk_free_rate: float,
    option_type: str,
) -> float | None:
    if (
        option_price is None
        or futures_price is None
        or strike is None
        or option_price <= 0
        or futures_price <= 0
        or strike <= 0
        or time_to_expiry <= 0
    ):
        return None
    intrinsic = _black76_price(
        futures_price=futures_price,
        strike=strike,
        time_to_expiry=time_to_expiry,
        risk_free_rate=risk_free_rate,
        volatility=1e-8,
        option_type=option_type,
    )
    maximum = math.exp(-risk_free_rate * time_to_expiry) * (
        futures_price if option_type == "C" else strike
    )
    if option_price < intrinsic - 1e-8 or option_price >= maximum:
        return None
    if abs(option_price - intrinsic) <= 1e-8:
        return 1e-8
    low = 1e-6
    high = 5.0
    high_price = _black76_price(
        futures_price=futures_price,
        strike=strike,
        time_to_expiry=time_to_expiry,
        risk_free_rate=risk_free_rate,
        volatility=high,
        option_type=option_type,
    )
    if high_price < option_price:
        return None
    for _ in range(80):
        mid = (low + high) / 2.0
        price = _black76_price(
            futures_price=futures_price,
            strike=strike,
            time_to_expiry=time_to_expiry,
            risk_free_rate=risk_free_rate,
            volatility=mid,
            option_type=option_type,
        )
        if abs(price - option_price) < 1e-8:
            return mid
        if price < option_price:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _parity_residual(
    *,
    call_price: float | None,
    put_price: float | None,
    futures_price: float | None,
    strike: float | None,
    time_to_expiry: float,
    risk_free_rate: float,
) -> float | None:
    if None in {call_price, put_price, futures_price, strike}:
        return None
    theoretical = math.exp(-risk_free_rate * time_to_expiry) * (
        float(futures_price) - float(strike)
    )
    return float(call_price) - float(put_price) - theoretical


def _rolling_rank(
    *, frame: pd.DataFrame, value_column: str, group_column: str, window: int
) -> list[float]:
    ranks = pd.Series(index=frame.index, dtype="float64")
    for _, group in frame.groupby(group_column, sort=False):
        values = pd.to_numeric(group[value_column], errors="coerce").tolist()
        group_ranks: list[float] = []
        for index, current in enumerate(values):
            if current is None or pd.isna(current):
                group_ranks.append(float("nan"))
                continue
            history = [
                value
                for value in values[max(0, index - window + 1) : index + 1]
                if value is not None and not pd.isna(value)
            ]
            group_ranks.append(
                float("nan")
                if len(history) < 2
                else sum(value <= current for value in history) / len(history)
            )
        ranks.loc[group.index] = group_ranks
    return ranks.tolist()


def _volatility_state(*, iv_rank: float | None, iv_rv_spread: float | None) -> str:
    if iv_rank is None:
        return "NOT_PRICED"
    if iv_rank <= 0.20 and iv_rv_spread is not None and iv_rv_spread <= 0:
        return "LOW_IV_DISCOUNT_COMPRESSION"
    if iv_rank <= 0.20:
        return "LOW_IV_PREMIUM_COMPRESSION"
    if iv_rank >= 0.80 and iv_rv_spread is not None and iv_rv_spread > 0:
        return "HIGH_IV_RISK_PREMIUM"
    if iv_rv_spread is not None and iv_rv_spread < 0:
        return "IV_BELOW_RV"
    return "NORMAL_VOLATILITY_PRICING"


def _term_structure_state(spread: float | None) -> str:
    if spread is None:
        return "TERM_STRUCTURE_NOT_AVAILABLE"
    if spread >= 0.03:
        return "FRONT_IV_PREMIUM"
    if spread <= -0.03:
        return "DEFERRED_IV_PREMIUM"
    return "FLAT_IV_TERM_STRUCTURE"


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _output_paths(
    *, start: date, end: date, output_dir: Path | None, report_output_dir: Path | None
) -> dict[str, Path]:
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "option_volatility"
    report_root = report_output_dir or reports_dir() / "research" / "option_volatility"
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_option_volatility"
    return {
        "contract_parquet": data_root / f"{stem}_contract_daily.parquet",
        "contract_csv": data_root / f"{stem}_contract_daily.csv",
        "curve_parquet": data_root / f"{stem}_curve_daily.parquet",
        "curve_csv": data_root / f"{stem}_curve_daily.csv",
        "validation_parquet": data_root / f"{stem}_validation_daily.parquet",
        "validation_csv": data_root / f"{stem}_validation_daily.csv",
        "validation_summary_parquet": data_root / f"{stem}_validation_summary.parquet",
        "validation_summary_csv": data_root / f"{stem}_validation_summary.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _evidence_level(sample_count: int, min_sample_size: int) -> str:
    if sample_count >= min_sample_size:
        return "READY"
    if sample_count >= max(10, min_sample_size // 2):
        return "WATCH"
    return "WEAK_OR_SMALL_SAMPLE"


def _mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.mean())


def _median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.median())


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _str_or_none(value: object) -> str | None:
    return None if value is None or pd.isna(value) else str(value)


def _date_or_none(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ResearchWorkbenchError(f"invalid option expiry date: {value}") from exc


def _float_or_none(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)
