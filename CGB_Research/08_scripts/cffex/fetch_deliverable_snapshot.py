#!/usr/bin/env python3
"""Capture and validate an immutable official CFFEX deliverable-bond snapshot.

This script only creates a dated snapshot. It never changes CURRENT.json, never
selects a main contract, and never promotes data into a production run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from validate_deliverable_snapshot import validate_snapshot
except ModuleNotFoundError:  # pragma: no cover - supports package-style execution
    from .validate_deliverable_snapshot import validate_snapshot


BASE_URL = "http://www.cffex.com.cn"
LANDING_URL = f"{BASE_URL}/kjggzxx/"
SCRIPT_URL = f"{BASE_URL}/r/cms/www/default/js/kjggzxx.js"
INDEX_URL = f"{BASE_URL}/sj/jgsj/jgqsj/index_6882.csv"
PRODUCTS = ("TS", "TF", "T", "TL")
USER_AGENT = "CGB-Research-Audit/0.1 (+immutable official-source snapshot)"
LONG_COLUMNS = (
    "snapshot_id",
    "product",
    "contract_code",
    "bond_code",
    "exchange_code_sse",
    "exchange_code_szse",
    "bond_full_name",
    "maturity_date",
    "coupon_rate_pct",
    "conversion_factor",
    "valid_from",
    "observed_on",
    "source_snapshot_id",
    "source_url",
)


def path_exists(path: Path) -> bool:
    """Return True for files, directories, and broken symlinks."""

    return path.exists() or path.is_symlink()


def assert_targets_absent(paths: tuple[Path, ...]) -> None:
    existing = [str(path) for path in paths if path_exists(path)]
    if existing:
        raise FileExistsError(
            "Immutable snapshot target already exists; refusing overwrite: "
            + ", ".join(existing)
        )


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def promote_staged_snapshot(
    staged_raw: Path,
    staged_processed: Path,
    staged_manifest: Path,
    raw_dir: Path,
    processed_path: Path,
    manifest_path: Path,
) -> None:
    """Atomically rename validated artifacts, with manifest as commit marker.

    Each rename is atomic on the shared volume. The manifest is promoted last,
    so manifest-driven readers never discover an incomplete snapshot. Any
    handled promotion failure rolls back every artifact already renamed.
    """

    final_paths = (raw_dir, processed_path, manifest_path)
    assert_targets_absent(final_paths)
    for parent in (raw_dir.parent, processed_path.parent, manifest_path.parent):
        parent.mkdir(parents=True, exist_ok=True)

    promoted: list[Path] = []
    try:
        for staged, final in (
            (staged_raw, raw_dir),
            (staged_processed, processed_path),
            (staged_manifest, manifest_path),
        ):
            if path_exists(final):
                raise FileExistsError(
                    f"Immutable snapshot target appeared during promotion: {final}"
                )
            os.rename(staged, final)
            promoted.append(final)
    except BaseException as exc:
        rollback_errors: list[str] = []
        for final in reversed(promoted):
            try:
                remove_path(final)
            except Exception as rollback_exc:  # pragma: no cover - rare filesystem failure
                rollback_errors.append(f"{final}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                f"Promotion failed ({exc}); rollback also failed: {rollback_errors}"
            ) from exc
        raise


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 30) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        if not body:
            raise RuntimeError(f"Empty response: {url}")
        return body, headers


def decode_cffex_csv(data: bytes) -> tuple[str, str]:
    for encoding in ("gb18030", "utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("cffex", data, 0, 1, "No supported encoding")


def clean_rows(text: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text))
        if row and any(cell.strip() for cell in row)
    ]


def normalize_date(value: str) -> str:
    parsed = datetime.strptime(value, "%Y%m%d").date()
    return parsed.isoformat()


def parse_index(data: bytes) -> tuple[list[dict[str, str]], str]:
    text, encoding = decode_cffex_csv(data)
    rows = clean_rows(text)
    parsed: list[dict[str, str]] = []
    for line_no, row in enumerate(rows, start=1):
        if len(row) != 9:
            raise ValueError(f"index row {line_no}: expected 9 fields, got {len(row)}")
        full_name, bank_code, sse_code, szse_code, maturity, coupon, factor, contract, product = row
        if product not in PRODUCTS:
            raise ValueError(f"index row {line_no}: unexpected product {product!r}")
        if not re.fullmatch(rf"{product}\d{{4}}", contract):
            raise ValueError(f"index row {line_no}: invalid contract {contract!r}")
        try:
            Decimal(coupon)
            Decimal(factor)
        except InvalidOperation as exc:
            raise ValueError(f"index row {line_no}: invalid decimal") from exc
        parsed.append(
            {
                "bond_full_name": full_name,
                "bond_code": bank_code,
                "exchange_code_sse": sse_code,
                "exchange_code_szse": szse_code,
                "maturity_date": normalize_date(maturity),
                "coupon_rate_pct": coupon,
                "conversion_factor": factor,
                "contract_code": contract,
                "product": product,
            }
        )
    return parsed, encoding


def parse_contract_csv(data: bytes, contract: str, product: str) -> tuple[list[dict[str, str]], str]:
    text, encoding = decode_cffex_csv(data)
    rows = clean_rows(text)
    if len(rows) < 2:
        raise ValueError(f"{contract}: contract CSV has no data rows")
    data_rows = rows[1:]
    parsed: list[dict[str, str]] = []
    for line_no, row in enumerate(data_rows, start=2):
        if len(row) != 7:
            raise ValueError(f"{contract} row {line_no}: expected 7 fields, got {len(row)}")
        full_name, bank_code, sse_code, szse_code, maturity, coupon, factor = row
        parsed.append(
            {
                "bond_full_name": full_name,
                "bond_code": bank_code,
                "exchange_code_sse": sse_code,
                "exchange_code_szse": szse_code,
                "maturity_date": normalize_date(maturity),
                "coupon_rate_pct": coupon,
                "conversion_factor": factor,
                "contract_code": contract,
                "product": product,
            }
        )
    return parsed, encoding


def canonical_row(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        row[key]
        for key in (
            "product",
            "contract_code",
            "bond_code",
            "exchange_code_sse",
            "exchange_code_szse",
            "bond_full_name",
            "maturity_date",
            "coupon_rate_pct",
            "conversion_factor",
        )
    )


def csv_bytes(rows: list[dict[str, str]], snapshot_id: str, observed_on: str) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=LONG_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for row in sorted(rows, key=lambda item: (item["product"], item["contract_code"], item["bond_code"])):
        contract = row["contract_code"]
        writer.writerow(
            {
                "snapshot_id": snapshot_id,
                **row,
                "valid_from": "",
                "observed_on": observed_on,
                "source_snapshot_id": snapshot_id,
                "source_url": f"{BASE_URL}/sj/jgsj/jgqsj/{contract}/{contract}.csv",
            }
        )
    return stream.getvalue().encode("utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-date", required=True, help="Observation date in YYYY-MM-DD")
    parser.add_argument("--snapshot-id", help="Immutable snapshot identifier")
    parser.add_argument("--project-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observed_on = date.fromisoformat(args.snapshot_date).isoformat()
    actual_retrieval_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if observed_on != actual_retrieval_date:
        raise ValueError(
            "snapshot_date must equal the actual Asia/Shanghai retrieval date; "
            "historical reconstruction belongs in the event-sourced backfill pipeline"
        )
    project_root = (args.project_root or Path(__file__).resolve().parents[2]).resolve()
    snapshot_id = args.snapshot_id or f"cffex_{observed_on.replace('-', '')}_official_01"
    if not re.fullmatch(r"[a-z0-9_]+", snapshot_id):
        raise ValueError("snapshot_id may contain only lowercase letters, digits, and underscores")

    raw_dir = project_root / "05_data" / "raw" / "cffex" / observed_on / snapshot_id
    processed_path = (
        project_root
        / "05_data"
        / "processed"
        / "cffex"
        / observed_on
        / f"deliverable_bonds_{snapshot_id}.csv"
    )
    manifest_path = (
        project_root
        / "05_data"
        / "snapshots"
        / "cffex"
        / observed_on
        / f"{snapshot_id}.manifest.json"
    )
    final_paths = (raw_dir, processed_path, manifest_path)
    assert_targets_absent(final_paths)

    # All staged artifacts live below the common 05_data parent, guaranteeing
    # same-volume atomic renames into raw/processed/snapshots.
    staging_parent = project_root / "05_data" / ".cffex_staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    lock_path = staging_parent / f"{snapshot_id}.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"Snapshot transaction is already running: {snapshot_id}") from exc
    try:
        os.write(
            lock_fd,
            (
                json.dumps(
                    {
                        "snapshot_id": snapshot_id,
                        "pid": os.getpid(),
                        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
                + "\n"
            ).encode("utf-8"),
        )
    finally:
        os.close(lock_fd)

    staging_root = staging_parent / f"{snapshot_id}.{uuid.uuid4().hex}.staging"
    staged_raw = staging_root / "raw"
    staged_processed = staging_root / "processed" / processed_path.name
    staged_manifest = staging_root / "manifest" / manifest_path.name
    validation_result: dict[str, object] = {}
    try:
        staging_root.mkdir(parents=False, exist_ok=False)

        landing, landing_headers = fetch(LANDING_URL)
        script, script_headers = fetch(SCRIPT_URL)
        index_data, index_headers = fetch(INDEX_URL)
        index_rows, index_encoding = parse_index(index_data)
        contracts_by_product: dict[str, set[str]] = defaultdict(set)
        for row in index_rows:
            contracts_by_product[row["product"]].add(row["contract_code"])
        if set(contracts_by_product) != set(PRODUCTS):
            raise ValueError(f"Missing products: {set(PRODUCTS) - set(contracts_by_product)}")
        if any(len(contracts_by_product[product]) != 3 for product in PRODUCTS):
            raise ValueError(f"Expected three listed contracts per product: {contracts_by_product}")

        raw_objects: dict[str, tuple[str, bytes, dict[str, str], str | None]] = {
            "landing.html": (LANDING_URL, landing, landing_headers, "utf-8"),
            "kjggzxx.js": (SCRIPT_URL, script, script_headers, "utf-8"),
            "index_6882.csv": (INDEX_URL, index_data, index_headers, index_encoding),
        }
        union_rows: list[dict[str, str]] = []
        contract_counts: dict[str, int] = {}
        contract_encodings: dict[str, str] = {}
        for product in PRODUCTS:
            for contract in sorted(contracts_by_product[product]):
                csv_url = f"{BASE_URL}/sj/jgsj/jgqsj/{contract}/{contract}.csv"
                xml_url = f"{BASE_URL}/sj/jgsj/jgqsj/{contract}/index_1.xml"
                contract_csv, csv_headers = fetch(csv_url)
                contract_xml, xml_headers = fetch(xml_url)
                rows, encoding = parse_contract_csv(contract_csv, contract, product)
                union_rows.extend(rows)
                contract_counts[contract] = len(rows)
                contract_encodings[contract] = encoding
                raw_objects[f"contracts/{contract}/{contract}.csv"] = (
                    csv_url,
                    contract_csv,
                    csv_headers,
                    encoding,
                )
                raw_objects[f"contracts/{contract}/index_1.xml"] = (
                    xml_url,
                    contract_xml,
                    xml_headers,
                    xml_headers.get("content-type"),
                )

        index_counter = Counter(canonical_row(row) for row in index_rows)
        contract_counter = Counter(canonical_row(row) for row in union_rows)
        if index_counter != contract_counter:
            missing = list((index_counter - contract_counter).elements())[:5]
            extra = list((contract_counter - index_counter).elements())[:5]
            raise ValueError(f"Index/per-contract mismatch; missing={missing}, extra={extra}")
        if any(count != 1 for count in index_counter.values()):
            raise ValueError("Unexpected duplicate product+contract+bond rows")

        normalized = csv_bytes(index_rows, snapshot_id, observed_on)
        retrieved_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        raw_manifest = []
        for relative_path, (url, body, headers, encoding) in sorted(raw_objects.items()):
            raw_manifest.append(
                {
                    "relative_path": relative_path,
                    "source_url": url,
                    "sha256": sha256_bytes(body),
                    "bytes": len(body),
                    "encoding_or_content_type": encoding,
                    "etag": headers.get("etag", ""),
                    "last_modified": headers.get("last-modified", ""),
                }
            )

        manifest = {
            "snapshot_id": snapshot_id,
            "snapshot_date": observed_on,
            "retrieved_at": retrieved_at,
            "source_authority": "China Financial Futures Exchange (CFFEX)",
            "source_landing_url": LANDING_URL,
            "source_index_url": INDEX_URL,
            "source_javascript_url": SCRIPT_URL,
            "raw_objects": raw_manifest,
            "normalized_relative_path": processed_path.relative_to(project_root).as_posix(),
            "normalized_sha256": sha256_bytes(normalized),
            "normalized_encoding": "utf-8-sig",
            "normalized_columns": list(LONG_COLUMNS),
            "row_count": len(index_rows),
            "contract_count": len(contract_counts),
            "product_contracts": {
                product: sorted(contracts_by_product[product]) for product in PRODUCTS
            },
            "contract_row_counts": dict(sorted(contract_counts.items())),
            "source_encodings": {
                "index": index_encoding,
                "contracts": dict(sorted(contract_encodings.items())),
            },
            "validation": {
                "all_four_products_present": True,
                "three_listed_contracts_per_product": True,
                "index_equals_union_of_contract_csv": True,
                "primary_key_unique": True,
                "current_cross_section_complete": True,
                "point_in_time_history_complete": False,
            },
            "promotion_enabled": False,
            "limitations": [
                "valid_from is intentionally blank until CFFEX release/addition notices are event-sourced.",
                "This snapshot does not select active/main contracts and does not modify CURRENT.json.",
            ],
            "tool": "08_scripts/cffex/fetch_deliverable_snapshot.py",
            "tool_version": "0.2.1",
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )

        for relative_path, (_, body, _, _) in raw_objects.items():
            target = staged_raw / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        staged_processed.parent.mkdir(parents=True, exist_ok=True)
        staged_processed.write_bytes(normalized)
        staged_manifest.parent.mkdir(parents=True, exist_ok=True)
        staged_manifest.write_bytes(manifest_bytes)

        validation_result = validate_snapshot(
            staged_manifest,
            project_root=project_root,
            raw_root_override=staged_raw,
            normalized_path_override=staged_processed,
        )
        if validation_result["status"] != "PASS":
            raise RuntimeError(
                "Staged snapshot failed independent self-validation: "
                + json.dumps(validation_result, ensure_ascii=False)
            )

        # Recheck under the per-snapshot lock immediately before promotion.
        assert_targets_absent(final_paths)
        promote_staged_snapshot(
            staged_raw,
            staged_processed,
            staged_manifest,
            raw_dir,
            processed_path,
            manifest_path,
        )
    finally:
        if path_exists(staging_root):
            shutil.rmtree(staging_root)
        lock_path.unlink(missing_ok=True)

    print(
        json.dumps(
            {
                "status": "PASS",
                "snapshot_id": snapshot_id,
                "rows": len(index_rows),
                "contracts": len(contract_counts),
                "products": list(PRODUCTS),
                "manifest": manifest_path.relative_to(project_root).as_posix(),
                "three_way_equal": validation_result.get("three_way_equal", False),
                "staging_self_validation": validation_result.get("status") == "PASS",
                "promotion_enabled": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
