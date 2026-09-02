from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]


def test_reproducible_runtime_contract_is_committed() -> None:
    runtime_file = PROJECT_ROOT / ".python-version"
    lock_file = PROJECT_ROOT / "uv.lock"

    assert runtime_file.read_text(encoding="utf-8").strip() == "3.12.10"
    lock_text = lock_file.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in lock_text
    assert 'name = "cotton-factor"' in lock_text


def test_optimization_contract_keeps_research_boundaries_visible() -> None:
    plan = (PROJECT_ROOT / "docs/PROJECT_OPTIMIZATION_PLAN_2026_08_26.md").read_text(
        encoding="utf-8"
    )
    retention = (PROJECT_ROOT / "docs/RESEARCH_ARTIFACT_RETENTION_POLICY.md").read_text(
        encoding="utf-8"
    )

    for marker in ("OPT-01", "OPT-02", "OPT-03", "OPT-04", "OPT-05", "OPT-06"):
        assert marker in plan
    assert "data/incoming" in plan
    assert "data/raw" in plan
    assert "不得因候选未通过而降低" in plan
    assert "UNKNOWN" in retention
    assert "--dry-run" in retention
