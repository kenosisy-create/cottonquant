# Research Cost Sensitivity

R18 compares hypothetical cost scenarios on top of R17 multifactor score
directions and R15 forward-return labels.

## Scope

R18 reads normalized research artifacts only:

- input: R17 `research_multifactor_score_daily` Parquet;
- input: R15 `research_forward_return_daily` Parquet;
- output: cost-sensitivity summary CSV/Parquet;
- output: cost-sensitivity warning CSV;
- output: Markdown summary for analyst review.

It does not parse exchange raw files. It does not create target lots, orders,
fills, positions, or production cost approvals.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-cost-sensitivity --start 2024-01-09 --end 2024-01-12 --horizons 1,3,5 --score-path data/research/CF/multifactor/CF_2024-01-09_2024-01-12_multifactor_score_daily.parquet --forward-return-path data/research/CF/returns/CF_2024-01-09_2024-01-12_forward_return_daily.parquet --scenario-cost-bps no_cost=0,normal_cost=5,conservative_cost=10
```

Useful options:

- `--horizons`: comma-separated positive horizons, default `1,3,5`.
- `--score-path`: optional R17 score parquet path.
- `--forward-return-path`: optional R15 forward-return parquet path.
- `--scenario-cost-bps`: comma-separated `scenario=bps` pairs. If omitted,
  R18 loads `configs/research_mode.yaml` scenario names and uses research
  placeholders: `no_cost=0`, `normal_cost=5`, `conservative_cost=10`.
- `--use-processed-score/--use-raw-score`: use processed score when available,
  default processed.
- `--run-id`: stable run id for reproducible research outputs.
- `--output-dir`: defaults to `data/research/CF/cost_sensitivity`.
- `--report-output-dir`: defaults to `reports/research/cost_sensitivity`.

## Outputs

Default output templates:

- `data/research/CF/cost_sensitivity/CF_{start}_{end}_cost_sensitivity_summary.parquet`
- `data/research/CF/cost_sensitivity/CF_{start}_{end}_cost_sensitivity_summary.csv`
- `data/research/CF/cost_sensitivity/CF_{start}_{end}_cost_sensitivity_warnings.csv`
- `reports/research/cost_sensitivity/CF_{start}_{end}_cost_sensitivity.md`

## Calculation

For each matched score/forward-return observation:

```text
direction = sign(score)
gross = direction * forward_return
net = gross - round_turn_cost_bps / 10000
```

Flat zero-score observations do not pay cost in R18 because they represent no
research signal direction.

## Warning Behavior

R18 writes warnings instead of treating costs as approved:

- `COST_SCENARIO_ASSUMPTION_REQUIRES_REVIEW`: every scenario is a hypothetical
  research assumption until cost parameters are reviewed.
- `COST_SENSITIVITY_JOINED_NO_OBSERVATIONS`: R17 scores and R15 forward returns
  have no overlapping dates.

## Research Boundary

R18 is a sensitivity summary for analyst review. It is not a reviewed production
fee, slippage, or impact model. It must not be used as production trading cost
approval.

## Human Review Required

R18 keeps these explicit gates:

- `cost_scenario_bps`;
- `round_turn_cost_definition`;
- `score_direction_to_position_mapping`.

## Next Step

R19 now generates a daily CF research brief from data quality, mapping state,
factor diagnostics, backtest evidence, multifactor score, cost sensitivity, and
tomorrow's watch items. R20 now adds a one-command research pipeline. R21 now
adds lightweight replay. R22 expansion gate now completes the current R-series
route.
