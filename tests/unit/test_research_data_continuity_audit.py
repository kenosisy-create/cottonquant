from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_data_continuity_audit


def test_data_continuity_audit_passes_with_core_option_download_and_raw(
    tmp_path: Path,
) -> None:
    core_path, option_path, calendar_path, fetch_json_path, raw_root = _write_complete_fixture(
        tmp_path
    )

    result = build_cf_data_continuity_audit(
        trade_date=date(2026, 7, 6),
        core_quote_path=core_path,
        option_core_path=option_path,
        calendar_path=calendar_path,
        official_daily_fetch_json_path=fetch_json_path,
        raw_root=raw_root,
        output_root=tmp_path / "runs" / "daily",
        run_id="continuity_pass",
    )

    assert result.passed
    assert result.continuity_status == "READY"
    assert result.error_count == 0
    assert len(result.downloaded_file_paths) == 2
    assert result.futures_audit.latest_trade_date == date(2026, 7, 6)
    assert result.option_audit is not None
    assert result.option_audit.latest_trade_date == date(2026, 7, 6)
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.warning_csv_path.exists()
    assert result.manifest_path.exists()
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "数据连续性与留存检查" in markdown
    assert "研究函数不直接解析交易所原始 Excel/ZIP" in markdown
    assert "不构成交易指令" in markdown


def test_data_continuity_audit_blocks_on_missing_trading_day(tmp_path: Path) -> None:
    core_path = tmp_path / "core_quote_daily.parquet"
    _write_futures_core(
        core_path,
        [
            ("2026-07-01", "CF609", "raw_fut_a:FutureDataDailyCF.xlsx"),
            ("2026-07-03", "CF609", "raw_fut_b:FutureDataDailyCF.xlsx"),
        ],
    )
    calendar_path = _write_calendar(
        tmp_path / "CZCE_2026_OFFICIAL.csv",
        ["2026-07-01", "2026-07-02", "2026-07-03"],
    )
    raw_root = tmp_path / "raw"
    _write_raw_manifest(raw_root, ["raw_fut_b"])

    result = build_cf_data_continuity_audit(
        trade_date=date(2026, 7, 3),
        core_quote_path=core_path,
        option_core_path=tmp_path / "missing_option.parquet",
        calendar_path=calendar_path,
        raw_root=raw_root,
        output_root=tmp_path / "runs" / "daily",
        run_id="continuity_gap",
        require_options=False,
    )

    assert not result.passed
    assert result.continuity_status == "BLOCKED"
    assert any(
        warning.warning_code == "FUTURES_CORE_MISSING_TRADING_DATES"
        for warning in result.warning_records
    )


def test_cli_build_cf_data_continuity_audit_returns_json(tmp_path: Path) -> None:
    core_path, option_path, calendar_path, fetch_json_path, raw_root = _write_complete_fixture(
        tmp_path
    )

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-data-continuity-audit",
            "--date",
            "2026-07-06",
            "--core-quote-path",
            str(core_path),
            "--option-core-path",
            str(option_path),
            "--calendar-path",
            str(calendar_path),
            "--official-daily-fetch-json-path",
            str(fetch_json_path),
            "--raw-root",
            str(raw_root),
            "--output-root",
            str(tmp_path / "runs" / "daily"),
            "--run-id",
            "continuity_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "continuity_cli"
    assert output["trade_date"] == "2026-07-06"
    assert output["continuity_status"] == "READY"
    assert output["passed"] is True


