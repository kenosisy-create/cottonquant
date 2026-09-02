# CF 轻量日更编排器

## 1. 定位

`operations run-cf-daily-update` 是默认 CF 日更的 Python 编排入口。它只编排
最新交易日可观察数据，不读取 forward return，不运行历史证据、发布包或退役影子台账。

PowerShell 仍可作为 Windows 入口：当没有请求重型研究时，
`scripts/update_cf_latest_research.ps1` 自动转交 Python 编排器；显式周更、历史研究、
发布包和清理参数继续走兼容路径。

## 2. 默认步骤

1. 可选下载郑商所期货和期权日文件。
2. 期货文件进入不可变 raw，并增量合并 futures core。
3. 从 core 刷新当年交易日历和数据截至日期。
4. 可选接入 option core。
5. 检查期货、期权、交易日历和 raw 血缘连续性。
6. 增量刷新期权 proxy。
7. 构建多周期信号矩阵。
8. 构建双价格、全链持仓、期权结构和趋势阶段侧车。
9. 写出最新信号简报、基本面状态和趋势连续性看板。
10. 可选写出日度 operation audit。

步骤包含显式依赖、阻断属性、耗时和错误。阻断步骤失败后，后续步骤不会继续启动；
基本面状态属于非阻断步骤，失败时日更可标记为 `COMPLETED_WITH_WARNINGS`。

## 3. 命令

直接使用 Python 公共 CLI：

```powershell
$env:PYTHONPATH="src"
py -3.12 -m cotton_factor.cli.main operations run-cf-daily-update `
  --date 2026-08-27 `
  --download-official
```

使用兼容 PowerShell 入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/update_cf_latest_research.ps1 `
  -DownloadOfficialDaily `
  -DownloadDate 2026-08-27
```

如需强制使用原 PowerShell 编排路径：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/update_cf_latest_research.ps1 `
  -UseLegacyPowerShellOrchestrator
```

## 4. 输出

每次运行在 `runs/daily/CF/YYYY-MM-DD/` 写出：

- `daily_update_pipeline.json`
- `daily_update_pipeline.md`
- 数据连续性报告
- 最新信号简报
- 趋势连续性看板
- 可选日度 operation audit

运行摘要固定包含请求日期、数据截至日期、每步状态、耗时、错误、研究边界和产物摘要。

## 5. 当前性能基线

2026-08-27 真实数据验证显示：轻量日更约 52 秒，带期权侧车的完整日更约 61 秒。
`signal_matrix` 仍会重算 2021 年以来全历史，但按交易日/合约预索引后单步约 28--31
秒，且与优化前 8,220 行、58 列结果逐字段一致。周期收益计算已从重复表筛选改为
合约结算价位置索引。

期权 core 接入已按源文件 SHA256 增量化：首轮解析历史文件后，未变化文件只复用既有
raw 快照并跳过解压，2026-08-27 验证中 7 个历史文件全部命中，接入耗时从约 272 秒
降至约 2.6 秒。变化文件仍会追加 raw 快照，并按键替换对应 core 行；`data/incoming`、
`data/raw` 和 manifest 不会被删除。

后续若继续优化，优先级是建立 signal matrix 增量合并方案，并与全量重算做逐字段、
逐行、逐日期等价比较；在等价性验证完成前不替换当前全量路径。

## 6. 研究边界

- latest-only 产物不包含 forward-return 历史后验标签。
- 连续合约只作信号对象；真实合约执行边界不变。
- 基本面和期权侧车不自动修改 `composite_score`。
- 日更摘要和研究简报不构成交易指令。
- HUMAN_REVIEW_REQUIRED。
