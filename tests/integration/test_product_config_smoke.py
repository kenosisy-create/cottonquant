from __future__ import annotations

from cotton_factor.smoke import run_product_config_smoke


def test_sr_ap_config_only_smoke_generates_contract_masters() -> None:
    result = run_product_config_smoke(product_codes=("SR", "AP"), year=2024)

    summary = result.to_summary()
    products = {item["product_code"]: item for item in summary["products"]}

    assert set(products) == {"SR", "AP"}
    assert products["SR"]["contract_codes"] == [
        "SR401",
        "SR403",
        "SR405",
        "SR407",
        "SR409",
        "SR411",
    ]
    assert products["AP"]["contract_codes"] == [
        "AP401",
        "AP403",
        "AP404",
        "AP405",
        "AP410",
        "AP411",
        "AP412",
    ]
    assert any("last_trade_day_rule requires human review" in item for item in result.warnings)
