"""欧奈尔 CAN SLIM 基线的本地 Qlib + 东方财富日线回测器。

平台策略仍以 ``baseline.py`` 为事实源。本文件只负责把本地 Qlib 行情、历史指数成分和
带公告日的财务缓存转换为基线纯函数需要的输入，并用次日开盘价近似聚宽 10:00 执行。
"""

import hashlib
import importlib.util
import json
import math
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parent
BASELINE_PATH = STRATEGY_DIR / "baseline.py"
COMMON_ENGINE_PATH = (
    STRATEGY_DIR.parent / "ktv-macd-resonance" / "local_backtest.py"
)
ARCHIVED_COMMON_ENGINE_PATH = STRATEGY_DIR / "common_engine.py"
DEFAULT_MARKETS = ("csi300", "csi500")
REQUIRED_PRICE_FIELDS = ("open", "high", "low", "close", "volume", "money")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_baseline_logic(path=BASELINE_PATH):
    return _load_module("oneil_canslim_joinquant_baseline", path)


def load_common_engine():
    path = (
        ARCHIVED_COMMON_ENGINE_PATH
        if ARCHIVED_COMMON_ENGINE_PATH.is_file()
        else COMMON_ENGINE_PATH
    )
    return _load_module("oneil_local_common_engine", path)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def eastmoney_code(symbol):
    symbol = str(symbol).strip().upper()
    if len(symbol) == 8 and symbol[:2] in {"SH", "SZ", "BJ"}:
        return f"{symbol[2:]}.{symbol[:2]}"
    raise ValueError(f"不支持的 Qlib 证券代码：{symbol}")


def qlib_symbol(code):
    value = str(code).strip().upper()
    if "." not in value:
        raise ValueError(f"不支持的东方财富证券代码：{code}")
    digits, market = value.split(".", 1)
    if market not in {"SH", "SZ", "BJ"} or len(digits) != 6:
        raise ValueError(f"不支持的东方财富证券代码：{code}")
    return f"{market}{digits}"


def _numeric(frame, column):
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def cumulative_to_single_quarter(reports):
    """把利润表累计值拆为单季度，并保留原始年报值。

    缺少紧邻的上一季度累计报告时不做猜测，相关单季度字段保持空值。
    """
    expected = [
        "symbol",
        "report_date",
        "notice_date",
        "basic_eps",
        "adjusted_profit",
        "parent_net_profit",
        "revenue",
        "roe",
    ]
    if reports is None or reports.empty:
        return pd.DataFrame(
            columns=expected
            + [
                "quarter_basic_eps",
                "quarter_adjusted_profit",
                "quarter_parent_net_profit",
                "quarter_revenue",
                "annual_basic_eps",
                "annual_roe",
            ]
        )
    frame = reports.copy()
    for column in expected:
        if column not in frame.columns:
            frame[column] = np.nan
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["report_date"] = pd.to_datetime(frame["report_date"], errors="coerce")
    frame["notice_date"] = pd.to_datetime(frame["notice_date"], errors="coerce")
    for column in (
        "basic_eps",
        "adjusted_profit",
        "parent_net_profit",
        "revenue",
        "roe",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["symbol", "report_date", "notice_date"])
        .sort_values(["symbol", "report_date", "notice_date"])
        .drop_duplicates(["symbol", "report_date"], keep="last")
        .reset_index(drop=True)
    )
    frame["quarter"] = frame["report_date"].dt.quarter
    frame["year"] = frame["report_date"].dt.year
    flow_columns = (
        ("basic_eps", "quarter_basic_eps"),
        ("adjusted_profit", "quarter_adjusted_profit"),
        ("parent_net_profit", "quarter_parent_net_profit"),
        ("revenue", "quarter_revenue"),
    )
    for _, output in flow_columns:
        frame[output] = np.nan

    for _, indices in frame.groupby(["symbol", "year"], sort=False).groups.items():
        ordered = frame.loc[list(indices)].sort_values("report_date")
        previous = None
        for index, row in ordered.iterrows():
            quarter = int(row["quarter"])
            for source, output in flow_columns:
                value = row[source]
                if quarter == 1:
                    frame.at[index, output] = value
                elif previous is not None and int(previous["quarter"]) == quarter - 1:
                    prior = previous[source]
                    if np.isfinite(value) and np.isfinite(prior):
                        frame.at[index, output] = value - prior
            previous = row

    is_annual = frame["quarter"].eq(4)
    frame["annual_basic_eps"] = frame["basic_eps"].where(is_annual)
    frame["annual_roe"] = frame["roe"].where(is_annual)
    return frame.drop(columns=["quarter", "year"]).reset_index(drop=True)


