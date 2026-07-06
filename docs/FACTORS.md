# Factor Framework

D11 established the factor framework. D12 added carry and momentum. D13 adds
curve slope and OI pressure, so the first four MVP factor formulas are now
available as research-layer APIs. D14 adds forward returns and the single factor
evaluator.

## Registry

Factor metadata lives in `configs/factor_registry.yaml`.

Each factor must declare:

- `family`
- `version`
- `owner`
- `status`
- `required_inputs`

`required_inputs` must be registered normalized table names from the core or
research layers. Research factors cannot depend on raw exchange files.

The current MVP factors are:

- `carry_nf_v1`: implemented in D12
- `mom_20_v1`: implemented in D12
- `curve_slope_v1`: implemented in D13
- `oi_pressure_v1`: implemented in D13

The current owner values are intentionally `TODO_REQUIRES_HUMAN_REVIEW`. D11
allows those values, but exposes them through `FactorDefinition.human_review_required`
instead of hiding them.

## Inputs

`FactorInputBundle` carries normalized row objects keyed by table name.
`validate_factor_dependencies()` checks that every required input table is
present, non-empty by default, and made of the expected schema row type.

This preserves the project boundary:

- raw snapshots stay immutable and outside research formulas
- core facts keep source lineage
- research derived tables are the only permitted derived inputs
- continuous prices remain signal objects only

## Output Rows

`build_factor_rows()` wraps factor observations into
`research_factor_value_daily` rows. Every row must keep non-empty
`input_snapshot_ids`, so factor lineage is enforced before D12/D13 formulas are
written.

## D12 Formulas

### `mom_20_v1`

Input table: `research_continuous_price_daily`.

Formula:

```text
momentum = adjusted_price_T / adjusted_price_T-20 - 1
```

The implementation uses the T-day adjusted continuous settlement series for the
signal object, sorted by trade date. It emits rows only after the 20-observation
lookback is available. It does not read T+1 data.

## Research Workbench R11

R11 reuses `mom_20_v1` and writes research-workbench artifacts under the R10
contract:

- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.csv`
- `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv`
- `reports/research/factors/CF_{start}_{end}_momentum_factor.md`

The R11 builder reads `research_continuous_price_daily` only. It filters output
rows to the requested date range and does not use rows after `end`. If lookback
history is insufficient, it writes warning rows instead of filling zeros.

### `carry_nf_v1`

Input tables: `core_quote_daily`, `core_contract_master`.

Formula:

```text
carry = (far_settle / near_settle - 1) * 365 / tenor_days
```

For each trade date, the implementation chooses the nearest and next-nearest
active contracts by contract tenor. It prefers `last_trade_date` as tenor. If
`last_trade_date` is missing, it falls back to the first day of the delivery
month and emits a `TODO_REQUIRES_HUMAN_REVIEW` warning.

This carry formula is a D12 MVP research convention, not a finalized production
rule. The registry owner remains `TODO_REQUIRES_HUMAN_REVIEW`.

## Research Workbench R12

R12 reuses `carry_nf_v1` and writes research-workbench artifacts under the R10
contract:

- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.csv`
- `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv`
- `reports/research/factors/CF_{start}_{end}_carry_factor.md`

The R12 builder reads `core_quote_daily.parquet` and generates CF contract master
rows from product config plus the official CZCE trading calendar. Carry tenor
and contract-rule assumptions remain visible as warning rows until human review
closes them.

## D13 Formulas

### `curve_slope_v1`

Input tables: `core_quote_daily`, `core_chain_map_daily`, `core_contract_master`.

Formula:

```text
curve_slope = next_far_settle / mapped_contract_settle - 1
```

For each signal date, the implementation uses `core_chain_map_daily` to find the
mapped signal contract, then picks the next farther active contract using
`core_contract_master` tenor information. It prefers `last_trade_date` as tenor.
If `last_trade_date` is missing, it falls back to the first day of the delivery
month and emits a `TODO_REQUIRES_HUMAN_REVIEW` warning.

### `oi_pressure_v1`

Input tables: `core_quote_daily`, `core_chain_map_daily`.

Formula:

```text
oi_pressure = settle_return * open_interest_change_ratio
settle_return = settle_T / settle_previous_same_contract - 1
open_interest_change_ratio =
  (open_interest_T - open_interest_previous_same_contract)
  / open_interest_previous_same_contract
```

The implementation computes pressure only for the mapped contract from
`core_chain_map_daily`. It uses the current T quote and the latest prior quote of
the same real contract. If there is no prior same-contract quote, it skips that
date rather than stitching across a roll.

