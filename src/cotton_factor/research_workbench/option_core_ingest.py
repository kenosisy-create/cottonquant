"""R47 option raw preservation and core normalization for CF."""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_bytes
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.core.schemas import CoreOptionQuoteDailyRow
from cotton_factor.raw import RawSnapshotStore
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.option_data_contract import (
    CORE_OPTION_QUOTE_FILE_NAME,
    EXPECTED_FILE_PATTERNS,
)

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
SOURCE_NAME = "CZCE_CF_OPTION_HISTORY"
OPTION_CORE_INGEST_VERSION = "R47_option_core_ingest_v1"
REPORT_DIR = "option_core_ingest"
SUPPORTED_SUFFIXES = {".csv", ".txt", ".xlsx", ".xls", ".zip"}
HUMAN_REVIEW_REQUIRED = (
    "official_option_field_interpretation",
    "option_symbol_format",
    "underlying_contract_mapping",
    "moneyness_definition",
    "liquidity_thresholds",
    "deep_otm_and_near_expiry_filters",
    "american_option_model_boundary",
)
TRADE_DATE_ALIASES = ("trade_date", "date", "交易日期", "交易日", "日期")
OPTION_SYMBOL_ALIASES = (
    "option_symbol",
    "option_code",
    "contract_code",
    "contract_id",
    "合约代码",
    "合约",
    "品种月份",
)
UNDERLYING_ALIASES = (
    "underlying_contract",
    "underlying",
    "标的合约",
    "标的期货",
    "标的期货合约",
)
OPTION_TYPE_ALIASES = ("option_type", "cp", "call_put", "C/P", "期权类型", "看涨看跌")
STRIKE_ALIASES = ("strike", "exercise_price", "行权价", "执行价")
SETTLE_ALIASES = ("settle", "settlement", "结算价", "今结算")
VOLUME_ALIASES = ("volume", "vol", "成交量", "成交量(手)", "成交量（手）")
OPEN_INTEREST_ALIASES = ("open_interest", "oi", "持仓量", "空盘量")


@dataclass(frozen=True)
class OptionSourceRecord:
    """One R47 option source file record."""

    source_path: Path
    status: str
    row_count: int = 0
    snapshot_id: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    error: str | None = None

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable source record."""
        return {
            "source_path": str(self.source_path),
            "status": self.status,
            "row_count": self.row_count,
            "snapshot_id": self.snapshot_id,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "error": self.error,
        }


@dataclass(frozen=True)
class OptionQualityRow:
    """One normalized option-quality row."""

    trade_date: date
    option_symbol: str
    underlying_contract: str
    option_type: str
    strike: float
    settle: float | None
    volume: int | None
    open_interest: int | None
    moneyness: float | None
    liquidity_flag: str
    data_quality_flag: str
    risk_flags: tuple[str, ...]
    source_snapshot_id: str

    def to_record(self) -> dict[str, object]:
        """Return a table row for quality artifacts."""
        return {
            "trade_date": self.trade_date.isoformat(),
            "option_symbol": self.option_symbol,
            "underlying_contract": self.underlying_contract,
            "option_type": self.option_type,
            "strike": self.strike,
            "settle": self.settle,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "moneyness": self.moneyness,
            "liquidity_flag": self.liquidity_flag,
            "data_quality_flag": self.data_quality_flag,
            "risk_flags": ";".join(self.risk_flags),
            "source_snapshot_id": self.source_snapshot_id,
        }


@dataclass(frozen=True)
class ResearchOptionCoreIngestResult:
    """Result of R47 option raw/core ingest."""

    product_code: str
    exchange: str
    run_id: str
    status: str
    incoming_dir: Path
    raw_snapshot_count: int
    core_row_count: int
    source_file_count: int
    core_option_quote_path: Path | None
    quality_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    source_records: tuple[OptionSourceRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether R47 completed without parser-level failures."""
        return self.status in {"COMPLETED", "MISSING_OPTION_HISTORY"}

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "exchange": self.exchange,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "incoming_dir": str(self.incoming_dir),
            "raw_snapshot_count": self.raw_snapshot_count,
            "core_row_count": self.core_row_count,
            "source_file_count": self.source_file_count,
            "core_option_quote_path": (
                None if self.core_option_quote_path is None else str(self.core_option_quote_path)
            ),
            "quality_csv_path": str(self.quality_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "source_records": [record.to_summary() for record in self.source_records],
            "human_review_required": list(self.human_review_required),
            "option_signal_status": "not_connected",
        }


def connect_cf_option_history(
    *,
    source_dir: Path | None = None,
    raw_root: Path | None = None,
    core_output_dir: Path | None = None,
    output_path: Path | None = None,
    core_quote_path: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    low_volume_threshold: int = 1,
    low_open_interest_threshold: int = 1,
    deep_otm_threshold: float = 0.10,
    near_expiry_days: int = 31,
) -> ResearchOptionCoreIngestResult:
    """Preserve local option history files and normalize parseable rows into core."""
    ingest_run_id = run_id or _default_run_id()
    incoming_dir = source_dir or data_dir() / "incoming" / PRODUCT_CODE / "options" / "history"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    source_files = _source_files(incoming_dir)
    core_path = output_path or _default_core_output_path(core_output_dir)
    quality_path = _quality_csv_path(report_output_dir)
    json_path = _json_path(report_output_dir)
    markdown_path = _markdown_path(report_output_dir)
    manifest_path = _manifest_path(report_output_dir)

    if not source_files:
        result = ResearchOptionCoreIngestResult(
            product_code=PRODUCT_CODE,
            exchange=EXCHANGE,
            run_id=ingest_run_id,
            status="MISSING_OPTION_HISTORY",
            incoming_dir=incoming_dir,
            raw_snapshot_count=0,
            core_row_count=0,
            source_file_count=0,
            core_option_quote_path=None,
            quality_csv_path=quality_path,
            json_path=json_path,
            markdown_path=markdown_path,
            manifest_path=manifest_path,
            source_records=(),
            human_review_required=HUMAN_REVIEW_REQUIRED,
        )
        _write_outputs(result=result, quality_rows=())
        return result

    store = RawSnapshotStore(raw_root)
    underlying_lookup = _underlying_price_lookup(core_quote_path)
    records: list[OptionSourceRecord] = []
    rows: list[CoreOptionQuoteDailyRow] = []
    quality_rows: list[OptionQualityRow] = []

    for source_file in source_files:
        payload = source_file.read_bytes()
        snapshot = store.write_snapshot(
            payload=payload,
            source_name=SOURCE_NAME,
            product_code=PRODUCT_CODE,
            content_type=_content_type(source_file),
            biz_date=None,
            metadata={
                "source_path": str(source_file),
                "source_layer": "option_raw_snapshot",
                "run_id": ingest_run_id,
                "parser_version": OPTION_CORE_INGEST_VERSION,
                "official_field_interpretation": "HUMAN_REVIEW_REQUIRED",
                "normalizes_business_fields": False,
                "captured_at": utc_now().isoformat(),
            },
            parser_version=OPTION_CORE_INGEST_VERSION,
        )
        try:
            parsed_rows, parsed_quality = _parse_payload(
                payload=store.read_payload(snapshot.snapshot_id),
                source_name=source_file.name,
                snapshot_id=snapshot.snapshot_id,
                underlying_lookup=underlying_lookup,
                low_volume_threshold=low_volume_threshold,
                low_open_interest_threshold=low_open_interest_threshold,
                deep_otm_threshold=deep_otm_threshold,
                near_expiry_days=near_expiry_days,
            )
        except ResearchWorkbenchError as exc:
            records.append(
                OptionSourceRecord(
                    source_path=source_file,
                    status="PARSE_FAILED",
                    snapshot_id=snapshot.snapshot_id,
                    byte_size=len(payload),
                    sha256=sha256_bytes(payload),
                    error=str(exc),
                )
            )
            continue
        rows.extend(parsed_rows)
        quality_rows.extend(parsed_quality)
        records.append(
            OptionSourceRecord(
                source_path=source_file,
                status="PARSED",
                row_count=len(parsed_rows),
                snapshot_id=snapshot.snapshot_id,
                byte_size=len(payload),
                sha256=sha256_bytes(payload),
            )
        )

    core_output_path: Path | None = None
    if rows:
        _validate_unique_core_keys(rows)
        core_output_path = core_path
        _write_parquet_replace_keys(output_path=core_path, rows=rows)

    result = ResearchOptionCoreIngestResult(
        product_code=PRODUCT_CODE,
        exchange=EXCHANGE,
        run_id=ingest_run_id,
        status=_result_status(records=records, row_count=len(rows)),
        incoming_dir=incoming_dir,
        raw_snapshot_count=sum(1 for record in records if record.snapshot_id is not None),
        core_row_count=len(rows),
        source_file_count=len(source_files),
        core_option_quote_path=core_output_path,
        quality_csv_path=quality_path,
        json_path=json_path,
        markdown_path=markdown_path,
        manifest_path=manifest_path,
        source_records=tuple(records),
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_outputs(result=result, quality_rows=tuple(quality_rows))
    return result


def _source_files(incoming_dir: Path) -> tuple[Path, ...]:
    if not incoming_dir.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in incoming_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )
    )


