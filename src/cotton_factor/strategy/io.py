"""Shared typed IO helpers for V5.1 strategy workflows."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import TypeVar

import pandas as pd
from pydantic import BaseModel

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir
from cotton_factor.core.contract_master import load_product_config
from cotton_factor.core.schemas import CoreContractMasterRow, CoreQuoteDailyRow

ModelRow = TypeVar("ModelRow", bound=BaseModel)


def load_typed_parquet(path: Path, row_type: type[ModelRow]) -> list[ModelRow]:
    """Load a Parquet artifact through its Pydantic row contract."""
    if not path.exists() or not path.is_file():
        raise StrategyError(f"strategy input parquet not found: {path}")
    frame = pd.read_parquet(path)
    rows: list[ModelRow] = []
    for record in frame.to_dict(orient="records"):
        rows.append(row_type.model_validate(_clean_record(record)))
    if not rows:
        raise StrategyError(f"strategy input parquet contains no rows: {path}")
    return rows


def load_core_quotes(path: Path) -> list[CoreQuoteDailyRow]:
    """Load normalized CF quotes for execution and marking."""
    rows = load_typed_parquet(path, CoreQuoteDailyRow)
    selected = [row for row in rows if row.product_code == "CF"]
    if not selected:
        raise StrategyError(f"core quote parquet contains no CF rows: {path}")
    return sorted(selected, key=lambda row: (row.trade_date, row.contract_code))


def engine_contracts_from_quotes(
    quotes: list[CoreQuoteDailyRow],
) -> list[CoreContractMasterRow]:
    """Build the multiplier rows required by the existing accounting engine."""
    config = load_product_config("CF")
    if not isinstance(config.multiplier, int | float):
        raise StrategyError("CF multiplier is not confirmed in product config")
    contracts: list[CoreContractMasterRow] = []
    first_quote_by_code: dict[str, CoreQuoteDailyRow] = {}
    for quote in quotes:
        first_quote_by_code.setdefault(quote.contract_code, quote)
    for contract_code, quote in sorted(first_quote_by_code.items()):
        delivery_year, delivery_month = infer_cf_delivery(contract_code, quote.trade_date)
        contracts.append(
            CoreContractMasterRow(
                exchange="CZCE",
                product_code="CF",
                contract_code=contract_code,
                contract_month=f"{delivery_year}{delivery_month:02d}",
                delivery_year=delivery_year,
                delivery_month=delivery_month,
                multiplier=float(config.multiplier),
                tick_size=None,
                first_trade_date=None,
                last_trade_date=None,
                rule_version_id=config.rule_version_id,
                source_config_version=config.source_config_version,
            )
        )
    return contracts


def infer_cf_delivery(contract_code: str, trade_date: date) -> tuple[int, int]:
    """Infer CZCE CF delivery year/month within the local historical decade."""
    match = re.fullmatch(r"CF([0-9])([0-9]{2})", contract_code.upper())
    if match is None:
        raise StrategyError(f"unsupported CF contract code: {contract_code}")
    year_digit = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise StrategyError(f"invalid CF delivery month: {contract_code}")
    candidates = [
        year
        for year in range(trade_date.year - 1, trade_date.year + 3)
        if year % 10 == year_digit
    ]
    non_past = [year for year in candidates if year >= trade_date.year]
    if not candidates:
        raise StrategyError(f"cannot infer CF delivery year: {contract_code}")
    return (min(non_past) if non_past else max(candidates), month)


def latest_strategy_input_paths(input_dir: Path | None = None) -> dict[str, Path]:
    """Resolve one internally consistent latest R86 input bundle."""
    root = input_dir or data_dir() / "strategy" / "CF" / "inputs"
    manifests = sorted(root.glob("CF_*_strategy_input_manifest.json"))
    if not manifests:
        raise StrategyError(f"no strategy input manifest found under {root}")
    manifest = manifests[-1]
    stem = manifest.name.removesuffix("_strategy_input_manifest.json")
    paths = {
        "manifest": manifest,
        "chain": root / f"{stem}_chain_map_daily.parquet",
        "trade": root / f"{stem}_trade_mapping_daily.parquet",
        "continuous": root / f"{stem}_continuous_price_daily.parquet",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise StrategyError(f"latest strategy input bundle is incomplete: {missing}")
    return paths


def default_core_quote_path() -> Path:
    """Return the normalized CF quote path."""
    return data_dir() / "core" / "CF" / "core_quote_daily.parquet"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, float) and pd.isna(value):
            cleaned[key] = None
        elif hasattr(value, "tolist") and not isinstance(value, str):
            cleaned[key] = value.tolist()
        else:
            cleaned[key] = value
    return cleaned
