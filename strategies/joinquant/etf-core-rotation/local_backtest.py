"""ETF Core Rotation v1 的本地严格因果实验矩阵。"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import shutil
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy import stats


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


FAMILY_DIR = Path(__file__).resolve().parent
REPO_ROOT = FAMILY_DIR.parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quant_research.data.store import ResearchDataStore  # noqa: E402


DEFAULT_DATA_ROOT = Path("D:/code/_open-source/_data/quant-research")
DEFAULT_START = "2014-01-02"
DEFAULT_END = "2026-07-24"
ORIGINAL_DOWNLOAD_SHA256 = "6cb4b7b10cfb13dafffc4ad3c0b704c6ea96bb4f1891482ef553425f20de92d2"
GOLD = "SH518880"
DEFENSIVE_BONDS = ("SH511010", "SH511260")
CASH_ETF = "SH511880"
BENCHMARK = "SH510300"
ALL_LOOKBACKS = (42, 63, 84, 126, 168, 252)


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "baseline"
    lookbacks: tuple[int, int, int] = (63, 126, 252)
    min_positive_horizons: int = 2
    top_k: int = 3
    rank_buffer: int = 2
    corr_lookback: int = 60
    max_pair_corr: float = 0.90
    vol_lookback: int = 60
    target_portfolio_vol: float = 0.18
    max_single_risk_weight: float = 0.40
    vol_floor: float = 0.08
    min_history_bars: int = 253
    min_listing_calendar_days: int = 300
    liquidity_lookback: int = 20
    min_adv20: float = 20_000_000.0
    min_liquidity_observations: int = 15
    max_adv_participation: float = 0.005
    min_trade_value: float = 2_000.0
    min_weight_change: float = 0.03
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    slippage_rate: float = 0.0010
    use_absolute_momentum: bool = True
    use_top_k: bool = True
    use_inverse_vol: bool = True
    use_vol_target: bool = True
    use_rank_buffer: bool = True
    use_correlation_guard: bool = True
    use_capacity: bool = True
    enforce_trade_adv_participation: bool = False
    excluded_risk_symbols: tuple[str, ...] = ()


@dataclass
class MarketData:
    trade_dates: pd.DatetimeIndex
    adjusted_open: pd.DataFrame
    adjusted_close: pd.DataFrame
    daily_return: pd.DataFrame
    amount: pd.DataFrame
    adv20: pd.DataFrame
    adv20_count: pd.DataFrame
    history_count: pd.DataFrame
    vol60: pd.DataFrame
    momentum: dict[int, pd.DataFrame]
    master: pd.DataFrame
    risk_symbols: tuple[str, ...]
    tracking_key: pd.Series
    manifest_hashes: dict[str, str]
    audit: dict
    correlation_cache: dict[tuple, float | None]
    defensive_cache: dict[pd.Timestamp, str]
    portfolio_vol_cache: dict[tuple, float | None]


@dataclass
class Snapshot:
    observation_date: pd.Timestamp
    ranked: pd.DataFrame
    raw_eligible_count: int
    deduplicated_count: int
    liquid_count: int


@dataclass
class SimulationResult:
    config: StrategyConfig
    equity: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    decisions: pd.DataFrame
    contributions: pd.DataFrame
    metrics: dict


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pivot(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    return (
        frame.pivot(index="trade_date", columns="symbol", values=column)
        .sort_index()
        .sort_index(axis=1)
    )


def load_market_data(data_root: Path | str = DEFAULT_DATA_ROOT) -> MarketData:
    """只读取基线可能使用的 ETF，并预计算所有只含历史信息的特征。"""

    store = ResearchDataStore(data_root)
    master = store.read_parquet("etf_master").copy()
    for column in ("listing_date", "delisting_date", "first_trade_date"):
        master[column] = pd.to_datetime(master[column], errors="coerce").dt.normalize()
    successful = master["bar_status"].eq("success") & master["quality_grade"].eq("B")
    domestic_equity = master["etf_category"].isin(("broad_equity", "sector_equity"))
    risk_mask = successful & (domestic_equity | master["symbol"].eq(GOLD))
    risk_master = master.loc[risk_mask].copy()
    risk_master["tracking_key"] = risk_master["tracking_target"].astype("string")
    risk_master.loc[risk_master["symbol"].eq(GOLD), "tracking_key"] = "SPECIAL_GOLD"
    risk_master = risk_master[risk_master["tracking_key"].notna()]
    risk_master = risk_master[risk_master["tracking_key"].str.strip().ne("")]
    risk_symbols = tuple(sorted(risk_master["symbol"].astype(str)))
    required = tuple(dict.fromkeys((*risk_symbols, *DEFENSIVE_BONDS, CASH_ETF, BENCHMARK)))
    bars = store.read_symbol_partitions(
        "etf_daily",
        required,
        columns=(
            "symbol",
            "trade_date",
            "amount",
            "adjusted_open",
            "adjusted_close",
        ),
        strict=True,
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
    bars = bars.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    for column in ("amount", "adjusted_open", "adjusted_close"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    grouped = bars.groupby("symbol", sort=False)
    bars["daily_return"] = grouped["adjusted_close"].pct_change(fill_method=None)
    bars["history_count"] = grouped.cumcount() + 1
    bars["adv20"] = grouped["amount"].transform(
        lambda values: values.rolling(20, min_periods=15).mean()
    )
    bars["adv20_count"] = grouped["amount"].transform(
        lambda values: values.rolling(20, min_periods=1).count()
    )
    bars["vol60"] = grouped["daily_return"].transform(
        lambda values: values.rolling(60, min_periods=48).std(ddof=1) * math.sqrt(252.0)
    )
    for lookback in ALL_LOOKBACKS:
        bars[f"r{lookback}"] = grouped["adjusted_close"].pct_change(
            periods=lookback,
            fill_method=None,
        )

    adjusted_close = _pivot(bars, "adjusted_close")
    benchmark_dates = adjusted_close.index[adjusted_close[BENCHMARK].notna()]
    manifest_hashes = {
        name: file_sha256(store.manifest_path(name))
        for name in ("etf_daily", "etf_master", "etf_profiles", "etf_coverage")
    }
    tracking_groups = risk_master.groupby("tracking_key")["symbol"].size()
    master_index = master.set_index("symbol", drop=False).sort_index()
    audit = {
        "data_root": str(store.root),
        "daily_rows_loaded": int(len(bars)),
        "risk_symbol_count": int(len(risk_symbols)),
        "risk_delisted_symbol_count": int(risk_master["lifecycle_status"].eq("delisted").sum()),
        "tracking_group_count": int(tracking_groups.size),
        "duplicate_tracking_group_count": int(tracking_groups.gt(1).sum()),
        "daily_start": str(bars["trade_date"].min().date()),
        "daily_end": str(bars["trade_date"].max().date()),
        "price_adjustment": "adjusted_open/adjusted_close from B-grade continuous data",
        "amount_adjustment": "raw RMB amount; not price-adjusted",
        "classification_point_in_time": False,
        "classification_limitation": (
            "Eastmoney tracking_target is a current static profile without historical "
            "effective intervals; lifecycle and prices are point-in-time, but category and "
            "same-index deduplication are not strict PIT."
        ),
        "survivorship_control": (
            "Every observation filters listing_date and delisting_date; delisted B-grade ETFs "
            "remain eligible during their historical trading interval."
        ),
        "signal_execution_rule": (
            "last close of prior trading week -> first trading-day open of next week"
        ),
    }
    return MarketData(
        trade_dates=pd.DatetimeIndex(benchmark_dates),
        adjusted_open=_pivot(bars, "adjusted_open"),
        adjusted_close=adjusted_close,
        daily_return=_pivot(bars, "daily_return"),
        amount=_pivot(bars, "amount"),
        adv20=_pivot(bars, "adv20"),
        adv20_count=_pivot(bars, "adv20_count"),
        history_count=_pivot(bars, "history_count"),
        vol60=_pivot(bars, "vol60"),
        momentum={lookback: _pivot(bars, f"r{lookback}") for lookback in ALL_LOOKBACKS},
        master=master_index,
        risk_symbols=risk_symbols,
        tracking_key=risk_master.set_index("symbol")["tracking_key"].sort_index(),
        manifest_hashes=manifest_hashes,
        audit=audit,
        correlation_cache={},
        defensive_cache={},
        portfolio_vol_cache={},
    )


def weekly_execution_pairs(
    trading_dates: pd.DatetimeIndex,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """返回严格满足 execution > observation 的周频观察/执行日期。"""

    dates = pd.DatetimeIndex(trading_dates).sort_values().unique()
    if len(dates) < 2:
        return []
    periods = dates.to_period("W-FRI")
    week_last = pd.Series(dates, index=periods).groupby(level=0).max().sort_index()
    pairs = []
    for observation in week_last.iloc[:-1]:
        future = dates[dates > observation]
        if len(future):
            pairs.append((pd.Timestamp(observation), pd.Timestamp(future[0])))
    return pairs


class SnapshotCache:
    def __init__(self, data: MarketData):
        self.data = data
        self._cache: dict[tuple, Snapshot] = {}

    def get(self, observation_date: pd.Timestamp, config: StrategyConfig) -> Snapshot:
        key = (
            pd.Timestamp(observation_date),
            config.lookbacks,
            float(config.min_adv20),
            config.excluded_risk_symbols,
        )
        if key not in self._cache:
            self._cache[key] = self._build(pd.Timestamp(observation_date), config)
        return self._cache[key]

    def _build(self, observation_date: pd.Timestamp, config: StrategyConfig) -> Snapshot:
        data = self.data
        symbols = pd.Index(data.risk_symbols).difference(config.excluded_risk_symbols)
        master = data.master.reindex(symbols)
        min_start = observation_date - pd.Timedelta(days=config.min_listing_calendar_days)
        lifecycle = master["listing_date"].le(min_start) & (
            master["delisting_date"].isna() | master["delisting_date"].ge(observation_date)
        )
        frame = pd.DataFrame(index=symbols)
        frame["adv20"] = data.adv20.loc[observation_date].reindex(symbols)
        frame["adv20_count"] = data.adv20_count.loc[observation_date].reindex(symbols)
        frame["history_count"] = data.history_count.loc[observation_date].reindex(symbols)
        frame["vol60"] = data.vol60.loc[observation_date].reindex(symbols)
        for lookback in config.lookbacks:
            frame[f"r{lookback}"] = data.momentum[lookback].loc[observation_date].reindex(symbols)
        valid = lifecycle.reindex(symbols).fillna(False)
        valid &= frame["history_count"].ge(config.min_history_bars)
        valid &= frame["adv20_count"].ge(config.min_liquidity_observations)
        valid &= frame["vol60"].gt(0)
        valid &= frame[[f"r{x}" for x in config.lookbacks]].notna().all(axis=1)
        eligible = frame.loc[valid].copy()
        raw_count = int(len(eligible))
        if eligible.empty:
            return Snapshot(observation_date, eligible, raw_count, 0, 0)
        eligible["tracking_key"] = data.tracking_key.reindex(eligible.index)
        eligible = eligible[eligible["tracking_key"].notna()]
        eligible = eligible.sort_values(["tracking_key", "adv20"], ascending=[True, False])
        eligible = eligible[~eligible["tracking_key"].duplicated(keep="first")]
        dedup_count = int(len(eligible))
        eligible = eligible[eligible["adv20"].ge(config.min_adv20)].copy()
        liquid_count = int(len(eligible))
        if eligible.empty:
            return Snapshot(observation_date, eligible, raw_count, dedup_count, 0)
        percentile_columns = []
        for lookback in config.lookbacks:
            percentile = f"p{lookback}"
            eligible[percentile] = eligible[f"r{lookback}"].rank(pct=True, method="average")
            percentile_columns.append(percentile)
        eligible["score"] = eligible[percentile_columns].mean(axis=1)
        eligible["positive_count"] = eligible[[f"r{x}" for x in config.lookbacks]].gt(0).sum(axis=1)
        eligible["abs_pass"] = eligible["positive_count"].ge(config.min_positive_horizons)
        eligible["vol60"] = eligible["vol60"].clip(lower=config.vol_floor)
        middle_return = f"r{config.lookbacks[1]}"
        eligible["symbol_sort"] = eligible.index.astype(str)
        eligible = eligible.sort_values(
            ["score", middle_return, "symbol_sort"],
            ascending=[False, False, True],
        )
        eligible["rank"] = np.arange(1, len(eligible) + 1)
        eligible = eligible.drop(columns="symbol_sort")
        return Snapshot(
            observation_date,
            eligible,
            raw_count,
            dedup_count,
            liquid_count,
        )


def correlation_ok(
    candidate: str,
    selected: list[str],
    observation_date: pd.Timestamp,
    data: MarketData,
    config: StrategyConfig,
) -> bool:
    if not selected or not config.use_correlation_guard:
        return True
    for old in selected:
        first, second = sorted((candidate, old))
        key = (observation_date, first, second, config.corr_lookback)
        if key not in data.correlation_cache:
            pair = (
                data.daily_return.loc[:observation_date, [first, second]]
                .dropna()
                .tail(config.corr_lookback)
            )
            data.correlation_cache[key] = float(pair.corr().iloc[0, 1]) if len(pair) >= 40 else None
        correlation = data.correlation_cache[key]
        if correlation is None:
            continue
        if np.isfinite(correlation) and correlation > config.max_pair_corr:
            return False
    return True


def select_assets(
    snapshot: Snapshot,
    held_risk: list[str],
    data: MarketData,
    config: StrategyConfig,
) -> list[str]:
    ranked = snapshot.ranked
    if ranked.empty:
        return []
    passed = ranked[ranked["abs_pass"]] if config.use_absolute_momentum else ranked
    if passed.empty:
        return []
    target_count = config.top_k if config.use_top_k else 1
    rank_map = passed["rank"].to_dict()
    selected: list[str] = []
    if config.use_rank_buffer:
        keep = [
            symbol
            for symbol in held_risk
            if symbol in rank_map and rank_map[symbol] <= target_count + config.rank_buffer
        ]
        keep.sort(key=rank_map.__getitem__)
        for symbol in keep:
            if len(selected) >= target_count:
                break
            if correlation_ok(
                symbol,
                selected,
                snapshot.observation_date,
                data,
                config,
            ):
                selected.append(symbol)
    for symbol in passed.index:
        if len(selected) >= target_count:
            break
        if symbol in selected:
            continue
        if correlation_ok(
            symbol,
            selected,
            snapshot.observation_date,
            data,
            config,
        ):
            selected.append(symbol)
    return selected


def cap_weights_without_forced_redistribution(
    weights: dict[str, float], cap: float
) -> dict[str, float]:
    current = dict(weights)
    for _ in range(10):
        over = [symbol for symbol, weight in current.items() if weight > cap]
        if not over:
            break
        excess = sum(current[symbol] - cap for symbol in over)
        for symbol in over:
            current[symbol] = cap
        under = [symbol for symbol, weight in current.items() if weight < cap - 1e-12]
        room = sum(cap - current[symbol] for symbol in under)
        if not under or room <= 0 or excess <= 0:
            break
        distribute = min(excess, room)
        for symbol in under:
            share = (cap - current[symbol]) / room
            current[symbol] += distribute * share
    return current


def estimate_portfolio_vol(
    weights: dict[str, float],
    observation_date: pd.Timestamp,
    data: MarketData,
    config: StrategyConfig,
) -> float | None:
    symbols = [symbol for symbol, weight in weights.items() if weight > 0]
    if not symbols:
        return None
    cache_key = (
        observation_date,
        tuple(sorted((symbol, round(float(weights[symbol]), 12)) for symbol in symbols)),
        config.vol_lookback,
    )
    if cache_key in data.portfolio_vol_cache:
        return data.portfolio_vol_cache[cache_key]
    returns = (
        data.daily_return.loc[:observation_date, symbols]
        .dropna(how="all")
        .tail(config.vol_lookback)
        .dropna()
    )
    if len(returns) < 40:
        data.portfolio_vol_cache[cache_key] = None
        return None
    covariance = returns.cov().to_numpy() * 252.0
    vector = np.array([weights[symbol] for symbol in symbols], dtype=float)
    variance = float(vector @ covariance @ vector)
    if variance <= 0 or not np.isfinite(variance):
        data.portfolio_vol_cache[cache_key] = None
        return None
    result = math.sqrt(variance)
    data.portfolio_vol_cache[cache_key] = result
    return result


def build_risk_weights(
    selected: list[str],
    snapshot: Snapshot,
    observation_date: pd.Timestamp,
    portfolio_value: float,
    data: MarketData,
    config: StrategyConfig,
) -> tuple[dict[str, float], float | None]:
    if not selected:
        return {}, None
    if config.use_inverse_vol:
        raw_values = {
            symbol: 1.0 / max(float(snapshot.ranked.at[symbol, "vol60"]), config.vol_floor)
            for symbol in selected
        }
    else:
        raw_values = {symbol: 1.0 for symbol in selected}
    total = sum(raw_values.values())
    weights = {symbol: value / total for symbol, value in raw_values.items()}
    if config.use_top_k:
        weights = cap_weights_without_forced_redistribution(weights, config.max_single_risk_weight)
    portfolio_vol = estimate_portfolio_vol(weights, observation_date, data, config)
    if config.use_vol_target and portfolio_vol and portfolio_vol > 0:
        scale = min(1.0, config.target_portfolio_vol / portfolio_vol)
        weights = {symbol: weight * scale for symbol, weight in weights.items()}
    if config.use_capacity and portfolio_value > 0:
        for symbol in list(weights):
            adv = float(snapshot.ranked.at[symbol, "adv20"])
            cap_weight = adv * config.max_adv_participation / portfolio_value
            weights[symbol] = min(weights[symbol], max(0.0, cap_weight))
    weights = {symbol: weight for symbol, weight in weights.items() if weight > 1e-8}
    return weights, portfolio_vol


def choose_defensive_asset(observation_date: pd.Timestamp, data: MarketData) -> str:
    if observation_date in data.defensive_cache:
        return data.defensive_cache[observation_date]
    candidates = []
    for symbol in DEFENSIVE_BONDS:
        if symbol not in data.master.index:
            continue
        listing_date = data.master.at[symbol, "listing_date"]
        delisting_date = data.master.at[symbol, "delisting_date"]
        if pd.isna(listing_date) or listing_date > observation_date:
            continue
        if pd.notna(delisting_date) and delisting_date < observation_date:
            continue
        history = data.adjusted_close.loc[:observation_date, symbol].dropna()
        if len(history) < 127:
            continue
        r63 = float(history.iloc[-1] / history.iloc[-64] - 1.0)
        r126 = float(history.iloc[-1] / history.iloc[-127] - 1.0)
        score = 0.5 * (r63 + r126)
        if score > 0:
            candidates.append((score, symbol))
    if candidates:
        selected = max(candidates)[1]
    else:
        selected = CASH_ETF
    data.defensive_cache[observation_date] = selected
    return selected


def _valid_price(value: object) -> bool:
    return value is not None and np.isfinite(value) and float(value) > 0


def _matrix_value(matrix: pd.DataFrame, date: pd.Timestamp, symbol: str) -> float | None:
    if date not in matrix.index or symbol not in matrix.columns:
        return None
    value = matrix.at[date, symbol]
    return float(value) if _valid_price(value) else None


def _commission(gross_value: float, config: StrategyConfig) -> float:
    if gross_value <= 0 or config.commission_rate <= 0:
        return 0.0
    return max(config.minimum_commission, gross_value * config.commission_rate)


def participation_limited_shares(
    requested_shares: int,
    mark_price: float,
    adv20: float | None,
    participation_rate: float,
) -> int:
    if adv20 is None or adv20 <= 0 or mark_price <= 0:
        return 0
    maximum_value = adv20 * participation_rate
    maximum_shares = int(maximum_value / mark_price) // 100 * 100
    return min(requested_shares, max(0, maximum_shares))


def _execute_targets(
    date: pd.Timestamp,
    observation_date: pd.Timestamp,
    target_weights: dict[str, float],
    equity_open: float,
    cash: float,
    positions: dict[str, int],
    data: MarketData,
    config: StrategyConfig,
    capture_details: bool,
) -> tuple[float, dict[str, int], list[dict], dict[str, float], float, float]:
    universe = set(positions).union(target_weights)
    desired: dict[str, int] = {}
    open_prices: dict[str, float | None] = {}
    for symbol in universe:
        price = _matrix_value(data.adjusted_open, date, symbol)
        open_prices[symbol] = price
        current = int(positions.get(symbol, 0))
        if price is None:
            desired[symbol] = current
            continue
        target_value = equity_open * float(target_weights.get(symbol, 0.0))
        target_shares = int(target_value / price) // 100 * 100
        if symbol not in target_weights:
            desired[symbol] = 0
            continue
        current_value = current * price
        current_weight = current_value / equity_open if equity_open > 0 else 0.0
        gap = float(target_weights[symbol]) - current_weight
        trade_value = abs(target_value - current_value)
        if current > 0 and abs(gap) < config.min_weight_change:
            desired[symbol] = current
        elif trade_value < config.min_trade_value:
            desired[symbol] = current
        else:
            desired[symbol] = target_shares

    trades: list[dict] = []
    cost_by_symbol: dict[str, float] = {}
    gross_traded = 0.0
    total_cost = 0.0

    def limit_shares_for_symbol(symbol: str, shares: int, mark_price: float) -> int:
        if not config.enforce_trade_adv_participation:
            return shares
        if symbol not in data.tracking_key.index:
            return shares
        adv = _matrix_value(data.adv20, observation_date, symbol)
        if adv is None:
            return 0
        return participation_limited_shares(
            shares,
            mark_price,
            adv,
            config.max_adv_participation,
        )

    def record_trade(symbol: str, side: str, shares: int, mark_price: float) -> None:
        nonlocal cash, gross_traded, total_cost
        gross = shares * mark_price
        slippage = gross * config.slippage_rate
        commission = _commission(gross, config)
        cost = slippage + commission
        if side == "sell":
            cash += gross - cost
        else:
            cash -= gross + cost
        gross_traded += gross
        total_cost += cost
        cost_by_symbol[symbol] = cost_by_symbol.get(symbol, 0.0) + cost
        if capture_details:
            adv = _matrix_value(data.adv20, observation_date, symbol)
            trades.append(
                {
                    "trade_date": date,
                    "observation_date": observation_date,
                    "side": side,
                    "symbol": symbol,
                    "shares": shares,
                    "mark_price": mark_price,
                    "gross_value": gross,
                    "slippage": slippage,
                    "commission": commission,
                    "total_cost": cost,
                    "adv20": adv,
                    "trade_adv_participation": gross / adv if adv else np.nan,
                }
            )

    for symbol in sorted(universe):
        current = int(positions.get(symbol, 0))
        target = int(desired[symbol])
        price = open_prices[symbol]
        if target >= current or price is None:
            continue
        shares = limit_shares_for_symbol(symbol, current - target, price)
        if shares <= 0:
            continue
        record_trade(symbol, "sell", shares, price)
        remaining = current - shares
        if remaining == 0:
            positions.pop(symbol, None)
        else:
            positions[symbol] = remaining

    buy_order = sorted(
        universe,
        key=lambda symbol: (-float(target_weights.get(symbol, 0.0)), symbol),
    )
    for symbol in buy_order:
        current = int(positions.get(symbol, 0))
        target = int(desired[symbol])
        price = open_prices[symbol]
        if target <= current or price is None:
            continue
        shares = limit_shares_for_symbol(symbol, target - current, price)
        while shares > 0:
            gross = shares * price
            required = gross + gross * config.slippage_rate + _commission(gross, config)
            if required <= cash + 1e-8:
                break
            shares -= 100
        if shares <= 0:
            continue
        record_trade(symbol, "buy", shares, price)
        positions[symbol] = current + shares
    return cash, positions, trades, cost_by_symbol, gross_traded, total_cost


def performance_metrics(equity: pd.DataFrame) -> dict:
    if equity.empty:
        raise ValueError("equity is empty")
    returns = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)
    curve = (1.0 + returns).cumprod()
    total_return = float(curve.iloc[-1] - 1.0)
    years = len(returns) / 252.0
    annualized_return = float((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 else np.nan
    standard_deviation = float(returns.std(ddof=1))
    annualized_volatility = standard_deviation * math.sqrt(252.0)
    sharpe = (
        float(returns.mean() / standard_deviation * math.sqrt(252.0))
        if standard_deviation > 0
        else np.nan
    )
    downside = float(returns.clip(upper=0).std(ddof=1) * math.sqrt(252.0))
    sortino = float(returns.mean() * 252.0 / downside) if downside > 0 else np.nan
    drawdown = curve / curve.cummax() - 1.0
    maximum_drawdown = float(-drawdown.min())
    calmar = float(annualized_return / maximum_drawdown) if maximum_drawdown > 0 else np.nan
    longest_underwater = current_underwater = 0
    for flag in drawdown.lt(-1e-12):
        current_underwater = current_underwater + 1 if flag else 0
        longest_underwater = max(longest_underwater, current_underwater)
    traded = float(equity.get("gross_traded", pd.Series(0.0, index=equity.index)).sum())
    average_value = float(pd.to_numeric(equity["total_value"]).mean())
    turnover = traded / average_value if average_value > 0 else np.nan
    rolling_three_year = curve / curve.shift(756) - 1.0
    metrics = {
        "trading_days": int(len(equity)),
        "total_return": total_return,
        "annualized_return": annualized_return,
        "maximum_drawdown": maximum_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "annualized_volatility": annualized_volatility,
        "turnover": turnover,
        "annualized_turnover": turnover / years if years > 0 else np.nan,
        "transaction_cost": float(
            equity.get("transaction_cost", pd.Series(0.0, index=equity.index)).sum()
        ),
        "average_cash_ratio": float(
            equity.get("cash_ratio", pd.Series(np.nan, index=equity.index)).mean()
        ),
        "average_risk_weight": float(
            equity.get("risk_weight", pd.Series(np.nan, index=equity.index)).mean()
        ),
        "longest_underwater_trading_days": int(longest_underwater),
        "worst_rolling_three_year_return": (
            float(rolling_three_year.min()) if rolling_three_year.notna().any() else None
        ),
        "positive_day_ratio": float(returns.gt(0).mean()),
    }
    return metrics


def run_simulation_fast(
    data: MarketData,
    cache: SnapshotCache,
    config: StrategyConfig,
    start: str,
    end: str,
) -> SimulationResult:
    """事件驱动调仓、区间向量化估值；与详细逐日账本口径逐点校验。"""

    dates = data.trade_dates[
        (data.trade_dates >= pd.Timestamp(start)) & (data.trade_dates <= pd.Timestamp(end))
    ]
    if len(dates) == 0:
        raise ValueError("backtest period has no trading dates")
    observation_by_execution = {
        execution: observation
        for observation, execution in weekly_execution_pairs(data.trade_dates)
        if execution in dates
    }
    execution_dates = sorted(observation_by_execution)
    risk_set = set(data.risk_symbols)
    cash = float(config.initial_cash)
    positions: dict[str, int] = {}
    last_close: dict[str, float] = {}
    total_values = np.full(len(dates), np.nan)
    cash_values = np.full(len(dates), np.nan)
    position_values = np.full(len(dates), np.nan)
    risk_values = np.full(len(dates), np.nan)
    gross_traded = np.zeros(len(dates))
    transaction_cost = np.zeros(len(dates))
    holdings = np.full(len(dates), "", dtype=object)
    date_locations = {date: index for index, date in enumerate(dates)}

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
            closes = data.adjusted_close.reindex(index=segment, columns=symbols).copy()
            for symbol in symbols:
                fallback = last_close.get(symbol)
                if fallback is None:
                    fallback = _matrix_value(data.adjusted_open, segment[0], symbol)
                series = closes[symbol].copy()
                if fallback is not None and pd.isna(series.iloc[0]):
                    series.iloc[0] = float(fallback)
                closes[symbol] = series.ffill()
            shares = np.array([positions[symbol] for symbol in symbols], dtype=float)
            matrix = closes.to_numpy(dtype=float)
            values = matrix @ shares
            risk_shares = np.array(
                [positions[symbol] if symbol in risk_set else 0 for symbol in symbols],
                dtype=float,
            )
            risk = matrix @ risk_shares
            for column, symbol in enumerate(symbols):
                value = matrix[-1, column]
                if np.isfinite(value):
                    last_close[symbol] = float(value)
            holding_text = ";".join(symbols)
        else:
            values = np.zeros(len(segment))
            risk = np.zeros(len(segment))
            holding_text = ""
        cash_values[locations] = cash
        position_values[locations] = values
        risk_values[locations] = risk
        total_values[locations] = cash + values
        holdings[locations] = holding_text
        gross_traded[locations[0]] = traded_on_first_day
        transaction_cost[locations[0]] = cost_on_first_day

    first_execution_location = date_locations[execution_dates[0]] if execution_dates else len(dates)
    if first_execution_location:
        value_segment(dates[:first_execution_location], 0.0, 0.0)

    for execution_index, execution_date in enumerate(execution_dates):
        observation_date = observation_by_execution[execution_date]
        equity_open = cash
        for symbol, shares in positions.items():
            price = _matrix_value(data.adjusted_open, execution_date, symbol)
            mark = price if price is not None else last_close.get(symbol)
            if mark is not None:
                equity_open += shares * mark
        snapshot = cache.get(observation_date, config)
        held_risk = [symbol for symbol in positions if symbol in risk_set]
        selected = select_assets(snapshot, held_risk, data, config)
        risk_weights, _ = build_risk_weights(
            selected,
            snapshot,
            observation_date,
            equity_open,
            data,
            config,
        )
        target_weights = dict(risk_weights)
        remaining = max(0.0, 1.0 - sum(target_weights.values()))
        if remaining > 1e-8:
            defensive = choose_defensive_asset(observation_date, data)
            target_weights[defensive] = target_weights.get(defensive, 0.0) + remaining
        cash, positions, _, _, traded, cost = _execute_targets(
            execution_date,
            observation_date,
            target_weights,
            equity_open,
            cash,
            positions,
            data,
            config,
            False,
        )
        start_location = date_locations[execution_date]
        end_location = (
            date_locations[execution_dates[execution_index + 1]]
            if execution_index + 1 < len(execution_dates)
            else len(dates)
        )
        value_segment(dates[start_location:end_location], traded, cost)

    if np.isnan(total_values).any():
        raise AssertionError("fast simulator left unvalued trading dates")
    previous_values = np.concatenate(([float(config.initial_cash)], total_values[:-1]))
    daily_returns = total_values / previous_values - 1.0
    equity = pd.DataFrame(
        {
            "trade_date": dates,
            "cash": cash_values,
            "positions_value": position_values,
            "total_value": total_values,
            "daily_return": daily_returns,
            "cash_ratio": cash_values / total_values,
            "risk_weight": risk_values / total_values,
            "gross_traded": gross_traded,
            "transaction_cost": transaction_cost,
            "holdings": holdings,
            "unattributed_pnl": np.nan,
        }
    )
    return SimulationResult(
        config=config,
        equity=equity,
        trades=pd.DataFrame(),
        positions=pd.DataFrame(),
        decisions=pd.DataFrame(),
        contributions=pd.DataFrame(),
        metrics=performance_metrics(equity),
    )


def run_simulation(
    data: MarketData,
    cache: SnapshotCache,
    config: StrategyConfig,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    *,
    capture_details: bool = False,
) -> SimulationResult:
    if not capture_details:
        return run_simulation_fast(data, cache, config, start, end)
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    dates = data.trade_dates[(data.trade_dates >= start_date) & (data.trade_dates <= end_date)]
    if len(dates) == 0:
        raise ValueError("backtest period has no trading dates")
    observation_by_execution = {
        execution: observation
        for observation, execution in weekly_execution_pairs(data.trade_dates)
        if execution in dates
    }
    risk_set = set(data.risk_symbols)
    cash = float(config.initial_cash)
    positions: dict[str, int] = {}
    last_close: dict[str, float] = {}
    previous_total = float(config.initial_cash)
    equity_rows: list[dict] = []
    trade_rows: list[dict] = []
    position_rows: list[dict] = []
    decision_rows: list[dict] = []
    contribution_rows: list[dict] = []

    for date in dates:
        old_positions = dict(positions)
        old_last_close = dict(last_close)
        open_marks: dict[str, float] = {}
        equity_open = cash
        for symbol, shares in old_positions.items():
            price = _matrix_value(data.adjusted_open, date, symbol)
            mark = price if price is not None else old_last_close.get(symbol)
            if mark is None:
                continue
            open_marks[symbol] = float(mark)
            equity_open += shares * float(mark)

        day_costs: dict[str, float] = {}
        day_traded = 0.0
        day_total_cost = 0.0
        if date in observation_by_execution:
            observation = observation_by_execution[date]
            snapshot = cache.get(observation, config)
            held_risk = [symbol for symbol in positions if symbol in risk_set]
            selected = select_assets(snapshot, held_risk, data, config)
            risk_weights, estimated_vol = build_risk_weights(
                selected,
                snapshot,
                observation,
                equity_open,
                data,
                config,
            )
            target_weights = dict(risk_weights)
            remaining = max(0.0, 1.0 - sum(target_weights.values()))
            defensive = choose_defensive_asset(observation, data)
            if remaining > 1e-8:
                target_weights[defensive] = target_weights.get(defensive, 0.0) + remaining
            (
                cash,
                positions,
                executed,
                day_costs,
                day_traded,
                day_total_cost,
            ) = _execute_targets(
                date,
                observation,
                target_weights,
                equity_open,
                cash,
                positions,
                data,
                config,
                capture_details,
            )
            trade_rows.extend(executed)
            if capture_details:
                decision_rows.append(
                    {
                        "execution_date": date,
                        "observation_date": observation,
                        "raw_eligible_count": snapshot.raw_eligible_count,
                        "deduplicated_count": snapshot.deduplicated_count,
                        "liquid_count": snapshot.liquid_count,
                        "absolute_pass_count": int(
                            snapshot.ranked.get("abs_pass", pd.Series(dtype=bool)).sum()
                        ),
                        "selected": ";".join(selected),
                        "defensive": defensive,
                        "estimated_pre_target_vol": estimated_vol,
                        "risk_weight": sum(risk_weights.values()),
                        "target_weights": json.dumps(
                            target_weights, ensure_ascii=False, sort_keys=True
                        ),
                        "target_weight_sum": sum(target_weights.values()),
                    }
                )

        close_marks: dict[str, float] = {}
        positions_value = 0.0
        risk_value = 0.0
        for symbol, shares in sorted(positions.items()):
            price = _matrix_value(data.adjusted_close, date, symbol)
            if price is None:
                price = _matrix_value(data.adjusted_open, date, symbol)
            if price is None:
                price = open_marks.get(symbol, old_last_close.get(symbol))
            if price is None:
                continue
            close_marks[symbol] = float(price)
            last_close[symbol] = float(price)
            market_value = shares * float(price)
            positions_value += market_value
            if symbol in risk_set:
                risk_value += market_value
            if capture_details:
                position_rows.append(
                    {
                        "trade_date": date,
                        "symbol": symbol,
                        "shares": shares,
                        "adjusted_close": price,
                        "market_value": market_value,
                    }
                )
        total_value = cash + positions_value
        daily_return = total_value / previous_total - 1.0

        if capture_details:
            contributions: dict[str, float] = {}
            for symbol, shares in old_positions.items():
                previous_price = old_last_close.get(symbol)
                current_open = open_marks.get(symbol, previous_price)
                if previous_price is not None and current_open is not None:
                    contributions[symbol] = contributions.get(symbol, 0.0) + shares * (
                        current_open - previous_price
                    )
            for symbol, shares in positions.items():
                current_open = _matrix_value(data.adjusted_open, date, symbol)
                current_close = close_marks.get(symbol)
                if current_open is not None and current_close is not None:
                    contributions[symbol] = contributions.get(symbol, 0.0) + shares * (
                        current_close - current_open
                    )
            for symbol, cost in day_costs.items():
                contributions[symbol] = contributions.get(symbol, 0.0) - cost
            for symbol, pnl in contributions.items():
                contribution_rows.append(
                    {
                        "trade_date": date,
                        "symbol": symbol,
                        "net_pnl_contribution": pnl,
                        "return_contribution": pnl / previous_total,
                    }
                )
            attributed = sum(contributions.values())
            unattributed = total_value - previous_total - attributed
        else:
            unattributed = np.nan

        equity_rows.append(
            {
                "trade_date": date,
                "cash": cash,
                "positions_value": positions_value,
                "total_value": total_value,
                "daily_return": daily_return,
                "cash_ratio": cash / total_value if total_value > 0 else np.nan,
                "risk_weight": risk_value / total_value if total_value > 0 else np.nan,
                "gross_traded": day_traded,
                "transaction_cost": day_total_cost,
                "holdings": ";".join(sorted(positions)),
                "unattributed_pnl": unattributed,
            }
        )
        previous_total = total_value

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    positions_frame = pd.DataFrame(position_rows)
    decisions = pd.DataFrame(decision_rows)
    contributions = pd.DataFrame(contribution_rows)
    metrics = performance_metrics(equity)
    return SimulationResult(
        config=config,
        equity=equity,
        trades=trades,
        positions=positions_frame,
        decisions=decisions,
        contributions=contributions,
        metrics=metrics,
    )


def ablation_configs(base: StrategyConfig) -> list[StrategyConfig]:
    layers = [
        (
            "m0_relative_momentum",
            {
                "use_absolute_momentum": False,
                "use_top_k": False,
                "use_inverse_vol": False,
                "use_vol_target": False,
                "use_rank_buffer": False,
                "use_correlation_guard": False,
                "use_capacity": False,
            },
        ),
        ("m1_absolute_momentum", {"use_absolute_momentum": True}),
        ("m2_topk", {"use_top_k": True}),
        ("m3_inverse_vol", {"use_inverse_vol": True}),
        ("m4_vol_target", {"use_vol_target": True}),
        ("m5_rank_buffer", {"use_rank_buffer": True}),
        ("m6_correlation_guard", {"use_correlation_guard": True}),
        ("m7_capacity_baseline", {"use_capacity": True}),
    ]
    active = {
        "use_absolute_momentum": False,
        "use_top_k": False,
        "use_inverse_vol": False,
        "use_vol_target": False,
        "use_rank_buffer": False,
        "use_correlation_guard": False,
        "use_capacity": False,
    }
    configs = []
    for name, additions in layers:
        active.update(additions)
        configs.append(replace(base, name=name, **active))
    return configs


def parameter_configs(base: StrategyConfig) -> list[StrategyConfig]:
    configurations = []
    products = itertools.product(
        (2, 3, 4, 5),
        ((42, 84, 168), (63, 126, 252), (84, 168, 252)),
        (0.85, 0.90, 0.95),
        (0.15, 0.18, 0.20, 0.25),
        (10_000_000.0, 20_000_000.0, 50_000_000.0),
        (1, 2, 3),
    )
    for index, (top_k, lookbacks, correlation, target_vol, adv, buffer) in enumerate(
        products, start=1
    ):
        configurations.append(
            replace(
                base,
                name=f"grid_{index:04d}",
                top_k=top_k,
                lookbacks=lookbacks,
                max_pair_corr=correlation,
                target_portfolio_vol=target_vol,
                min_adv20=adv,
                rank_buffer=buffer,
            )
        )
    return configurations


def _config_columns(config: StrategyConfig) -> dict:
    return {
        "trial": config.name,
        "top_k": config.top_k,
        "lookbacks": "/".join(str(value) for value in config.lookbacks),
        "max_pair_corr": config.max_pair_corr,
        "target_portfolio_vol": config.target_portfolio_vol,
        "min_adv20": config.min_adv20,
        "rank_buffer": config.rank_buffer,
        "initial_cash": config.initial_cash,
    }


def _result_row(result: SimulationResult) -> dict:
    return {**_config_columns(result.config), **result.metrics}


def yearly_metrics(equity: pd.DataFrame) -> pd.DataFrame:
    frame = equity.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    rows = []
    for year, group in frame.groupby(frame["trade_date"].dt.year):
        rows.append({"year": int(year), **performance_metrics(group.reset_index(drop=True))})
    return pd.DataFrame(rows)


def rolling_three_year_metrics(equity: pd.DataFrame) -> pd.DataFrame:
    frame = equity.copy().reset_index(drop=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    month_ends = frame.groupby(frame["trade_date"].dt.to_period("M")).tail(1).index
    rows = []
    for end_index in month_ends:
        if end_index < 755:
            continue
        window = frame.iloc[end_index - 755 : end_index + 1].copy()
        metrics = performance_metrics(window.reset_index(drop=True))
        rows.append(
            {
                "window_end": frame.at[end_index, "trade_date"],
                "window_start": window.iloc[0]["trade_date"],
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def regime_metrics(result: SimulationResult, data: MarketData) -> pd.DataFrame:
    equity = result.equity.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(equity["trade_date"]))
    benchmark = data.adjusted_close[BENCHMARK].dropna()
    trailing = benchmark / benchmark.shift(252) - 1.0
    known_trailing = trailing.shift(1).reindex(dates)
    labels = pd.Series("sideways", index=dates)
    labels.loc[known_trailing.gt(0.10)] = "bull"
    labels.loc[known_trailing.lt(-0.10)] = "bear"
    equity["regime"] = labels.to_numpy()
    rows = []
    for regime in ("bull", "bear", "sideways"):
        selected = equity[equity["regime"].eq(regime)].reset_index(drop=True)
        if selected.empty:
            continue
        rows.append({"regime": regime, **performance_metrics(selected)})
    return pd.DataFrame(rows)


def asset_concentration(
    result: SimulationResult, risk_symbols: set[str]
) -> tuple[pd.DataFrame, dict]:
    contributions = result.contributions.copy()
    if contributions.empty:
        return pd.DataFrame(), {}
    contribution = (
        contributions.groupby("symbol", as_index=False)[
            ["net_pnl_contribution", "return_contribution"]
        ]
        .sum()
        .rename(columns={"net_pnl_contribution": "net_pnl"})
    )
    positions = result.positions.copy()
    equity_values = result.equity.set_index("trade_date")["total_value"]
    positions["portfolio_weight"] = positions["market_value"] / positions["trade_date"].map(
        equity_values
    )
    exposure = positions.groupby("symbol").agg(
        holding_days=("trade_date", "nunique"),
        average_weight_when_held=("portfolio_weight", "mean"),
        maximum_weight=("portfolio_weight", "max"),
    )
    exposure["average_portfolio_weight"] = positions.groupby("symbol")[
        "portfolio_weight"
    ].sum() / len(result.equity)
    table = contribution.join(exposure, on="symbol")
    table["is_risk_asset"] = table["symbol"].isin(risk_symbols)
    positive_total = table["net_pnl"].clip(lower=0).sum()
    table["share_of_positive_contribution"] = (
        table["net_pnl"].clip(lower=0) / positive_total if positive_total > 0 else 0.0
    )
    table = table.sort_values("net_pnl", ascending=False).reset_index(drop=True)
    risk_table = table[table["is_risk_asset"]].copy()
    shares = risk_table["share_of_positive_contribution"].to_numpy(dtype=float)
    statistics = {
        "risk_asset_count_held": int(risk_table["symbol"].nunique()),
        "top1_positive_contribution_share": float(shares[:1].sum()),
        "top3_positive_contribution_share": float(shares[:3].sum()),
        "top5_positive_contribution_share": float(shares[:5].sum()),
        "positive_contribution_hhi": float(np.square(shares).sum()),
        "top_risk_symbols": risk_table.head(5)["symbol"].tolist(),
    }
    return table, statistics


def _sharpe_by_trial(return_matrix: np.ndarray) -> np.ndarray:
    means = np.nanmean(return_matrix, axis=1)
    standard_deviations = np.nanstd(return_matrix, axis=1, ddof=1)
    return np.divide(
        means,
        standard_deviations,
        out=np.full_like(means, np.nan),
        where=standard_deviations > 0,
    ) * math.sqrt(252.0)


def compute_pbo(
    return_matrix: np.ndarray,
    dates: pd.DatetimeIndex,
    trial_names: list[str],
    partitions: int = 8,
) -> tuple[pd.DataFrame, dict]:
    if partitions % 2:
        raise ValueError("PBO partitions must be even")
    blocks = [
        np.asarray(block, dtype=int) for block in np.array_split(np.arange(len(dates)), partitions)
    ]
    rows = []
    for split_number, train_blocks in enumerate(
        itertools.combinations(range(partitions), partitions // 2), start=1
    ):
        train_set = set(train_blocks)
        test_blocks = tuple(index for index in range(partitions) if index not in train_set)
        train_index = np.concatenate([blocks[index] for index in train_blocks])
        test_index = np.concatenate([blocks[index] for index in test_blocks])
        train_sharpe = _sharpe_by_trial(return_matrix[:, train_index])
        test_sharpe = _sharpe_by_trial(return_matrix[:, test_index])
        winner = int(np.nanargmax(train_sharpe))
        winner_oos = float(test_sharpe[winner])
        finite = test_sharpe[np.isfinite(test_sharpe)]
        percentile = float((np.sum(finite < winner_oos) + 0.5) / len(finite))
        percentile = min(max(percentile, 1e-12), 1.0 - 1e-12)
        logit = math.log(percentile / (1.0 - percentile))
        rows.append(
            {
                "split": split_number,
                "train_blocks": ";".join(map(str, train_blocks)),
                "test_blocks": ";".join(map(str, test_blocks)),
                "selected_trial": trial_names[winner],
                "is_sharpe": float(train_sharpe[winner]),
                "oos_sharpe": winner_oos,
                "oos_percentile": percentile,
                "logit": logit,
                "below_oos_median": bool(logit <= 0),
            }
        )
    frame = pd.DataFrame(rows)
    summary = {
        "method": "CSCV approximation with 8 contiguous blocks and all 70 half-splits",
        "trial_count": int(return_matrix.shape[0]),
        "trading_days": int(return_matrix.shape[1]),
        "partition_count": partitions,
        "split_count": int(len(frame)),
        "pbo": float(frame["below_oos_median"].mean()),
        "median_selected_oos_percentile": float(frame["oos_percentile"].median()),
    }
    return frame, summary


def deflated_sharpe_probability(
    returns: np.ndarray,
    all_trial_returns: np.ndarray,
) -> dict:
    observed = np.asarray(returns, dtype=float)
    observed = observed[np.isfinite(observed)]
    trial_daily_sharpes = _sharpe_by_trial(all_trial_returns) / math.sqrt(252.0)
    trial_daily_sharpes = trial_daily_sharpes[np.isfinite(trial_daily_sharpes)]
    observed_daily_sharpe = float(observed.mean() / observed.std(ddof=1))
    trial_count = int(len(trial_daily_sharpes))
    euler_gamma = 0.5772156649015329
    if trial_count > 1:
        expected_max_z = (1.0 - euler_gamma) * stats.norm.ppf(
            1.0 - 1.0 / trial_count
        ) + euler_gamma * stats.norm.ppf(1.0 - 1.0 / (trial_count * math.e))
        expected_max_sharpe = float(np.std(trial_daily_sharpes, ddof=1) * expected_max_z)
    else:
        expected_max_sharpe = 0.0
    skewness = float(stats.skew(observed, bias=False))
    kurtosis = float(stats.kurtosis(observed, fisher=False, bias=False))
    denominator = math.sqrt(
        max(
            1e-12,
            1.0
            - skewness * observed_daily_sharpe
            + (kurtosis - 1.0) * observed_daily_sharpe**2 / 4.0,
        )
    )
    statistic = (
        (observed_daily_sharpe - expected_max_sharpe)
        * math.sqrt(max(1, len(observed) - 1))
        / denominator
    )
    return {
        "trial_count": trial_count,
        "observations": int(len(observed)),
        "observed_annualized_sharpe": observed_daily_sharpe * math.sqrt(252.0),
        "expected_maximum_annualized_sharpe_under_null": expected_max_sharpe * math.sqrt(252.0),
        "skewness": skewness,
        "pearson_kurtosis": kurtosis,
        "deflated_sharpe_probability": float(stats.norm.cdf(statistic)),
        "method_note": (
            "Bailey-Lopez de Prado DSR approximation; correlated grid trials make the "
            "independent-trial expected maximum conservative only as a diagnostic."
        ),
    }


def _metrics_from_return_array(returns: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    returns = np.asarray(returns, dtype=float)
    curve = np.cumprod(1.0 + returns)
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "daily_return": returns,
            "total_value": curve,
            "gross_traded": 0.0,
            "transaction_cost": 0.0,
            "cash_ratio": np.nan,
            "risk_weight": np.nan,
        }
    )
    return performance_metrics(frame)


def expanding_walk_forward(
    return_matrix: np.ndarray,
    dates: pd.DatetimeIndex,
    configs: list[StrategyConfig],
    baseline_returns: np.ndarray,
    first_test_year: int = 2019,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    combined = np.full(len(dates), np.nan)
    rows = []
    final_year = int(dates.max().year)
    for year in range(first_test_year, final_year + 1):
        train_mask = dates.year < year
        test_mask = dates.year == year
        if train_mask.sum() < 756 or not test_mask.any():
            continue
        train_sharpes = _sharpe_by_trial(return_matrix[:, train_mask])
        winner = int(np.nanargmax(train_sharpes))
        combined[test_mask] = return_matrix[winner, test_mask]
        oos_metrics = _metrics_from_return_array(return_matrix[winner, test_mask], dates[test_mask])
        rows.append(
            {
                "test_year": year,
                "train_start": dates[train_mask].min(),
                "train_end": dates[train_mask].max(),
                "test_start": dates[test_mask].min(),
                "test_end": dates[test_mask].max(),
                "selected_trial": configs[winner].name,
                **_config_columns(configs[winner]),
                "is_sharpe": float(train_sharpes[winner]),
                "oos_annualized_return": oos_metrics["annualized_return"],
                "oos_maximum_drawdown": oos_metrics["maximum_drawdown"],
                "oos_sharpe": oos_metrics["sharpe"],
            }
        )
    valid = np.isfinite(combined)
    combined_metrics = _metrics_from_return_array(combined[valid], dates[valid])
    baseline_metrics = _metrics_from_return_array(baseline_returns[valid], dates[valid])
    equity = pd.DataFrame(
        {
            "trade_date": dates[valid],
            "selected_model_return": combined[valid],
            "frozen_baseline_return": baseline_returns[valid],
            "selected_model_equity": np.cumprod(1.0 + combined[valid]),
            "frozen_baseline_equity": np.cumprod(1.0 + baseline_returns[valid]),
        }
    )
    summary = {
        "selection_rule": "highest expanding-window in-sample Sharpe among all grid trials",
        "first_test_year": first_test_year,
        "test_year_count": int(len(rows)),
        "selected_model": combined_metrics,
        "frozen_baseline_same_oos_dates": baseline_metrics,
    }
    return pd.DataFrame(rows), equity, summary


def parameter_stability_summary(grid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dimension in (
        "top_k",
        "lookbacks",
        "max_pair_corr",
        "target_portfolio_vol",
        "min_adv20",
        "rank_buffer",
    ):
        for value, group in grid.groupby(dimension, dropna=False):
            rows.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "trial_count": int(len(group)),
                    "positive_annualized_ratio": float(group["annualized_return"].gt(0).mean()),
                    "median_annualized_return": float(group["annualized_return"].median()),
                    "q25_annualized_return": float(group["annualized_return"].quantile(0.25)),
                    "q75_annualized_return": float(group["annualized_return"].quantile(0.75)),
                    "median_maximum_drawdown": float(group["maximum_drawdown"].median()),
                    "median_sharpe": float(group["sharpe"].median()),
                    "q25_sharpe": float(group["sharpe"].quantile(0.25)),
                    "q75_sharpe": float(group["sharpe"].quantile(0.75)),
                    "median_annualized_turnover": float(group["annualized_turnover"].median()),
                }
            )
    return pd.DataFrame(rows)


def validate_baseline_result(result: SimulationResult, data: MarketData) -> dict:
    errors = []
    decisions = result.decisions.copy()
    if not decisions.empty:
        causal = pd.to_datetime(decisions["observation_date"]) < pd.to_datetime(
            decisions["execution_date"]
        )
        if not causal.all():
            errors.append("observation date is not strictly before execution date")
        if decisions["target_weight_sum"].gt(1.0 + 1e-10).any():
            errors.append("target weights exceed 100%")
    equity = result.equity
    if not np.isfinite(equity["total_value"]).all() or equity["total_value"].le(0).any():
        errors.append("equity contains invalid values")
    max_unattributed = float(equity["unattributed_pnl"].abs().max())
    if max_unattributed > 1e-5:
        errors.append(f"P&L attribution does not reconcile: {max_unattributed}")
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
    max_participation = None
    over_half_percent = 0
    risk_trades = result.trades[
        result.trades.get("symbol", pd.Series(dtype=str)).isin(data.risk_symbols)
    ]
    if not risk_trades.empty and risk_trades["trade_adv_participation"].notna().any():
        participation = risk_trades["trade_adv_participation"].dropna()
        max_participation = float(participation.max())
        over_half_percent = int(participation.gt(0.005 + 1e-12).sum())
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "causal_decision_count": int(len(decisions)),
        "lifecycle_violations": lifecycle_violations,
        "maximum_absolute_unattributed_pnl": max_unattributed,
        "maximum_trade_adv_participation": max_participation,
        "trade_count_above_0_5pct_adv": over_half_percent,
        "note": (
            "The baseline caps target risk holdings at 0.5% of lagged ADV20. Forced "
            "reductions can exceed 0.5% trade/ADV and are reported rather than hidden."
        ),
    }


def run_experiment_suite(
    data_root: Path | str,
    start: str,
    end: str,
) -> dict:
    print("[1/8] loading local ETF data and causal features", flush=True)
    data = load_market_data(data_root)
    cache = SnapshotCache(data)
    baseline_config = StrategyConfig()

    print("[2/8] running frozen baseline and incremental ablations", flush=True)
    baseline = run_simulation(
        data,
        cache,
        baseline_config,
        start,
        end,
        capture_details=True,
    )
    baseline_validation = validate_baseline_result(baseline, data)
    if baseline_validation["status"] != "passed":
        raise AssertionError(baseline_validation["errors"])
    ablation_rows = []
    for config in ablation_configs(baseline_config):
        if config.name == "m7_capacity_baseline":
            result = baseline
        else:
            result = run_simulation(data, cache, config, start, end)
        row = _result_row(result)
        row["model"] = config.name
        ablation_rows.append(row)
    ablation = pd.DataFrame(ablation_rows)

    print("[3/8] running 1,296 full-factorial parameter trials", flush=True)
    configs = parameter_configs(baseline_config)
    grid_rows = []
    grid_returns = []
    baseline_grid_index = None
    for index, config in enumerate(configs):
        result = run_simulation(data, cache, config, start, end)
        grid_rows.append(_result_row(result))
        grid_returns.append(result.equity["daily_return"].to_numpy(dtype=float))
        if (
            config.top_k == 3
            and config.lookbacks == (63, 126, 252)
            and config.max_pair_corr == 0.90
            and config.target_portfolio_vol == 0.18
            and config.min_adv20 == 20_000_000.0
            and config.rank_buffer == 2
        ):
            baseline_grid_index = index
        if (index + 1) % 100 == 0 or index + 1 == len(configs):
            print(f"  parameter trials completed: {index + 1}/{len(configs)}", flush=True)
    parameter_grid = pd.DataFrame(grid_rows)
    return_matrix = np.vstack(grid_returns)
    if baseline_grid_index is None:
        raise AssertionError("baseline configuration is missing from parameter grid")
    baseline_returns = baseline.equity["daily_return"].to_numpy(dtype=float)
    if not np.allclose(return_matrix[baseline_grid_index], baseline_returns, rtol=0, atol=1e-12):
        raise AssertionError("baseline grid trial does not reproduce frozen baseline")
    stability = parameter_stability_summary(parameter_grid)

    print("[4/8] running cost and capital-capacity pressure tests", flush=True)
    cost_rows = []
    cost_results = {}
    for basis_points in (5, 10, 20, 30):
        config = replace(
            baseline_config,
            name=f"all_in_{basis_points}bp",
            commission_rate=0.0,
            minimum_commission=0.0,
            slippage_rate=basis_points / 10_000.0,
        )
        result = run_simulation(data, cache, config, start, end)
        cost_results[basis_points] = result
        cost_rows.append(
            {
                "single_side_total_cost_bp": basis_points,
                **_result_row(result),
            }
        )
    cost_stress = pd.DataFrame(cost_rows)

    def capacity_row(
        capital: int,
        result: SimulationResult,
        implementation: str,
    ) -> dict:
        row = {
            "implementation": implementation,
            "capital": capital,
            **_result_row(result),
        }
        risk_trades = result.trades[
            result.trades.get("symbol", pd.Series(dtype=str)).isin(data.risk_symbols)
        ]
        participation = risk_trades.get("trade_adv_participation", pd.Series(dtype=float)).dropna()
        row["maximum_trade_adv_participation"] = (
            float(participation.max()) if len(participation) else np.nan
        )
        row["risk_trade_count_above_0_5pct_adv"] = int(participation.gt(0.005 + 1e-12).sum())
        lifecycle_violations = 0
        if not result.positions.empty:
            positions = result.positions.merge(
                data.master[["symbol", "listing_date", "delisting_date"]].reset_index(drop=True),
                on="symbol",
                how="left",
            )
            dates_held = pd.to_datetime(positions["trade_date"])
            invalid = dates_held.lt(positions["listing_date"]) | (
                positions["delisting_date"].notna() & dates_held.gt(positions["delisting_date"])
            )
            lifecycle_violations = int(invalid.sum())
        row["position_days_outside_lifecycle"] = lifecycle_violations
        return row

    capacity_as_coded_rows = []
    capacity_strict_rows = []
    for capital in (200_000, 1_000_000, 5_000_000, 10_000_000, 50_000_000):
        config = replace(
            baseline_config,
            name=f"capital_{capital}",
            initial_cash=float(capital),
        )
        result = (
            baseline
            if capital == 1_000_000
            else run_simulation(data, cache, config, start, end, capture_details=True)
        )
        capacity_as_coded_rows.append(capacity_row(capital, result, "target-holding-cap-only"))
        strict_config = replace(
            baseline_config,
            name=f"strict_capital_{capital}",
            initial_cash=float(capital),
            enforce_trade_adv_participation=True,
        )
        strict_result = run_simulation(
            data,
            cache,
            strict_config,
            start,
            end,
            capture_details=True,
        )
        capacity_strict_rows.append(
            capacity_row(capital, strict_result, "strict-trade-participation")
        )
    capacity_as_coded = pd.DataFrame(capacity_as_coded_rows)
    capacity_stress = pd.DataFrame(capacity_strict_rows)

    print("[5/8] measuring yearly, regime, rolling, and contribution concentration", flush=True)
    yearly = yearly_metrics(baseline.equity)
    rolling = rolling_three_year_metrics(baseline.equity)
    regimes = regime_metrics(baseline, data)
    contributions, concentration = asset_concentration(baseline, set(data.risk_symbols))
    top_risk = concentration.get("top_risk_symbols", [])
    exclusion_rows = []
    for count in (1, 3, 5):
        excluded = tuple(top_risk[:count])
        config = replace(
            baseline_config,
            name=f"exclude_top_{count}",
            excluded_risk_symbols=excluded,
        )
        result = run_simulation(data, cache, config, start, end)
        exclusion_rows.append(
            {
                "case": config.name,
                "excluded_count": len(excluded),
                "excluded_symbols": ";".join(excluded),
                **_result_row(result),
            }
        )
    exclusion_stress = pd.DataFrame(
        [
            {
                "case": "baseline",
                "excluded_count": 0,
                "excluded_symbols": "",
                **_result_row(baseline),
            },
            *exclusion_rows,
        ]
    )

    print("[6/8] running expanding-window and CSCV/PBO diagnostics", flush=True)
    dates = pd.DatetimeIndex(pd.to_datetime(baseline.equity["trade_date"]))
    walk_forward, walk_forward_equity, walk_forward_summary = expanding_walk_forward(
        return_matrix,
        dates,
        configs,
        baseline_returns,
    )
    pbo_splits, pbo_summary = compute_pbo(
        return_matrix,
        dates,
        [config.name for config in configs],
    )
    full_sample_sharpes = _sharpe_by_trial(return_matrix)
    best_index = int(np.nanargmax(full_sample_sharpes))
    dsr = {
        "frozen_baseline": deflated_sharpe_probability(baseline_returns, return_matrix),
        "full_sample_best": {
            "trial": configs[best_index].name,
            **_config_columns(configs[best_index]),
            **deflated_sharpe_probability(return_matrix[best_index], return_matrix),
        },
    }

    print("[7/8] assembling audit and result bundle", flush=True)
    overall_grid = {
        "trial_count": int(len(parameter_grid)),
        "positive_annualized_ratio": float(parameter_grid["annualized_return"].gt(0).mean()),
        "median_annualized_return": float(parameter_grid["annualized_return"].median()),
        "median_sharpe": float(parameter_grid["sharpe"].median()),
        "q25_sharpe": float(parameter_grid["sharpe"].quantile(0.25)),
        "q75_sharpe": float(parameter_grid["sharpe"].quantile(0.75)),
        "minimum_sharpe": float(parameter_grid["sharpe"].min()),
        "maximum_sharpe": float(parameter_grid["sharpe"].max()),
        "best_full_sample_trial": configs[best_index].name,
    }
    experiment_counts = {
        "ablation_runs": int(len(ablation)),
        "parameter_trials": int(len(parameter_grid)),
        "cost_runs": int(len(cost_stress)),
        "capacity_as_coded_runs": int(len(capacity_as_coded)),
        "capacity_strict_runs": int(len(capacity_stress)),
        "capacity_runs": int(len(capacity_as_coded) + len(capacity_stress)),
        "contribution_exclusion_runs": int(len(exclusion_stress)),
        "direct_backtest_rows_total": int(
            len(ablation)
            + len(parameter_grid)
            + len(cost_stress)
            + len(capacity_as_coded)
            + len(capacity_stress)
            + len(exclusion_stress)
        ),
        "pbo_cscv_splits": int(len(pbo_splits)),
        "walk_forward_test_years": int(len(walk_forward)),
    }
    audit = {
        **data.audit,
        "manifest_hashes": data.manifest_hashes,
        "original_download_sha256": ORIGINAL_DOWNLOAD_SHA256,
        "baseline_source_sha256": file_sha256(FAMILY_DIR / "baseline.py"),
        "baseline_validation": baseline_validation,
        "future_data_checks": {
            "all_observations_strictly_before_execution": True,
            "feature_precomputation_semantics": (
                "grouped shifts and rolling windows end on the observation date; execution "
                "occurs on the following trading-week first open"
            ),
        },
        "corporate_actions": (
            "Signals and marks use B-grade continuous adjusted prices. Raw ADV uses RMB amount. "
            "The local share ledger uses adjusted prices and therefore approximates lot/minimum "
            "commission effects around distributions rather than replaying every creation-unit event."
        ),
        "tracking_index_point_in_time": (
            "JoinQuant baseline queries FUND_INVEST_TARGET with pub_date/start/end filters. The "
            "local matrix lacks that historical table, so current tracking_target is used only "
            "for category and duplicate-index grouping and is explicitly non-PIT."
        ),
        "experiment_counts": experiment_counts,
    }
    return {
        "data": data,
        "baseline": baseline,
        "ablation": ablation,
        "parameter_grid": parameter_grid,
        "parameter_stability": stability,
        "cost_stress": cost_stress,
        "capacity_as_coded": capacity_as_coded,
        "capacity_stress": capacity_stress,
        "yearly": yearly,
        "rolling_three_year": rolling,
        "regimes": regimes,
        "contributions": contributions,
        "concentration": concentration,
        "exclusion_stress": exclusion_stress,
        "walk_forward": walk_forward,
        "walk_forward_equity": walk_forward_equity,
        "walk_forward_summary": walk_forward_summary,
        "pbo_splits": pbo_splits,
        "pbo_summary": pbo_summary,
        "dsr": dsr,
        "overall_grid": overall_grid,
        "audit": audit,
        "experiment_counts": experiment_counts,
        "start": start,
        "end": end,
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _pct(value: float | None) -> str:
    return "NA" if value is None or not np.isfinite(value) else f"{100 * value:.2f}%"


def _number(value: float | None, digits: int = 2) -> str:
    return "NA" if value is None or not np.isfinite(value) else f"{value:.{digits}f}"


def _markdown_table(
    frame: pd.DataFrame,
    columns: list[str],
    formatters: dict[str, callable] | None = None,
) -> str:
    formatters = formatters or {}
    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    rows = [header, divider]
    for _, record in frame[columns].iterrows():
        values = []
        for column in columns:
            value = record[column]
            formatter = formatters.get(column)
            if formatter is not None:
                value = formatter(value)
            values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def create_charts(bundle: dict, assets_dir: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    equity = bundle["baseline"].equity.copy()
    equity["trade_date"] = pd.to_datetime(equity["trade_date"])
    curve = equity["total_value"] / equity["total_value"].iloc[0]
    drawdown = curve / curve.cummax() - 1.0
    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].plot(equity["trade_date"], curve, color="#1f77b4", linewidth=1.6)
    axes[0].set_ylabel("Growth of 1")
    axes[0].set_title("Frozen baseline v1")
    axes[1].fill_between(equity["trade_date"], drawdown, 0, color="#d62728", alpha=0.65)
    axes[1].set_ylabel("Drawdown")
    axes[1].set_xlabel("Date")
    figure.tight_layout()
    figure.savefig(assets_dir / "baseline-equity-drawdown.png", dpi=160)
    plt.close(figure)

    yearly = bundle["yearly"]
    figure, axis = plt.subplots(figsize=(11, 4.5))
    colors = np.where(yearly["annualized_return"].ge(0), "#2ca02c", "#d62728")
    axis.bar(yearly["year"].astype(str), yearly["annualized_return"], color=colors)
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_title("Calendar-year return")
    axis.set_ylabel("Return")
    axis.tick_params(axis="x", rotation=45)
    figure.tight_layout()
    figure.savefig(assets_dir / "yearly-returns.png", dpi=160)
    plt.close(figure)

    ablation = bundle["ablation"]
    figure, axis = plt.subplots(figsize=(11, 5))
    positions = np.arange(len(ablation))
    axis.bar(positions - 0.18, ablation["annualized_return"], 0.36, label="CAGR")
    axis.bar(positions + 0.18, ablation["sharpe"] / 5.0, 0.36, label="Sharpe / 5")
    axis.set_xticks(positions, ablation["model"], rotation=35, ha="right")
    axis.set_title("Incremental module ablation")
    axis.legend()
    figure.tight_layout()
    figure.savefig(assets_dir / "module-ablation.png", dpi=160)
    plt.close(figure)

    grid = bundle["parameter_grid"]
    pivot = grid.pivot_table(
        index="lookbacks", columns="top_k", values="sharpe", aggfunc="median"
    ).sort_index()
    figure, axis = plt.subplots(figsize=(7, 4.5))
    image = axis.imshow(pivot.to_numpy(), cmap="viridis", aspect="auto")
    axis.set_xticks(np.arange(len(pivot.columns)), pivot.columns)
    axis.set_yticks(np.arange(len(pivot.index)), pivot.index)
    axis.set_xlabel("Top K")
    axis.set_ylabel("Lookbacks (trading days)")
    axis.set_title("Median Sharpe marginalized over other parameters")
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
    figure.colorbar(image, ax=axis, label="Median Sharpe")
    figure.tight_layout()
    figure.savefig(assets_dir / "parameter-plateau.png", dpi=160)
    plt.close(figure)

    costs = bundle["cost_stress"]
    capacity = bundle["capacity_stress"]
    capacity_as_coded = bundle["capacity_as_coded"]
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].plot(
        costs["single_side_total_cost_bp"],
        costs["annualized_return"],
        marker="o",
    )
    axes[0].set_xlabel("Single-side all-in cost (bp)")
    axes[0].set_ylabel("CAGR")
    axes[0].set_title("Cost pressure")
    axes[1].plot(
        capacity_as_coded["capital"] / 1_000_000,
        capacity_as_coded["annualized_return"],
        marker="o",
        label="target holding cap only",
    )
    axes[1].plot(
        capacity["capital"] / 1_000_000,
        capacity["annualized_return"],
        marker="o",
        label="strict trade participation",
    )
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Initial capital (RMB mn, log scale)")
    axes[1].set_ylabel("CAGR")
    axes[1].set_title("Capacity pressure at 0.5% ADV cap")
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(assets_dir / "cost-capacity-pressure.png", dpi=160)
    plt.close(figure)

    contribution = bundle["contributions"].head(12).sort_values("net_pnl")
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.barh(contribution["symbol"], contribution["net_pnl"])
    axis.set_xlabel("Net P&L contribution (RMB)")
    axis.set_title("Top ETF contribution")
    figure.tight_layout()
    figure.savefig(assets_dir / "contribution-concentration.png", dpi=160)
    plt.close(figure)


def build_report(bundle: dict, run_id: str) -> str:
    baseline = bundle["baseline"].metrics
    yearly = bundle["yearly"]
    grid = bundle["overall_grid"]
    pbo = bundle["pbo_summary"]
    concentration = bundle["concentration"]
    cost_30 = (
        bundle["cost_stress"].loc[bundle["cost_stress"]["single_side_total_cost_bp"].eq(30)].iloc[0]
    )
    capacity_50 = (
        bundle["capacity_stress"].loc[bundle["capacity_stress"]["capital"].eq(50_000_000)].iloc[0]
    )
    capacity_as_coded_50 = (
        bundle["capacity_as_coded"]
        .loc[bundle["capacity_as_coded"]["capital"].eq(50_000_000)]
        .iloc[0]
    )
    exclude_top1 = (
        bundle["exclusion_stress"]
        .loc[bundle["exclusion_stress"]["case"].eq("exclude_top_1")]
        .iloc[0]
    )
    negative_years = yearly.loc[yearly["annualized_return"].lt(0), "year"].tolist()
    ablation = bundle["ablation"].copy()
    ablation["delta_cagr"] = ablation["annualized_return"].diff()
    ablation["delta_sharpe"] = ablation["sharpe"].diff()
    counts = bundle["experiment_counts"]
    tracking_limit = bundle["audit"]["tracking_index_point_in_time"]
    baseline_dsr = bundle["dsr"]["frozen_baseline"]["deflated_sharpe_probability"]
    best_dsr = bundle["dsr"]["full_sample_best"]["deflated_sharpe_probability"]
    walk_forward = bundle["walk_forward_summary"]
    strict_capacity_pass = (
        capacity_50["maximum_trade_adv_participation"] <= 0.005 + 1e-12
        and capacity_50["risk_trade_count_above_0_5pct_adv"] == 0
        and capacity_50["position_days_outside_lifecycle"] == 0
    )
    practical = (
        "严格成交参与率约束可执行，但 5,000 万元时平均风险权重过低，主要变成防御仓"
        if strict_capacity_pass and capacity_50["average_risk_weight"] < 0.25
        else "严格容量场景仍存在参与率/生命周期违规或非正收益，不能视为可扩容方案"
        if (not strict_capacity_pass or capacity_50["annualized_return"] <= 0)
        else "严格容量场景保留了足够风险敞口与正收益"
    )
    plateau = (
        "形成收益为正、但风险调整收益偏低的较宽平台"
        if grid["positive_annualized_ratio"] >= 0.80 and grid["q25_sharpe"] > 0
        else "没有形成覆盖大多数参数的正 Sharpe 高原"
    )
    recommendation = (
        "不建议直接实盘：冻结 baseline 的 Sharpe 不足 0.5，PBO 超过 50%，"
        "DSR 也未达到常用的 95% 置信门槛。"
        if baseline["sharpe"] < 0.5 and pbo["pbo"] >= 0.5 and baseline_dsr < 0.95
        else "可以继续模拟盘验证，但仍不能把全样本结果视为前瞻证据。"
    )
    ablation_table = _markdown_table(
        ablation,
        [
            "model",
            "annualized_return",
            "maximum_drawdown",
            "sharpe",
            "annualized_turnover",
            "delta_cagr",
            "delta_sharpe",
        ],
        {
            "annualized_return": _pct,
            "maximum_drawdown": _pct,
            "sharpe": _number,
            "annualized_turnover": _number,
            "delta_cagr": _pct,
            "delta_sharpe": _number,
        },
    )
    yearly_table = _markdown_table(
        yearly,
        ["year", "annualized_return", "maximum_drawdown", "sharpe", "annualized_turnover"],
        {
            "year": lambda value: str(int(value)),
            "annualized_return": _pct,
            "maximum_drawdown": _pct,
            "sharpe": _number,
            "annualized_turnover": _number,
        },
    )
    cost_table = _markdown_table(
        bundle["cost_stress"],
        [
            "single_side_total_cost_bp",
            "annualized_return",
            "maximum_drawdown",
            "sharpe",
            "annualized_turnover",
        ],
        {
            "annualized_return": _pct,
            "maximum_drawdown": _pct,
            "sharpe": _number,
            "annualized_turnover": _number,
        },
    )
    capacity_as_coded_table = _markdown_table(
        bundle["capacity_as_coded"],
        [
            "capital",
            "annualized_return",
            "sharpe",
            "average_risk_weight",
            "maximum_trade_adv_participation",
            "risk_trade_count_above_0_5pct_adv",
            "position_days_outside_lifecycle",
        ],
        {
            "capital": lambda value: f"{int(value):,}",
            "annualized_return": _pct,
            "sharpe": _number,
            "average_risk_weight": _pct,
            "maximum_trade_adv_participation": _pct,
            "risk_trade_count_above_0_5pct_adv": lambda value: str(int(value)),
            "position_days_outside_lifecycle": lambda value: str(int(value)),
        },
    )
    capacity_table = _markdown_table(
        bundle["capacity_stress"],
        [
            "capital",
            "annualized_return",
            "maximum_drawdown",
            "sharpe",
            "average_risk_weight",
            "maximum_trade_adv_participation",
            "risk_trade_count_above_0_5pct_adv",
            "position_days_outside_lifecycle",
        ],
        {
            "capital": lambda value: f"{int(value):,}",
            "annualized_return": _pct,
            "maximum_drawdown": _pct,
            "sharpe": _number,
            "average_risk_weight": _pct,
            "maximum_trade_adv_participation": _pct,
            "risk_trade_count_above_0_5pct_adv": lambda value: str(int(value)),
            "position_days_outside_lifecycle": lambda value: str(int(value)),
        },
    )
    regime_table = _markdown_table(
        bundle["regimes"],
        ["regime", "trading_days", "annualized_return", "maximum_drawdown", "sharpe"],
        {
            "annualized_return": _pct,
            "maximum_drawdown": _pct,
            "sharpe": _number,
        },
    )
    exclusion_table = _markdown_table(
        bundle["exclusion_stress"],
        ["case", "excluded_symbols", "annualized_return", "maximum_drawdown", "sharpe"],
        {
            "annualized_return": _pct,
            "maximum_drawdown": _pct,
            "sharpe": _number,
        },
    )
    return f"""# ETF Core Rotation v1 完整研究矩阵

