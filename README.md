# Cotton Factor MVP

Local, reproducible, auditable daily factor research MVP for China agricultural
futures, starting with CZCE cotton futures CF.

## Current Status

This repository is at D23: project constitution, config placeholders, CLI status,
an immutable raw snapshot store, fixture-safe CZCE raw ingestion, core fact
schema contracts, product config validation, CF contract master generation, and
chain/trade mapping plus continuous price generation are in place. The factor
registry, factor dependency validation, deterministic preprocessing helpers, and
D12/D13 first-four MVP factors are also in place. D14 forward returns and the
single factor evaluator are available. D15 static HTML report rendering is
available. D16 daily backtest MVP, D17 equal-weight multifactor target lots, and
D18 archive manifest/bundle helpers are available. D19 adds CSV fixture
normalization and a CF full-chain smoke run that creates a report and archive
bundle. D20 adds SR/AP config-only smoke to prove product extension is driven by
config, not CF-specific engine branches. D21 adds QA CSV schema validation,
row-count/null-ratio audit checks, golden fixture checks, and reproducibility
tests. D22 adds a CF MVP UAT replay command with JSON/HTML pass-fail reports.
D23 adds release freeze packaging, changelog/checklist artifacts, and known TODO
classification. Production live endpoint field interpretation remains a
human-review follow-up.

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

## MVP Path

- Week 1: D0-D7, repository, raw layer, core schemas, contract master, calendar.
- Week 2: D8-D14, chain/trade mapping, continuous price, factors, evaluator.
- Week 3: D15-D19, reports, backtest, portfolio, archive, CF full smoke.
- Week 4: D20-D23, SR/AP smoke, golden tests, UAT replay, release freeze.
