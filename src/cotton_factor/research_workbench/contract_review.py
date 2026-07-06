"""R07 CF contract rule review artifacts."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from cotton_factor.common.exceptions import (
    ContractMasterError,
    ResearchWorkbenchError,
    TradingCalendarError,
)
from cotton_factor.common.paths import reports_dir
from cotton_factor.core.contract_master import (
    TODO_REQUIRES_HUMAN_REVIEW,
    build_contract_master,
    load_product_config,
)
from cotton_factor.core.trading_calendar import load_trading_calendar_csv, official_calendar_path

PRODUCT_CODE = "CF"
REVIEW_REPORT_DIR = "contract_rules"
ReviewStatus = Literal[
    "CONFIGURED",
    "COMPUTED_WITH_CALENDAR",
    "HUMAN_REVIEW_REQUIRED",
    "MISSING_CALENDAR",
    "WARNING",
]


@dataclass(frozen=True)
class ContractRuleReviewRow:
    """One row in the CF contract rule review table."""

    row_type: str
    item_id: str
    field_name: str
    configured_value: str
    review_status: ReviewStatus
    human_review_required: bool
    blocks_production: bool
    source: str
    notes: str
    contract_code: str = ""
    delivery_month: str = ""
    last_trade_date: str = ""

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe row."""
        return {
            "row_type": self.row_type,
            "item_id": self.item_id,
            "field_name": self.field_name,
            "configured_value": self.configured_value,
            "review_status": self.review_status,
            "human_review_required": str(self.human_review_required).lower(),
            "blocks_production": str(self.blocks_production).lower(),
            "source": self.source,
            "contract_code": self.contract_code,
            "delivery_month": self.delivery_month,
            "last_trade_date": self.last_trade_date,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ContractRuleReviewResult:
    """Result of building the R07 contract rule review artifacts."""

    product_code: str
    year: int
    csv_path: Path
    markdown_path: Path
    rows: tuple[ContractRuleReviewRow, ...]
    warnings: tuple[str, ...]

    @property
    def human_review_required_count(self) -> int:
        """Return how many rows still need human review."""
        return sum(1 for row in self.rows if row.human_review_required)

    @property
    def blocks_production_count(self) -> int:
        """Return how many rows block production confidence."""
        return sum(1 for row in self.rows if row.blocks_production)

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable summary."""
        return {
            "product_code": self.product_code,
            "year": self.year,
            "csv_path": str(self.csv_path),
            "markdown_path": str(self.markdown_path),
            "row_count": len(self.rows),
            "human_review_required_count": self.human_review_required_count,
            "blocks_production_count": self.blocks_production_count,
            "warnings": list(self.warnings),
        }


def build_cf_contract_rule_review(
    *,
    year: int,
    report_output_dir: Path | None = None,
    config_dir: Path | None = None,
    calendar_path: Path | None = None,
) -> ContractRuleReviewResult:
    """Build a CF contract rule review table for the research workbench."""
    if year < 1990 or year > 2100:
        raise ResearchWorkbenchError(f"year out of supported range: {year}")

    config = load_product_config(PRODUCT_CODE, config_dir)
    source = f"configs/products/{PRODUCT_CODE}.yaml"
    rows = _product_rule_rows(config=config, source=source)

    # R07 只产出复核证据，不把待复核字段升级成生产确认。
    trading_dates, calendar_warning = _trading_dates_for_year(
        exchange=config.exchange,
        year=year,
        calendar_path=calendar_path,
    )
    warnings: list[str] = []
    if calendar_warning is not None:
        warnings.append(calendar_warning)

    try:
        contract_result = build_contract_master(
            product_code=PRODUCT_CODE,
            year=year,
            config_dir=config_dir,
            trading_dates=trading_dates,
        )
    except ContractMasterError as exc:
        if trading_dates is None:
            raise ResearchWorkbenchError(f"cannot build CF contract review rows: {exc}") from exc
        contract_rows, partial_warnings = _partial_calendar_contract_rows(
            config=config,
            year=year,
            trading_dates=trading_dates,
            source=source,
            build_error=exc,
        )
        rows.extend(contract_rows)
        contract_warnings = partial_warnings
    else:
        rows.extend(_contract_rows(contract_result=contract_result, source=source))
        contract_warnings = tuple(contract_result.warnings)

    for warning in contract_warnings:
        rows.append(
            ContractRuleReviewRow(
                row_type="warning",
                item_id=f"warning.{len(warnings) + 1}",
                field_name="generation_warning",
                configured_value=warning,
                review_status="WARNING",
                human_review_required="human review" in warning.lower()
                or TODO_REQUIRES_HUMAN_REVIEW in warning,
                blocks_production="human review" in warning.lower()
                or TODO_REQUIRES_HUMAN_REVIEW in warning,
                source="contract_master",
                notes=warning,
            )
        )
    warnings.extend(contract_warnings)

    csv_path, markdown_path = _report_paths(year=year, report_output_dir=report_output_dir)
    result = ContractRuleReviewResult(
        product_code=PRODUCT_CODE,
        year=year,
        csv_path=csv_path,
        markdown_path=markdown_path,
        rows=tuple(rows),
        warnings=tuple(sorted(set(warnings))),
    )
    _write_review_csv(csv_path=csv_path, rows=result.rows)
    _write_review_markdown(markdown_path=markdown_path, result=result)
    return result


def _product_rule_rows(*, config: object, source: str) -> list[ContractRuleReviewRow]:
    rows: list[ContractRuleReviewRow] = []
    human_review_required = set(config.human_review_required)
    values = {
        "product_code": config.product_code,
        "exchange": config.exchange,
        "instrument_type": config.instrument_type,
        "currency": config.currency,
        "multiplier": config.multiplier,
        "tick_size": config.tick_size,
        "delivery_months": config.delivery_months,
        "last_trade_day_rule": config.last_trade_day_rule,
        "option_style": config.option_style,
        "contract_code_format": config.contract_code_format,
        "source_config_version": config.source_config_version,
        "rule_version_id": config.rule_version_id,
    }
    for field_name, value in values.items():
        needs_review = (
            field_name in human_review_required or value == TODO_REQUIRES_HUMAN_REVIEW
        )
        rows.append(
            ContractRuleReviewRow(
                row_type="rule",
                item_id=f"rule.{field_name}",
                field_name=field_name,
                configured_value=_display_value(value),
                review_status="HUMAN_REVIEW_REQUIRED" if needs_review else "CONFIGURED",
                human_review_required=needs_review,
                blocks_production=needs_review,
                source=source,
                notes=(
                    "Needs human confirmation before production confidence."
                    if needs_review
                    else "Configured for research workbench use."
                ),
            )
        )

    for field_name in sorted(human_review_required - set(values)):
        rows.append(
            ContractRuleReviewRow(
                row_type="rule",
                item_id=f"rule.{field_name}",
                field_name=field_name,
                configured_value=TODO_REQUIRES_HUMAN_REVIEW,
                review_status="HUMAN_REVIEW_REQUIRED",
                human_review_required=True,
                blocks_production=True,
                source=source,
                notes="Declared in human_review_required but not represented as a config scalar.",
            )
        )
    return rows


def _trading_dates_for_year(
    *,
    exchange: str,
    year: int,
    calendar_path: Path | None,
) -> tuple[tuple[date, ...] | None, str | None]:
    selected_path = calendar_path or official_calendar_path(exchange=exchange, year=year)
    if not selected_path.exists():
        return None, f"official calendar missing for {exchange} {year}: {selected_path}"
    try:
        rows = load_trading_calendar_csv(
            fixture_path=selected_path,
            exchange=exchange,
            start=date(year, 1, 1),
            end=date(year, 12, 31),
        )
    except TradingCalendarError as exc:
        return None, f"official calendar cannot be loaded for {exchange} {year}: {exc}"
    return tuple(row.trade_date for row in rows if row.is_trading_day), None


def _contract_rows(*, contract_result: object, source: str) -> list[ContractRuleReviewRow]:
    last_trade_needs_review = (
        "last_trade_day_rule" in contract_result.product_config.human_review_required
    )
    rows: list[ContractRuleReviewRow] = []
    for contract in contract_result.contracts:
        last_trade_date = (
            contract.last_trade_date.isoformat() if contract.last_trade_date is not None else ""
        )
        status: ReviewStatus
        if contract.last_trade_date is None:
            status = "MISSING_CALENDAR"
        elif last_trade_needs_review:
            status = "HUMAN_REVIEW_REQUIRED"
        else:
            status = "COMPUTED_WITH_CALENDAR"
        rows.append(
            ContractRuleReviewRow(
                row_type="contract",
                item_id=f"contract.{contract.contract_code}",
                field_name="last_trade_date",
                configured_value=contract.rule_version_id,
                review_status=status,
                human_review_required=last_trade_needs_review or contract.last_trade_date is None,
                blocks_production=last_trade_needs_review or contract.last_trade_date is None,
                source=source,
                notes=(
                    "Last trade date calculated from configured rule and available calendar; "
                    "rule still needs human confirmation."
                    if contract.last_trade_date is not None
                    else "Last trade date not available because calendar evidence is missing."
                ),
                contract_code=contract.contract_code,
                delivery_month=f"{contract.delivery_year}-{contract.delivery_month:02d}",
                last_trade_date=last_trade_date,
            )
        )
    return rows


def _partial_calendar_contract_rows(
    *,
    config: object,
    year: int,
    trading_dates: tuple[date, ...],
    source: str,
    build_error: ContractMasterError,
) -> tuple[list[ContractRuleReviewRow], tuple[str, ...]]:
    """Build review rows when a to-date official calendar cannot cover future months."""
    if config.last_trade_day_rule != "delivery_month_10th_trading_day":
        raise ResearchWorkbenchError(
            f"cannot build CF contract review rows: {build_error}"
        ) from build_error
    if not isinstance(config.delivery_months, list):
        raise ResearchWorkbenchError(
            f"cannot build CF contract review rows: {build_error}"
        ) from build_error

    last_trade_needs_review = "last_trade_day_rule" in config.human_review_required
    rows: list[ContractRuleReviewRow] = []
    missing_months: list[str] = []
    for month in config.delivery_months:
        month_dates = sorted(
            trade_date
            for trade_date in trading_dates
            if trade_date.year == year and trade_date.month == month
        )
        if len(month_dates) >= 10:
            last_trade_date = month_dates[9].isoformat()
            status: ReviewStatus = (
                "HUMAN_REVIEW_REQUIRED"
                if last_trade_needs_review
                else "COMPUTED_WITH_CALENDAR"
            )
            notes = (
                "Last trade date calculated from available official calendar; "
                "rule still needs human confirmation."
            )
        else:
            last_trade_date = ""
            status = "MISSING_CALENDAR"
            missing_months.append(f"{year}-{month:02d}")
            notes = (
                "Partial official calendar does not contain enough trading days "
                "for this delivery month; HUMAN_REVIEW_REQUIRED before production use."
            )

        rows.append(
            ContractRuleReviewRow(
                row_type="contract",
                item_id=f"contract.{PRODUCT_CODE}{year % 10}{month:02d}",
                field_name="last_trade_date",
                configured_value=config.rule_version_id,
                review_status=status,
                human_review_required=last_trade_needs_review or not last_trade_date,
                blocks_production=last_trade_needs_review or not last_trade_date,
                source=source,
                notes=notes,
                contract_code=f"{PRODUCT_CODE}{year % 10}{month:02d}",
                delivery_month=f"{year}-{month:02d}",
                last_trade_date=last_trade_date,
            )
        )

    warnings = [
        "partial official calendar cannot compute every CF contract last_trade_date; "
        "future delivery months require HUMAN_REVIEW_REQUIRED before production use"
    ]
    if missing_months:
        warnings.append(
            "partial official calendar missing enough trading dates for delivery months: "
            + ", ".join(missing_months)
        )
    if "last_trade_day_rule" in config.human_review_required:
        warnings.append("last_trade_day_rule requires human review before production use")
    if "tick_size" in config.human_review_required:
        warnings.append("tick_size requires human review")
    if config.tick_size == TODO_REQUIRES_HUMAN_REVIEW:
        warnings.append("tick_size is TODO_REQUIRES_HUMAN_REVIEW; emitted as null")
    warnings.extend(
        f"{field_name} requires human review" for field_name in config.human_review_required
    )
    return rows, tuple(sorted(set(warnings)))


def _write_review_csv(*, csv_path: Path, rows: tuple[ContractRuleReviewRow, ...]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "row_type",
            "item_id",
            "field_name",
            "configured_value",
            "review_status",
            "human_review_required",
            "blocks_production",
            "source",
            "contract_code",
            "delivery_month",
            "last_trade_date",
            "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())


def _write_review_markdown(
    *,
    markdown_path: Path,
    result: ContractRuleReviewResult,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Contract Rule Review - {result.year}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Rows: `{len(result.rows)}`",
        f"- Human review required rows: `{result.human_review_required_count}`",
        f"- Blocks production rows: `{result.blocks_production_count}`",
        "",
        "## Review Rows",
        "",
        "| Type | Field | Value | Status | Contract | Last Trade Date | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.row_type,
                    row.field_name,
                    row.configured_value.replace("|", "\\|"),
                    row.review_status,
                    row.contract_code,
                    row.last_trade_date,
                    row.notes.replace("|", "\\|"),
                ]
            )
            + " |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report_paths(
    *,
    year: int,
    report_output_dir: Path | None,
) -> tuple[Path, Path]:
    root = report_output_dir or reports_dir() / "research" / REVIEW_REPORT_DIR
    stem = f"{PRODUCT_CODE}_{year}_contract_rule_review"
    return root / f"{stem}.csv", root / f"{stem}.md"


def _display_value(value: object) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)
