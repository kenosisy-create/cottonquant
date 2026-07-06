"""CZCE official annual history connector for CF research data."""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_bytes
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.core.schemas import CoreQuoteDailyRow
from cotton_factor.raw import RawSnapshotStore

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
SOURCE_NAME = "CZCE_OFFICIAL_HISTORY_QUOTE"
PARSER_VERSION = "czce_official_history_quote.core.v1"
OFFICIAL_HISTORY_PAGE_URL = "https://www.czce.com.cn/cn/jysj/lshqxz/H077003019index_1.htm"
OFFICIAL_HISTORY_URL_TEMPLATE = (
    "https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/ALLFUTURES{year}.zip"
)
CORE_QUOTE_FILE_NAME = "core_quote_daily.parquet"
REPORT_DIR = "official_history"
HUMAN_REVIEW_REQUIRED = (
    "official_exchange_field_interpretation",
    "official_volume_open_interest_turnover_single_sided_scope",
    "official_turnover_unit_interpretation",
    "contract_rule_and_last_trading_day_review_before_trading_use",
)
DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": OFFICIAL_HISTORY_PAGE_URL,
}

SourceStatus = Literal[
    "LOCAL_ARCHIVE_READY",
    "DOWNLOADED",
    "MISSING_LOCAL_ARCHIVE",
    "DOWNLOAD_FAILED",
    "PARSE_FAILED",
]


@dataclass(frozen=True)
class OfficialHistoryYearRecord:
    """One year-level official-history ingest record."""

    year: int
    official_url: str
    status: SourceStatus
    row_count: int = 0
    source_path: Path | None = None
    snapshot_id: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    error: str | None = None

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable year record."""
        return {
            "year": self.year,
            "official_url": self.official_url,
            "status": self.status,
            "row_count": self.row_count,
            "source_path": str(self.source_path) if self.source_path is not None else None,
            "snapshot_id": self.snapshot_id,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "error": self.error,
        }


@dataclass(frozen=True)
class OfficialHistoryConnectResult:
    """Result of connecting official CZCE annual history into core quotes."""

    product_code: str
    years: tuple[int, ...]
    status: str
    raw_snapshot_count: int
    row_count: int
    core_output_path: Path | None
    json_path: Path
    markdown_path: Path
    records: tuple[OfficialHistoryYearRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether every requested year produced CF core quote rows."""
        return self.status == "COMPLETED"

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "years": list(self.years),
            "status": self.status,
            "passed": self.passed,
            "raw_snapshot_count": self.raw_snapshot_count,
            "row_count": self.row_count,
            "core_output_path": (
                str(self.core_output_path) if self.core_output_path is not None else None
            ),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "records": [record.to_summary() for record in self.records],
            "human_review_required": list(self.human_review_required),
        }


def connect_cf_official_history(
    *,
    years: tuple[int, ...] | None = None,
    source_dir: Path | None = None,
    allow_download: bool = False,
    raw_root: Path | None = None,
    core_output_dir: Path | None = None,
    output_path: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    today: date | None = None,
) -> OfficialHistoryConnectResult:
    """Preserve CZCE official annual ZIPs and normalize CF rows into core quotes."""
    active_years = _validate_years(years or default_recent_history_years(today=today))
    source_root = source_dir or data_dir() / "incoming" / PRODUCT_CODE / "history"
    store = RawSnapshotStore(raw_root)
    records: list[OfficialHistoryYearRecord] = []
    all_rows: list[CoreQuoteDailyRow] = []

    for year in active_years:
        official_url = official_history_url(year)
        local_archive = _find_local_archive(source_root=source_root, year=year)
        payload: bytes | None = None
        initial_status: SourceStatus
        source_path: Path | None = None

        if local_archive is not None:
            payload = local_archive.read_bytes()
            initial_status = "LOCAL_ARCHIVE_READY"
            source_path = local_archive
        elif allow_download:
            payload, download_error = _download_official_archive(year=year)
            if payload is None:
                records.append(
                    OfficialHistoryYearRecord(
                        year=year,
                        official_url=official_url,
                        status="DOWNLOAD_FAILED",
                        error=download_error,
                    )
                )
                continue
            initial_status = "DOWNLOADED"
        else:
            records.append(
                OfficialHistoryYearRecord(
                    year=year,
                    official_url=official_url,
                    status="MISSING_LOCAL_ARCHIVE",
                    source_path=source_root / f"ALLFUTURES{year}.zip",
                    error=(
                        "official archive is not available locally; place the ZIP under "
                        f"{source_root} or rerun with allow_download=True"
                    ),
                )
            )
            continue

        if payload is None:
            raise ResearchWorkbenchError(f"internal error: missing payload for {year}")

        snapshot = store.write_snapshot(
            payload=payload,
            source_name=SOURCE_NAME,
            product_code=PRODUCT_CODE,
            content_type="application/zip",
            biz_date=None,
            metadata={
                "year": year,
                "history_year": year,
                "official_url": official_url,
                "official_page_url": OFFICIAL_HISTORY_PAGE_URL,
                "source_path": str(source_path) if source_path is not None else None,
                "fetch_mode": "local_archive" if source_path is not None else "download",
                "run_id": run_id,
                "parser_version": PARSER_VERSION,
                "volume_open_interest_turnover_scope": (
                    "single_sided_after_2020_per_official_page"
                ),
                "normalizes_business_fields": False,
                "source_layer": "raw_snapshot",
                "captured_at": utc_now().isoformat(),
            },
            parser_version=PARSER_VERSION,
        )

        try:
            # 解析只发生在 core 标准化层；研究模块后续只能读 core parquet。
            rows = _parse_official_history_payload(
                payload=store.read_payload(snapshot.snapshot_id),
                snapshot_id=snapshot.snapshot_id,
                year=year,
                source_name=(
                    source_path.name if source_path is not None else f"ALLFUTURES{year}.zip"
                ),
            )
        except ResearchWorkbenchError as exc:
            records.append(
                OfficialHistoryYearRecord(
                    year=year,
                    official_url=official_url,
                    status="PARSE_FAILED",
                    source_path=source_path,
                    snapshot_id=snapshot.snapshot_id,
                    byte_size=len(payload),
                    sha256=sha256_bytes(payload),
                    error=str(exc),
                )
            )
            continue

        all_rows.extend(rows)
        records.append(
            OfficialHistoryYearRecord(
                year=year,
                official_url=official_url,
                status=initial_status,
                row_count=len(rows),
                source_path=source_path,
                snapshot_id=snapshot.snapshot_id,
                byte_size=len(payload),
                sha256=sha256_bytes(payload),
            )
        )

    core_output_path: Path | None = None
    if all_rows:
        _validate_unique_core_keys(all_rows)
        core_output_path = output_path or _default_core_output_path(core_output_dir)
        _write_parquet_replace_keys(output_path=core_output_path, rows=all_rows)

    json_path, markdown_path = _report_paths(
        years=active_years,
        report_output_dir=report_output_dir,
    )
    result = OfficialHistoryConnectResult(
        product_code=PRODUCT_CODE,
        years=active_years,
        status=_result_status(records=records, requested_years=active_years),
        raw_snapshot_count=sum(1 for record in records if record.snapshot_id is not None),
        row_count=len(all_rows),
        core_output_path=core_output_path,
        json_path=json_path,
        markdown_path=markdown_path,
        records=tuple(records),
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_reports(result)
    return result


def default_recent_history_years(*, today: date | None = None) -> tuple[int, int, int]:
    """Return the three most recent completed official annual history years."""
    current = today or date.today()
    last_completed_year = current.year - 1
    return (
        last_completed_year - 2,
        last_completed_year - 1,
        last_completed_year,
    )


def official_history_url(year: int) -> str:
    """Return the official annual history ZIP URL for one year."""
    _validate_year(year)
    return OFFICIAL_HISTORY_URL_TEMPLATE.format(year=year)


def _download_official_archive(*, year: int) -> tuple[bytes | None, str | None]:
    url = official_history_url(year)
    request = urllib.request.Request(url, headers=DOWNLOAD_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            status = getattr(response, "status", None)
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code} from official archive URL: {url}"
    except urllib.error.URLError as exc:
        return None, f"network error from official archive URL {url}: {exc.reason}"
    except TimeoutError:
        return None, f"timeout fetching official archive URL: {url}"

    if status is not None and int(status) >= 400:
        return None, f"HTTP {status} from official archive URL: {url}"
    if not payload.startswith(b"PK"):
        return None, (
            "official archive response is not a ZIP payload; "
            f"sha256={sha256_bytes(payload)} byte_size={len(payload)} url={url}"
        )
    return payload, None


def _parse_official_history_zip(
    *,
    payload: bytes,
    snapshot_id: str,
    year: int,
) -> list[CoreQuoteDailyRow]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ResearchWorkbenchError("official history payload is not a valid ZIP") from exc

    rows: list[CoreQuoteDailyRow] = []
    with archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith((".txt", ".csv"))
        ]
        if not members:
            raise ResearchWorkbenchError("official history ZIP contains no TXT/CSV members")
        for member in members:
            member_payload = archive.read(member)
            text = _decode_member(member_payload, member_name=member.filename)
            rows.extend(
                _parse_history_text(
                    text=text,
                    snapshot_id=snapshot_id,
                    member_name=member.filename,
                    year=year,
                )
            )

    if not rows:
        raise ResearchWorkbenchError(f"official history ZIP produced no {PRODUCT_CODE} rows")
    return rows


