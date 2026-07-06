# CF Research Data Sources

This document defines the research-grade CF daily data source convention. It is
for local production-like files first, not for a production API service.

## Scope

- Product: CF
- Exchange: CZCE
- Frequency: daily
- Primary input route: local files placed under `data/incoming/CF/YYYY-MM-DD/`
- Primary output route: raw preservation first, then normalized core facts

## Required Daily Quote Fields

Every CF daily quote file must provide fields that can be mapped to:

| Standard field | Description |
| --- | --- |
| `trade_date` | Trading date in `YYYY-MM-DD` format. |
| `exchange` | Exchange code, expected `CZCE`. |
| `product_code` | Product code, expected `CF`. |
| `contract_id` | Tradable contract id, for example `CF405`. |
| `open` | Daily open price. |
| `high` | Daily high price. |
| `low` | Daily low price. |
| `close` | Daily close price. |
| `settle` | Daily settlement price. |
| `volume` | Daily volume. |
| `open_interest` | Daily open interest. |

## Optional Settlement And Risk Fields

These fields are useful but may be missing in research files:

| Standard field | Description |
| --- | --- |
| `limit_up` | Daily upper price limit. |
| `limit_down` | Daily lower price limit. |
| `margin_rate` | Margin rate. |
| `trading_status` | Trading status such as normal, halted, or limit-only. |

Missing optional fields must become null or warnings. They must not be silently
invented.

## Supported Source Formats

Research-mode ingest may preserve the following local file types:

- `csv`
- `xlsx`
- `html`
- `zip`

Raw ingest only copies files and records hashes. Business field parsing happens
later from preserved raw files.

## Folder Convention

Analysts should place files under:

```text
data/incoming/CF/YYYY-MM-DD/
```

Example:

```text
data/incoming/CF/2026-06-11/czce_cf_daily.csv
```

Official annual history ZIPs should be placed under:

```text
data/incoming/CF/history/
```

Expected annual archive names:

```text
ALLFUTURES2023.zip
ALLFUTURES2024.zip
ALLFUTURES2025.zip
```

The official CZCE history page is:

```text
https://www.czce.com.cn/cn/jysj/lshqxz/H077003019index_1.htm
```

The workbench constructs annual archive URLs in this form:

```text
https://www.czce.com.cn/cn/DFSStaticFiles/Future/YYYY/ALLFUTURESYYYY.zip
```

If direct download is blocked by the exchange website, download the ZIPs
manually from the official page and place them in the folder above. The ingest
command still records the official URL, SHA256, byte size, raw snapshot id, and
core output path.

## Raw Preservation Convention

R04 raw ingest copies files into:

```text
data/raw/CF/YYYY-MM-DD/{run_id}/
```

It appends file-level records to:

```text
data/raw/CF/raw_manifest.jsonl
```

The raw manifest records `run_id`, `trade_date`, `product_code`,
`source_file_name`, `raw_path`, `sha256`, `content_length`, `captured_at`, and
`status`.

## Core Output Convention

R05 normalizes preserved raw CSV files into:

```text
data/core/CF/core_quote_daily.parquet
```

Core rows use `source_snapshot_id` in the existing core schema. In research mode
that value is derived from the raw manifest run id, source file name, and file
hash, so every research result can be traced back to preserved raw inputs.

Official annual ZIPs are handled by:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-official-history --years 2023,2024,2025 --source-dir data/incoming/CF/history
```

That command preserves the ZIPs as immutable raw snapshots first and only then
normalizes CF rows into:

```text
data/core/CF/core_quote_daily.parquet
```

It also writes a machine-readable and Markdown connect report under:

```text
reports/research/official_history/
```

## Known Unknowns

These must remain `HUMAN_REVIEW_REQUIRED` until reviewed:

- official exchange field names and unit interpretation
- whether volume, open interest, and turnover are single-sided or double-sided
  for a given source and date range
- settlement status semantics
- margin field definitions
- limit price field definitions
- whether a source file includes provisional or final settlement data
