# CF Research Replay

R21 adds a lightweight replay check for preserved R20 research outputs.

This is not the historical D22 UAT replay. R21 is narrower: it reads an R20
pipeline JSON log, checks the files recorded in that log, computes stable
fingerprints, and optionally compares them with a prior R21 replay JSON.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research replay-cf-daily-pipeline --pipeline-json-path reports/research/pipeline/CF_2024-01-10_r20_pipeline_pipeline.json
```

With a prior replay baseline:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research replay-cf-daily-pipeline --pipeline-json-path reports/research/pipeline/CF_2024-01-10_r20_pipeline_pipeline.json --baseline-json-path reports/research/replay/CF_2024-01-10_r21_replay_replay.json
```

## What It Checks

R21 checks:

- the R20 pipeline status is `COMPLETED` by default;
- every artifact path recorded in the R20 JSON exists;
- each artifact has a SHA256 fingerprint and byte size;
- CSV, Parquet, and recognized JSON artifacts expose row counts;
- optional baseline fingerprints still match.

## Outputs

R21 writes:

- `reports/research/replay/CF_{date}_{run_id}_replay.md`
- `reports/research/replay/CF_{date}_{run_id}_replay.json`

The JSON report includes:

- pass/fail checks;
- artifact fingerprints;
- missing artifacts;
- baseline differences when a baseline is supplied;
- inherited human-review fields from the R20 pipeline log.

## Research Boundary

R21 is only a replay confidence check for saved files. It does not:

- rerun R04-R19;
- parse exchange raw files;
- infer missing artifacts;
- approve trades, orders, or positions;
- close human-review items.

## Next Step

R22 expansion gate now completes the current R-series route by making CF
validation prerequisites explicit before broader ingestion begins.
