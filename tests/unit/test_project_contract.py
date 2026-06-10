from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_d0_required_paths_exist() -> None:
    required_paths = [
        "AGENTS.md",
        "VERSION",
        "CHANGELOG.md",
        "pyproject.toml",
        "README.md",
        "Makefile",
        "docs/ARCHITECTURE.md",
        "docs/TASK_BREAKDOWN.md",
        "docs/RELEASE_CHECKLIST.md",
        "docs/FIELD_DICTIONARY.md",
        "docs/TRADING_CALENDAR.md",
        "docs/CHAIN_MAP.md",
        "prompts/MASTER_ORCHESTRATOR.md",
        "prompts/D0_bootstrap.md",
        "configs/data_sources.yaml",
        "configs/factor_registry.yaml",
        "configs/backtest.yaml",
        "configs/cost_model.yaml",
        "configs/roll_rules.yaml",
        "src/cotton_factor/cli/main.py",
        ".codex/agents/data_ingest.toml",
        ".codex/agents/qa_ci.toml",
    ]

    missing = [path for path in required_paths if not (REPO_ROOT / path).exists()]

    assert missing == []


def test_product_configs_exist() -> None:
    expected_products = {"CF", "SR", "AP", "M", "C", "Y"}
    product_dir = REPO_ROOT / "configs" / "products"
    actual_products = {path.stem for path in product_dir.glob("*.yaml")}

    assert expected_products <= actual_products


def test_architecture_rules_are_documented() -> None:
    agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Raw snapshots are immutable" in agents_text
    assert "Continuous contracts are signal objects only" in agents_text
    assert "execute on T+1" in agents_text
    assert "TODO_REQUIRES_HUMAN_REVIEW" in agents_text
