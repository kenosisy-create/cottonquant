from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from cotton_factor.archive import (
    AuditLogWriter,
    build_archive_bundle,
    build_audit_event,
    build_run_manifest,
    read_artifact_registry,
    read_audit_log,
    read_run_manifest,
    register_artifact,
    write_artifact_registry,
    write_audit_event,
    write_run_manifest,
)
from cotton_factor.common.exceptions import ArchiveError
from cotton_factor.common.hashing import sha256_file


def test_run_manifest_writes_validated_lineage_json(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "CF.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("product_code: CF\n", encoding="utf-8")
    manifest_path = tmp_path / "archive" / "run_manifest.json"

    row = build_run_manifest(
        run_id="d18_archive_run",
        run_type="archive_smoke",
        input_snapshot_ids=["raw_1", "raw_1", "raw_2"],
        row_counts={"research_factor_value_daily": 2},
        artifact_paths=["reports/backtest.html"],
        warnings=[
            "TODO_REQUIRES_HUMAN_REVIEW: cost model",
            "TODO_REQUIRES_HUMAN_REVIEW: cost model",
        ],
        git_sha="abc123",
        config_paths=[config_path],
        started_at_utc=datetime(2024, 1, 2, 1, 0, tzinfo=UTC),
        ended_at_utc=datetime(2024, 1, 2, 1, 1, tzinfo=UTC),
    )

    write_run_manifest(row, manifest_path)
    loaded = read_run_manifest(manifest_path)

    assert loaded.run_id == "d18_archive_run"
    assert loaded.git_sha == "abc123"
    assert loaded.input_snapshot_ids == ["raw_1", "raw_2"]
    assert loaded.row_counts == {"research_factor_value_daily": 2}
    assert loaded.artifact_paths == ["reports/backtest.html"]
    assert loaded.warnings == ["TODO_REQUIRES_HUMAN_REVIEW: cost model"]


def test_artifact_registry_round_trips_file_checksums(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "backtest.html"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("<html>D18</html>\n", encoding="utf-8")
    registry_path = tmp_path / "archive" / "artifact_registry.json"

    record = register_artifact(
        path=report_path,
        artifact_type="html_report",
        root=tmp_path,
    )
    write_artifact_registry([record], registry_path)
    loaded = read_artifact_registry(registry_path)

    assert loaded == [record]
    assert record.path == "reports/backtest.html"
    assert record.sha256 == sha256_file(report_path)
    assert record.byte_size == report_path.stat().st_size


def test_audit_log_appends_and_reads_ordered_events(tmp_path: Path) -> None:
    audit_path = tmp_path / "archive" / "audit.jsonl"
    writer = AuditLogWriter(audit_path)

    first = writer.record(
        run_id="d18_archive_run",
        event_type="run_started",
        message="archive run started",
        payload={"input_snapshot_ids": ["raw_1"]},
        created_at_utc=datetime(2024, 1, 2, 1, 0, tzinfo=UTC),
    )
    second = build_audit_event(
        run_id="d18_archive_run",
        event_type="human_review_required",
        message="TODO_REQUIRES_HUMAN_REVIEW: cost model placeholder",
        severity="human_review",
        payload={"field": "cost_model_id"},
        created_at_utc=datetime(2024, 1, 2, 1, 1, tzinfo=UTC),
    )
    write_audit_event(audit_path, second)

    loaded = read_audit_log(audit_path)

    assert loaded == [first, second]
    assert loaded[1].severity == "human_review"
    assert loaded[1].payload == {"field": "cost_model_id"}


def test_archive_bundle_contains_manifest_registry_audit_and_report(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    manifest_path = archive_dir / "run_manifest.json"
    registry_path = archive_dir / "artifact_registry.json"
    audit_path = archive_dir / "audit.jsonl"
    report_path = tmp_path / "reports" / "backtest.html"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("<html>report</html>\n", encoding="utf-8")

    config_path = tmp_path / "configs" / "CF.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("product_code: CF\n", encoding="utf-8")
    manifest = build_run_manifest(
        run_id="d18_archive_run",
        run_type="archive_smoke",
        artifact_paths=["reports/backtest.html"],
        git_sha="abc123",
        config_paths=[config_path],
        started_at_utc=datetime(2024, 1, 2, 1, 0, tzinfo=UTC),
        ended_at_utc=datetime(2024, 1, 2, 1, 1, tzinfo=UTC),
    )
    write_run_manifest(manifest, manifest_path)
    write_audit_event(
        audit_path,
        build_audit_event(
            run_id="d18_archive_run",
            event_type="run_completed",
            message="archive artifacts produced",
            created_at_utc=datetime(2024, 1, 2, 1, 1, tzinfo=UTC),
        ),
    )
    records = [
        register_artifact(path=manifest_path, artifact_type="run_manifest", root=tmp_path),
        register_artifact(path=audit_path, artifact_type="audit_log", root=tmp_path),
        register_artifact(path=report_path, artifact_type="html_report", root=tmp_path),
    ]
    write_artifact_registry(records, registry_path)

    result = build_archive_bundle(
        bundle_path=archive_dir / "d18_archive_bundle.zip",
        artifact_paths=[manifest_path, registry_path, audit_path, report_path, report_path],
        root=tmp_path,
    )

    assert result.artifact_count == 4
    assert result.sha256 == sha256_file(result.bundle_path)
    assert result.byte_size == result.bundle_path.stat().st_size
    assert result.included_paths == [
        "archive/artifact_registry.json",
        "archive/audit.jsonl",
        "archive/run_manifest.json",
        "reports/backtest.html",
    ]
    with ZipFile(result.bundle_path) as archive:
        assert sorted(archive.namelist()) == result.included_paths


def test_archive_helpers_raise_on_missing_files(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError, match="artifact path not found"):
        register_artifact(path=tmp_path / "missing.html", artifact_type="html_report")

    with pytest.raises(ArchiveError, match="bundle artifact not found"):
        build_archive_bundle(
            bundle_path=tmp_path / "archive.zip",
            artifact_paths=[tmp_path / "missing.json"],
            root=tmp_path,
        )
