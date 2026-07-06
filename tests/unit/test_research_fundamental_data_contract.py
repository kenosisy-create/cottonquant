from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_fundamental_data_contract


def test_build_cf_fundamental_data_contract_missing_inputs_writes_artifacts(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "fundamentals" / "manual"

    result = build_cf_fundamental_data_contract(
        source_dir=source_dir,
        output_dir=tmp_path / "research" / "fundamentals",
        report_output_dir=tmp_path / "reports",
        run_id="r51_unit_missing",
    )

    assert result.status == "MISSING_FUNDAMENTAL_INPUT"
    assert result.passed is True
    assert result.incoming_dir.exists()
    assert result.incoming_file_count == 0
    assert len(result.dataset_contracts) == 5
    assert result.warnings[0].warning_code == "MISSING_FUNDAMENTAL_INPUT"
    assert result.to_summary()["fundamental_signal_status"] == "not_connected"

    schema = json.loads(result.schema_json_path.read_text(encoding="utf-8"))
    dataset_types = {dataset["dataset_type"] for dataset in schema["datasets"]}
    assert dataset_types == {
        "warehouse_receipt",
        "basis",
        "inventory",
        "import",
        "textile_chain",
    }
    assert schema["fundamental_signal_status"] == "not_connected"

    template_csv = result.template_csv_path.read_text(encoding="utf-8")
    assert "dataset_type" in template_csv
    assert "required_columns" in template_csv
    assert "warehouse_receipt" in template_csv

    warning_csv = result.warning_csv_path.read_text(encoding="utf-8")
    assert "MISSING_FUNDAMENTAL_INPUT" in warning_csv
    assert "FUNDAMENTAL_SIGNAL_NOT_CONNECTED" in warning_csv

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 基本面数据接口占位 R51" in markdown
    assert "当前不接入 signal matrix" in markdown
    assert "本报告不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "MISSING_FUNDAMENTAL_INPUT"
    assert manifest["fundamental_signal_status"] == "not_connected"


def test_build_cf_fundamental_data_contract_detects_present_files_without_parsing(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming" / "CF" / "fundamentals" / "manual"
    source_dir.mkdir(parents=True)
    (source_dir / "CF_basis_manual.xlsx").write_bytes(b"not a real excel file")

    result = build_cf_fundamental_data_contract(
        source_dir=source_dir,
        output_dir=tmp_path / "research" / "fundamentals",
        report_output_dir=tmp_path / "reports",
        run_id="r51_unit_present",
    )

    assert result.status == "FUNDAMENTAL_INPUT_PRESENT_CONTRACT_ONLY"
    assert result.incoming_file_count == 1
    assert result.warnings[0].warning_code == "FUNDAMENTAL_INPUT_PRESENT_NOT_PARSED"
    assert result.to_summary()["fundamental_signal_status"] == "not_connected"


def test_cli_build_cf_fundamental_data_contract(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-fundamental-data-contract",
            "--source-dir",
            str(tmp_path / "incoming" / "CF" / "fundamentals" / "manual"),
            "--output-dir",
            str(tmp_path / "research" / "fundamentals"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r51_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r51_cli"
    assert output["status"] == "MISSING_FUNDAMENTAL_INPUT"
    assert output["warnings"][0]["warning_code"] == "MISSING_FUNDAMENTAL_INPUT"
    assert output["fundamental_signal_status"] == "not_connected"
    assert Path(output["schema_json_path"]).exists()
    assert Path(output["template_csv_path"]).exists()
    assert Path(output["markdown_path"]).exists()
