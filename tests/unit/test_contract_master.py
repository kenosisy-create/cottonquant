from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import ConfigError
from cotton_factor.core import build_contract_master, load_all_product_configs, load_product_config


def test_all_product_configs_parse_and_expose_human_review_todos() -> None:
    configs = {config.product_code: config for config in load_all_product_configs()}

    assert {"CF", "SR", "AP", "M", "C", "Y"} == set(configs)
    assert configs["CF"].is_generation_ready() is True
    assert configs["SR"].is_generation_ready() is True
    assert configs["AP"].is_generation_ready() is True
    assert "tick_size" in configs["CF"].human_review_required
    assert "option_style" in configs["CF"].human_review_required


def test_cf_contract_master_generates_delivery_month_contracts() -> None:
    result = build_contract_master(product_code="CF", year=2024)

    assert result.rule_version.rule_version_id == "CZCE.CF.contract_rules.v1"
    assert result.rule_version.delivery_months == [1, 3, 5, 7, 9, 11]
    assert [contract.contract_code for contract in result.contracts] == [
        "CF401",
        "CF403",
        "CF405",
        "CF407",
        "CF409",
        "CF411",
    ]
    assert [contract.contract_month for contract in result.contracts] == [
        "202401",
        "202403",
        "202405",
        "202407",
        "202409",
        "202411",
    ]
    assert all(contract.multiplier == 5 for contract in result.contracts)
    assert all(contract.tick_size is None for contract in result.contracts)
    assert all(contract.last_trade_date is None for contract in result.contracts)
    assert "tick_size is TODO_REQUIRES_HUMAN_REVIEW; emitted as null" in result.warnings


def test_cf_contract_master_can_use_supplied_trading_dates_for_ltd() -> None:
    trading_dates = [
        date(2024, month, day)
        for month in (1, 3, 5, 7, 9, 11)
        for day in range(1, 16)
    ]
    result = build_contract_master(
        product_code="CF",
        year=2024,
        trading_dates=trading_dates,
    )

    january_contract = result.contracts[0]
    assert january_contract.contract_code == "CF401"
    assert january_contract.last_trade_date == date(2024, 1, 10)


def test_sr_and_ap_configs_generate_contract_master_by_config_only() -> None:
    expectations = {
        "SR": ["SR401", "SR403", "SR405", "SR407", "SR409", "SR411"],
        "AP": ["AP401", "AP403", "AP404", "AP405", "AP410", "AP411", "AP412"],
    }
    for product_code, expected_contracts in expectations.items():
        config = load_product_config(product_code)
        assert config.status == "config_smoke_only"
        assert config.is_generation_ready() is True

        result = build_contract_master(product_code=product_code, year=2024)

        assert [contract.contract_code for contract in result.contracts] == expected_contracts
        assert all(contract.multiplier == 10 for contract in result.contracts)
        assert all(contract.tick_size == 1 for contract in result.contracts)
        assert f"CZCE.{product_code}.contract_rules.v1" == result.rule_version.rule_version_id
        assert "last_trade_day_rule requires human review before production use" in result.warnings


def test_product_config_requires_todo_fields_in_human_review_list(tmp_path: Path) -> None:
    config_dir = tmp_path / "products"
    config_dir.mkdir()
    (config_dir / "XX.yaml").write_text(
        "\n".join(
            [
                "product_code: XX",
                "display_name: Bad config",
                "exchange: CZCE",
                "instrument_type: futures",
                "status: config_test",
                "currency: CNY",
                "multiplier: 1",
                "tick_size: TODO_REQUIRES_HUMAN_REVIEW",
                "delivery_months: [1]",
                "last_trade_day_rule: delivery_month_10th_trading_day",
                "option_style: TODO_REQUIRES_HUMAN_REVIEW",
                "human_review_required:",
                "  - option_style",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="tick_size"):
        load_product_config("XX", config_dir)
