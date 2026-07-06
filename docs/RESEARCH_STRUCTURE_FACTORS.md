# Research Structure Factors

R13 adapts `curve_slope_v1` and `oi_pressure_v1` into the CF research workbench
output path fixed by R10.

## Scope

R13 reads normalized artifacts only:

- input: `core_quote_daily.parquet`;
- input: R08 `core_chain_map_daily` Parquet;
- generated input: CF contract master from product config and official CZCE
  trading calendar;
- output: `research_factor_value_daily` rows for `curve_slope_v1` and
  `oi_pressure_v1`;
- output: R10 warning log rows for missing mapped quotes, missing far legs,
  missing prior same-contract quotes, and human-review gates.

It does not parse exchange raw files and does not create trading instructions.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-structure-factors --start 2024-01-09 --end 2024-01-09 --core-quote-path data/core/CF/core_quote_daily.parquet --chain-map-path data/research/CF/mapping/CF_2024-01-09_2024-01-09_chain_map_daily.parquet
```

Useful options:

- `--run-id`: stable run id for reproducible research outputs.
- `--calendar-path`: explicit official trading calendar CSV.
- `--output-dir`: defaults to `data/research/CF/factors`.
- `--report-output-dir`: defaults to `reports/research/factors`.

R13 currently supports one calendar year per run because contract tenor and
last-trading-day logic are generated from that year's official calendar.

## Outputs

Default output templates:

- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.csv`
- `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv`
- `reports/research/factors/CF_{start}_{end}_structure_factors.md`

The factor value rows follow `research_factor_value_daily.v1` and preserve
non-empty quote and chain-map `input_snapshot_ids`.

## Warning Behavior

R13 writes warnings instead of silently filling missing values:

- `CURVE_SLOPE_HUMAN_REVIEW_REQUIRED`: curve slope registry or far-leg rule needs review.
- `CURVE_SLOPE_MAPPED_QUOTE_MISSING`: mapped near-leg quote is missing.
- `CURVE_SLOPE_NO_FAR_LEG`: no farther quoted contract is available for the date.
- `CURVE_SLOPE_NO_ROWS_IN_RANGE`: no curve rows were produced for the window.
- `OI_PRESSURE_HUMAN_REVIEW_REQUIRED`: OI pressure matching rule needs review.
- `OI_PRESSURE_MAPPED_QUOTE_MISSING`: mapped current quote is missing.
- `OI_PRESSURE_NO_PRIOR_MATCH`: no prior same-contract quote was available.
- `OI_PRESSURE_NO_ROWS_IN_RANGE`: no OI pressure rows were produced for the window.

## Human Review Required

R13 keeps these explicit gates:

- `curve_slope_far_leg_rule`;
- `oi_pressure_prior_contract_matching`;
- factor owner / status fields from the registry;
- official field/unit assumptions inherited from product config review.

## Next Step

R14 now builds the daily factor diagnostic state table from the four factor
outputs and keeps `unknown` as a first-class state when inputs or rules are
missing. R15 now computes T+1-safe forward returns. R16 now runs single-factor
research backtest summaries. R17 now writes equal-weight multifactor score
diagnostics. R18 now compares cost sensitivity summaries. R19 now generates the
daily CF research brief. R20 now adds the one-command research pipeline. R21 now
adds lightweight replay. R22 expansion gate now completes the current R-series
route.
