# CF Research Continuous Price

R09 adds research-mode continuous price artifacts and roll diagnostics for CF.

This layer consumes normalized core quotes and R08 chain mapping only. It does
not read raw exchange files and does not create tradable contracts.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-continuous --start 2024-01-09 --end 2024-01-12
```

Useful options:

- `--core-quote-path`: explicit `core_quote_daily.parquet` input.
- `--chain-map-path`: explicit R08 chain-map parquet input.
- `--price-field`: quote field for the continuous series, default `settle`.
- `--output-dir`: output directory for CSV/Parquet continuous files.
- `--report-output-dir`: output directory for Markdown diagnostics.

## Inputs

Default inputs:

```text
data/core/CF/core_quote_daily.parquet
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_chain_map_daily.parquet
```

## Outputs

Default outputs:

```text
data/research/CF/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_continuous_price_daily.parquet
data/research/CF/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_continuous_price_daily.csv
data/research/CF/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_roll_diagnostics.csv
reports/research/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_continuous.md
```

## Roll Diagnostics

The roll diagnostics CSV includes:

- `trade_date`
- `signal_object_id`
- `roll_from_contract`
- `roll_to_contract`
- `roll_gap`
- `adjustment`
- `cumulative_adjustment`
- `chain_switch_reason`
- `input_snapshot_ids`

## Boundary

Continuous prices are signal objects only. Execution, backtest target contracts,
orders, fills, and positions must continue to use R08 trade mapping.
