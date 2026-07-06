Implement a lightweight research mode configuration.

Create:

- configs/research_mode.yaml
- src/cotton_factor/research_workbench/config.py if needed
- tests/unit/test_research_mode_config.py

research_mode.yaml must include:

- product: CF
- exchange: CZCE
- frequency: daily
- data_input_dir: data/incoming/CF
- raw_output_dir: data/raw
- core_output_dir: data/core
- research_output_dir: data/research
- report_output_dir: reports/daily
- active_factors:
  - momentum
  - carry
  - curve_slope
  - oi_pressure
- cost_scenarios:
  - no_cost
  - normal_cost
  - conservative_cost
- execution_rule: T_SIGNAL_T_PLUS_1_EXECUTION
- platform_features_paused:
  - release_freeze
  - gray_deployment
  - full_ci_cd
  - oms_integration
  - minute_execution
  - sr_ap_production_ingest

Acceptance:

- Config can be loaded and validated.
- Unknown product fails unless explicitly allowed.
- The config does not trigger platform release/UAT/gray deployment code.

Run:

```bash
python -m pytest tests/unit/test_research_mode_config.py
python -m pytest
python -m ruff check src tests
```
