# 回测归档

已完成归档：

- [`2026-07-24__baseline__local-qlib-2019-2025-v1/`](2026-07-24__baseline__local-qlib-2019-2025-v1/)：本地 Qlib 日线回测，2019—2025，固定基线参数。
- [`2026-07-24__ktv-entry-only__local-qlib-2019-2025-v1/`](2026-07-24__ktv-entry-only__local-qlib-2019-2025-v1/)：买入端移除 MACD 确认。
- [`2026-07-24__macd-entry-only__local-qlib-2019-2025-v1/`](2026-07-24__macd-entry-only__local-qlib-2019-2025-v1/)：买入端移除 KTV 确认。
- [`2026-07-24__left-only__local-qlib-2019-2025-v1/`](2026-07-24__left-only__local-qlib-2019-2025-v1/)：只允许完整双指标左侧入场。
- [`2026-07-24__right-only__local-qlib-2019-2025-v1/`](2026-07-24__right-only__local-qlib-2019-2025-v1/)：只允许完整双指标右侧入场。

五组结果的统一口径比较与研究结论见
[`2026-07-24__entry-ablation-study.md`](2026-07-24__entry-ablation-study.md)。

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
