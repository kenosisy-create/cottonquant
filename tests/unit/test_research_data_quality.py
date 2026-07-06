from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.research_workbench import check_cf_data_quality


def test_check_cf_data_quality_passes_and_writes_reports(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_core_quotes(
        core_path,
        [
            _quote_row("2026-06-11", "CF609", settle=15060, volume=1000, open_interest=30000),
            _quote_row("2026-06-11", "CF701", settle=15240, volume=800, open_interest=22000),
        ],
    )

    result = check_cf_data_quality(
        trade_date=date(2026, 6, 11),
        core_quote_path=core_path,
        report_output_dir=tmp_path / "reports",
    )

    assert result.passed
    assert result.row_count == 2
    assert result.csv_path.exists()
    assert result.markdown_path.exists()
    assert "Passed: `true`" in result.markdown_path.read_text(encoding="utf-8")
    assert any(issue.check_id == "optional_risk_fields_visible" for issue in result.issues)


def test_check_cf_data_quality_blocks_critical_failures(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_core_quotes(
        core_path,
        [
            _quote_row("2026-06-11", "CF609", settle=0, volume=-1, open_interest=30000),
            _quote_row("2026-06-11", "CF609", settle=15060, volume=1000, open_interest=30000),
        ],
    )

    result = check_cf_data_quality(
        trade_date=date(2026, 6, 11),
        core_quote_path=core_path,
        report_output_dir=tmp_path / "reports",
    )

    assert not result.passed
    assert result.severity_counts()["CRITICAL"] >= 3
    assert any(issue.check_id == "primary_key_unique" for issue in result.issues)
    assert any(
        issue.check_id == "positive_prices" and issue.status == "FAIL"
        for issue in result.issues
    )
    assert any(
        issue.check_id == "volume_non_negative" and issue.status == "FAIL"
        for issue in result.issues
    )


def test_check_cf_data_quality_reports_volume_spike_warning(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_core_quotes(
        core_path,
        [
            _quote_row("2026-06-10", "CF609", settle=15000, volume=100, open_interest=30000),
            _quote_row("2026-06-11", "CF609", settle=15060, volume=1000, open_interest=30010),
        ],
    )

    result = check_cf_data_quality(
        trade_date=date(2026, 6, 11),
        core_quote_path=core_path,
        report_output_dir=tmp_path / "reports",
    )

    assert result.passed
    assert any(
        issue.check_id == "volume_spike" and issue.status == "WARN"
        for issue in result.issues
    )


def test_check_cf_data_quality_missing_date_is_critical(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_core_quotes(
        core_path,
        [_quote_row("2026-06-10", "CF609", settle=15000, volume=100, open_interest=30000)],
    )

    result = check_cf_data_quality(
        trade_date=date(2026, 6, 11),
        core_quote_path=core_path,
        report_output_dir=tmp_path / "reports",
    )

    assert not result.passed
    assert result.row_count == 0
    assert any(issue.check_id == "active_cf_contract_exists" for issue in result.issues)


def _write_core_quotes(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _quote_row(
    trade_date: str,
    contract_code: str,
    *,
    settle: float,
    volume: int,
    open_interest: int,
) -> dict[str, object]:
    return {
        "schema_version": "core_quote_daily.v1",
        "source_snapshot_id": f"research_raw:test:{trade_date}:{contract_code}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "open": 15000.0,
        "high": 15100.0,
        "low": 14900.0,
        "close": 15080.0,
        "settle": float(settle),
        "pre_settle": None,
        "volume": volume,
        "open_interest": open_interest,
        "turnover": None,
        "quote_status": "normal",
    }
