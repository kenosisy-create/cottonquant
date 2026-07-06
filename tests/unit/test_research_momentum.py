from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.core.schemas import ResearchContinuousPriceDailyRow
from cotton_factor.research_workbench import build_cf_momentum_factor


def test_build_cf_momentum_factor_writes_r10_value_and_warning_contracts(
    tmp_path: Path,
) -> None:
    continuous_path = _write_continuous_rows(tmp_path, row_count=21)

    result = build_cf_momentum_factor(
        start=date(2024, 1, 21),
        end=date(2024, 1, 21),
        continuous_price_path=continuous_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r11_momentum_test",
    )

    assert result.factor_id == "mom_20_v1"
    assert result.run_id == "r11_momentum_test"
    assert len(result.rows) == 1
    assert result.rows[0].raw_value == pytest.approx(0.2)
    assert result.rows[0].input_snapshot_ids == ["raw_quote_0", "raw_quote_20"]
    assert result.factor_parquet_path.exists()
    assert result.factor_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()

    factor_frame = pd.read_parquet(result.factor_parquet_path)
    assert factor_frame["factor_id"].to_list() == ["mom_20_v1"]
    warning_frame = pd.read_csv(result.warning_csv_path)
    assert warning_frame["warning_code"].to_list() == ["MOMENTUM_HUMAN_REVIEW_REQUIRED"]


def test_build_cf_momentum_factor_keeps_insufficient_lookback_visible(
    tmp_path: Path,
) -> None:
    continuous_path = _write_continuous_rows(tmp_path, row_count=20)

    result = build_cf_momentum_factor(
        start=date(2024, 1, 20),
        end=date(2024, 1, 20),
        continuous_price_path=continuous_path,
        output_dir=tmp_path / "factors",
        report_output_dir=tmp_path / "reports",
        run_id="r11_momentum_short",
    )

    assert result.rows == ()
    assert result.factor_parquet_path.exists()
    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "MOMENTUM_LOOKBACK_INSUFFICIENT" in warning_codes
    assert "MOMENTUM_NO_ROWS_IN_RANGE" in warning_codes


def _write_continuous_rows(tmp_path: Path, *, row_count: int) -> Path:
    rows = _continuous_rows(row_count=row_count)
    path = tmp_path / "continuous" / "CF_2024-01-01_2024-01-21_settle_continuous.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _continuous_rows(*, row_count: int) -> list[ResearchContinuousPriceDailyRow]:
    start = date(2024, 1, 1)
    rows: list[ResearchContinuousPriceDailyRow] = []
    for offset in range(row_count):
        price = 100 + offset
        rows.append(
            ResearchContinuousPriceDailyRow(
                product_code="CF",
                signal_object_id="CF.C1",
                trade_date=start + timedelta(days=offset),
                mapped_contract="CF401",
                price_field="settle",
                raw_price=float(price),
                adjusted_price=float(price),
                adjustment=0,
                cumulative_adjustment=0,
                is_roll=False,
                chain_switch_reason="r11_fixture",
                continuous_rule_version="continuous_back_adjust_additive_v1",
                input_snapshot_ids=[f"raw_quote_{offset}"],
            )
        )
    return rows
