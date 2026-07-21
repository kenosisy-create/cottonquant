"""CZCE official daily file fetcher for CF futures and options."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_bytes
from cotton_factor.common.paths import data_dir, reports_dir

PRODUCT_CODE = "CF"
OFFICIAL_DAILY_DATE_FORMAT = "YYYYMMDD"
FUTURES_DAILY_URL_TEMPLATE = (
    "https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{date_key}/"
    "FutureDataDailyCF.xlsx"
)
OPTIONS_DAILY_URL_TEMPLATE = (
    "https://www.czce.com.cn/cn/DFSStaticFiles/Option/{year}/{date_key}/"
    "OptionDataDaily.xlsx"
)
REPORT_DIR = "official_daily_files"
DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.czce.com.cn/",
}

DailyFileKind = Literal["futures", "options"]
DailyFetchStatus = Literal["DOWNLOADED", "EXISTS", "SKIPPED", "DOWNLOAD_FAILED"]


@dataclass(frozen=True)
class OfficialDailyFileRecord:
    """One official daily file fetch record."""

    file_kind: DailyFileKind
    trade_date: date
    official_url: str
    output_path: Path | None
    status: DailyFetchStatus
    byte_size: int | None = None
    sha256: str | None = None
    error: str | None = None

    @property
    def ready(self) -> bool:
        """Return whether the file is available locally."""
        return self.status in {"DOWNLOADED", "EXISTS", "SKIPPED"}

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable record."""
        return {
            "file_kind": self.file_kind,
            "trade_date": self.trade_date.isoformat(),
            "official_url": self.official_url,
            "output_path": None if self.output_path is None else str(self.output_path),
            "status": self.status,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "error": self.error,
        }


@dataclass(frozen=True)
class OfficialDailyFilesFetchResult:
    """Result of fetching official daily futures/options files."""

    product_code: str
    run_id: str
    trade_date: date
    date_key: str
    status: str
    include_options: bool
    futures_source_dir: Path
    options_source_dir: Path
    futures_connect_source_dir: Path
    options_connect_source_dir: Path
    json_path: Path
    markdown_path: Path
    records: tuple[OfficialDailyFileRecord, ...]

    @property
    def passed(self) -> bool:
        """Return whether all requested official files are available."""
        required = [
            record
            for record in self.records
            if record.file_kind == "futures"
            or (self.include_options and record.file_kind == "options")
        ]
        return bool(required) and all(record.ready for record in required)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        futures_record = _record_by_kind(self.records, "futures")
        options_record = _record_by_kind(self.records, "options")
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "date_key": self.date_key,
            "date_format": OFFICIAL_DAILY_DATE_FORMAT,
            "status": self.status,
            "passed": self.passed,
            "include_options": self.include_options,
            "futures_url": None if futures_record is None else futures_record.official_url,
            "options_url": None if options_record is None else options_record.official_url,
            "futures_path": (
                None
                if futures_record is None or futures_record.output_path is None
                else str(futures_record.output_path)
            ),
            "options_path": (
                None
                if options_record is None or options_record.output_path is None
                else str(options_record.output_path)
            ),
            "futures_source_dir": str(self.futures_source_dir),
            "options_source_dir": str(self.options_source_dir),
            "futures_connect_source_dir": str(self.futures_connect_source_dir),
            "options_connect_source_dir": str(self.options_connect_source_dir),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "records": [record.to_summary() for record in self.records],
        }


def official_daily_date_key(trade_date: date) -> str:
    """Return the CZCE daily URL date key, e.g. 20260706."""
    return trade_date.strftime("%Y%m%d")


def official_daily_file_url(*, trade_date: date, file_kind: DailyFileKind) -> str:
    """Return the official daily file URL for futures or options."""
    template = (
        FUTURES_DAILY_URL_TEMPLATE
        if file_kind == "futures"
        else OPTIONS_DAILY_URL_TEMPLATE
    )
    return template.format(
        year=trade_date.year,
        date_key=official_daily_date_key(trade_date),
    )