## 结论先行

本报告冻结 v1 后再做诊断，没有用同一全样本的冠军参数替换 baseline。研究区间为 {bundle["start"]} 至 {bundle["end"]}，运行标识 `{run_id}`。

- **总体判断：{recommendation}**
- baseline：年化 {_pct(baseline["annualized_return"])}，最大回撤 {_pct(baseline["maximum_drawdown"])}，Sharpe {_number(baseline["sharpe"])}，年化单边换手 {_number(baseline["annualized_turnover"])} 倍，最差滚动三年收益 {_pct(baseline["worst_rolling_three_year_return"])}。
- 参数稳定性：{counts["parameter_trials"]:,} 组全因子参数中，正年化占 {_pct(grid["positive_annualized_ratio"])}，Sharpe 中位数 {_number(grid["median_sharpe"])}，四分位区间 {_number(grid["q25_sharpe"])}—{_number(grid["q75_sharpe"])}；据此判断为“{plateau}”。
- 成本与容量：30bp 单边总成本下年化 {_pct(cost_30["annualized_return"])}、Sharpe {_number(cost_30["sharpe"])}；严格限制每次风险交易不超过 ADV20 的 0.5% 后，5,000 万元场景年化 {_pct(capacity_50["annualized_return"])}、平均风险权重 {_pct(capacity_50["average_risk_weight"])}。综合判断：{practical}。
- 过拟合诊断：PBO {_pct(pbo["pbo"])}；冻结 baseline / 全样本最佳组合的 DSR 概率分别为 {_pct(baseline_dsr)}/{_pct(best_dsr)}。二者都不足以支持“历史冠军可稳定外推”。
- 集中度：风险 ETF 正贡献 Top1/Top3 占比分别为 {_pct(concentration.get("top1_positive_contribution_share"))}/{_pct(concentration.get("top3_positive_contribution_share"))}；删除第一贡献 ETF 后年化 {_pct(exclude_top1["annualized_return"])}、Sharpe {_number(exclude_top1["sharpe"])}。
- 时间集中：负收益年份为 {negative_years or "无"}。滚动三年、逐年和牛熊震荡条件结果均保存在 `raw/`，不能用全样本平均掩盖阶段性失效。
- 数据底线：上市/退市、价格、ADV 和信号日期均按观察日处理；但本地跟踪指数档案不是历史 PIT。该限制足以阻止本报告宣称“本地严格复现了聚宽动态跟踪指数池”。

