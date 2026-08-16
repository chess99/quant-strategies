"""ETF Core Rotation v2 条件式动量增强的预注册本地研究。"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

import local_backtest as engine


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


FAMILY_DIR = Path(__file__).resolve().parent
PROTOCOL_PATH = FAMILY_DIR / "protocols" / "2026-08-16-v2-conditional-overlay.json"
VARIANT_PATH = FAMILY_DIR / "variants" / "conditional_momentum_overlay_v2.py"
DEFAULT_OUTPUT = (
    FAMILY_DIR
    / "backtests"
    / "2026-08-16__conditional-momentum-overlay-v2__local-jq-2014-2026-v1"
)
CORE_EQUITY = "SH510300"
CORE_BOND = "SH511010"
CORE_GOLD = "SH518880"
HURDLE_CASH = "SH511880"
PERIODS = (
    ("full", "2014-01-02", "2026-07-24"),
    ("era_2014_2017", "2014-01-02", "2017-12-29"),
    ("era_2018_2021", "2018-01-02", "2021-12-31"),
    ("era_2022_2026", "2022-01-04", "2026-07-24"),
)
MODULE_FLAGS = (
    "use_excess_hurdle",
    "use_dispersion_gate",
    "use_rank_buffer",
    "use_correlation_guard",
)


@dataclass(frozen=True)
class V2Config:
    name: str = "frozen_v2"
    core_weights: tuple[tuple[str, float], ...] = (
        (CORE_EQUITY, 0.40),
        (CORE_BOND, 0.40),
        (CORE_GOLD, 0.20),
    )
    portfolio_mode: str = "overlay"
    active_sleeve: float = 0.30
    active_single_symbol_cap: float = 0.15
    lookbacks: tuple[int, int, int] = (63, 126, 252)
    top_k: int = 3
    rank_buffer: int = 2
    correlation_lookback: int = 60
    maximum_pair_correlation: float = 0.90
    minimum_excess_horizons: int = 2
    minimum_dispersion_iqr: float = 0.10
    minimum_adv20: float = 20_000_000.0
    maximum_adv_participation: float = 0.005
    minimum_trade_value: float = 2_000.0
    minimum_weight_change: float = 0.03
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    slippage_rate: float = 0.0010
    use_excess_hurdle: bool = True
    use_dispersion_gate: bool = True
    use_rank_buffer: bool = True
    use_correlation_guard: bool = True
    use_capacity: bool = True
    enforce_trade_adv_participation: bool = False
    capacity_scope_all_etfs: bool = False
    execution_lag_sessions: int = 1
    excluded_active_symbols: tuple[str, ...] = ()


@dataclass
class V2Result:
    config: V2Config
    equity: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    decisions: pd.DataFrame
    contributions: pd.DataFrame
    active_contributions: pd.DataFrame
    metrics: dict


def _engine_config(config: V2Config) -> engine.StrategyConfig:
    return engine.StrategyConfig(
        name=config.name,
        lookbacks=config.lookbacks,
        top_k=config.top_k,
        rank_buffer=config.rank_buffer,
        corr_lookback=config.correlation_lookback,
        max_pair_corr=config.maximum_pair_correlation,
        min_adv20=config.minimum_adv20,
        max_adv_participation=config.maximum_adv_participation,
        min_trade_value=config.minimum_trade_value,
        min_weight_change=config.minimum_weight_change,
        initial_cash=config.initial_cash,
        commission_rate=config.commission_rate,
        minimum_commission=config.minimum_commission,
        slippage_rate=config.slippage_rate,
        use_absolute_momentum=False,
        use_top_k=True,
        use_inverse_vol=False,
        use_vol_target=False,
        use_rank_buffer=config.use_rank_buffer,
        use_correlation_guard=config.use_correlation_guard,
        use_capacity=False,
        enforce_trade_adv_participation=config.enforce_trade_adv_participation,
        excluded_risk_symbols=config.excluded_active_symbols,
        execution_lag_sessions=config.execution_lag_sessions,
        capacity_scope_all_etfs=config.capacity_scope_all_etfs,
    )


def defensive_hurdles_from_prices(
    adjusted_close: pd.DataFrame,
    observation_date: pd.Timestamp,
    lookbacks: tuple[int, ...],
    *,
    bond_symbol: str = CORE_BOND,
    cash_symbol: str = HURDLE_CASH,
) -> dict[int, float]:
    """Return the investable per-horizon hurdle using only observation-date history."""

    date = pd.Timestamp(observation_date)
    hurdles = {}
    for lookback in lookbacks:
        candidates = [0.0]
        for symbol in (bond_symbol, cash_symbol):
            if symbol not in adjusted_close.columns:
                continue
            history = adjusted_close.loc[:date, symbol].dropna()
            if len(history) <= lookback:
                continue
            value = float(history.iloc[-1] / history.iloc[-lookback - 1] - 1.0)
            if np.isfinite(value):
                candidates.append(value)
        hurdles[int(lookback)] = max(candidates)
    return hurdles


def defensive_hurdles(
    data: engine.MarketData,
    observation_date: pd.Timestamp,
    lookbacks: tuple[int, ...],
) -> dict[int, float]:
    cache = getattr(data, "v2_hurdle_cache", None)
    if cache is None:
        cache = {}
        data.v2_hurdle_cache = cache
    key = (pd.Timestamp(observation_date), tuple(lookbacks))
    if key not in cache:
        cache[key] = defensive_hurdles_from_prices(
            data.adjusted_close,
            observation_date,
            lookbacks,
        )
    return cache[key]


def weekly_execution_pairs(
    data: engine.MarketData,
    lag_sessions: int,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    cache = getattr(data, "v2_execution_pair_cache", None)
    if cache is None:
        cache = {}
        data.v2_execution_pair_cache = cache
    if lag_sessions not in cache:
        cache[lag_sessions] = engine.weekly_execution_pairs(
            data.trade_dates,
            lag_sessions,
        )
    return cache[lag_sessions]


def valuation_arrays(
    data: engine.MarketData,
) -> tuple[np.ndarray, dict[str, int], dict[pd.Timestamp, int]]:
    cached = getattr(data, "v2_valuation_arrays", None)
    if cached is None:
        marks = data.adjusted_close.reindex(index=data.trade_dates).combine_first(
            data.adjusted_open.reindex(index=data.trade_dates)
        )
        marks = marks.ffill()
        cached = (
            marks.to_numpy(dtype=float),
            {symbol: index for index, symbol in enumerate(marks.columns)},
            {date: index for index, date in enumerate(marks.index)},
        )
        data.v2_valuation_arrays = cached
    return cached


def add_excess_gate(
    ranked: pd.DataFrame,
    lookbacks: tuple[int, ...],
    hurdles: dict[int, float],
    *,
    minimum_horizons: int,
) -> pd.DataFrame:
    frame = ranked.copy()
    flags = []
    for lookback in lookbacks:
        column = f"excess_{lookback}"
        frame[column] = frame[f"r{lookback}"].gt(float(hurdles.get(lookback, 0.0)))
        flags.append(column)
    frame["excess_count"] = frame[flags].sum(axis=1)
    frame["excess_pass"] = frame["excess_count"].ge(minimum_horizons)
    return frame


def cross_sectional_dispersion(ranked: pd.DataFrame, middle_lookback: int) -> float:
    if ranked.empty:
        return float("nan")
    values = pd.to_numeric(ranked[f"r{middle_lookback}"], errors="coerce").dropna()
    if len(values) < 4:
        return float("nan")
    return float(values.quantile(0.75) - values.quantile(0.25))


def prepared_signal_frame(
    snapshot: engine.Snapshot,
    data: engine.MarketData,
    config: V2Config,
) -> tuple[pd.DataFrame, dict[int, float], float]:
    cache = getattr(data, "v2_signal_frame_cache", None)
    if cache is None:
        cache = {}
        data.v2_signal_frame_cache = cache
    key = (
        snapshot.observation_date,
        config.lookbacks,
        float(config.minimum_adv20),
        config.excluded_active_symbols,
    )
    if key not in cache:
        ranked = snapshot.ranked.copy()
        if config.excluded_active_symbols:
            ranked = ranked.drop(
                index=list(config.excluded_active_symbols),
                errors="ignore",
            )
        hurdles = defensive_hurdles(
            data,
            snapshot.observation_date,
            config.lookbacks,
        )
        ranked = add_excess_gate(
            ranked,
            config.lookbacks,
            hurdles,
            minimum_horizons=1,
        )
        dispersion = cross_sectional_dispersion(ranked, config.lookbacks[1])
        cache[key] = (ranked, hurdles, dispersion)
    return cache[key]


def compose_core_and_satellite(
    config: V2Config,
    selected: list[str],
    active_caps: dict[str, float] | None = None,
) -> dict[str, float]:
    """Fund the active sleeve by scaling core; return unused budget to core pro rata."""

    selected = list(dict.fromkeys(selected))
    active_caps = active_caps or {}
    active_weights = {}
    if selected:
        equal = min(config.active_sleeve / len(selected), config.active_single_symbol_cap)
        for symbol in selected:
            active_weights[symbol] = min(equal, active_caps.get(symbol, equal))
    allocated = min(1.0, sum(active_weights.values()))
    core = dict(config.core_weights)
    core_total = sum(core.values())
    if core_total <= 0:
        raise ValueError("strategic core weights must sum to a positive value")
    target = {
        symbol: weight / core_total * (1.0 - allocated)
        for symbol, weight in core.items()
    }
    for symbol, weight in active_weights.items():
        target[symbol] = target.get(symbol, 0.0) + weight
    return {symbol: weight for symbol, weight in target.items() if weight > 1e-12}


def select_satellite(
    snapshot: engine.Snapshot,
    previous_selected: list[str],
    data: engine.MarketData,
    config: V2Config,
) -> tuple[list[str], pd.DataFrame, dict]:
    ranked, hurdles, dispersion = prepared_signal_frame(snapshot, data, config)
    dispersion_open = (
        np.isfinite(dispersion) and dispersion >= config.minimum_dispersion_iqr
    )
    diagnostics = {
        "hurdles": hurdles,
        "dispersion_iqr": dispersion,
        "dispersion_gate_open": bool(dispersion_open),
        "excess_pass_count": int(
            ranked["excess_count"].ge(config.minimum_excess_horizons).sum()
        )
        if len(ranked)
        else 0,
    }
    if ranked.empty or (config.use_dispersion_gate and not dispersion_open):
        return [], ranked, diagnostics
    passed = (
        ranked[ranked["excess_count"].ge(config.minimum_excess_horizons)]
        if config.use_excess_hurdle
        else ranked
    )
    if passed.empty:
        return [], ranked, diagnostics
    rank_map = passed["rank"].to_dict()
    selected = []
    strategy_config = _engine_config(config)
    if config.use_rank_buffer:
        keep = [
            symbol
            for symbol in previous_selected
            if symbol in rank_map and rank_map[symbol] <= config.top_k + config.rank_buffer
        ]
        keep.sort(key=rank_map.__getitem__)
        for symbol in keep:
            if len(selected) >= config.top_k:
                break
            if engine.correlation_ok(
                symbol,
                selected,
                snapshot.observation_date,
                data,
                strategy_config,
            ):
                selected.append(symbol)
    for symbol in passed.index:
        if len(selected) >= config.top_k:
            break
        if symbol in selected:
            continue
        if engine.correlation_ok(
            symbol,
            selected,
            snapshot.observation_date,
            data,
            strategy_config,
        ):
            selected.append(symbol)
    return selected, ranked, diagnostics


def _active_target_caps(
    selected: list[str],
    ranked: pd.DataFrame,
    portfolio_value: float,
    config: V2Config,
) -> dict[str, float]:
    if not config.use_capacity or portfolio_value <= 0:
        return {}
    caps = {}
    for symbol in selected:
        adv = float(ranked.at[symbol, "adv20"])
        caps[symbol] = max(
            0.0,
            adv * config.maximum_adv_participation / portfolio_value,
        )
    return caps


def build_targets(
    snapshot: engine.Snapshot,
    previous_selected: list[str],
    portfolio_value: float,
    data: engine.MarketData,
    config: V2Config,
) -> tuple[dict[str, float], dict[str, float], list[str], dict]:
    if config.portfolio_mode == "core_only":
        return compose_core_and_satellite(config, []), {}, [], {
            "dispersion_iqr": np.nan,
            "dispersion_gate_open": False,
            "excess_pass_count": 0,
            "hurdles": {},
        }
    selected, ranked, diagnostics = select_satellite(
        snapshot,
        previous_selected,
        data,
        config,
    )
    if config.portfolio_mode == "satellite_only":
        if not selected:
            return {HURDLE_CASH: 1.0}, {}, [], diagnostics
        active = {symbol: 1.0 / len(selected) for symbol in selected}
        return dict(active), active, selected, diagnostics
    if config.portfolio_mode != "overlay":
        raise ValueError(f"unknown portfolio mode: {config.portfolio_mode}")
    caps = _active_target_caps(selected, ranked, portfolio_value, config)
    target = compose_core_and_satellite(config, selected, caps)
    active = {}
    if selected:
        equal = min(config.active_sleeve / len(selected), config.active_single_symbol_cap)
        active = {symbol: min(equal, caps.get(symbol, equal)) for symbol in selected}
    return target, active, selected, diagnostics


def _active_fractions(
    positions: dict[str, int],
    target: dict[str, float],
    active: dict[str, float],
    previous: dict[str, float],
) -> dict[str, float]:
    fractions = {}
    for symbol in positions:
        if symbol in target and target[symbol] > 0:
            fractions[symbol] = min(1.0, max(0.0, active.get(symbol, 0.0) / target[symbol]))
        else:
            fractions[symbol] = previous.get(symbol, 0.0)
    return fractions


def _finish_metrics(
    equity: pd.DataFrame,
    gate_count: int,
    decision_count: int,
) -> dict:
    metrics = engine.performance_metrics(equity)
    metrics["average_active_exposure"] = float(equity["active_weight"].mean())
    metrics["maximum_active_exposure"] = float(equity["active_weight"].max())
    metrics["gate_open_ratio"] = gate_count / decision_count if decision_count else 0.0
    metrics["decision_count"] = int(decision_count)
    return metrics


def run_simulation_fast(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    config: V2Config,
    start: str = engine.DEFAULT_START,
    end: str = engine.DEFAULT_END,
) -> V2Result:
    dates = data.trade_dates[
        (data.trade_dates >= pd.Timestamp(start)) & (data.trade_dates <= pd.Timestamp(end))
    ]
    if len(dates) == 0:
        raise ValueError("backtest period has no trading dates")
    strategy_config = _engine_config(config)
    observation_by_execution = {
        execution: observation
        for observation, execution in weekly_execution_pairs(
            data, config.execution_lag_sessions
        )
        if execution in dates
    }
    execution_dates = sorted(observation_by_execution)
    cash = float(config.initial_cash)
    positions = {}
    last_close = {}
    previous_selected = []
    active_fraction = {}
    gate_count = 0
    decision_count = 0
    total_values = np.full(len(dates), np.nan)
    cash_values = np.full(len(dates), np.nan)
    position_values = np.full(len(dates), np.nan)
    active_values = np.full(len(dates), np.nan)
    gross_traded = np.zeros(len(dates))
    transaction_cost = np.zeros(len(dates))
    holdings = np.full(len(dates), "", dtype=object)
    date_locations = {date: index for index, date in enumerate(dates)}
    mark_values, mark_columns, mark_dates = valuation_arrays(data)

    def value_segment(
        segment: pd.DatetimeIndex,
        traded_on_first_day: float,
        cost_on_first_day: float,
    ) -> None:
        if len(segment) == 0:
            return
        locations = np.array([date_locations[date] for date in segment], dtype=int)
        if positions:
            symbols = sorted(positions)
            row_locations = np.array([mark_dates[date] for date in segment], dtype=int)
            column_locations = np.array([mark_columns[symbol] for symbol in symbols], dtype=int)
            shares = np.array([positions[symbol] for symbol in symbols], dtype=float)
            matrix = mark_values[np.ix_(row_locations, column_locations)]
            if not np.isfinite(matrix).all():
                raise AssertionError("held position has no causal valuation mark")
            values = matrix @ shares
            active_shares = np.array(
                [positions[symbol] * active_fraction.get(symbol, 0.0) for symbol in symbols],
                dtype=float,
            )
            active = matrix @ active_shares
            for column, symbol in enumerate(symbols):
                if np.isfinite(matrix[-1, column]):
                    last_close[symbol] = float(matrix[-1, column])
            holding_text = ";".join(symbols)
        else:
            values = np.zeros(len(segment))
            active = np.zeros(len(segment))
            holding_text = ""
        cash_values[locations] = cash
        position_values[locations] = values
        active_values[locations] = active
        total_values[locations] = cash + values
        holdings[locations] = holding_text
        gross_traded[locations[0]] = traded_on_first_day
        transaction_cost[locations[0]] = cost_on_first_day

    first_execution = date_locations[execution_dates[0]] if execution_dates else len(dates)
    if first_execution:
        value_segment(dates[:first_execution], 0.0, 0.0)
    for index, execution_date in enumerate(execution_dates):
        observation = observation_by_execution[execution_date]
        equity_open = cash
        for symbol, shares in positions.items():
            price = engine._matrix_value(data.adjusted_open, execution_date, symbol)
            mark = price if price is not None else last_close.get(symbol)
            if mark is not None:
                equity_open += shares * mark
        snapshot = cache.get(observation, strategy_config)
        target, active, selected, diagnostics = build_targets(
            snapshot,
            previous_selected,
            equity_open,
            data,
            config,
        )
        old_fraction = dict(active_fraction)
        cash, positions, _, _, traded, cost = engine._execute_targets(
            execution_date,
            observation,
            target,
            equity_open,
            cash,
            positions,
            data,
            strategy_config,
            False,
        )
        active_fraction = _active_fractions(positions, target, active, old_fraction)
        previous_selected = list(selected)
        decision_count += 1
        gate_count += int(
            bool(selected)
            and (not config.use_dispersion_gate or diagnostics["dispersion_gate_open"])
        )
        start_location = date_locations[execution_date]
        end_location = (
            date_locations[execution_dates[index + 1]]
            if index + 1 < len(execution_dates)
            else len(dates)
        )
        value_segment(dates[start_location:end_location], traded, cost)
    if np.isnan(total_values).any():
        raise AssertionError("v2 fast simulator left unvalued dates")
    previous_values = np.concatenate(([config.initial_cash], total_values[:-1]))
    equity = pd.DataFrame(
        {
            "trade_date": dates,
            "cash": cash_values,
            "positions_value": position_values,
            "total_value": total_values,
            "daily_return": total_values / previous_values - 1.0,
            "cash_ratio": cash_values / total_values,
            "risk_weight": active_values / total_values,
            "active_weight": active_values / total_values,
            "gross_traded": gross_traded,
            "transaction_cost": transaction_cost,
            "holdings": holdings,
            "unattributed_pnl": np.nan,
        }
    )
    return V2Result(
        config=config,
        equity=equity,
        trades=pd.DataFrame(),
        positions=pd.DataFrame(),
        decisions=pd.DataFrame(),
        contributions=pd.DataFrame(),
        active_contributions=pd.DataFrame(),
        metrics=_finish_metrics(equity, gate_count, decision_count),
    )


def run_simulation(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    config: V2Config,
    start: str = engine.DEFAULT_START,
    end: str = engine.DEFAULT_END,
    *,
    capture_details: bool = False,
) -> V2Result:
    if not capture_details:
        return run_simulation_fast(data, cache, config, start, end)
    dates = data.trade_dates[
        (data.trade_dates >= pd.Timestamp(start)) & (data.trade_dates <= pd.Timestamp(end))
    ]
    if len(dates) == 0:
        raise ValueError("backtest period has no trading dates")
    strategy_config = _engine_config(config)
    observation_by_execution = {
        execution: observation
        for observation, execution in weekly_execution_pairs(
            data, config.execution_lag_sessions
        )
        if execution in dates
    }
    cash = float(config.initial_cash)
    positions = {}
    last_close = {}
    previous_selected = []
    active_fraction = {}
    previous_total = float(config.initial_cash)
    gate_count = 0
    decision_count = 0
    equity_rows = []
    trade_rows = []
    position_rows = []
    decision_rows = []
    contribution_rows = []
    active_contribution_rows = []
    for date in dates:
        old_positions = dict(positions)
        old_last_close = dict(last_close)
        old_active_fraction = dict(active_fraction)
        open_marks = {}
        equity_open = cash
        for symbol, shares in old_positions.items():
            price = engine._matrix_value(data.adjusted_open, date, symbol)
            mark = price if price is not None else old_last_close.get(symbol)
            if mark is not None:
                open_marks[symbol] = float(mark)
                equity_open += shares * float(mark)
        day_costs = {}
        day_traded = 0.0
        day_total_cost = 0.0
        if date in observation_by_execution:
            observation = observation_by_execution[date]
            snapshot = cache.get(observation, strategy_config)
            target, active, selected, diagnostics = build_targets(
                snapshot,
                previous_selected,
                equity_open,
                data,
                config,
            )
            (
                cash,
                positions,
                executed,
                day_costs,
                day_traded,
                day_total_cost,
            ) = engine._execute_targets(
                date,
                observation,
                target,
                equity_open,
                cash,
                positions,
                data,
                strategy_config,
                True,
            )
            trade_rows.extend(executed)
            active_fraction = _active_fractions(
                positions,
                target,
                active,
                old_active_fraction,
            )
            previous_selected = list(selected)
            decision_count += 1
            gate_open = bool(selected) and (
                not config.use_dispersion_gate or diagnostics["dispersion_gate_open"]
            )
            gate_count += int(gate_open)
            decision_rows.append(
                {
                    "execution_date": date,
                    "observation_date": observation,
                    "raw_eligible_count": snapshot.raw_eligible_count,
                    "deduplicated_count": snapshot.deduplicated_count,
                    "liquid_count": snapshot.liquid_count,
                    "excess_pass_count": diagnostics["excess_pass_count"],
                    "dispersion_iqr": diagnostics["dispersion_iqr"],
                    "dispersion_gate_open": diagnostics["dispersion_gate_open"],
                    "gate_open": gate_open,
                    "selected": ";".join(selected),
                    "active_target_weight": sum(active.values()),
                    "target_weights": json.dumps(target, ensure_ascii=False, sort_keys=True),
                    "active_weights": json.dumps(active, ensure_ascii=False, sort_keys=True),
                    "target_weight_sum": sum(target.values()),
                    "hurdles": json.dumps(
                        diagnostics["hurdles"], ensure_ascii=False, sort_keys=True
                    ),
                }
            )
        close_marks = {}
        positions_value = 0.0
        active_value = 0.0
        for symbol, shares in sorted(positions.items()):
            price = engine._matrix_value(data.adjusted_close, date, symbol)
            if price is None:
                price = engine._matrix_value(data.adjusted_open, date, symbol)
            if price is None:
                price = open_marks.get(symbol, old_last_close.get(symbol))
            if price is None:
                continue
            close_marks[symbol] = float(price)
            last_close[symbol] = float(price)
            market_value = shares * float(price)
            fraction = active_fraction.get(symbol, 0.0)
            active_market_value = market_value * fraction
            positions_value += market_value
            active_value += active_market_value
            position_rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "shares": shares,
                    "adjusted_close": price,
                    "market_value": market_value,
                    "active_fraction": fraction,
                    "active_market_value": active_market_value,
                }
            )
        total_value = cash + positions_value
        total_contributions = {}
        active_contributions = {}
        for symbol, shares in old_positions.items():
            previous_price = old_last_close.get(symbol)
            current_open = open_marks.get(symbol, previous_price)
            if previous_price is not None and current_open is not None:
                pnl = shares * (current_open - previous_price)
                total_contributions[symbol] = total_contributions.get(symbol, 0.0) + pnl
                active_contributions[symbol] = active_contributions.get(symbol, 0.0) + (
                    pnl * old_active_fraction.get(symbol, 0.0)
                )
        for symbol, shares in positions.items():
            current_open = engine._matrix_value(data.adjusted_open, date, symbol)
            current_close = close_marks.get(symbol)
            if current_open is not None and current_close is not None:
                pnl = shares * (current_close - current_open)
                total_contributions[symbol] = total_contributions.get(symbol, 0.0) + pnl
                active_contributions[symbol] = active_contributions.get(symbol, 0.0) + (
                    pnl * active_fraction.get(symbol, 0.0)
                )
        for symbol, cost in day_costs.items():
            total_contributions[symbol] = total_contributions.get(symbol, 0.0) - cost
            active_share = max(
                old_active_fraction.get(symbol, 0.0),
                active_fraction.get(symbol, 0.0),
            )
            active_contributions[symbol] = active_contributions.get(symbol, 0.0) - (
                cost * active_share
            )
        for symbol, pnl in total_contributions.items():
            contribution_rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "net_pnl_contribution": pnl,
                    "return_contribution": pnl / previous_total,
                }
            )
        for symbol, pnl in active_contributions.items():
            active_contribution_rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "active_net_pnl_contribution": pnl,
                    "active_return_contribution": pnl / previous_total,
                }
            )
        attributed = sum(total_contributions.values())
        unattributed = total_value - previous_total - attributed
        equity_rows.append(
            {
                "trade_date": date,
                "cash": cash,
                "positions_value": positions_value,
                "total_value": total_value,
                "daily_return": total_value / previous_total - 1.0,
                "cash_ratio": cash / total_value if total_value > 0 else np.nan,
                "risk_weight": active_value / total_value if total_value > 0 else np.nan,
                "active_weight": active_value / total_value if total_value > 0 else np.nan,
                "gross_traded": day_traded,
                "transaction_cost": day_total_cost,
                "holdings": ";".join(sorted(positions)),
                "unattributed_pnl": unattributed,
            }
        )
        previous_total = total_value
    equity = pd.DataFrame(equity_rows)
    return V2Result(
        config=config,
        equity=equity,
        trades=pd.DataFrame(trade_rows),
        positions=pd.DataFrame(position_rows),
        decisions=pd.DataFrame(decision_rows),
        contributions=pd.DataFrame(contribution_rows),
        active_contributions=pd.DataFrame(active_contribution_rows),
        metrics=_finish_metrics(equity, gate_count, decision_count),
    )


def module_factorial_configs(base: V2Config) -> list[V2Config]:
    configs = []
    for bits in itertools.product((False, True), repeat=len(MODULE_FLAGS)):
        flags = dict(zip(MODULE_FLAGS, bits))
        name = "factorial_" + "".join("1" if value else "0" for value in bits)
        configs.append(replace(base, name=name, **flags))
    return configs


def parameter_configs(base: V2Config) -> list[V2Config]:
    configs = []
    products = itertools.product(
        ((42, 84, 168), (63, 126, 252), (84, 168, 252)),
        (2, 3, 4),
        (0.20, 0.30, 0.40),
        (1, 2, 3),
        (0.05, 0.10, 0.15),
        (1, 2, 3),
        (0.85, 0.90, 0.95),
    )
    for index, values in enumerate(products, start=1):
        lookbacks, top_k, sleeve, excess, dispersion, buffer, correlation = values
        configs.append(
            replace(
                base,
                name=f"grid_{index:04d}",
                lookbacks=lookbacks,
                top_k=top_k,
                active_sleeve=sleeve,
                minimum_excess_horizons=excess,
                minimum_dispersion_iqr=dispersion,
                rank_buffer=buffer,
                maximum_pair_correlation=correlation,
            )
        )
    return configs


def config_columns(config: V2Config) -> dict:
    return {
        "trial": config.name,
        "lookbacks": "/".join(str(value) for value in config.lookbacks),
        "top_k": config.top_k,
        "active_sleeve": config.active_sleeve,
        "minimum_excess_horizons": config.minimum_excess_horizons,
        "minimum_dispersion_iqr": config.minimum_dispersion_iqr,
        "rank_buffer": config.rank_buffer,
        "maximum_pair_correlation": config.maximum_pair_correlation,
        "minimum_adv20": config.minimum_adv20,
        "initial_cash": config.initial_cash,
    }


def result_row(result: V2Result) -> dict:
    return {**config_columns(result.config), **result.metrics}


def evaluate_success_criteria(facts: dict) -> dict:
    def finite_nonzero(value) -> bool:
        return value is not None and np.isfinite(value) and value != 0

    local_active_excess = facts.get("local_active_excess")
    platform_active_excesses = [
        facts.get("joinquant_pit_active_excess"),
        facts.get("joinquant_official_active_excess"),
    ]
    platform_sign_consistent = finite_nonzero(local_active_excess) and all(
        finite_nonzero(value) and np.sign(value) == np.sign(local_active_excess)
        for value in platform_active_excesses
    )

    risk_flags = [
        facts["v2_sharpe"] >= facts["core_sharpe"] + 0.05,
        facts["v2_maximum_drawdown"] <= facts["core_maximum_drawdown"],
        facts["v2_worst_rolling_return"] >= facts["core_worst_rolling_return"],
    ]
    criteria = {
        "cost_adjusted_increment": {
            "passed": facts["cost20_v2_cagr"] > facts["cost20_core_cagr"],
            "value": facts["cost20_v2_cagr"] - facts["cost20_core_cagr"],
        },
        "rolling_three_year": {
            "passed": facts["rolling_win_ratio"] >= 0.60
            and facts["worst_rolling_active_excess"] > -0.10,
            "value": {
                "win_ratio": facts["rolling_win_ratio"],
                "worst_active_excess": facts["worst_rolling_active_excess"],
            },
        },
        "risk_improvement": {
            "passed": sum(risk_flags) >= 2,
            "value": {"passed_components": int(sum(risk_flags)), "components": risk_flags},
        },
        "standalone_satellite": {
            "passed": facts["satellite_sharpe"] > 0
            and facts["satellite_20bp_sharpe"] > 0,
            "value": [facts["satellite_sharpe"], facts["satellite_20bp_sharpe"]],
        },
        "multiple_testing": {
            "passed": facts["pbo"] <= 0.40
            and facts["frozen_dsr_probability"] >= 0.80,
            "value": [facts["pbo"], facts["frozen_dsr_probability"]],
        },
        "concentration": {
            "passed": facts["top1_positive_contribution_share"] <= 0.25
            and facts["exclude_top1_active_excess"] > 0,
            "value": [
                facts["top1_positive_contribution_share"],
                facts["exclude_top1_active_excess"],
            ],
        },
        "capacity": {
            "passed": facts["capacity_10m_average_active_exposure"] >= 0.20
            and facts["capacity_10m_active_excess"] > 0,
            "value": [
                facts["capacity_10m_average_active_exposure"],
                facts["capacity_10m_active_excess"],
            ],
        },
        "platform": {
            "passed": platform_sign_consistent,
            "value": platform_active_excesses,
        },
    }
    return {
        "criteria": criteria,
        "passed_count": int(sum(item["passed"] for item in criteria.values())),
        "criterion_count": len(criteria),
        "overall_pass": all(item["passed"] for item in criteria.values()),
    }


def paired_module_effects(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metrics = (
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "annualized_turnover",
        "average_active_exposure",
    )
    for period, period_frame in frame.groupby("period", sort=False):
        for module in MODULE_FLAGS:
            others = [flag for flag in MODULE_FLAGS if flag != module]
            deltas = []
            for _, pair in period_frame.groupby(others, dropna=False):
                enabled = pair[pair[module]]
                disabled = pair[~pair[module]]
                if len(enabled) != 1 or len(disabled) != 1:
                    continue
                on = enabled.iloc[0]
                off = disabled.iloc[0]
                deltas.append({metric: float(on[metric] - off[metric]) for metric in metrics})
            delta_frame = pd.DataFrame(deltas)
            row = {"period": period, "module": module, "pair_count": len(delta_frame)}
            for metric in metrics:
                row[f"mean_delta_{metric}"] = float(delta_frame[metric].mean())
                row[f"median_delta_{metric}"] = float(delta_frame[metric].median())
            row["positive_sharpe_pair_ratio"] = float(delta_frame["sharpe"].gt(0).mean())
            rows.append(row)
    return pd.DataFrame(rows)


def parameter_stability_summary(grid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dimensions = (
        "lookbacks",
        "top_k",
        "active_sleeve",
        "minimum_excess_horizons",
        "minimum_dispersion_iqr",
        "rank_buffer",
        "maximum_pair_correlation",
    )
    for dimension in dimensions:
        for value, group in grid.groupby(dimension, dropna=False):
            rows.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "trial_count": int(len(group)),
                    "positive_annualized_ratio": float(
                        group["annualized_return"].gt(0).mean()
                    ),
                    "median_annualized_return": float(group["annualized_return"].median()),
                    "q25_annualized_return": float(group["annualized_return"].quantile(0.25)),
                    "q75_annualized_return": float(group["annualized_return"].quantile(0.75)),
                    "median_maximum_drawdown": float(group["maximum_drawdown"].median()),
                    "median_sharpe": float(group["sharpe"].median()),
                    "q25_sharpe": float(group["sharpe"].quantile(0.25)),
                    "q75_sharpe": float(group["sharpe"].quantile(0.75)),
                    "median_annualized_turnover": float(
                        group["annualized_turnover"].median()
                    ),
                    "median_active_exposure": float(
                        group["average_active_exposure"].median()
                    ),
                }
            )
    return pd.DataFrame(rows)


def rolling_three_year_comparison(
    candidate: pd.DataFrame,
    core: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    left = candidate[["trade_date", "daily_return"]].rename(
        columns={"daily_return": "v2_return"}
    )
    right = core[["trade_date", "daily_return"]].rename(
        columns={"daily_return": "core_return"}
    )
    frame = left.merge(right, on="trade_date", how="inner")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    v2_curve = (1.0 + frame["v2_return"]).cumprod()
    core_curve = (1.0 + frame["core_return"]).cumprod()
    frame["v2_three_year_return"] = v2_curve / v2_curve.shift(756) - 1.0
    frame["core_three_year_return"] = core_curve / core_curve.shift(756) - 1.0
    frame["active_excess"] = (
        frame["v2_three_year_return"] - frame["core_three_year_return"]
    )
    month_ends = frame.groupby(frame["trade_date"].dt.to_period("M")).tail(1)
    windows = month_ends.dropna(subset=["active_excess"]).copy()
    windows["window_start"] = windows["trade_date"].map(
        lambda date: frame.loc[
            max(0, frame.index[frame["trade_date"].eq(date)][0] - 756), "trade_date"
        ]
    )
    summary = {
        "window_count": int(len(windows)),
        "v2_win_ratio": float(windows["active_excess"].gt(0).mean()),
        "worst_active_excess": float(windows["active_excess"].min()),
        "median_active_excess": float(windows["active_excess"].median()),
        "worst_v2_three_year_return": float(windows["v2_three_year_return"].min()),
        "worst_core_three_year_return": float(windows["core_three_year_return"].min()),
    }
    return windows[
        [
            "window_start",
            "trade_date",
            "v2_three_year_return",
            "core_three_year_return",
            "active_excess",
        ]
    ], summary


def yearly_comparison(candidate: V2Result, core: V2Result) -> pd.DataFrame:
    left = engine.yearly_metrics(candidate.equity).add_prefix("v2_").rename(
        columns={"v2_year": "year"}
    )
    right = engine.yearly_metrics(core.equity).add_prefix("core_").rename(
        columns={"core_year": "year"}
    )
    frame = left.merge(right, on="year", how="inner")
    frame["annualized_excess"] = (
        frame["v2_annualized_return"] - frame["core_annualized_return"]
    )
    return frame


def regime_comparison(
    candidate: V2Result,
    core: V2Result,
    data: engine.MarketData,
) -> pd.DataFrame:
    left = engine.regime_metrics(candidate, data).add_prefix("v2_").rename(
        columns={"v2_regime": "regime"}
    )
    right = engine.regime_metrics(core, data).add_prefix("core_").rename(
        columns={"core_regime": "regime"}
    )
    frame = left.merge(right, on="regime", how="inner")
    frame["annualized_excess"] = (
        frame["v2_annualized_return"] - frame["core_annualized_return"]
    )
    return frame


def active_concentration(result: V2Result) -> tuple[pd.DataFrame, dict]:
    frame = result.active_contributions.copy()
    if frame.empty:
        return pd.DataFrame(), {
            "active_symbol_count": 0,
            "top1_positive_contribution_share": 0.0,
            "top3_positive_contribution_share": 0.0,
            "top5_positive_contribution_share": 0.0,
            "positive_contribution_hhi": 0.0,
            "top_active_symbols": [],
        }
    table = (
        frame.groupby("symbol", as_index=False)[
            ["active_net_pnl_contribution", "active_return_contribution"]
        ]
        .sum()
        .sort_values("active_net_pnl_contribution", ascending=False)
        .reset_index(drop=True)
    )
    positive = table["active_net_pnl_contribution"].clip(lower=0)
    total = float(positive.sum())
    table["share_of_positive_contribution"] = positive / total if total > 0 else 0.0
    shares = table["share_of_positive_contribution"].to_numpy(dtype=float)
    summary = {
        "active_symbol_count": int(table["symbol"].nunique()),
        "top1_positive_contribution_share": float(shares[:1].sum()),
        "top3_positive_contribution_share": float(shares[:3].sum()),
        "top5_positive_contribution_share": float(shares[:5].sum()),
        "positive_contribution_hhi": float(np.square(shares).sum()),
        "top_active_symbols": table.head(5)["symbol"].tolist(),
    }
    return table, summary


def moving_block_bootstrap(
    excess_returns: np.ndarray,
    block_sessions: int,
    *,
    resamples: int = 2000,
    seed: int = 20260816,
) -> dict:
    values = np.asarray(excess_returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < block_sessions:
        raise ValueError("bootstrap series is shorter than its block")
    rng = np.random.default_rng(seed + block_sessions)
    blocks_needed = math.ceil(len(values) / block_sessions)
    maximum_start = len(values) - block_sessions
    annualized = np.empty(resamples)
    for index in range(resamples):
        starts = rng.integers(0, maximum_start + 1, size=blocks_needed)
        sampled = np.concatenate(
            [values[start : start + block_sessions] for start in starts]
        )[: len(values)]
        annualized[index] = sampled.mean() * 252.0
    return {
        "block_sessions": int(block_sessions),
        "resamples": int(resamples),
        "seed": int(seed + block_sessions),
        "observed_annualized_mean_excess": float(values.mean() * 252.0),
        "probability_positive": float(np.mean(annualized > 0)),
        "q025": float(np.quantile(annualized, 0.025)),
        "median": float(np.quantile(annualized, 0.50)),
        "q975": float(np.quantile(annualized, 0.975)),
    }


def expanding_walk_forward(
    return_matrix: np.ndarray,
    dates: pd.DatetimeIndex,
    configs: list[V2Config],
    frozen_returns: np.ndarray,
    core_returns: np.ndarray,
    first_test_year: int = 2019,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    combined = np.full(len(dates), np.nan)
    rows = []
    for year in range(first_test_year, int(dates.max().year) + 1):
        train_mask = dates.year < year
        test_mask = dates.year == year
        if train_mask.sum() < 756 or not test_mask.any():
            continue
        train_sharpes = engine._sharpe_by_trial(return_matrix[:, train_mask])
        winner = int(np.nanargmax(train_sharpes))
        combined[test_mask] = return_matrix[winner, test_mask]
        oos = engine._metrics_from_return_array(
            return_matrix[winner, test_mask], dates[test_mask]
        )
        rows.append(
            {
                "test_year": year,
                "train_start": dates[train_mask].min(),
                "train_end": dates[train_mask].max(),
                "test_start": dates[test_mask].min(),
                "test_end": dates[test_mask].max(),
                "selected_trial": configs[winner].name,
                **config_columns(configs[winner]),
                "is_sharpe": float(train_sharpes[winner]),
                "oos_annualized_return": oos["annualized_return"],
                "oos_maximum_drawdown": oos["maximum_drawdown"],
                "oos_sharpe": oos["sharpe"],
            }
        )
    valid = np.isfinite(combined)
    selected_metrics = engine._metrics_from_return_array(combined[valid], dates[valid])
    frozen_metrics = engine._metrics_from_return_array(frozen_returns[valid], dates[valid])
    core_metrics = engine._metrics_from_return_array(core_returns[valid], dates[valid])
    equity = pd.DataFrame(
        {
            "trade_date": dates[valid],
            "selected_model_return": combined[valid],
            "frozen_v2_return": frozen_returns[valid],
            "static_core_return": core_returns[valid],
            "selected_model_equity": np.cumprod(1.0 + combined[valid]),
            "frozen_v2_equity": np.cumprod(1.0 + frozen_returns[valid]),
            "static_core_equity": np.cumprod(1.0 + core_returns[valid]),
        }
    )
    summary = {
        "selection_rule": "highest expanding-window in-sample Sharpe among 2,187 trials",
        "first_test_year": first_test_year,
        "test_year_count": int(len(rows)),
        "selected_model": selected_metrics,
        "frozen_v2_same_oos_dates": frozen_metrics,
        "static_core_same_oos_dates": core_metrics,
    }
    return pd.DataFrame(rows), equity, summary


def validate_result(result: V2Result, data: engine.MarketData) -> dict:
    errors = []
    if not result.decisions.empty:
        causal = pd.to_datetime(result.decisions["observation_date"]) < pd.to_datetime(
            result.decisions["execution_date"]
        )
        if not causal.all():
            errors.append("observation date is not strictly before execution date")
        if result.decisions["target_weight_sum"].gt(1.0 + 1e-10).any():
            errors.append("target weights exceed 100%")
    if not np.isfinite(result.equity["total_value"]).all():
        errors.append("non-finite portfolio value")
    max_unattributed = float(result.equity["unattributed_pnl"].abs().max())
    if max_unattributed > 1e-5:
        errors.append(f"P&L attribution error {max_unattributed}")
    lifecycle_violations = 0
    if not result.positions.empty:
        positions = result.positions.merge(
            data.master[["symbol", "listing_date", "delisting_date"]].reset_index(drop=True),
            on="symbol",
            how="left",
        )
        dates = pd.to_datetime(positions["trade_date"])
        invalid = dates.lt(positions["listing_date"]) | (
            positions["delisting_date"].notna() & dates.gt(positions["delisting_date"])
        )
        lifecycle_violations = int(invalid.sum())
        if lifecycle_violations:
            errors.append(f"positions outside lifecycle: {lifecycle_violations}")
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "causal_decision_count": int(len(result.decisions)),
        "lifecycle_violations": lifecycle_violations,
        "maximum_absolute_unattributed_pnl": max_unattributed,
    }


def _maximum_trade_participation(result: V2Result) -> tuple[float | None, int]:
    if result.trades.empty or not result.trades["trade_adv_participation"].notna().any():
        return None, 0
    participation = result.trades["trade_adv_participation"].dropna()
    return float(participation.max()), int(participation.gt(0.005 + 1e-12).sum())


def create_charts(bundle: dict, assets: Path) -> None:
    assets.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    reference_equity = bundle["reference_equity"]
    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for name in ("frozen_v2", "static_core", "frozen_v1"):
        frame = reference_equity[reference_equity["model"].eq(name)]
        curve = frame["total_value"] / frame["total_value"].iloc[0]
        axes[0].plot(frame["trade_date"], curve, label=name)
        if name in ("frozen_v2", "static_core"):
            drawdown = curve / curve.cummax() - 1.0
            axes[1].plot(frame["trade_date"], drawdown, label=name)
    axes[0].set_title("V2, strategic core, and frozen V1")
    axes[0].set_ylabel("Growth of 1")
    axes[0].legend()
    axes[1].set_ylabel("Drawdown")
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(assets / "v2-core-v1-equity.png", dpi=160)
    plt.close(figure)

    rolling = bundle["rolling_three_year"]
    figure, axis = plt.subplots(figsize=(11, 4.8))
    axis.plot(rolling["trade_date"], rolling["active_excess"])
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_title("Rolling three-year V2 excess over strategic core")
    axis.set_ylabel("Three-year return difference")
    figure.tight_layout()
    figure.savefig(assets / "rolling-active-excess.png", dpi=160)
    plt.close(figure)

    effects = bundle["module_effects"]
    full = effects[effects["period"].eq("full")]
    figure, axis = plt.subplots(figsize=(9, 4.8))
    axis.bar(full["module"], full["mean_delta_sharpe"])
    axis.axhline(0, color="black", linewidth=0.8)
    axis.tick_params(axis="x", rotation=30)
    axis.set_title("V2 module factorial marginal Sharpe effects")
    figure.tight_layout()
    figure.savefig(assets / "v2-module-effects.png", dpi=160)
    plt.close(figure)

    grid = bundle["parameter_grid"]
    pivot = grid.pivot_table(
        index="minimum_dispersion_iqr",
        columns="active_sleeve",
        values="sharpe",
        aggfunc="median",
    )
    figure, axis = plt.subplots(figsize=(7, 4.8))
    image = axis.imshow(pivot.to_numpy(), cmap="viridis", aspect="auto")
    axis.set_xticks(np.arange(len(pivot.columns)), pivot.columns)
    axis.set_yticks(np.arange(len(pivot.index)), pivot.index)
    axis.set_xlabel("Active sleeve")
    axis.set_ylabel("Minimum 6M dispersion IQR")
    axis.set_title("Median Sharpe across other grid dimensions")
    for row in range(len(pivot.index)):
        for column in range(len(pivot.columns)):
            axis.text(
                column,
                row,
                f"{pivot.iloc[row, column]:.2f}",
                ha="center",
                va="center",
                color="white",
            )
    figure.colorbar(image, ax=axis)
    figure.tight_layout()
    figure.savefig(assets / "v2-parameter-plateau.png", dpi=160)
    plt.close(figure)

    costs = bundle["cost_stress"]
    capacity = bundle["capacity_stress"]
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    for model, frame in costs.groupby("model"):
        axes[0].plot(
            frame["single_side_all_in_cost_bp"],
            frame["annualized_return"],
            marker="o",
            label=model,
        )
    axes[0].set_title("Cost pressure")
    axes[0].set_xlabel("Single-side all-in cost (bp)")
    axes[0].set_ylabel("CAGR")
    axes[0].legend()
    strict = capacity[capacity["implementation"].eq("strict")]
    for model, frame in strict.groupby("model"):
        axes[1].plot(
            frame["capital"] / 1_000_000,
            frame["annualized_return"],
            marker="o",
            label=model,
        )
    axes[1].set_xscale("log")
    axes[1].set_title("Strict 0.5% ADV capacity")
    axes[1].set_xlabel("Initial capital (RMB mn)")
    axes[1].set_ylabel("CAGR")
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(assets / "v2-cost-capacity.png", dpi=160)
    plt.close(figure)


def _reference_configs(base: V2Config) -> list[V2Config]:
    return [
        replace(base, name="static_core", portfolio_mode="core_only"),
        replace(
            base,
            name="always_on_overlay",
            use_excess_hurdle=False,
            use_dispersion_gate=False,
        ),
        replace(base, name="excess_gate_only", use_dispersion_gate=False),
        replace(base, name="dispersion_gate_only", use_excess_hurdle=False),
        base,
        replace(
            base,
            name="standalone_satellite",
            portfolio_mode="satellite_only",
            use_capacity=False,
        ),
    ]


def run_references(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
) -> tuple[dict[str, V2Result | engine.SimulationResult], pd.DataFrame, pd.DataFrame]:
    results = {}
    rows = []
    equity_rows = []
    detailed_names = {"static_core", "frozen_v2", "standalone_satellite"}
    for config in _reference_configs(base):
        result = run_simulation(
            data,
            cache,
            config,
            capture_details=config.name in detailed_names,
        )
        results[config.name] = result
        rows.append({"model": config.name, **result.metrics})
        equity = result.equity.copy()
        equity["model"] = config.name
        equity_rows.append(equity)
    v1 = engine.run_simulation_fast(
        data,
        cache,
        engine.StrategyConfig(),
        engine.DEFAULT_START,
        engine.DEFAULT_END,
    )
    results["frozen_v1"] = v1
    rows.append({"model": "frozen_v1", **v1.metrics})
    equity = v1.equity.copy()
    equity["model"] = "frozen_v1"
    equity_rows.append(equity)
    return results, pd.DataFrame(rows), pd.concat(equity_rows, ignore_index=True)


def run_module_factorial(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    configs = module_factorial_configs(base)
    for period, start, end in PERIODS:
        for config in configs:
            result = run_simulation_fast(data, cache, config, start, end)
            rows.append(
                {
                    "period": period,
                    **{flag: bool(getattr(config, flag)) for flag in MODULE_FLAGS},
                    **result_row(result),
                }
            )
    frame = pd.DataFrame(rows)
    return frame, paired_module_effects(frame)


def run_parameter_grid(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
    frozen_returns: np.ndarray,
) -> tuple[pd.DataFrame, np.ndarray, list[V2Config], int]:
    configs = parameter_configs(base)
    rows = []
    returns = []
    frozen_index = None
    for index, config in enumerate(configs):
        result = run_simulation_fast(data, cache, config)
        rows.append(result_row(result))
        returns.append(result.equity["daily_return"].to_numpy(dtype=float))
        if (
            config.lookbacks == base.lookbacks
            and config.top_k == base.top_k
            and config.active_sleeve == base.active_sleeve
            and config.minimum_excess_horizons == base.minimum_excess_horizons
            and config.minimum_dispersion_iqr == base.minimum_dispersion_iqr
            and config.rank_buffer == base.rank_buffer
            and config.maximum_pair_correlation == base.maximum_pair_correlation
        ):
            frozen_index = index
        if (index + 1) % 100 == 0 or index + 1 == len(configs):
            print(f"  v2 parameter trials completed: {index + 1}/{len(configs)}", flush=True)
    matrix = np.vstack(returns)
    if frozen_index is None:
        raise AssertionError("frozen v2 candidate is absent from parameter grid")
    if not np.allclose(matrix[frozen_index], frozen_returns, rtol=0, atol=1e-12):
        raise AssertionError("v2 grid does not reproduce the preregistered candidate")
    return pd.DataFrame(rows), matrix, configs, frozen_index


def run_cost_stress(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
) -> pd.DataFrame:
    rows = []
    for basis_points in (5, 10, 20, 30):
        cost = basis_points / 10_000.0
        models = (
            replace(
                base,
                name=f"v2_{basis_points}bp",
                commission_rate=0.0,
                minimum_commission=0.0,
                slippage_rate=cost,
            ),
            replace(
                base,
                name=f"core_{basis_points}bp",
                portfolio_mode="core_only",
                commission_rate=0.0,
                minimum_commission=0.0,
                slippage_rate=cost,
            ),
            replace(
                base,
                name=f"satellite_{basis_points}bp",
                portfolio_mode="satellite_only",
                use_capacity=False,
                commission_rate=0.0,
                minimum_commission=0.0,
                slippage_rate=cost,
            ),
        )
        for config in models:
            result = run_simulation_fast(data, cache, config)
            model = config.name.split("_")[0]
            rows.append(
                {
                    "single_side_all_in_cost_bp": basis_points,
                    "model": model,
                    **result_row(result),
                }
            )
    return pd.DataFrame(rows)


def run_capacity_stress(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
) -> pd.DataFrame:
    rows = []
    for capital in (200_000, 1_000_000, 5_000_000, 10_000_000, 50_000_000):
        as_coded = replace(base, name=f"target_cap_{capital}", initial_cash=float(capital))
        result = run_simulation_fast(data, cache, as_coded)
        rows.append(
            {
                "capital": capital,
                "implementation": "target-cap-only",
                "model": "v2",
                "maximum_trade_adv_participation": np.nan,
                "trade_count_above_0_5pct_adv": np.nan,
                **result_row(result),
            }
        )
        strict = replace(
            base,
            name=f"strict_v2_{capital}",
            initial_cash=float(capital),
            enforce_trade_adv_participation=True,
            capacity_scope_all_etfs=True,
        )
        strict_result = run_simulation(
            data,
            cache,
            strict,
            capture_details=True,
        )
        maximum, violations = _maximum_trade_participation(strict_result)
        rows.append(
            {
                "capital": capital,
                "implementation": "strict",
                "model": "v2",
                "maximum_trade_adv_participation": maximum,
                "trade_count_above_0_5pct_adv": violations,
                **result_row(strict_result),
            }
        )
        strict_core = replace(
            base,
            name=f"strict_core_{capital}",
            portfolio_mode="core_only",
            initial_cash=float(capital),
            enforce_trade_adv_participation=True,
            capacity_scope_all_etfs=True,
        )
        core_result = run_simulation_fast(data, cache, strict_core)
        rows.append(
            {
                "capital": capital,
                "implementation": "strict",
                "model": "core",
                "maximum_trade_adv_participation": np.nan,
                "trade_count_above_0_5pct_adv": np.nan,
                **result_row(core_result),
            }
        )
    return pd.DataFrame(rows)


def run_liquidity_stress(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
) -> pd.DataFrame:
    rows = []
    for period, start, end in PERIODS:
        for minimum_adv in (10_000_000.0, 20_000_000.0, 50_000_000.0):
            config = replace(
                base,
                name=f"adv_{int(minimum_adv)}",
                minimum_adv20=minimum_adv,
            )
            result = run_simulation_fast(data, cache, config, start, end)
            rows.append(
                {
                    "period": period,
                    "minimum_adv20": minimum_adv,
                    **result_row(result),
                }
            )
    return pd.DataFrame(rows)


def run_execution_lag_stress(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
) -> pd.DataFrame:
    rows = []
    for lag in (1, 2, 3, 5):
        config = replace(base, name=f"lag_{lag}", execution_lag_sessions=lag)
        result = run_simulation_fast(data, cache, config)
        rows.append({"lag_sessions": lag, **result_row(result)})
    return pd.DataFrame(rows)


def run_exclusion_stress(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: V2Config,
    frozen: V2Result,
    core: V2Result,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    table, concentration = active_concentration(frozen)
    symbols = concentration["top_active_symbols"]
    rows = [
        {
            "case": "frozen_v2",
            "excluded_count": 0,
            "excluded_symbols": "",
            "annualized_excess_over_core": frozen.metrics["annualized_return"]
            - core.metrics["annualized_return"],
            **result_row(frozen),
        }
    ]
    for count in (1, 3, 5):
        excluded = tuple(symbols[:count])
        config = replace(
            base,
            name=f"exclude_top_{count}",
            excluded_active_symbols=excluded,
        )
        result = run_simulation_fast(data, cache, config)
        rows.append(
            {
                "case": config.name,
                "excluded_count": len(excluded),
                "excluded_symbols": ";".join(excluded),
                "annualized_excess_over_core": result.metrics["annualized_return"]
                - core.metrics["annualized_return"],
                **result_row(result),
            }
        )
    return pd.DataFrame(rows), table, concentration


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _pct(value) -> str:
    if value is None or not np.isfinite(value):
        return "NA"
    return f"{100 * value:.2f}%"


def _number(value, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "NA"
    return f"{value:.{digits}f}"


def build_report(bundle: dict) -> str:
    references = bundle["references"].set_index("model")
    frozen = references.loc["frozen_v2"]
    core = references.loc["static_core"]
    satellite = references.loc["standalone_satellite"]
    success = bundle["success_evaluation"]
    local_criteria = {
        key: value
        for key, value in success["criteria"].items()
        if key != "platform"
    }
    local_passed = sum(item["passed"] for item in local_criteria.values())
    effects = bundle["module_effects"]
    effects = effects[effects["period"].eq("full")]
    effect_rows = []
    for _, row in effects.iterrows():
        effect_rows.append(
            "| {module} | {delta_return} | {delta_sharpe} | {positive} |".format(
                module=row["module"],
                delta_return=_pct(row["mean_delta_annualized_return"]),
                delta_sharpe=_number(row["mean_delta_sharpe"], 3),
                positive=_pct(row["positive_sharpe_pair_ratio"]),
            )
        )
    criteria_rows = []
    for name, item in success["criteria"].items():
        platform_pending = name == "platform" and any(
            value is None for value in item["value"]
        )
        status = "通过" if item["passed"] else ("待平台" if platform_pending else "失败")
        criteria_rows.append(f"| {name} | {status} | `{json.dumps(_json_safe(item['value']), ensure_ascii=False)}` |")
    cost20 = bundle["cost_stress"]
    cost20 = cost20[cost20["single_side_all_in_cost_bp"].eq(20)].set_index("model")
    rolling = bundle["rolling_summary"]
    bootstrap = bundle["bootstrap"]
    concentration = bundle["concentration"]
    pbo = bundle["pbo_summary"]
    dsr = bundle["dsr"]["frozen_v2"]
    walk = bundle["walk_forward_summary"]
    yearly = bundle["yearly"]
    negative_excess_years = yearly[yearly["annualized_excess"].lt(0)]["year"].tolist()
    capacity = bundle["capacity_stress"]
    cap10 = capacity[
        capacity["capital"].eq(10_000_000)
        & capacity["implementation"].eq("strict")
    ].set_index("model")
    return f"""# ETF Core Rotation v2：条件式动量增强完整研究

