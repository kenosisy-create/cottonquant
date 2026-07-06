# Post-R22 CF Real Data Validation Result

This note records the first real-data validation run after connecting the CZCE
official annual futures history archives.

## Data Connected

- Source archives: `ALLFUTURES2021.zip` through `ALLFUTURES2025.zip`
- Source folder: `data/incoming/CF/history/`
- Core output: `data/core/CF/core_quote_daily.parquet`
- Rows: `7272`
- Date range: `2021-01-04` to `2025-12-31`
- Contract count: `36`
- Required quote fields checked: open, high, low, close, settle, volume,
  open_interest, turnover
- Missing required quote fields after parser fix: `0`

## Successful R20-R22 Real-Data Run

Window:

```text
2024-08-01 -> 2024-09-20
```

Trade date:

```text
2024-09-20
```

Run root:

```text
runs/codex/real_cf_2024_20240920_allow_missing/
```

R20 pipeline:

```text
runs/codex/real_cf_2024_20240920_allow_missing/reports/pipeline/CF_2024-09-20_real_cf_2024_20240920_allow_missing_r20_pipeline.json
```

R21 replay:

```text
runs/codex/real_cf_2024_20240920_allow_missing/reports/replay/CF_2024-09-20_real_cf_2024_20240920_r21_replay_replay.json
```

R22 gate:

```text
runs/codex/real_cf_2024_20240920_allow_missing/reports/expansion_gate/CF_REAL_CF_2024_DATA_VALIDATION_real_cf_2024_20240920_r22_gate_expansion_gate.json
```

Daily brief:

```text
runs/codex/real_cf_2024_20240920_allow_missing/reports/daily_brief/CF_2024-09-20_daily_research_brief.md
```

Result:

- R20 status: `COMPLETED`
- R21 replay: passed, no missing artifacts
- R22 technical evidence: passed
- R22 status: `HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION`
- Daily brief status: `WATCH_REQUIRED`

## 2024-09-20 Brief Snapshot

- Mapped contract: `CF411`
- T+1 execution date: `2024-09-23`
- Execution blocked: `False`
- Multifactor direction: `long`
- Multifactor raw score: `0.008786711738199242`
- Factor count in score: `2`

Factor diagnostics:

| Factor | State | Note |
| --- | --- | --- |
| `mom_20_v1` | `long` | Available, human-review threshold still required. |
| `oi_pressure_v1` | `long` | Available, human-review threshold still required. |
| `carry_nf_v1` | `unknown` | Missing because near/far contract rule was not satisfied by current master. |
| `curve_slope_v1` | `unknown` | Missing far leg. |

## Late-Year Cross-Year Run

A late-year run was validated after extending the research contract universe to
include delivery years observed in the selected CF core quotes:

```text
2024-11-01 -> 2024-12-20
```

Trade date:

```text
2024-12-20
```

Run root:

```text
runs/codex/real_cf_2024_20241220_cross_year/
```

R20 pipeline:

```text
runs/codex/real_cf_2024_20241220_cross_year/reports/pipeline/CF_2024-12-20_real_cf_2024_20241220_cross_year_pipeline.json
```

Daily brief:

```text
runs/codex/real_cf_2024_20241220_cross_year/reports/daily_brief/CF_2024-12-20_daily_research_brief.md
```

Result:

- R20 status: `COMPLETED`
- Step count: `16`
- Chain rows: `36`
- Mapped contracts: `CF501` for 22 rows, `CF505` for 14 rows
- Factor rows: `124`
- Factor coverage: `carry_nf_v1`, `curve_slope_v1`, `oi_pressure_v1` each
  have 36 rows; `mom_20_v1` has 16 rows because the 20-period lookback only
  becomes available later in the window.

Research warning:

- The first cross-year bridge run generated 2025 contract master rows without
  an official 2025 trading calendar in the R08/R12/R13 research modules. That
  gap has now been reduced: `configs/calendars/CZCE_2025_OFFICIAL.csv` is
  derived from local CZCE official CF futures history dates, and R08/R12/R13 use
  it when calculating 2025 delivery contract `last_trade_date`.
- The newer validation run is:

```text
runs/codex/real_cf_2024_20241220_with_2025_calendar/
```

- R20 status: `COMPLETED`
- Step count: `16`
- Chain rows: `36`
- Mapped contracts: `CF501` for 22 rows, `CF505` for 14 rows
- `last_trade_date omitted` warning in factor warning log: `False`
- Cross-year calendar warning present: `used CZCE 2025 calendar`
- 2025 LTD examples: `CF501=2025-01-15`, `CF505=2025-05-19`,
  `CF511=2025-11-14`

Remaining review:

- The 2025 calendar source is official futures-history-derived rather than a
  manually reviewed holiday notice. It is acceptable for research backfill and
  must still be reviewed before production interpretation.

## Research TODO

- Review the official provenance of the 2025 trading calendar derived from CZCE
  futures history, and replace it with a reviewed holiday-notice calendar if
  required.
- Decide whether the R20 default should require all four factors or allow
  missing factors with explicit warnings for real-data research runs.
- Review carry and curve-slope far-leg rules against official CF listed
  contracts.
- Keep all factor thresholds, cost assumptions, and contract-rule assumptions
  under `HUMAN_REVIEW_REQUIRED` until reviewed.
