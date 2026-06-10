from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import FetchError
from cotton_factor.common.hashing import sha256_bytes
from cotton_factor.ingest.czce_daily_quote import (
    SOURCE_NAME,
    ingest_czce_daily_quote,
)
from cotton_factor.raw import RawSnapshotStore

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.parametrize(
    ("fixture_name", "content_type"),
    [
        ("czce_daily_quote_sample.html", "text/html"),
        ("czce_daily_quote_sample.csv", "text/csv"),
        (
            "czce_daily_quote_sample.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_czce_daily_quote_ingests_fixture_as_raw_snapshot(
    tmp_path: Path,
    fixture_name: str,
    content_type: str,
) -> None:
    fixture_path = FIXTURE_DIR / fixture_name
    payload = fixture_path.read_bytes()

    result = ingest_czce_daily_quote(
        trade_date=date(2024, 1, 2),
        product_code="CF",
        fixture_path=fixture_path,
        raw_root=tmp_path / "raw",
    )

    snapshot = result.snapshot
    assert snapshot.source_name == SOURCE_NAME
    assert snapshot.product_code == "CF"
    assert snapshot.biz_date == "2024-01-02"
    assert snapshot.content_type == content_type
    assert snapshot.byte_size == len(payload)
    assert snapshot.sha256 == sha256_bytes(payload)
    assert snapshot.parser_version == "czce_daily_quote.raw.v1"
    assert snapshot.metadata["fetch_mode"] == "fixture"
    assert snapshot.metadata["normalizes_business_fields"] is False
    assert snapshot.metadata["attempt_count"] == 1

    store = RawSnapshotStore(tmp_path / "raw")
    assert store.replay(snapshot.snapshot_id).payload == payload
    assert not (tmp_path / "core").exists()


def test_czce_daily_quote_requires_fixture_when_network_disabled(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="network fetch is disabled"):
        ingest_czce_daily_quote(
            trade_date=date(2024, 1, 2),
            product_code="CF",
            raw_root=tmp_path / "raw",
        )
