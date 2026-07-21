"""R69 CF futures-option divergence battle research."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
FUTURES_OPTION_DIVERGENCE_VERSION = "R69_futures_option_divergence_battle_v1"
OUTPUT_DIR = "futures_option_divergence"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20, 40)
DEFAULT_DEAD_ZONE_BPS = 10
DEFAULT_MIN_SAMPLE_SIZE = 30
INFO_SEVERITY = "INFO"
WARN_SEVERITY = "WARN"
WINNER_FUTURES = "FUTURES_WIN"
WINNER_OPTIONS = "OPTIONS_WIN"
WINNER_UNRESOLVED = "UNRESOLVED"
WINNER_FUTURES_FOLLOW = "FUTURES_FOLLOW_THROUGH"
WINNER_FUTURES_FAILED = "FUTURES_FAILED"
WINNER_NO_OPTION_SIDE = "NO_DIRECTIONAL_OPTION_SIDE"
WINNER_NO_FORWARD_LABEL = "NO_FORWARD_LABEL_CURRENT_ONLY"
HUMAN_REVIEW_REQUIRED = (
    "option_proxy_interpretation",
    "futures_option_divergence_definition",
    "forward_return_horizon_set",
    "dead_zone_threshold",
    "sample_size_evidence_level",
    "option_iv_greek_proxy_boundary",
)
REQUIRED_VALIDATION_COLUMNS = {
    "trade_date",
    "horizon",
    "main_contract",
    "direction",
    "trend_phase",
    "confidence",
    "oi_signal",
    "option_signal",
    "option_signal_direction",
    "option_factor_status",
    "option_atm_iv_rank",
    "option_pcr_volume",
    "option_pcr_oi",
    "option_skew_proxy",
    "forward_return",
    "forward_label_available",
    "execution_date",
    "exit_date",
    "forward_returns_are_validation_labels",
}
WARNING_COLUMNS = (
    "run_id",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)


@dataclass(frozen=True)
class FuturesOptionDivergenceWarningRecord:
    """Warning row for R69 futures-option divergence research."""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-safe warning summary."""
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV row."""
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
class ResearchFuturesOptionDivergenceResult:
    """Result of building R69 futures-option divergence battle research."""

    product_code: str
    run_id: str
    start: date
    end: date
    horizons: tuple[int, ...]
    dead_zone_bps: int
    min_sample_size: int
    status: str
    event_row_count: int
    labelled_event_row_count: int
    directional_divergence_count: int
    main_winner_label: str
    average_resolution_horizon: float | None
    validation_daily_path: Path
    option_factor_path: Path | None
    event_lifecycle_episode_path: Path | None
    event_lifecycle_tbm_path: Path | None
    event_parquet_path: Path
    event_csv_path: Path
    summary_by_horizon_parquet_path: Path
    summary_by_horizon_csv_path: Path
    summary_by_node_parquet_path: Path
    summary_by_node_csv_path: Path
    resolution_timing_parquet_path: Path
    resolution_timing_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    warning_records: tuple[FuturesOptionDivergenceWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    @property
    def passed(self) -> bool:
        """Return whether the R69 research pack is inspectable."""
        return self.status in {
            "FUTURES_OPTION_DIVERGENCE_READY",
            "FUTURES_OPTION_DIVERGENCE_READY_WITH_WARNINGS",
        }

    def to_summary(self) -> dict[str, object]:
        """Return compact CLI output."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "horizons": list(self.horizons),
            "dead_zone_bps": self.dead_zone_bps,
            "min_sample_size": self.min_sample_size,
            "event_row_count": self.event_row_count,
            "labelled_event_row_count": self.labelled_event_row_count,
            "directional_divergence_count": self.directional_divergence_count,
            "main_winner_label": self.main_winner_label,
            "average_resolution_horizon": self.average_resolution_horizon,
            "warning_count": self.warning_count,
            "warnings": [warning.to_summary() for warning in self.warning_records],
            "validation_daily_path": str(self.validation_daily_path),
            "option_factor_path": (
                None if self.option_factor_path is None else str(self.option_factor_path)
            ),
            "event_lifecycle_episode_path": (
                None
                if self.event_lifecycle_episode_path is None
                else str(self.event_lifecycle_episode_path)
            ),
            "event_lifecycle_tbm_path": (
                None
                if self.event_lifecycle_tbm_path is None
                else str(self.event_lifecycle_tbm_path)
            ),
            "event_parquet_path": str(self.event_parquet_path),
            "summary_by_horizon_parquet_path": str(self.summary_by_horizon_parquet_path),
            "summary_by_node_parquet_path": str(self.summary_by_node_parquet_path),
            "resolution_timing_parquet_path": str(self.resolution_timing_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "forward_returns_are_validation_labels": True,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(self.human_review_required),
        }


