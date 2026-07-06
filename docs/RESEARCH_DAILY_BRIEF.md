# Research Daily Brief

R19 generates an analyst-facing daily CF research brief from existing R06-R18
artifacts.

## Scope

R19 reads normalized research outputs only:

- R06 data-quality CSV;
- R08 chain map and trade mapping Parquet;
- R14 factor diagnostic Parquet;
- R16 single-factor evaluation Parquet;
- R17 multifactor score Parquet;
- R18 cost sensitivity summary Parquet.

It does not parse exchange raw files, recompute factors, create target lots, or
approve trades.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-daily-brief --date 2024-01-09 --start 2024-01-09 --end 2024-01-12 --quality-csv-path reports/research/data_quality/CF_2024-01-09_quality.csv --chain-map-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_chain_map_daily.parquet --trade-mapping-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_trade_mapping_daily.parquet --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet --single-factor-evaluation-path data/research/CF/backtests/CF_2024-01-09_2024-01-12_single_factor_evaluation.parquet --multifactor-score-path data/research/CF/multifactor/CF_2024-01-09_2024-01-12_multifactor_score_daily.parquet --cost-sensitivity-path data/research/CF/cost_sensitivity/CF_2024-01-09_2024-01-12_cost_sensitivity_summary.parquet
```

Useful options:

- `--date`: brief trade date.
- `--start` / `--end`: artifact window. Defaults to `--date` when omitted.
- `--quality-csv-path`: optional R06 quality CSV path.
- `--chain-map-path`: optional R08 chain map parquet path.
- `--trade-mapping-path`: optional R08 trade mapping parquet path.
- `--diagnostic-path`: optional R14 factor diagnostic parquet path.
- `--single-factor-evaluation-path`: optional R16 evaluation parquet path.
- `--multifactor-score-path`: optional R17 score parquet path.
- `--cost-sensitivity-path`: optional R18 cost summary parquet path.
- `--report-output-dir`: defaults to `reports/research/daily_brief`.
- `--run-id`: stable run id for reproducible report outputs.

## Outputs

Default output templates:

- `reports/research/daily_brief/CF_{date}_daily_research_brief.md`
- `reports/research/daily_brief/CF_{date}_daily_research_brief.json`
- `reports/research/daily_brief/CF_{date}_daily_research_brief_warnings.csv`

## Brief Sections

The Markdown brief contains:

- data-quality status and severity counts;
- market structure and T+1 mapping state;
- factor diagnostic states;
- selected single-factor historical evidence metrics;
- multifactor score direction;
- cost sensitivity table;
- tomorrow watch items;
- research boundary and human-review gates.

## Warning Behavior

R19 writes warning rows when:

- critical data-quality checks failed;
- T+1 trade mapping is blocked;
- any factor diagnostic state is `unknown`;
- cost sensitivity rows are used as hypothetical assumptions;
- multifactor score metadata is internally inconsistent.

## Research Boundary

R19 is a daily research reading layer. It summarizes evidence for analyst review
and does not approve trades, orders, target lots, positions, or production
execution.

## Human Review Required

R19 keeps these explicit gates:

- `daily_brief_interpretation`;
- `factor_thresholds`;
- `contract_rule_assumptions`;
- `cost_scenario_bps`.

## Next Step

R20 now adds a one-command research pipeline that runs R04-R19 in order for a
date/window and leaves a simple run log. R21 now adds lightweight replay. R22
should define the expansion gate next.
