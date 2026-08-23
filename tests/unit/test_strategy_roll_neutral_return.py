from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.core.schemas import CoreQuoteDailyRow, ResearchContinuousPriceDailyRow
from cotton_factor.strategy.roll_neutral_return import (
    build_cf_roll_neutral_return_research,
    build_roll_neutral_return_index,
    build_tsmom_measurement_comparison,
)
from cotton_factor.strategy.spec import load_strategy_spec


def test_same_contract_return_matches_real_contract_settlement() -> None:
    dates = [date(2024, 1, 2) + timedelta(days=index) for index in range(3)]
    prices = [100.0, 102.0, 101.0]
    continuous = [
        _continuous(
            trade_date=trade_date,
            contract="CF401",
            raw_price=price,
            adjusted_price=price,
        )
        for trade_date, price in zip(dates, prices, strict=True)
    ]
    quotes = [
        _quote(trade_date, "CF401", price)
        for trade_date, price in zip(dates, prices, strict=True)
    ]

    rows = build_roll_neutral_return_index(continuous_rows=continuous, quotes=quotes)

    assert rows[0].return_index == pytest.approx(100.0)
    assert rows[1].daily_return == pytest.approx(102.0 / 100.0 - 1.0)
    assert rows[2].daily_return == pytest.approx(101.0 / 102.0 - 1.0)
    assert rows[2].return_index == pytest.approx(101.0)
    assert rows[2].return_method == "SAME_CONTRACT"


def test_roll_date_uses_old_contract_return_and_excludes_roll_gap() -> None:
    dates = [date(2024, 1, 2) + timedelta(days=index) for index in range(4)]
    continuous = [
        _continuous(dates[0], "CF401", 100.0, 100.0),
        _continuous(dates[1], "CF401", 102.0, 102.0),
        _continuous(
            dates[2],
            "CF405",
            120.0,
            103.0,
            is_roll=True,
            roll_from="CF401",
            roll_to="CF405",
            roll_gap=17.0,
            adjustment=-17.0,
            cumulative_adjustment=-17.0,
        ),
        _continuous(
            dates[3],
            "CF405",
            122.0,
            105.0,
            cumulative_adjustment=-17.0,
        ),
    ]
    quotes = [
        _quote(dates[0], "CF401", 100.0),
        _quote(dates[1], "CF401", 102.0),
        _quote(dates[2], "CF401", 103.0),
        _quote(dates[2], "CF405", 120.0),
        _quote(dates[3], "CF405", 122.0),
    ]

    rows = build_roll_neutral_return_index(continuous_rows=continuous, quotes=quotes)

    assert rows[2].return_contract == "CF401"
    assert rows[2].return_method == "OLD_CONTRACT_ON_ROLL_DATE"
    assert rows[2].return_contract_prior_settle == pytest.approx(102.0)
    assert rows[2].return_contract_current_settle == pytest.approx(103.0)
    assert rows[2].daily_return == pytest.approx(103.0 / 102.0 - 1.0)
    assert rows[2].daily_return != pytest.approx(120.0 / 102.0 - 1.0)
    assert rows[3].daily_return == pytest.approx(122.0 / 120.0 - 1.0)
    expected_index = 100.0 * (102.0 / 100.0) * (103.0 / 102.0) * (122.0 / 120.0)
    assert rows[3].return_index == pytest.approx(expected_index)


def test_roll_neutral_history_is_identical_when_future_is_truncated() -> None:
    continuous, quotes = _long_fixture()
    cutoff = continuous[20].trade_date

    full = build_roll_neutral_return_index(continuous_rows=continuous, quotes=quotes)
    truncated = build_roll_neutral_return_index(
        continuous_rows=[row for row in continuous if row.trade_date <= cutoff],
        quotes=[row for row in quotes if row.trade_date <= cutoff],
    )

    full_at_cutoff = next(row for row in full if row.trade_date == cutoff)
    assert full_at_cutoff.to_record() == truncated[-1].to_record()
    spec = load_strategy_spec(Path("configs/strategy/CF_tsmom_v0.yaml"))
    full_comparison = build_tsmom_measurement_comparison(
        continuous_rows=continuous,
        return_rows=full,
        spec=spec,
        multiplier=5.0,
    )
    truncated_continuous = [row for row in continuous if row.trade_date <= cutoff]
    truncated_comparison = build_tsmom_measurement_comparison(
        continuous_rows=truncated_continuous,
        return_rows=truncated,
        spec=spec,
        multiplier=5.0,
    )
    full_comparison_at_cutoff = next(
        row for row in full_comparison if row["trade_date"] == cutoff
    )
    assert full_comparison_at_cutoff == truncated_comparison[-1]