def build_cf_futures_option_divergence_research(
    *,
    signal_matrix_validation_path: Path | None = None,
    option_factor_path: Path | None = None,
    event_lifecycle_episode_path: Path | None = None,
    event_lifecycle_tbm_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> ResearchFuturesOptionDivergenceResult:
    """Build R69 futures-option divergence battle labels from R36 validation rows."""
    normalized_horizons = _normalize_horizons(horizons)
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("dead_zone_bps must be non-negative")
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("min_sample_size must be positive")

    validation_path = signal_matrix_validation_path or _default_validation_daily_path()
    _validate_optional_path(option_factor_path, "option factor table")
    _validate_optional_path(event_lifecycle_episode_path, "event lifecycle episode table")
    _validate_optional_path(event_lifecycle_tbm_path, "event lifecycle TBM table")
    validation = _load_validation_daily(validation_path, horizons=normalized_horizons)
    start = min(validation["trade_date"])
    end = max(validation["trade_date"])
    divergence_run_id = run_id or _default_run_id(start=start, end=end)
    dead_zone = dead_zone_bps / 10_000

    # R69 只消费 R36 已生成的 T+1 后验标签，不重新生成信号，也不回写主模型方向。
    event_rows = _event_rows(
        validation=validation,
        run_id=divergence_run_id,
        dead_zone=dead_zone,
    )
    tbm_lookup = _load_tbm_lookup(event_lifecycle_tbm_path)
    resolution_rows = _resolution_timing_rows(
        event_rows=event_rows,
        run_id=divergence_run_id,
        tbm_lookup=tbm_lookup,
    )
    horizon_summary = _summary_rows(
        event_rows=event_rows,
        run_id=divergence_run_id,
        group_keys=("divergence_type", "horizon"),
        min_sample_size=min_sample_size,
        dead_zone=dead_zone,
        end=end,
    )
    node_summary = _summary_rows(
        event_rows=event_rows,
        run_id=divergence_run_id,
        group_keys=(
            "divergence_type",
            "trend_phase",
            "confidence",
            "option_signal",
            "iv_rank_bucket",
            "skew_bucket",
            "pcr_bucket",
            "oi_signal",
        ),
        min_sample_size=min_sample_size,
        dead_zone=dead_zone,
        end=end,
    )
    warnings = tuple(
        _warning_records(
            run_id=divergence_run_id,
            event_rows=event_rows,
            node_summary=node_summary,
            validation=validation,
            min_sample_size=min_sample_size,
            event_lifecycle_tbm_path=event_lifecycle_tbm_path,
        )
    )
    status = (
        "FUTURES_OPTION_DIVERGENCE_READY"
        if not _has_warn(warnings)
        else "FUTURES_OPTION_DIVERGENCE_READY_WITH_WARNINGS"
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    result = ResearchFuturesOptionDivergenceResult(
        product_code=PRODUCT_CODE,
        run_id=divergence_run_id,
        start=start,
        end=end,
        horizons=normalized_horizons,
        dead_zone_bps=dead_zone_bps,
        min_sample_size=min_sample_size,
        status=status,
        event_row_count=len(event_rows),
        labelled_event_row_count=_labelled_count(event_rows),
        directional_divergence_count=sum(
            1 for row in event_rows if row["divergence_type"] == "directional_divergence"
        ),
        main_winner_label=_main_winner_label(event_rows),
        average_resolution_horizon=_average_resolution_horizon(resolution_rows),
        validation_daily_path=validation_path,
        option_factor_path=option_factor_path,
        event_lifecycle_episode_path=event_lifecycle_episode_path,
        event_lifecycle_tbm_path=event_lifecycle_tbm_path,
        event_parquet_path=paths["event_parquet"],
        event_csv_path=paths["event_csv"],
        summary_by_horizon_parquet_path=paths["summary_by_horizon_parquet"],
        summary_by_horizon_csv_path=paths["summary_by_horizon_csv"],
        summary_by_node_parquet_path=paths["summary_by_node_parquet"],
        summary_by_node_csv_path=paths["summary_by_node_csv"],
        resolution_timing_parquet_path=paths["resolution_timing_parquet"],
        resolution_timing_csv_path=paths["resolution_timing_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=_markdown_path(start=start, end=end, report_output_dir=report_output_dir),
        json_path=_json_path(start=start, end=end, report_output_dir=report_output_dir),
        manifest_path=paths["manifest"],
        warning_records=warnings,
        human_review_required=_human_review_required(warnings),
    )
    _write_outputs(
        result=result,
        event_rows=event_rows,
        horizon_summary=horizon_summary,
        node_summary=node_summary,
        resolution_rows=resolution_rows,
    )
    return result


def _normalize_horizons(values: tuple[int, ...]) -> tuple[int, ...]:
    if not values:
        raise ResearchWorkbenchError("horizons must not be empty")
    normalized = tuple(sorted(dict.fromkeys(int(value) for value in values)))
    if any(value <= 0 for value in normalized):
        raise ResearchWorkbenchError("horizons must contain positive integers")
    return normalized


def _validate_optional_path(path: Path | None, label: str) -> None:
    if path is not None and not path.exists():
        raise ResearchWorkbenchError(f"{label} not found: {path}")


def _default_validation_daily_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    matches = sorted(root.glob("*_signal_matrix_validation_daily.parquet"))
    if not matches:
        raise ResearchWorkbenchError(f"R69 signal matrix validation daily table not found: {root}")
    return matches[-1]


def _load_validation_daily(path: Path, *, horizons: tuple[int, ...]) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"signal matrix validation daily table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(REQUIRED_VALIDATION_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(
            f"signal matrix validation daily table missing columns: {missing}"
        )
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["execution_date"] = pd.to_datetime(
        working["execution_date"],
        errors="coerce",
    ).dt.date
    working["exit_date"] = pd.to_datetime(working["exit_date"], errors="coerce").dt.date
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    working["forward_return"] = pd.to_numeric(working["forward_return"], errors="coerce")
    for column in (
        "option_atm_iv_rank",
        "option_pcr_volume",
        "option_pcr_oi",
        "option_skew_proxy",
    ):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working["forward_label_available"] = _bool_series(working["forward_label_available"])
    working["forward_returns_are_validation_labels"] = _bool_series(
        working["forward_returns_are_validation_labels"]
    )
    working = working.dropna(subset=["trade_date", "horizon", "main_contract"])
    working["horizon"] = working["horizon"].astype(int)
    working = working.loc[working["horizon"].isin(horizons)].copy()
    if working.empty:
        raise ResearchWorkbenchError("R69 validation table has no rows for requested horizons")
    labelled = working.loc[working["forward_label_available"]].copy()
    if labelled.empty:
        raise ResearchWorkbenchError("R69 requires at least one forward validation label")
    if not labelled["forward_returns_are_validation_labels"].all():
        raise ResearchWorkbenchError("R69 requires forward returns to be validation labels")
    return working.sort_values(["trade_date", "horizon"]).reset_index(drop=True)


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.map(
        lambda value: str(value).strip().lower() in {"true", "1", "yes", "y"}
        if pd.notna(value)
        else False
    )


def _event_rows(
    *,
    validation: pd.DataFrame,
    run_id: str,
    dead_zone: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sequence = 0
    for item in validation.to_dict(orient="records"):
        futures_direction = str(item.get("direction") or "unknown")
        if futures_direction not in {"long", "short"}:
            continue
        divergence_type = _divergence_type(item)
        if divergence_type is None:
            continue
        sequence += 1
        forward_return = _float_or_none(item.get("forward_return"))
        winner_label = _winner_label(
            futures_direction=futures_direction,
            option_direction=str(item.get("option_signal_direction") or "unknown"),
            forward_return=forward_return,
            forward_label_available=bool(item.get("forward_label_available")),
            dead_zone=dead_zone,
        )
        futures_directional_return = _directional_return(
            direction=futures_direction,
            forward_return=forward_return,
        )
        option_directional_return = _directional_return(
            direction=str(item.get("option_signal_direction") or "unknown"),
            forward_return=forward_return,
        )
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "event_id": f"{run_id}_divergence_{sequence:06d}",
                "trade_date": item["trade_date"],
                "horizon": int(item["horizon"]),
                "main_contract": str(item["main_contract"]),
                "futures_direction": futures_direction,
                "option_direction": str(item.get("option_signal_direction") or "unknown"),
                "divergence_type": divergence_type,
                "option_signal": str(item.get("option_signal") or "unknown"),
                "option_factor_status": str(item.get("option_factor_status") or "unknown"),
                "trend_phase": str(item.get("trend_phase") or "unknown"),
                "confidence": str(item.get("confidence") or "unknown"),
                "oi_signal": str(item.get("oi_signal") or "unknown"),
                "iv_rank_bucket": _iv_rank_bucket(_float_or_none(item.get("option_atm_iv_rank"))),
                "skew_bucket": _skew_bucket(_float_or_none(item.get("option_skew_proxy"))),
                "pcr_bucket": _pcr_bucket(
                    _float_or_none(item.get("option_pcr_volume")),
                    _float_or_none(item.get("option_pcr_oi")),
                ),
                "option_atm_iv_rank": _float_or_none(item.get("option_atm_iv_rank")),
                "option_pcr_volume": _float_or_none(item.get("option_pcr_volume")),
                "option_pcr_oi": _float_or_none(item.get("option_pcr_oi")),
                "option_skew_proxy": _float_or_none(item.get("option_skew_proxy")),
                "forward_return": forward_return,
                "futures_directional_forward_return": futures_directional_return,
                "option_directional_forward_return": option_directional_return,
                "forward_label_available": bool(item.get("forward_label_available")),
                "execution_date": item.get("execution_date"),
                "exit_date": item.get("exit_date"),
                "winner_label": winner_label,
                "resolution_horizon": (
                    int(item["horizon"]) if _is_resolved_winner(winner_label) else None
                ),
                "forward_returns_are_validation_labels": True,
                "label_rule_version": FUTURES_OPTION_DIVERGENCE_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    if not rows:
        raise ResearchWorkbenchError("R69 found no usable futures-option divergence rows")
    return rows


def _divergence_type(item: dict[str, object]) -> str | None:
    option_signal = str(item.get("option_signal") or "unknown")
    futures_direction = str(item.get("direction") or "unknown")
    iv_rank = _float_or_none(item.get("option_atm_iv_rank"))
    if option_signal == "volatility_risk":
        return "volatility_risk_override"
    if option_signal.startswith("diverge_"):
        return "directional_divergence"
    if option_signal.startswith("confirm_"):
        return "option_confirmation"
    if futures_direction in {"long", "short"} and option_signal in {
        "option_neutral",
        "option_watch",
    }:
        return "volatility_non_confirmation"
    if futures_direction in {"long", "short"} and iv_rank is not None and iv_rank <= 0.10:
        return "volatility_non_confirmation"
    return None


def _winner_label(
    *,
    futures_direction: str,
    option_direction: str,
    forward_return: float | None,
    forward_label_available: bool,
    dead_zone: float,
) -> str:
    if not forward_label_available or forward_return is None:
        return WINNER_NO_FORWARD_LABEL
    futures_directional_return = _directional_return(
        direction=futures_direction,
        forward_return=forward_return,
    )
    if futures_directional_return is None:
        return WINNER_NO_OPTION_SIDE
    if abs(futures_directional_return) <= dead_zone:
        return WINNER_UNRESOLVED

    # 有明确反向期权方向时，才存在“期货方 vs 期权方”的胜负关系。
    if option_direction in {"long", "short"} and option_direction != futures_direction:
        if futures_directional_return > dead_zone:
            return WINNER_FUTURES
        option_directional_return = _directional_return(
            direction=option_direction,
            forward_return=forward_return,
        )
        if option_directional_return is not None and option_directional_return > dead_zone:
            return WINNER_OPTIONS
        return WINNER_UNRESOLVED

    # 期权同向或无明确方向时，只判断期货结构是否跟随，不误判为期权方胜利。
    if option_direction not in {"long", "short"}:
        return (
            WINNER_FUTURES_FOLLOW
            if futures_directional_return > dead_zone
            else WINNER_FUTURES_FAILED
        )
    return (
        WINNER_FUTURES_FOLLOW
        if futures_directional_return > dead_zone
        else WINNER_FUTURES_FAILED
    )


def _directional_return(*, direction: str, forward_return: float | None) -> float | None:
    if forward_return is None or direction not in {"long", "short"}:
        return None
    return forward_return if direction == "long" else -forward_return


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iv_rank_bucket(value: float | None) -> str:
    if value is None:
        return "iv_unknown"
    if value <= 0.10:
        return "iv_low_0_10"
    if value >= 0.80:
        return "iv_high_80_100"
    return "iv_normal"


def _skew_bucket(value: float | None) -> str:
    if value is None:
        return "skew_unknown"
    if value < -0.001:
        return "skew_put_discount_or_call_rich"
    if value > 0.001:
        return "skew_put_rich_or_call_discount"
    return "skew_neutral"


def _pcr_bucket(pcr_volume: float | None, pcr_oi: float | None) -> str:
    values = [value for value in (pcr_volume, pcr_oi) if value is not None]
    if not values:
        return "pcr_unknown"
    average = sum(values) / len(values)
    if average < 0.80:
        return "pcr_low"
    if average > 1.20:
        return "pcr_high"
    return "pcr_neutral"


def _summary_rows(
    *,
    event_rows: list[dict[str, object]],
    run_id: str,
    group_keys: tuple[str, ...],
    min_sample_size: int,
    dead_zone: float,
    end: date,
) -> list[dict[str, object]]:
    frame = pd.DataFrame(event_rows)
    summary: list[dict[str, object]] = []
    recent_start = end - timedelta(days=365 * 2)
    for key_values, group in frame.groupby(list(group_keys), dropna=False):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        labelled = group.loc[group["forward_label_available"]].copy()
        winner_counts = labelled["winner_label"].value_counts().to_dict()
        sample_count = int(len(labelled))
        futures_win_count = int(
            labelled["winner_label"].isin({WINNER_FUTURES, WINNER_FUTURES_FOLLOW}).sum()
        )
        options_win_count = int(labelled["winner_label"].eq(WINNER_OPTIONS).sum())
        unresolved_count = int(labelled["winner_label"].eq(WINNER_UNRESOLVED).sum())
        directional_returns = pd.to_numeric(
            labelled["futures_directional_forward_return"],
            errors="coerce",
        ).dropna()
        resolved = labelled.loc[labelled["winner_label"].map(_is_resolved_winner)].copy()
        recent = labelled.loc[labelled["trade_date"] >= recent_start].copy()
        row = {
            "run_id": run_id,
            "product_code": PRODUCT_CODE,
            "grouping": "+".join(group_keys),
            "sample_count": sample_count,
            "total_row_count": int(len(group)),
            "futures_win_count": futures_win_count,
            "options_win_count": options_win_count,
            "unresolved_count": unresolved_count,
            "futures_win_rate": _safe_ratio(futures_win_count, sample_count),
            "options_win_rate": _safe_ratio(options_win_count, sample_count),
            "unresolved_rate": _safe_ratio(unresolved_count, sample_count),
            "avg_futures_directional_forward_return": _mean(directional_returns),
            "median_futures_directional_forward_return": _median(directional_returns),
            "earliest_resolution_horizon": _min_or_none(resolved["horizon"]),
            "average_resolution_horizon": _mean(resolved["horizon"]),
            "dominant_winner_label": _dominant_winner(winner_counts),
            "recent_sample_count": int(len(recent)),
            "recent_futures_win_rate": _winner_rate(
                recent,
                {WINNER_FUTURES, WINNER_FUTURES_FOLLOW},
            ),
            "recent_options_win_rate": _winner_rate(recent, {WINNER_OPTIONS}),
            "recent_stability": _recent_stability(labelled=labelled, recent=recent),
            "evidence_level": _evidence_level(
                sample_count=sample_count,
                futures_win_count=futures_win_count,
                options_win_count=options_win_count,
                avg_directional_return=_mean(directional_returns),
                min_sample_size=min_sample_size,
                dead_zone=dead_zone,
            ),
            "label_rule_version": FUTURES_OPTION_DIVERGENCE_VERSION,
            "trading_instruction": "not_a_trading_instruction",
        }
        row.update({group_keys[index]: key_values[index] for index in range(len(group_keys))})
        summary.append(row)
    return sorted(
        summary,
        key=lambda row: (
            str(row["grouping"]),
            str(row.get("divergence_type", "")),
            int(row.get("horizon", 0) or 0),
            -int(row["sample_count"]),
        ),
    )


def _load_tbm_lookup(path: Path | None) -> dict[tuple[date, str], dict[str, object]]:
    if path is None:
        return {}
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    required = {"start_date", "direction", "tbm_label", "days_to_barrier"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"event lifecycle TBM table missing columns: {missing}")
    working = frame.copy()
    working["start_date"] = pd.to_datetime(working["start_date"], errors="coerce").dt.date
    return {
        (row.start_date, str(row.direction)): row._asdict()
        for row in working.itertuples(index=False)
        if row.start_date is not None
    }


def _resolution_timing_rows(
    *,
    event_rows: list[dict[str, object]],
    run_id: str,
    tbm_lookup: dict[tuple[date, str], dict[str, object]],
) -> list[dict[str, object]]:
    frame = pd.DataFrame(event_rows)
    rows: list[dict[str, object]] = []
    keys = [
        "trade_date",
        "main_contract",
        "futures_direction",
        "option_direction",
        "option_signal",
        "divergence_type",
    ]
    for key_values, group in frame.groupby(keys, dropna=False):
        values = dict(zip(keys, key_values, strict=True))
        labelled = group.loc[group["forward_label_available"]].sort_values("horizon")
        resolved = labelled.loc[labelled["winner_label"].map(_is_resolved_winner)]
        first = None if resolved.empty else resolved.iloc[0].to_dict()
        tbm = tbm_lookup.get((values["trade_date"], values["futures_direction"]), {})
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                **values,
                "resolved": first is not None,
                "resolved_winner_label": (
                    WINNER_UNRESOLVED if first is None else str(first["winner_label"])
                ),
                "earliest_resolution_horizon": (
                    None if first is None else int(first["horizon"])
                ),
                "earliest_resolution_exit_date": (
                    None if first is None else first.get("exit_date")
                ),
                "earliest_directional_forward_return": (
                    None if first is None else first.get("futures_directional_forward_return")
                ),
                "tbm_label": tbm.get("tbm_label"),
                "tbm_days_to_barrier": tbm.get("days_to_barrier"),
                "label_rule_version": FUTURES_OPTION_DIVERGENCE_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return sorted(rows, key=lambda row: (row["trade_date"], str(row["option_signal"])))


def _warning_records(
    *,
    run_id: str,
    event_rows: list[dict[str, object]],
    node_summary: list[dict[str, object]],
    validation: pd.DataFrame,
    min_sample_size: int,
    event_lifecycle_tbm_path: Path | None,
) -> list[FuturesOptionDivergenceWarningRecord]:
    warnings = [
        FuturesOptionDivergenceWarningRecord(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="RESEARCH_ONLY_NOT_TRADING_INSTRUCTION",
            warning_message=(
                "R69 只做期货-期权背离历史后验研究，不修改 composite_score，"
                "不自动反转方向，也不构成交易指令。"
            ),
            affected_count=len(event_rows),
            human_review_required=("futures_option_divergence_definition",),
        )
    ]
    no_label_count = sum(not bool(row["forward_label_available"]) for row in event_rows)
    if no_label_count:
        warnings.append(
            FuturesOptionDivergenceWarningRecord(
                run_id=run_id,
                section="forward_labels",
                severity=WARN_SEVERITY,
                warning_code="CURRENT_ROWS_WITHOUT_FORWARD_LABEL",
                warning_message=(
                    "部分最新行没有 forward return，只能作为当前结构观察，不能进入胜负统计。"
                ),
                affected_count=no_label_count,
                human_review_required=("forward_return_horizon_set",),
            )
        )
    divergence_count = sum(
        1 for row in event_rows if row["divergence_type"] == "directional_divergence"
    )
    if divergence_count == 0:
        warnings.append(
            FuturesOptionDivergenceWarningRecord(
                run_id=run_id,
                section="divergence_sample",
                severity=WARN_SEVERITY,
                warning_code="NO_DIRECTIONAL_DIVERGENCE_SAMPLE",
                warning_message="未发现明确的期货-期权方向背离样本。",
                affected_count=0,
                human_review_required=("futures_option_divergence_definition",),
            )
        )
    weak_nodes = [
        row for row in node_summary if row.get("evidence_level") == "WEAK_OR_SMALL_SAMPLE"
    ]
    if weak_nodes:
        warnings.append(
            FuturesOptionDivergenceWarningRecord(
                run_id=run_id,
                section="sample_size",
                severity=WARN_SEVERITY,
                warning_code="NODE_SMALL_SAMPLE_DOWNGRADED",
                warning_message=(
                    f"部分结构性矛盾节点样本数低于 {min_sample_size}，已强制降级为观察。"
                ),
                affected_count=len(weak_nodes),
                human_review_required=("sample_size_evidence_level",),
            )
        )
    if event_lifecycle_tbm_path is None:
        warnings.append(
            FuturesOptionDivergenceWarningRecord(
                run_id=run_id,
                section="event_lifecycle",
                severity=INFO_SEVERITY,
                warning_code="TBM_CONTEXT_NOT_CONNECTED",
                warning_message="本次 R69 未接入 R68 TBM 表，解决周期仅使用固定 forward horizon。",
                affected_count=len(validation),
                human_review_required=("forward_return_horizon_set",),
            )
        )
    return warnings


def _write_outputs(
    *,
    result: ResearchFuturesOptionDivergenceResult,
    event_rows: list[dict[str, object]],
    horizon_summary: list[dict[str, object]],
    node_summary: list[dict[str, object]],
    resolution_rows: list[dict[str, object]],
) -> None:
    _write_table(event_rows, result.event_parquet_path, result.event_csv_path)
    _write_table(
        horizon_summary,
        result.summary_by_horizon_parquet_path,
        result.summary_by_horizon_csv_path,
    )
    _write_table(node_summary, result.summary_by_node_parquet_path, result.summary_by_node_csv_path)
    _write_table(
        resolution_rows,
        result.resolution_timing_parquet_path,
        result.resolution_timing_csv_path,
    )
    _write_warning_csv(result.warning_records, result.warning_csv_path)
    _write_markdown(
        result=result,
        horizon_summary=horizon_summary,
        node_summary=node_summary,
        resolution_rows=resolution_rows,
    )
    _write_json(
        result=result,
        horizon_summary=horizon_summary,
        node_summary=node_summary,
        resolution_rows=resolution_rows,
    )
    _write_manifest(result=result)


def _write_table(rows: list[dict[str, object]], parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([_json_safe(row) for row in rows])
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    warnings: tuple[FuturesOptionDivergenceWarningRecord, ...],
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
    result: ResearchFuturesOptionDivergenceResult,
    horizon_summary: list[dict[str, object]],
    node_summary: list[dict[str, object]],
    resolution_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    top_horizon = _top_rows(horizon_summary, limit=12)
    top_nodes = _top_rows(node_summary, limit=12)
    current_rows = _latest_rows_for_report(resolution_rows, limit=8)
    lines = [
        f"# CF 期货-期权背离胜负研究 R69（{result.start} 至 {result.end}）",
        "",
        "## 数据状态",
        f"- 研究状态：`{result.status}`",
        f"- 输入 R36 后验验证表：`{result.validation_daily_path}`",
        f"- 样本周期：`{result.start}` 至 `{result.end}`",
        f"- 观察周期：`{', '.join(str(item) + 'D' for item in result.horizons)}`",
        f"- dead zone：`{result.dead_zone_bps} bps`",
        f"- 背离/确认/波动非确认事件行数：`{result.event_row_count}`",
        f"- 明确方向背离行数：`{result.directional_divergence_count}`",
        "",
        "## 研究定义",
        "- 期货方使用 R35/R36 `direction`，代表期货多因子方向。",
        "- 期权方使用 `option_signal_direction`，只在 long/short 明确且与期货相反时"
        "判定期权方胜负。",
        "- 胜负标签使用 R36 `forward_return`，按 T 日信号、T+1 执行、T+1+horizon 退出。",
        "- `forward_return` 仅为历史后验验证标签，不参与最新日信号生成。",
        "",
        "## 总体胜负",
        f"- 主要胜方标签：`{result.main_winner_label}`",
        f"- 平均最早解决周期：`{_fmt_number(result.average_resolution_horizon)}` 个交易日",
        "- `FUTURES_WIN` 表示后验价格沿期货方向运行；`OPTIONS_WIN` 表示后验价格沿"
        "期权反向结构运行。",
        "- `UNRESOLVED` 表示收益落入 dead zone；期权中性/watch 不会被强行判定为期权胜。",
        "",
        "## 背离类型与周期",
        "| 背离类型 | 周期 | 样本数 | 期货胜率 | 期权胜率 | 平均方向收益 | 证据等级 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in top_horizon:
        lines.append(
            "| "
            f"{row.get('divergence_type')} | "
            f"{row.get('horizon')}D | "
            f"{row.get('sample_count')} | "
            f"{_fmt_percent(row.get('futures_win_rate'))} | "
            f"{_fmt_percent(row.get('options_win_rate'))} | "
            f"{_fmt_percent(row.get('avg_futures_directional_forward_return'))} | "
            f"{row.get('evidence_level')} |"
        )
    lines.extend(
        [
            "",
            "## 趋势阶段与结构性矛盾节点",
            "| 背离类型 | 趋势阶段 | 期权信号 | IV 桶 | PCR 桶 | 样本数 | 主导标签 | 证据等级 |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in top_nodes:
        lines.append(
            "| "
            f"{row.get('divergence_type')} | "
            f"{row.get('trend_phase')} | "
            f"{row.get('option_signal')} | "
            f"{row.get('iv_rank_bucket')} | "
            f"{row.get('pcr_bucket')} | "
            f"{row.get('sample_count')} | "
            f"{row.get('dominant_winner_label')} | "
            f"{row.get('evidence_level')} |"
        )
    lines.extend(
        [
            "",
            "## 解决周期",
            "| 日期 | 合约 | 背离类型 | 期货方向 | 期权方向 | 最早胜负 | 最早周期 | TBM 标签 |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for row in current_rows:
        lines.append(
            "| "
            f"{row.get('trade_date')} | "
            f"{row.get('main_contract')} | "
            f"{row.get('divergence_type')} | "
            f"{row.get('futures_direction')} | "
            f"{row.get('option_direction')} | "
            f"{row.get('resolved_winner_label')} | "
            f"{_fmt_number(row.get('earliest_resolution_horizon'))} | "
            f"{row.get('tbm_label') or '-'} |"
        )
    lines.extend(
        [
            "",
            "## 当前样本映射",
            "- 最新交易日如果缺少 forward label，只能进入当前结构观察，不能进入胜负统计。",
            "- 后续 R70 可把本报告中的高层结论接入 validated brief 和发布包。",
            "",
            "## 研究边界",
            "- 本报告不构成交易指令。",
            "- R69 不修改 `composite_score`，不把期权直接写入期货主模型权重。",
            "- R69 不自动反转做空；背离只作为期货方/期权方被后验验证的研究证据。",
            "- 期权 PCR、ATM IV rank、skew 均为研究 proxy；美式期权 IV/Greek 不是精确风险暴露。",
            "",
            "## 人工复核项",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchFuturesOptionDivergenceResult,
    horizon_summary: list[dict[str, object]],
    node_summary: list[dict[str, object]],
    resolution_rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "futures_option_divergence_research",
        "result": result.to_summary(),
        "horizon_summary": [_json_safe(row) for row in horizon_summary],
        "node_summary": [_json_safe(row) for row in node_summary],
        "resolution_timing": [_json_safe(row) for row in resolution_rows],
        "research_boundary": {
            "forward_returns_are_validation_labels": True,
            "auto_reverse_allowed": False,
            "trading_instruction": "not_a_trading_instruction",
            "option_iv_greek_is_proxy": True,
        },
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_manifest(result: ResearchFuturesOptionDivergenceResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": result.run_id,
        "product_code": result.product_code,
        "artifact_type": "futures_option_divergence_research",
        "version": FUTURES_OPTION_DIVERGENCE_VERSION,
        "created_at": utc_now().isoformat(),
        "inputs": {
            "validation_daily_path": str(result.validation_daily_path),
            "option_factor_path": (
                None if result.option_factor_path is None else str(result.option_factor_path)
            ),
            "event_lifecycle_episode_path": (
                None
                if result.event_lifecycle_episode_path is None
                else str(result.event_lifecycle_episode_path)
            ),
            "event_lifecycle_tbm_path": (
                None
                if result.event_lifecycle_tbm_path is None
                else str(result.event_lifecycle_tbm_path)
            ),
        },
        "outputs": result.to_summary(),
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _output_paths(start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_futures_option_divergence"
    return {
        "event_parquet": root / f"{stem}_divergence_event_daily.parquet",
        "event_csv": root / f"{stem}_divergence_event_daily.csv",
        "summary_by_horizon_parquet": root / f"{stem}_summary_by_horizon.parquet",
        "summary_by_horizon_csv": root / f"{stem}_summary_by_horizon.csv",
        "summary_by_node_parquet": root / f"{stem}_summary_by_node.parquet",
        "summary_by_node_csv": root / f"{stem}_summary_by_node.csv",
        "resolution_timing_parquet": root / f"{stem}_resolution_timing.parquet",
        "resolution_timing_csv": root / f"{stem}_resolution_timing.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_futures_option_divergence"
    return root / f"{stem}.md"


def _json_path(start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_futures_option_divergence"
    return root / f"{stem}.json"


def _default_run_id(*, start: date, end: date) -> str:
    return (
        f"r69_futures_option_divergence_{PRODUCT_CODE}_"
        f"{start.isoformat()}_{end.isoformat()}_{uuid.uuid4().hex[:8]}"
    )


def _has_warn(warnings: tuple[FuturesOptionDivergenceWarningRecord, ...]) -> bool:
    return any(warning.severity != INFO_SEVERITY for warning in warnings)


def _human_review_required(
    warnings: tuple[FuturesOptionDivergenceWarningRecord, ...],
) -> tuple[str, ...]:
    values = set(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        values.update(warning.human_review_required)
    return tuple(sorted(values))


def _labelled_count(rows: list[dict[str, object]]) -> int:
    return sum(1 for row in rows if bool(row.get("forward_label_available")))


def _main_winner_label(rows: list[dict[str, object]]) -> str:
    labelled = [row for row in rows if bool(row.get("forward_label_available"))]
    if not labelled:
        return "NO_LABELLED_SAMPLE"
    counts = pd.Series([row["winner_label"] for row in labelled]).value_counts()
    return str(counts.index[0])


def _average_resolution_horizon(rows: list[dict[str, object]]) -> float | None:
    values = [
        _float_or_none(row.get("earliest_resolution_horizon"))
        for row in rows
        if row.get("resolved")
    ]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return float(sum(values) / len(values))


def _is_resolved_winner(value: object) -> bool:
    return str(value) in {
        WINNER_FUTURES,
        WINNER_OPTIONS,
        WINNER_FUTURES_FOLLOW,
        WINNER_FUTURES_FAILED,
    }


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _winner_rate(frame: pd.DataFrame, labels: set[str]) -> float | None:
    if frame.empty:
        return None
    return float(frame["winner_label"].isin(labels).mean())


def _mean(values: object) -> float | None:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return None if series.empty else float(series.mean())


def _median(values: object) -> float | None:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return None if series.empty else float(series.median())


def _min_or_none(values: object) -> float | None:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return None if series.empty else float(series.min())


def _dominant_winner(counts: dict[str, int]) -> str:
    if not counts:
        return "NO_LABELLED_SAMPLE"
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _recent_stability(*, labelled: pd.DataFrame, recent: pd.DataFrame) -> str:
    if labelled.empty or recent.empty:
        return "INSUFFICIENT_RECENT"
    full = _dominant_winner(labelled["winner_label"].value_counts().to_dict())
    recent_winner = _dominant_winner(recent["winner_label"].value_counts().to_dict())
    return "STABLE" if full == recent_winner else "DRIFT"


def _evidence_level(
    *,
    sample_count: int,
    futures_win_count: int,
    options_win_count: int,
    avg_directional_return: float | None,
    min_sample_size: int,
    dead_zone: float,
) -> str:
    if sample_count < min_sample_size:
        return "WEAK_OR_SMALL_SAMPLE"
    dominant_rate = max(futures_win_count, options_win_count) / sample_count
    if (
        avg_directional_return is not None
        and dominant_rate >= 0.55
        and abs(avg_directional_return) > dead_zone
    ):
        return "READY"
    return "WATCH"


def _top_rows(rows: list[dict[str, object]], *, limit: int) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("evidence_level") != "READY",
            -int(row.get("sample_count") or 0),
            str(row.get("divergence_type", "")),
        ),
    )[:limit]


def _latest_rows_for_report(
    rows: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    return sorted(rows, key=lambda row: str(row.get("trade_date")), reverse=True)[:limit]


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _fmt_percent(value: object) -> str:
    number = _float_or_none(value)
    return "-" if number is None else f"{number:.2%}"


def _fmt_number(value: object) -> str:
    number = _float_or_none(value)
    return "-" if number is None else f"{number:.2f}"
