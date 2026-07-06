# CF Fundamental Data Contract R51

R51 establishes the manual-input contract for CF fundamental observations.
It does not fetch external data, parse official raw files, or create a
`fundamental_signal`.

R53 consumes the manual files that pass this contract and writes observation
tables only; it still keeps `fundamental_signal_status=not_connected`.

## Scope

- Product: CF only.
- Frequency: daily / weekly / monthly manual inputs.
- Input path: `data/incoming/CF/fundamentals/manual/`
- Data output: `data/research/CF/fundamentals/`
- Report output: `reports/research/fundamentals/`

## Dataset Contracts

| Dataset | Meaning | Required boundary |
| --- | --- | --- |
| `warehouse_receipt` | 仓单 | source and unit must be reviewed |
| `basis` | 基差 | region, spot source, and futures-settle match must be reviewed |
| `inventory` | 库存 | source, unit, and update frequency must be reviewed |
| `import` | 进口 | period and unit must be reviewed |
| `textile_chain` | 纺织链条 | indicator definition must be reviewed |

All datasets are `manual_input_only` and `not_connected` to signal production
until a later task adds field validation and research evidence.

## Command

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-fundamental-data-contract --source-dir data/incoming/CF/fundamentals/manual --output-dir data/research/CF/fundamentals --report-output-dir reports/research/fundamentals
```

## Outputs

- `data/research/CF/fundamentals/CF_fundamental_data_contract_schema.json`
- `data/research/CF/fundamentals/CF_fundamental_manual_input_template.csv`
- `data/research/CF/fundamentals/CF_fundamental_data_contract.json`
- `data/research/CF/fundamentals/CF_fundamental_data_contract_manifest.json`
- `reports/research/fundamentals/CF_fundamental_data_contract.md`
- `reports/research/fundamentals/CF_fundamental_data_contract_warnings.csv`

## Research Boundary

- Missing reliable fundamental inputs must be reported as
  `MISSING_FUNDAMENTAL_INPUT`.
- Manual files found under the incoming path are not parsed by R51.
- Fundamental fields do not enter `signal_matrix`, `latest_signal_brief`, or
  trading conclusions in this task.
- Forward return remains a historical after-the-fact validation label only.
- This output is not a trading instruction.

## Human Review Required

- `warehouse_receipt_source_and_units`
- `basis_region_and_spot_price_source`
- `inventory_source_and_unit`
- `import_period_and_unit`
- `textile_chain_indicator_definition`
- `official_fundamental_field_interpretation`
- `fundamental_signal_rule_before_use`
