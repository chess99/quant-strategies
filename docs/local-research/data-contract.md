# 本地研究数据契约

## 日期语义

| 字段 | 含义 |
|---|---|
| `trade_date` | 行情、估值或交易状态所属交易日 |
| `start_date` / `end_date` | 证券或成员关系生效的闭区间 |
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
display_name, quality_grade, source
```

统一代码使用 Qlib 风格，例如 `SH600000`、`SZ000001`、`SH510300`。聚宽兼容层负责
转换为 `600000.XSHG` 等平台代码。

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

清单中的 SHA-256 用于发现数据漂移；旧研究归档引用精确清单哈希，不引用 `latest`。
