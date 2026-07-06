# Research Output Contracts

R10 fixes the downstream output contract for CF factor diagnostics. The goal is
to let R11-R14 write factor artifacts in one stable shape before backtest and
daily brief work begins.

## Scope

R10 defines:

- stable file paths for factor values, factor diagnostics, warning logs, and
  Markdown diagnostics;
- schema-backed contracts for `research_factor_value_daily` and
  `research_factor_diagnostic_daily`;
- allowed daily diagnostic states: `long`, `short`, `neutral`, `unknown`;
- human-review gates that must stay visible until factor thresholds and business
  assumptions are approved.

R10 does not compute factors, generate backtests, or create trading advice.

## Command

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research write-cf-factor-output-contract
```

Optional output overrides:

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research write-cf-factor-output-contract --output-dir data/research/CF/output_contracts --report-output-dir reports/research/output_contracts
```

Default outputs:

- `data/research/CF/output_contracts/CF_factor_diagnostics_output_contract.json`
- `reports/research/output_contracts/CF_factor_diagnostics_output_contract.md`

## Artifact Contract

| Artifact | Producer | Consumer | Default path |
| --- | --- | --- | --- |
| `cf_factor_value_daily` | R11-R13 | R14-R17, R19 | `data/research/CF/factors/CF_{start}_{end}_factor_value_daily.parquet` |
| `cf_factor_diagnostic_daily` | R14 | R16-R17, R19 | `data/research/CF/factors/CF_{start}_{end}_factor_diagnostic_daily.parquet` |
| `cf_factor_diagnostic_report` | R14 | R19 | `reports/research/factors/CF_{start}_{end}_factor_diagnostics.md` |
| `cf_factor_warning_log` | R11-R14 | R14, R19 | `data/research/CF/factors/CF_{start}_{end}_factor_warnings.csv` |
| `cf_multifactor_score_daily` | R17 | R18-R19 | `data/research/CF/multifactor/CF_{start}_{end}_multifactor_score_daily.parquet` |
| `cf_cost_sensitivity_summary` | R18 | R19 | `data/research/CF/cost_sensitivity/CF_{start}_{end}_cost_sensitivity_summary.parquet` |
| `cf_daily_research_brief` | R19 | R20-R21 | `reports/research/daily_brief/CF_{date}_daily_research_brief.md` |

## Diagnostic Table

`research_factor_diagnostic_daily` is the daily analyst-facing state table. It
keeps the original factor value and the interpreted signal state together.

Required fields include:

- `run_id`
- `factor_id`
- `factor_version`
- `product_code`
- `universe`
- `signal_object_id`
- `trade_date`
- `signal_state`
- `diagnostic_reason`
- `diagnostic_rule_version`
- `input_snapshot_ids`

Optional context fields:

- `raw_value`
- `processed_value`
- `warning_flags`
- `human_review_required`

`unknown` is a first-class state. If a factor cannot be interpreted because of
missing inputs or unresolved business rules, downstream code must write
`unknown` plus warning or human-review context, not `neutral`.

## Research Rules

- Research functions must read normalized core/research artifacts only.
- T-day post-settlement diagnostics are research signals for T+1 or later use.
- Continuous contracts remain signal objects only.
- Missing inputs must surface as warning rows or `unknown` diagnostic states.
- Unknown business rules must stay marked as `HUMAN_REVIEW_REQUIRED`.

## Human Review Required

- factor thresholds for long/short/neutral states;
- carry tenor rule;
- curve-slope far-leg rule;
- OI pressure prior-contract matching;
- final interpretation wording in daily research briefs.

## Current Progress

R11 adapts momentum output to this contract by writing
`research_factor_value_daily` rows and warning records under the R10 paths.
R12 adapts carry output to the same contract while keeping carry-tenor and
contract-rule review items visible.
R13 adapts curve slope and OI pressure outputs to the same contract while
keeping missing far-leg and prior-contract inputs visible.
R14 builds `research_factor_diagnostic_daily` rows from those four factor
outputs and writes `unknown` states plus warning rows when factor/date values
are missing.
R15 builds T+1-safe `research_forward_return_daily` labels from R08 real-contract
trade mapping and normalized core quotes.
R16 builds `research_factor_evaluation` metrics from R14 diagnostics and R15
labels.
R17 builds `research_multifactor_score_daily` rows from non-unknown R14
diagnostics using explicit equal weights and writes missing-factor warnings.
R18 builds cost sensitivity summary rows from R17 score directions and R15
forward-return labels while keeping cost assumptions under human review.
R19 builds Markdown/JSON daily research briefs from R06-R18 artifacts.
R20 runs R04-R19 in order and writes a simple pipeline Markdown/JSON run log.
R21 replay-checks preserved R20 artifacts and optional baseline fingerprints.

## Next Step

R22 expansion gate now completes the current R-series route.
