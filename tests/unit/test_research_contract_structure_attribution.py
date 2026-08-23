from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import (
    build_cf_delivery_adjusted_curve,
    build_cf_structural_position_attribution,
)


def test_delivery_adjusted_curve_uses_far_minus_near_and_explicit_costs(
    tmp_path: Path,
) -> None:
    quote_path = _write_quotes(tmp_path)
    result = build_cf_delivery_adjusted_curve(
        core_quote_path=quote_path,
        near_contract="CF609",
        far_contract="CF611",
        start=date(2026, 1, 1),
        aging_discount=100.0,
        storage_cost_per_ton_day=1.0,
        annual_financing_rate=0.0,
        holding_days=10,
        near_zero_band=5.0,
        min_history_days=1,
        output_dir=tmp_path / "curve_data",
        report_output_dir=tmp_path / "curve_reports",
        run_id="curve_unit",
    )

    daily = pd.read_parquet(result.daily_parquet_path)
    latest = daily.iloc[-1]
    assert latest["observed_spread"] == 117.0
    assert latest["modeled_full_carry_cost"] == 110.0
    assert latest["delivery_adjusted_residual"] == 7.0
    assert latest["residual_state"] == "ABOVE_SCENARIO_COST"
    assert "forward_return" not in daily.columns
    assert result.monthly_parquet_path.exists()
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "不是理论公允价" in report
    assert "不构成交易指令" in report


def test_structural_attribution_separates_roll_pair_receipt_and_t1_option_labels(
    tmp_path: Path,
) -> None:
    quote_path = _write_quotes(tmp_path)
    member_path = _write_member_detail(tmp_path)
    warehouse_path = _write_warehouse(tmp_path)
    strike_path = _write_option_strike(tmp_path)
    option_factor_path = _write_option_factor(tmp_path)
    curve_path = _write_curve(tmp_path)

    result = build_cf_structural_position_attribution(
        core_quote_path=quote_path,
        member_detail_path=member_path,
        warehouse_receipt_path=warehouse_path,
        option_strike_position_path=strike_path,
        option_factor_path=option_factor_path,
        delivery_adjusted_curve_path=curve_path,
        target_contract="CF611",
        source_contract="CF609",
        next_contract="CF701",
        focus_start=date(2026, 6, 1),
        option_horizons=(1, 3),
        wall_distance=0.01,
        output_dir=tmp_path / "attribution_data",
        report_output_dir=tmp_path / "attribution_reports",
        run_id="attribution_unit",
    )

    member = pd.read_parquet(result.member_flow_parquet_path)
    latest_member = member.loc[
        member["trade_date"].astype(str).eq("2026-06-02")
    ].iloc[0]
    assert latest_member["source_to_target_long_roll_proxy"] == 80.0
    assert latest_member["source_to_target_short_roll_proxy"] == 60.0
    assert latest_member["source_to_target_gross_roll_proxy"] == 140.0
    assert latest_member["target_long_next_short_pair_proxy"] == 40.0
    assert latest_member["target_short_next_long_pair_proxy"] == 20.0

    windows = pd.read_parquet(result.window_summary_parquet_path)
    assert "COMMON_WAREHOUSE_WINDOW" in set(windows["window_type"])
    events = pd.read_parquet(result.option_event_parquet_path)
    near_call_1d = events.loc[
        events["event_type"].eq("NEAR_CALL_WALL")
        & events["horizon"].eq(1)
        & events["event_date"].astype(str).eq("2026-06-01")
    ].iloc[0]
    assert str(near_call_1d["execution_date"]) == "2026-06-02"
    assert str(near_call_1d["exit_date"]) == "2026-06-03"
    assert near_call_1d["forward_return"] == pytest.approx(214.0 / 212.0 - 1.0)

    daily = pd.read_parquet(result.daily_parquet_path)
    latest = daily.iloc[-1]
    assert latest["option_structure_state"] == "PRICE_UP_PUT_OI_DOMINANT_BUILD"
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "不能识别主动买方或卖方" in report
    assert "forward return仅作为历史后验验证标签" in report
    assert "不构成交易指令" in report


def test_contract_structure_cli_commands_write_json_and_artifacts(tmp_path: Path) -> None:
    quote_path = _write_quotes(tmp_path)
    curve_run = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-delivery-adjusted-curve",
            "--core-quote-path",
            str(quote_path),
            "--start",
            "2026-01-01",
            "--aging-discount",
            "100",
            "--storage-cost-per-ton-day",
            "1",
            "--annual-financing-rate",
            "0",
            "--holding-days",
            "10",
            "--min-history-days",
            "1",
            "--output-dir",
            str(tmp_path / "cli_curve_data"),
            "--report-output-dir",
            str(tmp_path / "cli_curve_reports"),
            "--run-id",
            "curve_cli",
        ],
    )
    assert curve_run.exit_code == 0, curve_run.output
    curve_payload = json.loads(curve_run.output)
    assert Path(curve_payload["daily_parquet_path"]).exists()

    attribution_run = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-structural-position-attribution",
            "--core-quote-path",
            str(quote_path),
            "--member-detail-path",
            str(_write_member_detail(tmp_path)),
            "--warehouse-receipt-path",
            str(_write_warehouse(tmp_path)),
            "--option-strike-position-path",
            str(_write_option_strike(tmp_path)),
            "--option-factor-path",
            str(_write_option_factor(tmp_path)),
            "--delivery-adjusted-curve-path",
            str(_write_curve(tmp_path)),
            "--focus-start",
            "2026-06-01",
            "--option-horizons",
            "1,3",
            "--output-dir",
            str(tmp_path / "cli_attribution_data"),
            "--report-output-dir",
            str(tmp_path / "cli_attribution_reports"),
            "--run-id",
            "attribution_cli",
        ],
    )
    assert attribution_run.exit_code == 0, attribution_run.output
    attribution_payload = json.loads(attribution_run.output)
    assert attribution_payload["target_contract"] == "CF611"
    assert Path(attribution_payload["option_event_parquet_path"]).exists()


