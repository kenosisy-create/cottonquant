from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import ingest_cf_raw, normalize_cf_core_quotes


def test_normalize_cf_core_quotes_from_preserved_raw_csv(tmp_path: Path) -> None:
    input_file = tmp_path / "incoming" / "CF" / "2026-06-11" / "cf_daily.csv"
    input_file.parent.mkdir(parents=True)
    input_file.write_text(
        (
            "交易日期,交易所,品种,合约代码,开盘价,最高价,最低价,收盘价,结算价,成交量,持仓量\n"
            "2026-06-11,CZCE,CF,CF609,15000,15100,14900,15080,15060,1000,30000\n"
            "2026-06-11,CZCE,CF,CF701,15200,15300,15100,15250,15240,800,22000\n"
        ),
        encoding="utf-8",
    )
    ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_file,
        raw_output_dir=tmp_path / "raw",
        run_id="r05_alias_csv",
    )

    result = normalize_cf_core_quotes(
        trade_date=date(2026, 6, 11),
        raw_output_dir=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        run_id="r05_alias_csv",
    )

    assert result.row_count == 2
    assert result.output_path == tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    assert result.output_path.exists()
    assert [row.contract_code for row in result.rows] == ["CF609", "CF701"]
    assert result.rows[0].source_snapshot_id.startswith("research_raw:r05_alias_csv:")

    parquet = pd.read_parquet(result.output_path)
    assert list(parquet["contract_code"]) == ["CF609", "CF701"]
    assert list(parquet["settle"]) == [15060.0, 15240.0]


def test_normalize_cf_core_quotes_replaces_existing_primary_key(tmp_path: Path) -> None:
    first_file = tmp_path / "incoming" / "first.csv"
    second_file = tmp_path / "incoming" / "second.csv"
    first_file.parent.mkdir()
    first_file.write_text(
        _quote_csv(settle=15060),
        encoding="utf-8",
    )
    second_file.write_text(
        _quote_csv(settle=15110),
        encoding="utf-8",
    )
    ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=first_file,
        raw_output_dir=tmp_path / "raw",
        run_id="r05_first",
    )
    ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=second_file,
        raw_output_dir=tmp_path / "raw",
        run_id="r05_second",
    )

    normalize_cf_core_quotes(
        trade_date=date(2026, 6, 11),
        raw_output_dir=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        run_id="r05_first",
    )
    result = normalize_cf_core_quotes(
        trade_date=date(2026, 6, 11),
        raw_output_dir=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        run_id="r05_second",
    )

    parquet = pd.read_parquet(result.output_path)
    assert len(parquet) == 1
    assert parquet.loc[0, "settle"] == 15110.0
    assert parquet.loc[0, "source_snapshot_id"].startswith("research_raw:r05_second:")


def test_normalize_cf_core_quotes_rejects_missing_required_columns(tmp_path: Path) -> None:
    input_file = tmp_path / "incoming" / "bad.csv"
    input_file.parent.mkdir()
    input_file.write_text(
        "trade_date,exchange,product_code,contract_id,settle\n"
        "2026-06-11,CZCE,CF,CF609,15060\n",
        encoding="utf-8",
    )
    ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_file,
        raw_output_dir=tmp_path / "raw",
        run_id="r05_missing_columns",
    )

    with pytest.raises(ResearchWorkbenchError, match="missing required columns"):
        normalize_cf_core_quotes(
            trade_date=date(2026, 6, 11),
            raw_output_dir=tmp_path / "raw",
            core_output_dir=tmp_path / "core",
            run_id="r05_missing_columns",
        )


def test_normalize_cf_core_quotes_skips_non_csv_raw_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "incoming" / "CF" / "2026-06-11"
    input_dir.mkdir(parents=True)
    (input_dir / "cf_daily.csv").write_text(_quote_csv(settle=15060), encoding="utf-8")
    (input_dir / "notes.xlsx").write_bytes(b"placeholder")
    ingest_cf_raw(
        trade_date=date(2026, 6, 11),
        input_path=input_dir,
        raw_output_dir=tmp_path / "raw",
        run_id="r05_mixed_folder",
    )

    result = normalize_cf_core_quotes(
        trade_date=date(2026, 6, 11),
        raw_output_dir=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        run_id="r05_mixed_folder",
    )

    assert result.row_count == 1
    assert result.warnings == (
        f"skipped unsupported core quote format: "
        f"{tmp_path / 'raw' / 'CF' / '2026-06-11' / 'r05_mixed_folder' / 'notes.xlsx'}",
    )


def _quote_csv(*, settle: int) -> str:
    return (
        "trade_date,exchange,product_code,contract_id,open,high,low,close,settle,"
        "volume,open_interest\n"
        f"2026-06-11,CZCE,CF,CF609,15000,15100,14900,15080,{settle},1000,30000\n"
    )
