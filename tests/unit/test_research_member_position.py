from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

import cotton_factor.research_workbench.member_position_ingest as member_position_ingest
from cotton_factor.cli.main import app
from cotton_factor.research_workbench import (
    build_cf_member_position_research,
    connect_cf_member_position_history,
    fetch_cf_official_member_position,
    fetch_cf_official_member_position_history,
    official_member_position_url,
    official_member_position_urls,
)


def test_official_member_position_url_and_fetch(tmp_path: Path) -> None:
    trade_date = date(2026, 7, 17)
    workbook = tmp_path / "fixture.xlsx"
    _write_holding_workbook(workbook, trade_date=trade_date)

    assert official_member_position_url(trade_date) == (
        "https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260717/"
        "FutureDataHolding.xlsx"
    )
    assert official_member_position_urls(trade_date)[1].endswith(
        "/20260717/FutureDataHolding.xls"
    )
    assert official_member_position_urls(date(2025, 1, 2))[0].endswith(
        "/20250102/FutureDataHolding.xls"
    )
    result = fetch_cf_official_member_position(
        trade_date=trade_date,
        source_dir=tmp_path / "incoming",
        report_output_dir=tmp_path / "reports",
        fetcher=lambda _: workbook.read_bytes(),
    )

    assert result.status == "DOWNLOADED"
    assert result.output_path is not None and result.output_path.exists()
    assert result.sha256
    assert result.json_path.exists()