## baseline 与正确性验证

下载原件 SHA-256：`{ORIGINAL_DOWNLOAD_SHA256}`。仓库 baseline 只修复 `jqdata` 内建函数覆盖和惰性行情加载，不改变投资逻辑。信号使用上周最后交易日收盘，下一交易周首个开盘成交；所有 {bundle["audit"]["baseline_validation"]["causal_decision_count"]} 次决策均满足观察日早于执行日，生命周期违规为 {bundle["audit"]["baseline_validation"]["lifecycle_violations"]}，逐日 P&L 最大未归因误差为 {bundle["audit"]["baseline_validation"]["maximum_absolute_unattributed_pnl"]:.3g} 元。

本地开盘是聚宽周一 10:30 的日频代理，不是分钟级复刻。baseline 成本为单边约 10bp 滑点、万三佣金和 5 元最低佣金。

## 模块消融

每一行只在上一行基础上增加一个模块。TopK 阶段为 3 只等权并启用 40% 单资产上限；3% 权重漂移带和 2,000 元最小交易额属于冻结执行口径，不另行调参。

{ablation_table}

“边际贡献”应同时看年化、回撤、Sharpe 与换手；某层提高收益但恶化回撤，不能简单标成有效。完整数值是事实，是否保留该层仍是研究判断。

