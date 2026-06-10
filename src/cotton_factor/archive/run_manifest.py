"""Run manifest construction and persistence."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from cotton_factor.common.exceptions import ArchiveError
from cotton_factor.common.hashing import sha256_bytes, sha256_file
from cotton_factor.common.paths import project_root
from cotton_factor.common.time import utc_now
from cotton_factor.core.schemas import ArchiveRunManifestRow

UNKNOWN_GIT_SHA = "UNKNOWN_GIT_SHA"


def build_run_manifest(
    *,
    run_id: str,
    run_type: str,
    input_snapshot_ids: Sequence[str] = (),
    row_counts: Mapping[str, int] | None = None,
    artifact_paths: Sequence[str] = (),
    warnings: Sequence[str] = (),
    parent_run_id: str | None = None,
    status: str = "success",
    git_sha: str | None = None,
    config_paths: Sequence[Path] | None = None,
    started_at_utc: datetime | None = None,
    ended_at_utc: datetime | None = None,
) -> ArchiveRunManifestRow:
    """Build a schema-validated archive_run_manifest row."""
    started = started_at_utc or utc_now()
    ended = ended_at_utc or utc_now()
    # run_manifest 是正式 run 的总账，必须把代码、配置、输入和产物 lineage 一次性固化。
    return ArchiveRunManifestRow(
        run_id=run_id,
        parent_run_id=parent_run_id,
        run_type=run_type,
        git_sha=git_sha or current_git_sha(),
        config_hash=config_hash(config_paths=config_paths),
        env_hash=env_hash(),
        input_snapshot_ids=list(_unique_values(input_snapshot_ids)),
        started_at_utc=started,
        ended_at_utc=ended,
        status=status,  # type: ignore[arg-type]
        row_counts=dict(row_counts or {}),
        artifact_paths=list(artifact_paths),
        warnings=list(_unique_values(warnings)),
    )


def write_run_manifest(row: ArchiveRunManifestRow, path: Path) -> Path:
    """Write one run manifest JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = row.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_run_manifest(path: Path) -> ArchiveRunManifestRow:
    """Read and validate one run manifest JSON file."""
    if not path.exists() or not path.is_file():
        raise ArchiveError(f"run manifest not found: {path}")
    return ArchiveRunManifestRow.model_validate(json.loads(path.read_text(encoding="utf-8")))


def current_git_sha(cwd: Path | None = None) -> str:
    """Return current git commit sha, or a stable unknown marker."""
    repo = cwd or project_root()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return UNKNOWN_GIT_SHA
    value = result.stdout.strip()
    return value or UNKNOWN_GIT_SHA


def config_hash(config_paths: Sequence[Path] | None = None) -> str:
    """Return deterministic hash for config files."""
    paths = list(config_paths) if config_paths is not None else _default_config_paths()
    payload: list[dict[str, str]] = []
    root = project_root()
    for path in sorted(paths):
        if not path.exists() or not path.is_file():
            raise ArchiveError(f"config path not found: {path}")
        payload.append(
            {
                "path": _relative_or_absolute(path=path, root=root),
                "sha256": sha256_file(path),
            }
        )
    return sha256_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


def env_hash() -> str:
    """Return deterministic hash for the local Python runtime fingerprint."""
    payload = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }
    return sha256_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


def _default_config_paths() -> list[Path]:
    config_dir = project_root() / "configs"
    return sorted(path for path in config_dir.rglob("*") if path.is_file())


def _relative_or_absolute(*, path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _unique_values(values: Sequence[str]) -> tuple[str, ...]:
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return tuple(unique_values)
