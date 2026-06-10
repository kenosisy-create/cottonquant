"""Base interfaces for raw data fetchers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

JsonScalar = str | int | float | bool | None
FetchMetadata = dict[str, JsonScalar]


@dataclass(frozen=True)
class FetchRequest:
    """A raw fetch request before any business normalization."""

    source_name: str
    product_code: str
    biz_date: date | None = None
    fixture_path: Path | None = None
    allow_network: bool = False
    max_retries: int = 0


@dataclass(frozen=True)
class FetchResult:
    """Fetched raw payload and metadata owned by ingestion."""

    payload: bytes
    content_type: str
    source_name: str
    metadata: FetchMetadata


class Fetcher(Protocol):
    """Protocol for fixture-safe raw fetchers."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch a raw payload without normalizing business fields."""


def infer_content_type(path: Path) -> str:
    """Infer a conservative content type from a raw payload path."""
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".xls":
        return "application/vnd.ms-excel"
    return "application/octet-stream"