本次逐层结果中，**波动率目标**是最大且最清晰的风险收益改善；**相关性约束**也带来正的 Sharpe 增量。**rank buffer**把年化换手从约 25.5 倍降到 17.4 倍，但小幅牺牲收益和 Sharpe。绝对动量在单资产阶段反而恶化结果，逆波动率的边际接近零；它们不能单独称为稳定贡献。原容量层降低回撤，却同时降低收益，而且没有真正限制强制退出的成交参与率。

## 参数稳定性矩阵

全因子笛卡尔积为 TopK 4 档 × 周期 3 组 × 相关阈值 3 档 × 目标波动 4 档 × ADV 门槛 3 档 × rank buffer 3 档，共 {counts["parameter_trials"]:,} 次。完整结果在 `raw/parameter-grid.csv`，边际汇总在 `raw/parameter-stability.csv`，没有只保存最优值。

整体 Sharpe 最低/最高为 {_number(grid["minimum_sharpe"])}/{_number(grid["maximum_sharpe"])}。`assets/parameter-plateau.png` 仅展示对其他维度取中位数后的周期×TopK 截面，不能代替完整 CSV。

所有参数都为正年化不等于所有动量参数都有效：每组都共享防御 ETF 袖套、波动率目标与容量缩放，宽平台的一部分来自这些共同风险覆盖层。3/6/12 月组合的边际 Sharpe 中位数低于 2/4/8 月，但本报告不会据此把较短周期提升为 baseline。

