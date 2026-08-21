# 指标计算规则

## 原则

1. 每个指标必须登记定义、单位、频率、原始来源、发布时间与可得时间。
2. 历史值、实时值、修订值和预测值分开存储。
3. 不把报告发布日期当作数据截止日。
4. 相关性指标不得自动转写为因果关系。
5. 现券、期货、曲线、期限利差、跨期价差、基差、净基差、CTD、IRR和Carry使用独立字段与单位。

## CFFEX可交割券长表

必需字段：`product, contract_code, bond_code, conversion_factor, valid_from, source_snapshot_id`。

转换因子必须按实际 `contract_code` 查找，禁止从Excel固定行或固定 `cf_2609/cf_2612/cf_2703` 列读取。官方页面的完整HTML或表格快照、抓取时间和SHA-256均为晋升前置条件。

## 主力合约

按产品分别保存 `active_contracts={TS,TF,T,TL}`。人工覆盖必须记录来源、理由、操作者和有效期。

## 数据晋升门

新数据入口必须从单一冻结run manifest读取精确输入。没有完整CFFEX快照、动态转换因子、单writer锁、原子更新 `CURRENT.json` 或回归校验时，只允许 `no-fetch/no-promote/no-publish` 演练。
