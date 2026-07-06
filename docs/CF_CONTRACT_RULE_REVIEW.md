# CF Contract Rule Review

R07 adds a research-mode contract rule review artifact for CF.

The purpose is not to declare production readiness. The purpose is to make every
contract-rule assumption visible before R08 chain/trade mapping and R09
continuous price diagnostics depend on it.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research review-cf-contract-rules --year 2024
```

## Outputs

```text
reports/research/contract_rules/CF_2024_contract_rule_review.csv
reports/research/contract_rules/CF_2024_contract_rule_review.md
```

The CSV is machine-readable. The Markdown file is intended for analyst and
architecture review.

## Review Contents

The review table includes:

- CF product config fields.
- Delivery months.
- Contract code format.
- Multiplier and tick size.
- Last-trade-day rule.
- Option-style placeholder.
- Official field-unit review item.
- Generated contract codes for the requested year.
- Last-trade-date calculation status when an official calendar is available.
- Warnings from contract master generation.

## Human Review Boundary

Rows marked `HUMAN_REVIEW_REQUIRED` or `blocks_production=true` must not be
treated as reviewed production rules.

Current CF review blockers include:

- `tick_size`
- `last_trade_day_rule`
- `option_style`
- `official_field_units`

The workbench may continue research with these rows visible, but later
production confidence requires human confirmation.
