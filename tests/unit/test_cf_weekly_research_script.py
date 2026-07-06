from __future__ import annotations

from pathlib import Path


def test_update_cf_latest_research_has_weekly_pack_contract() -> None:
    script = Path("scripts/update_cf_latest_research.ps1").read_text(encoding="utf-8")

    assert "[switch]$RunWeeklyResearchPack" in script
    assert "$runHistoricalEvidenceEffective" in script
    assert "$runEventExplanationEffective" in script
    assert "$runEventThresholdSensitivityEffective" in script
    assert "$runValidatedBriefEffective" in script
    assert "$runPublishPackEffective" in script

    assert "--fundamental-context-path" in script
    assert "--event-detail-path" in script
    assert "build-cf-event-threshold-sensitivity" in script
    assert "--event-threshold-summary-path" in script
    assert "--fundamental-observation-json-path" in script

    assert "cf_weekly_research_run_manifest" in script
    assert "R58_cf_weekly_research_run_v1" in script
    assert "build-cf-weekly-research-audit" in script
    assert "reports\\research\\weekly_audit" in script
    assert "runs\\weekly\\CF" in script
    assert "latest_signal_only_contains_forward_return_validation" in script
    assert "historical_forward_returns_are_validation_labels" in script
    assert "fundamental_signal_status" in script


def test_readme_documents_weekly_pack_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "-RunWeeklyResearchPack" in readme
    assert "R41 -> R55 -> R60 -> R56 -> R57 -> R59" in readme
    assert "build-cf-event-threshold-sensitivity" in readme
    assert "build-cf-weekly-research-audit" in readme
    assert "weekly_research_run_manifest.json" in readme
