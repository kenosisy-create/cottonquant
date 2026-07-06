# CF Research Field Mapping

This document maps incoming CF research file columns to standard names used by
the workbench.

## Required Quote Mapping

| Standard field | Common aliases | Required | Notes |
| --- | --- | --- | --- |
| `trade_date` | `trade_date`, `date`, `trading_day`, `交易日期` | Yes | Must normalize to `YYYY-MM-DD`. |
| `exchange` | `exchange`, `exch`, `交易所` | Yes | Expected `CZCE`; may be filled from config if the file source is reviewed. |
| `product_code` | `product_code`, `product`, `品种` | Yes | Expected `CF`; may be filled from config if the file source is reviewed. |
| `contract_id` | `contract_id`, `contract`, `symbol`, `合约`, `合约代码` | Yes | Must be a real tradable contract, not a continuous signal id. |
| `open` | `open`, `open_price`, `开盘价` | Yes | Must be positive for tradable rows. |
| `high` | `high`, `high_price`, `最高价` | Yes | Must be positive and `high >= low`. |
| `low` | `low`, `low_price`, `最低价` | Yes | Must be positive and `high >= low`. |
| `close` | `close`, `close_price`, `收盘价` | Yes | Must be positive for tradable rows. |
| `settle` | `settle`, `settlement`, `settle_price`, `结算价` | Yes | Required for post-settlement signal research. |
| `volume` | `volume`, `vol`, `成交量` | Yes | Must be non-negative. |
| `open_interest` | `open_interest`, `oi`, `持仓量` | Yes | Must be non-negative. |

## Optional Settlement And Risk Mapping

| Standard field | Common aliases | Required | Notes |
| --- | --- | --- | --- |
| `limit_up` | `limit_up`, `upper_limit`, `涨停板价` | No | `HUMAN_REVIEW_REQUIRED` for official interpretation. |
| `limit_down` | `limit_down`, `lower_limit`, `跌停板价` | No | `HUMAN_REVIEW_REQUIRED` for official interpretation. |
| `margin_rate` | `margin_rate`, `margin`, `保证金率` | No | `HUMAN_REVIEW_REQUIRED` for long/short and exchange/member meaning. |
| `trading_status` | `trading_status`, `status`, `交易状态` | No | Must be surfaced when it blocks research mapping. |

## Mapping Rules

1. Research functions must not parse `data/incoming` files directly.
2. R04 raw ingest preserves files first.
3. R05 normalizes only from preserved raw files.
4. Missing required fields must fail normalization.
5. Missing optional fields must become null or warnings.
6. Any source-specific fill rule must be documented here or in
   `configs/data_sources_cf_research.yaml`.
