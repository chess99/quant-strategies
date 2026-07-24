"""KTV + MACD 基线的本地 Qlib 日线回测器。

本模块直接读取 Qlib 标准二进制目录，不依赖远程行情接口，也不复制
baseline.py 的信号公式。交易信号使用前一交易日及以前的数据，在下一
交易日开盘执行。
"""

import hashlib
import importlib.util
import json
import math
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parent
BASELINE_PATH = STRATEGY_DIR / "baseline.py"
REQUIRED_FIELDS = ("open", "high", "low", "close", "volume", "factor", "amount")
DEFAULT_MARKETS = ("csi300", "csi500")
DEFAULT_EXCLUDED_SYMBOLS = frozenset({"SZ302132"})
ENTRY_MODE_DESCRIPTIONS = {
    "baseline": "完整 KTV + MACD 左右侧共振入场。",
    "ktv-entry-only": (
        "入场保留 KTV、趋势、位置、成交额条件，移除 MACD 确认；"
        "退出规则与基线完全一致。"
    ),
    "macd-entry-only": (
        "入场保留 MACD、趋势、位置、成交额条件，移除 KTV 确认；"
        "退出规则与基线完全一致。"
    ),
    "left-only": "只允许完整双指标左侧共振入场；退出规则与基线完全一致。",
    "right-only": "只允许完整双指标右侧共振入场；退出规则与基线完全一致。",
    "right-no-volume": (
        "只允许完整双指标右侧入场，但移除成交额温和放量过滤；"
        "趋势与退出规则保持不变。"
    ),
    "right-no-trend": (
        "只允许完整双指标右侧入场，但移除 MA20/MA60/MA120 多头趋势过滤；"
        "KTV、MACD、成交额与退出规则保持不变。"
    ),
}


@dataclass
class BacktestConfig:
    start_date: pd.Timestamp | str = "2019-01-01"
    end_date: pd.Timestamp | str = "2025-12-31"
    initial_cash: float = 1_000_000.0
    max_positions: int = 10
    target_gross_exposure: float = 0.95
    min_listing_days: int = 250
    history_count: int = 160
    min_signal_rows: int = 125
    board_lot: int = 100
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    sell_tax_rate: float = 0.001
    fixed_slippage_per_share: float = 0.002
    anomaly_adjusted_return: float = 0.30
    benchmark_symbol: str = "SZ399300"
    entry_mode: str = "baseline"
    markets: tuple[str, ...] = DEFAULT_MARKETS
    excluded_symbols: frozenset[str] = field(
        default_factory=lambda: DEFAULT_EXCLUDED_SYMBOLS
    )
    verbose: bool = False

    def __post_init__(self):
        self.start_date = pd.Timestamp(self.start_date).normalize()
        self.end_date = pd.Timestamp(self.end_date).normalize()
        self.markets = tuple(self.markets)
        self.entry_mode = str(self.entry_mode).strip().lower()
        self.excluded_symbols = frozenset(
            str(symbol).upper() for symbol in self.excluded_symbols
        )
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be later than end_date")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.max_positions <= 0 or self.board_lot <= 0:
            raise ValueError("max_positions and board_lot must be positive")
        if not 0 < self.target_gross_exposure <= 1:
            raise ValueError("target_gross_exposure must be in (0, 1]")
        if self.entry_mode not in ENTRY_MODE_DESCRIPTIONS:
            raise ValueError(f"unsupported entry mode: {self.entry_mode}")


@dataclass
class Position:
    symbol: str
    units: float
    avg_adjusted_cost: float
    entry_date: pd.Timestamp
    half_reduced: bool = False
    last_mark: float = np.nan


@dataclass
class BacktestResult:
    config: BacktestConfig
    equity: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict
    yearly: pd.DataFrame
    excluded_symbols: list[str]
    anomalies: pd.DataFrame
    data_fingerprint: dict
    runtime_seconds: float
    holding_days: list[int]
    round_trips: pd.DataFrame
    attribution: dict


