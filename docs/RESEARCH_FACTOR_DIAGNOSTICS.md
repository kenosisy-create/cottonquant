# Research Factor Diagnostics

R14 turns the R10/R11-R13 factor value and warning artifacts into a daily
analyst-facing diagnostic state table.

## Scope

R14 reads normalized research artifacts only:

- input: `research_factor_value_daily` Parquet from R11-R13;
- input: shared R10 factor warning CSV from R11-R13;
- output: `research_factor_diagnostic_daily` rows;
- output: R14 warning rows for missing factor/date observations;
- output: Markdown diagnostic summary for analyst review.

It does not parse exchange raw files and does not create trading instructions.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-factor-diagnostics --start 2024-01-09 --end 2024-01-09 --factor-value-path data/research/CF/factors/CF_2024-01-09_2024-01-09_factor_value_daily.parquet
```

Useful options:

- `--run-id`: stable diagnostics run id for reproducible research outputs.
- `--warning-csv-path`: explicit warning CSV input/output path.
- `--output-dir`: defaults to `data/research/CF/factors`.
- `--report-output-dir`: defaults to `reports/research/factors`.

## Outputs

Default output templates:

- `data/research/CF/factors/CF_{start}_{end}_factor_diagnostic_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_diagnostic_daily.csv`
- `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv`
- `reports/research/factors/CF_{start}_{end}_factor_diagnostics.md`

The diagnostic rows follow `research_factor_diagnostic_daily.v1` and preserve
non-empty `input_snapshot_ids`.

## State Logic

R14 uses an MVP sign heuristic:

- positive factor value -> `long`;
- negative factor value -> `short`;
- zero factor value -> `neutral`;
- missing factor/date value -> `unknown`.

This heuristic is a research diagnostic convention, not a final trading rule.
All diagnostic rows keep `factor_thresholds` in `human_review_required` until
factor thresholds and direction mapping are reviewed.

## Warning Behavior

R14 writes warnings instead of silently filling missing values:

- `R14_MISSING_FACTOR_VALUE`: an expected factor has no value row on a date.

Warnings inherited from R11-R13 remain visible as `warning_flags` and
`human_review_required` fields in the diagnostic table.

## Human Review Required

R14 keeps these explicit gates:

- `factor_thresholds`;
- carry tenor rule inherited from R12;
- curve-slope far-leg rule inherited from R13;
- OI pressure prior-contract matching inherited from R13;
- final long/short/neutral interpretation wording for daily briefs.

## Next Step

R15 now computes T+1-safe forward returns with explicit horizons and price
basis. R16 now runs single-factor research backtest summaries. R17 now writes
equal-weight multifactor score diagnostics. R18 now compares cost sensitivity
summaries. R19 now generates the daily CF research brief. R20 now adds the
one-command research pipeline. R21 now adds lightweight replay. R22 expansion
gate now completes the current R-series route.
