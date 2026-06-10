from __future__ import annotations

from pathlib import Path

import pytest

from cotton_factor.common.exceptions import QAError
from cotton_factor.qa import (
    audit_csv_table,
    parse_null_ratio_thresholds,
    validate_csv_table,
)


def test_validate_csv_table_uses_registered_schema() -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / (
        "core_quote_daily_cf_chain_sample.csv"
    )

    result = validate_csv_table(table_name="core_quote_daily", csv_path=fixture_path)

    assert result.table_name == "core_quote_daily"
    assert result.row_count == 8
    assert result.rows[0].contract_code == "CF401"


def test_validate_csv_table_fails_loudly_on_schema_violation(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_quote.csv"
    csv_path.write_text(
        "source_snapshot_id,exchange,product_code,contract_code,trade_date,high,low\n"
        "raw_1,CZCE,CF,CF401,2024-01-02,100,200\n",
        encoding="utf-8",
    )

    with pytest.raises(QAError, match="schema validation failed"):
        validate_csv_table(table_name="core_quote_daily", csv_path=csv_path)


def test_audit_csv_table_reports_row_count_and_null_ratio_warnings(tmp_path: Path) -> None:
    csv_path = tmp_path / "quotes.csv"
    csv_path.write_text(
        "source_snapshot_id,exchange,product_code,contract_code,trade_date,settle,volume\n"
        "raw_1,CZCE,CF,CF401,2024-01-02,,100\n"
        "raw_1,CZCE,CF,CF405,2024-01-02,15700,100\n",
        encoding="utf-8",
    )

    result = audit_csv_table(
        table_name="core_quote_daily",
        csv_path=csv_path,
        min_row_count=3,
        max_null_ratio_by_field={"settle": 0.0},
    )

    assert result.row_count == 2
    assert result.null_ratios["settle"] == 0.5
    assert result.passed is False
    assert any("row_count 2 < minimum 3" in warning for warning in result.warnings)
    assert any("settle null ratio" in warning for warning in result.warnings)


def test_parse_null_ratio_thresholds() -> None:
    assert parse_null_ratio_thresholds(["settle=0", "volume=0.25"]) == {
        "settle": 0.0,
        "volume": 0.25,
    }

    with pytest.raises(QAError, match="field=value"):
        parse_null_ratio_thresholds(["bad"])
