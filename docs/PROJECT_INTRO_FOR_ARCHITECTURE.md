# Cottonquant 项目架构端介绍

本文用于向新的架构端介绍 Cottonquant 当前项目背景、目标边界、已完成进度和后续规划。请优先按本文理解项目方向，再参考更细的架构与任务文档。

## 1. 项目背景

Cottonquant 最初按中国农产品期货日频因子研究 MVP 推进，起点品种是郑商所棉花期货 CF。前期 D0-D23 已经证明一条完整的研究型量化链路可以跑通：

- 原始数据保存。
- 核心事实表标准化。
- 合约主数据、交易日历、主力链路和交易映射。
- 连续价格作为信号对象。
- carry、momentum、curve slope、OI pressure 四个第一批因子。
- T 日结算后信号、T+1 执行约束。
- 回测、报告、归档、QA、UAT 和 release freeze 能力。

但项目方向已经调整：后续不继续扩展成生产级量化平台，而是收缩成“研究级生产数据决策工作台”。

## 2. 当前目标

当前目标是建设 CF 优先的日频研究工作台，帮助研究人员每天回答：

- 今天 CF 数据是否完整、可信。
- 主力/次主力合约、换月状态和市场结构发生了什么。
- momentum、carry、curve slope、OI pressure 当前是偏多、偏空、中性还是未知。
- 历史检验是否支持当前信号方向。
- 明天交易决策前最需要关注什么。

核心数据链路是：

```text
real or production-like CF daily data
  -> raw preservation
  -> core facts
  -> factor diagnostics
  -> research backtest
  -> daily research brief
```

## 3. 架构边界

必须保留的研究正确性规则：

- research 代码不能直接解析交易所原始文件。
- 原始文件必须先保存，再规范化。
- core 表必须标准化、可检查、可追溯。
- 连续合约只能作为信号对象，不能作为真实交易对象。
- 回测和交易相关输出必须使用真实可交易合约。
- T 日结算后信号不能在 T 日同日执行，最早 T+1。
- 不允许未来函数和同日偷看。
- 合约切换原因、阻断原因、临近最后交易日风险必须显式展示。
- 合约规则、字段口径、成本参数、换月阈值等不明确事项必须标记为 `HUMAN_REVIEW_REQUIRED`，不能静默假设。

当前暂停或降级的方向：

- 不优先做 release freeze、灰度发布、完整 CI/CD、SRE 监控。
- 不优先做 OMS、分钟级执行、服务化 API、多用户平台。
- 不优先做 SR/AP 真实生产接入，直到 CF 工作台验证完成。
- 不优先接入外部现货、天气、USDA 等数据。

## 4. 当前完成进度

历史基础：

- D0-D23 已完成，作为可复用工程基础保留。
- 已有 raw/core/research/archive 分层。
- 已有 CF fixture 级全链路 smoke、QA、UAT 和 release freeze 历史能力。

当前 R 系列研究工作台进度：

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| R00 | 已完成 | 项目范围锁定为 CF 研究级生产数据决策工作台。 |
| R01 | 已完成 | 已把 D0-D23 模块映射为复用、简化、暂停、延后四类。 |
| R02 | 已完成 | 已新增 `configs/research_mode.yaml`，锁定 CF daily 研究模式。 |
| R03 | 已完成 | 已新增 CF 数据源、字段映射、数据质量规则文档。 |
| R04 | 已完成 | 已支持本地 CF 文件保存到 research raw，并写入 manifest。 |
| R05 | 已完成 | 已支持从保存后的 CF CSV 规范化生成 `core_quote_daily.parquet`。 |
| R06 | 已完成 | 对 core quote 做日频数据质量检查，输出 CSV/Markdown 并阻断 CRITICAL。 |
| R07 | 已完成 | 建立 CF 合约规则人工复核表，显式暴露生产置信阻断项。 |
| R08 | 已完成 | 输出 research-mode chain/trade mapping 文件，展示换月和阻断原因。 |
| R09 | 已完成 | 输出连续价格与 roll diagnostics，保留 signal-object 边界。 |
| R10 | 已完成 | 定义下游因子诊断输出契约，写出 JSON/Markdown 并补充诊断日表 schema。 |
| R11 | 已完成 | 把 momentum 因子输出接入 R10 契约，写出 factor value、warning 和 Markdown 摘要。 |
| R12 | 已完成 | 把 carry 因子输出接入 R10 契约，保留 carry tenor 和合约规则 warning。 |
| R13 | 已完成 | 把 curve slope 和 OI pressure 因子输出接入 R10 契约，缺失输入写 warning。 |
| R14 | 已完成 | 生成每日因子诊断状态表，显式输出 long/short/neutral/unknown。 |
| R15 | 已完成 | 计算 T+1 约束下的 multi-horizon forward returns，明确 horizon 和价格口径。 |
| R16 | 已完成 | 运行单因子研究型回测摘要，输出 evaluation metrics 和 warning。 |
| R17 | 已完成 | 运行等权多因子 score diagnostics，输出 score、权重和缺失因子 warning。 |
| R18 | 已完成 | 做成本敏感性对比，并把成本参数保留为人工复核项。 |
| R19 | 已完成 | 生成每日 CF 研究简报，汇总数据质量、市场结构、因子、回测和风险观察。 |
| R20 | 已完成 | 增加一键 research pipeline，把 R04-R19 串联并输出简单 run log。 |
| R21 | 已完成 | 增加轻量 replay，复核 R20 保存产物、hash、行数和可选 baseline。 |
| R22 | 已完成 | 定义 SR/AP 或外部数据 expansion gate，先证明 CF 可验证再扩展。 |

