# Cotton Factor Research Workbench

Research-grade production data decision workbench for China agricultural futures,
starting with CZCE cotton futures CF.

## Current Status

The historical D0-D23 MVP foundation is complete: raw preservation, core
schemas, contract master, chain/trade mapping, continuous prices, the first four
factors, T+1 backtest constraints, reports, archive helpers, smoke checks, QA,
UAT replay, and release freeze artifacts all exist.

The active route is now the R-series research workbench path. R00-R38 are in
place: scope lock, current-state map, research mode config, CF source docs, raw
file preservation, and preserved CSV -> `core_quote_daily.parquet`
normalization, daily data quality CSV/Markdown reports, and CF contract rule
review artifacts, research-mode chain/trade mapping outputs, and continuous
price roll diagnostics, downstream factor diagnostic output contracts, plus
momentum, carry, curve slope, and OI pressure factor value/warning outputs, and
daily long/short/neutral/unknown factor diagnostic states, plus T+1-safe
multi-horizon forward-return labels, plus single-factor research backtest
summaries, plus equal-weight multifactor score diagnostics, plus research cost
sensitivity summaries, plus the daily CF research brief and one-command R20
research pipeline, plus R21 lightweight replay checks, plus the R22 expansion
gate, plus the R23 latest signal-only brief and R24 trend phase classification.
R25 adds rolling trend phase validation that compares S0-S4 phase states with
later real-contract forward-return labels. R26 turns R25 daily rows into phase
transition event studies for S1->S2, S2->S3, S3->S4, and related switches.
R27 filters those event studies into daily-brief trend explanation rule
candidates while keeping weak or sample-poor transitions as watch-only items.
R28 connects those R27 aggregated candidates into the R23 latest signal-only
brief as trend explanation context, without reading raw future-return labels.
R29 adds a latest trend continuity board that tracks recent S0-S4 phases,
transitions, main contract, OI pressure, carry, curve, and multifactor direction
from observable core data only.
R30 extends the transition taxonomy for real-window S0/S3 oscillation patterns:
`S0_TO_S3` and `S3_TO_S0` now flow through R26 event studies, R27 rule
candidates, and R29 transition explanations.
R31 adds a heuristic trend quality score to the R29 board, combining phase,
phase duration, S0/S3 oscillation count, OI pressure, carry/curve, multifactor
direction, and R27 candidate status into a Chinese research explanation field.
R32 adds historical calibration for that score: current-score percentile,
score-bucket后验表现, phase-score distribution, and Chinese Markdown/JSON reports
that keep forward-return labels as validation-only evidence.
R33 connects the R32 calibration manifest and score-bucket aggregate table into
the R29 daily trend continuity board as Chinese context, without reading R32
daily forward-return labels.
R34 adds a Chinese daily operation audit summary that consolidates the R23
latest signal brief, the R29/R33 trend continuity board, core freshness, warning
counts, calibration context, tomorrow watch items, and research-only boundaries.
R35 adds a horizon-aware signal matrix for 1D/3D/5D/10D/20D/40D direction,
phase, confidence, evidence level, and risk flags. R36 validates that matrix in
rolling windows with T+1 forward returns as historical labels only. R37 studies
factor thresholds and filtering/weight candidates from R36 validation rows.
R38 connects the R35 latest matrix snapshot into the R23 latest signal-only
brief while rejecting any input that contains forward-return labels.
R39 connects R37 aggregated threshold/weight candidates into the latest brief
as historical explanation candidates, still requiring human review before any
rule interpretation.
R40 extends that section with non-primary-horizon reference candidates when the
current primary horizon has no READY/WATCH threshold match, explicitly marking
them as cross-horizon context that cannot replace primary-horizon confirmation.
R41 starts the next mainline away from latest-day-only work: it builds a
historical multi-factor evidence pack from R35/R36/R37 full-window artifacts,
including horizon decay, grouped hit/return evidence, cost-sensitive stability,
and Chinese research boundaries.
R42 extends the same full-history path into event explanation: trend starts,
continuations, exhaustion, endings, main-contract switches, OI anomalies, and
curve shocks are extracted from R36 validation rows and summarized with
1/3/5/10/20D historical outcomes.
R43 builds a validated Chinese research brief by combining the latest
signal-only state with R41 historical evidence and R42 event explanations,
while keeping latest observations separate from historical forward-return
validation labels.
R55 connects R54 fundamental context into full-history event explanations; R56
publishes that event-fundamental evidence chain inside the validated brief; R57
pushes the same chain into the WeChat/chart publish pack. R58 adds a one-switch
weekly run mode and writes a weekly run manifest for the R41 -> R55 -> R56 -> R57
chain. R59 turns that weekly manifest into a Chinese weekly audit report covering
artifact completeness, event-threshold review, fundamental interpretation review,
event-fundamental coverage, and research boundaries. R60 adds a dedicated event
threshold sensitivity review pack for baseline R55 events plus OI anomaly and
curve-shock quantile thresholds, producing KEEP/WATCH/REVISE/REJECT review
candidates without turning them into trading rules. R62 turns those R60
candidates into a traceable manual-review ledger with event examples, factor
context, fundamental context when available, and explicit research boundaries.
R63 adds a data continuity and retention audit for daily official files, core
tables, official calendar continuity, checksums, and raw snapshot traceability.
R65 adds a CF stage decision pack that combines R59 weekly audit, R52 expansion
gate, latest signal state, R48 option factors, and R60 threshold review into a
Chinese go/no-go review artifact before any non-CF pilot. Future work should
stay on the CF-first research route until human review clears the R65/R52
expansion boundary.

