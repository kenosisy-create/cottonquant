from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from cotton_factor.common.exceptions import ReleaseError
from cotton_factor.release import BLOCKS_PRODUCTION, FUTURE_ENHANCEMENT, run_release_freeze


def test_release_freeze_builds_release_candidate_bundle(tmp_path: Path) -> None:
    result = run_release_freeze(
        version="0.1.0",
        output_root=tmp_path / "archive",
        run_id="d23_release_test",
    )

    assert result.passed is True
    assert result.production_ready is False
    assert result.release_dir.name == "release-0.1.0"
    assert result.release_manifest_path.exists()
    assert result.run_manifest_path.exists()
    assert result.audit_path.exists()
    assert result.checksums_path.exists()
    assert result.registry_path.exists()
    assert result.todo_inventory_path.exists()
    assert result.todo_inventory_markdown_path.exists()
    assert result.test_summary_path.exists()
    assert result.bundle_path.exists()
    assert result.todo_summary[BLOCKS_PRODUCTION] > 0

    release_manifest = json.loads(result.release_manifest_path.read_text(encoding="utf-8"))
    assert release_manifest["version"] == "0.1.0"
    assert release_manifest["mvp_release_candidate"] is True
    assert release_manifest["production_ready"] is False
    assert release_manifest["versions"]["package_version"] == "0.1.0"
    assert release_manifest["dependency_lock"]["dependency_lock_hash"]
    assert release_manifest["config_file_count"] > 0

    todo_items = json.loads(result.todo_inventory_path.read_text(encoding="utf-8"))
    assert any(
        item["classification"] == BLOCKS_PRODUCTION
        and item["path"] == "configs/data_sources.yaml"
        for item in todo_items
    )
    assert any(
        item["classification"] == FUTURE_ENHANCEMENT
        and item["path"] == "configs/products/M.yaml"
        for item in todo_items
    )

    with ZipFile(result.bundle_path) as archive:
        names = set(archive.namelist())
    assert {
        "release_manifest.json",
        "run_manifest.json",
        "audit.jsonl",
        "checksums.json",
        "artifact_registry.json",
        "known_todos.json",
        "known_todos.md",
        "test_summary.json",
        "CHANGELOG.md",
        "RELEASE_CHECKLIST.md",
    } <= names
    assert any(name.endswith("uat_report.json") for name in names)
    assert any(name.endswith("uat_report.html") for name in names)


def test_release_freeze_rejects_unsafe_version_segment(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError):
        run_release_freeze(
            version="../0.1.0",
            output_root=tmp_path / "archive",
            run_id="d23_bad_version",
        )
