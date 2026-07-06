from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.research_workbench import build_cf_carry_factor


def test_build_cf_carry_factor_writes_r10_value_and_warning_contracts(
    tmp_path: Path,
) -> None:
    core_path = _write_core_quotes(
        tmp_path,
        [
            _quote("CF401", settle=100, snapshot_id="raw_quote_near"),
            _quote("CF405", settle=110, snapshot_id="raw_quote_far"),
        ],
    )

    result = build_cf_carry_factor(
        start=date(2024, 1, 9),
        end=date(2024, 1, 9),
        core_quote_path=core_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r12_carry_test",
    )

    assert result.factor_id == "carry_nf_v1"
    assert result.run_id == "r12_carry_test"
    assert len(result.rows) == 1
    assert result.rows[0].input_snapshot_ids == ["raw_quote_near", "raw_quote_far"]
    assert result.rows[0].raw_value > 0
    assert "carry_tenor_rule" in result.human_review_required
    assert result.factor_parquet_path.exists()
    assert result.factor_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()

    factor_frame = pd.read_parquet(result.factor_parquet_path)
    assert factor_frame["factor_id"].to_list() == ["carry_nf_v1"]
    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "CARRY_HUMAN_REVIEW_REQUIRED" in warning_codes


def test_build_cf_carry_factor_keeps_missing_far_leg_visible(tmp_path: Path) -> None:
    core_path = _write_core_quotes(
        tmp_path,
        [_quote("CF401", settle=100, snapshot_id="raw_quote_near")],
    )

    result = build_cf_carry_factor(
        start=date(2024, 1, 9),
        end=date(2024, 1, 9),
        core_quote_path=core_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r12_carry_one_leg",
    )

    assert result.rows == ()
    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "CARRY_FEWER_THAN_TWO_LEGS" in warning_codes
    assert "CARRY_NO_ROWS_IN_RANGE" in warning_codes


def test_build_cf_carry_factor_supports_cross_year_far_leg(tmp_path: Path) -> None:
    core_path = _write_core_quotes(
        tmp_path,
        [
            _quote_at(
                "CF411",
                date(2024, 11, 14),
                settle=14000,
                snapshot_id="raw_quote_near",
            ),
            _quote_at(
                "CF501",
                date(2024, 11, 14),
                settle=14120,
                snapshot_id="raw_quote_next_year",
            ),
        ],
    )

    result = build_cf_carry_factor(
        start=date(2024, 11, 14),
        end=date(2024, 11, 14),
        core_quote_path=core_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r12_carry_cross_year",
    )

    assert len(result.rows) == 1
    assert result.rows[0].input_snapshot_ids == ["raw_quote_near", "raw_quote_next_year"]
    warning_messages = pd.read_csv(result.warning_csv_path)["warning_message"].to_list()
    assert any("R12 carry used CZCE 2025 calendar" in message for message in warning_messages)
    assert not any("last_trade_date omitted" in message for message in warning_messages)


def _write_core_quotes(tmp_path: Path, rows: list[CoreQuoteDailyRow]) -> Path:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _quote(contract_code: str, *, settle: float, snapshot_id: str) -> CoreQuoteDailyRow:
    return _quote_at(
        contract_code,
        date(2024, 1, 9),
        settle=settle,
        snapshot_id=snapshot_id,
    )


def _quote_at(
    contract_code: str,
    trade_date: date,
    *,
    settle: float,
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
        open_interest=1000,
    )
