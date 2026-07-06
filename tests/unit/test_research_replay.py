from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import replay_cf_research_pipeline_outputs


def test_replay_cf_research_pipeline_outputs_writes_fingerprints(tmp_path: Path) -> None:
    pipeline_json = _write_fake_pipeline_log(tmp_path)

    result = replay_cf_research_pipeline_outputs(
        pipeline_json_path=pipeline_json,
        report_output_dir=tmp_path / "replay",
        run_id="r21_replay_test",
    )

    assert result.passed is True
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.pipeline_status == "COMPLETED"
    assert {artifact.row_count for artifact in result.artifacts if artifact.row_count} >= {1, 2}

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["failed_checks"] == []
    assert len(payload["artifact_fingerprints"]) == 4


def test_replay_cf_research_pipeline_outputs_detects_baseline_change(tmp_path: Path) -> None:
    pipeline_json = _write_fake_pipeline_log(tmp_path)
    baseline = replay_cf_research_pipeline_outputs(
        pipeline_json_path=pipeline_json,
        report_output_dir=tmp_path / "replay",
        run_id="r21_replay_baseline",
    )
    (tmp_path / "artifacts" / "brief.md").write_text("changed\n", encoding="utf-8")

    result = replay_cf_research_pipeline_outputs(
        pipeline_json_path=pipeline_json,
        baseline_json_path=baseline.json_path,
        report_output_dir=tmp_path / "replay",
        run_id="r21_replay_changed",
    )

    assert result.passed is False
    failed = {check.check_id for check in result.checks if not check.passed}
    assert "baseline_artifacts_match" in failed


def test_cli_research_replay_cf_daily_pipeline(tmp_path: Path) -> None:
    pipeline_json = _write_fake_pipeline_log(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "replay-cf-daily-pipeline",
            "--pipeline-json-path",
            str(pipeline_json),
            "--report-output-dir",
            str(tmp_path / "replay"),
            "--run-id",
            "r21_cli_replay",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["passed"] is True
    assert output["artifact_count"] == 4
    assert Path(output["json_path"]).exists()


def _write_fake_pipeline_log(tmp_path: Path) -> Path:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True)
    parquet_path = artifact_dir / "factor.parquet"
    pd.DataFrame([{"trade_date": "2024-01-10", "value": 1.0}]).to_parquet(
        parquet_path,
        index=False,
    )
    csv_path = artifact_dir / "quality.csv"
    pd.DataFrame(
        [
            {"check_id": "required_fields", "status": "PASS"},
            {"check_id": "calendar", "status": "PASS"},
        ]
    ).to_csv(csv_path, index=False)
    brief_path = artifact_dir / "brief.md"
    brief_path.write_text("# brief\n", encoding="utf-8")
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps({"steps": [{"step_id": "fake"}]}), encoding="utf-8")

    pipeline_json = tmp_path / "pipeline.json"
    pipeline_json.write_text(
        json.dumps(
            {
                "run_id": "r20_fake",
                "trade_date": "2024-01-10",
                "start": "2024-01-09",
                "end": "2024-01-12",
                "status": "COMPLETED",
                "artifacts": {
                    "factor.factor_parquet_path": str(parquet_path),
                    "quality.csv_path": str(csv_path),
                    "brief.markdown_path": str(brief_path),
                    "brief.json_path": str(summary_path),
                },
                "human_review_required": ["factor_thresholds"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return pipeline_json
