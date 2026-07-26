# 统一数据接口与聚宽兼容层

`LocalDataPortal` 是策略与底层数据源之间的稳定边界。所有点时查询都要求观察日，数据集
低于策略声明的最低质量时直接拒绝，不做静默补零或用当前状态回填历史。

## 本地接口

- `calendar`：交易日历。
- `instruments`：观察日仍有效的证券。
- `bars`：原始价或前复权日线。
- `index_members`：观察日历史指数成分。
- `market_snapshot`：停牌、ST、涨跌停和原始收盘价。
- `valuation`：观察日之前最近且未过期的日估值。
- `fundamentals`：按公告日可见的最新财务记录；第六轮接入数据。
- `industry`：历史行业有效区间；第六轮接入数据。

Qlib 日线适配器把成交量从“手”统一为“股”。`raw` 返回不复权价格；`pre` 以请求区间
最后一个交易日为锚点计算前复权价。当前不接受分钟频率和后复权语义。

## 聚宽薄兼容

`JoinQuantCompat` 提供 `get_price`、`attribute_history`、`get_all_securities`、
`get_index_stocks`、`get_current_data`、`get_fundamentals` 和 `get_industry`。
它用于降低策略迁移成本，并不伪装成完整的聚宽运行时：

- 运行前必须固定 `observation_date`，或给查询传显式日期。
- 多证券 `get_price` 使用 `(trade_date, symbol)` MultiIndex，不复刻旧版 Panel。
- `get_current_data()` 是按代码加载的映射，要求 `current_data[code]`，故意拒绝 `.get()`。
- 不支持的数据和字段抛出 `CapabilityError`，质量不足抛出 `DataQualityError`。

历史沪深300、中证500、中证1000、中证800和中证全指成分区间由 Qlib 文件导入，质量 B。
这能避免使用当前成分解释历史，但尚未与指数公司公告逐次核验。
