# h18 持仓管理独立消融

选股、月度候选、直接入场、成本和撮合完全相同，只比较持仓管理。日频退出均使用
前一交易日收盘信号，在下一交易日开盘执行。

| 阶段 | 模型 | 年化 | 年化超额 | 最大回撤 | Sharpe | Calmar |
|---|---|---:|---:|---:|---:|---:|
| development | monthly-control | 14.32% | 9.99% | 51.99% | 0.646 | 0.275 |
| selection-validation | monthly-control | 18.28% | 13.96% | 36.52% | 0.771 | 0.501 |
| full | monthly-control | 15.62% | 11.30% | 51.99% | 0.688 | 0.301 |
| development | hard-stop-8pct | 12.50% | 8.18% | 46.18% | 0.653 | 0.271 |
| selection-validation | hard-stop-8pct | 9.50% | 5.18% | 38.54% | 0.513 | 0.247 |
| full | hard-stop-8pct | 11.49% | 7.17% | 46.25% | 0.605 | 0.248 |
| development | trend-exit-50d | 6.82% | 2.50% | 37.87% | 0.528 | 0.180 |
| selection-validation | trend-exit-50d | 2.52% | -1.80% | 21.98% | 0.242 | 0.115 |
| full | trend-exit-50d | 5.36% | 1.04% | 42.95% | 0.431 | 0.125 |
| development | winner-hold-50d | 6.39% | 2.07% | 41.10% | 0.483 | 0.156 |
| selection-validation | winner-hold-50d | 5.53% | 1.21% | 20.96% | 0.446 | 0.264 |
| full | winner-hold-50d | 6.10% | 1.78% | 43.74% | 0.471 | 0.140 |
