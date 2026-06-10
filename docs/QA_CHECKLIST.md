# QA Checklist

D21 adds automated QA checks for schema validation, row counts, null ratios,
fixture hashes, and smoke reproducibility.

## Commands

Run all tests:

```bash
py -3.12 -m pytest
py -3.12 -m ruff check src tests
```

Validate one CSV artifact against a registered schema:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main qa validate-csv --table core_quote_daily --csv tests/fixtures/core_quote_daily_cf_chain_sample.csv
```

Audit row count and null ratios:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main qa audit-csv --table core_quote_daily --csv tests/fixtures/core_quote_daily_cf_chain_sample.csv --min-row-count 8 --max-null-ratio settle=0
```

Run golden and reproducibility checks:

```bash
py -3.12 -m pytest tests/golden/test_d21_quality.py
```

## Automated Checks

- raw fixture SHA256 values match golden expectations
- normalized quote edge rows match golden expectations
- D19 CF smoke stable row counts and warnings are reproducible across runs
- D20 SR/AP config-only contract outputs match golden expectations
- CLI CSV validation fails loudly on schema violations
- CLI CSV audit reports row-count and null-ratio warnings

## Review Before Gate E

- Confirm `TODO_REQUIRES_HUMAN_REVIEW` items are not hidden in warnings.
- Confirm row-count changes are intentional and documented.
- Confirm null-ratio thresholds fit the target artifact, not just the fixture.
- Confirm any new public CLI command has a README example.
- Confirm archive bundles include manifest, audit log, checksums, registry, and report.

## Still Manual

The following cannot be accepted by automated D21 checks alone:

- contract rule assumptions
- last trading day interpretation
- roll thresholds
- execution timing assumptions beyond covered fixtures
- cost model parameters
- official data field interpretation
