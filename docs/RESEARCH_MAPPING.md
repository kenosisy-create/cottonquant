# CF Research Mapping

R08 adds research-mode chain and trade mapping outputs for CF.

This layer consumes normalized core facts only. It must not read `data/incoming`
or raw exchange files directly.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-mapping --start 2024-01-09 --end 2024-01-12 --ltd-buffer-days 2
```

Useful options:

- `--core-quote-path`: explicit `core_quote_daily.parquet` input.
- `--output-dir`: output directory for CSV/Parquet mapping files.
- `--report-output-dir`: output directory for Markdown mapping summary.
- `--calendar-path`: explicit official trading calendar CSV.
- `--ltd-buffer-days`: explicit last-trading-day guard buffer.
- `--min-volume`: minimum volume for chain-map eligibility.

## Inputs

R08 reads:

```text
data/core/CF/core_quote_daily.parquet
configs/calendars/CZCE_YYYY_OFFICIAL.csv
configs/products/CF.yaml
```

An official calendar is required. R08 does not silently fall back to a
provisional weekday calendar because T+1 execution and LTD guards depend on
official trading days.

## Outputs

Default output files:

```text
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_chain_map_daily.parquet
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_chain_map_daily.csv
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_trade_mapping_daily.parquet
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_trade_mapping_daily.csv
reports/research/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_mapping.md
```

The Markdown summary includes:

- chain row count
- trade row count
- blocked trade row count
- switch-reason counts
- block-reason counts
- warnings inherited from calendar, contract master, chain map, and trade mapping

## Research Rules

- Chain rows map the signal object `CF.C1` to a real contract for signal use.
- Trade rows map the signal object to a real target contract for T+1 execution.
- `execution_date` must be strictly later than `trade_date`.
- Blocked trade rows keep `target_contract=null`, `execution_eligible=false`,
  and an explicit `block_reason`.
- Continuous contracts are still signal objects only.
- R08 does not generate orders or fills.

## Human Review Boundary

R07 contract-rule review may still contain production blockers. R08 can proceed
for research only because those blockers are surfaced in warnings and review
artifacts. Production confidence still requires closing the human-review rows.
