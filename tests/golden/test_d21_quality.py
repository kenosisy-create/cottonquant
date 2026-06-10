from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cotton_factor.common.hashing import sha256_file
from cotton_factor.core import normalize_quote_snapshots
from cotton_factor.ingest.czce_history import ingest_czce_history
from cotton_factor.qa import stable_smoke_fingerprint
from cotton_factor.smoke import run_cf_smoke, run_product_config_smoke

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PATH = REPO_ROOT / "tests" / "golden" / "fixtures" / "d21_quality_expected.json"


def test_d21_fixture_hashes_match_golden() -> None:
    expected = _expected()

    for relative_path, expected_hash in expected["fixture_sha256"].items():
        assert sha256_file(REPO_ROOT / relative_path) == expected_hash


def test_d21_normalized_quote_edges_match_golden(tmp_path: Path) -> None:
    expected = _expected()
    history_result = ingest_czce_history(
        year=2024,
        product_code="CF",
        file_type="csv",
        fixture_path=REPO_ROOT / "tests" / "fixtures" / "czce_history_full_chain_2024",
        raw_root=tmp_path / "raw",
    )

    result = normalize_quote_snapshots(
        snapshot_ids=[snapshot.snapshot_id for snapshot in history_result.snapshots],
        raw_root=tmp_path / "raw",
    )
    edges = [result.rows[0], result.rows[-1]]

    assert [
        {
            "contract_code": row.contract_code,
            "trade_date": row.trade_date.isoformat(),
            "settle": row.settle,
            "open_interest": row.open_interest,
        }
        for row in edges
    ] == expected["normalized_quote_edges"]


def test_d21_cf_smoke_is_reproducible_for_stable_outputs(tmp_path: Path) -> None:
    expected = _expected()
    first = run_cf_smoke(
        start=date(2024, 1, 2),
        end=date(2024, 2, 5),
        run_id="d21_repro_a",
        raw_root=tmp_path / "raw_a",
        archive_root=tmp_path / "archive_a",
    )
    second = run_cf_smoke(
        start=date(2024, 1, 2),
        end=date(2024, 2, 5),
        run_id="d21_repro_b",
        raw_root=tmp_path / "raw_b",
        archive_root=tmp_path / "archive_b",
    )

    first_fingerprint = stable_smoke_fingerprint(first.to_summary())
    second_fingerprint = stable_smoke_fingerprint(second.to_summary())

    assert first_fingerprint == second_fingerprint
    for key, expected_count in expected["cf_smoke_row_counts"].items():
        assert first_fingerprint["row_counts"][key] == expected_count


def test_d21_product_config_smoke_matches_golden_contracts() -> None:
    expected = _expected()
    result = run_product_config_smoke(product_codes=("SR", "AP"), year=2024)

    contracts_by_product = {
        item.product_code: item.contract_codes for item in result.products
    }
    assert contracts_by_product == expected["product_contracts"]


def _expected() -> dict[str, object]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
