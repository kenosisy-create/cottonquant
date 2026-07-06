"""Research contract-universe helpers for CF daily workbench tasks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cotton_factor.common.exceptions import (
    ConfigError,
    ContractMasterError,
    ResearchWorkbenchError,
    TradingCalendarError,
)
from cotton_factor.core import build_contract_master, build_trading_calendar
from cotton_factor.core.contract_master import (
    TODO_REQUIRES_HUMAN_REVIEW,
    load_product_config,
)
from cotton_factor.core.schemas import CoreContractMasterRow, CoreQuoteDailyRow
from cotton_factor.core.trading_calendar import TradingCalendar, official_calendar_path


@dataclass(frozen=True)
class ResearchContractUniverseBuildResult:
    """Contract rows and calendar used by one research workbench window."""

    calendar: TradingCalendar
    contracts: tuple[CoreContractMasterRow, ...]
    warnings: tuple[str, ...]
    delivery_years: tuple[int, ...]


def build_research_contract_universe(
    *,
    start: date,
    product_code: str,
    exchange: str,
    quotes: Sequence[CoreQuoteDailyRow],
    calendar_path: Path | None,
    context_name: str,
) -> ResearchContractUniverseBuildResult:
    """Build contract rows for all delivery years visible in a research window."""
    product = product_code.upper()
    resolved_calendar_path = calendar_path or official_calendar_path(
        exchange=exchange,
        year=start.year,
    )
    if not resolved_calendar_path.exists():
        raise ResearchWorkbenchError(
            f"official calendar is required for {context_name}: {resolved_calendar_path}"
        )

    try:
        primary_calendar_result = build_trading_calendar(
            start=date(start.year, 1, 1),
            end=date(start.year, 12, 31),
            exchange=exchange,
            fixture_path=resolved_calendar_path,
        )
        delivery_years = _delivery_years_from_quotes(
            product_code=product,
            base_year=start.year,
            quotes=quotes,
        )
        contract_rows: list[CoreContractMasterRow] = []
        warnings: list[str] = list(primary_calendar_result.warnings)
        for delivery_year in delivery_years:
            # 研究窗口按交易年运行，但年末主力可能已经切到次年交割合约。
            # 若对应交割年已有官方/可追溯日历，就用于 LTD；没有时才显式留空并提示复核。
            delivery_trading_dates, delivery_warnings = _delivery_trading_dates(
                delivery_year=delivery_year,
                start_year=start.year,
                exchange=exchange,
                primary_calendar=primary_calendar_result.calendar,
                context_name=context_name,
            )
            warnings.extend(delivery_warnings)
            contracts, contract_warnings = _build_contract_rows_for_research_year(
                product_code=product,
                delivery_year=delivery_year,
                trading_dates=delivery_trading_dates,
                context_name=context_name,
            )
            contract_rows.extend(contracts)
            warnings.extend(contract_warnings)
            if delivery_year != start.year and delivery_trading_dates is None:
                warnings.append(
                    "HUMAN_REVIEW_REQUIRED: "
                    f"{context_name} generated {product} {delivery_year} contract master "
                    f"without official {delivery_year} calendar; last_trade_date omitted "
                    "for cross-year research coverage"
                )
    except (ConfigError, ContractMasterError, TradingCalendarError) as exc:
        raise ResearchWorkbenchError(f"cannot build {context_name} contract master: {exc}") from exc

    return ResearchContractUniverseBuildResult(
        calendar=primary_calendar_result.calendar,
        contracts=tuple(contract_rows),
        warnings=tuple(sorted(set(warnings))),
        delivery_years=delivery_years,
    )


def _build_contract_rows_for_research_year(
    *,
    product_code: str,
    delivery_year: int,
    trading_dates: tuple[date, ...] | None,
    context_name: str,
) -> tuple[tuple[CoreContractMasterRow, ...], tuple[str, ...]]:
    try:
        contract_result = build_contract_master(
            product_code=product_code,
            year=delivery_year,
            trading_dates=trading_dates,
        )
    except ContractMasterError as exc:
        if trading_dates is None:
            raise
        return _partial_calendar_contract_rows(
            product_code=product_code,
            delivery_year=delivery_year,
            trading_dates=trading_dates,
            context_name=context_name,
            build_error=exc,
        )
    return tuple(contract_result.contracts), tuple(contract_result.warnings)


def _partial_calendar_contract_rows(
    *,
    product_code: str,
    delivery_year: int,
    trading_dates: tuple[date, ...],
    context_name: str,
    build_error: ContractMasterError,
) -> tuple[tuple[CoreContractMasterRow, ...], tuple[str, ...]]:
    config = load_product_config(product_code)
    if config.last_trade_day_rule != "delivery_month_10th_trading_day":
        raise build_error
    if config.contract_code_format != "czce_yymm_last_digit":
        raise build_error
    if not isinstance(config.delivery_months, list) or not isinstance(
        config.multiplier,
        int | float,
    ):
        raise build_error

    # 研究窗口允许使用“截至当前”的官方日历，但不能推测未来交割月的最后交易日。
    contracts: list[CoreContractMasterRow] = []
    missing_months: list[str] = []
    for month in config.delivery_months:
        month_dates = sorted(
            trade_date
            for trade_date in trading_dates
            if trade_date.year == delivery_year and trade_date.month == month
        )
        last_trade_date = month_dates[9] if len(month_dates) >= 10 else None
        if last_trade_date is None:
            missing_months.append(f"{delivery_year}-{month:02d}")
        contracts.append(
            CoreContractMasterRow(
                exchange=config.exchange,
                product_code=config.product_code,
                contract_code=f"{config.product_code}{delivery_year % 10}{month:02d}",
                contract_month=f"{delivery_year}{month:02d}",
                delivery_year=delivery_year,
                delivery_month=month,
                instrument_type="futures",
                multiplier=float(config.multiplier),
                tick_size=_optional_float(config.tick_size),
                first_trade_date=None,
                last_trade_date=last_trade_date,
                rule_version_id=config.rule_version_id,
                source_config_version=config.source_config_version,
            )
        )

    warnings = [
        "HUMAN_REVIEW_REQUIRED: "
        f"{context_name} used partial official calendar for {product_code} "
        f"{delivery_year}; last_trade_date omitted for delivery months: "
        + ", ".join(missing_months)
    ]
    if "last_trade_day_rule" in config.human_review_required:
        warnings.append("last_trade_day_rule requires human review before production use")
    if config.tick_size == TODO_REQUIRES_HUMAN_REVIEW:
        warnings.append("tick_size is TODO_REQUIRES_HUMAN_REVIEW; emitted as null")
    warnings.extend(
        f"{field_name} requires human review" for field_name in config.human_review_required
    )
    return tuple(contracts), tuple(sorted(set(warnings)))


def _delivery_trading_dates(
    *,
    delivery_year: int,
    start_year: int,
    exchange: str,
    primary_calendar: TradingCalendar,
    context_name: str,
) -> tuple[tuple[date, ...] | None, tuple[str, ...]]:
    if delivery_year == start_year:
        return primary_calendar.trading_dates, ()

    delivery_calendar_path = official_calendar_path(exchange=exchange, year=delivery_year)
    if not delivery_calendar_path.exists():
        return None, ()

    delivery_calendar_result = build_trading_calendar(
        start=date(delivery_year, 1, 1),
        end=date(delivery_year, 12, 31),
        exchange=exchange,
        fixture_path=delivery_calendar_path,
    )
    return (
        delivery_calendar_result.calendar.trading_dates,
        (
            *delivery_calendar_result.warnings,
            (
                f"{context_name} used {exchange.upper()} {delivery_year} calendar "
                "for cross-year contract last_trade_date calculation"
            ),
        ),
    )


def _delivery_years_from_quotes(
    *,
    product_code: str,
    base_year: int,
    quotes: Sequence[CoreQuoteDailyRow],
) -> tuple[int, ...]:
    years = {base_year}
    for quote in quotes:
        if quote.product_code.upper() != product_code:
            continue
        years.add(
            _infer_czce_delivery_year(
                contract_code=quote.contract_code,
                product_code=product_code,
                base_year=base_year,
            )
        )
    return tuple(sorted(years))


def _infer_czce_delivery_year(*, contract_code: str, product_code: str, base_year: int) -> int:
    """Infer delivery year from CZCE product + last-year-digit contract code."""
    normalized = contract_code.strip().upper()
    product = product_code.upper()
    if not normalized.startswith(product):
        raise ResearchWorkbenchError(
            f"contract {contract_code} does not match product {product_code}"
        )
    suffix = normalized[len(product) :]
    if len(suffix) != 3 or not suffix.isdigit():
        raise ResearchWorkbenchError(
            f"unsupported CZCE contract code for research universe: {contract_code}"
        )

    year_digit = int(suffix[0])
    candidates = [
        year
        for year in range(base_year - 1, base_year + 3)
        if year % 10 == year_digit
    ]
    if not candidates:
        raise ResearchWorkbenchError(
            f"cannot infer delivery year for {contract_code} around {base_year}; "
            "HUMAN_REVIEW_REQUIRED"
        )
    return min(candidates, key=lambda year: (abs(year - base_year), year < base_year))


def _optional_float(value: float | str | None) -> float | None:
    if value in {None, TODO_REQUIRES_HUMAN_REVIEW}:
        return None
    return float(value)
