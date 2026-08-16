"""聚宽 Research 上的五福 A7 配对分钟成交校准。

把本目录生成的 a7-switch-events.csv 上传到 Research 根目录后，Python 3 内核运行：

    from a7_minute_calibration import run
    run(0, 300, "part-1")
    run(300, 600, "part-2")
    run(600, None, "part-3")

三个 CSV 下载后可由本地 research.py 的 --a7-parts 汇总。目标ETF及退出日均被冻结，
A7 只改变买入分钟；卖出统一按退出日 13:10，避免把选股差异混入执行实验。
"""

import builtins
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from jqdata import *


CHECK_TIMES = ("13:10", "13:40", "14:10", "14:40")
FORCE_TIME = "14:55"


def intraday_trend(closes):
    values = np.asarray(closes, dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if len(values) < 5:
        return False, 0.0, 0.0
    values = values[-30:]
    x = np.arange(len(values), dtype=float)
    weights = np.linspace(0.5, 2.0, len(values))
    weights = weights / weights.sum()
    x_bar = np.sum(weights * x)
    y_bar = np.sum(weights * values)
    dx = x - x_bar
    variance_x = np.sum(weights * dx ** 2)
    slope = np.sum(weights * dx * (values - y_bar)) / variance_x if variance_x > 0 else 0.0
    slope_pct = slope / y_bar * 100.0 if y_bar > 0 else 0.0
    predicted = slope * x + (y_bar - slope * x_bar)
    ss_res = np.sum(weights * (values - predicted) ** 2)
    ss_tot = np.sum(weights * (values - y_bar) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return bool(slope_pct > 0.001 and r_squared > 0.3), float(slope_pct), float(r_squared)


def normalize_minutes(frame):
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["time", "close"])
    result = frame.reset_index().copy()
    time_column = "time" if "time" in result.columns else result.columns[0]
    result["time"] = pd.to_datetime(result[time_column])
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    return result[["time", "close"]].dropna().sort_values("time")


def day_minutes(symbol, day):
    day = pd.Timestamp(day)
    return normalize_minutes(
        get_price(
            symbol,
            start_date=day.strftime("%Y-%m-%d 09:30:00"),
            end_date=day.strftime("%Y-%m-%d 15:00:00"),
            frequency="1m",
            fields=["close"],
            skip_paused=False,
            fq="pre",
        )
    )


def price_at_or_before(frame, day, clock):
    cutoff = pd.Timestamp("{} {}:00".format(pd.Timestamp(day).date(), clock))
    selected = frame.loc[frame["time"] <= cutoff, "close"]
    return float(selected.iloc[-1]) if len(selected) else math.nan


def calibrate_event(event):
    entry_date = pd.Timestamp(event["entry_date"])
    exit_date = pd.Timestamp(event["exit_date"]) if pd.notna(event["exit_date"]) else pd.NaT
    symbol = str(event["symbol"])
    entry = day_minutes(symbol, entry_date)
    if entry.empty:
        return {**event.to_dict(), "status": "entry_minutes_missing"}
    baseline_price = price_at_or_before(entry, entry_date, "13:10")
    selected_time = None
    selected_price = math.nan
    selected_slope = math.nan
    selected_r2 = math.nan
    forced = True
    for clock in CHECK_TIMES:
        cutoff = pd.Timestamp("{} {}:00".format(entry_date.date(), clock))
        history = entry.loc[entry["time"] <= cutoff, "close"].tail(30).to_numpy()
        passed, slope_pct, r_squared = intraday_trend(history)
        if passed:
            selected_time = clock
            selected_price = price_at_or_before(entry, entry_date, clock)
            selected_slope = slope_pct
            selected_r2 = r_squared
            forced = False
            break
    if selected_time is None:
        selected_time = FORCE_TIME
        selected_price = price_at_or_before(entry, entry_date, FORCE_TIME)
    if pd.isna(exit_date):
        exit_price = math.nan
    else:
        exit_minutes = day_minutes(symbol, exit_date)
        exit_price = price_at_or_before(exit_minutes, exit_date, "13:10")
    status = "ok" if np.isfinite(baseline_price) and np.isfinite(selected_price) else "price_missing"
    return {
        **event.to_dict(),
        "status": status,
        "baseline_time": "13:10",
        "a7_time": selected_time,
        "forced_1455": forced,
        "baseline_entry_price": baseline_price,
        "a7_entry_price": selected_price,
        "entry_price_edge_bp": (
            (baseline_price / selected_price - 1.0) * 10000.0
            if np.isfinite(baseline_price) and np.isfinite(selected_price)
            else math.nan
        ),
        "trend_slope_pct_per_minute": selected_slope,
        "trend_r_squared": selected_r2,
        "exit_price_1310": exit_price,
        "baseline_trade_return": (
            exit_price / baseline_price - 1.0
            if np.isfinite(exit_price) and np.isfinite(baseline_price)
            else math.nan
        ),
        "a7_trade_return": (
            exit_price / selected_price - 1.0
            if np.isfinite(exit_price) and np.isfinite(selected_price)
            else math.nan
        ),
    }


def summarize(frame):
    valid = frame.loc[frame["status"].eq("ok")].copy()
    counts = valid["a7_time"].value_counts().to_dict()
    return {
        "method": "paired entry-only minute calibration; target and 13:10 exit frozen",
        "requested_events": int(len(frame)),
        "valid_events": int(len(valid)),
        "valid_ratio": float(len(valid) / len(frame)) if len(frame) else 0.0,
        "confirmation_counts": {str(key): int(value) for key, value in counts.items()},
        "forced_1455_ratio": float(valid["forced_1455"].mean()) if len(valid) else None,
        "mean_entry_edge_bp": float(valid["entry_price_edge_bp"].mean()) if len(valid) else None,
        "median_entry_edge_bp": float(valid["entry_price_edge_bp"].median()) if len(valid) else None,
        "positive_entry_edge_ratio": float(valid["entry_price_edge_bp"].gt(0).mean()) if len(valid) else None,
        "paired_trade_return_delta": float(
            valid["a7_trade_return"].mean() - valid["baseline_trade_return"].mean()
        )
        if len(valid)
        else None,
        "relative_wealth_from_entry_only": float(
            np.prod(valid["baseline_entry_price"] / valid["a7_entry_price"]) - 1.0
        )
        if len(valid)
        else None,
        "limitations": [
            "This is not a full official-backtest Sharpe comparison.",
            "Local A6 switch dates are held fixed, so it isolates execution but does not reproduce 13:10 selection.",
            "Suspension, limit queue, partial fills and portfolio cash path are outside this paired price test.",
        ],
    }


def run(start_row=0, end_row=None, suffix="all"):
    events = pd.read_csv("a7-switch-events.csv", parse_dates=["entry_date", "exit_date"])
    selected = events.iloc[int(start_row) : None if end_row is None else int(end_row)]
    rows = []
    for number, (_, event) in enumerate(selected.iterrows(), start=1):
        rows.append(calibrate_event(event))
        if number % 25 == 0:
            print("processed {}/{}".format(number, len(selected)))
    result = pd.DataFrame(rows)
    csv_path = Path("a7-minute-results-{}.csv".format(suffix))
    json_path = Path("a7-summary-{}.json".format(suffix))
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(
        json.dumps(summarize(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(str(csv_path), str(json_path))
    return result, summarize(result)


if __name__ == "__main__":
    run()
