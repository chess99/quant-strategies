# 实验变体

参数与模块实验由 `local_backtest.py` 的显式配置矩阵生成。在样本外证据充分前，不把任何历史最优组合复制成聚宽变体，也不替换 baseline。

## conditional-momentum-overlay-v2

- 状态：完整实验已结束，仅通过 2/8 项预注册标准；拒绝提升为 baseline，保留为冻结研究变体。
- 核心变化：从“整个组合由轮动决定”改为“40/40/20 股债黄金战略底仓 + 最多 30% 条件式动量增强”。
- 冻结入口：`../protocols/2026-08-16-v2-conditional-overlay.json`。
- 平台文件在本地完整矩阵结束后创建；聚宽 Research 与官方 10:30 配对结果都确认 v2 相对同平台底仓为负。
- 研究归档：`../backtests/2026-08-16__conditional-momentum-overlay-v2__local-jq-2014-2026-v1/report.md`。
