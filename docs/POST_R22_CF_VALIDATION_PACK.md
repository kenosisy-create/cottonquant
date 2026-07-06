# Post-R22 CF Validation Pack

This document defines the first post-R22 bridge task: prove that the completed
CF research workbench can run and produce inspectable outputs without expanding
into platform machinery.

## Purpose

The validation pack answers one operational question:

Can the local CF research workbench run from a daily input CSV through R20
pipeline, R21 replay, and R22 gate, then leave enough evidence for review?

It is not a production exchange-data connector and does not approve trading.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-validation-pack --date 2024-01-31 --start 2024-01-22 --end 2024-01-31 --horizons 1 --lookback-periods 3
```

Optional isolated root:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-validation-pack --output-root runs/codex/post_r22_cf_validation --run-id manual_validation_20240131
```

## What It Does

The pack:

1. Creates generated production-like CF daily quote rows in an isolated run
   folder.
2. Preloads historical core rows to simulate an existing daily core table.
3. Sends the target trade date through R04 raw preservation and R05
   normalization.
4. Runs R20 from R04 through R19.
5. Runs R21 replay against the saved R20 pipeline JSON.
6. Runs R22 expansion gate using the R20/R21 evidence.
7. Writes a post-R22 summary JSON and Markdown report.

## Default Outputs

```text
runs/codex/post_r22_cf_validation/{run_id}/
  incoming/
  raw/
  core/
  research/
  reports/
```

Key evidence files:

- `reports/pipeline/*_pipeline.json`
- `reports/replay/*_replay.json`
- `reports/expansion_gate/*_expansion_gate.json`
- `reports/post_r22_cf_validation/*.json`
- `reports/post_r22_cf_validation/*.md`

## Boundary

The pack uses generated sample data. It proves local system operability and
artifact production, not real production-data permission or official field
interpretation.

The following remain `HUMAN_REVIEW_REQUIRED`:

- real CF data source permission;
- official exchange field interpretation;
- contract rule assumptions;
- last-trading-day and roll logic;
- factor thresholds and direction wording;
- cost and slippage assumptions.

## Success Criteria

The command succeeds when:

- R20 pipeline status is `COMPLETED`;
- R21 replay `passed=true`;
- R22 gate `passed=true` with status
  `HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION`;
- the post-R22 validation summary status is `PASSED_WITH_HUMAN_REVIEW`.
