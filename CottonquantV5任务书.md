# CottonquantV5任务书：从"研究观察工作台"升级为"策略问责的研究系统"

本任务书是 `CottonquantV4任务书.md` 的后继执行文件，面向工程执行方（Codex）。定位仍然是研究系统设计，不构成投资建议或交易指令。所有新增模块延续本仓库既有纪律：raw/core/research 分层、T 日结算后信号 T+1 执行、无未来函数、可审计、中文报告、显式 HUMAN_REVIEW_REQUIRED。

模块编号从 **R86** 起顺延（当前仓库主线已推进至 R85）。若实际仓库中某编号已被占用，顺延编号并在 `docs/RESEARCH_WORKBENCH_ROADMAP.md` 中注明映射。

---

## 一、阶段判断：V4 之后系统所处的位置

V4 任务书发布后，R23-R85 主线已基本落地：最新日 signal-only brief、S0-S4 趋势阶段（R24 与 R76 v2 两套判定）、1/3/5/10/20/40D 信号矩阵、期权 proxy 与期货-期权联动、历史证据与事件解释链、双价格状态、全链持仓分解、竞争风险模型、会员持仓 2021-2026 回填、行权价 OI 结构、日更/周更双车道与 R63 数据连续性审计。质量基线为 pytest 全过 + ruff 通过。

但系统存在三个结构性问题，V5 必须正面回答：

### 问题 1：单品种统计功效接近耗尽

CF 日频 core 数据约 1,340 个交易日。主观察周期 20D 下，不重叠的独立观测仅约 65 个；S1→S2 一类趋势转换事件五年半内可辨识样本约二三十次。这解释了为什么 R37 阈值候选长期 watch-only、最新日报置信度长期 low。继续在 CF 单品种上加研究模块，边际产出递减。

### 问题 2：研究产出从未折算为策略净值

系统的终点是"研究观察"（方向、阶段、置信度），刻意不给交易指令。该边界应保留，但它导致所有研究成果没有一个统一的可证伪度量。判断一个模块是否有用，目前依赖叙事合理性，而不是"它是否改善了一条无未来函数的净值曲线"。

### 问题 3：模块必要性缺乏统一判据

R83 会员持仓、R84 行权价 OI 墙等模块与外部平台（行情终端、持仓数据网站）高度同质。做得再好，作为展示功能的必要性也接近零。它们的真实价值只能是：作为因子/过滤器候选，在可复核的检验中证明对策略有增量。

### 定位升级

> V5 的系统定位：**strategy-accountable research workbench（策略问责的研究工作台）**。
>
> 所有研究模块最终以"是否改善策略影子净值"接受检验；影子台账每日前向运行、无未来函数、不下单。

---

## 二、总目标与模块必要性判据

### 1. 总目标

在不破坏现有研究边界（不下单、不接实盘、不给交易指令）的前提下，新增三层能力：

1. **策略对象层**：把现有信号组装成版本化、可复核的策略规格（spec），并建立"笨基准"；
2. **影子台账层**：日更管线每天写出策略目标仓位与影子净值，形成前向可证伪记录；
3. **薄扩品种层**：用同一套因子/策略模板扩展 3-4 个 CZCE 品种，为统计功效与组合分散服务。

### 2. 模块必要性三分类判据（此后所有模块立项必须先归类）

| 类别 | 判据 | 投资策略 |
| --- | --- | --- |
| SIGNAL | 改变策略仓位方向或开平 | 优先投入 |
| RISK | 改变仓位大小、风险敞口或止损 | 优先投入 |
| CONTEXT | 只改变研究叙事，不改变仓位 | 冻结新增，存量降级维护 |

### 3. 现有模块按新判据的重新分类

| 模块 | 分类 | V5 处置 |
| --- | --- | --- |
| 四因子 + 信号矩阵（R11-R14, R35） | SIGNAL | 作为策略输入，参数锁定 |
| 趋势阶段 R24 / R76 v2 | SIGNAL 候选 | 进入 R89 门控检验，须打败笨基准 |
| 期权过滤（R48/R49/R75） | SIGNAL 候选 | 进入 R92 overlay A/B 检验 |
| carry / curve（R12/R13） | SIGNAL 候选 | 进入 R89 倾斜系数检验 |
| 会员持仓（R83/R85） | CONTEXT → SIGNAL 候选 | **研究深挖冻结**，数据摄入保留；进入 R92 检验后再定去留 |
| 行权价 OI 墙（R84） | CONTEXT → SIGNAL 候选 | 同上 |
| 事件解释 / 历史叙事（R42/R55/R71） | CONTEXT | 冻结新增，只随周报维护 |
| 基本面接口（R51/R53/R54） | CONTEXT | 保持手工占位，不投研发 |
| 公众号发布线（R45/R57） | CONTEXT | 继续暂停 |
| 数据连续性审计（R63） | 基础设施 | 原样保留，薄扩品种复用 |

