from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_expansion_gate


def test_build_cf_expansion_gate_blocks_without_cf_evidence(tmp_path: Path) -> None:
    result = build_cf_expansion_gate(
        candidate_scope="SR_AP",
        report_output_dir=tmp_path / "gate",
        run_id="r22_missing_evidence",
    )

    assert result.passed is False
    assert result.status == "BLOCKED_MISSING_CF_MAINLINE_EVIDENCE"
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    blocked = {item.requirement_id for item in result.requirements if item.blocking}
    assert blocked == {
        "cf_r20_pipeline_completed",
        "cf_r21_replay_passed",
        "cf_r20_r21_evidence_linked",
        "cf_r41_historical_evidence_ready",
        "cf_r42_event_explanation_ready",
        "cf_r49_option_linkage_ready",
        "cf_r45_publish_pack_ready",
        "cf_r50_product_registry_ready",
        "cf_r51_fundamental_contract_ready",
    }


def test_build_cf_expansion_gate_legacy_r22_uses_r20_r21_evidence(
    tmp_path: Path,
) -> None:
    paths = _write_gate_evidence(tmp_path)

    result = build_cf_expansion_gate(
        candidate_scope="SR_AP",
        pipeline_json_path=paths["pipeline"],
        replay_json_path=paths["replay"],
        report_output_dir=tmp_path / "gate",
        run_id="r22_gate_test",
        gate_version="R22",
    )

    assert result.passed is True
    assert result.gate_version == "R22"
    assert result.status == "HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION"
    assert "candidate_field_mapping" in result.human_review_required
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION"
    assert payload["blocked_requirements"] == []


def test_build_cf_expansion_gate_r52_uses_mainline_evidence(tmp_path: Path) -> None:
    paths = _write_gate_evidence(tmp_path)
    r52_paths = _write_r52_evidence(tmp_path)

    result = build_cf_expansion_gate(
        candidate_scope="SR_AP",
        pipeline_json_path=paths["pipeline"],
        replay_json_path=paths["replay"],
        historical_evidence_manifest_path=r52_paths["historical_evidence"],
        event_explanation_manifest_path=r52_paths["event_explanation"],
        signal_matrix_manifest_path=r52_paths["signal_matrix"],
        publish_pack_manifest_path=r52_paths["publish_pack"],
        product_registry_manifest_path=r52_paths["product_registry"],
        fundamental_contract_manifest_path=r52_paths["fundamental_contract"],
        report_output_dir=tmp_path / "gate",
        run_id="r52_gate_test",
    )

    assert result.passed is True
    assert result.gate_version == "R52"
    assert result.status == "HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION"
    assert result.to_summary()["r52_evidence_paths"]["publish_pack_manifest_path"] == str(
        r52_paths["publish_pack"]
    )
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["gate_version"] == "R52"
    assert payload["blocked_requirements"] == []
    requirement_ids = {row["requirement_id"] for row in payload["requirements"]}
    assert "cf_r51_fundamental_contract_ready" in requirement_ids


