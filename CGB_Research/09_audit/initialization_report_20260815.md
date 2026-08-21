# CGB_Research 初始化交付报告（2026-08-15）

## 1. 完成结果

项目已在 `D:\国债\CGB_Research` 初始化为可审计资料库，并停在批准计划规定的边界：

- 已建立项目骨架、强制约束、注册表、字段证据、问题表、工作簿资产表、模板和本地Git；
- 已把15份PDF复制为只读项目原件，并逐份验证源/目标SHA-256和页数；
- 已按逻辑完整、物理哈希去重迁移旧iFinD数据快照和旧代码档案；
- 已登记6份可复现试处理样本；
- 未生成任何报告摘要或报告卡片；
- 未调用iFinD API，未晋升数据，未发布周报，未发送邮件，未创建计划任务；
- 新周报入口保持禁用，旧数据和旧代码目录未删除、未移动、未重写。

## 2. 读取的文件

### 国债研究资料源

完整读取并核验了以下15份PDF：

1. `D:\researchreports\bond\【期债半年报】水活则鱼动，把握流动性改善的机遇.pdf`
2. `D:\researchreports\bond\20260706-华泰期货-国债半年报：反弹之后，等待拐点.pdf`
3. `D:\researchreports\bond\20260706-建信期货-国债半年报：1.65％—1.95％，利率的窄走廊与新均衡.pdf`
4. `D:\researchreports\bond\20260726-国泰海通证券-债券基金周度数据观察：30年国债ETF为何越涨越赎.pdf`
5. `D:\researchreports\bond\20260727-国泰海通证券-市场策略周报：如何识别国债期货盘中的“量化”博弈特征.pdf`
6. `D:\researchreports\bond\20260730-国泰海通证券-7月FOMC：沃什说了什么，票委做了什么.pdf`
7. `D:\researchreports\bond\20260802-国泰海通证券-透视股债跷跷板：细分资产相关性的K型分化.pdf`
8. `D:\researchreports\bond\20260804-国泰海通证券-机构行为周度跟踪：30年国债走强行情，会起波动吗，机构行为关注三个关键信号.pdf`
9. `D:\researchreports\bond\20260809-国泰海通证券-30年活跃券如何切换：历史规律与26特6的“不稳定接棒”.pdf`
10. `D:\researchreports\bond\20260809-国泰海通证券-港交所国债期货上市首周：定价中枢与跨境联动.pdf`
11. `D:\researchreports\bond\20260809-华泰期货-国债周报：国债期货偏弱震荡，长端跌幅大于短端.pdf`
12. `D:\researchreports\bond\20260810-国泰海通证券-债基久期高位之后：关注绩优基金久期“死叉”.pdf`
13. `D:\researchreports\bond\20260814-国泰君安期货-2026H2海外宏观经济及大类资产展望：旧序余寒，新质去伪存真.pdf`
14. `D:\researchreports\bond\东证期货_半年报_国债_起伏相循，择时择势_张粲东_20260624.pdf`
15. `D:\researchreports\bond\光期宏观：2026年下半年国债报告.pdf`

另读取并核验：

- `D:\researchreports\bond\20260811-国泰海通证券-基金短端增持降温——信用债机构久期热度观测.xlsx`
- `D:\国债\tmp\周报底稿_只读快照_20260815.xlsx`

### iFinD与旧周报资产

- `D:\国债\ifind_data` 中73个文件、47,504,367字节；
- 17份采集manifest、17份raw响应、17份normalized CSV；
- 正式周报SQLite、mart manifest、6个 `.bak`、2个current副本和9个发布基准文件；
- 顶层92行legacy probe的CSV、JSON和manifest；
- `D:\国债\ifind_rebuild` 中排除 `.venv`、缓存和日志后的32个核心文件；
- 其中7个旧脚本、18个request JSON、5个顶层JSON和2个Markdown说明。

每一个旧路径到新对象的映射、源/目标哈希、编码、行数和schema hash均在 `ifind_migration_manifest.json` 中逐项列出。

### 项目规则与验证资料

- 创建后重新读取了完整 `AGENTS.md`；SHA-256为 `a5c23a05ba341c4f7119acad90899227a2d2bc553eee716365e1fbc3edb59097`。
- 读取了生成后的15个注册/模板CSV、迁移manifest、冻结run manifest、SQLite和Git状态用于验收。

## 3. 创建或修改的项目文件

### 规则、说明和模板

- `AGENTS.md`、`README.md`、`.gitignore`
- `02_report_cards/CARD_TEMPLATE.md`
- `03_frameworks/` 下6个研究框架模板
- `04_indicators/calculation_rules.md`
- `06_weekly/template/weekly_template.md`

### 注册表与账本

