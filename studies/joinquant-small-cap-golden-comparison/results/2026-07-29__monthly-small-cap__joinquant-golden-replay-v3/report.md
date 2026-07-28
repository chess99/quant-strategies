# 全市场小市值聚宽黄金对照

## 事实

- 状态：passed；逐项检查：{'joinquant_candidate_dates_complete': True, 'joinquant_holding_dates_complete': True, 'candidate_overlap_at_least_80_percent': True, 'holding_overlap_at_least_80_percent': True, 'annualized_difference_at_most_3pp': True, 'drawdown_difference_at_most_3pp': True, 'initial_cash_matches_platform': True, 'platform_source_matches_prepared_strategy': True}。
- 聚宽运行：https://www.joinquant.com/algorithm/backtest/detail?backtestId=fd4f04ed4711b333961fec6244c16e84；初始资金
  10,000,000 元；平台实际源码与准备源码一致：
  True。
- 聚宽候选日志 54/
  54 个调仓日；持仓日志
  54/54 个调仓日。
- 目标候选平均重合率 95.93%；实际持仓平均重合率
  98.50%；下单证券平均重合率
  98.60%。
- 本地年化 13.03%，聚宽年化 12.06%，
  差 +0.97%。
- 本地最大回撤 47.34%，聚宽最大回撤
  48.02%，差 -0.68%。

## 判定

完成要求是候选和持仓重合率均至少 80%，年化及最大回撤绝对差均不超过 3 个百分点，
且 54 个调仓日的结构化日志完整。任何一项失败都保留本归档并继续定位，不能以聚合收益相近替代。
