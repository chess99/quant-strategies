# 聚宽 Research Runner

这是仓库正式维护的聚宽 Research 执行后端。它使用聚宽研究环境中的 `jqdata` 获取点时行情，
自行完成日频调度、撮合、账本和结果导出，不调用聚宽官方策略回测任务。

它适合数据依赖型研究、参数预检和短周期黄金对照，不冒充聚宽完整回测引擎。

## 文件

```text
runners/joinquant-research/
  README.md
  research_runner.py
  examples/
    monthly_etf_momentum.py
    platform_acceptance_20260812.py
    platform_acceptance_20260812.ipynb
tests/joinquant_research/
  test_runner.py
```

- `research_runner.py`：直接上传聚宽的单文件、自包含运行模块。
- `monthly_etf_momentum.py`：只演示策略回调和导出流程。
- `platform_acceptance_20260812.*`：真实平台固定成交验收入口及最小 Notebook。
- `test_runner.py`：使用伪造的 `jqdata` 做本地确定性验证。

## 策略契约

策略提供一个函数，接收 `ResearchContext`，返回证券到目标权重的映射：

```python
def target_weights(context):
    observation_date = context.observation_date
    # 所有信号查询必须使用 observation_date 或更早日期。
    return {
        "510300.XSHG": 0.5,
        "510500.XSHG": 0.5,
    }
```

权重必须非负、有限且总和不超过 1；未使用的部分保留现金。回调还能读取：

- `context.current_date`：执行日；
- `context.observation_date` / `previous_date`：前一交易日；
- `context.portfolio`：执行前现金、总资产和持仓只读快照；
- `context.run_id`：运行标识。

Runner 固定在执行日前生成观察上下文，随后计算目标股数，先卖后买。卖出失败不会释放现金。
同一执行日不会在买入后再次卖出，因此日频目标权重接口天然不产生当日回转交易。

## 聚宽内运行

当前必须选择 **Python 3** 内核。聚宽该内核会把 `get_price`、`get_extras`
等部分行情 API 注入 `builtins`，但 `get_all_trade_days` 仍由 `jqdata` 导出；
Runner 已统一解析这两种来源，策略示例应从 `research_runner` 导入
`get_price`，不要直接写 `from jqdata import get_price`。

1. 将 `research_runner.py` 和策略文件上传到聚宽 Research 文件根目录。
   覆盖 `research_runner.py` 后必须重启 Notebook 内核或整个 Research 环境，避免继续使用
   Python 模块缓存中的旧版本。
2. 在 Notebook 中导入并运行：

```python
from monthly_etf_momentum import run

result, manifest, bundle = run()
manifest["metrics"]
```

3. 从文件列表下载返回的 ZIP。
4. 解压到对应策略族的新回测目录，核对 `manifest.json`、`source.py`、`engine.py` 和原始账本。
5. 更新策略族 README 的结果索引；已有回测目录不得覆盖。

不要把账号、Cookie、密码或 token 写入仓库。后续自动化只操作已经登录的浏览器页面，不读取
或持久化浏览器凭据，也不依赖聚宽未公开的内部接口。

## 输出契约

`ResearchResult.export()` 拒绝覆盖非空目录，并生成：

```text
{output}/
  manifest.json
  report.md
  source.py
  engine.py
  raw/
    equity.csv
    orders.csv
    trades.csv
    positions.csv
    log.txt          # 有警告时
{output}.zip
```

manifest 记录运行参数、费用、指标、策略源码 SHA-256、引擎 SHA-256 和每个工件的 SHA-256。
报告明确区分事实、推断、限制和下一步实验。

## 已实现语义

- 日、周、月频；周/月按实际首个或最后一个交易日调度；
- 前一交易日观察，执行日开盘或收盘成交；
- A 股整数手、现金约束、先卖后买；
- 停牌、ST、涨停买入和跌停卖出拒单；未知 ST/涨停状态默认拒绝买入；
- ST 查询只对股票执行；聚宽的 `get_extras("is_st")` 不接受 ETF，ETF 仍严格检查停牌和涨跌停；
- 买卖佣金、最低佣金、印花税和双向滑点；
- 现金、净值、订单、成交、持仓和警告账本；
- 累计/年化收益、最大回撤、Sharpe、换手、最长水下期和年度收益。

## 明确限制

- 不兼容聚宽 `initialize`、`run_daily`、`order_target_value` 等完整策略运行时；现有正式策略需
  抽取或包装为目标权重回调。
- 不模拟分钟、Tick、集合竞价、涨跌停排队、成交量冲击或部分成交。
- 默认使用连续前复权价格；公司行为后的名义股数、整数手和最低佣金不等同于逐事件模拟。
- 聚宽 Research 的环境、配额和可用内存由平台控制，不适合无限制并行参数搜索。
- 正式结论必须再与聚宽官方回测做同源码、同区间黄金对照。

第一批黄金对照建议依次使用 ETF 轮动、月度小市值、月度财务选股；只有目标、成交、持仓和
关键指标均达到各策略预设阈值后，才将这个后端作为该策略的默认 Research 执行方式。

## 平台验证记录

- 2026-08-12：在聚宽 Research Python 3 内核完成真实固定成交验收。
- 验证区间：2024-01-02 至 2024-03-29，共 58 个交易日。
- 固定序列：2024-01-02 买入 `510300.XSHG`；2024-02-01 卖出后买入
  `510500.XSHG`；2024-03-01 卖出，合计 4 笔成交并最终空仓。
- 已验证：真实行情、月初调度、先卖后买、ETF 100 股整数手、交易费用、现金与持仓账本、
  无警告运行，以及 `manifest.json` / 报告 / CSV / ZIP 导出。
- 指标：累计收益 3.323964%，年化收益 15.136086%，最大回撤 5.648852%，Sharpe 1.088490，
  换手 1.990011，最长水下期 36 天，期末资产 1,033,239.64。
- 生成文件：`exports/platform-acceptance-20260812-v5.zip`。

## 上线前剩余验收

真实成交链路已通过，可以用于受控研究；成为正式策略的默认后端前，还需要按优先级完成：

1. **官方回测黄金对照（硬门槛）**：同一策略源码、区间、复权和成本参数，对比成交、持仓、
   净值、费用、年化收益和最大回撤，并为各字段预先设定误差阈值。
2. **点时数据与容错**：验证历史股票池、财务批量查询、行业分类和观察日期均不使用未来数据；
   单批数据缺失或接口失败时记录警告且不得静默清仓。
3. **真实风控边界**：分别用股票和 ETF 覆盖停牌、ST、涨停、跌停的真实返回形状及拒单行为。
4. **可复现与归档闭环**：重复运行结果一致；run ID 不覆盖；策略与引擎 SHA-256 正确；ZIP
   可下载、解压并导入策略族的不可变 `backtests/` 目录。
5. **容量和敏感性**：验证长区间的时间、内存与平台配额，并测试佣金、最低佣金、印花税和
   滑点变化对结论的影响。
