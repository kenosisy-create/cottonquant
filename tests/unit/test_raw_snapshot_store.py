from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from cotton_factor.common.exceptions import (
    RawSnapshotError,
    RawSnapshotIntegrityError,
    RawSnapshotNotFoundError,
)
from cotton_factor.common.hashing import sha256_bytes
from cotton_factor.raw import RawSnapshotStore


def test_write_snapshot_records_manifest_and_replays_payload(tmp_path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")
    payload = b'{"exchange": "CZCE", "contract": "CF401"}'

    record = store.write_snapshot(
        payload=payload,
        source_name="czce_daily_quote",
        product_code="CF",
        biz_date=date(2024, 1, 3),
        content_type="application/json",
        metadata={"fixture": True},
        captured_at_utc=datetime(2024, 1, 3, 8, 30, tzinfo=UTC),
    )

    payload_path = tmp_path / "raw" / record.payload_path
    assert payload_path.read_bytes() == payload
    assert record.biz_date == "2024-01-03"
    assert record.byte_size == len(payload)
    assert record.sha256 == sha256_bytes(payload)
    assert record.metadata == {"fixture": True}

    manifest_lines = (tmp_path / "raw" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 1
    assert json.loads(manifest_lines[0])["snapshot_id"] == record.snapshot_id

    replayed = store.replay(record.snapshot_id)
    assert replayed.record == record
    assert replayed.payload == payload


def test_repeated_ingestion_creates_distinct_immutable_snapshots(tmp_path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")
    captured_at = datetime(2024, 1, 3, 8, 30, tzinfo=UTC)
    payload = b"same exchange payload"

    first = store.write_snapshot(
        payload=payload,
        source_name="czce_daily_quote",
        product_code="CF",
        biz_date="2024-01-03",
        content_type="text/plain",
        captured_at_utc=captured_at,
    )
    second = store.write_snapshot(
        payload=payload,
        source_name="czce_daily_quote",
        product_code="CF",
        biz_date="2024-01-03",
        content_type="text/plain",
        captured_at_utc=captured_at,
    )

    assert first.snapshot_id != second.snapshot_id
    assert first.sha256 == second.sha256
    assert first.payload_path != second.payload_path
    assert [record.snapshot_id for record in store.list_records()] == [
        first.snapshot_id,
        second.snapshot_id,
    ]
    assert store.read_payload(first.snapshot_id) == payload
    assert store.read_payload(second.snapshot_id) == payload


def test_replay_rejects_tampered_payload(tmp_path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")
    record = store.write_snapshot(
        payload=b"official raw payload",
        source_name="czce_daily_quote",
        product_code="CF",
        biz_date="2024-01-03",
        content_type="text/plain",
    )
    (tmp_path / "raw" / record.payload_path).write_bytes(b"tampered payload")

    with pytest.raises(RawSnapshotIntegrityError, match="checksum mismatch|byte size mismatch"):
        store.replay(record.snapshot_id)


def test_replay_requires_manifest_record(tmp_path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")

    with pytest.raises(RawSnapshotNotFoundError, match="snapshot not found"):
        store.replay("missing_snapshot")


def test_store_rejects_unsafe_path_segments(tmp_path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")

    with pytest.raises(RawSnapshotError, match="unsafe source_name"):
        store.write_snapshot(
            payload=b"payload",
            source_name="../czce",
            product_code="CF",
            content_type="text/plain",
        )

    assert not (tmp_path / "raw" / "snapshots").exists()
