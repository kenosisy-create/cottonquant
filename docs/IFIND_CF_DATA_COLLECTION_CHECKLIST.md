# iFinD 补数清单：CF 研究工作台

本清单用于指导人工从 iFinD Excel 插件补齐 CF 研究工作台下一阶段需要的数据。
当前阶段不直接把基本面数据写入自动信号；先按 R51 手工输入契约落地，后续再做字段
校验和质量报告。

## 总原则

- 主数据源：iFinD Excel 插件。
- 不手写未知 iFinD 指标代码；通过 Excel 插件函数库确认代码和字段。
- 每个数据都要保留：日期、指标、数值、单位、来源、频率、iFinD 公式或函数、刷新时间、备注。
- 期货/期权行情仍优先保留交易所官方文件；iFinD 可作为复核或补缺来源。
- 基本面数据当前只进入 `data/incoming/CF/fundamentals/manual/`，不进入自动交易方向。

## 你优先补的文件

| 优先级 | 文件名 | 放置路径 | 最小历史范围 | 频率 | 状态 |
| --- | --- | --- | --- | --- | --- |
| P0 | `CFFUTURES{year}.xlsx` 或 `ALLFUTURES{year}.zip` | `data/incoming/CF/history/` | 2021 至今 | 日频 | 继续保持 |
| P0 | `CFOPTIONS{year}.xlsx` | `data/incoming/CF/options/history/` | 2021 至今 | 日频 | 继续保持 |
| P1 | `CF_warehouse_receipt_manual.csv` | `data/incoming/CF/fundamentals/manual/` | 2021 至今，至少近 3 年 | 日频 | 需要补 |
| P1 | `CF_basis_manual.csv` | `data/incoming/CF/fundamentals/manual/` | 2021 至今，至少近 3 年 | 日频 | 需要补 |
| P1 | `CF_inventory_manual.csv` | `data/incoming/CF/fundamentals/manual/` | 2021 至今，至少近 3 年 | 周频/日频 | 需要补 |
| P1 | `CF_import_manual.csv` | `data/incoming/CF/fundamentals/manual/` | 2021 至今，至少近 3 年 | 月频 | 需要补 |
| P1 | `CF_textile_chain_manual.csv` | `data/incoming/CF/fundamentals/manual/` | 2021 至今，至少近 3 年 | 周频/月频 | 需要补 |

## iFinD 取数入口建议

### 1. 期货行情

- iFinD 入口：`期货全部指标`
- 搜索关键词：`棉花期货`、`郑棉`、`CF`、`郑商所 棉花`
- 必要字段：交易日、合约代码、开盘、最高、最低、收盘、结算、成交量、持仓量。
- 说明：当前系统直接接郑商所官方年度文件；iFinD 行情先用于复核或临时补缺。

### 2. 期权行情

- iFinD 入口：`期货全部指标` 或期权相关函数库，以插件实际分类为准。
- 搜索关键词：`棉花期权`、`CF 期权`、`郑商所 棉花期权`
- 必要字段：交易日、期权合约、标的期货、C/P、行权价、结算价、成交量、持仓量。
- 说明：如果 iFinD 返回字段名称和郑商所不同，先导出原始表，不要自行改名覆盖官方文件。

### 3. 仓单

- iFinD 搜索关键词：`棉花 仓单`、`郑商所 棉花 仓单`、`CF 仓单`
- 输出文件：`CF_warehouse_receipt_manual.csv`
- 必填字段：
  - `trade_date`
  - `product_code`
  - `warehouse_receipt`
  - `change`
  - `source_name`
  - `data_quality_flag`
  - `human_review_required`
- 建议固定值：
  - `product_code=CF`
  - `source_name=iFinD`
  - `data_quality_flag=REVIEW_REQUIRED`
  - `human_review_required=TRUE`
- 备注：在 `remark` 中写入 iFinD 指标名和公式。

### 4. 基差

- iFinD 搜索关键词：`棉花 基差`、`郑棉 基差`、`棉花 现货价`、`中国棉花价格指数`
- 输出文件：`CF_basis_manual.csv`
- 必填字段：
  - `trade_date`
  - `product_code`
  - `region`
  - `spot_price`
  - `futures_contract`
  - `futures_settle`
  - `basis`
  - `source_name`
  - `data_quality_flag`
  - `human_review_required`
- 计算规则：`basis = spot_price - futures_settle`
- 备注：`region` 必须写清楚，例如全国、新疆、内地或 iFinD 原始口径；不要混用不同口径。

### 5. 库存

- iFinD 搜索关键词：`棉花 库存`、`棉花 商业库存`、`棉花 工业库存`
- 输出文件：`CF_inventory_manual.csv`
- 必填字段：
  - `trade_date`
  - `product_code`
  - `inventory_value`
  - `unit`
  - `source_name`
  - `data_quality_flag`
  - `human_review_required`
- 备注：库存口径和单位必须写在 `remark`，例如商业库存、工业库存、万吨等。

### 6. 进口

- iFinD 搜索关键词：`棉花 进口`、`棉花 进口数量`、`海关 棉花进口`
- 输出文件：`CF_import_manual.csv`
- 必填字段：
  - `period`
  - `product_code`
  - `import_volume`
  - `unit`
  - `source_name`
  - `data_quality_flag`
  - `human_review_required`
- 备注：`period` 用 `YYYY-MM`；不要把月频数据强行扩成日频。

### 7. 纺织链条

- iFinD 搜索关键词：`棉纱 开机率`、`纺织 开机率`、`棉纱 库存`、
  `坯布 库存`、`纺织 订单`、`棉纱 利润`
- 输出文件：`CF_textile_chain_manual.csv`
- 必填字段：
  - `period`
  - `indicator_name`
  - `indicator_value`
  - `unit`
  - `source_name`
  - `data_quality_flag`
  - `human_review_required`
- 建议指标：
  - 纺纱/织厂开机率
  - 棉纱库存
  - 坯布库存
  - 订单或景气指标
  - 棉纱利润

## iFinD Excel 操作步骤

1. 打开 Excel，确认 iFinD 插件已登录。
2. 进入函数库或数据浏览器。
3. 按上面的关键词搜索指标。
4. 用函数向导生成公式，不要手写未确认的指标代码。
5. 刷新公式。
6. 检查 `#NAME?`、`#VALUE!`、`#N/A`、空值、权限错误、最新日期滞后。
7. 将刷新后的值另存为 CSV。
8. 按本清单字段重命名并放入对应路径。
9. 在 `remark` 中保留 iFinD 指标名、公式、刷新时间。

## 如果 iFinD 缺失或没有权限

| 数据口 | 缺失处理 |
| --- | --- |
| 期货行情 | 继续用郑商所官方年度文件；iFinD 只做复核 |
| 期权行情 | 继续用郑商所官方期权年度文件；没有则 `option_signal=not_connected` |
| 仓单 | 标记 `MISSING_FUNDAMENTAL_INPUT`，不要自行估算 |
| 基差 | 只在现货价和期货结算价来源都明确时计算 |
| 库存 | 标记缺失，等待可靠来源 |
| 进口 | 可用海关/月频公开数据补，但要写明来源 |
| 纺织链条 | 先作为人工备注，不进入自动信号 |

## 当前不能做的事

- 不能把基本面数据直接写成交易信号。
- 不能把月频进口数据硬扩成日频交易结论。
- 不能把不同地区或不同口径的基差混成一个序列。
- 不能用估算值填补缺失。
- 不能把 iFinD 未确认指标代码写入项目脚本。
