from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
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
        futures_option_divergence_json_path=paths["divergence"],
        futures_option_playbook_json_path=paths["playbook"],
        current_watch_window_json_path=paths["watch"],
        state_transition_json_path=paths["state_transition"],
        option_volatility_json_path=paths["option_volatility"],
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
    assert "研究评价框架修正（R67）" in markdown
    assert "signal_strength" in markdown
    assert "historical_reliability" in markdown
    assert "WATCH_ONLY_OOS_REQUIRED" in markdown
    assert "事件生命周期标签缺口" in markdown
    assert "历史窗口证据" in markdown
    assert "基本面观察与人工复核状态" in markdown
    assert "仓单数量按郑商所口径处理" in markdown
    assert "最新纺织链" in markdown
    assert "相似历史事件" in markdown
    assert "基本面事件解释链" in markdown
    assert "事件阈值敏感性复核" in markdown
    assert "R60 只作为历史阈值复核底稿" in markdown
    assert "R56 基本面事件解释只作为历史复盘上下文" in markdown
    assert "期货-期权矛盾节点（R70）" in markdown
    assert "R69 中的 `forward_return` 仅为历史后验验证标签" in markdown
    assert "期货-期权当前结构映射（R72）" in markdown
    assert "R71/R72 中的当前映射只回答" in markdown
    assert "当前确认与失效窗口（R77）" in markdown
    assert "EXHAUSTION_OR_FAILURE_WATCH" in markdown
    assert "多日移仓上下文" in markdown
    assert "状态转移竞争风险（R82 接入 R79）" in markdown
    assert "历史已关闭事件的竞争风险后验分布" in markdown
    assert "期权波动率与期限结构（R82 接入 R80/R81）" in markdown
    assert "EXPLICIT_EXPIRY_REGISTRY" in markdown
    assert "latest signal-only 部分不包含 forward-return 验证" in markdown
    assert "本报告不构成交易指令" in markdown

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "validated_research_brief"
    assert payload["latest_signal_only_contains_forward_return_validation"] is False
    assert payload["historical_forward_returns_are_validation_labels"] is True
    assert payload["research_framework_context"]["rule_version"].startswith("R67")
    assert (
        payload["research_framework_context"]["threshold_interpretation"][
            "publish_status"
        ]
        == "WATCH_ONLY_OOS_REQUIRED"
    )
    assert "validated_stance" in payload["research_framework_context"]
    assert payload["fundamental_observation_context"]["report_type"] == "fundamental_observation"
    assert payload["event_fundamental_context"]["connected"] is True
    assert payload["event_fundamental_context"]["context_available_count"] == 2
    assert payload["event_threshold_sensitivity_context"]["connected"] is True
    assert payload["event_threshold_sensitivity_context"]["review_decision_counts"]["KEEP"] == 1
    assert payload["futures_option_divergence_context"]["connected"] is True
    assert (
        payload["futures_option_divergence_context"]["result"][
            "directional_divergence_count"
        ]
        == 12
    )
    assert payload["futures_option_playbook_context"]["connected"] is True
    assert payload["futures_option_playbook_context"]["current_mapping_rows"][0][
        "matched_playbook_label_cn"
    ] == "同向确认观察"
    assert payload["current_watch_window_context"]["connected"] is True
    assert payload["current_watch_window_context"]["watch_window"]["phase_v2"] == "S3"
    assert payload["state_transition_context"]["connected"] is True
    assert payload["state_transition_context"]["current_mapping"]["phase_code"] == "S3"
    assert payload["option_volatility_context"]["connected"] is True
    assert (
        payload["option_volatility_context"]["latest_curve"]["main_atm_iv_approx"]
        == 0.12
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["report_type"] == "validated_research_brief"
    assert manifest["fundamental_observation_json_path"] == str(paths["fundamental"])
    assert manifest["event_detail_path"] == str(paths["event_detail"])
    assert manifest["event_threshold_summary_path"] == str(paths["event_threshold"])
    assert manifest["futures_option_divergence_json_path"] == str(paths["divergence"])
    assert manifest["futures_option_playbook_json_path"] == str(paths["playbook"])
    assert manifest["current_watch_window_json_path"] == str(paths["watch"])
    assert manifest["state_transition_json_path"] == str(paths["state_transition"])
    assert manifest["option_volatility_json_path"] == str(paths["option_volatility"])
    assert manifest["validated_brief_futures_option_context_rule_version"].startswith("R70")
    assert manifest["validated_brief_futures_option_playbook_context_rule_version"].startswith(
        "R72"
    )
    assert manifest["validated_brief_watch_window_context_rule_version"].startswith("R77")
    assert manifest["validated_brief_state_transition_context_rule_version"].startswith(
        "R82"
    )
    assert manifest["validated_brief_option_volatility_context_rule_version"].startswith(
        "R82"
    )


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
            "--futures-option-divergence-json-path",
            str(paths["divergence"]),
            "--futures-option-playbook-json-path",
            str(paths["playbook"]),
            "--current-watch-window-json-path",
            str(paths["watch"]),
            "--state-transition-json-path",
            str(paths["state_transition"]),
            "--option-volatility-json-path",
            str(paths["option_volatility"]),
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
    assert output["futures_option_divergence_json_path"] == str(paths["divergence"])
    assert output["futures_option_playbook_json_path"] == str(paths["playbook"])
    assert output["current_watch_window_json_path"] == str(paths["watch"])
    assert output["state_transition_json_path"] == str(paths["state_transition"])
    assert output["option_volatility_json_path"] == str(paths["option_volatility"])
    assert Path(output["daily_markdown_path"]).exists()


def test_r82_rejects_stale_option_volatility_context(tmp_path: Path) -> None:
    paths = _write_r43_inputs(tmp_path)
    payload = json.loads(paths["option_volatility"].read_text(encoding="utf-8"))
    payload["end"] = "2026-06-30"
    paths["option_volatility"].write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ResearchWorkbenchError, match="does not match latest data_asof"):
        build_cf_validated_research_brief(
            latest_signal_json_path=paths["latest"],
            historical_evidence_decay_path=paths["decay"],
            historical_evidence_stability_path=paths["stability"],
            event_summary_path=paths["events"],
            state_transition_json_path=paths["state_transition"],
            option_volatility_json_path=paths["option_volatility"],
            output_dir=tmp_path / "validated",
        )


