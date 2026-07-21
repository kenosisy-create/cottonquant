"""R62 event threshold review ledger for CF research evidence."""

from __future__ import annotations

import csv
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
EVENT_THRESHOLD_REVIEW_VERSION = "R62_event_threshold_review_ledger_v1"
OUTPUT_DIR = "event_threshold_review"
DEFAULT_EXAMPLE_EVENT_COUNT = 3
INFO_SEVERITY = "INFO"
WARN_SEVERITY = "WARN"
HUMAN_REVIEW_REQUIRED = (
    "event_thresholds",
    "threshold_quantile_selection",
    "historical_event_interpretation",
    "cost_after_threshold_review",
    "research_report_wording",
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
class EventThresholdReviewWarningRecord:
    """Warning row for R62 event threshold review ledger."""

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
class ResearchEventThresholdReviewResult:
    """Result of building the R62 threshold review ledger."""

    product_code: str
    run_id: str
    start: date
    end: date
    status: str
    candidate_count: int
    evidence_row_count: int
    review_action_counts: dict[str, int]
    threshold_summary_path: Path
    threshold_detail_path: Path
    event_detail_path: Path
    ledger_parquet_path: Path
    ledger_csv_path: Path
    evidence_parquet_path: Path
    evidence_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    warning_records: tuple[EventThresholdReviewWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    @property
    def passed(self) -> bool:
        """R62 passes when review artifacts are inspectable."""
        return self.status in {
            "EVENT_THRESHOLD_REVIEW_READY",
            "EVENT_THRESHOLD_REVIEW_READY_WITH_WARNINGS",
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
            "candidate_count": self.candidate_count,
            "evidence_row_count": self.evidence_row_count,
            "review_action_counts": self.review_action_counts,
            "warning_count": self.warning_count,
            "warnings": [warning.to_summary() for warning in self.warning_records],
            "threshold_summary_path": str(self.threshold_summary_path),
            "threshold_detail_path": str(self.threshold_detail_path),
            "event_detail_path": str(self.event_detail_path),
            "ledger_parquet_path": str(self.ledger_parquet_path),
            "ledger_csv_path": str(self.ledger_csv_path),
            "evidence_parquet_path": str(self.evidence_parquet_path),
            "evidence_csv_path": str(self.evidence_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "forward_returns_are_validation_labels": True,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(self.human_review_required),
        }


def build_cf_event_threshold_review_ledger(
    *,
    threshold_summary_path: Path | None = None,
    threshold_detail_path: Path | None = None,
    event_detail_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    example_event_count: int = DEFAULT_EXAMPLE_EVENT_COUNT,
) -> ResearchEventThresholdReviewResult:
    """Build an inspectable R62 review ledger from R60/R55 outputs."""
    if example_event_count <= 0:
        raise ResearchWorkbenchError("example_event_count must be positive")
    summary_path = threshold_summary_path or _latest_threshold_summary_path()
    detail_path = threshold_detail_path or _resolve_threshold_detail_path(summary_path)
    resolved_event_path = event_detail_path or _latest_event_detail_path()
    summary = _load_threshold_summary(summary_path)
    detail = _load_threshold_detail(detail_path)
    events = _load_event_detail(resolved_event_path)
    start, end = _date_range(detail=detail, events=events)
    review_run_id = run_id or _default_run_id(start=start, end=end)

    ledger = _ledger_rows(
        run_id=review_run_id,
        summary=summary,
        detail=detail,
        example_event_count=example_event_count,
    )
    evidence = _candidate_evidence_rows(
        ledger=ledger,
        detail=detail,
        events=events,
        example_event_count=example_event_count,
    )
    warnings = tuple(
        _warning_records(
            run_id=review_run_id,
            ledger=ledger,
            evidence=evidence,
            event_detail=events,
        )
    )
    status = (
        "EVENT_THRESHOLD_REVIEW_READY"
        if not _has_warn(warnings)
        else "EVENT_THRESHOLD_REVIEW_READY_WITH_WARNINGS"
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    result = ResearchEventThresholdReviewResult(
        product_code=PRODUCT_CODE,
        run_id=review_run_id,
        start=start,
        end=end,
        status=status,
        candidate_count=int(len(ledger)),
        evidence_row_count=int(len(evidence)),
        review_action_counts=_review_action_counts(ledger),
        threshold_summary_path=summary_path,
        threshold_detail_path=detail_path,
        event_detail_path=resolved_event_path,
        ledger_parquet_path=paths["ledger_parquet"],
        ledger_csv_path=paths["ledger_csv"],
        evidence_parquet_path=paths["evidence_parquet"],
        evidence_csv_path=paths["evidence_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=_markdown_path(start=start, end=end, report_output_dir=report_output_dir),
        json_path=_json_path(start=start, end=end, report_output_dir=report_output_dir),
        manifest_path=paths["manifest"],
        warning_records=warnings,
        human_review_required=_human_review_required(warnings),
    )
    _write_outputs(result=result, ledger=ledger, evidence=evidence)
    return result


def _load_threshold_summary(path: Path) -> pd.DataFrame:
    frame = _read_table(path)
    required = {
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
        "forward_returns_are_validation_labels",
        "trading_instruction",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"R60 threshold summary missing columns: {missing}")
    working = frame.copy()
    _validate_research_boundary(working, source_name="R60 threshold summary")
    return working.reset_index(drop=True)


def _load_threshold_detail(path: Path) -> pd.DataFrame:
    frame = _read_table(path)
    required = {
        "run_id",
        "product_code",
        "threshold_scope",
        "event_category",
        "event_type",
        "threshold_quantile",
        "event_date",
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
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"R60 threshold detail missing columns: {missing}")
    working = frame.copy()
    _validate_research_boundary(working, source_name="R60 threshold detail")
    working["event_date"] = pd.to_datetime(working["event_date"], errors="coerce").dt.date
    working = working.dropna(subset=["event_date"])
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce").astype("Int64")
    working["forward_return"] = pd.to_numeric(working["forward_return"], errors="coerce")
    working["forward_label_available"] = _bool_series(working["forward_label_available"])
    working["directional_hit"] = _bool_series(working["directional_hit"])
    _validate_t_plus_one(working)
    return working.sort_values(["event_date", "threshold_scope", "horizon"]).reset_index(
        drop=True
    )


def _load_event_detail(path: Path) -> pd.DataFrame:
    frame = _read_table(path)
    required = {"event_date", "event_category", "event_type"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"R55 event detail missing columns: {missing}")
    working = frame.copy()
    working["event_date"] = pd.to_datetime(working["event_date"], errors="coerce").dt.date
    return working.dropna(subset=["event_date"]).reset_index(drop=True)


def _validate_research_boundary(frame: pd.DataFrame, *, source_name: str) -> None:
    if frame.empty:
        return
    if not _bool_series(frame["forward_returns_are_validation_labels"]).all():
        raise ResearchWorkbenchError(
            f"{source_name} must mark forward returns as validation labels"
        )
    if not frame["trading_instruction"].astype(str).eq("not_a_trading_instruction").all():
        raise ResearchWorkbenchError(f"{source_name} must not contain trading instructions")


def _validate_t_plus_one(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    execution = pd.to_datetime(frame["execution_date"], errors="coerce").dt.date
    bad_execution = (
        frame["forward_label_available"].astype(bool)
        & execution.notna()
        & (execution <= frame["event_date"])
    )
    if bool(bad_execution.fillna(False).any()):
        raise ResearchWorkbenchError("R62 detail rows violate T+1 execution timing")


def _ledger_rows(
    *,
    run_id: str,
    summary: pd.DataFrame,
    detail: pd.DataFrame,
    example_event_count: int,
) -> pd.DataFrame:
    if summary.empty:
        return _empty_ledger_frame()
    rows: list[dict[str, object]] = []
    working = summary.copy()
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce").astype("Int64")
    working = working.sort_values(
        ["threshold_scope", "event_type", "threshold_quantile", "horizon"],
        na_position="first",
    ).reset_index(drop=True)
    for index, row in working.iterrows():
        candidate_id = _candidate_id(row, index=index)
        examples = _detail_examples(
            detail=_matching_detail(detail=detail, row=row),
            example_event_count=example_event_count,
        )
        decision = str(row.get("review_decision_candidate"))
        evidence_level, evidence_level_cn = _evidence_level(
            review_decision=decision,
            observation_count=_int_value(row.get("observation_count")),
            year_count=_int_value(row.get("year_count")),
            min_annual_observation_count=_int_value(
                row.get("min_annual_observation_count")
            ),
            directional_hit_rate=_float_value(row.get("directional_hit_rate")),
        )
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "candidate_id": candidate_id,
                "threshold_scope": row.get("threshold_scope"),
                "event_category": row.get("event_category"),
                "event_type": row.get("event_type"),
                "threshold_quantile": _float_value(row.get("threshold_quantile")),
                "threshold_value": _float_value(row.get("threshold_value")),
                "horizon": _int_value(row.get("horizon")),
                "review_decision_candidate": decision,
                "suggested_review_action": _suggested_review_action(decision),
                "review_priority": _review_priority(decision),
                "event_count": _int_value(row.get("event_count")),
                "observation_count": _int_value(row.get("observation_count")),
                "sample_event_count": int(len(examples)),
                "mean_forward_return": _float_value(row.get("mean_forward_return")),
                "median_forward_return": _float_value(row.get("median_forward_return")),
                "directional_hit_rate": _float_value(row.get("directional_hit_rate")),
                "positive_return_rate": _float_value(row.get("positive_return_rate")),
                "year_count": _int_value(row.get("year_count")),
                "min_annual_observation_count": _int_value(
                    row.get("min_annual_observation_count")
                ),
                "year_distribution": row.get("year_distribution"),
                "example_event_dates": _example_dates(examples),
                "example_source_event_ids": _example_source_ids(examples),
                "best_evidence_level": evidence_level,
                "evidence_level_cn": evidence_level_cn,
                "human_review_question_cn": _human_review_question(
                    decision=decision,
                    event_type=str(row.get("event_type")),
                    horizon=_int_value(row.get("horizon")),
                ),
                "review_boundary_cn": (
                    "该行只用于阈值候选人工复核；forward_return 是历史后验验证标签。"
                ),
                "forward_returns_are_validation_labels": True,
                "interpretation_status": "HUMAN_REVIEW_REQUIRED",
                "trading_instruction": "not_a_trading_instruction",
                "ledger_rule_version": EVENT_THRESHOLD_REVIEW_VERSION,
            }
        )
    return pd.DataFrame(rows)


def _candidate_evidence_rows(
    *,
    ledger: pd.DataFrame,
    detail: pd.DataFrame,
    events: pd.DataFrame,
    example_event_count: int,
) -> pd.DataFrame:
    if ledger.empty or detail.empty:
        return _empty_evidence_frame()
    event_lookup = _event_lookup(events)
    rows: list[dict[str, object]] = []
    for ledger_row in ledger.itertuples(index=False):
        matched_detail = _matching_detail(detail=detail, row=pd.Series(ledger_row._asdict()))
        examples = _detail_examples(
            detail=matched_detail,
            example_event_count=example_event_count,
        )
        for example in examples.itertuples(index=False):
            event_context = _match_event_context(event_lookup, example)
            rows.append(
                {
                    "run_id": ledger_row.run_id,
                    "product_code": PRODUCT_CODE,
                    "candidate_id": ledger_row.candidate_id,
                    "threshold_scope": ledger_row.threshold_scope,
                    "event_category": ledger_row.event_category,
                    "event_type": ledger_row.event_type,
                    "threshold_quantile": ledger_row.threshold_quantile,
                    "horizon": ledger_row.horizon,
                    "event_date": example.event_date,
                    "event_year": _int_value(getattr(example, "event_year", None)),
                    "source_event_id": example.source_event_id,
                    "forward_return": _float_value(example.forward_return),
                    "directional_hit": bool(example.directional_hit),
                    "execution_date": _date_text(getattr(example, "execution_date", None)),
                    "exit_date": _date_text(getattr(example, "exit_date", None)),
                    "event_intensity": _float_value(getattr(example, "event_intensity", None)),
                    "event_detail_trace_status": event_context["trace_status"],
                    "main_contract": event_context.get("main_contract"),
                    "direction": event_context.get("direction"),
                    "confidence": event_context.get("confidence"),
                    "composite_score": _float_value(event_context.get("composite_score")),
                    "factor_contribution_cn": event_context.get("factor_contribution_cn"),
                    "event_reason": event_context.get("event_reason"),
                    "fundamental_context_available": event_context.get(
                        "fundamental_context_available"
                    ),
                    "fundamental_aligned_count": _int_value(
                        event_context.get("fundamental_aligned_count")
                    ),
                    "fundamental_divergent_count": _int_value(
                        event_context.get("fundamental_divergent_count")
                    ),
                    "fundamental_context_summary_cn": event_context.get(
                        "fundamental_context_summary_cn"
                    ),
                    "forward_returns_are_validation_labels": True,
                    "interpretation_status": "HUMAN_REVIEW_REQUIRED",
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    if not rows:
        return _empty_evidence_frame()
    return pd.DataFrame(rows).sort_values(["candidate_id", "event_date"]).reset_index(drop=True)


def _matching_detail(*, detail: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()
    selected = detail.loc[
        detail["threshold_scope"].astype(str).eq(str(row.get("threshold_scope")))
        & detail["event_category"].astype(str).eq(str(row.get("event_category")))
        & detail["event_type"].astype(str).eq(str(row.get("event_type")))
        & detail["horizon"].astype("Int64").eq(_int_value(row.get("horizon")))
    ].copy()
    row_quantile = _float_value(row.get("threshold_quantile"))
    if row_quantile is None:
        selected = selected.loc[selected["threshold_quantile"].isna()]
    else:
        selected = selected.loc[
            pd.to_numeric(selected["threshold_quantile"], errors="coerce").sub(
                row_quantile
            ).abs()
            < 1e-12
        ]
    return selected


def _detail_examples(*, detail: pd.DataFrame, example_event_count: int) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()
    selected = detail.loc[detail["forward_label_available"].astype(bool)].copy()
    if selected.empty:
        selected = detail.copy()
    selected["_abs_return"] = pd.to_numeric(
        selected["forward_return"],
        errors="coerce",
    ).abs()
    selected["_event_date_sort"] = pd.to_datetime(selected["event_date"], errors="coerce")
    # 复核样本优先展示最近且波动较大的事件，便于人工快速判断阈值是否可解释。
    selected = selected.sort_values(
        ["_event_date_sort", "_abs_return"],
        ascending=[False, False],
        na_position="last",
    )
    return selected.drop(columns=["_abs_return", "_event_date_sort"]).head(
        example_event_count
    )


def _event_lookup(events: pd.DataFrame) -> dict[tuple[object, ...], dict[str, object]]:
    lookup: dict[tuple[object, ...], dict[str, object]] = {}
    if events.empty:
        return lookup
    for row in events.to_dict(orient="records"):
        event_date = _date_value(row.get("event_date"))
        event_category = str(row.get("event_category"))
        event_type = str(row.get("event_type"))
        lookup.setdefault((event_date, event_category, event_type), row)
        lookup.setdefault((event_date, event_category), row)
        lookup.setdefault((event_date,), row)
    return lookup


def _match_event_context(
    event_lookup: dict[tuple[object, ...], dict[str, object]],
    example: object,
) -> dict[str, object]:
    event_date = _date_value(getattr(example, "event_date", None))
    event_category = str(getattr(example, "event_category", ""))
    event_type = str(getattr(example, "event_type", ""))
    for key in (
        (event_date, event_category, event_type),
        (event_date, event_category),
        (event_date,),
    ):
        matched = event_lookup.get(key)
        if matched is not None:
            return {**matched, "trace_status": "EVENT_DETAIL_MATCHED"}
    return {"trace_status": "THRESHOLD_DETAIL_ONLY"}


def _warning_records(
    *,
    run_id: str,
    ledger: pd.DataFrame,
    evidence: pd.DataFrame,
    event_detail: pd.DataFrame,
) -> list[EventThresholdReviewWarningRecord]:
    warnings = [
        EventThresholdReviewWarningRecord(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R62_REVIEW_LEDGER_ONLY",
            warning_message=(
                "R62 只生成事件阈值人工复核台账；forward_return 只作为历史后验验证标签。"
            ),
            affected_count=int(len(ledger)),
            human_review_required=("research_report_wording",),
        )
    ]
    if ledger.empty:
        warnings.append(
            EventThresholdReviewWarningRecord(
                run_id=run_id,
                section="ledger",
                severity=WARN_SEVERITY,
                warning_code="R62_EMPTY_REVIEW_LEDGER",
                warning_message="R60 threshold summary produced no review ledger rows.",
                affected_count=0,
                human_review_required=("event_thresholds",),
            )
        )
    if not ledger.empty and not ledger["review_decision_candidate"].astype(str).eq("KEEP").any():
        warnings.append(
            EventThresholdReviewWarningRecord(
                run_id=run_id,
                section="keep_candidates",
                severity=WARN_SEVERITY,
                warning_code="R62_NO_KEEP_CANDIDATES",
                warning_message="当前 R60 候选没有 KEEP，阈值不得进入稳定表述。",
                affected_count=0,
                human_review_required=("threshold_quantile_selection",),
            )
        )
    if evidence.empty:
        warnings.append(
            EventThresholdReviewWarningRecord(
                run_id=run_id,
                section="evidence",
                severity=WARN_SEVERITY,
                warning_code="R62_NO_TRACEABLE_EVENT_EXAMPLES",
                warning_message="未生成候选事件追溯样本。",
                affected_count=0,
                human_review_required=("historical_event_interpretation",),
            )
        )
    if event_detail.empty:
        warnings.append(
            EventThresholdReviewWarningRecord(
                run_id=run_id,
                section="event_detail",
                severity=WARN_SEVERITY,
                warning_code="R62_EVENT_DETAIL_EMPTY",
                warning_message=(
                    "R55 event detail is empty; factor/fundamental context cannot be joined."
                ),
                affected_count=0,
                human_review_required=("historical_event_interpretation",),
            )
        )
    elif not evidence.empty:
        unmatched = evidence.loc[
            evidence["event_detail_trace_status"].astype(str).ne("EVENT_DETAIL_MATCHED")
        ]
        if not unmatched.empty:
            warnings.append(
                EventThresholdReviewWarningRecord(
                    run_id=run_id,
                    section="event_trace",
                    severity=WARN_SEVERITY,
                    warning_code="R62_EVENT_CONTEXT_PARTIAL_MATCH",
                    warning_message=(
                        f"{len(unmatched)} evidence row(s) have no exact R55 event context."
                    ),
                    affected_count=int(len(unmatched)),
                    human_review_required=("historical_event_interpretation",),
                )
            )
    return warnings


def _write_outputs(
    *,
    result: ResearchEventThresholdReviewResult,
    ledger: pd.DataFrame,
    evidence: pd.DataFrame,
) -> None:
    result.ledger_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_parquet(result.ledger_parquet_path, index=False)
    ledger.to_csv(result.ledger_csv_path, index=False, encoding="utf-8-sig")
    evidence.to_parquet(result.evidence_parquet_path, index=False)
    evidence.to_csv(result.evidence_csv_path, index=False, encoding="utf-8-sig")
    _write_warning_csv(result)
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text(
        _render_markdown(result=result, ledger=ledger, evidence=evidence),
        encoding="utf-8",
    )
    result.json_path.write_text(
        json.dumps(
            _json_safe(
                {
                    "report_type": "event_threshold_review_ledger",
                    "rule_version": EVENT_THRESHOLD_REVIEW_VERSION,
                    "generated_at": utc_now().isoformat(),
                    "summary": result.to_summary(),
                    "top_ledger_rows": _top_ledger_rows(ledger),
                    "top_evidence_rows": _top_evidence_rows(evidence),
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
                    "report_type": "event_threshold_review_ledger",
                    "rule_version": EVENT_THRESHOLD_REVIEW_VERSION,
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


def _write_warning_csv(result: ResearchEventThresholdReviewResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in result.warning_records])


def _render_markdown(
    *,
    result: ResearchEventThresholdReviewResult,
    ledger: pd.DataFrame,
    evidence: pd.DataFrame,
) -> str:
    lines = [
        f"# CF 事件阈值候选复核台账 R62 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 数据状态",
        "",
        "- 报告类型：`event_threshold_review_ledger`",
        f"- 状态：`{result.status}`",
        f"- Run ID：`{result.run_id}`",
        f"- R60 汇总表：`{result.threshold_summary_path}`",
        f"- R60 明细表：`{result.threshold_detail_path}`",
        f"- R55 事件表：`{result.event_detail_path}`",
        f"- 候选数量：`{result.candidate_count}`",
        f"- 事件追溯样本：`{result.evidence_row_count}`",
        "",
        "## R60 候选总览",
        "",
    ]
    for action, count in result.review_action_counts.items():
        lines.append(f"- `{action}`：`{count}`")
    lines.extend(
        [
            "",
            "## KEEP 候选复核台账",
            "",
            "| 候选ID | 事件类型 | 分位 | 周期 | 样本 | 年份 | 命中率 | 均值收益 | 复核动作 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    keep_rows = _ledger_by_decision(ledger, decision="KEEP")
    if keep_rows.empty:
        lines.append("| - | 当前没有 KEEP 候选 | - | - | - | - | - | - | - |")
    else:
        for row in keep_rows.head(20).itertuples(index=False):
            lines.append(_ledger_table_line(row))
    lines.extend(
        [
            "",
            "## WATCH/REVISE/REJECT 复核重点",
            "",
            "| 候选ID | 事件类型 | 分位 | 周期 | 样本 | 年份 | 命中率 | 均值收益 | 复核动作 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    other_rows = ledger.loc[
        ~ledger["review_decision_candidate"].astype(str).eq("KEEP")
    ].copy()
    if other_rows.empty:
        lines.append("| - | 无 | - | - | - | - | - | - | - |")
    else:
        for row in _sort_ledger_for_report(other_rows).head(30).itertuples(index=False):
            lines.append(_ledger_table_line(row))
    lines.extend(
        [
            "",
            "## 事件样本追溯",
            "",
            "| 候选ID | 事件日 | 类型 | 周期 | 后验收益 | 命中 | 事实/因子上下文 | 基本面上下文 |",
            "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    if evidence.empty:
        lines.append("| - | - | - | - | - | - | 暂无追溯样本 | - |")
    else:
        for row in _top_evidence_rows(evidence, limit=24):
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("candidate_id")),
                        _date_text(row.get("event_date")) or "-",
                        str(row.get("event_type")),
                        str(row.get("horizon")),
                        _fmt_percent(row.get("forward_return")),
                        "是" if bool(row.get("directional_hit")) else "否",
                        _short_text(row.get("factor_contribution_cn") or row.get("event_reason")),
                        _short_text(row.get("fundamental_context_summary_cn")),
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## 年度覆盖与样本风险",
            "",
            "- 年度覆盖不足或单年样本过低的候选不能固化为稳定阈值。",
            "- `WATCH` 可以进入后续观察，但不能写成已验证结论。",
            "- `REVISE` 需要回到事件定义、分位阈值或观察周期重新调整。",
            "- `REJECT` 原则上不进入 validated brief 正文证据链，只保留审计痕迹。",
            "",
            "## 人工复核问题清单",
            "",
        ]
    )
    review_questions = _review_questions(ledger)
    if review_questions:
        lines.extend(f"- {item}" for item in review_questions[:20])
    else:
        lines.append("- 当前没有可复核候选。")
    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            f"- 复核台账：`{result.ledger_parquet_path}`",
            f"- 事件追溯样本：`{result.evidence_parquet_path}`",
            f"- 警告清单：`{result.warning_csv_path}`",
            f"- JSON 摘要：`{result.json_path}`",
            "",
            "## 研究边界",
            "",
            "- R62 不重新生成交易信号，也不把阈值候选升级为交易规则。",
            "- forward_return 只作为历史后验验证标签。",
            "- 所有 KEEP/WATCH/REVISE/REJECT 仍为 `HUMAN_REVIEW_REQUIRED`。",
            "- 本报告不构成交易指令。",
        ]
    )
    return "\n".join(lines) + "\n"


def _ledger_table_line(row: object) -> str:
    return (
        "| "
        + " | ".join(
            [
                str(getattr(row, "candidate_id")),
                str(getattr(row, "event_type")),
                _fmt_quantile(getattr(row, "threshold_quantile")),
                str(getattr(row, "horizon")),
                str(getattr(row, "observation_count")),
                str(getattr(row, "year_count")),
                _fmt_percent(getattr(row, "directional_hit_rate")),
                _fmt_percent(getattr(row, "mean_forward_return")),
                str(getattr(row, "suggested_review_action")),
            ]
        )
        + " |"
    )


def _top_ledger_rows(ledger: pd.DataFrame, *, limit: int = 30) -> list[dict[str, object]]:
    if ledger.empty:
        return []
    return _sort_ledger_for_report(ledger).head(limit).to_dict(orient="records")


def _top_evidence_rows(evidence: pd.DataFrame, *, limit: int = 24) -> list[dict[str, object]]:
    if evidence.empty:
        return []
    working = evidence.copy()
    working["_abs_return"] = pd.to_numeric(working["forward_return"], errors="coerce").abs()
    return (
        working.sort_values(["event_date", "_abs_return"], ascending=[False, False])
        .drop(columns=["_abs_return"], errors="ignore")
        .head(limit)
        .to_dict(orient="records")
    )


def _ledger_by_decision(ledger: pd.DataFrame, *, decision: str) -> pd.DataFrame:
    if ledger.empty:
        return ledger.copy()
    selected = ledger.loc[ledger["review_decision_candidate"].astype(str).eq(decision)].copy()
    return _sort_ledger_for_report(selected)


def _sort_ledger_for_report(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return ledger.copy()
    working = ledger.copy()
    working["_decision_rank"] = working["review_decision_candidate"].map(
        {"KEEP": 0, "WATCH": 1, "REVISE": 2, "REJECT": 3}
    )
    working["_hit_rate"] = pd.to_numeric(working["directional_hit_rate"], errors="coerce")
    working["_sample"] = pd.to_numeric(working["observation_count"], errors="coerce")
    return (
        working.sort_values(
            ["_decision_rank", "_hit_rate", "_sample", "candidate_id"],
            ascending=[True, False, False, True],
            na_position="last",
        )
        .drop(columns=["_decision_rank", "_hit_rate", "_sample"], errors="ignore")
        .reset_index(drop=True)
    )


def _review_questions(ledger: pd.DataFrame) -> list[str]:
    if ledger.empty:
        return []
    ordered = _sort_ledger_for_report(ledger)
    return list(dict.fromkeys(str(item) for item in ordered["human_review_question_cn"]))


def _review_action_counts(ledger: pd.DataFrame) -> dict[str, int]:
    actions = {
        "KEEP_REVIEW": 0,
        "WATCH_REVIEW": 0,
        "REVISE_REVIEW": 0,
        "REJECT_REVIEW": 0,
    }
    if ledger.empty:
        return actions
    observed = ledger["suggested_review_action"].astype(str).value_counts().to_dict()
    for action in actions:
        actions[action] = int(observed.get(action, 0))
    return actions


def _candidate_id(row: pd.Series, *, index: int) -> str:
    quantile = _fmt_quantile(row.get("threshold_quantile")).replace(".", "p")
    parts = [
        PRODUCT_CODE,
        str(row.get("threshold_scope")),
        str(row.get("event_category")),
        quantile,
        f"h{_int_value(row.get('horizon'))}",
        str(index),
    ]
    text = "_".join(parts)
    return re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_")


def _suggested_review_action(decision: str) -> str:
    return {
        "KEEP": "KEEP_REVIEW",
        "WATCH": "WATCH_REVIEW",
        "REVISE": "REVISE_REVIEW",
        "REJECT": "REJECT_REVIEW",
    }.get(decision, "WATCH_REVIEW")


def _review_priority(decision: str) -> int:
    return {"KEEP": 1, "WATCH": 2, "REVISE": 3, "REJECT": 4}.get(decision, 9)


def _evidence_level(
    *,
    review_decision: str,
    observation_count: int | None,
    year_count: int | None,
    min_annual_observation_count: int | None,
    directional_hit_rate: float | None,
) -> tuple[str, str]:
    if review_decision == "KEEP":
        stable = (
            (observation_count or 0) >= 20
            and (year_count or 0) >= 3
            and (min_annual_observation_count or 0) >= 2
            and directional_hit_rate is not None
            and directional_hit_rate >= 0.55
        )
        if stable:
            return "STRONG_HISTORY_CANDIDATE", "历史样本较稳定，允许进入重点人工复核。"
        return "MODERATE_HISTORY_CANDIDATE", "候选为 KEEP，但样本分布仍需人工确认。"
    if review_decision == "WATCH":
        return "WATCH_CONTEXT", "证据可观察，但不得固化为稳定阈值。"
    if review_decision == "REVISE":
        return "WEAK_NEEDS_REVISION", "定义、分位或周期需要修订。"
    if review_decision == "REJECT":
        return "REJECT_CANDIDATE", "历史后验表现不足，建议从正文证据链剔除。"
    return "UNKNOWN_REVIEW_STATUS", "未知候选状态，需要人工确认。"


def _human_review_question(*, decision: str, event_type: str, horizon: int | None) -> str:
    horizon_text = "NA" if horizon is None else f"{horizon}D"
    if decision == "KEEP":
        return (
            f"是否允许 `{event_type}` 在 {horizon_text} 作为 validated brief 的重点证据项，"
            "并确认成本后叙述不会变成交易指令？"
        )
    if decision == "WATCH":
        return f"`{event_type}` 在 {horizon_text} 是否继续观察，还是需要增加样本后再进入正文？"
    if decision == "REVISE":
        return f"`{event_type}` 在 {horizon_text} 的事件定义、阈值分位或样本周期应如何修订？"
    if decision == "REJECT":
        return f"`{event_type}` 在 {horizon_text} 是否确认从稳定证据链剔除，仅保留审计痕迹？"
    return f"`{event_type}` 在 {horizon_text} 的复核状态未知，需要人工判断。"


def _example_dates(examples: pd.DataFrame) -> str:
    if examples.empty:
        return ""
    values = [_date_text(value) for value in examples["event_date"].tolist()]
    return ";".join(value for value in values if value)


def _example_source_ids(examples: pd.DataFrame) -> str:
    if examples.empty or "source_event_id" not in examples.columns:
        return ""
    return ";".join(str(value) for value in examples["source_event_id"].dropna().tolist())


def _date_range(*, detail: pd.DataFrame, events: pd.DataFrame) -> tuple[date, date]:
    dates: list[date] = []
    if not detail.empty:
        dates.extend(_date_value(value) for value in detail["event_date"].dropna())
    if not events.empty:
        dates.extend(_date_value(value) for value in events["event_date"].dropna())
    clean = [value for value in dates if value is not None]
    if not clean:
        raise ResearchWorkbenchError("R62 cannot infer date range from input tables")
    return min(clean), max(clean)


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"input table not found: {path}")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise ResearchWorkbenchError(f"unsupported input table type: {path}")


def _latest_threshold_summary_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "event_threshold_sensitivity"
    return _latest_path(root, f"{PRODUCT_CODE}_*_event_threshold_sensitivity_summary.parquet")


def _resolve_threshold_detail_path(summary_path: Path) -> Path:
    if summary_path.name.endswith("_summary.parquet"):
        candidate = summary_path.with_name(
            summary_path.name.replace("_summary.parquet", "_detail.parquet")
        )
        if candidate.exists():
            return candidate
    if summary_path.name.endswith("_summary.csv"):
        candidate = summary_path.with_name(summary_path.name.replace("_summary.csv", "_detail.csv"))
        if candidate.exists():
            return candidate
    root = data_dir() / "research" / PRODUCT_CODE / "event_threshold_sensitivity"
    return _latest_path(root, f"{PRODUCT_CODE}_*_event_threshold_sensitivity_detail.parquet")


def _latest_event_detail_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "event_explanation"
    return _latest_path(root, f"{PRODUCT_CODE}_*_event_explanation_events.parquet")


def _latest_path(root: Path, pattern: str) -> Path:
    candidates = sorted(root.glob(pattern))
    if not candidates:
        raise ResearchWorkbenchError(f"no input file matching {pattern} under {root}")
    return candidates[-1]


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_threshold_review"
    return {
        "ledger_parquet": root / f"{stem}_ledger.parquet",
        "ledger_csv": root / f"{stem}_ledger.csv",
        "evidence_parquet": root / f"{stem}_candidate_evidence.parquet",
        "evidence_csv": root / f"{stem}_candidate_evidence.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_threshold_review"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_threshold_review"
    return root / f"{stem}.json"


def _human_review_required(
    warnings: tuple[EventThresholdReviewWarningRecord, ...],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        values.extend(warning.human_review_required)
    return tuple(dict.fromkeys(values))


def _has_warn(warnings: tuple[EventThresholdReviewWarningRecord, ...]) -> bool:
    return any(warning.severity != INFO_SEVERITY for warning in warnings)


def _empty_ledger_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "run_id",
            "product_code",
            "candidate_id",
            "threshold_scope",
            "event_category",
            "event_type",
            "threshold_quantile",
            "threshold_value",
            "horizon",
            "review_decision_candidate",
            "suggested_review_action",
            "review_priority",
            "event_count",
            "observation_count",
            "sample_event_count",
            "mean_forward_return",
            "median_forward_return",
            "directional_hit_rate",
            "positive_return_rate",
            "year_count",
            "min_annual_observation_count",
            "year_distribution",
            "example_event_dates",
            "example_source_event_ids",
            "best_evidence_level",
            "evidence_level_cn",
            "human_review_question_cn",
            "review_boundary_cn",
            "forward_returns_are_validation_labels",
            "interpretation_status",
            "trading_instruction",
            "ledger_rule_version",
        ]
    )


def _empty_evidence_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "run_id",
            "product_code",
            "candidate_id",
            "threshold_scope",
            "event_category",
            "event_type",
            "threshold_quantile",
            "horizon",
            "event_date",
            "event_year",
            "source_event_id",
            "forward_return",
            "directional_hit",
            "execution_date",
            "exit_date",
            "event_intensity",
            "event_detail_trace_status",
            "main_contract",
            "direction",
            "confidence",
            "composite_score",
            "factor_contribution_cn",
            "event_reason",
            "fundamental_context_available",
            "fundamental_aligned_count",
            "fundamental_divergent_count",
            "fundamental_context_summary_cn",
            "forward_returns_are_validation_labels",
            "interpretation_status",
            "trading_instruction",
        ]
    )


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _float_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: object) -> int | None:
    numeric = _float_value(value)
    if numeric is None:
        return None
    return int(numeric)


def _date_value(value: object) -> date | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _date_text(value: object) -> str | None:
    date_value = _date_value(value)
    return None if date_value is None else date_value.isoformat()


def _fmt_percent(value: object) -> str:
    numeric = _float_value(value)
    if numeric is None:
        return "-"
    return f"{numeric:.2%}"


def _fmt_quantile(value: object) -> str:
    numeric = _float_value(value)
    if numeric is None:
        return "baseline"
    return f"{numeric:.3f}"


def _short_text(value: object, *, max_chars: int = 80) -> str:
    if value is None:
        return "-"
    try:
        if bool(pd.isna(value)):
            return "-"
    except (TypeError, ValueError):
        return "-"
    text = str(value).replace("\n", " ").strip()
    if not text:
        return "-"
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _default_run_id(*, start: date, end: date) -> str:
    return (
        f"r62_event_threshold_review_{PRODUCT_CODE}_{start.isoformat()}_"
        f"{end.isoformat()}_{uuid.uuid4().hex[:8]}"
    )


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
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return value
    return value
