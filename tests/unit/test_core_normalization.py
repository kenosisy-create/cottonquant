from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import CoreNormalizationError
from cotton_factor.core import normalize_quote_snapshots, normalize_settlement_snapshots
from cotton_factor.raw import RawSnapshotStore


def test_normalize_quote_snapshot_from_history_csv(tmp_path: Path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")
    record = store.write_snapshot(
        payload=(
            b"contract,trade_date,open,high,low,close,settle,volume,open_interest\n"
            b"CF405,2024-01-02,15500,15600,15400,15550,15540,100,2000\n"
        ),
        source_name="CZCE_HISTORY_QUOTE",
        product_code="CF",
        content_type="text/csv",
        metadata={"source_layer": "raw_snapshot"},
    )

    result = normalize_quote_snapshots(
        snapshot_ids=[record.snapshot_id],
        raw_root=tmp_path / "raw",
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.source_snapshot_id == record.snapshot_id
    assert row.exchange == "CZCE"
    assert row.contract_code == "CF405"
    assert row.trade_date == date(2024, 1, 2)
    assert row.settle == 15540
    assert row.open_interest == 2000


def test_normalize_daily_quote_uses_snapshot_biz_date(tmp_path: Path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")
    record = store.write_snapshot(
        payload=b"contract,open,settle\nCF405,15500,15540\n",
        source_name="CZCE_DAILY_QUOTE",
        product_code="CF",
        content_type="text/csv",
        biz_date=date(2024, 1, 2),
        metadata={"source_layer": "raw_snapshot"},
    )

    result = normalize_quote_snapshots(
        snapshot_ids=[record.snapshot_id],
        raw_root=tmp_path / "raw",
    )

    assert result.rows[0].trade_date == date(2024, 1, 2)
    assert result.rows[0].source_snapshot_id == record.snapshot_id


def test_normalize_settlement_maps_margin_rate_to_long_and_short(tmp_path: Path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")
    record = store.write_snapshot(
        payload=(
            b"contract,limit_up,limit_down,margin_rate,trading_status\n"
            b"CF405,16530,14530,0.07,normal\n"
        ),
        source_name="CZCE_SETTLEMENT_PARAM",
        product_code="CF",
        content_type="text/csv",
        biz_date=date(2024, 1, 2),
        metadata={"source_layer": "raw_snapshot"},
    )

    result = normalize_settlement_snapshots(
        snapshot_ids=[record.snapshot_id],
        raw_root=tmp_path / "raw",
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.source_snapshot_id == record.snapshot_id
    assert row.trade_date == date(2024, 1, 2)
    assert row.margin_rate_long == 0.07
    assert row.margin_rate_short == 0.07
    assert row.trading_status == "normal"


def test_normalize_quote_rejects_unsupported_source(tmp_path: Path) -> None:
    store = RawSnapshotStore(tmp_path / "raw")
    record = store.write_snapshot(
        payload=b"contract,trade_date\nCF405,2024-01-02\n",
        source_name="OTHER_SOURCE",
        product_code="CF",
        content_type="text/csv",
        metadata={"source_layer": "raw_snapshot"},
    )

    with pytest.raises(CoreNormalizationError, match="unsupported quote source"):
        normalize_quote_snapshots(
            snapshot_ids=[record.snapshot_id],
            raw_root=tmp_path / "raw",
        )
