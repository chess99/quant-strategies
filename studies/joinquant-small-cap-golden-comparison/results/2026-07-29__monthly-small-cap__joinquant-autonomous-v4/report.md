# 全市场小市值聚宽黄金对照

## 事实

- 状态：passed；逐项检查：{'joinquant_candidate_dates_complete': True, 'joinquant_holding_dates_complete': True, 'candidate_overlap_at_least_80_percent': True, 'holding_overlap_at_least_80_percent': True, 'annualized_difference_at_most_3pp': True, 'drawdown_difference_at_most_3pp': True, 'initial_cash_matches_platform': True, 'platform_source_matches_prepared_strategy': True}。
- 聚宽运行：https://www.joinquant.com/algorithm/backtest/detail?backtestId=fd4f04ed4711b333961fec6244c16e84；本次只复用已归档日志，
  没有新增平台运行或额度消耗。
- 聚宽候选日志 54/
  54 个调仓日；持仓日志
  54/54 个调仓日。
- 自主目标候选平均重合率 100.00%；实际持仓平均重合率
  98.70%；下单证券平均重合率
  98.59%。
- 本地年化 12.51%，聚宽年化 12.06%，
  差 +0.45%。
- 本地最大回撤 47.56%，聚宽最大回撤
  48.02%，差 -0.46%。

## 判定

完成要求是候选和持仓重合率均至少 80%，年化及最大回撤绝对差均不超过 3 个百分点，
且 54 个调仓日的结构化日志完整。本归档使用本地自主选股结果，不使用聚宽目标覆盖。