---

## 三、vNext 架构

### 1. 层级：在现有四层之上只加不改

```text
现有（不改动行为）：
  raw snapshot → core facts → research（因子/矩阵/阶段/期权）→ reports/runs

V5 新增：
  策略规格层  strategy spec registry     （版本化 YAML + changelog）
  策略引擎层  strategy engine            （baseline / candidate，共用记账内核）
  影子台账层  shadow ledger              （日更前向记录，无未来函数）
  组合层      portfolio shadow           （薄扩品种后的等风险加总）
  评估层      strategy evaluation        （策略级 walk-forward + overlay A/B）
  治理层      iteration budget / gates v2（参数预登记、变更审计、扩展门分层）
```

### 2. 新增目录与产物约定

```text
src/cotton_factor/strategy/
  __init__.py
  spec.py                  # 规格加载与校验（pydantic）
  registry.py              # 规格注册表与 changelog
  signals.py               # 从 research 产物读取信号的适配层（只读）
  sizing.py                # 波动率目标手数
  accounting.py            # T+1 记账内核（唯一实现，baseline/candidate 共用）
  baseline_tsmom.py        # R87 笨基准
  phase_gated.py           # R89 候选策略
  shadow_ledger.py         # R90 每日影子台账
  evaluation.py            # R88 策略级滚动验证
  overlay_test.py          # R92 增量价值检验
  portfolio.py             # R98 组合影子

configs/strategy/
  CF_tsmom_v0.yaml
  CF_phase_gated_v0.yaml
  strategy_registry.yaml   # 全部 spec 的注册与状态（baseline/candidate/frozen）

data/strategy/{PRODUCT}/
  {STRATEGY_ID}_{VERSION}_backtest_daily.parquet
  {STRATEGY_ID}_shadow_ledger.parquet        # 追加式，前向唯一真相
reports/strategy/
runs/daily/{PRODUCT}/{date}/strategy_shadow.json / strategy_shadow.md
runs/daily/PORTFOLIO/{date}/portfolio_shadow.json
docs/STRATEGY_SPEC.md  docs/STRATEGY_SHADOW_LEDGER.md  docs/STRATEGY_EVALUATION.md
tests/unit/test_strategy_*.py
```

### 3. 硬性纪律（继承并加强）

1. 策略信号只允许读取 T 日及以前可观察的 research 产物；**engine 层必须显式断言输入表不含 `forward_return`/`fwd_ret` 类字段**，违反即抛异常（单测覆盖）。
2. 连续价格仍然只作信号对象；记账 PnL 必须走 trade_mapping 的真实合约结算价。
3. 换月日视为旧合约平仓 + 新合约开仓，计两笔成本，换月原因沿用 chain/trade mapping 的可见理由。
4. 影子台账是追加式的：历史行一经写入不得修改；重跑当日只允许覆盖当日行并在 manifest 记录覆盖原因。
5. 所有新产物带 run_id、input snapshot、warning CSV、中文 Markdown 报告与 manifest，与现有产物同规格。
6. 不引入新依赖（现有 pandas/polars/pyarrow/duckdb/pydantic/typer/jinja2 足够）；如确需新增，先写入 `docs/DEPENDENCIES.md`。

---

## 四、Lane A：策略对象主线（最高优先级，R86-R93）

### R86 方向文件收口与策略规格注册表

**目的**：让仓库的"宪法文件"与 V5 定位一致，否则后续任务与 AGENTS.md 现行 "CF only / 不做 SR-AP ingest" 条款自相冲突；同时建立策略规格的 schema 与注册表。

**工程产物**：

```text
修订 AGENTS.md：
  - Mission 增加 strategy-accountable 定位与影子台账边界（不下单、不接实盘）
  - Strategic Scope 改为 "CF 深研究底盘 + CZCE 薄扩品种（仅 core/因子/矩阵/策略模板）"
  - Do-not-prioritize 保留 OMS/实盘/分钟级，明确新增：不做自动下单、不做实时推送
修订 docs/PROJECT_DIRECTION.md：增加 V5 定位一节
修订 docs/RESEARCH_WORKBENCH_ROADMAP.md：新增 V5 progress 小节（R86 起逐条打勾）
新增 src/cotton_factor/strategy/spec.py + registry.py
新增 configs/strategy/strategy_registry.yaml
新增 docs/STRATEGY_SPEC.md
新增 tests/unit/test_strategy_spec.py
```

