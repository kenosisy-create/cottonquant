# Research Single-Factor Backtests

R16 builds single-factor research summaries from R14 factor diagnostics and R15
forward-return labels.

## Scope

R16 reads normalized research artifacts only:

- input: R14 `research_factor_diagnostic_daily` Parquet;
- input: R15 `research_forward_return_daily` Parquet;
- output: `research_factor_evaluation` metric rows;
- output: single-factor warning CSV;
- output: Markdown summary for analyst review.

It does not parse exchange raw files and does not create trading instructions.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-single-factor-backtest --start 2024-01-09 --end 2024-01-12 --factor-ids mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1 --horizons 1,3,5 --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet --forward-return-path data/research/CF/returns/CF_2024-01-09_2024-01-12_forward_return_daily.parquet
```

Useful options:

- `--factor-ids`: comma-separated factor IDs, default all four MVP factors.
- `--horizons`: comma-separated positive horizons, default `1,3,5`.
- `--use-processed-value/--use-raw-value`: use processed factor values when
  available, default processed.
- `--run-id`: stable run id for reproducible research outputs.
- `--output-dir`: defaults to `data/research/CF/backtests`.
- `--report-output-dir`: defaults to `reports/research/backtests`.

## Outputs

Default output templates:

- `data/research/CF/backtests/CF_{start}_{end}_single_factor_evaluation.parquet`
- `data/research/CF/backtests/CF_{start}_{end}_single_factor_evaluation.csv`
- `data/research/CF/backtests/CF_{start}_{end}_single_factor_backtest_warnings.csv`
- `reports/research/backtests/CF_{start}_{end}_single_factor_backtest.md`

The evaluation rows follow `research_factor_evaluation.v1` and preserve
non-empty `input_snapshot_ids`.

## Metrics

R16 reuses the existing research evaluator and writes metrics such as:

- `observation_count`;
- `mean_factor_value`;
- `mean_forward_return`;
- `pearson_ic`;
- `spearman_rank_ic`;
- `directional_accuracy`.

Metrics that cannot be computed because a series is constant or the joined
sample is empty are surfaced as warnings instead of being filled.

## Warning Behavior

R16 writes warnings instead of silently treating missing evidence as neutral:

- `SINGLE_FACTOR_UNKNOWN_DIAGNOSTICS_SKIPPED`: R14 diagnostic rows are unknown.
- `SINGLE_FACTOR_NO_DIAGNOSTIC_ROWS`: no usable diagnostic rows for a factor.
- `SINGLE_FACTOR_JOINED_NO_OBSERVATIONS`: diagnostics and forward returns do
  not overlap.
- `SINGLE_FACTOR_METRIC_NOT_COMPUTABLE`: a metric cannot be computed.
- `SINGLE_FACTOR_EVALUATION_ERROR`: evaluator input is invalid.

## Research Boundary

R16 is evidence support for research. It does not approve trades, orders,
positions, or production execution. Any use in a daily brief must preserve
warnings and human-review gates.

## Human Review Required

R16 keeps these explicit gates:

- `single_factor_metric_set`;
- `minimum_observation_count`.

## Next Step

R17 now writes equal-weight multifactor diagnostics with explicit factor weights
and missing-factor handling. R18 now compares research cost sensitivity
summaries. R19 now generates the daily CF research brief. R20 now adds the
one-command research pipeline. R21 now adds lightweight replay. R22 expansion
gate now completes the current R-series route.