## Current Direction

The project is no longer being pushed as a full production-grade factor
platform. The current engineering direction is a CF-first research workbench:

```text
real or production-like CF daily data
  -> core facts
  -> factor diagnostics
  -> research backtest
  -> daily research brief
```

D0-D23 remain the historical foundation. They are not the next execution path.
Do not prioritize platform hardening, release machinery, gray deployment,
multi-user dashboards, OMS integration, or SR/AP production ingest before CF is
validated.

The current research direction is documented in:

- `docs/PROJECT_INTRO_FOR_ARCHITECTURE.md`
- `docs/PROJECT_DIRECTION.md`
- `docs/CURRENT_STATE_RESEARCH_MAP.md`
- `docs/RESEARCH_WORKBENCH_ROADMAP.md`
- `docs/CF_CONTRACT_RULE_REVIEW.md`
- `docs/RESEARCH_MAPPING.md`
- `docs/RESEARCH_CONTINUOUS_PRICE.md`
- `docs/RESEARCH_OUTPUT_CONTRACTS.md`
- `docs/RESEARCH_MOMENTUM_FACTOR.md`
- `docs/RESEARCH_CARRY_FACTOR.md`
- `docs/RESEARCH_STRUCTURE_FACTORS.md`
- `docs/RESEARCH_FACTOR_DIAGNOSTICS.md`
- `docs/RESEARCH_FORWARD_RETURNS.md`
- `docs/RESEARCH_SINGLE_FACTOR_BACKTESTS.md`
- `docs/RESEARCH_MULTIFACTOR_DIAGNOSTICS.md`
- `docs/RESEARCH_COST_SENSITIVITY.md`
- `docs/RESEARCH_DAILY_BRIEF.md`
- `docs/RESEARCH_DAILY_PIPELINE.md`
- `docs/RESEARCH_REPLAY.md`
- `docs/RESEARCH_EXPANSION_GATE.md`
- `docs/RESEARCH_DATA_PORTS_NEXT.md`
- `docs/POST_R22_CF_VALIDATION_PACK.md`

## Architecture

The system is built around four layers:

1. Raw snapshot: immutable exchange payloads plus checksums, append-only
   manifests, and replay by snapshot_id.
2. Core facts: normalized, schema-versioned facts linked to raw snapshots.
3. Research derived: continuous prices, factors, forward returns, and evaluations.
4. Archive and audit: run manifests, checksums, reports, logs, and bundles.

Research code must never parse raw exchange files directly. Continuous contracts
are signal objects only. Orders, fills, costs, and positions must always use real
tradable contracts. Daily signals use T-day post-settlement data and execute on
T+1.

## Setup

This project requires Python 3.11+. On this Windows machine, the default
`python` currently points to Python 3.8, so use `py -3.12` or a newer 3.11+
runtime explicitly.

```bash
py -3.12 -m pip install -e ".[dev]"
```

