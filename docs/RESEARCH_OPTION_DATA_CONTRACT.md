# R46 CF Option Data Contract

R46 establishes the CF option data contract before any option IV, surface, PCR,
skew, or futures-option linkage work.

## Scope

- Incoming path: `data/incoming/CF/options/history/`
- Core table path: `data/core/CF/core_option_quote_daily.parquet`
- CLI: `research build-cf-option-data-contract`

R46 does not parse official option files. It only makes the data boundary
visible and testable. Raw/core option parsing starts in R47.

## Core Schema

`core_option_quote_daily` uses these fields:

- `trade_date`
- `option_symbol`
- `underlying_contract`
- `option_type`
- `strike`
- `settle`
- `volume`
- `open_interest`
- `moneyness`
- `liquidity_flag`
- `data_quality_flag`

The registered schema also keeps `schema_version`, `source_snapshot_id`,
`exchange`, and `product_code` for lineage and validation.

## Missing Data Rule

If no local option history file exists, the command writes:

- status: `MISSING_OPTION_HISTORY`
- warning CSV row: `MISSING_OPTION_HISTORY`
- schema-only empty core parquet
- Markdown/JSON/manifest reports

This is intentional. The system must not silently skip option data.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-option-data-contract --source-dir data/incoming/CF/options/history --core-output-dir data/core --report-output-dir reports/research/option_data_contract
```

## Research Boundary

- R46 does not create option signals.
- R46 does not calculate IV or Greeks.
- R46 does not change `option_signal=not_connected` in the signal matrix.
- R47 must preserve raw option files and then normalize into core.
- R48 may build IV/surface only after model assumptions are explicitly marked.
- R49 may use option data only as futures-signal confirmation, divergence, or
  volatility-risk context.

## Human Review Required

- official option field interpretation
- option symbol format
- underlying contract mapping
- moneyness definition
- liquidity thresholds
- deep OTM and near-expiry filters