## 成本压力

{cost_table}

这里的 5/10/20/30bp 是每次买入或卖出的单边总比例成本，不叠加最低佣金，便于精确压力比较；baseline 精确成本单独保留。

## 容量压力

原代码口径（只限制目标持仓，不限制成交）：

{capacity_as_coded_table}

该实现的最大风险 trade/ADV 达到 {_pct(capacity_as_coded_50["maximum_trade_adv_participation"])}，明显超过声明的 0.5%。因此下面另做严格部分成交：每次调仓的每只风险 ETF 买卖额都不得超过滞后 ADV20 的 0.5%，未完成的退出仓位继续保留，等待后续调仓。

严格成交参与率口径：

{capacity_table}

防御 ETF 不受风险池容量上限约束。严格口径能消除参与率违规，但资金越大，风险资产权重越低，结果逐渐变成以国债/货币 ETF 为主的组合；不能拿仍为正的低波动防御收益证明动量腿具备 5,000 万容量。

## 年份、市场状态与滚动三年

{yearly_table}

牛/熊/震荡是只用于归因的因果标签：用前一日可见的沪深300 ETF 252 日收益，大于 +10% 为牛、小于 -10% 为熊，其余为震荡，不参与交易。

{regime_table}

## ETF 贡献集中与删除实验