**spec 必备字段**（pydantic 校验，缺一即 fail）：

`strategy_id, version, status(baseline|candidate|frozen), product, signal_object(继承连续价格 id), signal_windows, entry_rule, exit_rule, gate_rules, sizing(model, capital_base, target_vol, vol_window, vol_floor, max_lots), execution(T+1_settle), costs(scenario 名单), data_dependencies(路径清单), forbidden_inputs(必须含 forward_return), created_at, changelog[]`

**验收标准**：

| 验收项 | 标准 |
| --- | --- |
| 文档一致 | AGENTS.md / PROJECT_DIRECTION / roadmap 三处修订完成且相互无矛盾 |
| 规格校验 | 缺字段、含禁止输入路径的 spec 加载即报错，有单测 |
| 注册表 | registry 能列出全部 spec 与状态，重复 strategy_id+version 报错 |

---

### R87 笨基准策略引擎（baseline_tsmom_v0）

**目的**：建立所有后续模块必须打败的基准。刻意简单：时间序列动量 + 波动率目标仓位，不含任何本仓库特色模块。

**规则定义**（写死为 `CF_tsmom_v0.yaml`，全文见第六章）：

```text
信号价格   P_c(t)：现有连续价格（settle 口径，signal object）
方向       dir(t) = sign( P_c(t)/P_c(t-20) - 1 )；恰为 0 时沿用前一日方向
年化波动   sigma(t) = std( ln P_c(s)/P_c(s-1), s ∈ [t-19, t] ) * sqrt(252)
           sigma_eff(t) = max(sigma(t), 0.05)
目标手数   N(t) = floor( capital_base * target_vol / sigma_eff(t) / ( S_main(t) * unit ) )
           N(t) = clip(N(t), 0, max_lots)
目标仓位   target_pos(t) = dir(t) * N(t)
默认参数   capital_base = 1,000,000 CNY（研究记账资本，非真实资金）
           target_vol = 0.12；vol_window = 20；vol_floor = 0.05
           unit = 5 吨/手（CF）；max_lots = 20
```

**记账内核**（`accounting.py`，唯一实现，全部策略共用；与既有 `backtest/engine.py` 的 T+1 约束对齐但不修改旧引擎）：

```text
pos(t) 于 t 日结算后确定，对 t→t+1 的价格变动生效：
  pnl_gross(t) = pos(t-1) * ( S(t) - S(t-1) ) * unit        # S 为 trade_mapping 真实主力合约结算价
  换月日：pnl 按新旧合约各自结算价分段计算
  cost(t) = |pos(t) - pos(t-1)| * S(t) * unit * c_bps
            + 换月日额外的平旧/开新双边成本
  nav(t) = nav(t-1) + pnl_gross(t) - cost(t)
成本情景沿用现有三档：no_cost=0 / normal_cost=5bps / conservative_cost=10bps（单边）
```

**工程产物**：

```text
src/cotton_factor/strategy/{signals,sizing,accounting,baseline_tsmom}.py
configs/strategy/CF_tsmom_v0.yaml
CLI：research 之外新增顶层子命令组 strategy：
  py -3.12 -m cotton_factor.cli.main strategy run-backtest --spec configs/strategy/CF_tsmom_v0.yaml --start 2021-01-04 --end <latest>
输出：data/strategy/CF/CF_tsmom_v0_backtest_daily.parquet
      reports/strategy/CF_tsmom_v0_backtest.md/.json + manifest + warning CSV
tests/unit/test_strategy_baseline.py（含 no-look-ahead 断言、换月双边成本断言、金额可复算 fixture）
```

**验收标准**：

| 验收项 | 标准 |
| --- | --- |
| 无未来函数 | 把输入截断到 t 日重算，pos(≤t) 与全量回算完全一致（单测） |
| 换月正确 | 换月日两笔成本、分段 pnl，有 golden fixture 数字级校验 |
| 三档成本 | 三档净值单调递减，成本拖累字段可对账 |
| 报告 | 中文报告含年化收益/波动/Sharpe/最大回撤/换手/在场时间/逐年表 |

---

### R88 策略级滚动验证（walk-forward）

**目的**：把 R36 的滚动窗口机制升格到策略层：评价对象从因子 IC 换成净值指标。

**规则**：

