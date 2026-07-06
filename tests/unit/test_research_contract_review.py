from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from cotton_factor.research_workbench import build_cf_contract_rule_review


def test_build_cf_contract_rule_review_writes_human_review_artifacts(tmp_path: Path) -> None:
    result = build_cf_contract_rule_review(
        year=2024,
        report_output_dir=tmp_path / "contract_rules",
    )

    assert result.product_code == "CF"
    assert result.csv_path.exists()
    assert result.markdown_path.exists()
    assert result.human_review_required_count > 0
    assert result.blocks_production_count > 0
    assert any(row.field_name == "tick_size" for row in result.rows)
    assert any(row.field_name == "last_trade_day_rule" for row in result.rows)
    assert any(row.contract_code == "CF405" and row.last_trade_date for row in result.rows)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF Contract Rule Review" in markdown
    assert "HUMAN_REVIEW_REQUIRED" in markdown


def test_build_cf_contract_rule_review_marks_missing_calendar(tmp_path: Path) -> None:
    result = build_cf_contract_rule_review(
        year=2024,
        calendar_path=tmp_path / "missing_calendar.csv",
        report_output_dir=tmp_path / "contract_rules",
    )

    assert any("official calendar missing" in warning for warning in result.warnings)
    contract_rows = [row for row in result.rows if row.row_type == "contract"]
    assert contract_rows
    assert all(row.review_status == "MISSING_CALENDAR" for row in contract_rows)
    assert all(row.human_review_required for row in contract_rows)


def test_build_cf_contract_rule_review_allows_partial_to_date_calendar(
    tmp_path: Path,
) -> None:
    calendar_path = tmp_path / "CZCE_2026_OFFICIAL_TO_DATE.csv"
    _write_partial_to_date_calendar(calendar_path)

    result = build_cf_contract_rule_review(
        year=2026,
        calendar_path=calendar_path,
        report_output_dir=tmp_path / "contract_rules",
    )

    rows_by_contract = {
        row.contract_code: row for row in result.rows if row.row_type == "contract"
    }
    assert rows_by_contract["CF601"].last_trade_date == "2026-01-14"
    assert rows_by_contract["CF607"].review_status == "MISSING_CALENDAR"
    assert rows_by_contract["CF607"].human_review_required is True
    assert rows_by_contract["CF609"].blocks_production is True
    assert any("partial official calendar" in warning for warning in result.warnings)
    assert result.markdown_path.exists()


def _write_partial_to_date_calendar(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = date(2026, 1, 1)
    end = date(2026, 7, 1)
    current = start
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
            # 单元测试使用“截至当日”的官方日历形态，未来月份必须显式留给人工复核。
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
