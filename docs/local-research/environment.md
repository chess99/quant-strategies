# 本地研究环境

研究环境固定为 Windows x86-64、CPython 3.12.9，并与 Anaconda base 的
`site-packages` 隔离。仓库中的锁文件是
`requirements/research-win-py312.lock`；顶层依赖来源是
`requirements/research-win-py312.in`。

从空目录重建并完成环境自检、全仓测试、仓库验证和 Ruff：

```powershell
powershell -ExecutionPolicy Bypass -File tools\rebuild_research_env.ps1 `
  -EnvDir D:\code\_open-source\_venvs\quant-research-py312
```

脚本拒绝覆盖已有目录，避免误删环境。若要重建，传入一个新的空路径，验证通过后再由
用户自行移除旧环境。

环境包含 Qlib、AkShare、TA-Lib、LightGBM、XGBoost、CVXPY、Optuna 和 PyTorch。
`tools/verify_research_environment.py` 会核对 Python 与包版本、确认 Anaconda base
包目录没有泄漏，检查所有顶层包能在同一进程加载，并实际运行每个关键计算库的小型
工作负载。它还逐项比较锁文件与环境内全部已安装 distribution；缺包、多包或任一
传递依赖版本漂移都会失败。机器可读验证结果默认写入
外部数据目录 `D:/code/_open-source/_data/quant-research/environment/verification.json`。
仓库内的脱敏验收摘要见 `environment-verification.json`。

首次验收发现 PyArrow 14.0.2 在 Windows 下先于 CVXPY/OSQP 加载时会导致原生访问
冲突，因此最终锁定 PyArrow 19.0.1，并把“所有顶层依赖在同一进程依次导入”纳入
验证器，防止通过调整导入顺序掩盖 DLL 冲突。PyTorch 固定为 2.6.0 CPU 构建，
运行时版本字符串为 `2.6.0+cpu`。

更新依赖时必须同时：

1. 修改 `.in` 和 `expected.json`。
2. 在 CPython 3.12.9 的隔离环境中重新生成 lock。
3. 从新的空环境运行重建脚本。
4. 提交 lock、验证代码和验证摘要；不得只修改 `pyproject.toml`。
