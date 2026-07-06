# Post-R22 CF Official History Connect

This document defines the first real-data bridge after R06-R22. The goal is to
connect recent CZCE CF daily history into the research workbench without turning
the repository into a production data platform.

## Scope

- Product: CF only
- Exchange: CZCE
- Frequency: daily
- First window: 2023, 2024, 2025 official annual history archives
- Output: `data/core/CF/core_quote_daily.parquet`

The current date is 2026-06-25, so the three most recent completed annual
archives are 2023-2025. The 2026 trading year is not treated as a completed
annual history archive.

## Official Source

History page:

```text
https://www.czce.com.cn/cn/jysj/lshqxz/H077003019index_1.htm
```

Expected annual archive pattern:

```text
https://www.czce.com.cn/cn/DFSStaticFiles/Future/YYYY/ALLFUTURESYYYY.zip
```

The exchange page states that from 2020-01-01, volume, open interest, and
turnover are single-sided. The workbench records this source note, but official
field interpretation still remains `HUMAN_REVIEW_REQUIRED`.

## Local File Convention

Place manually downloaded files here:

```text
data/incoming/CF/history/ALLFUTURES2023.zip
data/incoming/CF/history/ALLFUTURES2024.zip
data/incoming/CF/history/ALLFUTURES2025.zip
```

Direct download can be attempted, but the CZCE site may return an HTTP 412
protection response. In that case, manually download from the official page and
rerun the same command without `--allow-download`.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-official-history --years 2023,2024,2025 --source-dir data/incoming/CF/history
```

Optional direct-download attempt:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-official-history --years 2023,2024,2025 --allow-download
```

## Data Boundary

The connector preserves official ZIP files as immutable raw snapshots first.
Parsing happens only in the core normalization step, and research functions must
continue to read normalized core/research files instead of the exchange ZIPs.

Outputs:

```text
data/raw/manifest.jsonl
data/raw/snapshots/CZCE_OFFICIAL_HISTORY_QUOTE/CF/no_biz_date/
data/core/CF/core_quote_daily.parquet
reports/research/official_history/
```

## Human Review Required

- official exchange field interpretation
- volume, open interest, and turnover unit/sidedness
- turnover unit interpretation
- contract rule and last-trading-day review before any trading use

## Follow-Up

After the three annual archives are connected, run data quality on representative
dates and then use the existing R20/R21/R22 validation pack against the real core
table.
