# 变体

变体必须是可直接复制到聚宽运行的完整单文件，不得依赖 `baseline.py` 导入。

建议先做能够回答独立问题的消融变体：

| 变体 | 只改变什么 | 状态 |
|---|---|---|
| `left-only` | 只允许左侧低位共振开仓 | planned |
| `right-only` | 只允许右侧趋势中继开仓 | planned |
| `ktv-only` | 移除 MACD 确认 | planned |
| `macd-only` | 移除 KTV 确认 | planned |
| `no-volume-filter` | 移除温和放量条件 | planned |

不要在同一变体里同时更换公式、股票池、周期和风控，否则结果无法归因。
