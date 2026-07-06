from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_daily_operation_audit


def test_build_cf_daily_operation_audit_writes_chinese_outputs(tmp_path: Path) -> None:
    core_path = _write_core_quotes(tmp_path, trade_date=date(2026, 7, 1))
    latest_path = _write_latest_signal_json(tmp_path, trade_date="2026-07-01")
    board_path = _write_trend_board_json(tmp_path, trade_date="2026-07-01")

    result = build_cf_daily_operation_audit(
        latest_signal_json_path=latest_path,
        trend_board_json_path=board_path,
        core_quote_path=core_path,
        output_root=tmp_path / "runs" / "daily",
        run_id="r34_unit",
    )

    assert result.trade_date == date(2026, 7, 1)
    assert result.core_latest_trade_date == date(2026, 7, 1)
    assert result.warning_count == 0
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.warning_csv_path.exists()
    assert result.manifest_path.exists()
    assert result.to_summary()["operation_status"] == "RUNNABLE_WITH_WARNINGS"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 日更运行审计摘要" in markdown
    assert "数据与产物状态" in markdown
    assert "趋势阶段与质量" in markdown
    assert "历史校准上下文" in markdown
    assert "未包含未来收益标签" in markdown
    assert "未完成 forward-return 验证" in markdown
    assert "不构成交易指令" in markdown
    assert "forward_return_h" not in markdown

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "daily_operation_audit"
    assert payload["no_future_return_labels"] is True
    assert payload["contains_forward_return_validation"] is False
    assert payload["main_contract"] == "CF609"
    assert payload["trend_phase_code"] == "S3"
    assert "forward_return_h" not in result.json_path.read_text(encoding="utf-8")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["no_lookahead"] is True
    assert manifest["contains_forward_return_validation"] is False


def test_build_cf_daily_operation_audit_warns_on_stale_core(tmp_path: Path) -> None:
    core_path = _write_core_quotes(tmp_path, trade_date=date(2026, 6, 30))
    latest_path = _write_latest_signal_json(tmp_path, trade_date="2026-07-01")
    board_path = _write_trend_board_json(tmp_path, trade_date="2026-07-01")

    result = build_cf_daily_operation_audit(
        latest_signal_json_path=latest_path,
        trend_board_json_path=board_path,
        core_quote_path=core_path,
        output_root=tmp_path / "runs" / "daily",
        run_id="r34_stale_core",
    )

    assert result.warning_count == 1
    assert result.warning_records[0].warning_code == "CORE_LATEST_DATE_MISMATCH"


def test_build_cf_daily_operation_audit_rejects_date_mismatch(tmp_path: Path) -> None:
    latest_path = _write_latest_signal_json(tmp_path, trade_date="2026-07-01")
    board_path = _write_trend_board_json(tmp_path, trade_date="2026-06-30")

    with pytest.raises(ResearchWorkbenchError, match="trade_date mismatch"):
        build_cf_daily_operation_audit(
            latest_signal_json_path=latest_path,
            trend_board_json_path=board_path,
            output_root=tmp_path / "runs" / "daily",
        )


def test_cli_build_cf_daily_operation_audit(tmp_path: Path) -> None:
    core_path = _write_core_quotes(tmp_path, trade_date=date(2026, 7, 1))
    latest_path = _write_latest_signal_json(tmp_path, trade_date="2026-07-01")
    board_path = _write_trend_board_json(tmp_path, trade_date="2026-07-01")

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-daily-operation-audit",
            "--latest-signal-json-path",
            str(latest_path),
            "--trend-board-json-path",
            str(board_path),
            "--core-quote-path",
            str(core_path),
            "--output-root",
            str(tmp_path / "runs" / "daily"),
            "--run-id",
            "r34_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["trade_date"] == "2026-07-01"
    assert output["main_contract"] == "CF609"
    assert Path(output["markdown_path"]).exists()


def _write_core_quotes(tmp_path: Path, *, trade_date: date) -> Path:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "source_snapshot_id": f"r34_fixture_{trade_date:%Y%m%d}",
                "exchange": "CZCE",
                "product_code": "CF",
                "contract_code": "CF609",
                "trade_date": trade_date,
                "settle": 16140.0,
                "volume": 1000,
                "open_interest": 5000,
            }
        ]
    ).to_parquet(path, index=False)
    return path


def _write_latest_signal_json(tmp_path: Path, *, trade_date: str) -> Path:
    path = tmp_path / "latest_signal_brief.json"
    payload = {
        "product_code": "CF",
        "run_id": "r23_fixture",
        "trade_date": trade_date,
        "data_asof": trade_date,
        "main_contract": "CF609",
        "signal_direction": "long",
        "warning_count": 0,
        "json_path": str(path),
        "summary": {
            "factor_signals": {
                "states": {
                    "momentum": "short",
                    "carry": "long",
                    "curve": "long",
                    "oi_pressure": "long",
                },
                "multi_factor": {
                    "direction": "long",
                    "score": 2,
                    "confidence": "medium",
                },
                "main_returns": {
                    "1": 0.003,
                    "3": 0.02,
                    "5": 0.01,
                    "10": 0.02,
                    "20": -0.01,
                },
            },
            "term_structure": {
                "near_contract": "CF607",
                "far_contract": "CF611",
                "main_minus_near": 180.0,
                "far_minus_main": 260.0,
                "carry_annualized": 0.09,
                "curve_slope": 0.01,
            },
            "watch_items": ["观察上涨增仓能否延续。"],
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_trend_board_json(tmp_path: Path, *, trade_date: str) -> Path:
    path = tmp_path / "trend_continuity_board.json"
    payload = {
        "product_code": "CF",
        "run_id": "r29_fixture",
        "trade_date": trade_date,
        "latest_main_contract": "CF609",
        "latest_phase_code": "S3",
        "latest_phase_label": "衰竭观察",
        "latest_observation_marker": "衰竭观察",
        "latest_transition_code": None,
        "latest_trend_quality_score": 45,
        "latest_trend_quality_label": "震荡观察",
        "row_count": 20,
        "warning_count": 0,
        "json_path": str(path),
        "trend_quality_calibration_context": {
            "context_status": "PROVIDED",
            "alignment_status": "MATCHED",
            "latest_score_context_label": "历史中位",
            "latest_score_percentile": 0.64,
            "interpretation_cn": "R32 校准显示当前质量位于历史中位。",
            "bucket_summary": [
                {
                    "horizon": 5,
                    "mean_forward_return": -0.008,
                    "directional_hit_rate": 0.5,
                }
            ],
        },
        "rows": [
            {
                "trade_date": trade_date,
                "trend_quality_reason": "阶段 S3 调整，结构信号分歧。",
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