class FinancialDataPortal:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.financial_path = self.root / "financials.parquet"
        self.industry_path = self.root / "industries.csv"
        if not self.financial_path.is_file():
            raise FileNotFoundError(f"财务缓存不存在：{self.financial_path}")
        if not self.industry_path.is_file():
            raise FileNotFoundError(f"行业缓存不存在：{self.industry_path}")
        frame = pd.read_parquet(self.financial_path)
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame["report_date"] = pd.to_datetime(frame["report_date"], errors="coerce")
        frame["notice_date"] = pd.to_datetime(frame["notice_date"], errors="coerce")
        self.frame = frame.dropna(
            subset=["symbol", "report_date", "notice_date"]
        ).sort_values(["symbol", "notice_date", "report_date"])
        self.by_symbol = {
            symbol: group.reset_index(drop=True)
            for symbol, group in self.frame.groupby("symbol", sort=False)
        }
        industries = pd.read_csv(self.industry_path, dtype=str)
        industries["symbol"] = industries["symbol"].astype(str).str.upper()
        self.industries = industries.drop_duplicates("symbol").set_index("symbol")

    def industry(self, symbol):
        symbol = str(symbol).upper()
        if symbol not in self.industries.index:
            return "未知行业"
        value = self.industries.at[symbol, "industry"]
        return str(value) if pd.notna(value) and str(value).strip() else "未知行业"

    def name(self, symbol):
        symbol = str(symbol).upper()
        if symbol not in self.industries.index or "name" not in self.industries:
            return ""
        value = self.industries.at[symbol, "name"]
        return str(value) if pd.notna(value) else ""

    def histories(self, symbol, observation_date):
        symbol = str(symbol).upper()
        observation_date = pd.Timestamp(observation_date).normalize()
        frame = self.by_symbol.get(symbol)
        empty = pd.DataFrame()
        if frame is None:
            return SimpleNamespace(quarterly=empty, annual=empty)
        visible = frame.loc[
            frame["notice_date"].le(observation_date)
            & frame["report_date"].le(observation_date)
        ].copy()
        if visible.empty:
            return SimpleNamespace(quarterly=empty, annual=empty)
        quarterly = pd.DataFrame(
            {
                "code": visible["symbol"],
                "statDate": visible["report_date"],
                "basic_eps": visible["quarter_basic_eps"],
                "adjusted_profit": visible["quarter_adjusted_profit"],
                "np_parent_company_owners": visible[
                    "quarter_parent_net_profit"
                ],
                "total_operating_revenue": visible["quarter_revenue"],
            }
        )
        annual_rows = visible.loc[visible["report_date"].dt.quarter.eq(4)]
        annual = pd.DataFrame(
            {
                "code": annual_rows["symbol"],
                "statDate": annual_rows["report_date"],
                "basic_eps": annual_rows["annual_basic_eps"],
                "adjusted_profit": annual_rows["adjusted_profit"],
                "np_parent_company_owners": annual_rows["parent_net_profit"],
                "total_operating_revenue": annual_rows["revenue"],
                "roe": annual_rows["annual_roe"],
            }
        )
        return SimpleNamespace(
            quarterly=quarterly.reset_index(drop=True),
            annual=annual.reset_index(drop=True),
        )

    def fingerprint(self):
        return {
            "root": str(self.root),
            "financials": {
                "rows": int(len(self.frame)),
                "symbols": int(self.frame["symbol"].nunique()),
                "first_report": self.frame["report_date"].min().strftime("%Y-%m-%d"),
                "last_report": self.frame["report_date"].max().strftime("%Y-%m-%d"),
                "sha256": sha256_file(self.financial_path),
            },
            "industries": {
                "rows": int(len(self.industries)),
                "sha256": sha256_file(self.industry_path),
            },
        }


