# joinquant_archive/lib/

从聚宽社区归档的工具库，非策略源码。

## 文件列表

### TinyBacktest.py

**作者：** 聚宽社区用户  
**目的：** 无需消耗聚宽积分即可在研究环境中运行策略回测。聚宽运行策略需要消耗积分，而积分获取有难度，TinyBacktest 可以在研究中测试耗时策略，绕过积分限制。

微型 A 股回测引擎，约 400 行。依赖 `jqdata` 获取行情数据，自实现回测循环、持仓管理、绩效评估。

**特性：**
- 支持日/周/月频率调仓
- 开盘价成交，默认考虑涨跌停/停牌限制
- 输出：累计/年化收益、Alpha/Beta、最大回撤、夏普、胜率、盈亏比、持仓天数
- 支持策略参数调优（通过策略类传参）

**用法：** 将 `TinyBacktest.py` 上传到聚宽研究环境，编写策略回调函数 `trade_cb(ctx, prof)`，传入 `trade_daily/weekly/monthly` 即可回测。

```python
from TinyBacktest import *

# 双均线策略示例
def double_ma(ctx, prof):
    day = ctx.pre_time
    code = '000001.XSHE'
    price = get_price(code, count=121, end_date=day, panel=False)
    ma120 = price['close'].rolling(56).mean().dropna()
    ma60 = price['close'].rolling(6).mean().dropna()

    if ma60[-2] < ma120[-2] and ma60[-1] > ma120[-1]:
        prof.buy(code)
    elif ma60[-2] > ma120[-2] and ma60[-1] < ma120[-1]:
        prof.sell(code)

prof = trade_daily(double_ma, '2006-1-1', '2024-1-1', 10000000)
prof.summary(benchmark=m_ret)
```

**来源：** https://www.joinquant.com/view/community/detail/fddb02970d54625af69b7a0d7bc79ea0