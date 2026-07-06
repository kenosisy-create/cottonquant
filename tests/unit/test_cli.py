from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.core import load_core_quote_daily_csv
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchContinuousPriceDailyRow,
    ResearchFactorDiagnosticDailyRow,
    ResearchFactorEvaluationRow,
    ResearchFactorValueDailyRow,
    ResearchForwardReturnDailyRow,
    ResearchMultifactorScoreDailyRow,
)


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "Cotton factor research workbench CLI" in result.output


def test_cli_status() -> None:
    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "research workbench ready" in result.output


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
            "TESTEX",
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


def test_cli_research_ingest_cf(tmp_path: Path) -> None:
    input_file = tmp_path / "incoming" / "cf_daily.csv"
    input_file.parent.mkdir()
    input_file.write_text(
        "trade_date,contract_id,settle\n2026-06-11,CF609,15000\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "research",
            "ingest-cf",
            "--date",
            "2026-06-11",
            "--input-path",
            str(input_file),
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--run-id",
            "r04_cli_ingest",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["run_id"] == "r04_cli_ingest"
    assert output["product_code"] == "CF"
    assert output["file_count"] == 1
    assert Path(output["records"][0]["raw_path"]).exists()
    assert Path(output["manifest_path"]).exists()


def test_cli_research_normalize_cf_quotes(tmp_path: Path) -> None:
    input_file = tmp_path / "incoming" / "cf_daily.csv"
    input_file.parent.mkdir()
    input_file.write_text(
        "trade_date,exchange,product_code,contract_id,open,high,low,close,settle,"
        "volume,open_interest\n"
        "2026-06-11,CZCE,CF,CF609,15000,15100,14900,15080,15060,1000,30000\n",
        encoding="utf-8",
    )
    ingest_result = CliRunner().invoke(
        app,
        [
            "research",
            "ingest-cf",
            "--date",
            "2026-06-11",
            "--input-path",
            str(input_file),
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--run-id",
            "r05_cli_raw",
        ],
    )
    assert ingest_result.exit_code == 0

    result = CliRunner().invoke(
        app,
        [
            "research",
            "normalize-cf-quotes",
            "--date",
            "2026-06-11",
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--core-output-dir",
            str(tmp_path / "core"),
            "--run-id",
            "r05_cli_raw",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 1
    assert output["source_raw_runs"] == ["r05_cli_raw"]
    assert Path(output["output_path"]).exists()


def test_cli_research_check_cf_quality(tmp_path: Path) -> None:
    input_file = tmp_path / "incoming" / "cf_daily.csv"
    input_file.parent.mkdir()
    input_file.write_text(
        "trade_date,exchange,product_code,contract_id,open,high,low,close,settle,"
        "volume,open_interest\n"
        "2026-06-11,CZCE,CF,CF609,15000,15100,14900,15080,15060,1000,30000\n",
        encoding="utf-8",
    )
    ingest_result = CliRunner().invoke(
        app,
        [
            "research",
            "ingest-cf",
            "--date",
            "2026-06-11",
            "--input-path",
            str(input_file),
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--run-id",
            "r06_cli_raw",
        ],
    )
    assert ingest_result.exit_code == 0

    normalize_result = CliRunner().invoke(
        app,
        [
            "research",
            "normalize-cf-quotes",
            "--date",
            "2026-06-11",
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--core-output-dir",
            str(tmp_path / "core"),
            "--run-id",
            "r06_cli_raw",
        ],
    )
    assert normalize_result.exit_code == 0

    result = CliRunner().invoke(
        app,
        [
            "research",
            "check-cf-quality",
            "--date",
            "2026-06-11",
            "--core-output-dir",
            str(tmp_path / "core"),
            "--report-output-dir",
            str(tmp_path / "quality"),
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["passed"] is True
    assert output["row_count"] == 1
    assert Path(output["csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_review_cf_contract_rules(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "research",
            "review-cf-contract-rules",
            "--year",
            "2024",
            "--report-output-dir",
            str(tmp_path / "contract_rules"),
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["product_code"] == "CF"
    assert output["year"] == 2024
    assert output["human_review_required_count"] > 0
    assert Path(output["csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_mapping(tmp_path: Path) -> None:
    quote_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
    )
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    core_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [row.model_dump(mode="json") for row in load_core_quote_daily_csv(quote_fixture)]
    ).to_parquet(core_path, index=False)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-mapping",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-12",
            "--core-quote-path",
            str(core_path),
            "--output-dir",
            str(tmp_path / "mapping"),
            "--report-output-dir",
            str(tmp_path / "mapping_report"),
            "--ltd-buffer-days",
            "2",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["chain_row_count"] == 4
    assert output["trade_row_count"] == 4
    assert output["blocked_trade_count"] == 1
    assert Path(output["chain_parquet_path"]).exists()
    assert Path(output["trade_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_continuous(tmp_path: Path) -> None:
    quote_fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
    )
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    core_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [row.model_dump(mode="json") for row in load_core_quote_daily_csv(quote_fixture)]
    ).to_parquet(core_path, index=False)

    mapping_result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-mapping",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-12",
            "--core-quote-path",
            str(core_path),
            "--output-dir",
            str(tmp_path / "mapping"),
            "--report-output-dir",
            str(tmp_path / "mapping_report"),
            "--ltd-buffer-days",
            "2",
        ],
    )
    assert mapping_result.exit_code == 0
    mapping_output = json.loads(mapping_result.output)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-continuous",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-12",
            "--core-quote-path",
            str(core_path),
            "--chain-map-path",
            mapping_output["chain_parquet_path"],
            "--output-dir",
            str(tmp_path / "continuous"),
            "--report-output-dir",
            str(tmp_path / "continuous_report"),
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 4
    assert output["roll_count"] == 1
    assert Path(output["continuous_parquet_path"]).exists()
    assert Path(output["roll_diagnostics_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_write_cf_factor_output_contract(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "research",
            "write-cf-factor-output-contract",
            "--output-dir",
            str(tmp_path / "contracts"),
            "--report-output-dir",
            str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["contract_version"] == "R10.factor_diagnostics_output_contract.v1"
    assert output["artifact_count"] == 4
    assert "cf_factor_diagnostic_daily" in output["artifact_ids"]
    assert Path(output["json_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_momentum_factor(tmp_path: Path) -> None:
    continuous_path = _write_cli_continuous_rows(tmp_path, row_count=21)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-momentum-factor",
            "--start",
            "2024-01-21",
            "--end",
            "2024-01-21",
            "--continuous-price-path",
            str(continuous_path),
            "--output-dir",
            str(tmp_path / "factors"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r11_cli_momentum",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["factor_id"] == "mom_20_v1"
    assert output["row_count"] == 1
    assert output["warning_count"] == 1
    assert Path(output["factor_parquet_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_carry_factor(tmp_path: Path) -> None:
    core_path = _write_cli_core_quote_rows(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-carry-factor",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-09",
            "--core-quote-path",
            str(core_path),
            "--output-dir",
            str(tmp_path / "factors"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r12_cli_carry",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["factor_id"] == "carry_nf_v1"
    assert output["row_count"] == 1
    assert output["warning_count"] >= 1
    assert "carry_tenor_rule" in output["human_review_required"]
    assert Path(output["factor_parquet_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_structure_factors(tmp_path: Path) -> None:
    core_path = _write_cli_structure_core_quote_rows(tmp_path)
    chain_path = _write_cli_chain_rows(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-structure-factors",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-09",
            "--core-quote-path",
            str(core_path),
            "--chain-map-path",
            str(chain_path),
            "--output-dir",
            str(tmp_path / "factors"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r13_cli_structure",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["curve_row_count"] == 1
    assert output["oi_pressure_row_count"] == 1
    assert output["row_count"] == 2
    assert output["warning_count"] >= 2
    assert Path(output["factor_parquet_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_factor_diagnostics(tmp_path: Path) -> None:
    factor_path = _write_cli_factor_value_rows(tmp_path)
    warning_path = tmp_path / "factors" / "CF_2024-01-09_2024-01-09_factor_warnings.csv"

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-factor-diagnostics",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-09",
            "--factor-value-path",
            str(factor_path),
            "--warning-csv-path",
            str(warning_path),
            "--output-dir",
            str(tmp_path / "diagnostics"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r14_cli_diagnostics",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 4
    assert output["unknown_count"] == 1
    assert output["missing_factor_count"] == 1
    assert Path(output["diagnostic_parquet_path"]).exists()
    assert Path(output["diagnostic_csv_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_forward_returns(tmp_path: Path) -> None:
    trade_path = _write_cli_trade_mapping_rows(tmp_path)
    quote_path = _write_cli_forward_quote_rows(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-forward-returns",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
            "--horizons",
            "1,2",
            "--core-quote-path",
            str(quote_path),
            "--trade-mapping-path",
            str(trade_path),
            "--output-dir",
            str(tmp_path / "returns"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r15_cli_forward",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 2
    assert output["row_count_by_horizon"] == {"1": 1, "2": 1}
    assert output["warning_count"] == 0
    assert Path(output["forward_return_parquet_path"]).exists()
    assert Path(output["forward_return_csv_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_run_cf_single_factor_backtest(tmp_path: Path) -> None:
    diagnostic_path = _write_cli_diagnostic_rows(tmp_path)
    forward_path = _write_cli_forward_return_rows(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "run-cf-single-factor-backtest",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
            "--factor-ids",
            "mom_20_v1",
            "--horizons",
            "1",
            "--diagnostic-path",
            str(diagnostic_path),
            "--forward-return-path",
            str(forward_path),
            "--output-dir",
            str(tmp_path / "backtests"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r16_cli_single_factor",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] >= 4
    assert output["metric_count_by_factor_horizon"]["mom_20_v1:1"] >= 4
    assert Path(output["evaluation_parquet_path"]).exists()
    assert Path(output["evaluation_csv_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_multifactor_diagnostics(tmp_path: Path) -> None:
    diagnostic_path = _write_cli_multifactor_diagnostic_rows(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-multifactor-diagnostics",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-01",
            "--factor-ids",
            "mom_20_v1,carry_nf_v1",
            "--diagnostic-path",
            str(diagnostic_path),
            "--output-dir",
            str(tmp_path / "multifactor"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r17_cli_multifactor",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 1
    assert output["factor_weights"] == {"mom_20_v1": 0.5, "carry_nf_v1": 0.5}
    assert Path(output["score_parquet_path"]).exists()
    assert Path(output["score_csv_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_cost_sensitivity(tmp_path: Path) -> None:
    score_path = _write_cli_multifactor_score_rows(tmp_path)
    forward_path = _write_cli_forward_return_rows(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-cost-sensitivity",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
            "--horizons",
            "1",
            "--score-path",
            str(score_path),
            "--forward-return-path",
            str(forward_path),
            "--scenario-cost-bps",
            "no_cost=0,normal_cost=5",
            "--output-dir",
            str(tmp_path / "costs"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r18_cli_cost",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["row_count"] == 2
    assert output["row_count_by_scenario"] == {"no_cost": 1, "normal_cost": 1}
    assert output["warning_count"] == 2
    assert Path(output["summary_parquet_path"]).exists()
    assert Path(output["summary_csv_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_cli_research_build_cf_daily_brief(tmp_path: Path) -> None:
    inputs = _write_cli_daily_brief_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-daily-brief",
            "--date",
            "2024-01-09",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-09",
            "--quality-csv-path",
            str(inputs["quality"]),
            "--chain-map-path",
            str(inputs["chain"]),
            "--trade-mapping-path",
            str(inputs["trade"]),
            "--diagnostic-path",
            str(inputs["diagnostic"]),
            "--single-factor-evaluation-path",
            str(inputs["evaluation"]),
            "--multifactor-score-path",
            str(inputs["score"]),
            "--cost-sensitivity-path",
            str(inputs["cost"]),
            "--report-output-dir",
            str(tmp_path / "briefs"),
            "--run-id",
            "r19_cli_brief",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["brief_status"] == "WATCH_REQUIRED"
    assert output["warning_count"] >= 1
    assert Path(output["markdown_path"]).exists()
    assert Path(output["json_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()


def test_cli_research_build_cf_latest_signal_brief(tmp_path: Path) -> None:
    core_path = _write_cli_latest_signal_core_quotes(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-latest-signal-brief",
            "--core-quote-path",
            str(core_path),
            "--output-root",
            str(tmp_path / "daily"),
            "--run-id",
            "r23_cli_latest",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["trade_date"] == "2024-02-05"
    assert output["main_contract"] == "CF405"
    assert output["signal_direction"] == "long"
    assert output["trend_phase"]["phase_code"] == "S2"
    assert Path(output["markdown_path"]).parent == tmp_path / "daily" / "CF" / "2024-02-05"
    assert Path(output["markdown_path"]).exists()
    assert Path(output["json_path"]).exists()
    assert Path(output["warning_csv_path"]).exists()
    assert Path(output["manifest_path"]).exists()


def test_cli_research_build_cf_latest_signal_brief_with_trend_rule_candidates(
    tmp_path: Path,
) -> None:
    core_path = _write_cli_latest_signal_transition_core_quotes(tmp_path)
    candidate_path = _write_cli_trend_rule_candidate_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-latest-signal-brief",
            "--core-quote-path",
            str(core_path),
            "--output-root",
            str(tmp_path / "daily"),
            "--run-id",
            "r28_cli_latest",
            "--trend-rule-candidate-path",
            str(candidate_path),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["trend_rule_candidate_path"] == str(candidate_path)
    assert output["trend_rule_context"]["transition_code"] == "S1_TO_S2"
    assert output["trend_rule_context"]["candidate_status"] == "READY_CANDIDATE"
    assert output["trend_rule_context"]["daily_brief_action"] == (
        "ALLOW_DAILY_EXPLANATION_CANDIDATE"
    )


def test_cli_research_build_cf_trend_continuity_board(tmp_path: Path) -> None:
    core_path = _write_cli_latest_signal_transition_core_quotes(tmp_path)
    candidate_path = _write_cli_trend_rule_candidate_fixture(tmp_path)
    calibration_manifest_path = _write_cli_trend_quality_calibration_manifest(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-continuity-board",
            "--core-quote-path",
            str(core_path),
            "--output-root",
            str(tmp_path / "daily"),
            "--run-id",
            "r29_cli_board",
            "--lookback-trading-days",
            "3",
            "--trend-rule-candidate-path",
            str(candidate_path),
            "--trend-quality-calibration-manifest-path",
            str(calibration_manifest_path),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r29_cli_board"
    assert output["row_count"] == 3
    assert output["latest_transition_code"] == "S1_TO_S2"
    assert output["latest_observation_marker"] == "趋势起点观察"
    assert output["latest_trend_quality_score"] >= 60
    assert output["latest_trend_quality_label"] in {"趋势质量改善", "强趋势质量"}
    assert output["trend_quality_calibration_manifest_path"] == str(calibration_manifest_path)
    assert output["trend_quality_calibration_context"]["context_status"] == "PROVIDED"
    assert Path(output["board_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()
    assert Path(output["json_path"]).exists()
    assert Path(output["manifest_path"]).exists()


def test_cli_research_build_cf_trend_quality_calibration(tmp_path: Path) -> None:
    core_path = _write_cli_latest_signal_transition_core_quotes(tmp_path)
    candidate_path = _write_cli_trend_rule_candidate_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-quality-calibration",
            "--start",
            "2024-01-15",
            "--end",
            "2024-02-02",
            "--horizons",
            "1,3",
            "--core-quote-path",
            str(core_path),
            "--output-dir",
            str(tmp_path / "quality_calibration"),
            "--report-output-dir",
            str(tmp_path / "quality_reports"),
            "--run-id",
            "r32_cli_calibration",
            "--trend-rule-candidate-path",
            str(candidate_path),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r32_cli_calibration"
    assert output["start"] == "2024-01-15"
    assert output["end"] == "2024-02-02"
    assert output["horizons"] == [1, 3]
    assert output["daily_row_count"] >= 1
    assert output["latest_main_contract"] == "CF405"
    assert output["latest_score_context_label"] in {"历史低位", "历史中位", "历史高位"}
    assert Path(output["daily_parquet_path"]).exists()
    assert Path(output["bucket_summary_parquet_path"]).exists()
    assert Path(output["phase_distribution_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()
    assert Path(output["json_path"]).exists()
    assert Path(output["manifest_path"]).exists()


def test_cli_research_build_cf_latest_signal_brief_rejects_missing_date(
    tmp_path: Path,
) -> None:
    core_path = _write_cli_latest_signal_core_quotes(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-latest-signal-brief",
            "--date",
            "2024-12-31",
            "--core-quote-path",
            str(core_path),
            "--output-root",
            str(tmp_path / "daily"),
            "--run-id",
            "r23_cli_missing",
        ],
    )

    assert result.exit_code == 1
    assert "no CF core rows for 2024-12-31" in result.output


def test_cli_research_build_cf_trend_phase_validation(tmp_path: Path) -> None:
    core_path = _write_cli_latest_signal_core_quotes(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-phase-validation",
            "--start",
            "2024-01-30",
            "--end",
            "2024-02-01",
            "--horizons",
            "1",
            "--core-quote-path",
            str(core_path),
            "--output-dir",
            str(tmp_path / "trend_phase"),
            "--report-output-dir",
            str(tmp_path / "trend_reports"),
            "--run-id",
            "r25_cli_validation",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r25_cli_validation"
    assert output["daily_row_count"] == 3
    assert output["summary_row_count"] >= 1
    assert Path(output["daily_parquet_path"]).exists()
    assert Path(output["summary_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()
    assert Path(output["manifest_path"]).exists()


def test_cli_research_build_cf_trend_phase_events(tmp_path: Path) -> None:
    daily_path = _write_cli_trend_phase_daily_rows(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-phase-events",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
            "--horizons",
            "1",
            "--trend-phase-daily-path",
            str(daily_path),
            "--output-dir",
            str(tmp_path / "events"),
            "--report-output-dir",
            str(tmp_path / "event_reports"),
            "--run-id",
            "r26_cli_events",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r26_cli_events"
    assert output["event_count"] == 2
    assert output["key_event_count"] == 2
    assert Path(output["event_parquet_path"]).exists()
    assert Path(output["summary_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()
    assert Path(output["manifest_path"]).exists()


def test_cli_research_build_cf_trend_rule_candidates(tmp_path: Path) -> None:
    summary_path, event_path = _write_cli_r26_event_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-rule-candidates",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-31",
            "--event-summary-path",
            str(summary_path),
            "--event-path",
            str(event_path),
            "--output-dir",
            str(tmp_path / "rule_candidates"),
            "--report-output-dir",
            str(tmp_path / "rule_reports"),
            "--run-id",
            "r27_cli_candidates",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r27_cli_candidates"
    assert output["candidate_count"] == 7
    assert output["ready_candidate_count"] == 1
    assert Path(output["candidate_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()
    assert Path(output["manifest_path"]).exists()


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


def _write_cli_continuous_rows(tmp_path: Path, *, row_count: int) -> Path:
    rows = []
    start = date(2024, 1, 1)
    for offset in range(row_count):
        price = 100 + offset
        rows.append(
            ResearchContinuousPriceDailyRow(
                product_code="CF",
                signal_object_id="CF.C1",
                trade_date=start + timedelta(days=offset),
                mapped_contract="CF401",
                price_field="settle",
                raw_price=float(price),
                adjusted_price=float(price),
                adjustment=0,
                cumulative_adjustment=0,
                is_roll=False,
                chain_switch_reason="r11_cli_fixture",
                continuous_rule_version="continuous_back_adjust_additive_v1",
                input_snapshot_ids=[f"raw_quote_{offset}"],
            )
        )
    path = tmp_path / "continuous" / "CF_2024-01-01_2024-01-21_settle_continuous.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_latest_signal_core_quotes(tmp_path: Path) -> Path:
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(_business_dates(date(2024, 1, 2), count=25)):
        main_settle = 100 + offset
        rows.extend(
            [
                _cli_latest_signal_quote(
                    contract_code="CF403",
                    trade_date=trade_date,
                    settle=main_settle - 2,
                    volume=800 + offset,
                    open_interest=7_000 + offset,
                ),
                _cli_latest_signal_quote(
                    contract_code="CF405",
                    trade_date=trade_date,
                    settle=main_settle,
                    volume=1_000 + offset,
                    open_interest=10_000 + offset * 100,
                ),
                _cli_latest_signal_quote(
                    contract_code="CF409",
                    trade_date=trade_date,
                    settle=main_settle + 4,
                    volume=700 + offset,
                    open_interest=6_000 + offset,
                ),
            ]
        )
    path = tmp_path / "core_latest_signal" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_cli_latest_signal_transition_core_quotes(tmp_path: Path) -> Path:
    rows: list[dict[str, object]] = []
    trade_dates = _business_dates(date(2024, 1, 2), count=25)
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset
        if offset == len(trade_dates) - 3:
            main_open_interest = 12_200
        elif offset == len(trade_dates) - 2:
            main_open_interest = 12_100
        elif offset == len(trade_dates) - 1:
            main_open_interest = 12_300
        else:
            main_open_interest = 10_000 + offset * 100
        rows.extend(
            [
                _cli_latest_signal_quote(
                    contract_code="CF403",
                    trade_date=trade_date,
                    settle=main_settle - 2,
                    volume=800 + offset,
                    open_interest=7_000 + offset,
                ),
                _cli_latest_signal_quote(
                    contract_code="CF405",
                    trade_date=trade_date,
                    settle=main_settle,
                    volume=1_000 + offset,
                    open_interest=main_open_interest,
                ),
                _cli_latest_signal_quote(
                    contract_code="CF409",
                    trade_date=trade_date,
                    settle=main_settle + 4,
                    volume=700 + offset,
                    open_interest=6_000 + offset,
                ),
            ]
        )
    path = tmp_path / "core_latest_signal_transition" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_cli_trend_rule_candidate_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "trend_rule_candidate_fixture" / "candidates.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "r27_cli_fixture",
                "product_code": "CF",
                "transition_code": "S1_TO_S2",
                "event_type": "趋势起点确认",
                "candidate_status": "READY_CANDIDATE",
                "daily_brief_action": "ALLOW_DAILY_EXPLANATION_CANDIDATE",
                "selected_horizon": 10,
                "event_count": 4,
                "observation_count": 4,
                "new_phase_direction": "long",
                "mean_forward_return": 0.0125,
                "median_forward_return": 0.011,
                "directional_hit_rate": 0.75,
                "positive_rate": 0.75,
                "negative_rate": 0.25,
                "latest_event_date": "2024-02-01",
                "evidence_score": 0.8,
                "rule_text_cn": "S1_TO_S2 可作为日报趋势解释候选，参考 h10。",
                "caveat_cn": "样本仍有限，仅用于研究解释。",
                "candidate_rule_version": "R27_trend_rule_candidates_v1",
                "source_event_rule_version": "R26_trend_phase_transition_events_v1",
            }
        ]
    ).to_parquet(path, index=False)
    return path


def _write_cli_trend_quality_calibration_manifest(tmp_path: Path) -> Path:
    root = tmp_path / "trend_quality_calibration_fixture"
    root.mkdir(parents=True)
    bucket_summary_path = root / "bucket_summary.parquet"
    pd.DataFrame(
        [
            {
                "score_bucket": "B3_60_74",
                "score_bucket_label": "60-74 趋势质量改善",
                "horizon": 5,
                "signal_day_count": 5,
                "observation_count": 4,
                "mean_forward_return": 0.01,
                "directional_hit_rate": 0.75,
            },
            {
                "score_bucket": "B3_60_74",
                "score_bucket_label": "60-74 趋势质量改善",
                "horizon": 10,
                "signal_day_count": 5,
                "observation_count": 3,
                "mean_forward_return": 0.015,
                "directional_hit_rate": 0.67,
            },
        ]
    ).to_parquet(bucket_summary_path, index=False)
    manifest_path = root / "manifest.json"
    manifest = {
        "report_type": "trend_quality_calibration",
        "rule_version": "R32_trend_quality_calibration_v1",
        "forward_returns_are_validation_labels": True,
        "start": "2024-01-02",
        "end": "2024-02-05",
        "daily_row_count": 25,
        "latest_trade_date": "2024-02-05",
        "latest_main_contract": "CF405",
        "latest_trend_quality_score": 60,
        "latest_trend_quality_label": "趋势质量改善",
        "latest_score_bucket": "B3_60_74",
        "latest_score_bucket_label": "60-74 趋势质量改善",
        "latest_score_percentile": 0.65,
        "latest_score_context_label": "历史中位",
        "bucket_summary_parquet_path": str(bucket_summary_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _write_cli_trend_phase_daily_rows(tmp_path: Path) -> Path:
    path = tmp_path / "trend_phase_events" / "daily.parquet"
    path.parent.mkdir(parents=True)
    rows = [
        _cli_trend_phase_daily("2024-01-01", "S0", "未确认", "neutral", 0, 0.0),
        _cli_trend_phase_daily("2024-01-02", "S1", "起点观察", "long", 1, 0.02),
        _cli_trend_phase_daily("2024-01-03", "S2", "趋势中", "long", 3, 0.03),
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_cli_r26_event_inputs(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "r26_events"
    root.mkdir(parents=True)
    summary_path = root / "summary.parquet"
    event_path = root / "events.parquet"
    pd.DataFrame(
        [
            _cli_r26_summary("S1_TO_S2", "趋势起点确认", "long", 3, 3, 3, 0.01, 0.67),
            _cli_r26_summary("S2_TO_S3", "衰竭观察出现", "long", 3, 1, 1, 0.02, 1.0),
        ]
    ).to_parquet(summary_path, index=False)
    pd.DataFrame(
        [
            {"transition_code": "S1_TO_S2", "event_date": "2024-01-10"},
            {"transition_code": "S2_TO_S3", "event_date": "2024-01-20"},
        ]
    ).to_parquet(event_path, index=False)
    return summary_path, event_path


def _cli_r26_summary(
    transition_code: str,
    event_type: str,
    direction: str,
    horizon: int,
    event_count: int,
    observation_count: int,
    mean_return: float,
    hit_rate: float,
) -> dict[str, object]:
    return {
        "transition_code": transition_code,
        "event_type": event_type,
        "new_phase_direction": direction,
        "horizon": horizon,
        "event_count": event_count,
        "observation_count": observation_count,
        "mean_forward_return": mean_return,
        "median_forward_return": mean_return,
        "positive_rate": hit_rate,
        "negative_rate": 1 - hit_rate,
        "directional_hit_rate": hit_rate,
        "event_rule_version": "R26_trend_phase_transition_events_v1",
    }


def _cli_trend_phase_daily(
    trade_date: str,
    phase_code: str,
    phase_label: str,
    direction: str,
    score: int,
    forward_return: float,
) -> dict[str, object]:
    return {
        "run_id": "r25_cli_fixture",
        "product_code": "CF",
        "trade_date": trade_date,
        "main_contract": "CF405",
        "trend_phase_code": phase_code,
        "trend_phase_label": phase_label,
        "trend_phase_direction": direction,
        "multi_factor_direction": direction,
        "multi_factor_score": score,
        "forward_return_h1": forward_return,
        "validation_rule_version": "R25_trend_phase_validation_v1",
    }


def _business_dates(start: date, *, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def _cli_latest_signal_quote(
    *,
    contract_code: str,
    trade_date: date,
    settle: float,
    volume: int,
    open_interest: int,
) -> dict[str, object]:
    return {
        "source_snapshot_id": f"r23_cli_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }


def _write_cli_core_quote_rows(tmp_path: Path) -> Path:
    rows = [
        CoreQuoteDailyRow(
            source_snapshot_id="raw_quote_near",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 9),
            settle=100,
            volume=100,
            open_interest=1000,
        ),
        CoreQuoteDailyRow(
            source_snapshot_id="raw_quote_far",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF405",
            trade_date=date(2024, 1, 9),
            settle=110,
            volume=100,
            open_interest=1000,
        ),
    ]
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_structure_core_quote_rows(tmp_path: Path) -> Path:
    rows = [
        CoreQuoteDailyRow(
            source_snapshot_id="raw_prev",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 8),
            settle=100,
            volume=100,
            open_interest=1000,
        ),
        CoreQuoteDailyRow(
            source_snapshot_id="raw_near",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 9),
            settle=102,
            volume=100,
            open_interest=1100,
        ),
        CoreQuoteDailyRow(
            source_snapshot_id="raw_far",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF403",
            trade_date=date(2024, 1, 9),
            settle=105,
            volume=100,
            open_interest=900,
        ),
    ]
    path = tmp_path / "core_structure" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_chain_rows(tmp_path: Path) -> Path:
    rows = [
        CoreChainMapDailyRow(
            source_snapshot_id="raw_chain_20240109",
            exchange="CZCE",
            product_code="CF",
            signal_object_id="CF.C1",
            trade_date=date(2024, 1, 9),
            mapped_contract="CF401",
            chain_rank=1,
            switch_reason="r13_cli_fixture",
            roll_rule_version="roll_placeholder_v1",
        )
    ]
    path = tmp_path / "mapping" / "CF_2024-01-09_2024-01-09_chain_map_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_factor_value_rows(tmp_path: Path) -> Path:
    rows = [
        _cli_factor_row("mom_20_v1", date(2024, 1, 9), 0.02, "mom_snap"),
        _cli_factor_row("carry_nf_v1", date(2024, 1, 9), -0.01, "carry_snap"),
        _cli_factor_row("curve_slope_v1", date(2024, 1, 9), 0.0, "curve_snap"),
    ]
    path = tmp_path / "factors" / "CF_2024-01-09_2024-01-09_factor_value_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _cli_factor_row(
    factor_id: str,
    trade_date: date,
    raw_value: float,
    snapshot_id: str,
) -> ResearchFactorValueDailyRow:
    return ResearchFactorValueDailyRow(
        run_id=f"{factor_id}_run",
        factor_id=factor_id,
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        input_snapshot_ids=[snapshot_id],
    )


def _write_cli_trade_mapping_rows(tmp_path: Path) -> Path:
    rows = [
        CoreTradeMappingDailyRow(
            source_snapshot_id="mapping_20240101",
            exchange="CZCE",
            product_code="CF",
            signal_object_id="CF.C1",
            trade_date=date(2024, 1, 1),
            execution_date=date(2024, 1, 2),
            target_contract="CF401",
            is_blocked=False,
            execution_eligible=True,
            mapping_rule_version="trade_mapping_v1",
        )
    ]
    path = tmp_path / "mapping" / "CF_2024-01-01_2024-01-02_trade_mapping_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_forward_quote_rows(tmp_path: Path) -> Path:
    rows = [
        CoreQuoteDailyRow(
            source_snapshot_id="quote_entry",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 2),
            settle=100,
            volume=100,
            open_interest=1000,
        ),
        CoreQuoteDailyRow(
            source_snapshot_id="quote_h1",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 3),
            settle=110,
            volume=100,
            open_interest=1000,
        ),
        CoreQuoteDailyRow(
            source_snapshot_id="quote_h2",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date=date(2024, 1, 4),
            settle=121,
            volume=100,
            open_interest=1000,
        ),
    ]
    path = tmp_path / "core_forward" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_diagnostic_rows(tmp_path: Path) -> Path:
    rows = [
        _cli_diagnostic_row(date(2024, 1, 1), raw_value=1.0),
        _cli_diagnostic_row(date(2024, 1, 2), raw_value=2.0),
    ]
    path = tmp_path / "factors" / "CF_2024-01-01_2024-01-02_factor_diagnostic_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_forward_return_rows(tmp_path: Path) -> Path:
    rows = [
        _cli_forward_return_row(date(2024, 1, 1), forward_return=0.1),
        _cli_forward_return_row(date(2024, 1, 2), forward_return=0.2),
    ]
    path = tmp_path / "returns" / "CF_2024-01-01_2024-01-02_forward_return_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_multifactor_diagnostic_rows(tmp_path: Path) -> Path:
    rows = [
        _cli_multifactor_diagnostic_row("mom_20_v1", date(2024, 1, 1), raw_value=0.4),
        _cli_multifactor_diagnostic_row("carry_nf_v1", date(2024, 1, 1), raw_value=0.2),
    ]
    path = tmp_path / "factors_multi" / "CF_2024-01-01_2024-01-01_diagnostic.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_multifactor_score_rows(tmp_path: Path) -> Path:
    rows = [
        _cli_multifactor_score_row(date(2024, 1, 1), raw_score=0.4),
        _cli_multifactor_score_row(date(2024, 1, 2), raw_score=-0.2),
    ]
    path = tmp_path / "scores" / "CF_2024-01-01_2024-01-02_multifactor_score_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_cli_daily_brief_inputs(tmp_path: Path) -> dict[str, Path]:
    quality_path = tmp_path / "quality" / "CF_2024-01-09_quality.csv"
    quality_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "severity": "CRITICAL",
                "check_id": "required_fields_not_null",
                "status": "PASS",
                "field_name": "settle",
                "contract_code": "",
                "observed_value": "",
                "threshold": "",
                "message": "settle is complete",
            }
        ]
    ).to_csv(quality_path, index=False)

    chain_path = _write_cli_chain_rows(tmp_path)
    trade_path = tmp_path / "mapping" / "CF_2024-01-09_2024-01-09_trade_mapping_daily.parquet"
    trade_rows = [
        CoreTradeMappingDailyRow(
            source_snapshot_id="trade_20240109",
            exchange="CZCE",
            product_code="CF",
            signal_object_id="CF.C1",
            trade_date=date(2024, 1, 9),
            execution_date=date(2024, 1, 10),
            target_contract="CF401",
            is_blocked=False,
            execution_eligible=True,
            mapping_rule_version="trade_mapping_fixture_v1",
        )
    ]
    pd.DataFrame([row.model_dump(mode="json") for row in trade_rows]).to_parquet(
        trade_path,
        index=False,
    )

    diagnostic_path = (
        tmp_path
        / "factors"
        / "CF_2024-01-09_2024-01-09_factor_diagnostic_daily.parquet"
    )
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_rows = [
        _cli_multifactor_diagnostic_row("mom_20_v1", date(2024, 1, 9), raw_value=0.4),
        _cli_multifactor_diagnostic_row("carry_nf_v1", date(2024, 1, 9), raw_value=0.2),
    ]
    pd.DataFrame([row.model_dump(mode="json") for row in diagnostic_rows]).to_parquet(
        diagnostic_path,
        index=False,
    )
    evaluation_path = (
        tmp_path
        / "backtests"
        / "CF_2024-01-09_2024-01-09_single_factor_evaluation.parquet"
    )
    evaluation_path.parent.mkdir(parents=True)
    evaluation_rows = [
        ResearchFactorEvaluationRow(
            run_id="r16_cli_eval",
            factor_id="mom_20_v1",
            factor_version="v1",
            product_code="CF",
            universe="CF_MAIN",
            horizon=1,
            metric_name="directional_accuracy",
            metric_value=1.0,
            observation_count=2,
            evaluation_rule_version="single_factor_eval_fixture_v1",
            input_snapshot_ids=["eval_snap"],
        )
    ]
    pd.DataFrame([row.model_dump(mode="json") for row in evaluation_rows]).to_parquet(
        evaluation_path,
        index=False,
    )

    score_path = tmp_path / "scores" / "CF_2024-01-09_2024-01-09_multifactor_score_daily.parquet"
    score_path.parent.mkdir(parents=True)
    score_rows = [_cli_multifactor_score_row(date(2024, 1, 9), raw_score=0.2)]
    pd.DataFrame([row.model_dump(mode="json") for row in score_rows]).to_parquet(
        score_path,
        index=False,
    )

    cost_path = tmp_path / "cost" / "CF_2024-01-09_2024-01-09_cost_sensitivity_summary.parquet"
    cost_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "r18_cli_cost",
                "scenario_id": "normal_cost",
                "product_code": "CF",
                "universe": "CF_MAIN",
                "signal_object_id": "CF.C1",
                "horizon": 1,
                "observation_count": 2,
                "signal_count": 2,
                "long_count": 1,
                "short_count": 1,
                "flat_count": 0,
                "round_turn_cost_bps": 5.0,
                "gross_mean_return": 0.01,
                "net_mean_return": 0.0095,
                "gross_hit_rate": 1.0,
                "net_hit_rate": 1.0,
                "average_abs_score": 0.2,
                "sensitivity_rule_version": "cost_sensitivity_round_turn_bps_v1",
                "input_snapshot_ids": "score_snap;return_snap",
            }
        ]
    ).to_parquet(cost_path, index=False)

    return {
        "quality": quality_path,
        "chain": chain_path,
        "trade": trade_path,
        "diagnostic": diagnostic_path,
        "evaluation": evaluation_path,
        "score": score_path,
        "cost": cost_path,
    }


def _cli_diagnostic_row(
    trade_date: date,
    *,
    raw_value: float,
) -> ResearchFactorDiagnosticDailyRow:
    return ResearchFactorDiagnosticDailyRow(
        run_id="r14_cli_diag",
        factor_id="mom_20_v1",
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        signal_state="long",
        diagnostic_reason="cli fixture",
        warning_flags=[],
        human_review_required=["factor_thresholds"],
        diagnostic_rule_version="r14_sign_state_heuristic_v1",
        input_snapshot_ids=[f"diag_{trade_date:%Y%m%d}"],
    )


def _cli_forward_return_row(
    trade_date: date,
    *,
    forward_return: float,
) -> ResearchForwardReturnDailyRow:
    return ResearchForwardReturnDailyRow(
        run_id="r15_cli_forward",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        execution_date=date(2024, 1, trade_date.day + 1),
        exit_date=date(2024, 1, trade_date.day + 2),
        horizon=1,
        target_contract="CF401",
        entry_price_field="settle",
        exit_price_field="settle",
        entry_price=100,
        exit_price=100 * (1 + forward_return),
        forward_return=forward_return,
        return_rule_version="forward_return_real_contract_tplus1_v1",
        input_snapshot_ids=[f"forward_{trade_date:%Y%m%d}"],
    )


def _cli_multifactor_diagnostic_row(
    factor_id: str,
    trade_date: date,
    *,
    raw_value: float,
) -> ResearchFactorDiagnosticDailyRow:
    return ResearchFactorDiagnosticDailyRow(
        run_id="r14_cli_diag",
        factor_id=factor_id,
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        signal_state="long",
        diagnostic_reason="cli multifactor fixture",
        warning_flags=[],
        human_review_required=["factor_thresholds"],
        diagnostic_rule_version="r14_sign_state_heuristic_v1",
        input_snapshot_ids=[f"{factor_id}_{trade_date:%Y%m%d}"],
    )


def _cli_multifactor_score_row(
    trade_date: date,
    *,
    raw_score: float,
) -> ResearchMultifactorScoreDailyRow:
    return ResearchMultifactorScoreDailyRow(
        run_id="r17_cli_score",
        score_id="cf_equal_weight_v1",
        score_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_score=raw_score,
        processed_score=None,
        factor_count=2,
        input_factor_ids=["mom_20_v1", "carry_nf_v1"],
        score_rule_version="equal_weight_multifactor_v1",
        input_snapshot_ids=[f"score_{trade_date:%Y%m%d}"],
    )