def _write_complete_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    option_path = tmp_path / "core" / "CF" / "core_option_quote_daily.parquet"
    calendar_path = _write_calendar(
        tmp_path / "configs" / "calendars" / "CZCE_2026_OFFICIAL.csv",
        ["2026-07-03", "2026-07-06"],
    )
    _write_futures_core(
        core_path,
        [
            ("2026-07-03", "CF609", "raw_fut_0703:FutureDataDailyCF.xlsx"),
            ("2026-07-06", "CF609", "raw_fut_0706:FutureDataDailyCF.xlsx"),
            ("2026-07-06", "CF701", "raw_fut_0706:FutureDataDailyCF.xlsx"),
        ],
    )
    _write_option_core(
        option_path,
        [
            ("2026-07-03", "CF609C15000", "raw_opt_0703:OptionDataDaily.xlsx"),
            ("2026-07-06", "CF609C15000", "raw_opt_0706:OptionDataDaily.xlsx"),
        ],
    )
    raw_root = tmp_path / "raw"
    _write_raw_manifest(
        raw_root,
        ["raw_fut_0706", "raw_opt_0706"],
    )
    futures_file = tmp_path / "incoming" / "FutureDataDailyCF.xlsx"
    options_file = tmp_path / "incoming" / "OptionDataDaily.xlsx"
    futures_file.parent.mkdir(parents=True, exist_ok=True)
    futures_file.write_bytes(b"PK\x03\x04future")
    options_file.write_bytes(b"PK\x03\x04option")
    fetch_json_path = tmp_path / "reports" / "official_daily_files.json"
    fetch_json_path.parent.mkdir(parents=True, exist_ok=True)
    fetch_json_path.write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "trade_date": "2026-07-06",
                "records": [
                    {
                        "file_kind": "futures",
                        "status": "DOWNLOADED",
                        "output_path": str(futures_file),
                        "sha256": hashlib.sha256(futures_file.read_bytes()).hexdigest(),
                    },
                    {
                        "file_kind": "options",
                        "status": "DOWNLOADED",
                        "output_path": str(options_file),
                        "sha256": hashlib.sha256(options_file.read_bytes()).hexdigest(),
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return core_path, option_path, calendar_path, fetch_json_path, raw_root


def _write_futures_core(
    path: Path,
    rows: list[tuple[str, str, str]],
) -> None:
    frame = pd.DataFrame(
        [
            {
                "schema_version": "core_quote_daily.v1",
                "source_snapshot_id": source_snapshot_id,
                "exchange": "CZCE",
                "product_code": "CF",
                "contract_code": contract_code,
                "trade_date": trade_date,
                "open": 15000.0,
                "high": 15100.0,
                "low": 14900.0,
                "close": 15050.0,
                "settle": 15020.0,
                "pre_settle": 15000.0,
                "volume": 100,
                "open_interest": 200,
                "turnover": 1000.0,
                "quote_status": "normal",
            }
            for trade_date, contract_code, source_snapshot_id in rows
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _write_option_core(
    path: Path,
    rows: list[tuple[str, str, str]],
) -> None:
    frame = pd.DataFrame(
        [
            {
                "schema_version": "core_option_quote_daily.v1",
                "source_snapshot_id": source_snapshot_id,
                "exchange": "CZCE",
                "product_code": "CF",
                "trade_date": trade_date,
                "option_symbol": option_symbol,
                "underlying_contract": "CF609",
                "option_type": "C",
                "strike": 15000.0,
                "settle": 200.0,
                "volume": 10,
                "open_interest": 20,
                "moneyness": 1.0,
                "liquidity_flag": "normal_liquidity",
                "data_quality_flag": "normal",
            }
            for trade_date, option_symbol, source_snapshot_id in rows
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _write_calendar(path: Path, trading_dates: list[str]) -> Path:
    frame = pd.DataFrame(
        [
            {
                "exchange": "CZCE",
                "trade_date": trade_date,
                "is_trading_day": "true",
                "calendar_version": "CZCE_2026_TEST",
                "source_snapshot_id": "calendar_fixture",
            }
            for trade_date in trading_dates
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


def _write_raw_manifest(raw_root: Path, snapshot_ids: list[str]) -> None:
    manifest_path = raw_root / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for snapshot_id in snapshot_ids:
        payload_path = raw_root / "snapshots" / snapshot_id / "payload.bin"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_bytes(b"raw")
        lines.append(
            json.dumps(
                {
                    "snapshot_id": snapshot_id,
                    "payload_path": str(payload_path.relative_to(raw_root)).replace("\\", "/"),
                },
                ensure_ascii=True,
            )
        )
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
