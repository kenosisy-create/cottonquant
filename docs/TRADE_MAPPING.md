# Trade Mapping

D9 builds `core_trade_mapping_daily` from signal-object chain rows to real
tradable contracts.

## Rules

- Input signal object remains `CF.C1`; output `target_contract` must be a real
  contract such as `CF401`.
- Every row has `trade_date` for the T-day post-settlement signal and
  `execution_date` for the next trading day.
- `execution_date` must be strictly after `trade_date`.
- If the mapped contract cannot be traded, the row is blocked with
  `block_reason` and `execution_eligible=false`.
- LTD buffers are checked again at execution time, because T+1 can move an
  otherwise valid signal into the final guard window.
- Optional normalized settlement rows can block execution through trading status
  such as `halted` or `limit_only`.

## Block Reasons

- `ltd_buffer_execution_block`
- `settlement_status_halted`
- `settlement_status_limit_only`
- `unknown_target_contract`

## CLI

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-trade-mapping --product CF --start 2024-01-09 --end 2024-01-12 --quote-fixture tests/fixtures/core_quote_daily_cf_chain_sample.csv --ltd-buffer-days 2
```

The command currently rebuilds chain map rows from the normalized quote fixture,
then builds trade mapping rows. D10+ should consume `core_chain_map_daily` for
continuous prices and `core_trade_mapping_daily` for execution/backtest objects.
