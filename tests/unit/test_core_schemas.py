from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cotton_factor.core import TABLE_SCHEMAS, table_contract, validate_row, validate_rows
from cotton_factor.core.schemas import SchemaValidationError


def _sample_rows() -> dict[str, dict[str, object]]:
    return {
        "core_contract_master": {
            "exchange": "CZCE",
            "product_code": "CF",
            "contract_code": "CF401",
            "contract_month": "202401",
            "delivery_year": 2024,
            "delivery_month": 1,
            "multiplier": 5,
            "tick_size": 5,
            "first_trade_date": "2023-01-01",
            "last_trade_date": "2024-01-15",
            "rule_version_id": "CF_RULE_V1",
            "source_config_version": "products.CF.v1",
        },
        "core_contract_rule_version": {
            "rule_version_id": "CF_RULE_V1",
            "exchange": "CZCE",
            "product_code": "CF",
            "effective_from": "2024-01-01",
            "delivery_months": [1, 3, 5, 7, 9, 11],
            "last_trade_day_rule": "delivery_month_10th_trading_day",
            "source_config_version": "products.CF.v1",
            "human_review_required": ["tick_size"],
        },
        "core_trading_calendar": {
            "exchange": "CZCE",
            "trade_date": "2024-01-02",
            "is_trading_day": True,
            "calendar_version": "PROVISIONAL_FIXTURE",
        },
        "core_quote_daily": {
            "source_snapshot_id": "raw_quote_1",
            "exchange": "CZCE",
            "product_code": "CF",
            "contract_code": "CF401",
            "trade_date": "2024-01-02",
            "open": 15520,
            "high": 15600,
            "low": 15480,
            "close": 15540,
            "settle": 15530,
            "pre_settle": 15500,
            "volume": 1000,
            "open_interest": 2000,
        },
        "core_option_quote_daily": {
            "source_snapshot_id": "raw_option_1",
            "exchange": "CZCE",
            "product_code": "CF",
            "trade_date": "2024-01-02",
            "option_symbol": "CF401C15000",
            "underlying_contract": "CF401",
            "option_type": "C",
            "strike": 15000,
            "settle": 120,
            "volume": 100,
            "open_interest": 200,
            "moneyness": 1.02,
            "liquidity_flag": "liquid",
            "data_quality_flag": "normal",
        },
        "core_member_position_daily": {
            "source_snapshot_id": "raw_member_position_1",
            "source_sha256": "abc123",
            "source_file_name": "FutureDataHolding.xlsx",
            "exchange": "CZCE",
            "product_code": "CF",
            "trade_date": "2024-01-02",
            "scope_type": "contract",
            "scope_code": "CF405",
            "contract_code": "CF405",
            "position_side": "long",
            "rank": 1,
            "member_name": "中信期货（代客）",
            "position_value": 10000,
            "position_change": -500,
            "data_quality_flag": "normal",
        },
        "core_settlement_param_daily": {
            "source_snapshot_id": "raw_settlement_1",
            "exchange": "CZCE",
            "product_code": "CF",
            "contract_code": "CF401",
            "trade_date": "2024-01-02",
            "limit_up": 16530,
            "limit_down": 14530,
            "margin_rate_long": 0.07,
            "margin_rate_short": 0.07,
            "trading_status": "normal",
        },
        "core_chain_map_daily": {
            "source_snapshot_id": "raw_quote_1",
            "exchange": "CZCE",
            "product_code": "CF",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "mapped_contract": "CF401",
            "chain_rank": 1,
            "switch_reason": "highest_open_interest",
            "roll_rule_version": "roll_placeholder_v1",
        },
        "core_trade_mapping_daily": {
            "source_snapshot_id": "raw_quote_1",
            "exchange": "CZCE",
            "product_code": "CF",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "execution_date": "2024-01-03",
            "target_contract": "CF401",
            "is_blocked": False,
            "execution_eligible": True,
            "mapping_rule_version": "trade_mapping_v1",
        },
        "research_continuous_price_daily": {
            "product_code": "CF",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "mapped_contract": "CF401",
            "price_field": "settle",
            "raw_price": 15530,
            "adjusted_price": 15530,
            "adjustment": 0,
            "cumulative_adjustment": 0,
            "is_roll": False,
            "chain_switch_reason": "initial_highest_open_interest",
            "continuous_rule_version": "continuous_back_adjust_additive_v1",
            "input_snapshot_ids": ["raw_quote_1"],
        },
        "research_factor_value_daily": {
            "run_id": "factor_run_1",
            "factor_id": "mom_20_v1",
            "factor_version": "v1",
            "product_code": "CF",
            "universe": "CF_MAIN",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "raw_value": 0.02,
            "processed_value": 0.1,
            "input_snapshot_ids": ["raw_quote_1"],
        },
        "research_factor_diagnostic_daily": {
            "run_id": "factor_run_1",
            "factor_id": "mom_20_v1",
            "factor_version": "v1",
            "product_code": "CF",
            "universe": "CF_MAIN",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "raw_value": 0.02,
            "processed_value": 0.1,
            "signal_state": "long",
            "diagnostic_reason": "processed value above long threshold",
            "warning_flags": [],
            "human_review_required": ["factor_thresholds"],
            "diagnostic_rule_version": "factor_diagnostic_v1",
            "input_snapshot_ids": ["raw_quote_1"],
        },
        "research_forward_return_daily": {
            "run_id": "forward_run_1",
            "product_code": "CF",
            "universe": "CF_MAIN",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "execution_date": "2024-01-03",
            "exit_date": "2024-01-04",
            "horizon": 1,
            "target_contract": "CF401",
            "entry_price_field": "settle",
            "exit_price_field": "settle",
            "entry_price": 15530,
            "exit_price": 15580,
            "forward_return": 0.003219575,
            "return_rule_version": "forward_return_real_contract_tplus1_v1",
            "input_snapshot_ids": ["raw_quote_1", "raw_quote_2"],
        },
        "research_factor_evaluation": {
            "run_id": "eval_run_1",
            "factor_id": "mom_20_v1",
            "factor_version": "v1",
            "product_code": "CF",
            "universe": "CF_MAIN",
            "horizon": 1,
            "metric_name": "pearson_ic",
            "metric_value": 0.5,
            "observation_count": 10,
            "evaluation_rule_version": "single_factor_eval_v1",
            "input_snapshot_ids": ["raw_quote_1", "raw_quote_2"],
        },
        "research_multifactor_score_daily": {
            "run_id": "score_run_1",
            "score_id": "cf_equal_weight_v1",
            "score_version": "v1",
            "product_code": "CF",
            "universe": "CF_MAIN",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "raw_score": 0.25,
            "processed_score": None,
            "factor_count": 2,
            "input_factor_ids": ["mom_20_v1", "carry_nf_v1"],
            "score_rule_version": "equal_weight_multifactor_v1",
            "input_snapshot_ids": ["raw_quote_1", "raw_quote_2"],
        },
        "backtest_target_lot_daily": {
            "run_id": "target_run_1",
            "strategy_id": "cf_equal_weight_v1",
            "product_code": "CF",
            "universe": "CF_MAIN",
            "signal_object_id": "CF.C1",
            "trade_date": "2024-01-02",
            "execution_date": "2024-01-03",
            "target_contract": "CF401",
            "target_lots": 1,
            "score": 0.25,
            "is_blocked": False,
            "execution_eligible": True,
            "target_rule_version": "score_to_target_lot_sign_v1",
            "input_snapshot_ids": ["raw_quote_1", "raw_mapping_1"],
        },
        "archive_run_manifest": {
            "run_id": "run_1",
            "run_type": "schema_test",
            "git_sha": "abc123",
            "config_hash": "cfg123",
            "env_hash": "env123",
            "input_snapshot_ids": ["raw_quote_1"],
            "started_at_utc": datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
            "ended_at_utc": datetime(2024, 1, 2, 8, 1, tzinfo=UTC),
            "status": "success",
            "row_counts": {"core_quote_daily": 1},
            "artifact_paths": ["reports/example.html"],
        },
    }


