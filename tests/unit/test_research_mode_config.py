from __future__ import annotations

from pathlib import Path

import pytest

from cotton_factor.common.exceptions import ConfigError
from cotton_factor.research_workbench import load_research_mode_config


def test_load_research_mode_config_defaults_to_cf_daily_workbench() -> None:
    config = load_research_mode_config()

    assert config.product == "CF"
    assert config.exchange == "CZCE"
    assert config.frequency == "daily"
    assert config.data_input_dir == Path("data/incoming/CF")
    assert config.report_output_dir == Path("reports/daily")
    assert config.execution_rule == "T_SIGNAL_T_PLUS_1_EXECUTION"
    assert config.active_factors == ("momentum", "carry", "curve_slope", "oi_pressure")
    assert "release_freeze" in config.platform_features_paused
    assert "sr_ap_production_ingest" in config.platform_features_paused


def test_research_mode_config_rejects_unknown_product(tmp_path: Path) -> None:
    config_path = tmp_path / "research_mode.yaml"
    config_path.write_text(
        "\n".join(
            [
                "product: SR",
                "exchange: CZCE",
                "frequency: daily",
                "data_input_dir: data/incoming/SR",
                "raw_output_dir: data/raw",
                "core_output_dir: data/core",
                "research_output_dir: data/research",
                "report_output_dir: reports/daily",
                "active_factors:",
                "  - momentum",
                "  - carry",
                "  - curve_slope",
                "  - oi_pressure",
                "cost_scenarios:",
                "  - no_cost",
                "execution_rule: T_SIGNAL_T_PLUS_1_EXECUTION",
                "platform_features_paused:",
                "  - release_freeze",
                "  - gray_deployment",
                "  - full_ci_cd",
                "  - oms_integration",
                "  - minute_execution",
                "  - sr_ap_production_ingest",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="unsupported research product"):
        load_research_mode_config(config_path)

    config = load_research_mode_config(config_path, allow_unknown_product=True)
    assert config.product == "SR"


def test_research_mode_config_requires_paused_platform_features(tmp_path: Path) -> None:
    config_path = tmp_path / "research_mode.yaml"
    config_path.write_text(
        "\n".join(
            [
                "product: CF",
                "exchange: CZCE",
                "frequency: daily",
                "data_input_dir: data/incoming/CF",
                "raw_output_dir: data/raw",
                "core_output_dir: data/core",
                "research_output_dir: data/research",
                "report_output_dir: reports/daily",
                "active_factors:",
                "  - momentum",
                "  - carry",
                "  - curve_slope",
                "  - oi_pressure",
                "cost_scenarios:",
                "  - no_cost",
                "execution_rule: T_SIGNAL_T_PLUS_1_EXECUTION",
                "platform_features_paused:",
                "  - release_freeze",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="missing paused platform features"):
        load_research_mode_config(config_path)
