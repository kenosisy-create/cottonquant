from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_fundamental_context


def test_build_cf_fundamental_context_writes_explanation_tables(
    tmp_path: Path,
) -> None:
    paths = _write_r54_inputs(tmp_path)

    result = build_cf_fundamental_context(
        fundamental_observation_json_path=paths["fundamental_json"],
        core_quote_path=paths["core"],
        output_dir=tmp_path / "research" / "fundamental_context",
        report_output_dir=tmp_path / "reports" / "fundamental_context",
        run_id="r54_unit",
        change_windows=(1, 4),
    )

    assert result.status == "FUNDAMENTAL_CONTEXT_READY_WITH_WARNINGS"
    assert result.passed is True
    assert result.context_row_count == 24
    assert result.summary_row_count == 4
    assert result.data_asof is not None
    assert result.data_asof.isoformat() == "2024-03-05"
    assert result.to_summary()["fundamental_signal_status"] == "not_connected"

    context = pd.read_parquet(result.context_parquet_path)
    assert {"change_4_obs", "context_label_4", "explanation_relation_4_vs_price20"} <= set(
        context.columns
    )
    assert "raw_indicator_name" in context.columns
    assert not any("forward_return" in column for column in context.columns)
    assert set(context["fundamental_signal_status"]) == {"not_connected"}
    assert "textile_chain" in set(context["dataset_type"])
    assert "aligned_trailing_context" in set(context["explanation_relation_4_vs_price20"])

    summary = pd.read_parquet(result.summary_parquet_path)
    assert {"alignment_rate", "latest_context_label_4", "raw_indicator_names"} <= set(
        summary.columns
    )
    assert "warehouse_receipt" in set(summary["dataset_type"])
    textile_summary = summary.loc[summary["dataset_type"].eq("textile_chain")].iloc[0]
    assert textile_summary["indicator_name"] == "纺企棉纱库存"
    assert textile_summary["raw_indicator_names"] == "纱线综合库存；纺企棉纱库存"

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "fundamental_context"
    assert payload["contains_forward_return_labels"] is False
    assert payload["summary"]["fundamental_signal_status"] == "not_connected"
    assert not _contains_forward_return_label(payload)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 基本面解释层 R54" in markdown
    assert "同向/背离历史观察" in markdown
    assert "R54 不生成 `fundamental_signal`" in markdown
    assert "不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["contains_forward_return_labels"] is False
    assert result.warning_csv_path.exists()


def test_cli_build_cf_fundamental_context(tmp_path: Path) -> None:
    paths = _write_r54_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-fundamental-context",
            "--fundamental-observation-json-path",
            str(paths["fundamental_json"]),
            "--core-quote-path",
            str(paths["core"]),
            "--output-dir",
            str(tmp_path / "research" / "fundamental_context"),
            "--report-output-dir",
            str(tmp_path / "reports" / "fundamental_context"),
            "--run-id",
            "r54_cli",
            "--change-windows",
            "1,4",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r54_cli"
    assert output["status"] == "FUNDAMENTAL_CONTEXT_READY_WITH_WARNINGS"
    assert output["fundamental_signal_status"] == "not_connected"
    assert Path(output["context_parquet_path"]).exists()
    assert Path(output["summary_parquet_path"]).exists()
    assert Path(output["markdown_path"]).exists()


def test_build_cf_fundamental_context_includes_import_observations(
    tmp_path: Path,
) -> None:
    paths = _write_r54_inputs(tmp_path)
    import_path = paths["fundamental_json"].parent / "import.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "product_code": "CF",
                "indicator_name": "棉花:进口数量:当月值",
                "import_value": 10 + index,
                "unit": "万吨",
                "frequency": "月",
                "source_name": "iFinD",
                "source_file": "import.xlsx",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
                "remark": "fixture",
            }
            for index, trade_date in enumerate(
                [
                    date(2024, 1, 31),
                    date(2024, 2, 29),
                    date(2024, 3, 31),
                    date(2024, 4, 30),
                    date(2024, 5, 31),
                    date(2024, 6, 30),
                ]
            )
        ]
    ).to_parquet(import_path, index=False)
    payload = json.loads(paths["fundamental_json"].read_text(encoding="utf-8"))
    payload["summary"]["import_path"] = str(import_path)
    paths["fundamental_json"].write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    result = build_cf_fundamental_context(
        fundamental_observation_json_path=paths["fundamental_json"],
        core_quote_path=paths["core"],
        output_dir=tmp_path / "research" / "fundamental_context",
        report_output_dir=tmp_path / "reports" / "fundamental_context",
        run_id="r54_import_unit",
        change_windows=(1, 4),
    )

    context = pd.read_parquet(result.context_parquet_path)
    summary = pd.read_parquet(result.summary_parquet_path)
    assert "import" in set(context["dataset_type"])
    import_context = context.loc[context["dataset_type"].eq("import")]
    assert set(import_context["fundamental_signal_status"]) == {"not_connected"}
    assert set(import_context["interpretation_status"]) == {"HUMAN_REVIEW_REQUIRED"}
    assert "import" in set(summary["dataset_type"])
    assert result.to_summary()["fundamental_signal_status"] == "not_connected"