def _parse_official_history_payload(
    *,
    payload: bytes,
    snapshot_id: str,
    year: int,
    source_name: str,
) -> list[CoreQuoteDailyRow]:
    suffix = Path(source_name).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return _parse_official_history_excel(
            payload=payload,
            snapshot_id=snapshot_id,
            source_name=source_name,
            year=year,
        )
    return _parse_official_history_zip(payload=payload, snapshot_id=snapshot_id, year=year)


def _parse_official_history_excel(
    *,
    payload: bytes,
    snapshot_id: str,
    source_name: str,
    year: int,
) -> list[CoreQuoteDailyRow]:
    try:
        frame = pd.read_excel(io.BytesIO(payload), header=1)
    except Exception as exc:
        raise ResearchWorkbenchError(f"{source_name}: cannot read official Excel") from exc
    if frame.shape[1] < 14:
        raise ResearchWorkbenchError(
            f"{source_name}: official Excel has too few columns: {frame.shape[1]}"
        )

    rows: list[CoreQuoteDailyRow] = []
    for row_number, row in enumerate(frame.itertuples(index=False, name=None), start=3):
        contract_code = _normalize_contract_code(str(row[1]))
        if not _is_product_contract(contract_code):
            continue
        trade_date = _excel_trade_date(row[0], source_name=source_name, row_number=row_number)
        if trade_date.year != year:
            continue

        # 单品种 Excel 表头在部分 Windows 终端会乱码；这里按郑商所固定列位映射。
        rows.append(
            CoreQuoteDailyRow(
                source_snapshot_id=f"{snapshot_id}:{source_name}",
                exchange=EXCHANGE,
                product_code=PRODUCT_CODE,
                contract_code=contract_code,
                trade_date=trade_date,
                pre_settle=_optional_float(row[2]),
                open=_optional_float(row[3]),
                high=_optional_float(row[4]),
                low=_optional_float(row[5]),
                close=_optional_float(row[6]),
                settle=_optional_float(row[7]),
                volume=_optional_int(row[10]),
                open_interest=_optional_int(row[11]),
                turnover=_optional_float(row[13]),
                quote_status="normal",
            )
        )
    if not rows:
        raise ResearchWorkbenchError(
            f"{source_name}: official Excel produced no {PRODUCT_CODE} rows"
        )
    return rows


def _excel_trade_date(value: object, *, source_name: str, row_number: int) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date()  # type: ignore[no-any-return, attr-defined]
        except TypeError:
            pass
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ResearchWorkbenchError(
            f"{source_name}:{row_number}: invalid trade date {text!r}"
        ) from exc


