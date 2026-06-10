# CF Smoke

D19 adds a full-chain CF fixture smoke workflow.
D20 adds product config-only smoke for SR/AP.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main smoke cf --start 2024-01-02 --end 2024-02-05 --run
```

Use `--dry-run` to print the planned workflow without writing artifacts.

## Workflow

The smoke command runs:

- CZCE history fixture ingestion into immutable raw snapshots
- CZCE settlement parameter fixture ingestion into immutable raw snapshots
- raw snapshot replay into `core_quote_daily`
- raw snapshot replay into `core_settlement_param_daily`
- official CZCE 2024 trading calendar loading
- CF contract master generation
- chain map and trade mapping
- continuous price generation
- four MVP factors
- one-period forward returns
- single-factor momentum evaluation
- equal-weight multifactor score
- target lot generation
- daily backtest
- HTML report rendering
- run manifest, audit log, checksums, artifact registry, and zip bundle

## Outputs

By default, artifacts are written under:

```text
data/archive/{run_id}/
  manifest.json
  audit.jsonl
  checksums.json
  artifact_registry.json
  reports/backtest.html
  {run_id}_bundle.zip
```

The command returns a JSON summary with row counts, input snapshot ids, warnings,
and artifact paths.

## Boundary

The D19 normalizers support local CSV fixtures. Live exchange endpoint field
interpretation remains `TODO_REQUIRES_HUMAN_REVIEW`.

## Product Config Smoke

Run:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main smoke products --products SR,AP --year 2024
```

This smoke only validates product configs and contract-master generation. It
does not ingest SR/AP market data or run SR/AP backtests.
