from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import (
    connect_cf_official_history,
    default_recent_history_years,
    official_history_url,
)


def test_default_recent_history_years_uses_completed_annual_archives() -> None:
    assert default_recent_history_years(today=date(2026, 6, 24)) == (2023, 2024, 2025)


def test_official_history_url_points_to_czce_annual_zip() -> None:
    assert official_history_url(2025).endswith("/Future/2025/ALLFUTURES2025.zip")


def test_connect_cf_official_history_from_local_annual_zip(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "history"
    source_dir.mkdir(parents=True)
    archive_path = source_dir / "ALLFUTURES2024.zip"
    archive_path.write_bytes(_official_history_zip(2024))

    result = connect_cf_official_history(
        years=(2024,),
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="official_history_test",
    )

    assert result.passed
    assert result.status == "COMPLETED"
    assert result.raw_snapshot_count == 1
    assert result.row_count == 2
    assert result.core_output_path == tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    assert result.core_output_path.exists()
    assert result.json_path.exists()
    assert result.markdown_path.exists()
    assert result.records[0].status == "LOCAL_ARCHIVE_READY"
    assert result.records[0].snapshot_id is not None

    core = pd.read_parquet(result.core_output_path)
    assert list(core["contract_code"]) == ["CF405", "CF409"]
    assert list(core["settle"]) == [15170.0, 15380.0]
    assert set(core["source_snapshot_id"].str.contains("ALLFUTURES2024.TXT")) == {True}


def test_connect_cf_official_history_from_local_product_excel(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "history"
    source_dir.mkdir(parents=True)
    excel_path = source_dir / "CFFUTURES2026.xlsx"
    _official_history_excel(2026, excel_path)

    result = connect_cf_official_history(
        years=(2026,),
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="official_history_excel_test",
    )

    assert result.passed
    assert result.status == "COMPLETED"
    assert result.row_count == 2
    assert result.records[0].source_path == excel_path.resolve()

    core = pd.read_parquet(result.core_output_path)
    assert list(core["contract_code"]) == ["CF601", "CF605"]
    assert list(core["settle"]) == [14760.0, 14700.0]
    assert list(core["volume"]) == [10291, 492738]
    assert set(core["source_snapshot_id"].str.contains("CFFUTURES2026.xlsx")) == {True}


def test_connect_cf_official_history_from_local_daily_excel_title_date(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "history" / "daily" / "2026" / "20260706"
    source_dir.mkdir(parents=True)
    excel_path = source_dir / "FutureDataDailyCF.xlsx"
    _official_daily_future_excel(excel_path)

    result = connect_cf_official_history(
        years=(2026,),
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="official_daily_excel_test",
    )

    assert result.passed
    assert result.status == "COMPLETED"
    assert result.row_count == 2
    assert result.records[0].source_path == excel_path.resolve()

    core = pd.read_parquet(result.core_output_path)
    assert list(core["trade_date"]) == ["2026-07-06", "2026-07-06"]
    assert list(core["contract_code"]) == ["CF607", "CF609"]
    assert list(core["settle"]) == [16045.0, 16295.0]
    assert list(core["open_interest"]) == [17335, 581306]


def test_connect_cf_official_history_requires_local_or_download(tmp_path: Path) -> None:
    result = connect_cf_official_history(
        years=(2024,),
        source_dir=tmp_path / "missing",
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
    )

    assert not result.passed
    assert result.status == "NEEDS_MANUAL_DOWNLOAD"
    assert result.row_count == 0
    assert result.core_output_path is None
    assert result.records[0].status == "MISSING_LOCAL_ARCHIVE"
    assert result.json_path.exists()
    assert result.markdown_path.exists()


def test_cli_connect_cf_official_history_from_local_zip(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "history"
    source_dir.mkdir(parents=True)
    (source_dir / "ALLFUTURES2024.zip").write_bytes(_official_history_zip(2024))

    result = CliRunner().invoke(
        app,
        [
            "research",
            "connect-cf-official-history",
            "--years",
            "2024",
            "--source-dir",
            str(source_dir),
            "--raw-root",
            str(tmp_path / "raw"),
            "--core-output-dir",
            str(tmp_path / "core"),
            "--report-output-dir",
            str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"status": "COMPLETED"' in result.output


def _official_history_zip(year: int) -> bytes:
    text = (
        "郑州商品交易所历史行情\n"
        "交易日期|品种月份|昨结算|今开盘|最高价|最低价|今收盘|今结算|成交量(手)|空盘量|成交额(万元)\n"
        f"{year}-01-02|CF405|15000|15100|15200|15050|15180|15170|100|200|1234.5\n"
        f"{year}-01-02|SR405|6000|6010|6020|5990|6015|6012|10|20|30\n"
        f"{year}0103|CF409|15300|15320|15400|15280|15390|15380|80|180|900\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"ALLFUTURES{year}.TXT", text.encode("gb18030"))
    return buffer.getvalue()


def _official_history_excel(year: int, path: Path) -> None:
    frame = pd.DataFrame(
        [
            [
                f"{year}-01-05",
                "CF601",
                "14,605.00",
                "14,620.00",
                "14,945.00",
                "14,620.00",
                "14,740.00",
                "14,760.00",
                135,
                155,
                "10,291",
                "82,645",
                "-7,734",
                "75,952.32",
                "14,370.00",
            ],
            [
                f"{year}-01-05",
                "CF605",
                "14,550.00",
                "14,600.00",
                "14,875.00",
                "14,515.00",
                "14,655.00",
                "14,700.00",
                105,
                150,
                "492,738",
                "889,861",
                "29,136",
                "3,621,909.66",
                "",
            ],
        ],
        columns=[
            "交易日期",
            "合约代码",
            "昨结算",
            "今开",
            "最高价",
            "最低价",
            "今收盘",
            "今结算",
            "涨跌1",
            "涨跌2",
            "成交量(手)",
            "持仓量",
            "持仓量变化",
            "成交额(万元)",
            "交割结算价",
        ],
    )
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([["郑州商品交易所期货历史行情"]]).to_excel(
            writer,
            index=False,
            header=False,
            sheet_name="sheet1",
        )
        frame.to_excel(writer, index=False, startrow=1, sheet_name="sheet1")


def _official_daily_future_excel(path: Path) -> None:
    frame = pd.DataFrame(
        [
            [
                "CF607",
                "16,030.00",
                "16,040.00",
                "16,100.00",
                "16,040.00",
                "16,100.00",
                "16,045.00",
                "70.00",
                "15.00",
                "112",
                "17,335",
                "-112",
                "898.57",
                "15,760.00",
            ],
            [
                "CF609",
                "16,215.00",
                "16,260.00",
                "16,355.00",
                "16,235.00",
                "16,265.00",
                "16,295.00",
                "50.00",
                "80.00",
                "318,578",
                "581,306",
                "-2,010",
                "2,595,473.12",
                "",
            ],
        ],
        columns=[
            "合约代码",
            "昨结算",
            "今开盘",
            "最高价",
            "最低价",
            "今收盘",
            "今结算",
            "涨跌1",
            "涨跌2",
            "成交量(手)",
            "持仓量",
            "增减量",
            "成交额(万元)",
            "交割结算价",
        ],
    )
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([["郑州商品交易所期货每日行情表(2026-07-06)"]]).to_excel(
            writer,
            index=False,
            header=False,
            sheet_name="sheet1",
        )
        frame.to_excel(writer, index=False, startrow=1, sheet_name="sheet1")
