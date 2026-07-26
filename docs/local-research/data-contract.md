# 本地研究数据契约

## 日期语义

| 字段 | 含义 |
|---|---|
| `trade_date` | 行情、估值或交易状态所属交易日 |
| `start_date` / `end_date` | 证券或成员关系生效的闭区间 |
| `listing_date` / `delisting_date` | 正式上市、退市日期；来源期末仍有效时退市日为空 |
| `report_date` | 财务报告期末日 |
| `notice_date` | 当时投资者最早可观察到该记录的公告日 |
| `effective_from` / `effective_to` | 行业、名称或状态的点时生效闭区间 |
| `ingested_at` | 本地抓取或导入时间，不等同于业务可见时间 |

策略在交易日计算信号时默认使用前一交易日作为观察日。财务记录必须满足
`notice_date <= observation_date`；证券、指数成分、行业和状态必须落在对应生效区间。

## 质量等级

- `A`：严格点时数据；保留当时可见版本或官方不可变历史记录。
- `B`：业务日期和公告日正确，但历史修订可能被后来版本回填，适合研究级回测。
- `C`：当前分类、推导状态或其他代理，只允许探索；正式回测必须显式放宽要求。

等级只表示点时与来源质量，不表示策略收益可信。一个数据集的有效质量是所有字段中
最低的等级。

## 证券主表

必需字段：

```text
symbol, exchange, asset_type, board, start_date, end_date,
listing_date, delisting_date, active_at_source_end,
canonical_symbol, lifecycle_status, lifecycle_quality, lifecycle_source,
display_name, quality_grade, source
```

统一代码使用 Qlib 风格，例如 `SH600000`、`SZ000001`、`SH510300`。聚宽兼容层负责
转换为 `600000.XSHG` 等平台代码。

Qlib 的 `end_date` 对当前证券表示来源快照的最后覆盖日，不可误当退市日。
`active_at_source_end=true` 时 `delisting_date` 必须为空；只有来源期末前已终止的
证券才填写退市日。

生命周期由交易所当前名单、沪深退市名单、北交所 `920` 换码规则和少量显式换码
事件共同校正。`canonical_symbol` 将旧代码指向当前代码，但历史行情仍保留在旧代码
下。生命周期质量低于策略要求时同样触发质量门禁。

## 日线行情

规范字段：

```text
symbol, trade_date, open, high, low, close, volume, amount,
factor, vwap, source, quality_grade
```

- `open/high/low/close` 默认保存原始价格；调整价由价格和 `factor` 明确计算。
- `amount` 统一为人民币元；来源为千元时必须在适配器转换。
- 缺失交易日不自动解释为停牌，必须与交易状态数据联合判断。

## 财务与估值

财务表保留原始报告期、报告类型、公告日和提供者记录 ID。累计利润表与单季度值分开，
禁止在同一字段混用。估值字段按交易日记录，市值统一为人民币元。

## 数据清单

每个规范化数据集必须有 JSON 清单，至少记录：

```text
schema_version, dataset, provider, quality_grade, created_at,
row_count, columns, date_range, data_files, sha256, source_files, notes
```

第二版清单还记录：

```text
primary_key, date_fields, partitioning, coverage, failures, limitations, checks
```

清单中的 SHA-256 用于发现数据漂移；旧研究归档引用精确清单哈希，不引用 `latest`。

## 分区规范

- 百万行级或会持续增长的日频事实表必须按 `year=YYYY/` 或
  `symbol=SH600000/` 分区，文件为 Parquet。
- 分区信息同时写入清单的 `partitioning` 和每个 `data_files[].partition_values`。
- 构建器逐证券或逐年写入，禁止把全市场几十年历史一次放入内存。
- 证券主表、交易日历等小型维表可保存为单个 Parquet。
- 原始下载保持不可变；规范化分区可以由相同来源版本确定性重建。

## 质量门禁与全量审计

策略通过 `require_quality(dataset, actual, minimum)` 声明最低等级；C 级代理不满足
B 级要求时直接抛出 `DataQualityError`。

`tools/build_local_data_foundation.py` 会重建证券主表和交易日历，并生成
`manifests/platform_coverage.json`。审计逐证券流式读取 Qlib 二进制，逐批读取
Parquet，检查文件哈希、行数、主键排序与重复、未知证券、时间倒置、公告日早于
报告期、证券有效期越界、OHLC、复权因子和异常收益。异常收益只报告不自动删除，
因为注册制新股首日可能合法超过常规涨跌幅。
