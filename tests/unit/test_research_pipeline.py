from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.research_workbench import build_cf_daily_research_pipeline


def test_build_cf_daily_research_pipeline_writes_brief_and_run_log(tmp_path: Path) -> None:
    input_path = _write_pipeline_inputs(tmp_path)

    result = build_cf_daily_research_pipeline(
        trade_date=date(2024, 1, 10),
        input_path=input_path,
        start=date(2024, 1, 9),
        end=date(2024, 1, 12),
        raw_output_dir=tmp_path / "raw",
        core_output_dir=tmp_path / "core",
        research_output_root=tmp_path / "research",
        report_output_root=tmp_path / "reports",
        run_id="r20_pipeline_test",
        horizons=(1,),
        scenario_cost_bps={"normal_cost": 5.0},
        lookback_periods=1,
    )

    assert result.status == "COMPLETED"
    assert result.passed is True
    assert [step.task_id for step in result.steps] == [
        "R04",
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R10",
        "R11",
        "R12",
        "R13",
        "R14",
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
    ]
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert Path(result.artifacts["build_cf_daily_brief.markdown_path"]).exists()
    assert "factor_thresholds" in result.human_review_required

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETED"
    assert payload["steps"][-1]["step_id"] == "build_cf_daily_brief"


def test_cli_research_run_cf_daily_pipeline(tmp_path: Path) -> None:
    input_path = _write_pipeline_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "run-cf-daily-pipeline",
            "--date",
            "2024-01-10",
            "--start",
            "2024-01-09",
            "--end",
            "2024-01-12",
            "--input-path",
            str(input_path),
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--core-output-dir",
            str(tmp_path / "core"),
            "--research-output-root",
            str(tmp_path / "research"),
            "--report-output-root",
            str(tmp_path / "reports"),
            "--run-id",
            "r20_cli_pipeline",
            "--horizons",
            "1",
            "--scenario-cost-bps",
            "normal_cost=5",
            "--lookback-periods",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "COMPLETED"
    assert output["step_count"] == 16
    assert Path(output["artifacts"]["build_cf_daily_brief.json_path"]).exists()


def _write_pipeline_inputs(tmp_path: Path) -> Path:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    core_path.parent.mkdir(parents=True)
    rows = [
        row.model_dump(mode="json")
        for row in _core_quote_rows(
            [
                date(2024, 1, 8),
                date(2024, 1, 9),
                date(2024, 1, 10),
                date(2024, 1, 11),
                date(2024, 1, 12),
                date(2024, 1, 15),
                date(2024, 1, 16),
            ]
        )
    ]
    pd.DataFrame(rows).to_parquet(core_path, index=False)

    input_path = tmp_path / "incoming" / "cf_2024-01-10.csv"
    input_path.parent.mkdir(parents=True)
    input_path.write_text(
        "\n".join(
            [
                "trade_date,exchange,product_code,contract_id,open,high,low,close,settle,"
                "volume,open_interest",
                "2024-01-10,CZCE,CF,CF405,15100,15200,15050,15150,15130,1200,5200",
                "2024-01-10,CZCE,CF,CF409,15300,15400,15250,15350,15330,600,3100",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return input_path


def _core_quote_rows(trade_dates: list[date]) -> list[CoreQuoteDailyRow]:
    rows: list[CoreQuoteDailyRow] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 15100 + offset * 10
        far_settle = 15300 + offset * 8
        rows.extend(
            [
                CoreQuoteDailyRow(
                    source_snapshot_id=f"preseed_main_{trade_date:%Y%m%d}",
                    exchange="CZCE",
                    product_code="CF",
                    contract_code="CF405",
                    trade_date=trade_date,
                    open=float(main_settle - 20),
                    high=float(main_settle + 80),
                    low=float(main_settle - 60),
                    close=float(main_settle + 15),
                    settle=float(main_settle),
                    pre_settle=float(main_settle - 10),
                    volume=1000 + offset * 50,
                    open_interest=5000 + offset * 100,
                    turnover=1_000_000.0 + offset * 1000,
                    quote_status="normal",
                ),
                CoreQuoteDailyRow(
                    source_snapshot_id=f"preseed_far_{trade_date:%Y%m%d}",
                    exchange="CZCE",
                    product_code="CF",
                    contract_code="CF409",
                    trade_date=trade_date,
                    open=float(far_settle - 20),
                    high=float(far_settle + 80),
                    low=float(far_settle - 60),
                    close=float(far_settle + 15),
                    settle=float(far_settle),
                    pre_settle=float(far_settle - 10),
                    volume=600 + offset * 20,
                    open_interest=3000 + offset * 50,
                    turnover=800_000.0 + offset * 1000,
                    quote_status="normal",
                ),
            ]
        )
    return rows