- 窗口沿用现有惯例：2021-2022 / 2022-2023 / 2023-2024 / 2024-2025 / 2025-2026 年度滚动 + 全窗；
- 指标集（每窗口 × 每成本档）：年化收益、年化波动、Sharpe（rf=0）、最大回撤、Calmar、日胜率、每笔交易胜率、平均持仓天数、年换手（手数与名义额两口径）、成本拖累（gross−net）、在场时间比、**按 S0-S4 阶段的 PnL 归因**（阶段标签用 R76 v2，缺失回退 R24；此归因是后验描述，不回流信号）；
- 参数不做任何窗口内重选（walk-forward 只验证，不优化）。

**工程产物**：

```text
src/cotton_factor/strategy/evaluation.py
CLI：strategy evaluate --spec ... --windows 2021-2022,...,2025-2026
输出：data/strategy/CF/{id}_{ver}_evaluation_window.parquet
      reports/strategy/{id}_{ver}_evaluation.md/.json
docs/STRATEGY_EVALUATION.md
tests/unit/test_strategy_evaluation.py
```

**验收标准**：

| 验收项 | 标准 |
| --- | --- |
| 指标可复算 | fixture 上全部指标手工数字可对上 |
| 逐窗输出 | 每窗口 × 每成本档一行，缺窗显式 WARNING 而非静默跳过 |
| 阶段归因 | 各阶段 pnl 之和等于总 pnl（对账断言） |

---

### R89 候选策略 v0（phase_gated_v0）与基准对决

**目的**：本仓库全部特色模块（趋势阶段、carry/curve、期权过滤）第一次接受"是否打败笨基准"的审判。

**规则定义**（`CF_phase_gated_v0.yaml`，系数 ex-ante 固定，全文见第六章）：

```text
base_pos(t) = R87 baseline 的 target_pos(t)
阶段门控 g_phase：S2=1.0；S1=0.5；S0=0；S3=0.5 且只减不加（不得高于前一日 |pos|）；S4=0
  阶段方向与 dir(t) 相反时 g_phase=0
  阶段源：R76 v2（trend_phase_v2 日表）；当日缺失回退 R24；两者都缺 → g_phase=0 并记 WARNING
carry 倾斜 g_carry：carry 信号与 dir 同向=1.0；反向=0.75；缺失=1.0
期权否决 g_opt：主周期 option_signal ∈ {diverge_short, diverge_long}（与 dir 反向）或
  volatility_risk 时 =0.5；缺失或 not_connected=1.0
target_pos(t) = round( base_pos(t) * g_phase * g_carry * g_opt )
```

**对决规则（ex-ante 固定，不许赛后改）**：

- 同窗、同成本档与 R87 对比；
- **晋级线**：5 个年度窗口中 ≥4 个 Sharpe 不低于基准，且全窗 conservative_cost 档 Sharpe ≥ 基准 + 0.10；
- 达线 → candidate 保留并进入 R90 双轨影子；未达线 → spec 标记 `frozen`，结论写入报告，**不得当场调参重跑**（调参属于下一季度迭代预算，见第七章）。

**工程产物**：

```text
src/cotton_factor/strategy/phase_gated.py
configs/strategy/CF_phase_gated_v0.yaml
CLI：strategy compare --spec-a CF_tsmom_v0 --spec-b CF_phase_gated_v0 --windows ...
输出：reports/strategy/CF_phase_gated_v0_vs_baseline.md/.json（含逐窗对比表与晋级判定）
tests/unit/test_strategy_phase_gated.py（门控系数逐条 fixture）
```

**验收标准**：

| 验收项 | 标准 |
| --- | --- |
| 门控正确 | 每条 g 规则有独立 fixture；S3 只减不加有专门断言 |
| 判定自动 | 报告自动输出 PASS/FROZEN 结论与依据行 |
| 输入合规 | 仅读 research 产物的 T 日可观察列，断言无 forward 列 |

---

### R90 每日影子台账（核心交付）

**目的**：从此每天的研究对一条前向净值曲线负责。这是 V5 最重要的单一产物。

**规则**：

- 日更管线在 latest brief 之后运行：对 registry 中全部 `status ∈ {baseline, candidate}` 的策略各写一行台账；
- 只用 T 日结算后信息计算 target_pos(t)，T+1 生效（记账内核同 R87）；
- 台账 parquet 为追加式；同一 (strategy_id, trade_date) 重跑覆盖须在 manifest 记录 `OVERWRITE_REASON`；
- 影子起始 nav = 1,000,000（每策略独立记账）；
- 台账行字段：

