from __future__ import annotations

import json
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import UATError
from cotton_factor.uat import run_uat_replay


def test_uat_replay_runs_cf_mvp_fixture_and_writes_reports(tmp_path: Path) -> None:
    result = run_uat_replay(
        scenario="cf_mvp_fixture",
        output_root=tmp_path / "uat",
        run_id="d22_uat_replay_test",
    )

    assert result.passed is True
    assert result.json_report_path.exists()
    assert result.html_report_path.exists()
    assert result.smoke_archive_dir.exists()
    assert all(check.passed for check in result.checks)

    payload = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    assert payload["scenario"] == "cf_mvp_fixture"
    assert payload["passed"] is True
    assert payload["failed_checks"] == []
    assert {check["name"] for check in payload["checks"]} >= {
        "cf_smoke_completed",
        "golden_row_counts_match",
        "golden_warnings_match",
        "human_review_cost_warnings_present",
    }

    html = result.html_report_path.read_text(encoding="utf-8")
    assert "D22 UAT Replay Report" in html
    assert "Overall: PASS" in html
    assert "TODO_REQUIRES_HUMAN_REVIEW: fee uses D16 placeholder cost" in html


def test_uat_replay_rejects_unknown_scenario(tmp_path: Path) -> None:
    with pytest.raises(UATError):
        run_uat_replay(
            scenario="unknown",
            output_root=tmp_path / "uat",
            run_id="d22_unknown_scenario_test",
        )
