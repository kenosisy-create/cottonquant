# Trading Calendar

D7 adds a local trading calendar abstraction for core-layer date navigation.

## Sources

Two sources are supported:

- CSV fixture calendar: preferred for tests and reviewable examples.
- Provisional weekday calendar: generated when no fixture is provided.

For CZCE 2024, the default calendar uses
`configs/calendars/CZCE_2024_OFFICIAL.csv`, generated from the Zhengzhou
Commodity Exchange notice on the 2024 national holiday trading schedule.
Rows carry `source_snapshot_id=czce_2024_holiday_notice_20231226` to preserve
source lineage for the reviewed official notice.

`PROVISIONAL_FIXTURE` is not an official calendar. It only marks Monday-Friday as
trading days and is used only when no reviewed official fixture exists.

## CLI

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-calendar --start 2024-01-01 --end 2024-01-10 --exchange CZCE
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-calendar --start 2024-01-01 --end 2024-01-10 --exchange CZCE --fixture tests/fixtures/czce_trading_calendar_sample.csv
```

## Navigation

The in-memory calendar supports:

- `prev_trade_date(date)`
- `next_trade_date(date)`
- `nth_trading_day_of_month(year=..., month=..., n=...)`

Navigation only uses the loaded calendar range. It fails loudly when the requested
date is outside the available data instead of guessing.

## Human Review

Before production use, replace provisional calendars with an official exchange
calendar or a reviewed fixture with clear source lineage.

## Source

- Zhengzhou Commodity Exchange, "Notice on Trading Schedule during National
  Holidays for Year 2024", modified 2023-12-26:
  https://english.czce.com.cn/en/AboutUs/News/ggytz/webinfo/2023/12/1703386438499236.htm
