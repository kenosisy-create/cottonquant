# CottonquantV4任务书

以下是我对项目阶段的判断，以及我建议你接下来采用的**后续架构与研究设计**。以下内容只作为研究系统设计，不构成投资建议或交易指令。

## 一、我对你当前项目阶段的判断

你的项目已经不是“从 0 到 1 搭建行情处理脚手架”的阶段，而是进入了：

> **CF 日频研究级生产数据决策工作台 vNext 阶段。**
>

现在已经具备三类基础能力：第一，CF 官方历史数据能够接入、标准化、留痕；第二，R20 研究管线已经可以输出因子、forward return、回测、成本敏感性和日报；第三，已有 `update_cf_latest_research.ps1` 日更脚本，可以形成轻量自动化路径。审计材料里也明确指出，当前定位应收缩为“研究级生产数据决策工作台”，而不是 OMS、多品种生产平台、分钟级执行系统或自动下单平台。

我对当前完成度的定义如下：

| 模块 | 当前状态 | 判断 |
| --- | --- | --- |
| 数据入库 | 已可用 | CF 2021-2026 日频核心数据已经形成，raw/core/research/archive 分层可复用 |
| 研究管线 | 已可用 | momentum、carry、curve slope、OI pressure、forward return、单因子、多因子、成本敏感性均已跑通 |
| 日更能力 | 基础可用 | 可靠主路径仍是人工或浏览器下载官方年度文件后由脚本自动接入 |
| 最新日报 | 尚未补齐 | 需要新增不依赖未来收益标签的 latest signal-only brief |
| 趋势识别 | 研究雏形已有 | 但尚未成为日报主流程 |
| 稳定交易结论 | 尚未完成 | 因子阈值、权重、成本后稳定性、趋势起终点都需要继续研究 |
| 多品种扩展 | 不宜马上铺开 | 应先抽象配置和扩展门槛，再选 1-2 个相近品种试点 |
| 期权联动 | 尚未纳入 | 是下一阶段最有价值的研究增强方向之一 |

