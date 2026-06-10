from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import TradingCalendarError
from cotton_factor.core import (
    PROVISIONAL_CALENDAR_VERSION,
    TradingCalendar,
    build_trading_calendar,
    generate_provisional_weekday_calendar,
    load_trading_calendar_csv,
    official_calendar_path,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "czce_trading_calendar_sample.csv"
)
OFFICIAL_SOURCE_ID = "czce_2024_holiday_notice_20231226"


def test_provisional_weekday_calendar_marks_version_and_weekends() -> None:
    result = build_trading_calendar(
        start=date(2026, 1, 5),
        end=date(2026, 1, 9),
        exchange="CZCE",
    )

    assert result.calendar.calendar_version == PROVISIONAL_CALENDAR_VERSION
    assert [row.trade_date for row in result.rows] == [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    ]
    assert result.calendar.trading_dates == (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    )
    assert result.warnings


def test_build_calendar_defaults_to_official_fixture_when_available() -> None:
    assert official_calendar_path(exchange="CZCE", year=2024).exists()

    result = build_trading_calendar(
        start=date(2024, 1, 1),
        end=date(2024, 1, 10),
        exchange="CZCE",
    )

    assert result.calendar.calendar_version == "CZCE_OFFICIAL_2024_HOLIDAY_NOTICE"
    assert result.calendar.is_trading_day(date(2024, 1, 1)) is False
    assert result.calendar.is_trading_day(date(2024, 1, 2)) is True
    assert all(row.source_snapshot_id == OFFICIAL_SOURCE_ID for row in result.rows)
    assert result.warnings == []


def test_calendar_navigation_and_nth_trading_day() -> None:
    rows = generate_provisional_weekday_calendar(
        start=date(2024, 1, 1),
        end=date(2024, 1, 15),
        exchange="CZCE",
    )
    calendar = TradingCalendar(rows)

    assert calendar.prev_trade_date(date(2024, 1, 9)) == date(2024, 1, 8)
    assert calendar.next_trade_date(date(2024, 1, 5)) == date(2024, 1, 8)
    assert calendar.nth_trading_day_of_month(year=2024, month=1, n=10) == date(2024, 1, 12)


def test_csv_fixture_calendar_loads_and_filters() -> None:
    rows = load_trading_calendar_csv(
        fixture_path=FIXTURE_PATH,
        exchange="CZCE",
        start=date(2024, 1, 2),
        end=date(2024, 1, 10),
    )
    calendar = TradingCalendar(rows)

    assert calendar.calendar_version == "CZCE_FIXTURE_2024"
    assert calendar.is_trading_day(date(2024, 1, 8)) is False
    assert calendar.next_trade_date(date(2024, 1, 5)) == date(2024, 1, 9)
    assert calendar.nth_trading_day_of_month(year=2024, month=1, n=5) == date(2024, 1, 9)
    assert all(row.source_snapshot_id == "raw_calendar_fixture" for row in rows)


def test_calendar_errors_on_out_of_range_navigation_and_invalid_n() -> None:
    calendar = TradingCalendar(
        generate_provisional_weekday_calendar(
            start=date(2024, 1, 2),
            end=date(2024, 1, 3),
            exchange="CZCE",
        )
    )

    with pytest.raises(TradingCalendarError, match="no previous"):
        calendar.prev_trade_date(date(2024, 1, 2))

    with pytest.raises(TradingCalendarError, match="no next"):
        calendar.next_trade_date(date(2024, 1, 3))

    with pytest.raises(TradingCalendarError, match="n must be >= 1"):
        calendar.nth_trading_day_of_month(year=2024, month=1, n=0)


def test_calendar_rejects_duplicate_dates() -> None:
    rows = generate_provisional_weekday_calendar(
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
        exchange="CZCE",
    )

    with pytest.raises(TradingCalendarError, match="duplicate"):
        TradingCalendar([*rows, *rows])
