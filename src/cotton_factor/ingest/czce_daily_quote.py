"""CZCE daily quote raw ingestion.

D2 intentionally captures only the exchange payload as a raw snapshot. Business
field parsing and normalization belong to D5+ core fact tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cotton_factor.common.exceptions import FetchError
from cotton_factor.common.time import utc_now
from cotton_factor.ingest.base import FetchRequest, FetchResult, infer_content_type
from cotton_factor.raw import RawSnapshotRecord, RawSnapshotStore

SOURCE_NAME = "CZCE_DAILY_QUOTE"
PARSER_VERSION = "czce_daily_quote.raw.v1"


@dataclass(frozen=True)
class CzceDailyQuoteIngestResult:
    """Result of storing one CZCE daily quote raw payload."""

    snapshot: RawSnapshotRecord


class CzceDailyQuoteFetcher:
    """Fixture-safe fetcher for CZCE daily quote raw payloads."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch a raw payload without normalizing business fields."""
        if request.source_name != SOURCE_NAME:
            raise FetchError(f"unsupported source for CZCE daily quote: {request.source_name}")
        if request.fixture_path is not None:
            return self._fetch_fixture(request)
        if not request.allow_network:
            raise FetchError("CZCE daily quote network fetch is disabled; provide --fixture")

        raise FetchError(
            "CZCE daily quote live endpoint is TODO_REQUIRES_HUMAN_REVIEW; use fixture mode"
        )

    def _fetch_fixture(self, request: FetchRequest) -> FetchResult:
        fixture_path = request.fixture_path
        if fixture_path is None:
            raise FetchError("fixture_path is required for fixture fetch")

        resolved_fixture_path = fixture_path.resolve()
        if not resolved_fixture_path.exists() or not resolved_fixture_path.is_file():
            raise FetchError(f"fixture not found: {fixture_path}")

        payload = resolved_fixture_path.read_bytes()
        return FetchResult(
            payload=payload,
            content_type=infer_content_type(resolved_fixture_path),
            source_name=SOURCE_NAME,
            metadata={
                "fetcher": "CzceDailyQuoteFetcher",
                "fetch_mode": "fixture",
                "fixture_path": str(resolved_fixture_path),
                "retry_attempts": 0,
                "normalizes_business_fields": False,
            },
        )


def ingest_czce_daily_quote(
    *,
    trade_date: date,
    product_code: str,
    fixture_path: Path | None = None,
    raw_root: Path | None = None,
    allow_network: bool = False,
    max_retries: int = 0,
    fetcher: CzceDailyQuoteFetcher | None = None,
) -> CzceDailyQuoteIngestResult:
    """Fetch and store one CZCE daily quote raw payload.

    The returned snapshot is raw-only. It must not be treated as a normalized
    core fact table.
    """
    store = RawSnapshotStore(raw_root)
    quote_fetcher = fetcher or CzceDailyQuoteFetcher()

    fetch_started_at = utc_now()
    result = _fetch_with_retries(
        fetcher=quote_fetcher,
        request=FetchRequest(
            source_name=SOURCE_NAME,
            product_code=product_code,
            biz_date=trade_date,
            fixture_path=fixture_path,
            allow_network=allow_network,
            max_retries=max_retries,
        ),
    )
    fetch_finished_at = utc_now()

    metadata = {
        **result.metadata,
        "trade_date": trade_date.isoformat(),
        "product_code": product_code,
        "fetch_started_at_utc": fetch_started_at.isoformat(),
        "fetch_finished_at_utc": fetch_finished_at.isoformat(),
        "source_layer": "raw_snapshot",
    }
    snapshot = store.write_snapshot(
        payload=result.payload,
        source_name=result.source_name,
        product_code=product_code,
        biz_date=trade_date,
        content_type=result.content_type,
        metadata=metadata,
        parser_version=PARSER_VERSION,
        captured_at_utc=fetch_finished_at,
    )
    return CzceDailyQuoteIngestResult(snapshot=snapshot)


def _fetch_with_retries(*, fetcher: CzceDailyQuoteFetcher, request: FetchRequest) -> FetchResult:
    attempts_allowed = max(0, request.max_retries) + 1
    last_error: FetchError | None = None

    for attempt in range(1, attempts_allowed + 1):
        try:
            result = fetcher.fetch(request)
            result.metadata["attempt_count"] = attempt
            return result
        except FetchError as exc:
            last_error = exc
            if attempt == attempts_allowed:
                break

    if last_error is None:
        raise FetchError("fetch failed without an error")
    raise last_error
