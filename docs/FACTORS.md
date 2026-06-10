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

D15 implements the report renderer for single factor and backtest reports.
