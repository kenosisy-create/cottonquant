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
        "docs/PROJECT_DIRECTION.md",
        "docs/CURRENT_STATE_RESEARCH_MAP.md",
        "docs/RESEARCH_WORKBENCH_ROADMAP.md",
        "docs/DATA_SOURCES_CF_RESEARCH.md",
        "docs/FIELD_MAPPING_CF_RESEARCH.md",
        "docs/DATA_QUALITY_RULES_CF.md",
        "docs/CF_CONTRACT_RULE_REVIEW.md",
        "docs/RESEARCH_MAPPING.md",
        "docs/RESEARCH_CONTINUOUS_PRICE.md",
        "docs/RESEARCH_OUTPUT_CONTRACTS.md",
        "docs/RESEARCH_MOMENTUM_FACTOR.md",
        "docs/RESEARCH_CARRY_FACTOR.md",
        "docs/RESEARCH_STRUCTURE_FACTORS.md",
        "docs/RESEARCH_FACTOR_DIAGNOSTICS.md",
        "docs/RESEARCH_FORWARD_RETURNS.md",
        "docs/RESEARCH_SINGLE_FACTOR_BACKTESTS.md",
        "docs/RESEARCH_MULTIFACTOR_DIAGNOSTICS.md",
        "docs/RESEARCH_COST_SENSITIVITY.md",
        "docs/RESEARCH_DAILY_BRIEF.md",
        "docs/RELEASE_CHECKLIST.md",
        "docs/FIELD_DICTIONARY.md",
        "docs/TRADING_CALENDAR.md",
        "docs/CHAIN_MAP.md",
        "prompts/MASTER_ORCHESTRATOR.md",
        "prompts/MASTER_RESEARCH_WORKBENCH.md",
        "prompts/D0_bootstrap.md",
        "prompts/R00_scope_lock.md",
        "prompts/R01_repo_audit.md",
        "prompts/R02_research_mode_config.md",
        "configs/data_sources.yaml",
        "configs/research_mode.yaml",
        "configs/data_sources_cf_research.yaml",
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

    assert "research-grade production data" in agents_text
    assert "workbench" in agents_text
    assert "Engineering serves research" in agents_text
    assert "Continuous contracts are signal objects only" in agents_text
    assert "execute no earlier than T+1" in agents_text
    assert "HUMAN_REVIEW_REQUIRED" in agents_text