## 结论先行

本报告严格使用提交 `0c06b5e` 中预注册的冻结候选和成功标准，不根据本次结果修改门控、底仓或参数。当前本地阶段通过 **{local_passed}/{len(local_criteria)}** 项本地标准；聚宽 PIT 与官方 10:30 同底仓对照将在本归档的平台校准字段中单列，未完成前不把 v2 提升为 baseline。

- 冻结 v2 年化 {_pct(frozen['annualized_return'])}、最大回撤 {_pct(frozen['maximum_drawdown'])}、Sharpe {_number(frozen['sharpe'])}；静态 40/40/20 底仓分别为 {_pct(core['annualized_return'])}、{_pct(core['maximum_drawdown'])}、{_number(core['sharpe'])}。v2 年化增量为 {_pct(frozen['annualized_return'] - core['annualized_return'])}。
- 20bp 单边总成本下，v2/底仓年化为 {_pct(cost20.loc['v2','annualized_return'])}/{_pct(cost20.loc['core','annualized_return'])}，净增量 {_pct(cost20.loc['v2','annualized_return'] - cost20.loc['core','annualized_return'])}。
- 独立条件式主动袖套年化 {_pct(satellite['annualized_return'])}、回撤 {_pct(satellite['maximum_drawdown'])}、Sharpe {_number(satellite['sharpe'])}。这一结果用于判断主动信号本身，而不是让底仓掩盖它。
- 滚动三年战胜底仓比例 {_pct(rolling['v2_win_ratio'])}，最差三年主动差额 {_pct(rolling['worst_active_excess'])}；负年度主动差额年份为 `{negative_excess_years}`。
- 2,187 组参数试验的近似 PBO 为 {_pct(pbo['pbo'])}，冻结候选 DSR 概率为 {_pct(dsr['deflated_sharpe_probability'])}。
- 严格 0.5% ADV、1,000 万元场景下，v2 平均主动暴露 {_pct(cap10.loc['v2','average_active_exposure'])}，年化相对严格底仓增量 {_pct(cap10.loc['v2','annualized_return'] - cap10.loc['core','annualized_return'])}。

