"""R41 historical evidence pack for CF multi-factor research."""

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
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.signal_matrix_validation import (
    SIGNAL_MATRIX_VALIDATION_VERSION,
)
from cotton_factor.research_workbench.signal_threshold_research import (
    SIGNAL_THRESHOLD_RESEARCH_VERSION,
)

PRODUCT_CODE = "CF"
HISTORICAL_EVIDENCE_VERSION = "R41_historical_multifactor_evidence_v1"
OUTPUT_DIR = "historical_evidence"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
DEFAULT_COST_SCENARIOS = {
    "no_cost": 0.0,
    "normal_cost": 5.0,
    "conservative_cost": 10.0,
}
HUMAN_REVIEW_REQUIRED = (
    "historical_evidence_interpretation",
    "cost_model_parameters",
    "factor_thresholds",
    "signal_matrix_weighting",
    "forward_return_horizon_set",
    "contract_rule_assumptions",
)

REQUIRED_VALIDATION_COLUMNS = {
    "trade_date",
    "horizon",
    "direction",
    "forward_return",
    "forward_label_available",
    "window_id",
    "execution_date",
    "exit_date",
    "directional_hit",
    "trend_phase",
    "confidence",
    "forward_returns_are_validation_labels",
}

REQUIRED_THRESHOLD_COLUMNS = {
    "scheme_id",
    "scheme_label_cn",
    "horizon",
    "observation_count",
    "mean_forward_return",
    "directional_hit_rate",
    "candidate_status",
}

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
class HistoricalEvidenceWarningRecord:
    """Warning row for R41 historical evidence."""

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
class ResearchHistoricalEvidenceResult:
    """Result of building R41 historical evidence artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    validation_row_count: int
    evidence_summary_row_count: int
    decay_row_count: int
    stability_row_count: int
    warning_records: tuple[HistoricalEvidenceWarningRecord, ...]
    evidence_summary_parquet_path: Path
    evidence_summary_csv_path: Path
    decay_parquet_path: Path
    decay_csv_path: Path
    stability_parquet_path: Path
    stability_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_quote_path: Path
    signal_matrix_path: Path
    validation_daily_path: Path
    validation_window_summary_path: Path
    threshold_weighting_path: Path
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
            "validation_row_count": self.validation_row_count,
            "evidence_summary_row_count": self.evidence_summary_row_count,
            "decay_row_count": self.decay_row_count,
            "stability_row_count": self.stability_row_count,
            "warning_count": self.warning_count,
            "evidence_summary_parquet_path": str(self.evidence_summary_parquet_path),
            "evidence_summary_csv_path": str(self.evidence_summary_csv_path),
            "decay_parquet_path": str(self.decay_parquet_path),
            "decay_csv_path": str(self.decay_csv_path),
            "stability_parquet_path": str(self.stability_parquet_path),
            "stability_csv_path": str(self.stability_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "signal_matrix_path": str(self.signal_matrix_path),
            "validation_daily_path": str(self.validation_daily_path),
            "validation_window_summary_path": str(self.validation_window_summary_path),
            "threshold_weighting_path": str(self.threshold_weighting_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_historical_evidence_pack(
    *,
    core_quote_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    validation_daily_path: Path | None = None,
    validation_window_summary_path: Path | None = None,
    threshold_weighting_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    cost_scenarios: dict[str, float] | None = None,
) -> ResearchHistoricalEvidenceResult:
    """Build R41 historical multi-factor evidence from R36/R37 artifacts."""
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    matrix_path = signal_matrix_path or _default_signal_matrix_path()
    validation_path = validation_daily_path or _default_validation_daily_path()
    window_path = validation_window_summary_path or _default_validation_window_summary_path()
    threshold_path = threshold_weighting_path or _default_threshold_weighting_path()
    scenarios = _resolve_cost_scenarios(cost_scenarios)

    core_status = _load_core_status(quote_path)
    matrix_status = _load_signal_matrix_status(matrix_path)
    validation = _load_validation_daily(validation_path)
    window_summary = _load_validation_window_summary(window_path)
    threshold = _load_threshold_weighting(threshold_path)
    start = min(validation["trade_date"])
    end = max(validation["trade_date"])
    evidence_run_id = run_id or _default_run_id(start=start, end=end)

    # R41 只在历史验证包中使用 forward_return，禁止把这些标签写入 latest signal brief。
    evidence_rows = _evidence_summary_rows(
        validation=validation,
        threshold=threshold,
        cost_scenarios=scenarios,
        run_id=evidence_run_id,
    )
    decay_rows = _decay_rows(
        validation=validation,
        threshold=threshold,
        cost_scenarios=scenarios,
        run_id=evidence_run_id,
    )
    stability_rows = _stability_rows(threshold=threshold, run_id=evidence_run_id)
    warnings = _warning_records(
        run_id=evidence_run_id,
        validation=validation,
        evidence_rows=evidence_rows,
        window_summary=window_summary,
        matrix_status=matrix_status,
        core_status=core_status,
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    json_path = _json_path(start=start, end=end, report_output_dir=report_output_dir)
    result = ResearchHistoricalEvidenceResult(
        product_code=PRODUCT_CODE,
        run_id=evidence_run_id,
        start=start,
        end=end,
        validation_row_count=len(validation),
        evidence_summary_row_count=len(evidence_rows),
        decay_row_count=len(decay_rows),
        stability_row_count=len(stability_rows),
        warning_records=warnings,
        evidence_summary_parquet_path=paths["evidence_summary_parquet"],
        evidence_summary_csv_path=paths["evidence_summary_csv"],
        decay_parquet_path=paths["decay_parquet"],
        decay_csv_path=paths["decay_csv"],
        stability_parquet_path=paths["stability_parquet"],
        stability_csv_path=paths["stability_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        signal_matrix_path=matrix_path,
        validation_daily_path=validation_path,
        validation_window_summary_path=window_path,
        threshold_weighting_path=threshold_path,
        human_review_required=_human_review_required(warnings),
    )
    _write_table(
        rows=evidence_rows,
        parquet_path=result.evidence_summary_parquet_path,
        csv_path=result.evidence_summary_csv_path,
    )
    _write_table(
        rows=decay_rows,
        parquet_path=result.decay_parquet_path,
        csv_path=result.decay_csv_path,
    )
    _write_table(
        rows=stability_rows,
        parquet_path=result.stability_parquet_path,
        csv_path=result.stability_csv_path,
    )
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_markdown(
        result=result,
        evidence_rows=evidence_rows,
        decay_rows=decay_rows,
        stability_rows=stability_rows,
        scenarios=scenarios,
    )
    _write_json(
        result=result,
        evidence_rows=evidence_rows,
        decay_rows=decay_rows,
        stability_rows=stability_rows,
        scenarios=scenarios,
    )
    _write_manifest(result=result, scenarios=scenarios)
    return result


def _load_core_status(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"core quote table not found: {path}")
    frame = pd.read_parquet(path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError("core quote table missing trade_date column")
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    return {
        "row_count": int(len(frame)),
        "start": min(dates).isoformat(),
        "end": max(dates).isoformat(),
    }


def _load_signal_matrix_status(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"signal matrix table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    forbidden = [column for column in frame.columns if str(column).startswith("forward_return")]
    if forbidden:
        raise ResearchWorkbenchError(
            f"R35 signal matrix must not contain forward return columns: {forbidden}"
        )
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError("signal matrix table missing trade_date column")
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    return {
        "row_count": int(len(frame)),
        "start": min(dates).isoformat(),
        "end": max(dates).isoformat(),
    }


def _load_validation_daily(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"signal validation daily table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(REQUIRED_VALIDATION_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"signal validation daily table missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["execution_date"] = pd.to_datetime(working["execution_date"], errors="coerce").dt.date
    working["exit_date"] = pd.to_datetime(working["exit_date"], errors="coerce").dt.date
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    working["forward_return"] = pd.to_numeric(working["forward_return"], errors="coerce")
    working["forward_label_available"] = _bool_series(working["forward_label_available"])
    working["forward_returns_are_validation_labels"] = _bool_series(
        working["forward_returns_are_validation_labels"]
    )
    working["directional_hit"] = _bool_series(working["directional_hit"])
    working = working.dropna(subset=["trade_date", "horizon"])
    working["horizon"] = working["horizon"].astype(int)
    labelled = working.loc[working["forward_label_available"]].copy()
    if labelled.empty:
        raise ResearchWorkbenchError("R41 historical evidence requires labelled validation rows")
    if not labelled["forward_returns_are_validation_labels"].all():
        raise ResearchWorkbenchError(
            "R41 requires forward returns to be marked as validation labels"
        )
    bad_execution = labelled.loc[labelled["execution_date"] <= labelled["trade_date"]]
    if not bad_execution.empty:
        raise ResearchWorkbenchError("R41 validation rows violate T+1 execution timing")
    bad_exit = labelled.loc[labelled["exit_date"] < labelled["execution_date"]]
    if not bad_exit.empty:
        raise ResearchWorkbenchError("R41 validation rows have exit_date before execution_date")
    return working.sort_values(["trade_date", "horizon"]).reset_index(drop=True)


def _load_validation_window_summary(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"validation window summary not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    required = {"window_id", "horizon", "observation_count", "mean_forward_return"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"validation window summary missing columns: {missing}")
    return frame.copy()


def _load_threshold_weighting(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"threshold weighting table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    forbidden = [column for column in frame.columns if str(column).startswith("forward_return")]
    if forbidden:
        raise ResearchWorkbenchError(
            f"R37 weighting table must be aggregated; forbidden columns: {forbidden}"
        )
    missing = sorted(REQUIRED_THRESHOLD_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"threshold weighting table missing columns: {missing}")
    working = frame.copy()
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce").astype("Int64")
    working = working.dropna(subset=["horizon"])
    working["horizon"] = working["horizon"].astype(int)
    for column in ("observation_count", "mean_forward_return", "directional_hit_rate"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return working.reset_index(drop=True)


def _evidence_summary_rows(
    *,
    validation: pd.DataFrame,
    threshold: pd.DataFrame,
    cost_scenarios: dict[str, float],
    run_id: str,
) -> list[dict[str, object]]:
    labelled = _labelled_validation(validation)
    rows: list[dict[str, object]] = []
    group_columns = {
        "overall": [],
        "window": ["window_id"],
        "trend_phase": ["trend_phase"],
        "confidence": ["confidence"],
        "direction": ["direction"],
    }
    for group_type, columns in group_columns.items():
        grouped_columns = ["horizon", *columns]
        for keys, group in labelled.groupby(grouped_columns, dropna=False, sort=True):
            key_values = keys if isinstance(keys, tuple) else (keys,)
            horizon = int(key_values[0])
            group_value = "ALL" if not columns else str(key_values[1])
            rows.extend(
                _scenario_metric_rows(
                    run_id=run_id,
                    group_type=group_type,
                    group_value=group_value,
                    horizon=horizon,
                    frame=group,
                    cost_scenarios=cost_scenarios,
                    threshold_status=_best_threshold_status(threshold=threshold, horizon=horizon),
                )
            )
    return rows


def _decay_rows(
    *,
    validation: pd.DataFrame,
    threshold: pd.DataFrame,
    cost_scenarios: dict[str, float],
    run_id: str,
) -> list[dict[str, object]]:
    labelled = _labelled_validation(validation)
    rows: list[dict[str, object]] = []
    for horizon, group in labelled.groupby("horizon", sort=True):
        scenario_means = {
            f"mean_net_return_{name}": _mean(_net_returns(group, cost_bps=cost_bps))
            for name, cost_bps in cost_scenarios.items()
        }
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "horizon": int(horizon),
                "observation_count": int(len(group)),
                "mean_forward_return": _mean(group["forward_return"]),
                "median_forward_return": _median(group["forward_return"]),
                "directional_hit_rate": _mean(group["directional_hit"].astype(float)),
                "mean_gross_return": _mean(_gross_returns(group)),
                **scenario_means,
                "best_threshold_status": _best_threshold_status(
                    threshold=threshold,
                    horizon=int(horizon),
                ),
                "stability_status": _stability_status(
                    observation_count=int(len(group)),
                    directional_hit_rate=_mean(group["directional_hit"].astype(float)),
                    mean_net_return=scenario_means.get("mean_net_return_normal_cost"),
                    threshold_status=_best_threshold_status(
                        threshold=threshold,
                        horizon=int(horizon),
                    ),
                ),
                "evidence_rule_version": HISTORICAL_EVIDENCE_VERSION,
            }
        )
    return rows


def _stability_rows(*, threshold: pd.DataFrame, run_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in threshold.sort_values(["horizon", "candidate_status", "scheme_id"]).itertuples():
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "horizon": int(row.horizon),
                "scheme_id": str(row.scheme_id),
                "scheme_label_cn": str(row.scheme_label_cn),
                "observation_count": _int_or_none(row.observation_count),
                "mean_forward_return": _float_or_none(row.mean_forward_return),
                "directional_hit_rate": _float_or_none(row.directional_hit_rate),
                "candidate_status": str(row.candidate_status),
                "stability_status": _candidate_stability_status(str(row.candidate_status)),
                "source_threshold_rule_version": SIGNAL_THRESHOLD_RESEARCH_VERSION,
                "evidence_rule_version": HISTORICAL_EVIDENCE_VERSION,
            }
        )
    return rows


def _scenario_metric_rows(
    *,
    run_id: str,
    group_type: str,
    group_value: str,
    horizon: int,
    frame: pd.DataFrame,
    cost_scenarios: dict[str, float],
    threshold_status: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    gross = _gross_returns(frame)
    hit_rate = _mean(frame["directional_hit"].astype(float))
    for scenario_name, cost_bps in cost_scenarios.items():
        net = _net_returns(frame, cost_bps=cost_bps)
        mean_net = _mean(net)
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "group_type": group_type,
                "group_value": group_value,
                "horizon": horizon,
                "cost_scenario": scenario_name,
                "cost_bps": float(cost_bps),
                "observation_count": int(len(frame)),
                "directional_hit_count": int(frame["directional_hit"].sum()),
                "directional_hit_rate": hit_rate,
                "mean_forward_return": _mean(frame["forward_return"]),
                "median_forward_return": _median(frame["forward_return"]),
                "mean_gross_return": _mean(gross),
                "median_gross_return": _median(gross),
                "mean_net_return": mean_net,
                "median_net_return": _median(net),
                "positive_net_rate": _mean((net > 0).astype(float)),
                "best_threshold_status": threshold_status,
                "stability_status": _stability_status(
                    observation_count=int(len(frame)),
                    directional_hit_rate=hit_rate,
                    mean_net_return=mean_net,
                    threshold_status=threshold_status,
                ),
                "forward_returns_are_validation_labels": True,
                "evidence_rule_version": HISTORICAL_EVIDENCE_VERSION,
            }
        )
    return rows


def _labelled_validation(validation: pd.DataFrame) -> pd.DataFrame:
    labelled = validation.loc[
        validation["forward_label_available"] & validation["forward_return"].notna()
    ].copy()
    if labelled.empty:
        raise ResearchWorkbenchError("R41 has no labelled validation rows after filtering")
    return labelled


def _gross_returns(frame: pd.DataFrame) -> pd.Series:
    direction = frame["direction"].astype(str).str.lower().map({"long": 1.0, "short": -1.0})
    direction = direction.fillna(0.0)
    return direction * frame["forward_return"].astype(float)


def _net_returns(frame: pd.DataFrame, *, cost_bps: float) -> pd.Series:
    gross = _gross_returns(frame)
    traded = frame["direction"].astype(str).str.lower().isin({"long", "short"})
    return gross - traded.astype(float) * (float(cost_bps) / 10_000.0)


def _best_threshold_status(*, threshold: pd.DataFrame, horizon: int) -> str:
    subset = threshold.loc[threshold["horizon"].eq(horizon)].copy()
    if subset.empty:
        return "WEAK_OR_UNSTABLE"
    order = {"READY_CANDIDATE": 0, "WATCH_CANDIDATE": 1, "WEAK_OR_UNSTABLE": 2}
    subset["_status_order"] = subset["candidate_status"].map(order).fillna(9)
    selected = subset.sort_values(
        ["_status_order", "directional_hit_rate", "observation_count"],
        ascending=[True, False, False],
    ).iloc[0]
    return str(selected["candidate_status"])


def _stability_status(
    *,
    observation_count: int,
    directional_hit_rate: float | None,
    mean_net_return: float | None,
    threshold_status: str,
) -> str:
    if (
        threshold_status == "READY_CANDIDATE"
        and observation_count >= 30
        and (directional_hit_rate or 0.0) >= 0.55
        and (mean_net_return or 0.0) > 0
    ):
        return "READY"
    if (
        threshold_status in {"READY_CANDIDATE", "WATCH_CANDIDATE"}
        and observation_count >= 10
        and ((directional_hit_rate or 0.0) >= 0.52 or (mean_net_return or 0.0) > 0)
    ):
        return "WATCH"
    return "WEAK_OR_UNSTABLE"


def _candidate_stability_status(candidate_status: str) -> str:
    if candidate_status == "READY_CANDIDATE":
        return "READY"
    if candidate_status == "WATCH_CANDIDATE":
        return "WATCH"
    return "WEAK_OR_UNSTABLE"


def _warning_records(
    *,
    run_id: str,
    validation: pd.DataFrame,
    evidence_rows: list[dict[str, object]],
    window_summary: pd.DataFrame,
    matrix_status: dict[str, object],
    core_status: dict[str, object],
) -> tuple[HistoricalEvidenceWarningRecord, ...]:
    warnings: list[HistoricalEvidenceWarningRecord] = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R41_FORWARD_RETURNS_ARE_HISTORICAL_LABELS",
            warning_message=(
                "R41 使用 forward_return 仅作为历史后验验证标签，"
                "不进入 latest signal-only brief。"
            ),
            affected_count=int(validation["forward_label_available"].sum()),
            human_review_required=("forward_return_horizon_set",),
        )
    ]
    unavailable = int((~validation["forward_label_available"]).sum())
    if unavailable:
        warnings.append(
            _warning(
                run_id=run_id,
                section="validation_daily",
                severity=WARNING_SEVERITY,
                warning_code="R41_FORWARD_LABEL_UNAVAILABLE_ROWS",
                warning_message="部分历史验证行缺少 forward-return 标签，已从统计中剔除。",
                affected_count=unavailable,
                human_review_required=("forward_return_horizon_set",),
            )
        )
    weak_rows = sum(1 for row in evidence_rows if row["stability_status"] == "WEAK_OR_UNSTABLE")
    if weak_rows:
        warnings.append(
            _warning(
                run_id=run_id,
                section="stability",
                severity=WARNING_SEVERITY,
                warning_code="R41_WEAK_OR_UNSTABLE_GROUPS",
                warning_message="存在历史证据不足或成本后不稳定的分组，不能解释为稳定交易规则。",
                affected_count=weak_rows,
                human_review_required=("factor_thresholds", "cost_model_parameters"),
            )
        )
    if window_summary.empty:
        warnings.append(
            _warning(
                run_id=run_id,
                section="window_summary",
                severity=WARNING_SEVERITY,
                warning_code="R41_WINDOW_SUMMARY_EMPTY",
                warning_message="R36 window summary 为空，年度稳定性证据不足。",
                affected_count=0,
                human_review_required=("rolling_window_definition",),
            )
        )
    if matrix_status["start"] != core_status["start"] or matrix_status["end"] != core_status["end"]:
        warnings.append(
            _warning(
                run_id=run_id,
                section="input_alignment",
                severity=WARNING_SEVERITY,
                warning_code="R41_MATRIX_CORE_DATE_RANGE_MISMATCH",
                warning_message=(
                    "R35 signal matrix 与 core quote 日期范围不完全一致，"
                    "需复核输入版本。"
                ),
                affected_count=0,
                human_review_required=("signal_matrix_weighting", "contract_rule_assumptions"),
            )
        )
    return tuple(warnings)


def _warning(
    *,
    run_id: str,
    section: str,
    severity: str,
    warning_code: str,
    warning_message: str,
    affected_count: int,
    human_review_required: tuple[str, ...],
) -> HistoricalEvidenceWarningRecord:
    return HistoricalEvidenceWarningRecord(
        run_id=run_id,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        affected_count=affected_count,
        human_review_required=human_review_required,
    )


def _human_review_required(
    warnings: tuple[HistoricalEvidenceWarningRecord, ...],
) -> tuple[str, ...]:
    values = set(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        values.update(warning.human_review_required)
    return tuple(sorted(values))


def _write_table(*, rows: list[dict[str, object]], parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[HistoricalEvidenceWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchHistoricalEvidenceResult,
    evidence_rows: list[dict[str, object]],
    decay_rows: list[dict[str, object]],
    stability_rows: list[dict[str, object]],
    scenarios: dict[str, float],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    overall_normal = [
        row
        for row in evidence_rows
        if row["group_type"] == "overall" and row["cost_scenario"] == "normal_cost"
    ]
    ready_rows = [row for row in stability_rows if row["stability_status"] == "READY"]
    lines = [
        f"# CF 历史多因子证据包 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        "- 报告类型：`historical_evidence_pack`",
        f"- Run ID：`{result.run_id}`",
        f"- R36 历史验证行数：`{result.validation_row_count}`",
        f"- R37 参数候选行数：`{result.stability_row_count}`",
        f"- 成本场景：`{_scenario_text(scenarios)}`",
        f"- warning_count：`{result.warning_count}`",
        "",
        "## 二、研究边界",
        "",
        "- forward_return 只作为历史后验验证标签。",
        "- 本报告不进入 latest signal-only brief，不构成交易指令。",
        "- 成本后统计只用于稳定性复核，不覆盖原始 forward_return。",
        "",
        "## 三、多周期信号衰减",
        "",
        "| Horizon | 样本 | 方向调整毛收益 | 方向命中率 | normal cost 后均值 | 稳定性 |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in sorted(decay_rows, key=lambda item: int(item["horizon"])):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["horizon"]),
                    str(row["observation_count"]),
                    _fmt_percent(row["mean_gross_return"]),
                    _fmt_percent(row["directional_hit_rate"]),
                    _fmt_percent(row.get("mean_net_return_normal_cost")),
                    str(row["stability_status"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 四、normal cost 分组摘要",
            "",
            "| 分组 | 周期 | 样本 | 净收益均值 | 方向命中率 | 阈值状态 | 稳定性 |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in sorted(overall_normal, key=lambda item: int(item["horizon"])):
        lines.append(_evidence_markdown_row(row))
    lines.extend(
        [
            "",
            "## 五、参数稳定性候选",
            "",
            "| 周期 | 方案 | 样本 | 平均后验收益 | 方向命中率 | 候选状态 | 稳定性 |",
            "| ---: | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    selected = ready_rows[:8] if ready_rows else stability_rows[:8]
    for row in selected:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["horizon"]),
                    str(row["scheme_label_cn"]),
                    str(row["observation_count"]),
                    _fmt_percent(row["mean_forward_return"]),
                    _fmt_percent(row["directional_hit_rate"]),
                    str(row["candidate_status"]),
                    str(row["stability_status"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 六、人工复核",
            "",
        ]
    )
    for item in result.human_review_required:
        lines.append(f"- `{item}`")
    lines.append("")
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")


def _evidence_markdown_row(row: dict[str, object]) -> str:
    return (
        "| "
        + " | ".join(
            [
                str(row["group_value"]),
                str(row["horizon"]),
                str(row["observation_count"]),
                _fmt_percent(row["mean_net_return"]),
                _fmt_percent(row["directional_hit_rate"]),
                str(row["best_threshold_status"]),
                str(row["stability_status"]),
            ]
        )
        + " |"
    )


def _write_json(
    *,
    result: ResearchHistoricalEvidenceResult,
    evidence_rows: list[dict[str, object]],
    decay_rows: list[dict[str, object]],
    stability_rows: list[dict[str, object]],
    scenarios: dict[str, float],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "historical_evidence_pack",
        "rule_version": HISTORICAL_EVIDENCE_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "cost_scenarios": scenarios,
        "forward_returns_are_validation_labels": True,
        "no_latest_signal_dependency": True,
        "evidence_summary_sample": evidence_rows[:20],
        "decay_rows": decay_rows,
        "stability_sample": stability_rows[:20],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_manifest(
    *,
    result: ResearchHistoricalEvidenceResult,
    scenarios: dict[str, float],
) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "report_type": "historical_evidence_pack",
        "rule_version": HISTORICAL_EVIDENCE_VERSION,
        "data_start": result.start.isoformat(),
        "data_end": result.end.isoformat(),
        "generated_at": utc_now().isoformat(),
        "forward_returns_are_validation_labels": True,
        "contains_latest_signal_only_inputs": False,
        "source_rule_versions": [
            SIGNAL_MATRIX_VALIDATION_VERSION,
            SIGNAL_THRESHOLD_RESEARCH_VERSION,
        ],
        "cost_scenarios": scenarios,
        "core_quote_path": str(result.core_quote_path),
        "signal_matrix_path": str(result.signal_matrix_path),
        "validation_daily_path": str(result.validation_daily_path),
        "validation_window_summary_path": str(result.validation_window_summary_path),
        "threshold_weighting_path": str(result.threshold_weighting_path),
        "evidence_summary_parquet_path": str(result.evidence_summary_parquet_path),
        "decay_parquet_path": str(result.decay_parquet_path),
        "stability_parquet_path": str(result.stability_parquet_path),
        "markdown_path": str(result.markdown_path),
        "json_path": str(result.json_path),
        "warning_csv_path": str(result.warning_csv_path),
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_cost_scenarios(value: str | None) -> dict[str, float] | None:
    """Parse CLI cost scenario text like ``normal_cost=5,conservative_cost=10``."""
    if value is None or not value.strip():
        return None
    parsed: dict[str, float] = {}
    for item in value.split(","):
        name, sep, raw_cost = item.partition("=")
        if not sep:
            raise ResearchWorkbenchError(f"invalid cost scenario: {item}")
        scenario = name.strip()
        if not scenario:
            raise ResearchWorkbenchError(f"invalid cost scenario name: {item}")
        try:
            cost_bps = float(raw_cost)
        except ValueError as exc:
            raise ResearchWorkbenchError(f"invalid cost bps: {item}") from exc
        if cost_bps < 0:
            raise ResearchWorkbenchError("cost scenario bps must be non-negative")
        parsed[scenario] = cost_bps
    return parsed


def _resolve_cost_scenarios(value: dict[str, float] | None) -> dict[str, float]:
    scenarios = dict(DEFAULT_COST_SCENARIOS if value is None else value)
    if not scenarios:
        raise ResearchWorkbenchError("at least one cost scenario is required")
    for name, cost in scenarios.items():
        if not name:
            raise ResearchWorkbenchError("cost scenario name must not be empty")
        if cost < 0:
            raise ResearchWorkbenchError("cost scenario bps must be non-negative")
    return scenarios


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_historical_evidence"
    return {
        "evidence_summary_parquet": root / f"{stem}_summary.parquet",
        "evidence_summary_csv": root / f"{stem}_summary.csv",
        "decay_parquet": root / f"{stem}_decay.parquet",
        "decay_csv": root / f"{stem}_decay.csv",
        "stability_parquet": root / f"{stem}_stability.parquet",
        "stability_csv": root / f"{stem}_stability.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_historical_evidence"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_historical_evidence"
    return root / f"{stem}.json"


def _default_signal_matrix_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_signal_matrix_daily.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R35 signal matrix parquet found under {root}")
    return candidates[-1]


def _default_validation_daily_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_signal_matrix_validation_daily.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R36 validation daily parquet found under {root}")
    return candidates[-1]


def _default_validation_window_summary_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    candidates = sorted(
        root.glob(f"{PRODUCT_CODE}_*_signal_matrix_validation_window_summary.parquet")
    )
    if not candidates:
        raise ResearchWorkbenchError(f"no R36 window summary parquet found under {root}")
    return candidates[-1]


def _default_threshold_weighting_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_threshold_research"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_signal_threshold_research_weighting.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R37 threshold weighting parquet found under {root}")
    return candidates[-1]


def _default_run_id(*, start: date, end: date) -> str:
    return (
        f"r41_historical_evidence_{PRODUCT_CODE}_{start.isoformat()}_"
        f"{end.isoformat()}_{uuid.uuid4().hex[:8]}"
    )


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    lowered = series.astype(str).str.lower()
    return lowered.isin({"true", "1", "yes", "y"})


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
    if pd.isna(value):
        return None
    return float(value)


def _int_or_none(value: object) -> int | None:
    if pd.isna(value):
        return None
    return int(value)


def _fmt_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _scenario_text(scenarios: dict[str, float]) -> str:
    return ",".join(f"{name}={cost:g}bps" for name, cost in scenarios.items())
