# 变体

本目录中的每个 Python 文件都能独立复制到聚宽运行，不依赖仓库模块。

| 文件 | 变体名 | 差异 | 状态 |
|---|---|---|---|
| `macd_binary.py` | `macd-binary` | 固定 MACD(12,26,9)，0%/99%二元仓位 | research |
| `balanced_ensemble.py` | `balanced-ensemble` | 风险核心、MACD覆盖和Keltner覆盖固定等权，10个百分点阈值 | research |

基线见上级目录 `baseline.py`。变体的本地历史指标只用于校验实现；完成聚宽回测后另建不可变
归档，不能把本地结果直接登记为平台结果。
