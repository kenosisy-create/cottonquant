from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreQuoteDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.strategy.shadow_ledger import run_cf_strategy_shadow


def test_shadow_ledger_executes_prior_target_then_earns_next_interval(tmp_path: Path) -> None:
    core_path, continuous_path, chain_path, dates = _shadow_fixture(tmp_path)
    kwargs = _shadow_kwargs(
        tmp_path,
        core_path=core_path,
        continuous_path=continuous_path,
        chain_path=chain_path,
    )

    first = run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[20],
        record_mode="HISTORICAL_REPLAY",
        run_id="shadow_first",
    )
    ledger_path = first.strategies[0].ledger_path
    first_row = pd.read_parquet(ledger_path).iloc[0]
    assert first_row["held_lots_after"] == 0
    assert first_row["gross_pnl"] == pytest.approx(0.0)
    assert first_row["target_lots"] > 0

    run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[21],
        record_mode="HISTORICAL_REPLAY",
        run_id="shadow_second",
    )
    second_row = pd.read_parquet(ledger_path).sort_values("trade_date").iloc[-1]
    assert second_row["held_lots_after"] == first_row["target_lots"]
    assert second_row["gross_pnl"] == pytest.approx(0.0)
    assert second_row["cost"] > 0

    third = run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[22],
        record_mode="HISTORICAL_REPLAY",
        run_id="shadow_third",
    )
    third_row = pd.read_parquet(ledger_path).sort_values("trade_date").iloc[-1]
    expected_gross = second_row["held_lots_after"] * 1.0 * 5.0
    assert third_row["gross_pnl"] == pytest.approx(expected_gross)
    assert third_row["executed_signal_date"] == dates[21].isoformat()
    assert "不构成交易指令" in third.markdown_path.read_text(encoding="utf-8")


def test_shadow_rerun_is_noop_and_correction_appends_event(tmp_path: Path) -> None:
    core_path, continuous_path, chain_path, dates = _shadow_fixture(tmp_path)
    kwargs = _shadow_kwargs(
        tmp_path,
        core_path=core_path,
        continuous_path=continuous_path,
        chain_path=chain_path,
    )
    for index in (20, 21, 22):
        run_cf_strategy_shadow(
            **kwargs,
            trade_date=dates[index],
            record_mode="HISTORICAL_REPLAY",
            run_id=f"shadow_{index}",
        )
    event_files = sorted((tmp_path / "events" / "CF_tsmom").glob("*/*.json"))
    assert len(event_files) == 3

    no_change = run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[22],
        record_mode="HISTORICAL_REPLAY",
        run_id="shadow_noop",
    )
    assert no_change.strategies[0].status == "NO_CHANGES"
    assert len(list((tmp_path / "events" / "CF_tsmom").glob("*/*.json"))) == 3

    core = pd.read_parquet(core_path)
    mask = pd.to_datetime(core["trade_date"]).dt.date.eq(dates[22])
    core.loc[mask, "settle"] = core.loc[mask, "settle"] + 0.5
    core.to_parquet(core_path, index=False)
    corrected = run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[22],
        record_mode="HISTORICAL_REPLAY",
        overwrite_reason="fixture settlement correction",
        run_id="shadow_correction",
    )
    assert corrected.strategies[0].status == "CORRECTED"
    files = list((tmp_path / "events" / "CF_tsmom").glob("*/*.json"))
    assert len(files) == 4
    correction = json.loads(corrected.strategies[0].event_path.read_text(encoding="utf-8"))
    assert correction["event_type"] == "CORRECTION"
    assert correction["supersedes_event_sha256"]
    ledger = pd.read_parquet(corrected.strategies[0].ledger_path)
    assert len(ledger) == 3


def test_forward_capture_requires_latest_core_date(tmp_path: Path) -> None:
    core_path, continuous_path, chain_path, dates = _shadow_fixture(
        tmp_path,
        end_date=date.today(),
    )
    kwargs = _shadow_kwargs(
        tmp_path,
        core_path=core_path,
        continuous_path=continuous_path,
        chain_path=chain_path,
    )
    with pytest.raises(StrategyError, match="latest core date"):
        run_cf_strategy_shadow(
            **kwargs,
            trade_date=dates[20],
            record_mode="FORWARD_CAPTURE",
        )

    result = run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[-1],
        record_mode="FORWARD_CAPTURE",
    )
    row = pd.read_parquet(result.strategies[0].ledger_path).iloc[0]
    assert row["record_mode"] == "FORWARD_CAPTURE"
    assert row["target_status"] == "PENDING_NEXT_OFFICIAL_SESSION"


