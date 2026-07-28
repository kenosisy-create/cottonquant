from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.backtest import NotionalBpsCostModel, run_daily_backtest
from cotton_factor.core.schemas import (
    BacktestTargetLotDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    CoreTradeMappingDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.strategy.baseline_tsmom import run_cf_tsmom_backtest
from cotton_factor.strategy.signals import build_tsmom_targets
from cotton_factor.strategy.spec import load_strategy_spec


def test_notional_bps_cost_uses_actual_fill_notional() -> None:
    estimate = NotionalBpsCostModel(one_way_bps=10).estimate(
        order_lots=-2,
        fill_price=100.0,
        multiplier=5.0,
    )

    assert estimate.total_cost == pytest.approx(1.0)
    assert estimate.fee == pytest.approx(1.0)
    assert estimate.warnings == ()


def test_baseline_signal_fills_t_plus_one_and_first_earns_after_fill(tmp_path: Path) -> None:
    continuous_path, mapping_path, core_path, signal_dates = _baseline_fixture(tmp_path)
    result = run_cf_tsmom_backtest(
        spec_path=Path("configs/strategy/CF_tsmom_v0.yaml"),
        start=signal_dates[0],
        end=signal_dates[-1],
        continuous_price_path=continuous_path,
        trade_mapping_path=mapping_path,
        core_quote_path=core_path,
        output_dir=tmp_path / "strategy",
        report_output_dir=tmp_path / "reports",
        run_id="r87_fixture",
    )

    targets = pd.read_parquet(result.target_path)
    fills = pd.read_parquet(result.fill_path)
    daily = pd.read_parquet(result.daily_path)
    no_cost = daily.loc[daily["cost_scenario"].eq("no_cost")].reset_index(drop=True)

    assert targets.iloc[0]["target_lots"] > 0
    assert str(fills.iloc[0]["execution_date"]) == str(targets.iloc[0]["execution_date"])
    assert no_cost.iloc[0]["daily_net_pnl"] == pytest.approx(0.0)
    expected_second_pnl = no_cost.iloc[0]["held_lots"] * 1.0 * 5.0
    assert no_cost.iloc[1]["daily_net_pnl"] == pytest.approx(expected_second_pnl)
    assert result.metrics_by_scenario["conservative_cost"]["final_nav"] < (
        result.metrics_by_scenario["no_cost"]["final_nav"]
    )
    assert "不构成交易指令" in result.markdown_path.read_text(encoding="utf-8")
    assert json.loads(result.manifest_path.read_text(encoding="utf-8"))[
        "backtest_rule_version"
    ] == "V5.1_R87_baseline_backtest_v1"


def test_real_contract_roll_charges_close_and_open_costs() -> None:
    result = run_daily_backtest(
        target_lot_rows=[
            _target(date(2024, 1, 2), date(2024, 1, 3), "CF401", 1),
            _target(date(2024, 1, 3), date(2024, 1, 4), "CF405", 1),
        ],
        quotes=[
            _quote(date(2024, 1, 3), "CF401", 100.0),
            _quote(date(2024, 1, 4), "CF401", 101.0),
            _quote(date(2024, 1, 4), "CF405", 110.0),
        ],
        contracts=[_contract("CF401", 1), _contract("CF405", 5)],
        run_id="roll_cost",
        product_code="CF",
        strategy_id="roll_fixture",
        cost_model=NotionalBpsCostModel(one_way_bps=10),
    )

    assert [fill.target_contract for fill in result.fills] == ["CF401", "CF401", "CF405"]
    second_day_costs = [
        row.total_cost for row in result.costs if row.execution_date == date(2024, 1, 4)
    ]
    assert second_day_costs == pytest.approx([0.505, 0.55])


def test_target_is_identical_when_future_prices_are_truncated(tmp_path: Path) -> None:
    continuous_path, mapping_path, core_path, signal_dates = _baseline_fixture(tmp_path)
    continuous = [
        ResearchContinuousPriceDailyRow.model_validate(row)
        for row in pd.read_parquet(continuous_path).to_dict(orient="records")
    ]
    mappings = [
        CoreTradeMappingDailyRow.model_validate(row)
        for row in pd.read_parquet(mapping_path).to_dict(orient="records")
    ]
    quotes = [
        CoreQuoteDailyRow.model_validate(row)
        for row in pd.read_parquet(core_path).to_dict(orient="records")
    ]
    spec = load_strategy_spec(Path("configs/strategy/CF_tsmom_v0.yaml"))
    first_date = signal_dates[0]

    full = build_tsmom_targets(
        spec=spec,
        continuous_rows=continuous,
        trade_mappings=[mappings[0]],
        quotes=quotes,
        multiplier=5.0,
        run_id="full",
    )
    truncated = build_tsmom_targets(
        spec=spec,
        continuous_rows=[row for row in continuous if row.trade_date <= first_date],
        trade_mappings=[mappings[0]],
        quotes=[row for row in quotes if row.trade_date <= first_date],
        multiplier=5.0,
        run_id="truncated",
    )

    assert full.target_rows[0].target_lots == truncated.target_rows[0].target_lots
    assert full.diagnostics[0]["annualized_sigma"] == pytest.approx(
        truncated.diagnostics[0]["annualized_sigma"]
    )


def _baseline_fixture(tmp_path: Path) -> tuple[Path, Path, Path, list[date]]:
    dates = [date(2024, 1, 1) + timedelta(days=index) for index in range(24)]
    continuous = [
        ResearchContinuousPriceDailyRow(
            product_code="CF",
            signal_object_id="CF.C1",
            trade_date=trade_date,
            mapped_contract="CF401",
            price_field="settle",
            raw_price=100.0 + index,
            adjusted_price=100.0 + index,
            adjustment=0.0,
            cumulative_adjustment=0.0,
            is_roll=False,
            chain_switch_reason="unchanged" if index else "initial_highest_open_interest",
            continuous_rule_version="fixture",
            input_snapshot_ids=[f"continuous_{trade_date:%Y%m%d}"],
        )
        for index, trade_date in enumerate(dates)
    ]
    signal_dates = dates[20:23]
    mappings = [
        CoreTradeMappingDailyRow(
            source_snapshot_id=f"mapping_{trade_date:%Y%m%d}",
            exchange="CZCE",
            product_code="CF",
            signal_object_id="CF.C1",
            trade_date=trade_date,
            execution_date=dates[index + 1],
            target_contract="CF401",
            is_blocked=False,
            execution_eligible=True,
            mapping_rule_version="fixture",
        )
        for index, trade_date in enumerate(dates)
        if trade_date in signal_dates
    ]
    quotes = [_quote(value, "CF401", 100.0 + index) for index, value in enumerate(dates)]
    continuous_path = tmp_path / "continuous.parquet"
    mapping_path = tmp_path / "mapping.parquet"
    core_path = tmp_path / "core.parquet"
    pd.DataFrame([row.model_dump(mode="json") for row in continuous]).to_parquet(
        continuous_path,
        index=False,
    )
    pd.DataFrame([row.model_dump(mode="json") for row in mappings]).to_parquet(
        mapping_path,
        index=False,
    )
    pd.DataFrame([row.model_dump(mode="json") for row in quotes]).to_parquet(
        core_path,
        index=False,
    )
    return continuous_path, mapping_path, core_path, signal_dates


def _target(
    trade_date: date,
    execution_date: date,
    contract: str,
    lots: int,
) -> BacktestTargetLotDailyRow:
    return BacktestTargetLotDailyRow(
        run_id="fixture",
        strategy_id="fixture",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        execution_date=execution_date,
        target_contract=contract,
        target_lots=lots,
        score=float(lots),
        target_rule_version="fixture",
        input_snapshot_ids=[f"target_{trade_date:%Y%m%d}"],
    )


def _quote(trade_date: date, contract: str, settle: float) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"quote_{contract}_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code=contract,
        trade_date=trade_date,
        open=settle,
        close=settle,
        settle=settle,
        volume=100,
        open_interest=1000,
    )


def _contract(contract_code: str, month: int) -> CoreContractMasterRow:
    return CoreContractMasterRow(
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        contract_month=f"2024{month:02d}",
        delivery_year=2024,
        delivery_month=month,
        multiplier=5.0,
        tick_size=None,
        first_trade_date=None,
        last_trade_date=None,
        rule_version_id="fixture",
        source_config_version="fixture",
    )
