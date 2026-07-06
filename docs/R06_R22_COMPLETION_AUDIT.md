# R06-R22 Completion Audit

This audit records the current evidence that the CF-first research workbench
route from R06 through R22 is complete.

## Verification Commands

```powershell
C:\Users\Yang\AppData\Local\Programs\Python\Python312\python.exe -m pytest
C:\Users\Yang\AppData\Local\Programs\Python\Python312\python.exe -m ruff check src tests
```

Latest verified results, checked in the local workspace on 2026-06-17:

- `pytest`: `189 passed`
- `ruff`: `All checks passed!`

Current completion decision:

- R06-R22 all have source modules, unit tests, and task-level documentation.
- R06-R22 CLI commands are registered in `src/cotton_factor/cli/main.py` and
  documented in `README.md` or the matching research document.
- No stale R20/R21/R22 wording remains that treats those tasks as the next
  unfinished route.
- The current route is complete; any further work should start as a separately
  scoped post-R22 research route.

## Task Evidence

| Task | Status | Primary Evidence |
| --- | --- | --- |
| R06 | Complete | `src/cotton_factor/research_workbench/data_quality.py`, `tests/unit/test_research_data_quality.py`, `docs/DATA_QUALITY_RULES_CF.md` |
| R07 | Complete | `src/cotton_factor/research_workbench/contract_review.py`, `tests/unit/test_research_contract_review.py`, `docs/CF_CONTRACT_RULE_REVIEW.md` |
| R08 | Complete | `src/cotton_factor/research_workbench/mapping.py`, `tests/unit/test_research_mapping.py`, `docs/RESEARCH_MAPPING.md` |
| R09 | Complete | `src/cotton_factor/research_workbench/continuous.py`, `tests/unit/test_research_continuous.py`, `docs/RESEARCH_CONTINUOUS_PRICE.md` |
| R10 | Complete | `src/cotton_factor/research_workbench/output_contracts.py`, `tests/unit/test_research_output_contracts.py`, `docs/RESEARCH_OUTPUT_CONTRACTS.md` |
| R11 | Complete | `src/cotton_factor/research_workbench/momentum.py`, `tests/unit/test_research_momentum.py`, `docs/RESEARCH_MOMENTUM_FACTOR.md` |
| R12 | Complete | `src/cotton_factor/research_workbench/carry.py`, `tests/unit/test_research_carry.py`, `docs/RESEARCH_CARRY_FACTOR.md` |
| R13 | Complete | `src/cotton_factor/research_workbench/structure_factors.py`, `tests/unit/test_research_structure_factors.py`, `docs/RESEARCH_STRUCTURE_FACTORS.md` |
| R14 | Complete | `src/cotton_factor/research_workbench/factor_diagnostics.py`, `tests/unit/test_research_factor_diagnostics.py`, `docs/RESEARCH_FACTOR_DIAGNOSTICS.md` |
| R15 | Complete | `src/cotton_factor/research_workbench/forward_returns.py`, `tests/unit/test_research_forward_returns.py`, `docs/RESEARCH_FORWARD_RETURNS.md` |
| R16 | Complete | `src/cotton_factor/research_workbench/single_factor_backtest.py`, `tests/unit/test_research_single_factor_backtest.py`, `docs/RESEARCH_SINGLE_FACTOR_BACKTESTS.md` |
| R17 | Complete | `src/cotton_factor/research_workbench/multifactor_diagnostics.py`, `tests/unit/test_research_multifactor_diagnostics.py`, `docs/RESEARCH_MULTIFACTOR_DIAGNOSTICS.md` |
| R18 | Complete | `src/cotton_factor/research_workbench/cost_sensitivity.py`, `tests/unit/test_research_cost_sensitivity.py`, `docs/RESEARCH_COST_SENSITIVITY.md` |
| R19 | Complete | `src/cotton_factor/research_workbench/daily_brief.py`, `tests/unit/test_research_daily_brief.py`, `docs/RESEARCH_DAILY_BRIEF.md` |
| R20 | Complete | `src/cotton_factor/research_workbench/pipeline.py`, `tests/unit/test_research_pipeline.py`, `docs/RESEARCH_DAILY_PIPELINE.md` |
| R21 | Complete | `src/cotton_factor/research_workbench/replay.py`, `tests/unit/test_research_replay.py`, `docs/RESEARCH_REPLAY.md` |
| R22 | Complete | `src/cotton_factor/research_workbench/expansion_gate.py`, `tests/unit/test_research_expansion_gate.py`, `docs/RESEARCH_EXPANSION_GATE.md` |

## Self-Audit Chain

- R06 blocks downstream research when critical data-quality failures appear.
- R10 fixes downstream artifact contracts for R11-R14.
- R14 preserves unknown factor states instead of silently converting missing
  values to neutral.
- R15 uses R08 real-contract trade mapping and T+1 execution dates.
- R19 summarizes R06-R18 evidence without producing trading approvals.
- R20 writes a one-command pipeline log for R04-R19.
- R21 replay-checks preserved R20 artifact paths, hashes, sizes, row counts, and
  optional baselines.
- R22 blocks expansion until CF R20/R21 evidence exists and candidate-specific
  rules remain under human review.

## Remaining Human Review Items

The current route is complete, but the following remain intentionally open:

- contract rule interpretation;
- last trading day and roll assumptions;
- factor thresholds and direction wording;
- carry tenor rule;
- curve far-leg rule;
- OI prior-contract matching;
- cost and slippage assumptions;
- candidate product or external data source rules before any post-R22 expansion.

These items must stay visible as `HUMAN_REVIEW_REQUIRED`; they are not blockers
to completing the R06-R22 research-workbench implementation, but they do block
production trading or broader ingestion approval.

## Post-R22 Boundary

R00-R22 complete the current CF-first research workbench route. Any SR/AP,
external data, dashboard, service API, or production ingest work should start as
a new post-R22 route with separate scope, evidence, and gates.
