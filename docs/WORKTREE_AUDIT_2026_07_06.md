# Cottonquant 工作树审计与整理建议 - 2026-07-06

## 结论

当前工作树“很脏”的主因不是代码坏掉，而是 D0-R61 大量阶段性成果已经落地到本地，但尚未做一次阶段性 Git 收口。

审计时仓库状态：

- 当前分支：`master`
- 远端：`origin https://github.com/kenosisy-create/cottonquant.git`
- HEAD：`ff910d4 chore: freeze cotton factor mvp`
- 已跟踪但修改：`21` 个文件
- 未跟踪：`157` 个文件
- 当前数据/报告/运行产物体积：
  - `data/`：约 `572.76 MB`
  - `reports/`：约 `82.95 MB`
  - `runs/`：约 `9.33 MB`
  - `src/`：约 `3.68 MB`
  - `tests/`：约 `2.02 MB`

当前代码质量基线仍有效：

- `py -3.12 -m pytest`：`292 passed`
- `py -3.12 -m ruff check src tests`：通过

## 为什么脏

### 1. 后续研究工作没有阶段性提交

当前远端仍停在 `chore: freeze cotton factor mvp`，而本地已经继续完成了研究工作台主线：

- R23 latest signal-only brief
- R24-R40 趋势、信号矩阵、阈值、日更审计等
- R41 历史证据包
- R42/R55 历史事件与基本面解释
- R46-R49 期权数据、期权因子、期货-期权联动
- R53-R54 基本面观察与上下文
- R59 周度审计
- R60 事件阈值敏感性
- R61 将 R60 接入 R56/R59/周更脚本

这些成果大量位于：

- `src/cotton_factor/research_workbench/`
- `tests/unit/test_research_*.py`
- `scripts/update_cf_latest_research.ps1`
- `docs/RESEARCH_*.md`
- `configs/*`

这些不是垃圾，应作为阶段性成果纳入版本管理。

### 2. 数据和报告产物被正确忽略，但本地体积很大

`.gitignore` 已经忽略：

- `data/raw/**`
- `data/core/**`
- `data/research/**`
- `data/archive/**`
- `data/incoming/**`
- `reports/**`
- `runs/**`

所以数据、报告、运行产物大多不会进 Git。它们让本地项目目录显得大，但不是 Git 脏状态的主要来源。

### 3. 占位文件仍未纳入 Git

这些 `.gitkeep` 仍是未跟踪，建议纳入 Git，保证空目录结构可复现：

- `data/incoming/CF/.gitkeep`
- `data/incoming/CF/history/.gitkeep`
- `data/incoming/CF/options/.gitkeep`
- `data/incoming/CF/options/history/.gitkeep`
- `reports/daily/.gitkeep`
- `reports/research/.gitkeep`
- `runs/codex/.gitkeep`

### 4. Windows 行尾提示较多

`git diff` 显示多处 `LF will be replaced by CRLF`。这不是业务错误，但建议后续增加 `.gitattributes` 固化 Markdown、Python、YAML、CSV 的行尾策略，避免每次审计时噪音很大。

## 应纳入 Git 的内容

### 必须纳入

这些是主线工程能力，不应删除：

- `src/cotton_factor/research_workbench/`
- `src/cotton_factor/cli/main.py`
- `src/cotton_factor/common/exceptions.py`
- `src/cotton_factor/core/schemas.py`
- `src/cotton_factor/core/__init__.py`
- `scripts/update_cf_latest_research.ps1`
- `tests/unit/test_research_*.py`
- `tests/unit/test_cf_weekly_research_script.py`
- `tests/fixtures/core_option_quote_daily_cf_sample.csv`
- `pyproject.toml`
- `.gitignore`

理由：

- 它们是 R00-R61 的研究工作台主线代码、CLI、schema、脚本和测试。
- 当前全量测试通过。
- 删除会导致后续 R62+ 无法继续。

### 建议纳入

这些是研究路线、口径和人工复核依据，建议保留：

- `AGENTS.md`
- `README.md`
- `docs/RESEARCH_*.md`
- `docs/PROJECT_DIRECTION.md`
- `docs/CURRENT_STATE_RESEARCH_MAP.md`
- `docs/RESEARCH_MANUAL_REVIEW_GUIDE.md`
- `docs/STAGE_AUDIT_FROM_V4_TASKBOOK_2026_07_05.md`
- `docs/STAGE_RESEARCH_AUDIT_2026_07_02.md`
- `configs/research_mode.yaml`
- `configs/data_sources_cf_research.yaml`
- `configs/cf_research_data_ports.csv`
- `configs/cf_ifind_collection_checklist.csv`
- `configs/calendars/CZCE_2025_OFFICIAL.csv`
- `configs/calendars/CZCE_2026_OFFICIAL.csv`
- `prompts/*.md`

