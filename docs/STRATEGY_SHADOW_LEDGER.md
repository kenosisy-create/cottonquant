# CF Strategy Shadow Ledger

R90 records daily research accountability without creating orders or connecting
to a trading account.

## Timing

- T settlement generates a target only.
- The prior target executes at T settlement when T becomes the next official
  observed trading session.
- That newly filled position first earns the T to T+1 interval after its fill.
- The first ledger row starts from zero position and research NAV 1,000,000.

## Evidence Modes

- `FORWARD_CAPTURE` is accepted only when the requested date is both today's
  Shanghai date and the latest date in normalized core quotes.
- `HISTORICAL_REPLAY` is deterministic engineering evidence but is excluded
  from the 40-day forward gate.

## Immutability

Each daily fact is first written as a unique JSON event under
`data/strategy/CF/shadow_events/`. The Parquet ledger is an atomically replaced
materialized view. An identical rerun returns `NO_CHANGES`. A changed latest
row requires `--overwrite-reason` and appends a correction event containing the
superseded event checksum; it never deletes the original event. Earlier rows
must retain identical business fingerprints.

## Commands

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main strategy run-shadow --date 2026-07-20 --record-mode HISTORICAL_REPLAY
```

The normal daily script runs the lightweight forward path unless
`-SkipStrategyShadow` is supplied. A shadow failure is reported as a warning
and does not block the daily research brief.

All shadow outputs are research simulations, not trading instructions. NAV is
a research accounting value, not real capital.
