from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_weekly_research_audit


def test_build_cf_weekly_research_audit_from_r58_manifest(tmp_path: Path) -> None:
    manifest_path = _write_weekly_manifest(tmp_path)

    result = build_cf_weekly_research_audit(
        weekly_manifest_path=manifest_path,
        output_dir=tmp_path / "reports" / "weekly_audit",
        run_id="r59_unit",
    )

    assert result.audit_status == "WEEKLY_AUDIT_READY"
    assert result.passed is True
    assert result.warning_count == 0
    assert result.step_statuses["historical_evidence"] == "completed"
    assert result.step_statuses["event_threshold_sensitivity"] == "completed"
    assert result.event_context_coverage["r55_event_count"] == 10
    assert result.event_context_coverage["r55_context_available_count"] == 10
    assert result.event_context_coverage["coverage_rate"] == 1.0
    assert result.event_threshold_context["review_decision_counts"]["KEEP"] == 2

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "weekly_research_audit"
    assert payload["summary"]["research_boundary"]["fundamental_signal_status"] == (
        "not_connected"
    )
    assert payload["summary"]["research_boundary"][
        "historical_forward_returns_are_validation_labels"
    ] is True

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "周更链路完成情况" in markdown
    assert "R41 历史证据" in markdown
    assert "R55 事件解释与基本面上下文覆盖" in markdown
    assert "R60 事件阈值敏感性" in markdown
    assert "KEEP=2" in markdown
    assert "事件阈值人工复核" in markdown
    assert "基本面解释人工复核" in markdown
    assert "latest signal-only 不包含 forward-return 验证" in markdown
    assert "本报告不构成交易指令" in markdown
    assert result.warning_csv_path.exists()
    assert result.manifest_path.exists()


