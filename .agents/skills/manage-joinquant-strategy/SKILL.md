---
name: manage-joinquant-strategy
description: Create, modify, test, organize, and archive JoinQuant strategy families in this repository. Use when adding a new quantitative strategy, creating a small variant, changing a JoinQuant-compatible Python strategy, importing a backtest result, or reviewing whether strategy artifacts follow repository conventions.
---

# 管理聚宽量化策略

## 准备

1. 从仓库根目录开始工作。
2. 完整读取 `AGENTS.md`。
3. 完整读取 `docs/architecture/repository-layout.md`。
4. 涉及聚宽源码时完整读取 `docs/platforms/joinquant/pitfalls.md`。
5. 运行 `python tools/validate_repo.py`，确认基线状态。

## 判断落点

- 核心投资假设未变：在现有策略族中修改 `baseline.py` 或新增 `variants/{slug}.py`。
- 仅用于实验且尚未证明优于基线：新增变体，不替换基线。
- 市场、数据模型或投资假设根本变化：从 `templates/strategy-family/` 新建策略族。
- 回测使用的源码与当前工作源码不同：仍按实际运行源码归档为 `source.py`。

## 修改策略

1. 先在策略族 `README.md` 写清假设、变更点和成功标准。
2. 先添加或修改 `tests/`，覆盖纯函数、平台兼容性和关键执行路径。
3. 保持每个聚宽 `.py` 文件自包含。
4. 禁止未来数据、当前成分股倒推、无日期财务查询和未限定的 `sum/all/any`。
5. 运行策略族测试，再运行全仓测试。

## 创建变体

1. 使用可描述假设的 kebab-case 名称。
2. 从实际基线复制为完整可运行文件。
3. 只修改该实验需要的逻辑，避免同时改变多个维度。
4. 在策略族 `README.md` 的变体表记录差异和状态。
5. 不把尚未经过样本外或滚动验证的变体提升为基线。

## 归档回测

1. 新建 `backtests/YYYY-MM-DD__{variant}__{run-id}/`。
2. 将平台实际运行源码保存为 `source.py`。
3. 创建 `manifest.json`，记录来源、区间、成本、指标和 `source_sha256`。
4. 创建 `report.md`，记录分阶段结果、风险、限制、失败点和下一步实验。
5. 将可用原始文件放进 `raw/`，截图放进 `assets/`。
6. 不修改既有回测目录。

## 验证和提交

依次运行：

```bash
pytest -q
python tools/validate_repo.py
git diff --check
```

只暂存本次文件，检查 `git diff --staged` 后提交。
