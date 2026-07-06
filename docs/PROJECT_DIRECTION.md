# Project Direction

This project is now a research-grade production data decision workbench, not a
production-grade factor platform.

The D0-D23 implementation is complete and remains the engineering foundation.
It proved that the repository can preserve raw data, normalize core facts, build
contract mappings, compute the first CF factors, run a T+1 backtest, and package
auditable outputs. The next execution path is different: use that foundation to
support daily CF research decisions with real or production-like data.

## Current Mission

Build a CF-first research workbench that helps an analyst answer:

- Is today's CF data complete and trustworthy?
- What happened in market structure, main/secondary contracts, and roll state?
- Are momentum, carry, curve slope, and OI pressure useful today?
- Does historical evidence support the current signal direction?
- What should be watched for tomorrow's trading decision?

## Scope Lock

Primary product:

- CF first.

Primary frequency:

- Daily.

Primary outputs:

- Daily research brief.
- Factor table.
- Data quality report.
- Research backtest summary.
- Simple run log.

The immediate priority is:

```text
real or production-like CF data
  -> core facts
  -> factors
  -> research backtest
  -> daily research brief
```

## What Stays

The following architectural constraints remain non-negotiable because they
protect research correctness:

- raw/core/research separation
- raw preservation before normalization
- normalized, inspectable core tables
- continuous contracts as signal objects only
- real tradable contracts for backtest and trading-related outputs
- T-day post-settlement signals executing no earlier than T+1
- no future data
- visible contract switch reasons
- explicit last trading day and roll risk

## What Is Downgraded Or Paused

Do not prioritize platform hardening in the next phase.

Downgraded:

- `run_manifest` -> `simple_run_log.jsonl`
- `archive_bundle` -> dated research output folder
- UAT replay -> lightweight periodic replay check
- HTML platform report -> Markdown daily research brief
- monitoring system -> daily data quality check
- artifact registry -> simple report index

Paused:

- release freeze
- gray deployment
- full CI/CD
- multi-user metadata catalog
- production-grade artifact registry
- OMS integration
- minute-level execution
- SR/AP real production ingest before CF is validated
- external spot/weather/USDA ingestion

## Historical Architecture References

The existing platform-style documents remain useful references, but they are no
longer the next execution path:

- `docs/ARCHITECTURE.md`
- `docs/TASK_BREAKDOWN.md`
- `docs/ARCHIVE.md`
- `docs/SMOKE.md`
- `docs/UAT.md`
- `docs/RELEASE_CHECKLIST.md`

Use them to understand previous design decisions. Build new work under the
research workbench path described in `docs/RESEARCH_WORKBENCH_ROADMAP.md`.

## Human Review Boundary

Unknown or ambiguous business rules must be visible as `RESEARCH_TODO` or
`HUMAN_REVIEW_REQUIRED`. They must not be silently converted into production
assumptions.