```text
trade_date, product, strategy_id, spec_version, run_id,
dir, sigma, target_lots, target_pos, prev_pos, executed_change(T+1 生效标记),
main_contract, settle, entry_date, holding_days,
pnl_gross, cost, pnl_net, nav, drawdown, high_watermark,
phase_code_used, gate_multipliers(json), signals_snapshot(json),
cost_scenario, warnings, input_snapshot_ids
```

**工程产物**：

```text
src/cotton_factor/strategy/shadow_ledger.py
CLI：strategy run-shadow --date <trade_date>（幂等，可回补缺日）
输出：data/strategy/CF/{id}_shadow_ledger.parquet
      runs/daily/CF/{date}/strategy_shadow.json / strategy_shadow.md（全部策略汇总）
scripts/update_cf_latest_research.ps1 新增开关 -RunStrategyShadow，**默认日更包含**
docs/STRATEGY_SHADOW_LEDGER.md
tests/unit/test_strategy_shadow_ledger.py
```

**警示语（写入每份 md/json）**：`影子台账为研究仿真，前向记录、无未来函数，不构成交易指令；nav 为记账值非真实资金`。

**验收标准**：

| 验收项 | 标准 |
| --- | --- |
| 幂等回补 | 对历史某日重跑，其余行 bit 级不变 |
| 前向一致 | 逐日运行 60 个交易日的台账与一次性回算同区间完全一致（单测用 fixture 模拟） |
| 日更集成 | ps1 默认路径产出 strategy_shadow.json，失败不阻断 brief 主链但记 WARNING |
| 对账 | nav 变化 = pnl_net 累计，误差为 0（整数金额断言） |

---

### R91 周度策略审计（接入 weekly lane）

**目的**：把影子表现纳入每周例行审计，与 R59 周报同节奏。

**内容**：本周各策略影子收益、nav、回撤、与基准差值、异常（超额换手、连续 WARNING、阶段与仓位长期矛盾）、下周复核项。输出 `reports/strategy/CF_{asof}_weekly_strategy_audit.md/.json`，`-RunWeeklyResearchPack` 自动包含。R59 周报增加一节引用该审计结论。

**验收**：周包一条命令产出；审计包含"本周影子结论不可回改历史"的边界声明；有单测。

---

### R92 增量价值检验框架（overlay A/B）——会员持仓等模块的审判台

**目的**：用统一机械程序回答"这个功能有没有必要深挖"。

**规则（ex-ante 固定）**：

- overlay 定义：在指定 base spec 上仅增加一条门控/过滤规则的增量 spec；
- 初始 overlay 清单（各自一个 yaml，规则先写死再检验）：
  1. `ovl_option_veto`：即 R89 的 g_opt 单独拆出，作用于 baseline；
  2. `ovl_member_position`：T 日 Top20 净多变化方向与 dir 同向→1.0，反向→0.5，缺失→1.0（数据源：现有 `core_member_position_daily.parquet`，**只做这一条规则，不新增研究深挖**）；
  3. `ovl_strike_wall`：主力结算价距最近同侧 OI 墙 < 1% 时新开仓 ×0.5（数据源：现有 R84 产物）；
- 判定（每 overlay 相对其 base，同窗同成本）：
  - `KEEP`：≥4/5 年度窗口 ΔSharpe > 0 且全窗 conservative 档 ΔSharpe ≥ +0.10；
  - `WATCH`：全窗 ΔSharpe > 0 但年度一致性不足；
  - `REJECT`：其余。REJECT 的 overlay 对应上游模块保持"数据摄入、研究冻结"状态。

**工程产物**：`overlay_test.py`；CLI `strategy test-overlay --overlay ovl_member_position --base CF_tsmom_v0`；报告 `reports/strategy/overlay_{name}.md/.json`（自动 KEEP/WATCH/REJECT）；单测。

**验收**：三个初始 overlay 各出一份判定报告；判定行可机器解析；overlay spec 复用 R86 校验器。

---

### R93 仪表盘策略卡

**目的**：把影子状态放进已有的 `scripts/build_dashboard.py` 单文件仪表盘。

**内容**：新增"策略影子"分区——每策略一行：当前目标仓位（手/方向）、进场日、持仓天数、nav 迷你曲线（近 60 交易日 sparkline）、回撤、与基准差；数据源 `runs/daily/{P}/{date}/strategy_shadow.json` 与台账 parquet 尾部（生成器读 parquet 需 pandas，允许 import pandas，失败时降级为只读 json 摘要）。分享图追加"策略影子"一栏。保持单文件 HTML、无外部依赖、研究边界声明照旧。

