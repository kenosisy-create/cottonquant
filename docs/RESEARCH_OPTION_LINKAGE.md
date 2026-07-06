# CF 期货-期权联动 R49

R49 把 R48 期权 proxy 接入期货研究信号矩阵，作为过滤器和风险提示，
不改变原有期货多因子 `composite_score`。

## 输入

- R35/R49 期货信号矩阵输入：`data/core/CF/core_quote_daily.parquet`
- R48 期权因子表：
  `data/research/CF/option_factors/*_option_factor_proxy_daily.parquet`

## 输出字段

R35 信号矩阵新增或填充以下字段：

- `option_signal`
- `option_signal_direction`
- `option_factor_status`
- `option_atm_iv_rank`
- `option_pcr_volume`
- `option_pcr_oi`
- `option_skew_proxy`

`option_signal` 初版状态：

- `confirm_long` / `confirm_short`：期权 proxy 与期货方向同向。
- `diverge_long` / `diverge_short`：期权 proxy 与期货方向背离。
- `volatility_risk`：ATM IV rank proxy 偏高，提示波动风险。
- `option_watch`：期权 proxy 行不是 READY，仅作观察。
- `option_neutral`：期权方向不明确。
- `not_connected` / `not_available`：未接入或当日无对应期权 proxy。

## 规则边界

- 期权信号是过滤器和风险提示，不进入 `composite_score`。
- ATM IV、IV rank、skew 仍来自 R48 研究 proxy，不是精确 IV/Greek。
- 本模块不做期权策略，不输出交易指令。
- 期权联动规则在进入交易使用前必须人工复核。

## 命令

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-signal-matrix --start 2021-01-04 --end 2026-07-03 --horizons 1,3,5,10,20,40 --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/signal_matrix --report-output-dir reports/research/signal_matrix --option-factor-path data/research/CF/option_factors/CF_2021-01-04_2026-07-03_option_factor_proxy_daily.parquet
```

日更脚本可以用 `-OptionFactorPath` 传入已生成的 R48 因子表。
