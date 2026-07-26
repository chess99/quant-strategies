# 变体

本策略族的比较变体当前由 `local_backtest.py` 中的固定模型配置实现。它们共享同一
点时财务、历史指数成分、次日开盘撮合和成本假设，避免因复制多个平台文件产生公式漂移。

| 变体 | 单一目的 | 状态 |
|---|---|---|
| `growth-new-high-simple` | 朴素“业绩增长 + 新高”对照 | archived |
| `huachuang-2019-available` | 复刻华创2019可观察条件 | baseline |
| `huachuang-2-lite` | 复刻华创2.0的盈利与动量横截面 | archived |
| `huachuang-2-risk-scaled` | 2.0选股不变，仅增加200日均线仓位覆盖 | archived |
| `shenwan-2018-lite` | 复刻申万基底、动量、营收与市场过滤 | archived |
| `a-share-adaptive` | 取消五年路径，使用当季增长与动量 | archived-failed |
| `a-share-cycle-turnaround` | 显式识别亏损转盈利 | archived-failed |

缺失基金持仓、北向持股、业绩预告/快报和分析师一致预期的版本一律使用
`available` 或 `lite` 命名，不冒充券商原报告的精确复刻。

