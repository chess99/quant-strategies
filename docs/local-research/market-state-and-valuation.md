# 日估值与市场状态

## 日估值

东方财富 `stock_value_em` 历史接口提供交易日总市值、流通市值、股本、PE、PB、PEG、
PCF 和 PS。规范化后统一使用人民币元和 Qlib 证券代码。接口可能按后来修订的财务值
重算历史估值，因此质量等级为 B。

同步器支持并发、失败重试、原始 CSV 不可变保存和按证券断点续跑。默认股票池为本地
欧奈尔研究使用的历史沪深300与中证500联合证券，共 1,310 只；可替换为全市场代码表。

## 停牌与涨跌停

- 停牌：证券处于有效上市区间，但当日 OHLC 缺失或成交量为零，质量 B。
- ST：公开接口暂不能可靠恢复逐日历史状态，保存为未知，不以 `False` 填充，质量 C。
- 涨跌停：使用上一有效原始收盘价、板块和规则生效日期推导；因 ST 未知，质量 C。
- 一字板：当日 OHLC 四价相同且非停牌。

正式策略若要求最低 B 级交易状态，在历史 ST 数据补齐前必须拒绝运行。探索性回测可
显式允许 C 级，并在报告中列明非 ST 假设。

## 命令

```powershell
D:\code\_open-source\_venvs\qlib\Scripts\python.exe tools\sync_local_valuation.py
D:\code\_open-source\_venvs\qlib\Scripts\python.exe tools\build_local_market_state.py
```
