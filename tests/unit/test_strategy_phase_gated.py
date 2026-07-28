from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from cotton_factor.core.schemas import BacktestTargetLotDailyRow
from cotton_factor.strategy.phase_gated import build_phase_gated_targets
from cotton_factor.strategy.spec import load_strategy_spec


def test_phase_gated_option_requires_label_and_explicit_opposite_direction() -> None:
    spec = load_strategy_spec(Path("configs/strategy/CF_phase_gated_v0.yaml"))
    dates = [date(2024, 1, 2) + timedelta(days=index) for index in range(3)]
    base_rows = [_base_target(value, lots=10) for value in dates]
    diagnostics = [_base_diagnostic(value, direction=1, lots=10) for value in dates]
    matrix = pd.DataFrame(
        [
            _matrix_row(dates[0], option_signal="diverge_long", option_direction="short"),
            _matrix_row(dates[1], option_signal="diverge_short", option_direction="long"),
            _matrix_row(dates[2], option_signal="volatility_risk", option_direction="neutral"),
        ]
    )
    phase = pd.DataFrame(
        [
            {"trade_date": value, "phase_v2": "S2", "phase_direction": "long"}
            for value in dates
        ]
    )

    targets, gated_diagnostics, warnings = build_phase_gated_targets(
        spec=spec,
        base_rows=base_rows,
        base_diagnostics=diagnostics,
        signal_matrix=matrix,
        trend_phase=phase,
        run_id="r89_fixture",
    )

    assert [row.target_lots for row in targets] == [5, 10, 5]
    assert gated_diagnostics[0]["g_option"] == 0.5
    assert gated_diagnostics[1]["g_option"] == 1.0
    assert not warnings

    conflicting = matrix.copy()
    conflicting.loc[0, "option_signal_direction"] = "long"
    _, _, conflict_warnings = build_phase_gated_targets(
        spec=spec,
        base_rows=base_rows,
        base_diagnostics=diagnostics,
        signal_matrix=conflicting,
        trend_phase=phase,
        run_id="r89_conflict_fixture",
    )
    assert any("OPTION_DIVERGENCE_SEMANTIC_CONFLICT" in value for value in conflict_warnings)


def test_s3_rule_can_reduce_but_cannot_add_or_reverse() -> None:
    spec = load_strategy_spec(Path("configs/strategy/CF_phase_gated_v0.yaml"))
    dates = [date(2024, 1, 2) + timedelta(days=index) for index in range(3)]
    base_rows = [
        _base_target(dates[0], lots=8),
        _base_target(dates[1], lots=20),
        _base_target(dates[2], lots=-20),
    ]
    diagnostics = [
        _base_diagnostic(dates[0], direction=1, lots=8),
        _base_diagnostic(dates[1], direction=1, lots=20),
        _base_diagnostic(dates[2], direction=-1, lots=-20),
    ]
    matrix = pd.DataFrame([_matrix_row(value) for value in dates])
    phase = pd.DataFrame(
        [
            {"trade_date": dates[0], "phase_v2": "S2", "phase_direction": "long"},
            {"trade_date": dates[1], "phase_v2": "S3", "phase_direction": "long"},
            {"trade_date": dates[2], "phase_v2": "S3", "phase_direction": "short"},
        ]
    )

    targets, _, _ = build_phase_gated_targets(
        spec=spec,
        base_rows=base_rows,
        base_diagnostics=diagnostics,
        signal_matrix=matrix,
        trend_phase=phase,
        run_id="r89_s3_fixture",
    )

    assert [row.target_lots for row in targets] == [8, 8, 0]


def _base_target(trade_date: date, *, lots: int) -> BacktestTargetLotDailyRow:
    return BacktestTargetLotDailyRow(
        run_id="base",
        strategy_id="CF_tsmom/v0",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        execution_date=trade_date + timedelta(days=1),
        target_contract="CF401",
        target_lots=lots,
        score=float(lots),
        target_rule_version="base",
        input_snapshot_ids=[f"base_{trade_date:%Y%m%d}"],
    )


def _base_diagnostic(trade_date: date, *, direction: int, lots: int) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "execution_date": trade_date + timedelta(days=1),
        "mapped_contract": "CF401",
        "adjusted_settle": 100.0,
        "momentum": float(direction),
        "direction": direction,
        "annualized_sigma": 0.1,
        "target_lots": lots,
        "warning_code": "",
    }


def _matrix_row(
    trade_date: date,
    *,
    option_signal: str = "confirm_long",
    option_direction: str = "long",
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "carry_signal": "long",
        "option_signal": option_signal,
        "option_signal_direction": option_direction,
        "source_snapshot_ids": f"matrix_{trade_date:%Y%m%d}",
    }
