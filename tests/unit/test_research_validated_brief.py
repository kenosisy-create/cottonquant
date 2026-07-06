from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_validated_research_brief


def test_build_cf_validated_research_brief_writes_chinese_report(
    tmp_path: Path,
) -> None:
    paths = _write_r43_inputs(tmp_path)

    result = build_cf_validated_research_brief(
        latest_signal_json_path=paths["latest"],
        historical_evidence_decay_path=paths["decay"],
        historical_evidence_stability_path=paths["stability"],
        event_summary_path=paths["events"],
        event_detail_path=paths["event_detail"],
        event_threshold_summary_path=paths["event_threshold"],
        fundamental_observation_json_path=paths["fundamental"],
        output_dir=tmp_path / "validated",
        daily_output_root=tmp_path / "daily",
        run_id="r43_unit",
    )

    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()
    assert result.daily_markdown_path is not None
    assert result.daily_markdown_path.exists()

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 验证型研究报告" in markdown
    assert "当前市场事实" in markdown
    assert "历史窗口证据" in markdown
    assert "基本面观察与人工复核状态" in markdown
    assert "仓单数量按郑商所口径处理" in markdown
    assert "最新纺织链" in markdown
    assert "相似历史事件" in markdown
    assert "基本面事件解释链" in markdown
    assert "事件阈值敏感性复核" in markdown
    assert "R60 只作为历史阈值复核底稿" in markdown
    assert "R56 基本面事件解释只作为历史复盘上下文" in markdown
    assert "latest signal-only 部分不包含 forward-return 验证" in markdown
    assert "本报告不构成交易指令" in markdown

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "validated_research_brief"
    assert payload["latest_signal_only_contains_forward_return_validation"] is False
    assert payload["historical_forward_returns_are_validation_labels"] is True
    assert payload["fundamental_observation_context"]["report_type"] == "fundamental_observation"
    assert payload["event_fundamental_context"]["connected"] is True
    assert payload["event_fundamental_context"]["context_available_count"] == 2
    assert payload["event_threshold_sensitivity_context"]["connected"] is True
    assert payload["event_threshold_sensitivity_context"]["review_decision_counts"]["KEEP"] == 1

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["report_type"] == "validated_research_brief"
    assert manifest["fundamental_observation_json_path"] == str(paths["fundamental"])
    assert manifest["event_detail_path"] == str(paths["event_detail"])
    assert manifest["event_threshold_summary_path"] == str(paths["event_threshold"])


def test_cli_build_cf_validated_research_brief(tmp_path: Path) -> None:
    paths = _write_r43_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-validated-research-brief",
            "--latest-signal-json-path",
            str(paths["latest"]),
            "--historical-evidence-decay-path",
            str(paths["decay"]),
            "--historical-evidence-stability-path",
            str(paths["stability"]),
            "--event-summary-path",
            str(paths["events"]),
            "--event-detail-path",
            str(paths["event_detail"]),
            "--event-threshold-summary-path",
            str(paths["event_threshold"]),
            "--fundamental-observation-json-path",
            str(paths["fundamental"]),
            "--output-dir",
            str(tmp_path / "validated"),
            "--daily-output-root",
            str(tmp_path / "daily"),
            "--run-id",
            "r43_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert Path(output["markdown_path"]).exists()
    assert output["event_detail_path"] == str(paths["event_detail"])
    assert output["event_threshold_summary_path"] == str(paths["event_threshold"])
    assert Path(output["daily_markdown_path"]).exists()


