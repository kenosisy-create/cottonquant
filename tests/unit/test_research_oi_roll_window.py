from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_oi_roll_window_research


def test_build_cf_oi_roll_window_research(tmp_path: Path) -> None:
    core_path, validation_path = _write_inputs(tmp_path)
    result = build_cf_oi_roll_window_research(
        core_quote_path=core_path,
        validation_daily_path=validation_path,
        windows=(3, 5, 10),
        output_dir=tmp_path / "research",
        report_output_dir=tmp_path / "reports",
        run_id="r78_unit",
    )

    daily = pd.read_parquet(result.daily_parquet_path)
    summary = pd.read_parquet(result.summary_parquet_path)
    latest = daily.loc[daily["trade_date"].eq(result.end)]
    assert set(latest["window_days"]) == {3, 5, 10}
    assert set(latest["roll_context"]) == {"ROLL_WITH_NET_EXIT"}
    assert latest.loc[latest["window_days"].eq(5), "roll_transfer_ratio_window"].iloc[
        0
    ] == 0.75
    assert not summary.empty
    assert summary["forward_returns_are_validation_labels"].all()
    assert result.markdown_path.exists()
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "多窗口移仓与净退出研究" in markdown
    assert "移仓承接不等于新增趋势资金" in markdown
    assert "不构成交易指令" in markdown


def test_cf_oi_roll_window_cli_respects_end_date(tmp_path: Path) -> None:
    core_path, validation_path = _write_inputs(tmp_path)
    end = pd.bdate_range("2026-01-05", periods=12)[-1].date()
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-oi-roll-window-research",
            "--core-quote-path",
            str(core_path),
            "--validation-daily-path",
            str(validation_path),
            "--end",
            end.isoformat(),
            "--windows",
            "3,5,10",
            "--output-dir",
            str(tmp_path / "cli_research"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["end"] == end.isoformat()
    assert payload["windows"] == [3, 5, 10]
    assert Path(payload["daily_parquet_path"]).exists()


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    core_path = tmp_path / "core.parquet"
    validation_path = tmp_path / "validation.parquet"
    dates = pd.bdate_range("2026-01-05", periods=15)
    rows: list[dict[str, object]] = []
    validation_rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(dates):
        for contract, open_interest, settle in (
            ("CF609", 2000 - index * 20, 100.0 + index),
            ("CF611", 900 + index * 10, 101.0 + index),
            ("CF701", 500 + index * 5, 102.0 + index),
        ):
            rows.append(
                {
                    "trade_date": timestamp.date(),
                    "contract_code": contract,
                    "close": settle,
                    "settle": settle,
                    "volume": 1000,
                    "open_interest": open_interest,
                }
            )
        for horizon in (5, 10):
            validation_rows.append(
                {
                    "trade_date": timestamp.date(),
                    "main_contract": "CF609",
                    "horizon": horizon,
                    "forward_return": 0.01 if index % 2 == 0 else -0.005,
                    "forward_label_available": index < len(dates) - 2,
                    "directional_hit": 1 if index % 2 == 0 else 0,
                }
            )
    pd.DataFrame(rows).to_parquet(core_path, index=False)
    pd.DataFrame(validation_rows).to_parquet(validation_path, index=False)
    return core_path, validation_path
