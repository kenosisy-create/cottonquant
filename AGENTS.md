# AGENTS.md

## Project Mission

This repository implements a China agricultural futures daily factor research MVP,
starting with cotton futures CF.

The first deliverable is a production-like MVP for CF:
- raw snapshot layer
- core facts layer
- research derived layer
- archive and audit layer
- signal object / trade object separation
- T settlement signal, T+1 execution
- first factors: carry, momentum, curve slope, OI pressure
- reproducible backtest and report bundle

## Non-negotiable Architecture

1. Never let research code parse raw exchange files directly.
2. All research functions must read normalized core facts or research derived tables.
3. Raw snapshots are immutable.
4. Every normalized fact must carry source_snapshot_id.
5. Every formal run must create run_manifest.
6. Continuous contracts are signal objects only.
7. Orders, fills, costs, and positions must use real tradable contracts.
8. Daily signals use T-day post-settlement data and execute on T+1.
9. No look-ahead data, no same-day execution using post-settlement official data.
10. Missing or ambiguous rules must become TODO_REQUIRES_HUMAN_REVIEW items, not silent assumptions.

## MVP Scope

In scope for Month 1:
- CZCE CF daily quote ingestion
- CZCE CF historical quote backfill
- CZCE settlement parameter ingestion
- product config for CF, SR, AP, M, C, Y
- CF contract master
- CF trading calendar
- CF chain map
- CF trade mapping
- carry, momentum, curve slope, OI pressure
- single factor evaluator
- basic multifactor equal-weight score
- daily backtest
- HTML report
- run manifest
- audit logs
- SR/AP config-only smoke test

Out of scope for Month 1:
- live trading
- minute-level execution
- external spot data
- weather
- USDA
- full options pricing engine
- production OMS connection

## Coding Standards

- Python 3.11+.
- Use typed code where practical.
- Prefer Polars or pandas for dataframes, DuckDB for local queries, Parquet for artifacts.
- Use Pydantic or Pandera for schema validation.
- Use pytest for tests.
- Use ruff for lint.
- Do not introduce heavy dependencies without adding the reason to docs/DEPENDENCIES.md.
- All public CLI commands must have examples in README.md.

## Required Commands

After modifying code:
- run `python -m pytest`
- run `python -m ruff check src tests`
- if schemas change, run core layer smoke test
- if factors change, run golden sample tests
- if backtest changes, run reproducibility test

## Output Contract

For every task, produce:
- changed files list
- commands run
- tests run
- artifacts generated
- known TODOs
- blocking questions, if any

Use JSON for final machine-readable summary when requested.

## Human Review Gates

Human review is mandatory for:
- contract rule assumptions
- last trading day logic
- roll rule thresholds
- execution timing
- cost model parameters
- production permissions
- official data field interpretation
