"""懒人 ETF 跨资产状态切换的本地严格因果实验引擎。"""

import argparse
import hashlib
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


FAMILY_DIR = Path(__file__).resolve().parent
ROOT = FAMILY_DIR.parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.store import ResearchDataStore, sha256_file  # noqa: E402


BASE_ASSETS = {
    "gem": "SZ159915",
    "nasdaq": "SH513100",
    "gold": "SH518880",
}
REPLACEMENTS = {
    "gem_to_csi500": {"gem": "SH510500", "gem_signal": "asset"},
    "nasdaq_to_sp500": {"nasdaq": "SH513500"},
    "gold_to_alt_gold": {"gold": "SH518800"},
}
ALL_ETFS = tuple(
    sorted(
        set(BASE_ASSETS.values())
        | {
            value
            for replacement in REPLACEMENTS.values()
            for key, value in replacement.items()
            if key in BASE_ASSETS
        }
    )
)
MODEL_LABELS = {
    "m0": "M0 纳指买入持有",
    "m1": "M1 纳指 MA",
    "m2": "M2 纳指 MA + 黄金",
    "m3": "M3 标准 CCI 覆盖",
    "m4": "M4 close-only CCI 原规则",
    "b1": "B1 三资产月度等权",
    "b2": "B2 三资产 52 周动量",
    "b3": "B3 MA40 后选最强动量",
}


@dataclass(frozen=True)
class SignalState:
    gem_close_cci: float
    gem_standard_cci: float
    nasdaq_above_ma: bool
    gold_above_ma: bool
    momentum: dict
    eligible_ma40: dict


@dataclass(frozen=True)
class CostAssumptions:
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    slippage_rate: float = 0.0002
    target_weight: float = 0.99


@dataclass
class SimulationResult:
    name: str
    equity: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    decisions: pd.DataFrame
    metrics: dict


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close_only_cci(close_values, period=14):
    values = np.asarray(close_values, dtype=float)
    if len(values) < period:
        return np.nan
    sample = values[-period:]
    if not np.isfinite(sample).all():
        return np.nan
    mean = float(np.mean(sample))
    mean_deviation = float(np.mean(np.abs(sample - mean)))
    if mean_deviation == 0:
        return 0.0
    return float((sample[-1] - mean) / (0.015 * mean_deviation))


def standard_cci(high_values, low_values, close_values, period=14):
    high = np.asarray(high_values, dtype=float)
    low = np.asarray(low_values, dtype=float)
    close = np.asarray(close_values, dtype=float)
    if min(len(high), len(low), len(close)) < period:
        return np.nan
    typical = (high[-period:] + low[-period:] + close[-period:]) / 3.0
    if not np.isfinite(typical).all():
        return np.nan
    mean = float(np.mean(typical))
    mean_deviation = float(np.mean(np.abs(typical - mean)))
    if mean_deviation == 0:
        return 0.0
    return float((typical[-1] - mean) / (0.015 * mean_deviation))


def above_moving_average(close_values, period):
    values = np.asarray(close_values, dtype=float)
    if len(values) < period:
        return False
    sample = values[-period:]
    return bool(np.isfinite(sample).all() and sample[-1] > np.mean(sample))


def trailing_momentum(close_values, period=52):
    values = np.asarray(close_values, dtype=float)
    if len(values) < period:
        return np.nan
    start = values[-period]
    end = values[-1]
    if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
        return np.nan
    return float(end / start - 1.0)


def choose_model_asset(model, signals, cci_threshold=130.0):
    if model == "m0":
        return "nasdaq"
    if model == "m1":
        return "nasdaq" if signals.nasdaq_above_ma else None
    if model == "m2":
        if signals.nasdaq_above_ma:
            return "nasdaq"
        return "gold" if signals.gold_above_ma else None
    if model == "m3":
        if np.isfinite(signals.gem_standard_cci) and signals.gem_standard_cci > cci_threshold:
            return "gem"
        if signals.nasdaq_above_ma:
            return "nasdaq"
        return "gold" if signals.gold_above_ma else None
    if model == "m4":
        if np.isfinite(signals.gem_close_cci) and signals.gem_close_cci > cci_threshold:
            return "gem"
        if signals.nasdaq_above_ma:
            return "nasdaq"
        return "gold" if signals.gold_above_ma else None
    if model in {"b2", "b3"}:
        candidates = []
        priority = {"gem": 0, "nasdaq": 1, "gold": 2}
        for role, value in signals.momentum.items():
            if not np.isfinite(value) or value <= 0:
                continue
            if model == "b3" and not signals.eligible_ma40.get(role, False):
                continue
            candidates.append((float(value), -priority[role], role))
        return max(candidates)[2] if candidates else None
    raise ValueError("unknown model: %s" % model)


def weekly_execution_pairs(trading_dates):
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize()
    dates = dates.sort_values().unique()
    if len(dates) < 2:
        return []
    grouped = pd.Series(dates, index=dates.to_period("W-FRI")).groupby(level=0).max()
    locations = {date: index for index, date in enumerate(dates)}
    pairs = []
    for observation in grouped:
        location = locations[observation]
        if location + 1 < len(dates):
            pairs.append((pd.Timestamp(observation), pd.Timestamp(dates[location + 1])))
    return pairs


def _weekly_ohlc(frame, adjusted=True):
    prefix = "adjusted_" if adjusted else ""
    columns = {
        prefix + "open": "open",
        prefix + "high": "high",
        prefix + "low": "low",
        prefix + "close": "close",
    }
    selected = frame[list(columns)].rename(columns=columns).sort_index()
    return selected.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna(subset=["close"])


