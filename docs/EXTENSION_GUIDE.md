# Extension Guide

D20 proves that the product layer is configuration-driven. SR and AP can now run
config-only smoke checks without adding product-specific engine code.

## Config-Only Smoke

Run:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main smoke products --products SR,AP --year 2024
```

This command:

- loads product configs
- loads the official CZCE 2024 trading calendar fixture
- builds `core_contract_master` rows
- builds `core_contract_rule_version` rows
- reports warnings and human-review items

It does not ingest SR/AP raw market data, compute SR/AP factors, or run SR/AP
backtests.

## Adding A Product

1. Add `configs/products/{PRODUCT}.yaml`.
2. Fill generation-critical fields:
   - `product_code`
   - `display_name`
   - `exchange`
   - `instrument_type`
   - `currency`
   - `multiplier`
   - `delivery_months`
   - `last_trade_day_rule`
3. Keep uncertain fields as `TODO_REQUIRES_HUMAN_REVIEW`.
4. List every TODO field in `human_review_required`.
5. Run product config smoke.
6. Only after config smoke passes, add data-source fixtures and product-specific
   raw ingestion tests if the product moves into full-chain scope.

## SR/AP D20 Status

SR and AP are not full MVP trading products yet. D20 only proves that the shared
contract-master path can build skeleton futures contracts from config.

D20 SR/AP config fields were populated from CZCE standard futures contract pages:

- SR: https://www.czce.com.cn/cn/sspz/bt/bzhy/qhhy/H077002004001001index_1.htm
- AP: https://www.czce.com.cn/cn/sspz/pg/bzhy/qhhy/H077002021001001index_1.htm

The following still require human review before production:

- last-trade-day rule interpretation
- official field units
- option-style placeholders
- any live data endpoint mapping

## Guardrails

- Do not add CF-specific branches to shared core, research, backtest, or archive
  modules.
- Do not treat config-only smoke as evidence that SR/AP data ingestion is ready.
- Do not remove `TODO_REQUIRES_HUMAN_REVIEW` from rule fields until the rule is
  reviewed and documented.
