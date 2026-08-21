"""Read-only structural and integrity validator for the three Gate B report cards."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "01_registry" / "reports.csv"
GATE_A = {
    "rpt_c5fb1a641cf93b7c",
    "rpt_feca128af69a3d3b",
    "rpt_c406ce66269f6c16",
}
GATE_B = {
    "rpt_5856700aced049fc": {"pages": 13, "minimum_audits": 10},
    "rpt_737662a2d6e52aed": {"pages": 8, "minimum_audits": 10},
    "rpt_bb2de5c3b82fc0e2": {"pages": 38, "minimum_audits": 12},
}
PAGE_COLUMNS = [
    "report_id",
    "page",
    "page_class",
    "text_char_count",
    "chart_dependency",
    "visual_review_required",
    "review_status",
    "notes",
]
AUDIT_COLUMNS = [
    "audit_id",
    "report_id",
    "card_evidence_id",
    "pdf_page",
    "claim_excerpt_or_paraphrase",
    "number_unit_direction_check",
    "cutoff_check",
    "instrument_check",
    "evidence_class_check",
    "chart_dependency_check",
    "result",
    "reviewer_note",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    data = path.read_bytes()
    if not data.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"missing UTF-8 BOM: {path}")
    if b"\n" in data.replace(b"\r\n", b""):
        raise ValueError(f"non-CRLF line ending: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def result(test_id: str, passed: bool, actual: object) -> dict[str, object]:
    return {"test_id": test_id, "status": "PASS" if passed else "FAIL", "actual": actual}


def page_reference_valid(value: str, maximum: int) -> bool:
    """Accept a single page or a compact range/list such as 6-8 or 3,5."""
    if not re.fullmatch(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*", value.strip()):
        return False
    pages: list[int] = []
    for part in value.split(","):
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            if start > end:
                return False
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    return bool(pages) and all(1 <= page <= maximum for page in pages)


def main() -> int:
    tests: list[dict[str, object]] = []
    _, registry_rows = read_csv(REPORTS)
    registry = {row["report_id"]: row for row in registry_rows}

    for report_id, rule in GATE_B.items():
        page_count = rule["pages"]
        card = ROOT / "02_report_cards" / "2026" / f"{report_id}_v0.1.md"
        page_inventory = ROOT / "09_audit" / "gate_b" / f"{report_id}_page_inventory.csv"
        evidence_audit = ROOT / "09_audit" / "gate_b" / f"{report_id}_evidence_audit.csv"
        paths_exist = all(path.is_file() for path in (card, page_inventory, evidence_audit))
        tests.append(result(f"{report_id}_outputs_exist", paths_exist, [str(card), str(page_inventory), str(evidence_audit)]))
        if not paths_exist:
            continue

        card_text = card.read_text(encoding="utf-8-sig")
        registry_row = registry[report_id]
        tests.append(result(f"{report_id}_frontmatter_report_id", f"report_id: {report_id}" in card_text, report_id))
        tests.append(result(f"{report_id}_source_sha", f"source_sha256: {registry_row['sha256']}" in card_text, registry_row["sha256"]))
        headings = [f"# {section}." for section in range(13)]
        missing_headings = [heading for heading in headings if heading not in card_text]
        tests.append(result(f"{report_id}_sections_0_to_12", not missing_headings, missing_headings))
        tests.append(result(f"{report_id}_card_version", "card_version: v0.1" in card_text, "v0.1"))
        tests.append(result(f"{report_id}_user_decision_blank", bool(re.search(r"^- 用户裁决：\s*$", card_text, re.MULTILINE)), "blank"))
        tests.append(result(f"{report_id}_evidence_marker_count", card_text.count("[E]") >= rule["minimum_audits"], card_text.count("[E]")))
        tests.append(result(f"{report_id}_chart_routing_present", "图表依赖度" in card_text and "图表复核裁决" in card_text, True))

        page_headers, page_rows = read_csv(page_inventory)
        tests.append(result(f"{report_id}_page_header", page_headers == PAGE_COLUMNS, page_headers))
        actual_pages = sorted(int(row["page"]) for row in page_rows)
        tests.append(result(f"{report_id}_page_coverage", actual_pages == list(range(1, page_count + 1)), actual_pages))
        tests.append(result(f"{report_id}_page_report_fk", all(row["report_id"] == report_id for row in page_rows), True))
        tests.append(result(f"{report_id}_page_review_status", all(row["review_status"].strip() for row in page_rows), True))

        audit_headers, audit_rows = read_csv(evidence_audit)
        tests.append(result(f"{report_id}_audit_header", audit_headers == AUDIT_COLUMNS, audit_headers))
        tests.append(result(f"{report_id}_audit_minimum", len(audit_rows) >= rule["minimum_audits"], len(audit_rows)))
        checks = [
            "number_unit_direction_check",
            "cutoff_check",
            "instrument_check",
            "evidence_class_check",
            "chart_dependency_check",
        ]
        audit_pass = all(
            row["report_id"] == report_id
            and page_reference_valid(row["pdf_page"], page_count)
            and row["result"].lower() in {"pass", "pass_with_u"}
            and all(row[column].lower().startswith("pass") for column in checks)
            for row in audit_rows
        )
        tests.append(result(f"{report_id}_audit_all_pass", audit_pass, len(audit_rows)))

        source_pdf = ROOT / registry_row["relative_path"]
        source_ok = source_pdf.is_file() and sha256(source_pdf) == registry_row["sha256"]
        if os.name == "nt" and source_pdf.is_file():
            source_ok = source_ok and bool(source_pdf.stat().st_file_attributes & 0x1)
        tests.append(result(f"{report_id}_source_integrity_readonly", source_ok, registry_row["relative_path"]))

    allowed = GATE_A | set(GATE_B)
    unexpected_cards: list[str] = []
    for path in (ROOT / "02_report_cards" / "2026").glob("rpt_*_v*.md"):
        match = re.match(r"(rpt_[0-9a-f]{16})_v", path.name)
        if not match or match.group(1) not in allowed:
            unexpected_cards.append(str(path.relative_to(ROOT)))
    tests.append(result("remaining_nine_not_processed", not unexpected_cards, unexpected_cards))

    failed = [test for test in tests if test["status"] == "FAIL"]
    output = {
        "status": "PASS" if not failed else "FAIL",
        "summary": {"pass": len(tests) - len(failed), "fail": len(failed)},
        "tests": tests,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
