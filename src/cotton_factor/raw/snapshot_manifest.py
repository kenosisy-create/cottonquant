"""Manifest models and IO for immutable raw snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from cotton_factor.common.exceptions import (
    RawSnapshotExistsError,
    RawSnapshotIntegrityError,
    RawSnapshotNotFoundError,
)

MANIFEST_SCHEMA_VERSION = "raw_snapshot_manifest.v1"
JsonScalar: TypeAlias = str | int | float | bool | None
Metadata: TypeAlias = Mapping[str, JsonScalar]


class RawSnapshotRecord(BaseModel):
    """Manifest entry for one immutable raw payload."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    product_code: str = Field(min_length=1)
    biz_date: str | None = None
    captured_at_utc: datetime
    content_type: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_path: str = Field(min_length=1)
    manifest_schema_version: str = MANIFEST_SCHEMA_VERSION
    parser_version: str | None = None
    status: Literal["captured"] = "captured"
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class SnapshotManifest:
    """Append-only JSONL manifest for raw snapshot records."""

    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path

    def append(self, record: RawSnapshotRecord) -> None:
        """Append a new record, rejecting duplicate snapshot ids."""
        if self.has_snapshot(record.snapshot_id):
            raise RawSnapshotExistsError(f"snapshot already exists: {record.snapshot_id}")

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=True, sort_keys=True)
        with self.manifest_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{line}\n")

    def has_snapshot(self, snapshot_id: str) -> bool:
        """Return whether a snapshot id is present in the manifest."""
        return any(record.snapshot_id == snapshot_id for record in self.iter_records())

    def get(self, snapshot_id: str) -> RawSnapshotRecord:
        """Return one manifest record by snapshot id."""
        matches = [record for record in self.iter_records() if record.snapshot_id == snapshot_id]
        if not matches:
            raise RawSnapshotNotFoundError(f"snapshot not found: {snapshot_id}")
        if len(matches) > 1:
            raise RawSnapshotIntegrityError(f"duplicate manifest entries for: {snapshot_id}")
        return matches[0]

    def iter_records(self) -> Iterator[RawSnapshotRecord]:
        """Yield manifest records in append order."""
        if not self.manifest_path.exists():
            return

        with self.manifest_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    yield RawSnapshotRecord.model_validate_json(stripped)
                except ValueError as exc:
                    raise RawSnapshotIntegrityError(
                        f"invalid manifest line {line_number}: {self.manifest_path}"
                    ) from exc

    def list_records(self) -> list[RawSnapshotRecord]:
        """Return manifest records in append order."""
        return list(self.iter_records())

    def extend(self, records: Iterable[RawSnapshotRecord]) -> None:
        """Append several records with duplicate checking."""
        for record in records:
            self.append(record)
