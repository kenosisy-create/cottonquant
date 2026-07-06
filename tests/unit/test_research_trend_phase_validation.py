from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_trend_phase_validation


def test_build_cf_trend_phase_validation_writes_daily_summary_and_report(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_trend_phase_validation_core_quotes(tmp_path)
    start = trade_dates[20]
    end = trade_dates[25]

    result = build_cf_trend_phase_validation(
        start=start,
        end=end,
        horizons=(1, 3),
        core_quote_path=core_path,
        output_dir=tmp_path / "trend_phase",
        report_output_dir=tmp_path / "reports",
        run_id="r25_unit_validation",
    )

    assert result.daily_row_count == 6
    assert result.summary_row_count >= 2
    assert result.warning_count == 0
    assert result.daily_parquet_path.exists()
    assert result.daily_csv_path.exists()
    assert result.summary_parquet_path.exists()
    assert result.summary_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.manifest_path.exists()

    daily = pd.read_parquet(result.daily_parquet_path)
    first = daily.loc[daily["trade_date"].eq(start.isoformat())].iloc[0]
    assert first["main_contract"] == "CF405"
    assert first["trend_phase_code"] == "S2"
    assert first["multi_factor_direction"] == "long"
    assert first["return_20d"] == pytest.approx(120 / 100 - 1)
    assert first["forward_return_h1"] == pytest.approx(122 / 121 - 1)
    assert first["forward_return_h3"] == pytest.approx(124 / 121 - 1)
    assert first["execution_date_h1"] == trade_dates[21].isoformat()
    assert first["exit_date_h1"] == trade_dates[22].isoformat()

    summary = pd.read_parquet(result.summary_parquet_path)
    s2_h1 = summary.loc[
        summary["phase_code"].eq("S2") & summary["horizon"].eq(1)
    ].iloc[0]
    assert s2_h1["observation_count"] == 6
    assert s2_h1["directional_hit_rate"] == pytest.approx(1.0)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "趋势阶段判断只使用 T 日及以前可观察数据" in markdown
    assert "forward_return_* 是后验验证标签" in markdown
    assert "本报告不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase_no_lookahead"] is True
    assert manifest["forward_returns_are_validation_labels"] is True


def test_build_cf_trend_phase_validation_validates_horizons(tmp_path: Path) -> None:
    core_path, trade_dates = _write_trend_phase_validation_core_quotes(tmp_path)

    with pytest.raises(ResearchWorkbenchError, match="positive integers"):
        build_cf_trend_phase_validation(
            start=trade_dates[20],
            end=trade_dates[21],
            horizons=(0,),
            core_quote_path=core_path,
            output_dir=tmp_path / "trend_phase",
            report_output_dir=tmp_path / "reports",
        )


def _write_trend_phase_validation_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=35)
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset
        rows.extend(
            [
                _quote(
                    contract_code="CF403",
                    trade_date=trade_date,
                    settle=main_settle - 2,
                    volume=800 + offset,
                    open_interest=7_000 + offset,
                ),
                _quote(
                    contract_code="CF405",
                    trade_date=trade_date,
                    settle=main_settle,
                    volume=1_000 + offset,
                    open_interest=10_000 + offset * 100,
                ),
                _quote(
                    contract_code="CF409",
                    trade_date=trade_date,
                    settle=main_settle + 4,
                    volume=700 + offset,
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
        "source_snapshot_id": f"r25_fixture_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }
