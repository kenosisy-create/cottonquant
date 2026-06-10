# Task Breakdown

The implementation follows the planned DAG. The priority is to close a CF MVP
loop first, then harden quality, then prove product extension by config.

## Current Progress

- D0 complete: repository skeleton, configs, docs, and minimal CLI.
- D1 complete: immutable raw snapshot store, SHA256 manifest, and snapshot_id replay.
- D2 complete: CZCE daily quote raw ingestion through a fixture-safe fetcher.
- D3 complete: CZCE historical quote raw backfill through the same raw store.
- D4 complete: CZCE settlement parameter raw ingestion.
- D5 complete: core and archive schema definitions plus field dictionary.
- D6 complete: product config validation and CF contract master generation.
- D7 complete: trading calendar abstraction with reviewed CZCE 2024 official fixture.
- D8 complete: chain_map_daily with explicit switch reasons and LTD/liquidity guards.
- D9 complete: trade_mapping_daily with real contracts, T+1 execution date, and blocks.
- D10 complete: continuous price builder with additive back adjustment and roll traceability.
- D11 complete: factor interface, registry, preprocessing, and dependency validation.
- D12 complete: carry and momentum factors with golden sample tests.
- D13 complete: curve slope and OI pressure factors with golden sample tests.
- D14 complete: forward returns and single factor evaluator with golden sample tests.
- D15 complete: Jinja2 report renderer for single factor and backtest reports.
- D16 complete: daily backtest MVP with T+1 execution, blocked handling, and cost placeholders.
- D17 complete: equal-weight multifactor score and target lots.
- D18 complete: run manifest, artifact registry, audit log, and archive bundle helpers.
- D19 complete: CF full-chain smoke test from fixture/raw to report/archive.
- D20 complete: SR/AP config-only smoke test and extension guide.
- D21 complete: golden fixtures, reproducibility, and CLI validation hardening.
- D22 complete: UAT replay command and JSON/HTML UAT report.
- D23 complete: version freeze, changelog, release bundle, and TODO classification.
- Next task: post-MVP production hardening and human-review closure.

## Phase 1: Foundation And Core Facts

| Task | Scope | Gate |
| --- | --- | --- |
| D0 | Repository skeleton, AGENTS.md, config skeleton, CLI placeholder, docs. | CLI help, tests, lint. |
| D1 | Immutable raw snapshot store, SHA256, manifest, replay by snapshot_id. | Gate A. |
| D2 | CZCE daily quote raw ingestion through fixture-safe fetcher. | Gate A. |
| D3 | CZCE historical quote raw backfill through the same raw store. | Gate A. |
| D4 | CZCE settlement parameter raw ingestion. | Gate A. |
| D5 | Core and archive schema definitions plus field dictionary. | Gate B. |
| D6 | Product config validation and CF contract master generation. | Gate B. |
| D7 | Trading calendar abstraction and provisional fixture calendar. | Gate B. |

## Phase 2: Mapping, Prices, Factors

| Task | Scope | Gate |
| --- | --- | --- |
| D8 | chain_map_daily with switch_reason, LTD guard, and liquidity rules. | Gate B. |
| D9 | trade_mapping_daily from signal objects to real tradable contracts. | Gate B. |
| D10 | Continuous price builder with roll traceability. | Gate B. |
| D11 | Factor interface, registry, preprocessing, dependency validation. | Gate C. |
| D12 | Carry and momentum factors. | Gate C. |
| D13 | Curve slope and OI pressure factors. | Gate C. |
| D14 | Forward returns and single factor evaluator. | Gate C. |

## Phase 3: Reports, Backtest, Archive

| Task | Scope | Gate |
| --- | --- | --- |
| D15 | Jinja2 report renderer for single factor and backtest reports. | Gate C. |
| D16 | Daily backtest with T+1 execution, blocked handling, cost placeholders. | Gate D. |
| D17 | Equal-weight multifactor score and target lots. | Gate D. |
| D18 | Run manifest, artifact registry, audit log, archive bundle. | Gate D. |
| D19 | CF full-chain smoke test from fixture/raw to report/archive. | Gate E. |

## Phase 4: Extension And Release

| Task | Scope | Gate |
| --- | --- | --- |
| D20 | SR/AP config-only smoke test and extension guide. | Gate E. |
| D21 | Golden fixtures, reproducibility, CLI validation hardening. | Gate E. |
| D22 | UAT replay command and UAT report. | Gate E. |
| D23 | Version freeze, changelog, release bundle, TODO classification. | Gate E. |

## Review Gates

- Gate A: raw payloads land completely, every payload has SHA256, manifest replay works,
  raw ingestion does no business normalization, repeated ingestion does not overwrite.
- Gate B: core facts have lineage, contract master follows config, chain map switch reasons
  are explicit, trade mapping uses real contracts or blocked states.
- Gate C: factors declare metadata and inputs, no future data is used, CF-only mode is
  labeled as time-series mode, reports include lineage and warnings.
- Gate D: backtest is strictly T+1, orders use real contracts, costs and blocked states are
  recorded, run manifest captures code/config/input/artifact lineage.
- Gate E: one command runs the fixture chain end to end, replay is deterministic, SR/AP pass
  by config only, release bundle exposes TODOs instead of hiding them.
