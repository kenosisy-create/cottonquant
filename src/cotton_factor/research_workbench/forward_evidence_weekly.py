"""R93E CF 策略与趋势候选的周度前向证据汇总。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir

PRODUCT_CODE = "CF"
FORWARD_EVIDENCE_WEEKLY_VERSION = "V5.1_R93E_forward_evidence_weekly_v1"
GOVERNANCE_TARGET_DAYS = 40
INFO = "INFO"
WARN = "WARN"
SHADOW_REQUIRED_COLUMNS = {
    "trade_date",
    "strategy_key",
    "record_mode",
    "event_type",
    "net_pnl",
    "nav",
    "drawdown",
}
CANDIDATE_REQUIRED_COLUMNS = {
    "hypothesis_id",
    "event_id",
    "event_date",
    "capture_as_of_date",
    "capture_mode",
    "strict_forward_eligible",
    "candidate_decision",
    "treated",
    "direction",
    "horizon",
    "outcome_status",
    "label_available",
    "outcome",
    "directional_return",
    "correction_count",
    "historical_result_is_oos",
    "strategy_change_allowed",
}
WARNING_COLUMNS = (
    "run_id",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)
HUMAN_REVIEW_REQUIRED = (
    "forward_evidence_interpretation",
    "outcome_correction_reason_review",
    "promotion_requires_explicit_approval",
)
RESEARCH_BOUNDARY = (
    "策略影子交易日与趋势候选事件是两条独立前向证据通道：40个真实前向交易日仅是阶段治理门槛，"
    "不是统计有效性证明；候选结果只能在预登记5D/20D周期到期后追加。"
    "历史回放、迟到补录和修订不得伪装为严格前向证据，不构成交易指令，NAV非真实资金。"
)


@dataclass(frozen=True)
class ForwardEvidenceWeeklyWarningRecord:
    """R93E 警告记录。"""

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
class ForwardEvidenceWeeklyResult:
    """R93E 周度前向证据汇总结果。"""

    run_id: str
    as_of_date: date
    status: str
    strategy_count: int
    strategy_forward_days: int
    governance_target_days: int
    governance_days_remaining: int
    candidate_capture_count: int
    candidate_unique_event_count: int
    candidate_pending_count: int
    candidate_resolved_count: int
    candidate_late_capture_count: int
    candidate_correction_count: int
    summary_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[ForwardEvidenceWeeklyWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        return sum(item.severity == WARN for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "as_of_date": self.as_of_date.isoformat(),
            "status": self.status,
            "strategy_count": self.strategy_count,
            "strategy_forward_days": self.strategy_forward_days,
            "governance_target_days": self.governance_target_days,
            "governance_days_remaining": self.governance_days_remaining,
            "candidate_capture_count": self.candidate_capture_count,
            "candidate_unique_event_count": self.candidate_unique_event_count,
            "candidate_pending_count": self.candidate_pending_count,
            "candidate_resolved_count": self.candidate_resolved_count,
            "candidate_late_capture_count": self.candidate_late_capture_count,
            "candidate_correction_count": self.candidate_correction_count,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "summary_path": str(self.summary_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "research_boundary": RESEARCH_BOUNDARY,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_forward_evidence_weekly(
    *,
    as_of_date: date | None = None,
    strategy_ledger_root: Path | None = None,
    candidate_ledger_path: Path | None = None,
    candidate_event_root: Path | None = None,
    candidate_run_json_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ForwardEvidenceWeeklyResult:
    """汇总两条前向通道，不重新计算策略或候选结果。"""

    shadow_root = strategy_ledger_root or data_dir() / "strategy" / PRODUCT_CODE
    shadow_paths = sorted(shadow_root.glob("*_shadow_ledger.parquet"))
    if not shadow_paths:
        raise ResearchWorkbenchError(f"R93E shadow ledger not found under {shadow_root}")
    shadow_frames = {path: _load_shadow_ledger(path) for path in shadow_paths}
    non_empty_shadow_dates = [
        frame["_trade_date"].max()
        for frame in shadow_frames.values()
        if not frame.empty
    ]
    if not non_empty_shadow_dates:
        raise ResearchWorkbenchError("R93E shadow ledgers contain no rows")
    latest_shadow_date = max(non_empty_shadow_dates)
    active_as_of = as_of_date or latest_shadow_date
    active_run_id = run_id or _default_run_id(active_as_of)

    ledger_path = candidate_ledger_path or (
        data_dir()
        / "research"
        / PRODUCT_CODE
        / "trend_candidate_forward_ledger"
        / "trend_candidate_forward_ledger.parquet"
    )
    candidate = _load_candidate_ledger(
        ledger_path,
        required=candidate_ledger_path is not None,
    )
    event_root = candidate_event_root or ledger_path.parent / "events"
    event_counts = _validate_candidate_event_chain(event_root, required=not candidate.empty)

    run_json_path = candidate_run_json_path or _latest_candidate_run_json()
    candidate_run = _load_candidate_run_json(
        run_json_path,
        required=candidate_run_json_path is not None,
    )

    strategy_summary, strategy_forward_dates = _build_strategy_summary(
        shadow_frames,
        active_as_of,
    )
    candidate_selected = _select_candidate_rows(candidate, active_as_of)
    candidate_summary = _build_candidate_summary(candidate_selected)
    warning_records = _build_warnings(
        run_id=active_run_id,
        as_of_date=active_as_of,
        strategy_summary=strategy_summary,
        strategy_forward_days=len(strategy_forward_dates),
        candidate=candidate_selected,
        candidate_run=candidate_run,
        event_counts=event_counts,
    )
    status = _status(warning_records, candidate_selected)
    strict_candidate = candidate_selected.loc[
        candidate_selected["strict_forward_eligible"].astype(bool)
    ]
    paths = _output_paths(
        as_of_date=active_as_of,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    result = ForwardEvidenceWeeklyResult(
        run_id=active_run_id,
        as_of_date=active_as_of,
        status=status,
        strategy_count=len(strategy_summary),
        strategy_forward_days=len(strategy_forward_dates),
        governance_target_days=GOVERNANCE_TARGET_DAYS,
        governance_days_remaining=max(
            GOVERNANCE_TARGET_DAYS - len(strategy_forward_dates), 0
        ),
        candidate_capture_count=len(candidate_selected),
        candidate_unique_event_count=int(candidate_selected["event_id"].nunique()),
        candidate_pending_count=int(
            candidate_selected["outcome_status"].eq("PENDING").sum()
        ),
        candidate_resolved_count=int(
            strict_candidate["outcome_status"].eq("RESOLVED").sum()
        ),
        candidate_late_capture_count=int(
            candidate_selected["capture_mode"].eq("LATE_BACKFILL_CAPTURE").sum()
        ),
        candidate_correction_count=int(
            pd.to_numeric(
                candidate_selected["correction_count"], errors="coerce"
            ).fillna(0).sum()
        ),
        summary_path=paths["summary"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=tuple(warning_records),
    )
    input_paths = [*shadow_paths]
    if ledger_path.exists():
        input_paths.append(ledger_path)
    if run_json_path is not None and run_json_path.exists():
        input_paths.append(run_json_path)
    input_paths.extend(sorted(event_root.rglob("*.json")) if event_root.exists() else [])
    _write_outputs(
        result=result,
        strategy_summary=strategy_summary,
        candidate_summary=candidate_summary,
        candidate_run=candidate_run,
        event_counts=event_counts,
        input_paths=tuple(input_paths),
    )
    return result


def _load_shadow_ledger(path: Path) -> pd.DataFrame:
    frame = _read_parquet(path, SHADOW_REQUIRED_COLUMNS, "R93E shadow ledger")
    parsed = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    if parsed.isna().any():
        raise ResearchWorkbenchError(f"R93E shadow ledger has invalid trade_date: {path}")
    if parsed.duplicated().any():
        raise ResearchWorkbenchError(f"R93E shadow ledger has duplicate trade_date: {path}")
    result = frame.copy()
    result["_trade_date"] = parsed
    return result.sort_values("_trade_date").reset_index(drop=True)


def _load_candidate_ledger(path: Path, *, required: bool) -> pd.DataFrame:
    if not path.exists():
        if required:
            raise ResearchWorkbenchError(f"R93E candidate ledger does not exist: {path}")
        return pd.DataFrame(columns=sorted(CANDIDATE_REQUIRED_COLUMNS))
    frame = _read_parquet(path, CANDIDATE_REQUIRED_COLUMNS, "R93E candidate ledger")
    if frame.duplicated(["hypothesis_id", "event_id"]).any():
        raise ResearchWorkbenchError("R93E candidate ledger has duplicate hypothesis/event")
    result = frame.copy()
    for column in ("event_date", "capture_as_of_date"):
        result[f"_{column}"] = pd.to_datetime(
            result[column], errors="coerce"
        ).dt.date
    if result[["_event_date", "_capture_as_of_date"]].isna().any().any():
        raise ResearchWorkbenchError("R93E candidate ledger contains invalid dates")
    for column in (
        "strict_forward_eligible",
        "label_available",
        "treated",
        "historical_result_is_oos",
        "strategy_change_allowed",
    ):
        result[column] = result[column].fillna(False).astype(bool)
    if result["strategy_change_allowed"].any():
        raise ResearchWorkbenchError("R93E candidate ledger must not allow strategy changes")
    invalid_oos = result["strict_forward_eligible"] & ~result["historical_result_is_oos"]
    if invalid_oos.any():
        raise ResearchWorkbenchError("R93E strict forward rows must be marked OOS")
    return result.sort_values(
        ["_event_date", "hypothesis_id", "event_id"]
    ).reset_index(drop=True)


def _select_candidate_rows(frame: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame.loc[
        frame["_event_date"].le(as_of_date)
        & frame["_capture_as_of_date"].le(as_of_date)
    ].copy()


def _load_candidate_run_json(
    path: Path | None,
    *,
    required: bool,
) -> dict[str, object] | None:
    if path is None or not path.exists():
        if required:
            raise ResearchWorkbenchError(f"R93E candidate run JSON does not exist: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchWorkbenchError(f"R93E invalid candidate run JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ResearchWorkbenchError(f"R93E candidate run JSON must be an object: {path}")
    return payload


def _build_strategy_summary(
    frames: dict[Path, pd.DataFrame],
    as_of_date: date,
) -> tuple[pd.DataFrame, set[date]]:
    rows: list[dict[str, object]] = []
    all_forward_dates: set[date] = set()
    for path, frame in frames.items():
        selected = frame.loc[frame["_trade_date"].le(as_of_date)].copy()
        if selected.empty:
            continue
        latest = selected.iloc[-1]
        forward = selected.loc[selected["record_mode"].eq("FORWARD_CAPTURE")]
        forward_dates = set(forward["_trade_date"].tolist())
        all_forward_dates.update(forward_dates)
        correction = selected.loc[selected["event_type"].eq("CORRECTION")]
        unexplained_correction_count = 0
        if not correction.empty:
            reasons = correction.get(
                "overwrite_reason", pd.Series(index=correction.index, dtype="object")
            )
            unexplained_correction_count = int(
                reasons.fillna("").astype(str).str.strip().eq("").sum()
            )
        rows.append(
            {
                "strategy_key": str(latest["strategy_key"]),
                "ledger_path": str(path),
                "latest_date": latest["_trade_date"].isoformat(),
                "total_row_count": len(selected),
                "historical_replay_days": int(
                    selected.loc[
                        selected["record_mode"].eq("HISTORICAL_REPLAY"), "_trade_date"
                    ].nunique()
                ),
                "forward_capture_days": len(forward_dates),
                "first_forward_date": (
                    min(forward_dates).isoformat() if forward_dates else None
                ),
                "latest_nav": _finite_or_none(latest["nav"]),
                "forward_net_pnl": float(
                    pd.to_numeric(forward["net_pnl"], errors="coerce").fillna(0).sum()
                ),
                "latest_drawdown": _finite_or_none(latest["drawdown"]),
                "latest_target_lots": _optional_int(latest.get("target_lots")),
                "latest_target_contract": _optional_text(
                    latest.get("target_contract")
                ),
                "latest_held_lots": _optional_int(latest.get("held_lots_after")),
                "correction_count": len(correction),
                "unexplained_correction_count": unexplained_correction_count,
            }
        )
    if not rows:
        raise ResearchWorkbenchError(f"R93E no shadow rows on or before {as_of_date}")
    return pd.DataFrame(rows), all_forward_dates


def _build_candidate_summary(frame: pd.DataFrame) -> pd.DataFrame:
    columns = (
        "hypothesis_id",
        "candidate_decision",
        "horizon",
        "captured_count",
        "strict_forward_count",
        "treated_count",
        "control_count",
        "pending_count",
        "resolved_count",
        "late_capture_count",
        "correction_count",
        "follow_through_rate",
        "mean_directional_return",
        "evidence_status",
        "promotion_allowed",
    )
    if frame.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for hypothesis_id, group in frame.groupby("hypothesis_id", sort=True):
        strict = group.loc[group["strict_forward_eligible"]]
        resolved = strict.loc[strict["outcome_status"].eq("RESOLVED")]
        rows.append(
            {
                "hypothesis_id": str(hypothesis_id),
                "candidate_decision": str(group.iloc[-1]["candidate_decision"]),
                "horizon": int(pd.to_numeric(group["horizon"]).iloc[-1]),
                "captured_count": len(group),
                "strict_forward_count": len(strict),
                "treated_count": int(strict["treated"].sum()),
                "control_count": int((~strict["treated"]).sum()),
                "pending_count": int(group["outcome_status"].eq("PENDING").sum()),
                "resolved_count": len(resolved),
                "late_capture_count": int(
                    group["capture_mode"].eq("LATE_BACKFILL_CAPTURE").sum()
                ),
                "correction_count": int(
                    pd.to_numeric(group["correction_count"], errors="coerce")
                    .fillna(0)
                    .sum()
                ),
                "follow_through_rate": (
                    None
                    if resolved.empty
                    else float(resolved["outcome"].eq("FOLLOW_THROUGH").mean())
                ),
                "mean_directional_return": (
                    None
                    if resolved.empty
                    else float(
                        pd.to_numeric(
                            resolved["directional_return"], errors="coerce"
                        ).mean()
                    )
                ),
                "evidence_status": (
                    "FORWARD_OUTCOME_AVAILABLE"
                    if not resolved.empty
                    else "COLLECTING_FORWARD_EVIDENCE"
                ),
                "promotion_allowed": False,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _build_warnings(
    *,
    run_id: str,
    as_of_date: date,
    strategy_summary: pd.DataFrame,
    strategy_forward_days: int,
    candidate: pd.DataFrame,
    candidate_run: dict[str, object] | None,
    event_counts: dict[str, int],
) -> list[ForwardEvidenceWeeklyWarningRecord]:
    warnings: list[ForwardEvidenceWeeklyWarningRecord] = [
        ForwardEvidenceWeeklyWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93E_STRATEGY_GATE_PROGRESS",
            warning_message="40日仅为R94-R99阶段治理门槛，不是策略有效性证明。",
            affected_count=strategy_forward_days,
        ),
        ForwardEvidenceWeeklyWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93E_NO_AUTO_PROMOTION",
            warning_message="本模块不定义自动晋级，不修改策略、目标手数或composite_score。",
            affected_count=0,
        ),
    ]
    stale_strategy_count = int(
        (~strategy_summary["latest_date"].eq(as_of_date.isoformat())).sum()
    )
    if stale_strategy_count:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93E_SHADOW_LEDGER_STALE",
                warning_message="部分策略影子账本未更新至汇总日期。",
                affected_count=stale_strategy_count,
            )
        )
    if strategy_forward_days == 0:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93E_NO_STRICT_STRATEGY_FORWARD_DAY",
                warning_message="尚无可计入治理门槛的FORWARD_CAPTURE交易日。",
                affected_count=0,
            )
        )
    unexplained_corrections = int(
        strategy_summary["unexplained_correction_count"].sum()
    )
    if unexplained_corrections:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93E_UNEXPLAINED_SHADOW_CORRECTION",
                warning_message="影子修订缺少可核对原因。",
                affected_count=unexplained_corrections,
                human_review_required=("outcome_correction_reason_review",),
            )
        )
    explained_corrections = int(strategy_summary["correction_count"].sum()) - (
        unexplained_corrections
    )
    if explained_corrections:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93E_EXPLAINED_SHADOW_CORRECTION_PRESENT",
                warning_message="影子账本含有带原因的修订，保留展示但不视为新增前向样本。",
                affected_count=explained_corrections,
            )
        )

    run_as_of = _parse_optional_date(
        candidate_run.get("as_of_date") if candidate_run else None
    )
    if candidate_run is None:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93E_CANDIDATE_REFRESH_UNVERIFIED",
                warning_message="缺少R93D当期运行摘要，无法确认候选账本已刷新至汇总日期。",
                affected_count=0,
            )
        )
    elif run_as_of != as_of_date:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93E_CANDIDATE_REFRESH_STALE",
                warning_message="R93D运行摘要日期与周度汇总日期不一致。",
                affected_count=1,
            )
        )
    if candidate.empty:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93E_NO_CANDIDATE_EVENT_YET",
                warning_message="前向边界后尚无候选事件，只报告采集链健康度。",
                affected_count=0,
            )
        )
    pending_count = int(candidate["outcome_status"].eq("PENDING").sum())
    if pending_count:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=INFO,
                warning_code="R93E_CANDIDATE_OUTCOME_PENDING",
                warning_message="候选CAPTURE尚未达到预登记周期，不能提前生成结果。",
                affected_count=pending_count,
            )
        )
    late_count = int(candidate["capture_mode"].eq("LATE_BACKFILL_CAPTURE").sum())
    if late_count:
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93E_LATE_CAPTURE_EXCLUDED",
                warning_message="迟到补录已保留，但不计入严格前向证据。",
                affected_count=late_count,
            )
        )
    correction_count = int(
        pd.to_numeric(candidate["correction_count"], errors="coerce").fillna(0).sum()
    )
    if correction_count or event_counts.get("OUTCOME_CORRECTION", 0):
        warnings.append(
            ForwardEvidenceWeeklyWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93E_CANDIDATE_OUTCOME_CORRECTION_PRESENT",
                warning_message="候选结果含有追加修订，须按理由链复核，不得覆盖原事件。",
                affected_count=max(
                    correction_count, event_counts.get("OUTCOME_CORRECTION", 0)
                ),
                human_review_required=("outcome_correction_reason_review",),
            )
        )
    return warnings


def _validate_candidate_event_chain(
    event_root: Path,
    *,
    required: bool,
) -> dict[str, int]:
    paths = sorted(event_root.rglob("*.json")) if event_root.exists() else []
    if required and not paths:
        raise ResearchWorkbenchError(f"R93E candidate event chain not found: {event_root}")
    previous_sha: str | None = None
    counts: dict[str, int] = {}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchWorkbenchError(f"R93E invalid candidate event: {path}") from exc
        if payload.get("previous_event_sha256") != previous_sha:
            raise ResearchWorkbenchError(
                f"R93E candidate event checksum chain is broken at {path}"
            )
        event_type = str(payload.get("event_type", "UNKNOWN"))
        counts[event_type] = counts.get(event_type, 0) + 1
        previous_sha = _sha256(path)
    return counts


def _write_outputs(
    *,
    result: ForwardEvidenceWeeklyResult,
    strategy_summary: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    candidate_run: dict[str, object] | None,
    event_counts: dict[str, int],
    input_paths: tuple[Path, ...],
) -> None:
    result.summary_path.parent.mkdir(parents=True, exist_ok=True)
    channel_rows: list[dict[str, object]] = []
    for row in strategy_summary.to_dict(orient="records"):
        channel_rows.append(
            {
                "channel": "STRATEGY_SHADOW",
                "item_id": row["strategy_key"],
                "latest_date": row["latest_date"],
                "forward_observation_count": row["forward_capture_days"],
                "pending_count": 0,
                "resolved_count": 0,
                "correction_count": row["correction_count"],
                "status": "COLLECTING",
            }
        )
    for row in candidate_summary.to_dict(orient="records"):
        channel_rows.append(
            {
                "channel": "TREND_CANDIDATE",
                "item_id": row["hypothesis_id"],
                "latest_date": result.as_of_date.isoformat(),
                "forward_observation_count": row["strict_forward_count"],
                "pending_count": row["pending_count"],
                "resolved_count": row["resolved_count"],
                "correction_count": row["correction_count"],
                "status": row["evidence_status"],
            }
        )
    pd.DataFrame(
        channel_rows,
        columns=(
            "channel",
            "item_id",
            "latest_date",
            "forward_observation_count",
            "pending_count",
            "resolved_count",
            "correction_count",
            "status",
        ),
    ).to_parquet(result.summary_path, index=False)
    _write_warning_csv(result.warning_csv_path, result.warning_records)
    payload = {
        **result.to_summary(),
        "rule_version": FORWARD_EVIDENCE_WEEKLY_VERSION,
        "strategy_summary": [
            _json_safe(row) for row in strategy_summary.to_dict(orient="records")
        ],
        "candidate_summary": [
            _json_safe(row) for row in candidate_summary.to_dict(orient="records")
        ],
        "candidate_run_status": candidate_run.get("status") if candidate_run else None,
        "candidate_event_type_counts": event_counts,
        "promotion_allowed": False,
        "trading_instruction": "not_a_trading_instruction",
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result.markdown_path.write_text(
        _render_markdown(
            result=result,
            strategy_summary=strategy_summary,
            candidate_summary=candidate_summary,
            candidate_run=candidate_run,
            event_counts=event_counts,
        ),
        encoding="utf-8",
    )
    artifacts = (
        result.summary_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        **result.to_summary(),
        "rule_version": FORWARD_EVIDENCE_WEEKLY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "promotion_allowed": False,
        "trading_instruction": "not_a_trading_instruction",
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: ForwardEvidenceWeeklyResult,
    strategy_summary: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    candidate_run: dict[str, object] | None,
    event_counts: dict[str, int],
) -> str:
    lines = [
        f"# CF 周度前向证据汇总 - {result.as_of_date}",
        "",
        "## 当前结论",
        "",
        f"- 采集状态：`{result.status}`。",
        f"- 策略影子严格前向交易日：`{result.strategy_forward_days}` / "
        f"`{result.governance_target_days}`，治理门槛尚余 "
        f"`{result.governance_days_remaining}` 日。",
        f"- 趋势候选：`{result.candidate_unique_event_count}` 个独立突破事件、"
        f"`{result.candidate_capture_count}` 条假设CAPTURE、"
        f"`{result.candidate_pending_count}` 条待结算、"
        f"`{result.candidate_resolved_count}` 条已结算。",
        "- 40日与5D/20D是不同口径：前者检查策略运行连续性，后者验证预登记候选。",
        "",
        "## 两条前向通道",
        "",
        "| 通道 | 观察对象 | 当前用途 | 不代表 |",
        "| --- | --- | --- | --- |",
        "| 策略影子 | 每日真实合约T+1记账 | 连续性、成本、NAV和阶段治理 | 自动证明策略有效 |",
        "| 趋势候选 | 突破当日CAPTURE及到期OUTCOME | 验证H1/H2的5D/20D增量 | 自动修改方向或仓位 |",
        "",
        "## 策略影子进度",
        "",
        "| 策略 | 最新日 | 前向日 | 前向净损益 | NAV | 回撤 | 当前持仓 | 当日目标 | 修订 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for row in strategy_summary.itertuples(index=False):
        lines.append(
            f"| {row.strategy_key} | {row.latest_date} | {int(row.forward_capture_days)} | "
            f"{float(row.forward_net_pnl):.2f} | {_format_number(row.latest_nav)} | "
            f"{_format_percent(row.latest_drawdown)} | "
            f"{_format_optional_int(row.latest_held_lots)} | "
            f"{row.latest_target_contract or '-'} "
            f"{_format_optional_int(row.latest_target_lots)}手 | "
            f"{int(row.correction_count)} |"
        )
    lines.extend(
        [
            "",
            "## 趋势候选进度",
            "",
            "| 假设 | 周期 | 严格CAPTURE | 处理/对照 | 待结算 | 已结算 | 命中率 | 平均方向收益 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    if candidate_summary.empty:
        lines.append("| 暂无候选事件 | - | 0 | 0/0 | 0 | 0 | - | - |")
    else:
        for row in candidate_summary.itertuples(index=False):
            lines.append(
                f"| {row.hypothesis_id} | {int(row.horizon)}D | "
                f"{int(row.strict_forward_count)} | {int(row.treated_count)}/"
                f"{int(row.control_count)} | {int(row.pending_count)} | "
                f"{int(row.resolved_count)} | {_format_percent(row.follow_through_rate)} | "
                f"{_format_percent(row.mean_directional_return)} |"
            )
    run_status = candidate_run.get("status") if candidate_run else "NOT_VERIFIED"
    lines.extend(
        [
            "",
            "## 采集健康度",
            "",
            f"- R93D当期状态：`{run_status}`。",
            f"- 不可变事件数：CAPTURE `{event_counts.get('CAPTURE', 0)}`，"
            f"OUTCOME `{event_counts.get('OUTCOME', 0)}`，"
            f"OUTCOME_CORRECTION `{event_counts.get('OUTCOME_CORRECTION', 0)}`。",
            f"- 迟到补录：`{result.candidate_late_capture_count}`；"
            f"候选结果修订：`{result.candidate_correction_count}`。",
            "",
            "## 当前可以与不可以判断",
            "",
            "- 可以确认：前向采集链是否连续、突破是否在结果形成前落账、到期结果是否按规则追加。",
            "- 尚不能确认：当前候选是否稳定有效；未到期CAPTURE不得提前解释为成功或失败。",
            "- 即使达到40个影子交易日，也仍需结合成本后表现、账务差异和候选事件结果进行阶段审查。",
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- 本报告不自动晋级、不自动反转方向、不修改现有影子策略。",
            f"- HUMAN_REVIEW_REQUIRED：`{';'.join(HUMAN_REVIEW_REQUIRED)}`。",
        ]
    )
    return "\n".join(lines) + "\n"


def _status(
    warnings: list[ForwardEvidenceWeeklyWarningRecord],
    candidate: pd.DataFrame,
) -> str:
    if any(item.severity == WARN for item in warnings):
        return "FORWARD_COLLECTION_WATCH"
    if candidate.empty:
        return "FORWARD_COLLECTION_HEALTHY_NO_CANDIDATE_EVENTS"
    return "FORWARD_COLLECTION_HEALTHY"


def _output_paths(
    *,
    as_of_date: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    data_root = output_dir or (
        data_dir() / "research" / PRODUCT_CODE / "forward_evidence_weekly"
    )
    report_root = report_output_dir or (
        reports_dir() / "research" / "forward_evidence_weekly"
    )
    stem = f"CF_{as_of_date}_forward_evidence_weekly"
    return {
        "summary": data_root / f"{stem}_summary.parquet",
        "warnings": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
    }


def _latest_candidate_run_json() -> Path | None:
    root = reports_dir() / "research" / "trend_candidate_forward_ledger"
    if not root.exists():
        return None
    paths = sorted(root.glob("CF_*_trend_candidate_forward_ledger.json"))
    return paths[-1] if paths else None


def _read_parquet(path: Path, required: set[str], label: str) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"{label} path does not exist: {path}")
    frame = pd.read_parquet(path)
    missing = required.difference(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"{label} missing columns {sorted(missing)}")
    return frame.copy()


def _write_warning_csv(
    path: Path,
    records: tuple[ForwardEvidenceWeeklyWarningRecord, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows(record.to_csv_row() for record in records)


def _parse_optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def _format_number(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.2f}"


def _format_percent(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.2%}"


def _format_optional_int(value: object) -> str:
    parsed = _optional_int(value)
    return "-" if parsed is None else str(parsed)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(as_of_date: date) -> str:
    return (
        f"cf_forward_evidence_weekly_{as_of_date:%Y%m%d}_"
        f"{datetime.now(UTC):%H%M%S}_{uuid.uuid4().hex[:8]}"
    )