def _history_at(weekly, observation_date):
    period_end = pd.Timestamp(observation_date).to_period("W-FRI").end_time.normalize()
    return weekly.loc[:period_end]


def build_signal_states(
    trading_dates,
    weekly_by_symbol,
    gem_index_weekly,
    assets,
    gem_signal="index",
    cci_period=14,
    cci_threshold=130.0,
    ma_period=45,
    momentum_period=52,
):
    del cci_threshold
    rows = []
    gem_weekly = (
        gem_index_weekly if gem_signal == "index" else weekly_by_symbol[assets["gem"]]
    )
    for observation, execution in weekly_execution_pairs(trading_dates):
        gem_history = _history_at(gem_weekly, observation)
        role_history = {
            role: _history_at(weekly_by_symbol[symbol], observation)
            for role, symbol in assets.items()
        }
        close_cci = close_only_cci(gem_history["close"].to_numpy(), cci_period)
        standard = standard_cci(
            gem_history["high"].to_numpy(),
            gem_history["low"].to_numpy(),
            gem_history["close"].to_numpy(),
            cci_period,
        )
        momentum = {
            role: trailing_momentum(history["close"].to_numpy(), momentum_period)
            for role, history in role_history.items()
        }
        eligible = {
            role: above_moving_average(history["close"].to_numpy(), 40)
            for role, history in role_history.items()
        }
        state = SignalState(
            gem_close_cci=close_cci,
            gem_standard_cci=standard,
            nasdaq_above_ma=above_moving_average(
                role_history["nasdaq"]["close"].to_numpy(), ma_period
            ),
            gold_above_ma=above_moving_average(
                role_history["gold"]["close"].to_numpy(), ma_period
            ),
            momentum=momentum,
            eligible_ma40=eligible,
        )
        rows.append(
            {
                "observation_date": observation,
                "execution_date": execution,
                "state": state,
                "gem_close_cci": close_cci,
                "gem_standard_cci": standard,
                "nasdaq_above_ma": state.nasdaq_above_ma,
                "gold_above_ma": state.gold_above_ma,
                **{"momentum_" + key: value for key, value in momentum.items()},
                **{"eligible_ma40_" + key: value for key, value in eligible.items()},
            }
        )
    return pd.DataFrame(rows)


def _single_asset_allocations(states, model, assets, costs, cci_threshold=130.0):
    allocations = {}
    decision_rows = []
    previous_role = object()
    for row in states.itertuples(index=False):
        role = choose_model_asset(model, row.state, cci_threshold=cci_threshold)
        if role != previous_role:
            weights = {} if role is None else {assets[role]: costs.target_weight}
            allocations[pd.Timestamp(row.execution_date)] = weights
            previous_role = role
        decision_rows.append(
            {
                "model": model,
                "observation_date": row.observation_date,
                "execution_date": row.execution_date,
                "target_role": role,
                "target_symbol": None if role is None else assets[role],
                "gem_close_cci": row.gem_close_cci,
                "gem_standard_cci": row.gem_standard_cci,
                "nasdaq_above_ma": row.nasdaq_above_ma,
                "gold_above_ma": row.gold_above_ma,
            }
        )
    return allocations, pd.DataFrame(decision_rows)


def _buy_and_hold_allocations(trading_dates, symbol, costs, model="m0"):
    first = pd.DatetimeIndex(trading_dates)[0]
    allocations = {pd.Timestamp(first): {symbol: costs.target_weight}}
    decisions = pd.DataFrame(
        [
            {
                "model": model,
                "observation_date": pd.NaT,
                "execution_date": first,
                "target_role": "nasdaq",
                "target_symbol": symbol,
            }
        ]
    )
    return allocations, decisions


def _equal_weight_allocations(trading_dates, assets, costs):
    dates = pd.DatetimeIndex(trading_dates)
    first_dates = pd.Series(dates, index=dates.to_period("M")).groupby(level=0).min()
    weight = costs.target_weight / len(assets)
    allocations = {
        pd.Timestamp(date): {symbol: weight for symbol in assets.values()}
        for date in first_dates
    }
    decisions = pd.DataFrame(
        [
            {
                "model": "b1",
                "observation_date": pd.NaT,
                "execution_date": date,
                "target_role": "equal_weight",
                "target_symbol": ";".join(sorted(assets.values())),
            }
            for date in first_dates
        ]
    )
    return allocations, decisions


def _valid_price(value):
    return value is not None and np.isfinite(value) and float(value) > 0


def _commission(gross, costs):
    return max(costs.minimum_commission, gross * costs.commission_rate) if gross > 0 else 0.0