def test_all_required_d5_schemas_are_registered_and_validate_samples() -> None:
    expected_tables = {
        "core_contract_master",
        "core_contract_rule_version",
        "core_trading_calendar",
        "core_quote_daily",
        "core_option_quote_daily",
        "core_member_position_daily",
        "core_settlement_param_daily",
        "core_chain_map_daily",
        "core_trade_mapping_daily",
        "research_continuous_price_daily",
        "research_factor_value_daily",
        "research_factor_diagnostic_daily",
        "research_forward_return_daily",
        "research_factor_evaluation",
        "research_multifactor_score_daily",
        "backtest_target_lot_daily",
        "archive_run_manifest",
    }

    assert expected_tables == set(TABLE_SCHEMAS)

    for table_name, row in _sample_rows().items():
        validated = validate_row(table_name, row)
        assert validated.table_name == table_name
        assert validated.schema_version.endswith(".v1")


def test_validate_rows_returns_models_in_order() -> None:
    rows = [
        _sample_rows()["core_quote_daily"],
        {**_sample_rows()["core_quote_daily"], "contract_code": "CF405"},
    ]

    validated = validate_rows("core_quote_daily", rows)

    assert [row.contract_code for row in validated] == ["CF401", "CF405"]


def test_core_quote_requires_source_snapshot_id_and_valid_high_low() -> None:
    valid_quote = _sample_rows()["core_quote_daily"]
    missing_lineage = dict(valid_quote)
    missing_lineage.pop("source_snapshot_id")

    with pytest.raises(SchemaValidationError, match="source_snapshot_id"):
        validate_row("core_quote_daily", missing_lineage)

    with pytest.raises(SchemaValidationError, match="high must be >= low"):
        validate_row("core_quote_daily", {**valid_quote, "high": 10, "low": 11})


