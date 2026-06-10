# UAT Replay

D22 adds a User Acceptance Test replay for the CF MVP fixture scenario. It is a
release-gate rehearsal, not production approval.

## Scope

The first supported scenario is `cf_mvp_fixture`. It replays the same CF fixture
window used by D19/D21:

- start: `2024-01-02`
- end: `2024-02-05`
- product: `CF`
- signal object: `CF.C1`
- execution rule: T settlement signal, T+1 real-contract execution

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main uat replay --scenario cf_mvp_fixture
```

For deterministic local checks:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main uat replay --scenario cf_mvp_fixture --output-root data/archive/uat --run-id d22_uat_local
```

## Outputs

By default, UAT outputs are written under:

```text
data/archive/uat/{run_id}/
  uat_report.json
  uat_report.html
  raw/
  smoke_archive/{run_id}/
    manifest.json
    audit.jsonl
    checksums.json
    artifact_registry.json
    reports/backtest.html
    {run_id}_bundle.zip
```

The CLI prints a JSON summary with:

- overall `passed`
- UAT report paths
- smoke archive path
- pass/fail checks
- stable warnings

## Automated Checks

The D22 replay report includes pass/fail items for:

- CF smoke completion
- required archive artifacts
- run manifest validity and `run_type == "cf_full_chain_smoke"`
- stable row counts matching golden expectations
- stable warnings matching golden expectations
- cost-model `TODO_REQUIRES_HUMAN_REVIEW` warnings being visible
- archive bundle existence
- backtest HTML report existence

## Review Checklist

- Open `uat_report.html` and confirm every automated check is `PASS`.
- Confirm `uat_report.json` has no `failed_checks`.
- Confirm warning changes are intentional before updating golden values.
- Confirm the smoke archive contains manifest, audit log, checksums, registry,
  HTML report, and zip bundle.
- Confirm any local `--raw-root` or `--archive-root` override points to a
  disposable replay area.

## Human Review Gates

UAT does not remove these manual gates:

- contract rule assumptions
- last trading day logic
- roll rule thresholds
- execution timing outside the covered fixture window
- cost model parameters
- official data field interpretation
- production permissions

Any unresolved gate must remain visible as `TODO_REQUIRES_HUMAN_REVIEW` or a
documented release TODO.
