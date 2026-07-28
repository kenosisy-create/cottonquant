from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.strategy import load_strategy_registry, load_strategy_spec


def test_default_strategy_registry_loads_baseline_candidate_and_overlays() -> None:
    registry = load_strategy_registry()

    assert registry.product_scope == "CF_ONLY"
    assert [spec.strategy_id for spec in registry.specs] == [
        "CF_tsmom",
        "CF_phase_gated",
        "ovl_option_veto",
        "ovl_member_position",
        "ovl_strike_wall",
    ]
    assert registry.find("CF_tsmom/v0").status == "baseline"
    assert registry.find("CF_phase_gated").signal_horizon == 20
    assert registry.find("ovl_option_veto").status == "frozen"


def test_strategy_spec_recursively_rejects_forward_inputs(tmp_path: Path) -> None:
    source = Path("configs/strategy/CF_tsmom_v0.yaml")
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["data_dependencies"].append("data/research/CF/forward_return_daily.parquet")
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    with pytest.raises(StrategyError, match="forbidden inputs"):
        load_strategy_spec(path)


def test_strategy_registry_rejects_duplicate_strategy_version(tmp_path: Path) -> None:
    spec_path = Path("configs/strategy/CF_tsmom_v0.yaml").resolve()
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "registry_version": "test",
                "product_scope": "CF_ONLY",
                "entries": [
                    {"spec_path": str(spec_path), "enabled": True},
                    {"spec_path": str(spec_path), "enabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StrategyError, match="duplicate strategy spec key"):
        load_strategy_registry(registry_path)
