from __future__ import annotations

import json
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


def _write_underlying_core_quotes(tmp_path: Path) -> Path:
    rows = [
        CoreQuoteDailyRow(
            source_snapshot_id="underlying_cf401",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date="2024-01-02",
            settle=14000,
            volume=100,
            open_interest=1000,
        )
    ]
    path = tmp_path / "core_quote" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path
