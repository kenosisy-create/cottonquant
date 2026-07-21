"""R48 CF option factor proxy research outputs."""

from __future__ import annotations

import csv
import json
import math
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.option_data_contract import CORE_OPTION_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
OPTION_FACTOR_PROXY_VERSION = "R48_option_factor_proxy_v2"
OUTPUT_DIR = "option_factors"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
DEFAULT_IV_RANK_LOOKBACK_DAYS = 252
DEFAULT_ATM_MONEYNESS_BAND = 0.03
DEFAULT_OTM_MONEYNESS_MIN = 0.90
DEFAULT_OTM_MONEYNESS_MAX = 0.98
DISQUALIFYING_RISK_FLAGS = {
    "LOW_LIQUIDITY_VOLUME",
    "LOW_LIQUIDITY_OPEN_INTEREST",
    "DEEP_OTM_PROXY",
    "NEAR_EXPIRY_REVIEW",
    "UNDERLYING_PRICE_MISSING",
    "MISSING_SETTLE",
}
HUMAN_REVIEW_REQUIRED = (
    "american_option_iv_proxy_model_boundary",
    "official_option_field_interpretation",
    "option_liquidity_thresholds",
    "moneyness_and_skew_proxy_definition",
    "underlying_contract_mapping",
    "option_signal_filter_rules_before_trading_use",
)
OPTION_REQUIRED_COLUMNS = {
    "trade_date",
    "option_symbol",
    "underlying_contract",
    "option_type",
    "strike",
    "settle",
    "volume",
    "open_interest",
    "moneyness",
    "liquidity_flag",
    "data_quality_flag",
}
QUOTE_REQUIRED_COLUMNS = {"trade_date", "contract_code", "settle"}
WARNING_COLUMNS = [
    "run_id",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
]


