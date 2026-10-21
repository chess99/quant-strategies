# 本地研究环境

## 安装与启动

统一使用 CPython 3.12.9，环境位于仓库根目录 `.venv/`，与系统 Python 和 Anaconda
隔离。依赖分别锁定 Windows x86-64、Linux x86-64 和 macOS Apple Silicon 的完整版本；
NumPy、pandas、Qlib、PyArrow 等核心库保持一致。

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。macOS 还需
安装 [Homebrew](https://brew.sh/) 并执行 `brew install libomp`，供 LightGBM、XGBoost
加载 OpenMP 运行库。然后在仓库根目录执行：

```bash
uv run --no-project --python 3.12.9 tools/rebuild_research_env.py
```

安装程序自动选择平台锁文件，下载指定 Python，创建 `.venv/`，安装依赖并执行计算库
验收、依赖兼容检查、全仓测试、仓库验证和静态检查。Linux 使用经过 SHA-256 校验的
PyTorch 2.6.0 CPU wheel，避免引入 CUDA/NCCL。macOS 使用原生 arm64 wheel。安装程序将 sklearn 和 PyTorch 自带的 OpenMP
运行库链接到 Homebrew 的同一份 `libomp`，保留原文件为 `.dylib.bundled`，并记录运行库
路径和 SHA-256。验收要求同进程只加载一份 OpenMP，避免混用模型库时出现卡住或崩溃。
Homebrew 升级 libomp 或手动重装这些 Python 包后，应重建研究环境并重新验收。

已有环境目录会被拒绝覆盖。重建时指定新路径，例如：

```bash
uv run --no-project --python 3.12.9 tools/rebuild_research_env.py --env-dir .venv-new
```

`tools/rebuild_research_env.sh` 和 `tools/rebuild_research_env.ps1` 是同一安装程序的
兼容入口。安装完成后，macOS/Linux 使用：

```bash
source .venv/bin/activate
```

Windows PowerShell 使用：

```powershell
.venv\Scripts\Activate.ps1
```

激活后即可执行：

```bash
python -m jupyterlab
python tools/check_research_data.py
python -m pytest -q
python tools/validate_repo.py
```

安装程序在虚拟环境内添加源码搜索路径，命令行与 Jupyter 均可导入 `quant_research`。
仓库移动后需要重新创建虚拟环境。`.venv/` 含平台二进制和本机路径，各电脑独立安装。

## 数据目录

默认布局以仓库位置为基准，与启动命令时的工作目录无关：

```text
quant-strategies/
  .venv/
  data/
    qlib/cn_data/          # calendars、instruments、features
    quant-research/        # raw、normalized、manifests、snapshots、quarantine
    oneil/                 # 财务缓存、行业与元数据
    oneil-all-a/            # 全 A 股财务缓存（相关研究需要时）
    oneil-rebuild/          # 特定研究的派生数据
    investment-data-dolt/  # 涨跌停与交易状态来源（相关任务需要时）
  research.local.json      # 可选的本机路径配置
```

`data/`、`.venv/`、`research.local.json` 均由 Git 忽略。代码、数据契约、测试及已有
研究归档保留在版本控制中。大体积行情和财务数据通过文件复制或专门的数据备份同步。
同步数据时应连同 manifests 和来源元数据保留，以便核对版本和文件哈希。

### 使用外部数据盘

复制 `research.local.example.json` 为 `research.local.json` 后设置数据父目录。
已有 Windows 数据布局可直接复用：

```json
{
  "data_home": "D:/code/_open-source/_data"
}
```

Mac 可使用仓库默认目录，也可将 `data_home` 指向外置盘，例如
`/Volumes/Research/quant-data`。本地配置无需在不同电脑之间同步。

各数据集也可单独指定路径。配置优先级为：命令行显式参数、数据集环境变量、
数据集本地配置、数据父目录下的默认布局。

| 用途 | 本地配置键 | 环境变量 |
| --- | --- | --- |
| 数据父目录 | `data_home` | `QUANT_DATA_HOME` |
| 研究数据 | `research_data_dir` | `QUANT_RESEARCH_DATA_DIR` |
| Qlib 中国日线 | `qlib_cn_data_dir` | `QLIB_CN_DATA_DIR` |
| 欧奈尔财务缓存 | `oneil_data_dir` | `QUANT_ONEIL_DATA_DIR` |
| Dolt 可执行文件 | `dolt_executable` | `DOLT_EXECUTABLE` |

数据父目录自身的环境变量优先于 `data_home` 本地配置。环境变量和本地配置里的
相对路径均以仓库为基准；命令行传入的相对路径沿用当前工作目录语义。
Dolt 默认从系统 `PATH` 查找，仅同步相关市场数据时需要安装。

### 在两台电脑之间迁移数据

将旧数据父目录中需要的数据集复制到本机 `data/` 下，保持子目录结构。例如：
`qlib/cn_data` 复制到 `data/qlib/cn_data`，`quant-research` 复制到
`data/quant-research`。保留 Windows 原文件即可继续在两端研究。

先运行 `python tools/check_research_data.py` 检查路径和主要文件，再针对具体研究
执行原有数据质量验收。该命令显示存在性，不代表覆盖区间、来源质量或文件哈希已通过
验收。环境安装会检查软件依赖；全量行情下载和历史财务重建按研究需求执行。

## 环境验收与依赖更新

```bash
python tools/verify_research_environment.py --output data/quant-research/environment/verification.json
```

验证器自动选择本机平台的 `requirements/*.expected.json` 和 `.lock`，核对
Python、架构、全部已安装 distribution，检查基础环境包隔离，并让顶层依赖在同一
进程加载。TA-Lib、LightGBM、XGBoost、CVXPY、Optuna 和 PyTorch 还会运行小型计算。
原始本机报告保存在被忽略的数据目录，仓库只保留脱敏验收摘要，Apple Silicon 的结果见
[`environment-verification-macos-arm64.json`](environment-verification-macos-arm64.json)。

PyArrow 固定为 19.0.1。Windows 首次验收曾发现 PyArrow 14.0.2 与 CVXPY/OSQP 的
原生加载冲突，同进程导入检查用于持续发现这类兼容性问题。

更新依赖时：

1. 修改目标平台 `.in` 和 `expected.json`；共享核心库版本变更需协调全部平台。
2. 在对应平台的 CPython 3.12.9 中运行 `uv pip compile` 生成完整精确版本锁。
3. 从新的空环境执行重建程序，通过计算库验收、测试和仓库检查。
4. 提交输入、锁文件及脱敏验收摘要。
