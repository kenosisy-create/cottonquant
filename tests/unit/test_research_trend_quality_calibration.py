from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import (
    build_cf_trend_continuity_board,
    build_cf_trend_quality_calibration,
)


def test_build_cf_trend_quality_calibration_writes_history_context(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_trend_quality_core_quotes(tmp_path)

    result = build_cf_trend_quality_calibration(
        core_quote_path=core_path,
        output_dir=tmp_path / "research",
        report_output_dir=tmp_path / "reports",
        run_id="r32_unit_calibration",
        horizons=(1, 3),
    )

    assert result.start == trade_dates[0]
    assert result.end == trade_dates[-1]
    assert result.daily_row_count == len(trade_dates)
    assert result.bucket_summary_row_count >= 1
    assert result.phase_distribution_row_count >= 1
    assert result.latest_main_contract == "CF405"
    assert 0 <= result.latest_score_percentile <= 1
    assert result.latest_score_context_label in {"历史低位", "历史中位", "历史高位"}
    assert result.daily_parquet_path.exists()
    assert result.daily_csv_path.exists()
    assert result.bucket_summary_parquet_path.exists()
    assert result.phase_distribution_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    daily = pd.read_parquet(result.daily_parquet_path)
    assert "trend_quality_score" in daily.columns
    assert "trend_quality_score_bucket" in daily.columns
    assert "forward_return_h1" in daily.columns
    assert "forward_label_available_h1" in daily.columns
    assert daily.iloc[0]["calibration_rule_version"] == "R32_trend_quality_calibration_v1"
    assert bool(daily.iloc[0]["forward_label_available_h1"]) is True
    assert bool(daily.iloc[-1]["forward_label_available_h1"]) is False

    bucket_summary = pd.read_parquet(result.bucket_summary_parquet_path)
    assert {"score_bucket", "horizon", "mean_forward_return", "directional_hit_rate"} <= set(
        bucket_summary.columns
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["score_no_lookahead"] is True
    assert payload["forward_returns_are_validation_labels"] is True
    assert payload["latest_context"]["latest_score_bucket"] == result.latest_score_bucket
    assert payload["trend_quality_rule_version"] == "R31_trend_quality_score_v1"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 趋势质量历史校准" in markdown
    assert "最新分数历史位置" in markdown
    assert "分数段后验表现" in markdown
    assert "forward_return_* 仅用于历史后验校准" in markdown
    assert "本报告不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["score_no_lookahead"] is True
    assert manifest["forward_returns_are_validation_labels"] is True


def test_trend_quality_score_matches_same_day_board_before_forward_labels(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_trend_quality_core_quotes(tmp_path)
    target_date = trade_dates[24]

    calibration = build_cf_trend_quality_calibration(
        start=trade_dates[20],
        end=target_date,
        core_quote_path=core_path,
        output_dir=tmp_path / "calibration",
        report_output_dir=tmp_path / "calibration_reports",
        run_id="r32_unit_no_lookahead",
        horizons=(1,),
    )
    same_day_board = build_cf_trend_continuity_board(
        trade_date=target_date,
        core_quote_path=core_path,
        output_root=tmp_path / "daily",
        run_id="r29_unit_same_day",
        lookback_trading_days=100,
    )

    daily = pd.read_parquet(calibration.daily_parquet_path)
    latest_row = daily.iloc[-1]
    assert int(latest_row["trend_quality_score"]) == same_day_board.latest_trend_quality_score
    assert latest_row["trend_quality_label"] == same_day_board.latest_trend_quality_label
    assert "forward_return_h1" in daily.columns


def test_build_cf_trend_quality_calibration_validates_window(tmp_path: Path) -> None:
    core_path, _ = _write_trend_quality_core_quotes(tmp_path)

    with pytest.raises(ResearchWorkbenchError, match="start must be <= end"):
        build_cf_trend_quality_calibration(
            start=date(2024, 2, 1),
            end=date(2024, 1, 1),
            core_quote_path=core_path,
            output_dir=tmp_path / "research",
            report_output_dir=tmp_path / "reports",
        )


def _write_trend_quality_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=35)
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset * 1.5
        if offset >= 25:
            main_settle = 140 - (offset - 25) * 0.7
        rows.extend(
            [
                _quote(
                    contract_code="CF403",
                    trade_date=trade_date,
                    settle=main_settle - 2,
                    volume=700 + offset,
                    open_interest=7_000 + offset,
                ),
                _quote(
                    contract_code="CF405",
                    trade_date=trade_date,
                    settle=main_settle,
                    volume=1_000 + offset,
                    open_interest=10_000 + offset * 150,
                ),
                _quote(
                    contract_code="CF409",
                    trade_date=trade_date,
                    settle=main_settle + 4,
                    volume=600 + offset,
                    open_interest=6_000 + offset,
                ),
            ]
        )
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path, trade_dates


def _business_dates(start: date, *, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def _quote(
    *,
    contract_code: str,
    trade_date: date,
    settle: float,
    volume: int,
    open_interest: int,
) -> dict[str, object]:
    return {
        "source_snapshot_id": f"r32_fixture_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }
