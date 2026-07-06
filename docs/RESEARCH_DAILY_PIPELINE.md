# CF Daily Research Pipeline

R20 adds a one-command research workflow for the CF daily workbench.

The pipeline runs existing R04-R19 modules in order. It is a research
convenience layer, not a production scheduler, release process, service API, or
trading approval system.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-daily-pipeline --date 2024-01-10 --start 2024-01-09 --end 2024-01-12 --input-path data/incoming/CF/2024-01-10 --horizons 1,3,5 --scenario-cost-bps no_cost=0,normal_cost=5,conservative_cost=10
```

Important options:

- `--date`: the CF trade date for the daily brief.
- `--input-path`: local CF file or folder preserved by R04 before parsing.
- `--start` / `--end`: research artifact window used by mapping, factors,
  returns, backtests, cost sensitivity, and the daily brief.
- `--raw-output-dir`, `--core-output-dir`, `--research-output-root`, and
  `--report-output-root`: optional roots for isolated test or replay runs.
- `--lookback-periods`: momentum lookback. A short window may not produce
  momentum rows unless enough prior continuous-price rows exist.
- `--allow-missing-factors`: lets R17 score only available non-unknown factors.
  The default requires all four MVP factors.

## Step Order

R20 runs:

1. R04 raw preservation.
2. R05 core quote normalization.
3. R06 data quality gate.
4. R07 contract rule review.
5. R08 chain and trade mapping.
6. R09 continuous price artifacts.
7. R10 factor output contract.
8. R11-R13 factor value and warning outputs.
9. R14 factor diagnostic states.
10. R15 forward-return labels.
11. R16 single-factor research backtest summaries.
12. R17 equal-weight multifactor score diagnostics.
13. R18 cost sensitivity summaries.
14. R19 daily research brief.

If R06 has critical data-quality failures, R20 stops after writing the quality
artifacts and pipeline run log.

## Outputs

R20 writes the usual R04-R19 artifacts plus:

- `reports/research/pipeline/CF_{date}_{run_id}_pipeline.md`
- `reports/research/pipeline/CF_{date}_{run_id}_pipeline.json`

The JSON file contains:

- completed step list;
- each step's compact summary;
- artifact paths;
- accumulated human-review fields.

## Research Boundary

R20 does not relax the research correctness rules:

- research functions still read normalized core/research artifacts only;
- continuous contracts remain signal objects only;
- forward returns and backtests use real tradable contracts from R08;
- T-day post-settlement signals are for T+1 or later use;
- cost, factor thresholds, contract rules, and roll assumptions remain human
  review items.

## Next Step

R21 now adds lightweight replay against preserved R20 outputs. R22 expansion
gate now completes the current R-series route.
