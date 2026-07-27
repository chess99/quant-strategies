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

`CompositeDailyBarSource` 按证券主表路由：股票和指数走 Qlib，ETF 走迭代 2 的
`etf_daily` 分区。所有分区查询只读取 manifest 中列出的目标证券文件，不会误读失败
代码遗留的陈旧分区，也不会一次装入全市场历史。

DataFrame 返回值在 `attrs["quant_research_provenance"]` 保存数据集、来源、质量、manifest
路径及 SHA-256；列表和惰性对象可通过 `portal.last_query_provenance` 或
`api.last_query_provenance` 追溯。复合行情同时列出实际命中的 Qlib/ETF 子来源。Qlib
行情用交易日历与证券清单内容哈希形成 `data_version`，并绑定最近一次全平台审计报告
SHA-256；不再只返回无法复现的“Qlib/B级”标签。

## 聚宽薄兼容

`JoinQuantCompat` 提供 `get_price`、`attribute_history`、`history`、`get_all_securities`、
`get_index_stocks`、`get_current_data`、`get_fundamentals` 和 `get_industry`。
它用于降低策略迁移成本，并不伪装成完整的聚宽运行时：

- 运行前必须固定 `observation_date`，或给查询传显式日期。
- 多证券 `get_price` 使用 `(trade_date, symbol)` MultiIndex，不复刻旧版 Panel。
- 接受 `000300.XSHG`、`000001.XSHE`、`920xxx.XBSE` 并与本地 `SH/SZ/BJ` 双向转换。
- `get_price(count=...)`、`panel=False`、`fill_paused` 和 `history(..., df=True/False)`
  覆盖源码中最常见的日频形式；`panel=True` 明确报错。
- `get_current_data()` 是按代码加载的映射，要求 `current_data[code]`，故意拒绝 `.get()`。
- 不支持的数据和字段抛出 `CapabilityError`，质量不足抛出 `DataQualityError`。

历史沪深300、中证500、中证1000、中证800和中证全指成分区间由 Qlib 文件导入，质量 B。
这能避免使用当前成分解释历史，但尚未与指数公司公告逐次核验。

## 源码覆盖与 query DSL

`jq-api-coverage.json` 是对 593 个本地源码文件的 AST 审计：576 个可解析文件中，目标
八类 API 共 4,135 次调用，3,633 次可直接兼容（87.86%），502 次需要显式迁移。
其中 481 次来自 `get_fundamentals(query(...))`。

本地不模拟聚宽动态字段对象和 SQL 式 query DSL。迁移方式固定为：

```python
api.get_fundamentals(
    symbols,
    fields=["revenue", "parent_net_profit", "roe"],
    date=observation_date,
)
```

传入 query 对象或 `statDate` 会抛出 `CapabilityError`，不会猜测字段、静默补零或使用当前
财务。17 个本身语法残缺的源码单独记录在报告中，不计为已验证兼容。

三类真实数据端到端验收位于
`studies/joinquant-api-compat-validation/results/2026-07-27__three-strategy-migration__v4/`：
同一兼容层运行指数择时、四 ETF 轮动和公告日基本面质量筛选，五项机器检查全部通过。
v1 的归档器异常与 v2 的失败验收也保留，未覆盖成成功结果。
