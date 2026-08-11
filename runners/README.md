# Research Runners

`runners/` 保存可复用、与具体投资逻辑无关的研究执行后端。策略事实源仍在
`strategies/{platform}/{strategy-family}/`，runner 只负责日历、撮合、账本和结果导出。

## 目录约定

```text
runners/
  {platform-runtime}/
    README.md
    {runtime_module}.py
    examples/
```

- 平台运行模块必须可直接上传、自包含，并兼容平台 Python 环境。
- 示例只演示接口，不作为策略事实源或业绩证据。
- runner 的本地测试统一放在 `tests/{platform_runtime}/`。
- 正式回测仍归档到对应策略族的 `backtests/`，同时保存 `source.py` 和 `engine.py`。

当前实现：

- `joinquant-research/`：在聚宽 Research 中使用 `jqdata` 执行日频和中低频目标权重策略。
