"""CZCE historical quote raw backfill.

D3 stores historical quote files as immutable raw snapshots. It does not parse
or normalize exchange business fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cotton_factor.common.exceptions import FetchError
from cotton_factor.common.time import utc_now
from cotton_factor.ingest.base import FetchResult, infer_content_type
from cotton_factor.raw import RawSnapshotRecord, RawSnapshotStore

SOURCE_NAME = "CZCE_HISTORY_QUOTE"
PARSER_VERSION = "czce_history_quote.raw.v1"
SUPPORTED_FILE_TYPES = {"csv", "html", "htm", "xls", "xlsx"}


@dataclass(frozen=True)
class CzceHistoryIngestResult:
    """Result of storing one or more CZCE historical quote raw payloads."""

    snapshots: list[RawSnapshotRecord]


class CzceHistoryFetcher:
    """Fixture-safe fetcher for CZCE historical quote raw files."""

    def fetch_fixtures(self, *, fixture_path: Path, file_type: str | None) -> list[FetchResult]:
        """Read historical quote fixture file(s) without normalizing business fields."""
        paths = _resolve_fixture_paths(fixture_path=fixture_path, file_type=file_type)
        results: list[FetchResult] = []

        for path in paths:
            results.append(
                FetchResult(
                    payload=path.read_bytes(),
                    content_type=infer_content_type(path),
                    source_name=SOURCE_NAME,
                    metadata={
                        "fetcher": "CzceHistoryFetcher",
                        "fetch_mode": "fixture",
                        "fixture_path": str(path.resolve()),
                        "fixture_name": path.name,
                        "normalizes_business_fields": False,
                    },
                )
            )
        return results


def ingest_czce_history(
    *,
    year: int,
    product_code: str,
    file_type: str | None = None,
    fixture_path: Path | None = None,
    raw_root: Path | None = None,
    allow_network: bool = False,
    fetcher: CzceHistoryFetcher | None = None,
) -> CzceHistoryIngestResult:
    """Fetch and store CZCE historical quote files as raw snapshots."""
    _validate_year(year)
    normalized_file_type = _normalize_file_type(file_type) if file_type else None

    if fixture_path is None:
        if not allow_network:
            raise FetchError("CZCE history network fetch is disabled; provide --fixture")
        raise FetchError(
            "CZCE history live endpoint is TODO_REQUIRES_HUMAN_REVIEW; use fixture mode"
        )

    store = RawSnapshotStore(raw_root)
    history_fetcher = fetcher or CzceHistoryFetcher()
    fetch_started_at = utc_now()
    results = history_fetcher.fetch_fixtures(
        fixture_path=fixture_path,
        file_type=normalized_file_type,
    )
    fetch_finished_at = utc_now()

    snapshots: list[RawSnapshotRecord] = []
    for index, result in enumerate(results, start=1):
        metadata = {
            **result.metadata,
            "year": year,
            "history_year": year,
            "product_code": product_code,
            "file_type": normalized_file_type or _file_type_from_content(result),
            "file_index": index,
            "file_count": len(results),
            "fetch_started_at_utc": fetch_started_at.isoformat(),
            "fetch_finished_at_utc": fetch_finished_at.isoformat(),
            "source_layer": "raw_snapshot",
        }
        snapshots.append(
            store.write_snapshot(
                payload=result.payload,
                source_name=result.source_name,
                product_code=product_code,
                content_type=result.content_type,
                biz_date=None,
                metadata=metadata,
                parser_version=PARSER_VERSION,
                captured_at_utc=fetch_finished_at,
            )
        )

    return CzceHistoryIngestResult(snapshots=snapshots)


def _resolve_fixture_paths(*, fixture_path: Path, file_type: str | None) -> list[Path]:
    resolved = fixture_path.resolve()
    if not resolved.exists():
        raise FetchError(f"fixture not found: {fixture_path}")

    if resolved.is_file():
        if file_type is not None and _normalize_file_type(resolved.suffix.lstrip(".")) != file_type:
            raise FetchError(
                f"fixture file type does not match --file-type {file_type}: {fixture_path}"
            )
        return [resolved]

    if not resolved.is_dir():
        raise FetchError(f"fixture path is not a file or directory: {fixture_path}")

    if file_type is None:
        patterns = [f"*.{suffix}" for suffix in SUPPORTED_FILE_TYPES]
    else:
        patterns = [f"*.{file_type}"]

    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(path for path in resolved.glob(pattern) if path.is_file())
    unique_paths = sorted(set(paths))
    if not unique_paths:
        suffix_text = file_type or "supported"
        raise FetchError(f"no {suffix_text} fixture files found under: {fixture_path}")
    return unique_paths


def _normalize_file_type(value: str) -> str:
    suffix = value.lower().lstrip(".")
    if suffix not in SUPPORTED_FILE_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_FILE_TYPES))
        raise FetchError(
            f"unsupported CZCE history file_type {value!r}; expected one of: {allowed}"
        )
    return suffix


def _validate_year(year: int) -> None:
    if year < 1990 or year > 2100:
        raise FetchError(f"year out of supported range: {year}")


def _file_type_from_content(result: FetchResult) -> str:
    content_type = result.content_type
    if content_type == "text/csv":
        return "csv"
    if content_type == "text/html":
        return "html"
    if content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return "xlsx"
    if content_type == "application/vnd.ms-excel":
        return "xls"
    return "unknown"
