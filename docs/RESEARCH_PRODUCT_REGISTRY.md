# CF 产品配置与因子注册 R50

R50 固化 CF 的产品规则、期货因子列表、期权 proxy 列表和人工复核项。
它不是多品种扩展，也不是生产级元数据平台。

## 输入

- `configs/products/CF.yaml`
- `configs/factor_registry.yaml`

## 输出

- `data/research/CF/product_registry/CF_product_research_registry.json`
- `data/research/CF/product_registry/CF_product_research_registry_manifest.json`
- `data/research/CF/product_registry/CF_factor_registry_snapshot.csv`
- `reports/research/product_registry/CF_product_research_registry.md`

## 固化内容

- 产品：CF
- 交易所：CZCE
- 频率：daily
- signal object：CF.C1
- universe：CF_MAIN
- 合约乘数：5
- 交割月份：1/3/5/7/9/11
- 最后交易日规则：delivery_month_10th_trading_day
- 期货因子：
  - `mom_20_v1`
  - `carry_nf_v1`
  - `curve_slope_v1`
  - `oi_pressure_v1`
- 期权 proxy：
  - `option_atm_iv_proxy_v1`
  - `option_iv_rank_proxy_v1`
  - `option_pcr_volume_v1`
  - `option_pcr_oi_v1`
  - `option_skew_proxy_v1`
  - `option_liquidity_score_v1`

## 边界

- 期权 proxy 属于 R48/R49 过滤层，不进入旧的 `research_factor_value_daily`。
- 研究函数仍只能读取 core/research 标准化表，不直接读取交易所 raw 文件。
- R50 不启动 SR/AP 或其他品种生产接入。
- 本快照不构成交易指令。

## 命令

```powershell
$env:PYTHONPATH="src"; py -3.12 -m cotton_factor.cli.main research build-cf-product-research-registry --output-dir data/research/CF/product_registry --report-output-dir reports/research/product_registry
```
