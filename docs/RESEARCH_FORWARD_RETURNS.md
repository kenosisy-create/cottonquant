# Research Forward Returns

R15 builds T+1-safe historical forward-return labels for CF factor evaluation.

## Scope

R15 reads normalized artifacts only:

- input: R08 `core_trade_mapping_daily` Parquet;
- input: normalized `core_quote_daily.parquet`;
- output: `research_forward_return_daily` rows;
- output: forward-return warning CSV;
- output: Markdown summary for analyst review.

It does not parse exchange raw files and does not create trading instructions.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-forward-returns --start 2024-01-09 --end 2024-01-12 --horizons 1,3,5 --core-quote-path data/core/CF/core_quote_daily.parquet --trade-mapping-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_trade_mapping_daily.parquet
```

Useful options:

- `--horizons`: comma-separated positive horizons, default `1,3,5`.
- `--entry-price-field`: default `settle`.
- `--exit-price-field`: default `settle`.
- `--run-id`: stable run id for reproducible research outputs.
- `--output-dir`: defaults to `data/research/CF/returns`.
- `--report-output-dir`: defaults to `reports/research/returns`.

## Outputs

Default output templates:

- `data/research/CF/returns/CF_{start}_{end}_forward_return_daily.parquet`
- `data/research/CF/returns/CF_{start}_{end}_forward_return_daily.csv`
- `data/research/CF/returns/CF_{start}_{end}_forward_return_warnings.csv`
- `reports/research/returns/CF_{start}_{end}_forward_returns.md`

The forward-return rows follow `research_forward_return_daily.v1` and preserve
non-empty `input_snapshot_ids`.

## Research Boundary

Forward returns are historical evaluation labels. They are allowed to use future
outcome quotes for historical validation, but they must not become same-day
signals or trading instructions.

The entry contract comes from R08 `core_trade_mapping_daily`, so backtest and
evaluation labels use real tradable contracts rather than continuous contracts.
The schema enforces `execution_date > trade_date` and `exit_date >
execution_date`.

## Warning Behavior

R15 writes warnings instead of silently filling labels:

- `FORWARD_RETURN_BLOCKED_MAPPING`: R08 trade mapping blocks execution.
- `FORWARD_RETURN_TARGET_CONTRACT_MISSING`: mapping lacks a tradable contract.
- `FORWARD_RETURN_ENTRY_QUOTE_MISSING`: entry-date quote is missing.
- `FORWARD_RETURN_EXIT_QUOTE_MISSING`: horizon exit quote is missing.
- `FORWARD_RETURN_NO_ROWS`: one horizon produced no rows.

## Human Review Required

R15 keeps these explicit gates:

- `forward_return_horizon_set`;
- `forward_return_price_basis`.

## Next Step

R16 now runs single-factor research backtest summaries from R14 diagnostic states
and R15 forward-return labels. R17 now writes equal-weight multifactor score
diagnostics. R18 now compares cost sensitivity summaries. R19 now generates the
daily CF research brief. R20 now adds the one-command research pipeline. R21 now
adds lightweight replay. R22 expansion gate now completes the current R-series
route.