def _write_r43_inputs(tmp_path: Path) -> dict[str, Path]:
    latest_path = tmp_path / "daily" / "CF" / "2026-07-01" / "latest_signal_brief.json"
    decay_path = tmp_path / "historical" / "decay.parquet"
    stability_path = tmp_path / "historical" / "stability.parquet"
    events_path = tmp_path / "events" / "summary.parquet"
    event_detail_path = tmp_path / "events" / "events.parquet"
    event_threshold_path = tmp_path / "events" / "threshold_summary.parquet"
    fundamental_path = tmp_path / "fundamentals" / "fundamental_observation.json"
    divergence_path = tmp_path / "divergence" / "r69_futures_option_divergence.json"
    playbook_path = tmp_path / "playbook" / "r71_futures_option_playbook.json"
    watch_path = tmp_path / "watch" / "r77_current_watch_window.json"
    state_transition_path = tmp_path / "transition" / "r79_state_transition.json"
    option_volatility_path = tmp_path / "option" / "r81_option_volatility.json"
    for path in (
        latest_path,
        decay_path,
        stability_path,
        events_path,
        event_detail_path,
        event_threshold_path,
        fundamental_path,
        divergence_path,
        playbook_path,
        watch_path,
        state_transition_path,
        option_volatility_path,
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
    divergence_path.write_text(
        json.dumps(
            {
                "report_type": "futures_option_divergence_research",
                "result": {
                    "start": "2021-01-04",
                    "end": "2026-07-01",
                    "event_row_count": 30,
                    "labelled_event_row_count": 28,
                    "directional_divergence_count": 12,
                    "main_winner_label": "FUTURES_WIN",
                    "average_resolution_horizon": 5.25,
                },
                "horizon_summary": [
                    {
                        "divergence_type": "directional_divergence",
                        "horizon": 5,
                        "sample_count": 12,
                        "futures_win_rate": 0.58,
                        "options_win_rate": 0.25,
                        "avg_futures_directional_forward_return": 0.012,
                        "evidence_level": "WATCH",
                    }
                ],
                "node_summary": [
                    {
                        "evidence_level": "READY",
                        "trend_phase": "S2",
                        "option_signal": "diverge_short",
                        "iv_rank_bucket": "low",
                        "pcr_bucket": "high",
                        "sample_count": 40,
                        "dominant_winner_label": "FUTURES_WIN",
                    }
                ],
                "research_boundary": {
                    "forward_returns_are_validation_labels": True,
                    "trading_instruction": "not_a_trading_instruction",
                    "option_iv_greek_is_proxy": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    playbook_path.write_text(
        json.dumps(
            {
                "report_type": "futures_option_divergence_playbook",
                "summary": {
                    "start": "2021-01-04",
                    "end": "2026-07-01",
                    "node_count": 10,
                    "ready_node_count": 2,
                    "current_mapping_count": 1,
                },
                "current_mapping_rows": [
                    {
                        "horizon": 20,
                        "divergence_type": "option_confirmation",
                        "trend_phase": "S2",
                        "matched_node_id": "R71_NODE_0204",
                        "matched_sample_count": 93,
                        "matched_playbook_label_cn": "同向确认观察",
                        "matched_futures_win_rate": 0.4838709677,
                        "matched_options_win_rate": 0.0,
                        "matched_average_resolution_horizon": 12.642857,
                        "forward_returns_are_validation_labels": True,
                        "trading_instruction": "not_a_trading_instruction",
                    }
                ],
                "node_rows": [],
                "research_boundary": {
                    "forward_returns_are_validation_labels": True,
                    "auto_reverse_allowed": False,
                    "trading_instruction": "not_a_trading_instruction",
                    "option_iv_greek_is_proxy": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    watch_path.write_text(
        json.dumps(
            {
                "report_type": "current_watch_window",
                "watch_window": {
                    "phase_v2": "S3",
                    "phase_v2_label": "衰竭观察",
                    "phase_quality": "weak",
                    "watch_status": "EXHAUSTION_OR_FAILURE_WATCH",
                    "dual_price_state": "BOTH_ABOVE",
                    "close_settle_gap_state": "SETTLE_STRONGER",
                    "participation_state": "SHORT_COVER_OR_EXIT",
                    "chain_oi_change": -1000,
                    "option_confirmation_state": "CONFIRM_LONG",
                    "option_confirmation_strength": "low",
                    "confirmation_level": 16330,
                    "invalidation_level": 16000,
                    "expected_resolution_days": 5,
                    "confirmation_conditions_cn": "价格突破且持仓改善",
                    "invalidation_conditions_cn": "双价格跌破均线",
                },
                "research_boundary": {
                    "latest_state_uses_future_data": False,
                    "forward_returns_are_validation_labels": True,
                    "auto_reverse_allowed": False,
                    "trading_instruction": "not_a_trading_instruction",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state_transition_path.write_text(
        json.dumps(
            {
                "end": "2026-07-01",
                "closed_event_count": 50,
                "censored_event_count": 2,
                "current_mapping": {
                    "phase_code": "S3",
                    "phase_direction": "long",
                    "mapping_status": "NODE_MATCHED",
                    "primary_outcome": "RECOVERY_TO_S2",
                    "primary_outcome_probability": 0.40,
                    "research_boundary": "历史后验竞争风险映射",
                    "rule_version": "R79_state_transition_competing_risk_v1",
                },
                "overall_summary": [
                    {
                        "phase_code": "S1",
                        "outcome_label_cn": "进入S2趋势中",
                        "outcome_count": 20,
                        "outcome_probability_closed": 0.40,
                        "avg_resolution_days": 2.0,
                        "evidence_level": "WATCH",
                    },
                    {
                        "phase_code": "S3",
                        "outcome_label_cn": "退回S0未确认",
                        "outcome_count": 30,
                        "outcome_probability_closed": 0.60,
                        "avg_resolution_days": 3.0,
                        "evidence_level": "READY",
                    },
                ],
                "human_review_required": ["current_episode_mapping"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    option_volatility_path.write_text(
        json.dumps(
            {
                "end": "2026-07-01",
                "expiry_registry_row_count": 100,
                "expiry_fallback_row_count": 2,
                "warning_count": 1,
                "latest_curve": {
                    "main_contract": "CF609",
                    "main_option_expiry_date": "2026-08-12",
                    "main_expiry_date_source": "EXPLICIT_EXPIRY_REGISTRY",
                    "main_expiry_quality_flag": "OFFICIAL_RULE_TEST_FIXTURE",
                    "main_atm_iv_approx": 0.12,
                    "main_rv": 0.10,
                    "main_iv_rv_spread": 0.02,
                    "main_iv_rv_ratio": 1.20,
                    "volatility_state": "NORMAL_VOLATILITY_PRICING",
                    "term_structure_state": "FLAT_IV_TERM_STRUCTURE",
                    "rule_version": "R81_official_option_expiry_registry_v1",
                },
                "research_boundary": {
                    "latest_state_uses_future_data": False,
                    "enters_composite_score": False,
                    "trading_instruction": "not_a_trading_instruction",
                },
                "human_review_required": ["american_option_early_exercise_premium"],
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
        "divergence": divergence_path,
        "playbook": playbook_path,
        "watch": watch_path,
        "state_transition": state_transition_path,
        "option_volatility": option_volatility_path,
    }