官方层面，郑商所网站已经把“棉花期货/期权”列为上市品种，并在交易数据栏目提供每日行情、历史行情下载、交易月历、仓单日报、结算参数等入口，这意味着你的系统后续可以围绕官方日频数据继续强化数据接入、日更校验和衍生指标构建。([郑州商品交易所](https://www.czce.com.cn/))

---

## 二、后续总目标：从“因子日报”升级为“研究操作系统”

我建议后续不要简单理解为“多加几个因子”。真正的升级方向应是：

> **把系统从单一 CF 因子管线，升级为可复核、可日更、可发布、可扩展的商品期货研究操作系统。**
>

这个操作系统应回答六类问题：

1. **市场事实**：今天价格、持仓、成交、期限结构、主力切换发生了什么？
2. **模型信号**：动量、carry、曲线、持仓压力、波动率、期权情绪给出什么方向？
3. **趋势阶段**：现在是低位修复、趋势起点、趋势中继、衰竭观察，还是终点确认？
4. **历史证据**：类似状态在 1/3/5/10/20/40 日之后的表现如何？
5. **风险约束**：成本、流动性、换月、交割月、异常行情、期权隐波是否降低信号可信度？
6. **发布输出**：能否自动生成公众号可用的文字、图表、结论边界和观察清单？

所以后续架构的核心不是“预测涨跌”，而是形成一个**市场状态识别 + 信号置信度过滤 + 可发布研究报告**的闭环。

---

## 三、建议的 vNext 架构

我建议把后续架构分为七层。

```
数据源层
  ├─ 郑商所期货日行情 / 历史行情 / 交易日历 / 仓单 / 结算参数
  ├─ 郑商所棉花期权日行情 / 期权结算 / 合约参数
  ├─ 现货、基差、仓单、库存、进口、纺织链条数据
  ├─ 外盘、汇率、宏观、事件日历
  └─ 人工复核输入

数据接入层
  ├─ raw snapshot
  ├─ incoming watcher
  ├─ schema validator
  ├─ checksum / manifest
  ├─ incremental updater
  └─ data quality report

核心数据层
  ├─ core_quote_daily
  ├─ core_option_quote_daily
  ├─ contract_master
  ├─ option_contract_master
  ├─ trade_calendar
  ├─ chain_mapping
  ├─ trade_mapping
  └─ continuous_price

特征与状态层
  ├─ futures factors
  ├─ option factors
  ├─ term structure factors
  ├─ volatility factors
  ├─ liquidity / position factors
  ├─ fundamental factors
  ├─ regime labels
  └─ trend phase labels

研究引擎层
  ├─ latest signal-only engine
  ├─ forward return labelling engine
  ├─ rolling validation engine
  ├─ threshold research engine
  ├─ factor combination engine
  ├─ option-futures linkage engine
  └─ trend start/end engine

报告与可视化层
  ├─ daily latest brief
  ├─ validated research brief
  ├─ weekly rolling review
  ├─ option dashboard
  ├─ factor dashboard
  ├─ chart pack
  └─ WeChat publish pack

扩展治理层
  ├─ product_config
  ├─ factor registry
  ├─ cost model registry
  ├─ expansion gate
  ├─ human review registry
  └─ release manifest
```

这套架构的关键是：**最新日观察报告**和**完整回测验证报告**必须分离。最新日可以输出市场事实和信号观察，但不能伪装成已经完成 forward-return 验证的结论。这个边界与你当前审计结论完全一致。

---

## 四、第一优先级：新增 latest signal-only brief

你现在最大的使用痛点是：完整研究窗口需要未来 1/3/5 日收益标签，所以最新交易日无法马上形成完整日报。这是合理的 no-look-ahead 约束，但会影响日常研究可用性。

我建议立即新增一个独立模块：

```
R23_latest_signal_only_brief
```

### 1. 报告定位

它只回答：

> 今天市场发生了什么？当前信号结构是什么？明天需要观察什么？
>

它不回答：

> 历史验证后确定能赚钱了吗？
>

### 2. 输出结构

建议 latest brief 固定为中文模板：

```
# CF 最新交易日研究观察

一、数据状态
- 最新交易日
- 入库文件
- 核心表最新日期
- 数据完整性检查
- 是否存在人工复核项

二、市场事实
- 主力合约
- 主力结算价、涨跌、成交、持仓、持仓变化
- 次主力与远月结构
- 合约活跃度排序
- 是否发生主力迁移预警

三、期限结构
- 近月-主力
- 远月-主力
- 曲线斜率
- 升贴水结构变化
- 与过去 N 日分位数比较

四、因子信号
- momentum
- carry
- curve slope
- OI pressure
- 多因子方向
- 信号一致性评分

五、趋势阶段
- 未确认
- 起点观察
- 趋势中
- 衰竭观察
- 终点确认

六、期权观察，若数据已接入
- ATM IV
- IV rank
- PCR
- 偏度
- 隐含波动率期限结构
- 期权持仓集中区域

七、明日观察清单
- 需要确认的价格点
- 需要确认的持仓行为
- 需要确认的期限结构变化
- 需要人工复核的数据或事件

八、边界声明
- 本报告不包含未来收益标签
- 本报告不代表完整回测验证
- 仅作研究，不构成投资建议
```

### 3. 工程产物

建议新增这些文件：

```
src/research/latest_signal_brief.py
src/research/render_latest_brief.py
configs/research/CF_latest_signal.yml
templates/reports/latest_signal_brief_cn.md.j2
scripts/run_cf_latest_signal_brief.ps1
tests/research/test_latest_signal_brief.py
```

### 4. 验收标准

| 验收项 | 标准 |
| --- | --- |
| 最新日期 | 报告日期等于 core 表最新交易日 |
| no-look-ahead | 不读取未来收益标签 |
| 中文化 | 所有章节中文输出 |
| 可审计 | 报告包含 run_id、data_asof、input_file、pipeline_version |
| 可发布 | 自动输出 `.md`、`.html`、核心图表 `.png` |
| 边界清晰 | 明确标记“未完成 forward-return 验证” |

---

## 五、第二优先级：趋势起点/终点识别主流程化

当前四个因子已经能描述“方向”，但还不能稳定回答你真正关心的问题：

> 现在是反弹、趋势起点、趋势中继，还是趋势衰竭？
>

我建议新增：

```
R24_trend_phase_engine
```

### 1. 趋势状态机

定义五种状态：

| 状态 | 含义 | 典型特征 |
| --- | --- | --- |
| S0 未确认 | 没有方向优势 | 因子分歧、价格横盘、持仓无确认 |
| S1 起点观察 | 可能从修复转趋势 | 价格突破、OI 同向、curve/carry 支持 |
| S2 趋势中 | 趋势确认 | 多周期动量共振、持仓支持、曲线结构稳定 |
| S3 衰竭观察 | 趋势质量下降 | 价格新高但持仓不支持，或曲线斜率回落 |
| S4 终点确认 | 趋势失败或结束 | 动量翻转、关键均线/结构破位、OI pressure 反向 |

### 2. 趋势起点候选条件

趋势起点不应该由单一价格突破决定，而应使用组合条件：

```
trend_start_score =
  price_breakout_score
+ momentum_turn_score
+ oi_confirm_score
+ curve_support_score
+ carry_support_score
+ volatility_filter_score
+ liquidity_filter_score
```

建议初始规则：

| 模块 | 起点确认方向 |
| --- | --- |
| 价格 | 主力收盘/结算突破 20 日区间或关键均线 |
| 动量 | 10D momentum 翻正，20D momentum 改善 |
| 持仓 | 上涨增仓或下跌增仓方向清晰 |
| 曲线 | 主力与远月结构支持方向 |
| carry | carry 信号与价格方向一致 |
| 波动率 | 突破不是单日异常放量假突破 |
| 流动性 | 主力合约成交和持仓稳定，非临近退市扰动 |

### 3. 趋势终点候选条件

```
trend_end_score =
  momentum_decay_score
+ oi_divergence_score
+ curve_flatten_score
+ drawdown_break_score
+ option_warning_score
+ roll_risk_score
```

终点确认应更保守，因为过早识别终点容易把趋势中继误判为结束。

### 4. 报告输出

在日报里增加一张表：

| 指标 | 当前状态 | 过去 5 日变化 | 判断 |
| --- | --- | --- | --- |
| 价格结构 | 突破观察 | 改善 | 支持起点 |
| 动量 | 修复中 | 改善 | 弱支持 |
| 持仓压力 | 同向增强 | 改善 | 支持 |
| 曲线结构 | 远月升水 | 稳定 | 支持 |
| 期权偏度 | 未接入/待确认 | - | 暂不评分 |
| 综合阶段 | S1 起点观察 | 上调 | 尚未进入强趋势 |

这样，你的报告就会从“因子 long/short”升级为“趋势阶段判断”。

---

## 六、第三优先级：期权联动研究模块

我建议你一定要加期权模块，但不要一开始就把目标设成“期权策略回测”。更稳妥的路线是：

> **先把期权作为波动率、情绪、风险定价和趋势过滤器。**
>

郑商所棉花期权合约的标的是棉花期货合约，合约类型包括看涨、看跌，交易单位为 1 手棉花期货合约，报价单位为元/吨，行权方式为美式，交易代码格式为 `CF—合约月份—C/P—行权价格`。这说明期权链天然可以和 CF 期货合约月份、行权价、看涨/看跌方向进行映射。([郑州商品交易所](https://www.czce.com.cn/cn/sspz/mh/bzhy/qqhy/H077002003001002index_1.htm))

同时，棉花期货合约交易单位为 5 吨/手，合约交割月份为 1、3、5、7、9、11 月，交易代码为 CF；这些字段应该进入你的 `product_config` 和 `contract_master`，作为期货与期权联动的底层参数。([郑州商品交易所](https://www.czce.com.cn/cn/sspz/mh/bzhy/qhhy/H077002003001001index_1.htm))

### 1. 期权数据表设计

新增核心表：

```
data/core/CF/core_option_quote_daily.parquet
```

建议字段：

| 字段 | 含义 |
| --- | --- |
| trade_date | 交易日 |
| option_symbol | 期权合约代码 |
| underlying_symbol | 标的期货合约 |
| option_type | C / P |
| strike | 行权价 |
| maturity_date | 到期日 |
| days_to_maturity | 剩余交易日或自然日 |
| open | 开盘价 |
| high | 最高价 |
| low | 最低价 |
| close | 收盘价 |
| settle | 结算价 |
| volume | 成交量 |
| open_interest | 持仓量 |
| underlying_settle | 标的期货结算价 |
| moneyness | 标的价格 / 行权价 |
| log_moneyness | ln(F/K) |
| is_atm | 是否 ATM 附近 |
| liquidity_flag | 流动性标签 |
| data_quality_flag | 数据质量标签 |

新增衍生表：

```
data/research/CF/option_surface_daily.parquet
data/research/CF/option_factor_daily.parquet
data/research/CF/option_futures_linkage_daily.parquet
```

### 2. 期权因子设计

先做六类因子。

| 因子组 | 指标 | 研究含义 |
| --- | --- | --- |
| 隐含波动率 | ATM IV、IV Rank、IV Percentile | 市场预期波动强弱 |
| 波动率风险溢价 | IV - RV、IV/RV | 期权定价是否偏贵 |
| 偏度 | Put skew、Call skew、25D RR、25D BF | 下行保护或上行追涨需求 |
| 期限结构 | 近月 IV - 远月 IV | 短期事件风险或远期风险定价 |
| 期权持仓 | PCR volume、PCR OI、ATM 附近 OI 集中 | 多空情绪和关键价位拥挤 |
| 隐含波动区间 | straddle implied move | 市场隐含的未来波动范围 |

### 3. 期货-期权联动规则

期权模块不要直接给“买卖建议”，而应作为信号过滤器。

#### 规则 A：趋势确认过滤

```
如果：
  futures_multi_factor_signal = long
且：
  OI pressure = long
且：
  option_skew 不显示明显下行保护升温
且：
  IV rank 未处于极端高位
则：
  long_signal_confidence 上调
```

#### 规则 B：趋势风险预警

```
如果：
  期货价格上涨
但：
  IV 同步快速上升
且：
  put skew 变陡
且：
  PCR OI 上升
则：
  标记为“上涨中的风险对冲增强”
  多头信号置信度下调
```

#### 规则 C：突破前压缩

```
如果：
  realized volatility 下降
且：
  ATM IV 处于低分位
且：
  期限结构稳定
且：
  价格接近区间边界
则：
  标记为“低波动压缩后的突破观察”
```

#### 规则 D：临近到期扰动

```
如果：
  days_to_maturity 较低
且：
  ATM 附近期权 OI 集中
且：
  期货价格靠近高持仓行权价
则：
  标记为“到期扰动观察”
```

这里需要注意：基于持仓量估算 gamma 暴露只能作为 proxy，不能等同于真实做市商库存，也不能直接推导盘中支撑压力。

### 4. 期权模块落地顺序

| 阶段 | 模块 | 目标 |
| --- | --- | --- |
| R30 | option raw/core 接入 | 解析期权代码、行权价、C/P、标的月份 |
| R31 | IV/Greeks/surface | 计算 ATM IV、偏度、期限结构、流动性标签 |
| R32 | option factor diagnostics | 研究 IV、skew、PCR 对未来收益和波动的解释力 |
| R33 | futures-option linkage | 把期权因子作为 futures signal 的置信度过滤器 |
| R34 | option chart pack | 输出 IV 曲线、偏度、PCR、OI 集中图 |
| R35 | option brief section | 接入 latest signal-only brief 和 weekly review |

由于棉花期权为美式行权，初期可以用统一近似模型生成可比 IV/Greek 序列，但必须给深实值、临近到期、低流动性合约打质量标签，不能把模型 Greek 当成精确风险暴露。棉花期权合约页面明确其行权方式为美式。([郑州商品交易所](https://www.czce.com.cn/cn/sspz/mh/bzhy/qqhy/H077002003001002index_1.htm))

---

## 七、多周期研判体系设计

你想要“不同周期的研判能力”，我建议不要简单做 5 日、20 日、60 日均线，而是构建一个**horizon-aware signal matrix**。

### 1. 周期分层

| 周期 | 目标 | 核心问题 | 主要信号 |
| --- | --- | --- | --- |
| T+1 / 1-3D | 次日观察 | 今天的结构变化明天是否延续？ | 日内涨跌、持仓变化、成交活跃、期权短端 IV |
| 3-5D | 短线确认 | 修复还是假突破？ | 短动量、OI pressure、近月曲线变化 |
| 10-20D | 波段趋势 | 是否形成可持续方向？ | momentum、carry、curve slope、趋势阶段 |
| 40-60D | 中期结构 | 是否处于产业或季节性结构阶段？ | 基差、仓单、库存、进口、外盘、宏观 |
| 90D+ | 季节/年度 | 当前价格是否处于年度结构性位置？ | 季节性、种植/收购/消费周期、长期分位 |

### 2. 信号矩阵

新增一张研究表：

```
data/research/CF/signal_matrix_daily.parquet
```

字段建议：

| 字段 | 含义 |
| --- | --- |
| trade_date | 交易日 |
| horizon | 1D / 3D / 5D / 10D / 20D / 40D |
| price_signal | 价格方向 |
| momentum_signal | 动量方向 |
| carry_signal | carry 方向 |
| curve_signal | 曲线方向 |
| oi_signal | 持仓压力方向 |
| option_signal | 期权方向或风险提示 |
| regime_state | 趋势/震荡/高波/低波 |
| trend_phase | S0-S4 |
| composite_score | 综合分数 |
| confidence_score | 置信度 |
| warning_flags | 风险标签 |
| evidence_level | 历史证据强弱 |

### 3. 研究输出不再只有 long/short

建议信号输出从现在的：

```
long / short / neutral
```

升级为：

```
direction: long / short / neutral
phase: 起点观察 / 趋势中 / 衰竭观察 / 终点确认
confidence: low / medium / high
evidence: weak / moderate / strong
action_type: 观察 / 验证 / 风险提示
```

这会更适合你做公众号研究，因为文章可以呈现“证据链”，而不是给一个容易被误解为交易指令的结论。

---

## 八、滚动验证与参数研究设计

当前最大问题不是没有因子，而是因子还没有被充分校准。下一阶段应建立：

```
R26_rolling_validation_engine
R27_parameter_threshold_lab
```

### 1. 滚动窗口

建议按两种方式验证。

第一种是年度滚动：

```
2021-2022
2022-2023
2023-2024
2024-2025
2025-2026
```

第二种是 walk-forward：

```
train: 2021-2023
test: 2024

train: 2021-2024
test: 2025

train: 2021-2025
test: 2026
```

### 2. 验证指标

| 维度 | 指标 |
| --- | --- |
| 方向解释力 | IC、Rank IC、方向准确率 |
| 收益表现 | mean return、median return、hit rate |
| 成本敏感性 | no cost / normal cost / conservative cost |
| 稳定性 | 年度分组、月份分组、主力/非主力分组 |
| 信号质量 | signal decay、turnover、holding period |
| 趋势识别 | 起点 precision、终点 precision、false positive |
| 风险 | 最大回撤、极端亏损日、换月期表现 |
| 可发布性 | 是否能形成稳定叙述，而非过拟合参数 |

### 3. 参数研究范围

| 因子 | 参数 |
| --- | --- |
| momentum | 5 / 10 / 20 / 40 日 |
| carry | 绝对阈值、滚动分位数、近远月组合 |
| curve slope | 近-主、远-主、主-远、全曲线 PCA |
| OI pressure | 单日变化、3 日变化、5 日变化、标准化变化 |
| option IV | IV rank lookback 60 / 120 / 250 |
| option skew | ATM 附近、25D、固定 moneyness |
| 多因子 | 等权、方向投票、IC 加权、regime 加权 |
| 趋势状态 | 突破窗口、回撤阈值、确认天数 |

### 4. 防止过拟合的原则

参数研究不要选“历史收益最高”的组合，而应优先选择：

1. 跨年度稳定；
2. 成本后不崩；
3. 样本量足够；
4. 解释逻辑清晰；
5. 在不同市场状态下表现可解释；
6. 参数轻微变化时结果不剧烈反转。

---

## 九、数据自动日更与审计设计

你当前的可靠路径是：人工或浏览器获取年度文件，放入 `data/incoming/CF/history/`，再由脚本接入 raw/core，并可选运行研究窗口。这个路径应该保留为主路径，因为审计材料已指出，直接自动下载郑商所年度 ZIP 存在网站拦截风险。

后续不要急于追求“全自动爬虫”，更应该做**稳健日更制度**。

### 1. 建议日更流程

```
Step 1  incoming watcher 检查新文件
Step 2  raw snapshot 留存原始文件
Step 3  schema validation 检查字段口径
Step 4  core updater 增量更新核心表
Step 5  calendar updater 刷新交易日历
Step 6  QA report 检查缺失、重复、异常
Step 7  latest signal-only brief 生成最新观察报告
Step 8  chart pack 生成图表
Step 9  publish pack 生成公众号素材
Step 10 run manifest 固化本次运行记录
```

### 2. 新增日更产物

```
runs/daily/CF/YYYYMMDD/
  ├─ manifest.json
  ├─ data_quality_report.md
  ├─ latest_signal_brief.md
  ├─ latest_signal_brief.html
  ├─ charts/
  │   ├─ price_oi_main.png
  │   ├─ term_structure.png
  │   ├─ factor_dashboard.png
  │   ├─ trend_phase.png
  │   └─ option_dashboard.png
  ├─ publish/
  │   ├─ wechat_article.md
  │   ├─ wechat_summary.txt
  │   └─ image_pack/
  └─ logs/
      └─ pipeline.json
```

### 3. 日更 QA 规则

| 检查项 | 规则 |
| --- | --- |
| 最新日期 | core 最新日期必须等于输入文件最新交易日 |
| 重复数据 | 同一 trade_date + contract 不得重复 |
| 合约合法性 | 合约月份必须符合品种规则 |
| 主力识别 | 成交量、持仓量、主力切换需要可解释 |
| 价格合法 | 结算价、收盘价、最高、最低不得异常 |
| 持仓合法 | 持仓量不得为负，异常跳变需要 warning |
| 期权链完整性 | 同一标的月份下 C/P、strike 覆盖需要检查 |
| 期权流动性 | 低成交、低持仓、深虚值合约不得直接用于核心信号 |
| 日历完整性 | 推导日历和官方日历不一致时必须 HUMAN_REVIEW_REQUIRED |

---

## 十、可视化与公众号发布设计

你需要的不是普通回测图，而是**研究叙事型图表**。公众号读者更关心“结构是否清楚、证据链是否可信、结论是否有边界”。

### 1. 每日图表包

| 图表 | 用途 |
| --- | --- |
| 主力价格 + 持仓量 | 判断价格上涨/下跌是否有持仓确认 |
| 合约期限结构柱状图 | 展示近月、主力、远月升贴水 |
| 因子方向热力图 | 一眼看出 momentum/carry/curve/OI 是否一致 |
| 多周期信号矩阵 | 展示 1D/3D/5D/20D 信号差异 |
| 趋势阶段仪表盘 | 展示 S0-S4 状态 |
| 滚动 IC 图 | 展示因子近期有效性 |
| 成本敏感性图 | 展示信号是否经得起交易成本 |
| 期权 IV 曲线 | 展示隐含波动率结构 |
| 期权偏度图 | 展示上行/下行风险定价 |
| 期权持仓分布图 | 展示关键行权价拥挤区 |

### 2. 公众号文章模板

```
标题：
郑棉 CF 日度研究：远月结构仍强，趋势确认还需持仓与动量共振

摘要：
今日 CF 主力合约延续修复，期限结构维持远月升水。模型层面，carry、curve slope、OI pressure 偏多，但短周期 momentum 尚未完全确认。当前更接近“趋势起点观察”，不宜直接定义为强趋势阶段。

一、今日市场事实
二、期限结构变化
三、四因子与多周期信号
四、趋势阶段判断
五、期权市场观察
六、历史窗口证据
七、明日重点观察
八、研究边界
```

### 3. 发布包设计

新增：

```
src/reporting/wechat_pack.py
templates/wechat/cf_daily_article.md.j2
templates/wechat/cf_weekly_review.md.j2
```

输出：

```
publish/wechat_article.md
publish/wechat_summary_300w.txt
publish/chart_pack.zip
publish/data_asof.json
```

每篇文章必须自动写明：

```
数据截至：YYYY-MM-DD
研究品种：CF
报告类型：latest signal-only / validated research
是否包含未来收益验证：是/否
是否存在人工复核项：是/否
```

这样可以降低研究误读风险。

---

## 十一、多品种扩展设计

多品种扩展不能直接复制 CF 的参数。应该先抽象框架，再逐品种通过 expansion gate。

### 1. product_config 抽象

建议建立：

```
configs/products/CF.yml
configs/products/SR.yml
configs/products/TA.yml
configs/products/OI.yml
```

以 CF 为例：

```yaml
product_id: CF
exchange: CZCE
name_cn: 棉花
asset_class: commodity_futures
frequency: daily

contract:
  code: CF
  months: [1, 3, 5, 7, 9, 11]
  unit: 5
  quote_unit: CNY_per_ton
  tick_size: 5

option:
  enabled: true
  option_code_pattern: "CF-{month}-{C/P}-{strike}"
  quote_unit: CNY_per_ton
  tick_size: 1
  exercise_style: american

research:
  horizons: [1, 3, 5, 10, 20, 40]
  default_factors:
    - momentum
    - carry
    - curve_slope
    - oi_pressure
  optional_factors:
    - option_iv
    - option_skew
    - pcr
    - basis
    - warehouse_receipt

risk:
  human_review_required:
    - contract_rule
    - calendar
    - cost_model
    - factor_threshold
    - option_liquidity
```

### 2. expansion gate

每个新品种必须通过六道门：

| Gate | 要求 |
| --- | --- |
| G1 数据接入 | raw/core 标准表可生成 |
| G2 合约规则 | 合约月份、单位、tick、最后交易日通过人工复核 |
| G3 mapping | chain/trade mapping、连续价格、roll diagnostics 可用 |
| G4 因子可用 | 基础因子能跑通，且无明显字段错配 |
| G5 历史验证 | 至少完成滚动窗口验证 |
| G6 报告输出 | latest brief 和 weekly review 可生成 |

### 3. 品种扩展顺序

我不建议马上扩到很多品种。更合理的路径是：

```
第一批：同交易所、同数据结构、已有期权的品种
第二批：产业链相关品种
第三批：跨交易所品种
第四批：外盘联动品种
```

CF 之后，可以优先选择一个“同交易所 + 有期权 + 日频数据结构相似”的品种做模板验证。不要一开始做 5-10 个品种，否则数据规则、合约规则、成本模型和流动性差异会拖慢主线。

---

## 十二、后续研究方向衍生设计

我建议你把研究方向分成四条主线。

### 主线 A：价格结构研究

目标是回答：

> 当前价格变化是趋势、修复、挤仓、换月扰动，还是产业链重估？
>

研究模块：

```
A1 多周期 momentum
A2 主力换月前后收益特征
A3 期限结构斜率
A4 曲线形态 PCA
A5 价差均值回归与趋势切换
A6 合约间强弱轮动
```

### 主线 B：持仓与流动性研究

目标是回答：

> 价格变化背后是否有资金和仓位确认？
>

研究模块：

```
B1 OI pressure 改良版
B2 成交/持仓比
B3 主力换月压力
B4 上涨增仓、上涨减仓、下跌增仓、下跌减仓状态分类
B5 持仓异常变化事件研究
B6 成交活跃度过滤
```

### 主线 C：期权风险定价研究

目标是回答：

> 期权市场是否在给出波动、方向或风险溢价信号？
>

研究模块：

```
C1 ATM IV 与未来 RV
C2 IV Rank 与突破/回撤概率
C3 Put skew 与下行风险
C4 Call skew 与上行追涨情绪
C5 PCR 与期货方向
C6 期权持仓集中与到期扰动
C7 低波动压缩后的方向突破
```

### 主线 D：产业与基本面研究

目标是回答：

> 价格结构是否有产业链证据支持？
>

研究模块：

```
D1 现货价格与基差
D2 仓单与有效预报
D3 进口利润与内外价差
D4 纺织开工与下游订单
D5 库存周期
D6 季节性窗口
D7 政策和报告事件
```

这些主线最终应该汇总成一个统一结论：

```
市场事实：偏强 / 偏弱 / 中性
模型信号：偏多 / 偏空 / 分歧
趋势阶段：起点观察 / 趋势中 / 衰竭观察
期权验证：确认 / 背离 / 风险预警
历史证据：强 / 中 / 弱
发布结论：观察为主 / 证据增强 / 风险升高
```

---

## 十三、建议的后续任务排期顺序

我建议你按下面顺序推进，不要同时开太多分支。

| 顺序 | 任务 | 目的 | 优先级 |
| --- | --- | --- | --- |
| 1 | R23 latest signal-only brief | 解决最新日无法出报告的问题 | 最高 |
| 2 | R24 trend phase engine | 把“反弹还是趋势”结构化 | 最高 |
| 3 | R25 中文报告与公众号 publish pack | 让研究成果可直接发布 | 高 |
| 4 | R26 rolling validation | 检验因子跨年度稳定性 | 高 |
| 5 | R27 threshold lab | 从方向信号升级到强弱信号 | 高 |
| 6 | R28 daily manifest & QA monitor | 固化日更审计 | 高 |
| 7 | R29 visualization dashboard | 增强图表表达 | 中高 |
| 8 | R30 option raw/core | 接入棉花期权数据 | 高 |
| 9 | R31 option IV/surface | 构建期权波动率研究层 | 高 |
| 10 | R32 futures-option linkage | 用期权过滤期货信号 | 高 |
| 11 | R33 fundamental connector | 增加产业链解释力 | 中高 |
| 12 | R34 product expansion kit | 为多品种扩展做抽象 | 中 |
| 13 | R35 first non-CF pilot | 选择一个新品种试点 | 中 |

---

## 十四、最应该马上启动的工程包

我建议下一步直接做这个组合包：

```
CF Research Workbench vNext Pack 01

包含：
1. latest signal-only brief
2. trend phase engine
3. Chinese report template
4. publish chart pack
5. daily run manifest
```

### 具体工程清单

```
新增：
src/research/latest_signal_brief.py
src/research/trend_phase.py
src/reporting/cn_templates.py
src/reporting/wechat_pack.py
src/visualization/factor_dashboard.py
src/visualization/term_structure.py
src/visualization/trend_phase_chart.py

新增配置：
configs/research/CF_latest_signal.yml
configs/research/CF_trend_phase.yml
configs/reporting/wechat.yml

新增模板：
templates/reports/latest_signal_brief_cn.md.j2
templates/reports/validated_research_brief_cn.md.j2
templates/wechat/cf_daily_article.md.j2

新增脚本：
scripts/run_cf_latest_signal_brief.ps1
scripts/run_cf_daily_publish_pack.ps1

新增测试：
tests/research/test_latest_signal_brief.py
tests/research/test_trend_phase.py
tests/reporting/test_wechat_pack.py
```

### 最小可用输出

```
runs/daily/CF/YYYYMMDD/latest_signal_brief.md
runs/daily/CF/YYYYMMDD/charts/factor_dashboard.png
runs/daily/CF/YYYYMMDD/charts/term_structure.png
runs/daily/CF/YYYYMMDD/charts/trend_phase.png
runs/daily/CF/YYYYMMDD/publish/wechat_article.md
runs/daily/CF/YYYYMMDD/manifest.json
```

---

## 十五、我的最终判断

你的项目当前已经完成“研究工作台 MVP”，下一步真正有价值的升级不是做得更像交易系统，而是做得更像一个**有证据链的研究生产系统**。

最优路线是：

```
先补最新日信号报告
再把趋势阶段识别纳入主流程
再做滚动验证和阈值校准
再接入期权波动率与情绪过滤
再做公众号发布包
最后再扩展到其他品种
```

期权模块值得做，但应定位为：

> **期货信号的验证器、过滤器和风险预警器，而不是一开始就做期权交易策略。**
>

多品种扩展也值得做，但前提是：

> **先把 CF 的 product_config、factor registry、report template、expansion gate 抽象出来，再复制到其他品种。**
>

这样推进，系统会从“能跑一次研究管线”，升级为“每天能生产可审计、可解释、可发布、可扩展的研究结论”。