**验收**：无台账时分区隐藏且整页不报错；有台账时渲染正确（用 fixture 生成的 json 做快照测试可选）。

---

## 五、Lane B：薄扩品种（统计功效与分散，R94-R99）

### 总原则

薄扩 ≠ 复制 CF 全链。每个新品种只建：core 数据 + 合约规则复核 + mapping/连续价格 + 四因子 + 信号矩阵 + 策略模板影子。**不建**期权链、事件解释、基本面、会员持仓深挖、观察窗口。参数一律沿用 CF 锁定值（跨品种一致优先于单品种调优，这是防过拟合手段，不是偷懒）。

### R94 expansion gate v2：thin/full 分层

修订 `expansion_gate.py` 与文档：

| 层 | 门槛 | 允许产物 |
| --- | --- | --- |
| THIN | G1 数据接入 + G2 合约规则人审 + G3 mapping/连续价格 + G4 因子跑通 | core、因子、矩阵、策略影子 |
| FULL | 原 R52 全部条件 | CF 现有全链 |

gate 报告显式列出每品种当前层级与缺口。原 R52 语义不变，只是变成 FULL 层。**验收**：gate JSON 含 `tier` 字段；CF=FULL，其余品种默认 NONE→THIN 流转；单测。

### R95 首个薄扩品种：SR（白糖）数据接入

- 历史：`data/incoming/CF/history/ALLFUTURES{year}.zip` 年度档为全品种文件，优先复用已下载档案抽取 SR，不足年份再人工补档（沿用现行人工下载主路径）；incoming 目录新增 `data/incoming/SR/history/`；
- 日更：验证 `FutureDataDailySR.xlsx` 官方 URL 同族可用性，接入现有 downloader（`-Products CF,SR` 风格参数）；
- core：`data/core/SR/core_quote_daily.parquet`，schema 与 CF 完全一致；R63 审计参数化品种；
- 合约规则：`configs/products/SR.yaml` 已有占位，交割月/交易单位/tick/最后交易日全部标 `HUMAN_REVIEW_REQUIRED`，以郑商所合约文本为准复核后落 `docs/SR_CONTRACT_RULE_REVIEW.md`（复用 R07 机制）。

**验收**：SR core 覆盖 2021 至最新；R63 对 SR 通过；contract review 报告存在且人审项显式；日历复用 CZCE 现有官方文件。

### R96 因子与信号矩阵跨品种化

- `build-cf-*` 系列中 mapping/continuous/因子/矩阵命令抽出品种参数（`--product SR`），内部实现参数化而非复制文件；CF 行为回归测试保证不变；
- SR 四因子 + 1/3/5/10/20/40D 矩阵产出，`option_signal=not_connected`（SR 期权不接）；
- 因子参数、矩阵权重与 CF 完全相同，禁止为 SR 单独调参。

**验收**：同一命令 `--product CF` 输出与改造前 bit 级一致（golden）；SR 矩阵每日可产出；文档更新。

### R97 品种级策略影子复制

- `SR_tsmom_v0.yaml`（仅 unit/tick/max_lots 因品种而异，其余参数与 CF 相同，unit 等字段引用 product yaml 且带人审标记）；
- SR 回测（R87/R88 机制）+ 日更影子（R90 机制，ps1 品种参数化）；
- 视 R95-R97 进度，TA、MA 依同路径跟进（各自 yaml，无新代码）。

**验收**：SR 影子进入日更；R88 报告可对 SR 产出；新增品种不修改任何 CF 产物。

### R98 等风险组合影子

- 组合定义：n 个品种各分配 `capital_base/n` 记账资本，各自 vol-target 相同（等风险近似），组合 nav = 各品种影子 pnl_net 加总；
- 每周最后交易日刷新 n（新品种上线次周生效）；
- 输出 `runs/daily/PORTFOLIO/{date}/portfolio_shadow.json/.md` 与 `data/strategy/PORTFOLIO/portfolio_shadow_ledger.parquet`；月度输出品种相关性矩阵（仅展示，不做优化）。

**验收**：组合 pnl = 分品种之和（对账断言）；单品种缺数时组合行记 WARNING 而非静默；报告含分散度描述（组合 vol 对比单品均值 vol）。

### R99 组合月度审计

每月首个交易日产出上月组合审计：分品种贡献、相关性、成本拖累、与 CF 单品对比、下月复核项。`reports/strategy/PORTFOLIO_{yyyymm}_monthly_audit.md`。**验收**：一条命令产出；含研究边界声明；单测。

