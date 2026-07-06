from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.research_workbench import build_cf_trend_turning_point_analysis


def test_build_cf_trend_turning_point_analysis_detects_confirmed_uptrend(
    tmp_path: Path,
) -> None:
    core_path = _write_core_quotes(tmp_path)

    result = build_cf_trend_turning_point_analysis(
        start=date(2025, 1, 2),
        end=date(2025, 3, 31),
        core_quote_path=core_path,
        output_dir=tmp_path / "trend",
        report_output_dir=tmp_path / "reports",
        momentum_lookback=5,
        ma_lookback=5,
        min_confirm_days=2,
    )

    segments = pd.read_parquet(result.segment_parquet_path)

    assert result.daily_row_count > 20
    assert result.segment_count >= 1
    assert "uptrend" in segments["direction"].to_list()
    first_uptrend = segments.loc[segments["direction"].eq("uptrend")].iloc[0]
    assert first_uptrend["confirmation_date"] > first_uptrend["start_date"]
    assert first_uptrend["trend_return"] > 0
    assert result.daily_csv_path.exists()
    assert result.segment_csv_path.exists()
    assert result.markdown_path.exists()


def _write_core_quotes(tmp_path: Path) -> Path:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    rows: list[CoreQuoteDailyRow] = []
    trade_dates = _business_dates(date(2025, 1, 2), count=45)
    for index, trade_date in enumerate(trade_dates):
        main_settle = 100 + index * 1.2
        far_settle = main_settle + 2
        oi = 1000 + index * 20
        rows.append(
            _quote(
                contract_code="CF505",
                trade_date=trade_date,
                settle=main_settle,
                open_interest=oi,
            )
        )
        rows.append(
            _quote(
                contract_code="CF509",
                trade_date=trade_date,
                settle=far_settle,
                open_interest=500 + index,
            )
        )
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(
        path,
        index=False,
    )
    return path


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
    open_interest: int,
) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=f"trend_fixture_{contract_code}_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code=contract_code,
        trade_date=trade_date,
        settle=settle,
        volume=100,
        open_interest=open_interest,
    )
