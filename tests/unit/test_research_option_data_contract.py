from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.core import table_contract, validate_rows
from cotton_factor.research_workbench import build_cf_option_data_contract


def test_build_cf_option_data_contract_missing_history_writes_warning_artifacts(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "options" / "history"

    result = build_cf_option_data_contract(
        source_dir=source_dir,
        core_output_dir=tmp_path / "core",
        report_output_dir=tmp_path / "reports",
        run_id="r46_unit_missing",
    )

    assert result.status == "MISSING_OPTION_HISTORY"
    assert result.passed is True
    assert result.incoming_dir.exists()
    assert result.core_option_quote_path.exists()
    assert result.core_row_count == 0
    assert result.incoming_file_count == 0
    assert result.schema_table == "core_option_quote_daily"
    assert "option_symbol" in result.schema_columns
    assert result.warnings[0].warning_code == "MISSING_OPTION_HISTORY"

    empty_core = pd.read_parquet(result.core_option_quote_path)
    assert empty_core.empty
    assert list(empty_core.columns) == list(result.schema_columns)

    warning_csv = result.warning_csv_path.read_text(encoding="utf-8")
    assert "MISSING_OPTION_HISTORY" in warning_csv
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 期权数据契约 R46" in markdown
    assert "MISSING_OPTION_HISTORY" in markdown
    assert "本报告不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "MISSING_OPTION_HISTORY"
    assert manifest["option_signal_status"] == "not_connected"


def test_build_cf_option_data_contract_detects_present_file_without_parsing(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "options" / "history"
    source_dir.mkdir(parents=True)
    (source_dir / "CFOPTIONS2024.xlsx").write_bytes(b"placeholder")

    result = build_cf_option_data_contract(
        source_dir=source_dir,
        output_path=tmp_path / "core" / "core_option_quote_daily.parquet",
        report_output_dir=tmp_path / "reports",
        run_id="r46_unit_present",
    )

    assert result.status == "OPTION_HISTORY_PRESENT_CONTRACT_ONLY"
    assert result.incoming_file_count == 1
    assert result.warnings[0].warning_code == "OPTION_HISTORY_PRESENT_NOT_PARSED_R47_REQUIRED"


def test_core_option_fixture_matches_registered_schema() -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "core_option_quote_daily_cf_sample.csv"
    )
    frame = pd.read_csv(fixture)

    rows = validate_rows("core_option_quote_daily", frame.to_dict("records"))

    assert rows[0].option_symbol == "CF401C15000"
    contract = table_contract("core_option_quote_daily")
    assert contract["primary_key"] == ["exchange", "option_symbol", "trade_date"]
    assert "source_snapshot_id" in contract["lineage_fields"]


def test_cli_build_cf_option_data_contract(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-option-data-contract",
            "--source-dir",
            str(tmp_path / "incoming" / "CF" / "options" / "history"),
            "--core-output-dir",
            str(tmp_path / "core"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r46_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r46_cli"
    assert output["status"] == "MISSING_OPTION_HISTORY"
    assert output["warnings"][0]["warning_code"] == "MISSING_OPTION_HISTORY"
    assert Path(output["core_option_quote_path"]).exists()
    assert Path(output["markdown_path"]).exists()
