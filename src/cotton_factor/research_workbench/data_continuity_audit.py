"""R63 CF daily data continuity and retention audit."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_file
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.option_data_contract import CORE_OPTION_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
DATA_CONTINUITY_AUDIT_VERSION = "R63_cf_data_continuity_audit_v1"
INFO_SEVERITY = "INFO"
WARN_SEVERITY = "WARN"
ERROR_SEVERITY = "ERROR"
AuditSeverity = Literal["INFO", "WARN", "ERROR"]

HUMAN_REVIEW_REQUIRED = (
    "official_calendar_continuity_review",
    "raw_snapshot_retention_review",
    "official_daily_download_retention_policy",
    "official_option_field_interpretation",
)

WARNING_COLUMNS = [
    "run_id",
    "trade_date",
    "dataset",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
]


@dataclass(frozen=True)
class DataContinuityWarningRecord:
    """One warning/error row for the R63 data continuity audit."""

    run_id: str
    trade_date: date
    dataset: str
    severity: AuditSeverity
    warning_code: str
    warning_message: str
    human_review_required: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "dataset": self.dataset,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class DataContinuityDatasetAudit:
    """Normalized audit summary for one retained core dataset."""

    dataset: str
    path: Path
    exists: bool
    row_count: int
    date_count: int
    latest_trade_date: date | None
    target_row_count: int
    target_contract_count: int
    duplicate_key_count: int
    missing_trading_dates: tuple[date, ...]
    source_snapshot_ids: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable dataset summary."""
        return {
            "dataset": self.dataset,
            "path": str(self.path),
            "exists": self.exists,
            "row_count": self.row_count,
            "date_count": self.date_count,
            "latest_trade_date": (
                None if self.latest_trade_date is None else self.latest_trade_date.isoformat()
            ),
            "target_row_count": self.target_row_count,
            "target_contract_count": self.target_contract_count,
            "duplicate_key_count": self.duplicate_key_count,
            "missing_trading_dates": [value.isoformat() for value in self.missing_trading_dates],
            "source_snapshot_ids": list(self.source_snapshot_ids),
        }


