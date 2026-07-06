"""Research-mode core quote normalization for preserved CF raw files."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ConfigError, ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.simple_yaml import load_simple_yaml
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.research_workbench.raw_ingest import list_cf_raw_manifest

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
DEFAULT_SOURCE_CONFIG = project_root() / "configs" / "data_sources_cf_research.yaml"
CORE_QUOTE_FILE_NAME = "core_quote_daily.parquet"
REQUIRED_SOURCE_FIELDS = {
    "trade_date",
    "exchange",
    "product_code",
    "contract_id",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "open_interest",
}
OPTIONAL_SOURCE_FIELDS = {
    "pre_settle",
    "turnover",
    "quote_status",
}


@dataclass(frozen=True)
class ResearchCoreQuoteBuildResult:
    """Result of building research-mode core quote facts."""

    trade_date: date
    product_code: str
    output_path: Path
    row_count: int
    rows: list[CoreQuoteDailyRow]
    source_raw_runs: tuple[str, ...]
    source_files: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a compact JSON-serializable summary."""
        return {
            "trade_date": self.trade_date.isoformat(),
            "product_code": self.product_code,
            "output_path": str(self.output_path),
            "row_count": self.row_count,
            "source_raw_runs": list(self.source_raw_runs),
            "source_files": list(self.source_files),
            "warnings": list(self.warnings),
        }


def normalize_cf_core_quotes(
    *,
    trade_date: date,
    raw_output_dir: Path | None = None,
    core_output_dir: Path | None = None,
    output_path: Path | None = None,
    run_id: str | None = None,
    source_config_path: Path | None = None,
) -> ResearchCoreQuoteBuildResult:
    """Normalize preserved CF CSV raw files into the research core quote table."""
    source_config = _load_source_config(source_config_path or DEFAULT_SOURCE_CONFIG)
    raw_rows = _manifest_rows_for_run(
        trade_date=trade_date,
        raw_output_dir=raw_output_dir,
        run_id=run_id,
    )

    # R05 的边界：只能读取 R04 已保存的 raw 文件，不能直接读取 data/incoming。
    rows: list[CoreQuoteDailyRow] = []
    warnings: list[str] = []
    for manifest_row in raw_rows:
        raw_path = Path(str(manifest_row["raw_path"]))
        if raw_path.suffix.lower() != ".csv":
            warnings.append(f"skipped unsupported core quote format: {raw_path}")
            continue
        rows.extend(
            _read_core_quote_csv(
                raw_path=raw_path,
                trade_date=trade_date,
                manifest_row=manifest_row,
                source_config=source_config,
            )
        )

    if not rows:
        raise ResearchWorkbenchError(
            f"no CSV quote rows normalized for {PRODUCT_CODE} {trade_date.isoformat()}"
        )
    _validate_unique_primary_key(rows)

    target_path = output_path or _default_output_path(core_output_dir)
    _write_parquet_replace_keys(output_path=target_path, rows=rows)
    return ResearchCoreQuoteBuildResult(
        trade_date=trade_date,
        product_code=PRODUCT_CODE,
        output_path=target_path,
        row_count=len(rows),
        rows=rows,
        source_raw_runs=_unique_str(row["run_id"] for row in raw_rows),
        source_files=_unique_str(row["source_file_name"] for row in raw_rows),
        warnings=tuple(warnings),
    )


def _manifest_rows_for_run(
    *,
    trade_date: date,
    raw_output_dir: Path | None,
    run_id: str | None,
) -> list[dict[str, object]]:
    rows = list_cf_raw_manifest(raw_output_dir=raw_output_dir, trade_date=trade_date)
    if run_id is not None:
        rows = [row for row in rows if row.get("run_id") == run_id]
    if not rows:
        qualifier = f" run_id={run_id}" if run_id else ""
        raise ResearchWorkbenchError(
            f"no research raw manifest rows for {PRODUCT_CODE} {trade_date.isoformat()}{qualifier}"
        )
    return rows


