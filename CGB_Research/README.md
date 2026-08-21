# CGB_Research

中国国债与国债期货的可追溯研究资料库。项目把“原始证据、报告观点、研究推断、外部数据和人工裁决”分开保存，目标是支持跨报告比较、周度增量更新和事后复盘，而不是自动给出投资方向。

## 当前状态（2026-08-16）

- 已完成项目初始化、报告注册、字段级证据登记、旧 iFinD 数据快照迁移与6份试处理抽样。
- `00_inbox/raw_reports` 是不可变原件区；PDF不进入Git，由SHA-256清单证明完整性。
- Gate A已用户审阅通过并冻结为v0.1；Gate B的3份试处理卡片、59页逐页清单和49条证据审计已于2026-08-21通过并冻结为v0.1。剩余9份报告未生成卡片。
- 卡片方法已经改为跨报告整合研究，不建立研究员画像。v0.2框架按“上期复盘—国内结构锚—战术触发—海外事件门控—市场定价—行为确认—工具表达—到期证伪”组织；文字优先，只有关键结论依赖图表时才做最小视觉复核。
- Gate B新增海外五级门控、事件分段和预测冲突账本设计，并已作为v0.2研究操作框架冻结。美债、美元、油价等外部变量只有经过方向一致的人民币/跨境桥梁、国内条件和独立市场定价检验后，才允许成为CGB解释变量；进一步映射到TS/TF/T/TL还必须通过对应工具的CTD、基差、DV01和换月门槛。框架`effective=true`；65项指标候选仍为`effective=false`，其中11项因关键依赖缺失而阻断、5项待可得性审计。
- 中金所当前可交割券官方截面已经形成不可变快照并通过独立核验；历史合约最终篮子和按生效日重建的事件账本尚未完成，不能用于声称无前视偏差的历史回测。
- 新 iFinD 流水线保持禁用。历史时点链路、冻结run manifest、单writer锁和原子发布全部通过前，不得切换生产入口。

## 证据等级

- `[E]`：报告明确陈述，必须带 `report_id + PDF物理页码 + 证据数据截止日/U状态`。
- `[I]`：基于证据的推断，不得伪装为报告原话。
- `[X]`：报告外数据、文件系统事实或外部资料。
- `[U]`：证据不足、日期口径不统一或提取质量不确定。

发布日期、数据截止日、历史样本期和预测期必须分列。`data_cutoff` 只记录报告明确声明的全篇统一截止日；多口径报告留空，并使用 `latest_explicit_data_date` 与 `data_cutoff_scope` 描述。

## 目录

- `00_inbox/`：只读PDF原件与待复核附件。
- `01_registry/`：报告、作者、附件、字段证据与处理日志。
- `02_report_cards/`：经Gate流程生成的版本化报告卡片；当前含3份已批准Gate A卡片和3份已批准冻结Gate B卡片，均为v0.1。
- `03_frameworks/`：长期机制框架模板与版本化整合框架。
- `04_indicators/`：指标字典、来源映射和计算规则。
- `05_data/`：iFinD原始响应、标准化数据与冻结快照。
- `06_weekly/`：周报模板、2026-W33回归基准和观点账本。
- `07_events/`：政策、经济日历和异常事件表。
- `08_scripts/`：安全校验入口与禁用的新流水线骨架。
- `09_audit/`：抽取问题、迁移清单、质量报告与预测评分。
- `99_archive/`：旧代码、排除探测数据与去重后的历史版本。

## 受控市场对象

现券、TS/TF/T/TL国债期货、收益率曲线、期限利差、跨期价差、基差、净基差、CTD、IRR、Carry分别登记，禁止混写。任何市场判断必须补齐适用期限、传导机制、触发条件、证伪条件和跟踪指标。

## Gate A / Gate B

抽样算法固定为 `seed=20260815`，排序键为 `SHA256(seed|层代码|NFC文件名)`，同一发布机构/模板家族最多2份。具体样本、排序键和验收门槛见 `09_audit/pilot_selection_20260815.csv` 与 `09_audit/registry_quality_report_20260815.md`。

Gate A成果见`03_frameworks/gate_a_integrated_framework_v0.1.md`；Gate B整合后的已冻结框架见`03_frameworks/gate_ab_integrated_framework_v0.2.md`。该框架不会把不同报告的美债区间或政策路径取平均，而是按场景角色、触发条件和证伪条件进入不可覆盖的预测声明账本；指标候选仍须完成依赖审计后才可进入生产字典。

## 安全边界

1. 不覆盖已确认卡片或周报，只创建递增版本。
2. 不扫描“latest”拼接不同采集批次；必须读取单一冻结run manifest。
3. 不把Excel固定行当作CFFEX可交割券权威数据。
4. 不在仓库保存 iFinD 用户名、密码或API Key；Windows凭据目标保持 `iFinD_API_Weekly_Report`。
5. 初始化阶段不刷新API、不发送邮件、不创建计划任务、不启用Office生成链路。

## 关键审计入口

- 报告目录：`01_registry/reports.csv`
- 字段证据：`01_registry/report_metadata_evidence.csv`
- 初始化质量报告：`09_audit/registry_quality_report_20260815.md`
- iFinD迁移清单：`09_audit/ifind_migration_manifest.json`
- 数据迁移问题：`09_audit/data_migration_issues.csv`
- 试处理抽样：`09_audit/pilot_selection_20260815.csv`
- Gate A质量报告：`09_audit/gate_a_quality_report_20260815.md`
- Gate A+B整合框架：`03_frameworks/gate_ab_integrated_framework_v0.2.md`
- Gate B候选指标：`09_audit/gate_b/indicator_candidates_v0.2.csv`
- Gate B质量报告：`09_audit/gate_b_quality_report_20260816.md`
- 中金所当前截面质量报告：`09_audit/cffex_snapshot_quality_report_20260815.md`
