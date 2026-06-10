# Architecture

## Mission

Build a local, reproducible, auditable daily factor MVP for China agricultural
futures, starting with CZCE cotton CF.

## Four Layers

### 1. Raw Snapshot

Raw snapshot storage owns all exchange payload capture. It records payload path,
source, business date, capture time, content type, parser version, status, and
SHA256. Raw snapshots are immutable. Repeated ingestion creates another snapshot
with its own snapshot_id, even when the payload hash is identical.

### 2. Core Facts

Core facts normalize exchange data into versioned tables. Core rows must include
lineage such as source_snapshot_id or an explicit source version. Contract master,
rule versions, trading calendar, quote facts, settlement facts, chain map, and
trade mapping live here.

### 3. Research Derived

Research derived data includes continuous prices, factors, forward returns, and
evaluation outputs. Research code must use core or research tables only. It must
not parse raw exchange files.

### 4. Archive And Audit

Formal runs produce a run_manifest, audit log, checksums, reports, and artifact
bundle. The archive must be sufficient to explain inputs, configs, code version,
warnings, and produced outputs.

## Signal And Trade Objects

Continuous contracts such as CF.C1 are signal objects. They can drive factors and
signals, but they cannot be used as order, fill, cost, or position objects. The
trade mapping layer converts signal objects to real tradable contracts or marks
the date as blocked with an explicit reason.

## Timing Rule

Daily signals are formed after T-day settlement data is available. Execution can
only happen on T+1. The backtest must support next_open and next_settle execution
price conventions, but neither may use same-day post-settlement data to trade on
T.

## Extension Rule

CF is the first product. SR/AP smoke tests must prove that the engine is driven by
product config rather than CF-specific code paths. M/C/Y stay represented as
validated configs until their ingestion and rules are explicitly implemented.