def _load_source_config(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ConfigError(f"research CF source config not found: {path}")
    payload = load_simple_yaml(path)
    required_fields = payload.get("required_quote_fields")
    if not isinstance(required_fields, list):
        raise ConfigError(f"{path}: required_quote_fields must be a list")
    missing = sorted(REQUIRED_SOURCE_FIELDS - {str(item) for item in required_fields})
    if missing:
        raise ConfigError(f"{path}: missing required_quote_fields: {missing}")
    return payload


def _read_core_quote_csv(
    *,
    raw_path: Path,
    trade_date: date,
    manifest_row: dict[str, object],
    source_config: dict[str, object],
) -> list[CoreQuoteDailyRow]:
    if not raw_path.exists():
        raise ResearchWorkbenchError(f"raw file missing from manifest: {raw_path}")

    with raw_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ResearchWorkbenchError(f"CSV has no header: {raw_path}")
        column_map = _build_column_map(reader.fieldnames, source_config=source_config)
        missing = sorted(REQUIRED_SOURCE_FIELDS - set(column_map))
        if missing:
            raise ResearchWorkbenchError(f"{raw_path}: missing required columns: {missing}")

        rows: list[CoreQuoteDailyRow] = []
        for row_number, csv_row in enumerate(reader, start=2):
            normalized = {
                field: _cell(csv_row, source_column)
                for field, source_column in column_map.items()
            }
            if not any(normalized.values()):
                continue
            rows.append(
                _build_core_quote_row(
                    raw_path=raw_path,
                    row_number=row_number,
                    trade_date=trade_date,
                    normalized=normalized,
                    manifest_row=manifest_row,
                )
            )

    if not rows:
        raise ResearchWorkbenchError(f"{raw_path}: CSV produced no quote rows")
    return rows


def _build_column_map(
    fieldnames: list[str],
    *,
    source_config: dict[str, object],
) -> dict[str, str]:
    alias_lookup = _alias_lookup(source_config)
    column_map: dict[str, str] = {}
    for fieldname in fieldnames:
        canonical = alias_lookup.get(_normalize_key(fieldname))
        if canonical is not None and canonical not in column_map:
            column_map[canonical] = fieldname
    return column_map


def _alias_lookup(source_config: dict[str, object]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for field in sorted(REQUIRED_SOURCE_FIELDS | OPTIONAL_SOURCE_FIELDS):
        aliases = [field]
        config_aliases = source_config.get(f"{field}_aliases")
        if isinstance(config_aliases, list):
            aliases.extend(str(alias) for alias in config_aliases)
        for alias in aliases:
            lookup[_normalize_key(alias)] = field
    return lookup


def _build_core_quote_row(
    *,
    raw_path: Path,
    row_number: int,
    trade_date: date,
    normalized: dict[str, str],
    manifest_row: dict[str, object],
) -> CoreQuoteDailyRow:
    row_trade_date = _parse_date(
        normalized["trade_date"],
        raw_path=raw_path,
        row_number=row_number,
        field_name="trade_date",
    )
    if row_trade_date != trade_date:
        raise ResearchWorkbenchError(
            f"{raw_path}:{row_number}: trade_date {row_trade_date.isoformat()} "
            f"does not match requested date {trade_date.isoformat()}"
        )

    exchange = normalized["exchange"].upper()
    product_code = normalized["product_code"].upper()
    if exchange != EXCHANGE:
        raise ResearchWorkbenchError(f"{raw_path}:{row_number}: unsupported exchange {exchange}")
    if product_code != PRODUCT_CODE:
        raise ResearchWorkbenchError(
            f"{raw_path}:{row_number}: unsupported product_code {product_code}"
        )

    # 这里保持旧 core schema 的 source_snapshot_id 字段，同时能追溯到 research raw run。
    source_snapshot_id = _research_source_snapshot_id(manifest_row)
    try:
        return CoreQuoteDailyRow(
            source_snapshot_id=source_snapshot_id,
            exchange=exchange,
            product_code=product_code,
            contract_code=normalized["contract_id"].upper(),
            trade_date=row_trade_date,
            open=_required_float(normalized, "open", raw_path=raw_path, row_number=row_number),
            high=_required_float(normalized, "high", raw_path=raw_path, row_number=row_number),
            low=_required_float(normalized, "low", raw_path=raw_path, row_number=row_number),
            close=_required_float(normalized, "close", raw_path=raw_path, row_number=row_number),
            settle=_required_float(normalized, "settle", raw_path=raw_path, row_number=row_number),
            pre_settle=_optional_float(normalized, "pre_settle"),
            volume=_required_int(normalized, "volume", raw_path=raw_path, row_number=row_number),
            open_interest=_required_int(
                normalized,
                "open_interest",
                raw_path=raw_path,
                row_number=row_number,
            ),
            turnover=_optional_float(normalized, "turnover"),
            quote_status=normalized.get("quote_status") or "normal",
        )
    except ValueError as exc:
        raise ResearchWorkbenchError(f"{raw_path}:{row_number}: {exc}") from exc


def _write_parquet_replace_keys(*, output_path: Path, rows: list[CoreQuoteDailyRow]) -> None:
    new_records = [row.model_dump(mode="json") for row in rows]
    new_frame = pd.DataFrame(new_records)
    key_columns = ["exchange", "contract_code", "trade_date"]

    if output_path.exists():
        existing = pd.read_parquet(output_path)
        for key_column in key_columns:
            if key_column not in existing.columns:
                raise ResearchWorkbenchError(
                    f"existing core quote table missing key column {key_column}: {output_path}"
                )
        existing["trade_date"] = existing["trade_date"].astype(str)
        new_frame["trade_date"] = new_frame["trade_date"].astype(str)
        new_keys = set(new_frame[key_columns].itertuples(index=False, name=None))
        keep_mask = [
            key not in new_keys
            for key in existing[key_columns].itertuples(index=False, name=None)
        ]
        combined = pd.concat([existing.loc[keep_mask], new_frame], ignore_index=True)
    else:
        combined = new_frame

    combined = combined.sort_values(["trade_date", "contract_code"]).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, index=False)


def _validate_unique_primary_key(rows: list[CoreQuoteDailyRow]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row.exchange, row.contract_code, row.trade_date.isoformat())
        if key in seen:
            raise ResearchWorkbenchError(
                "duplicate core_quote_daily primary key in normalized rows: "
                f"{row.exchange}/{row.contract_code}/{row.trade_date.isoformat()}"
            )
        seen.add(key)


def _research_source_snapshot_id(manifest_row: dict[str, object]) -> str:
    run_id = str(manifest_row["run_id"])
    source_file = str(manifest_row["source_file_name"])
    digest = str(manifest_row["sha256"])[:16]
    return f"research_raw:{run_id}:{digest}:{source_file}"


def _default_output_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME


def _cell(csv_row: dict[str, str], source_column: str) -> str:
    value = csv_row.get(source_column)
    return value.strip() if isinstance(value, str) else ""


def _parse_date(value: str, *, raw_path: Path, row_number: int, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ResearchWorkbenchError(
            f"{raw_path}:{row_number}: invalid {field_name} {value!r}"
        ) from exc


def _required_float(
    row: dict[str, str],
    field_name: str,
    *,
    raw_path: Path,
    row_number: int,
) -> float:
    value = row.get(field_name, "")
    if not value:
        raise ResearchWorkbenchError(f"{raw_path}:{row_number}: missing {field_name}")
    try:
        return float(value.replace(",", ""))
    except ValueError as exc:
        raise ResearchWorkbenchError(
            f"{raw_path}:{row_number}: invalid {field_name} {value!r}"
        ) from exc


def _required_int(
    row: dict[str, str],
    field_name: str,
    *,
    raw_path: Path,
    row_number: int,
) -> int:
    value = row.get(field_name, "")
    if not value:
        raise ResearchWorkbenchError(f"{raw_path}:{row_number}: missing {field_name}")
    try:
        return int(float(value.replace(",", "")))
    except ValueError as exc:
        raise ResearchWorkbenchError(
            f"{raw_path}:{row_number}: invalid {field_name} {value!r}"
        ) from exc


def _optional_float(row: dict[str, str], field_name: str) -> float | None:
    value = row.get(field_name, "")
    if not value:
        return None
    return float(value.replace(",", ""))


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _unique_str(values: object) -> tuple[str, ...]:
    unique: list[str] = []
    for value in values:
        text = str(value)
        if text not in unique:
            unique.append(text)
    return tuple(unique)
