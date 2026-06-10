from __future__ import annotations

from datetime import date

import pytest

from cotton_factor.core.schemas import (
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchFactorValueDailyRow,
)
from cotton_factor.research import build_forward_returns, evaluate_single_factor


def test_forward_returns_use_t_plus_one_real_contract_prices() -> None:
    result = build_forward_returns(
        trade_mappings=[
            _mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2)),
            _mapping(
                date(2024, 1, 2),
                execution_date=date(2024, 1, 3),
                is_blocked=True,
                target_contract=None,
            ),
        ],
        quotes=[
            _quote(date(2024, 1, 1), settle=90),
            _quote(date(2024, 1, 2), settle=100, snapshot_id="raw_quote_entry"),
            _quote(date(2024, 1, 3), settle=110, snapshot_id="raw_quote_exit"),
        ],
        run_id="forward_run_d14",
        product_code="CF",
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.trade_date == date(2024, 1, 1)
    assert row.execution_date == date(2024, 1, 2)
    assert row.exit_date == date(2024, 1, 3)
    assert row.target_contract == "CF401"
    assert row.forward_return == pytest.approx(0.1)
    assert row.input_snapshot_ids == [
        "raw_mapping_20240101",
        "raw_quote_entry",
        "raw_quote_exit",
    ]
    assert "trade mapping is blocked" in result.warnings[0]


def test_single_factor_evaluator_golden_metrics() -> None:
    forward_result = build_forward_returns(
        trade_mappings=[
            _mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2)),
            _mapping(date(2024, 1, 2), execution_date=date(2024, 1, 3)),
            _mapping(date(2024, 1, 3), execution_date=date(2024, 1, 4)),
        ],
        quotes=[
            _quote(date(2024, 1, 2), settle=100),
            _quote(date(2024, 1, 3), settle=110),
            _quote(date(2024, 1, 4), settle=132),
            _quote(date(2024, 1, 5), settle=171.6),
        ],
        run_id="forward_run_d14",
        product_code="CF",
    )
    eval_result = evaluate_single_factor(
        factor_rows=[
            _factor_row(date(2024, 1, 1), raw_value=1),
            _factor_row(date(2024, 1, 2), raw_value=2),
            _factor_row(date(2024, 1, 3), raw_value=3),
        ],
        forward_returns=forward_result.rows,
        run_id="eval_run_d14",
        factor_id="mom_20_v1",
        product_code="CF",
    )

    metrics = {row.metric_name: row.metric_value for row in eval_result.rows}
    assert eval_result.joined_observation_count == 3
    assert eval_result.warnings == []
    assert metrics["observation_count"] == 3
    assert metrics["mean_factor_value"] == pytest.approx(2)
    assert metrics["mean_forward_return"] == pytest.approx(0.2)
    assert metrics["pearson_ic"] == pytest.approx(1)
    assert metrics["spearman_rank_ic"] == pytest.approx(1)
    assert metrics["directional_accuracy"] == pytest.approx(1)
    assert eval_result.rows[0].input_snapshot_ids[0] == "raw_factor_20240101"


def test_single_factor_evaluator_warns_when_join_is_empty() -> None:
    result = evaluate_single_factor(
        factor_rows=[_factor_row(date(2024, 1, 1), raw_value=1)],
        forward_returns=[
            build_forward_returns(
                trade_mappings=[_mapping(date(2024, 1, 2), execution_date=date(2024, 1, 3))],
                quotes=[
                    _quote(date(2024, 1, 3), settle=100),
                    _quote(date(2024, 1, 4), settle=101),
                ],
                run_id="forward_run_d14",
                product_code="CF",
            ).rows[0]
        ],
        run_id="eval_run_d14",
        factor_id="mom_20_v1",
        product_code="CF",
    )

    assert result.rows == []
    assert result.joined_observation_count == 0
    assert "joined no observations" in result.warnings[0]


def _quote(
    trade_date: date,
    *,
    settle: float,
    snapshot_id: str | None = None,
) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=snapshot_id or f"raw_quote_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=trade_date,
        settle=settle,
        volume=100,
        open_interest=1000,
    )


def _mapping(
    trade_date: date,
    *,
    execution_date: date,
    is_blocked: bool = False,
    target_contract: str | None = "CF401",
) -> CoreTradeMappingDailyRow:
    return CoreTradeMappingDailyRow(
        source_snapshot_id=f"raw_mapping_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        execution_date=execution_date,
        target_contract=target_contract,
        is_blocked=is_blocked,
        block_reason="golden_block" if is_blocked else None,
        execution_eligible=not is_blocked,
        mapping_rule_version="trade_mapping_v1",
    )


def _factor_row(trade_date: date, *, raw_value: float) -> ResearchFactorValueDailyRow:
    return ResearchFactorValueDailyRow(
        run_id="factor_run_d14",
        factor_id="mom_20_v1",
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        input_snapshot_ids=[f"raw_factor_{trade_date:%Y%m%d}"],
    )
