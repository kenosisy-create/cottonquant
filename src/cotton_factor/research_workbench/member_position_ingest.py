"""R83 郑商所 CF 会员持仓排名下载、原始留存与 core 标准化。"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_bytes
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.core.schemas import CoreMemberPositionDailyRow
from cotton_factor.raw import RawSnapshotStore

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
SOURCE_NAME = "CZCE_CF_MEMBER_POSITION_HISTORY"
CORE_MEMBER_POSITION_FILE_NAME = "core_member_position_daily.parquet"
MEMBER_POSITION_INGEST_VERSION = "R85_member_position_incremental_ingest_v1"
MEMBER_POSITION_BACKFILL_VERSION = "R85_member_position_history_backfill_v1"
OFFICIAL_URL_TEMPLATE = (
    "https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{date_key}/"
    "FutureDataHolding{suffix}"
)
SUPPORTED_SUFFIXES = {".xlsx", ".xls", ".zip"}
EXPECTED_HEADERS = (
    "名次",
    "会员简称",
    "交易量（手）",
    "增减量",
    "会员简称",
    "持买仓量",
    "增减量",
    "会员简称",
    "持卖仓量",
    "增减量",
)
SIDE_COLUMNS = {
    "volume": (1, 2, 3),
    "long": (4, 5, 6),
    "short": (7, 8, 9),
}
HUMAN_REVIEW_REQUIRED = (
    "official_member_position_field_interpretation",
    "member_name_identity_and_customer_scope",
    "top_rank_concentration_denominator",
    "member_position_roll_migration_interpretation",
)


@dataclass(frozen=True)
class OfficialMemberPositionFetchResult:
    """单个交易日官方会员持仓文件下载结果。"""

    trade_date: date
    official_url: str
    status: str
    output_path: Path | None
    byte_size: int | None
    sha256: str | None
    json_path: Path
    markdown_path: Path
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status in {"DOWNLOADED", "EXISTS"}

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "trade_date": self.trade_date.isoformat(),
            "official_url": self.official_url,
            "status": self.status,
            "passed": self.passed,
            "output_path": None if self.output_path is None else str(self.output_path),
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "error": self.error,
        }


@dataclass(frozen=True)
class MemberPositionSourceRecord:
    """一个 incoming 源文件的留存和解析结果。"""

    source_path: Path
    status: str
    row_count: int = 0
    snapshot_id: str | None = None
    sha256: str | None = None
    error: str | None = None

    def to_summary(self) -> dict[str, object]:
        return {
            "source_path": str(self.source_path),
            "status": self.status,
            "row_count": self.row_count,
            "snapshot_id": self.snapshot_id,
            "sha256": self.sha256,
            "error": self.error,
        }


@dataclass(frozen=True)
class ResearchMemberPositionIngestResult:
    """R83 会员持仓 raw/core 接入结果。"""

    run_id: str
    status: str
    incoming_dir: Path
    raw_snapshot_count: int
    core_row_count: int
    date_count: int
    start: date | None
    end: date | None
    core_member_position_path: Path | None
    quality_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    source_records: tuple[MemberPositionSourceRecord, ...]

    @property
    def passed(self) -> bool:
        return self.status in {
            "COMPLETED",
            "NO_CHANGES",
            "MISSING_MEMBER_POSITION_HISTORY",
        }

    def to_summary(self) -> dict[str, object]:
        source_status_counts: dict[str, int] = {}
        for record in self.source_records:
            source_status_counts[record.status] = (
                source_status_counts.get(record.status, 0) + 1
            )
        return {
            "product_code": PRODUCT_CODE,
            "exchange": EXCHANGE,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "incoming_dir": str(self.incoming_dir),
            "raw_snapshot_count": self.raw_snapshot_count,
            "core_row_count": self.core_row_count,
            "date_count": self.date_count,
            "start": None if self.start is None else self.start.isoformat(),
            "end": None if self.end is None else self.end.isoformat(),
            "core_member_position_path": (
                None
                if self.core_member_position_path is None
                else str(self.core_member_position_path)
            ),
            "quality_csv_path": str(self.quality_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "source_file_count": len(self.source_records),
            "source_status_counts": source_status_counts,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


@dataclass(frozen=True)
class OfficialMemberPositionHistoryFetchResult:
    """按 core 真实交易日批量回补会员持仓文件的结果。"""

    start: date
    end: date
    status: str
    requested_date_count: int
    ready_date_count: int
    downloaded_date_count: int
    existing_date_count: int
    failed_date_count: int
    source_dir: Path
    status_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    records: tuple[OfficialMemberPositionFetchResult, ...]

    @property
    def passed(self) -> bool:
        return self.status == "COMPLETED"

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "status": self.status,
            "passed": self.passed,
            "requested_date_count": self.requested_date_count,
            "ready_date_count": self.ready_date_count,
            "downloaded_date_count": self.downloaded_date_count,
            "existing_date_count": self.existing_date_count,
            "failed_date_count": self.failed_date_count,
            "source_dir": str(self.source_dir),
            "status_csv_path": str(self.status_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "failed_dates": [
                record.trade_date.isoformat() for record in self.records if not record.passed
            ],
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def official_member_position_url(trade_date: date) -> str:
    """生成郑商所会员持仓日文件地址。"""
    return OFFICIAL_URL_TEMPLATE.format(
        year=trade_date.year,
        date_key=trade_date.strftime("%Y%m%d"),
        suffix=".xlsx",
    )


def official_member_position_urls(trade_date: date) -> tuple[str, str]:
    """按已验证年份优先级返回新旧两种官方扩展名地址。"""
    base = {
        "year": trade_date.year,
        "date_key": trade_date.strftime("%Y%m%d"),
    }
    suffixes = (".xlsx", ".xls") if trade_date.year >= 2026 else (".xls", ".xlsx")
    return tuple(
        OFFICIAL_URL_TEMPLATE.format(**base, suffix=suffix) for suffix in suffixes
    )


def fetch_cf_official_member_position(
    *,
    trade_date: date,
    source_dir: Path | None = None,
    report_output_dir: Path | None = None,
    overwrite: bool = False,
    official_url: str | None = None,
    fetcher: Callable[[str], bytes] | None = None,
    write_report: bool = True,
) -> OfficialMemberPositionFetchResult:
    """把官方日文件下载到 incoming，后续仍须由 connector 写入 raw/core。"""
    incoming_root = (
        source_dir
        or data_dir() / "incoming" / PRODUCT_CODE / "member_positions" / "history"
    )
    date_key = trade_date.strftime("%Y%m%d")
    output_dir = incoming_root / "daily" / str(trade_date.year) / date_key
    candidate_urls = (
        (official_url,)
        if official_url is not None
        else official_member_position_urls(trade_date)
    )
    report_root = report_output_dir or reports_dir() / "research" / "member_position_ingest"
    json_path = report_root / f"CF_{trade_date.isoformat()}_member_position_fetch.json"
    markdown_path = report_root / f"CF_{trade_date.isoformat()}_member_position_fetch.md"

    if not overwrite:
        for url in official_member_position_urls(trade_date):
            suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
            file_name = f"FutureDataHolding{suffix}"
            existing_path = output_dir / file_name
            if existing_path.exists():
                payload = existing_path.read_bytes()
                _validate_excel_payload(payload, url)
                result = OfficialMemberPositionFetchResult(
                    trade_date=trade_date,
                    official_url=url,
                    status="EXISTS",
                    output_path=existing_path,
                    byte_size=len(payload),
                    sha256=sha256_bytes(payload),
                    json_path=json_path,
                    markdown_path=markdown_path,
                )
                if write_report:
                    _write_fetch_outputs(result)
                return result

    errors: list[str] = []
    result: OfficialMemberPositionFetchResult | None = None
    for url in candidate_urls:
        try:
            payload = (fetcher or _download_url)(url)
            _validate_excel_payload(payload, url)
            suffix = ".xlsx" if url.lower().endswith(".xlsx") else ".xls"
            output_path = output_dir / f"FutureDataHolding{suffix}"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(payload)
            result = OfficialMemberPositionFetchResult(
                trade_date=trade_date,
                official_url=url,
                status="DOWNLOADED",
                output_path=output_path,
                byte_size=len(payload),
                sha256=sha256_bytes(payload),
                json_path=json_path,
                markdown_path=markdown_path,
            )
            break
        except ResearchWorkbenchError as exc:
            errors.append(str(exc))
    if result is None:
        result = OfficialMemberPositionFetchResult(
            trade_date=trade_date,
            official_url=str(candidate_urls[0]),
            status="DOWNLOAD_FAILED",
            output_path=None,
            byte_size=None,
            sha256=None,
            json_path=json_path,
            markdown_path=markdown_path,
            error=" | ".join(errors),
        )
    if write_report:
        _write_fetch_outputs(result)
    return result


def fetch_cf_official_member_position_history(
    *,
    start: date,
    end: date,
    core_quote_path: Path | None = None,
    source_dir: Path | None = None,
    report_output_dir: Path | None = None,
    overwrite: bool = False,
    max_workers: int = 4,
    fetcher: Callable[[str], bytes] | None = None,
) -> OfficialMemberPositionHistoryFetchResult:
    """依据 core 已确认交易日批量回补，避免向周末和节假日发请求。"""
    if start > end:
        raise ResearchWorkbenchError("member-position history start must be <= end")
    if max_workers < 1 or max_workers > 8:
        raise ResearchWorkbenchError("max_workers must be within 1..8")
    quote_path = core_quote_path or (
        data_dir() / "core" / PRODUCT_CODE / "core_quote_daily.parquet"
    )
    if not quote_path.exists():
        raise ResearchWorkbenchError(f"CF core quote not found: {quote_path}")
    quotes = pd.read_parquet(quote_path, columns=["trade_date"])
    parsed_dates = pd.to_datetime(quotes["trade_date"], errors="coerce").dt.date
    trade_dates = sorted(
        value for value in set(parsed_dates.dropna()) if start <= value <= end
    )
    if not trade_dates:
        raise ResearchWorkbenchError("no confirmed CF core trade dates in requested range")
    incoming_root = (
        source_dir
        or data_dir() / "incoming" / PRODUCT_CODE / "member_positions" / "history"
    )
    report_root = report_output_dir or reports_dir() / "research" / "member_position_ingest"
    records: list[OfficialMemberPositionFetchResult] = []

    # 并发只用于独立交易日下载；单日内部仍按 xlsx -> xls 的固定顺序回退。
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                fetch_cf_official_member_position,
                trade_date=trade_date,
                source_dir=incoming_root,
                report_output_dir=report_root,
                overwrite=overwrite,
                fetcher=fetcher,
                write_report=False,
            ): trade_date
            for trade_date in trade_dates
        }
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda record: record.trade_date)
    ready_count = sum(record.passed for record in records)
    downloaded_count = sum(record.status == "DOWNLOADED" for record in records)
    existing_count = sum(record.status == "EXISTS" for record in records)
    failed_count = len(records) - ready_count
    status = "COMPLETED" if failed_count == 0 else "PARTIAL" if ready_count else "FAILED"
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_member_position_history_fetch"
    result = OfficialMemberPositionHistoryFetchResult(
        start=start,
        end=end,
        status=status,
        requested_date_count=len(records),
        ready_date_count=ready_count,
        downloaded_date_count=downloaded_count,
        existing_date_count=existing_count,
        failed_date_count=failed_count,
        source_dir=incoming_root,
        status_csv_path=report_root / f"{stem}_status.csv",
        json_path=report_root / f"{stem}.json",
        markdown_path=report_root / f"{stem}.md",
        manifest_path=report_root / f"{stem}_manifest.json",
        records=tuple(records),
    )
    _write_history_fetch_outputs(result)
    return result


def connect_cf_member_position_history(
    *,
    source_dir: Path | None = None,
    raw_root: Path | None = None,
    core_output_dir: Path | None = None,
    output_path: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchMemberPositionIngestResult:
    """留存会员持仓官方文件，并把 CF 品种/合约排名写入 core 长表。"""
    active_run_id = run_id or f"r83_member_ingest_{utc_now().strftime('%Y%m%dT%H%M%SZ')}"
    incoming_dir = (
        source_dir
        or data_dir() / "incoming" / PRODUCT_CODE / "member_positions" / "history"
    )
    incoming_dir.mkdir(parents=True, exist_ok=True)
    core_path = output_path or (
        core_output_dir or data_dir() / "core" / PRODUCT_CODE
    ) / CORE_MEMBER_POSITION_FILE_NAME
    report_root = report_output_dir or reports_dir() / "research" / "member_position_ingest"
    quality_path = report_root / "CF_member_position_ingest_quality.csv"
    json_path = report_root / "CF_member_position_ingest.json"
    markdown_path = report_root / "CF_member_position_ingest.md"
    manifest_path = report_root / "CF_member_position_ingest_manifest.json"
    source_files = _source_files(incoming_dir)

    if not source_files:
        result = ResearchMemberPositionIngestResult(
            run_id=active_run_id,
            status="MISSING_MEMBER_POSITION_HISTORY",
            incoming_dir=incoming_dir,
            raw_snapshot_count=0,
            core_row_count=0,
            date_count=0,
            start=None,
            end=None,
            core_member_position_path=None,
            quality_csv_path=quality_path,
            json_path=json_path,
            markdown_path=markdown_path,
            manifest_path=manifest_path,
            source_records=(),
        )
        _write_ingest_outputs(result)
        return result

    store = RawSnapshotStore(raw_root)
    existing_core_hashes: dict[str, tuple[int, str]] = {}
    if core_path.exists():
        existing_core = pd.read_parquet(
            core_path,
            columns=["source_sha256", "source_snapshot_id"],
        )
        for checksum, group in existing_core.groupby("source_sha256", dropna=False):
            if pd.isna(checksum):
                continue
            existing_core_hashes[str(checksum)] = (
                len(group),
                str(group.iloc[0]["source_snapshot_id"]),
            )
    raw_records_by_hash = {
        record.sha256: record
        for record in store.find_records(
            source_name=SOURCE_NAME,
            product_code=PRODUCT_CODE,
        )
    }
    records: list[MemberPositionSourceRecord] = []
    rows: list[CoreMemberPositionDailyRow] = []
    new_raw_snapshot_count = 0
    for source_path in source_files:
        payload = source_path.read_bytes()
        checksum = sha256_bytes(payload)
        core_match = existing_core_hashes.get(checksum)
        if core_match is not None:
            row_count, snapshot_id = core_match
            records.append(
                MemberPositionSourceRecord(
                    source_path=source_path,
                    status="ALREADY_IN_CORE",
                    row_count=row_count,
                    snapshot_id=snapshot_id,
                    sha256=checksum,
                )
            )
            continue

        snapshot = raw_records_by_hash.get(checksum)
        parse_status = "PARSED_REUSED_RAW"
        if snapshot is None:
            snapshot = store.write_snapshot(
                payload=payload,
                source_name=SOURCE_NAME,
                product_code=PRODUCT_CODE,
                content_type=_content_type(source_path),
                biz_date=None,
                metadata={
                    "source_path": str(source_path),
                    "source_layer": "member_position_raw_snapshot",
                    "run_id": active_run_id,
                    "parser_version": MEMBER_POSITION_INGEST_VERSION,
                    "captured_at": utc_now().isoformat(),
                },
                parser_version=MEMBER_POSITION_INGEST_VERSION,
            )
            raw_records_by_hash[checksum] = snapshot
            new_raw_snapshot_count += 1
            parse_status = "PARSED_NEW_RAW"
        try:
            parsed = _parse_payload(
                payload=store.read_payload(snapshot.snapshot_id),
                source_path=source_path,
                snapshot_id=snapshot.snapshot_id,
                source_sha256=checksum,
            )
            rows.extend(parsed)
            records.append(
                MemberPositionSourceRecord(
                    source_path=source_path,
                    status=parse_status,
                    row_count=len(parsed),
                    snapshot_id=snapshot.snapshot_id,
                    sha256=checksum,
                )
            )
        except ResearchWorkbenchError as exc:
            records.append(
                MemberPositionSourceRecord(
                    source_path=source_path,
                    status="FORMAT_REVIEW_REQUIRED",
                    snapshot_id=snapshot.snapshot_id,
                    sha256=checksum,
                    error=str(exc),
                )
            )

    if any(record.status == "FORMAT_REVIEW_REQUIRED" for record in records):
        result = ResearchMemberPositionIngestResult(
            run_id=active_run_id,
            status="FORMAT_REVIEW_REQUIRED",
            incoming_dir=incoming_dir,
            raw_snapshot_count=new_raw_snapshot_count,
            core_row_count=0,
            date_count=0,
            start=None,
            end=None,
            core_member_position_path=None,
            quality_csv_path=quality_path,
            json_path=json_path,
            markdown_path=markdown_path,
            manifest_path=manifest_path,
            source_records=tuple(records),
        )
        _write_ingest_outputs(result)
        return result

    normalized_rows = _deduplicate_rows(rows)
    if normalized_rows:
        _write_core_replace_dates(core_path, normalized_rows)
        status = "COMPLETED"
    elif core_path.exists() and existing_core_hashes:
        status = "NO_CHANGES"
    else:
        raise ResearchWorkbenchError("member-position sources contain no CF ranking sections")
    core_row_count, dates = _core_member_position_coverage(core_path)
    result = ResearchMemberPositionIngestResult(
        run_id=active_run_id,
        status=status,
        incoming_dir=incoming_dir,
        raw_snapshot_count=new_raw_snapshot_count,
        core_row_count=core_row_count,
        date_count=len(dates),
        start=dates[0],
        end=dates[-1],
        core_member_position_path=core_path,
        quality_csv_path=quality_path,
        json_path=json_path,
        markdown_path=markdown_path,
        manifest_path=manifest_path,
        source_records=tuple(records),
    )
    _write_ingest_outputs(result)
    return result


def _source_files(source_dir: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in source_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_SUFFIXES
            and not path.name.startswith("~$")
        )
    )


def _core_member_position_coverage(output_path: Path) -> tuple[int, list[date]]:
    """读取增量合并后的 core 覆盖范围，报告总量而非本批次行数。"""
    frame = pd.read_parquet(output_path, columns=["trade_date"])
    parsed_dates = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    dates = sorted(set(parsed_dates.dropna()))
    return len(frame), dates


def _parse_payload(
    *,
    payload: bytes,
    source_path: Path,
    snapshot_id: str,
    source_sha256: str,
) -> list[CoreMemberPositionDailyRow]:
    if source_path.suffix.lower() != ".zip":
        return _parse_excel_payload(
            payload=payload,
            source_label=source_path.name,
            snapshot_id=snapshot_id,
            source_sha256=source_sha256,
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ResearchWorkbenchError(f"invalid member-position ZIP: {source_path}") from exc
    rows: list[CoreMemberPositionDailyRow] = []
    with archive:
        members = [
            name
            for name in archive.namelist()
            if Path(name).suffix.lower() in {".xlsx", ".xls"}
            and not Path(name).name.startswith("~$")
        ]
        if not members:
            raise ResearchWorkbenchError(f"member-position ZIP has no Excel file: {source_path}")
        for member in sorted(members):
            rows.extend(
                _parse_excel_payload(
                    payload=archive.read(member),
                    source_label=f"{source_path.name}!{member}",
                    snapshot_id=snapshot_id,
                    source_sha256=source_sha256,
                )
            )
    return rows


def _parse_excel_payload(
    *, payload: bytes, source_label: str, snapshot_id: str, source_sha256: str
) -> list[CoreMemberPositionDailyRow]:
    try:
        frame = pd.read_excel(io.BytesIO(payload), header=None, dtype=object)
    except Exception as exc:  # pandas 会保留具体引擎异常，外层统一转为业务错误。
        raise ResearchWorkbenchError(
            f"cannot read member-position workbook {source_label}: {exc}"
        ) from exc
    if frame.shape[1] < 10:
        raise ResearchWorkbenchError(
            f"member-position workbook has fewer than 10 columns: {source_label}"
        )

    rows: list[CoreMemberPositionDailyRow] = []
    cf_section_count = 0
    for row_index, value in frame.iloc[:, 0].items():
        section = _parse_section_header(value)
        if section is None or not _is_cf_section(section):
            continue
        cf_section_count += 1
        header_index = int(row_index) + 1
        if header_index >= len(frame):
            raise ResearchWorkbenchError(
                f"missing ranking header after {source_label}:{row_index + 1}"
            )
        _validate_header(frame.iloc[header_index, :10].tolist(), source_label, header_index)
        rank_rows: list[tuple[int, pd.Series]] = []
        cursor = header_index + 1
        while cursor < len(frame):
            first = frame.iat[cursor, 0]
            if _parse_section_header(first) is not None or _clean_text(first) == "合计":
                break
            rank = _optional_rank(first)
            if rank is None:
                if all(pd.isna(value) for value in frame.iloc[cursor, :10]):
                    cursor += 1
                    continue
                break
            rank_rows.append((rank, frame.iloc[cursor, :10]))
            cursor += 1
        ranks = [rank for rank, _ in rank_rows]
        if not ranks or ranks != list(range(1, len(ranks) + 1)):
            raise ResearchWorkbenchError(
                f"non-contiguous CF ranking rows in {source_label}:{header_index + 1}"
            )
        side_rank_counts = {
            side: sum(
                not _side_cells_are_empty(row, columns)
                for _, row in rank_rows
            )
            for side, columns in SIDE_COLUMNS.items()
        }
        for rank, row in rank_rows:
            for side, (member_col, value_col, change_col) in SIDE_COLUMNS.items():
                side_columns = (member_col, value_col, change_col)
                if _side_cells_are_empty(row, side_columns):
                    # 官方会用 '-' 表示该侧不足二十名；缺失排名不等同于零持仓。
                    continue
                member_name = _clean_text(row.iloc[member_col])
                if _is_empty_placeholder(member_name):
                    raise ResearchWorkbenchError(
                        f"missing member name in {source_label}:{cursor + 1}/{side}"
                    )
                side_rank_count = side_rank_counts[side]
                quality_flag = (
                    "normal"
                    if side_rank_count == 20
                    else f"PARTIAL_TOP_RANKS_{side_rank_count}"
                )
                rows.append(
                    CoreMemberPositionDailyRow(
                        source_snapshot_id=snapshot_id,
                        source_sha256=source_sha256,
                        source_file_name=source_label,
                        exchange=EXCHANGE,
                        product_code=PRODUCT_CODE,
                        trade_date=section["trade_date"],
                        scope_type=section["scope_type"],
                        scope_code=section["scope_code"],
                        contract_code=section["contract_code"],
                        position_side=side,
                        rank=rank,
                        member_name=member_name,
                        position_value=_required_non_negative_int(
                            row.iloc[value_col], source_label, cursor + 1, side
                        ),
                        position_change=_required_int(
                            row.iloc[change_col], source_label, cursor + 1, side
                        ),
                        data_quality_flag=quality_flag,
                    )
                )
    if cf_section_count == 0:
        raise ResearchWorkbenchError(f"no CF product or contract section in {source_label}")
    return rows


def _parse_section_header(value: object) -> dict[str, object] | None:
    text = _clean_text(value)
    if not text:
        return None
    date_match = re.search(r"日期[：:]\s*(\d{4}-\d{2}-\d{2})", text)
    if date_match is None:
        return None
    try:
        trade_date = date.fromisoformat(date_match.group(1))
    except ValueError as exc:
        raise ResearchWorkbenchError(f"invalid member-position title date: {text}") from exc
    product_match = re.match(r"品种[：:]\s*(.+?)\s+日期", text)
    if product_match is not None:
        return {
            "scope_type": "product",
            "scope_code": PRODUCT_CODE,
            "contract_code": None,
            "scope_label": product_match.group(1).strip(),
            "trade_date": trade_date,
        }
    contract_match = re.match(r"合约[：:]\s*([A-Za-z]+\d{3,4})\s+日期", text)
    if contract_match is not None:
        contract_code = contract_match.group(1).upper()
        return {
            "scope_type": "contract",
            "scope_code": contract_code,
            "contract_code": contract_code,
            "scope_label": contract_code,
            "trade_date": trade_date,
        }
    return None


def _is_cf_section(section: dict[str, object]) -> bool:
    if section["scope_type"] == "contract":
        return str(section["contract_code"]).startswith(PRODUCT_CODE)
    return PRODUCT_CODE in str(section["scope_label"]).upper()


def _validate_header(values: list[object], source_label: str, row_index: int) -> None:
    normalized = tuple(_normalize_header(value) for value in values)
    expected = tuple(_normalize_header(value) for value in EXPECTED_HEADERS)
    if normalized != expected:
        raise ResearchWorkbenchError(
            "official member-position field layout changed at "
            f"{source_label}:{row_index + 1}; HUMAN_REVIEW_REQUIRED"
        )


def _normalize_header(value: object) -> str:
    normalized = re.sub(r"\s+", "", _clean_text(value)).replace("(手)", "（手）")
    # 2021-2025 官方表使用“成交量”，2026 新表改为“交易量”，统一到同一字段语义。
    return normalized.replace("成交量（手）", "交易量（手）")


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _is_empty_placeholder(value: object) -> bool:
    return _clean_text(value) in {"", "-", "--", "—"}


def _side_cells_are_empty(row: pd.Series, columns: tuple[int, int, int]) -> bool:
    return all(_is_empty_placeholder(row.iloc[column]) for column in columns)


def _optional_rank(value: object) -> int | None:
    try:
        number = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 20 else None


def _required_non_negative_int(
    value: object, source_label: str, row_number: int, side: str
) -> int:
    result = _required_int(value, source_label, row_number, side)
    if result < 0:
        raise ResearchWorkbenchError(
            f"negative position value in {source_label}:{row_number}/{side}"
        )
    return result


def _required_int(value: object, source_label: str, row_number: int, side: str) -> int:
    text = _clean_text(value).replace(",", "")
    try:
        return int(float(text))
    except ValueError as exc:
        raise ResearchWorkbenchError(
            f"invalid integer in {source_label}:{row_number}/{side}: {value!r}"
        ) from exc


def _deduplicate_rows(
    rows: list[CoreMemberPositionDailyRow],
) -> list[CoreMemberPositionDailyRow]:
    by_key: dict[tuple[object, ...], CoreMemberPositionDailyRow] = {}
    for row in rows:
        key = (
            row.exchange,
            row.trade_date,
            row.scope_type,
            row.scope_code,
            row.position_side,
            row.rank,
        )
        existing = by_key.get(key)
        if existing is not None and (
            existing.member_name != row.member_name
            or existing.position_value != row.position_value
            or existing.position_change != row.position_change
        ):
            raise ResearchWorkbenchError(
                "conflicting duplicate member-position key: "
                f"{row.trade_date}/{row.scope_code}/{row.position_side}/{row.rank}"
            )
        by_key[key] = row
    return sorted(
        by_key.values(),
        key=lambda row: (
            row.trade_date,
            row.scope_type,
            row.scope_code,
            row.position_side,
            row.rank,
        ),
    )


def _write_core_replace_dates(
    output_path: Path, rows: list[CoreMemberPositionDailyRow]
) -> None:
    new_frame = pd.DataFrame([row.model_dump(mode="json") for row in rows])
    new_frame["trade_date"] = new_frame["trade_date"].astype(str)
    replace_dates = set(new_frame["trade_date"])
    if output_path.exists():
        existing = pd.read_parquet(output_path)
        required = {"trade_date", "product_code"}
        missing = required - set(existing.columns)
        if missing:
            raise ResearchWorkbenchError(
                f"existing member-position core missing columns: {sorted(missing)}"
            )
        existing["trade_date"] = existing["trade_date"].astype(str)
        keep = ~(
            existing["product_code"].astype(str).eq(PRODUCT_CODE)
            & existing["trade_date"].isin(replace_dates)
        )
        combined = pd.concat([existing.loc[keep], new_frame], ignore_index=True)
    else:
        combined = new_frame
    combined = combined.sort_values(
        ["trade_date", "scope_type", "scope_code", "position_side", "rank"]
    ).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, index=False)


def _download_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ResearchWorkbenchError(f"official member-position download failed: {exc}") from exc


def _validate_excel_payload(payload: bytes, url: str) -> None:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    is_xlsx = payload.startswith(b"PK")
    is_xls = payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    valid_signature = is_xlsx if suffix == ".xlsx" else is_xls if suffix == ".xls" else False
    if len(payload) < 1024 or not valid_signature:
        raise ResearchWorkbenchError(
            f"official member-position response is not a valid Excel payload: {url}"
        )


def _content_type(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        return "application/zip"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _write_fetch_outputs(result: OfficialMemberPositionFetchResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# CF 官方会员持仓文件下载",
        "",
        f"- 交易日：`{result.trade_date.isoformat()}`",
        f"- 状态：`{result.status}`",
        f"- 官方地址：`{result.official_url}`",
        f"- 本地文件：`{result.output_path or ''}`",
        f"- SHA256：`{result.sha256 or ''}`",
        f"- 错误：`{result.error or ''}`",
        "",
        "下载只进入 incoming；研究模块不得直接读取该文件，必须先写入 raw/core。",
    ]
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_history_fetch_outputs(
    result: OfficialMemberPositionHistoryFetchResult,
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    status_fields = [
        "trade_date",
        "official_url",
        "status",
        "output_path",
        "byte_size",
        "sha256",
        "error",
    ]
    with result.status_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=status_fields)
        writer.writeheader()
        for record in result.records:
            summary = record.to_summary()
            writer.writerow({field: summary.get(field) for field in status_fields})
    audit_payload = {
        **result.to_summary(),
        "records": [record.to_summary() for record in result.records],
    }
    result.json_path.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "report_type": "cf_member_position_history_backfill",
        "rule_version": MEMBER_POSITION_BACKFILL_VERSION,
        "generated_at_utc": utc_now().isoformat(),
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "status": result.status,
        "requested_date_count": result.requested_date_count,
        "ready_date_count": result.ready_date_count,
        "downloaded_date_count": result.downloaded_date_count,
        "existing_date_count": result.existing_date_count,
        "failed_date_count": result.failed_date_count,
        "status_csv_path": str(result.status_csv_path),
        "source_files": [
            {
                "trade_date": record.trade_date.isoformat(),
                "status": record.status,
                "path": None if record.output_path is None else str(record.output_path),
                "sha256": record.sha256,
            }
            for record in result.records
        ],
        "human_review_required": list(HUMAN_REVIEW_REQUIRED),
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# CF 官方会员持仓历史回补",
        "",
        f"- 区间：`{result.start}` 至 `{result.end}`",
        f"- 状态：`{result.status}`",
        f"- 请求交易日：`{result.requested_date_count}`",
        f"- 已就绪：`{result.ready_date_count}`",
        f"- 本次新下载：`{result.downloaded_date_count}`",
        f"- 断点复用：`{result.existing_date_count}`",
        f"- 失败：`{result.failed_date_count}`",
        f"- 状态清单：`{result.status_csv_path}`",
        f"- manifest：`{result.manifest_path}`",
        "",
        "下载日期只来自 core 中已确认的 CF 交易日。2021-2025 优先 `.xls`，",
        "2026 起优先 `.xlsx`，失败时回退另一格式。下载后仍须运行 raw/core connector。",
        "重复执行默认复用 incoming 中校验通过的已有文件，不重复下载。",
        "",
        "## 失败日期",
        "",
    ]
    failures = [record for record in result.records if not record.passed]
    if not failures:
        lines.append("无。")
    else:
        lines.extend(
            f"- `{record.trade_date}`：{record.error or record.status}"
            for record in failures
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 回填只建立会员排名历史证据，不代表可识别客户或机构净敞口。",
            "- 下载失败日期必须保留在状态清单中，不以期货总持仓替代。",
            "- 本模块不修改 composite_score，不构成交易指令。",
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ingest_outputs(result: ResearchMemberPositionIngestResult) -> None:
    result.quality_csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source_path", "status", "row_count", "snapshot_id", "sha256", "error"]
    with result.quality_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(record.to_summary() for record in result.source_records)
    result.json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "report_type": "cf_member_position_ingest",
        "rule_version": MEMBER_POSITION_INGEST_VERSION,
        "run_id": result.run_id,
        "status": result.status,
        "generated_at_utc": utc_now().isoformat(),
        "input_dir": str(result.incoming_dir),
        "output_path": (
            None
            if result.core_member_position_path is None
            else str(result.core_member_position_path)
        ),
        "source_checksums": [
            {"source_path": str(record.source_path), "sha256": record.sha256}
            for record in result.source_records
        ],
        "human_review_required": list(HUMAN_REVIEW_REQUIRED),
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# CF 会员持仓排名接入报告",
        "",
        "## 数据状态",
        "",
        f"- 状态：`{result.status}`",
        f"- 覆盖交易日：`{result.date_count}`",
        f"- 日期范围：`{result.start or ''}` 至 `{result.end or ''}`",
        f"- core 总行数：`{result.core_row_count}`",
        f"- 本次新增 raw 快照：`{result.raw_snapshot_count}`",
        f"- core：`{result.core_member_position_path or ''}`",
        "",
        "## 字段口径",
        "",
        "- 官方表的交易量、持买仓量、持卖仓量分别按 `volume/long/short` 长表保存。",
        "- 每一侧会员名称独立保存，不能假设同一名次对应同一会员。",
        "- 品种汇总与分合约排名通过 `scope_type` 明确区分。",
        "",
        "## 研究边界",
        "",
        "会员排名是期货公司会员口径，可能包含代客汇总，不等同于可识别客户或机构的真实净敞口。",
        "接入过程不生成交易指令；字段解释存在变更时状态会转为 `FORMAT_REVIEW_REQUIRED`。",
        "校验和已存在于 core 的文件会标记为 `ALREADY_IN_CORE`，不会重复生成 raw 快照。",
        "",
        "## HUMAN_REVIEW_REQUIRED",
        "",
    ]
    lines.extend(f"- `{item}`" for item in HUMAN_REVIEW_REQUIRED)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
