# Research Workbench Roadmap

The completed CF-first research workbench route uses `R00` through `R22`
instead of extending the historical `D0` through `D23` platform path.

## Strategy

Engineering serves research. The repository is being kept as a research-grade
production data decision workbench for CF daily analysis, not a production-grade
factor platform.

## Current Progress

- R00-R02 complete: scope lock, current-state map, and research mode config.
- R03 complete: CF source, field mapping, and data quality rules documented.
- R04 complete: local CF files are preserved into research raw storage.
- R05 complete: preserved CF CSV files normalize into `core_quote_daily.parquet`.
- R06 complete: daily data quality CSV/Markdown reports block critical failures.
- R07 complete: CF contract rule review CSV/Markdown exposes human-review gates.
- R08 complete: research-mode chain/trade mapping files expose switch and block reasons.
- R09 complete: continuous price files include roll diagnostics and signal-object boundary notes.
- R10 complete: downstream factor diagnostic output contracts are schema-backed and documented.
- R11 complete: momentum factor value and warning outputs follow the R10 contract.
- R12 complete: carry factor value and warning outputs follow the R10 contract.
- R13 complete: curve slope and OI pressure factor outputs follow the R10 contract.
- R14 complete: daily factor diagnostic states and report follow the R10 contract.
- R15 complete: T+1-safe forward-return labels write multi-horizon outputs.
- R16 complete: single-factor research backtest summaries write evaluation metrics.
- R17 complete: equal-weight multifactor score diagnostics write explicit weights and warnings.
- R18 complete: research cost sensitivity summaries compare hypothetical cost scenarios.
- R19 complete: daily CF research brief summarizes R06-R18 evidence and watch items.
- R20 complete: one-command research pipeline runs R04-R19 and writes a simple run log.
- R21 complete: lightweight replay checks preserved R20 artifacts and optional baselines.
- R22 complete: expansion gate blocks broader ingestion until CF evidence and review gates exist.
- R00-R22 complete for the current CF-first research workbench route.
- post-R22 bridge available: `research run-cf-validation-pack` runs an
  isolated CF validation pack and writes R20/R21/R22 evidence without adding
  platform scope.
- post-R22 real-data bridge complete for local official CF futures history:
  the workbench has validated a normal 2024 window and a late-year cross-year
  window where the main chain rolls into 2025 delivery contracts.
- 2025 CZCE calendar coverage is now available from local official CF futures
  history dates, allowing CF501/CF505 style cross-year contracts to carry
  calculated `last_trade_date` values in research runs.
- R23-R34 complete for latest-day CF research operation: latest signal-only
  brief, S0-S4 trend phase, trend continuity board, trend quality score,
  historical calibration context, and daily operation audit are available.
- R35-R40 complete or in integration verification for the next research
  mainline: horizon-aware signal matrix, rolling validation,
  factor-threshold/weight research, latest-brief matrix integration, and R37
  aggregated threshold/weight candidate context for the latest brief are
  available. R40 adds non-primary-horizon reference candidates when the current
  primary horizon has no READY/WATCH match, with an explicit boundary that this
  cannot replace primary-horizon confirmation. Do not continue by expanding
  audit-only artifacts; next work should improve research evidence and signal
  quality.
- R41 starts the required shift away from latest-day-only work. It builds a
  historical multi-factor evidence pack from R35/R36/R37 full-window artifacts,
  covering horizon decay, grouped historical hit/return evidence, cost-sensitive
  stability, and threshold-candidate status. This is the base for R42 historical
  event explanation and R43 validated research briefs.
- R42 extends the full-history route into event explanation. It extracts trend
  starts, trend continuations, exhaustion observations, end confirmations,
  main-contract switches, OI anomalies, and curve shocks from R36 validation
  rows, then summarizes 1/3/5/10/20D historical outcomes for each event type.
- R43 combines latest signal-only observations with R41 historical evidence and
  R42 event explanation into a validated Chinese research brief, while keeping
  latest-day facts separate from historical forward-return validation labels.
- R44/R45 extend the route into an operating cadence and publishable research
  package. Daily runs stay light with raw/core refresh, latest signal-only
  brief, trend board, and operation audit. Weekly/manual switches now build
  historical evidence, event explanation, validated brief, and the R45 chart +
  WeChat publish pack under `runs/daily/CF/{trade_date}/publish/`.
- R46 starts the option route without jumping into option strategy. It registers
  `core_option_quote_daily`, creates/checks `data/incoming/CF/options/history/`,
  writes a schema-only `core_option_quote_daily.parquet` when real option files
  are absent, and emits explicit `MISSING_OPTION_HISTORY` warnings plus Chinese
  Markdown/JSON/manifest artifacts.
- R47 connects local option history files into raw snapshots and
  `core_option_quote_daily.parquet`. It parses option symbol/C/P/strike/
  underlying contract, writes quality CSV/Markdown/JSON/manifest artifacts, and
  tags low-liquidity, deep-OTM proxy, missing underlying price, missing settle,
  and near-expiry review rows. `option_signal` remains `not_connected`.