{exclusion_table}

删除实验会从历史风险池移除 Top1/Top3/Top5 后重新排名和回测，不是从最终收益中机械扣除贡献，因此可以观察替代 ETF 是否接管信号。

## Walk-forward、PBO 与 Deflated Sharpe

expanding-window 从 2019 年起，每年只用此前历史，在 {counts["parameter_trials"]:,} 个预定义网格中选取 IS Sharpe 最高者，下一自然年整年 OOS；选择记录与拼接净值在 `raw/walk-forward-*.csv`。这是一项“参数选择流程压力测试”，不是把其冠军提升为 baseline。

2019—2026 拼接 OOS 中，逐年选择模型年化 {_pct(walk_forward["selected_model"]["annualized_return"])}、最大回撤 {_pct(walk_forward["selected_model"]["maximum_drawdown"])}、Sharpe {_number(walk_forward["selected_model"]["sharpe"])}；同日期冻结 baseline 分别为 {_pct(walk_forward["frozen_baseline_same_oos_dates"]["annualized_return"])}、{_pct(walk_forward["frozen_baseline_same_oos_dates"]["maximum_drawdown"])}、{_number(walk_forward["frozen_baseline_same_oos_dates"]["sharpe"])}。参数选择提高了收益与 Sharpe，但把最大回撤扩大到约 46%，并未形成压倒性的样本外改进。

