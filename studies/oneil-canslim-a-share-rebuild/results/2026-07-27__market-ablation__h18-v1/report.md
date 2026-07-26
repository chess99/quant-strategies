# h18 市场风险层独立消融

所有模型共享同一 h18 候选、直接买入、月度持有、成本与撮合。市场状态只使用月末
观察日已知的跨指数 200 日线和全 A 宽度。

| 阶段 | 模型 | 年化 | 年化超额 | 最大回撤 | Sharpe | Calmar |
|---|---|---:|---:|---:|---:|---:|
| development | market-control | 14.32% | 9.99% | 51.99% | 0.646 | 0.275 |
| selection-validation | market-control | 18.28% | 13.96% | 36.52% | 0.771 | 0.501 |
| full | market-control | 15.62% | 11.30% | 51.99% | 0.688 | 0.301 |
| development | market-block-new | 6.05% | 1.73% | 44.49% | 0.417 | 0.136 |
| selection-validation | market-block-new | 7.54% | 3.23% | 23.36% | 0.512 | 0.323 |
| full | market-block-new | 6.55% | 2.23% | 44.49% | 0.448 | 0.147 |
| development | market-scale-50 | 9.65% | 5.33% | 48.31% | 0.547 | 0.200 |
| selection-validation | market-scale-50 | 12.40% | 8.08% | 21.40% | 0.708 | 0.579 |
| full | market-scale-50 | 10.56% | 6.24% | 48.31% | 0.597 | 0.219 |
| development | market-cash | 3.22% | -1.10% | 41.95% | 0.270 | 0.077 |
| selection-validation | market-cash | 2.90% | -1.42% | 16.57% | 0.267 | 0.175 |
| full | market-cash | 3.11% | -1.21% | 41.95% | 0.268 | 0.074 |