@dataclass(frozen=True)
class ResearchDataContinuityAuditResult:
    """Result of R63 CF data continuity and retention audit."""

    product_code: str
    exchange: str
    run_id: str
    trade_date: date
    continuity_status: str
    core_quote_path: Path
    option_core_path: Path
    calendar_path: Path | None
    official_daily_fetch_json_path: Path | None
    raw_root: Path
    markdown_path: Path
    json_path: Path
    warning_csv_path: Path
    manifest_path: Path
    futures_audit: DataContinuityDatasetAudit
    option_audit: DataContinuityDatasetAudit | None
    official_daily_fetch_audit: dict[str, object]
    raw_retention_audit: dict[str, object]
    downloaded_file_paths: tuple[Path, ...]
    warning_records: tuple[DataContinuityWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def error_count(self) -> int:
        """Return hard-stop error count."""
        return sum(1 for warning in self.warning_records if warning.severity == ERROR_SEVERITY)

    @property
    def warning_count(self) -> int:
        """Return non-info warning and error count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    @property
    def passed(self) -> bool:
        """Return whether data continuity is safe enough for the daily chain to proceed."""
        return self.error_count == 0

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "exchange": self.exchange,
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "continuity_status": self.continuity_status,
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "core_latest_trade_date": (
                None
                if self.futures_audit.latest_trade_date is None
                else self.futures_audit.latest_trade_date.isoformat()
            ),
            "option_latest_trade_date": (
                None
                if self.option_audit is None or self.option_audit.latest_trade_date is None
                else self.option_audit.latest_trade_date.isoformat()
            ),
            "core_quote_path": str(self.core_quote_path),
            "option_core_path": str(self.option_core_path),
            "calendar_path": None if self.calendar_path is None else str(self.calendar_path),
            "official_daily_fetch_json_path": (
                None
                if self.official_daily_fetch_json_path is None
                else str(self.official_daily_fetch_json_path)
            ),
            "raw_root": str(self.raw_root),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "warning_csv_path": str(self.warning_csv_path),
            "manifest_path": str(self.manifest_path),
            "downloaded_file_paths": [str(path) for path in self.downloaded_file_paths],
            "futures_audit": self.futures_audit.to_summary(),
            "option_audit": None if self.option_audit is None else self.option_audit.to_summary(),
            "official_daily_fetch_audit": self.official_daily_fetch_audit,
            "raw_retention_audit": self.raw_retention_audit,
            "human_review_required": list(self.human_review_required),
        }


def build_cf_data_continuity_audit(
    *,
    trade_date: date | None = None,
    core_quote_path: Path | None = None,
    option_core_path: Path | None = None,
    calendar_path: Path | None = None,
    official_daily_fetch_json_path: Path | None = None,
    raw_root: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    require_options: bool = True,
    require_raw_retention: bool = True,
) -> ResearchDataContinuityAuditResult:
    """Build a daily data continuity audit from retained core/raw artifacts.

    R63 只读取 core parquet、官方日更下载摘要和 raw manifest，不解析交易所
    原始 Excel/ZIP，避免研究层绕过标准化数据链路。
    """
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    option_path = (
        option_core_path
        or data_dir() / "core" / PRODUCT_CODE / CORE_OPTION_QUOTE_FILE_NAME
    )
    raw_store_root = raw_root or data_dir() / "raw"
    futures_frame = _read_table_if_exists(quote_path)
    target_trade_date = trade_date or _latest_trade_date(futures_frame)
    if target_trade_date is None:
        raise ResearchWorkbenchError(
            "cannot resolve data continuity audit date; provide --date or a non-empty "
            f"core quote table: {quote_path}"
        )
    audit_run_id = run_id or _default_run_id(target_trade_date)
    active_calendar_path = calendar_path or _default_calendar_path(target_trade_date)
    warnings: list[DataContinuityWarningRecord] = []

    expected_dates = _expected_trading_dates(
        calendar_path=active_calendar_path,
        target_trade_date=target_trade_date,
        run_id=audit_run_id,
        warnings=warnings,
    )
    futures_audit = _audit_dataset(
        dataset="futures_core",
        path=quote_path,
        frame=futures_frame,
        key_columns=("exchange", "contract_code", "trade_date"),
        contract_column="contract_code",
        target_trade_date=target_trade_date,
        expected_dates=expected_dates,
        run_id=audit_run_id,
        required=True,
        warnings=warnings,
    )
    option_audit: DataContinuityDatasetAudit | None = None
    option_frame = _read_table_if_exists(option_path)
    if require_options or option_frame is not None:
        option_audit = _audit_dataset(
            dataset="option_core",
            path=option_path,
            frame=option_frame,
            key_columns=("exchange", "option_symbol", "trade_date"),
            contract_column="option_symbol",
            target_trade_date=target_trade_date,
            expected_dates=expected_dates,
            run_id=audit_run_id,
            required=require_options,
            warnings=warnings,
        )
    else:
        _append_warning(
            warnings,
            run_id=audit_run_id,
            trade_date=target_trade_date,
            dataset="option_core",
            severity=INFO_SEVERITY,
            warning_code="OPTION_CORE_CHECK_SKIPPED",
            warning_message="本次未要求期权 core 连续性检查。",
            human_review_required=(),
        )

    official_audit = _audit_official_daily_fetch(
        official_daily_fetch_json_path=official_daily_fetch_json_path,
        target_trade_date=target_trade_date,
        require_options=require_options,
        run_id=audit_run_id,
        warnings=warnings,
    )
    raw_audit = _audit_raw_retention(
        raw_root=raw_store_root,
        target_trade_date=target_trade_date,
        require_raw_retention=require_raw_retention,
        futures_audit=futures_audit,
        option_audit=option_audit,
        run_id=audit_run_id,
        warnings=warnings,
    )
    downloaded_file_paths = _verified_downloaded_paths(official_audit)
    status = _continuity_status(warnings)
    paths = _output_paths(trade_date=target_trade_date, output_root=output_root)
    result = ResearchDataContinuityAuditResult(
        product_code=PRODUCT_CODE,
        exchange=EXCHANGE,
        run_id=audit_run_id,
        trade_date=target_trade_date,
        continuity_status=status,
        core_quote_path=quote_path,
        option_core_path=option_path,
        calendar_path=active_calendar_path if active_calendar_path.exists() else None,
        official_daily_fetch_json_path=official_daily_fetch_json_path,
        raw_root=raw_store_root,
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        warning_csv_path=paths["warning_csv"],
        manifest_path=paths["manifest"],
        futures_audit=futures_audit,
        option_audit=option_audit,
        official_daily_fetch_audit=official_audit,
        raw_retention_audit=raw_audit,
        downloaded_file_paths=downloaded_file_paths,
        warning_records=tuple(warnings),
        human_review_required=_human_review_required(tuple(warnings)),
    )
    _write_outputs(result)
    return result


def _read_table_if_exists(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    if "trade_date" in frame.columns:
        frame = frame.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def _latest_trade_date(frame: pd.DataFrame | None) -> date | None:
    if frame is None or "trade_date" not in frame.columns or frame.empty:
        return None
    values = [value for value in frame["trade_date"].tolist() if isinstance(value, date)]
    return max(values) if values else None


def _audit_dataset(
    *,
    dataset: str,
    path: Path,
    frame: pd.DataFrame | None,
    key_columns: tuple[str, ...],
    contract_column: str,
    target_trade_date: date,
    expected_dates: tuple[date, ...],
    run_id: str,
    required: bool,
    warnings: list[DataContinuityWarningRecord],
) -> DataContinuityDatasetAudit:
    if frame is None:
        severity: AuditSeverity = ERROR_SEVERITY if required else INFO_SEVERITY
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=severity,
            warning_code=f"{dataset.upper()}_MISSING",
            warning_message=f"未找到 {dataset} core 表：{path}",
            human_review_required=("raw_snapshot_retention_review",),
        )
        return DataContinuityDatasetAudit(
            dataset=dataset,
            path=path,
            exists=False,
            row_count=0,
            date_count=0,
            latest_trade_date=None,
            target_row_count=0,
            target_contract_count=0,
            duplicate_key_count=0,
            missing_trading_dates=(),
            source_snapshot_ids=(),
        )

    required_columns = set(key_columns) | {contract_column, "source_snapshot_id"}
    missing_columns = sorted(required_columns.difference(frame.columns))
    if missing_columns:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=ERROR_SEVERITY,
            warning_code=f"{dataset.upper()}_SCHEMA_MISSING_COLUMNS",
            warning_message=f"{dataset} 缺少必要列：{', '.join(missing_columns)}",
            human_review_required=("official_exchange_field_interpretation",),
        )
        return DataContinuityDatasetAudit(
            dataset=dataset,
            path=path,
            exists=True,
            row_count=int(len(frame)),
            date_count=0,
            latest_trade_date=None,
            target_row_count=0,
            target_contract_count=0,
            duplicate_key_count=0,
            missing_trading_dates=(),
            source_snapshot_ids=(),
        )

    working = frame.copy()
    if "product_code" in working.columns:
        working = working.loc[working["product_code"].astype(str).str.upper() == PRODUCT_CODE]
    observed_dates = tuple(sorted(set(_date_values(working["trade_date"].tolist()))))
    latest = max(observed_dates) if observed_dates else None
    target_rows = working.loc[working["trade_date"] == target_trade_date].copy()
    duplicate_count = int(working.duplicated(list(key_columns), keep=False).sum())
    source_ids = tuple(
        sorted(
            {
                str(value).strip()
                for value in target_rows["source_snapshot_id"].tolist()
                if str(value).strip()
            }
        )
    )
    missing_dates = _missing_expected_dates(
        observed_dates=observed_dates,
        expected_dates=expected_dates,
        target_trade_date=target_trade_date,
    )

    if latest is None:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=ERROR_SEVERITY,
            warning_code=f"{dataset.upper()}_EMPTY",
            warning_message=f"{dataset} 表存在但没有可用交易日。",
            human_review_required=("raw_snapshot_retention_review",),
        )
    elif latest != target_trade_date:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=ERROR_SEVERITY,
            warning_code=f"{dataset.upper()}_LATEST_DATE_MISMATCH",
            warning_message=(
                f"{dataset} 最新交易日为 {latest.isoformat()}，"
                f"不是目标日 {target_trade_date.isoformat()}。"
            ),
            human_review_required=("official_calendar_continuity_review",),
        )
    if target_rows.empty:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=ERROR_SEVERITY,
            warning_code=f"{dataset.upper()}_TARGET_DATE_MISSING",
            warning_message=f"{dataset} 未包含目标交易日 {target_trade_date.isoformat()}。",
            human_review_required=("raw_snapshot_retention_review",),
        )
    if duplicate_count:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=ERROR_SEVERITY,
            warning_code=f"{dataset.upper()}_DUPLICATE_KEYS",
            warning_message=f"{dataset} 存在 {duplicate_count} 行重复主键记录。",
            human_review_required=("official_exchange_field_interpretation",),
        )
    if missing_dates:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=ERROR_SEVERITY,
            warning_code=f"{dataset.upper()}_MISSING_TRADING_DATES",
            warning_message=(
                f"{dataset} 缺少官方交易日："
                + "、".join(value.isoformat() for value in missing_dates[:10])
                + (" ..." if len(missing_dates) > 10 else "")
            ),
            human_review_required=("official_calendar_continuity_review",),
        )
    if target_rows.empty is False and not source_ids:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=dataset,
            severity=ERROR_SEVERITY,
            warning_code=f"{dataset.upper()}_SOURCE_SNAPSHOT_ID_MISSING",
            warning_message=f"{dataset} 目标日记录缺少 source_snapshot_id，无法确认 raw 留存。",
            human_review_required=("raw_snapshot_retention_review",),
        )

    target_contract_count = (
        int(target_rows[contract_column].nunique()) if not target_rows.empty else 0
    )
    return DataContinuityDatasetAudit(
        dataset=dataset,
        path=path,
        exists=True,
        row_count=int(len(working)),
        date_count=len(observed_dates),
        latest_trade_date=latest,
        target_row_count=int(len(target_rows)),
        target_contract_count=target_contract_count,
        duplicate_key_count=duplicate_count,
        missing_trading_dates=missing_dates,
        source_snapshot_ids=source_ids,
    )


def _expected_trading_dates(
    *,
    calendar_path: Path,
    target_trade_date: date,
    run_id: str,
    warnings: list[DataContinuityWarningRecord],
) -> tuple[date, ...]:
    if not calendar_path.exists():
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="calendar",
            severity=WARN_SEVERITY,
            warning_code="OFFICIAL_CALENDAR_MISSING",
            warning_message=f"未找到官方交易日历，无法完整检查交易日缺口：{calendar_path}",
            human_review_required=("official_calendar_continuity_review",),
        )
        return ()
    frame = pd.read_csv(calendar_path)
    required_columns = {"trade_date", "is_trading_day"}
    missing_columns = sorted(required_columns.difference(frame.columns))
    if missing_columns:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="calendar",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_CALENDAR_SCHEMA_MISSING_COLUMNS",
            warning_message=f"官方交易日历缺少必要列：{', '.join(missing_columns)}",
            human_review_required=("official_calendar_continuity_review",),
        )
        return ()
    working = frame.copy()
    if "exchange" in working.columns:
        working = working.loc[working["exchange"].astype(str).str.upper() == EXCHANGE]
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working = working.loc[
        (working["trade_date"].map(lambda value: value.year == target_trade_date.year))
        & (working["trade_date"] <= target_trade_date)
        & (working["is_trading_day"].map(_truthy))
    ]
    return tuple(sorted(set(_date_values(working["trade_date"].tolist()))))


def _missing_expected_dates(
    *,
    observed_dates: tuple[date, ...],
    expected_dates: tuple[date, ...],
    target_trade_date: date,
) -> tuple[date, ...]:
    if not observed_dates or not expected_dates:
        return ()
    observed_for_year = [value for value in observed_dates if value.year == target_trade_date.year]
    if not observed_for_year:
        return ()
    start_date = min(observed_for_year)
    expected_slice = [
        value for value in expected_dates if start_date <= value <= target_trade_date
    ]
    observed_set = set(observed_dates)
    return tuple(value for value in expected_slice if value not in observed_set)


def _audit_official_daily_fetch(
    *,
    official_daily_fetch_json_path: Path | None,
    target_trade_date: date,
    require_options: bool,
    run_id: str,
    warnings: list[DataContinuityWarningRecord],
) -> dict[str, object]:
    if official_daily_fetch_json_path is None:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="official_daily_fetch",
            severity=INFO_SEVERITY,
            warning_code="OFFICIAL_DAILY_FETCH_JSON_NOT_PROVIDED",
            warning_message="未提供官方日更下载摘要，本次仅检查 core/raw 留存。",
            human_review_required=(),
        )
        return {"provided": False, "verified_file_paths": []}
    if not official_daily_fetch_json_path.exists():
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="official_daily_fetch",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_DAILY_FETCH_JSON_MISSING",
            warning_message=f"未找到官方日更下载摘要：{official_daily_fetch_json_path}",
            human_review_required=("official_daily_download_retention_policy",),
        )
        return {"provided": True, "exists": False, "verified_file_paths": []}

    payload = json.loads(official_daily_fetch_json_path.read_text(encoding="utf-8"))
    status = str(payload.get("status") or "")
    payload_trade_date = str(payload.get("trade_date") or "")
    if payload_trade_date and payload_trade_date != target_trade_date.isoformat():
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="official_daily_fetch",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_DAILY_FETCH_DATE_MISMATCH",
            warning_message=(
                f"官方日更下载摘要日期 {payload_trade_date} 与目标日 "
                f"{target_trade_date.isoformat()} 不一致。"
            ),
            human_review_required=("official_daily_download_retention_policy",),
        )
    if status != "COMPLETED":
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="official_daily_fetch",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_DAILY_FETCH_NOT_COMPLETED",
            warning_message=f"官方日更下载状态不是 COMPLETED：{status}",
            human_review_required=("official_daily_download_retention_policy",),
        )

    verified_paths: list[str] = []
    records = payload.get("records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            kind = str(record.get("file_kind") or "")
            if kind == "options" and not require_options:
                continue
            if kind not in {"futures", "options"}:
                continue
            _audit_download_record(
                record=record,
                target_trade_date=target_trade_date,
                run_id=run_id,
                warnings=warnings,
                verified_paths=verified_paths,
            )
    else:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="official_daily_fetch",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_DAILY_FETCH_RECORDS_MISSING",
            warning_message="官方日更下载摘要缺少 records 明细。",
            human_review_required=("official_daily_download_retention_policy",),
        )

    return {
        "provided": True,
        "exists": True,
        "path": str(official_daily_fetch_json_path),
        "status": status,
        "trade_date": payload_trade_date,
        "verified_file_paths": verified_paths,
    }


def _audit_download_record(
    *,
    record: dict[str, object],
    target_trade_date: date,
    run_id: str,
    warnings: list[DataContinuityWarningRecord],
    verified_paths: list[str],
) -> None:
    kind = str(record.get("file_kind") or "unknown")
    status = str(record.get("status") or "")
    output_value = record.get("output_path")
    sha256_value = record.get("sha256")
    if status not in {"DOWNLOADED", "EXISTS"}:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=f"official_daily_{kind}",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_DAILY_FILE_NOT_READY",
            warning_message=f"{kind} 官方日更文件未处于可处理状态：{status}",
            human_review_required=("official_daily_download_retention_policy",),
        )
        return
    if not isinstance(output_value, str) or not output_value:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=f"official_daily_{kind}",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_DAILY_FILE_PATH_MISSING",
            warning_message=f"{kind} 官方日更摘要缺少本地文件路径。",
            human_review_required=("official_daily_download_retention_policy",),
        )
        return
    path = Path(output_value)
    if not path.exists():
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset=f"official_daily_{kind}",
            severity=ERROR_SEVERITY,
            warning_code="OFFICIAL_DAILY_FILE_MISSING",
            warning_message=f"{kind} 官方日更文件不存在：{path}",
            human_review_required=("official_daily_download_retention_policy",),
        )
        return
    if isinstance(sha256_value, str) and sha256_value:
        actual_sha256 = sha256_file(path)
        if actual_sha256 != sha256_value:
            _append_warning(
                warnings,
                run_id=run_id,
                trade_date=target_trade_date,
                dataset=f"official_daily_{kind}",
                severity=ERROR_SEVERITY,
                warning_code="OFFICIAL_DAILY_FILE_CHECKSUM_MISMATCH",
                warning_message=f"{kind} 官方日更文件 checksum 不一致：{path}",
                human_review_required=("official_daily_download_retention_policy",),
            )
            return
    verified_paths.append(str(path))


def _audit_raw_retention(
    *,
    raw_root: Path,
    target_trade_date: date,
    require_raw_retention: bool,
    futures_audit: DataContinuityDatasetAudit,
    option_audit: DataContinuityDatasetAudit | None,
    run_id: str,
    warnings: list[DataContinuityWarningRecord],
) -> dict[str, object]:
    target_source_ids = list(futures_audit.source_snapshot_ids)
    if option_audit is not None:
        target_source_ids.extend(option_audit.source_snapshot_ids)
    snapshot_ids = tuple(
        sorted(set(_snapshot_id_from_source_id(value) for value in target_source_ids))
    )
    if not require_raw_retention:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="raw_retention",
            severity=INFO_SEVERITY,
            warning_code="RAW_RETENTION_CHECK_SKIPPED",
            warning_message="本次未要求 raw snapshot 留存检查。",
            human_review_required=(),
        )
        return {"required": False, "snapshot_ids": list(snapshot_ids)}

    manifest_path = raw_root / "manifest.jsonl"
    if not snapshot_ids:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="raw_retention",
            severity=ERROR_SEVERITY,
            warning_code="RAW_SNAPSHOT_IDS_MISSING",
            warning_message="目标日 core 记录无法追溯到 raw snapshot id。",
            human_review_required=("raw_snapshot_retention_review",),
        )
        return {"required": True, "manifest_path": str(manifest_path), "snapshot_ids": []}
    if not manifest_path.exists():
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="raw_retention",
            severity=ERROR_SEVERITY,
            warning_code="RAW_MANIFEST_MISSING",
            warning_message=f"未找到 raw manifest，不能确认下载文件已进入留存层：{manifest_path}",
            human_review_required=("raw_snapshot_retention_review",),
        )
        return {
            "required": True,
            "manifest_path": str(manifest_path),
            "snapshot_ids": list(snapshot_ids),
            "missing_snapshot_ids": list(snapshot_ids),
        }
    manifest_records = _raw_manifest_records(manifest_path)
    missing_ids = [
        snapshot_id for snapshot_id in snapshot_ids if snapshot_id not in manifest_records
    ]
    missing_payload_ids: list[str] = []
    for snapshot_id, record in manifest_records.items():
        if snapshot_id not in snapshot_ids:
            continue
        payload_path = raw_root / str(record.get("payload_path") or "")
        if not payload_path.exists():
            missing_payload_ids.append(snapshot_id)
    if missing_ids:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="raw_retention",
            severity=ERROR_SEVERITY,
            warning_code="RAW_SNAPSHOT_RECORD_MISSING",
            warning_message="raw manifest 缺少目标日 snapshot：" + "、".join(missing_ids),
            human_review_required=("raw_snapshot_retention_review",),
        )
    if missing_payload_ids:
        _append_warning(
            warnings,
            run_id=run_id,
            trade_date=target_trade_date,
            dataset="raw_retention",
            severity=ERROR_SEVERITY,
            warning_code="RAW_SNAPSHOT_PAYLOAD_MISSING",
            warning_message="raw snapshot payload 文件缺失：" + "、".join(missing_payload_ids),
            human_review_required=("raw_snapshot_retention_review",),
        )
    return {
        "required": True,
        "manifest_path": str(manifest_path),
        "snapshot_ids": list(snapshot_ids),
        "missing_snapshot_ids": missing_ids,
        "missing_payload_snapshot_ids": missing_payload_ids,
    }


def _raw_manifest_records(manifest_path: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            snapshot_id = payload.get("snapshot_id")
            if isinstance(snapshot_id, str) and snapshot_id:
                records[snapshot_id] = payload
    return records


def _snapshot_id_from_source_id(value: str) -> str:
    return value.split(":", 1)[0].strip()


def _verified_downloaded_paths(official_audit: dict[str, object]) -> tuple[Path, ...]:
    values = official_audit.get("verified_file_paths")
    if not isinstance(values, list):
        return ()
    return tuple(Path(str(value)) for value in values if str(value).strip())


def _date_values(values: list[object]) -> list[date]:
    result: list[date] = []
    for value in values:
        if isinstance(value, date):
            result.append(value)
        elif value is not None and str(value).strip():
            result.append(date.fromisoformat(str(value)[:10]))
    return result


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _append_warning(
    warnings: list[DataContinuityWarningRecord],
    *,
    run_id: str,
    trade_date: date,
    dataset: str,
    severity: AuditSeverity,
    warning_code: str,
    warning_message: str,
    human_review_required: tuple[str, ...],
) -> None:
    warnings.append(
        DataContinuityWarningRecord(
            run_id=run_id,
            trade_date=trade_date,
            dataset=dataset,
            severity=severity,
            warning_code=warning_code,
            warning_message=warning_message,
            human_review_required=human_review_required,
        )
    )


def _continuity_status(warnings: list[DataContinuityWarningRecord]) -> str:
    if any(warning.severity == ERROR_SEVERITY for warning in warnings):
        return "BLOCKED"
    if any(warning.severity == WARN_SEVERITY for warning in warnings):
        return "REVIEW_REQUIRED"
    return "READY"


def _human_review_required(
    warnings: tuple[DataContinuityWarningRecord, ...],
) -> tuple[str, ...]:
    values: list[str] = list(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        values.extend(warning.human_review_required)
    return tuple(dict.fromkeys(value for value in values if value))


def _write_outputs(result: ResearchDataContinuityAuditResult) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text(_markdown_report(result), encoding="utf-8")
    result.json_path.write_text(
        json.dumps(
            {
                **result.to_summary(),
                "report_type": "data_continuity_audit",
                "rule_version": DATA_CONTINUITY_AUDIT_VERSION,
                "warnings": [warning.to_csv_row() for warning in result.warning_records],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_warning_csv(result)
    _write_manifest(result)


def _write_warning_csv(result: ResearchDataContinuityAuditResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in result.warning_records])


def _write_manifest(result: ResearchDataContinuityAuditResult) -> None:
    manifest = {
        "run_id": result.run_id,
        "product_code": result.product_code,
        "exchange": result.exchange,
        "report_type": "data_continuity_audit",
        "rule_version": DATA_CONTINUITY_AUDIT_VERSION,
        "data_asof": result.trade_date.isoformat(),
        "generated_at": utc_now().isoformat(),
        "continuity_status": result.continuity_status,
        "passed": result.passed,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "core_quote_path": str(result.core_quote_path),
        "option_core_path": str(result.option_core_path),
        "calendar_path": None if result.calendar_path is None else str(result.calendar_path),
        "official_daily_fetch_json_path": (
            None
            if result.official_daily_fetch_json_path is None
            else str(result.official_daily_fetch_json_path)
        ),
        "raw_root": str(result.raw_root),
        "downloaded_file_paths": [str(path) for path in result.downloaded_file_paths],
        "markdown_path": str(result.markdown_path),
        "json_path": str(result.json_path),
        "warning_csv_path": str(result.warning_csv_path),
        "human_review_required": list(result.human_review_required),
        "research_boundary": {
            "research_functions_parse_exchange_raw_files": False,
            "contains_forward_return_validation": False,
            "trading_instruction": "not_a_trading_instruction",
            "download_cleanup_allowed_only_after_passed_audit": True,
        },
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _markdown_report(result: ResearchDataContinuityAuditResult) -> str:
    lines = [
        f"# CF 数据连续性与留存检查 - {result.trade_date.isoformat()}",
        "",
        "## 数据状态",
        "",
        f"- 检查状态：`{result.continuity_status}`",
        f"- 错误数：{result.error_count}",
        f"- 警告数：{result.warning_count}",
        f"- 期货 core：`{result.core_quote_path}`",
        f"- 期权 core：`{result.option_core_path}`",
        f"- raw 留存目录：`{result.raw_root}`",
        "",
        "## 期货连续性",
        "",
        _dataset_line(result.futures_audit),
        "",
        "## 期权连续性",
        "",
        (
            _dataset_line(result.option_audit)
            if result.option_audit is not None
            else "- 未要求期权检查。"
        ),
        "",
        "## 官方下载与文件留存",
        "",
        f"- 下载摘要：`{result.official_daily_fetch_json_path}`",
        f"- 已校验下载文件数：{len(result.downloaded_file_paths)}",
        "- 可清理文件：" + (
            "、".join(f"`{path}`" for path in result.downloaded_file_paths)
            if result.downloaded_file_paths
            else "无"
        ),
        "",
        "## raw/core 留存",
        "",
        f"- raw manifest：`{result.raw_retention_audit.get('manifest_path', '')}`",
        f"- 目标日 snapshot 数：{len(result.raw_retention_audit.get('snapshot_ids', []))}",
        f"- 缺失 snapshot：{result.raw_retention_audit.get('missing_snapshot_ids', [])}",
        "",
        "## 警告清单",
        "",
    ]
    if result.warning_records:
        lines.extend(
            [
                "| 数据集 | 级别 | 代码 | 说明 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for warning in result.warning_records:
            lines.append(
                "| "
                + " | ".join(
                    [
                        warning.dataset,
                        warning.severity,
                        warning.warning_code,
                        warning.warning_message,
                    ]
                )
                + " |"
            )
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 本检查只读取 core parquet、官方日更下载摘要和 raw manifest。",
            "- 研究函数不直接解析交易所原始 Excel/ZIP。",
            "- 未包含未来收益标签。",
            "- 不构成交易指令。",
            "- 下载文件仅在检查通过后才允许按显式开关清理。",
            "- 人工复核项：" + "、".join(result.human_review_required),
        ]
    )
    return "\n".join(lines) + "\n"


def _dataset_line(audit: DataContinuityDatasetAudit | None) -> str:
    if audit is None:
        return "- 未检查。"
    return (
        f"- 路径：`{audit.path}`；最新交易日："
        f"`{None if audit.latest_trade_date is None else audit.latest_trade_date.isoformat()}`；"
        f"目标日行数：{audit.target_row_count}；"
        f"目标日合约数：{audit.target_contract_count}；"
        f"缺失交易日数：{len(audit.missing_trading_dates)}；"
        f"重复主键行数：{audit.duplicate_key_count}。"
    )


def _output_paths(*, trade_date: date, output_root: Path | None) -> dict[str, Path]:
    root = output_root or project_root() / "runs" / "daily"
    output_dir = root / PRODUCT_CODE / trade_date.isoformat()
    return {
        "markdown": output_dir / "data_continuity_audit.md",
        "json": output_dir / "data_continuity_audit.json",
        "warning_csv": output_dir / "data_continuity_audit_warnings.csv",
        "manifest": output_dir / "data_continuity_audit_manifest.json",
    }


def _default_calendar_path(trade_date: date) -> Path:
    return project_root() / "configs" / "calendars" / f"{EXCHANGE}_{trade_date.year}_OFFICIAL.csv"


def _default_run_id(trade_date: date) -> str:
    return f"r63_data_continuity_{PRODUCT_CODE}_{trade_date.isoformat()}_{uuid.uuid4().hex[:8]}"
