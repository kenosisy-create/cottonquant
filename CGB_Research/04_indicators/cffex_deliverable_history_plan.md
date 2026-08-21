# 中金所可交割券与转换因子历史链路方案

## 1. 结论

不建议让用户人工汇总历年招商周报作为主数据源。中金所官网已经公开当前总表、逐合约CSV/XML以及历年交易所通知，可以构建三层数据：当前官方截面、历史合约最终篮子、按发布日期重建的时点事件账本。招商周报只用于抽样复核或补充官方旧附件无法访问的极少数缺口。

本方案不改变国债期货主力合约，不修改 `CURRENT.json`，也不启用生产发布。

## 2. 官方数据入口

- 可交割国债页面：`http://www.cffex.com.cn/kjggzxx/`
- 页面使用的脚本：`http://www.cffex.com.cn/r/cms/www/default/js/kjggzxx.js`
- 当前全部产品和合约总表：`http://www.cffex.com.cn/sj/jgsj/jgqsj/index_6882.csv`
- 逐合约CSV：`http://www.cffex.com.cn/sj/jgsj/jgqsj/{contract_code}/{contract_code}.csv`
- 逐合约XML：`http://www.cffex.com.cn/sj/jgsj/jgqsj/{contract_code}/index_1.xml`
- 交易所通知归档：`http://www.cffex.com.cn/jystz/`，后续分页为 `jystz_2.html` 等。

当前页面脚本明确使用总表CSV和逐合约XML/CSV。原始HTML、脚本、CSV和XML均应保存不可变字节快照及SHA-256，不能只保存解析后的行数。

## 3. 三层数据模型

### 3.1 当前官方截面

用途：周报当期CTD、IRR、基差、净基差和成交量候选券筛选。

流程：

1. 保存页面HTML、页面脚本和官方总表CSV。
2. 从总表取得TS、TF、T、TL当前展示的三个季月合约。
3. 逐合约下载CSV和XML。
4. 验证总表等于12份逐合约CSV的并集。
5. 转成长表，主键为 `product + contract_code + bond_code`。
6. `valid_from`暂留空，`observed_on`记录快照日期。

### 3.2 历史合约最终篮子

用途：历史合约研究、合约间可交割券集合比较、旧周报回溯。

按季度枚举合约代码并请求逐合约CSV：

- TF：从TF1312开始；
- T：从T1509开始；
- TS：从TS1812开始；
- TL：从TL2306开始。

成功响应保存原始字节；404或空响应也写入请求日志。逐合约文件可恢复该合约最终纳入的债券和转换因子，但不能单独证明某只券首次纳入的日期。

### 3.3 按时点可复原的事件账本

用途：无前视偏差回测，以及回答“某周当时有哪些券已经可交割”。

自动遍历中金所交易所通知分页，只保留以下标题：

- `关于发布国债期货合约可交割国债的通知`；
- `关于增加…年期国债期货合约可交割国债的通知`；
- `国债期货新合约上市通知`。

事件表建议字段：

`event_id, notice_date, effective_date, event_type, product, contract_code, bond_code, conversion_factor, notice_url, attachment_url, raw_sha256, extraction_status, review_status`

按 `effective_date <= as_of_date` 累积初始发布和新增事件，即可重建任一历史日期的篮子。若通知只有发布日期而未明确生效日，保留 `[U]`，不得自行用发布日期替代。

## 4. 主力合约与转换因子分离

可交割券篮子回答“某实际合约有哪些合格券”；主力合约回答“研究周应关注哪个合约”。二者不得混为一张静态Excel表。

- `active_contracts={TS,TF,T,TL}` 由成交量、持仓量和换月规则分别判定；
- 转换因子严格按 `product + contract_code + bond_code` 查询；
- 禁止读取固定列 `cf_2609/cf_2612/cf_2703`；
- 人工覆盖主力合约时必须记录来源、理由和有效期。

## 5. 验收门槛

1. 当前总表与逐合约CSV并集完全一致。
2. 四个产品均存在，每个产品当前展示三个季月合约。
3. 主键无重复，转换因子为可解析数值。
4. 原始文件SHA、抓取时间、URL、编码和HTTP元数据进入manifest。
5. 至少选择一个正常周和一个换月周回归验证TS、TF、T、TL。
6. 当前截面完成不等于历史时点完成；事件账本未完成前，历史回测不得标记为无前视偏差。
7. CFFEX校验通过仍不代表可以发布；冻结run manifest、单writer锁和原子发布必须独立通过。

## 6. 何时才需要用户提供旧周报

只有同时满足以下条件时才请求人工材料：

1. 官方逐合约文件不可访问；
2. 官方通知正文和附件均无法恢复；
3. iFinD或其他机器可读来源也无法交叉验证；
4. 该缺口会实际影响研究期内CTD、IRR或基差结论。

届时只需汇总最小字段：`周报日期、产品、实际合约、债券代码、转换因子、原表页码或截图`，无需人工抄录整张历史表。
