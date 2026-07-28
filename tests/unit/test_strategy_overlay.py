from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import StrategyError
from cotton_factor.core.schemas import BacktestTargetLotDailyRow
from cotton_factor.strategy.overlay_test import (
    _read_safe_research_table,
    build_overlay_targets,
    overlay_decision,
)
from cotton_factor.strategy.spec import load_strategy_spec


def test_option_overlay_requires_explicit_opposite_direction() -> None:
    spec = load_strategy_spec(Path("configs/strategy/ovl_option_veto_v0.yaml"))
    dates = [date(2024, 1, 2) + timedelta(days=index) for index in range(3)]
    base_rows = [_base_target(value, lots=10) for value in dates]
    diagnostics = [_base_diagnostic(value, direction=1, lots=10) for value in dates]
    source = pd.DataFrame(
        [
            _option_row(dates[0], signal="diverge_long", direction="short"),
            _option_row(dates[1], signal="diverge_long", direction="long"),
            _option_row(dates[2], signal="volatility_risk", direction="neutral"),
        ]
    )

    targets, rows, warnings = build_overlay_targets(
        spec=spec,
        base_rows=base_rows,
        base_diagnostics=diagnostics,
        source_frame=source,
        run_id="option_overlay_fixture",
    )

    assert [row.target_lots for row in targets] == [5, 10, 5]
    assert all(row.execution_date == base.execution_date for row, base in zip(targets, base_rows))
    assert [row["g_overlay"] for row in rows] == [0.5, 1.0, 0.5]
    assert any("OPTION_DIVERGENCE_SEMANTIC_CONFLICT" in value for value in warnings)


def test_member_and_strike_overlays_follow_only_registered_rules() -> None:
    dates = [date(2024, 2, 1) + timedelta(days=index) for index in range(4)]
    base_rows = [
        _base_target(dates[0], lots=10),
        _base_target(dates[1], lots=10),
        _base_target(dates[2], lots=-10),
        _base_target(dates[3], lots=-10),
    ]
    diagnostics = [
        _base_diagnostic(value, direction=1 if index < 2 else -1, lots=row.target_lots)
        for index, (value, row) in enumerate(zip(dates, base_rows, strict=True))
    ]

    member_spec = load_strategy_spec(Path("configs/strategy/ovl_member_position_v0.yaml"))
    member_source = pd.DataFrame(
        [
            _member_row(dates[0], direction="long"),
            _member_row(dates[1], direction="short"),
        ]
    )
    member_targets, _, member_warnings = build_overlay_targets(
        spec=member_spec,
        base_rows=base_rows,
        base_diagnostics=diagnostics,
        source_frame=member_source,
        run_id="member_overlay_fixture",
    )
    assert [row.target_lots for row in member_targets] == [10, 5, -10, -10]
    assert any("MISSING_MEMBER_POSITION_INPUT" in value for value in member_warnings)

    strike_spec = load_strategy_spec(Path("configs/strategy/ovl_strike_wall_v0.yaml"))
    strike_source = pd.DataFrame(
        [
            _strike_row(dates[0], call_distance=0.005, put_distance=-0.10),
            _strike_row(dates[1], call_distance=0.005, put_distance=-0.10),
            _strike_row(dates[2], call_distance=0.10, put_distance=-0.005),
            _strike_row(dates[3], call_distance=0.10, put_distance=-0.02),
        ]
    )
    strike_targets, strike_rows, _ = build_overlay_targets(
        spec=strike_spec,
        base_rows=base_rows,
        base_diagnostics=diagnostics,
        source_frame=strike_source,
        run_id="strike_overlay_fixture",
    )
    assert [row.target_lots for row in strike_targets] == [5, 10, -5, -10]
    assert strike_rows[1]["overlay_state"] == "NEAR_SAME_SIDE_WALL_EXISTING"


@pytest.mark.parametrize(
    ("promotion_status", "delta_sharpe", "expected"),
    [("PASS", 0.10, "KEEP"), ("FROZEN", 0.01, "WATCH"), ("FROZEN", 0.0, "REJECT")],
)
def test_overlay_decision_is_mechanical(
    promotion_status: str,
    delta_sharpe: float,
    expected: str,
) -> None:
    assert (
        overlay_decision(
            {"decision": promotion_status, "full_delta_sharpe": delta_sharpe}
        )
        == expected
    )


def test_overlay_source_rejects_forward_labels(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.parquet"
    pd.DataFrame(
        [{"trade_date": "2024-01-01", "forward_return_20d": 0.1}]
    ).to_parquet(path, index=False)

    with pytest.raises(StrategyError, match="forbidden columns"):
        _read_safe_research_table(path)


def test_overlay_cli_is_registered() -> None:
    result = CliRunner().invoke(app, ["strategy", "test-overlay", "--help"])
    assert result.exit_code == 0, result.output
    assert "--overlay" in result.output
    assert "KEEP/WATCH/REJECT" in result.output


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


def _option_row(trade_date: date, *, signal: str, direction: str) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "option_signal": signal,
        "option_signal_direction": direction,
        "source_snapshot_ids": f"option_{trade_date:%Y%m%d}",
    }


def _member_row(trade_date: date, *, direction: str) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "member_direction": direction,
        "member_net_change": 1.0 if direction == "long" else -1.0,
        "member_source_complete": True,
        "source_snapshot_ids": f"member_{trade_date:%Y%m%d}",
    }


def _strike_row(
    trade_date: date,
    *,
    call_distance: float,
    put_distance: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "distance_to_call_wall": call_distance,
        "distance_to_put_wall": put_distance,
        "run_id": f"strike_{trade_date:%Y%m%d}",
    }