def test_cli_research_build_cf_expansion_gate(tmp_path: Path) -> None:
    paths = _write_gate_evidence(tmp_path)
    r52_paths = _write_r52_evidence(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-expansion-gate",
            "--candidate-scope",
            "SR_AP",
            "--pipeline-json-path",
            str(paths["pipeline"]),
            "--replay-json-path",
            str(paths["replay"]),
            "--historical-evidence-manifest-path",
            str(r52_paths["historical_evidence"]),
            "--event-explanation-manifest-path",
            str(r52_paths["event_explanation"]),
            "--signal-matrix-manifest-path",
            str(r52_paths["signal_matrix"]),
            "--publish-pack-manifest-path",
            str(r52_paths["publish_pack"]),
            "--product-registry-manifest-path",
            str(r52_paths["product_registry"]),
            "--fundamental-contract-manifest-path",
            str(r52_paths["fundamental_contract"]),
            "--report-output-dir",
            str(tmp_path / "gate"),
            "--run-id",
            "r52_cli_gate",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["passed"] is True
    assert output["gate_version"] == "R52"
    assert output["status"] == "HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION"
    assert Path(output["json_path"]).exists()


def _write_gate_evidence(tmp_path: Path) -> dict[str, Path]:
    pipeline_json = tmp_path / "pipeline.json"
    pipeline_json.write_text(
        json.dumps(
            {
                "run_id": "r20_gate_fixture",
                "trade_date": "2024-01-10",
                "start": "2024-01-09",
                "end": "2024-01-12",
                "status": "COMPLETED",
                "artifacts": {"brief.json_path": str(tmp_path / "brief.json")},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    replay_json = tmp_path / "replay.json"
    replay_json.write_text(
        json.dumps(
            {
                "run_id": "r21_gate_fixture",
                "passed": True,
                "source_pipeline_json_path": str(pipeline_json),
                "missing_artifact_count": 0,
                "artifact_count": 1,
                "failed_checks": [],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"pipeline": pipeline_json, "replay": replay_json}


def _write_r52_evidence(tmp_path: Path) -> dict[str, Path]:
    publish_chart_pack = tmp_path / "publish" / "chart_pack.zip"
    publish_chart_pack.parent.mkdir(parents=True)
    publish_chart_pack.write_bytes(b"zip")
    wechat_article = tmp_path / "publish" / "wechat_article.md"
    wechat_article.write_text("不构成交易指令\n", encoding="utf-8")

    historical_evidence = _write_manifest(
        tmp_path / "historical_evidence_manifest.json",
        {
            "product_code": "CF",
            "report_type": "historical_evidence_pack",
            "rule_version": "R41_historical_multifactor_evidence_v1",
            "run_id": "r41_fixture",
            "data_start": "2021-01-04",
            "data_end": "2026-07-01",
            "forward_returns_are_validation_labels": True,
        },
    )
    event_explanation = _write_manifest(
        tmp_path / "event_explanation_manifest.json",
        {
            "product_code": "CF",
            "report_type": "historical_event_explanation",
            "rule_version": "R42_historical_event_explanation_v1",
            "run_id": "r42_fixture",
            "data_start": "2021-01-04",
            "data_end": "2026-07-01",
            "forward_returns_are_event_labels": True,
        },
    )
    signal_matrix = _write_manifest(
        tmp_path / "signal_matrix_manifest.json",
        {
            "product_code": "CF",
            "report_type": "signal_matrix",
            "rule_version": "R35_signal_matrix_v1",
            "run_id": "r49_fixture",
            "start": "2021-01-04",
            "end": "2026-07-03",
            "contains_forward_return_validation": False,
            "option_factor_path": str(tmp_path / "option_factor_proxy.parquet"),
        },
    )
    publish_pack = _write_manifest(
        tmp_path / "publish_pack_manifest.json",
        {
            "product_code": "CF",
            "report_type": "publish_pack",
            "rule_version": "R45_cf_publish_pack_v1",
            "run_id": "r45_fixture",
            "data_asof": "2026-07-01",
            "chart_pack_zip_path": str(publish_chart_pack),
            "wechat_article_path": str(wechat_article),
        },
    )
    product_registry = _write_manifest(
        tmp_path / "product_registry_manifest.json",
        {
            "product_code": "CF",
            "report_type": "cf_product_research_registry",
            "rule_version": "R50_cf_product_research_registry_v1",
            "run_id": "r50_fixture",
            "futures_factor_count": 4,
            "option_proxy_factor_count": 6,
        },
    )
    fundamental_contract = _write_manifest(
        tmp_path / "fundamental_contract_manifest.json",
        {
            "product_code": "CF",
            "report_type": "fundamental_data_contract",
            "rule_version": "R51_fundamental_data_contract_v1",
            "run_id": "r51_fixture",
            "status": "MISSING_FUNDAMENTAL_INPUT",
            "fundamental_signal_status": "not_connected",
        },
    )
    return {
        "historical_evidence": historical_evidence,
        "event_explanation": event_explanation,
        "signal_matrix": signal_matrix,
        "publish_pack": publish_pack,
        "product_registry": product_registry,
        "fundamental_contract": fundamental_contract,
    }


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