def simulate_allocations(
    name,
    trading_dates,
    daily_by_symbol,
    allocations,
    decisions,
    costs,
    initial_cash=1_000_000.0,
):
    dates = pd.DatetimeIndex(trading_dates)
    cash = float(initial_cash)
    positions = {}
    last_close = {}
    equity_rows = []
    trade_rows = []
    position_rows = []

    for date in dates:
        for symbol, frame in daily_by_symbol.items():
            if date in frame.index and _valid_price(frame.at[date, "adjusted_close"]):
                last_close[symbol] = float(frame.at[date, "adjusted_close"])

        if date in allocations:
            weights = allocations[date]
            universe = set(positions).union(weights)

            def open_price(symbol):
                frame = daily_by_symbol[symbol]
                if date not in frame.index:
                    return np.nan
                return float(frame.at[date, "adjusted_open"])

            equity_open = cash
            for symbol, shares in positions.items():
                price = open_price(symbol)
                mark = price if _valid_price(price) else last_close.get(symbol, np.nan)
                if _valid_price(mark):
                    equity_open += shares * mark

            desired = {}
            for symbol in universe:
                price = open_price(symbol)
                if not _valid_price(price):
                    desired[symbol] = positions.get(symbol, 0)
                    continue
                target_value = equity_open * float(weights.get(symbol, 0.0))
                desired[symbol] = int(target_value / price) // 100 * 100

            for symbol in sorted(universe):
                current = positions.get(symbol, 0)
                target = desired[symbol]
                if target >= current:
                    continue
                shares = current - target
                raw_price = open_price(symbol)
                if not _valid_price(raw_price):
                    continue
                price = raw_price * (1.0 - costs.slippage_rate)
                gross = shares * price
                commission = _commission(gross, costs)
                cash += gross - commission
                if target == 0:
                    positions.pop(symbol, None)
                else:
                    positions[symbol] = target
                trade_rows.append(
                    {
                        "model": name,
                        "trade_date": date,
                        "side": "sell",
                        "symbol": symbol,
                        "shares": shares,
                        "price": price,
                        "gross_value": gross,
                        "commission": commission,
                        "slippage_rate": costs.slippage_rate,
                    }
                )

            buy_order = sorted(
                universe,
                key=lambda symbol: (-float(weights.get(symbol, 0.0)), symbol),
            )
            for symbol in buy_order:
                current = positions.get(symbol, 0)
                target = desired[symbol]
                if target <= current:
                    continue
                raw_price = open_price(symbol)
                if not _valid_price(raw_price):
                    continue
                price = raw_price * (1.0 + costs.slippage_rate)
                shares = target - current
                while shares > 0:
                    gross = shares * price
                    commission = _commission(gross, costs)
                    if gross + commission <= cash + 1e-8:
                        break
                    shares -= 100
                if shares <= 0:
                    continue
                gross = shares * price
                commission = _commission(gross, costs)
                cash -= gross + commission
                positions[symbol] = current + shares
                trade_rows.append(
                    {
                        "model": name,
                        "trade_date": date,
                        "side": "buy",
                        "symbol": symbol,
                        "shares": shares,
                        "price": price,
                        "gross_value": gross,
                        "commission": commission,
                        "slippage_rate": costs.slippage_rate,
                    }
                )

        positions_value = 0.0
        for symbol, shares in sorted(positions.items()):
            mark = last_close.get(symbol, np.nan)
            if not _valid_price(mark):
                continue
            market_value = shares * mark
            positions_value += market_value
            position_rows.append(
                {
                    "model": name,
                    "trade_date": date,
                    "symbol": symbol,
                    "shares": shares,
                    "close": mark,
                    "market_value": market_value,
                }
            )
        total = cash + positions_value
        previous = equity_rows[-1]["total_value"] if equity_rows else initial_cash
        equity_rows.append(
            {
                "model": name,
                "trade_date": date,
                "cash": cash,
                "positions_value": positions_value,
                "total_value": total,
                "daily_return": total / previous - 1.0,
                "cash_ratio": cash / total if total > 0 else np.nan,
                "holdings": ";".join(sorted(positions)),
            }
        )

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    positions_frame = pd.DataFrame(position_rows)
    metrics = calculate_metrics(equity, trades, initial_value=initial_cash)
    return SimulationResult(
        name=name,
        equity=equity,
        trades=trades,
        positions=positions_frame,
        decisions=decisions,
        metrics=metrics,
    )


def calculate_metrics(equity, trades=None, initial_value=1_000_000.0):
    if equity.empty:
        raise ValueError("equity is empty")
    values = pd.to_numeric(equity["total_value"], errors="raise")
    returns = pd.to_numeric(equity["daily_return"], errors="raise").copy()
    returns.iloc[0] = values.iloc[0] / float(initial_value) - 1.0
    years = len(values) / 250.0
    total_return = float(values.iloc[-1] / float(initial_value) - 1.0)
    annualized = float((1.0 + total_return) ** (1.0 / years) - 1.0)
    curve = pd.concat(
        [pd.Series([float(initial_value)]), values.reset_index(drop=True)],
        ignore_index=True,
    )
    drawdown = curve / curve.cummax() - 1.0
    volatility = float(returns.std(ddof=1) * math.sqrt(250.0))
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(250.0))
    downside = returns.clip(upper=0).std(ddof=1) * math.sqrt(250.0)
    sortino = float(returns.mean() * 250.0 / downside) if downside > 0 else np.nan
    maximum_drawdown = float(-drawdown.min())
    calmar = annualized / maximum_drawdown if maximum_drawdown > 0 else np.nan
    underwater = drawdown < -1e-12
    longest = current = 0
    for flag in underwater:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    dates = pd.DatetimeIndex(pd.to_datetime(equity["trade_date"]))
    yearly = pd.Series(returns.to_numpy(), index=dates).groupby(dates.year).apply(
        lambda series: float((1.0 + series).prod() - 1.0)
    )
    gross_traded = 0.0
    fees = 0.0
    order_count = 0
    if trades is not None and not trades.empty:
        gross_traded = float(trades["gross_value"].sum())
        fees = float(trades["commission"].sum())
        order_count = len(trades)
    rolling = values / values.shift(756) - 1.0
    return {
        "trading_days": len(values),
        "total_return": total_return,
        "annualized_return": annualized,
        "maximum_drawdown": maximum_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "annualized_volatility": volatility,
        "turnover": gross_traded / float(values.mean()),
        "transaction_fees": fees,
        "order_count": order_count,
        "average_cash_ratio": float(equity["cash_ratio"].mean()),
        "longest_underwater_trading_days": longest,
        "worst_rolling_three_year_return": (
            float(rolling.min()) if rolling.notna().any() else None
        ),
        "yearly_returns": {str(year): float(value) for year, value in yearly.items()},
    }


