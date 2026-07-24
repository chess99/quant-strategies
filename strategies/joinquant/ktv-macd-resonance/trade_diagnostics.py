"""KTV + MACD 本地回测的逐持仓路径诊断。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


DEFAULT_HORIZONS = (3, 5, 10)


def _finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return np.nan
    return result if np.isfinite(result) else np.nan


def _return(value, base):
    value = _finite(value)
    base = _finite(base)
    if not np.isfinite(value) or not np.isfinite(base) or base <= 0.0:
        return np.nan
    return value / base - 1.0


def _path_metrics(frame, base_price, horizons, prefix=""):
    result = {}
    high = pd.to_numeric(frame.get("high"), errors="coerce")
    low = pd.to_numeric(frame.get("low"), errors="coerce")
    valid_high = high.dropna()
    valid_low = low.dropna()
    result[f"{prefix}bars"] = int(len(frame))
    result[f"{prefix}mfe"] = (
        _return(valid_high.max(), base_price) if not valid_high.empty else np.nan
    )
    result[f"{prefix}mae"] = (
        _return(valid_low.min(), base_price) if not valid_low.empty else np.nan
    )
    if not valid_high.empty:
        result[f"{prefix}bars_to_mfe"] = int(
            frame.index.get_loc(valid_high.idxmax()) + 1
        )
    else:
        result[f"{prefix}bars_to_mfe"] = np.nan
    if not valid_low.empty:
        result[f"{prefix}bars_to_mae"] = int(
            frame.index.get_loc(valid_low.idxmin()) + 1
        )
    else:
        result[f"{prefix}bars_to_mae"] = np.nan
    for horizon in horizons:
        window = frame.head(horizon)
        window_high = pd.to_numeric(window.get("high"), errors="coerce").dropna()
        window_low = pd.to_numeric(window.get("low"), errors="coerce").dropna()
        window_close = pd.to_numeric(window.get("close"), errors="coerce").dropna()
        result[f"{prefix}mfe_{horizon}"] = (
            _return(window_high.max(), base_price)
            if not window_high.empty
            else np.nan
        )
        result[f"{prefix}mae_{horizon}"] = (
            _return(window_low.min(), base_price)
            if not window_low.empty
            else np.nan
        )
        result[f"{prefix}close_return_{horizon}"] = (
            _return(window_close.iloc[-1], base_price)
            if len(window) >= horizon and not window_close.empty
            else np.nan
        )
    return result


def _entry_features(indicator, observation_date, entry_price):
    window = indicator.loc[:observation_date]
    if window.empty:
        return {}
    latest = window.iloc[-1]
    close = pd.to_numeric(window["close"], errors="coerce")
    money = pd.to_numeric(window["money"], errors="coerce").dropna()
    returns = close.pct_change(fill_method=None).dropna()
    ma20 = _finite(latest.get("ma20"))
    ma60 = _finite(latest.get("ma60"))
    k = _finite(latest.get("k"))
    t = _finite(latest.get("t"))
    diff = _finite(latest.get("diff"))
    dea = _finite(latest.get("dea"))
    latest_close = _finite(latest.get("close"))
    crosses = (
        (window["k"] > window["t"])
        & (window["k"].shift(1) <= window["t"].shift(1))
    ).tail(3)
    cross_locations = np.flatnonzero(crosses.fillna(False).to_numpy())
    cross_age = (
        int(len(crosses) - 1 - cross_locations[-1])
        if len(cross_locations)
        else np.nan
    )
    return {
        "observation_close": latest_close,
        "entry_gap": _return(entry_price, latest_close),
        "trend_gap": (
            ma20 / ma60 - 1.0
            if np.isfinite(ma20) and np.isfinite(ma60) and ma60 > 0.0
            else np.nan
        ),
        "distance_to_ma60": _return(latest_close, ma60),
        "t_value": t,
        "kt_spread": k - t if np.isfinite(k) and np.isfinite(t) else np.nan,
        "macd_spread_pct": (
            (diff - dea) / latest_close
            if np.isfinite(diff)
            and np.isfinite(dea)
            and np.isfinite(latest_close)
            and latest_close > 0.0
            else np.nan
        ),
        "volume_ratio_5_20": (
            money.tail(5).mean() / money.tail(20).mean()
            if len(money) >= 20 and money.tail(20).mean() > 0.0
            else np.nan
        ),
        "prior_return_20": (
            _return(close.dropna().iloc[-1], close.dropna().iloc[-21])
            if len(close.dropna()) >= 21
            else np.nan
        ),
        "prior_return_60": (
            _return(close.dropna().iloc[-1], close.dropna().iloc[-61])
            if len(close.dropna()) >= 61
            else np.nan
        ),
        "realized_volatility_20": (
            float(returns.tail(20).std(ddof=1) * math.sqrt(252.0))
            if len(returns) >= 20
            else np.nan
        ),
        "kt_cross_age": cross_age,
    }


def _trade_maps(trades):
    frame = trades.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    buys = {}
    exits = {}
    for row in frame.itertuples(index=False):
        key = (str(row.symbol), pd.Timestamp(row.date).normalize())
        if row.side == "buy":
            buys[key] = row
        elif row.side == "sell" and str(row.reason) not in {
            "exit_half",
            "exit_take_profit_half",
        }:
            exits[key] = row
    return buys, exits


def analyze_trade_paths(
    data,
    logic,
    round_trips,
    trades,
    end_date,
    forward_days=10,
    horizons=DEFAULT_HORIZONS,
):
    """计算持仓内 MFE/MAE、入场特征和退出后的反事实路径。"""
    if forward_days <= 0:
        raise ValueError("forward_days must be positive")
    horizons = tuple(sorted(set(int(value) for value in horizons) | {forward_days}))
    if any(value <= 0 for value in horizons):
        raise ValueError("horizons must be positive")
    episodes = round_trips.copy()
    if episodes.empty:
        return episodes
    episodes["entry_date"] = pd.to_datetime(episodes["entry_date"]).dt.normalize()
    episodes["exit_date"] = pd.to_datetime(episodes["exit_date"]).dt.normalize()
    end_date = pd.Timestamp(end_date).normalize()
    buys, exits = _trade_maps(trades)

    result_rows = []
    for symbol, symbol_episodes in episodes.groupby("symbol", sort=True):
        first_entry = symbol_episodes["entry_date"].min()
        first_location = data.calendar.searchsorted(first_entry, side="left")
        warmup_location = max(0, first_location - 260)
        end_location = data.calendar.searchsorted(end_date, side="right") - 1
        extended_location = min(
            len(data.calendar) - 1,
            end_location + forward_days,
        )
        raw = data.load_symbol_frame(
            symbol,
            data.calendar[warmup_location],
            data.calendar[extended_location],
        )
        indicator = logic.build_indicator_frame(raw[["close", "money"]])
        for column in ("high", "low", "open", "raw_open"):
            indicator[column] = raw[column]

        for episode in symbol_episodes.itertuples(index=False):
            entry_date = pd.Timestamp(episode.entry_date).normalize()
            exit_date = (
                pd.Timestamp(episode.exit_date).normalize()
                if pd.notna(episode.exit_date)
                else pd.NaT
            )
            buy = buys.get((str(symbol), entry_date))
            if buy is None:
                raise ValueError(f"missing buy trade for {symbol} on {entry_date.date()}")
            entry_price = _finite(buy.adjusted_price)
            observation_date = pd.Timestamp(buy.observation_date).normalize()
            holding_end = exit_date if pd.notna(exit_date) else end_date
            if pd.notna(exit_date):
                holding = indicator.loc[
                    (indicator.index >= entry_date)
                    & (indicator.index < exit_date)
                ]
            else:
                holding = indicator.loc[
                    (indicator.index >= entry_date)
                    & (indicator.index <= holding_end)
                ]

            row = episode._asdict()
            row["entry_price"] = entry_price
            row["observation_date"] = observation_date
            row.update(_entry_features(indicator, observation_date, entry_price))
            holding_metrics = _path_metrics(
                holding,
                entry_price,
                horizons,
            )
            row["holding_bars"] = holding_metrics.pop("bars")
            row.update(holding_metrics)

            if pd.notna(exit_date):
                exit_trade = exits.get((str(symbol), exit_date))
                exit_price = (
                    _finite(exit_trade.adjusted_price)
                    if exit_trade is not None
                    else np.nan
                )
                row["exit_price"] = exit_price
                row["terminal_price_return"] = _return(exit_price, entry_price)
                post_exit = indicator.loc[indicator.index >= exit_date].head(
                    forward_days
                )
                post_metrics = _path_metrics(
                    post_exit,
                    exit_price,
                    horizons,
                    prefix="post_exit_",
                )
                row.update(post_metrics)
            else:
                row["exit_price"] = np.nan
                row["terminal_price_return"] = np.nan
                for key, value in _path_metrics(
                    indicator.iloc[0:0],
                    np.nan,
                    horizons,
                    prefix="post_exit_",
                ).items():
                    row[key] = value if key == "post_exit_bars" else np.nan
            result_rows.append(row)

    result = pd.DataFrame(result_rows)
    result.sort_values(["entry_date", "symbol"], inplace=True, ignore_index=True)
    return result
