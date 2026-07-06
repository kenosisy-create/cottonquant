# CF 基本面观察 R53

R53 在 R51 手工输入契约之后，读取已经放入
`data/incoming/CF/fundamentals/manual/` 的 iFinD 手工导出文件，生成可审计的
基本面观察表和中文报告。

## 定位

- 产品范围：仅 CF。
- 数据来源：本地手工放入的 iFinD CSV / Excel 文件，以及 TTEB 纺织链分块 Excel。
- 研究用途：库存、现货价格、基差的人工复核观察。
- 信号状态：`fundamental_signal_status=not_connected`。
- 研究边界：不进入 `signal_matrix`，不进入 `composite_score`，不构成交易指令。

## 当前已支持

| 数据集 | 当前处理 | 输出 |
| --- | --- | --- |
| 库存 | 解析 iFinD 宽表中包含“库存”的指标 | `CF_fundamental_inventory_daily.parquet` |
| 现货价格 | 解析价格指数、现货、提货价、到厂价、期货收盘价 | `CF_fundamental_spot_price_daily.parquet` |
| 基差 | 使用中国棉花价格指数 3128B 与 iFinD 活跃合约价格形成观察口径 | `CF_fundamental_basis_daily.parquet` |
| 仓单数量 | 解析 iFinD/Wind 汇总的郑商所仓单窄表 Excel | `CF_fundamental_warehouse_receipt_daily.parquet` |
| 进口 | 仅检查 Excel 是否已经刷新为数值 | 未刷新时输出 `IMPORT_INPUT_NOT_REFRESHED` |
| 纺织链条 | 解析 TTEB 开工负荷、纱厂/织厂库存分块 Excel；仍只作为观察层 | `CF_fundamental_textile_chain_daily.parquet` |

## 命令

```powershell
$env:PYTHONPATH="src"; $env:PYTHONIOENCODING="utf-8"; py -3.12 -m cotton_factor.cli.main research build-cf-fundamental-observation --source-dir data/incoming/CF/fundamentals/manual --output-dir data/research/CF/fundamentals --report-output-dir reports/research/fundamentals
```

## 输出

- `data/research/CF/fundamentals/CF_fundamental_inventory_daily.parquet`
- `data/research/CF/fundamentals/CF_fundamental_inventory_daily.csv`
- `data/research/CF/fundamentals/CF_fundamental_basis_daily.parquet`
- `data/research/CF/fundamentals/CF_fundamental_basis_daily.csv`
- `data/research/CF/fundamentals/CF_fundamental_spot_price_daily.parquet`
- `data/research/CF/fundamentals/CF_fundamental_spot_price_daily.csv`
- `data/research/CF/fundamentals/CF_fundamental_warehouse_receipt_daily.parquet`
- `data/research/CF/fundamentals/CF_fundamental_warehouse_receipt_daily.csv`
- `data/research/CF/fundamentals/CF_fundamental_textile_chain_daily.parquet`
- `data/research/CF/fundamentals/CF_fundamental_textile_chain_daily.csv`
- `data/research/CF/fundamentals/CF_fundamental_field_metadata.csv`
- `data/research/CF/fundamentals/CF_fundamental_observation_quality.csv`
- `data/research/CF/fundamentals/CF_fundamental_observation.json`
- `data/research/CF/fundamentals/CF_fundamental_observation_manifest.json`
- `reports/research/fundamentals/CF_fundamental_observation.md`
- `reports/research/fundamentals/CF_fundamental_observation_warnings.csv`

## 人工复核项

- iFinD 指标含义、单位和来源。
- 基差中的期货“活跃合约”是否能映射到真实可交易主力合约。
- 仓单数量来源和单位；当前按郑商所口径，由 iFinD 或 Wind 汇总文件提供。
- 进口数据的期间、单位和刷新状态。
- TTEB 纺织链条口径：纯棉纱厂负荷、全棉坯布负荷、纺企棉花库存、纺企棉纱库存、织厂棉纱库存、全棉坯布库存的单位和来源。
- 纺织链条仍缺失项：纺织订单、棉纱利润等未提供数据，不得估算填补。
- 基本面观察是否可以进入信号，需要另做历史验证后再决定。

## 后续路线

1. 先把 R53 作为独立观察层稳定运行。
2. `validated_research_brief` 已支持通过 `--fundamental-observation-json-path`
   引用 R53，并增加“基本面观察/人工复核状态”章节。
3. 继续刷新仓单数量，补齐刷新后的进口数据。
4. 基本面字段连续稳定并通过人工复核后，再研究 `fundamental_signal`，不能直接接入交易结论。
