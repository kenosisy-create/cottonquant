# Daily Backtest

D16 adds a minimal daily backtest engine.

## Scope

The D16 engine is a single-factor fixed-lot MVP:

- factor value > 0: target `+1` lot
- factor value < 0: target `-1` lot
- factor value = 0: target `0` lots

D17 adds equal-weight multifactor scoring and target lot generation. The D16
single-factor path remains available for focused tests, while D17 target lot rows
can feed `run_daily_backtest()` directly.

## D17 Multifactor Targets

Functions:

```python
from cotton_factor.research import build_equal_weight_scores
from cotton_factor.backtest import build_target_lots_from_scores
```

Rules:

- scores are built on the signal object, usually `CF.C1`
- default score id is `cf_equal_weight_v1`
- each configured factor has equal weight
- dates with missing required factors are skipped by default
- target lots use the sign of the score
- target rows use D9 `core_trade_mapping_daily` for T+1 execution date and real
  `target_contract`
- blocked trade mappings become blocked target rows with `target_lots=0`

## Execution Boundary

Inputs:

- `research_factor_value_daily`
- `core_trade_mapping_daily`
- `core_quote_daily`
- `core_contract_master`

Rules:

- signal date is T
- execution date comes from D9 `core_trade_mapping_daily`
- fills use `target_contract`, which must be a real tradable contract
- continuous signal objects are never used as order/fill/position contracts
- blocked trade mappings create blocked records and warnings
- default execution mode is `next_settle`
- `next_open` is also supported

## Costs

D16 records one cost row per fill through `cost_placeholder_v1`.

The default placeholder has zero fee, slippage, and impact. It emits
`TODO_REQUIRES_HUMAN_REVIEW` warnings for fee, slippage, and impact because cost
parameters are a human review gate.

## Outputs

`run_daily_backtest()` returns:

- orders
- fills
- costs
- position snapshots
- equity curve
- blocked signals
- warnings

The result can provide summary/equity/trade mappings for the D15 report renderer.

## Not Yet In Scope

- volatility targeting
- full production cost model
- OMS connection
- run manifest and artifact bundle