def _write_r43_inputs(tmp_path: Path) -> dict[str, Path]:
    latest_path = tmp_path / "daily" / "CF" / "2026-07-01" / "latest_signal_brief.json"
    decay_path = tmp_path / "historical" / "decay.parquet"
    stability_path = tmp_path / "historical" / "stability.parquet"
    events_path = tmp_path / "events" / "summary.parquet"
    event_detail_path = tmp_path / "events" / "events.parquet"
    event_threshold_path = tmp_path / "events" / "threshold_summary.parquet"
    fundamental_path = tmp_path / "fundamentals" / "fundamental_observation.json"
    for path in (
        latest_path,
        decay_path,
        stability_path,
        events_path,
        event_detail_path,
        event_threshold_path,
        fundamental_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(
            {
                "report_type": "latest_signal_only",
                "data_asof": "2026-07-01",
                "main_contract": "CF609",
                "signal_direction": "long",
                "trend_phase": {
                    "phase_code": "S3",
                    "phase_label": "衰竭观察",
                    "reason": "结构信号仍偏多但动量背离。",
                },
                "signal_matrix_context": {
                    "primary_horizon": 20,
                    "primary_direction": "long",
                    "primary_confidence": "low",
                },
                "signal_threshold_context": {
                    "horizon_alignment_status": "ALTERNATE_ONLY",
                    "explanation_cn": "20D 无 READY/WATCH，10D 有参考候选。",
                },
                "summary": {
                    "research_boundary": {
                        "forward_return_validation": "未完成 forward-return 验证"
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "horizon": 10,
                "observation_count": 100,
                "mean_net_return_normal_cost": 0.01,
                "directional_hit_rate": 0.58,
                "stability_status": "WATCH",
            },
            {
                "horizon": 20,
                "observation_count": 90,
                "mean_net_return_normal_cost": -0.002,
                "directional_hit_rate": 0.49,
                "stability_status": "WEAK_OR_UNSTABLE",
            },
        ]
    ).to_parquet(decay_path, index=False)
    pd.DataFrame(
        [
            {
                "horizon": 10,
                "scheme_label_cn": "置信度 >=70",
                "observation_count": 30,
                "mean_forward_return": 0.012,
                "directional_hit_rate": 0.61,
                "candidate_status": "READY_CANDIDATE",
                "stability_status": "READY",
            }
        ]
    ).to_parquet(stability_path, index=False)
    pd.DataFrame(
        [
            {
                "event_type": "趋势中继",
                "horizon": 10,
                "event_count": 20,
                "observation_count": 20,
                "mean_forward_return": 0.015,
                "directional_hit_rate": 0.65,
            },
            {
                "event_type": "终点确认",
                "horizon": 20,
                "event_count": 12,
                "observation_count": 10,
                "mean_forward_return": -0.004,
                "directional_hit_rate": 0.45,
            },
        ]
    ).to_parquet(events_path, index=False)
    pd.DataFrame(
        [
            {
                "event_date": "2026-06-28",
                "event_type": "趋势中继",
                "fundamental_context_available": True,
                "fundamental_context_count": 4,
                "fundamental_aligned_count": 2,
                "fundamental_divergent_count": 1,
                "fundamental_context_asof": "2026-06-28",
                "fundamental_context_summary_cn": (
                    "截至 2026-06-28 可见基本面上下文 4 项，同向 2 项，背离 1 项。"
                ),
                "fundamental_context_rule_version": "R55_event_fundamental_context_v1",
            },
            {
                "event_date": "2026-07-01",
                "event_type": "终点确认",
                "fundamental_context_available": True,
                "fundamental_context_count": 5,
                "fundamental_aligned_count": 1,
                "fundamental_divergent_count": 3,
                "fundamental_context_asof": "2026-07-01",
                "fundamental_context_summary_cn": (
                    "截至 2026-07-01 可见基本面上下文 5 项，同向 1 项，背离 3 项。"
                ),
                "fundamental_context_rule_version": "R55_event_fundamental_context_v1",
            },
        ]
    ).to_parquet(event_detail_path, index=False)
    pd.DataFrame(
        [
            {
                "threshold_scope": "baseline_r55",
                "event_type": "趋势中继",
                "threshold_quantile": None,
                "horizon": 10,
                "observation_count": 24,
                "directional_hit_rate": 0.58,
                "mean_forward_return": 0.012,
                "review_decision_candidate": "KEEP",
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
                "interpretation_status": "HUMAN_REVIEW_REQUIRED",
            },
            {
                "threshold_scope": "oi_anomaly",
                "event_type": "持仓异常变化",
                "threshold_quantile": 0.95,
                "horizon": 20,
                "observation_count": 8,
                "directional_hit_rate": 0.50,
                "mean_forward_return": 0.001,
                "review_decision_candidate": "WATCH",
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
                "interpretation_status": "HUMAN_REVIEW_REQUIRED",
            },
        ]
    ).to_parquet(event_threshold_path, index=False)
    fundamental_path.write_text(
        json.dumps(
            {
                "report_type": "fundamental_observation",
                "fundamental_signal_status": "not_connected",
                "summary": {
                    "status": "OBSERVATION_READY_WITH_WARNINGS",
                    "data_asof": "2026-07-01",
                    "fundamental_signal_status": "not_connected",
                    "field_metadata_csv_path": "fundamentals/metadata.csv",
                    "dataset_summaries": [
                        {
                            "dataset_type": "basis",
                            "status": "READY_WITH_REVIEW",
                            "row_count": 2,
                            "date_start": "2026-06-28",
                            "date_end": "2026-07-01",
                        },
                        {
                            "dataset_type": "warehouse_receipt",
                            "status": "MISSING_INPUT",
                            "row_count": 0,
                            "date_start": None,
                            "date_end": None,
                        },
                    ],
                    "warnings": [
                        {
                            "severity": "WARN",
                            "warning_code": "WAREHOUSE_RECEIPT_QUANTITY_MISSING",
                            "message": "仓单数量待接入。",
                        }
                    ],
                },
                "latest_observations": {
                    "basis": [
                        {
                            "trade_date": "2026-07-01",
                            "spot_price": 17700.0,
                            "futures_settle": 16200.0,
                            "basis": 1500.0,
                        }
                    ],
                    "warehouse_receipt": [
                        {
                            "trade_date": "2026-07-01",
                            "indicator_name": "仓单数量:一号棉",
                            "warehouse_receipt": 11019.0,
                            "unit": "张",
                        }
                    ],
                    "inventory": [
                        {
                            "indicator_name": "中国:商业库存量:棉花",
                            "inventory_value": 340.0,
                            "unit": "万吨",
                        }
                    ],
                    "spot_price": [
                        {
                            "indicator_name": "中国棉花价格指数:3128B",
                            "indicator_value": 17700.0,
                            "unit": "元/吨",
                        }
                    ],
                    "textile_chain": [
                        {
                            "trade_date": "2026-07-01",
                            "indicator_name": "纯棉纱厂负荷",
                            "metric_name": "周均",
                            "indicator_value": 56.0,
                            "unit": "%",
                        },
                        {
                            "trade_date": "2026-07-01",
                            "indicator_name": "纺企棉纱库存",
                            "metric_name": "周均",
                            "indicator_value": 25.0,
                            "unit": "天",
                        },
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "latest": latest_path,
        "decay": decay_path,
        "stability": stability_path,
        "events": events_path,
        "event_detail": event_detail_path,
        "event_threshold": event_threshold_path,
        "fundamental": fundamental_path,
    }