- `01_registry/reports.csv`：15条
- `01_registry/report_metadata_evidence.csv`：222条
- `01_registry/source_assets.csv`：1条
- `01_registry/researchers.csv`：13条明确署名人员
- `01_registry/processing_log.csv`：注册、复制、去重和迁移操作日志
- `04_indicators/indicator_dictionary.csv`、`data_source_map.csv`：仅表头
- `06_weekly/view_ledger.csv`：仅表头
- `07_events/` 下3个事件表：仅表头
- `09_audit/forecast_scorecard.csv`：仅表头

### 原件与数据快照

- `00_inbox/raw_reports`：15份只读PDF副本
- `00_inbox/pending_review`：1份只读XLSX附件
- `05_data/raw/ifind`：12个生产raw响应
- `05_data/processed/ifind`：12个生产normalized CSV
- `05_data/snapshots/lineage/ifind`：17份原字节v1 manifest
- `05_data/snapshots/weekly/2026-08-14`：正式SQLite与manifest
- `05_data/snapshots/weekly/CURRENT.json`：只读基准指针，`promotion_enabled=false`
- `06_weekly/2026-W33/data_snapshot`：9个已发布回归基准
- `06_weekly/template/imported`：冻结Excel模板副本
- `99_archive`：5个排除/探测数据集、92行legacy子集、一个唯一旧SQLite物理版本及旧代码档案

### 审计文件

- `09_audit/extraction_issues.csv`：39条
- `09_audit/pilot_selection_20260815.csv`：6条
- `09_audit/ifind_migration_manifest.json`：124条旧路径映射
- `09_audit/data_migration_issues.csv`：6个生产阻断问题
- `09_audit/registry_quality_report_20260815.md`
- `09_audit/no_fetch_dry_run_manifest_20260815.json`
- 本交付报告

### 脚本

- 安全入口：`extract_reports.py`、`build_weekly_snapshot.py`、`update_charts.py`、`validate_weekly.py`
- 初始化/迁移/验收工具：`audit_sources.py`、`find_pdf_dates.py`、`inspect_pdf_pages.py`、`initialize_registry.py`、`migrate_ifind_snapshot.py`、`validate_spreadsheet_artifacts.mjs`、`validate_initialization.py`
- 旧脚本只作为 `99_archive/ifind_rebuild_v0` 历史版本保存，没有启用。

除 `D:\国债\CGB_Research` 内的新项目文件外，没有修改任何外部源文件。外部源目录的文件名、内容和位置保持不变。

## 4. 未能可靠提取的内容

- 所有图表曲线的精确点位、图例方向、单位、表格行列和历史分位；
- 报告未明确说明的计算口径、阈值与隐含假设；
- 任何报告的全篇统一数据截止日；
- 光大报告的明确作者；
- 国泰君安报告精确发布日期、p7截止日期年份和联合品牌结构；
- 东证报告冲突日期中哪个应作为外部分发日；
- 工作簿 `首页!B59` 的原公式；当前文件只保存 `#VALUE!` 错误值且无公式节点；
- CFFEX官方完整可交割券与转换因子快照；旧文件只有行数和文字声明；
- 旧Word源模板的可复现路径与哈希。

这些内容均未猜测填充，已保留空值或 `[U]` 问题。

## 5. 需要人工复核的事项

1. 确认光大报告作者，不得仅凭研究员简介认定。
2. 确认国泰君安报告的精确发布日期、`截止8.7`年份及联合品牌。
3. 裁决东证封面日期与文件名日期冲突；作者以明确署名为准，PDF属性仅作冲突记录。
4. 逐图核对所有曲线数值、单位、图例和表格方向后，才能把图表数字写成 `[E]`。
5. 回到工作簿上游模板或生成链路恢复/解释 `首页!B59`。
6. 用户决定是否批准 Gate A 三份试处理；批准前卡片目录保持空。
7. 在生产数据入口启用前，补齐CFFEX完整官方快照、动态转换因子换月测试、单writer锁和原子 `CURRENT.json` 更新。

## 6. 验收结果

只读整体验收共29项，结果为 `29 PASS / 0 FAIL`：

- 15份PDF源/目标哈希、大小、页数和只读属性全部通过；
- 15个注册/模板CSV均为UTF-8-SIG、CRLF并可按RFC 4180解析；
- 15个CSV另经工作簿工具导入检查全部成功；
- `reports.csv` 恰有15条唯一 `report_id`，受控枚举、外键和页码范围全部通过；
- 222条证据满足E/I/X/U及 `[E]` 页码/截止日或U说明要求；
- iFinD 12个生产数据集35,912行、5个排除集545行，哈希、行数和隔离路径全部通过；
- SQLite `quick_check`、`integrity_check`、外键、17表行数和自然键重复检查全部通过；
- 2026-W33九个发布基准文件齐全；
- 无报告卡片、无报告摘要、无API刷新、无晋升或发布动作；
- 验收前后177个项目及源文件的大小、修改时间和SHA-256完全一致；
- Git根目录正确且没有远程。

结论：**初始化技术验收通过，但尚未获得进入Gate A的用户授权。**
