from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.core.schemas import CoreChainMapDailyRow, CoreQuoteDailyRow
from cotton_factor.research_workbench import build_cf_structure_factors


def test_build_cf_structure_factors_writes_curve_and_oi_outputs(tmp_path: Path) -> None:
    core_path = _write_core_quotes(
        tmp_path,
        [
            _quote("CF401", date(2024, 1, 8), settle=100, oi=1000, snapshot_id="raw_prev"),
            _quote("CF401", date(2024, 1, 9), settle=102, oi=1100, snapshot_id="raw_near"),
            _quote("CF403", date(2024, 1, 9), settle=105, oi=900, snapshot_id="raw_far"),
        ],
    )
    chain_path = _write_chain_rows(tmp_path, [_chain(date(2024, 1, 9), "CF401")])

    result = build_cf_structure_factors(
        start=date(2024, 1, 9),
        end=date(2024, 1, 9),
        core_quote_path=core_path,
        chain_map_path=chain_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r13_structure_test",
    )

    assert result.curve_row_count == 1
    assert result.oi_pressure_row_count == 1
    assert {row.factor_id for row in result.rows} == {"curve_slope_v1", "oi_pressure_v1"}
    assert result.factor_parquet_path.exists()
    assert result.factor_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()

    factor_frame = pd.read_parquet(result.factor_parquet_path)
    assert sorted(factor_frame["factor_id"].to_list()) == ["curve_slope_v1", "oi_pressure_v1"]
    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "CURVE_SLOPE_HUMAN_REVIEW_REQUIRED" in warning_codes
    assert "OI_PRESSURE_HUMAN_REVIEW_REQUIRED" in warning_codes


def test_build_cf_structure_factors_keeps_missing_inputs_visible(tmp_path: Path) -> None:
    core_path = _write_core_quotes(
        tmp_path,
        [_quote("CF401", date(2024, 1, 9), settle=102, oi=1100, snapshot_id="raw_near")],
    )
    chain_path = _write_chain_rows(tmp_path, [_chain(date(2024, 1, 9), "CF401")])

    result = build_cf_structure_factors(
        start=date(2024, 1, 9),
        end=date(2024, 1, 9),
        core_quote_path=core_path,
        chain_map_path=chain_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r13_structure_missing",
    )

    assert result.rows == ()
    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "CURVE_SLOPE_NO_FAR_LEG" in warning_codes
    assert "CURVE_SLOPE_NO_ROWS_IN_RANGE" in warning_codes
    assert "OI_PRESSURE_NO_PRIOR_MATCH" in warning_codes
    assert "OI_PRESSURE_NO_ROWS_IN_RANGE" in warning_codes


def test_build_cf_structure_factors_supports_cross_year_curve_leg(tmp_path: Path) -> None:
    core_path = _write_core_quotes(
        tmp_path,
        [
            _quote("CF501", date(2024, 11, 13), settle=14100, oi=1000, snapshot_id="raw_prev"),
            _quote(
                "CF501",
                date(2024, 11, 14),
                settle=14120,
                oi=1120,
                snapshot_id="raw_next_year_near",
            ),
            _quote(
                "CF505",
                date(2024, 11, 14),
                settle=14300,
                oi=900,
                snapshot_id="raw_next_year_far",
            ),
        ],
    )
    chain_path = _write_chain_rows(tmp_path, [_chain(date(2024, 11, 14), "CF501")])

    result = build_cf_structure_factors(
        start=date(2024, 11, 14),
        end=date(2024, 11, 14),
        core_quote_path=core_path,
        chain_map_path=chain_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r13_structure_cross_year",
    )

    assert result.curve_row_count == 1
    assert result.oi_pressure_row_count == 1
    warning_messages = pd.read_csv(result.warning_csv_path)["warning_message"].to_list()
    assert any(
        "R13 structure factors used CZCE 2025 calendar" in message
        for message in warning_messages
    )
    assert not any("last_trade_date omitted" in message for message in warning_messages)


def _write_core_quotes(tmp_path: Path, rows: list[CoreQuoteDailyRow]) -> Path:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_chain_rows(tmp_path: Path, rows: list[CoreChainMapDailyRow]) -> Path:
    path = tmp_path / "mapping" / "CF_2024-01-09_2024-01-09_chain_map_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _quote(
    contract_code: str,
    trade_date: date,
    *,
    settle: float,
    oi: int,
    snapshot_id: str,
) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=snapshot_id,
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        trade_date=trade_date,
        settle=settle,
        volume=100,
        open_interest=oi,
    )


def _chain(trade_date: date, mapped_contract: str) -> CoreChainMapDailyRow:
    return CoreChainMapDailyRow(
        source_snapshot_id=f"raw_chain_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        mapped_contract=mapped_contract,
        chain_rank=1,
        switch_reason="r13_fixture",
        roll_rule_version="roll_placeholder_v1",
    )
