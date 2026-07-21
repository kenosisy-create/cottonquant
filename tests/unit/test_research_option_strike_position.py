from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_option_strike_position_research


def test_option_strike_position_builds_walls_migration_and_tplus1_labels(
    tmp_path: Path,
) -> None:
    option_path = _write_option_core(tmp_path)
    quote_path = _write_quotes(tmp_path)
    expiry_path = _write_expiry_registry(tmp_path)

    result = build_cf_option_strike_position_research(
        option_core_path=option_path,
        core_quote_path=quote_path,
        option_expiry_path=expiry_path,
        horizons=(1, 3),
        min_sample_size=1,
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="r84_unit",
    )

    assert result.latest_main_contract == "CF609"
    assert result.latest_call_wall == 120
    assert result.latest_put_wall == 110
    assert result.validation_summary_row_count > 0
    daily = pd.read_parquet(result.daily_parquet_path)
    second = daily.loc[daily["trade_date"].astype(str).eq("2026-07-14")].iloc[0]
    assert second["call_wall_strike"] == 120
    assert second["call_wall_strike_shift_1d"] == 10
    assert second["put_wall_strike_shift_1d"] == 10
    assert second["key_level_migration_state"] == "BOTH_WALLS_UP"
    assert second["call_build_strike"] == 120
    validation = pd.read_parquet(result.validation_parquet_path)
    available = validation.loc[validation["forward_label_available"].astype(bool)]
    assert not available.empty
    assert pd.to_datetime(available["execution_date"]).gt(
        pd.to_datetime(available["trade_date"])
    ).all()
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "期权行权价持仓关键点位研究" in report
    assert "不推断做市商净 Gamma" in report
    assert "不构成交易指令" in report


def test_option_strike_position_cli_writes_json_and_tables(tmp_path: Path) -> None:
    option_path = _write_option_core(tmp_path)
    quote_path = _write_quotes(tmp_path)
    expiry_path = _write_expiry_registry(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-option-strike-position-research",
            "--option-core-path",
            str(option_path),
            "--core-quote-path",
            str(quote_path),
            "--option-expiry-path",
            str(expiry_path),
            "--horizons",
            "1,3",
            "--min-sample-size",
            "1",
            "--output-dir",
            str(tmp_path / "data"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r84_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["latest_main_contract"] == "CF609"
    assert Path(output["daily_parquet_path"]).exists()
    assert Path(output["json_path"]).exists()


def _write_option_core(tmp_path: Path) -> Path:
    dates = pd.date_range("2026-07-13", periods=5, freq="D")
    rows: list[dict[str, object]] = []
    call_oi = [
        (100, 300, 200),
        (100, 250, 500),
        (120, 240, 520),
        (130, 230, 540),
        (140, 220, 560),
    ]
    put_oi = [
        (400, 200, 100),
        (200, 500, 100),
        (180, 520, 110),
        (170, 540, 120),
        (160, 560, 130),
    ]
    for index, trade_date in enumerate(dates):
        for strike_index, strike in enumerate((100, 110, 120)):
            for option_type, values in (("C", call_oi), ("P", put_oi)):
                rows.append(
                    {
                        "trade_date": trade_date.date().isoformat(),
                        "option_symbol": f"CF609{option_type}{strike}",
                        "underlying_contract": "CF609",
                        "option_type": option_type,
                        "strike": strike,
                        "open_interest": values[index][strike_index],
                        "data_quality_flag": "normal",
                    }
                )
    path = tmp_path / "core_option_quote_daily.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_quotes(tmp_path: Path) -> Path:
    dates = pd.date_range("2026-07-13", periods=8, freq="D")
    rows = []
    for index, trade_date in enumerate(dates):
        settle = 105 + index
        rows.append(
            {
                "trade_date": trade_date.date().isoformat(),
                "contract_code": "CF609",
                "settle": settle,
                "high": settle + 3,
                "low": settle - 3,
                "open_interest": 2000 - index * 10,
            }
        )
        rows.append(
            {
                "trade_date": trade_date.date().isoformat(),
                "contract_code": "CF611",
                "settle": settle + 1,
                "high": settle + 4,
                "low": settle - 2,
                "open_interest": 1000 + index * 5,
            }
        )
    path = tmp_path / "core_quote_daily.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_expiry_registry(tmp_path: Path) -> Path:
    path = tmp_path / "expiry.csv"
    pd.DataFrame(
        [
            {
                "underlying_contract": "CF609",
                "option_expiry_date": "2026-08-12",
                "rule_code": "CZCE_OPTION_PREV_MONTH_DAY15_THIRD_LAST_TRADING_DAY",
                "source_name": "unit fixture",
                "source_url": "https://www.czce.com.cn/",
                "quality_flag": "OFFICIAL_RULE_AND_2026_HOLIDAY_SCHEDULE",
                "human_review_required": False,
            }
        ]
    ).to_csv(path, index=False)
    return path
