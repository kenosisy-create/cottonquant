# Contract Master

D6 adds product config validation and CF futures contract master generation.
D20 extends config-only contract master smoke to SR/AP.
R07 adds CF contract rule review artifacts for the research workbench route.

## Rules

- Product config is the only source for delivery months, multiplier, exchange,
  and last-trade-day rule identifiers.
- `TODO_REQUIRES_HUMAN_REVIEW` fields must be listed in
  `human_review_required`.
- Configs with generation-critical TODO fields can parse for inventory tests, but
  cannot generate `core_contract_master`.
- `tick_size` may remain null in D6 if it is still marked for human review.
- Last trade date is not inferred without a trading calendar. When no calendar is
  supplied, `last_trade_date` is null and a warning is emitted.

## CF

For CF, D6 generates one futures contract row for each configured delivery month.
With the current config this produces:

```text
CF401, CF403, CF405, CF407, CF409, CF411
```

## SR/AP

D20 config-only smoke generates skeleton contract master rows for SR/AP without
adding product-specific engine code:

```text
SR401, SR403, SR405, SR407, SR409, SR411
AP401, AP403, AP404, AP405, AP410, AP411, AP412
```

This is not SR/AP full-chain readiness. Raw ingestion, normalization fixtures,
factors, and backtests remain out of D20 scope.

## CLI

```bash
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main core build-contract-master --product CF --year 2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main smoke products --products SR,AP --year 2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research review-cf-contract-rules --year 2024
```

The command emits JSON containing:

- `rule_version`
- `contracts`
- `warnings`

## Human Review

Human review is still required before production use for:

- CF tick size
- CF last-trade-day rule interpretation
- SR/AP last-trade-day rule interpretation
- option-style placeholders
- official exchange field interpretation

R07 writes the visible review table to:

```text
reports/research/contract_rules/CF_2024_contract_rule_review.csv
reports/research/contract_rules/CF_2024_contract_rule_review.md
```