## Commands

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main --help
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main status
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-calendar --start 2024-01-01 --end 2024-01-10 --exchange CZCE
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-contract-master --product CF --year 2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-chain-map --product CF --start 2024-01-09 --end 2024-01-12 --quote-fixture tests/fixtures/core_quote_daily_cf_chain_sample.csv --ltd-buffer-days 2
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-trade-mapping --product CF --start 2024-01-09 --end 2024-01-12 --quote-fixture tests/fixtures/core_quote_daily_cf_chain_sample.csv --ltd-buffer-days 2
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-continuous-price --product CF --start 2024-01-09 --end 2024-01-12 --quote-fixture tests/fixtures/core_quote_daily_cf_chain_sample.csv --ltd-buffer-days 2
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main ingest czce-daily-quote --date 2024-01-02 --product CF --fixture tests/fixtures/czce_daily_quote_sample.html
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main ingest czce-history --year 2024 --product CF --file-type csv --fixture tests/fixtures/czce_history_2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main ingest czce-settlement --date 2024-01-02 --product CF --fixture tests/fixtures/czce_settlement_param_sample.csv
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main raw list --source CZCE_HISTORY_QUOTE --product CF --year 2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main smoke cf --start 2024-01-01 --end 2024-01-05 --dry-run
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main smoke cf --start 2024-01-02 --end 2024-02-05 --run
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main smoke products --products SR,AP --year 2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main qa validate-csv --table core_quote_daily --csv tests/fixtures/core_quote_daily_cf_chain_sample.csv
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main qa audit-csv --table core_quote_daily --csv tests/fixtures/core_quote_daily_cf_chain_sample.csv --min-row-count 8 --max-null-ratio settle=0
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main uat replay --scenario cf_mvp_fixture
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main release freeze --version 0.1.0
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research ingest-cf --date 2026-06-11 --input-path data/incoming/CF/2026-06-11
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research normalize-cf-quotes --date 2026-06-11
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research check-cf-quality --date 2026-06-11
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research review-cf-contract-rules --year 2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-mapping --start 2024-01-09 --end 2024-01-12 --ltd-buffer-days 2
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-continuous --start 2024-01-09 --end 2024-01-12
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research write-cf-factor-output-contract
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-momentum-factor --start 2024-01-21 --end 2024-01-21 --continuous-price-path data/research/CF/continuous/CF_2024-01-01_2024-01-21_settle_continuous_price_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-carry-factor --start 2024-01-09 --end 2024-01-09 --core-quote-path data/core/CF/core_quote_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-structure-factors --start 2024-01-09 --end 2024-01-09 --core-quote-path data/core/CF/core_quote_daily.parquet --chain-map-path data/research/CF/mapping/CF_2024-01-09_2024-01-09_chain_map_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-factor-diagnostics --start 2024-01-09 --end 2024-01-09 --factor-value-path data/research/CF/factors/CF_2024-01-09_2024-01-09_factor_value_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-forward-returns --start 2024-01-09 --end 2024-01-12 --horizons 1,3,5 --core-quote-path data/core/CF/core_quote_daily.parquet --trade-mapping-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_trade_mapping_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-single-factor-backtest --start 2024-01-09 --end 2024-01-12 --factor-ids mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1 --horizons 1,3,5 --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet --forward-return-path data/research/CF/returns/CF_2024-01-09_2024-01-12_forward_return_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-multifactor-diagnostics --start 2024-01-09 --end 2024-01-12 --factor-ids mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1 --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-cost-sensitivity --start 2024-01-09 --end 2024-01-12 --horizons 1,3,5 --score-path data/research/CF/multifactor/CF_2024-01-09_2024-01-12_multifactor_score_daily.parquet --forward-return-path data/research/CF/returns/CF_2024-01-09_2024-01-12_forward_return_daily.parquet --scenario-cost-bps no_cost=0,normal_cost=5,conservative_cost=10
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-daily-brief --date 2024-01-09 --start 2024-01-09 --end 2024-01-12 --quality-csv-path reports/research/data_quality/CF_2024-01-09_quality.csv --chain-map-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_chain_map_daily.parquet --trade-mapping-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_trade_mapping_daily.parquet --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet --single-factor-evaluation-path data/research/CF/backtests/CF_2024-01-09_2024-01-12_single_factor_evaluation.parquet --multifactor-score-path data/research/CF/multifactor/CF_2024-01-09_2024-01-12_multifactor_score_daily.parquet --cost-sensitivity-path data/research/CF/cost_sensitivity/CF_2024-01-09_2024-01-12_cost_sensitivity_summary.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-latest-signal-brief --core-quote-path data/core/CF/core_quote_daily.parquet --output-root runs/daily --trend-rule-candidate-path data/research/CF/trend_rule_candidates/CF_2026-02-26_2026-06-24_trend_rule_candidates.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-signal-matrix --start 2021-01-04 --end 2026-07-01 --horizons 1,3,5,10,20,40 --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/signal_matrix --report-output-dir reports/research/signal_matrix --trend-rule-candidate-path data/research/CF/trend_rule_candidates/CF_2026-02-26_2026-06-24_trend_rule_candidates.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-signal-matrix --start 2021-01-04 --end 2026-07-03 --horizons 1,3,5,10,20,40 --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/signal_matrix --report-output-dir reports/research/signal_matrix --option-factor-path data/research/CF/option_factors/CF_2021-01-04_2026-07-03_option_factor_proxy_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-signal-matrix-validation --signal-matrix-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-01_signal_matrix_daily.parquet --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/signal_matrix_validation --report-output-dir reports/research/signal_matrix_validation --windows 2021-2022,2022-2023,2023-2024,2024-2025,2025-2026
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-signal-threshold-research --validation-daily-path data/research/CF/signal_matrix_validation/CF_2021-01-04_2026-07-01_signal_matrix_validation_daily.parquet --output-dir data/research/CF/signal_threshold_research --report-output-dir reports/research/signal_threshold_research
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-historical-evidence-pack --core-quote-path data/core/CF/core_quote_daily.parquet --signal-matrix-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-01_signal_matrix_daily.parquet --validation-daily-path data/research/CF/signal_matrix_validation/CF_2021-01-04_2026-07-01_signal_matrix_validation_daily.parquet --validation-window-summary-path data/research/CF/signal_matrix_validation/CF_2021-01-04_2026-07-01_signal_matrix_validation_window_summary.parquet --threshold-weighting-path data/research/CF/signal_threshold_research/CF_2021-01-04_2026-07-01_signal_threshold_research_weighting.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-historical-event-explanation --validation-daily-path data/research/CF/signal_matrix_validation/CF_2021-01-04_2026-07-03_signal_matrix_validation_daily.parquet --output-dir data/research/CF/event_explanation --report-output-dir reports/research/event_explanation --primary-horizon 20 --horizons 1,3,5,10,20 --fundamental-context-path data/research/CF/fundamental_context/CF_fundamental_context_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-event-threshold-sensitivity --validation-daily-path data/research/CF/signal_matrix_validation/CF_2021-01-04_2026-07-03_signal_matrix_validation_daily.parquet --event-path data/research/CF/event_explanation/CF_2021-01-04_2026-07-03_event_explanation_events.parquet --output-dir data/research/CF/event_threshold_sensitivity --report-output-dir reports/research/event_threshold_sensitivity --primary-horizon 20 --horizons 1,3,5,10,20 --threshold-quantiles 0.90,0.95,0.975
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-event-threshold-review-ledger --threshold-summary-path data/research/CF/event_threshold_sensitivity/CF_2021-01-04_2026-07-03_event_threshold_sensitivity_summary.parquet --threshold-detail-path data/research/CF/event_threshold_sensitivity/CF_2021-01-04_2026-07-03_event_threshold_sensitivity_detail.parquet --event-detail-path data/research/CF/event_explanation/CF_2021-01-04_2026-07-03_event_explanation_events.parquet --output-dir data/research/CF/event_threshold_review --report-output-dir reports/research/event_threshold_review
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-validated-research-brief --latest-signal-json-path runs/daily/CF/2026-07-03/latest_signal_brief.json --historical-evidence-decay-path data/research/CF/historical_evidence/CF_2021-01-04_2026-07-03_historical_evidence_decay.parquet --historical-evidence-stability-path data/research/CF/historical_evidence/CF_2021-01-04_2026-07-03_historical_evidence_stability.parquet --event-summary-path data/research/CF/event_explanation/CF_2021-01-04_2026-07-03_event_explanation_summary.parquet --event-detail-path data/research/CF/event_explanation/CF_2021-01-04_2026-07-03_event_explanation_events.parquet --event-threshold-summary-path data/research/CF/event_threshold_sensitivity/CF_2021-01-04_2026-07-03_event_threshold_sensitivity_summary.parquet --fundamental-observation-json-path data/research/CF/fundamentals/CF_fundamental_observation.json --output-dir reports/research/validated_brief --daily-output-root runs/daily
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-publish-pack --latest-signal-json-path runs/daily/CF/2026-07-03/latest_signal_brief.json --validated-brief-path runs/daily/CF/2026-07-03/validated_research_brief.md --core-quote-path data/core/CF/core_quote_daily.parquet --signal-matrix-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-03_signal_matrix_daily.parquet --historical-evidence-decay-path data/research/CF/historical_evidence/CF_2021-01-04_2026-07-03_historical_evidence_decay.parquet --event-summary-path data/research/CF/event_explanation/CF_2021-01-04_2026-07-03_event_explanation_summary.parquet --output-root runs/daily
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-weekly-research-audit --weekly-manifest-path runs/weekly/CF/2026-07-03/weekly_research_run_manifest.json --output-dir reports/research/weekly_audit
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-stage-decision-pack --weekly-audit-json-path reports/research/weekly_audit/CF_2026-07-06_weekly_research_audit.json --expansion-gate-json-path reports/research/expansion_gate/CF_SR_AP_OR_EXTERNAL_DATA_r64_latest_evidence_20260706_with_r20_r21_expansion_gate.json --latest-signal-json-path runs/daily/CF/2026-07-06/latest_signal_brief.json --option-factor-json-path reports/research/option_factors/CF_2021-01-04_2026-07-06_option_factor_proxy.json --event-threshold-json-path reports/research/event_threshold_sensitivity/CF_2021-01-04_2026-07-06_event_threshold_sensitivity.json --output-dir reports/research/stage_decision --daily-output-root runs/daily
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-event-lifecycle-research --signal-matrix-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-17_signal_matrix_daily.parquet --output-dir data/research/CF/event_lifecycle --report-output-dir reports/research/event_lifecycle --horizon 20
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-state-transition-competing-risk --event-lifecycle-episode-path data/research/CF/event_lifecycle/CF_2021-01-04_2026-07-17_event_lifecycle_episodes.parquet --output-dir data/research/CF/state_transition --report-output-dir reports/research/state_transition --max-age-days 20 --min-sample-size 30
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-futures-option-divergence-research --signal-matrix-validation-path data/research/CF/signal_matrix_validation/CF_2021-01-04_2026-07-06_signal_matrix_validation_daily.parquet --event-lifecycle-tbm-path data/research/CF/event_lifecycle/CF_2021-01-04_2026-07-06_event_lifecycle_tbm_labels.parquet --output-dir data/research/CF/futures_option_divergence --report-output-dir reports/research/futures_option_divergence --horizons 1,3,5,10,20,40
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-futures-option-divergence-playbook --event-path data/research/CF/futures_option_divergence/CF_2021-01-04_2026-07-06_futures_option_divergence_divergence_event_daily.parquet --node-summary-path data/research/CF/futures_option_divergence/CF_2021-01-04_2026-07-06_futures_option_divergence_summary_by_node.parquet --latest-signal-json-path runs/daily/CF/2026-07-07/latest_signal_brief.json --output-dir data/research/CF/futures_option_divergence_playbook --report-output-dir reports/research/futures_option_divergence_playbook
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-dual-price-state --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/dual_price_state --report-output-dir reports/research/dual_price_state
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-chain-oi-structure --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/chain_oi_structure --report-output-dir reports/research/chain_oi_structure --roll-lookback-days 5
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-oi-roll-window-research --core-quote-path data/core/CF/core_quote_daily.parquet --windows 3,5,10 --output-dir data/research/CF/oi_roll_window --report-output-dir reports/research/oi_roll_window
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-option-structure-research --option-factor-path data/research/CF/option_factors/CF_2021-01-04_2026-07-13_option_factor_proxy_daily.parquet --signal-matrix-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-13_signal_matrix_daily.parquet --output-dir data/research/CF/option_structure --report-output-dir reports/research/option_structure
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-trend-phase-v2 --dual-price-path data/research/CF/dual_price_state/CF_2021-01-04_2026-07-13_dual_price_state_daily.parquet --chain-oi-path data/research/CF/chain_oi_structure/CF_2021-01-04_2026-07-13_chain_oi_structure_daily.parquet --option-structure-path data/research/CF/option_structure/CF_2021-01-04_2026-07-13_option_structure_daily.parquet --signal-matrix-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-13_signal_matrix_daily.parquet --output-dir data/research/CF/trend_phase_v2 --report-output-dir reports/research/trend_phase_v2
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-current-watch-window --latest-signal-json-path runs/daily/CF/2026-07-13/latest_signal_brief.json --dual-price-path data/research/CF/dual_price_state/CF_2021-01-04_2026-07-13_dual_price_state_daily.parquet --chain-oi-path data/research/CF/chain_oi_structure/CF_2021-01-04_2026-07-13_chain_oi_structure_daily.parquet --option-structure-path data/research/CF/option_structure/CF_2021-01-04_2026-07-13_option_structure_daily.parquet --trend-phase-v2-path data/research/CF/trend_phase_v2/CF_2021-01-04_2026-07-13_trend_phase_v2_daily.parquet --output-dir data/research/CF/current_watch_window --report-output-dir reports/research/current_watch_window --daily-output-root runs/daily
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-validated-research-brief --futures-option-divergence-json-path reports/research/futures_option_divergence/CF_2021-01-04_2026-07-06_futures_option_divergence.json --futures-option-playbook-json-path reports/research/futures_option_divergence_playbook/CF_2021-01-04_2026-07-06_futures_option_playbook.json --state-transition-json-path reports/research/state_transition/CF_2021-02-03_2026-07-17_state_transition_competing_risk.json --option-volatility-json-path reports/research/option_volatility/CF_2021-01-04_2026-07-17_option_volatility.json
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-publish-pack --futures-option-divergence-json-path reports/research/futures_option_divergence/CF_2021-01-04_2026-07-06_futures_option_divergence.json --futures-option-playbook-json-path reports/research/futures_option_divergence_playbook/CF_2021-01-04_2026-07-06_futures_option_playbook.json
.\scripts\update_cf_latest_research.ps1 -RunFuturesOptionDivergence -RunValidatedBrief -RunPublishPack
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-option-data-contract --source-dir data/incoming/CF/options/history --core-output-dir data/core --report-output-dir reports/research/option_data_contract
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-option-history --source-dir data/incoming/CF/options/history --raw-root data/raw --core-output-dir data/core --core-quote-path data/core/CF/core_quote_daily.parquet --report-output-dir reports/research/option_core_ingest
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-option-factor-proxy --option-core-path data/core/CF/core_option_quote_daily.parquet --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/option_factors --report-output-dir reports/research/option_factors
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-option-volatility-term-structure --option-factor-path data/research/CF/option_factors/CF_2021-01-04_2026-07-17_option_factor_proxy_daily.parquet --core-quote-path data/core/CF/core_quote_daily.parquet --option-expiry-path configs/products/CF_OPTION_EXPIRY_OFFICIAL.csv --output-dir data/research/CF/option_volatility --report-output-dir reports/research/option_volatility --risk-free-rate 0.02 --rv-window 20 --iv-rank-window 252 --horizons 5,10,20
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-product-research-registry --output-dir data/research/CF/product_registry --report-output-dir reports/research/product_registry
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-fundamental-data-contract --source-dir data/incoming/CF/fundamentals/manual --output-dir data/research/CF/fundamentals --report-output-dir reports/research/fundamentals
$env:PYTHONPATH="src"; $env:PYTHONIOENCODING="utf-8"; py -3.12 -m cotton_factor.cli.main research build-cf-fundamental-observation --source-dir data/incoming/CF/fundamentals/manual --output-dir data/research/CF/fundamentals --report-output-dir reports/research/fundamentals
$env:PYTHONPATH="src"; $env:PYTHONIOENCODING="utf-8"; py -3.12 -m cotton_factor.cli.main research build-cf-fundamental-context --fundamental-observation-json-path data/research/CF/fundamentals/CF_fundamental_observation.json --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/fundamental_context --report-output-dir reports/research/fundamental_context --change-windows 1,4,12
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research fetch-cf-official-daily-files --date 2026-07-06 --futures-source-dir data/incoming/CF/history --options-source-dir data/incoming/CF/options/history --report-output-dir reports/research/official_daily_files
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-latest-signal-brief --core-quote-path data/core/CF/core_quote_daily.parquet --output-root runs/daily --signal-matrix-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-01_signal_matrix_latest_snapshot.json --signal-threshold-research-path data/research/CF/signal_threshold_research/CF_2021-01-04_2026-07-01_signal_threshold_research_weighting.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-trend-continuity-board --core-quote-path data/core/CF/core_quote_daily.parquet --output-root runs/daily --lookback-trading-days 20 --trend-rule-candidate-path data/research/CF/trend_rule_candidates/CF_2026-02-26_2026-06-24_trend_rule_candidates.parquet --trend-quality-calibration-manifest-path data/research/CF/trend_quality_calibration/CF_2026-02-26_2026-07-01_trend_quality_calibration_manifest.json
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-daily-operation-audit --latest-signal-json-path runs/daily/CF/2026-07-01/latest_signal_brief.json --trend-board-json-path runs/daily/CF/2026-07-01/trend_continuity_board.json --core-quote-path data/core/CF/core_quote_daily.parquet --output-root runs/daily
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-trend-quality-calibration --start 2026-02-26 --end 2026-07-01 --horizons 1,3,5,10,20 --core-quote-path data/core/CF/core_quote_daily.parquet --trend-rule-candidate-path data/research/CF/trend_rule_candidates/CF_2026-02-26_2026-06-24_trend_rule_candidates.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-trend-phase-validation --start 2026-02-26 --end 2026-06-24 --horizons 1,3,5,10,20 --core-quote-path data/core/CF/core_quote_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-trend-phase-events --start 2026-02-26 --end 2026-06-24 --horizons 1,3,5,10,20 --trend-phase-daily-path data/research/CF/trend_phase_validation/CF_2026-02-26_2026-06-24_trend_phase_validation_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-trend-rule-candidates --start 2026-02-26 --end 2026-06-24 --event-summary-path data/research/CF/trend_phase_events/CF_2026-02-26_2026-06-24_trend_phase_events_summary.parquet --event-path data/research/CF/trend_phase_events/CF_2026-02-26_2026-06-24_trend_phase_events_events.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-daily-pipeline --date 2024-01-10 --start 2024-01-09 --end 2024-01-12 --input-path data/incoming/CF/2024-01-10 --horizons 1,3,5 --scenario-cost-bps no_cost=0,normal_cost=5,conservative_cost=10
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research replay-cf-daily-pipeline --pipeline-json-path reports/research/pipeline/CF_2024-01-10_r20_pipeline_pipeline.json
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-expansion-gate --gate-version R22 --candidate-scope SR_AP --pipeline-json-path reports/research/pipeline/CF_2024-01-10_r20_pipeline_pipeline.json --replay-json-path reports/research/replay/CF_2024-01-10_r21_replay_replay.json
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-expansion-gate --candidate-scope SR_AP --pipeline-json-path reports/research/pipeline/CF_2024-01-10_r20_pipeline_pipeline.json --replay-json-path reports/research/replay/CF_2024-01-10_r21_replay_replay.json --historical-evidence-manifest-path data/research/CF/historical_evidence/CF_2021-01-04_2026-07-01_historical_evidence_manifest.json --event-explanation-manifest-path data/research/CF/event_explanation/CF_2021-01-04_2026-07-01_event_explanation_manifest.json --signal-matrix-manifest-path data/research/CF/signal_matrix/CF_2021-01-04_2026-07-03_signal_matrix_manifest.json --publish-pack-manifest-path runs/daily/CF/2026-07-01/publish/manifest.json --product-registry-manifest-path data/research/CF/product_registry/CF_product_research_registry_manifest.json --fundamental-contract-manifest-path data/research/CF/fundamentals/CF_fundamental_data_contract_manifest.json
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-official-history --years 2023,2024,2025 --source-dir data/incoming/CF/history
$env:PYTHONPATH="src"; powershell -ExecutionPolicy Bypass -File scripts/update_cf_latest_research.ps1 -Year 2026
$env:PYTHONPATH="src"; powershell -ExecutionPolicy Bypass -File scripts/update_cf_latest_research.ps1 -Year 2026 -RunResearchWindow
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-validation-pack --date 2024-01-31 --start 2024-01-22 --end 2024-01-31 --horizons 1 --lookback-periods 3
```

For daily CF updates, place the newest official file under
`data/incoming/CF/history/` as one of `CFFUTURES{year}.xlsx`,
`CFFUTURES{year}.xls`, or `ALLFUTURES{year}.zip`, then run
`scripts/update_cf_latest_research.ps1`. The default mode updates raw/core data,
refreshes `configs/calendars/CZCE_{year}_OFFICIAL.csv` from confirmed CF trade
dates, and writes the R23 latest signal-only brief under
`runs/daily/CF/{trade_date}/`. It now also builds the R35 signal matrix first
and passes the R35 latest snapshot into R23, so the R38 multi-horizon matrix
section appears in the latest brief. The script then writes the R29 trend
continuity board and R34 daily operation audit summary in the same folder.
Pass `-TrendRuleCandidatePath` to connect R27 aggregated trend-rule
candidates into the R23 trend section and R29 transition table. Pass
`-TrendQualityCalibrationManifestPath` to connect R32 aggregated trend-quality
calibration into the R29 board without reading daily forward-return labels.
Pass `-SignalThresholdResearchPath` to connect R37 aggregated threshold/weight
candidates into the R39/R40 latest-brief explanation section. When the current
primary horizon has no READY/WATCH match, the brief can display other-horizon
reference candidates, but they remain research context only.
To fetch official daily futures and options directly, use:

```powershell
.\scripts\update_cf_latest_research.ps1 -DownloadOfficialDaily -DownloadDate 2026-07-06
```

CZCE daily URLs use `YYYY` for the year directory and `YYYYMMDD` for the date
directory:

```text
https://www.czce.com.cn/cn/DFSStaticFiles/Future/YYYY/YYYYMMDD/FutureDataDailyCF.xlsx
https://www.czce.com.cn/cn/DFSStaticFiles/Option/YYYY/YYYYMMDD/OptionDataDaily.xlsx
https://www.czce.com.cn/cn/DFSStaticFiles/Future/YYYY/YYYYMMDD/FutureDataHolding.xlsx
```

The daily downloader saves futures under
`data/incoming/CF/history/daily/YYYY/YYYYMMDD/` and options under
`data/incoming/CF/options/history/daily/YYYY/YYYYMMDD/`. The script then connects futures into
`core_quote_daily.parquet` and option history into
`core_option_quote_daily.parquet`. Use `-SkipOptionDailyDownload` for futures
only and `-OverwriteOfficialDaily` to refresh an existing incoming file.
After core refresh, the script runs the R63 data continuity audit by default.
It verifies futures/option core freshness, official calendar continuity,
downloaded-file checksums, and raw snapshot retention before the research
brief chain continues. Downloaded Excel files are retained by default. Use
`-RemoveDownloadedDailyAfterIngest` only when the R63 audit has passed and you
want to remove the specific newly downloaded incoming files:

Official daily option updates now rebuild R48 automatically. The daily path uses
an incremental latest-date build and merges it into the existing historical
factor/surface artifacts; `-RunWeeklyResearchPack` keeps the full-history rebuild
for periodic verification. The script prints the option-factor and total elapsed
seconds so daily performance regressions remain visible.

R83 keeps member-position research in the weekly lane. Download and normalize
the official ranking workbook, then build Top5/10/20 concentration, member long/
short change, price/OI divergence, and roll-migration evidence with:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research fetch-cf-official-member-position-history --start 2021-01-04 --end 2026-07-20 --core-quote-path data/core/CF/core_quote_daily.parquet --source-dir data/incoming/CF/member_positions/history --max-workers 6
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research fetch-cf-official-member-position --date 2026-07-17 --source-dir data/incoming/CF/member_positions/history
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-member-position-history --source-dir data/incoming/CF/member_positions/history --output-path data/core/CF/core_member_position_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-member-position-research --member-position-path data/core/CF/core_member_position_daily.parquet --core-quote-path data/core/CF/core_quote_daily.parquet
```