def _write_quotes(tmp_path: Path) -> Path:
    dates = pd.bdate_range("2026-06-01", periods=8).date
    rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        for contract, settle, open_interest in (
            ("CF609", 100.0 + index, 1000.0 - index * 20),
            ("CF611", 210.0 + index * 2, 100.0 + index * 50),
            ("CF701", 230.0 + index, 300.0 + index * 10),
        ):
            rows.append(
                {
                    "trade_date": trade_date,
                    "contract_code": contract,
                    "settle": settle,
                    "close": settle + 1.0,
                    "volume": 1000.0 + index,
                    "open_interest": open_interest,
                }
            )
    path = tmp_path / "core_quote.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_member_detail(tmp_path: Path) -> Path:
    rows = [
        _member_row("2026-06-01", "A", "CF609", 0, 0),
        _member_row("2026-06-01", "A", "CF611", 0, 0),
        _member_row("2026-06-02", "A", "CF609", -100, -60),
        _member_row("2026-06-02", "A", "CF611", 80, 70),
        _member_row("2026-06-02", "B", "CF611", 50, 30),
        _member_row("2026-06-02", "B", "CF701", 20, 40),
    ]
    path = tmp_path / "member_detail.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _member_row(
    trade_date: str,
    member_name: str,
    contract_code: str,
    long_change: float,
    short_change: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "scope_type": "contract",
        "contract_code": contract_code,
        "member_name": member_name,
        "long_change": long_change,
        "short_change": short_change,
        "net_position": 0.0,
        "net_change": long_change - short_change,
    }


def _write_warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": "2026-06-01",
                "warehouse_receipt": 1000.0,
                "source_name": "CZCE fixture",
            },
            {
                "trade_date": "2026-06-04",
                "warehouse_receipt": 950.0,
                "source_name": "CZCE fixture",
            },
        ]
    ).to_parquet(path, index=False)
    return path


def _write_option_strike(tmp_path: Path) -> Path:
    dates = pd.bdate_range("2026-06-01", periods=8).date
    rows = []
    for index, trade_date in enumerate(dates):
        rows.append(
            {
                "trade_date": trade_date,
                "underlying_contract": "CF611",
                "call_total_open_interest": 1000.0 + index * 5,
                "put_total_open_interest": 800.0 + index * 20,
                "pcr_open_interest": (800.0 + index * 20) / (1000.0 + index * 5),
                "call_wall_strike": 212.0,
                "call_wall_open_interest": 300.0,
                "call_wall_oi_change": -10.0,
                "call_build_strike": 214.0,
                "call_build_oi_change": 5.0,
                "call_unwind_strike": 212.0,
                "call_unwind_oi_change": -10.0,
                "put_wall_strike": 200.0,
                "put_wall_open_interest": 250.0,
                "put_wall_oi_change": 20.0,
                "put_build_strike": 210.0,
                "put_build_oi_change": 20.0,
                "put_unwind_strike": 190.0,
                "put_unwind_oi_change": -2.0,
                "max_pain_strike": 210.0,
                "distance_to_call_wall": (212.0 - (210.0 + index * 2)) / (
                    210.0 + index * 2
                ),
                "distance_to_put_wall": -0.05,
                "distance_to_max_pain": 0.0,
                "key_level_state": "BETWEEN_OI_WALLS",
                "key_level_migration_state": "WALLS_UNCHANGED",
            }
        )
    path = tmp_path / "option_strike.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_option_factor(tmp_path: Path) -> Path:
    dates = pd.bdate_range("2026-06-01", periods=8).date
    path = tmp_path / "option_factor.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "underlying_contract": "CF611",
                "atm_iv_proxy": 0.03,
                "atm_iv_rank": 0.10,
                "pcr_volume": 0.8,
                "pcr_oi": 0.9,
                "skew_proxy": -0.002,
                "call_volume": 100.0,
                "put_volume": 80.0,
                "call_open_interest": 1000.0,
                "put_open_interest": 900.0,
                "option_liquidity_score": 80.0,
                "factor_status": "READY",
            }
            for trade_date in dates
        ]
    ).to_parquet(path, index=False)
    return path


def _write_curve(tmp_path: Path) -> Path:
    dates = pd.bdate_range("2026-06-01", periods=8).date
    path = tmp_path / "curve.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "observed_spread": 110.0 + index,
                "modeled_full_carry_cost": 120.0,
                "delivery_adjusted_residual": -10.0 + index,
                "residual_state": "BELOW_SCENARIO_COST",
            }
            for index, trade_date in enumerate(dates)
        ]
    ).to_parquet(path, index=False)
    return path