def test_first_forward_capture_resets_historical_replay_account(tmp_path: Path) -> None:
    core_path, continuous_path, chain_path, dates = _shadow_fixture(
        tmp_path,
        end_date=date.today(),
    )
    kwargs = _shadow_kwargs(
        tmp_path,
        core_path=core_path,
        continuous_path=continuous_path,
        chain_path=chain_path,
    )
    replay = run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[-2],
        record_mode="HISTORICAL_REPLAY",
        run_id="shadow_replay_before_forward",
    )
    replay_row = pd.read_parquet(replay.strategies[0].ledger_path).iloc[-1]
    assert replay_row["target_lots"] > 0

    forward = run_cf_strategy_shadow(
        **kwargs,
        trade_date=dates[-1],
        record_mode="FORWARD_CAPTURE",
        run_id="shadow_forward_segment_start",
    )
    row = pd.read_parquet(forward.strategies[0].ledger_path).sort_values(
        "trade_date"
    ).iloc[-1]
    assert bool(row["accounting_segment_start"]) is True
    assert row["execution_status"] == "NO_PRIOR_TARGET"
    assert row["held_contract_before"] == ""
    assert row["held_lots_before"] == 0
    assert row["held_contract_after"] == ""
    assert row["held_lots_after"] == 0
    assert row["gross_pnl"] == pytest.approx(0.0)
    assert row["cost"] == pytest.approx(0.0)
    assert row["net_pnl"] == pytest.approx(0.0)
    assert row["nav"] == pytest.approx(1_000_000.0)
    assert row["target_lots"] > 0

    with pytest.raises(StrategyError, match="cannot return to HISTORICAL_REPLAY"):
        run_cf_strategy_shadow(
            **kwargs,
            trade_date=dates[-1],
            record_mode="HISTORICAL_REPLAY",
            overwrite_reason="invalid mode rollback",
        )


def _shadow_kwargs(
    tmp_path: Path,
    *,
    core_path: Path,
    continuous_path: Path,
    chain_path: Path,
) -> dict[str, object]:
    return {
        "core_quote_path": core_path,
        "continuous_price_path": continuous_path,
        "chain_map_path": chain_path,
        "event_root": tmp_path / "events",
        "ledger_root": tmp_path / "ledgers",
        "daily_output_root": tmp_path / "daily",
    }


def _shadow_fixture(
    tmp_path: Path,
    *,
    end_date: date | None = None,
) -> tuple[Path, Path, Path, list[date]]:
    first_date = (end_date - timedelta(days=22)) if end_date else date(2024, 1, 1)
    dates = [first_date + timedelta(days=index) for index in range(23)]
    quotes = [_quote(value, settle=100.0 + index) for index, value in enumerate(dates)]
    continuous = [
        ResearchContinuousPriceDailyRow(
            product_code="CF",
            signal_object_id="CF.C1",
            trade_date=value,
            mapped_contract="CF401",
            price_field="settle",
            raw_price=100.0 + index,
            adjusted_price=100.0 + index,
            adjustment=0.0,
            cumulative_adjustment=0.0,
            is_roll=False,
            chain_switch_reason="unchanged" if index else "initial_highest_open_interest",
            continuous_rule_version="fixture",
            input_snapshot_ids=[f"continuous_{value:%Y%m%d}"],
        )
        for index, value in enumerate(dates)
    ]
    chains = [
        CoreChainMapDailyRow(
            source_snapshot_id=f"chain_{value:%Y%m%d}",
            exchange="CZCE",
            product_code="CF",
            signal_object_id="CF.C1",
            trade_date=value,
            mapped_contract="CF401",
            switch_reason="unchanged" if index else "initial_highest_open_interest",
            roll_rule_version="fixture",
        )
        for index, value in enumerate(dates)
    ]
    core_path = tmp_path / "core.parquet"
    continuous_path = tmp_path / "continuous.parquet"
    chain_path = tmp_path / "chain.parquet"
    pd.DataFrame([row.model_dump(mode="json") for row in quotes]).to_parquet(
        core_path,
        index=False,
    )
    pd.DataFrame([row.model_dump(mode="json") for row in continuous]).to_parquet(
        continuous_path,
        index=False,
    )
    pd.DataFrame([row.model_dump(mode="json") for row in chains]).to_parquet(
        chain_path,
        index=False,
    )
    return core_path, continuous_path, chain_path, dates


def _quote(trade_date: date, *, settle: float) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"quote_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=trade_date,
        open=settle,
        close=settle,
        settle=settle,
        volume=100,
        open_interest=1000,
    )