R85 makes the historical fetch and connector incremental. The batch downloader
uses only trade dates confirmed by CF core, prefers the verified `.xls` format
for 2021-2025 and `.xlsx` from 2026, writes a status CSV and manifest, and reuses
valid incoming files on rerun. The connector reuses immutable raw snapshots by
checksum and returns `NO_CHANGES` when all files are already represented in
core. Historical header aliases and official `-` placeholders are normalized
without treating missing ranks as zero positions.

The normalized table stores volume, long and short rankings as independent
rows because the member name at the same rank can differ across all three
lists. Member rankings may include customer aggregates and are not treated as
identified customer net exposure. Missing history is reported as
`MISSING_MEMBER_POSITION_HISTORY`; aggregate futures OI is never substituted.
Use `-RunMemberPositionResearch` for an ad-hoc run. The weekly pack runs R83 by
default and downloads the current holding workbook only when
`-DownloadOfficialDaily` is also explicitly supplied.

R84 adds strike-level option open-interest research. It reports Call/Put OI
walls, daily build/unwind strikes, OI centers, wall migration, a static max-pain
proxy and T+1 historical wall-crossing paths:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-option-strike-position-research --option-core-path data/core/CF/core_option_quote_daily.parquet --core-quote-path data/core/CF/core_quote_daily.parquet --option-expiry-path configs/products/CF_OPTION_EXPIRY_OFFICIAL.csv --horizons 1,3,5,10
```

Use `-RunOptionStrikePositionResearch` for an ad-hoc run. R84 stays in the
weekly lane because its full-history path validation is intentionally heavier.
Public OI does not reveal who bought or sold the option, so R84 does not infer
dealer gamma and does not treat a high-OI strike as an automatic support or
resistance level.

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-data-continuity-audit --date 2026-07-06 --core-quote-path data/core/CF/core_quote_daily.parquet --option-core-path data/core/CF/core_option_quote_daily.parquet --calendar-path configs/calendars/CZCE_2026_OFFICIAL.csv --official-daily-fetch-json-path reports/research/official_daily_files/CF_2026-07-06_official_daily_files.json
.\scripts\update_cf_latest_research.ps1 -DownloadOfficialDaily -DownloadDate 2026-07-06 -RemoveDownloadedDailyAfterIngest
```