def period_metrics(result, start, end, label):
    equity = result.equity.copy()
    equity["trade_date"] = pd.to_datetime(equity["trade_date"])
    selected = equity[
        equity["trade_date"].between(pd.Timestamp(start), pd.Timestamp(end))
    ].copy()
    if selected.empty:
        raise ValueError("period contains no equity rows: %s" % label)
    first_index = selected.index[0]
    initial = (
        1_000_000.0
        if first_index == equity.index[0]
        else float(equity.loc[first_index - 1, "total_value"])
    )
    selected["daily_return"] = selected["total_value"].pct_change()
    selected.iloc[0, selected.columns.get_loc("daily_return")] = (
        selected.iloc[0]["total_value"] / initial - 1.0
    )
    trades = result.trades
    if trades is not None and not trades.empty:
        trades = trades[
            pd.to_datetime(trades["trade_date"]).between(
                pd.Timestamp(start), pd.Timestamp(end)
            )
        ]
    metrics = calculate_metrics(selected, trades, initial_value=initial)
    return {"model": result.name, "period": label, **metrics}


def _normalise_etf_frames(bars):
    frames = {}
    for symbol, frame in bars.groupby("symbol"):
        current = frame.copy()
        current["trade_date"] = pd.to_datetime(current["trade_date"]).dt.normalize()
        current = current.set_index("trade_date").sort_index()
        frames[str(symbol)] = current
    return frames


