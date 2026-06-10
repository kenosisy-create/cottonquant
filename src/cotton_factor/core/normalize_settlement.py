"""Normalize CZCE settlement parameter raw snapshots into core facts."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path

from cotton_factor.common.exceptions import CoreNormalizationError
from cotton_factor.core.schemas import CoreSettlementParamDailyRow
from cotton_factor.raw import RawSnapshot, RawSnapshotStore

SOURCE_NAME = "CZCE_SETTLEMENT_PARAM"
DEFAULT_EXCHANGE = "CZCE"


@dataclass(frozen=True)
class SettlementNormalizationResult:
    """Normalized settlement parameter facts from one or more raw snapshots."""

    rows: list[CoreSettlementParamDailyRow]
    warnings: list[str]


def normalize_settlement_snapshots(
    *,
    snapshot_ids: Sequence[str],
    raw_root: Path | None = None,
    exchange: str = DEFAULT_EXCHANGE,
) -> SettlementNormalizationResult:
    """Replay raw settlement snapshots and normalize them into core rows."""
    if not snapshot_ids:
        return SettlementNormalizationResult(rows=[], warnings=[])

    store = RawSnapshotStore(raw_root)
    rows: list[CoreSettlementParamDailyRow] = []
    warnings: list[str] = []
    for snapshot_id in snapshot_ids:
        snapshot = store.replay(snapshot_id)
        result = normalize_settlement_snapshot(snapshot=snapshot, exchange=exchange)
        rows.extend(result.rows)
        warnings.extend(result.warnings)

    return SettlementNormalizationResult(
        rows=sorted(rows, key=lambda row: (row.trade_date, row.contract_code)),
        warnings=_unique_warnings(warnings),
    )


def normalize_settlement_snapshot(
    *,
    snapshot: RawSnapshot,
    exchange: str = DEFAULT_EXCHANGE,
) -> SettlementNormalizationResult:
    """Normalize one raw settlement snapshot into validated core settlement rows."""
    record = snapshot.record
    if record.source_name != SOURCE_NAME:
        raise CoreNormalizationError(f"unsupported settlement source: {record.source_name}")
    if record.content_type != "text/csv":
        raise CoreNormalizationError(
            f"{record.snapshot_id}: settlement normalizer supports text/csv only"
        )

    # 结算参数在 core 层解释为交易状态事实；raw 层仍然保持不可变原文。
    csv_rows = _read_csv_payload(snapshot.payload, snapshot_id=record.snapshot_id)
    rows = [
        CoreSettlementParamDailyRow(
            source_snapshot_id=record.snapshot_id,
            exchange=exchange.upper(),
            product_code=record.product_code.upper(),
            contract_code=_contract_code(csv_row, snapshot_id=record.snapshot_id),
            trade_date=_trade_date(csv_row=csv_row, snapshot=snapshot),
            limit_up=_optional_float(csv_row, "limit_up"),
            limit_down=_optional_float(csv_row, "limit_down"),
            margin_rate_long=_margin_rate(csv_row, "margin_rate_long"),
            margin_rate_short=_margin_rate(csv_row, "margin_rate_short"),
            trading_status=csv_row.get("trading_status") or "unknown",
            settlement_status=csv_row.get("settlement_status") or "official",
        )
        for csv_row in csv_rows
    ]
    return SettlementNormalizationResult(rows=rows, warnings=[])


def _read_csv_payload(payload: bytes, *, snapshot_id: str) -> list[dict[str, str]]:
    reader = csv.DictReader(StringIO(payload.decode("utf-8-sig")))
    if reader.fieldnames is None:
        raise CoreNormalizationError(f"{snapshot_id}: settlement CSV has no header")
    normalized_fields = {_normalize_key(field_name) for field_name in reader.fieldnames}
    if "contract" not in normalized_fields and "contract_code" not in normalized_fields:
        raise CoreNormalizationError(f"{snapshot_id}: settlement CSV missing contract column")

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
        raise CoreNormalizationError(f"{snapshot_id}: settlement row missing contract code")
    return value.upper()


def _trade_date(*, csv_row: dict[str, str], snapshot: RawSnapshot) -> date:
    raw_value = csv_row.get("trade_date") or csv_row.get("date") or snapshot.record.biz_date
    if not raw_value:
        raise CoreNormalizationError(
            f"{snapshot.record.snapshot_id}: settlement row missing trade_date"
        )
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise CoreNormalizationError(
            f"{snapshot.record.snapshot_id}: invalid settlement trade_date {raw_value!r}"
        ) from exc


def _optional_float(row: dict[str, str], field_name: str) -> float | None:
    value = row.get(field_name)
    if value in {None, ""}:
        return None
    return float(value.replace(",", ""))


def _margin_rate(row: dict[str, str], field_name: str) -> float | None:
    return _optional_float(row, field_name) or _optional_float(row, "margin_rate")


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _unique_warnings(warnings: Sequence[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values