def test_cli_build_cf_weekly_research_audit(tmp_path: Path) -> None:
    manifest_path = _write_weekly_manifest(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-weekly-research-audit",
            "--weekly-manifest-path",
            str(manifest_path),
            "--output-dir",
            str(tmp_path / "reports" / "weekly_audit"),
            "--run-id",
            "r59_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r59_cli"
    assert output["status"] == "WEEKLY_AUDIT_READY"
    assert output["event_context_coverage"]["r56_event_context_connected"] is True
    assert output["event_threshold_context"]["review_decision_counts"]["WATCH"] == 3
    assert Path(output["markdown_path"]).exists()


def _write_weekly_manifest(tmp_path: Path) -> Path:
    artifact_paths = {
        "signal_matrix": _touch(tmp_path / "data" / "signal_matrix.parquet"),
        "latest_signal": _touch(tmp_path / "runs" / "latest_signal_brief.json"),
        "trend_board": _touch(tmp_path / "runs" / "trend_continuity_board.json"),
        "daily_audit": _touch(tmp_path / "runs" / "daily_operation_audit.md"),
        "historical_decay": _touch(tmp_path / "data" / "historical_decay.parquet"),
        "historical_stability": _touch(
            tmp_path / "data" / "historical_stability.parquet"
        ),
        "historical_report": _touch(tmp_path / "reports" / "historical.md"),
        "event_events": _touch(tmp_path / "data" / "event_events.parquet"),
        "event_summary": _touch(tmp_path / "data" / "event_summary.parquet"),
        "event_report": _touch(tmp_path / "reports" / "event.md"),
        "threshold_detail": _touch(tmp_path / "data" / "threshold_detail.parquet"),
        "threshold_summary": _touch(tmp_path / "data" / "threshold_summary.parquet"),
        "threshold_annual": _touch(tmp_path / "data" / "threshold_annual.parquet"),
        "threshold_report": _touch(tmp_path / "reports" / "threshold.md"),
        "validated_report": _touch(tmp_path / "reports" / "validated.md"),
        "validated_json": _touch(tmp_path / "reports" / "validated.json"),
        "validated_manifest": _touch(tmp_path / "reports" / "validated_manifest.json"),
        "publish_article": _touch(tmp_path / "runs" / "publish" / "wechat_article.md"),
        "publish_summary": _touch(tmp_path / "runs" / "publish" / "wechat_summary.txt"),
        "publish_zip": _touch(tmp_path / "runs" / "publish" / "chart_pack.zip"),
        "publish_manifest": _touch(tmp_path / "runs" / "publish" / "manifest.json"),
    }
    manifest_path = tmp_path / "runs" / "weekly" / "weekly_research_run_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "report_type": "cf_weekly_research_run_manifest",
                "rule_version": "R58_cf_weekly_research_run_v1",
                "run_id": "r58_fixture",
                "product_code": "CF",
                "data_asof": "2026-07-03",
                "core_path": str(_touch(tmp_path / "data" / "core.parquet")),
                "weekly_chain_enabled": True,
                "effective_steps": {
                    "historical_evidence": True,
                    "event_explanation": True,
                    "event_threshold_sensitivity": True,
                    "validated_brief": True,
                    "publish_pack": True,
                },
                "steps": {
                    "signal_matrix": {
                        "status": "completed",
                        "matrix_parquet_path": str(artifact_paths["signal_matrix"]),
                    },
                    "latest_signal_brief": {
                        "status": "completed",
                        "json_path": str(artifact_paths["latest_signal"]),
                    },
                    "trend_continuity_board": {
                        "status": "completed",
                        "json_path": str(artifact_paths["trend_board"]),
                    },
                    "daily_operation_audit": {
                        "status": "completed",
                        "warning_count": 0,
                        "markdown_path": str(artifact_paths["daily_audit"]),
                    },
                    "historical_evidence": {
                        "status": "completed",
                        "decay_parquet_path": str(artifact_paths["historical_decay"]),
                        "stability_parquet_path": str(
                            artifact_paths["historical_stability"]
                        ),
                        "markdown_path": str(artifact_paths["historical_report"]),
                    },
                    "event_explanation": {
                        "status": "completed",
                        "event_parquet_path": str(artifact_paths["event_events"]),
                        "summary_parquet_path": str(artifact_paths["event_summary"]),
                        "markdown_path": str(artifact_paths["event_report"]),
                    },
                    "event_threshold_sensitivity": {
                        "status": "completed",
                        "detail_parquet_path": str(artifact_paths["threshold_detail"]),
                        "summary_parquet_path": str(artifact_paths["threshold_summary"]),
                        "annual_parquet_path": str(artifact_paths["threshold_annual"]),
                        "markdown_path": str(artifact_paths["threshold_report"]),
                        "warning_count": 1,
                        "summary_row_count": 8,
                        "review_decision_counts": {
                            "KEEP": 2,
                            "WATCH": 3,
                            "REVISE": 1,
                            "REJECT": 2,
                        },
                        "forward_returns_are_validation_labels": True,
                        "trading_instruction": "not_a_trading_instruction",
                    },
                    "validated_brief": {
                        "status": "completed",
                        "markdown_path": str(artifact_paths["validated_report"]),
                        "json_path": str(artifact_paths["validated_json"]),
                        "manifest_path": str(artifact_paths["validated_manifest"]),
                    },
                    "publish_pack": {
                        "status": "completed",
                        "wechat_article_path": str(artifact_paths["publish_article"]),
                        "wechat_summary_path": str(artifact_paths["publish_summary"]),
                        "chart_pack_zip_path": str(artifact_paths["publish_zip"]),
                        "manifest_path": str(artifact_paths["publish_manifest"]),
                        "validated_event_context": {
                            "r56_event_context_connected": True,
                            "r55_event_count": 10,
                            "r55_context_available_count": 10,
                            "rule_version": "R57_publish_pack_event_context_v1",
                        },
                    },
                },
                "research_boundary": {
                    "latest_signal_only_contains_forward_return_validation": False,
                    "historical_forward_returns_are_validation_labels": True,
                    "fundamental_signal_status": "not_connected",
                    "trading_instruction": "not_a_trading_instruction",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest_path


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture", encoding="utf-8")
    return path
