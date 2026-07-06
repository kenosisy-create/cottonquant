# Data Sources

## CZCE_DAILY_QUOTE

Status: implemented for D2 fixture-safe raw capture.

The D2 ingestion path accepts a trade date, product code, and local fixture path,
then writes the payload to the immutable raw snapshot store. It records source,
product, business date, content type, byte size, SHA256, parser version, fetch
timing metadata, and payload path in the raw manifest.

D2 does not parse or normalize exchange business fields. It does not create core
fact rows. Core quote normalization is reserved for D5+.

Example:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main ingest czce-daily-quote --date 2024-01-02 --product CF --fixture tests/fixtures/czce_daily_quote_sample.html
```

Live endpoint configuration remains TODO_REQUIRES_HUMAN_REVIEW. Tests must use
fixtures and must not require external network access.

## CZCE_OFFICIAL_HISTORY_QUOTE

Status: implemented as a post-R22 CF official annual-history connector.

The connector targets the CZCE history page:

```text
https://www.czce.com.cn/cn/jysj/lshqxz/H077003019index_1.htm
```

For the current MVP bridge, use the latest three completed annual archives:

```text
data/incoming/CF/history/ALLFUTURES2023.zip
data/incoming/CF/history/ALLFUTURES2024.zip
data/incoming/CF/history/ALLFUTURES2025.zip
```

Command:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-official-history --years 2023,2024,2025 --source-dir data/incoming/CF/history
```

The command preserves every annual ZIP into the immutable raw snapshot store
before parsing. Core normalization then extracts only CF daily rows and writes:

```text
data/core/CF/core_quote_daily.parquet
```

Direct network download is optional (`--allow-download`) and may be blocked by
the official website. A blocked download must remain visible as
`DOWNLOAD_BLOCKED`/`NEEDS_MANUAL_DOWNLOAD`; do not silently substitute a third
party source.

Known human-review gates:

- official exchange field interpretation
- official volume, open interest, and turnover unit/sidedness
- contract rule and last-trading-day review before any trading use

## CZCE_SETTLEMENT_PARAM

Status: implemented for D4 fixture-safe raw capture.

The D4 ingestion path accepts a trade date, product code, and local fixture path,
then writes the payload to the immutable raw snapshot store. The raw manifest
records source, product, business date, content type, byte size, SHA256, parser
version, fetch metadata, and a role marker for future limit, margin,
trading-status, and blocked-trade facts.

D4 does not parse or normalize exchange business fields. It does not create core
settlement rows. Core settlement normalization is reserved for D5+.

Example:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main ingest czce-settlement --date 2024-01-02 --product CF --fixture tests/fixtures/czce_settlement_param_sample.csv
```

Live endpoint configuration remains TODO_REQUIRES_HUMAN_REVIEW. Tests must use
fixtures and must not require external network access.

## CZCE_HISTORY_QUOTE

Status: implemented for D3 fixture-safe raw backfill.

The D3 ingestion path accepts a historical year, product code, optional file
type, and local fixture file or directory. Every matched fixture file is written
as its own immutable raw snapshot. The raw manifest records source, product,
content type, byte size, SHA256, parser version, fixture metadata, and
`history_year`.

Historical year files are not treated as a single trade date. Their manifest
`biz_date` is left empty and the year is stored in metadata as `year` and
`history_year`. Raw snapshot listing can filter by source, product, and year.

Examples:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main ingest czce-history --year 2024 --product CF --file-type csv --fixture tests/fixtures/czce_history_2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main raw list --source CZCE_HISTORY_QUOTE --product CF --year 2024
```

Live endpoint configuration remains TODO_REQUIRES_HUMAN_REVIEW. Tests must use
fixtures and must not require external network access.
