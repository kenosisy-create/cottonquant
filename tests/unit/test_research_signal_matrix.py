from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_signal_matrix


def test_build_cf_signal_matrix_writes_multi_horizon_outputs(tmp_path: Path) -> None:
    core_path, trade_dates = _write_signal_matrix_core_quotes(tmp_path)

    result = build_cf_signal_matrix(
        start=trade_dates[10],
        end=trade_dates[-1],
        horizons=(1, 5, 20, 40),
        core_quote_path=core_path,
        output_dir=tmp_path / "research",
        report_output_dir=tmp_path / "reports",
        run_id="r35_unit_matrix",
    )

    assert result.start == trade_dates[10]
    assert result.end == trade_dates[-1]
    assert result.trade_day_count == len(trade_dates[10:])
    assert result.row_count == result.trade_day_count * 4
    assert result.latest_main_contract == "CF405"
    assert result.latest_primary_direction in {"long", "short", "neutral"}
    assert result.matrix_parquet_path.exists()
    assert result.matrix_csv_path.exists()
    assert result.latest_snapshot_json_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    matrix = pd.read_parquet(result.matrix_parquet_path)
    assert set(matrix["horizon"]) == {1, 5, 20, 40}
    assert {
        "trade_date",
        "horizon",
        "price_signal",
        "momentum_signal",
        "carry_signal",
        "curve_signal",
        "oi_signal",
        "option_signal",
        "regime_state",
        "trend_phase",
        "composite_score",
        "confidence_score",
        "evidence_level",
        "action_type",
        "warning_flags",
    } <= set(matrix.columns)
    latest_20d = matrix.loc[
        (matrix["trade_date"] == trade_dates[-1].isoformat()) & (matrix["horizon"] == 20)
    ].iloc[0]
    assert latest_20d["main_contract"] == "CF405"
    assert latest_20d["option_signal"] == "not_connected"
    assert bool(latest_20d["no_future_return_labels"]) is True

    snapshot = json.loads(result.latest_snapshot_json_path.read_text(encoding="utf-8"))
    assert snapshot["report_type"] == "signal_matrix_latest_snapshot"
    assert len(snapshot["latest_rows"]) == 4

    payload_text = result.json_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    assert payload["report_type"] == "signal_matrix"
    assert payload["no_future_return_labels"] is True
    assert "forward_return_h" not in payload_text

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 多周期信号矩阵" in markdown
    assert "最新多周期观察" in markdown
    assert "不包含未来收益标签" in markdown
    assert "本表用于研究观察，不构成交易指令" in markdown
    assert "forward_return_h" not in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["no_lookahead"] is True
    assert manifest["contains_forward_return_validation"] is False


def test_build_cf_signal_matrix_connects_option_factor_filter(tmp_path: Path) -> None:
    core_path, trade_dates = _write_signal_matrix_core_quotes(tmp_path)
    option_factor_path = _write_option_factor_proxy(tmp_path, trade_date=trade_dates[-1])

    result = build_cf_signal_matrix(
        start=trade_dates[-3],
        end=trade_dates[-1],
        horizons=(20,),
        core_quote_path=core_path,
        option_factor_path=option_factor_path,
        output_dir=tmp_path / "research",
        report_output_dir=tmp_path / "reports",
        run_id="r49_unit_option_filter",
    )

    matrix = pd.read_parquet(result.matrix_parquet_path)
    latest = matrix.loc[matrix["trade_date"] == trade_dates[-1].isoformat()].iloc[0]
    assert latest["option_signal"] != "not_connected"
    assert latest["option_signal_direction"] == "long"
    assert latest["option_factor_status"] == "READY"
    assert latest["option_pcr_volume"] == pytest.approx(0.55)
    if latest["direction"] == "long":
        assert latest["option_signal"] == "confirm_long"
    elif latest["direction"] == "short":
        assert latest["option_signal"] == "diverge_short"
    else:
        assert latest["option_signal"] == "option_long"

    warning_text = result.warning_csv_path.read_text(encoding="utf-8")
    assert "R49_OPTION_SIGNAL_FILTER_CONNECTED" in warning_text
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "期权过滤" in markdown


def test_build_cf_signal_matrix_validates_window(tmp_path: Path) -> None:
    core_path, _ = _write_signal_matrix_core_quotes(tmp_path)

    with pytest.raises(ResearchWorkbenchError, match="start must be <= end"):
        build_cf_signal_matrix(
            start=date(2024, 3, 1),
            end=date(2024, 1, 1),
            core_quote_path=core_path,
            output_dir=tmp_path / "research",
            report_output_dir=tmp_path / "reports",
        )


def test_cli_build_cf_signal_matrix(tmp_path: Path) -> None:
    core_path, trade_dates = _write_signal_matrix_core_quotes(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-signal-matrix",
            "--start",
            trade_dates[5].isoformat(),
            "--end",
            trade_dates[-1].isoformat(),
            "--horizons",
            "1,3,5",
            "--core-quote-path",
            str(core_path),
            "--output-dir",
            str(tmp_path / "research"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r35_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["row_count"] == (len(trade_dates) - 5) * 3
    assert output["latest_main_contract"] == "CF405"
    assert Path(output["matrix_parquet_path"]).exists()


def _write_signal_matrix_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=48)
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset * 1.4
        if offset >= 38:
            main_settle = 154 - (offset - 38) * 0.5
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
                    open_interest=10_000 + offset * 120,
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


def _write_option_factor_proxy(tmp_path: Path, *, trade_date: date) -> Path:
    path = tmp_path / "option_factors" / "CF_option_factor_proxy_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "trade_date": trade_date.isoformat(),
                "underlying_contract": "CF405",
                "factor_status": "READY",
                "atm_iv_rank": 0.35,
                "pcr_volume": 0.55,
                "pcr_oi": 0.70,
                "skew_proxy": -0.002,
            }
        ]
    ).to_parquet(path, index=False)
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
    volume: int,
    open_interest: int,
) -> dict[str, object]:
    return {
        "source_snapshot_id": f"r35_fixture_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }
