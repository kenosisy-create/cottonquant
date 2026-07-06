# CF 后续需要补的数据口清单

本文件用于承接 V4 任务书和 R52 expansion gate 之后的下一阶段工作：
继续保持 CF-first，不启动多品种真实 ingest；先把 CF 研究工作台缺失的数据口、
人工复核项、默认落点和接入优先级固定下来。

## 当前主线状态

| 模块 | 当前状态 | 最新证据 |
| --- | --- | --- |
| 期货 core | 已接入 | `data/core/CF/core_quote_daily.parquet`，截至 `2026-07-03` |
| 期权 core/proxy/linkage | 已接入研究 proxy | `data/core/CF/core_option_quote_daily.parquet`、R48/R49 产物 |
| 历史验证 | 已刷新 | R36/R37/R41/R42 已刷新到 `2026-07-03` |
| 验证型日报/发布包 | 已刷新 | `runs/daily/CF/2026-07-03/` |
| 基本面 | 库存/现货/基差/仓单观察已接入 | R53 输出基本面观察表，仍为 `not_connected`，不进自动信号 |
| 扩品种 gate | 已刷新 | R52 输出 `HUMAN_REVIEW_REQUIRED_BEFORE_EXPANSION` |

## P0：必须优先补的数据口

### 1. 交易所日更文件

- 用途：维持 `core_quote_daily.parquet` 和最新日报。
- 当前路径：`data/incoming/CF/history/`
- 推荐文件：`CFFUTURES{year}.xlsx`、`CFFUTURES{year}.xls`、`ALLFUTURES{year}.zip`
- 当前接入方式：本地官方文件放入后运行 `scripts/update_cf_latest_research.ps1`
- 是否自动入信号：是，进入期货 core 后参与 observable signal。
- 人工复核：官方字段解释、缺失列、成交量/持仓量单位、交易日是否完整。
- 阻塞风险：如果年度文件字段变化，必须停止并更新字段映射，不能静默兼容。

### 2. 期权年度历史文件

- 用途：维持期权 PCR、IV proxy、skew proxy、option filter。
- 当前路径：`data/incoming/CF/options/history/`
- 当前 core：`data/core/CF/core_option_quote_daily.parquet`
- 是否自动入信号：作为期货信号过滤器，不进入 `composite_score`。
- 人工复核：期权合约代码、C/P、行权价、标的月份、低流动性过滤、美式期权
  IV proxy 口径。
- 阻塞风险：缺期权数据时必须回退为 `option_signal=not_connected`，不能假装中性。

### 3. R51/R53 基本面手工输入与观察文件

- 用途：先用于人工观察，不进入自动交易方向。
- 当前路径：`data/incoming/CF/fundamentals/manual/`
- 契约文件：`data/research/CF/fundamentals/CF_fundamental_manual_input_template.csv`
- 当前状态：库存、现货价格、基差、仓单数量已由 R53 解析为观察表；进口 Excel 未刷新；纺织链条仍缺失。
- 是否自动入信号：否。
- 人工复核：所有字段。
- 阻塞风险：没有可靠来源前，只能作为“基本面观察/人工复核状态”，不能变成
  `fundamental_signal`。

## P1：下一阶段建议补的数据口

### 4. 仓单

- 建议文件：`CF_warehouse_receipt_manual.csv`
- 建议字段：`trade_date`、`product_code`、`warehouse_receipt`、`change`、
  `source_name`、`data_quality_flag`、`human_review_required`
- 推荐频率：日频。
- 研究用途：库存压力、交割压力、趋势衰竭辅助解释。
- 暂不自动入信号原因：仓单单位和口径需要人工确认。

### 5. 基差

- 建议文件：`CF_basis_manual.csv`
- 建议字段：`trade_date`、`product_code`、`region`、`spot_price`、
  `futures_contract`、`futures_settle`、`basis`、`source_name`、
  `data_quality_flag`、`human_review_required`
- 推荐频率：日频。
- 研究用途：现货强弱、期货价格偏离、趋势确认/背离解释。
- 暂不自动入信号原因：区域、现货价格来源、期货合约匹配规则必须复核。

### 6. 库存

- 建议文件：`CF_inventory_manual.csv`
- 建议字段：`trade_date`、`product_code`、`inventory_value`、`unit`、
  `source_name`、`data_quality_flag`、`human_review_required`
- 推荐频率：周频或日频。
- 研究用途：中周期供需压力解释。
- 暂不自动入信号原因：库存口径和单位不稳定时会误导趋势解释。

### 7. 进口

- 建议文件：`CF_import_manual.csv`
- 建议字段：`period`、`product_code`、`import_volume`、`unit`、
  `source_name`、`data_quality_flag`、`human_review_required`
- 推荐频率：月频。
- 研究用途：供应冲击和中长期供需解释。
- 暂不自动入信号原因：月频数据不能直接等同日频交易信号，需要滞后处理。

### 8. 纺织链条

- 建议文件：`CF_textile_chain_manual.csv`
- 建议字段：`period`、`indicator_name`、`indicator_value`、`unit`、
  `source_name`、`data_quality_flag`、`human_review_required`
- 推荐指标：开机率、纱线库存、坯布库存、订单、利润、下游价格。
- 研究用途：需求侧解释和趋势持续性辅助判断。
- 暂不自动入信号原因：指标定义、频率和来源差异大，先做人审解释。

## P2：暂缓的数据口

### 9. 天气、USDA、宏观、外盘

- 暂缓原因：当前阶段任务书要求 CF 研究闭环，不扩展为大平台。
- 可保留方向：只做接口占位或人工备注，不进入自动信号。

### 10. SR/AP 等多品种真实 ingest

- 暂缓原因：R52 gate 仍要求人工 go/no-go。
- 前置条件：CF 主线证据、人审、候选品种合约规则、字段映射、质量规则、
  执行边界全部完成。

## 后续接入顺序建议

1. 继续保持期货、期权官方文件日更。
2. 维持 R53 基本面观察层，不进入自动信号。
3. 补齐仓单数量和刷新后的进口数据，同时保留纺织链条缺失 warning。
4. 已在 validated brief 中增加“基本面观察/人工复核状态”，下一步继续补缺口数据。
5. 只有当基本面字段连续稳定并通过人工复核，才研究 `fundamental_signal`。
6. 多品种扩展只允许在 R52 gate 和人审通过后启动一个研究试点。

## 研究边界

- 本清单不构成交易指令。
- 缺失数据必须显式输出 warning，不能静默填充。
- 所有基本面和扩品种字段解释都属于 `HUMAN_REVIEW_REQUIRED`。
- forward return 只作为历史后验验证标签，不参与最新日信号生成。