@dataclass
class BacktestConfig:
    start_date: pd.Timestamp | str = "2019-01-01"
    end_date: pd.Timestamp | str = "2025-12-31"
    initial_cash: float = 1_000_000.0
    markets: tuple[str, ...] = DEFAULT_MARKETS
    benchmark_symbol: str = "SZ399300"
    market_symbol: str = "SZ399300"
    board_lot: int = 100
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    sell_tax_rate: float = 0.001
    fixed_slippage_per_share: float = 0.002
    max_positions: int = 6
    verbose: bool = False

    def __post_init__(self):
        self.start_date = pd.Timestamp(self.start_date).normalize()
        self.end_date = pd.Timestamp(self.end_date).normalize()
        self.markets = tuple(self.markets)
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be later than end_date")
        if self.initial_cash <= 0 or self.max_positions <= 0:
            raise ValueError("initial_cash and max_positions must be positive")


@dataclass
class Position:
    symbol: str
    units: float
    avg_adjusted_cost: float
    initial_adjusted_price: float
    entry_date: pd.Timestamp
    pivot: float
    stage: int = 1
    power_hold_until: pd.Timestamp | None = None
    last_mark: float = np.nan


@dataclass
class BacktestResult:
    config: BacktestConfig
    equity: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict
    yearly: pd.DataFrame
    scans: pd.DataFrame
    anomalies: pd.DataFrame
    qlib_fingerprint: dict
    financial_fingerprint: dict
    runtime_seconds: float
    holding_days: list[int]


