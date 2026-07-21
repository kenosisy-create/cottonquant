from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.research_workbench import connect_cf_option_history


def test_connect_cf_option_history_missing_files_writes_boundary_reports(
    tmp_path: Path,
) -> None:
    result = connect_cf_option_history(
        source_dir=tmp_path / "incoming" / "CF" / "options" / "history",
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="r47_missing",
    )

    assert result.status == "MISSING_OPTION_HISTORY"
    assert result.raw_snapshot_count == 0
    assert result.core_row_count == 0
    assert result.core_option_quote_path is None
    assert result.quality_csv_path.exists()
    assert result.markdown_path.exists()
    assert "MISSING_OPTION_HISTORY" in result.markdown_path.read_text(encoding="utf-8")


def test_connect_cf_option_history_csv_preserves_raw_and_writes_core(
    tmp_path: Path,
) -> None:
    source_dir = _write_option_source(tmp_path)
    core_quote_path = _write_underlying_core_quotes(tmp_path)

    result = connect_cf_option_history(
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        core_quote_path=core_quote_path,
        report_output_dir=tmp_path / "reports",
        run_id="r47_unit_csv",
        low_volume_threshold=1,
        low_open_interest_threshold=1,
        deep_otm_threshold=0.10,
        near_expiry_days=31,
    )

    assert result.status == "COMPLETED"
    assert result.raw_snapshot_count == 1
    assert result.core_row_count == 2
    assert result.core_option_quote_path is not None
    assert result.core_option_quote_path.exists()
    assert (tmp_path / "raw" / "manifest.jsonl").exists()

    core = pd.read_parquet(result.core_option_quote_path)
    assert set(core["option_symbol"]) == {"CF401C17000", "CF401P12000"}
    assert set(core["underlying_contract"]) == {"CF401"}
    assert set(core["option_type"]) == {"C", "P"}
    assert core["moneyness"].notna().all()
    assert "LOW_LIQUIDITY_VOLUME" in ";".join(core["data_quality_flag"].astype(str))
    assert "DEEP_OTM_PROXY" in ";".join(core["data_quality_flag"].astype(str))
    assert "NEAR_EXPIRY_REVIEW" in ";".join(core["data_quality_flag"].astype(str))

    quality = result.quality_csv_path.read_text(encoding="utf-8")
    assert "LOW_LIQUIDITY_VOLUME" in quality
    assert "DEEP_OTM_PROXY" in quality

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["risk_flag_counts"]["DEEP_OTM_PROXY"] == 2
    assert manifest["option_signal_status"] == "not_connected"


def test_connect_cf_option_history_daily_excel_uses_title_date(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "options" / "history"
    source_dir.mkdir(parents=True)
    _write_option_daily_excel(source_dir / "OptionDataDaily_20260706.xlsx")
    core_quote_path = _write_underlying_core_quotes(
        tmp_path,
        trade_date=date(2026, 7, 6),
        contract_code="CF609",
        settle=16295,
    )

    result = connect_cf_option_history(
        source_dir=source_dir,
        raw_root=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        core_quote_path=core_quote_path,
        report_output_dir=tmp_path / "reports",
        run_id="r47_daily_excel",
    )

    assert result.status == "COMPLETED"
    assert result.core_row_count == 2

    core = pd.read_parquet(result.core_option_quote_path)
    assert set(core["option_symbol"]) == {"CF609C16000", "CF609P16500"}
    assert set(core["trade_date"]) == {"2026-07-06"}
    assert set(core["underlying_contract"]) == {"CF609"}
    assert core["moneyness"].notna().all()


def test_cli_connect_cf_option_history(tmp_path: Path) -> None:
    source_dir = _write_option_source(tmp_path)
    core_quote_path = _write_underlying_core_quotes(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "connect-cf-option-history",
            "--source-dir",
            str(source_dir),
            "--raw-root",
            str(tmp_path / "raw"),
            "--core-output-dir",
            str(tmp_path / "core"),
            "--core-quote-path",
            str(core_quote_path),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r47_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r47_cli"
    assert output["status"] == "COMPLETED"
    assert output["core_row_count"] == 2
    assert Path(output["core_option_quote_path"]).exists()
    assert Path(output["quality_csv_path"]).exists()


def _write_option_source(tmp_path: Path) -> Path:
    source_dir = tmp_path / "incoming" / "CF" / "options" / "history"
    source_dir.mkdir(parents=True)
    path = source_dir / "CZCE_CF_OPTIONS_fixture.csv"
    path.write_text(
        "\n".join(
            [
                "trade_date,option_symbol,settle,volume,open_interest",
                "2024-01-02,CF401C17000,120,0,200",
                "2024-01-02,CF401P12000,80,100,0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return source_dir


def _write_underlying_core_quotes(
    tmp_path: Path,
    *,
    trade_date: date = date(2024, 1, 2),
    contract_code: str = "CF401",
    settle: float = 14000,
) -> Path:
    rows = [
        CoreQuoteDailyRow(
            source_snapshot_id=f"underlying_{contract_code.lower()}",
            exchange="CZCE",
            product_code="CF",
            contract_code=contract_code,
            trade_date=trade_date,
            settle=settle,
            volume=100,
            open_interest=1000,
        )
    ]
    path = tmp_path / "core_quote" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_option_daily_excel(path: Path) -> None:
    frame = pd.DataFrame(
        [
            [
                "AP610C10000",
                "7.50",
                "12.00",
                "12.50",
                "9.50",
                "11.00",
                "6.50",
                "3.50",
                "-1.00",
                "602",
                "8,862",
                "196",
                "6.31",
                "0.0195",
                "33.10",
                "0",
            ],
            [
                "CF609C16000",
                "330.00",
                "360.00",
                "370.00",
                "320.00",
                "350.00",
                "345.00",
                "20.00",
                "15.00",
                "120",
                "1,200",
                "30",
                "208.00",
                "0.5000",
                "20.10",
                "0",
            ],
            [
                "CF609P16500",
                "280.00",
                "300.00",
                "320.00",
                "270.00",
                "290.00",
                "295.00",
                "10.00",
                "15.00",
                "80",
                "900",
                "12",
                "120.00",
                "-0.5000",
                "22.30",
                "0",
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
            "DELTA",
            "隐含波动率",
            "行权量",
        ],
    )
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([["郑州商品交易所期权每日行情表(2026-07-06)"]]).to_excel(
            writer,
            index=False,
            header=False,
            sheet_name="sheet1",
        )
        frame.to_excel(writer, index=False, startrow=1, sheet_name="sheet1")
