"""Trading calendar loading, provisional generation, and navigation."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from cotton_factor.common.exceptions import TradingCalendarError
from cotton_factor.common.paths import project_root
from cotton_factor.core.schemas import CoreTradingCalendarRow

PROVISIONAL_CALENDAR_VERSION = "PROVISIONAL_FIXTURE"
CSV_FIXTURE_CALENDAR_VERSION = "CSV_FIXTURE"


@dataclass(frozen=True)
class TradingCalendarBuildResult:
    """Trading calendar build output."""

    calendar: TradingCalendar
    rows: list[CoreTradingCalendarRow]
    warnings: list[str]


class TradingCalendar:
    """In-memory trading calendar for core-layer date navigation."""

    def __init__(self, rows: Iterable[CoreTradingCalendarRow]) -> None:
        normalized_rows = sorted(rows, key=lambda row: row.trade_date)
        if not normalized_rows:
            raise TradingCalendarError("trading calendar requires at least one row")

        first = normalized_rows[0]
        for row in normalized_rows:
            if row.exchange != first.exchange:
                raise TradingCalendarError("calendar rows must have one exchange")
            if row.calendar_version != first.calendar_version:
                raise TradingCalendarError("calendar rows must have one calendar_version")

        self.exchange = first.exchange
        self.calendar_version = first.calendar_version
        self.rows = normalized_rows
        self._row_by_date = {row.trade_date: row for row in normalized_rows}
        if len(self._row_by_date) != len(normalized_rows):
            raise TradingCalendarError("calendar rows contain duplicate trade_date values")

        self._trading_dates = tuple(row.trade_date for row in normalized_rows if row.is_trading_day)

    @property
    def trading_dates(self) -> tuple[date, ...]:
        """Return trading dates in ascending order."""
        return self._trading_dates

    def is_trading_day(self, value: date) -> bool:
        """Return whether a date is marked as a trading day."""
        row = self._row_by_date.get(value)
        return bool(row and row.is_trading_day)

    def prev_trade_date(self, value: date) -> date:
        """Return the previous trading date strictly before value."""
        # 导航函数只看已加载日历范围；范围外不猜测，避免把临时规则扩散成事实。
        for trade_date in reversed(self._trading_dates):
            if trade_date < value:
                return trade_date
        raise TradingCalendarError(f"no previous trading date before {value}")

    def next_trade_date(self, value: date) -> date:
        """Return the next trading date strictly after value."""
        for trade_date in self._trading_dates:
            if trade_date > value:
                return trade_date
        raise TradingCalendarError(f"no next trading date after {value}")

    def nth_trading_day_of_month(self, *, year: int, month: int, n: int) -> date:
        """Return the nth trading day for a year/month."""
        if n < 1:
            raise TradingCalendarError("n must be >= 1")
        # 合约最后交易日等规则会依赖这里；如果样本不足，必须失败而不是回退到自然日。
        month_dates = [
            trade_date
            for trade_date in self._trading_dates
            if trade_date.year == year and trade_date.month == month
        ]
        if len(month_dates) < n:
            raise TradingCalendarError(
                f"month {year}-{month:02d} has only {len(month_dates)} trading days"
            )
        return month_dates[n - 1]


def build_trading_calendar(
    *,
    start: date,
    end: date,
    exchange: str,
    fixture_path: Path | None = None,
) -> TradingCalendarBuildResult:
    """Build a trading calendar from a CSV fixture or provisional weekdays."""
    _validate_range(start=start, end=end)
    calendar_path = fixture_path or official_calendar_path(exchange=exchange, year=start.year)
    if start.year != end.year and fixture_path is None:
        calendar_path = None

    if calendar_path is not None and calendar_path.exists():
        rows = load_trading_calendar_csv(
            fixture_path=calendar_path,
            exchange=exchange,
            start=start,
            end=end,
        )
        return TradingCalendarBuildResult(calendar=TradingCalendar(rows), rows=rows, warnings=[])

    # 临时工作日日历只服务测试和早期骨架验证；正式交易日历必须用 fixture/官方来源替换。
    rows = generate_provisional_weekday_calendar(start=start, end=end, exchange=exchange)
    warning = (
        "PROVISIONAL_FIXTURE calendar uses weekdays only and is not official; "
        "replace before production use"
    )
    return TradingCalendarBuildResult(
        calendar=TradingCalendar(rows),
        rows=rows,
        warnings=[warning],
    )


def official_calendar_path(*, exchange: str, year: int) -> Path:
    """Return the repository path for a reviewed official calendar fixture."""
    return project_root() / "configs" / "calendars" / f"{exchange.upper()}_{year}_OFFICIAL.csv"


def load_trading_calendar_csv(
    *,
    fixture_path: Path,
    exchange: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[CoreTradingCalendarRow]:
    """Load trading calendar rows from a CSV fixture."""
    if not fixture_path.exists() or not fixture_path.is_file():
        raise TradingCalendarError(f"calendar fixture not found: {fixture_path}")

    rows: list[CoreTradingCalendarRow] = []
    with fixture_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"exchange", "trade_date", "is_trading_day"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise TradingCalendarError(f"calendar fixture missing columns: {sorted(missing)}")

        for csv_row in reader:
            trade_date = date.fromisoformat(csv_row["trade_date"])
            if start is not None and trade_date < start:
                continue
            if end is not None and trade_date > end:
                continue

            row_exchange = csv_row["exchange"].strip().upper()
            if exchange is not None and row_exchange != exchange.upper():
                continue

            rows.append(
                CoreTradingCalendarRow(
                    exchange=row_exchange,
                    trade_date=trade_date,
                    is_trading_day=_parse_bool(csv_row["is_trading_day"]),
                    calendar_version=csv_row.get("calendar_version")
                    or CSV_FIXTURE_CALENDAR_VERSION,
                    source_snapshot_id=csv_row.get("source_snapshot_id") or None,
                )
            )

    if not rows:
        raise TradingCalendarError("calendar fixture produced no rows for requested filters")
    return rows


def generate_provisional_weekday_calendar(
    *,
    start: date,
    end: date,
    exchange: str,
) -> list[CoreTradingCalendarRow]:
    """Generate a weekday-only provisional calendar for tests."""
    _validate_range(start=start, end=end)
    normalized_exchange = exchange.strip().upper()
    if not normalized_exchange:
        raise TradingCalendarError("exchange must be non-empty")

    rows: list[CoreTradingCalendarRow] = []
    current = start
    while current <= end:
        rows.append(
            CoreTradingCalendarRow(
                exchange=normalized_exchange,
                trade_date=current,
                is_trading_day=current.weekday() < 5,
                calendar_version=PROVISIONAL_CALENDAR_VERSION,
            )
        )
        current += timedelta(days=1)
    return rows


def _validate_range(*, start: date, end: date) -> None:
    if start > end:
        raise TradingCalendarError("start must be <= end")


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise TradingCalendarError(f"invalid boolean value: {value!r}")
