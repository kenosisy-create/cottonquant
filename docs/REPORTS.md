# Reports

D15 adds static HTML report rendering for archive artifacts.

## Single Factor Report

Function:

```python
from cotton_factor.archive import render_single_factor_report
```

Inputs:

- `research_factor_evaluation` rows from D14
- optional `research_factor_value_daily` rows
- optional `research_forward_return_daily` rows
- warnings
- output path

The report includes:

- run metadata
- factor metrics
- warnings
- input snapshot lineage
- renderer version

## Backtest Report

Function:

```python
from cotton_factor.archive import render_backtest_report
```

Inputs:

- backtest summary mapping
- optional equity curve rows
- optional trade rows
- warnings
- input snapshot lineage
- output path

D15 only renders structured backtest outputs. D16 `DailyBacktestResult` exposes
`report_summary()`, `equity_records()`, and `trade_records()` so its output can
feed this renderer directly.

## Output

Reports are UTF-8 static HTML files. If no explicit path is supplied, they are
written under `reports/`.

The renderer uses Jinja2 with autoescaping enabled, so warnings and titles are
escaped before being written to HTML.