def load_gem_index(path=None):
    if path is not None:
        frame = pd.read_csv(path)
    else:
        import akshare as ak

        frame = ak.stock_zh_index_daily(symbol="sz399006")
    frame = frame.rename(columns={"date": "trade_date"})
    required = {"trade_date", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError("创业板指数文件缺少字段: %s" % sorted(missing))
    frame = frame[list(required)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    return frame.sort_values("trade_date").drop_duplicates("trade_date", keep="last")


def _build_asset_set(replacement=None):
    assets = dict(BASE_ASSETS)
    gem_signal = "index"
    if replacement is not None:
        for key, value in replacement.items():
            if key == "gem_signal":
                gem_signal = value
            else:
                assets[key] = value
    return assets, gem_signal


def _model_result(
    model,
    trading_dates,
    daily_by_symbol,
    weekly_by_symbol,
    gem_weekly,
    assets,
    gem_signal,
    costs,
    cci_period=14,
    cci_threshold=130.0,
    ma_period=45,
):
    if model == "m0":
        allocations, decisions = _buy_and_hold_allocations(
            trading_dates, assets["nasdaq"], costs, model=model
        )
    elif model == "b1":
        allocations, decisions = _equal_weight_allocations(trading_dates, assets, costs)
    else:
        states = build_signal_states(
            trading_dates,
            weekly_by_symbol,
            gem_weekly,
            assets,
            gem_signal=gem_signal,
            cci_period=cci_period,
            cci_threshold=cci_threshold,
            ma_period=ma_period,
        )
        allocations, decisions = _single_asset_allocations(
            states, model, assets, costs, cci_threshold=cci_threshold
        )
    return simulate_allocations(
        model,
        trading_dates,
        daily_by_symbol,
        allocations,
        decisions,
        costs,
    )


def run_experiments(data_root, gem_index, start="2014-01-02", end="2026-07-24"):
    store = ResearchDataStore(data_root)
    bars = store.read_symbol_partitions("etf_daily", ALL_ETFS)
    daily_by_symbol = _normalise_etf_frames(bars)
    weekly_by_symbol = {
        symbol: _weekly_ohlc(frame, adjusted=True)
        for symbol, frame in daily_by_symbol.items()
    }
    gem_daily = gem_index.set_index("trade_date").sort_index()
    gem_weekly = _weekly_ohlc(gem_daily, adjusted=False)

    base_dates = set(daily_by_symbol[BASE_ASSETS["gem"]].index)
    base_dates &= set(daily_by_symbol[BASE_ASSETS["nasdaq"]].index)
    base_dates &= set(daily_by_symbol[BASE_ASSETS["gold"]].index)
    dates = pd.DatetimeIndex(sorted(base_dates))
    dates = dates[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]
    if len(dates) == 0:
        raise ValueError("回测区间没有共同交易日")

    base_costs = CostAssumptions()
    assets, gem_signal = _build_asset_set()
    results = {}
    for model in ("m0", "m1", "m2", "m3", "m4", "b1", "b2", "b3"):
        results[model] = _model_result(
            model,
            dates,
            daily_by_symbol,
            weekly_by_symbol,
            gem_weekly,
            assets,
            gem_signal,
            base_costs,
        )

    model_metrics = []
    for model, result in results.items():
        model_metrics.append(
            {"model": model, "label": MODEL_LABELS[model], **result.metrics}
        )
    # B0/B4 是刻意重复的外部基准，用别名保留比较关系。
    model_metrics.extend(
        [
            {"model": "b0", "label": "B0 纳指买入持有", **results["m0"].metrics},
            {"model": "b4", "label": "B4 纳指 MA45", **results["m1"].metrics},
        ]
    )
    model_metrics_frame = pd.DataFrame(model_metrics)

    period_rows = []
    periods = (
        ("2014-2018", "2014-01-02", "2018-12-31"),
        ("2019-2022", "2019-01-01", "2022-12-31"),
        ("2023-end", "2023-01-01", str(dates.max().date())),
    )
    for model in ("m0", "m1", "m2", "m3", "m4", "b1", "b2", "b3"):
        for label, period_start, period_end in periods:
            period_rows.append(
                period_metrics(results[model], period_start, period_end, label)
            )
    period_frame = pd.DataFrame(period_rows)

    replacement_rows = []
    replacement_results = {}
    for name, replacement in REPLACEMENTS.items():
        replacement_assets, replacement_signal = _build_asset_set(replacement)
        result = _model_result(
            "m4",
            dates,
            daily_by_symbol,
            weekly_by_symbol,
            gem_weekly,
            replacement_assets,
            replacement_signal,
            base_costs,
        )
        result.name = name
        replacement_results[name] = result
        replacement_rows.append(
            {
                "replacement": name,
                "gem": replacement_assets["gem"],
                "nasdaq": replacement_assets["nasdaq"],
                "gold": replacement_assets["gold"],
                **result.metrics,
            }
        )
    replacement_frame = pd.DataFrame(replacement_rows)

    m4_allocations, m4_decisions = _single_asset_allocations(
        build_signal_states(
            dates,
            weekly_by_symbol,
            gem_weekly,
            assets,
            gem_signal=gem_signal,
            cci_period=14,
            cci_threshold=130,
            ma_period=45,
        ),
        "m4",
        assets,
        base_costs,
        cci_threshold=130,
    )
    cost_rows = []
    cost_results = {}
    for name, assumptions in (
        (
            "zero",
            CostAssumptions(
                commission_rate=0.0,
                minimum_commission=0.0,
                slippage_rate=0.0,
            ),
        ),
        ("base", base_costs),
        (
            "slippage-10bp",
            CostAssumptions(slippage_rate=0.001),
        ),
    ):
        result = simulate_allocations(
            name,
            dates,
            daily_by_symbol,
            m4_allocations,
            m4_decisions,
            assumptions,
        )
        cost_results[name] = result
        cost_rows.append(
            {
                "cost_case": name,
                "commission_rate": assumptions.commission_rate,
                "minimum_commission": assumptions.minimum_commission,
                "slippage_rate": assumptions.slippage_rate,
                **result.metrics,
            }
        )
    cost_frame = pd.DataFrame(cost_rows)

    grid_rows = run_parameter_grid(
        dates,
        daily_by_symbol,
        weekly_by_symbol,
        gem_weekly,
        assets,
        base_costs,
    )
    original_grid = grid_rows[
        grid_rows["cci_period"].eq(14)
        & grid_rows["cci_threshold"].eq(130)
        & grid_rows["ma_period"].eq(45)
    ].iloc[0]
    for metric in ("annualized_return", "maximum_drawdown", "sharpe"):
        if not np.isclose(
            float(original_grid[metric]),
            float(results["m4"].metrics[metric]),
            rtol=0,
            atol=1e-12,
        ):
            raise AssertionError("参数网格快速撮合与正式 M4 口径不一致: %s" % metric)

    return {
        "store": store,
        "dates": dates,
        "results": results,
        "model_metrics": model_metrics_frame,
        "period_metrics": period_frame,
        "replacement_results": replacement_results,
        "replacement_metrics": replacement_frame,
        "cost_results": cost_results,
        "cost_metrics": cost_frame,
        "parameter_grid": grid_rows,
        "gem_index": gem_index,
    }


def _rolling_close_cci(series, period):
    return series.rolling(period).apply(
        lambda values: close_only_cci(values, period), raw=True
    )


def _fast_single_asset_metrics(
    trading_dates,
    opens,
    closes,
    event_targets,
    costs,
    initial_cash=1_000_000.0,
):
    cash = float(initial_cash)
    held = -1
    shares = 0
    values = np.empty(len(trading_dates), dtype=float)
    cash_values = np.empty(len(trading_dates), dtype=float)
    gross_traded = 0.0
    fees = 0.0
    order_count = 0
    last_marks = np.full(opens.shape[1], np.nan, dtype=float)

    for index in range(len(trading_dates)):
        valid_close = np.isfinite(closes[index]) & (closes[index] > 0)
        last_marks[valid_close] = closes[index, valid_close]
        target = int(event_targets[index])
        if target != -2 and target != held:
            equity_open = cash
            if held >= 0 and shares > 0:
                mark = opens[index, held]
                if not np.isfinite(mark) or mark <= 0:
                    mark = last_marks[held]
                if np.isfinite(mark) and mark > 0:
                    equity_open += shares * mark
            if held >= 0 and shares > 0:
                raw_price = opens[index, held]
                if np.isfinite(raw_price) and raw_price > 0:
                    price = raw_price * (1.0 - costs.slippage_rate)
                    gross = shares * price
                    commission = _commission(gross, costs)
                    cash += gross - commission
                    gross_traded += gross
                    fees += commission
                    order_count += 1
                    held = -1
                    shares = 0
            if target >= 0 and held == -1:
                raw_price = opens[index, target]
                if np.isfinite(raw_price) and raw_price > 0:
                    price = raw_price * (1.0 + costs.slippage_rate)
                    desired = int(equity_open * costs.target_weight / raw_price) // 100 * 100
                    while desired > 0:
                        gross = desired * price
                        commission = _commission(gross, costs)
                        if gross + commission <= cash + 1e-8:
                            break
                        desired -= 100
                    if desired > 0:
                        gross = desired * price
                        commission = _commission(gross, costs)
                        cash -= gross + commission
                        gross_traded += gross
                        fees += commission
                        order_count += 1
                        held = target
                        shares = desired
        market_value = 0.0
        if held >= 0 and shares > 0 and np.isfinite(last_marks[held]):
            market_value = shares * last_marks[held]
        values[index] = cash + market_value
        cash_values[index] = cash

    previous = np.concatenate(([float(initial_cash)], values[:-1]))
    returns = values / previous - 1.0
    years = len(values) / 250.0
    total_return = values[-1] / float(initial_cash) - 1.0
    annualized = (1.0 + total_return) ** (1.0 / years) - 1.0
    curve = np.concatenate(([float(initial_cash)], values))
    drawdown = curve / np.maximum.accumulate(curve) - 1.0
    standard_deviation = returns.std(ddof=1)
    volatility = standard_deviation * math.sqrt(250.0)
    sharpe = returns.mean() / standard_deviation * math.sqrt(250.0)
    downside = np.minimum(returns, 0).std(ddof=1) * math.sqrt(250.0)
    underwater = drawdown < -1e-12
    longest = current = 0
    for flag in underwater:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    rolling = values[756:] / values[:-756] - 1.0 if len(values) > 756 else np.array([])
    maximum_drawdown = float(-drawdown.min())
    return {
        "trading_days": len(values),
        "total_return": float(total_return),
        "annualized_return": float(annualized),
        "maximum_drawdown": maximum_drawdown,
        "sharpe": float(sharpe),
        "sortino": float(returns.mean() * 250.0 / downside) if downside > 0 else np.nan,
        "calmar": float(annualized / maximum_drawdown) if maximum_drawdown > 0 else np.nan,
        "annualized_volatility": float(volatility),
        "turnover": float(gross_traded / values.mean()),
        "transaction_fees": float(fees),
        "order_count": int(order_count),
        "average_cash_ratio": float(np.mean(cash_values / values)),
        "longest_underwater_trading_days": int(longest),
        "worst_rolling_three_year_return": (
            float(np.min(rolling)) if len(rolling) else None
        ),
    }


def run_parameter_grid(
    trading_dates,
    daily_by_symbol,
    weekly_by_symbol,
    gem_weekly,
    assets,
    costs,
):
    pairs = weekly_execution_pairs(trading_dates)
    observation_periods = [
        observation.to_period("W-FRI").end_time.normalize()
        for observation, _ in pairs
    ]
    execution_dates = [execution for _, execution in pairs]
    gem_close = gem_weekly["close"]
    nasdaq_close = weekly_by_symbol[assets["nasdaq"]]["close"]
    gold_close = weekly_by_symbol[assets["gold"]]["close"]
    cci_cache = {
        period: _rolling_close_cci(gem_close, period).reindex(observation_periods)
        for period in range(10, 21)
    }
    nasdaq_cache = {
        period: (
            nasdaq_close > nasdaq_close.rolling(period).mean()
        ).reindex(observation_periods).fillna(False)
        for period in range(30, 61)
    }
    gold_cache = {
        period: (
            gold_close > gold_close.rolling(period).mean()
        ).reindex(observation_periods).fillna(False)
        for period in range(30, 61)
    }
    role_order = ("gem", "nasdaq", "gold")
    opens = np.column_stack(
        [
            daily_by_symbol[assets[role]]["adjusted_open"]
            .reindex(trading_dates)
            .to_numpy(dtype=float)
            for role in role_order
        ]
    )
    closes = np.column_stack(
        [
            daily_by_symbol[assets[role]]["adjusted_close"]
            .reindex(trading_dates)
            .to_numpy(dtype=float)
            for role in role_order
        ]
    )
    execution_locations = {
        pd.Timestamp(date): index for index, date in enumerate(trading_dates)
    }
    role_codes = {role: index for index, role in enumerate(role_order)}
    rows = []
    for cci_period in range(10, 21):
        cci_values = cci_cache[cci_period].to_numpy(dtype=float)
        for threshold in range(100, 181, 10):
            gem_mask = np.isfinite(cci_values) & (cci_values > threshold)
            for ma_period in range(30, 61):
                nasdaq_mask = nasdaq_cache[ma_period].to_numpy(dtype=bool)
                gold_mask = gold_cache[ma_period].to_numpy(dtype=bool)
                roles = np.where(
                    gem_mask,
                    "gem",
                    np.where(nasdaq_mask, "nasdaq", np.where(gold_mask, "gold", "")),
                )
                event_targets = np.full(len(trading_dates), -2, dtype=np.int8)
                previous = object()
                for execution, role in zip(execution_dates, roles):
                    target = None if role == "" else str(role)
                    if target == previous:
                        continue
                    event_targets[execution_locations[pd.Timestamp(execution)]] = (
                        -1 if target is None else role_codes[target]
                    )
                    previous = target
                grid_metrics = _fast_single_asset_metrics(
                    trading_dates,
                    opens,
                    closes,
                    event_targets,
                    costs,
                )
                rows.append(
                    {
                        "cci_period": cci_period,
                        "cci_threshold": threshold,
                        "ma_period": ma_period,
                        **grid_metrics,
                    }
                )
    return pd.DataFrame(rows)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    return value


def _metric_table(frame, key_column):
    columns = [
        key_column,
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "turnover",
        "order_count",
    ]
    header = "| " + " | ".join(columns) + " |\n"
    separator = "|" + "---|" * len(columns) + "\n"
    rows = []
    for row in frame[columns].itertuples(index=False, name=None):
        values = [str(row[0])]
        values.extend(
            [
                "{:.2%}".format(row[1]),
                "{:.2%}".format(row[2]),
                "{:.2f}".format(row[3]),
                "{:.2f}".format(row[4]),
                str(int(row[5])),
            ]
        )
        rows.append("| " + " | ".join(values) + " |")
    return header + separator + "\n".join(rows)


def build_report(bundle, run_id):
    models = bundle["model_metrics"]
    periods = bundle["period_metrics"]
    replacements = bundle["replacement_metrics"]
    costs = bundle["cost_metrics"]
    grid = bundle["parameter_grid"]
    m4 = models.loc[models["model"].eq("m4")].iloc[0]
    m1 = models.loc[models["model"].eq("m1")].iloc[0]
    m2 = models.loc[models["model"].eq("m2")].iloc[0]
    m4_periods = periods[periods["model"].eq("m4")]
    grid_positive = float(grid["annualized_return"].gt(0).mean())
    grid_median_sharpe = float(grid["sharpe"].median())
    replacement_positive = int(replacements["annualized_return"].gt(0).sum())
    replacement_sharpe = int(replacements["sharpe"].ge(0.8).sum())
    stress = costs.loc[costs["cost_case"].eq("slippage-10bp")].iloc[0]
    criteria = {
        "M4 Sharpe 高于 M1/M2 且回撤未恶化 5pp": bool(
            m4["sharpe"] > max(m1["sharpe"], m2["sharpe"])
            and m4["maximum_drawdown"]
            <= min(m1["maximum_drawdown"], m2["maximum_drawdown"]) + 0.05
        ),
        "M4 三段正收益且至少两段 Sharpe>=0.8": bool(
            m4_periods["annualized_return"].gt(0).all()
            and m4_periods["sharpe"].ge(0.8).sum() >= 2
        ),
        "参数平原>=80%正收益且中位 Sharpe>=0.8": bool(
            grid_positive >= 0.8 and grid_median_sharpe >= 0.8
        ),
        "三项替换正收益且至少两项 Sharpe>=0.8": bool(
            replacement_positive == 3 and replacement_sharpe >= 2
        ),
        "10bp 单边滑点仍正年化": bool(stress["annualized_return"] > 0),
    }
    criteria_lines = "\n".join(
        "- {}：{}".format(name, "通过" if passed else "未通过")
        for name, passed in criteria.items()
    )
    original = grid[
        grid["cci_period"].eq(14)
        & grid["cci_threshold"].eq(130)
        & grid["ma_period"].eq(45)
    ].iloc[0]
    return """# 懒人 ETF 严格因果实验套件

## 结论

本报告只评价 2014—{end} 的可见历史，不构成发布后的样本外业绩。所有周频信号在周内
最后一个交易日收盘后确定，下一交易日开盘成交，不使用原策略的周五 14:50 当日最终
收盘价。

事前成功标准：

{criteria}

## 消融与外部基准

{model_table}

B0 与 M0、B4 与 M1 是刻意重复的基准别名。M3 使用标准 HLC CCI，M4 使用原策略的
close-only CCI，因此两者差异只来自 CCI 定义。

## M4 分阶段

{period_table}

## 参数平原

- 组合数：{grid_count}
- 正年化比例：{grid_positive:.2%}
- 年化中位数：{grid_annual_median:.2%}
- Sharpe 中位数：{grid_sharpe_median:.2f}
- 年化范围：{grid_annual_min:.2%} 至 {grid_annual_max:.2%}
- 原参数 14/130/45：年化 {original_annual:.2%}，最大回撤 {original_drawdown:.2%}，
  Sharpe {original_sharpe:.2f}

完整 3,069 组结果均保存在 `raw/parameter-grid.csv`，没有只保留最优值。

## 资产替换

{replacement_table}

替换实验逐次只改变一条风险资产腿。创业板替换会改用中证500 ETF 自身周线计算 CCI；
标普500和另一只黄金 ETF 则分别替换纳指与原黄金腿。

## 成本敏感性

{cost_table}

基础成本为 ETF 双边万三佣金、最低 5 元和单边 2bp 价格滑点，不征股票印花税。

## 事实与限制

- 运行标识：`{run_id}`；初始资金 100 万元；目标仓位 99%；100 份整数手。
- ETF 使用本地新浪连续复权日线 B 级数据；创业板指数输入快照随结果归档。
- 日线引擎未模拟成交量约束、ETF 溢价、跨境 ETF 申赎额度和尾盘盘口冲击。
- 连续复权价格保持总收益连续，但股数和最低佣金不是逐公司行为事件的精确复刻。
- 参数平原和替代资产都是在整段历史可见后执行的稳健性诊断，不能转化成真正的前瞻证据。

## 推断

消融实验用于区分底层资产 Beta、单资产趋势、黄金防御和创业板覆盖层的增量；参数平原
用于识别是否只在精确参数点成立；替换实验用于识别是否依赖原始三资产选择。是否具有
未来 Alpha，仍需冻结 M4 后继续积累未参与本报告的实盘或模拟盘数据。
""".format(
        end=bundle["dates"].max().date(),
        criteria=criteria_lines,
        model_table=_metric_table(models, "model"),
        period_table=_metric_table(m4_periods, "period"),
        grid_count=len(grid),
        grid_positive=grid_positive,
        grid_annual_median=grid["annualized_return"].median(),
        grid_sharpe_median=grid_median_sharpe,
        grid_annual_min=grid["annualized_return"].min(),
        grid_annual_max=grid["annualized_return"].max(),
        original_annual=original["annualized_return"],
        original_drawdown=original["maximum_drawdown"],
        original_sharpe=original["sharpe"],
        replacement_table=_metric_table(replacements, "replacement"),
        cost_table=_metric_table(costs, "cost_case"),
        run_id=run_id,
    )


def archive_results(bundle, run_id, archived_at="2026-08-11"):
    variant = "causal-experiment-suite"
    target = FAMILY_DIR / "backtests" / (archived_at + "__" + variant + "__" + run_id)
    if target.exists():
        raise FileExistsError("回测归档已存在，不可覆盖：%s" % target)
    raw = target / "raw"
    raw.mkdir(parents=True)

    bundle["model_metrics"].to_csv(raw / "model-metrics.csv", index=False, encoding="utf-8")
    bundle["period_metrics"].to_csv(raw / "period-metrics.csv", index=False, encoding="utf-8")
    bundle["replacement_metrics"].to_csv(
        raw / "asset-replacements.csv", index=False, encoding="utf-8"
    )
    bundle["cost_metrics"].to_csv(raw / "cost-sensitivity.csv", index=False, encoding="utf-8")
    bundle["parameter_grid"].to_csv(raw / "parameter-grid.csv", index=False, encoding="utf-8")
    bundle["gem_index"].to_csv(raw / "gem-index.csv", index=False, encoding="utf-8")

    equity_frames = []
    trade_frames = []
    position_frames = []
    decision_frames = []
    for result in bundle["results"].values():
        equity_frames.append(result.equity)
        if not result.trades.empty:
            trade_frames.append(result.trades)
        if not result.positions.empty:
            position_frames.append(result.positions)
        if not result.decisions.empty:
            decision_frames.append(result.decisions)
    pd.concat(equity_frames, ignore_index=True).to_csv(
        raw / "model-equity.csv", index=False, encoding="utf-8"
    )
    pd.concat(trade_frames, ignore_index=True).to_csv(
        raw / "model-trades.csv", index=False, encoding="utf-8"
    )
    pd.concat(position_frames, ignore_index=True).to_csv(
        raw / "model-positions.csv", index=False, encoding="utf-8"
    )
    pd.concat(decision_frames, ignore_index=True).to_csv(
        raw / "model-decisions.csv", index=False, encoding="utf-8"
    )

    shutil.copy2(FAMILY_DIR / "baseline.py", target / "source.py")
    shutil.copy2(Path(__file__).resolve(), target / "engine.py")
    artifacts = {}
    for path in sorted(raw.iterdir()):
        artifacts[path.name] = {
            "file": "raw/" + path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    source_hash = file_sha256(target / "source.py")
    engine_hash = file_sha256(target / "engine.py")
    m4_metrics = bundle["results"]["m4"].metrics
    manifest = {
        "schema_version": 1,
        "strategy_id": "lazy-etf-regime-switch",
        "variant": "causal-experiment-suite",
        "platform": "joinquant",
        "archived_at": archived_at,
        "run_id": run_id,
        "source_file": "source.py",
        "source_sha256": source_hash,
        "engine_file": "engine.py",
        "engine_sha256": engine_hash,
        "period": {
            "start": str(bundle["dates"].min().date()),
            "end": str(bundle["dates"].max().date()),
        },
        "execution": {
            "signal": "last trading day weekly close",
            "fill": "next trading day adjusted open",
            "initial_cash": 1000000,
            "target_weight": 0.99,
            "lot_size": 100,
        },
        "costs": {
            "commission_rate": 0.0003,
            "minimum_commission": 5.0,
            "slippage_rate": 0.0002,
            "stamp_tax": 0.0,
        },
        "metrics": _json_safe(m4_metrics),
        "experiment_counts": {
            "models_and_benchmarks": len(bundle["model_metrics"]),
            "subperiod_rows": len(bundle["period_metrics"]),
            "parameter_combinations": len(bundle["parameter_grid"]),
            "asset_replacements": len(bundle["replacement_metrics"]),
            "cost_cases": len(bundle["cost_metrics"]),
        },
        "data_manifests": {
            "etf_daily": {
                "path": str(bundle["store"].manifest_path("etf_daily")),
                "sha256": sha256_file(bundle["store"].manifest_path("etf_daily")),
            }
        },
        "artifacts": artifacts,
        "source": {
            "post": "https://www.joinquant.com/post/77576",
            "archive_commit": "02ec2a7",
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "report.md").write_text(
        build_report(bundle, run_id), encoding="utf-8"
    )
    return target


def parse_args():
    parser = argparse.ArgumentParser(description="懒人 ETF 严格因果实验套件")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("D:/code/_open-source/_data/quant-research"),
    )
    parser.add_argument("--gem-index-csv", type=Path)
    parser.add_argument("--start", default="2014-01-02")
    parser.add_argument("--end", default="2026-07-24")
    parser.add_argument("--run-id", default="local-etf-2014-2026-v1")
    parser.add_argument("--archived-at", default="2026-08-11")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    # 先载入 Parquet，随后才按需导入 AkShare，避免 Windows 原生库加载顺序干扰。
    store = ResearchDataStore(args.data_root)
    store.read_symbol_partitions("etf_daily", ALL_ETFS, columns=["symbol", "trade_date"])
    gem_index = load_gem_index(args.gem_index_csv)
    bundle = run_experiments(args.data_root, gem_index, start=args.start, end=args.end)
    summary = {
        "m4": bundle["results"]["m4"].metrics,
        "parameter_combinations": len(bundle["parameter_grid"]),
        "parameter_positive_rate": float(
            bundle["parameter_grid"]["annualized_return"].gt(0).mean()
        ),
        "asset_replacements": bundle["replacement_metrics"].to_dict("records"),
    }
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    if not args.no_archive:
        target = archive_results(bundle, args.run_id, archived_at=args.archived_at)
        print("结果已归档：%s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
