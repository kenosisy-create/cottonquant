# Changelog

## 0.1.0 - MVP Release Candidate

This release freezes the Month 1 CF MVP research path.

### Added

- Immutable raw snapshot store and replay manifest.
- CZCE CF daily quote, historical quote, and settlement-parameter fixture ingestion.
- Core fact schemas, CF contract master, official CZCE 2024 calendar fixture,
  chain map, trade mapping, and continuous price construction.
- Carry, momentum, curve slope, and OI pressure factors.
- Forward returns, single-factor evaluator, equal-weight multifactor score, target
  lots, and daily T+1 backtest MVP.
- HTML reports, run manifests, audit logs, artifact registry, checksums, and
  archive bundles.
- CF full-chain smoke, SR/AP config-only smoke, golden checks, UAT replay, and
  release freeze packaging.

### Known Boundaries

- This is not a live-trading release.
- Cost model parameters remain human-review items.
- Live exchange endpoint field interpretation remains human-review.
- Contract rule assumptions and roll thresholds must be reviewed before
  production use.
