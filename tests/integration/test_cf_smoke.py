from __future__ import annotations

from datetime import date
from pathlib import Path
from zipfile import ZipFile

from cotton_factor.archive import read_run_manifest
from cotton_factor.smoke import run_cf_smoke


def test_cf_smoke_runs_full_chain_and_creates_archive_bundle(tmp_path: Path) -> None:
    result = run_cf_smoke(
        start=date(2024, 1, 2),
        end=date(2024, 2, 5),
        run_id="d19_cf_smoke_test",
        raw_root=tmp_path / "raw",
        archive_root=tmp_path / "archive",
    )

    assert result.report_path.exists()
    assert result.manifest_path.exists()
    assert result.audit_path.exists()
    assert result.checksums_path.exists()
    assert result.registry_path.exists()
    assert result.bundle_path.exists()

    assert result.row_counts["raw_snapshots"] == 2
    assert result.row_counts["core_quote_daily"] == 56
    assert result.row_counts["research_multifactor_score_daily"] > 0
    assert result.row_counts["backtest_fills"] > 0
    assert result.row_counts["archive_artifacts"] == 5

    manifest = read_run_manifest(result.manifest_path)
    assert manifest.run_id == "d19_cf_smoke_test"
    assert manifest.run_type == "cf_full_chain_smoke"
    assert manifest.status == "success"
    assert manifest.input_snapshot_ids == result.input_snapshot_ids
    assert manifest.row_counts["research_multifactor_score_daily"] > 0

    html = result.report_path.read_text(encoding="utf-8")
    assert "d19_cf_smoke_test Backtest Report" in html
    assert "CF405" in html

    with ZipFile(result.bundle_path) as archive:
        assert sorted(archive.namelist()) == [
            "artifact_registry.json",
            "audit.jsonl",
            "checksums.json",
            "manifest.json",
            "reports/backtest.html",
        ]