- R48 builds option factor proxy artifacts from `core_option_quote_daily` and
  `core_quote_daily`: ATM IV proxy, IV rank, PCR volume, PCR OI, skew proxy,
  option liquidity score, and an inspectable surface proxy table. It excludes
  low-liquidity, deep-OTM, near-expiry, missing-settle, and missing-underlying
  rows from the core proxy while preserving them with `exclusion_reason`.
  American-option IV/Greek assumptions remain marked as research proxy only.
- R49 connects the R48 option factor proxy table into the R35/R49 signal matrix
  as a futures signal filter. It fills `option_signal` with confirm/diverge/
  volatility-risk/watch states, surfaces the option filter in the latest brief,
  and keeps option inputs out of `composite_score` until the filter rules pass
  human review. When no option factor table is provided, `option_signal` remains
  `not_connected`.
- R50 hardens the CF product config and research factor registry. It writes a
  CF-only registry snapshot with contract rule fields, signal object, four
  futures factors, six option proxy factors, and explicit human-review gates.
  It does not start multi-product expansion.
- R51 establishes CF fundamental interface placeholders for warehouse receipts,
  basis, inventory, import, and textile-chain inputs. It writes schema,
  manual-input templates, warning CSV, manifest, and Chinese Markdown report
  artifacts, while keeping all fundamental fields out of automatic signals
  until reliable data and human-reviewed rules exist.
- R52 refreshes the expansion gate. The default gate now keeps CF as the only
  active product and requires R20/R21 pipeline evidence plus R41 historical
  evidence, R42 event explanation, R49 option linkage, R45 publish pack, R50
  product registry, and R51 fundamental contract readiness before any
  multi-product pilot. R22 remains available only as a legacy validation-pack
  compatibility mode.
- Post-R52 data-port planning is documented in
  `docs/RESEARCH_DATA_PORTS_NEXT.md` and
  `configs/cf_research_data_ports.csv`. It identifies the P0/P1/P2 data inputs
  that must be supplemented before basic fundamental observation or any
  multi-product research pilot.
- Next mainline task should refresh the weekly evidence chain to the latest
  available core date before any product expansion decision: rebuild historical
  evidence/event explanation/publish pack on the latest full validation window,
  then re-run the R52 gate.

## Sprint Order

| Sprint | Tasks | Goal |
| --- | --- | --- |
| Sprint 0 | R00-R02 | Scope lock, current-state map, research mode config. |
| Sprint 1 | R03-R06 | CF production-like data docs, raw ingest, core quotes, data quality. |
| Sprint 2 | R07-R10 | Contract rule review, chain/trade mapping, continuous price, output contract. |
| Sprint 3 | R11-R14 | Four factors and diagnostics. |
| Sprint 4 | R15-R18 | Forward returns and research backtests. |
| Sprint 5 | R19-R20 | Daily CF research brief and one-command research pipeline. |
| Sprint 6 | R21-R22 | Lightweight replay and expansion gate. |

## Do Not Build Next

- release freeze
- gray deployment
- production OMS
- minute-level execution
- service API platform
- multi-user dashboard
- SRE-grade monitoring
- full metadata catalog
- SR/AP real production ingest
- external spot/weather/USDA ingestion
- complex portfolio optimizer
- automatic trading recommendation

## Post-R22 Bridge

The next useful work is not another platform layer. The current bridge command
is:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-validation-pack --date 2024-01-31 --start 2024-01-22 --end 2024-01-31 --horizons 1 --lookback-periods 3
```

It proves the local CF workbench can produce inspectable pipeline, replay, gate,
and summary artifacts in an isolated run folder. Real CF data source
permissions and official field interpretation remain human-review gates.

The first real-data bridge after that validation pack is:

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research connect-cf-official-history --years 2023,2024,2025 --source-dir data/incoming/CF/history
```

This command connects the three latest completed official annual history
archives into the existing raw/core boundary. It does not add a production data
service or change the CF-first research scope.

The late-year real-data validation run is:

```powershell
py -3.12 -m cotton_factor.cli.main research run-cf-daily-pipeline --date 2024-12-20 --start 2024-11-01 --end 2024-12-20 --input-path runs\codex\real_cf_2024_20241220_cross_year\incoming\CF\2024-12-20\cf_daily.csv --raw-output-dir runs\codex\real_cf_2024_20241220_cross_year\raw --core-output-dir runs\codex\real_cf_2024_20241220_cross_year\core --research-output-root runs\codex\real_cf_2024_20241220_cross_year\research\CF --report-output-root runs\codex\real_cf_2024_20241220_cross_year\reports --run-id real_cf_2024_20241220_cross_year --allow-missing-factors
```

It completed R04-R19 and produced the daily brief under:

```text
runs/codex/real_cf_2024_20241220_cross_year/reports/daily_brief/CF_2024-12-20_daily_research_brief.md
```

After adding the 2025 calendar fixture, the refreshed run is:

```text
runs/codex/real_cf_2024_20241220_with_2025_calendar/
```

This run no longer emits `last_trade_date omitted` for 2025 cross-year CF
contracts.

## Final Research Questions

Every new feature should help answer:

1. Is today's CF data complete and trustworthy?
2. What is the current main/secondary contract and roll state?
3. Are the four core factors long-biased, short-biased, neutral, or unknown?
4. Does history support the current signal direction?
5. What should tomorrow's research watchlist focus on?
