# 五福 ETF 轮动：证据审计

- 正式事实源：`strategies/joinquant/wufu-etf-rotation/`。
- 直接分解与 T3 归档分别为 `strategies/joinquant/wufu-etf-rotation/backtests/2026-08-16__direct-decomposition__local-etf-2015-2026-v1/manifest.json` 和
  `strategies/joinquant/wufu-etf-rotation/backtests/2026-08-21__tradability-v3__local-etf-2015-2026-v1/manifest.json`。
- T3 源码 SHA-256：`61692fcf084e46addf7a0863256b3e08b6708ca26765f4d985c48378913c9242`；协议 SHA-256：`ef8848f98e00b285c400be38ebcb6d6eaa2594257213e9ac0b11acb0e789f582`。
- T3 的本地 `original_like` 仅有生命周期 PIT；ETF 跟踪标的仍来自当前静态字段，不能称为完整因果池。
- A7 只完成事件级分钟校准，没有完整组合净值与成交后 Sharpe 对照。
