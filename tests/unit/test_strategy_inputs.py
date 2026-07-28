from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.strategy.inputs import prepare_cf_strategy_inputs


def test_prepare_strategy_inputs_keeps_cross_year_t_plus_one_mapping(tmp_path: Path) -> None:
    core_path, calendar_dir = _fixture_inputs(tmp_path)

    result = prepare_cf_strategy_inputs(
        core_quote_path=core_path,
        calendar_dir=calendar_dir,
        output_dir=tmp_path / "strategy_inputs",
        report_output_dir=tmp_path / "reports",
        run_id="r86_fixture",
    )

    trade = pd.read_parquet(result.trade_mapping_path)
    continuous = pd.read_parquet(result.continuous_price_path)
    validation = pd.read_csv(result.calendar_validation_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert trade["trade_date"].astype(str).tolist() == ["2023-12-29", "2024-01-02"]
    assert trade["execution_date"].astype(str).tolist() == ["2024-01-02", "2024-01-03"]
    assert continuous["trade_date"].astype(str).tolist() == [
        "2023-12-29",
        "2024-01-02",
        "2024-01-03",
    ]
    assert validation["status"].tolist() == ["PASS", "PASS"]
    assert result.pending_signal_dates == (date(2024, 1, 3),)
    assert manifest["rule_version"] == "V5.1_R86_strategy_inputs_v1"
    assert "不构成交易指令" in result.markdown_path.read_text(encoding="utf-8")


def test_strategy_cli_validates_specs_and_prepares_inputs(tmp_path: Path) -> None:
    runner = CliRunner()
    validated = runner.invoke(app, ["strategy", "validate-specs"])
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["strategy_count"] == 2

    core_path, calendar_dir = _fixture_inputs(tmp_path)
    prepared = runner.invoke(
        app,
        [
            "strategy",
            "prepare-inputs",
            "--core-quote-path",
            str(core_path),
            "--calendar-dir",
            str(calendar_dir),
            "--output-dir",
            str(tmp_path / "cli_inputs"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "r86_cli_fixture",
        ],
    )
    assert prepared.exit_code == 0, prepared.output
    assert json.loads(prepared.output)["trade_mapping_row_count"] == 2


def _fixture_inputs(tmp_path: Path) -> tuple[Path, Path]:
    rows = [
        _quote(date(2023, 12, 29), settle=100.0),
        _quote(date(2024, 1, 2), settle=101.0),
        _quote(date(2024, 1, 3), settle=102.0),
    ]
    core_path = tmp_path / "core_quote_daily.parquet"
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(
        core_path,
        index=False,
    )
    calendar_dir = tmp_path / "calendars"
    calendar_dir.mkdir()
    _write_calendar(calendar_dir / "CZCE_2023_OFFICIAL.csv", 2023, {date(2023, 12, 29)})
    _write_calendar(
        calendar_dir / "CZCE_2024_OFFICIAL.csv",
        2024,
        {date(2024, 1, 2), date(2024, 1, 3)},
    )
    return core_path, calendar_dir


def _write_calendar(path: Path, year: int, trading_dates: set[date]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "exchange",
                "trade_date",
                "is_trading_day",
                "calendar_version",
                "source_snapshot_id",
            ),
        )
        writer.writeheader()
        current = date(year, 1, 1)
        while current <= date(year, 12, 31):
            writer.writerow(
                {
                    "exchange": "CZCE",
                    "trade_date": current.isoformat(),
                    "is_trading_day": "true" if current in trading_dates else "false",
                    "calendar_version": f"TEST_{year}",
                    "source_snapshot_id": f"test_calendar_{year}",
                }
            )
            current += timedelta(days=1)


def _quote(trade_date: date, *, settle: float) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"official_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=trade_date,
        open=settle,
        high=settle,
        low=settle,
        close=settle,
        settle=settle,
        volume=100,
        open_interest=1000,
    )
