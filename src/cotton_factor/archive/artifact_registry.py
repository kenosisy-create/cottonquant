"""Artifact registry and archive bundle helpers."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from cotton_factor.common.exceptions import ArchiveError
from cotton_factor.common.hashing import sha256_file
from cotton_factor.common.paths import project_root

DEFAULT_ARTIFACT_REGISTRY_VERSION = "artifact_registry_v1"


@dataclass(frozen=True)
class ArtifactRecord:
    """One artifact registry record."""

    artifact_id: str
    artifact_type: str
    path: str
    sha256: str
    byte_size: int
    registry_version: str = DEFAULT_ARTIFACT_REGISTRY_VERSION


@dataclass(frozen=True)
class ArchiveBundleResult:
    """Archive bundle output summary."""

    bundle_path: Path
    artifact_count: int
    sha256: str
    byte_size: int
    included_paths: list[str]


def register_artifact(
    *,
    path: Path,
    artifact_type: str,
    artifact_id: str | None = None,
    root: Path | None = None,
) -> ArtifactRecord:
    """Create one artifact registry record from a local file."""
    if not path.exists() or not path.is_file():
        raise ArchiveError(f"artifact path not found: {path}")
    base = root or project_root()
    artifact_path = _relative_or_absolute(path=path, root=base)
    return ArtifactRecord(
        artifact_id=artifact_id or _safe_artifact_id(artifact_path),
        artifact_type=artifact_type,
        path=artifact_path,
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


def write_artifact_registry(records: Sequence[ArtifactRecord], path: Path) -> Path:
    """Write artifact registry as deterministic JSON."""
    if not records:
        raise ArchiveError("artifact registry requires at least one record")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(record) for record in sorted(records, key=lambda item: item.artifact_id)]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_artifact_registry(path: Path) -> list[ArtifactRecord]:
    """Read artifact registry JSON."""
    if not path.exists() or not path.is_file():
        raise ArchiveError(f"artifact registry not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ArchiveError("artifact registry payload must be a list")
    return [ArtifactRecord(**item) for item in payload]


def build_archive_bundle(
    *,
    bundle_path: Path,
    artifact_paths: Sequence[Path],
    root: Path | None = None,
) -> ArchiveBundleResult:
    """Build a zip archive from manifest, registry, audit log, and reports."""
    if not artifact_paths:
        raise ArchiveError("archive bundle requires at least one artifact path")
    base = root or project_root()
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    included_paths: list[str] = []

    with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for artifact_path in sorted(artifact_paths):
            if not artifact_path.exists() or not artifact_path.is_file():
                raise ArchiveError(f"bundle artifact not found: {artifact_path}")
            archive_name = _relative_or_absolute(path=artifact_path, root=base)
            if archive_name in included_paths:
                continue
            # bundle 只打包已生成的审计产物，不在这里重新解释或改写业务结果。
            archive.write(artifact_path, arcname=archive_name)
            included_paths.append(archive_name)

    return ArchiveBundleResult(
        bundle_path=bundle_path,
        artifact_count=len(included_paths),
        sha256=sha256_file(bundle_path),
        byte_size=bundle_path.stat().st_size,
        included_paths=included_paths,
    )


def _safe_artifact_id(path: str) -> str:
    value = "".join(character if character.isalnum() else "_" for character in path)
    return value.strip("_") or "artifact"


def _relative_or_absolute(*, path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
