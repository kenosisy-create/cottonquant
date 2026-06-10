"""Append-only audit log helpers for formal archive runs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from cotton_factor.common.exceptions import ArchiveError
from cotton_factor.common.time import utc_now

DEFAULT_AUDIT_LOG_VERSION = "audit_log_v1"
AUDIT_SEVERITIES = ("info", "warning", "error", "human_review")


@dataclass(frozen=True)
class AuditEvent:
    """One append-only audit event."""

    run_id: str
    event_type: str
    message: str
    created_at_utc: datetime
    severity: str = "info"
    payload: dict[str, object] = field(default_factory=dict)
    audit_version: str = DEFAULT_AUDIT_LOG_VERSION


@dataclass(frozen=True)
class AuditLogWriter:
    """Small writer facade for appending events to one JSONL audit log."""

    path: Path

    def record(
        self,
        *,
        run_id: str,
        event_type: str,
        message: str,
        severity: str = "info",
        payload: Mapping[str, object] | None = None,
        created_at_utc: datetime | None = None,
    ) -> AuditEvent:
        """Build and append one audit event."""
        event = build_audit_event(
            run_id=run_id,
            event_type=event_type,
            message=message,
            severity=severity,
            payload=payload,
            created_at_utc=created_at_utc,
        )
        write_audit_event(self.path, event)
        return event


def build_audit_event(
    *,
    run_id: str,
    event_type: str,
    message: str,
    severity: str = "info",
    payload: Mapping[str, object] | None = None,
    created_at_utc: datetime | None = None,
) -> AuditEvent:
    """Create one validated audit event."""
    if not run_id:
        raise ArchiveError("audit event requires run_id")
    if not event_type:
        raise ArchiveError("audit event requires event_type")
    if not message:
        raise ArchiveError("audit event requires message")
    if severity not in AUDIT_SEVERITIES:
        raise ArchiveError(f"audit severity must be one of {AUDIT_SEVERITIES}: {severity}")

    event_payload = dict(payload or {})
    _assert_json_serializable(event_payload, context="audit payload")
    # 审计日志只记录运行决策、告警和人工复核项；它不解析或改写任何交易所原始文件。
    return AuditEvent(
        run_id=run_id,
        event_type=event_type,
        message=message,
        created_at_utc=created_at_utc or utc_now(),
        severity=severity,
        payload=event_payload,
    )


def write_audit_event(path: Path, event: AuditEvent) -> Path:
    """Append one audit event to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _event_to_dict(event)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def write_audit_log(events: Sequence[AuditEvent], path: Path) -> Path:
    """Write a complete JSONL audit log from ordered events."""
    if not events:
        raise ArchiveError("audit log requires at least one event")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(_event_to_dict(event), ensure_ascii=False, sort_keys=True)
        for event in events
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_audit_log(path: Path) -> list[AuditEvent]:
    """Read and validate an audit JSONL file."""
    if not path.exists() or not path.is_file():
        raise ArchiveError(f"audit log not found: {path}")

    events: list[AuditEvent] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArchiveError(f"audit log line {line_number} is not valid JSON") from exc
        events.append(_event_from_dict(payload, line_number=line_number))
    return events


def _event_to_dict(event: AuditEvent) -> dict[str, object]:
    payload = asdict(event)
    payload["created_at_utc"] = event.created_at_utc.isoformat()
    _assert_json_serializable(payload, context="audit event")
    return payload


def _event_from_dict(payload: object, *, line_number: int) -> AuditEvent:
    if not isinstance(payload, dict):
        raise ArchiveError(f"audit log line {line_number} must be a JSON object")

    try:
        created_at_raw = payload["created_at_utc"]
        created_at_utc = datetime.fromisoformat(str(created_at_raw))
    except (KeyError, ValueError) as exc:
        raise ArchiveError(f"audit log line {line_number} has invalid created_at_utc") from exc
    if created_at_utc.tzinfo is None:
        raise ArchiveError(f"audit log line {line_number} created_at_utc must be timezone-aware")

    payload_value = payload.get("payload", {})
    if not isinstance(payload_value, dict):
        raise ArchiveError(f"audit log line {line_number} payload must be an object")

    return build_audit_event(
        run_id=str(payload.get("run_id", "")),
        event_type=str(payload.get("event_type", "")),
        message=str(payload.get("message", "")),
        severity=str(payload.get("severity", "info")),
        payload=payload_value,
        created_at_utc=created_at_utc,
    )


def _assert_json_serializable(value: object, *, context: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError as exc:
        raise ArchiveError(f"{context} must be JSON serializable") from exc