def _parse_payload(
    *,
    payload: bytes,
    source_name: str,
    snapshot_id: str,
    underlying_lookup: dict[tuple[str, date], float],
    low_volume_threshold: int,
    low_open_interest_threshold: int,
    deep_otm_threshold: float,
    near_expiry_days: int,
) -> tuple[list[CoreOptionQuoteDailyRow], list[OptionQualityRow]]:
    suffix = Path(source_name).suffix.lower()
    if suffix == ".zip":
        return _parse_zip_payload(
            payload=payload,
            source_name=source_name,
            snapshot_id=snapshot_id,
            underlying_lookup=underlying_lookup,
            low_volume_threshold=low_volume_threshold,
            low_open_interest_threshold=low_open_interest_threshold,
            deep_otm_threshold=deep_otm_threshold,
            near_expiry_days=near_expiry_days,
        )
    if suffix in {".xlsx", ".xls"}:
        frame = _read_excel(payload=payload, source_name=source_name)
    else:
        frame = _read_csv(payload=payload, source_name=source_name)
    return _rows_from_frame(
        frame=frame,
        source_label=source_name,
        source_snapshot_id=f"{snapshot_id}:{source_name}",
        underlying_lookup=underlying_lookup,
        low_volume_threshold=low_volume_threshold,
        low_open_interest_threshold=low_open_interest_threshold,
        deep_otm_threshold=deep_otm_threshold,
        near_expiry_days=near_expiry_days,
    )


def _parse_zip_payload(
    *,
    payload: bytes,
    source_name: str,
    snapshot_id: str,
    underlying_lookup: dict[tuple[str, date], float],
    low_volume_threshold: int,
    low_open_interest_threshold: int,
    deep_otm_threshold: float,
    near_expiry_days: int,
) -> tuple[list[CoreOptionQuoteDailyRow], list[OptionQualityRow]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ResearchWorkbenchError(f"{source_name}: option history ZIP is invalid") from exc
    rows: list[CoreOptionQuoteDailyRow] = []
    quality_rows: list[OptionQualityRow] = []
    with archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and Path(member.filename).suffix.lower() in SUPPORTED_SUFFIXES
        ]
        if not members:
            raise ResearchWorkbenchError(f"{source_name}: no parseable members in ZIP")
        for member in members:
            member_payload = archive.read(member)
            member_name = member.filename
            suffix = Path(member_name).suffix.lower()
            try:
                frame = (
                    _read_excel(payload=member_payload, source_name=member_name)
                    if suffix in {".xlsx", ".xls"}
                    else _read_csv(payload=member_payload, source_name=member_name)
                )
                parsed_rows, parsed_quality = _rows_from_frame(
                    frame=frame,
                    source_label=member_name,
                    source_snapshot_id=f"{snapshot_id}:{member_name}",
                    underlying_lookup=underlying_lookup,
                    low_volume_threshold=low_volume_threshold,
                    low_open_interest_threshold=low_open_interest_threshold,
                    deep_otm_threshold=deep_otm_threshold,
                    near_expiry_days=near_expiry_days,
                )
            except ResearchWorkbenchError as exc:
                if "no CF option rows" in str(exc):
                    continue
                raise
            rows.extend(parsed_rows)
            quality_rows.extend(parsed_quality)
    if not rows:
        raise ResearchWorkbenchError(f"{source_name}: no CF option rows parsed from ZIP")
    return rows, quality_rows


