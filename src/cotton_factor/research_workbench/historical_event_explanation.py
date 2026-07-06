"""R42 historical event explanation for CF trend and structure events."""

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
from cotton_factor.research_workbench.signal_matrix_validation import (
    SIGNAL_MATRIX_VALIDATION_VERSION,
)

PRODUCT_CODE = "CF"
HISTORICAL_EVENT_EXPLANATION_VERSION = "R42_historical_event_explanation_v1"
FUNDAMENTAL_EVENT_CONTEXT_VERSION = "R55_event_fundamental_context_v1"
OUTPUT_DIR = "event_explanation"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
DEFAULT_PRIMARY_HORIZON = 20
HUMAN_REVIEW_REQUIRED = (
    "historical_event_interpretation",
    "trend_phase_rules",
    "event_thresholds",
    "forward_return_horizon_set",
    "contract_rule_assumptions",
    "fundamental_context_interpretation",
)

REQUIRED_VALIDATION_COLUMNS = {
    "trade_date",
    "horizon",
    "main_contract",
    "direction",
    "trend_phase",
    "trend_phase_label",
    "confidence",
    "forward_return",
    "forward_label_available",
    "directional_hit",
    "execution_date",
    "exit_date",
    "forward_returns_are_validation_labels",
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
class HistoricalEventExplanationWarningRecord:
    """Warning row for R42 historical event explanation."""

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
class ResearchHistoricalEventExplanationResult:
    """Result of building R42 historical event explanation artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    primary_horizon: int
    horizons: tuple[int, ...]
    event_row_count: int
    summary_row_count: int
    warning_records: tuple[HistoricalEventExplanationWarningRecord, ...]
    event_parquet_path: Path
    event_csv_path: Path
    summary_parquet_path: Path
    summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    validation_daily_path: Path
    fundamental_context_path: Path | None
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
            "primary_horizon": self.primary_horizon,
            "horizons": list(self.horizons),
            "event_row_count": self.event_row_count,
            "summary_row_count": self.summary_row_count,
            "warning_count": self.warning_count,
            "event_parquet_path": str(self.event_parquet_path),
            "event_csv_path": str(self.event_csv_path),
            "summary_parquet_path": str(self.summary_parquet_path),
            "summary_csv_path": str(self.summary_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "validation_daily_path": str(self.validation_daily_path),
            "fundamental_context_path": (
                None
                if self.fundamental_context_path is None
                else str(self.fundamental_context_path)
            ),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_historical_event_explanation(
    *,
    validation_daily_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    primary_horizon: int = DEFAULT_PRIMARY_HORIZON,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    oi_anomaly_quantile: float = 0.95,
    curve_shock_quantile: float = 0.95,
    fundamental_context_path: Path | None = None,
) -> ResearchHistoricalEventExplanationResult:
    """Build R42 full-history event explanations from R36 validation rows."""
    validation_path = validation_daily_path or _default_validation_daily_path()
    validation = _load_validation_daily(validation_path)
    _validate_horizons(horizons=horizons, primary_horizon=primary_horizon)
    start = min(validation["trade_date"])
    end = max(validation["trade_date"])
    event_run_id = run_id or _default_run_id(start=start, end=end)
    base = _primary_rows(validation=validation, primary_horizon=primary_horizon)
    outcome_lookup = _outcome_lookup(validation=validation, horizons=horizons)

    # R42 使用 R36 已生成的后验标签解释历史事件，不重新生成或前视使用标签。
    event_rows = _event_rows(
        base=base,
        outcome_lookup=outcome_lookup,
        run_id=event_run_id,
        horizons=horizons,
        oi_anomaly_quantile=oi_anomaly_quantile,
        curve_shock_quantile=curve_shock_quantile,
    )
    fundamental_context = _load_fundamental_context(fundamental_context_path)
    event_rows = _attach_fundamental_context(
        event_rows=event_rows,
        fundamental_context=fundamental_context,
    )
    summary_rows = _summary_rows(event_rows=event_rows, horizons=horizons, run_id=event_run_id)
    warnings = _warning_records(
        run_id=event_run_id,
        validation=validation,
        event_rows=event_rows,
        primary_horizon=primary_horizon,
        fundamental_context=fundamental_context,
        fundamental_context_path=fundamental_context_path,
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    json_path = _json_path(start=start, end=end, report_output_dir=report_output_dir)
    result = ResearchHistoricalEventExplanationResult(
        product_code=PRODUCT_CODE,
        run_id=event_run_id,
        start=start,
        end=end,
        primary_horizon=primary_horizon,
        horizons=tuple(horizons),
        event_row_count=len(event_rows),
        summary_row_count=len(summary_rows),
        warning_records=warnings,
        event_parquet_path=paths["events_parquet"],
        event_csv_path=paths["events_csv"],
        summary_parquet_path=paths["summary_parquet"],
        summary_csv_path=paths["summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        validation_daily_path=validation_path,
        fundamental_context_path=fundamental_context_path,
        human_review_required=_human_review_required(warnings),
    )
    _write_table(
        rows=event_rows,
        parquet_path=result.event_parquet_path,
        csv_path=result.event_csv_path,
    )
    _write_table(
        rows=summary_rows,
        parquet_path=result.summary_parquet_path,
        csv_path=result.summary_csv_path,
    )
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_markdown(result=result, event_rows=event_rows, summary_rows=summary_rows)
    _write_json(result=result, event_rows=event_rows, summary_rows=summary_rows)
    _write_manifest(result=result)
    return result


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
    working["directional_hit"] = _bool_series(working["directional_hit"])
    working["forward_returns_are_validation_labels"] = _bool_series(
        working["forward_returns_are_validation_labels"]
    )
    working = working.dropna(subset=["trade_date", "horizon"])
    working["horizon"] = working["horizon"].astype(int)
    labelled = working.loc[working["forward_label_available"]].copy()
    if labelled.empty:
        raise ResearchWorkbenchError("R42 requires labelled validation rows")
    if not labelled["forward_returns_are_validation_labels"].all():
        raise ResearchWorkbenchError("R42 requires forward returns to be validation labels")
    bad_execution = labelled.loc[labelled["execution_date"] <= labelled["trade_date"]]
    if not bad_execution.empty:
        raise ResearchWorkbenchError("R42 validation rows violate T+1 execution timing")
    return working.sort_values(["trade_date", "horizon"]).reset_index(drop=True)


def _load_fundamental_context(path: Path | None) -> pd.DataFrame:
    if path is None:
        return _empty_fundamental_context_frame()
    if not path.exists():
        raise ResearchWorkbenchError(f"fundamental context table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(
        {
            "trade_date",
            "dataset_type",
            "indicator_name",
            "metric_name",
            "indicator_value",
            "explanation_relation_4_vs_price20",
            "context_label_4",
            "fundamental_signal_status",
        }
        - set(frame.columns)
    )
    if missing:
        raise ResearchWorkbenchError(f"fundamental context table missing columns: {missing}")
    if any(str(column).startswith("forward_return") for column in frame.columns):
        raise ResearchWorkbenchError("fundamental context must not contain forward_return labels")
    working = frame.copy()
    if "raw_indicator_name" not in working.columns:
        working["raw_indicator_name"] = working["indicator_name"]
    if not working["fundamental_signal_status"].astype(str).eq("not_connected").all():
        raise ResearchWorkbenchError("fundamental context must remain not_connected")
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce").dt.date
    working["indicator_value"] = pd.to_numeric(working["indicator_value"], errors="coerce")
    working = working.dropna(subset=["trade_date"])
    if working.empty:
        return _empty_fundamental_context_frame()
    return working.sort_values(
        ["trade_date", "dataset_type", "indicator_name", "metric_name"]
    ).reset_index(drop=True)


def _primary_rows(*, validation: pd.DataFrame, primary_horizon: int) -> pd.DataFrame:
    primary = validation.loc[validation["horizon"].eq(primary_horizon)].copy()
    if primary.empty:
        raise ResearchWorkbenchError(f"R42 has no rows for primary horizon {primary_horizon}")
    optional_numeric = (
        "composite_score",
        "return_20d",
        "main_oi_pressure",
        "curve_slope",
        "carry_annualized",
    )
    for column in optional_numeric:
        if column in primary.columns:
            primary[column] = pd.to_numeric(primary[column], errors="coerce")
    return primary.sort_values("trade_date").reset_index(drop=True)


def _outcome_lookup(
    *,
    validation: pd.DataFrame,
    horizons: tuple[int, ...],
) -> dict[tuple[date, int], dict[str, object]]:
    lookup: dict[tuple[date, int], dict[str, object]] = {}
    selected = validation.loc[validation["horizon"].isin(horizons)].copy()
    for row in selected.itertuples(index=False):
        lookup[(row.trade_date, int(row.horizon))] = {
            "forward_return": _float_or_none(row.forward_return),
            "forward_label_available": bool(row.forward_label_available),
            "directional_hit": bool(row.directional_hit),
            "execution_date": _date_text(row.execution_date),
            "exit_date": _date_text(row.exit_date),
        }
    return lookup


def _event_rows(
    *,
    base: pd.DataFrame,
    outcome_lookup: dict[tuple[date, int], dict[str, object]],
    run_id: str,
    horizons: tuple[int, ...],
    oi_anomaly_quantile: float,
    curve_shock_quantile: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    oi_threshold = _abs_quantile(base.get("main_oi_pressure"), oi_anomaly_quantile)
    curve_change = (
        pd.to_numeric(base["curve_slope"], errors="coerce").diff()
        if "curve_slope" in base.columns
        else pd.Series(dtype=float)
    )
    curve_threshold = _abs_quantile(curve_change, curve_shock_quantile)
    previous: pd.Series | None = None
    for current in base.itertuples(index=False):
        current_series = pd.Series(current._asdict())
        if previous is not None:
            rows.extend(
                _events_for_day(
                    previous=previous,
                    current=current_series,
                    outcome_lookup=outcome_lookup,
                    run_id=run_id,
                    horizons=horizons,
                    oi_threshold=oi_threshold,
                    curve_threshold=curve_threshold,
                )
            )
        previous = current_series
    return rows


def _events_for_day(
    *,
    previous: pd.Series,
    current: pd.Series,
    outcome_lookup: dict[tuple[date, int], dict[str, object]],
    run_id: str,
    horizons: tuple[int, ...],
    oi_threshold: float | None,
    curve_threshold: float | None,
) -> list[dict[str, object]]:
    events: list[tuple[str, str, str, bool, str]] = []
    previous_phase = str(previous.get("trend_phase"))
    current_phase = str(current.get("trend_phase"))
    transition_code = f"{previous_phase}_TO_{current_phase}"
    if previous_phase == "S1" and current_phase == "S2":
        events.append(("trend_start", "趋势起点", transition_code, True, "S1 转入 S2"))
    if previous_phase == "S2" and current_phase == "S2":
        events.append(("trend_continuation", "趋势中继", "S2_CONTINUE", False, "S2 阶段延续"))
    if previous_phase == "S2" and current_phase == "S3":
        events.append(("trend_exhaustion", "衰竭观察", transition_code, True, "S2 转入 S3"))
    if previous_phase == "S3" and current_phase in {"S4", "S0"}:
        events.append(("trend_end", "终点确认", transition_code, True, f"S3 转入 {current_phase}"))
    if str(previous.get("main_contract")) != str(current.get("main_contract")):
        events.append(
            ("main_contract_switch", "主力切换", "MAIN_CONTRACT_SWITCH", True, "主力合约改变")
        )
    oi_value = _float_or_none(current.get("main_oi_pressure"))
    if oi_threshold is not None and oi_value is not None and abs(oi_value) >= oi_threshold:
        events.append(
            ("oi_anomaly", "持仓异常变化", "OI_ANOMALY", True, "主力持仓压力进入极端分位")
        )
    curve_delta = _curve_delta(previous=previous, current=current)
    if (
        curve_threshold is not None
        and curve_delta is not None
        and abs(curve_delta) >= curve_threshold
    ):
        events.append(
            ("curve_shock", "曲线结构突变", "CURVE_SHOCK", True, "曲线斜率变化进入极端分位")
        )
    return [
        _event_row(
            run_id=run_id,
            previous=previous,
            current=current,
            outcome_lookup=outcome_lookup,
            horizons=horizons,
            event_category=category,
            event_type=event_type,
            transition_code=code,
            is_key_event=is_key,
            event_reason=reason,
        )
        for category, event_type, code, is_key, reason in events
    ]


def _event_row(
    *,
    run_id: str,
    previous: pd.Series,
    current: pd.Series,
    outcome_lookup: dict[tuple[date, int], dict[str, object]],
    horizons: tuple[int, ...],
    event_category: str,
    event_type: str,
    transition_code: str,
    is_key_event: bool,
    event_reason: str,
) -> dict[str, object]:
    event_date = current["trade_date"]
    row: dict[str, object] = {
        "run_id": run_id,
        "product_code": PRODUCT_CODE,
        "event_date": event_date,
        "event_category": event_category,
        "event_type": event_type,
        "transition_code": transition_code,
        "is_key_event": is_key_event,
        "explainable_historical_sample": False,
        "main_contract": current.get("main_contract"),
        "previous_main_contract": previous.get("main_contract"),
        "previous_trend_phase": previous.get("trend_phase"),
        "new_trend_phase": current.get("trend_phase"),
        "previous_trend_phase_label": previous.get("trend_phase_label"),
        "new_trend_phase_label": current.get("trend_phase_label"),
        "direction": current.get("direction"),
        "confidence": current.get("confidence"),
        "composite_score": _float_or_none(current.get("composite_score")),
        "factor_contribution_cn": _factor_contribution(current),
        "event_reason": event_reason,
        "event_return_20d": _float_or_none(current.get("return_20d")),
        "event_oi_pressure": _float_or_none(current.get("main_oi_pressure")),
        "event_curve_slope": _float_or_none(current.get("curve_slope")),
        "event_carry_annualized": _float_or_none(current.get("carry_annualized")),
        "source_validation_rule_version": SIGNAL_MATRIX_VALIDATION_VERSION,
        "event_rule_version": HISTORICAL_EVENT_EXPLANATION_VERSION,
    }
    explainable = False
    for horizon in horizons:
        outcome = outcome_lookup.get((event_date, horizon), {})
        available = bool(outcome.get("forward_label_available"))
        explainable = explainable or available
        row[f"forward_return_h{horizon}"] = outcome.get("forward_return")
        row[f"forward_label_available_h{horizon}"] = available
        row[f"event_direction_hit_h{horizon}"] = outcome.get("directional_hit")
        row[f"execution_date_h{horizon}"] = outcome.get("execution_date")
        row[f"exit_date_h{horizon}"] = outcome.get("exit_date")
    row["explainable_historical_sample"] = explainable
    return row


def _attach_fundamental_context(
    *,
    event_rows: list[dict[str, object]],
    fundamental_context: pd.DataFrame,
) -> list[dict[str, object]]:
    if not event_rows:
        return []
    enriched: list[dict[str, object]] = []
    for row in event_rows:
        copied = dict(row)
        event_date = row.get("event_date")
        latest_rows = _latest_fundamental_rows_for_event(
            fundamental_context=fundamental_context,
            event_date=event_date,
        )
        copied.update(_fundamental_context_fields(latest_rows))
        enriched.append(copied)
    return enriched


def _latest_fundamental_rows_for_event(
    *,
    fundamental_context: pd.DataFrame,
    event_date: object,
) -> pd.DataFrame:
    if fundamental_context.empty or event_date is None or pd.isna(event_date):
        return _empty_fundamental_context_frame()
    event_date_value = (
        event_date if isinstance(event_date, date) else pd.to_datetime(event_date).date()
    )
    eligible = fundamental_context.loc[fundamental_context["trade_date"] <= event_date_value]
    if eligible.empty:
        return _empty_fundamental_context_frame()
    # 每个基本面口径只取事件日前可见的最近一条，避免把事件日之后的数据带入解释。
    return (
        eligible.sort_values("trade_date")
        .groupby(["dataset_type", "indicator_name", "metric_name"], dropna=False)
        .tail(1)
        .sort_values(["dataset_type", "indicator_name", "metric_name"])
        .reset_index(drop=True)
    )


def _fundamental_context_fields(latest_rows: pd.DataFrame) -> dict[str, object]:
    if latest_rows.empty:
        return {
            "fundamental_context_available": False,
            "fundamental_context_count": 0,
            "fundamental_aligned_count": 0,
            "fundamental_divergent_count": 0,
            "fundamental_context_asof": None,
            "fundamental_context_summary_cn": "事件日前无可用 R54 基本面上下文。",
            "fundamental_context_rule_version": FUNDAMENTAL_EVENT_CONTEXT_VERSION,
        }
    relation = latest_rows["explanation_relation_4_vs_price20"].astype(str)
    aligned = int((relation == "aligned_trailing_context").sum())
    divergent = int((relation == "divergent_trailing_context").sum())
    asof = pd.to_datetime(latest_rows["trade_date"], errors="coerce").max().date()
    return {
        "fundamental_context_available": True,
        "fundamental_context_count": int(len(latest_rows)),
        "fundamental_aligned_count": aligned,
        "fundamental_divergent_count": divergent,
        "fundamental_context_asof": asof.isoformat(),
        "fundamental_context_summary_cn": _fundamental_context_summary_cn(
            latest_rows=latest_rows,
            asof=asof,
            aligned=aligned,
            divergent=divergent,
        ),
        "fundamental_context_rule_version": FUNDAMENTAL_EVENT_CONTEXT_VERSION,
    }


def _fundamental_context_summary_cn(
    *,
    latest_rows: pd.DataFrame,
    asof: date,
    aligned: int,
    divergent: int,
) -> str:
    selected = latest_rows.loc[
        latest_rows["explanation_relation_4_vs_price20"].astype(str).isin(
            {"aligned_trailing_context", "divergent_trailing_context"}
        )
    ].head(4)
    examples: list[str] = []
    for row in selected.to_dict(orient="records"):
        relation_label = _fundamental_relation_label(
            row.get("explanation_relation_4_vs_price20")
        )
        examples.append(
            f"{row.get('indicator_name')}/{row.get('metric_name')}({relation_label})："
            f"{row.get('context_label_4')}"
        )
    detail = "；".join(examples) if examples else "暂无可比较的同向/背离样本"
    return (
        f"截至 {asof.isoformat()} 可见基本面上下文 {len(latest_rows)} 项，"
        f"同向 {aligned} 项，背离 {divergent} 项；{detail}。"
    )


def _fundamental_relation_label(value: object) -> str:
    mapping = {
        "aligned_trailing_context": "同向",
        "divergent_trailing_context": "背离",
        "neutral_price_context": "价格中性",
        "insufficient_context": "上下文不足",
    }
    return mapping.get(str(value), "未分类")


def _summary_rows(
    *,
    event_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
    run_id: str,
) -> list[dict[str, object]]:
    if not event_rows:
        return []
    frame = pd.DataFrame(event_rows)
    rows: list[dict[str, object]] = []
    for event_type, group in frame.groupby("event_type", sort=True):
        fundamental_available = (
            group["fundamental_context_available"].astype(bool)
            if "fundamental_context_available" in group.columns
            else pd.Series(False, index=group.index)
        )
        fundamental_aligned = _sum_numeric(group.get("fundamental_aligned_count"))
        fundamental_divergent = _sum_numeric(group.get("fundamental_divergent_count"))
        for horizon in horizons:
            available = group.loc[group[f"forward_label_available_h{horizon}"].astype(bool)]
            rows.append(
                {
                    "run_id": run_id,
                    "product_code": PRODUCT_CODE,
                    "event_type": event_type,
                    "horizon": horizon,
                    "event_count": int(len(group)),
                    "observation_count": int(len(available)),
                    "mean_forward_return": _mean(available[f"forward_return_h{horizon}"]),
                    "median_forward_return": _median(available[f"forward_return_h{horizon}"]),
                    "directional_hit_rate": _mean(
                        available[f"event_direction_hit_h{horizon}"].astype(float)
                    ),
                    "explainable_rate": _mean(group["explainable_historical_sample"].astype(float)),
                    "fundamental_context_event_count": int(fundamental_available.sum()),
                    "fundamental_aligned_count": fundamental_aligned,
                    "fundamental_divergent_count": fundamental_divergent,
                    "fundamental_context_rule_version": FUNDAMENTAL_EVENT_CONTEXT_VERSION,
                    "event_rule_version": HISTORICAL_EVENT_EXPLANATION_VERSION,
                }
            )
    return rows


def _warning_records(
    *,
    run_id: str,
    validation: pd.DataFrame,
    event_rows: list[dict[str, object]],
    primary_horizon: int,
    fundamental_context: pd.DataFrame,
    fundamental_context_path: Path | None,
) -> tuple[HistoricalEventExplanationWarningRecord, ...]:
    warnings = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R42_FORWARD_RETURNS_ARE_EVENT_LABELS",
            warning_message="R42 forward_return_* 只用于历史事件后验解释，不构成交易规则。",
            affected_count=int(validation["forward_label_available"].sum()),
            human_review_required=("forward_return_horizon_set",),
        )
    ]
    if not event_rows:
        warnings.append(
            _warning(
                run_id=run_id,
                section="events",
                severity=WARNING_SEVERITY,
                warning_code="R42_NO_EVENTS_FOUND",
                warning_message="未识别到历史事件，需复核趋势阶段或事件阈值。",
                affected_count=0,
                human_review_required=("trend_phase_rules", "event_thresholds"),
            )
        )
    primary_rows = validation.loc[validation["horizon"].eq(primary_horizon)]
    missing_primary = int((~primary_rows["forward_label_available"]).sum())
    if missing_primary:
        warnings.append(
            _warning(
                run_id=run_id,
                section="primary_horizon",
                severity=WARNING_SEVERITY,
                warning_code="R42_PRIMARY_HORIZON_LABEL_GAPS",
                warning_message="主观察周期存在缺失的后验标签，相关事件统计样本会减少。",
                affected_count=missing_primary,
                human_review_required=("forward_return_horizon_set",),
            )
        )
    if fundamental_context_path is not None:
        if fundamental_context.empty:
            warnings.append(
                _warning(
                    run_id=run_id,
                    section="fundamental_context",
                    severity=WARNING_SEVERITY,
                    warning_code="R55_FUNDAMENTAL_CONTEXT_EMPTY",
                    warning_message="已提供 R54 基本面上下文路径，但表内无可用行。",
                    affected_count=0,
                    human_review_required=("fundamental_context_interpretation",),
                )
            )
        else:
            available_events = sum(
                1 for row in event_rows if bool(row.get("fundamental_context_available"))
            )
            warnings.append(
                _warning(
                    run_id=run_id,
                    section="fundamental_context",
                    severity=INFO_SEVERITY,
                    warning_code="R55_FUNDAMENTAL_CONTEXT_CONNECTED",
                    warning_message="R55 已按事件日前最近可见数据接入 R54 基本面上下文。",
                    affected_count=available_events,
                    human_review_required=("fundamental_context_interpretation",),
                )
            )
            if event_rows and available_events == 0:
                warnings.append(
                    _warning(
                        run_id=run_id,
                        section="fundamental_context",
                        severity=WARNING_SEVERITY,
                        warning_code="R55_NO_EVENT_FUNDAMENTAL_CONTEXT",
                        warning_message="事件样本未匹配到事件日前可见的基本面上下文。",
                        affected_count=len(event_rows),
                        human_review_required=("fundamental_context_interpretation",),
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
) -> HistoricalEventExplanationWarningRecord:
    return HistoricalEventExplanationWarningRecord(
        run_id=run_id,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        affected_count=affected_count,
        human_review_required=human_review_required,
    )


def _human_review_required(
    warnings: tuple[HistoricalEventExplanationWarningRecord, ...],
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
    warnings: tuple[HistoricalEventExplanationWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchHistoricalEventExplanationResult,
    event_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(summary_rows)
    event_counts = pd.DataFrame(event_rows)["event_type"].value_counts() if event_rows else {}
    lines = [
        f"# CF 全历史事件解释包 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        "- 报告类型：`historical_event_explanation`",
        f"- Run ID：`{result.run_id}`",
        f"- 主观察周期：`{result.primary_horizon}D`",
        f"- 事件数：`{result.event_row_count}`",
        f"- 汇总行数：`{result.summary_row_count}`",
        f"- warning_count：`{result.warning_count}`",
        "- 基本面上下文："
        + (
            "`未接入`"
            if result.fundamental_context_path is None
            else f"`{result.fundamental_context_path}`"
        ),
        "",
        "## 二、研究边界",
        "",
        "- forward_return_* 只作为历史事件后的后验验证标签。",
        "- 事件解释用于研究复盘，不构成交易指令。",
        "- R55 基本面上下文只使用事件日及以前可见数据，不生成 fundamental_signal。",
        "- 主力切换、持仓异常、曲线突变阈值需要人工复核。",
        "",
        "## 三、事件数量",
        "",
        "| 事件类型 | 数量 |",
        "| --- | ---: |",
    ]
    if event_counts is not None:
        for event_type, count in dict(event_counts).items():
            lines.append(f"| {event_type} | {count} |")
    lines.extend(
        [
            "",
            "## 四、事件后验表现摘要",
            "",
            "| 事件类型 | Horizon | 事件数 | 样本 | 平均后验收益 | 方向命中率 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    if not summary.empty:
        selected = summary.loc[summary["horizon"].isin((1, 5, 10, 20))]
        for row in selected.to_dict(orient="records"):
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["event_type"]),
                        str(row["horizon"]),
                        str(row["event_count"]),
                        str(row["observation_count"]),
                        _fmt_percent(row["mean_forward_return"]),
                        _fmt_percent(row["directional_hit_rate"]),
                    ]
                )
                + " |"
            )
    lines.extend(["", "## 五、基本面事件解释", ""])
    if result.fundamental_context_path is None:
        lines.append("- 未提供 R54 基本面上下文路径，本次事件解释不包含基本面上下文。")
    else:
        lines.append(f"- 基本面上下文输入：`{result.fundamental_context_path}`")
        fundamental_rows = _fundamental_event_markdown_rows(event_rows)
        if not fundamental_rows:
            lines.append("- 未匹配到事件日前可见的 R54 基本面上下文。")
        else:
            lines.extend(
                [
                    "",
                    "| 事件类型 | 事件数 | 有基本面上下文 | 同向项合计 | 背离项合计 | 示例解释 |",
                    "| --- | ---: | ---: | ---: | ---: | --- |",
                ]
            )
            for row in fundamental_rows:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(row["event_type"]),
                            str(row["event_count"]),
                            str(row["context_event_count"]),
                            str(row["aligned_count"]),
                            str(row["divergent_count"]),
                            str(row["sample_summary"]),
                        ]
                    )
                    + " |"
                )
    lines.extend(["", "## 六、人工复核", ""])
    for item in result.human_review_required:
        lines.append(f"- `{item}`")
    lines.append("")
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")


def _fundamental_event_markdown_rows(
    event_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not event_rows:
        return []
    frame = pd.DataFrame(event_rows)
    if "fundamental_context_available" not in frame.columns:
        return []
    rows: list[dict[str, object]] = []
    for event_type, group in frame.groupby("event_type", sort=True):
        available = group["fundamental_context_available"].astype(bool)
        if not available.any():
            continue
        sample = group.loc[available, "fundamental_context_summary_cn"].iloc[0]
        rows.append(
            {
                "event_type": event_type,
                "event_count": int(len(group)),
                "context_event_count": int(available.sum()),
                "aligned_count": _sum_numeric(group.get("fundamental_aligned_count")),
                "divergent_count": _sum_numeric(group.get("fundamental_divergent_count")),
                "sample_summary": sample,
            }
        )
    return rows


def _write_json(
    *,
    result: ResearchHistoricalEventExplanationResult,
    event_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "historical_event_explanation",
        "rule_version": HISTORICAL_EVENT_EXPLANATION_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "forward_returns_are_event_labels": True,
        "fundamental_context_connected": result.fundamental_context_path is not None,
        "fundamental_context_path": (
            None
            if result.fundamental_context_path is None
            else str(result.fundamental_context_path)
        ),
        "event_sample": event_rows[:20],
        "summary_rows": summary_rows,
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_manifest(*, result: ResearchHistoricalEventExplanationResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "report_type": "historical_event_explanation",
        "rule_version": HISTORICAL_EVENT_EXPLANATION_VERSION,
        "data_start": result.start.isoformat(),
        "data_end": result.end.isoformat(),
        "generated_at": utc_now().isoformat(),
        "primary_horizon": result.primary_horizon,
        "horizons": list(result.horizons),
        "forward_returns_are_event_labels": True,
        "source_rule_versions": [SIGNAL_MATRIX_VALIDATION_VERSION],
        "validation_daily_path": str(result.validation_daily_path),
        "fundamental_context_connected": result.fundamental_context_path is not None,
        "fundamental_context_path": (
            None
            if result.fundamental_context_path is None
            else str(result.fundamental_context_path)
        ),
        "event_parquet_path": str(result.event_parquet_path),
        "summary_parquet_path": str(result.summary_parquet_path),
        "markdown_path": str(result.markdown_path),
        "json_path": str(result.json_path),
        "warning_csv_path": str(result.warning_csv_path),
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _factor_contribution(row: pd.Series) -> str:
    values = []
    for column, label in (
        ("price_signal", "价格"),
        ("momentum_signal", "动量"),
        ("carry_signal", "carry"),
        ("curve_signal", "曲线"),
        ("oi_signal", "持仓"),
    ):
        if column in row:
            values.append(f"{label}={row.get(column)}")
    return "；".join(values) if values else "因子贡献字段不足"


def _curve_delta(*, previous: pd.Series, current: pd.Series) -> float | None:
    previous_value = _float_or_none(previous.get("curve_slope"))
    current_value = _float_or_none(current.get("curve_slope"))
    if previous_value is None or current_value is None:
        return None
    return current_value - previous_value


def _abs_quantile(values: object, quantile: float) -> float | None:
    if values is None:
        return None
    series = pd.Series(values).dropna().abs()
    if series.empty:
        return None
    return float(series.quantile(quantile))


def _validate_horizons(*, horizons: tuple[int, ...], primary_horizon: int) -> None:
    if primary_horizon <= 0:
        raise ResearchWorkbenchError("primary_horizon must be positive")
    if not horizons:
        raise ResearchWorkbenchError("at least one horizon is required")
    if any(horizon <= 0 for horizon in horizons):
        raise ResearchWorkbenchError("horizons must be positive")


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_explanation"
    return {
        "events_parquet": root / f"{stem}_events.parquet",
        "events_csv": root / f"{stem}_events.csv",
        "summary_parquet": root / f"{stem}_summary.parquet",
        "summary_csv": root / f"{stem}_summary.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_explanation"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_explanation"
    return root / f"{stem}.json"


def _empty_fundamental_context_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trade_date",
            "dataset_type",
            "indicator_name",
            "raw_indicator_name",
            "metric_name",
            "indicator_value",
            "explanation_relation_4_vs_price20",
            "context_label_4",
            "fundamental_signal_status",
        ]
    )


def _default_validation_daily_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_signal_matrix_validation_daily.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R36 validation daily parquet found under {root}")
    return candidates[-1]


def _default_run_id(*, start: date, end: date) -> str:
    return (
        f"r42_event_explanation_{PRODUCT_CODE}_{start.isoformat()}_"
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


def _sum_numeric(values: object) -> int:
    if values is None:
        return 0
    series = pd.to_numeric(pd.Series(values), errors="coerce").fillna(0)
    return int(series.sum())


def _median(values: object) -> float | None:
    series = pd.Series(values).dropna()
    if series.empty:
        return None
    return float(series.median())


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _fmt_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"
