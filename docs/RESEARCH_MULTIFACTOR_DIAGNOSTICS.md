# Research Multifactor Diagnostics

R17 builds equal-weight multifactor score diagnostics from R14 factor
diagnostic states.

## Scope

R17 reads normalized research artifacts only:

- input: R14 `research_factor_diagnostic_daily` Parquet;
- output: `research_multifactor_score_daily` score rows;
- output: multifactor warning CSV;
- output: Markdown diagnostics for analyst review.

It does not parse exchange raw files. It does not create target lots, orders,
positions, execution approvals, or production trading instructions.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-multifactor-diagnostics --start 2024-01-09 --end 2024-01-12 --factor-ids mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1 --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet
```

Useful options:

- `--factor-ids`: comma-separated factor IDs, default all four MVP factors.
- `--use-processed-value/--use-raw-value`: use processed factor values when
  available, default processed.
- `--require-all-factors/--allow-missing-factors`: controls whether each score
  date must contain every requested factor.
- `--run-id`: stable run id for reproducible research outputs.
- `--score-id`: score identifier, default `cf_equal_weight_v1`.
- `--output-dir`: defaults to `data/research/CF/multifactor`.
- `--report-output-dir`: defaults to `reports/research/multifactor`.

## Outputs

Default output templates:

- `data/research/CF/multifactor/CF_{start}_{end}_multifactor_score_daily.parquet`
- `data/research/CF/multifactor/CF_{start}_{end}_multifactor_score_daily.csv`
- `data/research/CF/multifactor/CF_{start}_{end}_multifactor_warnings.csv`
- `reports/research/multifactor/CF_{start}_{end}_multifactor_diagnostics.md`

The score rows follow `research_multifactor_score_daily.v1` and preserve
non-empty `input_snapshot_ids`.

## Weighting

R17 uses explicit equal weights across the selected factor IDs. The weight map
is returned in the CLI summary and written into the Markdown report.

This is intentionally simple. Factor direction alignment and weighting changes
remain research decisions and must not be silently adjusted inside the CLI.

## Warning Behavior

R17 writes warnings instead of silently treating missing evidence as neutral:

- `MULTIFACTOR_UNKNOWN_DIAGNOSTICS_SKIPPED`: R14 diagnostic rows are unknown or
  have no raw value.
- `MULTIFACTOR_MISSING_REQUIRED_FACTORS`: at least one requested factor is
  missing on a score date when `--require-all-factors` is active.
- `MULTIFACTOR_SCORE_NO_ROWS`: no score rows can be built from the selected
  diagnostics.
- `MULTIFACTOR_SCORE_BUILD_ERROR`: the score builder rejected the input.

## Research Boundary

R17 is a diagnostic layer for combining factor evidence. It is not a portfolio
optimizer and not a trading system. Any downstream daily brief must preserve
missing-factor warnings and human-review gates.

## Human Review Required

R17 keeps these explicit gates:

- `multifactor_weight_scheme`;
- `factor_direction_alignment`;
- `missing_factor_policy`.

## Next Step

R18 now compares cost sensitivity summaries while keeping cost assumptions as
human-review items. R19 now generates the daily CF research brief. R20 now adds
the one-command research pipeline. R21 now adds lightweight replay. R22
expansion gate now completes the current R-series route.