Pass `-OptionFactorPath` to connect an existing R48 option factor proxy table
into the R49 signal-matrix option filter. This fills `option_signal` in the
matrix and latest brief, but it does not change `composite_score`.
Pass `-RunHistoricalEvidence` for a weekly/manual R41 historical evidence pack;
pass `-RunEventExplanation` for a weekly/manual R42/R55 historical event
explanation pack, pass `-RunEventThresholdSensitivity` for the R60 event
threshold sensitivity review pack, and pass `-RunValidatedBrief` to build the
R43/R56 validated Chinese research brief. The public-account publishing lane is
paused by default; `-RunPublishPack` remains an explicit manual command for a
future publication review and is not included in the weekly pack. When
R54 fundamental context, R55 event details, R60 threshold summary, or R53
observation JSON already exist, the weekly script passes them forward
automatically. Default daily updates do not run these weekly research/publish
steps.
Default daily updates also skip the R34 operation audit to keep the research
refresh fast. Use `-RunDailyOperationAudit` only for an ad-hoc review.
Use `-RunWeeklyResearchPack` after the final official trading session of each
week (normally the fifth trading day) as the one-switch weekly path for
R41 -> R83 -> R84 -> R55 -> R60 -> R69 -> R71 -> R56 -> R59, a run manifest, and a weekly
audit report:

