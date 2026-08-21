#!/usr/bin/env python3
"""Read-only semantic validator for an immutable CFFEX deliverable snapshot.

The validator does not trust the manifest's validation flags. It reparses the
official index, every per-contract CSV, and the processed long table, then
compares all three representations in both directions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PRODUCTS = ("TS", "TF", "T", "TL")
CONTRACT_HEADER = (
    "国债全称",
    "银行间国债代码",
    "上交所国债代码",
    "深交所国债代码",
    "到期日",
    "票面利率",
    "转换因子",
)
CANONICAL_FIELDS = (
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_cffex_csv(data: bytes) -> tuple[str, str]:
    for encoding in ("gb18030", "utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("cffex", data, 0, 1, "No supported encoding")


def clean_rows(path: Path) -> tuple[list[list[str]], str]:
    text, encoding = decode_cffex_csv(path.read_bytes())
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text))
        if row and any(cell.strip() for cell in row)
    ]
    return rows, encoding


def normalize_compact_date(value: str, context: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"{context}: invalid YYYYMMDD maturity {value!r}") from exc


def normalize_iso_date(value: str, context: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"{context}: invalid ISO maturity {value!r}") from exc


def checked_decimal(value: str, field: str, context: str, *, positive: bool = False) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{context}: invalid {field} {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"{context}: non-finite {field} {value!r}")
    if positive and parsed <= 0:
        raise ValueError(f"{context}: {field} must be positive, got {value!r}")
    return value


def make_record(
    fields: list[str],
    contract: str,
    product: str,
    context: str,
    *,
    maturity_is_iso: bool = False,
) -> dict[str, str]:
    if len(fields) != 7:
        raise ValueError(f"{context}: expected 7 fields, got {len(fields)}")
    full_name, bank_code, sse_code, szse_code, maturity, coupon, factor = fields
    if not full_name:
        raise ValueError(f"{context}: empty bond_full_name")
    if not bank_code:
        raise ValueError(f"{context}: empty interbank bond_code")
    normalized_maturity = (
        normalize_iso_date(maturity, context)
        if maturity_is_iso
        else normalize_compact_date(maturity, context)
    )
    checked_decimal(coupon, "coupon_rate_pct", context)
    checked_decimal(factor, "conversion_factor", context, positive=True)
    return {
        "bond_full_name": full_name,
        "bond_code": bank_code,
        "exchange_code_sse": sse_code,
        "exchange_code_szse": szse_code,
        "maturity_date": normalized_maturity,
        "coupon_rate_pct": coupon,
        "conversion_factor": factor,
        "contract_code": contract,
        "product": product,
    }


def canonical_row(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row[field] for field in CANONICAL_FIELDS)


def expected_contract_map(manifest: dict[str, Any], errors: list[str]) -> dict[str, str]:
    configured = manifest.get("product_contracts")
    if not isinstance(configured, dict):
        errors.append("manifest product_contracts must be an object")
        return {}
    extra_products = sorted(set(configured) - set(PRODUCTS))
    if extra_products:
        errors.append(f"unexpected products in manifest: {extra_products}")
    mapping: dict[str, str] = {}
    for product in PRODUCTS:
        contracts = configured.get(product)
        if not isinstance(contracts, list):
            errors.append(f"manifest product_contracts[{product}] must be a list")
            continue
        if len(contracts) != 3:
            errors.append(f"{product}: expected three contracts, got {len(contracts)}")
        for contract in contracts:
            if not isinstance(contract, str) or not re.fullmatch(rf"{product}\d{{4}}", contract):
                errors.append(f"{product}: invalid contract code {contract!r}")
                continue
            if contract in mapping:
                errors.append(f"duplicate contract in manifest: {contract}")
                continue
            mapping[contract] = product
    if len(mapping) != 12:
        errors.append(f"expected 12 unique contracts, got {len(mapping)}")
    return mapping


def parse_index(path: Path, contract_map: dict[str, str]) -> tuple[list[dict[str, str]], str]:
    rows, encoding = clean_rows(path)
    parsed: list[dict[str, str]] = []
    for line_no, row in enumerate(rows, start=1):
        if len(row) != 9:
            raise ValueError(f"index row {line_no}: expected 9 fields, got {len(row)}")
        full_name, bank_code, sse_code, szse_code, maturity, coupon, factor, contract, product = row
        expected_product = contract_map.get(contract)
        if product not in PRODUCTS:
            raise ValueError(f"index row {line_no}: unexpected product {product!r}")
        if not re.fullmatch(rf"{product}\d{{4}}", contract):
            raise ValueError(f"index row {line_no}: invalid contract {contract!r}")
        if expected_product != product:
            raise ValueError(
                f"index row {line_no}: {contract} maps to {product}, expected {expected_product}"
            )
        parsed.append(
            make_record(
                [full_name, bank_code, sse_code, szse_code, maturity, coupon, factor],
                contract,
                product,
                f"index row {line_no}",
            )
        )
    return parsed, encoding


def parse_contract(path: Path, contract: str, product: str) -> tuple[list[dict[str, str]], str]:
    rows, encoding = clean_rows(path)
    if not rows:
        raise ValueError(f"{contract}: empty contract CSV")
    if tuple(rows[0]) != CONTRACT_HEADER:
        raise ValueError(
            f"{contract}: unexpected 7-column header {rows[0]!r}; expected {list(CONTRACT_HEADER)!r}"
        )
    if len(rows) == 1:
        raise ValueError(f"{contract}: contract CSV has no data rows")
    parsed = [
        make_record(row, contract, product, f"{contract} row {line_no}")
        for line_no, row in enumerate(rows[1:], start=2)
    ]
    return parsed, encoding


def parse_processed(
    path: Path,
    manifest: dict[str, Any],
    contract_map: dict[str, str],
    errors: list[str],
) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected_columns = manifest.get("normalized_columns")
        if isinstance(expected_columns, list) and reader.fieldnames != expected_columns:
            errors.append(
                f"normalized columns mismatch: {reader.fieldnames!r} != {expected_columns!r}"
            )
        rows: list[dict[str, str]] = []
        for line_no, row in enumerate(reader, start=2):
            missing = [field for field in CANONICAL_FIELDS if field not in row]
            if missing:
                raise ValueError(f"normalized row {line_no}: missing columns {missing}")
            product = row["product"].strip()
            contract = row["contract_code"].strip()
            if contract_map.get(contract) != product:
                raise ValueError(
                    f"normalized row {line_no}: {contract} maps to {product}, "
                    f"expected {contract_map.get(contract)}"
                )
            record = make_record(
                [
                    row["bond_full_name"].strip(),
                    row["bond_code"].strip(),
                    row["exchange_code_sse"].strip(),
                    row["exchange_code_szse"].strip(),
                    row["maturity_date"].strip(),
                    row["coupon_rate_pct"].strip(),
                    row["conversion_factor"].strip(),
                ],
                contract,
                product,
                f"normalized row {line_no}",
                maturity_is_iso=True,
            )
            rows.append({**row, **record})
    return rows


def compare_counters(
    left_name: str,
    left: Counter[tuple[str, ...]],
    right_name: str,
    right: Counter[tuple[str, ...]],
    errors: list[str],
) -> None:
    if left == right:
        return
    left_only = list((left - right).elements())
    right_only = list((right - left).elements())
    errors.append(
        f"{left_name}/{right_name} mismatch: "
        f"{left_name}_only={len(left_only)} sample={left_only[:3]!r}; "
        f"{right_name}_only={len(right_only)} sample={right_only[:3]!r}"
    )


def safe_relative_path(value: str, context: str, errors: list[str]) -> Path | None:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{context}: unsafe relative path {value!r}")
        return None
    return relative


def validate_snapshot(
    manifest_path: Path,
    *,
    project_root: Path | None = None,
    raw_root_override: Path | None = None,
    normalized_path_override: Path | None = None,
) -> dict[str, Any]:
    """Validate a snapshot without modifying it.

    Overrides are used by the fetcher to validate a staged transaction before
    any artifact is promoted into its immutable final location.
    """

    manifest_path = manifest_path.resolve()
    project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot_id = manifest.get("snapshot_id", "")
    snapshot_date = manifest.get("snapshot_date", "")
    errors: list[str] = []

    contract_map = expected_contract_map(manifest, errors)
    raw_root = (
        raw_root_override.resolve()
        if raw_root_override is not None
        else project_root / "05_data" / "raw" / "cffex" / snapshot_date / snapshot_id
    )

    raw_items = manifest.get("raw_objects")
    if not isinstance(raw_items, list):
        errors.append("manifest raw_objects must be a list")
        raw_items = []
    declared_raw_paths: set[str] = set()
    for item_no, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            errors.append(f"raw object {item_no}: expected object")
            continue
        relative_value = item.get("relative_path")
        if not isinstance(relative_value, str):
            errors.append(f"raw object {item_no}: missing relative_path")
            continue
        if relative_value in declared_raw_paths:
            errors.append(f"duplicate raw relative_path: {relative_value}")
            continue
        declared_raw_paths.add(relative_value)
        relative = safe_relative_path(relative_value, f"raw object {item_no}", errors)
        if relative is None:
            continue
        path = raw_root / relative
        if not path.is_file():
            errors.append(f"missing raw object: {path}")
            continue
        if sha256_file(path) != item.get("sha256"):
            errors.append(f"raw hash mismatch: {path}")
        if path.stat().st_size != item.get("bytes"):
            errors.append(f"raw size mismatch: {path}")

    required_raw_paths = {"index_6882.csv"}
    required_raw_paths.update(
        f"contracts/{contract}/{contract}.csv" for contract in contract_map
    )
    missing_declarations = sorted(required_raw_paths - declared_raw_paths)
    if missing_declarations:
        errors.append(f"required raw CSVs absent from manifest: {missing_declarations}")

    normalized_relative_value = manifest.get("normalized_relative_path")
    normalized_path: Path | None
    if normalized_path_override is not None:
        normalized_path = normalized_path_override.resolve()
    elif isinstance(normalized_relative_value, str):
        relative = safe_relative_path(
            normalized_relative_value, "normalized_relative_path", errors
        )
        normalized_path = project_root / relative if relative is not None else None
    else:
        errors.append("manifest normalized_relative_path must be a string")
        normalized_path = None

    processed_rows: list[dict[str, str]] = []
    if normalized_path is None or not normalized_path.is_file():
        errors.append(f"missing normalized CSV: {normalized_path}")
    else:
        if sha256_file(normalized_path) != manifest.get("normalized_sha256"):
            errors.append("normalized hash mismatch")
        try:
            processed_rows = parse_processed(
                normalized_path, manifest, contract_map, errors
            )
        except Exception as exc:
            errors.append(f"normalized semantic parse failed: {exc}")

    index_rows: list[dict[str, str]] = []
    index_encoding = ""
    index_path = raw_root / "index_6882.csv"
    if index_path.is_file():
        try:
            index_rows, index_encoding = parse_index(index_path, contract_map)
        except Exception as exc:
            errors.append(f"index semantic parse failed: {exc}")
    elif "index_6882.csv" not in missing_declarations:
        errors.append(f"missing raw index: {index_path}")

    union_rows: list[dict[str, str]] = []
    contract_row_counts: dict[str, int] = {}
    contract_encodings: dict[str, str] = {}
    for contract, product in sorted(contract_map.items()):
        contract_path = raw_root / "contracts" / contract / f"{contract}.csv"
        if not contract_path.is_file():
            if f"contracts/{contract}/{contract}.csv" not in missing_declarations:
                errors.append(f"missing contract CSV: {contract_path}")
            continue
        try:
            rows, encoding = parse_contract(contract_path, contract, product)
        except Exception as exc:
            errors.append(f"contract semantic parse failed: {exc}")
            continue
        union_rows.extend(rows)
        contract_row_counts[contract] = len(rows)
        contract_encodings[contract] = encoding

    manifest_counts = manifest.get("contract_row_counts")
    if isinstance(manifest_counts, dict):
        normalized_manifest_counts = {
            str(key): int(value) for key, value in manifest_counts.items()
        }
        if contract_row_counts != normalized_manifest_counts:
            errors.append(
                f"contract row counts mismatch: {contract_row_counts} != "
                f"{normalized_manifest_counts}"
            )
    else:
        errors.append("manifest contract_row_counts must be an object")

    expected_row_count = manifest.get("row_count")
    for name, count in (
        ("index", len(index_rows)),
        ("contract union", len(union_rows)),
        ("processed", len(processed_rows)),
    ):
        if count != expected_row_count:
            errors.append(f"{name} row count mismatch: {count} != {expected_row_count}")

    index_counter = Counter(canonical_row(row) for row in index_rows)
    union_counter = Counter(canonical_row(row) for row in union_rows)
    processed_counter = Counter(canonical_row(row) for row in processed_rows)
    for name, counter in (
        ("index", index_counter),
        ("contract union", union_counter),
        ("processed", processed_counter),
    ):
        duplicates = sum(count - 1 for count in counter.values() if count > 1)
        if duplicates:
            errors.append(f"{name}: {duplicates} duplicate canonical rows")

    compare_counters("index", index_counter, "contract_union", union_counter, errors)
    compare_counters("index", index_counter, "processed", processed_counter, errors)
    compare_counters(
        "contract_union", union_counter, "processed", processed_counter, errors
    )

    keys = [
        (row["product"], row["contract_code"], row["bond_code"])
        for row in processed_rows
    ]
    if len(keys) != len(set(keys)):
        errors.append("duplicate product+contract+bond key")

    products: dict[str, set[str]] = defaultdict(set)
    for row in processed_rows:
        products[row["product"]].add(row["contract_code"])
    expected_products: dict[str, set[str]] = defaultdict(set)
    for contract, product in contract_map.items():
        expected_products[product].add(contract)
    if dict(products) != dict(expected_products):
        errors.append(
            f"product/contract mismatch: {dict(products)} != {dict(expected_products)}"
        )

    if any(row.get("valid_from") for row in processed_rows):
        errors.append("valid_from must remain blank until notice-event backfill")
    if any(row.get("observed_on") != snapshot_date for row in processed_rows):
        errors.append("observed_on mismatch")
    if any(row.get("snapshot_id") != snapshot_id for row in processed_rows):
        errors.append("normalized snapshot_id mismatch")
    if any(row.get("source_snapshot_id") != snapshot_id for row in processed_rows):
        errors.append("source_snapshot_id mismatch")
    if manifest.get("promotion_enabled") is not False:
        errors.append("promotion must remain disabled")

    three_way_equal = (
        bool(index_rows)
        and bool(union_rows)
        and bool(processed_rows)
        and index_counter == union_counter == processed_counter
    )
    return {
        "status": "FAIL" if errors else "PASS",
        "snapshot_id": snapshot_id,
        "raw_objects": len(raw_items),
        "rows": len(processed_rows),
        "index_rows": len(index_rows),
        "contract_union_rows": len(union_rows),
        "contracts": len(contract_row_counts),
        "three_way_equal": three_way_equal,
        "index_encoding": index_encoding,
        "contract_encodings": contract_encodings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = validate_snapshot(args.manifest)
    except Exception as exc:
        result = {
            "status": "FAIL",
            "snapshot_id": "",
            "raw_objects": 0,
            "rows": 0,
            "index_rows": 0,
            "contract_union_rows": 0,
            "contracts": 0,
            "three_way_equal": False,
            "errors": [f"validator exception: {exc}"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