## 冻结假设与实验规模

战略底仓固定为 40% 沪深300 ETF、40% 国债 ETF、20% 黄金 ETF；主动预算上限 30%。只有候选在至少 2/3 个周期跑赢 `max(0, 国债, 现金)` 且六个月收益横截面 IQR 不低于 10% 时才启用增强。主动 Top3 等权，单标的不超过 15%，未使用预算回到底仓。

直接回测共 {bundle['experiment_counts']['direct_backtest_rows_total']:,} 条：7 个参考模型、64 个模块×时期结果、2,187 组完整参数网格、12 个成本结果、15 个容量结果、12 个流动性×时期结果、4 个执行延迟和 4 个贡献删除结果。另报告 70 个 CSCV 分割、{bundle['experiment_counts']['walk_forward_test_years']} 个 expanding-window 样本外年份和 4,000 次成对移动区块 bootstrap。

## 参考组合

| 模型 | 年化 | 最大回撤 | Sharpe | 年化换手 | 平均主动暴露 |
|---|---:|---:|---:|---:|---:|
| 冻结 v2 | {_pct(frozen['annualized_return'])} | {_pct(frozen['maximum_drawdown'])} | {_number(frozen['sharpe'])} | {_number(frozen['annualized_turnover'])} | {_pct(frozen['average_active_exposure'])} |
| 静态 40/40/20 底仓 | {_pct(core['annualized_return'])} | {_pct(core['maximum_drawdown'])} | {_number(core['sharpe'])} | {_number(core['annualized_turnover'])} | 0.00% |
| 独立主动袖套 | {_pct(satellite['annualized_return'])} | {_pct(satellite['maximum_drawdown'])} | {_number(satellite['sharpe'])} | {_number(satellite['annualized_turnover'])} | {_pct(satellite['average_active_exposure'])} |
| 冻结 v1 | {_pct(references.loc['frozen_v1','annualized_return'])} | {_pct(references.loc['frozen_v1','maximum_drawdown'])} | {_number(references.loc['frozen_v1','sharpe'])} | {_number(references.loc['frozen_v1','annualized_turnover'])} | — |

