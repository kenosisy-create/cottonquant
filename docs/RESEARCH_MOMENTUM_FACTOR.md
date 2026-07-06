# Research Momentum Factor

R11 adapts the existing `mom_20_v1` factor into the CF research workbench output
path fixed by R10.

## Scope

R11 reads normalized research artifacts only:

- input: `research_continuous_price_daily` from R09 continuous prices;
- output: `research_factor_value_daily` rows for `mom_20_v1`;
- output: R10 warning log rows for lookback gaps and human-review gates.

It does not parse exchange raw files and does not create trading instructions.
Continuous prices remain signal objects only.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-momentum-factor --start 2024-01-21 --end 2024-01-21 --continuous-price-path data/research/CF/continuous/CF_2024-01-01_2024-01-21_settle_continuous_price_daily.parquet
```

Useful options:

- `--run-id`: stable run id for reproducible research outputs.
- `--lookback-periods`: default `20`.
- `--price-field`: default `settle`.
- `--output-dir`: defaults to `data/research/CF/factors`.
- `--report-output-dir`: defaults to `reports/research/factors`.

For a narrow target window, pass a continuous-price file that includes enough
pre-window history for the lookback. The function filters output rows to
`start <= trade_date <= end` and never uses rows after `end`.

## Outputs

Default output templates:

- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.csv`
- `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv`
- `reports/research/factors/CF_{start}_{end}_momentum_factor.md`

The factor value rows follow `research_factor_value_daily.v1` and preserve
non-empty `input_snapshot_ids`.

## Warning Behavior

R11 writes warnings instead of silently filling missing values:

- `MOMENTUM_HUMAN_REVIEW_REQUIRED`: factor registry still has review fields.
- `MOMENTUM_LOOKBACK_INSUFFICIENT`: the continuous price input has too few rows.
- `MOMENTUM_NO_ROWS_IN_RANGE`: no factor rows were produced for the requested
  output window.

## Human Review Required

The momentum formula is implemented, but registry ownership and final threshold
interpretation still require human review before R14 can turn values into
long/short/neutral/unknown states.

## Next Step

R14 turns all four factor value outputs into daily diagnostic states. R15 now
computes T+1-safe forward returns for historical support checks. R16 now runs
single-factor research backtest summaries. R17 now writes equal-weight
multifactor score diagnostics. R18 now compares cost sensitivity summaries.
R19 now generates the daily CF research brief. R20 now adds the one-command
research pipeline. R21 now adds lightweight replay. R22 expansion gate now
completes the current R-series route.