@dataclass(frozen=True)
class OptionFactorProxyWarningRecord:
    """Warning row for R48 option factor proxy outputs."""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchOptionFactorProxyResult:
    """Result of R48 CF option factor proxy build."""

    product_code: str
    exchange: str
    run_id: str
    status: str
    build_mode: str
    start: date
    end: date
    option_row_count: int
    surface_row_count: int
    factor_row_count: int
    eligible_option_row_count: int
    excluded_option_row_count: int
    warning_records: tuple[OptionFactorProxyWarningRecord, ...]
    factor_parquet_path: Path
    factor_csv_path: Path
    surface_parquet_path: Path
    surface_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    option_core_path: Path
    core_quote_path: Path
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether R48 built usable factor proxy rows."""
        return self.status == "COMPLETED"

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "exchange": self.exchange,
            "run_id": self.run_id,
            "status": self.status,
            "build_mode": self.build_mode,
            "passed": self.passed,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "option_row_count": self.option_row_count,
            "surface_row_count": self.surface_row_count,
            "factor_row_count": self.factor_row_count,
            "eligible_option_row_count": self.eligible_option_row_count,
            "excluded_option_row_count": self.excluded_option_row_count,
            "warning_count": self.warning_count,
            "factor_parquet_path": str(self.factor_parquet_path),
            "factor_csv_path": str(self.factor_csv_path),
            "surface_parquet_path": str(self.surface_parquet_path),
            "surface_csv_path": str(self.surface_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "option_core_path": str(self.option_core_path),
            "core_quote_path": str(self.core_quote_path),
            "option_signal_status": "not_connected",
            "human_review_required": list(self.human_review_required),
        }


def build_cf_option_factor_proxy(
    *,
    option_core_path: Path | None = None,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    iv_rank_lookback_days: int = DEFAULT_IV_RANK_LOOKBACK_DAYS,
    atm_moneyness_band: float = DEFAULT_ATM_MONEYNESS_BAND,
    otm_moneyness_min: float = DEFAULT_OTM_MONEYNESS_MIN,
    otm_moneyness_max: float = DEFAULT_OTM_MONEYNESS_MAX,
    incremental: bool = False,
) -> ResearchOptionFactorProxyResult:
    """Build R48 option PCR/skew/ATM-volatility proxy factors from core tables."""
    if iv_rank_lookback_days <= 0:
        raise ResearchWorkbenchError("iv_rank_lookback_days must be positive")
    if not 0 < atm_moneyness_band < 1:
        raise ResearchWorkbenchError("atm_moneyness_band must be between 0 and 1")
    if not 0 < otm_moneyness_min <= otm_moneyness_max < 1:
        raise ResearchWorkbenchError("OTM moneyness bounds must be within (0, 1)")

    option_path = (
        option_core_path
        or data_dir() / "core" / PRODUCT_CODE / CORE_OPTION_QUOTE_FILE_NAME
    )
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    option_frame = _load_option_core(option_path)
    quote_frame = _load_core_quotes(quote_path)
    start = min(option_frame["trade_date"])
    end = max(option_frame["trade_date"])
    proxy_run_id = run_id or _default_run_id(start=start, end=end)

    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    build_mode = "FULL"
    incremental_base = _incremental_base(
        output_root=paths["factor_parquet"].parent,
        start=start,
        end=end,
        option_frame=option_frame,
    ) if incremental else None
    if incremental_base is None:
        surface_rows = _surface_proxy_rows(
            option_frame=option_frame,
            quote_frame=quote_frame,
            run_id=proxy_run_id,
            atm_moneyness_band=atm_moneyness_band,
            otm_moneyness_min=otm_moneyness_min,
            otm_moneyness_max=otm_moneyness_max,
        )
        surface_frame = pd.DataFrame(surface_rows)
        factor_rows = _factor_rows(
            surface=surface_rows,
            run_id=proxy_run_id,
            iv_rank_lookback_days=iv_rank_lookback_days,
            otm_moneyness_min=otm_moneyness_min,
            otm_moneyness_max=otm_moneyness_max,
        )
    else:
        # 日更只重算最新交易日；历史表继续保留，周更再做全历史重建校验。
        latest_option = option_frame.loc[option_frame["trade_date"] == end].copy()
        latest_quote = quote_frame.loc[quote_frame["trade_date"] == end].copy()
        latest_surface_rows = _surface_proxy_rows(
            option_frame=latest_option,
            quote_frame=latest_quote,
            run_id=proxy_run_id,
            atm_moneyness_band=atm_moneyness_band,
            otm_moneyness_min=otm_moneyness_min,
            otm_moneyness_max=otm_moneyness_max,
        )
        latest_factor_rows = _factor_rows(
            surface=latest_surface_rows,
            run_id=proxy_run_id,
            iv_rank_lookback_days=iv_rank_lookback_days,
            otm_moneyness_min=otm_moneyness_min,
            otm_moneyness_max=otm_moneyness_max,
        )
        prior_factor, prior_surface = incremental_base
        factor_frame = pd.concat(
            [
                prior_factor.loc[prior_factor["trade_date"] < end],
                pd.DataFrame(latest_factor_rows),
            ],
            ignore_index=True,
        )
        factor_frame["run_id"] = proxy_run_id
        factor_rows = factor_frame.to_dict("records")
        surface_frame = pd.concat(
            [
                prior_surface.loc[prior_surface["trade_date"] < end],
                pd.DataFrame(latest_surface_rows),
            ],
            ignore_index=True,
        )
        surface_frame["run_id"] = proxy_run_id
        build_mode = "INCREMENTAL_LATEST_DATE"
    factor_rows = _attach_iv_rank(
        factor_rows=factor_rows,
        iv_rank_lookback_days=iv_rank_lookback_days,
    )
    warnings = _warning_records(
        run_id=proxy_run_id,
        surface=surface_frame,
        factor_rows=factor_rows,
    )
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    json_path = _json_path(start=start, end=end, report_output_dir=report_output_dir)
    status = "COMPLETED" if factor_rows else "NO_ELIGIBLE_OPTION_FACTOR_ROWS"
    result = ResearchOptionFactorProxyResult(
        product_code=PRODUCT_CODE,
        exchange=EXCHANGE,
        run_id=proxy_run_id,
        status=status,
        build_mode=build_mode,
        start=start,
        end=end,
        option_row_count=len(option_frame),
        surface_row_count=len(surface_frame),
        factor_row_count=len(factor_rows),
        eligible_option_row_count=int(surface_frame["included_in_factor"].astype(bool).sum()),
        excluded_option_row_count=int((~surface_frame["included_in_factor"].astype(bool)).sum()),
        warning_records=warnings,
        factor_parquet_path=paths["factor_parquet"],
        factor_csv_path=paths["factor_csv"],
        surface_parquet_path=paths["surface_parquet"],
        surface_csv_path=paths["surface_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        option_core_path=option_path,
        core_quote_path=quote_path,
        human_review_required=_human_review_required(warnings),
    )
    _write_table(
        factor_rows,
        parquet_path=result.factor_parquet_path,
        csv_path=result.factor_csv_path,
    )
    _write_table(
        surface_frame,
        parquet_path=result.surface_parquet_path,
        csv_path=result.surface_csv_path,
    )
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_markdown(result=result, factor_rows=factor_rows)
    _write_json(result=result, factor_rows=factor_rows)
    _write_manifest(result=result)
    return result


def _load_option_core(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"core option quote table not found: {path}")
    frame = pd.read_parquet(path)
    missing = sorted(OPTION_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"core option quote table missing columns: {missing}")
    if frame.empty:
        raise ResearchWorkbenchError(f"core option quote table is empty: {path}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    for column in ("strike", "settle", "volume", "open_interest", "moneyness"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working["option_type"] = working["option_type"].astype(str).str.upper()
    working["underlying_contract"] = working["underlying_contract"].astype(str)
    working["option_symbol"] = working["option_symbol"].astype(str)
    working["data_quality_flag"] = working["data_quality_flag"].fillna("normal").astype(str)
    working["liquidity_flag"] = working["liquidity_flag"].fillna("").astype(str)
    return working.sort_values(["trade_date", "underlying_contract", "option_symbol"]).reset_index(
        drop=True
    )


def _load_core_quotes(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"core quote table not found: {path}")
    frame = pd.read_parquet(path)
    missing = sorted(QUOTE_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"core quote table missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["contract_code"] = working["contract_code"].astype(str)
    working["settle"] = pd.to_numeric(working["settle"], errors="coerce")
    working = working.dropna(subset=["trade_date", "contract_code", "settle"])
    return working[["trade_date", "contract_code", "settle"]].rename(
        columns={"contract_code": "underlying_contract", "settle": "underlying_settle"}
    )


def _incremental_base(
    *,
    output_root: Path,
    start: date,
    end: date,
    option_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    factor_path = _latest_existing_path(output_root, "*_option_factor_proxy_daily.parquet")
    surface_path = _latest_existing_path(output_root, "*_option_surface_proxy_daily.parquet")
    if factor_path is None or surface_path is None:
        return None
    factor = pd.read_parquet(factor_path)
    surface = pd.read_parquet(surface_path)
    if factor.empty or surface.empty:
        return None
    factor["trade_date"] = pd.to_datetime(factor["trade_date"], errors="coerce").dt.date
    surface["trade_date"] = pd.to_datetime(surface["trade_date"], errors="coerce").dt.date
    available_dates = sorted(set(option_frame["trade_date"]))
    expected_prior = available_dates[-2] if len(available_dates) >= 2 else start
    if min(factor["trade_date"]) > start or min(surface["trade_date"]) > start:
        return None
    if max(factor["trade_date"]) < expected_prior or max(surface["trade_date"]) < expected_prior:
        return None
    if end not in set(option_frame["trade_date"]):
        return None
    return factor, surface


def _latest_existing_path(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    candidates = sorted(
        root.glob(pattern),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _surface_proxy_rows(
    *,
    option_frame: pd.DataFrame,
    quote_frame: pd.DataFrame,
    run_id: str,
    atm_moneyness_band: float,
    otm_moneyness_min: float,
    otm_moneyness_max: float,
) -> list[dict[str, object]]:
    merged = option_frame.merge(
        quote_frame,
        how="left",
        on=["trade_date", "underlying_contract"],
        validate="many_to_one",
    )
    rows: list[dict[str, object]] = []
    for record in merged.itertuples(index=False):
        risk_flags = _risk_flags(str(record.data_quality_flag))
        underlying_settle = _float_or_none(record.underlying_settle)
        settle = _float_or_none(record.settle)
        moneyness = _float_or_none(record.moneyness)
        premium_to_underlying = _safe_ratio(settle, underlying_settle)
        exclusion_reasons = _exclusion_reasons(
            risk_flags=risk_flags,
            settle=settle,
            underlying_settle=underlying_settle,
            moneyness=moneyness,
        )
        included = not exclusion_reasons
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "exchange": EXCHANGE,
                "trade_date": record.trade_date,
                "underlying_contract": str(record.underlying_contract),
                "option_symbol": str(record.option_symbol),
                "option_type": str(record.option_type),
                "strike": _float_or_none(record.strike),
                "settle": settle,
                "underlying_settle": underlying_settle,
                "volume": _int_or_none(record.volume),
                "open_interest": _int_or_none(record.open_interest),
                "moneyness": moneyness,
                "moneyness_distance": None if moneyness is None else abs(moneyness - 1.0),
                "premium_to_underlying": premium_to_underlying,
                "moneyness_bucket": _moneyness_bucket(
                    moneyness=moneyness,
                    risk_flags=risk_flags,
                    atm_moneyness_band=atm_moneyness_band,
                    otm_moneyness_min=otm_moneyness_min,
                    otm_moneyness_max=otm_moneyness_max,
                ),
                "liquidity_flag": str(record.liquidity_flag),
                "data_quality_flag": str(record.data_quality_flag),
                "included_in_factor": included,
                "exclusion_reason": "normal" if included else ";".join(exclusion_reasons),
                "model_boundary": "美式期权研究 proxy，不是精确 IV/Greek",
                "option_factor_rule_version": OPTION_FACTOR_PROXY_VERSION,
            }
        )
    return rows


def _factor_rows(
    *,
    surface: list[dict[str, object]],
    run_id: str,
    iv_rank_lookback_days: int,
    otm_moneyness_min: float,
    otm_moneyness_max: float,
) -> list[dict[str, object]]:
    frame = pd.DataFrame(surface)
    if frame.empty:
        return []
    rows: list[dict[str, object]] = []
    for (trade_date_value, underlying_contract), group in frame.groupby(
        ["trade_date", "underlying_contract"],
        sort=True,
    ):
        eligible = group.loc[group["included_in_factor"].astype(bool)].copy()
        underlying_settle = _first_float(group["underlying_settle"])
        atm = _atm_pair(eligible=eligible, underlying_settle=underlying_settle)
        call_volume = _sum_numeric(eligible.loc[eligible["option_type"] == "C", "volume"])
        put_volume = _sum_numeric(eligible.loc[eligible["option_type"] == "P", "volume"])
        call_oi = _sum_numeric(eligible.loc[eligible["option_type"] == "C", "open_interest"])
        put_oi = _sum_numeric(eligible.loc[eligible["option_type"] == "P", "open_interest"])
        pcr_volume = _safe_ratio(put_volume, call_volume)
        pcr_oi = _safe_ratio(put_oi, call_oi)
        skew_proxy = _skew_proxy(
            eligible=eligible,
            otm_moneyness_min=otm_moneyness_min,
            otm_moneyness_max=otm_moneyness_max,
        )
        option_liquidity_score = _liquidity_score(
            volume=(call_volume or 0.0) + (put_volume or 0.0),
            open_interest=(call_oi or 0.0) + (put_oi or 0.0),
        )
        # 这里的 ATM IV 是 straddle extrinsic / futures settle 的研究 proxy；
        # 未引入美式期权定价模型、利率、期限和 Greek，因此不能当作精确隐波。
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "exchange": EXCHANGE,
                "trade_date": trade_date_value,
                "underlying_contract": str(underlying_contract),
                "underlying_settle": underlying_settle,
                "option_count": int(len(group)),
                "eligible_option_count": int(len(eligible)),
                "excluded_option_count": int(len(group) - len(eligible)),
                "atm_strike": atm["atm_strike"],
                "atm_call_settle": atm["atm_call_settle"],
                "atm_put_settle": atm["atm_put_settle"],
                "atm_straddle_value": atm["atm_straddle_value"],
                "atm_extrinsic_value": atm["atm_extrinsic_value"],
                "atm_iv_proxy": atm["atm_iv_proxy"],
                "iv_rank_lookback_days": iv_rank_lookback_days,
                "atm_iv_rank": None,
                "pcr_volume": pcr_volume,
                "pcr_oi": pcr_oi,
                "skew_proxy": skew_proxy,
                "call_volume": call_volume,
                "put_volume": put_volume,
                "call_open_interest": call_oi,
                "put_open_interest": put_oi,
                "option_liquidity_score": option_liquidity_score,
                "factor_status": _factor_status(
                    eligible_count=int(len(eligible)),
                    atm_iv_proxy=atm["atm_iv_proxy"],
                    pcr_volume=pcr_volume,
                    pcr_oi=pcr_oi,
                    skew_proxy=skew_proxy,
                ),
                "option_signal_status": "not_connected",
                "model_boundary": "美式期权 IV/Greek 未精确定价；本表为研究 proxy",
                "option_factor_rule_version": OPTION_FACTOR_PROXY_VERSION,
            }
        )
    return rows


def _attach_iv_rank(
    *,
    factor_rows: list[dict[str, object]],
    iv_rank_lookback_days: int,
) -> list[dict[str, object]]:
    if not factor_rows:
        return []
    frame = pd.DataFrame(factor_rows).sort_values(["underlying_contract", "trade_date"])
    ranks: list[float | None] = []
    for _, group in frame.groupby("underlying_contract", sort=False):
        values = [_float_or_none(value) for value in group["atm_iv_proxy"].tolist()]
        for index, current in enumerate(values):
            if current is None:
                ranks.append(None)
                continue
            window = [
                value
                for value in values[max(0, index - iv_rank_lookback_days + 1) : index + 1]
                if value is not None
            ]
            ranks.append(
                None
                if len(window) < 2
                else sum(value <= current for value in window) / len(window)
            )
    frame["atm_iv_rank"] = ranks
    return frame.to_dict("records")


def _atm_pair(
    *,
    eligible: pd.DataFrame,
    underlying_settle: float | None,
) -> dict[str, float | None]:
    if eligible.empty or underlying_settle is None or underlying_settle <= 0:
        return {
            "atm_strike": None,
            "atm_call_settle": None,
            "atm_put_settle": None,
            "atm_straddle_value": None,
            "atm_extrinsic_value": None,
            "atm_iv_proxy": None,
        }
    candidates: list[dict[str, float]] = []
    for strike, strike_group in eligible.groupby("strike", sort=True):
        call_settle = _first_float(
            strike_group.loc[strike_group["option_type"] == "C", "settle"]
        )
        put_settle = _first_float(
            strike_group.loc[strike_group["option_type"] == "P", "settle"]
        )
        strike_value = _float_or_none(strike)
        if strike_value is None or call_settle is None or put_settle is None:
            continue
        straddle = call_settle + put_settle
        extrinsic = max(straddle - abs(underlying_settle - strike_value), 0.0)
        candidates.append(
            {
                "atm_strike": strike_value,
                "atm_call_settle": call_settle,
                "atm_put_settle": put_settle,
                "atm_straddle_value": straddle,
                "atm_extrinsic_value": extrinsic,
                "atm_iv_proxy": extrinsic / underlying_settle,
                "distance": abs(strike_value - underlying_settle),
            }
        )
    if not candidates:
        return {
            "atm_strike": None,
            "atm_call_settle": None,
            "atm_put_settle": None,
            "atm_straddle_value": None,
            "atm_extrinsic_value": None,
            "atm_iv_proxy": None,
        }
    selected = min(candidates, key=lambda item: item["distance"])
    selected.pop("distance")
    return selected


def _skew_proxy(
    *,
    eligible: pd.DataFrame,
    otm_moneyness_min: float,
    otm_moneyness_max: float,
) -> float | None:
    if eligible.empty:
        return None
    band = eligible.loc[
        (eligible["moneyness"] >= otm_moneyness_min)
        & (eligible["moneyness"] <= otm_moneyness_max)
    ].copy()
    put_premium = _mean_float(
        band.loc[band["option_type"] == "P", "premium_to_underlying"]
    )
    call_premium = _mean_float(
        band.loc[band["option_type"] == "C", "premium_to_underlying"]
    )
    if put_premium is None or call_premium is None:
        return None
    return put_premium - call_premium


def _risk_flags(value: str) -> tuple[str, ...]:
    if not value or value == "normal":
        return ()
    return tuple(flag for flag in value.split(";") if flag and flag != "normal")


def _exclusion_reasons(
    *,
    risk_flags: tuple[str, ...],
    settle: float | None,
    underlying_settle: float | None,
    moneyness: float | None,
) -> tuple[str, ...]:
    reasons = [flag for flag in risk_flags if flag in DISQUALIFYING_RISK_FLAGS]
    if settle is None:
        reasons.append("MISSING_SETTLE")
    if underlying_settle is None or underlying_settle <= 0:
        reasons.append("UNDERLYING_PRICE_MISSING")
    if moneyness is None:
        reasons.append("MISSING_MONEYNESS")
    return tuple(dict.fromkeys(reasons))


def _moneyness_bucket(
    *,
    moneyness: float | None,
    risk_flags: tuple[str, ...],
    atm_moneyness_band: float,
    otm_moneyness_min: float,
    otm_moneyness_max: float,
) -> str:
    if moneyness is None:
        return "missing_moneyness"
    if "DEEP_OTM_PROXY" in risk_flags:
        return "deep_otm_proxy"
    if abs(moneyness - 1.0) <= atm_moneyness_band:
        return "atm_band"
    if otm_moneyness_min <= moneyness <= otm_moneyness_max:
        return "otm_reference_band"
    return "other"


def _warning_records(
    *,
    run_id: str,
    surface: list[dict[str, object]] | pd.DataFrame,
    factor_rows: list[dict[str, object]],
) -> tuple[OptionFactorProxyWarningRecord, ...]:
    surface_frame = surface.copy() if isinstance(surface, pd.DataFrame) else pd.DataFrame(surface)
    warnings: list[OptionFactorProxyWarningRecord] = [
        OptionFactorProxyWarningRecord(
            run_id=run_id,
            section="model_boundary",
            severity=INFO_SEVERITY,
            warning_code="AMERICAN_OPTION_PROXY_ONLY",
            warning_message=(
                "ATM IV、IV rank、skew 均为研究 proxy；未完成美式期权精确定价、Greek "
                "或期限结构模型校准。"
            ),
            affected_count=len(factor_rows),
            human_review_required=("american_option_iv_proxy_model_boundary",),
        )
    ]
    excluded_count = int((~surface_frame["included_in_factor"].astype(bool)).sum())
    if excluded_count:
        warnings.append(
            OptionFactorProxyWarningRecord(
                run_id=run_id,
                section="option_quality_filter",
                severity=INFO_SEVERITY,
                warning_code="OPTION_ROWS_EXCLUDED_FROM_FACTOR",
                warning_message=(
                    "低流动性、深虚值、临近到期、缺结算或缺标的价格的期权行未进入核心 proxy。"
                ),
                affected_count=excluded_count,
                human_review_required=("option_liquidity_thresholds",),
            )
        )
    missing_underlying = int(
        surface_frame["exclusion_reason"].astype(str).str.contains("UNDERLYING_PRICE_MISSING").sum()
    )
    if missing_underlying:
        warnings.append(
            OptionFactorProxyWarningRecord(
                run_id=run_id,
                section="underlying_mapping",
                severity=WARNING_SEVERITY,
                warning_code="UNDERLYING_PRICE_MISSING",
                warning_message="部分期权行缺少对应期货结算价，不能进入 R48 因子。",
                affected_count=missing_underlying,
                human_review_required=("underlying_contract_mapping",),
            )
        )
    incomplete_factor_count = sum(
        1 for row in factor_rows if row.get("factor_status") != "READY"
    )
    if incomplete_factor_count:
        warnings.append(
            OptionFactorProxyWarningRecord(
                run_id=run_id,
                section="factor_completeness",
                severity=WARNING_SEVERITY,
                warning_code="INCOMPLETE_OPTION_FACTOR_ROWS",
                warning_message="部分合约日缺少 ATM 配对、PCR 或 skew proxy，状态不是 READY。",
                affected_count=incomplete_factor_count,
                human_review_required=("moneyness_and_skew_proxy_definition",),
            )
        )
    return tuple(warnings)


def _human_review_required(
    warnings: tuple[OptionFactorProxyWarningRecord, ...],
) -> tuple[str, ...]:
    items = set(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        items.update(warning.human_review_required)
    return tuple(sorted(items))


def _factor_status(
    *,
    eligible_count: int,
    atm_iv_proxy: float | None,
    pcr_volume: float | None,
    pcr_oi: float | None,
    skew_proxy: float | None,
) -> str:
    if eligible_count >= 4 and all(
        value is not None for value in (atm_iv_proxy, pcr_volume, pcr_oi, skew_proxy)
    ):
        return "READY"
    if eligible_count > 0 and any(value is not None for value in (pcr_volume, pcr_oi)):
        return "WATCH"
    return "WEAK_OR_INCOMPLETE"


def _liquidity_score(*, volume: float, open_interest: float) -> float | None:
    if volume <= 0 and open_interest <= 0:
        return None
    score = 10.0 * math.log10(1.0 + max(volume, 0.0)) + 5.0 * math.log10(
        1.0 + max(open_interest, 0.0)
    )
    return round(min(score, 100.0), 6)


def _safe_ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _sum_numeric(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.sum())


def _mean_float(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _first_float(values: object) -> float | None:
    if isinstance(values, pd.Series):
        numeric = pd.to_numeric(values, errors="coerce").dropna()
        return None if numeric.empty else float(numeric.iloc[0])
    return _float_or_none(values)


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _int_or_none(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(float(value))


def _write_table(
    rows: list[dict[str, object]] | pd.DataFrame,
    *,
    parquet_path: Path,
    csv_path: Path,
) -> None:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[OptionFactorProxyWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for warning in warnings:
            writer.writerow(warning.to_csv_row())


def _write_markdown(
    *,
    result: ResearchOptionFactorProxyResult,
    factor_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    latest_rows = [
        row for row in factor_rows if str(row["trade_date"]) == result.end.isoformat()
    ]
    ready_count = sum(1 for row in factor_rows if row.get("factor_status") == "READY")
    lines = [
        "# CF 期权因子 proxy R48",
        "",
        "## 数据状态",
        "",
        f"- 状态：`{result.status}`",
        f"- 构建模式：`{result.build_mode}`",
        f"- 数据区间：{result.start.isoformat()} 至 {result.end.isoformat()}",
        f"- 输入期权 core：`{result.option_core_path}`",
        f"- 输入期货 core：`{result.core_quote_path}`",
        f"- 期权行数：{result.option_row_count}",
        f"- 可进入核心 proxy 的期权行数：{result.eligible_option_row_count}",
        f"- 因质量/风险排除的期权行数：{result.excluded_option_row_count}",
        f"- 合约日因子行数：{result.factor_row_count}",
        f"- READY 因子行数：{ready_count}",
        "- option_signal 状态：`not_connected`，R49 前不进入期货信号过滤。",
        "",
        "## R48 输出",
        "",
        f"- 因子表：`{result.factor_parquet_path}`",
        f"- surface proxy 表：`{result.surface_parquet_path}`",
        f"- warning 表：`{result.warning_csv_path}`",
        "",
        "## 最新日摘要",
        "",
        "| Underlying | ATM IV Proxy | IV Rank | PCR Volume | PCR OI "
        "| Skew Proxy | Liquidity | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    if latest_rows:
        for row in latest_rows[:12]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["underlying_contract"]),
                        _format_number(row.get("atm_iv_proxy")),
                        _format_number(row.get("atm_iv_rank")),
                        _format_number(row.get("pcr_volume")),
                        _format_number(row.get("pcr_oi")),
                        _format_number(row.get("skew_proxy")),
                        _format_number(row.get("option_liquidity_score")),
                        str(row["factor_status"]),
                    ]
                )
                + " |"
            )
    else:
        lines.append("|  |  |  |  |  |  |  | no latest factor rows |")
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 本模块只读取 core 期权表和 core 期货表，不直接解析交易所 raw 文件。",
            "- ATM IV、IV rank、skew 是研究 proxy，未完成美式期权精确定价和 Greek 校准。",
            "- 低流动性、深虚值、临近到期、缺结算或缺标的价格的期权不进入核心 proxy。",
            "- forward return、回测收益、交易成本不进入本模块。",
            "- 本报告不构成交易指令，所有期权解释均需人工复核。",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchOptionFactorProxyResult,
    factor_rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    latest_rows = [
        _json_ready(row) for row in factor_rows if str(row["trade_date"]) == result.end.isoformat()
    ]
    payload = {
        **result.to_summary(),
        "latest_rows": latest_rows,
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_manifest(result: ResearchOptionFactorProxyResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "option_factor_proxy",
        "rule_version": OPTION_FACTOR_PROXY_VERSION,
        "generated_at": utc_now().isoformat(),
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "exchange": EXCHANGE,
        "status": result.status,
        "build_mode": result.build_mode,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "option_core_path": str(result.option_core_path),
        "core_quote_path": str(result.core_quote_path),
        "factor_parquet_path": str(result.factor_parquet_path),
        "surface_parquet_path": str(result.surface_parquet_path),
        "option_signal_status": "not_connected",
        "model_boundary": "American option IV/Greek not precisely priced; research proxies only.",
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "factor_parquet": root / f"{stem}_option_factor_proxy_daily.parquet",
        "factor_csv": root / f"{stem}_option_factor_proxy_daily.csv",
        "surface_parquet": root / f"{stem}_option_surface_proxy_daily.parquet",
        "surface_csv": root / f"{stem}_option_surface_proxy_daily.csv",
        "warning_csv": root / f"{stem}_option_factor_proxy_warnings.csv",
        "manifest": root / f"{stem}_option_factor_proxy_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_option_factor_proxy.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_option_factor_proxy.json"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r48_option_factor_proxy_{start.isoformat()}_{end.isoformat()}_{uuid.uuid4().hex[:8]}"


def _format_number(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):.6f}"


def _json_ready(row: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, date):
            payload[key] = value.isoformat()
        elif value is None or (isinstance(value, float) and math.isnan(value)):
            payload[key] = None
        else:
            payload[key] = value
    return payload
