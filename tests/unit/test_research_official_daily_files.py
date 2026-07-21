from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import (
    fetch_cf_official_daily_files,
    official_daily_date_key,
    official_daily_file_url,
    official_daily_file_urls,
)


def test_official_daily_url_date_format() -> None:
    trade_date = date(2026, 7, 6)

    assert official_daily_date_key(trade_date) == "20260706"
    assert official_daily_file_url(trade_date=trade_date, file_kind="futures") == (
        "https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260706/"
        "FutureDataDailyCF.xlsx"
    )
    assert official_daily_file_urls(trade_date)["options"] == (
        "https://www.czce.com.cn/cn/DFSStaticFiles/Option/2026/20260706/"
        "OptionDataDaily.xlsx"
    )


def test_fetch_cf_official_daily_files_writes_incoming_and_report(tmp_path: Path) -> None:
    payload = b"PK\x03\x04fake-xlsx"

    result = fetch_cf_official_daily_files(
        trade_date=date(2026, 7, 6),
        futures_source_dir=tmp_path / "incoming" / "CF" / "history",
        options_source_dir=tmp_path / "incoming" / "CF" / "options" / "history",
        report_output_dir=tmp_path / "reports",
        run_id="daily_fetch_unit",
        fetcher=lambda _url: payload,
    )

    assert result.passed
    assert result.status == "COMPLETED"
    assert result.date_key == "20260706"
    assert result.futures_connect_source_dir == (
        tmp_path / "incoming" / "CF" / "history" / "daily" / "2026" / "20260706"
    )
    assert result.options_connect_source_dir == (
        tmp_path
        / "incoming"
        / "CF"
        / "options"
        / "history"
        / "daily"
        / "2026"
        / "20260706"
    )
    assert result.to_summary()["futures_path"].endswith("FutureDataDailyCF.xlsx")
    assert result.to_summary()["options_path"].endswith("OptionDataDaily.xlsx")
    assert Path(result.to_summary()["futures_path"]).read_bytes() == payload
    assert Path(result.to_summary()["options_path"]).read_bytes() == payload
    assert result.json_path.exists()
    assert "YYYYMMDD" in result.markdown_path.read_text(encoding="utf-8")


def test_cli_fetch_cf_official_daily_files_with_file_urls(tmp_path: Path) -> None:
    futures_file = tmp_path / "FutureDataDailyCF.xlsx"
    options_file = tmp_path / "OptionDataDaily.xlsx"
    futures_file.write_bytes(b"PK\x03\x04future")
    options_file.write_bytes(b"PK\x03\x04option")

    result = CliRunner().invoke(
        app,
        [
            "research",
            "fetch-cf-official-daily-files",
            "--date",
            "2026-07-06",
            "--futures-source-dir",
            str(tmp_path / "incoming" / "CF" / "history"),
            "--options-source-dir",
            str(tmp_path / "incoming" / "CF" / "options" / "history"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "daily_fetch_cli",
            "--futures-url",
            futures_file.as_uri(),
            "--options-url",
            options_file.as_uri(),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "daily_fetch_cli"
    assert output["date_key"] == "20260706"
    assert output["passed"] is True
    assert Path(output["futures_path"]).exists()
    assert Path(output["options_path"]).exists()
