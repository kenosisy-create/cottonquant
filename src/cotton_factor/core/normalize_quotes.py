"""Normalize CZCE quote raw snapshots into core quote facts."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path

from cotton_factor.common.exceptions import CoreNormalizationError
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.raw import RawSnapshot, RawSnapshotStore

SUPPORTED_QUOTE_SOURCES = {"CZCE_DAILY_QUOTE", "CZCE_HISTORY_QUOTE"}
DEFAULT_EXCHANGE = "CZCE"


@dataclass(frozen=True)
class QuoteNormalizationResult:
    """Normalized quote facts from one or more raw snapshots."""

    rows: list[CoreQuoteDailyRow]
    warnings: list[str]


def normalize_quote_snapshots(
    *,
    snapshot_ids: Sequence[str],
    raw_root: Path | None = None,
    exchange: str = DEFAULT_EXCHANGE,
) -> QuoteNormalizationResult:
    """Replay raw quote snapshots and normalize them into core quote rows."""
    if not snapshot_ids:
        raise CoreNormalizationError("quote normalization requires at least one snapshot_id")

    store = RawSnapshotStore(raw_root)
    rows: list[CoreQuoteDailyRow] = []
    warnings: list[str] = []
    for snapshot_id in snapshot_ids:
        snapshot = store.replay(snapshot_id)
        result = normalize_quote_snapshot(snapshot=snapshot, exchange=exchange)
        rows.extend(result.rows)
        warnings.extend(result.warnings)

    return QuoteNormalizationResult(
        rows=sorted(rows, key=lambda row: (row.trade_date, row.contract_code)),
        warnings=_unique_warnings(warnings),
    )


def normalize_quote_snapshot(
    *,
    snapshot: RawSnapshot,
    exchange: str = DEFAULT_EXCHANGE,
) -> QuoteNormalizationResult:
    """Normalize one raw quote snapshot into validated core quote rows."""
    record = snapshot.record
    if record.source_name not in SUPPORTED_QUOTE_SOURCES:
        raise CoreNormalizationError(f"unsupported quote source: {record.source_name}")
    if record.content_type != "text/csv":
        raise CoreNormalizationError(
            f"{record.snapshot_id}: quote normalizer currently supports text/csv only"
        )

    # 这里是 raw -> core 的唯一解析边界；后续 research/factor 只能读取这些 schema 行。
    csv_rows = _read_csv_payload(snapshot.payload, snapshot_id=record.snapshot_id)
    rows = [
        CoreQuoteDailyRow(
            source_snapshot_id=record.snapshot_id,
            exchange=exchange.upper(),
            product_code=record.product_code.upper(),
            contract_code=_contract_code(csv_row, snapshot_id=record.snapshot_id),
            trade_date=_trade_date(csv_row=csv_row, snapshot=snapshot),
            open=_optional_float(csv_row, "open"),
            high=_optional_float(csv_row, "high"),
            low=_optional_float(csv_row, "low"),
            close=_optional_float(csv_row, "close"),
            settle=_optional_float(csv_row, "settle"),
            pre_settle=_optional_float(csv_row, "pre_settle"),
            volume=_optional_int(csv_row, "volume"),
            open_interest=_optional_int(csv_row, "open_interest"),
            turnover=_optional_float(csv_row, "turnover"),
            quote_status=csv_row.get("quote_status") or "normal",
        )
        for csv_row in csv_rows
    ]
    if not rows:
        raise CoreNormalizationError(f"{record.snapshot_id}: quote snapshot produced no rows")
    return QuoteNormalizationResult(rows=rows, warnings=[])


def _read_csv_payload(payload: bytes, *, snapshot_id: str) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise CoreNormalizationError(f"{snapshot_id}: quote CSV has no header")
    normalized_fields = {_normalize_key(field_name) for field_name in reader.fieldnames}
    if "contract" not in normalized_fields and "contract_code" not in normalized_fields:
        raise CoreNormalizationError(f"{snapshot_id}: quote CSV missing contract column")

    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {
            _normalize_key(key): (value.strip() if isinstance(value, str) else "")
            for key, value in row.items()
            if key is not None
        }
        if any(value for value in normalized.values()):
            rows.append(normalized)
    return rows


def _contract_code(row: dict[str, str], *, snapshot_id: str) -> str:
    value = row.get("contract_code") or row.get("contract") or row.get("instrument_id")
    if not value:
        raise CoreNormalizationError(f"{snapshot_id}: quote row missing contract code")
    return value.upper()


def _trade_date(*, csv_row: dict[str, str], snapshot: RawSnapshot) -> date:
    raw_value = csv_row.get("trade_date") or csv_row.get("date") or snapshot.record.biz_date
    if not raw_value:
        raise CoreNormalizationError(
            f"{snapshot.record.snapshot_id}: quote row missing trade_date"
        )
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise CoreNormalizationError(
            f"{snapshot.record.snapshot_id}: invalid trade_date {raw_value!r}"
        ) from exc


def _optional_float(row: dict[str, str], field_name: str) -> float | None:
    value = row.get(field_name)
    if value in {None, ""}:
        return None
    return float(value.replace(",", ""))


def _optional_int(row: dict[str, str], field_name: str) -> int | None:
    value = row.get(field_name)
    if value in {None, ""}:
        return None
    return int(float(value.replace(",", "")))


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _unique_warnings(warnings: Sequence[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values
