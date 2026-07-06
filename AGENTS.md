# AGENTS.md

## Project Mission

This repository is no longer being pushed as a full production-grade factor
platform.

The current mission is to build a research-grade production data decision
workbench for China agricultural futures, starting with CZCE cotton futures CF.

Engineering serves research. Do not turn this repository into a platform
project.

The workbench must help a research analyst answer:

1. What happened in CF market structure today?
2. Are momentum, carry, curve slope, and OI pressure giving useful signals?
3. Do historical tests support the signal direction?
4. What should be watched for tomorrow's trading decision?

## Strategic Scope

Primary product:

- CF only.

Primary frequency:

- Daily data.

Primary output:

- Daily research brief.
- Factor table.
- Backtest summary.
- Data quality report.
- Simple run log.

Do not prioritize:

- release freeze
- gray deployment
- multi-user platform
- full CI/CD
- SRE-grade monitoring
- OMS integration
- minute-level execution
- full metadata catalog
- production-grade artifact registry
- SR/AP real production ingest before CF is validated

## Non-Negotiable Research Correctness Rules

1. Do not let research functions parse exchange raw files directly.
2. Raw data may be simple, but must be preserved.
3. Core tables must be normalized and inspectable.
4. Continuous contracts are signal objects only.
5. Backtest and trading-related outputs must use real tradable contracts.
6. T-day post-settlement signals must execute no earlier than T+1.
7. Do not use future data.
8. Every contract switch must have a visible reason.
9. Near last trading day risk must be explicit.
10. Unknown business rules must be marked as RESEARCH_TODO or
    HUMAN_REVIEW_REQUIRED, never silently assumed.

## Development Philosophy

Prefer:

- small, inspectable modules
- CSV/Parquet outputs
- Markdown reports
- clear charts
- simple configs
- reproducible notebooks or scripts
- direct usefulness for factor research

Avoid:

- heavy platform abstractions
- service APIs unless necessary
- complex orchestration
- premature multi-product architecture
- enterprise release machinery
- over-engineered monitoring

## Historical Foundation

D0-D23 are complete and remain useful as foundation:

- raw/core/research/archive separation
- CF fixture ingestion and normalization
- contract master, chain map, trade mapping, and continuous price logic
- four MVP factors
- T+1 backtest constraints
- smoke, QA, UAT, and release freeze artifacts

Future work must not continue by expanding release/UAT/platform machinery. It
must build the R00-R22 research workbench path around real or production-like CF
daily data, data quality checks, factor diagnostics, research backtests, and
daily research briefs.

## Coding Standards

- Python 3.11+.
- Use typed code where practical.
- Prefer Polars or pandas for dataframes, DuckDB for local queries, Parquet for
  artifacts.
- Use Pydantic or Pandera for schema validation when it pays for itself.
- Use pytest for tests.
- Use ruff for lint.
- Do not introduce heavy dependencies without adding the reason to
  docs/DEPENDENCIES.md.
- All public CLI commands must have examples in README.md.

## Required Commands

After modifying code:

- run `python -m pytest`
- run `python -m ruff check src tests`

If the task touches factors, also run factor fixture tests.

If the task touches backtest, also run T+1 and no-look-ahead tests.

If the task touches data parsing, also run data quality checks on fixtures.

## Output Contract

Every task must end with:

- changed files
- commands run
- tests run
- generated artifacts
- assumptions
- research TODOs
- human review required
- next recommended task

Use JSON for final machine-readable summaries when requested.

## Human Review Gates

Human review is mandatory for:

- contract rule assumptions
- last trading day logic
- roll rule thresholds
- execution timing
- cost model parameters
- production permissions
- official data field interpretation

## Hard Stop Conditions

Stop and report instead of guessing when:

- CF contract rule is unclear
- last trading day logic is unclear
- exchange field interpretation is unclear
- production data source format changed
- data source credentials are missing
- factor result looks materially different from baseline without explanation
