# 全市场价值质量聚宽黄金对照

## 事实

- 状态：failed；逐项检查：{'joinquant_candidate_dates_complete': True, 'joinquant_holding_dates_complete': True, 'candidate_overlap_at_least_80_percent': False, 'holding_overlap_at_least_80_percent': False, 'annualized_difference_at_most_3pp': False, 'drawdown_difference_at_most_3pp': False, 'initial_cash_matches_platform': True, 'platform_source_matches_prepared_strategy': True}。
- 聚宽运行：https://www.joinquant.com/algorithm/backtest/detail?backtestId=c29fcd867c0701ef9254567a93475cef；初始资金
  10,000,000 元；平台实际源码与准备源码一致：
  True。
- 聚宽目标日志 54/
  54 个调仓日；持仓日志
  54/54 个调仓日。
- 目标平均重合率 60.46%；实际持仓平均重合率
  60.39%；下单证券平均重合率
  59.21%。
- 本地年化 11.61%，聚宽年化 17.26%，
  差 -5.65%。
- 本地最大回撤 31.03%，聚宽最大回撤
  26.97%，差 +4.06%。

## 判定

54 个调仓日必须完整；目标和持仓平均重合率均至少 80%；年化和最大回撤绝对差均不超过
3 个百分点。任一失败都保留归档并继续定位，不能以本地预检代替聚宽黄金对照。

## 诊断

- 紧凑日志免费取得 54/54 个月，证明 v1 约 62% 的共同月份重合并非日志截断假象。
- 目标层在下单前已经只有 60.46% 重合；平台 28 条整数手、资金或最小 200 股相关
  订单错误不足以解释约 40% 的目标差异。
- 首要嫌疑是聚宽与东方财富的 PE/PB/PS、指标报告期、累计经营现金流及历史申万行业
  语义不同，而不是日线撮合器本身。

## 下一步

以 54 个月聚宽目标作为只读黄金标签，在本地逐项替换估值、财务报告期和行业语义，
记录每个字段对重合率的边际影响；在形成明确口径修复前不继续消耗聚宽运行额度。
