"""Config-only product extension smoke checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cotton_factor.common.exceptions import SmokeError
from cotton_factor.core import build_contract_master, build_trading_calendar

DEFAULT_EXTENSION_PRODUCTS = ("SR", "AP")


@dataclass(frozen=True)
class ProductConfigSmokeItem:
    """One product config-only smoke result."""

    product_code: str
    exchange: str
    contract_count: int
    contract_codes: list[str]
    rule_version_id: str
    warnings: list[str]


@dataclass(frozen=True)
class ProductConfigSmokeResult:
    """Config-only extension smoke result."""

    year: int
    products: list[ProductConfigSmokeItem]
    warnings: list[str]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable summary for CLI output."""
        return {
            "year": self.year,
            "products": [
                {
                    "product_code": item.product_code,
                    "exchange": item.exchange,
                    "contract_count": item.contract_count,
                    "contract_codes": item.contract_codes,
                    "rule_version_id": item.rule_version_id,
                    "warnings": item.warnings,
                }
                for item in self.products
            ],
            "warnings": self.warnings,
        }


def run_product_config_smoke(
    *,
    product_codes: tuple[str, ...] = DEFAULT_EXTENSION_PRODUCTS,
    year: int = 2024,
) -> ProductConfigSmokeResult:
    """Run config-only smoke for products beyond CF without data ingestion."""
    if not product_codes:
        raise SmokeError("product config smoke requires at least one product")
    if year < 1990 or year > 2100:
        raise SmokeError(f"year out of supported range: {year}")

    calendar_result = build_trading_calendar(
        start=date(year, 1, 1),
        end=date(year, 12, 31),
        exchange="CZCE",
    )
    items: list[ProductConfigSmokeItem] = []
    warnings: list[str] = list(calendar_result.warnings)
    for product_code in product_codes:
        normalized_product = product_code.strip().upper()
        if not normalized_product:
            raise SmokeError("product code must be non-empty")

        # D20 只验证“配置驱动合约主数据”；不接入 SR/AP 行情，也不触发研究/交易链路。
        result = build_contract_master(
            product_code=normalized_product,
            year=year,
            trading_dates=calendar_result.calendar.trading_dates,
        )
        item = ProductConfigSmokeItem(
            product_code=result.product_config.product_code,
            exchange=result.product_config.exchange,
            contract_count=len(result.contracts),
            contract_codes=[contract.contract_code for contract in result.contracts],
            rule_version_id=result.rule_version.rule_version_id,
            warnings=result.warnings,
        )
        if item.contract_count == 0:
            raise SmokeError(f"{normalized_product}: contract master produced no rows")
        items.append(item)
        warnings.extend(f"{item.product_code}: {warning}" for warning in item.warnings)

    return ProductConfigSmokeResult(
        year=year,
        products=items,
        warnings=_unique_warnings(warnings),
    )


def _unique_warnings(warnings: list[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values