```powershell
.\scripts\update_cf_latest_research.ps1 -Year 2026 -RunWeeklyResearchPack
```

The weekly manifest is written to
`runs\weekly\CF\<data_asof>\weekly_research_run_manifest.json`.
The weekly audit is written to
`reports\research\weekly_audit\CF_<data_asof>_weekly_research_audit.md`.
Holiday-shortened weeks should use the final official trading day rather than
waiting for a nonexistent fifth session.
`-RunResearchWindow` additionally runs the latest window with enough future observations for
1/3/5-day research labels.

Research workbench configuration is available from Python:

```python
from cotton_factor.research_workbench import (
    build_cf_contract_rule_review,
    build_cf_carry_factor,
    build_cf_cost_sensitivity,
    build_cf_daily_brief,
    build_cf_daily_operation_audit,
    build_cf_daily_research_pipeline,
    build_cf_expansion_gate,
    build_cf_latest_signal_brief,
    build_cf_option_data_contract,
    build_cf_publish_pack,
    build_cf_signal_matrix,
    build_cf_signal_matrix_validation,
    build_cf_signal_threshold_research,
    build_cf_trend_continuity_board,
    build_cf_trend_quality_calibration,
    build_cf_research_continuous,
    build_cf_research_mapping,
    build_cf_trend_phase_events,
    build_cf_trend_phase_validation,
    build_cf_trend_rule_candidates,
    build_cf_factor_output_contract,
    build_cf_factor_diagnostics,
    build_cf_momentum_factor,
    build_cf_multifactor_diagnostics,
    build_cf_forward_returns,
    build_cf_post_r22_validation_pack,
    build_cf_structure_factors,
    build_cf_single_factor_backtest,
    check_cf_data_quality,
    classify_cf_trend_phase,
    connect_cf_official_history,
    connect_cf_option_history,
    ingest_cf_raw,
    load_research_mode_config,
    normalize_cf_core_quotes,
    replay_cf_research_pipeline_outputs,
)

config = load_research_mode_config()
result = normalize_cf_core_quotes(trade_date=...)
quality = check_cf_data_quality(trade_date=...)
review = build_cf_contract_rule_review(year=2024)
mapping = build_cf_research_mapping(start=..., end=...)
continuous = build_cf_research_continuous(start=..., end=...)
contract = build_cf_factor_output_contract()
momentum = build_cf_momentum_factor(start=..., end=..., continuous_price_path=...)
carry = build_cf_carry_factor(start=..., end=..., core_quote_path=...)
structure = build_cf_structure_factors(start=..., end=..., core_quote_path=..., chain_map_path=...)
diagnostics = build_cf_factor_diagnostics(start=..., end=..., factor_value_path=...)
forward_returns = build_cf_forward_returns(start=..., end=..., trade_mapping_path=...)
single_factor = build_cf_single_factor_backtest(start=..., end=..., diagnostic_path=...)
multifactor = build_cf_multifactor_diagnostics(start=..., end=..., diagnostic_path=...)
costs = build_cf_cost_sensitivity(start=..., end=..., score_path=..., forward_return_path=...)
brief = build_cf_daily_brief(trade_date=..., start=..., end=...)
latest = build_cf_latest_signal_brief(core_quote_path=...)
trend_board = build_cf_trend_continuity_board(core_quote_path=...)
trend_quality_calibration = build_cf_trend_quality_calibration(core_quote_path=...)
phase = classify_cf_trend_phase(signal_states=..., latest_settle=..., ma20=...)
phase_validation = build_cf_trend_phase_validation(start=..., end=...)
phase_events = build_cf_trend_phase_events(start=..., end=..., trend_phase_daily_path=...)
trend_rules = build_cf_trend_rule_candidates(start=..., end=..., event_summary_path=...)
pipeline = build_cf_daily_research_pipeline(trade_date=..., input_path=..., start=..., end=...)
replay = replay_cf_research_pipeline_outputs(pipeline_json_path=...)
gate = build_cf_expansion_gate(pipeline_json_path=..., replay_json_path=...)
official_history = connect_cf_official_history(years=(2023, 2024, 2025))
validation = build_cf_post_r22_validation_pack()
```