---

## 六、策略规格 v0 默认参数（YAML 草案全文）

### configs/strategy/CF_tsmom_v0.yaml

```yaml
strategy_id: CF_tsmom
version: v0
status: baseline
product: CF
signal_object: CF.C1            # 现有连续价格 signal object
signal_windows: {momentum_days: 20}
entry_rule: "dir = sign(P_c[t]/P_c[t-20] - 1); dir==0 沿用前值"
exit_rule: "方向翻转即反手；无独立止损（基准刻意简单）"
gate_rules: []                  # 基准无门控
sizing:
  model: vol_target
  capital_base: 1000000         # 研究记账资本，HUMAN_REVIEW_REQUIRED
  target_vol: 0.12              # HUMAN_REVIEW_REQUIRED
  vol_window: 20
  vol_floor: 0.05
  unit_per_lot: 5               # 吨/手，引用 configs/products/CF.yaml，人审
  max_lots: 20
execution: {timing: T_plus_1_settle}
costs: {scenarios: {no_cost: 0, normal_cost: 5, conservative_cost: 10}}  # 单边 bps
data_dependencies:
  - data/research/CF/continuous/*settle_continuous_price_daily.parquet
  - data/core/CF/core_quote_daily.parquet
  - data/research/CF/mapping/*trade_mapping_daily.parquet
forbidden_inputs: [forward_return, fwd_ret, future_]
changelog:
  - {version: v0, date: TBD_BY_CODEX, note: "初始基准，参数 ex-ante 固定"}
```

### configs/strategy/CF_phase_gated_v0.yaml（增量部分）

```yaml
strategy_id: CF_phase_gated
version: v0
status: candidate
base: CF_tsmom/v0
gate_rules:
  - {name: phase, source: trend_phase_v2_daily, fallback: trend_phase_r24,
     map: {S2: 1.0, S1: 0.5, S0: 0.0, S3: 0.5, S4: 0.0},
     s3_no_add: true, conflict_with_dir: 0.0, missing: 0.0_with_warning}
  - {name: carry_tilt, source: factor_diagnostic_daily.carry,
     agree: 1.0, disagree: 0.75, missing: 1.0}
  - {name: option_veto, source: signal_matrix_latest.option_signal,
     veto_rule: "option_signal in {diverge_short, diverge_long} 且与 dir 反向，或 volatility_risk",
     veto_multiplier: 0.5, missing_or_not_connected: 1.0}
promotion_rule: ">=4/5 年度窗口 Sharpe 不低于基准，且全窗 conservative 档 Sharpe >= 基准+0.10"
```

以上所有带 `HUMAN_REVIEW_REQUIRED` 的数值（记账资本、目标波动、单位、tick、max_lots、成本档）在 R86 完成后、R87 运行前由人工确认一次并记入 changelog；Codex 不得自行改动。

---

## 七、防过拟合与迭代预算（策略级纪律）

1. **参数预登记**：任何参数网格必须在运行前写入 registry（`planned_grid` 字段）；未预登记的参数组合出现在报告中即视为违规。
2. **迭代预算**：每季度每 strategy_id 最多一次参数修订（bump version + changelog + 生效日）；R89/R92 判定失败不解锁额外修订。
3. **影子期神圣**：影子台账覆盖期的数据永不用于该策略的参数重选；重选只能用影子期之前的窗口。
4. **挑战者机制**：新版本 spec 上线后与旧版本并行影子 ≥ 20 个交易日，替换决定只看前向影子表现，历史回测优势只授予"挑战者"资格。
5. **评价优先级**：跨年稳定 > 成本后存活 > 绝对收益；报告排版按此顺序展示。
6. **单品种克制**：CF 上任何再优化动作前，优先把同一套参数摊到更多品种上验证（Lane B 就是防过拟合手段）。

---

## 八、边界与不做清单

**继续不做**：实盘下单、OMS、券商/柜台接口、分钟级数据与执行、自动调仓推送、实时行情服务、多用户平台、公众号发布线恢复、DCE/SHFE 跨交易所接入（本期）、期权策略回测。

**冻结但保留数据**：会员持仓深挖（R83/R85 摄入照常）、行权价 OI 墙深挖（R84 周更照常）、事件叙事扩展、基本面研究——解冻条件唯一：R92 判定 KEEP。

**永久边界**：影子台账及一切策略产物均为研究仿真，带显式声明；所有人审门（合约规则、成本参数、执行时点、官方字段解释）沿用 AGENTS.md。

