from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.core import load_core_quote_daily_csv
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.research_workbench import build_cf_research_mapping

QUOTE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
)


def test_build_cf_research_mapping_writes_chain_and_trade_outputs(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_quote_parquet(core_path)

    result = build_cf_research_mapping(
        start=date(2024, 1, 9),
        end=date(2024, 1, 12),
        core_quote_path=core_path,
        output_dir=tmp_path / "research_mapping",
        report_output_dir=tmp_path / "reports",
        ltd_buffer_days=2,
    )

    assert len(result.chain_rows) == 4
    assert len(result.trade_rows) == 4
    assert result.blocked_trade_count == 1
    assert [row.switch_reason for row in result.chain_rows] == [
        "initial_highest_open_interest",
        "unchanged",
        "ltd_guard_fallback",
        "unchanged",
    ]
    assert result.trade_rows[1].block_reason == "ltd_buffer_execution_block"
    assert result.chain_parquet_path.exists()
    assert result.chain_csv_path.exists()
    assert result.trade_parquet_path.exists()
    assert result.trade_csv_path.exists()
    assert result.markdown_path.exists()
    assert "ltd_guard_fallback" in result.markdown_path.read_text(encoding="utf-8")


def test_build_cf_research_mapping_requires_official_calendar(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_quote_parquet(core_path)

    with pytest.raises(ResearchWorkbenchError, match="official calendar is required"):
        build_cf_research_mapping(
            start=date(2024, 1, 9),
            end=date(2024, 1, 12),
            core_quote_path=core_path,
            calendar_path=tmp_path / "missing_calendar.csv",
        )


def test_build_cf_research_mapping_supports_cross_year_delivery_contracts(
    tmp_path: Path,
) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_quote_rows(
        core_path,
        [
            _quote("CF411", date(2024, 11, 14), volume=100, oi=5000),
            _quote("CF501", date(2024, 11, 14), volume=100, oi=4000),
            _quote("CF411", date(2024, 11, 15), volume=100, oi=5000),
            _quote("CF501", date(2024, 11, 15), volume=100, oi=4500),
        ],
    )

    result = build_cf_research_mapping(
        start=date(2024, 11, 14),
        end=date(2024, 11, 15),
        core_quote_path=core_path,
        output_dir=tmp_path / "research_mapping",
        report_output_dir=tmp_path / "reports",
    )

    assert [row.mapped_contract for row in result.chain_rows] == ["CF501", "CF501"]
    assert result.trade_rows[0].target_contract == "CF501"
    assert any("R08 mapping used CZCE 2025 calendar" in warning for warning in result.warnings)
    assert not any("last_trade_date omitted" in warning for warning in result.warnings)


def test_build_cf_research_mapping_allows_partial_to_date_calendar(
    tmp_path: Path,
) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    calendar_path = tmp_path / "CZCE_2026_OFFICIAL_TO_DATE.csv"
    _write_partial_to_date_calendar(calendar_path)
    _write_quote_rows(
        core_path,
        [
            _quote("CF607", date(2026, 6, 24), volume=100, oi=4000),
            _quote("CF609", date(2026, 6, 24), volume=100, oi=6000),
            _quote("CF607", date(2026, 6, 25), volume=100, oi=4100),
            _quote("CF609", date(2026, 6, 25), volume=100, oi=6100),
        ],
    )

    result = build_cf_research_mapping(
        start=date(2026, 6, 24),
        end=date(2026, 6, 25),
        core_quote_path=core_path,
        calendar_path=calendar_path,
        output_dir=tmp_path / "research_mapping",
        report_output_dir=tmp_path / "reports",
    )

    assert [row.mapped_contract for row in result.chain_rows] == ["CF609", "CF609"]
    assert result.trade_rows[0].target_contract == "CF609"
    assert any("partial official calendar" in warning for warning in result.warnings)
    assert any("HUMAN_REVIEW_REQUIRED" in warning for warning in result.warnings)


def _write_quote_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [row.model_dump(mode="json") for row in load_core_quote_daily_csv(QUOTE_FIXTURE)]
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_quote_rows(path: Path, rows: list[CoreQuoteDailyRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)


def _quote(contract_code: str, trade_date: date, *, volume: int, oi: int) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"raw_{contract_code}_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        trade_date=trade_date,
        settle=15000,
        volume=volume,
        open_interest=oi,
    )


def _write_partial_to_date_calendar(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = date(2026, 1, 1)
    end = date(2026, 7, 1)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "exchange",
                "trade_date",
                "is_trading_day",
                "calendar_version",
                "source_snapshot_id",
            ],
        )
        writer.writeheader()
        while current <= end:
            writer.writerow(
                {
                    "exchange": "CZCE",
                    "trade_date": current.isoformat(),
                    "is_trading_day": "true" if current.weekday() < 5 else "false",
                    "calendar_version": "CZCE_OFFICIAL_2026_TO_DATE_TEST",
                    "source_snapshot_id": "test_partial_calendar",
                }
            )
            current += timedelta(days=1)
