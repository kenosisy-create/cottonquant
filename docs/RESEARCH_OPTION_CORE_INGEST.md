# R47 CF Option Raw/Core Ingest

R47 connects local CF option history files into the research workbench without
building option strategies.

## Scope

- Preserve local option history files as raw snapshots.
- Parse option symbol, C/P, strike, and underlying contract.
- Write `data/core/CF/core_option_quote_daily.parquet`.
- Write option quality CSV/Markdown/JSON/manifest reports.
- Tag low-liquidity, deep-OTM proxy, missing underlying price, missing settle,
  and near-expiry review rows.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-option-history --source-dir data/incoming/CF/options/history --raw-root data/raw --core-output-dir data/core --core-quote-path data/core/CF/core_quote_daily.parquet --report-output-dir reports/research/option_core_ingest
```

## Accepted Local Files

- `.csv`
- `.txt`
- `.xlsx`
- `.xls`
- `.zip`

The current parser expects a visible `trade_date` and `option_symbol` column.
It can infer `underlying_contract`, `option_type`, and `strike` from symbols
like `CF401C15000`, `CF401-C-15000`, or `CF-401-P-15000`.

## Risk Tags

- `LOW_LIQUIDITY_VOLUME`
- `LOW_LIQUIDITY_OPEN_INTEREST`
- `DEEP_OTM_PROXY`
- `NEAR_EXPIRY_REVIEW`
- `UNDERLYING_PRICE_MISSING`
- `MISSING_SETTLE`

`moneyness` and `DEEP_OTM_PROXY` are research proxies. Their exact option model
interpretation is deliberately left for R48 human review.

## Research Boundary

- R47 does not calculate IV, Greek, PCR, or skew.
- R47 does not change signal matrix scoring.
- `option_signal` remains `not_connected` until R49.
- Low-liquidity and deep-OTM rows are tagged for filtering; they are not trading
  instructions.
- This report does not constitute trading advice.

## Human Review Required

- official option field interpretation
- option symbol format
- underlying contract mapping
- moneyness definition
- liquidity thresholds
- deep OTM and near-expiry filters
- American option model boundary
