"""R60 event threshold sensitivity review for CF research events."""

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
from cotton_factor.research_workbench import historical_event_explanation as r42

PRODUCT_CODE = "CF"
EVENT_THRESHOLD_SENSITIVITY_VERSION = "R60_event_threshold_sensitivity_v1"
OUTPUT_DIR = "event_threshold_sensitivity"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
DEFAULT_PRIMARY_HORIZON = 20
DEFAULT_QUANTILES = (0.90, 0.95, 0.975)
DEFAULT_MIN_OBSERVATION_COUNT = 20
INFO_SEVERITY = "INFO"
WARN_SEVERITY = "WARN"
HUMAN_REVIEW_REQUIRED = (
    "event_thresholds",
    "historical_event_interpretation",
    "threshold_quantile_selection",
    "forward_return_horizon_set",
    "cost_after_threshold_review",
)
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
class EventThresholdSensitivityWarningRecord:
    """Warning row for R60 event threshold sensitivity."""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable warning row."""
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
class ResearchEventThresholdSensitivityResult:
    """Result of building the R60 event threshold sensitivity pack."""

    product_code: str
    run_id: str
    start: date
    end: date
    primary_horizon: int
    horizons: tuple[int, ...]
    threshold_quantiles: tuple[float, ...]
    min_observation_count: int
    status: str
    detail_row_count: int
    summary_row_count: int
    annual_row_count: int
    review_decision_counts: dict[str, int]
    validation_daily_path: Path
    event_path: Path | None
    detail_parquet_path: Path
    detail_csv_path: Path
    summary_parquet_path: Path
    summary_csv_path: Path
    annual_parquet_path: Path
    annual_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    warning_records: tuple[EventThresholdSensitivityWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    @property
    def passed(self) -> bool:
        """R60 passes when review artifacts are inspectable."""
        return self.status in {
            "EVENT_THRESHOLD_SENSITIVITY_READY",
            "EVENT_THRESHOLD_SENSITIVITY_READY_WITH_WARNINGS",
        }

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "primary_horizon": self.primary_horizon,
            "horizons": list(self.horizons),
            "threshold_quantiles": list(self.threshold_quantiles),
            "min_observation_count": self.min_observation_count,
            "detail_row_count": self.detail_row_count,
            "summary_row_count": self.summary_row_count,
            "annual_row_count": self.annual_row_count,
            "review_decision_counts": self.review_decision_counts,
            "warning_count": self.warning_count,
            "warnings": [warning.to_summary() for warning in self.warning_records],
            "validation_daily_path": str(self.validation_daily_path),
            "event_path": None if self.event_path is None else str(self.event_path),
            "detail_parquet_path": str(self.detail_parquet_path),
            "summary_parquet_path": str(self.summary_parquet_path),
            "annual_parquet_path": str(self.annual_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "forward_returns_are_validation_labels": True,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(self.human_review_required),
        }


def build_cf_event_threshold_sensitivity(
    *,
    validation_daily_path: Path | None = None,
    event_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    primary_horizon: int = DEFAULT_PRIMARY_HORIZON,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    threshold_quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
    min_observation_count: int = DEFAULT_MIN_OBSERVATION_COUNT,
) -> ResearchEventThresholdSensitivityResult:
    """Build R60 threshold sensitivity tables from R36/R55 research artifacts."""
    normalized_quantiles = _normalize_quantiles(threshold_quantiles)
    r42._validate_horizons(horizons=horizons, primary_horizon=primary_horizon)
    validation_path = validation_daily_path or r42._default_validation_daily_path()
    validation = r42._load_validation_daily(validation_path)
    start = min(validation["trade_date"])
    end = max(validation["trade_date"])
    sensitivity_run_id = run_id or _default_run_id(start=start, end=end)
    primary_rows = r42._primary_rows(validation=validation, primary_horizon=primary_horizon)
    outcome_lookup = r42._outcome_lookup(validation=validation, horizons=horizons)
    baseline_event_path = event_path or _default_event_path()
    baseline_events = _load_event_table(baseline_event_path, horizons=horizons)

    detail = _detail_rows(
        run_id=sensitivity_run_id,
        baseline_events=baseline_events,
        primary_rows=primary_rows,
        outcome_lookup=outcome_lookup,
        horizons=horizons,
        threshold_quantiles=normalized_quantiles,
    )
    summary = _summary_rows(
        detail=detail,
        min_observation_count=min_observation_count,
    )
    annual = _annual_rows(detail=detail)
    review_decision_counts = _review_decision_counts(summary)
    warnings = tuple(
        _warning_records(
            run_id=sensitivity_run_id,
            summary=summary,
            baseline_events=baseline_events,
            min_observation_count=min_observation_count,
        )
    )
    status = (
        "EVENT_THRESHOLD_SENSITIVITY_READY"
        if not _has_warn(warnings)
        else "EVENT_THRESHOLD_SENSITIVITY_READY_WITH_WARNINGS"
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    result = ResearchEventThresholdSensitivityResult(
        product_code=PRODUCT_CODE,
        run_id=sensitivity_run_id,
        start=start,
        end=end,
        primary_horizon=primary_horizon,
        horizons=tuple(horizons),
        threshold_quantiles=normalized_quantiles,
        min_observation_count=min_observation_count,
        status=status,
        detail_row_count=int(len(detail)),
        summary_row_count=int(len(summary)),
        annual_row_count=int(len(annual)),
        review_decision_counts=review_decision_counts,
        validation_daily_path=validation_path,
        event_path=baseline_event_path,
        detail_parquet_path=paths["detail_parquet"],
        detail_csv_path=paths["detail_csv"],
        summary_parquet_path=paths["summary_parquet"],
        summary_csv_path=paths["summary_csv"],
        annual_parquet_path=paths["annual_parquet"],
        annual_csv_path=paths["annual_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=_markdown_path(start=start, end=end, report_output_dir=report_output_dir),
        json_path=_json_path(start=start, end=end, report_output_dir=report_output_dir),
        manifest_path=paths["manifest"],
        warning_records=warnings,
        human_review_required=_human_review_required(warnings),
    )
    _write_outputs(result=result, detail=detail, summary=summary, annual=annual)
    return result


def _normalize_quantiles(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values:
        raise ResearchWorkbenchError("threshold_quantiles must not be empty")
    normalized = tuple(sorted(dict.fromkeys(float(value) for value in values)))
    if any(value <= 0 or value >= 1 for value in normalized):
        raise ResearchWorkbenchError("threshold_quantiles must be between 0 and 1")
    return normalized


def _load_event_table(path: Path, *, horizons: tuple[int, ...]) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"R55 event table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    required = {
        "event_date",
        "event_type",
        "event_category",
        "forward_returns_are_event_labels",
    }
    missing = sorted(required - set(frame.columns))
    if "forward_returns_are_event_labels" in missing:
        # R42/R55 明细表用 forward_return_h* 命名，manifest/json 记录边界；
        # 明细表本身不一定有单独布尔列，下面用列名前缀做边界检查。
        missing.remove("forward_returns_are_event_labels")
    if missing:
        raise ResearchWorkbenchError(f"R55 event table missing columns: {missing}")
    for horizon in horizons:
        required_cols = {
            f"forward_return_h{horizon}",
            f"forward_label_available_h{horizon}",
            f"event_direction_hit_h{horizon}",
            f"execution_date_h{horizon}",
            f"exit_date_h{horizon}",
        }
        missing_horizon = sorted(required_cols - set(frame.columns))
        if missing_horizon:
            raise ResearchWorkbenchError(
                f"R55 event table missing horizon {horizon} columns: {missing_horizon}"
            )
    working = frame.copy()
    working["event_date"] = pd.to_datetime(working["event_date"], errors="coerce").dt.date
    working = working.dropna(subset=["event_date"])
    for horizon in horizons:
        working[f"forward_return_h{horizon}"] = pd.to_numeric(
            working[f"forward_return_h{horizon}"], errors="coerce"
        )
        working[f"forward_label_available_h{horizon}"] = _bool_series(
            working[f"forward_label_available_h{horizon}"]
        )
        working[f"event_direction_hit_h{horizon}"] = _bool_series(
            working[f"event_direction_hit_h{horizon}"]
        )
        execution = pd.to_datetime(
            working[f"execution_date_h{horizon}"], errors="coerce"
        ).dt.date
        bad_execution = execution <= working["event_date"]
        if bool(bad_execution.fillna(False).any()):
            raise ResearchWorkbenchError("R60 event rows violate T+1 execution timing")
    return working.sort_values(["event_date", "event_type"]).reset_index(drop=True)


def _detail_rows(
    *,
    run_id: str,
    baseline_events: pd.DataFrame,
    primary_rows: pd.DataFrame,
    outcome_lookup: dict[tuple[date, int], dict[str, object]],
    horizons: tuple[int, ...],
    threshold_quantiles: tuple[float, ...],
) -> pd.DataFrame:
    frames = [
        _baseline_detail_rows(run_id=run_id, events=baseline_events, horizons=horizons),
        _threshold_detail_rows(
            run_id=run_id,
            primary_rows=primary_rows,
            outcome_lookup=outcome_lookup,
            horizons=horizons,
            threshold_quantiles=threshold_quantiles,
        ),
    ]
    usable = [frame for frame in frames if not frame.empty]
    if not usable:
        return _empty_detail_frame()
    detail = pd.concat(usable, ignore_index=True)
    return detail.sort_values(
        ["threshold_scope", "event_type", "threshold_quantile", "event_date", "horizon"],
        na_position="first",
    ).reset_index(drop=True)


def _baseline_detail_rows(
    *,
    run_id: str,
    events: pd.DataFrame,
    horizons: tuple[int, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx, event in events.iterrows():
        for horizon in horizons:
            rows.append(
                _detail_row(
                    run_id=run_id,
                    threshold_scope="baseline_r55",
                    event_category=str(event.get("event_category")),
                    event_type=str(event.get("event_type")),
                    event_date=event["event_date"],
                    horizon=horizon,
                    forward_return=event.get(f"forward_return_h{horizon}"),
                    forward_label_available=event.get(
                        f"forward_label_available_h{horizon}"
                    ),
                    directional_hit=event.get(f"event_direction_hit_h{horizon}"),
                    execution_date=event.get(f"execution_date_h{horizon}"),
                    exit_date=event.get(f"exit_date_h{horizon}"),
                    threshold_quantile=None,
                    threshold_value=None,
                    event_intensity=_baseline_intensity(event),
                    source_event_id=f"baseline:{idx}",
                )
            )
    return pd.DataFrame(rows) if rows else _empty_detail_frame()


def _threshold_detail_rows(
    *,
    run_id: str,
    primary_rows: pd.DataFrame,
    outcome_lookup: dict[tuple[date, int], dict[str, object]],
    horizons: tuple[int, ...],
    threshold_quantiles: tuple[float, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    working = primary_rows.sort_values("trade_date").reset_index(drop=True).copy()
    working["curve_delta"] = pd.to_numeric(working.get("curve_slope"), errors="coerce").diff()
    for quantile in threshold_quantiles:
        rows.extend(
            _threshold_scope_rows(
                run_id=run_id,
                working=working,
                outcome_lookup=outcome_lookup,
                horizons=horizons,
                threshold_scope="oi_anomaly",
                event_category="oi_anomaly",
                event_type="持仓异常变化",
                value_column="main_oi_pressure",
                quantile=quantile,
            )
        )
        rows.extend(
            _threshold_scope_rows(
                run_id=run_id,
                working=working,
                outcome_lookup=outcome_lookup,
                horizons=horizons,
                threshold_scope="curve_shock",
                event_category="curve_shock",
                event_type="曲线结构突变",
                value_column="curve_delta",
                quantile=quantile,
            )
        )
    return pd.DataFrame(rows) if rows else _empty_detail_frame()


def _threshold_scope_rows(
    *,
    run_id: str,
    working: pd.DataFrame,
    outcome_lookup: dict[tuple[date, int], dict[str, object]],
    horizons: tuple[int, ...],
    threshold_scope: str,
    event_category: str,
    event_type: str,
    value_column: str,
    quantile: float,
) -> list[dict[str, object]]:
    values = pd.to_numeric(working[value_column], errors="coerce")
    threshold = _abs_quantile(values, quantile)
    if threshold is None:
        return []
    selected = working.loc[values.abs() >= threshold].copy()
    rows: list[dict[str, object]] = []
    for idx, event in selected.iterrows():
        event_date = event["trade_date"]
        for horizon in horizons:
            outcome = outcome_lookup.get((event_date, horizon), {})
            rows.append(
                _detail_row(
                    run_id=run_id,
                    threshold_scope=threshold_scope,
                    event_category=event_category,
                    event_type=event_type,
                    event_date=event_date,
                    horizon=horizon,
                    forward_return=outcome.get("forward_return"),
                    forward_label_available=outcome.get("forward_label_available"),
                    directional_hit=outcome.get("directional_hit"),
                    execution_date=outcome.get("execution_date"),
                    exit_date=outcome.get("exit_date"),
                    threshold_quantile=quantile,
                    threshold_value=threshold,
                    event_intensity=abs(float(values.loc[idx])),
                    source_event_id=f"{threshold_scope}:{quantile}:{idx}",
                )
            )
    return rows


def _detail_row(
    *,
    run_id: str,
    threshold_scope: str,
    event_category: str,
    event_type: str,
    event_date: object,
    horizon: int,
    forward_return: object,
    forward_label_available: object,
    directional_hit: object,
    execution_date: object,
    exit_date: object,
    threshold_quantile: float | None,
    threshold_value: float | None,
    event_intensity: float | None,
    source_event_id: str,
) -> dict[str, object]:
    event_date_value = _date_value(event_date)
    return {
        "run_id": run_id,
        "product_code": PRODUCT_CODE,
        "threshold_scope": threshold_scope,
        "event_category": event_category,
        "event_type": event_type,
        "threshold_quantile": threshold_quantile,
        "threshold_value": threshold_value,
        "event_intensity": event_intensity,
        "event_date": event_date_value,
        "event_year": None if event_date_value is None else event_date_value.year,
        "horizon": horizon,
        "forward_return": _float_or_none(forward_return),
        "forward_label_available": bool(forward_label_available),
        "directional_hit": bool(directional_hit),
        "execution_date": _date_text(execution_date),
        "exit_date": _date_text(exit_date),
        "source_event_id": source_event_id,
        "forward_returns_are_validation_labels": True,
        "interpretation_status": "HUMAN_REVIEW_REQUIRED",
        "trading_instruction": "not_a_trading_instruction",
    }


def _summary_rows(
    *,
    detail: pd.DataFrame,
    min_observation_count: int,
) -> pd.DataFrame:
    if detail.empty:
        return _empty_summary_frame()
    rows: list[dict[str, object]] = []
    group_columns = [
        "threshold_scope",
        "event_category",
        "event_type",
        "threshold_quantile",
        "threshold_value",
        "horizon",
    ]
    working = detail.copy()
    working["threshold_quantile"] = working["threshold_quantile"].fillna(-1.0)
    working["threshold_value"] = working["threshold_value"].fillna(float("nan"))
    for key, group in working.groupby(group_columns, dropna=False, sort=True):
        (
            threshold_scope,
            event_category,
            event_type,
            threshold_quantile,
            threshold_value,
            horizon,
        ) = key
        labelled = group.loc[group["forward_label_available"].astype(bool)].copy()
        annual_counts = labelled.groupby("event_year").size().to_dict()
        year_distribution = {
            str(int(year)): int(count)
            for year, count in sorted(annual_counts.items())
            if pd.notna(year)
        }
        observation_count = int(len(labelled))
        directional_hit_rate = _mean(labelled["directional_hit"].astype(float))
        mean_forward_return = _mean(labelled["forward_return"])
        median_forward_return = _median(labelled["forward_return"])
        min_annual_count = min(year_distribution.values()) if year_distribution else 0
        rows.append(
            {
                "product_code": PRODUCT_CODE,
                "threshold_scope": threshold_scope,
                "event_category": event_category,
                "event_type": event_type,
                "threshold_quantile": (
                    None if float(threshold_quantile) < 0 else float(threshold_quantile)
                ),
                "threshold_value": _float_or_none(threshold_value),
                "horizon": int(horizon),
                "event_count": int(group["source_event_id"].nunique()),
                "observation_count": observation_count,
                "mean_forward_return": mean_forward_return,
                "median_forward_return": median_forward_return,
                "directional_hit_rate": directional_hit_rate,
                "positive_return_rate": _mean((labelled["forward_return"] > 0).astype(float)),
                "year_count": len(year_distribution),
                "min_annual_observation_count": int(min_annual_count),
                "year_distribution": json.dumps(
                    year_distribution,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "review_decision_candidate": _review_decision(
                    observation_count=observation_count,
                    year_count=len(year_distribution),
                    min_annual_observation_count=int(min_annual_count),
                    directional_hit_rate=directional_hit_rate,
                    min_observation_count=min_observation_count,
                ),
                "interpretation_status": "HUMAN_REVIEW_REQUIRED",
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["threshold_scope", "event_type", "threshold_quantile", "horizon"],
        na_position="first",
    ).reset_index(drop=True)


def _annual_rows(*, detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return _empty_annual_frame()
    rows: list[dict[str, object]] = []
    group_columns = [
        "threshold_scope",
        "event_category",
        "event_type",
        "threshold_quantile",
        "threshold_value",
        "horizon",
        "event_year",
    ]
    working = detail.copy()
    working["threshold_quantile"] = working["threshold_quantile"].fillna(-1.0)
    working["threshold_value"] = working["threshold_value"].fillna(float("nan"))
    labelled = working.loc[working["forward_label_available"].astype(bool)].copy()
    for key, group in labelled.groupby(group_columns, dropna=False, sort=True):
        (
            threshold_scope,
            event_category,
            event_type,
            threshold_quantile,
            threshold_value,
            horizon,
            event_year,
        ) = key
        rows.append(
            {
                "product_code": PRODUCT_CODE,
                "threshold_scope": threshold_scope,
                "event_category": event_category,
                "event_type": event_type,
                "threshold_quantile": (
                    None if float(threshold_quantile) < 0 else float(threshold_quantile)
                ),
                "threshold_value": _float_or_none(threshold_value),
                "horizon": int(horizon),
                "event_year": int(event_year),
                "observation_count": int(len(group)),
                "mean_forward_return": _mean(group["forward_return"]),
                "median_forward_return": _median(group["forward_return"]),
                "directional_hit_rate": _mean(group["directional_hit"].astype(float)),
            }
        )
    if not rows:
        return _empty_annual_frame()
    return pd.DataFrame(rows).sort_values(
        ["threshold_scope", "event_type", "threshold_quantile", "horizon", "event_year"],
        na_position="first",
    ).reset_index(drop=True)


def _review_decision(
    *,
    observation_count: int,
    year_count: int,
    min_annual_observation_count: int,
    directional_hit_rate: float | None,
    min_observation_count: int,
) -> str:
    if observation_count == 0:
        return "REJECT"
    if (
        directional_hit_rate is not None
        and directional_hit_rate < 0.45
        and observation_count >= min_observation_count
    ):
        return "REJECT"
    if (
        observation_count >= min_observation_count
        and year_count >= 3
        and min_annual_observation_count >= 2
        and directional_hit_rate is not None
        and directional_hit_rate >= 0.55
    ):
        return "KEEP"
    if observation_count >= max(8, min_observation_count // 2) and year_count >= 2:
        return "WATCH"
    return "REVISE"


def _review_decision_counts(summary: pd.DataFrame) -> dict[str, int]:
    """汇总 R60 阈值候选分布，供周更 manifest 和审计报告直接读取。"""
    counts = {"KEEP": 0, "WATCH": 0, "REVISE": 0, "REJECT": 0}
    if summary.empty or "review_decision_candidate" not in summary.columns:
        return counts
    observed = summary["review_decision_candidate"].astype(str).value_counts().to_dict()
    for decision in counts:
        counts[decision] = int(observed.get(decision, 0))
    return counts


def _warning_records(
    *,
    run_id: str,
    summary: pd.DataFrame,
    baseline_events: pd.DataFrame,
    min_observation_count: int,
) -> list[EventThresholdSensitivityWarningRecord]:
    warnings = [
        EventThresholdSensitivityWarningRecord(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R60_FORWARD_RETURNS_ARE_VALIDATION_LABELS",
            warning_message=(
                "R60 forward_return 只作为历史后验验证标签；阈值结论必须人工复核。"
            ),
            affected_count=int(len(baseline_events)),
            human_review_required=("forward_return_horizon_set",),
        )
    ]
    if baseline_events.empty:
        warnings.append(
            EventThresholdSensitivityWarningRecord(
                run_id=run_id,
                section="baseline_events",
                severity=WARN_SEVERITY,
                warning_code="R60_BASELINE_EVENT_TABLE_EMPTY",
                warning_message="R55 baseline event table is empty.",
                affected_count=0,
                human_review_required=("historical_event_interpretation",),
            )
        )
    if summary.empty:
        warnings.append(
            EventThresholdSensitivityWarningRecord(
                run_id=run_id,
                section="summary",
                severity=WARN_SEVERITY,
                warning_code="R60_NO_THRESHOLD_SUMMARY_ROWS",
                warning_message="No threshold sensitivity summary rows were generated.",
                affected_count=0,
                human_review_required=("event_thresholds",),
            )
        )
        return warnings
    weak = summary.loc[
        summary["observation_count"].astype(int) < int(min_observation_count)
    ]
    if not weak.empty:
        warnings.append(
            EventThresholdSensitivityWarningRecord(
                run_id=run_id,
                section="sample_size",
                severity=WARN_SEVERITY,
                warning_code="R60_LOW_SAMPLE_THRESHOLD_GROUPS",
                warning_message=(
                    f"{len(weak)} threshold group(s) have observation_count "
                    f"below {min_observation_count}."
                ),
                affected_count=int(len(weak)),
                human_review_required=("threshold_quantile_selection",),
            )
        )
    return warnings


def _write_outputs(
    *,
    result: ResearchEventThresholdSensitivityResult,
    detail: pd.DataFrame,
    summary: pd.DataFrame,
    annual: pd.DataFrame,
) -> None:
    result.detail_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    detail.to_parquet(result.detail_parquet_path, index=False)
    detail.to_csv(result.detail_csv_path, index=False, encoding="utf-8-sig")
    summary.to_parquet(result.summary_parquet_path, index=False)
    summary.to_csv(result.summary_csv_path, index=False, encoding="utf-8-sig")
    annual.to_parquet(result.annual_parquet_path, index=False)
    annual.to_csv(result.annual_csv_path, index=False, encoding="utf-8-sig")
    _write_warning_csv(result)
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text(
        _render_markdown(result=result, summary=summary, annual=annual),
        encoding="utf-8",
    )
    result.json_path.write_text(
        json.dumps(
            _json_safe(
                {
                    "report_type": "event_threshold_sensitivity",
                    "rule_version": EVENT_THRESHOLD_SENSITIVITY_VERSION,
                    "generated_at": utc_now().isoformat(),
                    "summary": result.to_summary(),
                    "top_summary_rows": _top_summary_rows(summary),
                }
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result.manifest_path.write_text(
        json.dumps(
            _json_safe(
                {
                    "report_type": "event_threshold_sensitivity",
                    "rule_version": EVENT_THRESHOLD_SENSITIVITY_VERSION,
                    "generated_at": utc_now().isoformat(),
                    **result.to_summary(),
                }
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_warning_csv(result: ResearchEventThresholdSensitivityResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in result.warning_records])


def _render_markdown(
    *,
    result: ResearchEventThresholdSensitivityResult,
    summary: pd.DataFrame,
    annual: pd.DataFrame,
) -> str:
    lines = [
        f"# CF 事件阈值敏感性复核 R60 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 数据状态",
        "",
        "- 报告类型：`event_threshold_sensitivity`",
        f"- 状态：`{result.status}`",
        f"- Run ID：`{result.run_id}`",
        f"- 主观察周期：`{result.primary_horizon}`",
        f"- 观察周期：`{','.join(str(item) for item in result.horizons)}`",
        f"- 阈值分位：`{','.join(f'{item:.3f}' for item in result.threshold_quantiles)}`",
        f"- 最小样本阈值：`{result.min_observation_count}`",
        f"- 明细行数：`{result.detail_row_count}`",
        f"- 汇总行数：`{result.summary_row_count}`",
        "",
        "## 阈值敏感性总览",
        "",
        "| 阈值域 | 事件类型 | 分位 | 周期 | 样本 | 命中率 | "
        "均值收益 | 中位收益 | 年份数 | 复核候选 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in _top_summary_rows(summary):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("threshold_scope")),
                    str(row.get("event_type")),
                    _fmt_quantile(row.get("threshold_quantile")),
                    str(row.get("horizon")),
                    str(row.get("observation_count")),
                    _fmt_percent(row.get("directional_hit_rate")),
                    _fmt_percent(row.get("mean_forward_return")),
                    _fmt_percent(row.get("median_forward_return")),
                    str(row.get("year_count")),
                    str(row.get("review_decision_candidate")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 年度分布",
            "",
            f"- 年度分布表：`{result.annual_parquet_path}`",
            f"- 年度分布行数：`{len(annual)}`",
            "",
            "## 人工复核清单",
            "",
            "- `KEEP` 只表示历史样本候选稳定，仍需人工确认阈值、成本和行情阶段。",
            "- `WATCH` 表示样本或年度覆盖尚可，但不能直接固化。",
            "- `REVISE` 表示样本不足或年度分布不足，应调整阈值或事件定义。",
            "- `REJECT` 表示样本为空或足样本下命中率偏弱。",
            "- 持仓异常和曲线突变至少比较 0.90、0.95、0.975 三档分位。",
            "",
            "## 输出文件",
            "",
            f"- 事件阈值明细：`{result.detail_parquet_path}`",
            f"- 敏感性汇总：`{result.summary_parquet_path}`",
            f"- 年度分布：`{result.annual_parquet_path}`",
            f"- 警告清单：`{result.warning_csv_path}`",
            "",
            "## 研究边界",
            "",
            "- R60 不重新生成交易信号，只复核 R36/R55 历史研究产物。",
            "- forward_return 只作为历史后验验证标签。",
            "- 阈值结论必须 `HUMAN_REVIEW_REQUIRED`。",
            "- 本报告不构成交易指令。",
        ]
    )
    return "\n".join(lines) + "\n"


def _top_summary_rows(summary: pd.DataFrame) -> list[dict[str, object]]:
    if summary.empty:
        return []
    preferred = summary.loc[
        summary["horizon"].isin([1, 3, 5, 10, 20])
        & summary["threshold_scope"].isin(["baseline_r55", "oi_anomaly", "curve_shock"])
    ].copy()
    if preferred.empty:
        preferred = summary.copy()
    preferred["_decision_rank"] = preferred["review_decision_candidate"].map(
        {"KEEP": 0, "WATCH": 1, "REVISE": 2, "REJECT": 3}
    )
    return (
        preferred.sort_values(
            [
                "_decision_rank",
                "threshold_scope",
                "event_type",
                "threshold_quantile",
                "horizon",
            ],
            na_position="first",
        )
        .drop(columns=["_decision_rank"], errors="ignore")
        .head(24)
        .to_dict(orient="records")
    )


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_threshold_sensitivity"
    return {
        "detail_parquet": root / f"{stem}_detail.parquet",
        "detail_csv": root / f"{stem}_detail.csv",
        "summary_parquet": root / f"{stem}_summary.parquet",
        "summary_csv": root / f"{stem}_summary.csv",
        "annual_parquet": root / f"{stem}_annual.parquet",
        "annual_csv": root / f"{stem}_annual.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_threshold_sensitivity"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_threshold_sensitivity"
    return root / f"{stem}.json"


def _default_event_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "event_explanation"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_event_explanation_events.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R55 event parquet found under {root}")
    return candidates[-1]


def _default_run_id(*, start: date, end: date) -> str:
    return (
        f"r60_event_threshold_sensitivity_{PRODUCT_CODE}_{start.isoformat()}_"
        f"{end.isoformat()}_{uuid.uuid4().hex[:8]}"
    )


def _empty_detail_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "run_id",
            "product_code",
            "threshold_scope",
            "event_category",
            "event_type",
            "threshold_quantile",
            "threshold_value",
            "event_intensity",
            "event_date",
            "event_year",
            "horizon",
            "forward_return",
            "forward_label_available",
            "directional_hit",
            "execution_date",
            "exit_date",
            "source_event_id",
            "forward_returns_are_validation_labels",
            "interpretation_status",
            "trading_instruction",
        ]
    )


def _empty_summary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "product_code",
            "threshold_scope",
            "event_category",
            "event_type",
            "threshold_quantile",
            "threshold_value",
            "horizon",
            "event_count",
            "observation_count",
            "mean_forward_return",
            "median_forward_return",
            "directional_hit_rate",
            "positive_return_rate",
            "year_count",
            "min_annual_observation_count",
            "year_distribution",
            "review_decision_candidate",
            "interpretation_status",
            "forward_returns_are_validation_labels",
            "trading_instruction",
        ]
    )


def _empty_annual_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "product_code",
            "threshold_scope",
            "event_category",
            "event_type",
            "threshold_quantile",
            "threshold_value",
            "horizon",
            "event_year",
            "observation_count",
            "mean_forward_return",
            "median_forward_return",
            "directional_hit_rate",
        ]
    )


def _baseline_intensity(event: pd.Series) -> float | None:
    if str(event.get("event_category")) == "oi_anomaly":
        return _abs_float_or_none(event.get("event_oi_pressure"))
    if str(event.get("event_category")) == "curve_shock":
        return _abs_float_or_none(event.get("event_curve_slope"))
    return None


def _abs_quantile(values: object, quantile: float) -> float | None:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna().abs()
    if series.empty:
        return None
    return float(series.quantile(quantile))


def _human_review_required(
    warnings: tuple[EventThresholdSensitivityWarningRecord, ...],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        values.extend(warning.human_review_required)
    return tuple(dict.fromkeys(values))


def _has_warn(warnings: tuple[EventThresholdSensitivityWarningRecord, ...]) -> bool:
    return any(warning.severity != INFO_SEVERITY for warning in warnings)


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _mean(values: object) -> float | None:
    series = pd.Series(values).dropna()
    if series.empty:
        return None
    return float(series.mean())


def _median(values: object) -> float | None:
    series = pd.Series(values).dropna()
    if series.empty:
        return None
    return float(series.median())


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _abs_float_or_none(value: object) -> float | None:
    numeric = _float_or_none(value)
    return None if numeric is None else abs(numeric)


def _date_value(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _date_text(value: object) -> str | None:
    date_value = _date_value(value)
    return None if date_value is None else date_value.isoformat()


def _fmt_percent(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "-"
    return f"{numeric:.2%}"


def _fmt_quantile(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "baseline"
    return f"{numeric:.3f}"


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value
