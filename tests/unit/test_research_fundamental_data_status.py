from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench.fundamental_data_status import (
    build_cf_fundamental_data_status,
)
from cotton_factor.research_workbench.ifind_edb_context import COTTON_EDB, FX_SWAP_TENORS


def test_r93j_builds_frequency_aware_status_without_direction_signal(tmp_path: Path) -> None:
    core_path = _write_core(tmp_path)
    fundamental_dir = _write_fundamentals(tmp_path)
    manifest_path = _write_ifind_artifacts(tmp_path)

    result = build_cf_fundamental_data_status(
        as_of_date=date(2026, 8, 12),
        core_quote_path=core_path,
        fundamental_dir=fundamental_dir,
        ifind_edb_manifest_path=manifest_path,
        output_dir=tmp_path / "status_data",
        report_output_dir=tmp_path / "status_reports",
        run_id="r93j_unit",
    )

    assert result.passed
    assert result.status_counts["CURRENT"] >= 3
    assert result.status_counts["EVENT_DRIVEN"] == 4
    assert result.status_counts["MISSING"] >= 5
    for path in (
        result.status_parquet_path,
        result.status_csv_path,
        result.warning_csv_path,
        result.json_path,
        result.manifest_path,
        result.markdown_path,
    ):
        assert path.exists()
        assert path.stat().st_size > 0

    status = pd.read_parquet(result.status_parquet_path)
    daily_spot = status.loc[
        status["indicator_name"].eq("中国棉花价格指数:3128B")
    ].iloc[0]
    monthly_import = status.loc[
        status["indicator_name"].eq("棉花:进口数量:当月值")
    ].iloc[0]
    weekly_textile = status.loc[
        status["indicator_name"].eq("纯棉纱厂负荷:周均")
    ].iloc[0]
    policy = status.loc[status["indicator_id"].eq("S003986676")].iloc[0]
    missing_order = status.loc[status["indicator_name"].eq("纺织订单")].iloc[0]

    assert daily_spot["data_status"] == "CURRENT"
    assert monthly_import["data_status"] == "LAGGING"
    assert weekly_textile["data_status"] == "LAGGING"
    assert policy["data_status"] == "EVENT_DRIVEN"
    assert missing_order["data_status"] == "MISSING"
    assert set(status["signal_status"]) == {"not_connected"}

    report = result.markdown_path.read_text(encoding="utf-8")
    assert "月频进口、库存保留原统计期" in report
    assert "未公布期间不补零" in report
    assert "不进入signal matrix或composite_score" in report
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["contains_forward_labels"] is False
    assert payload["fundamental_signal_status"] == "not_connected"


def test_r93j_cli_defaults_as_of_to_latest_core_date(tmp_path: Path) -> None:
    core_path = _write_core(tmp_path)
    fundamental_dir = _write_fundamentals(tmp_path)
    manifest_path = _write_ifind_artifacts(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-fundamental-data-status",
            "--core-quote-path",
            str(core_path),
            "--fundamental-dir",
            str(fundamental_dir),
            "--ifind-edb-manifest-path",
            str(manifest_path),
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "r93j_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == "r93j_cli"
    assert payload["as_of_date"] == "2026-08-12"
    assert payload["fundamental_signal_status"] == "not_connected"


def _write_core(tmp_path: Path) -> Path:
    path = tmp_path / "core_quote_daily.parquet"
    pd.DataFrame(
        {
            "trade_date": ["2026-08-11", "2026-08-12"],
            "contract_code": ["CF701", "CF701"],
        }
    ).to_parquet(path, index=False)
    return path


def _write_fundamentals(tmp_path: Path) -> Path:
    root = tmp_path / "fundamentals"
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "trade_date": ["2026-08-11"],
            "indicator_name": ["中国棉花价格指数:3128B"],
            "indicator_value": [17600.0],
            "source_name": ["中国棉花信息网"],
            "indicator_id": ["S0031714"],
            "unit": ["元/吨"],
            "data_quality_flag": ["REVIEW_REQUIRED"],
            "human_review_required": [True],
        }
    ).to_parquet(root / "CF_fundamental_spot_price_daily.parquet", index=False)
    pd.DataFrame(
        {
            "trade_date": ["2026-05-31"],
            "indicator_name": ["棉花:进口数量:当月值"],
            "import_value": [11.0],
            "source_name": ["iFinD"],
            "indicator_id": ["IMPORT_CONFIRMED_FIXTURE"],
            "unit": ["万吨"],
            "data_quality_flag": ["REVIEW_REQUIRED"],
            "human_review_required": [True],
        }
    ).to_parquet(root / "CF_fundamental_import_daily.parquet", index=False)
    pd.DataFrame(
        {
            "trade_date": ["2026-08-01"],
            "indicator_name": ["纯棉纱厂负荷"],
            "metric_name": ["周均"],
            "indicator_value": [50.0],
            "source_name": ["TTEB"],
            "indicator_id": ["TTEB_FIXTURE"],
            "unit": ["%"],
            "data_quality_flag": ["REVIEW_REQUIRED"],
            "human_review_required": [True],
        }
    ).to_parquet(root / "CF_fundamental_textile_chain_daily.parquet", index=False)
    return root


def _write_ifind_artifacts(tmp_path: Path) -> Path:
    root = tmp_path / "ifind"
    root.mkdir(parents=True, exist_ok=True)
    cotton_rows: list[dict[str, object]] = []
    for indicator_id, (dataset_type, indicator_name, unit_status) in COTTON_EDB.items():
        trade_date = "2026-07-20" if dataset_type == "policy" else "2026-08-10"
        cotton_rows.append(
            {
                "trade_date": trade_date,
                "product_code": "CF",
                "dataset_type": dataset_type,
                "indicator_id": indicator_id,
                "indicator_name": indicator_name,
                "indicator_value": 100.0,
                "unit_status": unit_status,
                "source_name": "iFinD EDB",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
            }
        )
    cotton_path = root / "cotton.parquet"
    pd.DataFrame(cotton_rows).to_parquet(cotton_path, index=False)

    fx_rows = [
        {
            "trade_date": "2026-08-10",
            "product_code": "CF",
            "indicator_id": indicator_id,
            "index_name": f"USD/CNY外汇掉期曲线:{tenor}",
            "tenor": tenor,
            "swap_value": 1.0,
            "unit_status": "SWAP_POINT_UNIT_REVIEW_REQUIRED",
            "source_name": "iFinD EDB",
            "data_quality_flag": "REVIEW_REQUIRED",
            "human_review_required": True,
        }
        for indicator_id, tenor in FX_SWAP_TENORS.items()
    ]
    fx_path = root / "fx.parquet"
    pd.DataFrame(fx_rows).to_parquet(fx_path, index=False)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-12T12:00:00+00:00",
                "summary": {
                    "data_end": "2026-08-10",
                    "cotton_context_path": str(cotton_path),
                    "fx_swap_curve_path": str(fx_path),
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path
