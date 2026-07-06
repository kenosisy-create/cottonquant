# Chain Map

D8 builds `core_chain_map_daily` for signal objects such as `CF.C1`.
R08 adds research-mode CSV/Parquet outputs that persist these rows for the
workbench route.

## Inputs

- `core_quote_daily` rows from normalized quote fixtures.
- `core_contract_master` rows from product config.
- `core_trading_calendar` rows. For 2024 CZCE, the default calendar now loads
  `configs/calendars/CZCE_2024_OFFICIAL.csv`.

## Rules

- The ranked main contract is selected by open interest, then volume.
- Contracts inside the explicit LTD buffer are skipped.
- Contracts below `min_volume` are skipped.
- Every produced row has `switch_reason`.
- Chain map rows are signal-object mappings only; execution mapping is D9.

## Switch Reasons

- `initial_highest_open_interest`
- `unchanged`
- `open_interest_roll`
- `ltd_guard_fallback`
- `liquidity_fallback`

## CLI

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-chain-map --product CF --start 2024-01-09 --end 2024-01-12 --quote-fixture tests/fixtures/core_quote_daily_cf_chain_sample.csv --ltd-buffer-days 2
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-mapping --start 2024-01-09 --end 2024-01-12 --ltd-buffer-days 2
```
