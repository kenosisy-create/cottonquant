"""R93D CF 趋势候选先捕获、后结算的不可变前向账本。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.research_workbench.trend_candidate_stability import (
    CandidateHypothesis,
    TrendCandidateSpec,
    load_cf_trend_candidate_spec,
)

PRODUCT_CODE = "CF"
FORWARD_LEDGER_VERSION = "V5.1_R93D_trend_candidate_forward_ledger_v1"
INFO = "INFO"
WARN = "WARN"
ACTIVE_DECISIONS = {
    "READY_FOR_FORWARD_PREREGISTRATION",
    "FORWARD_WATCH_SMALL_SAMPLE",
    "FORWARD_WATCH_DIRECTIONAL_COVERAGE",
}
DAILY_REQUIRED_COLUMNS = {"trade_date"}
BREAKOUT_REQUIRED_COLUMNS = {
    "event_id",
    "event_date",
    "direction",
    "direction_episode_id",
    "start_stage",
    "start_strength",
    "start_price",
    "main_contract",
    "option_alignment",
    "participation_alignment",
    "horizon",
    "exit_date",
    "raw_return",
    "directional_return",
    "label_available",
    "outcome",
}
EVALUATION_REQUIRED_COLUMNS = {
    "hypothesis_id",
    "decision_status",
    "strategy_change_allowed",
}
LEDGER_COLUMNS = (
    "hypothesis_id",
    "event_id",
    "direction_episode_id",
    "event_date",
    "capture_as_of_date",
    "capture_mode",
    "strict_forward_eligible",
    "candidate_decision",
    "feature_column",
    "feature_value",
    "observed_feature_value",
    "treated",
    "direction",
    "main_contract",
    "start_stage",
    "start_strength",
    "start_price",
    "horizon",
    "capture_business_fingerprint",
    "capture_source_path",
    "capture_source_sha256",
    "capture_event_path",
    "capture_event_sha256",
    "captured_at",
    "outcome_status",
    "label_available",
    "exit_date",
    "outcome",
    "raw_return",
    "directional_return",
    "outcome_business_fingerprint",
    "outcome_source_path",
    "outcome_source_sha256",
    "outcome_event_path",
    "outcome_event_sha256",
    "outcome_recorded_at",
    "correction_count",
    "last_correction_reason",
    "record_mode",
    "historical_result_is_oos",
    "strategy_change_allowed",
    "rule_version",
)
WARNING_COLUMNS = (
    "run_id",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)
HUMAN_REVIEW_REQUIRED = (
    "late_capture_exclusion_policy",
    "outcome_correction_reason",
    "minimum_forward_event_promotion_gate",
    "option_proxy_interpretation",
    "forward_evidence_human_review",
)
RESEARCH_BOUNDARY = (
    "突破事件必须先记录不含未来收益的CAPTURE，后续标签只能通过OUTCOME事件追加；"
    "迟到补录不计入严格前向证据。账本不修改策略方向、目标手数或影子NAV，不构成交易指令。"
)


@dataclass(frozen=True)
class TrendCandidateForwardWarningRecord:
    """R93D warning 行。"""

    run_id: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class TrendCandidateForwardLedgerResult:
    """R93D 运行结果。"""

    run_id: str
    as_of_date: date
    effective_after_date: date
    status: str
    active_hypothesis_count: int
    ledger_row_count: int
    strict_forward_count: int
    pending_outcome_count: int
    resolved_outcome_count: int
    capture_appended_count: int
    outcome_appended_count: int
    correction_appended_count: int
    no_change_count: int
    ledger_path: Path
    event_root: Path
    summary_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[TrendCandidateForwardWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        return sum(item.severity != INFO for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "as_of_date": self.as_of_date.isoformat(),
            "effective_after_date": self.effective_after_date.isoformat(),
            "status": self.status,
            "active_hypothesis_count": self.active_hypothesis_count,
            "ledger_row_count": self.ledger_row_count,
            "strict_forward_count": self.strict_forward_count,
            "pending_outcome_count": self.pending_outcome_count,
            "resolved_outcome_count": self.resolved_outcome_count,
            "capture_appended_count": self.capture_appended_count,
            "outcome_appended_count": self.outcome_appended_count,
            "correction_appended_count": self.correction_appended_count,
            "no_change_count": self.no_change_count,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "ledger_path": str(self.ledger_path),
            "event_root": str(self.event_root),
            "summary_path": str(self.summary_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "research_boundary": RESEARCH_BOUNDARY,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_trend_candidate_forward_ledger(
    *,
    symmetric_trend_daily_path: Path | None = None,
    breakout_event_path: Path | None = None,
    candidate_evaluation_path: Path | None = None,
    spec_path: Path | None = None,
    as_of_date: date | None = None,
    ledger_root: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    correction_reason: str | None = None,
) -> TrendCandidateForwardLedgerResult:
    """把前向突破先写入CAPTURE，待标签形成后再追加OUTCOME。"""
    daily_path = symmetric_trend_daily_path or _latest_symmetric_daily_path()
    event_path = breakout_event_path or _latest_breakout_event_path()
    evaluation_path = candidate_evaluation_path or _latest_candidate_evaluation_path()
    active_spec_path = spec_path or _default_spec_path()
    spec = load_cf_trend_candidate_spec(active_spec_path)
    daily = _load_daily(daily_path)
    events = _load_breakout_events(event_path, spec)
    evaluations = _load_candidate_evaluations(evaluation_path)
    active_hypotheses = _active_hypotheses(spec, evaluations)
    active_as_of = as_of_date or daily["trade_date"].max()
    if active_as_of not in set(daily["trade_date"]):
        raise ResearchWorkbenchError(
            f"R93D as_of_date is not present in symmetric daily state: {active_as_of}"
        )
    if active_as_of < spec.effective_after_date:
        raise ResearchWorkbenchError(
            "R93D as_of_date cannot be earlier than the forward effective boundary"
        )
    active_run_id = run_id or _default_run_id(active_as_of)
    root = ledger_root or (
        data_dir() / "research" / PRODUCT_CODE / "trend_candidate_forward_ledger"
    )
    ledger_path = root / "trend_candidate_forward_ledger.parquet"
    event_root = root / "events"
    ledger = _load_ledger(ledger_path)
    _validate_event_chain(event_root)
    _validate_ledger_event_files(ledger)
    previous_ledger = ledger.copy(deep=True)
    source_sha = _sha256(event_path)
    capture_count = 0
    outcome_count = 0
    correction_count = 0
    no_change_count = 0
    appended_event_paths: list[Path] = []

    for hypothesis, candidate_decision in active_hypotheses:
        source_rows = events.loc[
            events["horizon"].eq(hypothesis.primary_horizon)
            & events["event_date"].gt(spec.effective_after_date)
            & events["event_date"].le(active_as_of)
        ].sort_values(["event_date", "event_id"])
        for source in source_rows.itertuples(index=False):
            key = (hypothesis.hypothesis_id, str(source.event_id))
            capture_business = _capture_business(
                source=source,
                hypothesis=hypothesis,
                candidate_decision=candidate_decision,
            )
            capture_fingerprint = _fingerprint(capture_business)
            row_index = _ledger_row_index(ledger, key)
            if row_index is None:
                capture_mode = (
                    "REALTIME_FORWARD_CAPTURE"
                    if source.event_date == active_as_of
                    else "LATE_BACKFILL_CAPTURE"
                )
                event_record = _append_event(
                    event_root=event_root,
                    as_of_date=active_as_of,
                    event_type="CAPTURE",
                    run_id=active_run_id,
                    event_business=capture_business,
                    source_path=event_path,
                    source_sha256=source_sha,
                    correction_reason=None,
                    supersedes_event_sha256=None,
                )
                appended_event_paths.append(event_record["path"])
                ledger = pd.concat(
                    [
                        ledger,
                        pd.DataFrame(
                            [
                                _new_ledger_row(
                                    capture_business=capture_business,
                                    capture_fingerprint=capture_fingerprint,
                                    capture_mode=capture_mode,
                                    capture_as_of_date=active_as_of,
                                    source_path=event_path,
                                    source_sha=source_sha,
                                    event_record=event_record,
                                )
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
                capture_count += 1
                row_index = len(ledger) - 1
            else:
                existing_fingerprint = str(
                    ledger.at[row_index, "capture_business_fingerprint"]
                )
                if existing_fingerprint != capture_fingerprint:
                    raise ResearchWorkbenchError(
                        "R93D captured T-day business state changed for "
                        f"{key}; immutable capture cannot be rewritten"
                    )

            if bool(source.label_available):
                outcome_business = _outcome_business(source=source, hypothesis=hypothesis)
                if date.fromisoformat(str(outcome_business["exit_date"])) > active_as_of:
                    raise ResearchWorkbenchError(
                        "R93D outcome exit_date is later than as_of_date"
                    )
                outcome_fingerprint = _fingerprint(outcome_business)
                existing_outcome_fingerprint = _optional_text(
                    ledger.at[row_index, "outcome_business_fingerprint"]
                )
                if existing_outcome_fingerprint == outcome_fingerprint:
                    no_change_count += 1
                    continue
                if existing_outcome_fingerprint and not correction_reason:
                    raise ResearchWorkbenchError(
                        "R93D outcome changed; correction_reason is required for "
                        f"{key}"
                    )
                event_type = (
                    "OUTCOME_CORRECTION"
                    if existing_outcome_fingerprint
                    else "OUTCOME"
                )
                event_record = _append_event(
                    event_root=event_root,
                    as_of_date=active_as_of,
                    event_type=event_type,
                    run_id=active_run_id,
                    event_business=outcome_business,
                    source_path=event_path,
                    source_sha256=source_sha,
                    correction_reason=(
                        correction_reason if existing_outcome_fingerprint else None
                    ),
                    supersedes_event_sha256=(
                        _optional_text(ledger.at[row_index, "outcome_event_sha256"])
                        if existing_outcome_fingerprint
                        else None
                    ),
                    capture_event_sha256=str(
                        ledger.at[row_index, "capture_event_sha256"]
                    ),
                )
                appended_event_paths.append(event_record["path"])
                ledger = _apply_outcome(
                    ledger=ledger,
                    row_index=row_index,
                    outcome_business=outcome_business,
                    outcome_fingerprint=outcome_fingerprint,
                    source_path=event_path,
                    source_sha=source_sha,
                    event_record=event_record,
                    correction_reason=(
                        correction_reason if existing_outcome_fingerprint else None
                    ),
                )
                if existing_outcome_fingerprint:
                    correction_count += 1
                else:
                    outcome_count += 1
            else:
                no_change_count += 1

    ledger = _normalize_ledger(ledger)
    _assert_prior_capture_rows_unchanged(previous=previous_ledger, current=ledger)
    if not ledger.equals(previous_ledger) or not ledger_path.exists():
        _atomic_write_parquet(ledger_path, ledger)
    summary = _build_summary(ledger, active_hypotheses)
    warnings = _warning_records(
        run_id=active_run_id,
        ledger=ledger,
        summary=summary,
        capture_appended_count=capture_count,
        correction_appended_count=correction_count,
    )
    paths = _report_paths(
        as_of_date=active_as_of,
        ledger_root=root,
        report_output_dir=report_output_dir,
    )
    status = _status(
        capture_count=capture_count,
        outcome_count=outcome_count,
        correction_count=correction_count,
        ledger_rows=len(ledger),
    )
    result = TrendCandidateForwardLedgerResult(
        run_id=active_run_id,
        as_of_date=active_as_of,
        effective_after_date=spec.effective_after_date,
        status=status,
        active_hypothesis_count=len(active_hypotheses),
        ledger_row_count=len(ledger),
        strict_forward_count=int(ledger["strict_forward_eligible"].sum()),
        pending_outcome_count=int(ledger["outcome_status"].eq("PENDING").sum()),
        resolved_outcome_count=int(ledger["outcome_status"].eq("RESOLVED").sum()),
        capture_appended_count=capture_count,
        outcome_appended_count=outcome_count,
        correction_appended_count=correction_count,
        no_change_count=no_change_count,
        ledger_path=ledger_path,
        event_root=event_root,
        summary_path=paths["summary"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=tuple(warnings),
    )
    _write_outputs(
        result=result,
        summary=summary,
        spec=spec,
        input_paths=(daily_path, event_path, evaluation_path, active_spec_path),
        appended_event_paths=tuple(appended_event_paths),
    )
    return result


def _load_daily(path: Path) -> pd.DataFrame:
    frame = _read_parquet(path, DAILY_REQUIRED_COLUMNS, "R93A symmetric daily")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    if frame["trade_date"].isna().any() or frame["trade_date"].duplicated().any():
        raise ResearchWorkbenchError("R93D symmetric daily contains invalid dates")
    return frame.sort_values("trade_date").reset_index(drop=True)


def _load_breakout_events(path: Path, spec: TrendCandidateSpec) -> pd.DataFrame:
    required = BREAKOUT_REQUIRED_COLUMNS | {
        item.feature_column
        for item in spec.hypotheses
        if item.feature_column in {"option_alignment", "participation_alignment"}
    }
    frame = _read_parquet(path, required, "R93A breakout event")
    for column in ("event_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    if frame["event_date"].isna().any():
        raise ResearchWorkbenchError("R93D breakout event contains invalid event_date")
    frame["horizon"] = pd.to_numeric(frame["horizon"], errors="coerce").astype(
        "Int64"
    )
    if frame["horizon"].isna().any():
        raise ResearchWorkbenchError("R93D breakout event contains invalid horizon")
    if frame.duplicated(["event_id", "horizon"]).any():
        raise ResearchWorkbenchError("R93D breakout event has duplicate event/horizon")
    return frame.sort_values(["event_date", "event_id", "horizon"]).reset_index(
        drop=True
    )


def _load_candidate_evaluations(path: Path) -> pd.DataFrame:
    frame = _read_parquet(path, EVALUATION_REQUIRED_COLUMNS, "R93C evaluation")
    if frame["hypothesis_id"].duplicated().any():
        raise ResearchWorkbenchError("R93D candidate evaluation has duplicate hypotheses")
    if not frame["strategy_change_allowed"].eq(False).all():  # noqa: E712
        raise ResearchWorkbenchError("R93D candidate evaluation permits strategy changes")
    return frame


def _active_hypotheses(
    spec: TrendCandidateSpec,
    evaluations: pd.DataFrame,
) -> tuple[tuple[CandidateHypothesis, str], ...]:
    decisions = evaluations.set_index("hypothesis_id")["decision_status"].astype(str)
    active: list[tuple[CandidateHypothesis, str]] = []
    for hypothesis in spec.hypotheses:
        if hypothesis.hypothesis_id not in decisions:
            raise ResearchWorkbenchError(
                f"R93D missing R93C decision for {hypothesis.hypothesis_id}"
            )
        decision = decisions[hypothesis.hypothesis_id]
        if decision in ACTIVE_DECISIONS:
            if hypothesis.feature_column not in {
                "option_alignment",
                "participation_alignment",
            }:
                raise ResearchWorkbenchError(
                    "R93D active hypothesis requires a feature present in R93A events: "
                    f"{hypothesis.hypothesis_id}"
                )
            active.append((hypothesis, decision))
    if not active:
        raise ResearchWorkbenchError("R93D has no active forward hypotheses")
    return tuple(active)


def _capture_business(
    *,
    source: object,
    hypothesis: CandidateHypothesis,
    candidate_decision: str,
) -> dict[str, object]:
    observed = str(getattr(source, hypothesis.feature_column))
    # CAPTURE 只保留突破当日事实，禁止写入任何结果或未来收益字段。
    return {
        "hypothesis_id": hypothesis.hypothesis_id,
        "event_id": str(source.event_id),
        "direction_episode_id": str(source.direction_episode_id),
        "event_date": source.event_date.isoformat(),
        "candidate_decision": candidate_decision,
        "feature_column": hypothesis.feature_column,
        "feature_value": hypothesis.feature_value,
        "observed_feature_value": observed,
        "treated": observed == hypothesis.feature_value,
        "direction": str(source.direction),
        "main_contract": str(source.main_contract),
        "start_stage": str(source.start_stage),
        "start_strength": float(source.start_strength),
        "start_price": float(source.start_price),
        "horizon": hypothesis.primary_horizon,
        "strategy_change_allowed": False,
        "rule_version": FORWARD_LEDGER_VERSION,
    }


def _outcome_business(
    *,
    source: object,
    hypothesis: CandidateHypothesis,
) -> dict[str, object]:
    if source.exit_date is None or pd.isna(source.exit_date):
        raise ResearchWorkbenchError("R93D available outcome is missing exit_date")
    raw_return = _finite_float(source.raw_return, "raw_return")
    directional_return = _finite_float(source.directional_return, "directional_return")
    return {
        "hypothesis_id": hypothesis.hypothesis_id,
        "event_id": str(source.event_id),
        "exit_date": source.exit_date.isoformat(),
        "outcome": str(source.outcome),
        "raw_return": raw_return,
        "directional_return": directional_return,
        "historical_posterior_label": True,
        "strategy_change_allowed": False,
        "rule_version": FORWARD_LEDGER_VERSION,
    }


def _new_ledger_row(
    *,
    capture_business: dict[str, object],
    capture_fingerprint: str,
    capture_mode: str,
    capture_as_of_date: date,
    source_path: Path,
    source_sha: str,
    event_record: dict[str, object],
) -> dict[str, object]:
    return {
        **capture_business,
        "event_date": date.fromisoformat(str(capture_business["event_date"])),
        "capture_as_of_date": capture_as_of_date,
        "capture_mode": capture_mode,
        "strict_forward_eligible": capture_mode == "REALTIME_FORWARD_CAPTURE",
        "capture_business_fingerprint": capture_fingerprint,
        "capture_source_path": str(source_path),
        "capture_source_sha256": source_sha,
        "capture_event_path": str(event_record["path"]),
        "capture_event_sha256": str(event_record["sha256"]),
        "captured_at": str(event_record["recorded_at"]),
        "outcome_status": "PENDING",
        "label_available": False,
        "exit_date": None,
        "outcome": None,
        "raw_return": math.nan,
        "directional_return": math.nan,
        "outcome_business_fingerprint": None,
        "outcome_source_path": None,
        "outcome_source_sha256": None,
        "outcome_event_path": None,
        "outcome_event_sha256": None,
        "outcome_recorded_at": None,
        "correction_count": 0,
        "last_correction_reason": None,
        "record_mode": capture_mode,
        "historical_result_is_oos": capture_mode == "REALTIME_FORWARD_CAPTURE",
    }


def _apply_outcome(
    *,
    ledger: pd.DataFrame,
    row_index: int,
    outcome_business: dict[str, object],
    outcome_fingerprint: str,
    source_path: Path,
    source_sha: str,
    event_record: dict[str, object],
    correction_reason: str | None,
) -> pd.DataFrame:
    updated = ledger.copy()
    updated.at[row_index, "outcome_status"] = "RESOLVED"
    updated.at[row_index, "label_available"] = True
    updated.at[row_index, "exit_date"] = date.fromisoformat(
        str(outcome_business["exit_date"])
    )
    for column in ("outcome", "raw_return", "directional_return"):
        updated.at[row_index, column] = outcome_business[column]
    updated.at[row_index, "outcome_business_fingerprint"] = outcome_fingerprint
    updated.at[row_index, "outcome_source_path"] = str(source_path)
    updated.at[row_index, "outcome_source_sha256"] = source_sha
    updated.at[row_index, "outcome_event_path"] = str(event_record["path"])
    updated.at[row_index, "outcome_event_sha256"] = str(event_record["sha256"])
    updated.at[row_index, "outcome_recorded_at"] = str(event_record["recorded_at"])
    if correction_reason:
        updated.at[row_index, "correction_count"] = int(
            updated.at[row_index, "correction_count"]
        ) + 1
        updated.at[row_index, "last_correction_reason"] = correction_reason
    return updated


def _append_event(
    *,
    event_root: Path,
    as_of_date: date,
    event_type: str,
    run_id: str,
    event_business: dict[str, object],
    source_path: Path,
    source_sha256: str,
    correction_reason: str | None,
    supersedes_event_sha256: str | None,
    capture_event_sha256: str | None = None,
) -> dict[str, object]:
    recorded_at = datetime.now(UTC)
    event_id = (
        f"{recorded_at:%Y%m%dT%H%M%S%fZ}_{event_type.lower()}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    path = event_root / as_of_date.isoformat() / f"{event_id}.json"
    previous = _latest_event_path(event_root)
    payload = {
        "schema_version": FORWARD_LEDGER_VERSION,
        "ledger_event_id": event_id,
        "event_type": event_type,
        "recorded_at": recorded_at.isoformat(),
        "run_id": run_id,
        "previous_event_sha256": _sha256(previous) if previous else None,
        "capture_event_sha256": capture_event_sha256,
        "supersedes_event_sha256": supersedes_event_sha256,
        "correction_reason": correction_reason,
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "event_business": event_business,
    }
    _atomic_write_json(path, payload)
    return {
        "path": path,
        "sha256": _sha256(path),
        "recorded_at": recorded_at.isoformat(),
    }


def _load_ledger(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    frame = pd.read_parquet(path)
    missing = set(LEDGER_COLUMNS).difference(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"R93D ledger missing columns {sorted(missing)}")
    frame = frame[list(LEDGER_COLUMNS)].copy()
    for column in ("event_date", "capture_as_of_date", "exit_date"):
        frame[column] = (
            pd.to_datetime(frame[column], errors="coerce").dt.date.astype(object)
        )
    if frame[["event_date", "capture_as_of_date"]].isna().any().any():
        raise ResearchWorkbenchError("R93D ledger contains invalid capture dates")
    if frame.duplicated(["hypothesis_id", "event_id"]).any():
        raise ResearchWorkbenchError("R93D ledger contains duplicate candidate events")
    return _normalize_ledger(frame)


def _normalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    normalized = frame[list(LEDGER_COLUMNS)].copy()
    for column in ("strict_forward_eligible", "label_available", "treated"):
        normalized[column] = normalized[column].astype(bool)
    normalized["correction_count"] = pd.to_numeric(
        normalized["correction_count"], errors="coerce"
    ).fillna(0).astype(int)
    return normalized.sort_values(["event_date", "hypothesis_id", "event_id"]).reset_index(
        drop=True
    )


def _ledger_row_index(
    ledger: pd.DataFrame,
    key: tuple[str, str],
) -> int | None:
    if ledger.empty:
        return None
    matches = ledger.index[
        ledger["hypothesis_id"].eq(key[0]) & ledger["event_id"].eq(key[1])
    ]
    return None if len(matches) == 0 else int(matches[0])


def _assert_prior_capture_rows_unchanged(
    *,
    previous: pd.DataFrame,
    current: pd.DataFrame,
) -> None:
    if previous.empty:
        return
    immutable_columns = (
        "hypothesis_id",
        "event_id",
        "event_date",
        "capture_as_of_date",
        "capture_mode",
        "strict_forward_eligible",
        "feature_column",
        "feature_value",
        "observed_feature_value",
        "treated",
        "direction",
        "main_contract",
        "start_stage",
        "start_strength",
        "start_price",
        "horizon",
        "capture_business_fingerprint",
        "capture_event_sha256",
    )
    prior = previous.set_index(["hypothesis_id", "event_id"])
    now = current.set_index(["hypothesis_id", "event_id"])
    if not prior.index.isin(now.index).all():
        raise ResearchWorkbenchError("R93D ledger lost prior capture rows")
    try:
        pd.testing.assert_frame_equal(
            prior[list(immutable_columns[2:])].sort_index(),
            now.loc[prior.index, list(immutable_columns[2:])].sort_index(),
            check_dtype=False,
            check_like=True,
        )
    except AssertionError as exc:
        raise ResearchWorkbenchError(
            "R93D prior immutable capture rows changed during materialization"
        ) from exc


def _validate_event_chain(event_root: Path) -> None:
    if not event_root.exists():
        return
    previous_sha: str | None = None
    for path in sorted(event_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchWorkbenchError(f"R93D invalid ledger event: {path}") from exc
        if payload.get("previous_event_sha256") != previous_sha:
            raise ResearchWorkbenchError(
                f"R93D event checksum chain is broken at {path}"
            )
        previous_sha = _sha256(path)


def _validate_ledger_event_files(ledger: pd.DataFrame) -> None:
    for row in ledger.itertuples(index=False):
        _validate_referenced_event(
            path_value=row.capture_event_path,
            sha_value=row.capture_event_sha256,
            label="CAPTURE",
        )
        if row.outcome_status == "RESOLVED":
            _validate_referenced_event(
                path_value=row.outcome_event_path,
                sha_value=row.outcome_event_sha256,
                label="OUTCOME",
            )


def _validate_referenced_event(
    *,
    path_value: object,
    sha_value: object,
    label: str,
) -> None:
    path_text = _optional_text(path_value)
    expected_sha = _optional_text(sha_value)
    if not path_text or not expected_sha:
        raise ResearchWorkbenchError(f"R93D ledger {label} reference is incomplete")
    path = Path(path_text)
    if not path.exists() or _sha256(path) != expected_sha:
        raise ResearchWorkbenchError(f"R93D ledger {label} checksum mismatch: {path}")


def _build_summary(
    ledger: pd.DataFrame,
    active_hypotheses: tuple[tuple[CandidateHypothesis, str], ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for hypothesis, decision in active_hypotheses:
        group = ledger.loc[ledger["hypothesis_id"].eq(hypothesis.hypothesis_id)]
        strict = group.loc[group["strict_forward_eligible"]]
        resolved = strict.loc[strict["outcome_status"].eq("RESOLVED")]
        treated = resolved.loc[resolved["treated"]]
        control = resolved.loc[~resolved["treated"]]
        rows.append(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "candidate_decision": decision,
                "primary_horizon": hypothesis.primary_horizon,
                "captured_count": len(group),
                "strict_forward_count": len(strict),
                "late_capture_count": int(
                    group["capture_mode"].eq("LATE_BACKFILL_CAPTURE").sum()
                ),
                "pending_count": int(group["outcome_status"].eq("PENDING").sum()),
                "resolved_count": len(resolved),
                "resolved_treated_count": len(treated),
                "resolved_control_count": len(control),
                "treated_follow_through_rate": _optional_hit_rate(treated),
                "control_follow_through_rate": _optional_hit_rate(control),
                "treated_mean_directional_return": _optional_mean_return(treated),
                "control_mean_directional_return": _optional_mean_return(control),
                "evidence_status": (
                    "NO_FORWARD_EVENTS"
                    if group.empty
                    else "COLLECTING_FORWARD_EVIDENCE"
                ),
                "promotion_allowed": False,
                "strategy_change_allowed": False,
                "rule_version": FORWARD_LEDGER_VERSION,
            }
        )
    return pd.DataFrame(rows)


def _warning_records(
    *,
    run_id: str,
    ledger: pd.DataFrame,
    summary: pd.DataFrame,
    capture_appended_count: int,
    correction_appended_count: int,
) -> list[TrendCandidateForwardWarningRecord]:
    warnings: list[TrendCandidateForwardWarningRecord] = []
    if ledger.empty:
        warnings.append(
            TrendCandidateForwardWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93D_NO_POST_REGISTRATION_BREAKOUT",
                warning_message="前向边界后尚无新突破事件，账本保持空白。",
                affected_count=0,
            )
        )
    late_count = int(ledger["capture_mode"].eq("LATE_BACKFILL_CAPTURE").sum())
    if late_count:
        warnings.append(
            TrendCandidateForwardWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93D_LATE_CAPTURE_EXCLUDED",
                warning_message="迟到补录事件已保留，但不计入严格前向证据。",
                affected_count=late_count,
                human_review_required=("late_capture_exclusion_policy",),
            )
        )
    pending_count = int(ledger["outcome_status"].eq("PENDING").sum())
    if pending_count:
        warnings.append(
            TrendCandidateForwardWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93D_OUTCOME_PENDING",
                warning_message="部分CAPTURE尚未达到预登记周期，等待OUTCOME追加。",
                affected_count=pending_count,
            )
        )
    if correction_appended_count:
        warnings.append(
            TrendCandidateForwardWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93D_OUTCOME_CORRECTION_APPENDED",
                warning_message="本次追加了有理由和前序checksum的结果修订事件。",
                affected_count=correction_appended_count,
                human_review_required=("outcome_correction_reason",),
            )
        )
    warnings.extend(
        [
            TrendCandidateForwardWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93D_CAPTURE_APPEND_STATUS",
                warning_message="本次新增CAPTURE数量。",
                affected_count=capture_appended_count,
            ),
            TrendCandidateForwardWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93D_PROMOTION_GATE_NOT_DEFINED",
                warning_message="前向样本晋级门槛尚未定义，任何样本量下都不自动晋级。",
                affected_count=len(summary),
                human_review_required=("minimum_forward_event_promotion_gate",),
            ),
            TrendCandidateForwardWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93D_STRATEGY_ISOLATION",
                warning_message="账本不修改策略、影子手数或composite_score。",
                affected_count=0,
            ),
        ]
    )
    return warnings


def _write_outputs(
    *,
    result: TrendCandidateForwardLedgerResult,
    summary: pd.DataFrame,
    spec: TrendCandidateSpec,
    input_paths: tuple[Path, ...],
    appended_event_paths: tuple[Path, ...],
) -> None:
    result.summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_parquet(result.summary_path, index=False)
    _write_warning_csv(result.warning_csv_path, result.warning_records)
    payload = {
        **result.to_summary(),
        "rule_version": FORWARD_LEDGER_VERSION,
        "active_summary": [
            _json_safe(row) for row in summary.to_dict(orient="records")
        ],
        "registered_at": spec.registered_at.isoformat(),
        "trading_instruction": "not_a_trading_instruction",
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result.markdown_path.write_text(
        _render_markdown(result=result, summary=summary, spec=spec),
        encoding="utf-8",
    )
    artifacts = (
        result.ledger_path,
        result.summary_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        **result.to_summary(),
        "rule_version": FORWARD_LEDGER_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "registered_at": spec.registered_at.isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "appended_event_sha256": {
            str(path): _sha256(path) for path in appended_event_paths
        },
        "trading_instruction": "not_a_trading_instruction",
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: TrendCandidateForwardLedgerResult,
    summary: pd.DataFrame,
    spec: TrendCandidateSpec,
) -> str:
    lines = [
        f"# CF 趋势候选前向事件账本 - {result.as_of_date}",
        "",
        "## 登记状态",
        "",
        f"- 规格登记日：`{spec.registered_at}`",
        f"- 前向生效边界：`{result.effective_after_date}` 之后",
        f"- 活跃假设：`{result.active_hypothesis_count}`",
        f"- 账本行：`{result.ledger_row_count}`",
        f"- 严格前向CAPTURE：`{result.strict_forward_count}`",
        f"- 待结算/已结算：`{result.pending_outcome_count}` / "
        f"`{result.resolved_outcome_count}`",
        "",
        "## 本次变化",
        "",
        f"- 新增CAPTURE：`{result.capture_appended_count}`",
        f"- 新增OUTCOME：`{result.outcome_appended_count}`",
        f"- 新增修订：`{result.correction_appended_count}`",
        f"- 幂等无变化：`{result.no_change_count}`",
        "",
        "## 候选采集进度",
        "",
        "| 假设 | 周期 | 决策 | 捕获 | 严格前向 | 待结算 | 已结算 | 状态 |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {row.hypothesis_id} | {int(row.primary_horizon)}D | "
            f"{row.candidate_decision} | {int(row.captured_count)} | "
            f"{int(row.strict_forward_count)} | {int(row.pending_count)} | "
            f"{int(row.resolved_count)} | {row.evidence_status} |"
        )
    lines.extend(
        [
            "",
            "## 账本规则",
            "",
            "- `CAPTURE`只包含突破当日可观察事实，不包含exit_date、outcome或收益。",
            "- `OUTCOME`必须引用原CAPTURE checksum；相同结果重跑为no-op。",
            "- 结果变化必须提供correction_reason并追加修订事件，原事件不得删除。",
            "- 事件日后才首次捕获的记录标记为LATE_BACKFILL，不计入严格前向统计。",
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- 当前前向晋级门槛尚未定义，报告只展示采集进度，不输出晋级判断。",
            f"- HUMAN_REVIEW_REQUIRED：`{';'.join(HUMAN_REVIEW_REQUIRED)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _status(
    *,
    capture_count: int,
    outcome_count: int,
    correction_count: int,
    ledger_rows: int,
) -> str:
    if correction_count:
        return "FORWARD_LEDGER_OUTCOME_CORRECTED"
    if capture_count or outcome_count:
        return "FORWARD_LEDGER_APPENDED"
    if ledger_rows:
        return "FORWARD_LEDGER_NO_CHANGES"
    return "FORWARD_LEDGER_READY_NO_EVENTS"


def _report_paths(
    *,
    as_of_date: date,
    ledger_root: Path,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    report_root = report_output_dir or (
        reports_dir() / "research" / "trend_candidate_forward_ledger"
    )
    stem = f"CF_{as_of_date}_trend_candidate_forward_ledger"
    return {
        "summary": ledger_root / "summaries" / f"{stem}_summary.parquet",
        "warnings": ledger_root / "summaries" / f"{stem}_warnings.csv",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
        "manifest": ledger_root / "summaries" / f"{stem}_manifest.json",
    }


def _read_parquet(path: Path, required: set[str], label: str) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"{label} path does not exist: {path}")
    frame = pd.read_parquet(path)
    missing = required.difference(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"{label} missing columns {sorted(missing)}")
    return frame.copy()


def _optional_hit_rate(frame: pd.DataFrame) -> float | None:
    return None if frame.empty else float(frame["outcome"].eq("FOLLOW_THROUGH").mean())


def _optional_mean_return(frame: pd.DataFrame) -> float | None:
    return None if frame.empty else float(frame["directional_return"].mean())


def _finite_float(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchWorkbenchError(f"R93D invalid {label}: {value}") from exc
    if not math.isfinite(number):
        raise ResearchWorkbenchError(f"R93D invalid {label}: {value}")
    return number


def _optional_text(value: object) -> str | None:
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value)
    return text if text and text.lower() != "nan" else None


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(record: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
        elif value is None or value is pd.NA:
            result[key] = None
        elif isinstance(value, float) and math.isnan(value):
            result[key] = None
        elif isinstance(value, np.generic):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _write_warning_csv(
    path: Path,
    warnings: tuple[TrendCandidateForwardWarningRecord, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for warning in warnings:
            writer.writerow(warning.to_csv_row())


def _latest_event_path(event_root: Path) -> Path | None:
    if not event_root.exists():
        return None
    paths = sorted(event_root.rglob("*.json"))
    return paths[-1] if paths else None


def _latest_symmetric_daily_path() -> Path:
    return _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "symmetric_trend",
        "*_symmetric_trend_daily.parquet",
        "R93A symmetric daily",
    )


def _latest_breakout_event_path() -> Path:
    return _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "symmetric_trend",
        "*_symmetric_trend_breakout_event_horizon.parquet",
        "R93A breakout event",
    )


def _latest_candidate_evaluation_path() -> Path:
    return _latest_path(
        data_dir() / "research" / PRODUCT_CODE / "trend_candidate_stability",
        "*_trend_candidate_stability_primary_evaluation.parquet",
        "R93C primary evaluation",
    )


def _latest_path(root: Path, pattern: str, label: str) -> Path:
    paths = sorted(root.glob(pattern))
    if not paths:
        raise ResearchWorkbenchError(f"{label} not found under {root}")
    return paths[-1]


def _default_spec_path() -> Path:
    return project_root() / "configs" / "research" / "CF_trend_candidate_preregistration_v1.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(as_of_date: date) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cf_trend_forward_{as_of_date:%Y%m%d}_{stamp}_{uuid.uuid4().hex[:8]}"
