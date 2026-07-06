from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import (
    build_cf_signal_matrix,
    build_cf_signal_matrix_validation,
)


def test_build_cf_signal_matrix_validation_writes_rolling_outputs(tmp_path: Path) -> None:
    core_path, trade_dates = _write_core_quotes(tmp_path)
    matrix = build_cf_signal_matrix(
        start=trade_dates[5],
        end=trade_dates[-1],
        horizons=(1, 3, 5),
        core_quote_path=core_path,
        output_dir=tmp_path / "matrix",
        report_output_dir=tmp_path / "matrix_reports",
        run_id="r35_for_r36",
    )

    result = build_cf_signal_matrix_validation(
        signal_matrix_path=matrix.matrix_parquet_path,
        core_quote_path=core_path,
        output_dir=tmp_path / "validation",
        report_output_dir=tmp_path / "validation_reports",
        run_id="r36_unit_validation",
        windows=("2024",),
    )

    assert result.daily_row_count == matrix.row_count
    assert result.window_summary_row_count == 3
    assert result.phase_summary_row_count >= 1
    assert result.daily_parquet_path.exists()
    assert result.window_summary_parquet_path.exists()
    assert result.phase_summary_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    daily = pd.read_parquet(result.daily_parquet_path)
    assert "forward_return" in daily.columns
    assert "forward_label_available" in daily.columns
    assert "directional_hit" in daily.columns
    assert "validation_rule_version" in daily.columns
    assert bool(daily.iloc[0]["forward_returns_are_validation_labels"]) is True
    assert daily["forward_label_available"].sum() > 0

    summary = pd.read_parquet(result.window_summary_parquet_path)
    assert {"window_id", "horizon", "mean_forward_return", "directional_hit_rate"} <= set(
        summary.columns
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "signal_matrix_rolling_validation"
    assert payload["forward_returns_are_validation_labels"] is True
    assert payload["source_signal_matrix_rule_version"] == "R35_signal_matrix_v1"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 多周期信号矩阵滚动验证" in markdown
    assert "窗口表现" in markdown
    assert "forward_return 只用于 R36 历史后验验证" in markdown
    assert "本报告不构成交易指令" in markdown


def test_cli_build_cf_signal_matrix_validation(tmp_path: Path) -> None:
    core_path, trade_dates = _write_core_quotes(tmp_path)
    matrix = build_cf_signal_matrix(
        start=trade_dates[5],
        end=trade_dates[-1],
        horizons=(1, 3),
        core_quote_path=core_path,
        output_dir=tmp_path / "matrix",
        report_output_dir=tmp_path / "matrix_reports",
        run_id="r35_cli_for_r36",
    )

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-signal-matrix-validation",
            "--signal-matrix-path",
            str(matrix.matrix_parquet_path),
            "--core-quote-path",
            str(core_path),
            "--output-dir",
            str(tmp_path / "validation"),
            "--report-output-dir",
            str(tmp_path / "validation_reports"),
            "--run-id",
            "r36_cli",
            "--windows",
            "2024",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["daily_row_count"] == matrix.row_count
    assert output["windows"] == ["2024"]
    assert Path(output["window_summary_parquet_path"]).exists()


def _write_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=55)
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset * 1.1
        if offset >= 42:
            main_settle = 146 - (offset - 42) * 0.4
        rows.extend(
            [
                _quote("CF403", trade_date, main_settle - 2, 700 + offset, 7_000 + offset),
                _quote("CF405", trade_date, main_settle, 1_000 + offset, 10_000 + offset * 90),
                _quote("CF409", trade_date, main_settle + 4, 600 + offset, 6_000 + offset),
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
    contract_code: str,
    trade_date: date,
    settle: float,
    volume: int,
    open_interest: int,
) -> dict[str, object]:
    return {
        "source_snapshot_id": f"r36_fixture_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }
