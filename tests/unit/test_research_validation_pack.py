from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_post_r22_validation_pack


def test_build_cf_post_r22_validation_pack_writes_evidence(tmp_path: Path) -> None:
    result = build_cf_post_r22_validation_pack(
        trade_date=date(2024, 1, 31),
        start=date(2024, 1, 22),
        end=date(2024, 1, 31),
        output_root=tmp_path,
        run_id="post_r22_validation_test",
        horizons=(1,),
        lookback_periods=3,
    )

    assert result.passed is True
    assert result.status == "PASSED_WITH_HUMAN_REVIEW"
    assert result.input_path.exists()
    assert result.preloaded_core_quote_path.exists()
    assert result.pipeline_json_path.exists()
    assert result.replay_json_path.exists()
    assert result.expansion_gate_json_path.exists()
    assert result.summary_json_path.exists()
    assert "real_cf_data_source_permission" in result.human_review_required

    payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert Path(payload["pipeline_json_path"]).exists()


def test_cli_research_run_cf_validation_pack(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "research",
            "run-cf-validation-pack",
            "--date",
            "2024-01-31",
            "--start",
            "2024-01-22",
            "--end",
            "2024-01-31",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "post_r22_cli_validation",
            "--horizons",
            "1",
            "--lookback-periods",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["passed"] is True
    assert output["status"] == "PASSED_WITH_HUMAN_REVIEW"
    assert Path(output["summary_markdown_path"]).exists()