def test_core_option_quote_requires_type_and_missing_fields_flag() -> None:
    row = _sample_rows()["core_option_quote_daily"]

    assert validate_row("core_option_quote_daily", row).option_type == "C"

    with pytest.raises(SchemaValidationError, match="option_type"):
        validate_row("core_option_quote_daily", {**row, "option_type": "CALL"})

    with pytest.raises(SchemaValidationError, match="missing option market fields"):
        validate_row(
            "core_option_quote_daily",
            {
                **row,
                "settle": None,
                "volume": None,
                "open_interest": None,
                "data_quality_flag": "normal",
            },
        )


def test_core_settlement_rejects_inverted_limits() -> None:
    row = _sample_rows()["core_settlement_param_daily"]

    with pytest.raises(SchemaValidationError, match="limit_up must be >= limit_down"):
        validate_row("core_settlement_param_daily", {**row, "limit_up": 10, "limit_down": 11})


def test_trade_mapping_requires_real_contract_or_block_reason() -> None:
    row = _sample_rows()["core_trade_mapping_daily"]

    with pytest.raises(SchemaValidationError, match="target_contract"):
        validate_row("core_trade_mapping_daily", {**row, "target_contract": None})

    with pytest.raises(SchemaValidationError, match="execution_date"):
        validate_row("core_trade_mapping_daily", {**row, "execution_date": row["trade_date"]})

    blocked_without_reason = {
        **row,
        "target_contract": None,
        "is_blocked": True,
        "execution_eligible": False,
    }
    with pytest.raises(SchemaValidationError, match="block_reason"):
        validate_row("core_trade_mapping_daily", blocked_without_reason)

    valid_blocked = {**blocked_without_reason, "block_reason": "ltd_guard"}
    assert validate_row("core_trade_mapping_daily", valid_blocked).is_blocked is True


def test_factor_values_require_input_snapshot_ids() -> None:
    row = _sample_rows()["research_factor_value_daily"]

    with pytest.raises(SchemaValidationError, match="input_snapshot_ids"):
        validate_row("research_factor_value_daily", {**row, "input_snapshot_ids": []})


def test_factor_diagnostics_keep_unknown_state_explicit() -> None:
    row = _sample_rows()["research_factor_diagnostic_daily"]

    assert validate_row("research_factor_diagnostic_daily", row).signal_state == "long"

    with pytest.raises(SchemaValidationError, match="unknown diagnostic"):
        validate_row(
            "research_factor_diagnostic_daily",
            {
                **row,
                "signal_state": "unknown",
                "warning_flags": [],
                "human_review_required": [],
            },
        )

    valid_unknown = {
        **row,
        "signal_state": "unknown",
        "warning_flags": ["missing_input"],
        "human_review_required": [],
    }
    assert validate_row("research_factor_diagnostic_daily", valid_unknown).signal_state == "unknown"