Core schema helpers are available from Python:

```python
from cotton_factor.core import validate_row

row = validate_row("core_quote_daily", {...})
```

Factor framework helpers are available from Python:

```python
from cotton_factor.research import load_factor_registry

registry = load_factor_registry()
momentum = registry.get("mom_20_v1")
```

D12/D13 factors are available from Python:

```python
from cotton_factor.research import (
    compute_carry_factor,
    compute_curve_slope_factor,
    compute_momentum_factor,
    compute_oi_pressure_factor,
)
```

D14 evaluation helpers are available from Python:

```python
from cotton_factor.research import build_forward_returns, evaluate_single_factor
```

D15 report helpers are available from Python:

```python
from cotton_factor.archive import render_backtest_report, render_single_factor_report
```

D18 archive helpers are available from Python:

```python
from cotton_factor.archive import (
    AuditLogWriter,
    build_archive_bundle,
    build_run_manifest,
    register_artifact,
)
```

D19 smoke workflow is available from Python:

```python
from datetime import date

from cotton_factor.smoke import run_cf_smoke

result = run_cf_smoke(start=date(2024, 1, 2), end=date(2024, 2, 5))
```

D20 product config smoke is available from Python:

```python
from cotton_factor.smoke import run_product_config_smoke

result = run_product_config_smoke(product_codes=("SR", "AP"), year=2024)
```

