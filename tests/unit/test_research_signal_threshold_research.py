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
    build_cf_signal_threshold_research,
)


def test_build_cf_signal_threshold_research_writes_candidate_tables(tmp_path: Path) -> None:
    validation = _build_validation_fixture(tmp_path)

    result = build_cf_signal_threshold_research(
        validation_daily_path=validation.daily_parquet_path,
        output_dir=tmp_path / "thresholds",
        report_output_dir=tmp_path / "threshold_reports",
        run_id="r37_unit_thresholds",
    )

    assert result.threshold_row_count > 0
    assert result.weighting_row_count > 0
    assert result.threshold_parquet_path.exists()
    assert result.weighting_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    thresholds = pd.read_parquet(result.threshold_parquet_path)
    assert {"factor_id", "horizon", "bucket_id", "mean_forward_return"} <= set(
        thresholds.columns
    )
    assert "candidate_status" in thresholds.columns
    assert set(thresholds["bucket_id"]) <= {"low", "middle", "high"}

    weights = pd.read_parquet(result.weighting_parquet_path)
    assert {"scheme_id", "horizon", "coverage_rate", "directional_hit_rate"} <= set(
        weights.columns
    )
    assert "matrix_all" in set(weights["scheme_id"])

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "signal_threshold_weight_research"
    assert payload["forward_returns_are_validation_labels"] is True
    assert payload["source_validation_rule_version"] == "R36_signal_matrix_rolling_validation_v1"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 因子阈值与权重研究" in markdown
    assert "权重与过滤方案候选" in markdown
    assert "R37 只形成阈值和权重候选" in markdown
    assert "本报告不构成交易指令" in markdown


def test_cli_build_cf_signal_threshold_research(tmp_path: Path) -> None:
    validation = _build_validation_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-signal-threshold-research",
            "--validation-daily-path",
            str(validation.daily_parquet_path),
            "--output-dir",
            str(tmp_path / "thresholds"),
            "--report-output-dir",
            str(tmp_path / "threshold_reports"),
            "--run-id",
            "r37_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["threshold_row_count"] > 0
    assert output["weighting_row_count"] > 0
    assert Path(output["threshold_parquet_path"]).exists()


def _build_validation_fixture(tmp_path: Path):
    core_path, trade_dates = _write_core_quotes(tmp_path)
    matrix = build_cf_signal_matrix(
        start=trade_dates[5],
        end=trade_dates[-1],
        horizons=(1, 3, 5),
        core_quote_path=core_path,
        output_dir=tmp_path / "matrix",
        report_output_dir=tmp_path / "matrix_reports",
        run_id="r35_for_r37",
    )
    return build_cf_signal_matrix_validation(
        signal_matrix_path=matrix.matrix_parquet_path,
        core_quote_path=core_path,
        output_dir=tmp_path / "validation",
        report_output_dir=tmp_path / "validation_reports",
        run_id="r36_for_r37",
        windows=("2024",),
    )


def _write_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=58)
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset * 1.2
        if offset >= 44:
            main_settle = 150 - (offset - 44) * 0.45
        rows.extend(
            [
                _quote("CF403", trade_date, main_settle - 2, 700 + offset, 7_000 + offset),
                _quote("CF405", trade_date, main_settle, 1_000 + offset, 10_000 + offset * 100),
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
        "source_snapshot_id": f"r37_fixture_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }
