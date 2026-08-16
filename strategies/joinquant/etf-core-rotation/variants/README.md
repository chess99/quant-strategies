# 实验变体

参数与模块实验由 `local_backtest.py` 的显式配置矩阵生成。在样本外证据充分前，不把任何历史最优组合复制成聚宽变体，也不替换 baseline。

## conditional-momentum-overlay-v2

- 状态：预注册，尚未提升为 baseline。
- 核心变化：从“整个组合由轮动决定”改为“40/40/20 股债黄金战略底仓 + 最多 30% 条件式动量增强”。
- 冻结入口：`../protocols/2026-08-16-v2-conditional-overlay.json`。
- 平台文件只有在本地完整矩阵完成后才创建；即使历史结果较好，也必须先保留为 `variants/` 下的研究变体。
