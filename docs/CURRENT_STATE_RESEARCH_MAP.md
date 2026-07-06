# Current State Research Map

This map translates the completed D0-D23 codebase into the new CF research
workbench route.

## Module Classification

| Research workflow area | Status | Useful files | Notes |
| --- | --- | --- | --- |
| Production data ingestion candidates | REUSE_WITH_SIMPLIFICATION | `src/cotton_factor/ingest/*`, `configs/data_sources.yaml` | Existing ingest modules are fixture-safe and raw-first, but live endpoint interpretation remains human review. R03/R04 should add local production-like file ingest before any API work. |
| Raw preservation | USE_AS_IS | `src/cotton_factor/raw/*`, `src/cotton_factor/common/hashing.py` | The raw snapshot store already preserves payloads with SHA256 and replay metadata. Research mode can use a simpler `data/raw/CF/raw_manifest.jsonl` wrapper. |
| Core quote table | REUSE_WITH_SIMPLIFICATION | `src/cotton_factor/research_workbench/core_quotes.py`, `src/cotton_factor/core/schemas.py` | R05 builds `core_quote_daily.parquet` from preserved research raw CSV files and keeps source lineage. |
| Data quality | USE_AS_IS | `src/cotton_factor/research_workbench/data_quality.py`, `docs/DATA_QUALITY_RULES_CF.md` | R06 writes CSV/Markdown reports and marks critical failures before factors/backtests. |
| Contract rule review | USE_AS_IS | `src/cotton_factor/research_workbench/contract_review.py`, `docs/CF_CONTRACT_RULE_REVIEW.md` | R07 writes CSV/Markdown review artifacts and keeps CF rule TODOs visible. |
| Contract master | USE_AS_IS | `src/cotton_factor/core/contract_master.py`, `configs/products/CF.yaml` | Good foundation. Production confidence still requires closing R07 human-review rows. |
| Chain/trade mapping | USE_AS_IS | `src/cotton_factor/research_workbench/mapping.py`, `src/cotton_factor/research_workbench/contract_universe.py`, `src/cotton_factor/core/chain_map.py`, `src/cotton_factor/core/trade_mapping.py` | R08 writes research-mode CSV/Parquet/Markdown outputs with switch reasons, T+1 execution dates, and block reasons. Late-year CF windows now include observed next-year delivery contracts, with missing next-year LTD dates kept as human-review warnings. |
| Continuous price | USE_AS_IS | `src/cotton_factor/research_workbench/continuous.py`, `src/cotton_factor/research/continuous_price.py` | R09 writes continuous CSV/Parquet plus roll diagnostics while keeping continuous contracts as signal objects only. |
| Factor output contracts | USE_AS_IS | `src/cotton_factor/research_workbench/output_contracts.py`, `docs/RESEARCH_OUTPUT_CONTRACTS.md` | R10 fixes R11-R14 output paths, schemas, diagnostic states, warnings, and human-review gates. |
| Factors | REUSE_WITH_SIMPLIFICATION | `src/cotton_factor/research_workbench/momentum.py`, `src/cotton_factor/research_workbench/carry.py`, `src/cotton_factor/research_workbench/structure_factors.py`, `src/cotton_factor/research_workbench/factor_diagnostics.py`, `src/cotton_factor/research_workbench/contract_universe.py`, `src/cotton_factor/research/factors/*`, `configs/factor_registry.yaml` | R11-R14 adapt all four MVP factors to factor value, warning, and daily diagnostic outputs. R12/R13 share the same late-year contract-universe bridge as R08, so CF501/CF505 style cross-year legs remain visible instead of being dropped as unknown contracts. |
| Forward returns | USE_AS_IS | `src/cotton_factor/research_workbench/forward_returns.py`, `src/cotton_factor/research/forward_returns.py` | R15 writes T+1-safe multi-horizon labels from R08 real-contract trade mapping and core quotes. |
| Backtest | REUSE_WITH_SIMPLIFICATION | `src/cotton_factor/research_workbench/single_factor_backtest.py`, `src/cotton_factor/research_workbench/multifactor_diagnostics.py`, `src/cotton_factor/research_workbench/cost_sensitivity.py`, `src/cotton_factor/research/evaluator.py`, `src/cotton_factor/backtest/*` | R16 writes single-factor research metrics from R14 diagnostics and R15 labels. R17 writes equal-weight multifactor score diagnostics from R14 diagnostics. R18 writes cost sensitivity summaries from R17 scores and R15 labels. Later work should stay in research-summary shape, not trading-system outputs. |
| Reports | REUSE_WITH_SIMPLIFICATION | `src/cotton_factor/research_workbench/daily_brief.py`, `src/cotton_factor/research_workbench/pipeline.py`, `src/cotton_factor/research_workbench/replay.py`, `src/cotton_factor/research_workbench/expansion_gate.py`, `src/cotton_factor/archive/report_renderer.py`, `docs/REPORTS.md` | R19 writes Markdown/JSON daily research briefs from R06-R18 artifacts. R20 runs R04-R19 in order and writes a simple pipeline run log. R21 replay-checks preserved R20 artifacts and optional baselines. R22 defines the expansion gate. Existing HTML reports are historical. |
| Archive/logging | KEEP_BUT_NOT_PRIORITY | `src/cotton_factor/archive/*`, `src/cotton_factor/release/*`, `src/cotton_factor/uat/*` | Keep for history and periodic checks, but do not extend release/UAT machinery in the next phase. |

## Platform-Heavy Areas To Pause

- `src/cotton_factor/release/*`
- `src/cotton_factor/uat/*` except lightweight periodic replay reference
- release bundle generation
- production-grade artifact registry work
- future gray deployment or monitoring abstractions

## Missing For CF Research Workbench

- No remaining R00-R22 gap for the current CF-first research workbench route.
- Post-R22 real-data validation now covers both an ordinary 2024 window and a
  late-year cross-year window. A 2025 calendar derived from local CZCE official
  CF futures history is available for cross-year `last_trade_date` calculation;
  the remaining gap is provenance review of that calendar source, not pipeline
  execution.

## Recommended Next Implementation Order

1. Open a new post-R22 route before adding SR/AP or external data.

Do not recommend platform hardening as the next priority.
