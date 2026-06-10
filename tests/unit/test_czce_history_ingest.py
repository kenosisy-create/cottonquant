from __future__ import annotations

from pathlib import Path

import pytest

from cotton_factor.common.exceptions import FetchError
from cotton_factor.common.hashing import sha256_bytes
from cotton_factor.ingest.czce_history import (
    SOURCE_NAME,
    ingest_czce_history,
)
from cotton_factor.raw import RawSnapshotStore

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "czce_history_2024"


def test_czce_history_ingests_directory_fixtures_as_raw_snapshots(tmp_path: Path) -> None:
    result = ingest_czce_history(
        year=2024,
        product_code="CF",
        file_type="csv",
        fixture_path=FIXTURE_DIR,
        raw_root=tmp_path / "raw",
    )

    assert len(result.snapshots) == 2
    store = RawSnapshotStore(tmp_path / "raw")
    listed = store.find_records(source_name=SOURCE_NAME, product_code="CF", year=2024)

    assert [record.snapshot_id for record in listed] == [
        snapshot.snapshot_id for snapshot in result.snapshots
    ]
    assert not (tmp_path / "core").exists()

    for snapshot in result.snapshots:
        fixture_path = Path(str(snapshot.metadata["fixture_path"]))
        payload = fixture_path.read_bytes()
        assert snapshot.source_name == SOURCE_NAME
        assert snapshot.product_code == "CF"
        assert snapshot.biz_date is None
        assert snapshot.content_type == "text/csv"
        assert snapshot.byte_size == len(payload)
        assert snapshot.sha256 == sha256_bytes(payload)
        assert snapshot.parser_version == "czce_history_quote.raw.v1"
        assert snapshot.metadata["year"] == 2024
        assert snapshot.metadata["history_year"] == 2024
        assert snapshot.metadata["file_type"] == "csv"
        assert snapshot.metadata["normalizes_business_fields"] is False
        assert store.replay(snapshot.snapshot_id).payload == payload


def test_czce_history_ingests_single_fixture_file(tmp_path: Path) -> None:
    fixture_path = FIXTURE_DIR / "CF_2024_history.html"

    result = ingest_czce_history(
        year=2024,
        product_code="CF",
        file_type="html",
        fixture_path=fixture_path,
        raw_root=tmp_path / "raw",
    )

    assert len(result.snapshots) == 1
    snapshot = result.snapshots[0]
    assert snapshot.content_type == "text/html"
    assert snapshot.metadata["fixture_name"] == "CF_2024_history.html"


def test_czce_history_requires_fixture_when_network_disabled(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="network fetch is disabled"):
        ingest_czce_history(year=2024, product_code="CF", raw_root=tmp_path / "raw")


def test_czce_history_rejects_file_type_mismatch(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="file type does not match"):
        ingest_czce_history(
            year=2024,
            product_code="CF",
            file_type="xlsx",
            fixture_path=FIXTURE_DIR / "CF_2024_part1.csv",
            raw_root=tmp_path / "raw",
        )