注意：`CottonquantV4任务书.md` 当前在项目根目录且未跟踪。建议后续移动或复制到 `docs/` 下统一管理，再纳入 Git。

## 不应纳入 Git 的内容

这些应保留在本地或外部数据目录，不进入版本管理：

- `data/incoming/CF/history/*.zip`
- `data/incoming/CF/history/*.xlsx`
- `data/incoming/CF/options/history/*.zip`
- `data/incoming/CF/options/history/*.xlsx`
- `data/raw/**`
- `data/core/**`
- `data/research/**`
- `reports/research/**`
- `runs/daily/**`
- `runs/weekly/**`
- `runs/codex/**`

理由：

- 文件体积大。
- 多数是可再生成产物。
- 原始行情/期权/基本面数据涉及本地来源，不应误提交到远端。

## 可考虑清理的本地产物

以下只建议在确认后清理，不在本次审计中直接删除。

### 可安全清理

- `.pytest_cache/`
- `.ruff_cache/`
- `runs/d2_cli_raw_check*/`
- `runs/d3_cli_raw_check*/`
- `runs/d4_cli_raw_check/`
- 早期 `runs/codex/*probe*`

理由：缓存或早期探针输出，可再生成，不影响当前主线。

### 建议确认后清理

- `reports/research/option_core_ingest/CF_option_core_ingest_quality.csv`
  - 约 `54.18 MB`
  - 属于质量报告 CSV，可再生成。
- `data/research/CF/option_factors/CF_2021-01-04_2026-07-03_option_surface_proxy_daily.csv`
  - 约 `83.32 MB`
  - 同目录已有 Parquet 版本，CSV 可考虑仅在需要人工检查时生成。
- `reports/research/signal_matrix/*_signal_matrix.json`
  - 单个约 `12-15 MB`
  - 可保留最新一份，其余归档或清理。

### 不建议直接清理

- `data/incoming/**`
- `data/raw/snapshots/**`

理由：

- `data/incoming` 是用户手工补充的官方/iFinD/期权源文件。
- `data/raw` 是 raw preservation 证据链。
- 如需清理 `data/raw/snapshots/CZCE_CF_OPTION_HISTORY` 的重复快照，应先建立“同 checksum 只保留一份”的去重脚本，并保留 manifest 追溯。

## 建议的阶段性工作树优化方案

### 阶段 A：建立干净的版本基线

目标：把所有主线代码、测试、配置、文档、占位目录纳入一次提交。

建议纳入：

- `.gitignore`
- `AGENTS.md`
- `README.md`
- `pyproject.toml`
- `configs/`
- `docs/`
- `prompts/`
- `scripts/`
- `src/cotton_factor/research_workbench/`
- 修改过的 `src/cotton_factor/*`
- `tests/`
- `.gitkeep` 占位文件

明确不纳入：

- `data/raw/**`
- `data/core/**`
- `data/research/**`
- `data/incoming/**` 中的真实数据文件
- `reports/**` 中的真实报告产物
- `runs/**` 中的真实运行产物

### 阶段 B：增加工作树卫生规则

建议增加：

- `.gitattributes`：固定文本文件行尾，降低 Windows CRLF 噪音。已在本次收口中新增。
- README 中增加“哪些目录不提交”的说明。
- 后续脚本默认少写大型 CSV，优先写 Parquet；CSV 作为人工审阅可选项。

### 阶段 C：本地清理采用 dry-run 机制

任何清理都先输出清单，不直接删除：

- 清理缓存：`.pytest_cache/`、`.ruff_cache/`
- 清理旧探针：`runs/d2*`、`runs/d3*`、`runs/d4*`
- 清理可再生成的大型 CSV/JSON
- raw 快照去重只在 checksum 确认后执行

### 阶段 D：每个大阶段结束后提交一次

建议提交节奏：

1. `research workbench baseline R00-R40`
2. `historical evidence and event explanation R41-R45`
3. `option linkage and fundamentals R46-R55`
4. `weekly audit and threshold review R59-R61`

当前由于历史阶段已经连续开发，实际可以先做一次大基线提交，再从 R62 开始恢复小步提交。

## 当前是否需要删除文件

不建议现在直接删除。

更合适的处理是：

1. 先提交主线代码、测试、文档、配置。
2. 确认 Git 工作树只剩被忽略的数据/报告/运行产物。
3. 再做本地 dry-run 清理清单。
4. 对 raw 和 incoming 只做归档或去重，不做直接删除。

## 后续建议任务

下一步建议执行“工作树收口任务”：

- 新增 `.gitattributes`
- 调整/确认 `.gitignore`
- 生成 `git add` 白名单
- 先做一次 dry-run staging 审查
- 用户确认后再提交到远端