def _parse_history_text(
    *,
    text: str,
    snapshot_id: str,
    member_name: str,
    year: int,
) -> list[CoreQuoteDailyRow]:
    lines = [line.strip("\ufeff\r\n") for line in text.splitlines()]
    header_index = _find_header_index(lines)
    if header_index is None:
        raise ResearchWorkbenchError(f"{member_name}: official history header not found")

    header_line = lines[header_index]
    delimiter = _detect_delimiter(header_line)
    table_text = "\n".join(line for line in lines[header_index:] if line.strip())
    reader = csv.DictReader(io.StringIO(table_text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ResearchWorkbenchError(f"{member_name}: official history table has no header")

    rows: list[CoreQuoteDailyRow] = []
    for row_number, row in enumerate(reader, start=header_index + 2):
        if not _looks_like_data_row(row):
            continue
        contract_code = _normalize_contract_code(_first_cell(row, CONTRACT_ALIASES))
        if not _is_product_contract(contract_code):
            continue
        try:
            trade_date = _parse_trade_date(
                _first_cell(row, TRADE_DATE_ALIASES),
                member_name=member_name,
                row_number=row_number,
            )
        except ResearchWorkbenchError:
            continue
        if trade_date.year != year:
            continue

        # 官方年包字段名可能随年份微调；这里集中做别名映射，避免研究层再碰 raw 字段。
        rows.append(
            CoreQuoteDailyRow(
                source_snapshot_id=f"{snapshot_id}:{member_name}",
                exchange=EXCHANGE,
                product_code=PRODUCT_CODE,
                contract_code=contract_code,
                trade_date=trade_date,
                open=_optional_float(_first_cell(row, OPEN_ALIASES)),
                high=_optional_float(_first_cell(row, HIGH_ALIASES)),
                low=_optional_float(_first_cell(row, LOW_ALIASES)),
                close=_optional_float(_first_cell(row, CLOSE_ALIASES)),
                settle=_optional_float(_first_cell(row, SETTLE_ALIASES)),
                pre_settle=_optional_float(_first_cell(row, PRE_SETTLE_ALIASES)),
                volume=_optional_int(_first_cell(row, VOLUME_ALIASES)),
                open_interest=_optional_int(_first_cell(row, OPEN_INTEREST_ALIASES)),
                turnover=_optional_float(_first_cell(row, TURNOVER_ALIASES)),
                quote_status="normal",
            )
        )
    return rows


TRADE_DATE_ALIASES = ("交易日期", "交易日", "日期", "trade_date")
CONTRACT_ALIASES = ("品种月份", "合约代码", "合约", "合约月份", "contract_id", "contract_code")
PRE_SETTLE_ALIASES = ("昨结算", "昨结算价", "pre_settle", "prev_settle")
OPEN_ALIASES = ("今开盘", "开盘价", "开盘", "open")
HIGH_ALIASES = ("最高价", "最高", "high")
LOW_ALIASES = ("最低价", "最低", "low")
CLOSE_ALIASES = ("今收盘", "收盘价", "收盘", "close")
SETTLE_ALIASES = ("今结算", "结算价", "结算", "settle")
VOLUME_ALIASES = ("成交量", "成交量(手)", "成交量（手）", "volume", "vol")
OPEN_INTEREST_ALIASES = ("空盘量", "持仓量", "open_interest", "oi")
TURNOVER_ALIASES = (
    "成交额",
    "成交额(万元)",
    "成交额（万元）",
    "交易额",
    "成交金额",
    "turnover",
)


def _find_local_archive(*, source_root: Path, year: int) -> Path | None:
    candidates = [
        source_root / str(year) / f"ALLFUTURES{year}.zip",
        source_root / f"ALLFUTURES{year}.zip",
        source_root / str(year) / f"CFFUTURES{year}.xlsx",
        source_root / f"CFFUTURES{year}.xlsx",
        source_root / str(year) / f"CFFUTURES{year}.xls",
        source_root / f"CFFUTURES{year}.xls",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    if not source_root.exists():
        return None
    matches = sorted(
        path
        for path in source_root.rglob(f"*{year}*")
        if path.suffix.lower() in {".zip", ".xlsx", ".xls"}
    )
    return matches[0].resolve() if matches else None


def _decode_member(payload: bytes, *, member_name: str) -> str:
    for encoding in ("utf-8-sig", "gb18030", "gbk"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ResearchWorkbenchError(f"{member_name}: unsupported text encoding")


def _find_header_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        normalized = _normalize_header_key(line)
        if "交易日期" in normalized and ("品种月份" in normalized or "合约" in normalized):
            return index
    return None


def _detect_delimiter(header_line: str) -> str:
    delimiter_counts = {
        "|": header_line.count("|"),
        "\t": header_line.count("\t"),
        ",": header_line.count(","),
    }
    return max(delimiter_counts, key=delimiter_counts.get)


def _looks_like_data_row(row: dict[str, str]) -> bool:
    values = [str(value).strip() for value in row.values() if value is not None]
    return any(values) and not any(value in {"合计", "小计", "总计"} for value in values)


def _first_cell(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    lookup = {_normalize_header_key(key): value for key, value in row.items() if key is not None}
    for alias in aliases:
        value = lookup.get(_normalize_header_key(alias))
        if value is not None:
            return str(value).strip()
    return ""


def _normalize_header_key(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("\ufeff", "").lower()


def _normalize_contract_code(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _is_product_contract(contract_code: str) -> bool:
    return bool(re.fullmatch(rf"{PRODUCT_CODE}\d{{3,4}}", contract_code))


def _parse_trade_date(value: str, *, member_name: str, row_number: int) -> date:
    text = value.strip()
    if not text:
        raise ResearchWorkbenchError(f"{member_name}:{row_number}: missing trade date")
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
    raise ResearchWorkbenchError(f"{member_name}:{row_number}: invalid trade date {value!r}")


def _optional_float(value: str) -> float | None:
    text = _clean_number(value)
    if not text:
        return None
    return float(text)


def _optional_int(value: str) -> int | None:
    text = _clean_number(value)
    if not text:
        return None
    return int(float(text))


def _clean_number(value: str) -> str:
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "—", "nan", "None"}:
        return ""
    return text


def _write_parquet_replace_keys(*, output_path: Path, rows: list[CoreQuoteDailyRow]) -> None:
    new_frame = pd.DataFrame([row.model_dump(mode="json") for row in rows])
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


def _validate_unique_core_keys(rows: list[CoreQuoteDailyRow]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row.exchange, row.contract_code, row.trade_date.isoformat())
        if key in seen:
            raise ResearchWorkbenchError(
                "duplicate official history core_quote_daily key: "
                f"{row.exchange}/{row.contract_code}/{row.trade_date.isoformat()}"
            )
        seen.add(key)


def _result_status(
    *,
    records: list[OfficialHistoryYearRecord],
    requested_years: tuple[int, ...],
) -> str:
    completed = {
        record.year
        for record in records
        if record.status in {"LOCAL_ARCHIVE_READY", "DOWNLOADED"} and record.row_count > 0
    }
    if len(completed) == len(requested_years):
        return "COMPLETED"
    if completed:
        return "PARTIAL"
    if any(record.status == "DOWNLOAD_FAILED" for record in records):
        return "DOWNLOAD_BLOCKED"
    return "NEEDS_MANUAL_DOWNLOAD"


def _write_reports(result: OfficialHistoryConnectResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result.markdown_path.write_text(_markdown_report(result), encoding="utf-8")


def _markdown_report(result: OfficialHistoryConnectResult) -> str:
    lines = [
        "# CF Official History Data Connect",
        "",
        f"- Product: `{result.product_code}`",
        f"- Years: `{','.join(str(year) for year in result.years)}`",
        f"- Status: `{result.status}`",
        f"- Rows: `{result.row_count}`",
        f"- Raw snapshots: `{result.raw_snapshot_count}`",
        f"- Core output: `{result.core_output_path or ''}`",
        f"- Official page: `{OFFICIAL_HISTORY_PAGE_URL}`",
        "",
        "## Year Records",
        "",
        "| Year | Status | Rows | Snapshot | Source | Error |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for record in result.records:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(record.year),
                    record.status,
                    str(record.row_count),
                    record.snapshot_id or "",
                    str(record.source_path or record.official_url),
                    (record.error or "").replace("|", "\\|"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "Official ZIP files are preserved as raw snapshots first. Core normalization "
            "then parses only the preserved snapshot payload and writes "
            "`core_quote_daily.parquet`. Research factors and briefs must keep reading "
            "normalized core/research tables rather than exchange ZIP files.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    return "\n".join(lines) + "\n"


def _report_paths(
    *,
    years: tuple[int, ...],
    report_output_dir: Path | None,
) -> tuple[Path, Path]:
    root = report_output_dir or reports_dir() / "research" / REPORT_DIR
    stem = f"{PRODUCT_CODE}_{years[0]}_{years[-1]}_official_history_connect"
    return root / f"{stem}.json", root / f"{stem}.md"


def _default_core_output_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME


def _validate_years(years: tuple[int, ...]) -> tuple[int, ...]:
    if not years:
        raise ResearchWorkbenchError("at least one official history year is required")
    cleaned = tuple(dict.fromkeys(int(year) for year in years))
    for year in cleaned:
        _validate_year(year)
    return cleaned


def _validate_year(year: int) -> None:
    if year < 2020 or year > 2100:
        raise ResearchWorkbenchError(f"official history year out of supported range: {year}")