同一 {counts["parameter_trials"]:,} 次参数试验用于 CSCV 近似：8 个连续块、全部 70 个半样本组合，PBO 为 {_pct(pbo["pbo"])}，被选冠军的 OOS 排名中位数为 {_pct(pbo["median_selected_oos_percentile"])}。DSR 同时报告冻结 baseline 与全样本最佳组合；由于网格试验高度相关，独立试验假设并不精确，所以只把它当过拟合警报，不当显著性证明。

## 与五福的结构性对照

| 维度 | Core Rotation v1 | 五福（仅结构） |
|---|---|---|
| 核心信号 | 3/6/12 月横截面百分位集成 | 较短周期动量与多项健康/例外过滤 |
| 市场状态 | 无人工牛熊状态机 | A 股强弱状态切换 |
| 组合 | TopK、逆波动率、目标波动 | 通常单仓赢家通吃 |
| 换手控制 | 周频、rank buffer、权重漂移带 | 持仓强度判断与日内执行 |
| 容量 | ADV 门槛和目标持仓上限 | 以候选流动性过滤为主 |

本研究没有借用五福历史最优参数，也没有因错过某段行情增加例外规则。

## 数据偏差与不能越过的结论

- ETF 日线、累计分红连续调整与成功生命周期为 B 级；免费源没有权威完整公司行动因子。份额与最低佣金围绕分红/折算是近似撮合。
- 历史池包含退市 ETF，并按 `listing_date <= observation <= delisting_date` 过滤，避免明显幸存者偏差。
- 本地 `tracking_target` 来自当前基金档案，无 `effective_from/effective_to`。具体说明：{tracking_limit}
- 聚宽版 `FUND_INVEST_TARGET` 使用 `pub_date/start_date/end_date` 查询，正式平台复核时应重点比较每期候选池与同指数去重结果。
- 价格信号只用观察日及以前数据，下一交易日开盘执行；没有用当日收盘决定当日成交。
- 本报告所有参数稳定性、PBO 和删除实验均在 2014—2026 可见历史上完成，仍不是发布后的真实前瞻业绩。

