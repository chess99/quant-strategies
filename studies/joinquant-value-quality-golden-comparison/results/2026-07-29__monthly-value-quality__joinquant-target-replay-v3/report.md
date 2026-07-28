# 全市场价值质量聚宽黄金对照

## 事实

- 状态：failed；逐项检查：{'joinquant_candidate_dates_complete': True, 'joinquant_holding_dates_complete': True, 'candidate_overlap_at_least_80_percent': False, 'holding_overlap_at_least_80_percent': True, 'annualized_difference_at_most_3pp': True, 'drawdown_difference_at_most_3pp': True, 'initial_cash_matches_platform': True, 'platform_source_matches_prepared_strategy': True}。
- 聚宽运行：https://www.joinquant.com/algorithm/backtest/detail?backtestId=c29fcd867c0701ef9254567a93475cef；初始资金
  10,000,000 元；平台实际源码与准备源码一致：
  True。
- 聚宽目标日志 54/
  54 个调仓日；持仓日志
  54/54 个调仓日。
- 目标平均重合率 60.46%；实际持仓平均重合率
  99.55%；下单证券平均重合率
  99.42%。
- 本地年化 15.25%，聚宽年化 17.26%，
  差 -2.01%。
- 本地最大回撤 28.35%，聚宽最大回撤
  26.97%，差 +1.38%。

## 判定

54 个调仓日必须完整；目标和持仓平均重合率均至少 80%；年化和最大回撤绝对差均不超过
3 个百分点。任一失败都保留归档并继续定位，不能以本地预检代替聚宽黄金对照。