![V2、底仓与V1净值](assets/v2-core-v1-equity.png)

## 模块全因子边际

下表控制其他三个开关后报告 8 组配对平均差；不是一条顺序消融路径。

| 模块 | 平均Δ年化 | 平均ΔSharpe | Sharpe改善比例 |
|---|---:|---:|---:|
{chr(10).join(effect_rows)}

![模块边际](assets/v2-module-effects.png)

## 参数高原、多重试验与样本外

- 网格维度严格为协议中的 3×3×3×3×3×3×3，共 2,187 组；冻结候选在网格中精确出现一次并逐日复现详细账本。
- 网格 Sharpe 中位数 {_number(bundle['grid_summary']['median_sharpe'])}，四分位区间 {_number(bundle['grid_summary']['q25_sharpe'])}—{_number(bundle['grid_summary']['q75_sharpe'])}；全样本冠军为 `{bundle['grid_summary']['best_trial']}`，但不替换冻结候选。
- expanding-window 选参 OOS 年化/回撤/Sharpe 为 {_pct(walk['selected_model']['annualized_return'])}/{_pct(walk['selected_model']['maximum_drawdown'])}/{_number(walk['selected_model']['sharpe'])}；同期冻结 v2 为 {_pct(walk['frozen_v2_same_oos_dates']['annualized_return'])}/{_pct(walk['frozen_v2_same_oos_dates']['maximum_drawdown'])}/{_number(walk['frozen_v2_same_oos_dates']['sharpe'])}，静态底仓为 {_pct(walk['static_core_same_oos_dates']['annualized_return'])}/{_pct(walk['static_core_same_oos_dates']['maximum_drawdown'])}/{_number(walk['static_core_same_oos_dates']['sharpe'])}。
- 21/63 日成对移动区块 bootstrap 的主动年化均值为 {_pct(bootstrap['21']['observed_annualized_mean_excess'])}/{_pct(bootstrap['63']['observed_annualized_mean_excess'])}，95% 区间为 [{_pct(bootstrap['21']['q025'])}, {_pct(bootstrap['21']['q975'])}] / [{_pct(bootstrap['63']['q025'])}, {_pct(bootstrap['63']['q975'])}]。

