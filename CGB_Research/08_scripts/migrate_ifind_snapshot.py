"""Migrate the audited iFinD snapshot without fetching, promoting, or publishing.

The old directories remain untouched. Historical manifests are copied byte-for-byte;
all relocation details live in a separate v2 migration manifest.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OLD_DATA = Path(r"D:\国债\ifind_data")
OLD_CODE = Path(r"D:\国债\ifind_rebuild")
TEMPLATE = Path(r"D:\国债\tmp\周报底稿_只读快照_20260815.xlsx")
MIGRATION_ID = "ifind_migration_20260815_v1"
CREATED_AT = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


DATASETS = [
    ("bond_futures_ctd_metrics", "20260815T135839+0800", 1100, "utf-8", "production"),
    ("deliverable_bond_volume", "20260815T142224+0800", 56, "utf-8", "production"),
    ("excess_reserve_rate_history", "20260815T142655+0800", 5, "gb18030", "excluded"),
    ("excess_reserve_ratio", "20260815T143957+0800", 22, "gb18030", "production"),
    ("futures_daily_market", "20260815T142030+0800", 6416, "utf-8", "production"),
    ("liquidity_policy_rates", "20260815T142106+0800", 8214, "gb18030", "production"),
    ("manufacturing_pmi_headline", "20260815T135901+0800", 266, "gb18030", "production"),
    ("specified_bond_irr_t", "20260815T142434+0800", 162, "utf-8", "production"),
    ("specified_bond_irr_t2609", "20260815T144144+0800", 162, "utf-8", "excluded"),
    ("specified_bond_irr_tf", "20260815T142415+0800", 108, "utf-8", "production"),
    ("specified_bond_irr_tf2609", "20260815T144126+0800", 108, "utf-8", "excluded"),
    ("specified_bond_irr_tl", "20260815T142452+0800", 162, "utf-8", "production"),
    ("specified_bond_irr_tl2609", "20260815T144203+0800", 162, "utf-8", "excluded"),
    ("specified_bond_irr_ts", "20260815T142356+0800", 108, "utf-8", "production"),
    ("specified_bond_irr_ts2609", "20260815T144108+0800", 108, "utf-8", "excluded"),
    ("specified_bond_irr_ts_fallback", "20260815T142950+0800", 162, "utf-8", "production"),
    ("yield_curve_cgb", "20260815T135558+0800", 19136, "gb18030", "production"),
]

EXPECTED_TABLE_ROWS = {
    "active_bond_selection": 10,
    "curve_and_futures_spreads": 1429,
    "deliverable_bond_master": 56,
    "deliverable_bond_volume": 56,
    "futures_ctd_daily": 1100,
    "futures_market_daily": 6416,
    "liquidity_policy_calendar": 1688,
    "liquidity_policy_raw": 8214,
    "manufacturing_pmi_monthly": 266,
    "manufacturing_pmi_wide": 19,
    "omo_weekly": 237,
    "report_futures_summary": 4,
    "report_yield_changes": 4,
    "report_yield_curve_snapshots": 78,
    "specified_bond_irr_daily": 702,
    "yield_curve_daily": 19136,
    "yield_curve_wide": 1472,
}

NATURAL_KEYS = {
    "active_bond_selection": ["report_date", "product", "rank"],
    "curve_and_futures_spreads": ["date"],
    "deliverable_bond_master": ["product", "bank_code"],
    "deliverable_bond_volume": ["date", "bank_code"],
    "futures_ctd_daily": ["date", "product", "continuous_code"],
    "futures_market_daily": ["date", "product", "continuous_code"],
    "liquidity_policy_calendar": ["date"],
    "liquidity_policy_raw": ["date", "id"],
    "manufacturing_pmi_monthly": ["date", "id"],
    "manufacturing_pmi_wide": ["date"],
    "omo_weekly": ["week_end"],
    "report_futures_summary": ["report_date", "product"],
    "report_yield_changes": ["report_date", "tenor"],
    "report_yield_curve_snapshots": ["snapshot", "tenor"],
    "specified_bond_irr_daily": ["date", "product", "active_contract", "bank_code"],
    "yield_curve_daily": ["date", "id"],
    "yield_curve_wide": ["date"],
}

PUBLISHED = {
    "active_bond_selection.csv": 10,
    "curve_and_futures_spreads.csv": 1429,
    "deliverable_bond_master.csv": 56,
    "manufacturing_pmi_wide.csv": 19,
    "omo_weekly.csv": 237,
    "report_futures_summary.csv": 4,
    "report_summary.json": None,
    "report_yield_changes.csv": 4,
    "report_yield_curve_snapshots.csv": 78,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def csv_profile(path: Path) -> tuple[int, list[str], str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = sum(1 for _ in reader)
    schema_hash = hashlib.sha256(
        json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return rows, header, schema_hash


def copy_verified(source: Path, target: Path, mappings: list[dict[str, object]], *,
                  role: str, encoding: str = "binary", row_count: int | None = None,
                  schema_hash: str = "", dataset_id: str = "", status: str = "copied") -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(source)
    if target.exists():
        if sha256(target) != source_hash:
            raise FileExistsError(f"Existing target differs: {target}")
    else:
        shutil.copy2(source, target)
    target_hash = sha256(target)
    if source_hash != target_hash or source.stat().st_size != target.stat().st_size:
        raise ValueError(f"Copy verification failed: {source}")
    mappings.append({
        "old_absolute_path": str(source), "new_relative_path": relative(target),
        "source_sha256": source_hash, "destination_sha256": target_hash,
        "bytes": source.stat().st_size, "encoding": encoding,
        "row_count": row_count, "schema_hash": schema_hash, "role": role,
        "dataset_id": dataset_id, "status": status,
    })


def alias_mapping(source: Path, target: Path, mappings: list[dict[str, object]], *,
                  role: str, reason: str) -> None:
    if not source.is_file() or not target.is_file():
        raise FileNotFoundError(source if not source.is_file() else target)
    source_hash, target_hash = sha256(source), sha256(target)
    if source_hash != target_hash:
        raise ValueError(f"Alias hash mismatch: {source} -> {target}")
    mappings.append({
        "old_absolute_path": str(source), "new_relative_path": relative(target),
        "source_sha256": source_hash, "destination_sha256": target_hash,
        "bytes": source.stat().st_size, "encoding": "binary", "row_count": None,
        "schema_hash": "", "role": role, "dataset_id": "",
        "status": "deduplicated_alias", "note": reason,
    })


def sqlite_checks(path: Path) -> dict[str, object]:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        quick = [row[0] for row in connection.execute("PRAGMA quick_check")]
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        duplicates: dict[str, int] = {}
        for table, keys in NATURAL_KEYS.items():
            key_sql = ", ".join(f'"{key}"' for key in keys)
            query = f'SELECT COUNT(*) FROM (SELECT {key_sql}, COUNT(*) AS duplicate_count FROM "{table}" GROUP BY {key_sql} HAVING COUNT(*)>1)'
            duplicates[table] = connection.execute(query).fetchone()[0]
        schema_rows = list(connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
        ))
        schema_hash = hashlib.sha256(
            json.dumps(schema_rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "quick_check": quick, "integrity_check": integrity,
            "foreign_key_check_rows": len(foreign_keys), "table_rows": counts,
            "natural_key_duplicate_groups": duplicates, "schema_hash": schema_hash,
        }
    finally:
        connection.close()


def append_csv_rows(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise ValueError(f"Unexpected CSV header: {path}")
            existing = list(reader)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(existing + rows)
    os.replace(temp, path)


def main() -> None:
    migration_manifest = ROOT / "09_audit" / "ifind_migration_manifest.json"
    if migration_manifest.exists():
        raise SystemExit("Migration manifest already exists; refusing to rerun or overwrite.")
    if not OLD_DATA.is_dir() or not OLD_CODE.is_dir() or not TEMPLATE.is_file():
        raise FileNotFoundError("Audited iFinD source roots or template are missing")
    mappings: list[dict[str, object]] = []
    dataset_records: list[dict[str, object]] = []
    production_rows = 0
    excluded_rows = 0

    for dataset_id, stamp, expected_rows, raw_encoding, disposition in DATASETS:
        filename = f"{dataset_id}_{stamp}"
        manifest_source = OLD_DATA / "manifests" / dataset_id / "2026-08-15" / f"{filename}.manifest.json"
        raw_source = OLD_DATA / "raw" / dataset_id / "2026-08-15" / f"{filename}.json"
        normalized_source = OLD_DATA / "normalized" / dataset_id / "2026-08-15" / f"{filename}.csv"
        request_source = OLD_CODE / "requests" / f"{dataset_id}.json"
        manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
        if manifest.get("status") != "success" or manifest.get("response", {}).get("errorcode") != 0:
            raise ValueError(f"Unsuccessful manifest: {dataset_id}")
        if manifest.get("response", {}).get("row_count") != expected_rows:
            raise ValueError(f"Manifest row mismatch: {dataset_id}")
        if manifest.get("response", {}).get("raw_sha256") != sha256(raw_source):
            raise ValueError(f"Raw manifest SHA mismatch: {dataset_id}")
        rows, header, schema_hash = csv_profile(normalized_source)
        if rows != expected_rows:
            raise ValueError(f"Normalized row mismatch: {dataset_id}")

        manifest_target = ROOT / "05_data" / "snapshots" / "lineage" / "ifind" / dataset_id / "2026-08-15" / manifest_source.name
        copy_verified(manifest_source, manifest_target, mappings, role="source_manifest_v1", encoding="utf-8", row_count=expected_rows, dataset_id=dataset_id)
        if disposition == "production":
            raw_target = ROOT / "05_data" / "raw" / "ifind" / dataset_id / "2026-08-15" / raw_source.name
            normalized_target = ROOT / "05_data" / "processed" / "ifind" / dataset_id / "2026-08-15" / normalized_source.name
            request_target = ROOT / "08_scripts" / "config" / "ifind_requests" / "templates" / request_source.name
            production_rows += expected_rows
            raw_role, normalized_role = "production_raw_response", "production_normalized"
        else:
            reason = "wrong_definition" if dataset_id == "excess_reserve_rate_history" else "actual_contract_probe"
            archive_root = ROOT / "99_archive" / "ifind_probes" / reason / dataset_id / "2026-08-15"
            raw_target = archive_root / "raw" / raw_source.name
            normalized_target = archive_root / "normalized" / normalized_source.name
            request_target = archive_root / "request" / request_source.name
            excluded_rows += expected_rows
            raw_role, normalized_role = "excluded_raw_response", "excluded_normalized"
        copy_verified(raw_source, raw_target, mappings, role=raw_role, encoding=raw_encoding, row_count=expected_rows, dataset_id=dataset_id)
        copy_verified(normalized_source, normalized_target, mappings, role=normalized_role, encoding="utf-8-sig", row_count=expected_rows, schema_hash=schema_hash, dataset_id=dataset_id)
        copy_verified(request_source, request_target, mappings, role="production_request_template" if disposition == "production" else "excluded_request", encoding="utf-8", dataset_id=dataset_id)
        dataset_records.append({
            "dataset_id": dataset_id, "disposition": disposition, "as_of": "2026-08-15",
            "stamp": stamp, "row_count": expected_rows, "raw_encoding": raw_encoding,
            "normalized_encoding": "utf-8-sig", "normalized_columns": header,
            "schema_hash": schema_hash, "source_manifest_sha256": sha256(manifest_source),
            "request_sha256": sha256(request_source), "raw_sha256": sha256(raw_source),
            "normalized_sha256": sha256(normalized_source),
            "manifest_relative_path": relative(manifest_target),
            "raw_relative_path": relative(raw_target),
            "normalized_relative_path": relative(normalized_target),
            "request_relative_path": relative(request_target),
        })

    if production_rows != 35912 or excluded_rows != 545:
        raise ValueError(f"Dataset totals mismatch: {production_rows}, {excluded_rows}")

    weekly_source = OLD_DATA / "local_mart" / "2026-08-14" / "weekly_report_20260814.sqlite"
    weekly_manifest_source = OLD_DATA / "local_mart" / "2026-08-14" / "weekly_report_20260814.manifest.json"
    weekly_target = ROOT / "05_data" / "snapshots" / "weekly" / "2026-08-14" / weekly_source.name
    weekly_manifest_target = weekly_target.with_suffix(".manifest.json")
    copy_verified(weekly_source, weekly_target, mappings, role="weekly_sqlite_baseline")
    copy_verified(weekly_manifest_source, weekly_manifest_target, mappings, role="weekly_manifest_v1", encoding="utf-8")
    source_sqlite_checks = sqlite_checks(weekly_source)
    target_sqlite_checks = sqlite_checks(weekly_target)
    if source_sqlite_checks != target_sqlite_checks:
        raise ValueError("SQLite source/target validation differs")
    if source_sqlite_checks["quick_check"] != ["ok"] or source_sqlite_checks["integrity_check"] != ["ok"]:
        raise ValueError("SQLite integrity failed")
    if source_sqlite_checks["foreign_key_check_rows"] != 0:
        raise ValueError("SQLite foreign-key check failed")
    if source_sqlite_checks["table_rows"] != EXPECTED_TABLE_ROWS:
        raise ValueError("SQLite table-row contract mismatch")
    if any(source_sqlite_checks["natural_key_duplicate_groups"].values()):
        raise ValueError("SQLite natural-key duplicates detected")

    published_records: list[dict[str, object]] = []
    for name, expected_rows in PUBLISHED.items():
        source = OLD_DATA / "published" / "2026-08-14" / name
        target = ROOT / "06_weekly" / "2026-W33" / "data_snapshot" / name
        if name.endswith(".csv"):
            rows, header, schema_hash = csv_profile(source)
            if rows != expected_rows:
                raise ValueError(f"Published row mismatch: {name}")
            encoding = "utf-8-sig"
        else:
            json.loads(source.read_text(encoding="utf-8"))
            rows, header, schema_hash, encoding = None, [], "", "utf-8"
        copy_verified(source, target, mappings, role="weekly_published_regression_baseline", encoding=encoding, row_count=rows, schema_hash=schema_hash)
        published_records.append({"filename": name, "rows": rows, "sha256": sha256(source), "columns": header, "relative_path": relative(target)})

    current_sqlite = OLD_DATA / "current" / "weekly_report_current.sqlite"
    current_summary = OLD_DATA / "current" / "report_summary_current.json"
    alias_mapping(current_sqlite, weekly_target, mappings, role="current_alias", reason="Current DB is byte-identical to the formal weekly snapshot; no second physical copy.")
    alias_mapping(current_summary, ROOT / "06_weekly" / "2026-W33" / "data_snapshot" / "report_summary.json", mappings, role="current_alias", reason="Current summary is byte-identical to the published baseline; no second physical copy.")

    weekly_pointer = ROOT / "05_data" / "snapshots" / "weekly" / "CURRENT.json"
    weekly_pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer_payload = {
        "snapshot_id": "weekly_2026-08-14_baseline",
        "snapshot_relative_path": relative(weekly_target),
        "snapshot_sha256": sha256(weekly_target),
        "report_summary_relative_path": "06_weekly/2026-W33/data_snapshot/report_summary.json",
        "report_summary_sha256": sha256(ROOT / "06_weekly" / "2026-W33" / "data_snapshot" / "report_summary.json"),
        "status": "baseline_read_only", "promotion_enabled": False,
        "note": "Initialization pointer only; no fetch, promote, publish, or writer switch was performed.",
    }
    weekly_pointer.write_text(json.dumps(pointer_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    local_mart = OLD_DATA / "local_mart" / "2026-08-14"
    old_hash = "1c1e882c78d08365b09056735c8643f2a87875dd93ad0a781caa321bb5ba65e2"
    formal_hash = sha256(weekly_source)
    bak_files = sorted(local_mart.glob("*.sqlite.bak"), key=lambda item: item.name)
    old_group = [path for path in bak_files if sha256(path) == old_hash]
    formal_group = [path for path in bak_files if sha256(path) == formal_hash]
    if len(old_group) != 2 or len(formal_group) != 4:
        raise ValueError("Unexpected .bak hash groups")
    old_archive = ROOT / "99_archive" / "ifind_sqlite_history" / old_hash / old_group[0].name
    copy_verified(old_group[0], old_archive, mappings, role="deduplicated_historical_sqlite")
    for source in old_group[1:]:
        alias_mapping(source, old_archive, mappings, role="historical_sqlite_alias", reason="Duplicate historical .bak content; mapped to one archived object.")
    for source in formal_group:
        alias_mapping(source, weekly_target, mappings, role="historical_sqlite_alias", reason="Backup is byte-identical to formal weekly snapshot; no archive duplicate.")
    alias_payload = {
        "unique_hashes": {
            old_hash: {"physical_object": relative(old_archive), "source_aliases": [str(path) for path in old_group]},
            formal_hash: {"physical_object": relative(weekly_target), "source_aliases": [str(path) for path in formal_group], "note": "Physical object retained in weekly baseline, referenced from archive index."},
        }
    }
    alias_index = ROOT / "99_archive" / "ifind_sqlite_history" / "dedup_aliases.json"
    alias_index.parent.mkdir(parents=True, exist_ok=True)
    alias_index.write_text(json.dumps(alias_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    legacy_probe_root = OLD_DATA / "2026-08-15"
    for source in sorted(legacy_probe_root.glob("*"), key=lambda item: item.name):
        if not source.is_file():
            continue
        target = ROOT / "99_archive" / "ifind_probes" / "legacy_subset" / "2026-08-15" / source.name
        encoding = "utf-8-sig" if source.suffix.lower() == ".csv" else "utf-8"
        row_count = csv_profile(source)[0] if source.suffix.lower() == ".csv" else None
        schema_hash = csv_profile(source)[2] if source.suffix.lower() == ".csv" else ""
        copy_verified(source, target, mappings, role="legacy_92row_subset", encoding=encoding, row_count=row_count, schema_hash=schema_hash)

    orphan_request = OLD_CODE / "requests" / "futures_active_contract_snapshot.json"
    orphan_target = ROOT / "99_archive" / "ifind_probes" / "orphan_request" / orphan_request.name
    copy_verified(orphan_request, orphan_target, mappings, role="orphan_request_no_data", encoding="utf-8")

    template_target = ROOT / "06_weekly" / "template" / "imported" / TEMPLATE.name
    copy_verified(TEMPLATE, template_target, mappings, role="weekly_excel_template_baseline")

    special_targets = {
        "project_data_registry.json": ROOT / "09_audit" / "legacy_ifind" / "project_data_registry_20260815.json",
        "cffex_deliverable_snapshot_20260815.json": ROOT / "09_audit" / "legacy_ifind" / "cffex_deliverable_snapshot_20260815.json",
        "weekly_report_copy_20260814.json": ROOT / "06_weekly" / "2026-W33" / "legacy_copy" / "weekly_report_copy_20260814.json",
    }
    archived_old_code: list[str] = []
    for source in sorted((path for path in OLD_CODE.rglob("*") if path.is_file()), key=lambda item: str(item)):
        relative_old = source.relative_to(OLD_CODE)
        parts_lower = {part.lower() for part in relative_old.parts}
        if ".venv" in parts_lower or "__pycache__" in parts_lower or "logs" in parts_lower or source.suffix.lower() == ".pyc":
            continue
        if relative_old.parts[0] == "requests":
            dataset_id = source.stem
            dataset = next((item for item in dataset_records if item["dataset_id"] == dataset_id), None)
            target = ROOT / dataset["request_relative_path"] if dataset else orphan_target
            alias_mapping(source, target, mappings, role="old_code_request_alias", reason="Request is already represented in active templates or excluded archive; no duplicate in old-code archive.")
            continue
        if source.name in special_targets:
            target = special_targets[source.name]
            copy_verified(source, target, mappings, role="legacy_audit_or_weekly_context", encoding="utf-8")
        else:
            target = ROOT / "99_archive" / "ifind_rebuild_v0" / relative_old
            copy_verified(source, target, mappings, role="disabled_legacy_code_or_config", encoding="utf-8")
        archived_old_code.append(str(relative_old).replace("\\", "/"))

    cffex_legacy = special_targets["cffex_deliverable_snapshot_20260815.json"]
    migration_payload = {
        "manifest_version": "2.0", "migration_id": MIGRATION_ID,
        "created_at": CREATED_AT, "project_root": str(ROOT),
        "mode": "logical_complete_physical_sha256_deduplicated",
        "old_roots_retained": True, "old_roots_modified": False,
        "api_fetch_performed": False, "promote_performed": False,
        "publish_performed": False, "pipeline_enabled": False,
        "credential_target": "iFinD_API_Weekly_Report",
        "legacy_absolute_path_values_in_19_manifests": 78,
        "all_json_absolute_path_values_including_automation_config": 79,
        "source_ifind_data_files": 73, "source_ifind_data_bytes": 47504367,
        "production_dataset_count": 12, "production_rows": production_rows,
        "excluded_dataset_count": 5, "excluded_rows": excluded_rows,
        "datasets": dataset_records,
        "weekly_baseline": {
            "sqlite_relative_path": relative(weekly_target), "sqlite_sha256": sha256(weekly_target),
            "manifest_relative_path": relative(weekly_manifest_target),
            "manifest_sha256": sha256(weekly_manifest_target),
            "sqlite_checks": target_sqlite_checks, "published": published_records,
            "current_pointer_relative_path": relative(weekly_pointer),
        },
        "template": {"relative_path": relative(template_target), "sha256": sha256(template_target)},
        "legacy_cffex_snapshot": {
            "relative_path": relative(cffex_legacy), "sha256": sha256(cffex_legacy),
            "complete_official_snapshot": False,
            "note": "Legacy file contains counts/assertions but not a complete official table/HTML snapshot; production remains disabled.",
        },
        "old_code_archive_files": archived_old_code,
        "excluded_from_copy": [".venv", "__pycache__", "logs", "*.pyc"],
        "file_mappings": mappings,
        "code_version": {"migration_script_sha256": sha256(Path(__file__)), "git_commit": None},
    }
    migration_manifest.write_text(json.dumps(migration_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    issue_columns = [
        "issue_id", "stage", "source_path", "target_relative_path", "issue_type",
        "severity", "evidence_class", "description", "status", "blocking_condition",
        "resolution", "detected_at", "reviewed_at",
    ]
    issue_specs = [
        ("legacy_paths", str(OLD_CODE), "99_archive/ifind_rebuild_v0", "hardcoded_paths_and_environment", "high", "旧采集脚本写死D:\\国债\\ifind_data、旧项目根和旧.venv。", "重构路径注入与依赖锁前不得启用。"),
        ("cffex_snapshot", str(OLD_CODE / "cffex_deliverable_snapshot_20260815.json"), relative(cffex_legacy), "incomplete_cffex_snapshot", "critical", "旧快照只有行数/声明，没有完整官方HTML或转换因子表。", "取得完整官方快照、来源URL与SHA前不得启用。"),
        ("conversion_factor", str(OLD_CODE / "build_weekly_datamart.py"), "08_scripts/ifind", "contract_roll_conversion_factor_mismatch", "critical", "旧逻辑固定cf_2609/cf_2612/cf_2703列，换月后会出现表头与转换因子错配。", "改用product+contract_code+bond_code长表并通过换月测试。"),
        ("mixed_batches", str(OLD_CODE / "build_weekly_datamart.py"), "08_scripts/build_weekly_snapshot.py", "latest_scan_can_mix_runs", "critical", "旧逻辑扫描latest，采集失败时可能混用不同批次。", "只允许单一冻结run manifest列出12个精确输入。"),
        ("double_writer", str(OLD_CODE / "run_weekly_update.ps1"), "05_data/snapshots/weekly/CURRENT.json", "non_atomic_publish_and_double_writer", "critical", "旧入口会覆盖current/config/request；新旧双写可能破坏可追溯性。", "完成单writer锁、唯一run目录和原子CURRENT切换后再授权。"),
        ("office_chain", str(OLD_CODE), "99_archive/ifind_rebuild_v0", "office_and_email_chain_disabled", "high", "Excel/Word COM和发送链路未串联且模板结构依赖未版本化。", "初始化阶段保持禁用，不创建计划任务、不发送邮件。"),
    ]
    issue_rows = []
    for idx, (_, source_path, target_path, issue_type, severity, description, blocker) in enumerate(issue_specs, start=1):
        issue_rows.append({
            "issue_id": f"mig_20260815_{idx:03d}", "stage": "initialization_migration",
            "source_path": source_path, "target_relative_path": target_path,
            "issue_type": issue_type, "severity": severity, "evidence_class": "X",
            "description": description, "status": "open", "blocking_condition": blocker,
            "resolution": "", "detected_at": CREATED_AT, "reviewed_at": "",
        })
    append_csv_rows(ROOT / "09_audit" / "data_migration_issues.csv", issue_columns, issue_rows)

    processing_columns = [
        "run_id", "step_no", "timestamp", "object_type", "object_id", "stage", "action",
        "tool", "tool_version", "input_sha256", "output_relative_path", "output_sha256",
        "status", "records_or_pages", "config_sha256", "git_commit", "message",
    ]
    processing_rows = []
    for step, item in enumerate(mappings, start=1):
        processing_rows.append({
            "run_id": MIGRATION_ID, "step_no": step, "timestamp": CREATED_AT,
            "object_type": item["role"], "object_id": item.get("dataset_id", "") or Path(str(item["old_absolute_path"])).name,
            "stage": "ifind_migration", "action": item["status"],
            "tool": "migrate_ifind_snapshot.py", "tool_version": f"python {sys.version_info.major}.{sys.version_info.minor}",
            "input_sha256": item["source_sha256"], "output_relative_path": item["new_relative_path"],
            "output_sha256": item["destination_sha256"], "status": "success",
            "records_or_pages": item.get("row_count") if item.get("row_count") is not None else "",
            "config_sha256": sha256(Path(__file__)), "git_commit": "",
            "message": "字节级复制并验哈希。" if item["status"] == "copied" else "按SHA-256映射到已存在物理对象，未重复复制。",
        })
    append_csv_rows(ROOT / "01_registry" / "processing_log.csv", processing_columns, processing_rows)

    print(json.dumps({
        "migration_id": MIGRATION_ID, "production_datasets": 12,
        "production_rows": production_rows, "excluded_datasets": 5,
        "excluded_rows": excluded_rows, "mapping_count": len(mappings),
        "sqlite_tables": len(target_sqlite_checks["table_rows"]),
        "sqlite_rows": sum(target_sqlite_checks["table_rows"].values()),
        "api_fetch_performed": False, "pipeline_enabled": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
