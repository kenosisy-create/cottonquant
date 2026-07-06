"""Research-mode raw ingest for local CF files."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.hashing import sha256_file
from cotton_factor.common.paths import data_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
RAW_MANIFEST_NAME = "raw_manifest.jsonl"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ResearchRawFileRecord:
    """One file preserved by research-mode raw ingest."""

    run_id: str
    trade_date: date
    product_code: str
    source_file_name: str
    raw_path: Path
    sha256: str
    content_length: int
    captured_at: str
    status: str = "captured"

    def to_manifest_row(self) -> dict[str, object]:
        """Return a JSON-serializable manifest row."""
        return {
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "product_code": self.product_code,
            "source_file_name": self.source_file_name,
            "raw_path": str(self.raw_path),
            "sha256": self.sha256,
            "content_length": self.content_length,
            "captured_at": self.captured_at,
            "status": self.status,
        }


@dataclass(frozen=True)
class ResearchRawIngestResult:
    """Result of preserving one local CF input file or folder."""

    run_id: str
    trade_date: date
    product_code: str
    output_dir: Path
    manifest_path: Path
    records: list[ResearchRawFileRecord]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable ingest summary."""
        return {
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "product_code": self.product_code,
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "file_count": len(self.records),
            "records": [record.to_manifest_row() for record in self.records],
        }


def ingest_cf_raw(
    *,
    trade_date: date,
    input_path: Path,
    raw_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchRawIngestResult:
    """Preserve a local CF file or folder without parsing business fields."""
    active_run_id = _validate_run_id(run_id or _default_run_id(trade_date))
    root = raw_output_dir or data_dir() / "raw"
    source_path = input_path.resolve()
    if not source_path.exists():
        raise ResearchWorkbenchError(f"input path not found: {input_path}")

    manifest_path = root / PRODUCT_CODE / RAW_MANIFEST_NAME
    output_dir = root / PRODUCT_CODE / trade_date.isoformat() / active_run_id
    if output_dir.exists():
        raise ResearchWorkbenchError(f"raw ingest run already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)

    files = _input_files(source_path)
    if not files:
        raise ResearchWorkbenchError(f"input path contains no files: {input_path}")

    captured_at = utc_now().isoformat()
    records: list[ResearchRawFileRecord] = []
    for source_file in files:
        relative_name = _relative_source_name(source_file=source_file, input_path=source_path)
        destination = output_dir / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ResearchWorkbenchError(f"raw destination already exists: {destination}")

        # R04 只做原始文件保存与校验，不在这里读取或解释交易所业务字段。
        shutil.copy2(source_file, destination)
        records.append(
            ResearchRawFileRecord(
                run_id=active_run_id,
                trade_date=trade_date,
                product_code=PRODUCT_CODE,
                source_file_name=relative_name.as_posix(),
                raw_path=destination,
                sha256=sha256_file(destination),
                content_length=destination.stat().st_size,
                captured_at=captured_at,
            )
        )

    _append_manifest(manifest_path=manifest_path, records=records)
    return ResearchRawIngestResult(
        run_id=active_run_id,
        trade_date=trade_date,
        product_code=PRODUCT_CODE,
        output_dir=output_dir,
        manifest_path=manifest_path,
        records=records,
    )


def list_cf_raw_manifest(
    *,
    raw_output_dir: Path | None = None,
    trade_date: date | None = None,
) -> list[dict[str, object]]:
    """List research raw manifest rows, optionally filtered by trade date."""
    root = raw_output_dir or data_dir() / "raw"
    manifest_path = root / PRODUCT_CODE / RAW_MANIFEST_NAME
    if not manifest_path.exists():
        return []

    rows: list[dict[str, object]] = []
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ResearchWorkbenchError(
                    f"invalid research raw manifest line {line_number}: {manifest_path}"
                ) from exc
            if trade_date is None or row.get("trade_date") == trade_date.isoformat():
                rows.append(row)
    return rows


def _input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.is_file())


def _relative_source_name(*, source_file: Path, input_path: Path) -> Path:
    if input_path.is_file():
        return Path(source_file.name)
    try:
        return source_file.relative_to(input_path)
    except ValueError as exc:
        raise ResearchWorkbenchError(f"source file escapes input folder: {source_file}") from exc


def _append_manifest(
    *,
    manifest_path: Path,
    records: list[ResearchRawFileRecord],
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            row = record.to_manifest_row()
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _default_run_id(trade_date: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    return f"cf_raw_{trade_date.isoformat()}_{timestamp}_{uuid.uuid4().hex[:8]}"


def _validate_run_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or cleaned in {".", ".."} or not RUN_ID_PATTERN.fullmatch(cleaned):
        raise ResearchWorkbenchError(
            "run_id must be one path segment using letters, numbers, dot, dash, or underscore"
        )
    return cleaned