![参数高原](assets/v2-parameter-plateau.png)

## 成本、容量、集中度与阶段性

- 成本表在 `raw/cost-stress.csv`；静态底仓也按相同成本重放，避免只惩罚 v2。
- 1,000 万严格容量下最大实际成交参与率为 {_pct(cap10.loc['v2','maximum_trade_adv_participation'])}，超出 0.5% 的成交数为 {int(cap10.loc['v2','trade_count_above_0_5pct_adv'])}。
- 主动正贡献 Top1/Top3/Top5 占比为 {_pct(concentration['top1_positive_contribution_share'])}/{_pct(concentration['top3_positive_contribution_share'])}/{_pct(concentration['top5_positive_contribution_share'])}；删除贡献最高 ETF 后的年化底仓增量为 {_pct(bundle['exclusion_stress'].set_index('case').loc['exclude_top_1','annualized_excess_over_core'])}。
- 滚动三年、逐年、牛熊震荡、ADV 门槛和执行延迟的完整结果分别保存在 `raw/rolling-three-year.csv`、`raw/yearly.csv`、`raw/regimes.csv`、`raw/liquidity-stress.csv` 和 `raw/execution-lag.csv`。

![成本与容量](assets/v2-cost-capacity.png)

![滚动三年主动差额](assets/rolling-active-excess.png)