def test_official_member_position_history_uses_confirmed_core_dates(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "fixture.xlsx"
    _write_holding_workbook(workbook, trade_date=date(2026, 7, 17))
    quote_path = tmp_path / "core_quote_daily.parquet"
    pd.DataFrame(
        {
            "trade_date": ["2026-07-16", "2026-07-17", "2026-07-17"],
        }
    ).to_parquet(quote_path, index=False)

    result = fetch_cf_official_member_position_history(
        start=date(2026, 7, 16),
        end=date(2026, 7, 17),
        core_quote_path=quote_path,
        source_dir=tmp_path / "history",
        report_output_dir=tmp_path / "reports",
        max_workers=2,
        fetcher=lambda _: workbook.read_bytes(),
    )

    assert result.status == "COMPLETED"
    assert result.requested_date_count == 2
    assert result.ready_date_count == 2
    assert result.downloaded_date_count == 2
    assert result.existing_date_count == 0
    assert result.failed_date_count == 0
    assert result.status_csv_path.exists()
    assert result.manifest_path.exists()
    assert result.markdown_path.exists()


def test_member_position_ingest_missing_history_is_visible(tmp_path: Path) -> None:
    result = connect_cf_member_position_history(
        source_dir=tmp_path / "incoming",
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="r83_missing",
    )

    assert result.status == "MISSING_MEMBER_POSITION_HISTORY"
    assert result.passed is True
    assert result.core_member_position_path is None
    assert "MISSING_MEMBER_POSITION_HISTORY" in result.markdown_path.read_text(
        encoding="utf-8"
    )


def test_member_position_ingest_preserves_raw_and_normalizes_sides(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming"
    source_dir.mkdir()
    _write_holding_workbook(
        source_dir / "FutureDataHolding.xlsx",
        trade_date=date(2026, 7, 17),
    )

    result = connect_cf_member_position_history(
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="r83_ingest",
    )

    assert result.status == "COMPLETED"
    assert result.raw_snapshot_count == 1
    assert result.core_row_count == 18
    assert result.core_member_position_path is not None
    assert (tmp_path / "raw" / "manifest.jsonl").exists()
    core = pd.read_parquet(result.core_member_position_path)
    assert set(core["scope_code"]) == {"CF", "CF609", "CF611"}
    assert set(core["position_side"]) == {"volume", "long", "short"}
    assert set(core["data_quality_flag"]) == {"PARTIAL_TOP_RANKS_2"}
    cf609_long = core.loc[
        core["scope_code"].eq("CF609") & core["position_side"].eq("long")
    ]
    assert cf609_long["position_value"].sum() == 1900

    manifest_path = tmp_path / "raw" / "manifest.jsonl"
    manifest_line_count = len(manifest_path.read_text(encoding="utf-8").splitlines())
    repeated = connect_cf_member_position_history(
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="r85_incremental_no_changes",
    )
    assert repeated.status == "NO_CHANGES"
    assert repeated.raw_snapshot_count == 0
    assert repeated.core_row_count == 18
    assert len(manifest_path.read_text(encoding="utf-8").splitlines()) == manifest_line_count


def test_member_position_ingest_accepts_legacy_volume_header_and_sparse_side(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming"
    source_dir.mkdir()
    _write_holding_workbook(
        source_dir / "FutureDataHolding.xls.xlsx",
        trade_date=date(2025, 1, 2),
        volume_header="成交量（手）",
        sparse_receiving_long_second=True,
    )

    result = connect_cf_member_position_history(
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="r85_legacy_sparse",
    )

    assert result.status == "COMPLETED"
    assert result.core_member_position_path is not None
    core = pd.read_parquet(result.core_member_position_path)
    receiving_long = core.loc[
        core["scope_code"].eq("CF611") & core["position_side"].eq("long")
    ]
    assert len(receiving_long) == 1
    assert set(receiving_long["data_quality_flag"]) == {"PARTIAL_TOP_RANKS_1"}


def test_member_position_history_cli_writes_r85_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = tmp_path / "fixture.xlsx"
    _write_holding_workbook(workbook, trade_date=date(2026, 7, 17))
    quote_path = tmp_path / "core_quote_daily.parquet"
    pd.DataFrame({"trade_date": ["2026-07-17"]}).to_parquet(quote_path, index=False)
    monkeypatch.setattr(
        member_position_ingest,
        "_download_url",
        lambda _: workbook.read_bytes(),
    )

    result = CliRunner().invoke(
        app,
        [
            "research",
            "fetch-cf-official-member-position-history",
            "--start",
            "2026-07-17",
            "--end",
            "2026-07-17",
            "--core-quote-path",
            str(quote_path),
            "--source-dir",
            str(tmp_path / "history"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--max-workers",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["status"] == "COMPLETED"
    assert summary["downloaded_date_count"] == 1
    assert Path(summary["status_csv_path"]).exists()
    assert Path(summary["manifest_path"]).exists()


def test_member_position_research_builds_concentration_roll_and_validation(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming"
    source_dir.mkdir()
    _write_holding_workbook(
        source_dir / "FutureDataHolding_20260716.xlsx",
        trade_date=date(2026, 7, 16),
        main_long_changes=(100, 50),
        main_short_changes=(-100, -50),
        receiving_long_changes=(0, 0),
        receiving_short_changes=(0, 0),
    )
    _write_holding_workbook(
        source_dir / "FutureDataHolding_20260717.xlsx",
        trade_date=date(2026, 7, 17),
        main_long_changes=(-50, -50),
        main_short_changes=(-600, -400),
        receiving_long_changes=(200, 200),
        receiving_short_changes=(150, 150),
    )
    ingest = connect_cf_member_position_history(
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core_member",
        report_output_dir=tmp_path / "ingest_reports",
        run_id="r83_research_ingest",
    )
    assert ingest.core_member_position_path is not None
    quote_path = _write_core_quotes(tmp_path)
    validation_path = _write_validation(tmp_path)

    result = build_cf_member_position_research(
        member_position_path=ingest.core_member_position_path,
        core_quote_path=quote_path,
        validation_daily_path=validation_path,
        top_ns=(5, 10, 20),
        horizons=(1,),
        min_sample_size=1,
        min_history_days=2,
        output_dir=tmp_path / "research_data",
        report_output_dir=tmp_path / "research_reports",
        run_id="r83_research",
    )

    assert result.end == date(2026, 7, 17)
    assert result.latest_main_contract == "CF609"
    assert result.latest_member_direction == "long"
    assert result.validation_row_count >= 1
    daily = pd.read_parquet(result.daily_parquet_path)
    latest_main = daily.loc[
        daily["trade_date"].astype(str).eq("2026-07-17")
        & daily["scope_code"].eq("CF609")
        & daily["top_n"].eq(20)
    ].iloc[0]
    assert latest_main["top_net_change"] == 900
    assert latest_main["price_member_relation"] == "ALIGNED_LONG"
    roll = pd.read_parquet(result.roll_parquet_path)
    assert roll.iloc[-1]["roll_migration_state"] == "ROLL_MIGRATION"
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "会员持仓集中度与多空变化研究" in report
    assert "forward return 仅作为历史后验验证标签" in report
    assert "不构成交易指令" in report


def test_member_position_cli_connect_and_research(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming"
    source_dir.mkdir()
    _write_holding_workbook(
        source_dir / "FutureDataHolding.xlsx",
        trade_date=date(2026, 7, 17),
    )
    core_path = tmp_path / "core" / "core_member_position_daily.parquet"
    connect = CliRunner().invoke(
        app,
        [
            "research",
            "connect-cf-member-position-history",
            "--source-dir",
            str(source_dir),
            "--raw-root",
            str(tmp_path / "raw"),
            "--output-path",
            str(core_path),
            "--report-output-dir",
            str(tmp_path / "ingest_reports"),
            "--run-id",
            "r83_cli_ingest",
        ],
    )
    assert connect.exit_code == 0, connect.output
    assert json.loads(connect.output)["status"] == "COMPLETED"

    quote_path = _write_core_quotes(tmp_path, only_latest=True)
    research = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-member-position-research",
            "--member-position-path",
            str(core_path),
            "--core-quote-path",
            str(quote_path),
            "--top-ns",
            "5,10,20",
            "--horizons",
            "1",
            "--min-history-days",
            "1",
            "--output-dir",
            str(tmp_path / "research_data"),
            "--report-output-dir",
            str(tmp_path / "research_reports"),
            "--run-id",
            "r83_cli_research",
        ],
    )
    assert research.exit_code == 0, research.output
    output = json.loads(research.output)
    assert output["latest_main_contract"] == "CF609"
    assert Path(output["daily_parquet_path"]).exists()


def _write_holding_workbook(
    path: Path,
    *,
    trade_date: date,
    main_long_changes: tuple[int, int] = (-50, -50),
    main_short_changes: tuple[int, int] = (-600, -400),
    receiving_long_changes: tuple[int, int] = (200, 200),
    receiving_short_changes: tuple[int, int] = (150, 150),
    volume_header: str = "交易量（手）",
    sparse_receiving_long_second: bool = False,
) -> None:
    headers = [
        "名次",
        "会员简称",
        volume_header,
        "增减量",
        "会员简称",
        "持买仓量",
        "增减量",
        "会员简称",
        "持卖仓量",
        "增减量",
    ]
    date_text = trade_date.isoformat()
    rows: list[list[object]] = [[f"郑州商品交易所期货持仓排名表({date_text})"]]
    rows.extend(
        _section_rows(
            f"品种：棉花CF     日期：{date_text}",
            headers,
            long_changes=(50, 25),
            short_changes=(-20, -10),
        )
    )
    rows.extend(
        _section_rows(
            f"合约：CF609     日期：{date_text}",
            headers,
            long_changes=main_long_changes,
            short_changes=main_short_changes,
        )
    )
    rows.extend(
        _section_rows(
            f"合约：CF611     日期：{date_text}",
            headers,
            long_changes=receiving_long_changes,
            short_changes=receiving_short_changes,
            sparse_long_second=sparse_receiving_long_second,
        )
    )
    frame = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False, header=False)


def _section_rows(
    title: str,
    headers: list[str],
    *,
    long_changes: tuple[int, int],
    short_changes: tuple[int, int],
    sparse_long_second: bool = False,
) -> list[list[object]]:
    rows = [
        [title],
        headers,
        [1, "成交甲", 5000, 500, "多头甲", 1000, long_changes[0], "空头甲", 900, short_changes[0]],
        [2, "成交乙", 4000, 400, "多头乙", 900, long_changes[1], "空头乙", 800, short_changes[1]],
        ["合计", None, 9000, 900, None, 1900, sum(long_changes), None, 1700, sum(short_changes)],
    ]
    if sparse_long_second:
        rows[3][4:7] = ["-", "-", "-"]
    return rows


def _write_core_quotes(tmp_path: Path, *, only_latest: bool = False) -> Path:
    rows = [
        {
            "trade_date": "2026-07-16",
            "contract_code": "CF609",
            "settle": 100.0,
            "close": 100.0,
            "open_interest": 2100,
        },
        {
            "trade_date": "2026-07-16",
            "contract_code": "CF611",
            "settle": 101.0,
            "close": 101.0,
            "open_interest": 900,
        },
        {
            "trade_date": "2026-07-17",
            "contract_code": "CF609",
            "settle": 102.0,
            "close": 103.0,
            "open_interest": 2000,
        },
        {
            "trade_date": "2026-07-17",
            "contract_code": "CF611",
            "settle": 102.0,
            "close": 102.0,
            "open_interest": 1200,
        },
    ]
    if only_latest:
        rows = rows[-2:]
    path = tmp_path / ("latest_quotes" if only_latest else "quotes") / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_validation(tmp_path: Path) -> Path:
    path = tmp_path / "validation" / "signal_matrix_validation_daily.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "trade_date": "2026-07-16",
                "main_contract": "CF609",
                "horizon": 1,
                "forward_return": 0.02,
                "forward_label_available": True,
            }
        ]
    ).to_parquet(path, index=False)
    return path