class LocalBacktester:
    def __init__(self, data, financials, config=None, logic=None, common=None):
        self.data = data
        self.financials = financials
        self.config = config if config is not None else BacktestConfig()
        self.logic = logic if logic is not None else load_baseline_logic()
        self.common = common if common is not None else load_common_engine()
        self.cash = float(self.config.initial_cash)
        self.positions = {}
        self.frames = {}
        self.trades = []
        self.scans = []
        self.anomaly_records = []
        self.excluded = set()
        self.holding_days = []
        self.watchlist = []
        self.candidate_meta = {}

    def _log(self, message):
        if self.config.verbose:
            print(message, flush=True)

    def _prepare_frames(self):
        start_index = self.data.calendar.searchsorted(self.config.start_date, side="left")
        warmup_index = max(0, start_index - self.logic.MARKET_LOOKBACK - 20)
        warmup_start = self.data.calendar[warmup_index]
        symbols = set(
            self.data.symbols_during(
                self.config.markets,
                self.config.start_date,
                self.config.end_date,
            )
        )
        symbols.update({self.config.market_symbol, self.config.benchmark_symbol})
        self._log(
            f"准备 {len(symbols)} 只证券：{warmup_start.date()} 至 "
            f"{self.config.end_date.date()}"
        )
        for number, symbol in enumerate(sorted(symbols), 1):
            raw = self.data.load_symbol_frame(
                symbol, warmup_start, self.config.end_date
            )
            anomalies = self.common.find_adjustment_anomalies(raw)
            if not anomalies.empty:
                self.excluded.add(symbol)
                annotated = anomalies.copy()
                annotated.insert(0, "symbol", symbol)
                self.anomaly_records.append(annotated)
                continue
            self.frames[symbol] = raw
            if self.config.verbose and number % 100 == 0:
                self._log(f"行情准备进度：{number}/{len(symbols)}")

    def _frame(self, symbol, observation_date, count):
        frame = self.frames.get(symbol)
        if frame is None:
            return None
        result = frame.loc[:observation_date].tail(count)
        return result if not result.empty else None

    def _logic_frame(self, symbol, observation_date, count):
        frame = self._frame(symbol, observation_date, count)
        if frame is None:
            return None
        result = frame.loc[:, list(REQUIRED_PRICE_FIELDS)].copy()
        result = result.reset_index().rename(columns={"date": "time"})
        result["code"] = symbol
        return result

    def _execution_row(self, symbol, trade_date):
        frame = self.frames.get(symbol)
        if frame is None or trade_date not in frame.index:
            return None
        return frame.loc[trade_date]

    def _is_tradeable(self, row):
        if row is None:
            return False
        required = ("open", "factor", "raw_open", "volume")
        if not all(np.isfinite(row.get(column, np.nan)) for column in required):
            return False
        if any(float(row[column]) <= 0 for column in required):
            return False
        values = [row.get("open"), row.get("high"), row.get("low")]
        scale = max(abs(float(values[0])), 1.0)
        return max(values) - min(values) > scale * 1.0e-8

    def _weekly_scan_dates(self, trade_dates):
        periods = trade_dates.to_period("W-SUN")
        return {
            trade_dates[periods == period][0]
            for period in periods.unique()
        }

    def _refresh_watchlist(self, observation_date):
        members = [
            symbol
            for symbol in self.data.members_on(self.config.markets, observation_date)
            if symbol in self.frames
            and symbol not in self.excluded
            and self.data.listing_start(symbol) is not None
            and (observation_date - self.data.listing_start(symbol)).days
            >= self.logic.MIN_LISTING_DAYS
            and "ST" not in self.financials.name(symbol).upper()
        ]
        liquid = []
        close_frames = []
        industries = {}
        for symbol in members:
            frame = self._logic_frame(symbol, observation_date, self.logic.PRICE_LOOKBACK)
            if frame is None or len(frame) < self.logic.MIN_RS_HISTORY:
                continue
            if frame["money"].tail(20).mean() < self.logic.MIN_AVERAGE_MONEY:
                continue
            liquid.append(symbol)
            close_frames.append(frame[["time", "code", "close"]])
            industries[symbol] = self.financials.industry(symbol)
        relative = self.logic.build_relative_strength_features(
            pd.concat(close_frames, ignore_index=True)
            if close_frames
            else pd.DataFrame(),
            industries,
        )
        leaders = (
            relative.loc[
                relative["rs_rating"].ge(self.logic.MIN_RS_RATING)
                & relative["industry_rs_rating"].ge(
                    self.logic.MIN_INDUSTRY_RS_RATING
                )
                & relative["trend_ok"]
                & relative["near_high"]
            ].copy()
            if not relative.empty
            else pd.DataFrame()
        )
        full_frames = []
        if not leaders.empty:
            for symbol in leaders["code"]:
                frame = self._logic_frame(
                    symbol, observation_date, self.logic.PRICE_LOOKBACK
                )
                if frame is not None:
                    full_frames.append(frame)
        price_features = self.logic.build_price_features(
            pd.concat(full_frames, ignore_index=True)
            if full_frames
            else pd.DataFrame(),
            industries=industries,
        )
        if not price_features.empty and not leaders.empty:
            ranking_columns = [
                "code",
                "relative_strength_raw",
                "rs_rating",
                "industry_rs_rating",
                "industry",
            ]
            price_features = price_features.drop(
                columns=[
                    column
                    for column in ranking_columns[1:]
                    if column in price_features.columns
                ]
            ).merge(leaders[ranking_columns], on="code", how="inner")
            price_candidates = price_features.loc[
                price_features["rs_rating"].ge(self.logic.MIN_RS_RATING)
                & price_features["industry_rs_rating"].ge(
                    self.logic.MIN_INDUSTRY_RS_RATING
                )
                & price_features["setup_ready"]
            ].copy()
        else:
            price_candidates = pd.DataFrame()

        fundamental_rows = []
        missing_financials = 0
        for symbol in (
            price_candidates["code"].tolist()
            if not price_candidates.empty
            else []
        ):
            histories = self.financials.histories(symbol, observation_date)
            features = self.logic.build_fundamental_features(
                symbol,
                histories.quarterly,
                histories.annual,
                observation_date=observation_date,
            )
            if features is None:
                missing_financials += 1
            else:
                fundamental_rows.append(features)
        fundamentals = pd.DataFrame(fundamental_rows)
        ranked = self.logic.score_candidates(fundamentals, price_candidates)
        eligible = (
            ranked.loc[ranked["eligible"]].head(self.logic.WATCHLIST_SIZE)
            if not ranked.empty
            else pd.DataFrame()
        )
        self.watchlist = eligible["code"].tolist() if not eligible.empty else []
        self.candidate_meta = (
            {row["code"]: row for row in eligible.to_dict("records")}
            if not eligible.empty
            else {}
        )
        self.scans.append(
            {
                "observation_date": pd.Timestamp(observation_date),
                "universe": len(members),
                "liquid": len(liquid),
                "leaders": len(leaders),
                "price_candidates": len(price_candidates),
                "fundamental_features": len(fundamentals),
                "missing_financials": missing_financials,
                "eligible": len(eligible),
            }
        )

    def _market(self, observation_date):
        frame = self._logic_frame(
            self.config.market_symbol,
            observation_date,
            self.logic.MARKET_LOOKBACK,
        )
        return self.logic.classify_market_regime(frame)

    def _portfolio_value(self, trade_date, field="open"):
        total = self.cash
        for symbol, position in self.positions.items():
            row = self._execution_row(symbol, trade_date)
            price = (
                float(row[field])
                if row is not None and np.isfinite(row.get(field, np.nan))
                else float(position.last_mark)
            )
            if np.isfinite(price):
                total += position.units * price
        return float(total)

    def _record_trade(
        self,
        date,
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
                "date": pd.Timestamp(date),
                "observation_date": pd.Timestamp(observation_date),
                "symbol": symbol,
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

    def _buy(self, symbol, trade_date, observation_date, target_value, reason, pivot):
        row = self._execution_row(symbol, trade_date)
        if not self._is_tradeable(row):
            return 0.0
        current_value = 0.0
        if symbol in self.positions:
            current_value = self.positions[symbol].units * float(row["open"])
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
        if gross + costs > self.cash + 1e-8:
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
            position.stage += 1
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                units=units,
                avg_adjusted_cost=adjusted_price,
                initial_adjusted_price=adjusted_price,
                entry_date=pd.Timestamp(trade_date),
                pivot=float(pivot),
                stage=1,
                last_mark=float(row["open"]),
            )
        self._record_trade(
            trade_date,
            observation_date,
            symbol,
            "buy",
            reason,
            shares,
            units,
            raw_price,
            adjusted_price,
            gross,
            costs,
            score=self.candidate_meta.get(symbol, {}).get("score", np.nan),
        )
        return float(gross)

    def _sell(self, symbol, trade_date, observation_date, reason):
        position = self.positions[symbol]
        row = self._execution_row(symbol, trade_date)
        if not self._is_tradeable(row):
            return 0.0
        factor = float(row["factor"])
        shares = max(int(round(position.units * factor)), 0)
        if shares <= 0:
            return 0.0
        raw_price = self.common.execution_raw_price(
            float(row["raw_open"]), "sell", self.config
        )
        adjusted_price = raw_price * factor
        gross = position.units * adjusted_price
        costs = self.common.transaction_cost(gross, "sell", self.config)
        self.cash += gross - costs
        self._record_trade(
            trade_date,
            observation_date,
            symbol,
            "sell",
            reason,
            shares,
            position.units,
            raw_price,
            adjusted_price,
            gross,
            costs,
        )
        self.holding_days.append(
            int((pd.Timestamp(trade_date) - position.entry_date).days)
        )
        del self.positions[symbol]
        return float(gross)

    def _exit_reason(self, symbol, observation_date, trade_date, market_state):
        position = self.positions[symbol]
        history = self._logic_frame(
            symbol, observation_date, self.logic.PRICE_LOOKBACK
        )
        row = self._execution_row(symbol, trade_date)
        if history is None or row is None:
            return None
        current_price = float(row["open"])
        gain = self.logic.safe_growth(
            current_price, position.initial_adjusted_price
        )
        holding_days = max(0, (trade_date - position.entry_date).days)
        if (
            np.isfinite(gain)
            and gain >= self.logic.FAST_GAIN
            and holding_days <= self.logic.FAST_GAIN_DAYS
            and position.power_hold_until is None
        ):
            position.power_hold_until = position.entry_date + pd.Timedelta(
                days=self.logic.POWER_HOLD_DAYS
            )
        power_hold = (
            position.power_hold_until is not None
            and trade_date < position.power_hold_until
        )
        closes = pd.to_numeric(history["close"], errors="coerce")
        volumes = pd.to_numeric(history["volume"], errors="coerce")
        ma50 = closes.tail(50).mean() if len(closes) >= 50 else np.nan
        volume_ratio = (
            self.logic.safe_divide(volumes.iloc[-1], volumes.iloc[-51:-1].mean())
            if len(volumes) >= 51
            else np.nan
        )
        return self.logic.position_exit_reason(
            current_price=current_price,
            technical_close=closes.iloc[-1],
            average_cost=position.avg_adjusted_cost,
            pivot=position.pivot,
            holding_days=holding_days,
            close_50d_ma=ma50,
            volume_ratio=volume_ratio,
            market_state=market_state,
            power_hold=power_hold,
        )

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
            raise ValueError("backtest period contains no trading dates")
        self._prepare_frames()
        weekly_scan_dates = self._weekly_scan_dates(trade_dates)
        benchmark_values = self._benchmark_values(trade_dates)
        equity_rows = []
        progress_year = None

        for trade_date in trade_dates:
            if self.config.verbose and progress_year != trade_date.year:
                progress_year = trade_date.year
                self._log(f"撮合进度：{progress_year}")
            observation_date = self.data.previous_trade_date(trade_date)
            if trade_date in weekly_scan_dates:
                self._refresh_watchlist(observation_date)
            market = self._market(observation_date)
            gross_traded = 0.0
            exit_signals = []
            for symbol in list(self.positions):
                reason = self._exit_reason(
                    symbol, observation_date, trade_date, market["state"]
                )
                if reason is None:
                    continue
                exit_signals.append((symbol, reason))
                gross_traded += self._sell(
                    symbol, trade_date, observation_date, reason
                )

            if not exit_signals and market["state"] == self.logic.MARKET_CONFIRMED:
                total_value = self._portfolio_value(trade_date, "open")
                for symbol in list(self.positions):
                    position = self.positions[symbol]
                    row = self._execution_row(symbol, trade_date)
                    if row is None:
                        continue
                    target_weight, next_stage = self.logic.pyramid_target(
                        position.stage,
                        float(row["open"]),
                        position.initial_adjusted_price,
                        pivot=position.pivot,
                    )
                    if next_stage > position.stage:
                        gross_traded += self._buy(
                            symbol,
                            trade_date,
                            observation_date,
                            total_value * target_weight,
                            f"pyramid_{next_stage}",
                            position.pivot,
                        )

                slots = self.config.max_positions - len(self.positions)
                for symbol in self.watchlist:
                    if slots <= 0:
                        break
                    if symbol in self.positions:
                        continue
                    history = self._logic_frame(
                        symbol, observation_date, self.logic.PRICE_LOOKBACK
                    )
                    if history is None:
                        continue
                    breakout = self.logic.detect_breakout(history)
                    if not breakout["is_breakout"]:
                        continue
                    row = self._execution_row(symbol, trade_date)
                    if not self._is_tradeable(row):
                        continue
                    current_price = float(row["open"])
                    pivot = float(breakout["pivot"])
                    if (
                        current_price < pivot
                        or current_price
                        > pivot * (1.0 + self.logic.MAX_BUY_ZONE_EXTENSION)
                    ):
                        continue
                    target = total_value * self.logic.INITIAL_POSITION_WEIGHT
                    gross = self._buy(
                        symbol,
                        trade_date,
                        observation_date,
                        target,
                        "breakout_entry",
                        pivot,
                    )
                    if gross > 0:
                        gross_traded += gross
                        slots -= 1

            market_value = 0.0
            for symbol, position in self.positions.items():
                row = self._execution_row(symbol, trade_date)
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
                    "market_state": market["state"],
                    "watchlist_size": len(self.watchlist),
                }
            )

        equity = pd.DataFrame(equity_rows).set_index("date")
        equity["daily_return"] = equity["equity"].pct_change(fill_method=None)
        equity.iloc[0, equity.columns.get_loc("daily_return")] = (
            equity["equity"].iloc[0] / self.config.initial_cash - 1.0
        )
        equity["drawdown"] = equity["equity"] / equity["equity"].cummax() - 1.0
        trades = pd.DataFrame(self.trades)
        metrics, yearly = self.common.calculate_performance(
            equity,
            trade_count=len(trades),
            holding_days=self.holding_days,
            initial_equity=self.config.initial_cash,
        )
        scans = pd.DataFrame(self.scans)
        anomalies = (
            pd.concat(self.anomaly_records, ignore_index=True)
            if self.anomaly_records
            else pd.DataFrame()
        )
        runtime = time.perf_counter() - started
        metrics["runtime_seconds"] = float(runtime)
        metrics["excluded_symbol_count"] = int(len(self.excluded))
        metrics["scan_count"] = int(len(scans))
        metrics["eligible_scan_count"] = int(
            scans["eligible"].gt(0).sum() if not scans.empty else 0
        )
        metrics["average_watchlist_size"] = float(
            scans["eligible"].mean() if not scans.empty else 0.0
        )
        return BacktestResult(
            config=self.config,
            equity=equity,
            trades=trades,
            metrics=metrics,
            yearly=yearly,
            scans=scans,
            anomalies=anomalies,
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


def _format_metric(value, percent=False):
    if value is None or not np.isfinite(float(value)):
        return "N/A"
    return f"{float(value):.2%}" if percent else f"{float(value):.3f}"


def render_report(result, run_id):
    metrics = result.metrics
    return f"""# 欧奈尔 CAN SLIM 本地研究级回测

## 回测事实

- 运行标识：`{run_id}`
- 区间：{result.config.start_date.date()} 至 {result.config.end_date.date()}
- 股票池：历史沪深300 + 中证500成分
- 初始资金：{result.config.initial_cash:,.0f} 元
- 交易次数：{int(metrics.get("trade_count", 0))}
- 累计收益：{_format_metric(metrics.get("total_return"), percent=True)}
- 年化收益：{_format_metric(metrics.get("annualized_return"), percent=True)}
- 基准累计收益：{_format_metric(metrics.get("benchmark_total_return"), percent=True)}
- 最大回撤：{_format_metric(metrics.get("max_drawdown"), percent=True)}
- Sharpe：{_format_metric(metrics.get("sharpe"))}
- Calmar：{_format_metric(metrics.get("calmar"))}
- 换手：{_format_metric(metrics.get("turnover"))}
- 最长水下期：{int(metrics.get("longest_underwater_trading_days", 0))} 个交易日
- 平均观察池：{_format_metric(metrics.get("average_watchlist_size"))} 只
- 有合格候选的周数：{int(metrics.get("eligible_scan_count", 0))} / {int(metrics.get("scan_count", 0))}

## 数据与执行口径

- 行情、复权因子和历史指数成分来自本地 Qlib 社区中国日线数据。
- 本地数据不含上证综指，`M` 状态改用沪深300代理；聚宽基线仍使用上证综指。
- 财务来自东方财富历史主要指标，按公告日控制可见性；累计利润表拆为单季度。
- 信号只使用前一交易日及此前数据，次日开盘价近似聚宽 10:00 成交。
- 费用包含双边万三佣金（最低 5 元）、卖出千一印花税、每股 0.002 元固定滑点。
- 使用 A 股 100 股整手；一字板按日线 OHLC 相等近似为不可交易。

## 已知限制

- 东方财富历史接口可能把后来修订值回填到旧报告，虽然公告日边界正确，仍不是严格 vintage 财报库。
- 行业使用当前东方财富行业作为申万历史行业的代理，存在行业分类回看偏差。
- Qlib 社区数据缺少点时 ST、停牌和精确涨跌停状态；日线开盘也不能精确复刻 10:00 价格。
- 股票池仅覆盖沪深300和中证500历史成分，不是完整 A 股流动性股票池。
- `M` 使用沪深300而非聚宽基线的上证综指，可能改变确认上升和调整期的日期。
- 本结果是研究级本地粗回测，不等同于聚宽官方撮合结果，不能直接视为实盘证据。

## 诊断结论

结果应结合 `raw/scans.csv` 判断严格财务门槛是否导致候选稀疏，并结合
`raw/trades.csv`、年度收益与市场状态检查收益是否集中在少数年份或少数股票。
首次运行不据此调参；任何阈值变化都应建立独立变体并重新归档。
"""


def archive_result(result, run_id, archived_at=None):
    archived_at = pd.Timestamp(
        archived_at if archived_at is not None else pd.Timestamp.now()
    ).normalize()
    target = (
        STRATEGY_DIR
        / "backtests"
        / f"{archived_at:%Y-%m-%d}__baseline__{run_id}"
    )
    if target.exists():
        raise FileExistsError(f"回测归档已存在，禁止覆盖：{target}")
    raw_dir = target / "raw"
    raw_dir.mkdir(parents=True)
    shutil.copy2(BASELINE_PATH, target / "source.py")
    shutil.copy2(Path(__file__), target / "engine.py")
    shutil.copy2(COMMON_ENGINE_PATH, target / "common_engine.py")
    result.equity.to_csv(raw_dir / "equity.csv", encoding="utf-8-sig")
    result.trades.to_csv(raw_dir / "trades.csv", index=False, encoding="utf-8-sig")
    result.yearly.to_csv(raw_dir / "yearly.csv", encoding="utf-8-sig")
    result.scans.to_csv(raw_dir / "scans.csv", index=False, encoding="utf-8-sig")
    result.anomalies.to_csv(
        raw_dir / "anomalies.csv", index=False, encoding="utf-8-sig"
    )
    config_payload = _json_safe(asdict(result.config))
    (target / "config.json").write_text(
        json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "strategy_id": "oneil-canslim-a-share",
        "platform": "joinquant",
        "strategy_family": "oneil-canslim-a-share",
        "variant": "baseline",
        "engine": "local-qlib-eastmoney-daily-v1",
        "run_id": run_id,
        "archived_at": f"{archived_at:%Y-%m-%d}",
        "period": {
            "start": f"{result.config.start_date:%Y-%m-%d}",
            "end": f"{result.config.end_date:%Y-%m-%d}",
        },
        "benchmark": "沪深300",
        "costs": {
            "commission_rate": result.config.commission_rate,
            "minimum_commission": result.config.minimum_commission,
            "sell_tax_rate": result.config.sell_tax_rate,
            "fixed_slippage_per_share": result.config.fixed_slippage_per_share,
        },
        "metrics": _json_safe(result.metrics),
        "source_file": "source.py",
        "source_sha256": sha256_file(target / "source.py"),
        "engine_file": "engine.py",
        "engine_sha256": sha256_file(target / "engine.py"),
        "common_engine_file": "common_engine.py",
        "common_engine_sha256": sha256_file(target / "common_engine.py"),
        "data": {
            "qlib": result.qlib_fingerprint,
            "financials": result.financial_fingerprint,
        },
        "limitations": [
            "research-grade local backtest, not JoinQuant official matching",
            "current industry proxy instead of point-in-time SW industry",
            "historical financial revisions may be backfilled",
            "CSI300 proxies the Shanghai Composite market regime",
            "daily bars approximate 10:00 execution and limit/paused states",
            "universe limited to historical CSI300 and CSI500 constituents",
        ],
    }
    (target / "manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "report.md").write_text(
        render_report(result, run_id), encoding="utf-8"
    )
    return target
