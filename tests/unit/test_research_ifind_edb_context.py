from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.ifind_edb_context import (
    COTTON_EDB,
    FX_SWAP_TENORS,
    connect_cf_ifind_edb_context,
)


def test_r93h_builder_and_cli_write_normalized_observation_only_artifacts(
    tmp_path: Path,
) -> None:
    source_dir = _write_source_bundle(tmp_path)
    result = connect_cf_ifind_edb_context(
        source_dir=source_dir,
        as_of_date=date(2026, 8, 1),
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="r93h_unit",
    )

    assert result.cotton_row_count == len(COTTON_EDB) * 2
    assert result.fx_swap_row_count == len(FX_SWAP_TENORS) * 2
    assert result.latest_spot_date == date(2026, 7, 31)
    for path in (
        result.cotton_context_path,
        result.spot_extension_path,
        result.policy_event_path,
        result.yarn_price_path,
        result.fx_swap_curve_path,
        result.quality_csv_path,
        result.warning_csv_path,
        result.json_path,
        result.manifest_path,
        result.markdown_path,
    ):
        assert path.exists()
        assert path.stat().st_size > 0

    spot = pd.read_parquet(result.spot_extension_path)
    policy = pd.read_parquet(result.policy_event_path)
    assert set(spot["indicator_id"]) == {"S002885871"}
    assert len(policy) == 8
    assert policy["trade_date"].min() == pd.Timestamp("2026-07-30")
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["contains_forward_labels"] is False
    assert payload["signal_status"] == "not_connected"
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "不能替代即期汇率" in report
    assert "不进入策略评分" in report

    cli_result = CliRunner().invoke(
        app,
        [
            "research",
            "connect-cf-ifind-edb-context",
            "--source-dir",
            str(source_dir),
            "--as-of-date",
            "2026-08-01",
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "r93h_cli",
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    cli_payload = json.loads(cli_result.output)
    assert cli_payload["run_id"] == "r93h_cli"
    assert cli_payload["signal_status"] == "not_connected"


def test_r93h_rejects_future_rows_and_missing_indicator_set(tmp_path: Path) -> None:
    source_dir = _write_source_bundle(tmp_path)
    cotton_path = source_dir / "cotton_policy_spot_yarn_edb.parquet"
    cotton = pd.read_parquet(cotton_path)
    cotton.loc[0, "date"] = "2026-08-02"
    cotton.to_parquet(cotton_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="future-dated"):
        connect_cf_ifind_edb_context(
            source_dir=source_dir,
            as_of_date=date(2026, 8, 1),
            output_dir=tmp_path / "future_data",
            report_output_dir=tmp_path / "future_reports",
        )

    source_dir = _write_source_bundle(tmp_path / "missing")
    cotton_path = source_dir / "cotton_policy_spot_yarn_edb.parquet"
    cotton = pd.read_parquet(cotton_path)
    cotton = cotton.loc[cotton["indicator"].ne("S002885871")]
    cotton.to_parquet(cotton_path, index=False)
    with pytest.raises(ResearchWorkbenchError, match="indicator set mismatch"):
        connect_cf_ifind_edb_context(
            source_dir=source_dir,
            as_of_date=date(2026, 8, 1),
            output_dir=tmp_path / "missing_data",
            report_output_dir=tmp_path / "missing_reports",
        )


def _write_source_bundle(tmp_path: Path) -> Path:
    source_dir = tmp_path / "incoming" / "2026-08-01"
    source_dir.mkdir(parents=True, exist_ok=True)
    cotton_rows: list[dict[str, object]] = []
    for indicator_id, (_, indicator_name, _) in COTTON_EDB.items():
        for trade_date, value in (("2026-07-30", 100.0), ("2026-07-31", 101.0)):
            cotton_rows.append(
                _raw_edb_row(
                    trade_date=trade_date,
                    indicator_id=indicator_id,
                    indicator_name=indicator_name,
                    value=value,
                )
            )
    fx_rows: list[dict[str, object]] = []
    for indicator_id, tenor in FX_SWAP_TENORS.items():
        for trade_date, value in (("2026-07-30", 1.0), ("2026-07-31", 1.1)):
            fx_rows.append(
                _raw_edb_row(
                    trade_date=trade_date,
                    indicator_id=indicator_id,
                    indicator_name=f"USD/CNY外汇掉期曲线:{tenor}",
                    value=value,
                )
            )
    pd.DataFrame(cotton_rows).to_parquet(
        source_dir / "cotton_policy_spot_yarn_edb.parquet",
        index=False,
    )
    pd.DataFrame(fx_rows).to_parquet(
        source_dir / "usdcny_swap_curve_edb.parquet",
        index=False,
    )
    return source_dir


def _raw_edb_row(
    *,
    trade_date: str,
    indicator_id: str,
    indicator_name: str,
    value: float,
) -> dict[str, object]:
    return {
        "date": trade_date,
        "indicator": indicator_id,
        "value": value,
        "source_func": "THS_EDB",
        "fetch_time": "2026-08-01T09:00:00+08:00",
        "index_name": indicator_name,
        "rtime": f"{trade_date} 15:00:00",
    }
