"""Read-only acceptance checks for the CGB_Research initialization."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

from migrate_ifind_snapshot import EXPECTED_TABLE_ROWS, sha256, sqlite_checks


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(r"D:\researchreports\bond")
OLD_DATA = Path(r"D:\国债\ifind_data")
GIT = Path(r"C:\Users\zsqh\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe")

REPORT_COLUMNS = [
    "report_id", "relative_path", "source_original_path", "filename", "sha256",
    "file_size_bytes", "page_count", "title", "institution", "co_brand",
    "authors_display", "publish_date", "publish_date_text", "publish_date_precision",
    "filename_date", "data_cutoff", "latest_explicit_data_date", "data_cutoff_scope",
    "primary_topic", "topic_tags", "report_type", "research_horizon",
    "instrument_scope", "has_text_layer", "text_page_coverage_pct", "text_char_count",
    "ocr_requirement", "visual_review_requirement", "chart_density", "duplicate_status",
    "duplicate_of_report_id", "partial_overlap_group", "extraction_quality",
    "manual_review_status", "ingested_at", "notes",
]
EVIDENCE_COLUMNS = [
    "evidence_id", "report_id", "field_name", "field_value", "evidence_class",
    "source_type", "page_start", "page_end", "evidence_data_cutoff", "cutoff_scope",
    "extraction_method", "confidence", "review_status", "note",
]
ASSET_COLUMNS = [
    "asset_id", "relative_path", "source_original_path", "filename", "file_type",
    "sha256", "file_size_bytes", "asset_role", "associated_report_id", "institution",
    "asset_date", "sheet_count", "extraction_quality", "manual_review_status", "notes",
]
PROCESSING_COLUMNS = [
    "run_id", "step_no", "timestamp", "object_type", "object_id", "stage", "action",
    "tool", "tool_version", "input_sha256", "output_relative_path", "output_sha256",
    "status", "records_or_pages", "config_sha256", "git_commit", "message",
]
ISSUE_COLUMNS = [
    "issue_id", "report_id", "asset_id", "field_name", "page_start", "page_end",
    "issue_type", "severity", "evidence_class", "description", "status", "resolution",
    "detected_at", "reviewed_at",
]

ENUMS = {
    "data_cutoff_scope": {"report_wide", "section_specific", "mixed", "none"},
    "ocr_requirement": {"none", "targeted", "full"},
    "duplicate_status": {"unique", "exact_duplicate", "near_duplicate", "version_candidate", "partial_overlap_review"},
    "manual_review_status": {"pending", "approved", "changes_requested", "rejected"},
    "report_type": {"half_year_outlook", "weekly_market", "institution_behavior", "fund_data", "event_commentary", "futures_microstructure", "cross_asset_macro", "other"},
}


def inventory(paths: list[Path]) -> dict[str, tuple[int, int, str]]:
    records: dict[str, tuple[int, int, str]] = {}
    for base in paths:
        if base.is_file():
            items = [base]
        else:
            items = [path for path in base.rglob("*") if path.is_file() and ".git" not in path.parts]
        for path in items:
            stat_result = path.stat()
            records[str(path)] = (stat_result.st_size, stat_result.st_mtime_ns, sha256(path))
    return records


def read_csv(path: Path, expected: list[str] | None = None) -> list[dict[str, str]]:
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), f"missing UTF-8 BOM: {path}"
    assert b"\n" not in raw.replace(b"\r\n", b""), f"non-CRLF line ending: {path}"
    text = raw.decode("utf-8-sig", errors="strict")
    assert "\ufffd" not in text, f"replacement character: {path}"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        if expected is not None:
            assert reader.fieldnames == expected, f"header mismatch: {path}"
        assert reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), f"duplicate header: {path}"
        return list(reader)


def check(condition: bool, test_id: str, actual: object, results: list[dict[str, object]], severity: str = "P0") -> None:
    results.append({"test_id": test_id, "severity": severity, "status": "PASS" if condition else "FAIL", "actual": actual})
    if not condition:
        raise AssertionError(f"{test_id}: {actual}")


def git_output(*args: str) -> str:
    result = subprocess.run([str(GIT), *args], cwd=ROOT, check=True, text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def main() -> None:
    results: list[dict[str, object]] = []
    critical_before = inventory([ROOT, SOURCE_ROOT])

    required_paths = [
        "AGENTS.md", "README.md", ".gitignore", "00_inbox/raw_reports", "00_inbox/pending_review",
        "01_registry", "02_report_cards/2025", "02_report_cards/2026", "03_frameworks/researcher_profiles",
        "04_indicators", "05_data/raw", "05_data/processed", "05_data/snapshots", "06_weekly/template",
        "06_weekly/2026-W33", "07_events", "08_scripts", "09_audit/weekly_quality_reports", "99_archive",
    ]
    missing = [item for item in required_paths if not (ROOT / item).exists()]
    check(not missing, "T01_required_paths", missing, results)

    agents_path = ROOT / "AGENTS.md"
    agents_hash_1 = sha256(agents_path)
    agents_text = agents_path.read_text(encoding="utf-8", errors="strict")
    required_phrases = [
        "建立一套可追溯、可比较、可持续更新的中国国债与国债期货研究体系。",
        "Codex是研究资料管理员、研究工程师和审稿人，不是最终投资判断者。",
        "00_inbox/raw_reports 下的原始文件只读",
        "不得编造报告作者、日期、数据、页码、图表含义或引用",
        "[E] Explicit", "[I] Inference", "[X] External", "[U] Uncertain",
        "每条[E]必须标注report_id、页码和报告数据截止日",
        "严格区分报告发布日期与报告所使用数据的截止日期",
        "严格区分现券、国债期货、收益率曲线、期限利差、基差、CTD、IRR和Carry",
        "适用期限", "传导机制", "触发条件", "证伪条件", "跟踪指标",
        "区分长期有效的机制和短期市场叙事", "不得把相关性直接写成因果关系",
        "先用3份报告测试并生成质量审计", "不直接覆盖已确认的周报和研究卡片",
        "结论先行，但结论必须有数据或事件支撑", "区分事实、解释、市场定价和未来情景",
        "每张图表必须支撑一个明确论点", "复核上一期观点", "不使用空泛表达",
    ]
    absent = [phrase for phrase in required_phrases if phrase not in agents_text]
    agents_hash_2 = sha256(agents_path)
    check(not absent and agents_hash_1 == agents_hash_2 and "\ufffd" not in agents_text, "T02_agents_utf8_hash_and_rules", {"sha256": agents_hash_2, "missing": absent}, results)

    reports = read_csv(ROOT / "01_registry" / "reports.csv", REPORT_COLUMNS)
    evidence = read_csv(ROOT / "01_registry" / "report_metadata_evidence.csv", EVIDENCE_COLUMNS)
    assets = read_csv(ROOT / "01_registry" / "source_assets.csv", ASSET_COLUMNS)
    processing = read_csv(ROOT / "01_registry" / "processing_log.csv", PROCESSING_COLUMNS)
    issues = read_csv(ROOT / "09_audit" / "extraction_issues.csv", ISSUE_COLUMNS)
    for path in [
        ROOT / "01_registry" / "researchers.csv", ROOT / "04_indicators" / "indicator_dictionary.csv",
        ROOT / "04_indicators" / "data_source_map.csv", ROOT / "06_weekly" / "view_ledger.csv",
        ROOT / "07_events" / "policy_events.csv", ROOT / "07_events" / "economic_calendar.csv",
        ROOT / "07_events" / "market_anomalies.csv", ROOT / "09_audit" / "forecast_scorecard.csv",
        ROOT / "09_audit" / "pilot_selection_20260815.csv", ROOT / "09_audit" / "data_migration_issues.csv",
    ]:
        read_csv(path)
    check(len(reports) == 15, "T04_report_count", len(reports), results)
    report_ids = {row["report_id"] for row in reports}
    check(len(report_ids) == 15 and all(row["report_id"] == "rpt_" + row["sha256"][:16] for row in reports), "T04_report_id_contract", sorted(report_ids), results)
    for field, allowed in ENUMS.items():
        invalid = sorted({row[field] for row in reports} - allowed)
        check(not invalid, f"T04_enum_{field}", invalid, results, "P1")
    check(all(row["manual_review_status"] == "pending" for row in reports), "T04_reports_pending_review", True, results)
    check(all(not row["data_cutoff"] for row in reports), "T04_no_invented_report_wide_cutoff", True, results)
    check(all(row["ocr_requirement"] != "full" for row in reports), "T04_no_full_ocr", True, results)

    source_pdfs = sorted(SOURCE_ROOT.glob("*.pdf"), key=lambda path: path.name)
    target_pdfs = sorted((ROOT / "00_inbox" / "raw_reports").glob("*.pdf"), key=lambda path: path.name)
    check(len(source_pdfs) == len(target_pdfs) == 15 and {p.name for p in source_pdfs} == {p.name for p in target_pdfs}, "T03_pdf_sets", {"source": len(source_pdfs), "target": len(target_pdfs)}, results)
    by_filename = {row["filename"]: row for row in reports}
    pdf_matrix = []
    for source in source_pdfs:
        target = ROOT / "00_inbox" / "raw_reports" / source.name
        row = by_filename[source.name]
        source_hash, target_hash = sha256(source), sha256(target)
        read_only = bool(getattr(target.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_READONLY)
        pages = len(PdfReader(str(target)).pages)
        ok = (
            source_hash == target_hash == row["sha256"]
            and source.stat().st_size == target.stat().st_size == int(row["file_size_bytes"])
            and pages == int(row["page_count"]) and read_only
            and row["relative_path"] == f"00_inbox/raw_reports/{source.name}"
        )
        pdf_matrix.append({"filename": source.name, "status": "PASS" if ok else "FAIL"})
        if not ok:
            raise AssertionError(f"PDF integrity failed: {source.name}")
    check(all(item["status"] == "PASS" for item in pdf_matrix), "T03_pdf_integrity_and_readonly", {"passed": len(pdf_matrix)}, results)

    workbook_source = next(SOURCE_ROOT.glob("*.xlsx"))
    workbook_target = ROOT / "00_inbox" / "pending_review" / workbook_source.name
    check(len(assets) == 1 and sha256(workbook_source) == sha256(workbook_target) == assets[0]["sha256"], "T03_workbook_asset_integrity", assets[0]["asset_id"], results)

    evidence_ids = [row["evidence_id"] for row in evidence]
    evidence_bad = []
    for row in evidence:
        if row["report_id"] not in report_ids or row["evidence_class"] not in {"E", "I", "X", "U"}:
            evidence_bad.append(row["evidence_id"])
            continue
        report = next(item for item in reports if item["report_id"] == row["report_id"])
        if row["page_start"]:
            if not (1 <= int(row["page_start"]) <= int(row["page_end"]) <= int(report["page_count"])):
                evidence_bad.append(row["evidence_id"])
        if row["evidence_class"] == "E":
            if not row["page_start"] or (not row["evidence_data_cutoff"] and "U" not in row["note"]):
                evidence_bad.append(row["evidence_id"])
    check(len(evidence_ids) == len(set(evidence_ids)) and not evidence_bad, "T05_evidence_fk_pages_and_E_contract", evidence_bad, results)
    asset_ids = {row["asset_id"] for row in assets}
    issue_bad = [row["issue_id"] for row in issues if (row["report_id"] and row["report_id"] not in report_ids) or (row["asset_id"] and row["asset_id"] not in asset_ids) or (not row["report_id"] and not row["asset_id"])]
    check(not issue_bad and len({row["issue_id"] for row in issues}) == len(issues), "T05_issue_fk_and_unique", issue_bad, results)
    forbidden_actions = ("generate_card", "summarize_report", "build_weekly_report", "delete", "rename", "overwrite_raw")
    processing_actions = "\n".join(
        f"{row['stage']}|{row['action']}|{row['message']}".lower() for row in processing
    )
    check(not any(term in processing_actions for term in forbidden_actions), "T05_processing_log_no_forbidden_actions", True, results)

    migration = json.loads((ROOT / "09_audit" / "ifind_migration_manifest.json").read_text(encoding="utf-8"))
    datasets = migration["datasets"]
    production = [item for item in datasets if item["disposition"] == "production"]
    excluded = [item for item in datasets if item["disposition"] == "excluded"]
    lineage_manifests = list((ROOT / "05_data" / "snapshots" / "lineage" / "ifind").rglob("*.manifest.json"))
    check(len(datasets) == 17 and len(production) == 12 and len(excluded) == 5 and sum(item["row_count"] for item in production) == 35912 and sum(item["row_count"] for item in excluded) == 545 and len(lineage_manifests) == 17, "T06_dataset_contract", {"production": len(production), "production_rows": sum(item["row_count"] for item in production), "excluded": len(excluded), "excluded_rows": sum(item["row_count"] for item in excluded), "lineage": len(lineage_manifests)}, results)
    dataset_bad = []
    for item in datasets:
        for key, hash_key in (("manifest_relative_path", "source_manifest_sha256"), ("raw_relative_path", "raw_sha256"), ("normalized_relative_path", "normalized_sha256"), ("request_relative_path", "request_sha256")):
            path = ROOT / item[key]
            if not path.is_file() or sha256(path) != item[hash_key]:
                dataset_bad.append(f"{item['dataset_id']}:{key}")
        rows = read_csv(ROOT / item["normalized_relative_path"])
        if len(rows) != item["row_count"]:
            dataset_bad.append(f"{item['dataset_id']}:rows")
        if item["disposition"] == "excluded" and not item["normalized_relative_path"].startswith("99_archive/"):
            dataset_bad.append(f"{item['dataset_id']}:excluded_path")
    check(not dataset_bad, "T06_dataset_hashes_rows_and_separation", dataset_bad, results)
    old_data_files = [path for path in OLD_DATA.rglob("*") if path.is_file()]
    check(len(old_data_files) == 73 and sum(path.stat().st_size for path in old_data_files) == 47504367, "T06_old_data_root_unchanged_shape", {"files": len(old_data_files), "bytes": sum(path.stat().st_size for path in old_data_files)}, results)

    weekly = ROOT / "05_data" / "snapshots" / "weekly" / "2026-08-14" / "weekly_report_20260814.sqlite"
    sql = sqlite_checks(weekly)
    check(sql["quick_check"] == ["ok"] and sql["integrity_check"] == ["ok"] and sql["foreign_key_check_rows"] == 0 and sql["table_rows"] == EXPECTED_TABLE_ROWS and not any(sql["natural_key_duplicate_groups"].values()), "T07_sqlite_integrity_rows_keys", {"tables": len(sql["table_rows"]), "rows": sum(sql["table_rows"].values()), "schema_hash": sql["schema_hash"]}, results)
    published = ROOT / "06_weekly" / "2026-W33" / "data_snapshot"
    check(len([path for path in published.iterdir() if path.is_file()]) == 9, "T07_published_regression_files", sorted(path.name for path in published.iterdir() if path.is_file()), results)
    pointer = json.loads((ROOT / "05_data" / "snapshots" / "weekly" / "CURRENT.json").read_text(encoding="utf-8"))
    check(pointer["promotion_enabled"] is False and pointer["snapshot_sha256"] == sha256(weekly), "T07_current_pointer_readonly", pointer, results)

    dry_run = json.loads((ROOT / "09_audit" / "no_fetch_dry_run_manifest_20260815.json").read_text(encoding="utf-8"))
    check(len(dry_run["frozen_inputs"]) == 12 and not dry_run["cffex_snapshot_complete"] and not dry_run["dynamic_conversion_factor_validated"] and not dry_run["single_writer_lock_validated"] and not dry_run["atomic_current_update_validated"], "T07_dry_run_blockers_locked", True, results)

    card_files = [path for year in ("2025", "2026") for path in (ROOT / "02_report_cards" / year).rglob("*") if path.is_file()]
    check(not card_files, "T09_no_report_cards_or_summaries", [str(path) for path in card_files], results)

    check((ROOT / ".git").is_dir(), "T08_git_initialized", True, results)
    top = Path(git_output("rev-parse", "--show-toplevel")).resolve()
    remotes = git_output("remote")
    check(top == ROOT.resolve() and not remotes, "T08_git_root_no_remote", {"top": str(top), "remotes": remotes}, results)

    critical_after = inventory([ROOT, SOURCE_ROOT])
    check(critical_before == critical_after, "T00_validation_read_only", {"files": len(critical_after)}, results)
    print(json.dumps({
        "status": "PASS", "tests": results,
        "summary": {"pass": sum(item["status"] == "PASS" for item in results), "fail": 0},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