def load_baseline_logic(path=BASELINE_PATH):
    """加载聚宽基线，使本地执行层复用同一套指标和信号函数。"""
    path = Path(path)
    spec = importlib.util.spec_from_file_location("ktv_macd_joinquant_baseline", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load strategy logic from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _left_score(logic, frame):
    latest = logic._finite_number(frame["close"].iloc[-1])
    high = logic._finite_number(frame["close"].tail(60).max())
    drawdown = 1.0 - latest / high if np.isfinite(high) and high > 0.0 else 0.0
    return 100.0 + min(max(drawdown, 0.0), 0.50) * 100.0


def _right_score(logic, frame):
    latest = frame.iloc[-1]
    ma20 = logic._finite_number(latest["ma20"])
    ma60 = logic._finite_number(latest["ma60"])
    trend_gap = ma20 / ma60 - 1.0 if np.isfinite(ma60) and ma60 > 0.0 else 0.0
    return 200.0 + min(max(trend_gap, 0.0), 0.20) * 100.0


def _ktv_left_entry(logic, frame):
    v = logic._last_values(frame, "v", 5)
    return bool(
        len(v) == 5
        and v.min() <= 20.0
        and logic.crossed_up_recent(frame["k"], frame["t"], lookback=3)
        and logic._not_in_downtrend(frame)
        and logic._stage_low_not_falling_knife(frame)
        and logic._moderate_volume(frame)
    )


def _ktv_right_entry(logic, frame):
    t_value = logic._finite_number(frame.iloc[-1].get("t"))
    return bool(
        logic._bull_trend(frame)
        and np.isfinite(t_value)
        and t_value >= 50.0
        and logic.crossed_up_recent(frame["k"], frame["t"], lookback=3)
        and logic._moderate_volume(frame)
    )


def _macd_left_entry(logic, frame):
    return bool(
        (
            logic._green_histogram_shrinking(frame)
            or logic._macd_crossed_up_recent(frame)
        )
        and logic._not_in_downtrend(frame)
        and logic._stage_low_not_falling_knife(frame)
        and logic._moderate_volume(frame)
    )


def _macd_right_entry(logic, frame):
    latest = frame.iloc[-1]
    diff = logic._finite_number(latest.get("diff"))
    dea = logic._finite_number(latest.get("dea"))
    return bool(
        logic._bull_trend(frame)
        and np.isfinite(diff)
        and np.isfinite(dea)
        and diff > dea
        and dea > 0.0
        and logic._red_histogram_reexpanding(frame)
        and logic._moderate_volume(frame)
    )


def _right_resonance_entry(
    logic,
    frame,
    require_trend=True,
    require_volume=True,
):
    latest = frame.iloc[-1]
    diff = logic._finite_number(latest.get("diff"))
    dea = logic._finite_number(latest.get("dea"))
    t_value = logic._finite_number(latest.get("t"))
    conditions = [
        np.isfinite(t_value),
        t_value >= 50.0,
        logic.crossed_up_recent(frame["k"], frame["t"], lookback=3),
        np.isfinite(diff),
        np.isfinite(dea),
        diff > dea,
        dea > 0.0,
        logic._red_histogram_reexpanding(frame),
    ]
    if require_trend:
        conditions.append(logic._bull_trend(frame))
    if require_volume:
        conditions.append(logic._moderate_volume(frame))
    return bool(all(conditions))


def entry_signal_for_mode(logic, frame, mode):
    """按控制实验模式生成入场信号；所有模式共用基线退出逻辑。"""
    mode = str(mode).strip().lower()
    if mode == "baseline":
        return logic.entry_signal(frame)
    if mode == "left-only":
        return (
            {"kind": "left", "score": _left_score(logic, frame)}
            if logic.is_left_entry(frame)
            else None
        )
    if mode == "right-only":
        return (
            {"kind": "right", "score": _right_score(logic, frame)}
            if logic.is_right_entry(frame)
            else None
        )
    if mode == "right-no-volume":
        return (
            {"kind": "right", "score": _right_score(logic, frame)}
            if _right_resonance_entry(
                logic,
                frame,
                require_trend=True,
                require_volume=False,
            )
            else None
        )
    if mode == "right-no-trend":
        return (
            {"kind": "right", "score": _right_score(logic, frame)}
            if _right_resonance_entry(
                logic,
                frame,
                require_trend=False,
                require_volume=True,
            )
            else None
        )
    if mode == "ktv-entry-only":
        if _ktv_right_entry(logic, frame):
            return {"kind": "right", "score": _right_score(logic, frame)}
        if _ktv_left_entry(logic, frame):
            return {"kind": "left", "score": _left_score(logic, frame)}
        return None
    if mode == "macd-entry-only":
        if _macd_right_entry(logic, frame):
            return {"kind": "right", "score": _right_score(logic, frame)}
        if _macd_left_entry(logic, frame):
            return {"kind": "left", "score": _left_score(logic, frame)}
        return None
    raise ValueError(f"unsupported entry mode: {mode}")


def classify_exit_reason(
    logic,
    frame,
    decision,
    avg_cost=None,
    half_reduced=False,
):
    """在不改变基线退出决定的前提下，按基线优先级标注具体原因。"""
    try:
        latest_close = logic._finite_number(frame["close"].iloc[-1])
        cost = logic._finite_number(avg_cost)
        hard_stop = (
            np.isfinite(cost)
            and cost > 0.0
            and np.isfinite(latest_close)
            and latest_close <= cost * (1.0 - logic.HARD_STOP_LOSS)
        )
        if decision == "full":
            if hard_stop:
                return "exit_hard_stop"
            if logic._resonance_full_exit(frame):
                return "exit_resonance"
            if logic._trend_invalid(frame):
                return "exit_trend_invalid"
        if (
            decision == "half"
            and not half_reduced
            and logic._take_profit_signal(frame)
        ):
            return "exit_take_profit_half"
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return f"exit_{decision}"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class QlibBinDataPortal:
    """读取 Qlib 日线二进制、证券有效区间和历史指数成分。"""

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.calendar_path = self.root / "calendars" / "day.txt"
        self.instruments_dir = self.root / "instruments"
        self.features_dir = self.root / "features"
        if not self.calendar_path.is_file():
            raise FileNotFoundError(f"Qlib calendar not found: {self.calendar_path}")
        if not self.instruments_dir.is_dir() or not self.features_dir.is_dir():
            raise FileNotFoundError(f"invalid Qlib data directory: {self.root}")
        calendar_values = [
            value.strip()
            for value in self.calendar_path.read_text(encoding="utf-8").splitlines()
            if value.strip()
        ]
        self.calendar = pd.DatetimeIndex(pd.to_datetime(calendar_values))
        self._market_cache = {}
        self._listing_spans = self._read_instrument_file(
            self.instruments_dir / "all.txt"
        )
        self._listing_start = {
            symbol: min(start for _, start, _ in rows)
            for symbol, rows in self._group_spans(self._listing_spans).items()
        }

    @staticmethod
    def _group_spans(rows):
        grouped = {}
        for symbol, start, end in rows:
            grouped.setdefault(symbol, []).append((symbol, start, end))
        return grouped

    @staticmethod
    def _read_instrument_file(path):
        rows = []
        if not Path(path).is_file():
            raise FileNotFoundError(f"instrument file not found: {path}")
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            symbol, start, end = line.split("\t")
            rows.append(
                (
                    symbol.upper(),
                    pd.Timestamp(start).normalize(),
                    pd.Timestamp(end).normalize(),
                )
            )
        return rows

    def _market_rows(self, market):
        market = str(market).lower()
        if market not in self._market_cache:
            self._market_cache[market] = self._read_instrument_file(
                self.instruments_dir / f"{market}.txt"
            )
        return self._market_cache[market]

    def members_on(self, markets, observation_date):
        observation_date = pd.Timestamp(observation_date).normalize()
        members = set()
        for market in markets:
            for symbol, start, end in self._market_rows(market):
                if start <= observation_date <= end:
                    members.add(symbol)
        return sorted(members)

    def symbols_during(self, markets, start_date, end_date):
        start_date = pd.Timestamp(start_date).normalize()
        end_date = pd.Timestamp(end_date).normalize()
        symbols = set()
        for market in markets:
            for symbol, start, end in self._market_rows(market):
                if start <= end_date and end >= start_date:
                    symbols.add(symbol)
        return sorted(symbols)

    def listing_start(self, symbol):
        return self._listing_start.get(str(symbol).upper())

    def previous_trade_date(self, value):
        value = pd.Timestamp(value).normalize()
        location = self.calendar.searchsorted(value, side="left") - 1
        if location < 0:
            raise ValueError(f"no previous trade date before {value.date()}")
        return self.calendar[location]

    def trade_dates(self, start_date, end_date):
        start_date = pd.Timestamp(start_date).normalize()
        end_date = pd.Timestamp(end_date).normalize()
        return self.calendar[(self.calendar >= start_date) & (self.calendar <= end_date)]

    def _read_feature(self, symbol, field):
        path = (
            self.features_dir
            / str(symbol).lower()
            / f"{str(field).lower()}.day.bin"
        )
        if not path.is_file():
            return pd.Series(dtype="float32", name=field)
        payload = np.fromfile(path, dtype="<f4")
        if payload.size < 2 or not np.isfinite(payload[0]):
            return pd.Series(dtype="float32", name=field)
        start_index = int(payload[0])
        values = payload[1:]
        end_index = start_index + len(values)
        if start_index < 0 or end_index > len(self.calendar):
            raise ValueError(f"feature calendar bounds invalid: {path}")
        return pd.Series(
            values,
            index=self.calendar[start_index:end_index],
            name=field,
            dtype="float32",
        )

    def load_symbol_frame(self, symbol, start_date, end_date):
        symbol = str(symbol).upper()
        target_calendar = self.trade_dates(start_date, end_date)
        fields = {
            field: self._read_feature(symbol, field).reindex(target_calendar)
            for field in REQUIRED_FIELDS
        }
        frame = pd.DataFrame(fields, index=target_calendar)
        frame.index.name = "date"
        frame["money"] = pd.to_numeric(frame["amount"], errors="coerce") * 1000.0
        valid_factor = pd.to_numeric(frame["factor"], errors="coerce").replace(
            0.0, np.nan
        )
        frame["raw_open"] = frame["open"] / valid_factor
        frame["raw_close"] = frame["close"] / valid_factor
        return frame

    def fingerprint(self):
        files = [
            self.calendar_path,
            self.instruments_dir / "all.txt",
            self.instruments_dir / "csi300.txt",
            self.instruments_dir / "csi500.txt",
        ]
        return {
            "root": str(self.root),
            "calendar_first": self.calendar[0].strftime("%Y-%m-%d"),
            "calendar_last": self.calendar[-1].strftime("%Y-%m-%d"),
            "calendar_rows": int(len(self.calendar)),
            "files": {
                path.relative_to(self.root).as_posix(): {
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in files
            },
        }


def find_adjustment_anomalies(
    frame,
    adjusted_threshold=0.30,
    raw_threshold=0.30,
):
    """找出调整价巨变、但原始价没有同步巨变的复权异常。"""
    required = {"close", "factor"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(
            columns=[
                "date",
                "adjusted_return",
                "raw_return",
                "previous_factor",
                "factor",
            ]
        )
    close = pd.to_numeric(frame["close"], errors="coerce")
    factor = pd.to_numeric(frame["factor"], errors="coerce").replace(0.0, np.nan)
    raw_close = close / factor
    adjusted_return = close.pct_change(fill_method=None)
    raw_return = raw_close.pct_change(fill_method=None)
    mask = (
        adjusted_return.abs().gt(adjusted_threshold)
        & raw_return.abs().le(raw_threshold)
        & adjusted_return.notna()
        & raw_return.notna()
    )
    result = pd.DataFrame(
        {
            "date": frame.index[mask],
            "adjusted_return": adjusted_return[mask].to_numpy(),
            "raw_return": raw_return[mask].to_numpy(),
            "previous_factor": factor.shift(1)[mask].to_numpy(),
            "factor": factor[mask].to_numpy(),
        }
    )
    return result.reset_index(drop=True)


def execution_raw_price(raw_open, side, config):
    raw_open = float(raw_open)
    if side == "buy":
        return raw_open + config.fixed_slippage_per_share
    if side == "sell":
        return max(raw_open - config.fixed_slippage_per_share, 0.000001)
    raise ValueError(f"unknown side: {side}")


def transaction_cost(gross, side, config):
    gross = max(float(gross), 0.0)
    if gross <= 0:
        return 0.0
    commission = max(config.minimum_commission, gross * config.commission_rate)
    tax = gross * config.sell_tax_rate if side == "sell" else 0.0
    return commission + tax


def affordable_board_lot(budget, cash, raw_price, config):
    available = min(float(budget), float(cash))
    if available <= 0 or not np.isfinite(raw_price) or raw_price <= 0:
        return 0
    price = execution_raw_price(raw_price, "buy", config)
    lots = int(available // (price * config.board_lot))
    while lots > 0:
        shares = lots * config.board_lot
        gross = shares * price
        if gross + transaction_cost(gross, "buy", config) <= available + 1.0e-8:
            return shares
        lots -= 1
    return 0


def _longest_true_run(values):
    longest = 0
    current = 0
    for value in values:
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def calculate_performance(
    equity,
    trade_count,
    holding_days,
    initial_equity=None,
):
    """计算策略和基准绩效；返回机器指标与年度收益表。"""
    if equity is None or equity.empty:
        raise ValueError("equity curve is empty")
    frame = equity.sort_index().copy()
    values = pd.to_numeric(frame["equity"], errors="coerce")
    if values.isna().any() or (values <= 0).any():
        raise ValueError("equity values must be finite and positive")
    base = float(values.iloc[0] if initial_equity is None else initial_equity)
    periods = max(len(values) - (0 if initial_equity is not None else 1), 1)
    returns = values.pct_change(fill_method=None)
    if initial_equity is not None:
        returns.iloc[0] = values.iloc[0] / base - 1.0

    total_return = float(values.iloc[-1] / base - 1.0)
    annualized_return = float((values.iloc[-1] / base) ** (252.0 / periods) - 1.0)
    volatility = float(returns.std(ddof=1) * math.sqrt(252.0))
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(252.0))
        if returns.std(ddof=1) > 0
        else np.nan
    )

    if initial_equity is not None:
        drawdown_values = pd.concat(
            [
                pd.Series([base], index=[frame.index[0] - pd.Timedelta(nanoseconds=1)]),
                values,
            ]
        )
    else:
        drawdown_values = values
    running_peak = drawdown_values.cummax()
    drawdown = drawdown_values / running_peak - 1.0
    max_drawdown = float(drawdown.min())
    trough_date = drawdown.idxmin()
    peak_date = drawdown_values.loc[:trough_date].idxmax()
    underwater = (values / values.cummax() - 1.0).lt(-1.0e-12)
    longest_underwater = _longest_true_run(underwater)

    benchmark = pd.to_numeric(frame["benchmark_value"], errors="coerce").ffill()
    benchmark_base = 1.0 if initial_equity is not None else float(benchmark.iloc[0])
    benchmark_total = float(benchmark.iloc[-1] / benchmark_base - 1.0)
    benchmark_annualized = float(
        (benchmark.iloc[-1] / benchmark_base) ** (252.0 / periods) - 1.0
    )
    annualized_excess = float(
        (1.0 + annualized_return) / (1.0 + benchmark_annualized) - 1.0
    )
    calmar = (
        float(annualized_return / abs(max_drawdown))
        if max_drawdown < 0
        else np.nan
    )
    gross_traded = pd.to_numeric(
        frame.get("gross_traded", pd.Series(0.0, index=frame.index)),
        errors="coerce",
    ).fillna(0.0)
    turnover = float(gross_traded.sum() / values.mean())
    cash = pd.to_numeric(frame["cash"], errors="coerce")
    average_cash_ratio = float((cash / values).mean())
    daily_win_rate = float(returns.dropna().gt(0.0).mean())

    strategy_yearly = (1.0 + returns.fillna(0.0)).groupby(frame.index.year).prod() - 1.0
    benchmark_returns = benchmark.pct_change(fill_method=None)
    if initial_equity is not None:
        benchmark_returns.iloc[0] = benchmark.iloc[0] / benchmark_base - 1.0
    benchmark_yearly = (
        (1.0 + benchmark_returns.fillna(0.0))
        .groupby(frame.index.year)
        .prod()
        - 1.0
    )
    yearly = pd.DataFrame(
        {
            "strategy_return": strategy_yearly,
            "benchmark_return": benchmark_yearly,
        }
    )
    yearly["excess_return"] = (
        (1.0 + yearly["strategy_return"])
        / (1.0 + yearly["benchmark_return"])
        - 1.0
    )
    yearly.index.name = "year"

    metrics = {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "benchmark_total_return": benchmark_total,
        "benchmark_annualized_return": benchmark_annualized,
        "annualized_excess_return": annualized_excess,
        "max_drawdown": max_drawdown,
        "max_drawdown_peak": pd.Timestamp(peak_date).strftime("%Y-%m-%d"),
        "max_drawdown_trough": pd.Timestamp(trough_date).strftime("%Y-%m-%d"),
        "sharpe": sharpe,
        "calmar": calmar,
        "annualized_volatility": volatility,
        "turnover": turnover,
        "longest_underwater_trading_days": longest_underwater,
        "trade_count": int(trade_count),
        "average_holding_days": (
            float(np.mean(holding_days)) if holding_days else np.nan
        ),
        "daily_win_rate": daily_win_rate,
        "average_cash_ratio": average_cash_ratio,
        "final_equity": float(values.iloc[-1]),
    }
    return metrics, yearly


def build_round_trip_attribution(trades):
    """把买入、分批卖出和最终卖出还原为独立持仓回合。"""
    columns = [
        "symbol",
        "entry_date",
        "exit_date",
        "status",
        "entry_kind",
        "entry_score",
        "entry_gross",
        "exit_gross",
        "gross_pnl",
        "total_costs",
        "net_pnl",
        "net_return",
        "holding_days",
        "had_partial_exit",
        "partial_exit_count",
        "exit_reason",
    ]
    if trades is None or trades.empty:
        empty = pd.DataFrame(columns=columns)
        return empty, {
            "completed_round_trips": 0,
            "open_round_trips": 0,
            "round_trip_win_rate": np.nan,
            "round_trip_profit_factor": np.nan,
            "round_trip_net_pnl": 0.0,
            "round_trip_gross_pnl": 0.0,
            "transaction_cost_total": 0.0,
        }

    ordered = trades.copy()
    ordered["date"] = pd.to_datetime(ordered["date"])
    ordered["_sequence"] = np.arange(len(ordered))
    ordered["_event_order"] = np.where(ordered["side"].eq("sell"), 0, 1)
    ordered.sort_values(
        ["date", "symbol", "_event_order", "_sequence"],
        inplace=True,
    )

    active = {}
    records = []
    for row in ordered.itertuples(index=False):
        symbol = str(row.symbol)
        side = str(row.side)
        gross = float(row.gross)
        costs = float(row.costs)
        date = pd.Timestamp(row.date)
        if side == "buy":
            if symbol in active:
                raise ValueError(f"duplicate open position in trades: {symbol}")
            active[symbol] = {
                "symbol": symbol,
                "entry_date": date,
                "entry_kind": getattr(row, "kind", None),
                "entry_score": getattr(row, "score", np.nan),
                "entry_gross": gross,
                "exit_gross": 0.0,
                "total_costs": costs,
                "partial_exit_count": 0,
            }
            continue
        if side != "sell":
            raise ValueError(f"unsupported trade side: {side}")
        if symbol not in active:
            raise ValueError(f"sell without open position in trades: {symbol}")
        episode = active[symbol]
        episode["exit_gross"] += gross
        episode["total_costs"] += costs
        reason = str(row.reason)
        is_partial = reason in {"exit_half", "exit_take_profit_half"}
        if is_partial:
            episode["partial_exit_count"] += 1
            continue
        gross_pnl = episode["exit_gross"] - episode["entry_gross"]
        net_pnl = gross_pnl - episode["total_costs"]
        deployed = episode["entry_gross"] + episode["total_costs"]
        records.append(
            {
                **episode,
                "exit_date": date,
                "status": "closed",
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "net_return": net_pnl / deployed if deployed > 0.0 else np.nan,
                "holding_days": int((date - episode["entry_date"]).days),
                "had_partial_exit": episode["partial_exit_count"] > 0,
                "exit_reason": reason,
            }
        )
        del active[symbol]

    for episode in active.values():
        records.append(
            {
                **episode,
                "exit_date": pd.NaT,
                "status": "open",
                "gross_pnl": np.nan,
                "net_pnl": np.nan,
                "net_return": np.nan,
                "holding_days": np.nan,
                "had_partial_exit": episode["partial_exit_count"] > 0,
                "exit_reason": None,
            }
        )

    round_trips = pd.DataFrame(records, columns=columns)
    if not round_trips.empty:
        round_trips.sort_values(
            ["entry_date", "symbol"],
            inplace=True,
            ignore_index=True,
        )
    completed = round_trips.loc[round_trips["status"].eq("closed")]
    winners = completed.loc[completed["net_pnl"].gt(0.0), "net_pnl"].sum()
    losers = completed.loc[completed["net_pnl"].lt(0.0), "net_pnl"].sum()
    profit_factor = (
        float(winners / abs(losers))
        if losers < 0.0
        else (np.inf if winners > 0.0 else np.nan)
    )
    summary = {
        "completed_round_trips": int(len(completed)),
        "open_round_trips": int(round_trips["status"].eq("open").sum()),
        "round_trip_win_rate": (
            float(completed["net_pnl"].gt(0.0).mean())
            if not completed.empty
            else np.nan
        ),
        "round_trip_profit_factor": profit_factor,
        "round_trip_net_pnl": float(completed["net_pnl"].sum()),
        "round_trip_gross_pnl": float(completed["gross_pnl"].sum()),
        "transaction_cost_total": float(
            pd.to_numeric(trades["costs"], errors="coerce").fillna(0.0).sum()
        ),
    }
    return round_trips, summary


class LocalBacktester:
    """事件驱动的日线撮合器，保持聚宽基线的信号和调度顺序。"""

    def __init__(self, data, logic=None, config=None):
        self.data = data
        self.logic = logic if logic is not None else load_baseline_logic()
        self.config = config if config is not None else BacktestConfig()
        self.cash = float(self.config.initial_cash)
        self.positions = {}
        self.frames = {}
        self.trades = []
        self.holding_days = []
        self.excluded = set(self.config.excluded_symbols)
        self.anomaly_records = []

    def _log(self, message):
        if self.config.verbose:
            print(message, flush=True)

    def _prepare_frames(self):
        start_location = self.data.calendar.searchsorted(
            self.config.start_date, side="left"
        )
        warmup_count = max(self.config.history_count + 120, 260)
        warmup_location = max(0, start_location - warmup_count)
        warmup_start = self.data.calendar[warmup_location]
        symbols = self.data.symbols_during(
            self.config.markets,
            self.config.start_date,
            self.config.end_date,
        )
        self._log(
            f"准备 {len(symbols)} 只历史成分股："
            f"{warmup_start.date()} 至 {self.config.end_date.date()}"
        )
        for number, symbol in enumerate(symbols, 1):
            if symbol in self.excluded:
                continue
            raw = self.data.load_symbol_frame(
                symbol, warmup_start, self.config.end_date
            )
            anomalies = find_adjustment_anomalies(
                raw,
                adjusted_threshold=self.config.anomaly_adjusted_return,
            )
            if not anomalies.empty:
                self.excluded.add(symbol)
                annotated = anomalies.copy()
                annotated.insert(0, "symbol", symbol)
                self.anomaly_records.append(annotated)
                continue
            indicator = self.logic.build_indicator_frame(raw[["close", "money"]])
            for column in (
                "open",
                "high",
                "low",
                "volume",
                "factor",
                "amount",
                "raw_open",
                "raw_close",
            ):
                indicator[column] = raw[column]
            self.frames[symbol] = indicator
            if self.config.verbose and number % 100 == 0:
                self._log(f"指标准备进度：{number}/{len(symbols)}")

    def _window(self, symbol, observation_date):
        frame = self.frames.get(symbol)
        if frame is None:
            return None
        window = frame.loc[:observation_date].tail(self.config.history_count)
        if len(window) < self.config.min_signal_rows:
            return None
        return window

    def _execution_row(self, symbol, trade_date):
        frame = self.frames.get(symbol)
        if frame is None or trade_date not in frame.index:
            return None
        return frame.loc[trade_date]

    @staticmethod
    def _is_locked_bar(row):
        values = [row.get("open"), row.get("high"), row.get("low")]
        if not all(np.isfinite(value) for value in values):
            return True
        scale = max(abs(float(values[0])), 1.0)
        return max(values) - min(values) <= scale * 1.0e-8

    def _is_tradeable(self, row):
        if row is None:
            return False
        required = ("open", "factor", "raw_open", "volume")
        if not all(np.isfinite(row.get(column, np.nan)) for column in required):
            return False
        if (
            float(row["open"]) <= 0
            or float(row["factor"]) <= 0
            or float(row["raw_open"]) <= 0
            or float(row["volume"]) <= 0
        ):
            return False
        return not self._is_locked_bar(row)

    def _position_open_value(self, trade_date):
        total = self.cash
        for symbol, position in self.positions.items():
            row = self._execution_row(symbol, trade_date)
            if row is not None and np.isfinite(row.get("open", np.nan)):
                price = float(row["open"])
            else:
                price = float(position.last_mark)
            if np.isfinite(price):
                total += position.units * price
        return float(total)

    def _record_trade(
        self,
        *,
        date,
        observation_date,
        symbol,
        side,
        reason,
        kind,
        score,
        shares,
        units,
        raw_price,
        adjusted_price,
        gross,
        costs,
    ):
        self.trades.append(
            {
                "date": pd.Timestamp(date),
                "observation_date": pd.Timestamp(observation_date),
                "symbol": symbol,
                "side": side,
                "reason": reason,
                "kind": kind,
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

    def _buy(self, symbol, trade_date, observation_date, budget, signal):
        row = self._execution_row(symbol, trade_date)
        if not self._is_tradeable(row):
            return 0.0
        raw_price = execution_raw_price(float(row["raw_open"]), "buy", self.config)
        shares = affordable_board_lot(
            budget=budget,
            cash=self.cash,
            raw_price=float(row["raw_open"]),
            config=self.config,
        )
        if shares < self.config.board_lot:
            return 0.0
        gross = shares * raw_price
        costs = transaction_cost(gross, "buy", self.config)
        if gross + costs > self.cash + 1.0e-8:
            return 0.0
        factor = float(row["factor"])
        units = shares / factor
        adjusted_price = raw_price * factor
        self.cash -= gross + costs
        self.positions[symbol] = Position(
            symbol=symbol,
            units=units,
            avg_adjusted_cost=adjusted_price,
            entry_date=pd.Timestamp(trade_date),
            half_reduced=False,
            last_mark=float(row["open"]),
        )
        self._record_trade(
            date=trade_date,
            observation_date=observation_date,
            symbol=symbol,
            side="buy",
            reason=f"entry_{signal['kind']}",
            kind=signal["kind"],
            score=signal["score"],
            shares=shares,
            units=units,
            raw_price=raw_price,
            adjusted_price=adjusted_price,
            gross=gross,
            costs=costs,
        )
        return float(gross)

    def _sell(
        self,
        symbol,
        trade_date,
        observation_date,
        decision,
        reason=None,
    ):
        position = self.positions[symbol]
        row = self._execution_row(symbol, trade_date)
        if not self._is_tradeable(row):
            return 0.0
        factor = float(row["factor"])
        current_shares = max(int(round(position.units * factor)), 0)
        if decision == "half":
            target_shares = (
                int((current_shares * 0.5) // self.config.board_lot)
                * self.config.board_lot
            )
            if (
                target_shares < self.config.board_lot
                or target_shares >= current_shares
            ):
                return 0.0
            shares = current_shares - target_shares
            units = shares / factor
        else:
            shares = current_shares
            units = position.units
        if shares <= 0 or units <= 0:
            return 0.0
        raw_price = execution_raw_price(float(row["raw_open"]), "sell", self.config)
        adjusted_price = raw_price * factor
        gross = units * adjusted_price
        costs = transaction_cost(gross, "sell", self.config)
        self.cash += gross - costs
        self._record_trade(
            date=trade_date,
            observation_date=observation_date,
            symbol=symbol,
            side="sell",
            reason=reason if reason is not None else f"exit_{decision}",
            kind=None,
            score=np.nan,
            shares=shares,
            units=units,
            raw_price=raw_price,
            adjusted_price=adjusted_price,
            gross=gross,
            costs=costs,
        )
        if decision == "full":
            self.holding_days.append(
                int((pd.Timestamp(trade_date) - position.entry_date).days)
            )
            del self.positions[symbol]
        else:
            position.units -= units
            position.half_reduced = True
        return float(gross)

    def _mark_close(self, trade_date):
        market_value = 0.0
        for symbol, position in self.positions.items():
            row = self._execution_row(symbol, trade_date)
            if row is not None and np.isfinite(row.get("close", np.nan)):
                position.last_mark = float(row["close"])
            if np.isfinite(position.last_mark):
                market_value += position.units * position.last_mark
        return float(market_value)

    def _weekly_scan_dates(self, trade_dates):
        periods = trade_dates.to_period("W-SUN")
        result = set()
        for period in periods.unique():
            result.add(trade_dates[periods == period][0])
        return result

    def _benchmark_values(self, trade_dates):
        prior = self.data.previous_trade_date(trade_dates[0])
        benchmark = self.data.load_symbol_frame(
            self.config.benchmark_symbol,
            prior,
            trade_dates[-1],
        )["close"].ffill()
        base = benchmark.loc[:prior].dropna()
        if base.empty:
            base = benchmark.dropna().head(1)
        if base.empty:
            raise ValueError("benchmark has no valid close data")
        normalized = benchmark / float(base.iloc[-1])
        return normalized.reindex(trade_dates).ffill()

    def run(self):
        started = time.perf_counter()
        trade_dates = self.data.trade_dates(
            self.config.start_date, self.config.end_date
        )
        if trade_dates.empty:
            raise ValueError("backtest period contains no trading dates")
        self._prepare_frames()
        weekly_scan_dates = self._weekly_scan_dates(trade_dates)
        benchmark_values = self._benchmark_values(trade_dates)
        equity_rows = []
        progress_year = None

        for trade_date in trade_dates:
            if self.config.verbose and trade_date.year != progress_year:
                progress_year = trade_date.year
                self._log(f"撮合进度：{progress_year}")
            observation_date = self.data.previous_trade_date(trade_date)
            gross_traded = 0.0

            for symbol in list(self.positions):
                window = self._window(symbol, observation_date)
                if window is None:
                    continue
                position = self.positions[symbol]
                decision = self.logic.exit_decision(
                    window,
                    avg_cost=position.avg_adjusted_cost,
                    half_reduced=position.half_reduced,
                )
                if decision in {"full", "half"}:
                    exit_reason = classify_exit_reason(
                        self.logic,
                        window,
                        decision,
                        avg_cost=position.avg_adjusted_cost,
                        half_reduced=position.half_reduced,
                    )
                    gross_traded += self._sell(
                        symbol,
                        trade_date,
                        observation_date,
                        decision,
                        reason=exit_reason,
                    )

            if (
                trade_date in weekly_scan_dates
                and len(self.positions) < self.config.max_positions
            ):
                signals = []
                for symbol in self.data.members_on(
                    self.config.markets, observation_date
                ):
                    if (
                        symbol in self.positions
                        or symbol in self.excluded
                        or symbol not in self.frames
                    ):
                        continue
                    listing_start = self.data.listing_start(symbol)
                    if (
                        listing_start is None
                        or (observation_date - listing_start).days
                        < self.config.min_listing_days
                    ):
                        continue
                    window = self._window(symbol, observation_date)
                    if window is None:
                        continue
                    signal = entry_signal_for_mode(
                        self.logic,
                        window,
                        self.config.entry_mode,
                    )
                    if signal is not None:
                        signals.append((symbol, signal))
                signals.sort(
                    key=lambda item: (-float(item[1]["score"]), item[0])
                )
                slots = self.config.max_positions - len(self.positions)
                slot_value = (
                    self._position_open_value(trade_date)
                    * self.config.target_gross_exposure
                    / self.config.max_positions
                )
                bought = 0
                for symbol, signal in signals:
                    if bought >= slots:
                        break
                    budget = min(slot_value, self.cash * 0.98)
                    gross = self._buy(
                        symbol,
                        trade_date,
                        observation_date,
                        budget,
                        signal,
                    )
                    if gross > 0:
                        gross_traded += gross
                        bought += 1

            market_value = self._mark_close(trade_date)
            total_equity = self.cash + market_value
            equity_rows.append(
                {
                    "date": trade_date,
                    "equity": total_equity,
                    "cash": self.cash,
                    "market_value": market_value,
                    "positions": len(self.positions),
                    "gross_traded": gross_traded,
                    "benchmark_value": float(benchmark_values.loc[trade_date]),
                }
            )

        equity = pd.DataFrame(equity_rows).set_index("date")
        equity["daily_return"] = equity["equity"].pct_change(fill_method=None)
        equity.iloc[
            0, equity.columns.get_loc("daily_return")
        ] = equity["equity"].iloc[0] / self.config.initial_cash - 1.0
        equity["drawdown"] = (
            equity["equity"] / equity["equity"].cummax() - 1.0
        )
        trades = pd.DataFrame(self.trades)
        if not trades.empty:
            trades["_event_order"] = np.where(
                trades["side"].eq("sell"),
                0,
                1,
            )
            trades.sort_values(
                ["date", "symbol", "_event_order"],
                inplace=True,
            )
            trades.drop(columns=["_event_order"], inplace=True)
            trades.reset_index(drop=True, inplace=True)
        metrics, yearly = calculate_performance(
            equity,
            trade_count=len(trades),
            holding_days=self.holding_days,
            initial_equity=self.config.initial_cash,
        )
        anomalies = (
            pd.concat(self.anomaly_records, ignore_index=True)
            if self.anomaly_records
            else pd.DataFrame(
                columns=[
                    "symbol",
                    "date",
                    "adjusted_return",
                    "raw_return",
                    "previous_factor",
                    "factor",
                ]
            )
        )
        runtime = time.perf_counter() - started
        metrics["runtime_seconds"] = float(runtime)
        metrics["excluded_symbol_count"] = int(len(self.excluded))
        round_trips, attribution = build_round_trip_attribution(trades)
        metrics.update(attribution)
        return BacktestResult(
            config=self.config,
            equity=equity,
            trades=trades,
            metrics=metrics,
            yearly=yearly,
            excluded_symbols=sorted(self.excluded),
            anomalies=anomalies,
            data_fingerprint=self.data.fingerprint(),
            runtime_seconds=runtime,
            holding_days=list(self.holding_days),
            round_trips=round_trips,
            attribution=attribution,
        )


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def _format_percent(value):
    if value is None or not np.isfinite(value):
        return "N/A"
    return f"{float(value):.2%}"


def _format_number(value, digits=2):
    if value is None or not np.isfinite(value):
        return "N/A"
    return f"{float(value):.{digits}f}"


def build_report(result, run_id, variant=None):
    metrics = result.metrics
    variant = result.config.entry_mode if variant is None else str(variant)
    control_description = ENTRY_MODE_DESCRIPTIONS.get(
        result.config.entry_mode,
        "自定义入场控制；退出规则沿用基线。",
    )
    yearly_lines = [
        "| 年份 | 策略 | 沪深300 | 几何超额 |",
        "|---:|---:|---:|---:|",
    ]
    for year, row in result.yearly.iterrows():
        yearly_lines.append(
            f"| {int(year)} | {_format_percent(row['strategy_return'])} | "
            f"{_format_percent(row['benchmark_return'])} | "
            f"{_format_percent(row['excess_return'])} |"
        )
    if metrics["annualized_excess_return"] > 0 and metrics["sharpe"] > 0:
        inference = "全周期风险调整后收益为正，但仍需按既定开发/样本外区间拆分验证。"
    else:
        inference = "当前实验尚未证明优于宽基指数，不应直接进入参数寻优。"
    return f"""# KTV + MACD 本地 Qlib 回测：{variant}

## 结论

{inference}

本报告记录一次固定参数控制实验。结果是策略研究证据，不构成投资建议。

## 事实

- 运行标识：`{run_id}`
- 入场控制：`{variant}`
- 控制定义：{control_description}
- 区间：{result.config.start_date:%Y-%m-%d} 至 {result.config.end_date:%Y-%m-%d}
- 初始资金：{result.config.initial_cash:,.2f} 元
- 数据：Qlib 社区中国日线包，历史沪深300与中证500成分
- 实际交易指令：{int(metrics['trade_count'])}
- 排除证券：{", ".join(result.excluded_symbols) if result.excluded_symbols else "无"}
- 运行耗时：{metrics['runtime_seconds']:.2f} 秒

| 指标 | 策略结果 |
|---|---:|
| 累计收益 | {_format_percent(metrics['total_return'])} |
| 年化收益 | {_format_percent(metrics['annualized_return'])} |
| 沪深300累计收益 | {_format_percent(metrics['benchmark_total_return'])} |
| 沪深300年化收益 | {_format_percent(metrics['benchmark_annualized_return'])} |
| 年化几何超额 | {_format_percent(metrics['annualized_excess_return'])} |
| 最大回撤 | {_format_percent(metrics['max_drawdown'])} |
| 最大回撤区间 | {metrics['max_drawdown_peak']} 至 {metrics['max_drawdown_trough']} |
| Sharpe | {_format_number(metrics['sharpe'])} |
| Calmar | {_format_number(metrics['calmar'])} |
| 年化波动率 | {_format_percent(metrics['annualized_volatility'])} |
| 换手 | {_format_number(metrics['turnover'])} |
| 最长水下期 | {int(metrics['longest_underwater_trading_days'])} 个交易日 |
| 平均持仓期 | {_format_number(metrics['average_holding_days'])} 个自然日 |
| 平均现金比例 | {_format_percent(metrics['average_cash_ratio'])} |
| 完整持仓回合 | {int(metrics['completed_round_trips'])} |
| 持仓回合胜率 | {_format_percent(metrics['round_trip_win_rate'])} |
| 持仓回合 Profit Factor | {_format_number(metrics['round_trip_profit_factor'])} |
| 显式交易成本合计 | {_format_number(metrics['transaction_cost_total'])} 元 |

## 年度表现

{chr(10).join(yearly_lines)}

## 推断

- 本地回测直接调用归档的聚宽基线指标与退出函数；入场控制由归档的本地执行引擎实现。
- 如果交易次数很少，收益、胜率和 Sharpe 的统计意义有限，应优先检查信号覆盖率而不是调参。
- 收益若主要来自少数年份，必须经过滚动窗口和冻结样本外验证。

## 口径限制

- 日线开盘价近似聚宽 09:31/09:35 可成交价。
- 数据包缺少逐日 ST 标签和精确涨跌停价；历史指数成分与一字板规则只能近似过滤。
- 调整价持仓按总收益口径计价，近似现金分红再投资。
- 本地指标从完整预热历史计算，极少数 EMA 阈值边缘信号可能与聚宽160行重算不同。
- 当前固定使用千分之一卖出印花税，没有按历史税率切换。

## 下一步实验

1. 按 README 既定的开发样本与冻结样本外区间分别复算。
2. 运行仅 KTV、仅 MACD、仅左侧、仅右侧等必要对照。
3. 对交易成本、开盘成交和涨跌停近似做敏感性分析。
"""


def archive_result(
    result,
    run_id,
    variant=None,
    archived_at=None,
    strategy_dir=STRATEGY_DIR,
    baseline_path=BASELINE_PATH,
):
    """写入不可变归档；目标目录已存在时拒绝覆盖。"""
    strategy_dir = Path(strategy_dir).resolve()
    baseline_path = Path(baseline_path).resolve()
    variant = result.config.entry_mode if variant is None else str(variant)
    variant = variant.strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", variant):
        raise ValueError(f"invalid archive variant: {variant}")
    if not (
        variant == result.config.entry_mode
        or variant.startswith(f"{result.config.entry_mode}-")
    ):
        raise ValueError(
            "archive variant must equal or extend the executed entry_mode"
        )
    archived_at = (
        pd.Timestamp.today().normalize()
        if archived_at is None
        else pd.Timestamp(archived_at).normalize()
    )
    target = (
        strategy_dir
        / "backtests"
        / f"{archived_at:%Y-%m-%d}__{variant}__{run_id}"
    )
    if target.exists():
        raise FileExistsError(f"archive already exists: {target}")
    raw_dir = target / "raw"
    target.mkdir(parents=True)
    raw_dir.mkdir()

    source_target = target / "source.py"
    engine_target = target / "engine.py"
    shutil.copy2(baseline_path, source_target)
    shutil.copy2(Path(__file__).resolve(), engine_target)

    equity_output = result.equity.reset_index()
    equity_output.to_csv(raw_dir / "equity.csv", index=False, encoding="utf-8")
    result.trades.to_csv(raw_dir / "trades.csv", index=False, encoding="utf-8")
    result.round_trips.to_csv(
        raw_dir / "round_trips.csv",
        index=False,
        encoding="utf-8",
    )
    result.yearly.reset_index().to_csv(
        raw_dir / "yearly.csv", index=False, encoding="utf-8"
    )
    if not result.anomalies.empty:
        result.anomalies.to_csv(
            raw_dir / "anomalies.csv", index=False, encoding="utf-8"
        )

    config_payload = _json_safe(asdict(result.config))
    (target / "config.json").write_text(
        json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "strategy_id": "ktv-macd-resonance",
        "variant": variant,
        "experiment": {
            "entry_mode": result.config.entry_mode,
            "entry_control": ENTRY_MODE_DESCRIPTIONS[result.config.entry_mode],
            "exit_logic": "baseline unchanged",
        },
        "platform": "joinquant",
        "engine": "local-qlib-daily-v1",
        "run_id": run_id,
        "archived_at": archived_at.strftime("%Y-%m-%d"),
        "source_file": "source.py",
        "source_sha256": sha256_file(source_target),
        "engine_file": "engine.py",
        "engine_sha256": sha256_file(engine_target),
        "period": {
            "start": result.config.start_date.strftime("%Y-%m-%d"),
            "end": result.config.end_date.strftime("%Y-%m-%d"),
        },
        "benchmark": result.config.benchmark_symbol,
        "initial_cash": result.config.initial_cash,
        "costs": {
            "commission_rate": result.config.commission_rate,
            "minimum_commission": result.config.minimum_commission,
            "sell_tax_rate": result.config.sell_tax_rate,
            "fixed_slippage_per_share": result.config.fixed_slippage_per_share,
        },
        "data_fingerprint": result.data_fingerprint,
        "excluded_symbols": result.excluded_symbols,
        "metrics": _json_safe(result.metrics),
        "artifacts": {
            "equity": "raw/equity.csv",
            "trades": "raw/trades.csv",
            "round_trips": "raw/round_trips.csv",
            "yearly": "raw/yearly.csv",
            "anomalies": (
                "raw/anomalies.csv" if not result.anomalies.empty else None
            ),
            "config": "config.json",
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "report.md").write_text(
        build_report(result, run_id, variant=variant),
        encoding="utf-8",
    )
    return target
