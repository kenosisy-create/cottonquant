# Research Workbench Task Breakdown

The completed CF-first research workbench route is `R00` through `R22`. The
historical `D0` through `D23` work remains the engineering foundation, but it is
no longer the execution queue.

## Current Progress

| Task | Status | Scope |
| --- | --- | --- |
| R00 | Complete | Scope locked to a CF-first research-grade production data decision workbench. |
| R01 | Complete | Existing D0-D23 modules mapped into reuse, simplify, pause, and defer groups. |
| R02 | Complete | `configs/research_mode.yaml` defines CF daily mode and paused platform features. |
| R03 | Complete | CF research data source, field mapping, and data quality rules documented. |
| R04 | Complete | Local CF files are preserved under research raw storage with manifest rows. |
| R05 | Complete | Preserved CF CSV files normalize into `core_quote_daily.parquet`. |
| R06 | Complete | Core quote data quality checks write CSV/Markdown and block critical failures. |
| R07 | Complete | CF contract rule review table writes CSV/Markdown with human-review gates. |
| R08 | Complete | Research-mode chain/trade mapping writes CSV/Parquet/Markdown outputs. |
| R09 | Complete | Continuous price artifacts write CSV/Parquet plus roll diagnostics. |
| R10 | Complete | Downstream factor diagnostic output contracts write JSON/Markdown and schema rules. |
| R11 | Complete | Momentum factor value and warning outputs follow the R10 contract. |
| R12 | Complete | Carry factor value and warning outputs follow the R10 contract. |
| R13 | Complete | Curve slope and OI pressure factor outputs follow the R10 contract. |
| R14 | Complete | Daily factor diagnostic table writes long/short/neutral/unknown states. |
| R15 | Complete | T+1-safe forward returns write multi-horizon labels from real contracts. |
| R16 | Complete | Single-factor research backtest summaries write evaluation metrics and warnings. |
| R17 | Complete | Equal-weight multifactor score diagnostics write score rows and warnings. |
| R18 | Complete | Cost sensitivity summaries compare hypothetical cost scenarios. |
| R19 | Complete | Daily CF research brief summarizes R06-R18 evidence and watch items. |
| R20 | Complete | One-command research pipeline runs R04-R19 and writes a simple run log. |
| R21 | Complete | Lightweight replay checks preserved R20 artifacts and optional baselines. |
| R22 | Complete | Expansion gate blocks broader ingestion until CF evidence and review gates exist. |

## Sprint 0: Scope And Configuration

| Task | Scope | Gate |
| --- | --- | --- |
| R00 | Lock project mission to research workbench, not production factor platform. | README/AGENTS direction is explicit. |
| R01 | Classify existing D0-D23 modules for reuse or pause. | Current-state map exists. |
| R02 | Add research mode config for CF daily workflow. | Config loads without release/UAT side effects. |

## Sprint 1: CF Production-Like Data Path

| Task | Scope | Gate |
| --- | --- | --- |
| R03 | Document CF source convention, field aliases, and data quality rules. | Source docs and mapping docs exist. |
| R04 | Preserve local `data/incoming/CF/YYYY-MM-DD/` files into raw storage. | Raw manifest captures hash, size, source file, and run id. |
| R05 | Normalize preserved CSV raw files into core quote facts. | Core parquet rows carry research raw lineage. |
| R06 | Validate core quote completeness, price sanity, uniqueness, and warnings. | Quality CSV/Markdown blocks factors on critical failures. |

## Sprint 2: Mapping And Continuous Signal Objects

| Task | Scope | Gate |
| --- | --- | --- |
| R07 | Build CF contract rule review table. | Human-review items are visible. |
| R08 | Produce research-mode chain and trade mapping outputs. | Switch and blocked reasons are inspectable. |
| R09 | Build continuous price artifacts with roll annotations. | Continuous contracts remain signal objects only. |
| R10 | Define output contract for downstream factor diagnostics. | Stable file paths and schemas are documented and machine-readable. |

## Sprint 3: Factor Diagnostics

| Task | Scope | Gate |
| --- | --- | --- |
| R11 | Adapt momentum factor output to the research workbench path. | Factor rows include input lineage. |
| R12 | Adapt carry factor output to the research workbench path. | Carry assumptions are marked for review. |
| R13 | Adapt curve slope and OI pressure outputs. | Missing inputs surface as warnings, not silent zeros. |
| R14 | Produce daily factor diagnostic table. | Long/short/neutral/unknown state is visible. |

## Sprint 4: Research Backtest

| Task | Scope | Gate |
| --- | --- | --- |
| R15 | Compute forward returns with explicit horizons and price basis. | T+1 rule is enforced. |
| R16 | Run single-factor research backtest summaries. | Results are analysis support, not trading approval. |
| R17 | Run equal-weight multifactor score diagnostics. | Factor weights and missing-factor handling are explicit. |
| R18 | Compare cost scenarios for research sensitivity. | Cost assumptions remain human-review items. |

## Sprint 5: Daily Research Decision Workbench

| Task | Scope | Gate |
| --- | --- | --- |
| R19 | Generate daily CF research brief. | Data quality, factor evidence, mapping, and risks are readable. |
| R20 | Add one-command research pipeline. | R04-R19 can run in order for one date. |

## Sprint 6: Replay And Expansion Gate

| Task | Scope | Gate |
| --- | --- | --- |
| R21 | Add lightweight replay against preserved research outputs. | Results are reproducible enough for analyst review. |
| R22 | Define expansion gate for SR/AP or external data. | CF is validated before broader ingestion begins. |

R00-R22 are now complete for the CF-first research workbench route.

## Deferred Platform Scope

- release freeze
- gray deployment
- production OMS
- minute-level execution
- service API platform
- multi-user dashboard
- SRE-grade monitoring
- full metadata catalog
- SR/AP real production ingest before CF validation
- external spot, weather, and USDA ingestion

## Review Gates

- Raw files must be preserved before parsing.
- Research functions must read core or research artifacts, not incoming files.
- Core rows must include source lineage.
- Continuous contracts are signal objects only.
- Backtest and decision outputs must use real tradable contracts.
- T-day post-settlement signals execute no earlier than T+1.
- Ambiguous exchange, contract, roll, execution, and cost rules must be marked
  `HUMAN_REVIEW_REQUIRED`.