def test_forward_returns_require_t_plus_one_and_future_exit() -> None:
    row = _sample_rows()["research_forward_return_daily"]

    with pytest.raises(SchemaValidationError, match="execution_date"):
        validate_row("research_forward_return_daily", {**row, "execution_date": row["trade_date"]})

    with pytest.raises(SchemaValidationError, match="exit_date"):
        validate_row(
            "research_forward_return_daily",
            {**row, "exit_date": row["execution_date"]},
        )


def test_factor_evaluation_requires_lineage_and_non_negative_count() -> None:
    row = _sample_rows()["research_factor_evaluation"]

    with pytest.raises(SchemaValidationError, match="input_snapshot_ids"):
        validate_row("research_factor_evaluation", {**row, "input_snapshot_ids": []})

    with pytest.raises(SchemaValidationError, match="observation_count"):
        validate_row("research_factor_evaluation", {**row, "observation_count": -1})


def test_multifactor_scores_and_target_lots_require_lineage_and_mapping_state() -> None:
    score_row = _sample_rows()["research_multifactor_score_daily"]
    target_row = _sample_rows()["backtest_target_lot_daily"]

    with pytest.raises(SchemaValidationError, match="input_factor_ids"):
        validate_row("research_multifactor_score_daily", {**score_row, "input_factor_ids": []})

    with pytest.raises(SchemaValidationError, match="target_contract"):
        validate_row("backtest_target_lot_daily", {**target_row, "target_contract": None})

    blocked = {
        **target_row,
        "target_contract": None,
        "target_lots": 0,
        "is_blocked": True,
        "execution_eligible": False,
        "block_reason": "ltd_guard",
    }
    assert validate_row("backtest_target_lot_daily", blocked).is_blocked is True

    with pytest.raises(SchemaValidationError, match="execution_date"):
        validate_row(
            "backtest_target_lot_daily",
            {**target_row, "execution_date": target_row["trade_date"]},
        )


def test_continuous_price_roll_rows_require_trace_contracts() -> None:
    row = {
        **_sample_rows()["research_continuous_price_daily"],
        "is_roll": True,
        "roll_gap": 100,
    }

    with pytest.raises(SchemaValidationError, match="roll_from_contract"):
        validate_row("research_continuous_price_daily", row)

    valid_roll = {
        **row,
        "roll_from_contract": "CF401",
        "roll_to_contract": "CF405",
    }
    assert validate_row("research_continuous_price_daily", valid_roll).is_roll is True


def test_archive_manifest_rejects_invalid_time_order_and_row_counts() -> None:
    row = _sample_rows()["archive_run_manifest"]

    with pytest.raises(SchemaValidationError, match="ended_at_utc"):
        validate_row(
            "archive_run_manifest",
            {
                **row,
                "ended_at_utc": datetime(2024, 1, 2, 7, 59, tzinfo=UTC),
            },
        )

    with pytest.raises(SchemaValidationError, match="row_counts"):
        validate_row("archive_run_manifest", {**row, "row_counts": {"bad": -1}})


def test_table_contract_exposes_keys_required_versions_and_lineage() -> None:
    contract = table_contract("core_quote_daily")

    assert contract["primary_key"] == ["exchange", "contract_code", "trade_date"]
    assert "source_snapshot_id" in contract["required_fields"]
    assert contract["version_fields"] == ["schema_version"]
    assert contract["lineage_fields"] == ["source_snapshot_id"]


def test_unknown_table_and_extra_fields_fail_loudly() -> None:
    with pytest.raises(SchemaValidationError, match="unknown table schema"):
        validate_row("missing_table", {})

    with pytest.raises(SchemaValidationError, match="extra_forbidden"):
        validate_row(
            "core_quote_daily",
            {**_sample_rows()["core_quote_daily"], "raw_payload": "no"},
        )
