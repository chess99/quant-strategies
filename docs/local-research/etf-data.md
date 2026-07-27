# 场内 ETF 历史数据

## 已验收范围

迭代 2 的事实源由上交所、深交所、新浪、同花顺和东方财富交叉构建。候选池不是
“今天仍上市的 ETF”倒推历史：

- 上交所使用 2013 年以来的逐月官方规模快照恢复历史产品；
- 当前有效分母取交易所清单和新浪、同花顺有效交易清单的并集；
- 东方财富基金档案补充成立日期、基金类型和跟踪标的；
- 新浪逐只下载原始日线和累计分红；
- 每只候选都有 `success`、`empty` 或 `failed` 状态，空结果不会静默丢弃。

2026-07-27 全量验收得到 1,735 只候选、1,687 只有历史日线，共
1,493,394 行，日期覆盖 2005-02-23 至 2026-07-24。当前有效目标 1,618 只，
其中 1,608 只有日线，覆盖率 99.38%。另恢复 79 只已终止 ETF 的交易区间；
10 只新成立产品尚无新浪行情，38 只非当前候选得到明确空结果。

## 数据布局

```text
normalized/
  etf_candidates/data.parquet
  etf_daily/symbol=SH510300/data.parquet
  etf_master/data.parquet
  etf_profiles/data.parquet
  etf_sync_status/data.parquet
manifests/
  etf_candidates.json
  etf_daily.json
  etf_master.json
  etf_profiles.json
  etf_coverage.json
```

日线按证券分区，研究代码应使用 `ResearchDataStore.read_symbol_partitions()` 只读所需
证券，不把全市场历史一次载入内存。原始行情、分红和档案分别不可变保存在
`raw/sina/` 与 `raw/eastmoney/`，manifest 保存逐文件 SHA-256。

## 更新与断点续跑

```powershell
D:\code\_open-source\_venvs\quant-research-py312\Scripts\python.exe `
  tools\sync_local_etf_daily.py `
  --stage all `
  --data-root D:\code\_open-source\_data\quant-research
```

同步器每 25 只更新一次 `etf_sync_status`。再次运行默认跳过行情与档案均成功的证券。
AkShare 的 JavaScript 运行库在 Windows 上不保证多线程重复初始化安全；若只重试少量
失败证券，使用 `--workers 1`。

## 质量等级与限制

- 成功日线和基金档案为 B 级：原始行情、分红和常见份额折算均有来源记录，但免费源
  不提供权威的完整公司行为因子。
- ETF 主表整体为 C 级，因为 38 只非当前候选没有可验证交易区间；这些记录只用于
  审计，不能进入要求 B 级的回测。
- 当前 10 只 `active_no_history` 产品已由当前清单和基金档案确认，但在行情出现前不能
  交易。
- 上交所历史快照从 2013 年开始；更早上市又在 2013 年前终止的短命产品仍可能遗漏。
- 深交所没有同等公开的按历史日期查询接口。当前已把所有候选逐只尝试并保留状态，
  但不能声称免费源给出了绝对完整的历史退市名录。

策略必须按 `listing_date`、`delisting_date` 和观察日期构造 ETF 池。只用当前有效池
回测历史会遗漏至少 79 只已恢复的终止产品，产生幸存者偏差。

## 黄金对照

完整归档位于
`studies/joinquant-etf-rotation-replication/results/2026-07-27__local-full-etf-universe-v2/`。
聚宽帖子公开结果接口提供 2,297 天的四条评分曲线和每日买卖总额，因此无需新跑聚宽
回测、也不消耗研究额度。

- 逐日目标兼容匹配率：100%（2,297/2,297）。
- 聚宽评分唯一最高日期严格匹配率：100%（2,217/2,217）。
- 订单事件日期 Jaccard：98.55%。
- 年化收益：聚宽 36.93%，本地 36.86%，差 -0.07 个百分点。
- 最大回撤：聚宽 30.61%，本地 30.61%。

唯一订单日期偏移发生在公开评分四舍五入后并列的相邻两天；聚宽不公开未舍入评分和
逐笔证券成交，因此保留为已解释差异。