def official_daily_file_urls(trade_date: date) -> dict[str, str]:
    """Return both CF futures and all-product option daily URLs."""
    return {
        "futures": official_daily_file_url(trade_date=trade_date, file_kind="futures"),
        "options": official_daily_file_url(trade_date=trade_date, file_kind="options"),
    }


def fetch_cf_official_daily_files(
    *,
    trade_date: date | None = None,
    futures_source_dir: Path | None = None,
    options_source_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    include_options: bool = True,
    overwrite: bool = False,
    futures_url: str | None = None,
    options_url: str | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> OfficialDailyFilesFetchResult:
    """Fetch official daily files into incoming storage.

    下载层只负责把交易所文件落到 incoming。后续 raw snapshot 和 core 标准化
    仍由现有 futures/options connector 完成，避免研究代码直接读取交易所文件。
    """
    active_date = trade_date or date.today()
    date_key = official_daily_date_key(active_date)
    if len(date_key) != 8:
        raise ResearchWorkbenchError(f"invalid CZCE daily date key: {date_key}")
    fetch_run_id = run_id or _default_run_id(active_date)
    futures_root = futures_source_dir or data_dir() / "incoming" / PRODUCT_CODE / "history"
    options_root = (
        options_source_dir
        or data_dir() / "incoming" / PRODUCT_CODE / "options" / "history"
    )
    futures_connect_dir = futures_root / "daily" / str(active_date.year) / date_key
    options_connect_dir = options_root / "daily" / str(active_date.year) / date_key
    futures_path = futures_connect_dir / "FutureDataDailyCF.xlsx"
    options_path = options_connect_dir / "OptionDataDaily.xlsx"
    effective_fetcher = fetcher or _download_url

    records = [
        _fetch_one(
            file_kind="futures",
            trade_date=active_date,
            official_url=futures_url
            or official_daily_file_url(trade_date=active_date, file_kind="futures"),
            output_path=futures_path,
            overwrite=overwrite,
            fetcher=effective_fetcher,
        )
    ]
    if include_options:
        records.append(
            _fetch_one(
                file_kind="options",
                trade_date=active_date,
                official_url=options_url
                or official_daily_file_url(trade_date=active_date, file_kind="options"),
                output_path=options_path,
                overwrite=overwrite,
                fetcher=effective_fetcher,
            )
        )
    else:
        records.append(
            OfficialDailyFileRecord(
                file_kind="options",
                trade_date=active_date,
                official_url=options_url
                or official_daily_file_url(trade_date=active_date, file_kind="options"),
                output_path=None,
                status="SKIPPED",
            )
        )

    json_path, markdown_path = _report_paths(
        trade_date=active_date,
        report_output_dir=report_output_dir,
    )
    result = OfficialDailyFilesFetchResult(
        product_code=PRODUCT_CODE,
        run_id=fetch_run_id,
        trade_date=active_date,
        date_key=date_key,
        status=_result_status(records=tuple(records), include_options=include_options),
        include_options=include_options,
        futures_source_dir=futures_root,
        options_source_dir=options_root,
        futures_connect_source_dir=futures_connect_dir,
        options_connect_source_dir=options_connect_dir,
        json_path=json_path,
        markdown_path=markdown_path,
        records=tuple(records),
    )
    _write_reports(result)
    return result


def _fetch_one(
    *,
    file_kind: DailyFileKind,
    trade_date: date,
    official_url: str,
    output_path: Path,
    overwrite: bool,
    fetcher: Callable[[str], bytes],
) -> OfficialDailyFileRecord:
    if output_path.exists() and not overwrite:
        payload = output_path.read_bytes()
        return OfficialDailyFileRecord(
            file_kind=file_kind,
            trade_date=trade_date,
            official_url=official_url,
            output_path=output_path,
            status="EXISTS",
            byte_size=len(payload),
            sha256=sha256_bytes(payload),
        )
    try:
        payload = fetcher(official_url)
        _validate_xlsx_payload(payload=payload, official_url=official_url)
    except ResearchWorkbenchError as exc:
        return OfficialDailyFileRecord(
            file_kind=file_kind,
            trade_date=trade_date,
            official_url=official_url,
            output_path=output_path,
            status="DOWNLOAD_FAILED",
            error=str(exc),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return OfficialDailyFileRecord(
        file_kind=file_kind,
        trade_date=trade_date,
        official_url=official_url,
        output_path=output_path,
        status="DOWNLOADED",
        byte_size=len(payload),
        sha256=sha256_bytes(payload),
    )


def _download_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers=DOWNLOAD_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            status = getattr(response, "status", None)
    except urllib.error.HTTPError as exc:
        raise ResearchWorkbenchError(f"HTTP {exc.code} from official daily URL: {url}") from exc
    except urllib.error.URLError as exc:
        raise ResearchWorkbenchError(
            f"network error from official daily URL {url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise ResearchWorkbenchError(f"timeout fetching official daily URL: {url}") from exc
    if status is not None and int(status) >= 400:
        raise ResearchWorkbenchError(f"HTTP {status} from official daily URL: {url}")
    return payload


def _validate_xlsx_payload(*, payload: bytes, official_url: str) -> None:
    if not payload.startswith(b"PK"):
        raise ResearchWorkbenchError(
            "official daily response is not an XLSX payload; "
            f"byte_size={len(payload)} sha256={sha256_bytes(payload)} url={official_url}"
        )


def _result_status(
    *,
    records: tuple[OfficialDailyFileRecord, ...],
    include_options: bool,
) -> str:
    required = [
        record
        for record in records
        if record.file_kind == "futures"
        or (include_options and record.file_kind == "options")
    ]
    if required and all(record.ready for record in required):
        return "COMPLETED"
    if any(record.status == "DOWNLOAD_FAILED" for record in required):
        return "DOWNLOAD_FAILED"
    return "PARTIAL"


def _record_by_kind(
    records: tuple[OfficialDailyFileRecord, ...],
    file_kind: DailyFileKind,
) -> OfficialDailyFileRecord | None:
    for record in records:
        if record.file_kind == file_kind:
            return record
    return None


def _write_reports(result: OfficialDailyFilesFetchResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result.markdown_path.write_text(_markdown_report(result), encoding="utf-8")


def _markdown_report(result: OfficialDailyFilesFetchResult) -> str:
    lines = [
        f"# CF 官方日频文件下载 - {result.trade_date.isoformat()}",
        "",
        "## 日期格式",
        "",
        f"- URL 年份目录：`{result.trade_date.year}`",
        f"- URL 日期目录：`{result.date_key}`",
        f"- 日期格式：`{OFFICIAL_DAILY_DATE_FORMAT}`",
        "",
        "## 下载状态",
        "",
        f"- 状态：`{result.status}`",
        f"- Run ID：`{result.run_id}`",
        f"- 期货 incoming：`{result.futures_connect_source_dir}`",
        f"- 期权 incoming：`{result.options_connect_source_dir}`",
        "",
        "| 文件 | 状态 | URL | 本地路径 | SHA256 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in result.records:
        lines.append(
            "| "
            + " | ".join(
                [
                    record.file_kind,
                    record.status,
                    record.official_url,
                    "" if record.output_path is None else str(record.output_path),
                    record.sha256 or "",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 本步骤只下载官方日频文件并保存到 incoming。",
            "- raw snapshot、core 标准化和研究报告仍由后续 connector 负责。",
            "- 官方字段口径、成交额单位和期权字段解释仍需人工复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def _report_paths(
    *,
    trade_date: date,
    report_output_dir: Path | None,
) -> tuple[Path, Path]:
    root = report_output_dir or reports_dir() / "research" / REPORT_DIR
    stem = f"{PRODUCT_CODE}_{trade_date.isoformat()}_official_daily_files"
    return root / f"{stem}.json", root / f"{stem}.md"


def _default_run_id(trade_date: date) -> str:
    return f"official_daily_{PRODUCT_CODE}_{trade_date.isoformat()}_{uuid.uuid4().hex[:8]}"
