"""Immutable raw snapshot store."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from cotton_factor.common.exceptions import RawSnapshotError, RawSnapshotIntegrityError
from cotton_factor.common.hashing import sha256_bytes, sha256_file
from cotton_factor.common.paths import data_dir
from cotton_factor.common.time import utc_now
from cotton_factor.raw.snapshot_manifest import Metadata, RawSnapshotRecord, SnapshotManifest

_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class RawSnapshot:
    """Replayed raw snapshot payload plus its manifest record."""

    record: RawSnapshotRecord
    payload: bytes


class RawSnapshotStore:
    """Write-once raw payload store with manifest-based replay."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir() / "raw"
        self.snapshots_dir = self.root / "snapshots"
        self.manifest = SnapshotManifest(self.root / "manifest.jsonl")

    def write_snapshot(
        self,
        *,
        payload: bytes,
        source_name: str,
        product_code: str,
        content_type: str,
        biz_date: date | str | None = None,
        metadata: Metadata | None = None,
        parser_version: str | None = None,
        captured_at_utc: datetime | None = None,
    ) -> RawSnapshotRecord:
        """Persist one raw payload and append its manifest record.

        The store never parses payload contents; it only records lineage and
        integrity metadata needed by downstream normalized layers.
        """
        source_segment = _safe_segment(source_name, "source_name")
        product_segment = _safe_segment(product_code, "product_code")
        biz_date_value = _coerce_biz_date(biz_date)
        biz_date_segment = biz_date_value or "no_biz_date"
        content_type_value = _required_text(content_type, "content_type")
        captured_at = captured_at_utc or utc_now()

        payload_sha256 = sha256_bytes(payload)
        snapshot_id = _new_snapshot_id(captured_at, payload_sha256)
        relative_payload_path = Path(
            "snapshots",
            source_segment,
            product_segment,
            biz_date_segment,
            snapshot_id,
            "payload.bin",
        )
        payload_path = self.root / relative_payload_path
        payload_path.parent.mkdir(parents=True, exist_ok=False)

        with payload_path.open("xb") as handle:
            handle.write(payload)

        file_sha256 = sha256_file(payload_path)
        if file_sha256 != payload_sha256:
            raise RawSnapshotIntegrityError(f"snapshot write checksum mismatch: {snapshot_id}")

        record = RawSnapshotRecord(
            snapshot_id=snapshot_id,
            source_name=source_name,
            product_code=product_code,
            biz_date=biz_date_value,
            captured_at_utc=captured_at,
            content_type=content_type_value,
            byte_size=len(payload),
            sha256=payload_sha256,
            payload_path=relative_payload_path.as_posix(),
            parser_version=parser_version,
            metadata=dict(metadata or {}),
        )
        self.manifest.append(record)
        return record

    def replay(self, snapshot_id: str) -> RawSnapshot:
        """Load a raw snapshot by id and verify size and SHA256."""
        record = self.manifest.get(snapshot_id)
        payload_path = self._resolve_payload_path(record.payload_path)
        if not payload_path.exists():
            raise RawSnapshotIntegrityError(f"snapshot payload missing: {snapshot_id}")

        payload = payload_path.read_bytes()
        if len(payload) != record.byte_size:
            raise RawSnapshotIntegrityError(f"snapshot byte size mismatch: {snapshot_id}")
        if sha256_bytes(payload) != record.sha256:
            raise RawSnapshotIntegrityError(f"snapshot checksum mismatch: {snapshot_id}")
        return RawSnapshot(record=record, payload=payload)

    def read_payload(self, snapshot_id: str) -> bytes:
        """Return raw payload bytes for a snapshot id."""
        return self.replay(snapshot_id).payload

    def list_records(self) -> list[RawSnapshotRecord]:
        """Return all raw snapshot manifest records in append order."""
        return self.manifest.list_records()

    def find_records(
        self,
        *,
        source_name: str | None = None,
        product_code: str | None = None,
        year: int | None = None,
    ) -> list[RawSnapshotRecord]:
        """Return manifest records matching optional source, product, and year filters."""
        return [
            record
            for record in self.list_records()
            if _matches_record(
                record,
                source_name=source_name,
                product_code=product_code,
                year=year,
            )
        ]

    def _resolve_payload_path(self, relative_path: str) -> Path:
        payload_path = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if not payload_path.is_relative_to(root):
            raise RawSnapshotIntegrityError(f"payload path escapes raw store: {relative_path}")
        return payload_path


def _new_snapshot_id(captured_at_utc: datetime, payload_sha256: str) -> str:
    timestamp = captured_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
    return f"raw_{timestamp}_{payload_sha256[:12]}_{uuid.uuid4().hex[:12]}"


def _safe_segment(value: str, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not _SEGMENT_PATTERN.fullmatch(text) or text in {".", ".."}:
        raise RawSnapshotError(f"unsafe {field_name}: {value!r}")
    return text


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RawSnapshotError(f"{field_name} must be a non-empty string")
    return value.strip()


def _coerce_biz_date(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise RawSnapshotError(f"biz_date must be YYYY-MM-DD: {value!r}") from exc
    raise RawSnapshotError(f"unsupported biz_date type: {type(value).__name__}")


def _matches_record(
    record: RawSnapshotRecord,
    *,
    source_name: str | None,
    product_code: str | None,
    year: int | None,
) -> bool:
    if source_name is not None and record.source_name != source_name:
        return False
    if product_code is not None and record.product_code != product_code:
        return False
    if year is not None:
        year_text = str(year)
        if record.biz_date is not None and record.biz_date.startswith(f"{year_text}-"):
            return True
        metadata_year = record.metadata.get("year") or record.metadata.get("history_year")
        return str(metadata_year) == year_text
    return True
