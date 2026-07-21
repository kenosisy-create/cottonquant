"""R81 CF option expiry registry loading and quality gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import project_root

PRODUCT_CODE = "CF"
OFFICIAL_RULE_CODE = "CZCE_OPTION_PREV_MONTH_DAY15_THIRD_LAST_TRADING_DAY"
OFFICIAL_RULE_TEXT_CN = (
    "标的期货交割月份前一个月第15个日历日之前（含该日）的倒数第3个交易日"
)
REGISTRY_REQUIRED_COLUMNS = {
    "underlying_contract",
    "option_expiry_date",
    "rule_code",
    "source_name",
    "source_url",
    "quality_flag",
    "human_review_required",
}


@dataclass(frozen=True)
class OptionExpiryResolution:
    """One contract-day expiry resolution used by the IV model."""

    option_expiry_date: date
    days_to_expiry: int
    expiry_date_source: str
    expiry_rule_code: str
    expiry_quality_flag: str
    expiry_source_name: str
    expiry_source_url: str
    expiry_human_review_required: bool
    risk_flags: tuple[str, ...]


def default_option_expiry_registry_path() -> Path:
    """Return the reviewed CF option expiry registry path."""
    return project_root() / "configs" / "products" / "CF_OPTION_EXPIRY_OFFICIAL.csv"


def load_option_expiry_registry(path: Path | None = None) -> pd.DataFrame:
    """Load and validate an explicit contract expiry registry."""
    resolved_path = path or default_option_expiry_registry_path()
    if not resolved_path.exists() or not resolved_path.is_file():
        raise ResearchWorkbenchError(
            f"CF option expiry registry not found: {resolved_path}"
        )
    try:
        frame = pd.read_csv(resolved_path)
    except Exception as exc:  # pragma: no cover - pandas message varies by engine
        raise ResearchWorkbenchError(
            f"cannot read CF option expiry registry: {resolved_path}: {exc}"
        ) from exc
    missing = REGISTRY_REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(
            f"CF option expiry registry missing columns: {sorted(missing)}"
        )
    if frame.empty:
        raise ResearchWorkbenchError("CF option expiry registry is empty")

    working = frame.copy()
    working["underlying_contract"] = (
        working["underlying_contract"].astype(str).str.strip().str.upper()
    )
    if working["underlying_contract"].duplicated().any():
        duplicates = sorted(
            working.loc[
                working["underlying_contract"].duplicated(keep=False),
                "underlying_contract",
            ].unique()
        )
        raise ResearchWorkbenchError(
            f"CF option expiry registry has duplicate contracts: {duplicates}"
        )
    parsed_dates = pd.to_datetime(working["option_expiry_date"], errors="coerce")
    if parsed_dates.isna().any():
        bad_contracts = working.loc[
            parsed_dates.isna(), "underlying_contract"
        ].tolist()
        raise ResearchWorkbenchError(
            f"CF option expiry registry has invalid dates: {bad_contracts}"
        )
    working["option_expiry_date"] = parsed_dates.dt.date
    working["human_review_required"] = working["human_review_required"].map(
        _parse_bool
    )

    for column in ("rule_code", "source_name", "source_url", "quality_flag"):
        working[column] = working[column].astype(str).str.strip()
        if working[column].eq("").any():
            raise ResearchWorkbenchError(
                f"CF option expiry registry contains blank {column}"
            )
    for row in working.itertuples(index=False):
        if not str(row.underlying_contract).startswith(PRODUCT_CODE):
            raise ResearchWorkbenchError(
                "CF option expiry registry contains unsupported contract: "
                f"{row.underlying_contract}"
            )
        if row.rule_code == OFFICIAL_RULE_CODE:
            _validate_official_rule_date(
                underlying_contract=str(row.underlying_contract),
                expiry_date=row.option_expiry_date,
            )
    return working.sort_values("option_expiry_date").reset_index(drop=True)


def resolve_option_expiry(
    *,
    underlying_contract: str,
    trade_date: date,
    registry: pd.DataFrame,
) -> OptionExpiryResolution:
    """Resolve explicit expiry first and use a visible month-start fallback."""
    contract = underlying_contract.strip().upper()
    matched = registry.loc[registry["underlying_contract"] == contract]
    if matched.empty:
        fallback = contract_month_start_proxy(
            underlying_contract=contract,
            trade_date=trade_date,
        )
        if fallback < trade_date:
            raise ResearchWorkbenchError(
                f"expiry fallback is before trade_date for {contract}: "
                f"{fallback} < {trade_date}"
            )
        return OptionExpiryResolution(
            option_expiry_date=fallback,
            days_to_expiry=max((fallback - trade_date).days, 1),
            expiry_date_source="MONTH_START_PROXY_FALLBACK",
            expiry_rule_code="CONTRACT_MONTH_FIRST_DAY_PROXY",
            expiry_quality_flag="HUMAN_REVIEW_REQUIRED",
            expiry_source_name="R80 legacy month-start proxy",
            expiry_source_url="",
            expiry_human_review_required=True,
            risk_flags=("EXPIRY_DATE_MONTH_START_FALLBACK",),
        )

    row = matched.iloc[0]
    expiry_date = row["option_expiry_date"]
    if expiry_date < trade_date:
        raise ResearchWorkbenchError(
            f"option expiry is before trade_date for {contract}: "
            f"{expiry_date} < {trade_date}"
        )
    flags = ["OPTION_EXPIRY_REGISTRY"]
    if bool(row["human_review_required"]):
        flags.append("OPTION_EXPIRY_HUMAN_REVIEW_REQUIRED")
    if expiry_date == trade_date:
        flags.append("OPTION_EXPIRY_DAY_ONE_DAY_FLOOR")
    return OptionExpiryResolution(
        option_expiry_date=expiry_date,
        days_to_expiry=max((expiry_date - trade_date).days, 1),
        expiry_date_source="EXPLICIT_EXPIRY_REGISTRY",
        expiry_rule_code=str(row["rule_code"]),
        expiry_quality_flag=str(row["quality_flag"]),
        expiry_source_name=str(row["source_name"]),
        expiry_source_url=str(row["source_url"]),
        expiry_human_review_required=bool(row["human_review_required"]),
        risk_flags=tuple(flags),
    )


def contract_month_start_proxy(
    *, underlying_contract: str, trade_date: date
) -> date:
    """Keep the legacy proxy only as an explicit, reviewable fallback."""
    text = underlying_contract.upper().replace(PRODUCT_CODE, "", 1)
    if not text.isdigit():
        raise ResearchWorkbenchError(
            f"unsupported underlying contract for expiry proxy: {underlying_contract}"
        )
    if len(text) == 3:
        year_digit = int(text[0])
        month = int(text[1:])
        decade = trade_date.year // 10 * 10
        year = decade + year_digit
        if year < trade_date.year - 5:
            year += 10
        if year > trade_date.year + 5:
            year -= 10
    elif len(text) == 4:
        year = 2000 + int(text[:2])
        month = int(text[2:])
    elif len(text) == 6:
        year = int(text[:4])
        month = int(text[4:])
    else:
        raise ResearchWorkbenchError(
            f"unsupported underlying contract month: {underlying_contract}"
        )
    try:
        return date(year, month, 1)
    except ValueError as exc:
        raise ResearchWorkbenchError(
            f"invalid underlying contract month: {underlying_contract}"
        ) from exc


def _validate_official_rule_date(
    *, underlying_contract: str, expiry_date: date
) -> None:
    text = underlying_contract.upper().replace(PRODUCT_CODE, "", 1)
    if not text.isdigit() or len(text) not in {3, 4, 6}:
        raise ResearchWorkbenchError(
            f"unsupported official expiry contract: {underlying_contract}"
        )
    delivery_month = int(text[-2:])
    expected_expiry_month = 12 if delivery_month == 1 else delivery_month - 1
    if expiry_date.month != expected_expiry_month or expiry_date.day > 15:
        raise ResearchWorkbenchError(
            f"official expiry date violates {OFFICIAL_RULE_CODE} for "
            f"{underlying_contract}: {expiry_date}"
        )
    delivery_year = expiry_date.year + 1 if delivery_month == 1 else expiry_date.year
    encoded_year = int(text[:-2])
    if len(text) == 3 and encoded_year != delivery_year % 10:
        raise ResearchWorkbenchError(
            f"official expiry year does not match contract: {underlying_contract}"
        )
    if len(text) == 4 and encoded_year != delivery_year % 100:
        raise ResearchWorkbenchError(
            f"official expiry year does not match contract: {underlying_contract}"
        )
    if len(text) == 6 and encoded_year != delivery_year:
        raise ResearchWorkbenchError(
            f"official expiry year does not match contract: {underlying_contract}"
        )


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ResearchWorkbenchError(
        f"invalid human_review_required value in option expiry registry: {value!r}"
    )
