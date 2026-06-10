# Release Checklist

D23 freezes the MVP release candidate package.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main release freeze --version 0.1.0
```

The default output directory is:

```text
data/archive/release-0.1.0/
```

## Required Contents

- `release_manifest.json`
- `run_manifest.json`
- `audit.jsonl`
- `checksums.json`
- `artifact_registry.json`
- `test_summary.json`
- `known_todos.json`
- `known_todos.md`
- copied `CHANGELOG.md`
- copied `RELEASE_CHECKLIST.md`
- UAT JSON and HTML reports
- `release_bundle.zip`

## Gate Checks

- Version in CLI argument, `VERSION`, package `__version__`, and `pyproject.toml`
  must match.
- CF UAT replay must pass.
- SR/AP config-only smoke must pass.
- Every `TODO_REQUIRES_HUMAN_REVIEW` occurrence in runtime/config/docs scope must
  be classified as one of:
  - `blocks production`
  - `acceptable for MVP`
  - `future enhancement`
- Release bundle must include manifest, audit log, checksums, registry, UAT
  reports, changelog, checklist, and TODO inventory.

## Human Review

The release command can mark the MVP candidate as pass while still reporting
`production_ready=false`. Production readiness requires closing all items
classified as `blocks production`.
