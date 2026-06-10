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
