from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_file
from cotton_factor.research_workbench import ingest_cf_raw, list_cf_raw_manifest


def test_ingest_cf_raw_file_preserves_payload_and_manifest(tmp_path: Path) -> None:
    input_file = tmp_path / "incoming" / "cf_daily.csv"
    input_file.parent.mkdir()
    input_file.write_text(
        "trade_date,contract_id,settle\n2026-06-11,CF609,15000\n",
        encoding="utf-8",
    )

    result = ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_file,
        raw_output_dir=tmp_path / "raw",
        run_id="r04_file_ingest",
    )

    assert result.run_id == "r04_file_ingest"
    assert result.product_code == "CF"
    assert result.output_dir == tmp_path / "raw" / "CF" / "2026-06-11" / "r04_file_ingest"
    assert result.manifest_path.exists()
    assert len(result.records) == 1

    record = result.records[0]
    assert record.source_file_name == "cf_daily.csv"
    assert record.raw_path.exists()
    assert record.raw_path.read_text(encoding="utf-8") == input_file.read_text(encoding="utf-8")
    assert record.sha256 == sha256_file(input_file)
    assert record.content_length == input_file.stat().st_size

    rows = list_cf_raw_manifest(raw_output_dir=tmp_path / "raw", trade_date=date(2026, 6, 11))
    assert [row["run_id"] for row in rows] == ["r04_file_ingest"]
    assert rows[0]["sha256"] == sha256_file(input_file)


def test_ingest_cf_raw_folder_preserves_all_files_without_core_output(tmp_path: Path) -> None:
    input_dir = tmp_path / "incoming" / "CF" / "2026-06-11"
    input_dir.mkdir(parents=True)
    (input_dir / "cf_daily.csv").write_text("contract_id,settle\nCF609,15000\n", encoding="utf-8")
    (input_dir / "settlement.xlsx").write_bytes(b"xlsx-like bytes")

    result = ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_dir,
        raw_output_dir=tmp_path / "raw",
        run_id="r04_folder_ingest",
    )

    assert sorted(record.source_file_name for record in result.records) == [
        "cf_daily.csv",
        "settlement.xlsx",
    ]
    assert not (tmp_path / "core").exists()
    assert not (tmp_path / "research").exists()


def test_ingest_cf_raw_rerun_uses_new_directory_and_same_checksum(tmp_path: Path) -> None:
    input_file = tmp_path / "cf_daily.csv"
    input_file.write_text("same payload\n", encoding="utf-8")

    first = ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_file,
        raw_output_dir=tmp_path / "raw",
    )
    second = ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_file,
        raw_output_dir=tmp_path / "raw",
    )

    assert first.run_id != second.run_id
    assert first.records[0].raw_path != second.records[0].raw_path
    assert first.records[0].sha256 == second.records[0].sha256 == sha256_file(input_file)


def test_ingest_cf_raw_rejects_existing_run_id(tmp_path: Path) -> None:
    input_file = tmp_path / "cf_daily.csv"
    input_file.write_text("payload\n", encoding="utf-8")

    ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_file,
        raw_output_dir=tmp_path / "raw",
        run_id="duplicate_run",
    )

    with pytest.raises(ResearchWorkbenchError, match="already exists"):
        ingest_cf_raw(
            trade_date=date(2026, 6, 11),
            input_path=input_file,
            raw_output_dir=tmp_path / "raw",
            run_id="duplicate_run",
        )