D21 QA helpers are available from Python:

```python
from cotton_factor.qa import audit_csv_table, stable_smoke_fingerprint, validate_csv_table
```

D22 UAT replay is available from Python:

```python
from cotton_factor.uat import run_uat_replay

result = run_uat_replay(scenario="cf_mvp_fixture")
```

D23 release freeze is available from Python:

```python
from cotton_factor.release import run_release_freeze

result = run_release_freeze(version="0.1.0")
```

D16/D17 backtest helpers are available from Python:

```python
from cotton_factor.backtest import build_target_lots_from_scores, run_daily_backtest
from cotton_factor.research import build_equal_weight_scores
```

Contract master helpers are available from Python:

```python
from cotton_factor.core import build_contract_master

result = build_contract_master(product_code="CF", year=2024)
```

Trading calendar helpers are available from Python:

```python
from cotton_factor.core import build_trading_calendar

result = build_trading_calendar(start=..., end=..., exchange="CZCE")
```

## Quality Checks

```bash
py -3.12 -m pytest
py -3.12 -m ruff check src tests
```

## Research Workbench Path

- R00-R02: scope lock, current-state map, and research mode config.
- R03-R06: CF source docs, raw preservation, core quote normalization, and data quality.
- R07-R10: contract review, chain/trade mapping, continuous prices, and output contracts.
- R11-R14: four factor outputs and daily factor diagnostic states.
- R15-R18: forward returns and research backtests.
- R19-R20: daily CF research brief and one-command pipeline.
- R21: lightweight replay against preserved R20 outputs.
- R22: expansion gate.
- post-R22 bridge: isolated CF validation pack proves the local workbench can
  produce R20/R21/R22 evidence without becoming a platform project.

The D0-D23 path is retained as historical foundation, not the current task
queue.
