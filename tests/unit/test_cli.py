from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cotton_factor.cli.main import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Cotton factor MVP CLI" in result.output


def test_cli_status() -> None:
    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "D23 ready" in result.output


def test_cli_build_calendar_provisional() -> None:
    result = CliRunner().invoke(
        app,
        [
            "core",
            "build-calendar",
            "--start",
            "2026-01-05",
            "--end",
            "2026-01-09",
            "--exchange",
            "CZCE",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["calendar_version"] == "PROVISIONAL_FIXTURE"
    assert output["row_count"] == 5
    assert output["trading_day_count"] == 5
    assert output["warnings"]


def test_cli_build_calendar_defaults_to_official_2024() -> None:
    result = CliRunner().invoke(
        app,
        [
            "core",
            "build-calendar",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-10",
            "--exchange",
            "CZCE",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["calendar_version"] == "CZCE_OFFICIAL_2024_HOLIDAY_NOTICE"
    assert output["trading_day_count"] == 7
    assert output["rows"][0]["source_snapshot_id"] == "czce_2024_holiday_notice_20231226"
    assert output["warnings"] == []


def test_cli_build_chain_map_with_ltd_guard() -> None:
    quote_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
    )
    result = CliRunner().invoke(
        app,
        [
            "core",
            "build-chain-map",
            "--product",
            "CF",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-12",
            "--quote-fixture",
            str(quote_fixture),
            "--ltd-buffer-days",
            "2",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 4
    assert [row["mapped_contract"] for row in output["rows"]] == [
        "CF401",
        "CF401",
        "CF405",
        "CF405",
    ]
    assert output["rows"][2]["switch_reason"] == "ltd_guard_fallback"


def test_cli_build_trade_mapping_with_t_plus_one_and_ltd_guard() -> None:
    quote_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
    )
    result = CliRunner().invoke(
        app,
        [
            "core",
            "build-trade-mapping",
            "--product",
            "CF",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-12",
            "--quote-fixture",
            str(quote_fixture),
            "--ltd-buffer-days",
            "2",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 4
    assert output["blocked_count"] == 1
    assert [row["execution_date"] for row in output["rows"]] == [
        "2024-01-10",
        "2024-01-11",
        "2024-01-12",
        "2024-01-15",
    ]
    assert output["rows"][0]["target_contract"] == "CF401"
    assert output["rows"][1]["target_contract"] is None
    assert output["rows"][1]["block_reason"] == "ltd_buffer_execution_block"


def test_cli_build_trade_mapping_with_settlement_block() -> None:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    result = CliRunner().invoke(
        app,
        [
            "core",
            "build-trade-mapping",
            "--product",
            "CF",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-09",
            "--quote-fixture",
            str(fixture_dir / "core_quote_daily_cf_chain_sample.csv"),
            "--settlement-fixture",
            str(fixture_dir / "core_settlement_param_daily_cf_block_sample.csv"),
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["blocked_count"] == 1
    assert output["rows"][0]["execution_date"] == "2024-01-10"
    assert output["rows"][0]["block_reason"] == "settlement_status_halted"


def test_cli_build_continuous_price_with_roll_trace() -> None:
    quote_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
    )
    result = CliRunner().invoke(
        app,
        [
            "core",
            "build-continuous-price",
            "--product",
            "CF",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-12",
            "--quote-fixture",
            str(quote_fixture),
            "--ltd-buffer-days",
            "2",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 4
    assert output["roll_count"] == 1
    assert [row["adjusted_price"] for row in output["rows"]] == [
        15540.0,
        15550.0,
        15560.0,
        15570.0,
    ]
    assert output["rows"][2]["roll_from_contract"] == "CF401"
    assert output["rows"][2]["roll_to_contract"] == "CF405"


def test_cli_build_contract_master_cf() -> None:
    result = CliRunner().invoke(
        app,
        ["core", "build-contract-master", "--product", "CF", "--year", "2024"],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["product_code"] == "CF"
    assert output["rule_version"]["rule_version_id"] == "CZCE.CF.contract_rules.v1"
    assert [row["contract_code"] for row in output["contracts"]] == [
        "CF401",
        "CF403",
        "CF405",
        "CF407",
        "CF409",
        "CF411",
    ]
    assert output["warnings"]


def test_smoke_cf_dry_run() -> None:
    result = CliRunner().invoke(
        app,
        ["smoke", "cf", "--start", "2024-01-01", "--end", "2024-01-05", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "D19 full chain" in result.output


def test_smoke_products_sr_ap_config_only() -> None:
    result = CliRunner().invoke(app, ["smoke", "products", "--products", "SR,AP"])

    assert result.exit_code == 0
    output = json.loads(result.output)
    products = {item["product_code"]: item for item in output["products"]}
    assert products["SR"]["contract_count"] == 6
    assert products["AP"]["contract_count"] == 7
    assert products["SR"]["rule_version_id"] == "CZCE.SR.contract_rules.v1"


def test_cli_qa_validate_csv() -> None:
    quote_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
    )
    result = CliRunner().invoke(
        app,
        ["qa", "validate-csv", "--table", "core_quote_daily", "--csv", str(quote_fixture)],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["table_name"] == "core_quote_daily"
    assert output["row_count"] == 8


def test_cli_qa_audit_csv() -> None:
    quote_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
    )
    result = CliRunner().invoke(
        app,
        [
            "qa",
            "audit-csv",
            "--table",
            "core_quote_daily",
            "--csv",
            str(quote_fixture),
            "--min-row-count",
            "8",
            "--max-null-ratio",
            "settle=0",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["passed"] is True
    assert output["null_ratios"]["settle"] == 0.0


def test_cli_uat_replay(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "uat",
            "replay",
            "--scenario",
            "cf_mvp_fixture",
            "--output-root",
            str(tmp_path / "uat"),
            "--run-id",
            "d22_cli_uat_replay_test",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["passed"] is True
    assert output["failed_checks"] == []
    assert Path(output["json_report_path"]).exists()
    assert Path(output["html_report_path"]).exists()


def test_cli_release_freeze(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "release",
            "freeze",
            "--version",
            "0.1.0",
            "--output-root",
            str(tmp_path / "archive"),
            "--run-id",
            "d23_cli_release_test",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["passed"] is True
    assert output["production_ready"] is False
    assert output["failed_checks"] == []
    assert Path(output["release_manifest_path"]).exists()
    assert Path(output["bundle_path"]).exists()


def test_cli_ingest_czce_daily_quote_fixture(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "czce_daily_quote_sample.html"
    )

    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "czce-daily-quote",
            "--date",
            "2024-01-02",
            "--product",
            "CF",
            "--fixture",
            str(fixture_path),
            "--raw-root",
            str(tmp_path / "raw"),
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["source_name"] == "CZCE_DAILY_QUOTE"
    assert output["product_code"] == "CF"
    assert output["biz_date"] == "2024-01-02"
    assert output["content_type"] == "text/html"
    assert (tmp_path / "raw" / "manifest.jsonl").exists()


def test_cli_ingest_czce_history_and_list_raw_snapshots(tmp_path: Path) -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "czce_history_2024"
    raw_root = tmp_path / "raw"

    ingest_result = CliRunner().invoke(
        app,
        [
            "ingest",
            "czce-history",
            "--year",
            "2024",
            "--product",
            "CF",
            "--file-type",
            "csv",
            "--fixture",
            str(fixture_path),
            "--raw-root",
            str(raw_root),
        ],
    )

    assert ingest_result.exit_code == 0
    ingest_output = json.loads(ingest_result.output)
    assert len(ingest_output) == 2
    assert {row["source_name"] for row in ingest_output} == {"CZCE_HISTORY_QUOTE"}

    list_result = CliRunner().invoke(
        app,
        [
            "raw",
            "list",
            "--source",
            "CZCE_HISTORY_QUOTE",
            "--product",
            "CF",
            "--year",
            "2024",
            "--raw-root",
            str(raw_root),
        ],
    )

    assert list_result.exit_code == 0
    listed_output = json.loads(list_result.output)
    assert [row["snapshot_id"] for row in listed_output] == [
        row["snapshot_id"] for row in ingest_output
    ]
    assert all(row["metadata"]["history_year"] == 2024 for row in listed_output)


def test_cli_ingest_czce_settlement_fixture(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "czce_settlement_param_sample.csv"
    )

    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "czce-settlement",
            "--date",
            "2024-01-02",
            "--product",
            "CF",
            "--fixture",
            str(fixture_path),
            "--raw-root",
            str(tmp_path / "raw"),
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["source_name"] == "CZCE_SETTLEMENT_PARAM"
    assert output["product_code"] == "CF"
    assert output["biz_date"] == "2024-01-02"
    assert output["content_type"] == "text/csv"
    assert output["metadata"]["settlement_param_roles"] == (
        "limit_margin_trading_status_blocking_entry"
    )
    assert (tmp_path / "raw" / "manifest.jsonl").exists()