---

## 九、Codex 执行约定

1. **执行顺序**：严格按 R86 → R87 → R88 → R89 → R90 → R91 → R92 → R93 → R94 → R95 → R96 → R97 → R98 → R99；R90 完成后 Lane B 可与 R91-R93 并行。
2. **提交纪律**（针对本仓库既往"只开发不收口"的教训）：每完成一个 R 模块：`py -3.12 -m pytest` 与 `py -3.12 -m ruff check src tests` 全过 → 更新 README（命令示例 + R-note 一段）与 roadmap 进度行 → 单独 git commit，message 格式 `R86: strategy spec registry and direction docs`；不得把多个 R 模块混在一个提交。
3. **不改旧行为**：除 R86 文档修订与 R96 的参数化改造（有 golden 回归护栏）外，不修改任何既有模块的输出；CF 现有产物 bit 级不变是默认验收项。
4. **输出契约**：每个 R 模块结束时按 AGENTS.md Output Contract 汇报（changed files / commands / tests / artifacts / assumptions / research TODOs / human review required / next task）。
5. **硬停条件**：沿用 AGENTS.md Hard Stop；另加两条——(a) 影子台账历史行需要修改时停下报告；(b) 任何检验结果触发"想调参重跑"冲动时停下报告，引用第七章预算规则。
6. **环境**：Windows，`py -3.12`，`$env:PYTHONPATH="src"`；新表 schema 进 `core/schemas.py` 同风格注册；中文报告用现有 renderer 惯例。

---

## 十、排期与优先级

| 顺序 | 模块 | 目的 | 优先级 |
| --- | --- | --- | --- |
| 1 | R86 方向收口 + spec 注册表 | 消除宪法冲突，建立规格基座 | 最高 |
| 2 | R87 笨基准引擎 | 建立全系统的对照组 | 最高 |
| 3 | R88 策略级滚动验证 | 净值成为统一度量 | 最高 |
| 4 | R89 候选策略对决 | 特色模块第一次接受审判 | 高 |
| 5 | R90 每日影子台账 | 前向可证伪记录（核心交付） | 最高 |
| 6 | R91 周度策略审计 | 影子进入例行治理 | 高 |
| 7 | R92 overlay 检验 | 会员持仓等模块去留判据 | 高 |
| 8 | R93 仪表盘策略卡 | 策略状态可视化 | 中 |
| 9 | R94 gate v2 分层 | 薄扩合法化 | 高 |
| 10 | R95 SR 数据接入 | 第二品种 core | 高 |
| 11 | R96 因子/矩阵参数化 | 模板跨品种 | 高 |
| 12 | R97 SR/TA/MA 策略影子 | 广度落地 | 中高 |
| 13 | R98 等风险组合影子 | CTA 分散特性显形 | 中高 |
| 14 | R99 组合月度审计 | 组合治理 | 中 |

---

## 十一、V5 第一阶段总验收（Definition of Done）

1. 一条命令可复现 CF 基准全窗回测，三档成本报告齐全；
2. 日更脚本默认产出 `strategy_shadow.json`，影子台账连续、可对账、幂等；
3. `CF_phase_gated_v0 vs baseline` 对比报告存在且含自动晋级判定；
4. 三个初始 overlay（期权否决 / 会员持仓 / OI 墙）各有 KEEP/WATCH/REJECT 判定报告；
5. 至少 SR 一个品种通过 THIN gate 并进入日更影子；
6. 组合影子（≥2 品种）开始逐日记账；
7. AGENTS.md / PROJECT_DIRECTION / roadmap / README 与实际状态一致；
8. `pytest` 与 `ruff` 全过；每个 R 模块一个独立提交。

---

## 十二、最终判断

V4 把系统建成了一个纪律严格的研究观察工作台；V5 的全部工作只回答一个问题：

> **这些研究，折算成一条无未来函数的净值曲线之后，还剩多少是真的？**

因此执行上：先立笨基准，再让特色模块逐个对决晋级；先在 CF 上把影子台账跑起来，再用同一套锁定参数摊到 SR/TA/MA 攒统计功效与分散；所有"别的平台也有"的功能，一律送上 R92 的审判台，用 ΔSharpe 说话。历史回测结论只授予挑战者资格，主策略地位永远由前向影子表现授予。

本任务书完成后，系统将同时拥有：可发布的研究叙事（V4 遗产）、可证伪的策略记录（V5 新增）、以及一个不断用数据裁决"什么值得做"的治理机制。
