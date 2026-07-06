# CF 期权因子 proxy R48

R48 在 R47 已生成的 `core_option_quote_daily.parquet` 基础上构建期权研究
proxy。它不直接解析交易所 raw 文件，也不生成期权交易策略。

## 输入

- `data/core/CF/core_option_quote_daily.parquet`
- `data/core/CF/core_quote_daily.parquet`

## 输出

- `data/research/CF/option_factors/*_option_factor_proxy_daily.parquet`
- `data/research/CF/option_factors/*_option_surface_proxy_daily.parquet`
- `data/research/CF/option_factors/*_option_factor_proxy_warnings.csv`
- `reports/research/option_factors/*_option_factor_proxy.md`
- `reports/research/option_factors/*_option_factor_proxy.json`

## 初版因子

- `atm_iv_proxy`：ATM call/put straddle extrinsic value 除以标的期货结算价。
- `atm_iv_rank`：同一标的合约的 rolling proxy rank。
- `pcr_volume`：put 成交量 / call 成交量。
- `pcr_oi`：put 持仓量 / call 持仓量。
- `skew_proxy`：OTM reference band 内 put premium ratio 减 call premium ratio。
- `option_liquidity_score`：成交量和持仓量的对数流动性 proxy。

## 质量过滤

以下期权行不会进入核心 proxy：

- `LOW_LIQUIDITY_VOLUME`
- `LOW_LIQUIDITY_OPEN_INTEREST`
- `DEEP_OTM_PROXY`
- `NEAR_EXPIRY_REVIEW`
- `UNDERLYING_PRICE_MISSING`
- `MISSING_SETTLE`

被过滤的行仍会写入 surface proxy 表，并保留 `exclusion_reason`。

## 研究边界

- ATM IV、IV rank、skew 都是研究 proxy。
- 美式期权 IV/Greek 未完成精确定价，不作为精确风险暴露。
- forward return、回测收益、交易成本不进入 R48。
- `option_signal_status` 仍为 `not_connected`；R49 才把期权作为期货信号过滤器。
- 本报告不构成交易指令。

## 命令

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-option-factor-proxy --option-core-path data/core/CF/core_option_quote_daily.parquet --core-quote-path data/core/CF/core_quote_daily.parquet --output-dir data/research/CF/option_factors --report-output-dir reports/research/option_factors
```
