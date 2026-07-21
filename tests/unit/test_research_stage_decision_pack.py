from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_stage_decision_pack


def test_build_cf_stage_decision_pack_writes_chinese_review_material(
    tmp_path: Path,
) -> None:
    weekly_path, gate_path, latest_path, option_path, threshold_path = _write_inputs(tmp_path)

    result = build_cf_stage_decision_pack(
        weekly_audit_json_path=weekly_path,
        expansion_gate_json_path=gate_path,
        latest_signal_json_path=latest_path,
        option_factor_json_path=option_path,
        event_threshold_json_path=threshold_path,
        output_dir=tmp_path / "reports" / "stage_decision",
        daily_output_root=tmp_path / "runs" / "daily",
        run_id="stage_decision_unit",
    )

    assert result.decision_status == "READY_FOR_HUMAN_REVIEW"
    assert result.data_asof.isoformat() == "2026-07-06"
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()
    assert result.daily_markdown_path is not None
    assert result.daily_markdown_path.exists()
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 阶段决策包 R65" in markdown
    assert "期权联动" in markdown
    assert "不启动非 CF 数据接入" in markdown
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["option_summary"]["selected_underlying_contract"] == "CF609"
    assert payload["threshold_summary"]["review_decision_counts"]["KEEP"] == 12


def test_cli_build_cf_stage_decision_pack_returns_json(tmp_path: Path) -> None:
    weekly_path, gate_path, latest_path, option_path, threshold_path = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-stage-decision-pack",
            "--weekly-audit-json-path",
            str(weekly_path),
            "--expansion-gate-json-path",
            str(gate_path),
            "--latest-signal-json-path",
            str(latest_path),
            "--option-factor-json-path",
            str(option_path),
            "--event-threshold-json-path",
            str(threshold_path),
            "--output-dir",
            str(tmp_path / "reports" / "stage_decision"),
            "--run-id",
            "stage_decision_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "stage_decision_cli"
    assert output["decision_status"] == "READY_FOR_HUMAN_REVIEW"
    assert output["recommended_next_step"].startswith("先完成人工复核")


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    weekly_path = tmp_path / "weekly_audit.json"
    gate_path = tmp_path / "expansion_gate.json"
    latest_path = tmp_path / "latest_signal.json"
    option_path = tmp_path / "option_factor.json"
    threshold_path = tmp_path / "event_threshold.json"
    _write_json(
        weekly_path,
        {
            "report_type": "weekly_research_audit",
            "summary": {
                "status": "WEEKLY_AUDIT_READY",
                "data_asof": "2026-07-06",
                "artifact_missing_count": 0,
                "event_context_coverage": {
                    "coverage_rate": 1.0,
                    "r55_event_count": 403,
                    "r55_context_available_count": 403,
                    "r56_event_context_connected": True,
                },
                "event_threshold_context": {
                    "status": "completed",
                    "summary_row_count": 65,
                    "forward_returns_are_validation_labels": True,
                    "review_decision_counts": {
                        "KEEP": 12,
                        "WATCH": 43,
                        "REJECT": 10,
                        "REVISE": 0,
                    },
                },
                "human_review_required": ["publish_wording"],
            },
        },
    )
    _write_json(
        gate_path,
        {
            "product_code": "CF",
            "gate_version": "R52",
            "status": "HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION",
            "passed": True,
            "candidate_scope": "SR_AP_OR_EXTERNAL_DATA",
            "blocked_requirements": [],
            "requirement_count": 11,
            "human_review_required": ["product_expansion_go_no_go"],
            "requirements": [
                {"status": "PASS", "blocking": False},
                {"status": "HUMAN_REVIEW_REQUIRED", "blocking": False},
            ],
        },
    )
    _write_json(
        latest_path,
        {
            "data_asof": "2026-07-06",
            "main_contract": "CF609",
            "signal_direction": "long",
            "trend_phase": {
                "phase_code": "S1",
                "phase_label": "起点观察",
                "direction": "long",
            },
            "signal_matrix_context": {
                "primary_horizon": 20,
                "primary_direction": "long",
                "primary_confidence": "high",
                "rows": [
                    {
                        "horizon": 20,
                        "option_signal": "confirm_long",
                        "option_signal_direction": "long",
                        "evidence_level": "strong",
                    }
                ],
            },
            "human_review_required": ["latest_signal_interpretation"],
        },
    )
    _write_json(
        option_path,
        {
            "status": "COMPLETED",
            "passed": True,
            "option_row_count": 295910,
            "eligible_option_row_count": 111746,
            "excluded_option_row_count": 184164,
            "factor_row_count": 5488,
            "warning_count": 1,
            "latest_rows": [
                {
                    "underlying_contract": "CF609",
                    "factor_status": "READY",
                    "atm_iv_rank": 0.03,
                    "pcr_oi": 0.67,
                    "pcr_volume": 0.56,
                    "skew_proxy": -0.001,
                    "model_boundary": "美式期权 IV/Greek 未精确定价；本表为研究 proxy",
                }
            ],
            "human_review_required": ["option_signal_filter_rules_before_trading_use"],
        },
    )
    _write_json(
        threshold_path,
        {
            "status": "EVENT_THRESHOLD_SENSITIVITY_READY_WITH_WARNINGS",
            "passed": True,
            "summary_row_count": 65,
            "detail_row_count": 4365,
            "review_decision_counts": {
                "KEEP": 12,
                "WATCH": 43,
                "REJECT": 10,
                "REVISE": 0,
            },
            "warning_count": 1,
            "forward_returns_are_validation_labels": True,
        },
    )
    return weekly_path, gate_path, latest_path, option_path, threshold_path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
