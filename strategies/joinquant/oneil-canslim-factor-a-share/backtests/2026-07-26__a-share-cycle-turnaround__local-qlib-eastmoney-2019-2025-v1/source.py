"""欧奈尔/CANSLIM 券商月频因子版本的本地 Qlib 回测器。

本模块用于比较公开研报口径与透明的可得数据代理。信号只使用观察日已经公告的
财务报告和观察日收盘前的行情，并在下一交易日开盘执行。机构持仓、分析师一致
预期和历史行业分类缺失时保持缺失，不用价量指标冒充。
"""

import hashlib
import importlib.util
import json
import math
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = STRATEGY_DIR.parents[2]
COMMON_ENGINE_PATH = (
    STRATEGY_DIR.parent / "ktv-macd-resonance" / "local_backtest.py"
)
FINANCIAL_ENGINE_PATH = (
    STRATEGY_DIR.parent / "oneil-canslim-a-share" / "local_backtest.py"
)
DEFAULT_MARKETS = ("csi300", "csi500")
SUPPORTED_MODELS = (
    "growth-new-high-simple",
    "huachuang-2019-available",
    "huachuang-2-lite",
    "shenwan-2018-lite",
    "a-share-adaptive",
    "a-share-cycle-turnaround",
)
MODEL_DESCRIPTIONS = {
    "growth-new-high-simple": (
        "季度利润和营收增长均不低于20%，位于52周高点10%以内；"
        "用于检验复杂规则是否优于朴素成长动量。"
    ),
    "huachuang-2019-available": (
        "华创2019可得数据复刻：季度EPS>=18%、营收>=25%、"
        "五年利润CAGR>=15%且逐年增长、52周新高附近、RPS>=80；"
        "缺失的机构/外资条件不做替代。"
    ),
    "huachuang-2-lite": (
        "华创CANSLIM 2.0轻量复刻：季度利润增速和9-1动量均取"
        "横截面前20%，选择综合得分前30；缺失基金基础池、业绩"
        "预告快报和一致预期。"
    ),
    "shenwan-2018-lite": (
        "申万2018轻量复刻：基底代理、RPS前2/3、营收增速前1/3，"
        "沪深300跌破250日均线时降至50%仓位；缺失机构持股增长。"
    ),
    "a-share-adaptive": (
        "A股自适应版：取消五年逐年增长硬门槛，以当季利润或EPS增长、"
        "营收增长、9-1动量和高位验证组合选股；弱市只降仓，不清仓。"
    ),
    "a-share-cycle-turnaround": (
        "A股周期反转版：把负利润转正单独定义为盈利拐点，不计算失真的同比；"
        "要求当季盈利、营收增长、9-1动量和高位验证，弱市只降仓。"
    ),
}


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    if spec is None or spec.loader is None:
        raise ImportError("无法加载模块：{}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_common_engine():
    return _load_module("oneil_factor_common_engine", COMMON_ENGINE_PATH)


def load_financial_engine():
    return _load_module("oneil_factor_financial_engine", FINANCIAL_ENGINE_PATH)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_growth(current, base):
    try:
        current = float(current)
        base = float(base)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(current) or not np.isfinite(base) or base <= 0.0:
        return np.nan
    return current / base - 1.0


def turnaround_strength(current, base):
    """为横截面排序识别亏损转盈利，不把它伪装成普通同比百分比。"""
    try:
        current = float(current)
        base = float(base)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(current) or not np.isfinite(base) or current <= 0.0:
        return np.nan
    if base <= 0.0:
        return 4.0
    return min(current / base - 1.0, 4.0)


def _numeric(frame, column):
    if frame is None or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def latest_quarter_growths(quarterly):
    result = {
        "report_date": pd.NaT,
        "eps_current": np.nan,
        "eps_prior": np.nan,
        "profit_current": np.nan,
        "profit_prior": np.nan,
        "revenue_current": np.nan,
        "revenue_prior": np.nan,
        "eps_growth": np.nan,
        "profit_growth": np.nan,
        "revenue_growth": np.nan,
    }
    if quarterly is None or quarterly.empty or "statDate" not in quarterly:
        return result
    frame = quarterly.copy()
    frame["statDate"] = pd.to_datetime(frame["statDate"], errors="coerce")
    frame = (
        frame.dropna(subset=["statDate"])
        .sort_values("statDate")
        .drop_duplicates("statDate", keep="last")
    )
    if frame.empty:
        return result
    latest = frame.iloc[-1]
    latest_date = pd.Timestamp(latest["statDate"])
    prior_date = latest_date - pd.DateOffset(years=1)
    prior = frame.loc[frame["statDate"].eq(prior_date)]
    result["report_date"] = latest_date
    if prior.empty:
        return result
    prior = prior.iloc[-1]
    mappings = (
        ("basic_eps", "eps_growth", "eps_current", "eps_prior"),
        (
            "np_parent_company_owners",
            "profit_growth",
            "profit_current",
            "profit_prior",
        ),
        (
            "total_operating_revenue",
            "revenue_growth",
            "revenue_current",
            "revenue_prior",
        ),
    )
    for column, output, current_output, prior_output in mappings:
        result[current_output] = latest.get(column, np.nan)
        result[prior_output] = prior.get(column, np.nan)
        result[output] = safe_growth(latest.get(column), prior.get(column))
    return result


def annual_growth_path(annual):
    result = {
        "years": 0,
        "cagr": np.nan,
        "all_positive_growth": False,
    }
    if annual is None or annual.empty or "statDate" not in annual:
        return result
    frame = annual.copy()
    frame["statDate"] = pd.to_datetime(frame["statDate"], errors="coerce")
    frame["profit"] = _numeric(frame, "np_parent_company_owners")
    frame = (
        frame.dropna(subset=["statDate", "profit"])
        .sort_values("statDate")
        .drop_duplicates("statDate", keep="last")
        .tail(5)
    )
    result["years"] = int(len(frame))
    if len(frame) < 5:
        return result
    values = frame["profit"].to_numpy(dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        return result
    result["cagr"] = float((values[-1] / values[0]) ** (1.0 / 4.0) - 1.0)
    result["all_positive_growth"] = bool(np.all(np.diff(values) > 0.0))
    return result


def nine_one_momentum(closes):
    values = pd.to_numeric(pd.Series(closes), errors="coerce").dropna()
    if len(values) < 211:
        return np.nan
    return safe_growth(values.iloc[-22], values.iloc[-211])


def percentile_rank(values):
    numeric = pd.to_numeric(values, errors="coerce")
    if len(numeric) == 0:
        return numeric.astype(float)
    return numeric.rank(method="max") / float(len(numeric)) * 100.0


def price_features(frame):
    empty = {
        "momentum_9_1": np.nan,
        "return_12m": np.nan,
        "high_proximity": np.nan,
        "base_depth": np.nan,
        "base_ready": False,
        "average_money_20d": np.nan,
        "liquid": False,
    }
    if frame is None or frame.empty or "close" not in frame:
        return empty
    ordered = frame.sort_index()
    close = pd.to_numeric(ordered["close"], errors="coerce").dropna()
    if len(close) < 211:
        return empty
    current = float(close.iloc[-1])
    one_year = close.tail(252)
    reference_high = float(one_year.max())
    high_proximity = (
        current / reference_high
        if np.isfinite(reference_high) and reference_high > 0.0
        else np.nan
    )
    base = close.tail(65)
    base_high = float(base.max())
    base_low = float(base.min())
    base_depth = (
        1.0 - base_low / base_high
        if np.isfinite(base_high) and base_high > 0.0
        else np.nan
    )
    money = pd.to_numeric(
        ordered.get("money", pd.Series(index=ordered.index, dtype=float)),
        errors="coerce",
    )
    average_money = float(money.tail(20).mean()) if money.notna().any() else np.nan
    return {
        "momentum_9_1": nine_one_momentum(close),
        "return_12m": (
            safe_growth(close.iloc[-1], close.iloc[-252])
            if len(close) >= 252
            else np.nan
        ),
        "high_proximity": high_proximity,
        "base_depth": base_depth,
        "base_ready": bool(
            np.isfinite(high_proximity)
            and high_proximity >= 0.85
            and np.isfinite(base_depth)
            and 0.05 <= base_depth <= 0.35
        ),
        "average_money_20d": average_money,
        "liquid": bool(np.isfinite(average_money) and average_money >= 50_000_000.0),
    }


def _score(frame, weights):
    score = pd.Series(0.0, index=frame.index)
    for column, weight in weights.items():
        values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        score = score + values * float(weight)
    return score


def select_candidates(features, model):
    model = str(model).strip().lower()
    if model not in SUPPORTED_MODELS:
        raise ValueError("不支持的模型：{}".format(model))
    if features is None or features.empty:
        return pd.DataFrame(columns=[] if features is None else features.columns)
    frame = features.copy()
    truth = pd.Series(True, index=frame.index)
    liquid = frame.get("liquid", truth).fillna(False).astype(bool)

    if model == "growth-new-high-simple":
        mask = (
            liquid
            & pd.to_numeric(frame["profit_growth"], errors="coerce").ge(0.20)
            & pd.to_numeric(frame["revenue_growth"], errors="coerce").ge(0.20)
            & pd.to_numeric(frame["high_proximity"], errors="coerce").ge(0.90)
        )
        frame["score"] = _score(
            frame,
            {
                "growth_percentile": 0.45,
                "revenue_percentile": 0.25,
                "rps": 0.30,
            },
        )
    elif model == "huachuang-2019-available":
        mask = (
            liquid
            & pd.to_numeric(frame["eps_growth"], errors="coerce").ge(0.18)
            & pd.to_numeric(frame["revenue_growth"], errors="coerce").ge(0.25)
            & pd.to_numeric(frame["annual_cagr"], errors="coerce").ge(0.15)
            & frame["annual_positive_path"].fillna(False).astype(bool)
            & pd.to_numeric(frame["rps"], errors="coerce").ge(80.0)
            & pd.to_numeric(frame["high_proximity"], errors="coerce").ge(0.95)
        )
        frame["score"] = _score(
            frame,
            {
                "rps": 0.40,
                "growth_percentile": 0.30,
                "revenue_percentile": 0.30,
            },
        )
    elif model == "huachuang-2-lite":
        mask = (
            liquid
            & pd.to_numeric(frame["growth_percentile"], errors="coerce").ge(80.0)
            & pd.to_numeric(frame["momentum_percentile"], errors="coerce").ge(80.0)
        )
        frame["score"] = _score(
            frame,
            {"growth_percentile": 0.50, "momentum_percentile": 0.50},
        )
    elif model == "shenwan-2018-lite":
        mask = (
            liquid
            & frame["base_ready"].fillna(False).astype(bool)
            & pd.to_numeric(frame["momentum_percentile"], errors="coerce").ge(
                100.0 / 3.0
            )
            & pd.to_numeric(frame["revenue_percentile"], errors="coerce").ge(
                200.0 / 3.0
            )
        )
        frame["score"] = _score(
            frame,
            {"momentum_percentile": 0.50, "revenue_percentile": 0.50},
        )
    elif model == "a-share-adaptive":
        profit_or_eps = (
            pd.to_numeric(frame["profit_growth"], errors="coerce").ge(0.20)
            | pd.to_numeric(frame["eps_growth"], errors="coerce").ge(0.20)
        )
        mask = (
            liquid
            & profit_or_eps
            & pd.to_numeric(frame["revenue_growth"], errors="coerce").ge(0.15)
            & pd.to_numeric(frame["momentum_percentile"], errors="coerce").ge(70.0)
            & pd.to_numeric(frame["high_proximity"], errors="coerce").ge(0.85)
        )
        frame["score"] = _score(
            frame,
            {
                "growth_percentile": 0.35,
                "revenue_percentile": 0.20,
                "momentum_percentile": 0.35,
                "rps": 0.10,
            },
        )
    else:
        mask = (
            liquid
            & pd.to_numeric(frame["profit_current"], errors="coerce").gt(0.0)
            & pd.to_numeric(
                frame["turnaround_percentile"], errors="coerce"
            ).ge(80.0)
            & pd.to_numeric(frame["revenue_growth"], errors="coerce").ge(0.15)
            & pd.to_numeric(frame["momentum_percentile"], errors="coerce").ge(70.0)
            & pd.to_numeric(frame["high_proximity"], errors="coerce").ge(0.80)
        )
        frame["score"] = _score(
            frame,
            {
                "turnaround_percentile": 0.40,
                "revenue_percentile": 0.20,
                "momentum_percentile": 0.30,
                "rps": 0.10,
            },
        )
    selected = frame.loc[mask].copy()
    selected.index.name = None
    return selected.sort_values(
        ["score", "symbol"], ascending=[False, True]
    )


def market_exposure(benchmark_closes, model):
    model = str(model).strip().lower()
    closes = pd.to_numeric(pd.Series(benchmark_closes), errors="coerce").dropna()
    if model not in {
        "shenwan-2018-lite",
        "a-share-adaptive",
        "a-share-cycle-turnaround",
    }:
        return 1.0
    lookback = 250 if model == "shenwan-2018-lite" else 200
    if len(closes) < lookback:
        return 0.5
    average = float(closes.tail(lookback).mean())
    if float(closes.iloc[-1]) < average:
        return 0.5
    return 1.0 if model == "shenwan-2018-lite" else 0.95


def monthly_rebalance_dates(trade_dates):
    dates = pd.DatetimeIndex(trade_dates)
    if dates.empty:
        return set()
    periods = dates.to_period("M")
    return {dates[periods == period][0] for period in periods.unique()}


def max_positions_for_model(model):
    return 30 if model == "huachuang-2-lite" else 20


@dataclass
class BacktestConfig:
    start_date: pd.Timestamp | str = "2019-01-01"
    end_date: pd.Timestamp | str = "2025-12-31"
    model: str = "huachuang-2019-available"
    initial_cash: float = 1_000_000.0
    markets: tuple[str, ...] = DEFAULT_MARKETS
    benchmark_symbol: str = "SZ399300"
    board_lot: int = 100
    commission_rate: float = 0.0013
    minimum_commission: float = 0.0
    sell_tax_rate: float = 0.0
    fixed_slippage_per_share: float = 0.002
    min_listing_days: int = 250
    verbose: bool = False

    def __post_init__(self):
        self.start_date = pd.Timestamp(self.start_date).normalize()
        self.end_date = pd.Timestamp(self.end_date).normalize()
        self.model = str(self.model).strip().lower()
        self.markets = tuple(self.markets)
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be later than end_date")
        if self.model not in SUPPORTED_MODELS:
            raise ValueError("不支持的模型：{}".format(self.model))
        if self.initial_cash <= 0.0 or self.board_lot <= 0:
            raise ValueError("initial_cash and board_lot must be positive")


@dataclass
class Position:
    symbol: str
    units: float
    avg_adjusted_cost: float
    entry_date: pd.Timestamp
    last_mark: float


@dataclass
class BacktestResult:
    config: BacktestConfig
    equity: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict
    yearly: pd.DataFrame
    selections: pd.DataFrame
    qlib_fingerprint: dict
    financial_fingerprint: dict
    runtime_seconds: float
    holding_days: list


class LocalBacktester:
    def __init__(self, data, financials, config=None, common=None):
        self.data = data
        self.financials = financials
        self.config = config if config is not None else BacktestConfig()
        self.common = common if common is not None else load_common_engine()
        self.cash = float(self.config.initial_cash)
        self.positions = {}
        self.frames = {}
        self.trades = []
        self.selections = []
        self.holding_days = []
        self._industry_cache = {}
        self.feature_cache = {}

    def _log(self, message):
        if self.config.verbose:
            print(message, flush=True)

    def _prepare_frames(self):
        start_index = self.data.calendar.searchsorted(self.config.start_date, side="left")
        warmup_index = max(0, start_index - 280)
        warmup_start = self.data.calendar[warmup_index]
        symbols = set(self.financials.by_symbol)
        symbols.add(self.config.benchmark_symbol)
        self._log(
            "准备 {} 只证券：{} 至 {}".format(
                len(symbols), warmup_start.date(), self.config.end_date.date()
            )
        )
        for number, symbol in enumerate(sorted(symbols), 1):
            self.frames[symbol] = self.data.load_symbol_frame(
                symbol, warmup_start, self.config.end_date
            )
            if self.config.verbose and number % 200 == 0:
                self._log("行情准备进度：{}/{}".format(number, len(symbols)))

    def _members(self, observation_date):
        index_members = set(
            self.data.members_on(self.config.markets, observation_date)
        )
        return sorted(index_members.intersection(self.financials.by_symbol))

    def _history(self, symbol, observation_date, count=260):
        frame = self.frames.get(symbol)
        if frame is None:
            return None
        result = frame.loc[:observation_date].tail(count)
        return result if not result.empty else None

    def _execution_row(self, symbol, trade_date):
        frame = self.frames.get(symbol)
        if frame is None or trade_date not in frame.index:
            return None
        return frame.loc[trade_date]

    def _tradeable(self, row):
        if row is None:
            return False
        required = ("open", "high", "low", "factor", "raw_open", "volume")
        if not all(np.isfinite(row.get(column, np.nan)) for column in required):
            return False
        if any(float(row[column]) <= 0.0 for column in required):
            return False
        scale = max(abs(float(row["open"])), 1.0)
        return float(row["high"]) - float(row["low"]) > scale * 1.0e-8

    def _features(self, observation_date):
        observation_date = pd.Timestamp(observation_date).normalize()
        if observation_date in self.feature_cache:
            return self.feature_cache[observation_date].copy()
        rows = []
        for symbol in self._members(observation_date):
            listing_start = self.data.listing_start(symbol)
            if listing_start is None:
                continue
            if (pd.Timestamp(observation_date) - listing_start).days < self.config.min_listing_days:
                continue
            history = self._history(symbol, observation_date)
            prices = price_features(history)
            if not prices["liquid"]:
                continue
            visible = self.financials.histories(symbol, observation_date)
            quarter = latest_quarter_growths(visible.quarterly)
            annual = annual_growth_path(visible.annual)
            report_date = quarter["report_date"]
            report_age = (
                (pd.Timestamp(observation_date) - report_date).days
                if pd.notna(report_date)
                else np.nan
            )
            rows.append(
                {
                    "symbol": symbol,
                    "name": self.financials.name(symbol),
                    "industry": self.financials.industry(symbol),
                    **quarter,
                    "report_age_days": report_age,
                    "annual_cagr": annual["cagr"],
                    "annual_positive_path": annual["all_positive_growth"],
                    **prices,
                }
            )
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame.set_index("symbol", drop=False, inplace=True)
        fresh = pd.to_numeric(frame["report_age_days"], errors="coerce").le(240)
        for column in ("eps_growth", "profit_growth", "revenue_growth"):
            frame.loc[~fresh, column] = np.nan
        frame["growth_percentile"] = percentile_rank(frame["profit_growth"])
        frame["turnaround_strength"] = [
            turnaround_strength(current, prior)
            for current, prior in zip(
                frame["profit_current"], frame["profit_prior"]
            )
        ]
        frame["turnaround_percentile"] = percentile_rank(
            frame["turnaround_strength"]
        )
        frame["revenue_percentile"] = percentile_rank(frame["revenue_growth"])
        frame["momentum_percentile"] = percentile_rank(frame["momentum_9_1"])
        frame["rps"] = percentile_rank(frame["return_12m"])
        self.feature_cache[observation_date] = frame.copy()
        return frame

    def _benchmark_history(self, observation_date):
        return self._history(self.config.benchmark_symbol, observation_date, 300)

    def _portfolio_value(self, trade_date, field):
        total = float(self.cash)
        for position in self.positions.values():
            row = self._execution_row(position.symbol, trade_date)
            if row is not None and np.isfinite(row.get(field, np.nan)):
                price = float(row[field])
                if field == "close":
                    position.last_mark = price
            else:
                price = float(position.last_mark)
            if np.isfinite(price):
                total += position.units * price
        return total

    def _record_trade(
        self,
        trade_date,
        observation_date,
        symbol,
        side,
        reason,
        shares,
        units,
        raw_price,
        adjusted_price,
        gross,
        costs,
        score=np.nan,
    ):
        self.trades.append(
            {
                "date": pd.Timestamp(trade_date),
                "observation_date": pd.Timestamp(observation_date),
                "symbol": symbol,
                "name": self.financials.name(symbol),
                "industry": self.financials.industry(symbol),
                "side": side,
                "reason": reason,
                "score": score,
                "shares": float(shares),
                "adjusted_units": float(units),
                "raw_price": float(raw_price),
                "adjusted_price": float(adjusted_price),
                "gross": float(gross),
                "costs": float(costs),
                "cash_after": float(self.cash),
            }
        )

    def _sell_to_target(
        self, symbol, trade_date, observation_date, target_value, reason
    ):
        position = self.positions.get(symbol)
        row = self._execution_row(symbol, trade_date)
        if position is None or not self._tradeable(row):
            return 0.0
        current_value = position.units * float(row["open"])
        reduction = max(current_value - float(target_value), 0.0)
        factor = float(row["factor"])
        current_shares = max(int(round(position.units * factor)), 0)
        if target_value <= 0.0:
            shares = current_shares
        else:
            raw_value = reduction / factor
            raw_price_reference = float(row["raw_open"])
            shares = int(raw_value // (raw_price_reference * self.config.board_lot))
            shares *= self.config.board_lot
            shares = min(shares, current_shares)
        if shares <= 0:
            return 0.0
        raw_price = self.common.execution_raw_price(
            float(row["raw_open"]), "sell", self.config
        )
        units = shares / factor
        adjusted_price = raw_price * factor
        gross = units * adjusted_price
        costs = self.common.transaction_cost(gross, "sell", self.config)
        self.cash += gross - costs
        position.units -= units
        fully_closed = position.units <= max(1.0e-8, 0.5 / factor)
        if fully_closed:
            self.holding_days.append(
                int((pd.Timestamp(trade_date) - position.entry_date).days)
            )
            del self.positions[symbol]
        self._record_trade(
            trade_date,
            observation_date,
            symbol,
            "sell",
            reason,
            shares,
            units,
            raw_price,
            adjusted_price,
            gross,
            costs,
        )
        return float(gross)

    def _buy_to_target(
        self,
        symbol,
        trade_date,
        observation_date,
        target_value,
        score,
    ):
        row = self._execution_row(symbol, trade_date)
        if not self._tradeable(row):
            return 0.0
        current_value = (
            self.positions[symbol].units * float(row["open"])
            if symbol in self.positions
            else 0.0
        )
        budget = max(float(target_value) - current_value, 0.0)
        shares = self.common.affordable_board_lot(
            budget=budget,
            cash=self.cash,
            raw_price=float(row["raw_open"]),
            config=self.config,
        )
        if shares < self.config.board_lot:
            return 0.0
        raw_price = self.common.execution_raw_price(
            float(row["raw_open"]), "buy", self.config
        )
        gross = shares * raw_price
        costs = self.common.transaction_cost(gross, "buy", self.config)
        if gross + costs > self.cash + 1.0e-8:
            return 0.0
        factor = float(row["factor"])
        units = shares / factor
        adjusted_price = raw_price * factor
        self.cash -= gross + costs
        if symbol in self.positions:
            position = self.positions[symbol]
            total_units = position.units + units
            position.avg_adjusted_cost = (
                position.avg_adjusted_cost * position.units
                + adjusted_price * units
            ) / total_units
            position.units = total_units
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                units=units,
                avg_adjusted_cost=adjusted_price,
                entry_date=pd.Timestamp(trade_date),
                last_mark=float(row["open"]),
            )
        self._record_trade(
            trade_date,
            observation_date,
            symbol,
            "buy",
            "monthly_rebalance",
            shares,
            units,
            raw_price,
            adjusted_price,
            gross,
            costs,
            score=score,
        )
        return float(gross)

    def _record_selections(self, observation_date, candidates, selected):
        selected_set = set(selected)
        if candidates.empty:
            self.selections.append(
                {
                    "observation_date": pd.Timestamp(observation_date),
                    "model": self.config.model,
                    "symbol": "",
                    "selected": False,
                    "rank": np.nan,
                    "candidate_count": 0,
                }
            )
            return
        for rank, row in enumerate(candidates.itertuples(index=False), 1):
            record = row._asdict()
            record.update(
                {
                    "observation_date": pd.Timestamp(observation_date),
                    "model": self.config.model,
                    "selected": row.symbol in selected_set,
                    "rank": rank,
                    "candidate_count": len(candidates),
                }
            )
            self.selections.append(record)

    def _rebalance(self, trade_date, observation_date):
        features = self._features(observation_date)
        candidates = select_candidates(features, self.config.model)
        limit = max_positions_for_model(self.config.model)
        selected_frame = candidates.head(limit)
        selected = selected_frame["symbol"].tolist()
        self._record_selections(observation_date, candidates, selected)
        benchmark = self._benchmark_history(observation_date)
        closes = (
            benchmark["close"]
            if benchmark is not None and "close" in benchmark
            else pd.Series(dtype=float)
        )
        exposure = market_exposure(closes, self.config.model)
        total_value = self._portfolio_value(trade_date, "open")
        weight = min(0.05, exposure / len(selected)) if selected else 0.0
        target_value = total_value * weight
        gross_traded = 0.0

        for symbol in list(self.positions):
            target = target_value if symbol in selected else 0.0
            gross_traded += self._sell_to_target(
                symbol,
                trade_date,
                observation_date,
                target,
                "monthly_rebalance" if symbol in selected else "not_selected",
            )
        score_by_symbol = (
            selected_frame.set_index("symbol")["score"].to_dict()
            if not selected_frame.empty
            else {}
        )
        for symbol in selected:
            gross_traded += self._buy_to_target(
                symbol,
                trade_date,
                observation_date,
                target_value,
                score_by_symbol.get(symbol, np.nan),
            )
        return gross_traded, len(candidates), len(selected), exposure

    def _benchmark_values(self, trade_dates):
        prior = self.data.previous_trade_date(trade_dates[0])
        benchmark = self.data.load_symbol_frame(
            self.config.benchmark_symbol, prior, trade_dates[-1]
        )["close"].ffill()
        base = benchmark.loc[:prior].dropna()
        if base.empty:
            raise ValueError("benchmark has no valid close data")
        return (benchmark / float(base.iloc[-1])).reindex(trade_dates).ffill()

    def run(self):
        started = time.perf_counter()
        trade_dates = self.data.trade_dates(
            self.config.start_date, self.config.end_date
        )
        if trade_dates.empty:
            raise ValueError("回测区间内没有交易日")
        if not self.frames:
            self._prepare_frames()
        rebalance_dates = monthly_rebalance_dates(trade_dates)
        benchmark_values = self._benchmark_values(trade_dates)
        equity_rows = []
        last_candidate_count = 0
        last_selected_count = 0
        last_exposure = 0.0

        for trade_date in trade_dates:
            gross_traded = 0.0
            observation_date = self.data.previous_trade_date(trade_date)
            if trade_date in rebalance_dates:
                self._log(
                    "{} {} 月度扫描".format(self.config.model, observation_date.date())
                )
                (
                    gross_traded,
                    last_candidate_count,
                    last_selected_count,
                    last_exposure,
                ) = self._rebalance(trade_date, observation_date)
            market_value = 0.0
            for position in self.positions.values():
                row = self._execution_row(position.symbol, trade_date)
                if row is not None and np.isfinite(row.get("close", np.nan)):
                    position.last_mark = float(row["close"])
                if np.isfinite(position.last_mark):
                    market_value += position.units * position.last_mark
            equity_rows.append(
                {
                    "date": trade_date,
                    "equity": self.cash + market_value,
                    "cash": self.cash,
                    "market_value": market_value,
                    "positions": len(self.positions),
                    "gross_traded": gross_traded,
                    "benchmark_value": float(benchmark_values.loc[trade_date]),
                    "candidate_count": last_candidate_count,
                    "selected_count": last_selected_count,
                    "target_exposure": last_exposure,
                }
            )

        equity = pd.DataFrame(equity_rows).set_index("date")
        equity["daily_return"] = equity["equity"].pct_change(fill_method=None)
        equity.iloc[0, equity.columns.get_loc("daily_return")] = (
            equity["equity"].iloc[0] / self.config.initial_cash - 1.0
        )
        equity["drawdown"] = equity["equity"] / equity["equity"].cummax() - 1.0
        trades = pd.DataFrame(self.trades)
        selections = pd.DataFrame(self.selections)
        metrics, yearly = self.common.calculate_performance(
            equity,
            trade_count=len(trades),
            holding_days=self.holding_days,
            initial_equity=self.config.initial_cash,
        )
        metrics["runtime_seconds"] = float(time.perf_counter() - started)
        metrics["model"] = self.config.model
        metrics["rebalance_count"] = int(len(rebalance_dates))
        metrics["average_candidate_count"] = float(
            selections.groupby("observation_date")["candidate_count"].first().mean()
            if not selections.empty
            else 0.0
        )
        selected_rows = (
            selections.loc[selections["selected"].eq(True)]
            if not selections.empty and "selected" in selections
            else pd.DataFrame()
        )
        semiconductor = (
            selected_rows.loc[selected_rows["industry"].eq("半导体")]
            if not selected_rows.empty and "industry" in selected_rows
            else pd.DataFrame()
        )
        metrics["semiconductor_selection_rows"] = int(len(semiconductor))
        metrics["unique_semiconductors_selected"] = int(
            semiconductor["symbol"].nunique() if not semiconductor.empty else 0
        )
        if not trades.empty:
            semi_buys = trades.loc[
                trades["side"].eq("buy") & trades["industry"].eq("半导体")
            ]
            metrics["semiconductor_buy_events"] = int(len(semi_buys))
            metrics["unique_semiconductors_bought"] = int(
                semi_buys["symbol"].nunique()
            )
            metrics["transaction_cost_total"] = float(trades["costs"].sum())
        else:
            metrics["semiconductor_buy_events"] = 0
            metrics["unique_semiconductors_bought"] = 0
            metrics["transaction_cost_total"] = 0.0
        runtime = time.perf_counter() - started
        return BacktestResult(
            config=self.config,
            equity=equity,
            trades=trades,
            metrics=metrics,
            yearly=yearly,
            selections=selections,
            qlib_fingerprint=self.data.fingerprint(),
            financial_fingerprint=self.financials.fingerprint(),
            runtime_seconds=runtime,
            holding_days=list(self.holding_days),
        )


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def _format_percent(value):
    if value is None or not np.isfinite(float(value)):
        return "N/A"
    return "{:.2%}".format(float(value))


def render_report(result, run_id):
    metrics = result.metrics
    selected = (
        result.selections.loc[result.selections["selected"].eq(True)]
        if not result.selections.empty
        else pd.DataFrame()
    )
    semis = (
        selected.loc[selected["industry"].eq("半导体")]
        if not selected.empty and "industry" in selected
        else pd.DataFrame()
    )
    names = []
    if not semis.empty:
        grouped = (
            semis.groupby(["symbol", "name"], dropna=False)
            .size()
            .sort_values(ascending=False)
            .head(20)
        )
        names = [
            "{} {}（{}个月）".format(symbol, name, count)
            for (symbol, name), count in grouped.items()
        ]
    semi_lines = "\n".join("- {}".format(item) for item in names) or "- 无"
    limitations = {
        "huachuang-2019-available": (
            "机构持有数与北向持股缺失，因此这是移除I条件的可得数据版，"
            "不能称为研报精确复刻。"
        ),
        "huachuang-2-lite": (
            "缺失基金基础池、业绩预告/快报和分析师一致预期；只复刻了"
            "季度增长与动量两个可观察维度。"
        ),
        "shenwan-2018-lite": (
            "缺失自由流通市值和机构持股比例增长；基底为65日深度与高位代理。"
        ),
        "growth-new-high-simple": "这是刻意简化的对照模型，不代表任何原始研报。",
        "a-share-adaptive": "这是研究者判断形成的变体，不是欧奈尔或券商原始规则。",
        "a-share-cycle-turnaround": (
            "这是针对强周期行业负利润转正口径的研究者变体；"
            "4.0只是排序上限，不是400%的同比增速。"
        ),
    }[result.config.model]
    return """# {model} 本地回测

运行标识：`{run_id}`

## 事实

- 区间：{start} 至 {end}
- 累计收益：{total}
- 年化收益：{annual}
- 沪深300累计收益：{benchmark}
- 年化超额：{excess}
- 最大回撤：{drawdown}
- Sharpe：{sharpe}
- Calmar：{calmar}
- 换手：{turnover}
- 最长水下期：{underwater} 个交易日
- 平均现金比例：{cash}
- 半导体入选：{semi_rows} 个“股票-月份”，{semi_unique} 只股票
- 成交事件：{trades}，其中半导体买入 {semi_buys} 次
- 单边成本假设：成交额的 0.13%，另加每股 0.002 元滑点

## 半导体捕获

{semi_lines}

## 口径边界

{limitations}

本地股票池为观察日的历史沪深300与中证500成分交集；财务报告按公告日可见，
但缓存可能使用后来修订的旧报告版本；行业为当前东方财富分类，不是点时分类。

## 推断

该结果只回答“在相同本地数据和撮合下，这组透明规则是否参与成长主线”，
不能证明缺失的机构或预期因子无效。若模型抓到半导体而严格版没有，首先支持的是
“长期连续增长硬门槛与新赛道盈利周期不匹配”，而不是支持任意放宽基本面。

## 下一步

补充点时基金重仓、北向持仓、业绩预告/快报和一致预期后，应新增精确版本，
不得覆盖本归档。还应做成本翻倍、全A股票池、分市场指数过滤和样本外滚动验证。
""".format(
        model=result.config.model,
        run_id=run_id,
        start=result.config.start_date.date(),
        end=result.config.end_date.date(),
        total=_format_percent(metrics.get("total_return")),
        annual=_format_percent(metrics.get("annualized_return")),
        benchmark=_format_percent(metrics.get("benchmark_total_return")),
        excess=_format_percent(metrics.get("annualized_excess_return")),
        drawdown=_format_percent(metrics.get("max_drawdown")),
        sharpe=(
            "{:.3f}".format(metrics["sharpe"])
            if metrics.get("sharpe") is not None
            and np.isfinite(metrics["sharpe"])
            else "N/A"
        ),
        calmar=(
            "{:.3f}".format(metrics["calmar"])
            if metrics.get("calmar") is not None
            and np.isfinite(metrics["calmar"])
            else "N/A"
        ),
        turnover="{:.2f}".format(metrics.get("turnover", 0.0)),
        underwater=metrics.get("longest_underwater_trading_days", "N/A"),
        cash=_format_percent(metrics.get("average_cash_ratio")),
        semi_rows=metrics.get("semiconductor_selection_rows", 0),
        semi_unique=metrics.get("unique_semiconductors_selected", 0),
        trades=metrics.get("trade_count", 0),
        semi_buys=metrics.get("semiconductor_buy_events", 0),
        semi_lines=semi_lines,
        limitations=limitations,
    )


def archive_result(result, run_id, archived_at=None):
    archived_at = (
        pd.Timestamp(archived_at).normalize()
        if archived_at is not None
        else pd.Timestamp.now().normalize()
    )
    model = result.config.model
    target = (
        STRATEGY_DIR
        / "backtests"
        / "{}__{}__{}".format(
            archived_at.strftime("%Y-%m-%d"), model, str(run_id)
        )
    )
    if target.exists():
        raise FileExistsError("回测归档已存在，不可覆盖：{}".format(target))
    raw = target / "raw"
    raw.mkdir(parents=True)
    source = target / "source.py"
    shutil.copy2(Path(__file__).resolve(), source)
    result.equity.to_csv(raw / "equity.csv", encoding="utf-8-sig")
    result.trades.to_csv(raw / "trades.csv", index=False, encoding="utf-8-sig")
    result.yearly.to_csv(raw / "yearly.csv", encoding="utf-8-sig")
    result.selections.to_csv(
        raw / "selections.csv", index=False, encoding="utf-8-sig"
    )
    manifest = {
        "schema_version": 1,
        "strategy_id": "oneil-canslim-factor-a-share",
        "variant": model,
        "platform": "joinquant",
        "archived_at": archived_at.strftime("%Y-%m-%d"),
        "source_file": "source.py",
        "source_sha256": sha256_file(source),
        "period": {
            "start": result.config.start_date.strftime("%Y-%m-%d"),
            "end": result.config.end_date.strftime("%Y-%m-%d"),
        },
        "benchmark": "沪深300/SZ399300",
        "costs": {
            "commission_each_side": result.config.commission_rate,
            "sell_tax": result.config.sell_tax_rate,
            "fixed_slippage_per_share": result.config.fixed_slippage_per_share,
        },
        "metrics": _json_safe(result.metrics),
        "config": _json_safe(asdict(result.config)),
        "model_description": MODEL_DESCRIPTIONS[model],
        "data": {
            "qlib": _json_safe(result.qlib_fingerprint),
            "financials": _json_safe(result.financial_fingerprint),
        },
        "limitations": [
            "股票池仅为观察日历史沪深300与中证500成分交集。",
            "财务缓存按公告日可见，但历史报告修订版本可能回填。",
            "行业为当前东方财富分类，不是点时分类。",
            "机构持仓、分析师一致预期和业绩预告/快报不可用。",
        ],
        "run_id": str(run_id),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target / "report.md").write_text(
        render_report(result, run_id), encoding="utf-8"
    )
    return target