def _write_r54_inputs(tmp_path: Path) -> dict[str, Path]:
    core_path = _write_core_quotes(tmp_path)
    fundamental_dir = tmp_path / "fundamentals"
    fundamental_dir.mkdir(parents=True)
    trade_dates = [date(2024, 1, 30) + timedelta(days=7 * index) for index in range(6)]

    basis_path = fundamental_dir / "basis.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "product_code": "CF",
                "region": "CCIndex_3128B_vs_iFinD_active_contract",
                "basis": 100 + index * 10,
                "unit": "元/吨",
                "source_name": "iFinD",
                "source_file": "basis.csv",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
                "remark": "fixture",
            }
            for index, trade_date in enumerate(trade_dates)
        ]
    ).to_parquet(basis_path, index=False)

    warehouse_path = fundamental_dir / "warehouse.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "product_code": "CF",
                "indicator_name": "仓单数量:一号棉",
                "warehouse_receipt": 1200 - index * 20,
                "unit": "张",
                "source_name": "郑州商品交易所/iFinD汇总",
                "source_file": "warehouse.xlsx",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
                "remark": "fixture",
            }
            for index, trade_date in enumerate(trade_dates)
        ]
    ).to_parquet(warehouse_path, index=False)

    inventory_path = fundamental_dir / "inventory.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "product_code": "CF",
                "indicator_name": "中国:商业库存量:棉花",
                "inventory_value": 300 - index * 5,
                "unit": "万吨",
                "source_name": "iFinD",
                "source_file": "inventory.csv",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
                "remark": "fixture",
            }
            for index, trade_date in enumerate(trade_dates)
        ]
    ).to_parquet(inventory_path, index=False)

    textile_path = fundamental_dir / "textile.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "product_code": "CF",
                "indicator_name": "纺企棉纱库存",
                "raw_indicator_name": (
                    "纺企棉纱库存" if index < 3 else "纱线综合库存"
                ),
                "metric_name": "周均",
                "indicator_value": 45 + index * 2,
                "unit": "天",
                "frequency": "周",
                "source_name": "TTEB",
                "source_file": "tteb.xlsx",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
                "remark": "fixture",
            }
            for index, trade_date in enumerate(trade_dates)
        ]
    ).to_parquet(textile_path, index=False)

    fundamental_json = fundamental_dir / "fundamental_observation.json"
    fundamental_json.write_text(
        json.dumps(
            {
                "report_type": "fundamental_observation",
                "fundamental_signal_status": "not_connected",
                "summary": {
                    "status": "OBSERVATION_READY_WITH_WARNINGS",
                    "data_asof": trade_dates[-1].isoformat(),
                    "fundamental_signal_status": "not_connected",
                    "basis_path": str(basis_path),
                    "warehouse_receipt_path": str(warehouse_path),
                    "inventory_path": str(inventory_path),
                    "textile_chain_path": str(textile_path),
                    "warnings": [
                        {
                            "severity": "WARN",
                            "warning_code": "TEXTILE_CHAIN_FIELD_REVIEW_REQUIRED",
                            "message": "fixture warning",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"core": core_path, "fundamental_json": fundamental_json}


def _write_core_quotes(tmp_path: Path) -> Path:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    current = date(2024, 1, 2)
    trade_dates: list[date] = []
    while len(trade_dates) < 55:
        if current.weekday() < 5:
            trade_dates.append(current)
        current += timedelta(days=1)
    for index, trade_date in enumerate(trade_dates):
        rows.append(
            {
                "source_snapshot_id": f"r54_fixture_{trade_date:%Y%m%d}",
                "exchange": "CZCE",
                "product_code": "CF",
                "contract_code": "CF405",
                "trade_date": trade_date,
                "settle": 100 + index,
                "volume": 1_000 + index,
                "open_interest": 10_000 + index,
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _contains_forward_return_label(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if key_text == "forward_return" or key_text.startswith("forward_return_h"):
                return True
            if _contains_forward_return_label(nested):
                return True
    if isinstance(value, list):
        return any(_contains_forward_return_label(item) for item in value)
    return False