R04-R19 当前命令：

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research ingest-cf --date 2026-06-11 --input-path data/incoming/CF/2026-06-11
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research normalize-cf-quotes --date 2026-06-11
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research check-cf-quality --date 2026-06-11
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research review-cf-contract-rules --year 2024
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-mapping --start 2024-01-09 --end 2024-01-12 --ltd-buffer-days 2
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-continuous --start 2024-01-09 --end 2024-01-12
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research write-cf-factor-output-contract
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-momentum-factor --start 2024-01-21 --end 2024-01-21 --continuous-price-path data/research/CF/continuous/CF_2024-01-01_2024-01-21_settle_continuous_price_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-carry-factor --start 2024-01-09 --end 2024-01-09 --core-quote-path data/core/CF/core_quote_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-structure-factors --start 2024-01-09 --end 2024-01-09 --core-quote-path data/core/CF/core_quote_daily.parquet --chain-map-path data/research/CF/mapping/CF_2024-01-09_2024-01-09_chain_map_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-factor-diagnostics --start 2024-01-09 --end 2024-01-09 --factor-value-path data/research/CF/factors/CF_2024-01-09_2024-01-09_factor_value_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-forward-returns --start 2024-01-09 --end 2024-01-12 --horizons 1,3,5 --core-quote-path data/core/CF/core_quote_daily.parquet --trade-mapping-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_trade_mapping_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research run-cf-single-factor-backtest --start 2024-01-09 --end 2024-01-12 --factor-ids mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1 --horizons 1,3,5 --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet --forward-return-path data/research/CF/returns/CF_2024-01-09_2024-01-12_forward_return_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-multifactor-diagnostics --start 2024-01-09 --end 2024-01-12 --factor-ids mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1 --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-cost-sensitivity --start 2024-01-09 --end 2024-01-12 --horizons 1,3,5 --score-path data/research/CF/multifactor/CF_2024-01-09_2024-01-12_multifactor_score_daily.parquet --forward-return-path data/research/CF/returns/CF_2024-01-09_2024-01-12_forward_return_daily.parquet --scenario-cost-bps no_cost=0,normal_cost=5,conservative_cost=10
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-daily-brief --date 2024-01-09 --start 2024-01-09 --end 2024-01-12 --quality-csv-path reports/research/data_quality/CF_2024-01-09_quality.csv --chain-map-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_chain_map_daily.parquet --trade-mapping-path data/research/CF/mapping/CF_2024-01-09_2024-01-12_trade_mapping_daily.parquet --diagnostic-path data/research/CF/factors/CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet --single-factor-evaluation-path data/research/CF/backtests/CF_2024-01-09_2024-01-12_single_factor_evaluation.parquet --multifactor-score-path data/research/CF/multifactor/CF_2024-01-09_2024-01-12_multifactor_score_daily.parquet --cost-sensitivity-path data/research/CF/cost_sensitivity/CF_2024-01-09_2024-01-12_cost_sensitivity_summary.parquet
```

## 5. 当前主要目录和文件

方向与任务文档：

- `README.md`
- `AGENTS.md`
- `docs/PROJECT_DIRECTION.md`
- `docs/CURRENT_STATE_RESEARCH_MAP.md`
- `docs/RESEARCH_WORKBENCH_ROADMAP.md`
- `docs/TASK_BREAKDOWN.md`

CF 数据源与质量文档：

- `docs/DATA_SOURCES_CF_RESEARCH.md`
- `docs/FIELD_MAPPING_CF_RESEARCH.md`
- `docs/DATA_QUALITY_RULES_CF.md`
- `docs/CF_CONTRACT_RULE_REVIEW.md`
- `docs/RESEARCH_MAPPING.md`
- `docs/RESEARCH_CONTINUOUS_PRICE.md`
- `docs/RESEARCH_OUTPUT_CONTRACTS.md`
- `docs/RESEARCH_MOMENTUM_FACTOR.md`
- `docs/RESEARCH_CARRY_FACTOR.md`
- `docs/RESEARCH_STRUCTURE_FACTORS.md`
- `docs/RESEARCH_FACTOR_DIAGNOSTICS.md`
- `docs/RESEARCH_FORWARD_RETURNS.md`
- `docs/RESEARCH_SINGLE_FACTOR_BACKTESTS.md`
- `docs/RESEARCH_MULTIFACTOR_DIAGNOSTICS.md`
- `docs/RESEARCH_COST_SENSITIVITY.md`
- `docs/RESEARCH_DAILY_BRIEF.md`
- `docs/RESEARCH_DAILY_PIPELINE.md`
- `docs/RESEARCH_REPLAY.md`
- `docs/RESEARCH_EXPANSION_GATE.md`
- `configs/data_sources_cf_research.yaml`
- `configs/research_mode.yaml`

研究工作台代码：

- `src/cotton_factor/research_workbench/config.py`
- `src/cotton_factor/research_workbench/raw_ingest.py`
- `src/cotton_factor/research_workbench/core_quotes.py`
- `src/cotton_factor/research_workbench/data_quality.py`
- `src/cotton_factor/research_workbench/contract_review.py`
- `src/cotton_factor/research_workbench/mapping.py`
- `src/cotton_factor/research_workbench/continuous.py`
- `src/cotton_factor/research_workbench/output_contracts.py`
- `src/cotton_factor/research_workbench/momentum.py`
- `src/cotton_factor/research_workbench/carry.py`
- `src/cotton_factor/research_workbench/structure_factors.py`
- `src/cotton_factor/research_workbench/factor_diagnostics.py`
- `src/cotton_factor/research_workbench/forward_returns.py`
- `src/cotton_factor/research_workbench/single_factor_backtest.py`
- `src/cotton_factor/research_workbench/multifactor_diagnostics.py`
- `src/cotton_factor/research_workbench/cost_sensitivity.py`
- `src/cotton_factor/research_workbench/daily_brief.py`

历史工程基础：

- `src/cotton_factor/raw/`
- `src/cotton_factor/core/`
- `src/cotton_factor/research/`
- `src/cotton_factor/backtest/`
- `src/cotton_factor/archive/`
- `src/cotton_factor/qa/`

## 6. 数据与输出约定

输入约定：

```text
data/incoming/CF/YYYY-MM-DD/
```

R04 raw 保存输出：

```text
data/raw/CF/YYYY-MM-DD/{run_id}/
data/raw/CF/raw_manifest.jsonl
```

R05 core quote 输出：

```text
data/core/CF/core_quote_daily.parquet
```

R06 输出：

```text
reports/research/data_quality/CF_YYYY-MM-DD_quality.csv
reports/research/data_quality/CF_YYYY-MM-DD_quality.md
```

R07 输出：

```text
reports/research/contract_rules/CF_YYYY_contract_rule_review.csv
reports/research/contract_rules/CF_YYYY_contract_rule_review.md
```

R08 输出：

```text
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_chain_map_daily.parquet
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_chain_map_daily.csv
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_trade_mapping_daily.parquet
data/research/CF/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_trade_mapping_daily.csv
reports/research/mapping/CF_YYYY-MM-DD_YYYY-MM-DD_mapping.md
```

R09 输出：

```text
data/research/CF/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_continuous_price_daily.parquet
data/research/CF/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_continuous_price_daily.csv
data/research/CF/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_roll_diagnostics.csv
reports/research/continuous/CF_YYYY-MM-DD_YYYY-MM-DD_settle_continuous.md
```

R10 输出：

```text
data/research/CF/output_contracts/CF_factor_diagnostics_output_contract.json
reports/research/output_contracts/CF_factor_diagnostics_output_contract.md
```

R11 输出：

```text
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_value_daily.parquet
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_value_daily.csv
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_warnings.csv
reports/research/factors/CF_YYYY-MM-DD_YYYY-MM-DD_momentum_factor.md
```

R12 输出：

```text
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_value_daily.parquet
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_value_daily.csv
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_warnings.csv
reports/research/factors/CF_YYYY-MM-DD_YYYY-MM-DD_carry_factor.md
```

R13 输出：

```text
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_value_daily.parquet
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_value_daily.csv
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_warnings.csv
reports/research/factors/CF_YYYY-MM-DD_YYYY-MM-DD_structure_factors.md
```

R14 输出：

```text
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_diagnostic_daily.parquet
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_diagnostic_daily.csv
data/research/CF/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_warnings.csv
reports/research/factors/CF_YYYY-MM-DD_YYYY-MM-DD_factor_diagnostics.md
```

R15 输出：

```text
data/research/CF/returns/CF_YYYY-MM-DD_YYYY-MM-DD_forward_return_daily.parquet
data/research/CF/returns/CF_YYYY-MM-DD_YYYY-MM-DD_forward_return_daily.csv
data/research/CF/returns/CF_YYYY-MM-DD_YYYY-MM-DD_forward_return_warnings.csv
reports/research/returns/CF_YYYY-MM-DD_YYYY-MM-DD_forward_returns.md
```

R16 输出：

```text
data/research/CF/backtests/CF_YYYY-MM-DD_YYYY-MM-DD_single_factor_evaluation.parquet
data/research/CF/backtests/CF_YYYY-MM-DD_YYYY-MM-DD_single_factor_evaluation.csv
data/research/CF/backtests/CF_YYYY-MM-DD_YYYY-MM-DD_single_factor_backtest_warnings.csv
reports/research/backtests/CF_YYYY-MM-DD_YYYY-MM-DD_single_factor_backtest.md
```

R17 输出：

```text
data/research/CF/multifactor/CF_YYYY-MM-DD_YYYY-MM-DD_multifactor_score_daily.parquet
data/research/CF/multifactor/CF_YYYY-MM-DD_YYYY-MM-DD_multifactor_score_daily.csv
data/research/CF/multifactor/CF_YYYY-MM-DD_YYYY-MM-DD_multifactor_warnings.csv
reports/research/multifactor/CF_YYYY-MM-DD_YYYY-MM-DD_multifactor_diagnostics.md
```

R18 输出：

```text
data/research/CF/cost_sensitivity/CF_YYYY-MM-DD_YYYY-MM-DD_cost_sensitivity_summary.parquet
data/research/CF/cost_sensitivity/CF_YYYY-MM-DD_YYYY-MM-DD_cost_sensitivity_summary.csv
data/research/CF/cost_sensitivity/CF_YYYY-MM-DD_YYYY-MM-DD_cost_sensitivity_warnings.csv
reports/research/cost_sensitivity/CF_YYYY-MM-DD_YYYY-MM-DD_cost_sensitivity.md
```

R19 输出：

```text
reports/research/daily_brief/CF_YYYY-MM-DD_daily_research_brief.md
reports/research/daily_brief/CF_YYYY-MM-DD_daily_research_brief.json
reports/research/daily_brief/CF_YYYY-MM-DD_daily_research_brief_warnings.csv
```

后续研究输出会继续放在 `data/research/` 和 `reports/research/` 下，优先使用 Parquet/CSV/Markdown，避免过早做平台化 artifact registry。

## 7. 后续规划

近期优先级：

1. R00-R22 当前路线已完成；如要继续扩展，应先开 post-R22 路线。

扩展原则：

- 先验证 CF，再考虑 SR/AP。
- 先保证数据质量、追溯和研究解释性，再考虑自动化和平台化。
- 新增任何外部数据源前，必须先定义 raw 保存、字段映射、质量检查和人工复核边界。

## 8. 架构端接入建议

新架构端不要从 release/UAT/platform hardening 方向接手。推荐从以下顺序理解和推进：

1. 阅读 `docs/PROJECT_DIRECTION.md`，确认项目已经从生产平台收缩为研究工作台。
2. 阅读 `docs/CURRENT_STATE_RESEARCH_MAP.md`，理解哪些旧模块复用、哪些暂停。
3. 阅读 `docs/TASK_BREAKDOWN.md`，理解 R00-R22 已完成的 CF 研究工作台路线。
4. 后续开发应先明确 post-R22 任务边界，避免把已完成路线继续扩写成平台化工程。
5. 不要直接跳入 SR/AP 或外部数据 ingest；必须先通过 expansion gate 和人工复核。
6. 每个新模块都要保持 raw/core/research 边界，输出可检查文件和明确 warning。

## 9. 当前风险和人工复核项

仍需人工复核：

- CZCE 官方字段名称和单位口径。
- 成交量是单边还是双边口径。
- 结算状态、交易状态、涨跌停、保证金字段含义。
- CF 合约规则、最后交易日逻辑、换月阈值。
- 成本模型参数。
- 任何真实生产数据源的权限和使用边界。

这些事项在完成复核前只能作为 `HUMAN_REVIEW_REQUIRED` 或 warning 暴露，不能作为隐含生产假设进入研究结论。

## 10. 一句话总结

Cottonquant 当前不是要继续做生产级量化平台，而是要基于已有 D0-D23 工程基础，完成一个 CF 优先、日频、可追溯、可检查、可解释的研究级生产数据决策工作台。R10 已经固定下游因子诊断输出契约，R11-R22 已经接入四个 MVP 因子输出、每日诊断状态表、T+1 forward returns、单因子研究型回测摘要、等权多因子 score diagnostics、成本敏感性 summaries、每日研究简报、一键 research pipeline、轻量 replay 与 expansion gate。
下一步应先定义 post-R22 路线，再决定是否进入 SR/AP 或外部数据研究原型。