## 预注册成功标准

| 标准 | 状态 | 机器值 |
|---|---|---|
{chr(10).join(criteria_rows)}

`platform` 在聚宽 PIT Research 与官方 10:30 同底仓结果写入前保持待平台状态；本地通过不能代替该项。

## 偏差审计与限制

- 每次周频决策的观察日严格早于执行日；动量、ADV、相关性、分散度和防御门槛都只截止观察日。详细账本归因误差和持仓生命周期检查见 `audit.json`。
- 本地行情、复权、动量、波动率和 ADV 已在 v1 阶段与聚宽几乎逐位对齐；但本地 `tracking_target` 仍是当前静态档案。v2 必须再次使用聚宽历史 `FUND_INVEST_TARGET` 做全路径校准。
- 主动/底仓持有同一 ETF 时，详细账本按目标权重比例拆分虚拟袖套贡献；总账户 P&L 精确对账，虚拟袖套归因是分析口径，不是独立托管账户。
- 全部稳健性试验仍来自同一 2014—2026 历史；walk-forward 和 PBO 降低但不能消除数据挖掘风险。

## 决策

是否提升 v2 只按预注册八项标准判断。全样本冠军、某个更优延迟或参数单点都不会写回冻结候选；未通过的标准保留为失败证据。
"""


def run_experiment_suite(
    data_root: Path,
    output: Path,
) -> dict:
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite experiment archive: {output}")
    raw = output / "raw"
    assets = output / "assets"
    raw.mkdir(parents=True)
    assets.mkdir(parents=True)
    print("[1/11] loading causal ETF data", flush=True)
    data = engine.load_market_data(data_root)
    cache = engine.SnapshotCache(data)
    base = V2Config()

    print("[2/11] frozen candidate, strategic core, satellite, and V1 references", flush=True)
    results, references, reference_equity = run_references(data, cache, base)
    frozen = results["frozen_v2"]
    core = results["static_core"]
    satellite = results["standalone_satellite"]
    validation = validate_result(frozen, data)
    if validation["status"] != "passed":
        raise AssertionError(validation["errors"])

    print("[3/11] 16-module factorial across four periods", flush=True)
    factorial, effects = run_module_factorial(data, cache, base)

    print("[4/11] 2,187 preregistered parameter trials", flush=True)
    frozen_returns = frozen.equity["daily_return"].to_numpy(dtype=float)
    grid, return_matrix, configs, frozen_index = run_parameter_grid(
        data,
        cache,
        base,
        frozen_returns,
    )
    stability = parameter_stability_summary(grid)

    print("[5/11] cost, capacity, liquidity, and execution stresses", flush=True)
    cost_stress = run_cost_stress(data, cache, base)
    capacity_stress = run_capacity_stress(data, cache, base)
    liquidity_stress = run_liquidity_stress(data, cache, base)
    execution_lag = run_execution_lag_stress(data, cache, base)

    print("[6/11] active ETF concentration and deletion stress", flush=True)
    exclusion_stress, contribution, concentration = run_exclusion_stress(
        data,
        cache,
        base,
        frozen,
        core,
    )

    print("[7/11] yearly, regime, rolling three-year, and block bootstrap", flush=True)
    yearly = yearly_comparison(frozen, core)
    regimes = regime_comparison(frozen, core, data)
    rolling, rolling_summary = rolling_three_year_comparison(
        frozen.equity,
        core.equity,
    )
    excess_returns = frozen_returns - core.equity["daily_return"].to_numpy(dtype=float)
    bootstrap = {
        str(block): moving_block_bootstrap(excess_returns, block)
        for block in (21, 63)
    }

    print("[8/11] CSCV/PBO, DSR, and expanding-window OOS", flush=True)
    dates = pd.DatetimeIndex(pd.to_datetime(frozen.equity["trade_date"]))
    pbo_splits, pbo_summary = engine.compute_pbo(
        return_matrix,
        dates,
        [config.name for config in configs],
    )
    sharpes = engine._sharpe_by_trial(return_matrix)
    best_index = int(np.nanargmax(sharpes))
    dsr = {
        "frozen_v2": engine.deflated_sharpe_probability(
            frozen_returns,
            return_matrix,
        ),
        "full_sample_best": {
            **config_columns(configs[best_index]),
            **engine.deflated_sharpe_probability(
                return_matrix[best_index],
                return_matrix,
            ),
        },
    }
    walk_forward, walk_equity, walk_summary = expanding_walk_forward(
        return_matrix,
        dates,
        configs,
        frozen_returns,
        core.equity["daily_return"].to_numpy(dtype=float),
    )

    print("[9/11] applying frozen success criteria", flush=True)
    cost20 = cost_stress[cost_stress["single_side_all_in_cost_bp"].eq(20)].set_index(
        "model"
    )
    cap10 = capacity_stress[
        capacity_stress["capital"].eq(10_000_000)
        & capacity_stress["implementation"].eq("strict")
    ].set_index("model")
    exclusions = exclusion_stress.set_index("case")
    facts = {
        "cost20_v2_cagr": float(cost20.loc["v2", "annualized_return"]),
        "cost20_core_cagr": float(cost20.loc["core", "annualized_return"]),
        "rolling_win_ratio": rolling_summary["v2_win_ratio"],
        "worst_rolling_active_excess": rolling_summary["worst_active_excess"],
        "v2_sharpe": frozen.metrics["sharpe"],
        "core_sharpe": core.metrics["sharpe"],
        "v2_maximum_drawdown": frozen.metrics["maximum_drawdown"],
        "core_maximum_drawdown": core.metrics["maximum_drawdown"],
        "v2_worst_rolling_return": rolling_summary["worst_v2_three_year_return"],
        "core_worst_rolling_return": rolling_summary["worst_core_three_year_return"],
        "satellite_sharpe": satellite.metrics["sharpe"],
        "satellite_20bp_sharpe": float(cost20.loc["satellite", "sharpe"]),
        "pbo": pbo_summary["pbo"],
        "frozen_dsr_probability": dsr["frozen_v2"]["deflated_sharpe_probability"],
        "top1_positive_contribution_share": concentration[
            "top1_positive_contribution_share"
        ],
        "exclude_top1_active_excess": float(
            exclusions.loc["exclude_top_1", "annualized_excess_over_core"]
        ),
        "capacity_10m_average_active_exposure": float(
            cap10.loc["v2", "average_active_exposure"]
        ),
        "capacity_10m_active_excess": float(
            cap10.loc["v2", "annualized_return"]
            - cap10.loc["core", "annualized_return"]
        ),
        "local_active_excess": float(
            frozen.metrics["annualized_return"] - core.metrics["annualized_return"]
        ),
        "joinquant_pit_active_excess": None,
        "joinquant_official_active_excess": None,
    }
    success = evaluate_success_criteria(facts)
    experiment_counts = {
        "reference_runs": int(len(references)),
        "module_period_runs": int(len(factorial)),
        "parameter_trials": int(len(grid)),
        "cost_runs": int(len(cost_stress)),
        "capacity_runs": int(len(capacity_stress)),
        "liquidity_period_runs": int(len(liquidity_stress)),
        "execution_lag_runs": int(len(execution_lag)),
        "contribution_exclusion_runs": int(len(exclusion_stress)),
        "direct_backtest_rows_total": int(
            len(references)
            + len(factorial)
            + len(grid)
            + len(cost_stress)
            + len(capacity_stress)
            + len(liquidity_stress)
            + len(execution_lag)
            + len(exclusion_stress)
        ),
        "pbo_cscv_splits": int(len(pbo_splits)),
        "walk_forward_test_years": int(len(walk_forward)),
        "bootstrap_resamples": 4000,
    }
    grid_summary = {
        "trial_count": int(len(grid)),
        "median_annualized_return": float(grid["annualized_return"].median()),
        "median_sharpe": float(grid["sharpe"].median()),
        "q25_sharpe": float(grid["sharpe"].quantile(0.25)),
        "q75_sharpe": float(grid["sharpe"].quantile(0.75)),
        "positive_annualized_ratio": float(grid["annualized_return"].gt(0).mean()),
        "best_trial": configs[best_index].name,
        "frozen_grid_index": int(frozen_index),
    }
    audit = {
        "schema_version": 1,
        "protocol_status": "frozen-before-results",
        "protocol_sha256": engine.file_sha256(PROTOCOL_PATH),
        "data": data.audit,
        "manifest_hashes": data.manifest_hashes,
        "frozen_result_validation": validation,
        "future_data": (
            "All signals end on observation_date; every detailed decision observation date "
            "is strictly earlier than execution date."
        ),
        "survivorship": data.audit["survivorship_control"],
        "tracking_index_point_in_time": data.audit["classification_limitation"],
        "price_adjustment": data.audit["price_adjustment"],
        "capacity": (
            "Target active holdings and strict trade stresses use lagged ADV20. Strict runs "
            "apply the 0.5% participation cap to active and strategic-core ETF trades."
        ),
        "virtual_sleeve_attribution": (
            "When active and core own the same ETF, active P&L is split by target-weight "
            "fractions. Total-account P&L remains exactly reconciled."
        ),
        "experiment_counts": experiment_counts,
        "platform_status": "pending JoinQuant PIT Research and official 10:30 paired core run",
    }
    bundle = {
        "data": data,
        "results": results,
        "references": references,
        "reference_equity": reference_equity,
        "module_factorial": factorial,
        "module_effects": effects,
        "parameter_grid": grid,
        "parameter_stability": stability,
        "cost_stress": cost_stress,
        "capacity_stress": capacity_stress,
        "liquidity_stress": liquidity_stress,
        "execution_lag": execution_lag,
        "exclusion_stress": exclusion_stress,
        "active_contribution": contribution,
        "concentration": concentration,
        "yearly": yearly,
        "regimes": regimes,
        "rolling_three_year": rolling,
        "rolling_summary": rolling_summary,
        "bootstrap": bootstrap,
        "pbo_splits": pbo_splits,
        "pbo_summary": pbo_summary,
        "dsr": dsr,
        "walk_forward": walk_forward,
        "walk_forward_equity": walk_equity,
        "walk_forward_summary": walk_summary,
        "facts": facts,
        "success_evaluation": success,
        "experiment_counts": experiment_counts,
        "grid_summary": grid_summary,
        "audit": audit,
    }

    print("[10/11] writing immutable-style local evidence package", flush=True)
    frames = {
        "references.csv": references,
        "reference-equity.csv": reference_equity,
        "module-factorial.csv": factorial,
        "module-effects.csv": effects,
        "parameter-grid.csv": grid,
        "parameter-stability.csv": stability,
        "cost-stress.csv": cost_stress,
        "capacity-stress.csv": capacity_stress,
        "liquidity-stress.csv": liquidity_stress,
        "execution-lag.csv": execution_lag,
        "exclusion-stress.csv": exclusion_stress,
        "active-contribution.csv": contribution,
        "yearly.csv": yearly,
        "regimes.csv": regimes,
        "rolling-three-year.csv": rolling,
        "pbo-splits.csv": pbo_splits,
        "walk-forward.csv": walk_forward,
        "walk-forward-equity.csv": walk_equity,
        "v2-equity.csv": frozen.equity,
        "v2-trades.csv": frozen.trades,
        "v2-positions.csv": frozen.positions,
        "v2-decisions.csv": frozen.decisions,
        "v2-contributions.csv": frozen.contributions,
        "v2-active-contributions.csv": frozen.active_contributions,
        "core-equity.csv": core.equity,
    }
    for filename, frame in frames.items():
        frame.to_csv(raw / filename, index=False, encoding="utf-8")
    json_artifacts = {
        "bootstrap.json": bootstrap,
        "pbo-summary.json": pbo_summary,
        "dsr.json": dsr,
        "walk-forward-summary.json": walk_summary,
        "rolling-summary.json": rolling_summary,
        "concentration.json": concentration,
        "success-evaluation.json": success,
        "facts.json": facts,
        "grid-summary.json": grid_summary,
        "experiment-counts.json": experiment_counts,
    }
    for filename, value in json_artifacts.items():
        (raw / filename).write_text(
            json.dumps(_json_safe(value), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    shutil.copy2(PROTOCOL_PATH, output / "protocol.json")
    shutil.copy2(VARIANT_PATH, output / "source.py")
    shutil.copy2(Path(__file__), output / "engine.py")
    (output / "config.json").write_text(
        json.dumps(_json_safe(asdict(base)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "audit.json").write_text(
        json.dumps(_json_safe(audit), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    create_charts(bundle, assets)
    report = build_report(bundle)
    (output / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "strategy_id": "etf-core-rotation",
        "platform": "joinquant",
        "variant": "conditional-momentum-overlay-v2",
        "archived_at": "2026-08-16",
        "run_id": "local-jq-2014-2026-v1",
        "source_file": "source.py",
        "period": {"start": engine.DEFAULT_START, "end": engine.DEFAULT_END},
        "research_engine": "local-daily-causal-replay; JoinQuant calibration pending",
        "metrics": _json_safe(frozen.metrics),
        "strategic_core_metrics": _json_safe(core.metrics),
        "standalone_satellite_metrics": _json_safe(satellite.metrics),
        "experiment_counts": experiment_counts,
        "success_evaluation": _json_safe(success),
        "source_sha256": engine.file_sha256(output / "source.py"),
        "engine_sha256": engine.file_sha256(output / "engine.py"),
        "protocol_sha256": engine.file_sha256(output / "protocol.json"),
        "limitations": [
            "Local tracking_target is current-static rather than strict historical PIT.",
            "Local execution is next-session open, not official Monday 10:30 minute matching.",
            "All robustness tests use the same 2014-2026 historical record.",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[11/11] local v2 matrix complete", flush=True)
    return bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--data-root", type=Path, default=engine.DEFAULT_DATA_ROOT)
    parser.add_argument("--start", default=engine.DEFAULT_START)
    parser.add_argument("--end", default=engine.DEFAULT_END)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = run_experiment_suite(args.data_root, args.output)
    print(
        json.dumps(
            {
                "metrics": _json_safe(bundle["results"]["frozen_v2"].metrics),
                "success": _json_safe(bundle["success_evaluation"]),
                "experiments": bundle["experiment_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
