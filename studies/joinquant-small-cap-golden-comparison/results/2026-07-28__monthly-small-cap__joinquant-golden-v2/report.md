# 全市场小市值聚宽黄金对照

## 事实

- 状态：failed；逐项检查：{'joinquant_candidate_dates_complete': True, 'joinquant_holding_dates_complete': True, 'candidate_overlap_at_least_80_percent': True, 'holding_overlap_at_least_80_percent': False, 'annualized_difference_at_most_3pp': False, 'drawdown_difference_at_most_3pp': False, 'initial_cash_matches_platform': True, 'platform_source_matches_prepared_strategy': True}。
- 聚宽运行：https://www.joinquant.com/algorithm/backtest/detail?backtestId=fd4f04ed4711b333961fec6244c16e84；初始资金
  10,000,000 元；平台实际源码与准备源码一致：
  True。
- 聚宽候选日志 54/
  54 个调仓日；持仓日志
  54/54 个调仓日。
- 目标候选平均重合率 82.04%；实际持仓平均重合率
  77.87%；下单证券平均重合率
  79.03%。
- 本地年化 30.57%，聚宽年化 12.06%，
  差 +18.51%。
- 本地最大回撤 33.77%，聚宽最大回撤
  48.02%，差 -14.25%。

## 判定

完成要求是候选和持仓重合率均至少 80%，年化及最大回撤绝对差均不超过 3 个百分点，
且 54 个调仓日的结构化日志完整。任何一项失败都保留本归档并继续定位，不能以聚合收益相近替代。

## 诊断

- 相比 v1，保护限价使持仓重合率由 69.79% 提升到 77.87%，下单证券重合率由
  78.02% 提升到 79.03%，原科创板保护限价报错消失。
- 平台仍有 73 条订单错误，其中 24 条是停牌卖出失败；资金不足、整数手和科创板
  最小 200 股限制也产生拒单或调整。2020 年多个月份因此残留平台停牌持仓。
- 候选重合率仍只有 82.04%，所以剩余收益差不能只归因于撮合；点时市值排序和状态
  事实口径也是主要候选。

## 下一步

先用现有 54 个月候选和订单离线对齐市值排序、停牌残留及平台下单语义；只有产生
明确修复后才运行新的聚宽版本，不以重复运行代替诊断。