def _read_csv(*, payload: bytes, source_name: str) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "gb18030", "gbk"):
        try:
            text = payload.decode(encoding)
            return _frame_from_text_table(text=text, source_name=source_name)
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            raise ResearchWorkbenchError(f"{source_name}: cannot read option CSV") from exc
    raise ResearchWorkbenchError(f"{source_name}: unsupported option CSV encoding")


def _read_excel(*, payload: bytes, source_name: str) -> pd.DataFrame:
    try:
        raw = pd.read_excel(io.BytesIO(payload), header=None)
    except Exception as exc:
        raise ResearchWorkbenchError(f"{source_name}: cannot read option Excel") from exc
    header_index = _header_index_from_frame(raw, source_name=source_name)
    columns = [str(value).strip() for value in raw.iloc[header_index].tolist()]
    frame = raw.iloc[header_index + 1 :].copy()
    frame.columns = columns
    frame = frame.dropna(how="all").reset_index(drop=True)
    return frame


def _frame_from_text_table(*, text: str, source_name: str) -> pd.DataFrame:
    lines = [line.rstrip("\r\n") for line in text.splitlines()]
    header_index = _header_index_from_lines(lines, source_name=source_name)
    delimiter = _detect_delimiter(lines[header_index])
    table_text = "\n".join(line for line in lines[header_index:] if line.strip())
    reader = csv.DictReader(io.StringIO(table_text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ResearchWorkbenchError(f"{source_name}: option text table has no header")
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {
            str(key).strip(): str(value).strip()
            for key, value in row.items()
            if key is not None and value is not None
        }
        if any(cleaned.values()):
            rows.append(cleaned)
    if not rows:
        raise ResearchWorkbenchError(f"{source_name}: option text table has no data rows")
    return pd.DataFrame(rows)


def _header_index_from_lines(lines: list[str], *, source_name: str) -> int:
    for index, line in enumerate(lines):
        if _looks_like_option_header(line):
            return index
    raise ResearchWorkbenchError(f"{source_name}: option header not found")


def _header_index_from_frame(frame: pd.DataFrame, *, source_name: str) -> int:
    for index, row in frame.iterrows():
        text = "|".join("" if pd.isna(value) else str(value) for value in row.tolist())
        if _looks_like_option_header(text):
            return int(index)
    raise ResearchWorkbenchError(f"{source_name}: option header not found")


def _looks_like_option_header(text: str) -> bool:
    normalized = _normalize_column(text)
    has_date = any(_normalize_column(alias) in normalized for alias in TRADE_DATE_ALIASES)
    has_symbol = any(_normalize_column(alias) in normalized for alias in OPTION_SYMBOL_ALIASES)
    return has_date and has_symbol


def _detect_delimiter(header_line: str) -> str:
    counts = {
        "|": header_line.count("|"),
        "\t": header_line.count("\t"),
        ",": header_line.count(","),
    }
    return max(counts, key=counts.get)


def _rows_from_frame(
    *,
    frame: pd.DataFrame,
    source_label: str,
    source_snapshot_id: str,
    underlying_lookup: dict[tuple[str, date], float],
    low_volume_threshold: int,
    low_open_interest_threshold: int,
    deep_otm_threshold: float,
    near_expiry_days: int,
) -> tuple[list[CoreOptionQuoteDailyRow], list[OptionQualityRow]]:
    if frame.empty:
        raise ResearchWorkbenchError(f"{source_label}: option table is empty")
    column_map = _column_map(frame.columns)
    if "trade_date" not in column_map or "option_symbol" not in column_map:
        raise ResearchWorkbenchError(f"{source_label}: missing trade_date or option_symbol")

    rows: list[CoreOptionQuoteDailyRow] = []
    quality_rows: list[OptionQualityRow] = []
    for row_number, record in enumerate(frame.to_dict("records"), start=2):
        try:
            row, quality = _row_from_record(
                record=record,
                column_map=column_map,
                row_number=row_number,
                source_label=source_label,
                source_snapshot_id=source_snapshot_id,
                underlying_lookup=underlying_lookup,
                low_volume_threshold=low_volume_threshold,
                low_open_interest_threshold=low_open_interest_threshold,
                deep_otm_threshold=deep_otm_threshold,
                near_expiry_days=near_expiry_days,
            )
        except ResearchWorkbenchError as exc:
            if "invalid CF option symbol" in str(exc):
                continue
            raise
        rows.append(row)
        quality_rows.append(quality)
    if not rows:
        raise ResearchWorkbenchError(f"{source_label}: no CF option rows parsed")
    return rows, quality_rows


def _row_from_record(
    *,
    record: dict[str, object],
    column_map: dict[str, str],
    row_number: int,
    source_label: str,
    source_snapshot_id: str,
    underlying_lookup: dict[tuple[str, date], float],
    low_volume_threshold: int,
    low_open_interest_threshold: int,
    deep_otm_threshold: float,
    near_expiry_days: int,
) -> tuple[CoreOptionQuoteDailyRow, OptionQualityRow]:
    trade_date = _parse_date(_value(record, column_map["trade_date"]), source_label, row_number)
    parsed_symbol = _parse_option_symbol(_value(record, column_map["option_symbol"]))
    underlying_contract = _optional_text(record, column_map, "underlying_contract")
    option_type = _optional_text(record, column_map, "option_type")
    strike = _optional_float(record, column_map, "strike")
    if underlying_contract is None:
        underlying_contract = parsed_symbol["underlying_contract"]
    if option_type is None:
        option_type = parsed_symbol["option_type"]
    if strike is None:
        strike = float(parsed_symbol["strike"])
    option_symbol = parsed_symbol["option_symbol"]
    settle = _optional_float(record, column_map, "settle")
    volume = _optional_int(record, column_map, "volume")
    open_interest = _optional_int(record, column_map, "open_interest")

    underlying_price = underlying_lookup.get((underlying_contract, trade_date))
    moneyness = _moneyness(
        option_type=option_type,
        strike=strike,
        underlying_price=underlying_price,
    )
    risk_flags = _risk_flags(
        option_type=option_type,
        strike=strike,
        trade_date=trade_date,
        contract_month=parsed_symbol["contract_month"],
        underlying_price=underlying_price,
        volume=volume,
        open_interest=open_interest,
        settle=settle,
        low_volume_threshold=low_volume_threshold,
        low_open_interest_threshold=low_open_interest_threshold,
        deep_otm_threshold=deep_otm_threshold,
        near_expiry_days=near_expiry_days,
    )
    liquidity_flag = _liquidity_flag(risk_flags)
    data_quality_flag = "normal" if not risk_flags else ";".join(risk_flags)
    core_row = CoreOptionQuoteDailyRow(
        source_snapshot_id=source_snapshot_id,
        exchange=EXCHANGE,
        product_code=PRODUCT_CODE,
        trade_date=trade_date,
        option_symbol=option_symbol,
        underlying_contract=underlying_contract,
        option_type=option_type,  # type: ignore[arg-type]
        strike=strike,
        settle=settle,
        volume=volume,
        open_interest=open_interest,
        moneyness=moneyness,
        liquidity_flag=liquidity_flag,
        data_quality_flag=data_quality_flag,
    )
    quality = OptionQualityRow(
        trade_date=trade_date,
        option_symbol=option_symbol,
        underlying_contract=underlying_contract,
        option_type=option_type,
        strike=strike,
        settle=settle,
        volume=volume,
        open_interest=open_interest,
        moneyness=moneyness,
        liquidity_flag=liquidity_flag,
        data_quality_flag=data_quality_flag,
        risk_flags=tuple(risk_flags),
        source_snapshot_id=source_snapshot_id,
    )
    return core_row, quality


def _parse_option_symbol(value: object) -> dict[str, str | float]:
    text = str(value).strip().upper()
    compact = re.sub(r"[\s_-]+", "", text)
    match = re.fullmatch(
        rf"(?P<product>{PRODUCT_CODE})(?P<month>\d{{3,6}})(?P<option_type>[CP])"
        r"(?P<strike>\d+(?:\.\d+)?)",
        compact,
    )
    if match is None:
        raise ResearchWorkbenchError(f"invalid CF option symbol: {value!r}")
    strike_text = match.group("strike")
    strike = float(strike_text)
    if strike <= 0:
        raise ResearchWorkbenchError(f"invalid CF option strike: {value!r}")
    month = match.group("month")
    option_type = match.group("option_type")
    normalized_strike = str(int(strike)) if strike.is_integer() else str(strike)
    return {
        "option_symbol": f"{PRODUCT_CODE}{month}{option_type}{normalized_strike}",
        "underlying_contract": f"{PRODUCT_CODE}{month}",
        "option_type": option_type,
        "strike": strike,
        "contract_month": month,
    }


def _risk_flags(
    *,
    option_type: str,
    strike: float,
    trade_date: date,
    contract_month: str,
    underlying_price: float | None,
    volume: int | None,
    open_interest: int | None,
    settle: float | None,
    low_volume_threshold: int,
    low_open_interest_threshold: int,
    deep_otm_threshold: float,
    near_expiry_days: int,
) -> list[str]:
    flags: list[str] = []
    if settle is None:
        flags.append("MISSING_SETTLE")
    if volume is None or volume < low_volume_threshold:
        flags.append("LOW_LIQUIDITY_VOLUME")
    if open_interest is None or open_interest < low_open_interest_threshold:
        flags.append("LOW_LIQUIDITY_OPEN_INTEREST")
    if underlying_price is None or underlying_price <= 0:
        flags.append("UNDERLYING_PRICE_MISSING")
    else:
        if _deep_otm_proxy(
            option_type=option_type,
            strike=strike,
            underlying_price=underlying_price,
            threshold=deep_otm_threshold,
        ):
            flags.append("DEEP_OTM_PROXY")
    if _near_expiry_proxy(
        trade_date=trade_date,
        contract_month=contract_month,
        near_expiry_days=near_expiry_days,
    ):
        flags.append("NEAR_EXPIRY_REVIEW")
    return flags


def _moneyness(
    *,
    option_type: str,
    strike: float,
    underlying_price: float | None,
) -> float | None:
    if underlying_price is None or underlying_price <= 0:
        return None
    # R47 使用研究 proxy：C 为 underlying/strike，P 为 strike/underlying；精确口径留到 R48 复核。
    if option_type == "C":
        return underlying_price / strike
    return strike / underlying_price


def _deep_otm_proxy(
    *,
    option_type: str,
    strike: float,
    underlying_price: float,
    threshold: float,
) -> bool:
    if option_type == "C":
        return strike / underlying_price - 1 >= threshold
    return underlying_price / strike - 1 >= threshold


def _near_expiry_proxy(
    *,
    trade_date: date,
    contract_month: str,
    near_expiry_days: int,
) -> bool:
    year, month = _contract_year_month(contract_month=contract_month, trade_date=trade_date)
    month_start = date(year, month, 1)
    delta = (month_start - trade_date).days
    return delta <= near_expiry_days


def _contract_year_month(*, contract_month: str, trade_date: date) -> tuple[int, int]:
    if len(contract_month) == 3:
        year_digit = int(contract_month[0])
        month = int(contract_month[1:])
        decade = trade_date.year // 10 * 10
        year = decade + year_digit
        if year < trade_date.year - 5:
            year += 10
        if year > trade_date.year + 5:
            year -= 10
        return year, month
    if len(contract_month) == 4:
        return 2000 + int(contract_month[:2]), int(contract_month[2:])
    if len(contract_month) == 6:
        return int(contract_month[:4]), int(contract_month[4:])
    raise ResearchWorkbenchError(f"unsupported option contract month: {contract_month}")


def _liquidity_flag(risk_flags: list[str]) -> str:
    if "LOW_LIQUIDITY_VOLUME" in risk_flags or "LOW_LIQUIDITY_OPEN_INTEREST" in risk_flags:
        return "low_liquidity"
    return "normal_liquidity"


def _underlying_price_lookup(core_quote_path: Path | None) -> dict[tuple[str, date], float]:
    path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    if not path.exists():
        return {}
    frame = pd.read_parquet(path)
    required = {"contract_code", "trade_date", "settle"}
    if not required.issubset(frame.columns):
        return {}
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["settle"] = pd.to_numeric(working["settle"], errors="coerce")
    working = working.dropna(subset=["contract_code", "trade_date", "settle"])
    return {
        (str(row.contract_code), row.trade_date): float(row.settle)
        for row in working.itertuples(index=False)
    }


def _column_map(columns: pd.Index) -> dict[str, str]:
    aliases = {
        "trade_date": TRADE_DATE_ALIASES,
        "option_symbol": OPTION_SYMBOL_ALIASES,
        "underlying_contract": UNDERLYING_ALIASES,
        "option_type": OPTION_TYPE_ALIASES,
        "strike": STRIKE_ALIASES,
        "settle": SETTLE_ALIASES,
        "volume": VOLUME_ALIASES,
        "open_interest": OPEN_INTEREST_ALIASES,
    }
    lookup: dict[str, str] = {}
    normalized_columns = {_normalize_column(str(column)): str(column) for column in columns}
    for field, field_aliases in aliases.items():
        for alias in field_aliases:
            source = normalized_columns.get(_normalize_column(alias))
            if source is not None:
                lookup[field] = source
                break
    return lookup


def _normalize_column(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("\ufeff", "").replace("_", "").lower()


def _value(record: dict[str, object], column: str) -> object:
    value = record.get(column)
    if pd.isna(value):
        return ""
    return value


def _optional_text(
    record: dict[str, object],
    column_map: dict[str, str],
    field: str,
) -> str | None:
    column = column_map.get(field)
    if column is None:
        return None
    text = str(_value(record, column)).strip().upper()
    return text or None


def _optional_float(
    record: dict[str, object],
    column_map: dict[str, str],
    field: str,
) -> float | None:
    column = column_map.get(field)
    if column is None:
        return None
    text = _clean_number(_value(record, column))
    return None if not text else float(text)


def _optional_int(
    record: dict[str, object],
    column_map: dict[str, str],
    field: str,
) -> int | None:
    column = column_map.get(field)
    if column is None:
        return None
    text = _clean_number(_value(record, column))
    return None if not text else int(float(text))


def _clean_number(value: object) -> str:
    text = str(value).strip().replace(",", "")
    if text.lower() in {"", "-", "--", "nan", "none"}:
        return ""
    return text


def _parse_date(value: object, source_label: str, row_number: int) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date()  # type: ignore[no-any-return, attr-defined]
        except TypeError:
            pass
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            if fmt == "%Y-%m-%d":
                return date.fromisoformat(text)
            if fmt == "%Y/%m/%d":
                year_text, month_text, day_text = text.split("/")
                return date(int(year_text), int(month_text), int(day_text))
            if fmt == "%Y%m%d" and re.fullmatch(r"\d{8}", text):
                return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            continue
    raise ResearchWorkbenchError(f"{source_label}:{row_number}: invalid trade date {value!r}")


def _write_parquet_replace_keys(*, output_path: Path, rows: list[CoreOptionQuoteDailyRow]) -> None:
    new_frame = pd.DataFrame([row.model_dump(mode="json") for row in rows])
    key_columns = ["exchange", "option_symbol", "trade_date"]
    if output_path.exists():
        existing = pd.read_parquet(output_path)
        for key_column in key_columns:
            if key_column not in existing.columns:
                raise ResearchWorkbenchError(
                    f"existing core option quote table missing key column {key_column}: "
                    f"{output_path}"
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
    combined = combined.sort_values(["trade_date", "option_symbol"]).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, index=False)


def _validate_unique_core_keys(rows: list[CoreOptionQuoteDailyRow]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row.exchange, row.option_symbol, row.trade_date.isoformat())
        if key in seen:
            raise ResearchWorkbenchError(
                "duplicate core_option_quote_daily key: "
                f"{row.exchange}/{row.option_symbol}/{row.trade_date.isoformat()}"
            )
        seen.add(key)


def _write_outputs(
    *,
    result: ResearchOptionCoreIngestResult,
    quality_rows: tuple[OptionQualityRow, ...],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_quality_csv(result.quality_csv_path, quality_rows=quality_rows)
    result.json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result.markdown_path.write_text(
        _render_markdown(result=result, quality_rows=quality_rows),
        encoding="utf-8",
    )
    _write_manifest(result=result, quality_rows=quality_rows)


def _write_quality_csv(path: Path, *, quality_rows: tuple[OptionQualityRow, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trade_date",
        "option_symbol",
        "underlying_contract",
        "option_type",
        "strike",
        "settle",
        "volume",
        "open_interest",
        "moneyness",
        "liquidity_flag",
        "data_quality_flag",
        "risk_flags",
        "source_snapshot_id",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in quality_rows:
            writer.writerow(row.to_record())


def _write_manifest(
    *,
    result: ResearchOptionCoreIngestResult,
    quality_rows: tuple[OptionQualityRow, ...],
) -> None:
    payload = {
        "report_type": "option_core_ingest",
        "rule_version": OPTION_CORE_INGEST_VERSION,
        "generated_at": utc_now().isoformat(),
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "exchange": EXCHANGE,
        "status": result.status,
        "incoming_dir": str(result.incoming_dir),
        "raw_snapshot_count": result.raw_snapshot_count,
        "core_row_count": result.core_row_count,
        "core_option_quote_path": (
            None if result.core_option_quote_path is None else str(result.core_option_quote_path)
        ),
        "quality_csv_path": str(result.quality_csv_path),
        "risk_flag_counts": _risk_flag_counts(quality_rows),
        "source_records": [record.to_summary() for record in result.source_records],
        "expected_file_patterns": list(EXPECTED_FILE_PATTERNS),
        "option_signal_status": "not_connected",
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: ResearchOptionCoreIngestResult,
    quality_rows: tuple[OptionQualityRow, ...],
) -> str:
    lines = [
        "# CF 期权 raw/core 接入 R47",
        "",
        "## 数据状态",
        "",
        f"- 状态：`{result.status}`",
        f"- incoming 路径：`{result.incoming_dir}`",
        f"- raw snapshot 数：`{result.raw_snapshot_count}`",
        f"- core 行数：`{result.core_row_count}`",
        f"- core 期权表：`{result.core_option_quote_path or ''}`",
        f"- 质量报告：`{result.quality_csv_path}`",
        "- 期权信号状态：`not_connected`",
        "",
        "## Source Records",
        "",
        "| Source | Status | Rows | Snapshot | Error |",
        "| --- | --- | ---: | --- | --- |",
    ]
    if result.source_records:
        for record in result.source_records:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(record.source_path),
                        record.status,
                        str(record.row_count),
                        record.snapshot_id or "",
                        (record.error or "").replace("|", "\\|"),
                    ]
                )
                + " |"
            )
    else:
        lines.append("|  | MISSING_OPTION_HISTORY | 0 |  | no option history files |")

    lines.extend(
        [
            "",
            "## 风险标签摘要",
            "",
            "| Risk Flag | Count |",
            "| --- | ---: |",
        ]
    )
    counts = _risk_flag_counts(quality_rows)
    if counts:
        for flag, count in counts.items():
            lines.append(f"| `{flag}` | {count} |")
    else:
        lines.append("| `MISSING_OPTION_HISTORY` | 1 |")

    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- R47 只做 raw 保全、期权代码解析、core 期权行情标准化和质量标签。",
            "- moneyness 与 deep OTM 仍是研究 proxy，R48 前必须人工复核。",
            "- 低流动性、深虚值、临近到期行会打标签；不进入任何交易指令。",
            "- 本报告不构成交易指令。",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    return "\n".join(lines) + "\n"


def _risk_flag_counts(quality_rows: tuple[OptionQualityRow, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in quality_rows:
        for flag in row.risk_flags:
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items()))


def _result_status(*, records: list[OptionSourceRecord], row_count: int) -> str:
    if row_count > 0 and all(record.status == "PARSED" for record in records):
        return "COMPLETED"
    if row_count > 0:
        return "PARTIAL"
    if any(record.status == "PARSE_FAILED" for record in records):
        return "PARSE_FAILED"
    return "MISSING_OPTION_HISTORY"


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return "application/zip"
    if suffix in {".xlsx", ".xls"}:
        return "application/vnd.ms-excel"
    return "text/csv"


def _quality_csv_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_core_ingest_quality.csv"


def _json_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_core_ingest.json"


def _markdown_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_core_ingest.md"


def _manifest_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_core_ingest_manifest.json"


def _report_root(report_output_dir: Path | None) -> Path:
    return report_output_dir or reports_dir() / "research" / REPORT_DIR


def _default_core_output_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_OPTION_QUOTE_FILE_NAME


def _default_run_id() -> str:
    return f"r47_option_core_{PRODUCT_CODE}_{uuid.uuid4().hex[:8]}"