def test_r93f_writes_artifacts_without_overwriting_additive_input(tmp_path: Path) -> None:
    continuous_path, core_path = _write_long_fixture(tmp_path)
    original_sha = _sha256(continuous_path)

    result = build_cf_roll_neutral_return_research(
        continuous_price_path=continuous_path,
        core_quote_path=core_path,
        strategy_spec_path=Path("configs/strategy/CF_tsmom_v0.yaml"),
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="r93f_fixture",
    )

    assert _sha256(continuous_path) == original_sha
    assert result.row_count == 25
    assert result.eligible_row_count == 5
    assert result.roll_count == 2
    for path in (
        result.return_index_path,
        result.comparison_path,
        result.warning_csv_path,
        result.json_path,
        result.manifest_path,
        result.markdown_path,
    ):
        assert path.exists()
        assert path.stat().st_size > 0
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "无换月跳空收益指数" in report
    assert "不构成交易指令" in report
    assert "不修改现有策略、影子账本或历史结果" in report
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["rule_version"] == "V5.1_R93F_roll_neutral_return_v1"
    assert str(continuous_path) in manifest["input_sha256"]


def test_r93f_cli_builds_roll_neutral_research_on_fixture(tmp_path: Path) -> None:
    continuous_path, core_path = _write_long_fixture(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "strategy",
            "build-roll-neutral-return-index",
            "--continuous-price-path",
            str(continuous_path),
            "--core-quote-path",
            str(core_path),
            "--spec",
            "configs/strategy/CF_tsmom_v0.yaml",
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "r93f_cli_fixture",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == "r93f_cli_fixture"
    assert payload["row_count"] == 25
    assert Path(payload["return_index_path"]).exists()
    assert Path(payload["comparison_path"]).exists()


def _write_long_fixture(tmp_path: Path) -> tuple[Path, Path]:
    continuous, quotes = _long_fixture()
    continuous_path = tmp_path / "continuous.parquet"
    core_path = tmp_path / "core.parquet"
    pd.DataFrame([row.model_dump(mode="json") for row in continuous]).to_parquet(
        continuous_path,
        index=False,
    )
    pd.DataFrame([row.model_dump(mode="json") for row in quotes]).to_parquet(
        core_path,
        index=False,
    )
    return continuous_path, core_path


def _long_fixture() -> tuple[list[ResearchContinuousPriceDailyRow], list[CoreQuoteDailyRow]]:
    dates = [date(2024, 1, 1) + timedelta(days=index) for index in range(25)]
    continuous: list[ResearchContinuousPriceDailyRow] = []
    quotes: list[CoreQuoteDailyRow] = []
    cumulative_adjustment = 0.0
    prior_contract: str | None = None
    for index, trade_date in enumerate(dates):
        if index < 10:
            contract = "CF401"
            raw_price = 100.0 + index
        elif index < 20:
            contract = "CF405"
            raw_price = 130.0 + (index - 10)
        else:
            contract = "CF409"
            raw_price = 160.0 + (index - 20)
        is_roll = prior_contract is not None and contract != prior_contract
        roll_gap = 20.0 if is_roll else None
        adjustment = -20.0 if is_roll else 0.0
        cumulative_adjustment += adjustment
        continuous.append(
            _continuous(
                trade_date,
                contract,
                raw_price,
                raw_price + cumulative_adjustment,
                is_roll=is_roll,
                roll_from=prior_contract if is_roll else None,
                roll_to=contract if is_roll else None,
                roll_gap=roll_gap,
                adjustment=adjustment,
                cumulative_adjustment=cumulative_adjustment,
            )
        )
        quotes.append(_quote(trade_date, contract, raw_price))
        if is_roll:
            assert prior_contract is not None
            old_price = raw_price - 20.0
            quotes.append(_quote(trade_date, prior_contract, old_price))
        prior_contract = contract
    return continuous, quotes


def _continuous(
    trade_date: date,
    contract: str,
    raw_price: float,
    adjusted_price: float,
    *,
    is_roll: bool = False,
    roll_from: str | None = None,
    roll_to: str | None = None,
    roll_gap: float | None = None,
    adjustment: float = 0.0,
    cumulative_adjustment: float = 0.0,
) -> ResearchContinuousPriceDailyRow:
    return ResearchContinuousPriceDailyRow(
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        mapped_contract=contract,
        price_field="settle",
        raw_price=raw_price,
        adjusted_price=adjusted_price,
        adjustment=adjustment,
        cumulative_adjustment=cumulative_adjustment,
        is_roll=is_roll,
        roll_from_contract=roll_from,
        roll_to_contract=roll_to,
        roll_gap=roll_gap,
        chain_switch_reason="roll" if is_roll else "unchanged",
        continuous_rule_version="fixture",
        input_snapshot_ids=[f"continuous_{trade_date:%Y%m%d}_{contract}"],
    )


def _quote(trade_date: date, contract: str, settle: float) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"quote_{trade_date:%Y%m%d}_{contract}",
        exchange="CZCE",
        product_code="CF",
        contract_code=contract,
        trade_date=trade_date,
        open=settle,
        high=settle,
        low=settle,
        close=settle,
        settle=settle,
        volume=100,
        open_interest=1000,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