Both D13 formulas are MVP research conventions and still require human review
before being treated as final production factor definitions.

## Research Workbench R13

R13 reuses `curve_slope_v1` and `oi_pressure_v1` and writes research-workbench
artifacts under the R10 contract:

- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.csv`
- `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv`
- `reports/research/factors/CF_{start}_{end}_structure_factors.md`

The R13 builder reads normalized `core_quote_daily` rows and R08
`core_chain_map_daily` rows. It generates CF contract master rows from product
config plus the official CZCE calendar. Missing far-leg quotes, missing mapped
quotes, and missing prior same-contract quotes are warning rows, not silent
zero factor values.

## Research Workbench R14

R14 reads the shared R10 factor value and warning artifacts from R11-R13 and
writes daily `research_factor_diagnostic_daily` rows:

- `data/research/CF/factors/CF_{start}_{end}_factor_diagnostic_daily.parquet`
- `data/research/CF/factors/CF_{start}_{end}_factor_diagnostic_daily.csv`
- `reports/research/factors/CF_{start}_{end}_factor_diagnostics.md`

The MVP diagnostic rule maps positive values to `long`, negative values to
`short`, zero values to `neutral`, and missing factor/date observations to
`unknown`. The rule is a research sign heuristic. Final thresholds and
direction mapping remain `HUMAN_REVIEW_REQUIRED`.

## Research Workbench R15

R15 reads R08 `core_trade_mapping_daily` rows and normalized `core_quote_daily`
rows, then writes multi-horizon historical labels:

- `data/research/CF/returns/CF_{start}_{end}_forward_return_daily.parquet`
- `data/research/CF/returns/CF_{start}_{end}_forward_return_daily.csv`
- `data/research/CF/returns/CF_{start}_{end}_forward_return_warnings.csv`
- `reports/research/returns/CF_{start}_{end}_forward_returns.md`

Forward returns are labels for historical evaluation. They use future outcome
quotes by design, but they must not become same-day signal inputs. Entry
contracts come from R08 real-contract trade mapping, not continuous contracts.

## Research Workbench R16

R16 reads R14 factor diagnostics and R15 forward returns, then writes
single-factor evaluation metrics:

- `data/research/CF/backtests/CF_{start}_{end}_single_factor_evaluation.parquet`
- `data/research/CF/backtests/CF_{start}_{end}_single_factor_evaluation.csv`
- `data/research/CF/backtests/CF_{start}_{end}_single_factor_backtest_warnings.csv`
- `reports/research/backtests/CF_{start}_{end}_single_factor_backtest.md`

Unknown diagnostic states are skipped with warnings. The metrics are research
evidence only and do not approve trading or production execution.

## D14 Forward Returns

Input tables: `core_trade_mapping_daily`, `core_quote_daily`.

Forward returns are evaluation labels, not trading orders. They use D9 trade
mapping to preserve the architecture boundary:

```text
signal date = T
entry date = execution_date from core_trade_mapping_daily, normally T+1
entry contract = target_contract from core_trade_mapping_daily
exit date = horizon quote observations after entry, same real contract
forward_return = exit_price / entry_price - 1
```

Blocked trade mappings are skipped with warnings. Continuous contracts are not
used as return-bearing trade objects.

Default rule version:

```text
forward_return_real_contract_tplus1_v1
```

## D14 Single Factor Evaluator

Input tables: `research_factor_value_daily`, `research_forward_return_daily`.

The evaluator joins rows by:

```text
signal_object_id + trade_date
```

It emits schema-validated `research_factor_evaluation` metric rows:

- `observation_count`
- `mean_factor_value`
- `mean_forward_return`
- `pearson_ic`
- `spearman_rank_ic`
- `directional_accuracy`

The evaluator is a research diagnostic layer. It does not create orders, fills,
costs, positions, or reports.

## Preprocessing

D11 adds deterministic helpers:

- `winsorize_series()`
- `zscore_series()`
- `rank_series()`

Empty inputs return empty outputs. Constant z-score inputs return zeros. Non-finite
values fail loudly.

## Next Step

The active research-workbench route has already adapted the four MVP factors
through R19: factor outputs, daily diagnostic states, T+1 forward returns,
single-factor research summaries, equal-weight multifactor diagnostics,
research cost sensitivity summaries, and the daily CF research brief. R20 now
adds the one-command research pipeline. R21 now adds lightweight replay. The
R22 expansion gate now completes the current R-series route.
