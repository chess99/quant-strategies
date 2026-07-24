# 回测归档

已完成归档：

- [`2026-07-24__baseline__local-qlib-2019-2025-v1/`](2026-07-24__baseline__local-qlib-2019-2025-v1/)：本地 Qlib 日线回测，2019—2025，固定基线参数。
- [`2026-07-24__ktv-entry-only__local-qlib-2019-2025-v1/`](2026-07-24__ktv-entry-only__local-qlib-2019-2025-v1/)：买入端移除 MACD 确认。
- [`2026-07-24__macd-entry-only__local-qlib-2019-2025-v1/`](2026-07-24__macd-entry-only__local-qlib-2019-2025-v1/)：买入端移除 KTV 确认。
- [`2026-07-24__left-only__local-qlib-2019-2025-v1/`](2026-07-24__left-only__local-qlib-2019-2025-v1/)：只允许完整双指标左侧入场。
- [`2026-07-24__right-only__local-qlib-2019-2025-v1/`](2026-07-24__right-only__local-qlib-2019-2025-v1/)：只允许完整双指标右侧入场。

五组结果的统一口径比较与研究结论见
[`2026-07-24__entry-ablation-study.md`](2026-07-24__entry-ablation-study.md)。

右侧信号第二层诊断：

- [`2026-07-24__right-only-attribution__local-qlib-2019-2025-v1/`](2026-07-24__right-only-attribution__local-qlib-2019-2025-v1/)：基准成本精确复现，并增加逐回合退出归因。
- [`2026-07-24__right-no-volume__local-qlib-2019-2025-v1/`](2026-07-24__right-no-volume__local-qlib-2019-2025-v1/)：右侧信号移除成交额过滤。
- [`2026-07-24__right-no-trend__local-qlib-2019-2025-v1/`](2026-07-24__right-no-trend__local-qlib-2019-2025-v1/)：右侧信号移除均线趋势过滤。
- [`2026-07-24__right-only-zero-cost__local-qlib-2019-2025-v1/`](2026-07-24__right-only-zero-cost__local-qlib-2019-2025-v1/)：零成本敏感性。
- [`2026-07-24__right-only-double-cost__local-qlib-2019-2025-v1/`](2026-07-24__right-only-double-cost__local-qlib-2019-2025-v1/)：双倍成本敏感性。

统一诊断与结论见
[`2026-07-24__right-only-diagnostics-study.md`](2026-07-24__right-only-diagnostics-study.md)。

最终路径诊断：

- [`2026-07-24__right-only-trade-paths.csv`](2026-07-24__right-only-trade-paths.csv)：770个持仓回合的 MFE、MAE、入场特征和退出后10日路径。
- [`2026-07-24__right-low-extension__local-qlib-2019-2025-v1/`](2026-07-24__right-low-extension__local-qlib-2019-2025-v1/)：保持信号不变，反转 MA20/MA60 趋势间距排序。
- [`2026-07-24__right-only-path-study.md`](2026-07-24__right-only-path-study.md)：路径诊断、排序控制和停止继续调参的证据。

后续聚宽或本地回测继续新建：

```text
YYYY-MM-DD__{variant}__{run-id}/
  manifest.json
  report.md
  source.py
  raw/
  assets/
```

`source.py` 必须是平台实际运行的精确源码，而不是事后修改的 `baseline.py`。失败或不理想的实验也应归档，已有归档不得覆盖。
