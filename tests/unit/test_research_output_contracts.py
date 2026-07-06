from __future__ import annotations

import json
from pathlib import Path

from cotton_factor.research_workbench import (
    build_cf_factor_output_contract,
    factor_output_artifact_contracts,
)


def test_factor_output_artifact_contracts_define_r11_to_r14_outputs() -> None:
    artifacts = factor_output_artifact_contracts()
    by_id = {artifact.artifact_id: artifact for artifact in artifacts}

    assert set(by_id) == {
        "cf_factor_value_daily",
        "cf_factor_diagnostic_daily",
        "cf_factor_diagnostic_report",
        "cf_factor_warning_log",
    }
    assert by_id["cf_factor_value_daily"].schema["table_name"] == (
        "research_factor_value_daily"
    )
    assert by_id["cf_factor_diagnostic_daily"].schema["table_name"] == (
        "research_factor_diagnostic_daily"
    )
    assert "signal_state" in by_id["cf_factor_diagnostic_daily"].schema["all_fields"]
    assert by_id["cf_factor_warning_log"].fields == (
        "run_id",
        "factor_id",
        "trade_date",
        "severity",
        "warning_code",
        "warning_message",
        "human_review_required",
        "input_snapshot_ids",
    )


def test_build_cf_factor_output_contract_writes_json_and_markdown(tmp_path: Path) -> None:
    result = build_cf_factor_output_contract(
        output_dir=tmp_path / "contracts",
        report_output_dir=tmp_path / "reports",
    )

    assert result.contract_version == "R10.factor_diagnostics_output_contract.v1"
    assert result.factor_ids == (
        "mom_20_v1",
        "carry_nf_v1",
        "curve_slope_v1",
        "oi_pressure_v1",
    )
    assert result.signal_states == ("long", "short", "neutral", "unknown")
    assert result.json_path.exists()
    assert result.markdown_path.exists()

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["contract_version"] == result.contract_version
    assert payload["artifacts"][1]["table_name"] == "research_factor_diagnostic_daily"
    assert "Missing inputs must surface" in "\n".join(payload["research_rules"])
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF Factor Diagnostic Output Contract" in markdown
    assert "HUMAN_REVIEW_REQUIRED" in markdown