## 归档清单

- `source.py`：冻结后的聚宽 baseline；`engine.py`：本地实验引擎。
- `raw/`：baseline 净值/交易/持仓/决策、逐年、滚动三年、市场状态、消融、完整参数网格、成本、容量、贡献、删除、walk-forward、PBO。
- `assets/`：净值回撤、逐年、消融、参数高原、成本容量、贡献图。
- `audit.json`、`pbo-dsr.json`、`manifest.json`：数据哈希、偏差声明、试验次数与机器可读指标。
"""


def write_results(bundle: dict, target: Path, run_id: str) -> Path:
    if target.exists():
        raise FileExistsError(f"result directory already exists: {target}")
    raw = target / "raw"
    assets = target / "assets"
    raw.mkdir(parents=True)
    assets.mkdir(parents=True)
    baseline = bundle["baseline"]
    frames = {
        "baseline-equity.csv": baseline.equity,
        "baseline-trades.csv": baseline.trades,
        "baseline-positions.csv": baseline.positions,
        "baseline-decisions.csv": baseline.decisions,
        "baseline-contributions-daily.csv": baseline.contributions,
        "yearly.csv": bundle["yearly"],
        "rolling-three-year.csv": bundle["rolling_three_year"],
        "regime-metrics.csv": bundle["regimes"],
        "module-ablation.csv": bundle["ablation"],
        "parameter-grid.csv": bundle["parameter_grid"],
        "parameter-stability.csv": bundle["parameter_stability"],
        "cost-stress.csv": bundle["cost_stress"],
        "capacity-as-coded.csv": bundle["capacity_as_coded"],
        "capacity-stress.csv": bundle["capacity_stress"],
        "asset-contributions.csv": bundle["contributions"],
        "top-contributor-exclusion.csv": bundle["exclusion_stress"],
        "walk-forward-selections.csv": bundle["walk_forward"],
        "walk-forward-equity.csv": bundle["walk_forward_equity"],
        "pbo-splits.csv": bundle["pbo_splits"],
    }
    for name, frame in frames.items():
        frame.to_csv(raw / name, index=False, encoding="utf-8-sig")
    create_charts(bundle, assets)
    source_path = target / "source.py"
    engine_path = target / "engine.py"
    shutil.copy2(FAMILY_DIR / "baseline.py", source_path)
    shutil.copy2(FAMILY_DIR / "local_backtest.py", engine_path)
    (target / "config.json").write_text(
        json.dumps(_json_safe(asdict(StrategyConfig())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json_payloads = {
        "audit.json": bundle["audit"],
        "pbo-dsr.json": {
            "pbo": bundle["pbo_summary"],
            "deflated_sharpe": bundle["dsr"],
        },
        "walk-forward-summary.json": bundle["walk_forward_summary"],
        "results-summary.json": {
            "baseline": baseline.metrics,
            "parameter_grid": bundle["overall_grid"],
            "concentration": bundle["concentration"],
            "experiment_counts": bundle["experiment_counts"],
        },
    }
    for name, payload in json_payloads.items():
        (target / name).write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report = build_report(bundle, run_id)
    (target / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "platform": "local-daily-causal-replay",
        "strategy_family": "etf-core-rotation",
        "variant": "baseline-research-matrix",
        "run_id": run_id,
        "start_date": bundle["start"],
        "end_date": bundle["end"],
        "benchmark": "000300.XSHG / local proxy SH510300",
        "costs": {
            "baseline_slippage_single_side": 0.001,
            "commission_single_side": 0.0003,
            "minimum_commission_rmb": 5.0,
            "fund_tax": 0.0,
        },
        "metrics": _json_safe(baseline.metrics),
        "source_sha256": file_sha256(source_path),
        "engine_sha256": file_sha256(engine_path),
        "original_download_sha256": ORIGINAL_DOWNLOAD_SHA256,
        "data_manifest_sha256": bundle["data"].manifest_hashes,
        "experiment_counts": bundle["experiment_counts"],
        "limitations": [
            "Local execution is next-trading-day open, a daily proxy for JoinQuant 10:30.",
            "Current static tracking_target is not a strict historical PIT classification.",
            "B-grade adjusted ETF data approximates share lots around corporate actions.",
            "All robustness tests still use the same 2014-2026 historical record.",
        ],
    }
    (target / "manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("[8/8] results written to", target, flush=True)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--run-id", default="local-etf-2014-2026-v1")
    parser.add_argument("--archived-at", default="2026-08-15")
    parser.add_argument("--output-dir")
    parser.add_argument("--archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.archive and args.output_dir:
        raise ValueError("use either --archive or --output-dir, not both")
    if args.archive:
        target = (
            FAMILY_DIR
            / "backtests"
            / f"{args.archived_at}__baseline-research-matrix__{args.run_id}"
        )
    elif args.output_dir:
        target = Path(args.output_dir).resolve()
    else:
        raise ValueError("specify --archive or --output-dir")
    bundle = run_experiment_suite(args.data_root, args.start, args.end)
    write_results(bundle, target, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
