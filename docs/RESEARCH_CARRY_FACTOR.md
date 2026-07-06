# Research Carry Factor

R12 adapts the existing `carry_nf_v1` factor into the CF research workbench
output path fixed by R10.

## Scope

R12 reads normalized artifacts only:

- input: `core_quote_daily.parquet`;
- generated input: CF contract master from product config and official CZCE
  trading calendar;
- output: `research_factor_value_daily` rows for `carry_nf_v1`;
- output: R10 warning log rows for missing carry legs, contract-rule review
  gates, and carry-tenor assumptions.

It does not parse exchange raw files and does not create trading instructions.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-carry-factor --start 2024-01-09 --end 2024-01-09 --core-quote-path data/core/CF/core_quote_daily.parquet
```

Useful options:

- `--run-id`: stable run id for reproducible research outputs.
- `--calendar-path`: explicit official trading calendar CSV.
- `--output-dir`: defaults to `data/research/CF/factors`.
- `--report-output-dir`: defaults to `reports/research/factors`.

R12 currently supports one calendar year per run because last-trading-day logic
is generated from the official calendar for that year.

## Outputs

Default output templates:

- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.csv`
- `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv`
- `reports/research/factors/CF_{start}_{end}_carry_factor.md`

The factor value rows follow `research_factor_value_daily.v1` and preserve
non-empty quote `input_snapshot_ids`.

## Warning Behavior

R12 writes warnings instead of silently filling missing values:

- `CARRY_HUMAN_REVIEW_REQUIRED`: factor registry or carry rule still has review fields.
- `CARRY_RULE_HUMAN_REVIEW_REQUIRED`: contract or carry rule needs human review.
- `CARRY_FEWER_THAN_TWO_LEGS`: a date lacks both near and far carry legs.
- `CARRY_CONTRACT_NOT_IN_MASTER`: a quote contract is not in generated master data.
- `CARRY_SETTLE_MISSING`: a required settlement price is missing.
- `CARRY_NO_ROWS_IN_RANGE`: no factor rows were produced for the requested window.

## Human Review Required

Carry currently keeps these explicit gates:

- factor owner / status fields from the registry;
- `carry_tenor_rule`;
- CF last-trading-day rule and official field/unit assumptions inherited from
  product config review.

## Next Step

R14 turns all four factor value outputs into daily diagnostic states. R15 now
computes T+1-safe forward returns for historical support checks. R16 now runs
single-factor research backtest summaries. R17 now writes equal-weight
multifactor score diagnostics. R18 now compares cost sensitivity summaries.
R19 now generates the daily CF research brief. R20 now adds the one-command
research pipeline. R21 now adds lightweight replay. R22 expansion gate now
completes the current R-series route.
