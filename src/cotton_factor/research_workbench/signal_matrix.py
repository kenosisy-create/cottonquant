"""R35 horizon-aware CF signal matrix."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench import latest_signal_brief as r23
from cotton_factor.research_workbench import trend_continuity_board as r29
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
SIGNAL_MATRIX_VERSION = "R35_signal_matrix_v1"
OUTPUT_DIR = "signal_matrix"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20, 40)
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "signal_matrix_weighting",
    "horizon_score_mapping",
    "trend_phase_rules",
    "factor_thresholds",
    "option_signal_placeholder",
    "option_signal_filter_rules_before_trading_use",
    "contract_rule_assumptions",
)

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
class SignalMatrixWarningRecord:
    """Warning row for the R35 signal matrix."""

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
class ResearchSignalMatrixResult:
    """Result of building R35 signal matrix artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    horizons: tuple[int, ...]
    row_count: int
    trade_day_count: int
    latest_trade_date: date
    latest_main_contract: str
    latest_primary_direction: str
    latest_primary_confidence: str
    warning_records: tuple[SignalMatrixWarningRecord, ...]
    matrix_parquet_path: Path
    matrix_csv_path: Path
    latest_snapshot_json_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_quote_path: Path
    trend_rule_candidate_path: Path | None
    option_factor_path: Path | None
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "horizons": list(self.horizons),
            "row_count": self.row_count,
            "trade_day_count": self.trade_day_count,
            "latest_trade_date": self.latest_trade_date.isoformat(),
            "latest_main_contract": self.latest_main_contract,
            "latest_primary_direction": self.latest_primary_direction,
            "latest_primary_confidence": self.latest_primary_confidence,
            "warning_count": self.warning_count,
            "matrix_parquet_path": str(self.matrix_parquet_path),
            "matrix_csv_path": str(self.matrix_csv_path),
            "latest_snapshot_json_path": str(self.latest_snapshot_json_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "trend_rule_candidate_path": (
                None
                if self.trend_rule_candidate_path is None
                else str(self.trend_rule_candidate_path)
            ),
            "option_factor_path": (
                None if self.option_factor_path is None else str(self.option_factor_path)
            ),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_signal_matrix(
    *,
    start: date | None = None,
    end: date | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    trend_rule_candidate_path: Path | None = None,
    option_factor_path: Path | None = None,
) -> ResearchSignalMatrixResult:
    """Build an R35 horizon-aware signal matrix from observable CF core data."""
    normalized_horizons = _normalize_horizons(horizons)
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = r23._load_core_quotes(input_path=quote_path)
    available_dates = sorted(set(quotes["trade_date"]))
    if not available_dates:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core rows available")

    active_start = start or available_dates[0]
    active_end = end or available_dates[-1]
    if active_start > active_end:
        raise ResearchWorkbenchError("start must be <= end")
    output_dates = [value for value in available_dates if active_start <= value <= active_end]
    if not output_dates:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} core rows from {active_start.isoformat()} to "
            f"{active_end.isoformat()}"
        )

    matrix_run_id = run_id or _default_run_id(start=active_start, end=active_end)
    candidates = (
        None
        if trend_rule_candidate_path is None
        else r23._load_trend_rule_candidates(input_path=trend_rule_candidate_path)
    )
    option_lookup = _load_option_factor_lookup(option_factor_path)
    # R35 复用 R29 逐日可观察状态，避免另起一套主力识别、趋势阶段和质量评分规则。
    score_dates = [value for value in available_dates if value <= active_end]
    board_rows = r29._board_rows(
        quotes=quotes,
        trade_dates=score_dates,
        run_id=matrix_run_id,
        candidates=candidates,
    )
    matrix_rows = _matrix_rows(
        board_rows=board_rows,
        quotes=quotes,
        start=active_start,
        end=active_end,
        horizons=normalized_horizons,
        option_lookup=option_lookup,
    )
    if not matrix_rows:
        raise ResearchWorkbenchError("signal matrix has no rows")
    latest_rows = [row for row in matrix_rows if row["trade_date"] == output_dates[-1].isoformat()]
    latest_primary = _primary_latest_row(latest_rows=latest_rows)
    warnings = _warning_records(
        run_id=matrix_run_id,
        matrix_rows=matrix_rows,
        horizons=normalized_horizons,
        trend_rule_candidate_path=trend_rule_candidate_path,
        option_factor_path=option_factor_path,
    )
    paths = _output_paths(start=active_start, end=active_end, output_dir=output_dir)
    markdown_path = _markdown_path(
        start=active_start,
        end=active_end,
        report_output_dir=report_output_dir,
    )
    json_path = _json_path(start=active_start, end=active_end, report_output_dir=report_output_dir)
    result = ResearchSignalMatrixResult(
        product_code=PRODUCT_CODE,
        run_id=matrix_run_id,
        start=active_start,
        end=active_end,
        horizons=normalized_horizons,
        row_count=len(matrix_rows),
        trade_day_count=len(output_dates),
        latest_trade_date=output_dates[-1],
        latest_main_contract=str(latest_primary["main_contract"]),
        latest_primary_direction=str(latest_primary["direction"]),
        latest_primary_confidence=str(latest_primary["confidence"]),
        warning_records=warnings,
        matrix_parquet_path=paths["matrix_parquet"],
        matrix_csv_path=paths["matrix_csv"],
        latest_snapshot_json_path=paths["latest_snapshot_json"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        trend_rule_candidate_path=trend_rule_candidate_path,
        option_factor_path=option_factor_path,
        human_review_required=_human_review_required(warnings),
    )
    _write_table(
        rows=matrix_rows,
        parquet_path=result.matrix_parquet_path,
        csv_path=result.matrix_csv_path,
    )
    _write_latest_snapshot(result=result, latest_rows=latest_rows)
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_markdown(result=result, matrix_rows=matrix_rows, latest_rows=latest_rows)
    _write_json(result=result, matrix_rows=matrix_rows, latest_rows=latest_rows)
    _write_manifest(result=result)
    return result


def _matrix_rows(
    *,
    board_rows: list[dict[str, object]],
    quotes: pd.DataFrame,
    start: date,
    end: date,
    horizons: tuple[int, ...],
    option_lookup: dict[tuple[date, str], dict[str, object]] | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for board_row in board_rows:
        trade_date = date.fromisoformat(str(board_row["trade_date"]))
        if trade_date < start or trade_date > end:
            continue
        for horizon in horizons:
            rows.append(
                _matrix_row(
                    board_row=board_row,
                    quotes=quotes,
                    horizon=horizon,
                    option_lookup=option_lookup,
                )
            )
    return rows


def _matrix_row(
    *,
    board_row: dict[str, object],
    quotes: pd.DataFrame,
    horizon: int,
    option_lookup: dict[tuple[date, str], dict[str, object]] | None,
) -> dict[str, object]:
    trade_date = date.fromisoformat(str(board_row["trade_date"]))
    main_contract = str(board_row["main_contract"])
    horizon_return = _past_return(
        quotes=quotes,
        trade_date=trade_date,
        contract_code=main_contract,
        horizon=horizon,
    )
    price_signal = _direction(horizon_return)
    momentum_signal = _horizon_momentum_signal(
        board_row=board_row,
        horizon=horizon,
        horizon_return=horizon_return,
    )
    carry_signal = str(board_row.get("carry_signal", "unknown"))
    curve_signal = str(board_row.get("curve_signal", "unknown"))
    oi_signal = str(board_row.get("oi_pressure_signal", "unknown"))
    phase_signal = _phase_signal(board_row)
    score_detail = _composite_score(
        horizon=horizon,
        price_signal=price_signal,
        momentum_signal=momentum_signal,
        carry_signal=carry_signal,
        curve_signal=curve_signal,
        oi_signal=oi_signal,
        phase_signal=phase_signal,
    )
    trend_quality_score = _int_or_none(board_row.get("trend_quality_score"))
    confidence_score = _confidence_score(
        composite_score=int(score_detail["composite_score"]),
        max_score=int(score_detail["max_score"]),
        trend_quality_score=trend_quality_score,
        available_signal_count=int(score_detail["available_signal_count"]),
    )
    direction = _score_direction(int(score_detail["composite_score"]))
    option_context = _option_context(
        option_lookup=option_lookup,
        trade_date=trade_date,
        main_contract=main_contract,
        futures_direction=direction,
    )
    warning_flags = _warning_flags(
        board_row=board_row,
        confidence_score=confidence_score,
        horizon_return=horizon_return,
        option_signal=str(option_context["option_signal"]),
    )
    return {
        "run_id": board_row["run_id"],
        "product_code": PRODUCT_CODE,
        "trade_date": trade_date.isoformat(),
        "horizon": horizon,
        "horizon_label": f"{horizon}D",
        "main_contract": main_contract,
        "main_settle": board_row.get("main_settle"),
        "price_signal": price_signal,
        "momentum_signal": momentum_signal,
        "carry_signal": carry_signal,
        "curve_signal": curve_signal,
        "oi_signal": oi_signal,
        "option_signal": option_context["option_signal"],
        "option_signal_direction": option_context["option_signal_direction"],
        "option_factor_status": option_context["option_factor_status"],
        "option_atm_iv_rank": option_context["option_atm_iv_rank"],
        "option_pcr_volume": option_context["option_pcr_volume"],
        "option_pcr_oi": option_context["option_pcr_oi"],
        "option_skew_proxy": option_context["option_skew_proxy"],
        "regime_state": _regime_state(board_row),
        "trend_phase": board_row.get("trend_phase_code"),
        "trend_phase_label": board_row.get("trend_phase_label"),
        "trend_phase_direction": board_row.get("trend_phase_direction"),
        "trend_quality_score": trend_quality_score,
        "trend_quality_label": board_row.get("trend_quality_label"),
        "composite_score": score_detail["composite_score"],
        "composite_max_score": score_detail["max_score"],
        "direction": direction,
        "confidence_score": confidence_score,
        "confidence": _confidence_label(confidence_score),
        "evidence_level": _evidence_level(
            confidence_score=confidence_score,
            warning_flags=warning_flags,
        ),
        "action_type": _action_type(board_row=board_row, confidence_score=confidence_score),
        "warning_flags": ";".join(warning_flags),
        "past_return": horizon_return,
        "return_1d": board_row.get("return_1d"),
        "return_3d": board_row.get("return_3d"),
        "return_5d": board_row.get("return_5d"),
        "return_10d": board_row.get("return_10d"),
        "return_20d": board_row.get("return_20d"),
        "main_oi_pressure": board_row.get("main_oi_pressure"),
        "carry_annualized": board_row.get("carry_annualized"),
        "curve_slope": board_row.get("curve_slope"),
        "phase_run_length": board_row.get("phase_run_length"),
        "transition_code": board_row.get("transition_code"),
        "observation_marker": board_row.get("observation_marker"),
        "source_snapshot_ids": board_row.get("source_snapshot_ids"),
        "signal_matrix_rule_version": SIGNAL_MATRIX_VERSION,
        "no_future_return_labels": True,
    }


def _past_return(
    *,
    quotes: pd.DataFrame,
    trade_date: date,
    contract_code: str,
    horizon: int,
) -> float | None:
    series = quotes.loc[quotes["contract_code"].astype(str) == contract_code].copy()
    series = series.sort_values("trade_date").reset_index(drop=True)
    matches = series.index[series["trade_date"] == trade_date].tolist()
    if not matches:
        return None
    current_index = int(matches[0])
    prior_index = current_index - horizon
    if prior_index < 0:
        return None
    latest = r23._float_or_none(series.iloc[current_index]["settle"])
    prior = r23._float_or_none(series.iloc[prior_index]["settle"])
    return None if latest is None or prior is None or prior <= 0 else latest / prior - 1


def _load_option_factor_lookup(
    option_factor_path: Path | None,
) -> dict[tuple[date, str], dict[str, object]] | None:
    if option_factor_path is None:
        return None
    if not option_factor_path.exists():
        raise ResearchWorkbenchError(f"option factor table not found: {option_factor_path}")
    frame = (
        pd.read_csv(option_factor_path)
        if option_factor_path.suffix == ".csv"
        else pd.read_parquet(option_factor_path)
    )
    required = {
        "trade_date",
        "underlying_contract",
        "factor_status",
        "atm_iv_rank",
        "pcr_volume",
        "pcr_oi",
        "skew_proxy",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"option factor table missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["underlying_contract"] = working["underlying_contract"].astype(str)
    for column in ("atm_iv_rank", "pcr_volume", "pcr_oi", "skew_proxy"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    lookup: dict[tuple[date, str], dict[str, object]] = {}
    for row in working.itertuples(index=False):
        lookup[(row.trade_date, str(row.underlying_contract))] = {
            "factor_status": str(row.factor_status),
            "atm_iv_rank": r23._float_or_none(row.atm_iv_rank),
            "pcr_volume": r23._float_or_none(row.pcr_volume),
            "pcr_oi": r23._float_or_none(row.pcr_oi),
            "skew_proxy": r23._float_or_none(row.skew_proxy),
        }
    return lookup


def _option_context(
    *,
    option_lookup: dict[tuple[date, str], dict[str, object]] | None,
    trade_date: date,
    main_contract: str,
    futures_direction: str,
) -> dict[str, object]:
    if option_lookup is None:
        return _empty_option_context(option_signal="not_connected")
    option_row = option_lookup.get((trade_date, main_contract))
    if option_row is None:
        return _empty_option_context(option_signal="not_available")
    factor_status = str(option_row.get("factor_status"))
    atm_iv_rank = r23._float_or_none(option_row.get("atm_iv_rank"))
    pcr_volume = r23._float_or_none(option_row.get("pcr_volume"))
    pcr_oi = r23._float_or_none(option_row.get("pcr_oi"))
    skew_proxy = r23._float_or_none(option_row.get("skew_proxy"))
    option_direction = _option_direction(
        pcr_volume=pcr_volume,
        pcr_oi=pcr_oi,
        skew_proxy=skew_proxy,
    )
    if atm_iv_rank is not None and atm_iv_rank >= 0.80:
        option_signal = "volatility_risk"
    elif factor_status != "READY":
        option_signal = "option_watch"
    elif option_direction == "neutral":
        option_signal = "option_neutral"
    elif futures_direction in {"long", "short"}:
        option_signal = (
            f"confirm_{option_direction}"
            if option_direction == futures_direction
            else f"diverge_{futures_direction}"
        )
    else:
        option_signal = f"option_{option_direction}"
    return {
        "option_signal": option_signal,
        "option_signal_direction": option_direction,
        "option_factor_status": factor_status,
        "option_atm_iv_rank": atm_iv_rank,
        "option_pcr_volume": pcr_volume,
        "option_pcr_oi": pcr_oi,
        "option_skew_proxy": skew_proxy,
    }


def _empty_option_context(*, option_signal: str) -> dict[str, object]:
    return {
        "option_signal": option_signal,
        "option_signal_direction": "unknown",
        "option_factor_status": "not_connected",
        "option_atm_iv_rank": None,
        "option_pcr_volume": None,
        "option_pcr_oi": None,
        "option_skew_proxy": None,
    }


def _option_direction(
    *,
    pcr_volume: float | None,
    pcr_oi: float | None,
    skew_proxy: float | None,
) -> str:
    votes: list[str] = []
    # PCR 偏低通常表示看涨成交/持仓占优；偏高则提示看跌或保护需求占优。
    for value in (pcr_volume, pcr_oi):
        if value is None:
            continue
        if value < 0.80:
            votes.append("long")
        elif value > 1.20:
            votes.append("short")
    # R48 skew_proxy = OTM put premium ratio - OTM call premium ratio。
    if skew_proxy is not None:
        if skew_proxy < -0.001:
            votes.append("long")
        elif skew_proxy > 0.001:
            votes.append("short")
    long_count = votes.count("long")
    short_count = votes.count("short")
    if long_count > short_count:
        return "long"
    if short_count > long_count:
        return "short"
    return "neutral"


def _horizon_momentum_signal(
    *,
    board_row: dict[str, object],
    horizon: int,
    horizon_return: float | None,
) -> str:
    if horizon <= 10:
        return _direction(horizon_return)
    if horizon <= 20:
        return _direction(board_row.get("return_20d"))
    return _direction(horizon_return if horizon_return is not None else board_row.get("return_20d"))


def _phase_signal(board_row: dict[str, object]) -> str:
    phase_code = str(board_row.get("trend_phase_code"))
    phase_direction = str(board_row.get("trend_phase_direction"))
    if phase_code in {"S1", "S2"} and phase_direction in {"long", "short"}:
        return phase_direction
    if phase_code == "S4" and phase_direction in {"long", "short"}:
        return "short" if phase_direction == "long" else "long"
    return "neutral"


def _composite_score(
    *,
    horizon: int,
    price_signal: str,
    momentum_signal: str,
    carry_signal: str,
    curve_signal: str,
    oi_signal: str,
    phase_signal: str,
) -> dict[str, int]:
    weights = _horizon_weights(horizon)
    signal_map = {
        "price": price_signal,
        "momentum": momentum_signal,
        "carry": carry_signal,
        "curve": curve_signal,
        "oi": oi_signal,
        "phase": phase_signal,
    }
    score = 0
    max_score = 0
    available = 0
    for key, signal in signal_map.items():
        weight = weights[key]
        if signal not in {"long", "short", "neutral"}:
            continue
        max_score += weight
        available += 1
        if signal == "long":
            score += weight
        elif signal == "short":
            score -= weight
    return {
        "composite_score": score,
        "max_score": max_score,
        "available_signal_count": available,
    }


def _horizon_weights(horizon: int) -> dict[str, int]:
    if horizon <= 3:
        return {"price": 2, "momentum": 1, "carry": 1, "curve": 1, "oi": 2, "phase": 1}
    if horizon <= 5:
        return {"price": 1, "momentum": 2, "carry": 1, "curve": 1, "oi": 2, "phase": 1}
    if horizon <= 20:
        return {"price": 1, "momentum": 2, "carry": 2, "curve": 2, "oi": 1, "phase": 2}
    return {"price": 1, "momentum": 1, "carry": 2, "curve": 2, "oi": 1, "phase": 2}


def _confidence_score(
    *,
    composite_score: int,
    max_score: int,
    trend_quality_score: int | None,
    available_signal_count: int,
) -> int:
    if max_score <= 0 or available_signal_count < 3:
        return 0
    score_strength = abs(composite_score) / max_score
    quality_component = 0 if trend_quality_score is None else trend_quality_score * 0.35
    confidence = score_strength * 65 + quality_component
    return max(0, min(100, int(round(confidence))))


def _warning_flags(
    *,
    board_row: dict[str, object],
    confidence_score: int,
    horizon_return: float | None,
    option_signal: str,
) -> tuple[str, ...]:
    flags: list[str] = []
    if option_signal in {"not_connected", "not_available"}:
        flags.append("option_not_connected")
    elif option_signal.startswith("diverge_"):
        flags.append("option_divergence")
    elif option_signal == "volatility_risk":
        flags.append("option_volatility_risk")
    elif option_signal == "option_watch":
        flags.append("option_watch")
    phase_code = str(board_row.get("trend_phase_code"))
    if phase_code == "S3":
        flags.append("trend_exhaustion_watch")
    if phase_code == "S4":
        flags.append("trend_end_risk")
    if confidence_score < 40:
        flags.append("low_confidence")
    if horizon_return is None:
        flags.append("short_history")
    return tuple(r23._unique_values(flags))


def _direction(value: object) -> str:
    numeric = r23._float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric > 0:
        return "long"
    if numeric < 0:
        return "short"
    return "neutral"


def _score_direction(score: int) -> str:
    if score > 0:
        return "long"
    if score < 0:
        return "short"
    return "neutral"


def _confidence_label(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _evidence_level(*, confidence_score: int, warning_flags: tuple[str, ...]) -> str:
    if "short_history" in warning_flags or confidence_score < 40:
        return "weak"
    if confidence_score >= 70 and not any(flag.endswith("risk") for flag in warning_flags):
        return "strong"
    return "moderate"


def _action_type(*, board_row: dict[str, object], confidence_score: int) -> str:
    phase_code = str(board_row.get("trend_phase_code"))
    if phase_code in {"S3", "S4"}:
        return "风险提示"
    if confidence_score >= 55:
        return "验证"
    return "观察"


def _regime_state(board_row: dict[str, object]) -> str:
    phase_code = str(board_row.get("trend_phase_code"))
    return {
        "S0": "未确认",
        "S1": "起点观察",
        "S2": "趋势中",
        "S3": "衰竭观察",
        "S4": "终点确认",
    }.get(phase_code, "未知")


def _primary_latest_row(*, latest_rows: list[dict[str, object]]) -> dict[str, object]:
    if not latest_rows:
        raise ResearchWorkbenchError("latest signal matrix snapshot has no rows")
    priority = {20: 0, 10: 1, 5: 2, 3: 3, 1: 4, 40: 5}
    return sorted(latest_rows, key=lambda row: priority.get(int(row["horizon"]), 99))[0]


def _warning_records(
    *,
    run_id: str,
    matrix_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
    trend_rule_candidate_path: Path | None,
    option_factor_path: Path | None,
) -> tuple[SignalMatrixWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R35_NO_FORWARD_RETURN_LABELS",
            warning_message="R35 信号矩阵只使用 T 日及以前可观察数据，不包含未来收益标签。",
            affected_count=len(matrix_rows),
            human_review_required=(),
        ),
    ]
    if option_factor_path is None:
        records.append(
            _warning(
                run_id=run_id,
                section="option_signal",
                severity=INFO_SEVERITY,
                warning_code="R35_OPTION_SIGNAL_NOT_CONNECTED",
                warning_message="期权信号当前为占位字段，不参与 R35 综合评分。",
                affected_count=len(matrix_rows),
                human_review_required=("option_signal_placeholder",),
            )
        )
    else:
        connected_count = sum(
            str(row.get("option_signal")) not in {"not_connected", "not_available"}
            for row in matrix_rows
        )
        records.append(
            _warning(
                run_id=run_id,
                section="option_signal",
                severity=INFO_SEVERITY,
                warning_code="R49_OPTION_SIGNAL_FILTER_CONNECTED",
                warning_message=(
                    "R49 已接入 R48 期权 proxy 作为期货信号过滤器；"
                    "暂不改变原综合得分。"
                ),
                affected_count=connected_count,
                human_review_required=("option_signal_filter_rules_before_trading_use",),
            )
        )
    records.append(
        _warning(
            run_id=run_id,
            section="option_signal_boundary",
            severity=INFO_SEVERITY,
            warning_code="R49_OPTION_SIGNAL_NOT_SCORE_COMPONENT",
            warning_message="option_signal 是过滤和风险提示字段，未进入 composite_score。",
            affected_count=len(matrix_rows),
            human_review_required=("signal_matrix_weighting",),
        )
    )
    short_history_count = sum(
        "short_history" in str(row.get("warning_flags")) for row in matrix_rows
    )
    if short_history_count:
        records.append(
            _warning(
                run_id=run_id,
                section="history_length",
                severity=WARNING_SEVERITY,
                warning_code="R35_SHORT_HISTORY_FOR_SOME_HORIZONS",
                warning_message="部分交易日缺少指定 horizon 的历史观察，矩阵已标记 short_history。",
                affected_count=short_history_count,
                human_review_required=("horizon_score_mapping",),
            )
        )
    if 40 in horizons:
        records.append(
            _warning(
                run_id=run_id,
                section="horizon_design",
                severity=INFO_SEVERITY,
                warning_code="R35_MEDIUM_TERM_HORIZON_HEURISTIC",
                warning_message=(
                    "40D 中期 horizon 当前仍基于期货日行情启发式评分，"
                    "未接入产业基本面。"
                ),
                affected_count=sum(1 for row in matrix_rows if int(row["horizon"]) == 40),
                human_review_required=("horizon_score_mapping",),
            )
        )
    if trend_rule_candidate_path is not None:
        records.append(
            _warning(
                run_id=run_id,
                section="trend_rule_context",
                severity=INFO_SEVERITY,
                warning_code="R35_R27_CANDIDATE_CONTEXT_ONLY",
                warning_message="R27 候选规则只作为阶段切换解释上下文，不构成交易规则。",
                affected_count=len(matrix_rows),
                human_review_required=("trend_rule_candidate_thresholds",),
            )
        )
    return tuple(records)


def _warning(
    *,
    run_id: str,
    section: str,
    severity: str,
    warning_code: str,
    warning_message: str,
    affected_count: int,
    human_review_required: tuple[str, ...],
) -> SignalMatrixWarningRecord:
    return SignalMatrixWarningRecord(
        run_id=run_id,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        affected_count=affected_count,
        human_review_required=human_review_required,
    )


def _write_table(*, rows: list[dict[str, object]], parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_latest_snapshot(
    *,
    result: ResearchSignalMatrixResult,
    latest_rows: list[dict[str, object]],
) -> None:
    result.latest_snapshot_json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "signal_matrix_latest_snapshot",
        "rule_version": SIGNAL_MATRIX_VERSION,
        "no_future_return_labels": True,
        "latest_rows": latest_rows,
    }
    result.latest_snapshot_json_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warning_csv(
    *,
    warnings: tuple[SignalMatrixWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchSignalMatrixResult,
    matrix_rows: list[dict[str, object]],
    latest_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(matrix_rows)
    latest_sorted = sorted(latest_rows, key=lambda row: int(row["horizon"]))
    lines = [
        f"# CF 多周期信号矩阵 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        f"- Run ID：`{result.run_id}`",
        f"- 核心表：`{result.core_quote_path}`",
        f"- 交易日数量：`{result.trade_day_count}`",
        f"- 矩阵行数：`{result.row_count}`",
        f"- Horizon：`{','.join(str(item) for item in result.horizons)}`",
        "- 是否包含未来收益标签：`否`",
        "",
        "## 二、最新多周期观察",
        "",
        "| Horizon | 方向 | 期权过滤 | 置信度 | 阶段 | 证据等级 | 操作类型 | 风险标签 |",
        "| ---: | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in latest_sorted:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["horizon"]),
                    str(row["direction"]),
                    str(row.get("option_signal")),
                    str(row["confidence_score"]),
                    f"{row['trend_phase']} {row['trend_phase_label']}",
                    str(row["evidence_level"]),
                    str(row["action_type"]),
                    str(row["warning_flags"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 三、窗口分布",
            "",
            "| Horizon | 多头 | 空头 | 中性 | 高置信 | 中置信 | 低置信 |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for horizon, group in frame.groupby("horizon", sort=True):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(horizon),
                    str(int((group["direction"] == "long").sum())),
                    str(int((group["direction"] == "short").sum())),
                    str(int((group["direction"] == "neutral").sum())),
                    str(int((group["confidence"] == "high").sum())),
                    str(int((group["confidence"] == "medium").sum())),
                    str(int((group["confidence"] == "low").sum())),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 四、研究边界",
            "",
            "- R35 只输出多周期可观察信号矩阵，不包含未来收益标签。",
            "- evidence_level 当前是启发式证据等级，完整历史表现由 R36 滚动验证更新。",
            "- option_signal 是期权过滤和风险提示字段，不进入 composite_score。",
            "- 本表用于研究观察，不构成交易指令。",
            "",
            "## 五、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchSignalMatrixResult,
    matrix_rows: list[dict[str, object]],
    latest_rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "signal_matrix",
        "rule_version": SIGNAL_MATRIX_VERSION,
        "no_future_return_labels": True,
        "matrix_rows": matrix_rows,
        "latest_rows": latest_rows,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_manifest(*, result: ResearchSignalMatrixResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "signal_matrix",
        "rule_version": SIGNAL_MATRIX_VERSION,
        "generated_at": utc_now().isoformat(),
        "no_lookahead": True,
        "contains_forward_return_validation": False,
    }
    result.manifest_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _normalize_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    if not horizons:
        raise ResearchWorkbenchError("at least one horizon is required")
    values = tuple(sorted(set(horizons)))
    invalid = [horizon for horizon in values if horizon <= 0]
    if invalid:
        raise ResearchWorkbenchError(f"horizons must be positive integers: {invalid}")
    return values


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_matrix"
    return {
        "matrix_parquet": root / f"{stem}_daily.parquet",
        "matrix_csv": root / f"{stem}_daily.csv",
        "latest_snapshot_json": root / f"{stem}_latest_snapshot.json",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_matrix"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_matrix"
    return root / f"{stem}.json"


def _human_review_required(warnings: tuple[SignalMatrixWarningRecord, ...]) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(r23._unique_values(values))


def _int_or_none(value: object) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if _is_scalar_missing(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _is_scalar_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict, str, Path, date)):
        return False
    return bool(pd.isna(value))


def _default_run_id(*, start: date, end: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return (
        f"r35_signal_matrix_{PRODUCT_CODE}_{start.isoformat()}_"
        f"{end.isoformat()}_{timestamp}_{suffix}"
    )
