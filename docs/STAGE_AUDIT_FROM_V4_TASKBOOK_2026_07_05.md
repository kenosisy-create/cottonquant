# Cottonquant V4 阶段审计

审计口径：从 `CottonquantV4任务书.md` 最后修改时间
`2026-07-03 20:42:21` 之后，到本次审计时间 `2026-07-05` 的工程状态。

## 一、审计结论

V4 任务书发布后，项目已经从“最新日报单点打磨”推进到“历史证据、
期权联动、配置固化”的研究工作台主线。

当前系统已具备：

- CF 期货 core 数据覆盖 `2021-01-04` 至 `2026-07-03`。
- CF 期权 core 数据覆盖 `2021-01-04` 至 `2026-07-03`。
- 最新 signal-only brief 可在无未来收益标签时生成。
- 趋势阶段 S0-S4 已进入最新日报和多周期矩阵。
- 历史证据、事件解释、validated brief、publish pack 主链路已完成工程闭环。
- R48 期权 proxy 和 R49 期货-期权过滤已接入。
- R50 CF 产品配置与因子注册快照已完成。

但仍不能视为“全部研究生产完成”：

- 历史验证与事件解释当前最新后验窗口仍停在 `2026-07-01`，因为
  `2026-07-02` 和 `2026-07-03` 尚未形成完整 forward-return 标签。
- 公众号发布包最新一次仍是 `2026-07-01`，尚未刷新到 `2026-07-03`。
- 期权 IV、skew、PCR 均是研究 proxy，未完成美式期权精确定价和 Greek 校准。
- CF 合约规则、tick size、期权字段解释、流动性阈值仍有人工复核项。

## 二、任务书路线对照

| 任务书方向 | 当前完成度 | 证据 | 判断 |
| --- | ---: | --- | --- |
| latest signal-only brief | 95% | `runs/daily/CF/2026-07-03/latest_signal_brief.md` | 已能在最新日生成，不依赖未来收益。 |
| 趋势起点/终点识别 | 85% | R24-R40 趋势阶段、事件、质量校准模块 | S0-S4 已接入，历史解释可用，仍需继续复核阈值。 |
| 多周期信号矩阵 | 90% | `data/research/CF/signal_matrix/*2026-07-03*` | 1/3/5/10/20/40D 已覆盖，R49 期权过滤可见。 |
| 滚动验证与参数研究 | 80% | R41 historical evidence、R42 event explanation | 历史证据链已成型，但最新后验验证需等待未来标签。 |
| 期权联动研究 | 75% | R46-R49 产物 | raw/core/proxy/linkage 已完成，精确 IV/Greek 未做。 |
| 数据日更与审计 | 75% | `scripts/update_cf_latest_research.ps1` | 默认日更和周更开关已具备，期权 proxy 仍建议周更或显式参数接入。 |
| 可视化与公众号发布 | 65% | `runs/daily/CF/2026-07-01/publish/` | 发布包已完成一次，需刷新到最新日并稳定模板。 |
| product_config 抽象 | 70% | R50 product registry | CF 已固化，未启动多品种。 |
| 基本面接口 | 60% | R51 fundamental data contract | 已建立仓单、基差、库存、进口、纺织链条的手工输入 schema/模板/warning/report；尚未接入可靠数据源和自动信号。 |
| 多品种扩展 | 15% | R52 expansion gate refresh | 已把 R41-R51 主线证据纳入扩品种前置条件；仍正确保持 CF-only。 |

## 三、关键数据状态

| 数据/产物 | 行数 | 日期范围 | 状态 |
| --- | ---: | --- | --- |
| `core_quote_daily.parquet` | 7,986 | 2021-01-04 至 2026-07-03 | 已对齐最新期货数据。 |
| `core_option_quote_daily.parquet` | 295,662 | 2021-01-04 至 2026-07-03 | 已对齐期货标的价格，缺标的价格为 0。 |
| R48 option factor proxy | 5,483 | 2021-01-04 至 2026-07-03 | READY 4,131, WATCH 601, WEAK 751。 |
| R49 signal matrix | 7,986 | 2021-01-04 至 2026-07-03 | 最新日 `option_signal=confirm_long`。 |
| R50 product registry | 10 factor rows | 配置快照 | 4 个期货因子，6 个期权 proxy。 |

## 四、最新日研究状态

截至 `2026-07-03`：

- 主力合约：`CF609`
- 最新方向：`long`
- 趋势阶段：`S3 衰竭观察`
- 期权过滤：`confirm_long`
- PCR volume：`0.553764`
- PCR OI：`0.697677`
- skew proxy：`-0.002417`

解释：期货多周期方向与期权 proxy 同向偏多，但趋势阶段处于 S3，
说明系统当前不是简单给出追多结论，而是同时提示“偏多确认”和
“衰竭观察/低置信风险”。

## 五、本阶段新增工程产物

- R48：`src/cotton_factor/research_workbench/option_factor_proxy.py`
- R49：`src/cotton_factor/research_workbench/signal_matrix.py` 接入 `option_factor_path`
- R49：`latest_signal_brief` 和 `validated_research_brief` 展示期权过滤证据
- R50：`src/cotton_factor/research_workbench/product_research_registry.py`
- R50：`reports/research/product_registry/CF_product_research_registry.md`
- 审计文档：`docs/STAGE_AUDIT_FROM_V4_TASKBOOK_2026_07_05.md`

## 六、质量验证

本阶段已通过：

- `py -3.12 -m ruff check src tests`
- `py -3.12 -m pytest`

最近一次全量测试结果：`271 passed`。

## 七、主要风险与人工复核

必须保留人工复核：

- `tick_size`
- `last_trade_day_rule`
- `official_field_units`
- `option_style`
- `official_option_field_interpretation`
- `american_option_iv_proxy_model_boundary`
- `moneyness_and_skew_proxy_definition`
- `option_liquidity_thresholds`
- `option_signal_filter_rules_before_trading_use`

当前最重要的研究风险：

- R48 期权 proxy 不是精确隐波，不应被包装成定价结论。
- R49 期权过滤暂不改变 `composite_score`，这是正确边界。
- R41/R42 后验验证仍需要等待足够 forward-return 标签再刷新到最新日期。
- 发布包尚未更新到 `2026-07-03`。

## 八、下一步建议

R51 基本面接口占位和 R52 expansion gate 刷新已经进入实现与验证。

建议范围：

- 先刷新最新完整验证窗口的 R41/R42/R45 证据链，再重跑 R52 gate。
- R51 后续只在可靠数据源和人工复核规则确定后，才进入字段校验或基本面观察展示。
- 多品种扩展仍不能启动真实 ingest，只能在 gate 全部通过并完成人审后做一个同交易所近似品种研究试点。

R52 多品种扩展仍应继续等待，直到 CF 的历史证据、事件解释、期权联动、
发布包和基本面接口全部稳定。
