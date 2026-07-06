# CF Research Expansion Gate

R52 refreshes the gate before Cottonquant expands from CF daily research into
SR/AP or external data. R22 remains available only as a legacy compatibility
mode for the post-R22 validation pack.

The gate is deliberately conservative. It does not start SR/AP ingest, external
spot/weather/USDA ingest, or new factor research. It checks whether CF has
enough preserved evidence from R20/R21 and the R41-R51 mainline before any
broader research prototype can begin.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-expansion-gate --candidate-scope SR_AP --pipeline-json-path runs/codex/post_r22_cf_validation/.../reports/pipeline/..._pipeline.json --replay-json-path runs/codex/post_r22_cf_validation/.../reports/replay/..._replay.json --historical-evidence-manifest-path data/research/CF/historical_evidence/CF_2021-01-04_2026-07-01_historical_evidence_manifest.json --event-explanation-manifest-path data/research/CF/event_explanation/CF_2021-01-04_2026-07-01_event_explanation_manifest.json --signal-matrix-manifest-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-03_signal_matrix_manifest.json --publish-pack-manifest-path runs/daily/CF/2026-07-01/publish/manifest.json --product-registry-manifest-path data/research/CF/product_registry/CF_product_research_registry_manifest.json --fundamental-contract-manifest-path data/research/CF/fundamentals/CF_fundamental_data_contract_manifest.json
```

## Gate Requirements

R52 requires:

- candidate expansion scope is explicitly declared;
- R20 CF pipeline JSON exists and has status `COMPLETED`;
- R21 replay JSON exists and has `passed=true`;
- R21 replay source is linked to the same R20 pipeline JSON;
- R41 historical evidence manifest is present and marks forward returns as
  historical validation labels;
- R42 event explanation manifest is present and marks event returns as
  after-the-fact labels;
- R49 signal matrix manifest is present, has no forward-return validation
  content, and references the R48 option factor proxy;
- R45 publish pack manifest is present and has a non-empty chart pack;
- R50 product registry manifest is present with the four futures factors and
  six option proxy factors;
- R51 fundamental contract manifest is present and keeps fundamental signals
  `not_connected`;
- candidate-specific business rules remain under human review before real
  ingest begins.

If CF evidence is missing, the gate status is:

- `BLOCKED_MISSING_CF_MAINLINE_EVIDENCE`

If CF evidence is present, the usual status is:

- `HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION`

That status means the gate definition is satisfied at the CF evidence level,
but expansion is not automatically approved.

## Outputs

R52 writes:

- `reports/research/expansion_gate/CF_{scope}_{run_id}_expansion_gate.md`
- `reports/research/expansion_gate/CF_{scope}_{run_id}_expansion_gate.json`

## Human Review Required

Before SR/AP or external data can move beyond a research prototype, the
following must be reviewed:

- candidate contract rules;
- candidate raw source convention;
- candidate field mapping;
- candidate data quality rules;
- candidate execution boundary;
- candidate cost and slippage assumptions.
- CF mainline evidence interpretation;
- option signal filter rules before expansion;
- fundamental data source and signal rules;
- publish pack readability and compliance;
- product expansion go/no-go.

## Research Boundary

R52 keeps CF as the only active product. It does not override any existing
non-negotiable research correctness rule and does not approve live ingestion or
trading use.
