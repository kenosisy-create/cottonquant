# Archive

D18 adds formal archive helpers for reproducible runs.

## Run Manifest

`archive_run_manifest` records one formal run. It captures:

- run id and run type
- git sha
- config hash
- Python environment hash
- input snapshot ids
- row counts
- artifact paths
- warnings and human review notes

The manifest is schema-validated by `ArchiveRunManifestRow`.

## Artifact Registry

The artifact registry records generated files with:

- artifact id
- artifact type
- relative path
- SHA256
- byte size
- registry version

It is intentionally a checksum ledger. It does not parse reports, factors, raw
exchange files, or backtest outputs.

## Audit Log

Audit logs are UTF-8 JSONL files. Each line is one ordered event with:

- run id
- event type
- severity
- message
- UTC timestamp
- JSON payload

Use `human_review` severity for `TODO_REQUIRES_HUMAN_REVIEW` events.

## Archive Bundle

The archive bundle is a zip file that packages generated audit artifacts such as:

- `run_manifest.json`
- `artifact_registry.json`
- `audit.jsonl`
- static HTML reports

The bundle helper returns bundle path, checksum, byte size, and included paths.
It only packages already generated artifacts; it does not reinterpret business
outputs.

## Python API

```python
from cotton_factor.archive import (
    AuditLogWriter,
    build_archive_bundle,
    build_run_manifest,
    register_artifact,
    write_artifact_registry,
    write_run_manifest,
)
```

D19 should use these helpers to produce the CF full-chain smoke archive.
