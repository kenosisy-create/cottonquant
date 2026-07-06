# CF Data Quality Rules

R06 implements these checks for `core_quote_daily.parquet`.

## Severity Levels

| Severity | Meaning | Downstream behavior |
| --- | --- | --- |
| `CRITICAL` | Data cannot safely support downstream research. | Stop before factors. |
| `WARNING` | Data can continue, but report risk clearly. | Continue with warning. |
| `INFO` | Informational observation. | Continue. |

## Required Checks

| Check | Severity | Rule |
| --- | --- | --- |
| Required fields not null | `CRITICAL` | `trade_date`, `exchange`, `product_code`, `contract_code`, OHLC, `settle`, `volume`, `open_interest`, and `source_snapshot_id` must exist for tradable rows. |
| Primary key uniqueness | `CRITICAL` | `trade_date + contract_code` must be unique. |
| Positive prices | `CRITICAL` | `open`, `high`, `low`, `close`, and `settle` must be positive. |
| High/low order | `CRITICAL` | `high >= low`. |
| Non-negative volume | `CRITICAL` | `volume >= 0`. |
| Non-negative open interest | `CRITICAL` | `open_interest >= 0`. |
| Settle exists | `CRITICAL` | Post-settlement factors require settlement price. |
| Active CF contract exists | `CRITICAL` | At least one CF contract must be available for the date. |
| Volume or OI spike | `WARNING` | Large day-over-day spike should be shown, not hidden. |
| Missing trading day | `WARNING` | Use calendar when available. |
| Optional risk fields missing | `INFO` | `limit_up`, `limit_down`, `margin_rate`, and `trading_status` may be null but must be visible. |

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research check-cf-quality --date 2026-06-11
```

The command returns a non-zero exit code when any `CRITICAL` check fails.

## Output Convention

R06 writes:

```text
reports/research/data_quality/CF_YYYY-MM-DD_quality.csv
reports/research/data_quality/CF_YYYY-MM-DD_quality.md
```

The Markdown report must be readable by a research analyst. The CSV must be
machine-readable for downstream gates.

## Human Review

The following remain `HUMAN_REVIEW_REQUIRED`:

- official settlement field interpretation
- volume and turnover unit interpretation
- settlement status and trading status semantics
- limit price semantics
- margin field semantics
