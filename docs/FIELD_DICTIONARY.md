# Field Dictionary

D5 defines row-level schema contracts for the core facts layer, research factor
values, and archive run manifests. These schemas are validation contracts only;
they do not perform raw parsing or normalization.

## Tables

| Table | Primary Key | Required Fields | Version Fields | Lineage Fields |
| --- | --- | --- | --- | --- |
| core_contract_master | exchange, product_code, contract_code | exchange, product_code, contract_code, contract_month, delivery_year, delivery_month, multiplier, rule_version_id, source_config_version | schema_version | source_config_version |
| core_contract_rule_version | rule_version_id | rule_version_id, exchange, product_code, effective_from, delivery_months, last_trade_day_rule, source_config_version | schema_version | source_config_version |
| core_trading_calendar | exchange, trade_date, calendar_version | exchange, trade_date, is_trading_day, calendar_version | schema_version | calendar_version, source_snapshot_id |
| core_quote_daily | exchange, contract_code, trade_date | source_snapshot_id, exchange, product_code, contract_code, trade_date | schema_version | source_snapshot_id |
| core_settlement_param_daily | exchange, contract_code, trade_date | source_snapshot_id, exchange, product_code, contract_code, trade_date | schema_version | source_snapshot_id |
| core_chain_map_daily | product_code, signal_object_id, trade_date | source_snapshot_id, exchange, product_code, signal_object_id, trade_date, mapped_contract, switch_reason, roll_rule_version | schema_version | source_snapshot_id |
| core_trade_mapping_daily | product_code, signal_object_id, trade_date | source_snapshot_id, exchange, product_code, signal_object_id, trade_date, execution_date, mapping_rule_version | schema_version | source_snapshot_id |
| research_continuous_price_daily | product_code, signal_object_id, trade_date, price_field | product_code, signal_object_id, trade_date, mapped_contract, price_field, raw_price, adjusted_price, adjustment, cumulative_adjustment, chain_switch_reason, continuous_rule_version, input_snapshot_ids | schema_version | input_snapshot_ids |
| research_factor_value_daily | run_id, factor_id, signal_object_id, trade_date | run_id, factor_id, factor_version, product_code, universe, signal_object_id, trade_date, raw_value, input_snapshot_ids | schema_version | input_snapshot_ids |
| research_forward_return_daily | run_id, product_code, signal_object_id, trade_date, horizon | run_id, product_code, universe, signal_object_id, trade_date, execution_date, exit_date, horizon, target_contract, entry_price_field, exit_price_field, entry_price, exit_price, forward_return, return_rule_version, input_snapshot_ids | schema_version | input_snapshot_ids |
| research_factor_evaluation | run_id, factor_id, horizon, metric_name | run_id, factor_id, factor_version, product_code, universe, horizon, metric_name, metric_value, observation_count, evaluation_rule_version, input_snapshot_ids | schema_version | input_snapshot_ids |
| research_multifactor_score_daily | run_id, score_id, signal_object_id, trade_date | run_id, score_id, score_version, product_code, universe, signal_object_id, trade_date, raw_score, factor_count, input_factor_ids, score_rule_version, input_snapshot_ids | schema_version | input_snapshot_ids |
| backtest_target_lot_daily | run_id, strategy_id, signal_object_id, trade_date | run_id, strategy_id, product_code, universe, signal_object_id, trade_date, execution_date, target_lots, score, target_rule_version, input_snapshot_ids | schema_version | input_snapshot_ids |
| archive_run_manifest | run_id | run_id, run_type, git_sha, config_hash, env_hash, started_at_utc, status | schema_version | input_snapshot_ids |

## Validation Notes

- Core quote and settlement rows require `source_snapshot_id`.
- Quote rows reject `high < low`.
- Settlement rows reject `limit_up < limit_down`.
- Chain map rows require explicit `switch_reason`.
- Trade mapping rows must either map to a real `target_contract` or be blocked
  with `block_reason`; blocked rows cannot be execution eligible.
- Trade mapping rows require `execution_date > trade_date` to preserve T signal
  and T+1 execution separation.
- Continuous price roll rows require `roll_from_contract` and `roll_to_contract`;
  they carry `input_snapshot_ids` for quote and chain-map lineage.
- Factor rows require non-empty `input_snapshot_ids`.
- Forward return rows require `execution_date > trade_date`,
  `exit_date > execution_date`, positive entry/exit prices, and non-empty
  `input_snapshot_ids`.
- Factor evaluation rows require non-empty `input_snapshot_ids` and non-negative
  observation counts.
- Multifactor score rows require at least one input factor id and non-empty
  `input_snapshot_ids`.
- Target lot rows require `execution_date > trade_date`; unblocked rows require
  a real `target_contract`, while blocked rows require `block_reason` and cannot
  be execution eligible.
- Archive run manifests reject `ended_at_utc` earlier than `started_at_utc`.
- Unknown fields are rejected by all row schemas.
