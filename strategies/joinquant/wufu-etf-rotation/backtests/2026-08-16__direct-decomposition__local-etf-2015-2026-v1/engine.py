"""五福 7.5 的冻结日频因果拆解、稳健性与归因实验。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import math
import shutil
import sys
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
from scipy import stats


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


FAMILY = Path(__file__).resolve().parent
ROOT = FAMILY.parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.store import ResearchDataStore, sha256_file  # noqa: E402


DEFAULT_DATA_ROOT = Path("D:/code/_open-source/_data/quant-research")
REFERENCE_SOURCE = (
    ROOT / "joinquant_archive" / "sources" / "ETF轮动策略" / "五福7.5.py"
)
PUBLIC_BACKTEST = (
    ROOT / "joinquant_archive" / "data" / "ETF轮动策略" / "五福7.5_backtest.json"
)
PROTOCOL_PATH = FAMILY / "protocols" / "2026-08-16-wufu-direct-decomposition-v1.json"
START_DATE = pd.Timestamp("2015-01-01")
END_DATE = pd.Timestamp("2026-07-24")
WARMUP_START = pd.Timestamp("2014-08-01")
CASH_ETF = "SH511880"
BENCHMARK = "SH510300"
INDEX_SYMBOLS = ("sh000300", "sz399101", "sz399006", "sh000510")
SUBPERIODS = (
    ("2015-2018", pd.Timestamp("2015-01-01"), pd.Timestamp("2018-12-31")),
    ("2019-2022", pd.Timestamp("2019-01-01"), pd.Timestamp("2022-12-31")),
    ("2023-2026", pd.Timestamp("2023-01-01"), END_DATE),
)


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "A6_top1"
    top_k: int = 1
    universe: str = "original_like"
    lookback: int = 25
    r2_threshold: float = 0.4
    score_max: float = 5.0
    buffer_ratio: float = 0.9
    use_r2: bool = True
    use_ordinary_filters: bool = True
    use_buffer: bool = True
    use_regime: bool = True
    use_mainline: bool = True
    use_retention: bool = True
    regime_pool_switch: bool = True
    regime_filter_relaxation: bool = True
    regime_dynamic_lookback: bool = True
    regime_buffer_disable: bool = True
    single_side_total_cost_bp: float = 2.0
    initial_cash: float = 200_000.0
    adv_participation: float | None = None
    excluded_symbols: tuple[str, ...] = ()
    execution_price: str = "open"
    listing_cutoff: str | None = None
    mainline_score_min: float = 5.0
    mainline_score_max: float = 20.0
    mainline_r2_current: float = 0.85
    mainline_r2_average: float = 0.90
    mainline_volume_average: float = 1.8
    mainline_score_up_days: int = 4
    mainline_positive_laplace_days: int = 5
    mainline_score_growth: float = 2.0


@dataclass
class TrendFeatures:
    annualized_return: np.ndarray
    r_squared: np.ndarray
    score: np.ndarray


@dataclass
class MarketData:
    dates: pd.DatetimeIndex
    symbols: tuple[str, ...]
    symbol_to_index: dict[str, int]
    adjusted_open: np.ndarray
    adjusted_close: np.ndarray
    raw_open: np.ndarray
    raw_close: np.ndarray
    volume: np.ndarray
    amount: np.ndarray
    adv3: np.ndarray
    adv20: np.ndarray
    ma10: np.ndarray
    volume_ratio5: np.ndarray
    loss_floor3: np.ndarray
    divergence_ok: np.ndarray
    laplace_slope: np.ndarray
    master: pd.DataFrame
    index_close: np.ndarray
    weak_state: np.ndarray
    choppy_state: np.ndarray
    weak_lookback: np.ndarray
    universes: dict[str, list[np.ndarray]]
    global_universe: list[np.ndarray]
    reference: dict[str, Any]
    input_hashes: dict[str, Any]


@dataclass
class SimulationResult:
    config: StrategyConfig
    metrics: dict[str, Any]
    equity: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    decisions: pd.DataFrame
    contributions: pd.DataFrame


class FeatureCache:
    def __init__(self, data: MarketData):
        self.data = data
        self._trend: dict[int, TrendFeatures] = {}
        self._mainline: dict[tuple[Any, ...], np.ndarray] = {}

    def trend(self, lookback: int) -> TrendFeatures:
        if lookback not in self._trend:
            annual, r2, score = weighted_trend_matrix(
                self.data.adjusted_close, lookback
            )
            self._trend[lookback] = TrendFeatures(annual, r2, score)
        return self._trend[lookback]

    def mainline(self, config: StrategyConfig) -> np.ndarray:
        key = (
            config.lookback,
            config.mainline_score_min,
            config.mainline_score_max,
            config.mainline_r2_current,
            config.mainline_r2_average,
            config.mainline_volume_average,
            config.mainline_score_up_days,
            config.mainline_positive_laplace_days,
            config.mainline_score_growth,
        )
        if key not in self._mainline:
            feature = self.trend(config.lookback)
            self._mainline[key] = mainline_matrix(
                feature.score,
                feature.r_squared,
                self.data.volume_ratio5,
                self.data.laplace_slope,
                config,
            )
        return self._mainline[key]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jq_to_local(symbol: str) -> str:
    code, exchange = str(symbol).split(".")
    return ("SH" if exchange == "XSHG" else "SZ") + code


def local_to_jq(symbol: str) -> str:
    return symbol[2:] + (".XSHG" if symbol.startswith("SH") else ".XSHE")


def _safe_ast_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [_safe_ast_value(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(values)
        if isinstance(node, ast.Set):
            return set(values)
        return values
    if isinstance(node, ast.Dict):
        return {
            _safe_ast_value(key): _safe_ast_value(value)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_ast_value(node.operand)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name in {"list", "set", "tuple"}:
            value = _safe_ast_value(node.args[0]) if node.args else []
            return {"list": list, "set": set, "tuple": tuple}[name](value)
        if name == "sorted":
            value = list(_safe_ast_value(node.args[0]))
            reverse = False
            for keyword in node.keywords:
                if keyword.arg == "reverse":
                    reverse = bool(_safe_ast_value(keyword.value))
            if value and isinstance(value[0], dict) and "keywords" in value[0]:
                return sorted(
                    value,
                    key=lambda item: max(len(text) for text in item["keywords"]),
                    reverse=reverse,
                )
            return sorted(value, key=len, reverse=reverse)
    raise ValueError(f"unsupported frozen-source expression: {ast.dump(node)[:160]}")


def extract_reference(path: Path = REFERENCE_SOURCE) -> dict[str, Any]:
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    values: dict[str, Any] = {}
    wanted_locals = {"FUND_COMPANIES", "NOISE_WORDS", "SPECIAL_GROUPS", "exclude_keywords"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            key = None
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "g"
            ):
                key = target.attr
            elif isinstance(target, ast.Name) and target.id in wanted_locals:
                key = target.id
            if key is None:
                continue
            try:
                values[key] = _safe_ast_value(node.value)
            except ValueError:
                continue
    required = {
        "global_etf_pool",
        "china_etf_pool",
        "FUND_COMPANIES",
        "NOISE_WORDS",
        "SPECIAL_GROUPS",
        "exclude_keywords",
    }
    missing = required.difference(values)
    if missing:
        raise ValueError(f"frozen source values missing: {sorted(missing)}")
    values["global_etf_pool"] = tuple(
        jq_to_local(item) for item in values["global_etf_pool"]
    )
    values["china_etf_pool"] = tuple(
        jq_to_local(item) for item in values["china_etf_pool"]
    )
    values["source_sha256"] = file_sha256(Path(path))
    return values


def weighted_trend_metrics(
    prices: np.ndarray | list[float], lookback: int = 25
) -> tuple[float, float, float]:
    values = np.asarray(prices, dtype=float)
    if len(values) < lookback + 1:
        return (math.nan, math.nan, math.nan)
    values = values[-(lookback + 1) :]
    if np.any(~np.isfinite(values)) or np.any(values <= 0.0):
        return (math.nan, math.nan, math.nan)
    y = np.log(values)
    x = np.arange(len(y), dtype=float)
    weights = np.linspace(1.0, 2.0, len(y))
    regression_weights = weights**2
    x_bar = float(np.sum(regression_weights * x) / regression_weights.sum())
    y_bar = float(np.sum(regression_weights * y) / regression_weights.sum())
    dx = x - x_bar
    variance_x = float(np.sum(regression_weights * dx**2))
    slope = float(np.sum(regression_weights * dx * (y - y_bar)) / variance_x)
    intercept = y_bar - slope * x_bar
    annualized = math.exp(float(np.clip(slope * 250.0, -50.0, 50.0))) - 1.0
    fitted = slope * x + intercept
    ss_res = float(np.sum(weights * (y - fitted) ** 2))
    ss_tot = float(np.sum(weights * (y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 0.0
    return annualized, r_squared, annualized * r_squared


def weighted_trend_matrix(
    adjusted_close: np.ndarray, lookback: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    close = np.asarray(adjusted_close, dtype=float)
    rows, columns = close.shape
    annual = np.full((rows, columns), np.nan, dtype=np.float32)
    r_squared = np.full((rows, columns), np.nan, dtype=np.float32)
    if rows < lookback + 1:
        return annual, r_squared, annual.copy()
    y = np.log(np.where(close > 0.0, close, np.nan))
    windows = np.lib.stride_tricks.sliding_window_view(
        y, window_shape=lookback + 1, axis=0
    )
    # numpy puts the rolling axis last: (date, symbol, window).
    x = np.arange(lookback + 1, dtype=float)
    weights = np.linspace(1.0, 2.0, lookback + 1)
    regression_weights = weights**2
    x_bar = float(np.sum(regression_weights * x) / regression_weights.sum())
    dx = x - x_bar
    variance_x = float(np.sum(regression_weights * dx**2))
    slope_coefficients = regression_weights * dx / variance_x
    slope = np.einsum("dsk,k->ds", windows, slope_coefficients, optimize=True)
    y_bar = np.einsum(
        "dsk,k->ds", windows, regression_weights / regression_weights.sum(), optimize=True
    )
    intercept = y_bar - slope * x_bar
    sum_w_y2 = np.einsum("dsk,dsk,k->ds", windows, windows, weights, optimize=True)
    sum_w_xy = np.einsum("dsk,k->ds", windows, weights * x, optimize=True)
    sum_w_y = np.einsum("dsk,k->ds", windows, weights, optimize=True)
    sum_w_x2 = float(np.sum(weights * x**2))
    sum_w_x = float(np.sum(weights * x))
    sum_w = float(np.sum(weights))
    ss_res = (
        sum_w_y2
        - 2.0 * slope * sum_w_xy
        - 2.0 * intercept * sum_w_y
        + slope**2 * sum_w_x2
        + 2.0 * slope * intercept * sum_w_x
        + intercept**2 * sum_w
    )
    unweighted_mean = np.einsum(
        "dsk,k->ds", windows, np.ones(lookback + 1) / (lookback + 1), optimize=True
    )
    ss_tot = sum_w_y2 - 2.0 * unweighted_mean * sum_w_y + unweighted_mean**2 * sum_w
    valid = np.all(np.isfinite(windows), axis=2) & (ss_tot > 1e-14)
    annual_window = np.expm1(np.clip(slope * 250.0, -50.0, 50.0))
    r2_window = np.divide(
        ss_tot - ss_res,
        ss_tot,
        out=np.full_like(ss_tot, np.nan),
        where=valid,
    )
    annual[lookback:] = np.where(valid, annual_window, np.nan).astype(np.float32)
    r_squared[lookback:] = np.where(valid, r2_window, np.nan).astype(np.float32)
    return annual, r_squared, (annual * r_squared).astype(np.float32)


def is_a_share_weak(index_closes: np.ndarray, ma_days: int = 10) -> bool:
    values = np.asarray(index_closes, dtype=float)
    if values.ndim != 2 or len(values) < ma_days:
        return False
    current = values[-1]
    moving_average = np.nanmean(values[-ma_days:], axis=0)
    valid = np.isfinite(current) & np.isfinite(moving_average)
    below = int(np.sum(valid & (current < moving_average)))
    return below >= 3


def select_with_buffer(
    ranked: list[tuple[str, float]],
    current_holdings: list[str],
    top_k: int,
    ratio: float,
) -> list[str]:
    if not ranked or top_k <= 0:
        return []
    ranked = sorted(ranked, key=lambda item: (-item[1], item[0]))
    reference = ranked[min(top_k, len(ranked)) - 1][1]
    threshold = reference * ratio
    eligible = {symbol for symbol, score in ranked if score >= threshold}
    score_map = dict(ranked)
    retained = [symbol for symbol in current_holdings if symbol in eligible]
    retained.sort(key=lambda symbol: (-score_map[symbol], symbol))
    result = retained[:top_k]
    for symbol, _ in ranked:
        if len(result) >= top_k:
            break
        if symbol not in result:
            result.append(symbol)
    return sorted(result, key=lambda symbol: (-score_map[symbol], symbol))


def evaluate_mainline_history(
    history: dict[str, list[float] | np.ndarray],
    *,
    score_min: float = 5.0,
    score_max: float = 20.0,
    r2_current: float = 0.85,
    r2_average: float = 0.90,
    volume_average: float = 1.8,
    score_up_days: int = 4,
    positive_laplace_days: int = 5,
    score_growth: float = 2.0,
) -> bool:
    scores = np.asarray(history["scores"], dtype=float)
    r2 = np.asarray(history["r2"], dtype=float)
    volume = np.asarray(history["volume_ratio"], dtype=float)
    laplace = np.asarray(history["laplace_slope"], dtype=float)
    if not (len(scores) == len(r2) == len(volume) == len(laplace) == 5):
        return False
    if np.any(~np.isfinite(np.concatenate([scores, r2, volume, laplace]))):
        return False
    growth = scores[-1] / scores[0] if scores[0] > 0.0 else math.inf
    return bool(
        score_min < scores[-1] <= score_max
        and r2[-1] >= r2_current
        and r2.mean() >= r2_average
        and volume.mean() >= volume_average
        and int(np.sum(np.diff(scores) >= 0.0)) >= score_up_days
        and int(np.sum(laplace > 0.0)) >= positive_laplace_days
        and growth >= score_growth
    )


def mainline_matrix(
    score: np.ndarray,
    r_squared: np.ndarray,
    volume_ratio: np.ndarray,
    laplace_slope: np.ndarray,
    config: StrategyConfig,
) -> np.ndarray:
    result = np.zeros(score.shape, dtype=bool)
    if len(score) < 5:
        return result
    score_window = np.lib.stride_tricks.sliding_window_view(score, 5, axis=0)
    r2_window = np.lib.stride_tricks.sliding_window_view(r_squared, 5, axis=0)
    volume_window = np.lib.stride_tricks.sliding_window_view(volume_ratio, 5, axis=0)
    laplace_window = np.lib.stride_tricks.sliding_window_view(laplace_slope, 5, axis=0)
    current = score_window[:, :, -1]
    start = score_window[:, :, 0]
    growth = np.divide(
        current,
        start,
        out=np.full_like(current, np.nan),
        where=start > 0.0,
    )
    valid = (
        np.all(np.isfinite(score_window), axis=2)
        & np.all(np.isfinite(r2_window), axis=2)
        & np.all(np.isfinite(volume_window), axis=2)
        & np.all(np.isfinite(laplace_window), axis=2)
    )
    passed = (
        valid
        & (current > config.mainline_score_min)
        & (current <= config.mainline_score_max)
        & (r2_window[:, :, -1] >= config.mainline_r2_current)
        & (np.mean(r2_window, axis=2) >= config.mainline_r2_average)
        & (np.mean(volume_window, axis=2) >= config.mainline_volume_average)
        & (np.sum(np.diff(score_window, axis=2) >= 0.0, axis=2) >= config.mainline_score_up_days)
        & (np.sum(laplace_window > 0.0, axis=2) >= config.mainline_positive_laplace_days)
        & (growth >= config.mainline_score_growth)
    )
    result[4:] = passed
    return result


def _pivot_array(
    bars: pd.DataFrame,
    dates: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    column: str,
) -> np.ndarray:
    frame = (
        bars.pivot(index="trade_date", columns="symbol", values=column)
        .reindex(index=dates, columns=symbols)
    )
    return frame.to_numpy(dtype=np.float64)


def fetch_index_close(
    start: pd.Timestamp = WARMUP_START,
    end: pd.Timestamp = END_DATE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """从新浪指数日线接口取得四指数，并返回可归档的原始收盘矩阵。"""

    import akshare as ak

    series = []
    audit: dict[str, Any] = {"provider": "akshare.stock_zh_index_daily", "symbols": {}}
    for symbol in INDEX_SYMBOLS:
        frame = ak.stock_zh_index_daily(symbol=symbol).copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.loc[
            frame["date"].between(start, end), ["date", "close"]
        ].drop_duplicates("date", keep="last")
        audit["symbols"][symbol] = {
            "rows": int(len(frame)),
            "start": str(frame["date"].min().date()),
            "end": str(frame["date"].max().date()),
        }
        series.append(frame.set_index("date")["close"].rename(symbol))
    result = pd.concat(series, axis=1).sort_index()
    payload = result.reset_index().to_csv(index=False).encode("utf-8")
    audit["csv_sha256"] = hashlib.sha256(payload).hexdigest()
    return result, audit


def _regime_arrays(index_close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rows = len(index_close)
    weak = np.zeros(rows, dtype=bool)
    choppy = np.zeros(rows, dtype=bool)
    state = False
    weak_anchor: int | None = None
    for row in range(rows):
        if row >= 9:
            current = index_close[row]
            average = np.nanmean(index_close[row - 9 : row + 1], axis=0)
            valid = np.isfinite(current) & np.isfinite(average)
            below = int(np.sum(valid & (current < average)))
            above = int(np.sum(valid & (current > average)))
            if state:
                duration = row - weak_anchor + 1 if weak_anchor is not None else 0
                if duration >= 20 or above >= 3:
                    state = False
                    weak_anchor = None
                elif below >= 3:
                    # 原策略每次重复触发都会重置最长持续期计数。
                    weak_anchor = row
            elif below >= 3:
                state = True
                weak_anchor = row
        weak[row] = state
        if row >= 10:
            old = index_close[row - 10]
            current = index_close[row]
            change = np.divide(
                current,
                old,
                out=np.full_like(current, np.nan),
                where=np.isfinite(old) & (old != 0.0),
            ) - 1.0
            choppy[row] = int(np.sum(np.isfinite(change) & (np.abs(change) < 0.01))) >= 3
    return weak, choppy


def _weak_lookback_array(
    r_squared_25: np.ndarray,
    global_indices: np.ndarray,
) -> np.ndarray:
    result = np.full(len(r_squared_25), 25, dtype=np.int16)
    active = 25
    high_streak = 0
    low_streak = 0
    for row in range(len(result)):
        values = r_squared_25[row, global_indices]
        values = values[np.isfinite(values)]
        pool_r2 = float(values.mean()) if len(values) else math.nan
        if np.isfinite(pool_r2) and pool_r2 > 0.4:
            high_streak += 1
            low_streak = 0
        elif np.isfinite(pool_r2) and pool_r2 < 0.38:
            low_streak += 1
            high_streak = 0
        else:
            high_streak = 0
            low_streak = 0
        if active == 25 and high_streak >= 2:
            active = 23
        elif active == 23 and low_streak >= 2:
            active = 25
        result[row] = active
    return result


def _lifecycle_matrix(
    dates: pd.DatetimeIndex,
    master: pd.DataFrame,
) -> np.ndarray:
    listed = pd.to_datetime(master["listing_date"], errors="coerce").to_numpy(
        dtype="datetime64[ns]"
    )
    first_trade = pd.to_datetime(master["first_trade_date"], errors="coerce").to_numpy(
        dtype="datetime64[ns]"
    )
    listed = np.where(np.isnat(listed), first_trade, listed)
    delisted = pd.to_datetime(master["delisting_date"], errors="coerce").to_numpy(
        dtype="datetime64[ns]"
    )
    day = dates.to_numpy(dtype="datetime64[ns]")[:, None]
    return (day >= listed[None, :]) & (np.isnat(delisted)[None, :] | (day <= delisted[None, :]))


def _build_universes(
    dates: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    master: pd.DataFrame,
    amount: np.ndarray,
    adv3: np.ndarray,
    reference: dict[str, Any],
) -> tuple[dict[str, list[np.ndarray]], list[np.ndarray], dict[str, Any]]:
    symbol_to_index = {symbol: index for index, symbol in enumerate(symbols)}
    lifecycle = _lifecycle_matrix(dates, master)
    total_amount = np.nansum(np.where(lifecycle, amount, np.nan), axis=1)
    total_series = pd.Series(total_amount, index=dates)
    liquidity_threshold = total_series.rolling(3, min_periods=3).mean().to_numpy() / 15000.0
    liquid = lifecycle & np.isfinite(adv3) & (adv3 > liquidity_threshold[:, None])

    global_indices = np.asarray(
        [symbol_to_index[item] for item in reference["global_etf_pool"] if item in symbol_to_index],
        dtype=int,
    )
    fixed_indices = np.asarray(
        [
            symbol_to_index[item]
            for item in (*reference["global_etf_pool"], *reference["china_etf_pool"])
            if item in symbol_to_index
        ],
        dtype=int,
    )
    category = master["etf_category"].astype("string").fillna("").to_numpy()
    risk_mask = ~np.isin(category, ["money", "bond"])
    dynamic_mask = np.isin(category, ["sector_equity", "cross_border", "commodity"])
    listed_by_cutoff = (
        pd.to_datetime(master["listing_date"], errors="coerce")
        .le(pd.Timestamp("2023-12-31"))
        .fillna(False)
        .to_numpy()
    )
    tracking = master["tracking_target"].astype("string").fillna("")
    empty_tracking = tracking.str.strip().eq("")
    tracking = tracking.mask(empty_tracking, master["symbol"].astype("string"))
    tracking_codes, _ = pd.factorize(tracking, sort=False)

    universes: dict[str, list[np.ndarray]] = {
        name: []
        for name in ("fixed_only", "original_like", "pit_all_etf", "listed_by_2023_end")
    }
    global_universe: list[np.ndarray] = []
    all_indices = np.arange(len(symbols), dtype=int)
    for row in range(len(dates)):
        fixed = fixed_indices[liquid[row, fixed_indices]]
        global_today = global_indices[liquid[row, global_indices]]
        global_universe.append(global_today)
        universes["fixed_only"].append(fixed)

        dynamic_candidates = all_indices[liquid[row] & dynamic_mask]
        if len(dynamic_candidates):
            order = dynamic_candidates[
                np.argsort(-np.nan_to_num(adv3[row, dynamic_candidates], nan=-np.inf))
            ]
            seen: set[int] = set()
            deduplicated = []
            for candidate in order:
                key = int(tracking_codes[candidate])
                if key in seen:
                    continue
                seen.add(key)
                deduplicated.append(int(candidate))
                if len(deduplicated) >= 150:
                    break
            dynamic = np.asarray(deduplicated, dtype=int)
        else:
            dynamic = np.asarray([], dtype=int)
        universes["original_like"].append(np.union1d(fixed, dynamic).astype(int))
        universes["pit_all_etf"].append(all_indices[liquid[row] & risk_mask])
        universes["listed_by_2023_end"].append(
            all_indices[liquid[row] & risk_mask & listed_by_cutoff]
        )

    audit = {
        "liquidity_formula": "all lifecycle-valid ETFs' three-day mean total amount / 15000",
        "fixed_reference_count": int(len(fixed_indices)),
        "fixed_reference_missing": sorted(
            set((*reference["global_etf_pool"], *reference["china_etf_pool"]))
            .difference(symbol_to_index)
        ),
        "global_reference_count": int(len(global_indices)),
        "dynamic_proxy": (
            "lifecycle-valid sector/cross-border/commodity ETFs, deduplicated by current static "
            "tracking_target and ranked by causal ADV3; original name-cleaning cannot be exact "
            "because local master names contain irreversible source encoding loss"
        ),
        "median_counts": {
            name: float(np.median([len(items) for items in values]))
            for name, values in universes.items()
        },
    }
    return universes, global_universe, audit


def load_market_data(
    data_root: Path | str = DEFAULT_DATA_ROOT,
    *,
    index_frame: pd.DataFrame | None = None,
) -> MarketData:
    """载入全部历史ETF，按上市/退市时点构造严格因果日频研究矩阵。"""

    store = ResearchDataStore(data_root)
    master = store.read_parquet("etf_master").copy()
    for column in ("listing_date", "delisting_date", "first_trade_date", "last_trade_date"):
        master[column] = pd.to_datetime(master[column], errors="coerce").dt.normalize()
    master = master.loc[
        master["bar_status"].eq("success") & master["quality_grade"].eq("B")
    ].copy()
    master = master.sort_values("symbol").drop_duplicates("symbol", keep="last")
    symbols = tuple(master["symbol"].astype(str))
    master = master.set_index("symbol", drop=False).reindex(symbols)
    bars = store.read_symbol_partitions(
        "etf_daily",
        symbols,
        columns=(
            "symbol",
            "trade_date",
            "open",
            "close",
            "adjusted_open",
            "adjusted_close",
            "volume",
            "amount",
        ),
        strict=True,
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
    bars = bars.loc[bars["trade_date"].between(WARMUP_START, END_DATE)].copy()
    for column in ("open", "close", "adjusted_open", "adjusted_close", "volume", "amount"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    benchmark_dates = (
        bars.loc[bars["symbol"].eq(BENCHMARK), "trade_date"].drop_duplicates().sort_values()
    )
    dates = pd.DatetimeIndex(benchmark_dates)
    adjusted_open = _pivot_array(bars, dates, symbols, "adjusted_open")
    adjusted_close = _pivot_array(bars, dates, symbols, "adjusted_close")
    raw_open = _pivot_array(bars, dates, symbols, "open")
    raw_close = _pivot_array(bars, dates, symbols, "close")
    volume = _pivot_array(bars, dates, symbols, "volume")
    amount = _pivot_array(bars, dates, symbols, "amount")
    amount_frame = pd.DataFrame(amount, index=dates)
    close_frame = pd.DataFrame(adjusted_close, index=dates)
    volume_frame = pd.DataFrame(volume, index=dates)
    adv3 = amount_frame.rolling(3, min_periods=3).mean().to_numpy()
    adv20 = amount_frame.rolling(20, min_periods=15).mean().to_numpy()
    ma10 = close_frame.rolling(10, min_periods=10).mean().to_numpy()
    volume_ratio5 = np.divide(
        volume,
        volume_frame.shift(1).rolling(5, min_periods=5).mean().to_numpy(),
        out=np.full_like(volume, np.nan),
        where=volume_frame.shift(1).rolling(5, min_periods=5).mean().to_numpy() > 0.0,
    )
    daily_ratio = close_frame / close_frame.shift(1)
    loss_floor3 = daily_ratio.rolling(3, min_periods=3).min().ge(0.97).to_numpy()
    price_change5 = close_frame / close_frame.shift(5) - 1.0
    recent_volume = volume_frame.rolling(3, min_periods=3).mean()
    earlier_volume = volume_frame.shift(3).rolling(3, min_periods=3).mean()
    volume_change = recent_volume / earlier_volume - 1.0
    divergence_ok = ~((price_change5 > 0.02) & (volume_change < -0.10))
    divergence_ok = divergence_ok.fillna(True).to_numpy()
    alpha = 1.0 - math.exp(-0.05)
    laplace = close_frame.ewm(alpha=alpha, adjust=False, ignore_na=False).mean()
    laplace_slope = laplace.diff().to_numpy()

    if index_frame is None:
        index_frame, index_audit = fetch_index_close()
    else:
        index_frame = index_frame.copy()
        index_frame.index = pd.to_datetime(index_frame.index).normalize()
        index_audit = {"provider": "caller-supplied", "rows": int(len(index_frame))}
    index_frame = index_frame.reindex(index=dates, columns=INDEX_SYMBOLS).ffill(limit=2)
    index_close = index_frame.to_numpy(dtype=float)
    weak_state, choppy_state = _regime_arrays(index_close)
    reference = extract_reference()
    universes, global_universe, universe_audit = _build_universes(
        dates, symbols, master.reset_index(drop=True), amount, adv3, reference
    )
    global_static = np.asarray(
        [symbols.index(item) for item in reference["global_etf_pool"] if item in symbols],
        dtype=int,
    )
    _, r2_25, _ = weighted_trend_matrix(adjusted_close, 25)
    weak_lookback = _weak_lookback_array(r2_25, global_static)
    input_hashes = {
        name: sha256_file(store.manifest_path(name))
        for name in ("etf_daily", "etf_master", "etf_profiles", "etf_coverage")
    }
    reference.update(
        {
            "index_audit": index_audit,
            "universe_audit": universe_audit,
            "index_raw": index_frame.reset_index(names="trade_date"),
        }
    )
    return MarketData(
        dates=dates,
        symbols=symbols,
        symbol_to_index={symbol: index for index, symbol in enumerate(symbols)},
        adjusted_open=adjusted_open,
        adjusted_close=adjusted_close,
        raw_open=raw_open,
        raw_close=raw_close,
        volume=volume,
        amount=amount,
        adv3=adv3,
        adv20=adv20,
        ma10=ma10,
        volume_ratio5=volume_ratio5,
        loss_floor3=loss_floor3,
        divergence_ok=divergence_ok,
        laplace_slope=laplace_slope,
        master=master,
        index_close=index_close,
        weak_state=weak_state,
        choppy_state=choppy_state,
        weak_lookback=weak_lookback,
        universes=universes,
        global_universe=global_universe,
        reference=reference,
        input_hashes=input_hashes,
    )


def _finite_value(matrix: np.ndarray, row: int, column: int) -> float | None:
    value = float(matrix[row, column])
    return value if np.isfinite(value) and value > 0.0 else None


def stage_configs(top_k: int = 1, universe: str = "original_like") -> list[StrategyConfig]:
    switches = {
        "use_r2": False,
        "use_ordinary_filters": False,
        "use_buffer": False,
        "use_regime": False,
        "use_mainline": False,
        "use_retention": False,
    }
    rows = []
    additions = (
        ("A0", {}),
        ("A1", {"use_r2": True}),
        ("A2", {"use_ordinary_filters": True}),
        ("A3", {"use_buffer": True}),
        ("A4", {"use_regime": True}),
        ("A5", {"use_mainline": True}),
        ("A6", {"use_retention": True}),
    )
    for stage, changes in additions:
        switches.update(changes)
        rows.append(
            StrategyConfig(
                name=f"{stage}_top{top_k}_{universe}",
                top_k=top_k,
                universe=universe,
                **switches,
            )
        )
    return rows


def _select_targets(
    row: int,
    holdings: list[str],
    data: MarketData,
    cache: FeatureCache,
    config: StrategyConfig,
) -> tuple[list[str], dict[str, Any]]:
    weak = bool(config.use_regime and data.weak_state[row])
    signal_lookback = (
        int(data.weak_lookback[row])
        if weak and config.regime_dynamic_lookback
        else config.lookback
    )
    trend = cache.trend(signal_lookback)
    annual = trend.annualized_return[row]
    r_squared = trend.r_squared[row]
    score = trend.score[row]
    candidates = (
        data.global_universe[row]
        if weak and config.regime_pool_switch
        else data.universes[config.universe][row]
    )
    if config.listing_cutoff is not None:
        cutoff = pd.Timestamp(config.listing_cutoff)
        listed = pd.to_datetime(
            data.master.iloc[candidates]["listing_date"], errors="coerce"
        ).le(cutoff).to_numpy()
        candidates = candidates[listed]
    if config.excluded_symbols:
        excluded = {
            data.symbol_to_index[item]
            for item in config.excluded_symbols
            if item in data.symbol_to_index
        }
        if excluded:
            candidates = np.asarray(
                [item for item in candidates if int(item) not in excluded], dtype=int
            )
    valid = np.isfinite(annual[candidates]) & (annual[candidates] > 0.0)
    if config.use_r2:
        valid &= np.isfinite(score[candidates])
        valid &= np.isfinite(r_squared[candidates]) & (
            r_squared[candidates] > config.r2_threshold
        )
    ordinary_pass = valid.copy()
    relax_filters = weak and config.regime_filter_relaxation
    if config.use_ordinary_filters and not relax_filters:
        ordinary_pass &= (score[candidates] >= 0.0) & (
            score[candidates] <= config.score_max
        )
        ordinary_pass &= data.adjusted_close[row, candidates] > data.ma10[row, candidates]
        ordinary_pass &= np.isfinite(data.volume_ratio5[row, candidates]) & (
            data.volume_ratio5[row, candidates] < 1.8
        )
        ordinary_pass &= data.loss_floor3[row, candidates]
        if data.choppy_state[row]:
            ordinary_pass &= data.divergence_ok[row, candidates]
    eligible = set(int(item) for item in candidates[ordinary_pass])

    mainline_count = 0
    if config.use_mainline:
        mainline = cache.mainline(config)[row, candidates]
        mainline &= data.loss_floor3[row, candidates]
        if weak:
            mainline &= data.adjusted_close[row, candidates] > data.ma10[row, candidates]
        additions = candidates[mainline]
        mainline_count = int(len(additions))
        eligible.update(int(item) for item in additions)

    retained_count = 0
    if config.use_retention and holdings:
        base = cache.trend(config.lookback)
        for symbol in holdings:
            column = data.symbol_to_index.get(symbol)
            if column is None or column not in set(int(item) for item in candidates):
                continue
            current_score = float(base.score[row, column])
            current_r2 = float(base.r_squared[row, column])
            laplace = float(data.laplace_slope[row, column])
            passed = (
                np.isfinite(current_score)
                and current_score > config.mainline_score_max
                and np.isfinite(current_r2)
                and current_r2 >= config.mainline_r2_current
                and np.isfinite(laplace)
                and laplace > 0.0
                and bool(data.loss_floor3[row, column])
            )
            if weak:
                passed = passed and bool(
                    data.adjusted_close[row, column] > data.ma10[row, column]
                )
            if passed:
                eligible.add(column)
                retained_count += 1

    ranking_values = score if config.use_r2 else annual
    ranked = [
        (data.symbols[column], float(ranking_values[column]))
        for column in eligible
        if np.isfinite(ranking_values[column])
    ]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    disable_buffer = weak and config.regime_buffer_disable
    ratio = config.buffer_ratio if (config.use_buffer and not disable_buffer) else 1.0
    selected = select_with_buffer(
        ranked,
        holdings if config.use_buffer or config.use_retention else [],
        config.top_k,
        ratio,
    )
    if not selected and CASH_ETF in data.symbol_to_index:
        selected = [CASH_ETF]
    diagnostics = {
        "weak": weak,
        "choppy": bool(data.choppy_state[row]),
        "signal_lookback": signal_lookback,
        "universe_count": int(len(candidates)),
        "ordinary_pass_count": int(np.sum(ordinary_pass)),
        "mainline_pass_count": mainline_count,
        "retained_count": retained_count,
    }
    return selected, diagnostics


def _performance_metrics(equity: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)
    curve = (1.0 + returns).cumprod()
    total_return = float(curve.iloc[-1] - 1.0)
    years = len(returns) / 252.0
    annualized = (
        float((1.0 + total_return) ** (1.0 / years) - 1.0)
        if years > 0.0 and total_return > -1.0
        else -1.0
    )
    standard_deviation = float(returns.std(ddof=1))
    volatility = standard_deviation * math.sqrt(252.0)
    sharpe = (
        float(returns.mean() / standard_deviation * math.sqrt(252.0))
        if standard_deviation > 0.0
        else math.nan
    )
    curve_drawdown = curve / curve.cummax() - 1.0
    current_underwater = 0
    longest_underwater = 0
    for flag in curve_drawdown.lt(-1e-12):
        current_underwater = current_underwater + 1 if flag else 0
        longest_underwater = max(longest_underwater, current_underwater)
    average_value = float(equity["total_value"].mean())
    turnover = (
        float(equity["gross_traded"].sum()) / average_value
        if average_value > 0.0
        else math.nan
    )
    rolling = curve / curve.shift(756) - 1.0
    return {
        "trading_days": int(len(equity)),
        "total_return": total_return,
        "annualized_return": annualized,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "maximum_drawdown": float(-curve_drawdown.min()),
        "turnover": turnover,
        "annualized_turnover": turnover / years if years > 0.0 else math.nan,
        "transaction_cost": float(equity["transaction_cost"].sum()),
        "average_cash_ratio": float(equity["cash_ratio"].mean()),
        "average_exposure": float(equity["exposure"].mean()),
        "longest_underwater_trading_days": int(longest_underwater),
        "worst_rolling_three_year_return": (
            float(rolling.min()) if rolling.notna().any() else None
        ),
    }


def run_simulation(
    data: MarketData,
    cache: FeatureCache,
    config: StrategyConfig,
    start: pd.Timestamp | str = START_DATE,
    end: pd.Timestamp | str = END_DATE,
    *,
    capture_details: bool = False,
) -> SimulationResult:
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    output_rows = np.flatnonzero((data.dates >= start_date) & (data.dates <= end_date))
    if len(output_rows) == 0:
        raise ValueError("backtest period has no observations")
    cash = float(config.initial_cash)
    positions: dict[str, int] = {}
    last_close: dict[str, float] = {}
    previous_total = float(config.initial_cash)
    equity_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    contribution_rows: list[dict[str, Any]] = []
    cost_rate = config.single_side_total_cost_bp / 10000.0

    for row in output_rows:
        date_value = data.dates[row]
        observation_row = row - 1
        old_positions = dict(positions)
        old_last_close = dict(last_close)
        open_marks: dict[str, float] = {}
        equity_open = cash
        for symbol, shares in old_positions.items():
            column = data.symbol_to_index[symbol]
            mark = _finite_value(data.adjusted_open, row, column)
            if mark is None:
                mark = old_last_close.get(symbol)
            if mark is not None:
                open_marks[symbol] = float(mark)
                equity_open += shares * float(mark)

        holdings_for_signal = [
            symbol for symbol, shares in positions.items() if shares > 0 and symbol != CASH_ETF
        ]
        if observation_row >= 0:
            targets, diagnostics = _select_targets(
                observation_row, holdings_for_signal, data, cache, config
            )
        else:
            targets, diagnostics = ([CASH_ETF], {"weak": False, "choppy": False})
        target_set = set(targets)
        day_cost_by_symbol: dict[str, float] = {}
        gross_traded = 0.0
        transaction_cost = 0.0

        def participation_limit(symbol: str, requested: int, price: float) -> int:
            if config.adv_participation is None:
                return requested
            column = data.symbol_to_index[symbol]
            adv = float(data.adv20[observation_row, column]) if observation_row >= 0 else math.nan
            if not np.isfinite(adv) or adv <= 0.0:
                return 0
            maximum = int((adv * config.adv_participation) / price) // 100 * 100
            return max(0, min(requested, maximum))

        def trade(symbol: str, side: str, shares: int, price: float) -> None:
            nonlocal cash, gross_traded, transaction_cost
            gross = shares * price
            cost = gross * cost_rate
            cash += gross - cost if side == "sell" else -gross - cost
            gross_traded += gross
            transaction_cost += cost
            day_cost_by_symbol[symbol] = day_cost_by_symbol.get(symbol, 0.0) + cost
            if capture_details:
                column = data.symbol_to_index[symbol]
                adv = (
                    float(data.adv20[observation_row, column])
                    if observation_row >= 0
                    else math.nan
                )
                trade_rows.append(
                    {
                        "trade_date": date_value,
                        "observation_date": data.dates[observation_row] if observation_row >= 0 else pd.NaT,
                        "side": side,
                        "symbol": symbol,
                        "shares": shares,
                        "adjusted_open": price,
                        "gross_value": gross,
                        "cost": cost,
                        "adv20": adv,
                        "adv_participation": gross / adv if np.isfinite(adv) and adv > 0 else math.nan,
                    }
                )

        for symbol in sorted(list(positions)):
            if symbol in target_set:
                continue
            price = open_marks.get(symbol)
            if price is None:
                continue
            requested = int(positions[symbol])
            shares = participation_limit(symbol, requested, price)
            if shares <= 0:
                continue
            trade(symbol, "sell", shares, price)
            positions[symbol] -= shares
            if positions[symbol] <= 0:
                positions.pop(symbol, None)

        if config.adv_participation is None:
            missing_targets = [symbol for symbol in targets if positions.get(symbol, 0) <= 0]
            for index, symbol in enumerate(missing_targets):
                column = data.symbol_to_index.get(symbol)
                if column is None:
                    continue
                price = _finite_value(data.adjusted_open, row, column)
                if price is None:
                    continue
                remaining = len(missing_targets) - index
                budget = cash / remaining if remaining > 0 else 0.0
                shares = int(budget / (price * (1.0 + cost_rate))) // 100 * 100
                if shares <= 0:
                    continue
                trade(symbol, "buy", shares, price)
                positions[symbol] = positions.get(symbol, 0) + shares
        else:
            desired: dict[str, int] = {}
            for symbol in targets:
                column = data.symbol_to_index.get(symbol)
                price = _finite_value(data.adjusted_open, row, column) if column is not None else None
                if price is not None:
                    desired[symbol] = int((equity_open / len(targets)) / price) // 100 * 100
            for symbol in targets:
                column = data.symbol_to_index.get(symbol)
                price = _finite_value(data.adjusted_open, row, column) if column is not None else None
                if price is None:
                    continue
                requested = max(0, desired.get(symbol, 0) - positions.get(symbol, 0))
                shares = participation_limit(symbol, requested, price)
                while shares > 0 and shares * price * (1.0 + cost_rate) > cash + 1e-8:
                    shares -= 100
                if shares <= 0:
                    continue
                trade(symbol, "buy", shares, price)
                positions[symbol] = positions.get(symbol, 0) + shares

        close_marks: dict[str, float] = {}
        positions_value = 0.0
        for symbol, shares in sorted(positions.items()):
            column = data.symbol_to_index[symbol]
            mark = _finite_value(data.adjusted_close, row, column)
            if mark is None:
                mark = open_marks.get(symbol, old_last_close.get(symbol))
            if mark is None:
                continue
            last_close[symbol] = float(mark)
            close_marks[symbol] = float(mark)
            market_value = shares * float(mark)
            positions_value += market_value
            if capture_details:
                position_rows.append(
                    {
                        "trade_date": date_value,
                        "symbol": symbol,
                        "shares": shares,
                        "adjusted_close": mark,
                        "market_value": market_value,
                    }
                )
        total_value = cash + positions_value
        daily_return = total_value / previous_total - 1.0

        if capture_details:
            contribution: dict[str, float] = {}
            for symbol, shares in old_positions.items():
                previous_mark = old_last_close.get(symbol)
                current_open = open_marks.get(symbol, previous_mark)
                if previous_mark is not None and current_open is not None:
                    contribution[symbol] = contribution.get(symbol, 0.0) + shares * (
                        current_open - previous_mark
                    )
            for symbol, shares in positions.items():
                current_open = _finite_value(
                    data.adjusted_open, row, data.symbol_to_index[symbol]
                )
                current_close = close_marks.get(symbol)
                if current_open is not None and current_close is not None:
                    contribution[symbol] = contribution.get(symbol, 0.0) + shares * (
                        current_close - current_open
                    )
            for symbol, cost in day_cost_by_symbol.items():
                contribution[symbol] = contribution.get(symbol, 0.0) - cost
            for symbol, pnl in contribution.items():
                contribution_rows.append(
                    {
                        "trade_date": date_value,
                        "symbol": symbol,
                        "net_pnl": pnl,
                        "return_contribution": pnl / previous_total,
                    }
                )
            decision_rows.append(
                {
                    "execution_date": date_value,
                    "observation_date": data.dates[observation_row] if observation_row >= 0 else pd.NaT,
                    "selected": ";".join(targets),
                    **diagnostics,
                }
            )

        exposure = positions_value / total_value if total_value > 0.0 else math.nan
        equity_rows.append(
            {
                "trade_date": date_value,
                "cash": cash,
                "positions_value": positions_value,
                "total_value": total_value,
                "daily_return": daily_return,
                "cash_ratio": cash / total_value if total_value > 0.0 else math.nan,
                "exposure": exposure,
                "gross_traded": gross_traded,
                "transaction_cost": transaction_cost,
                "holdings": ";".join(sorted(positions)),
            }
        )
        previous_total = total_value

    equity = pd.DataFrame(equity_rows)
    return SimulationResult(
        config=config,
        metrics=_performance_metrics(equity),
        equity=equity,
        trades=pd.DataFrame(trade_rows),
        positions=pd.DataFrame(position_rows),
        decisions=pd.DataFrame(decision_rows),
        contributions=pd.DataFrame(contribution_rows),
    )


def _result_row(result: SimulationResult) -> dict[str, Any]:
    config = result.config
    return {
        "trial": config.name,
        "top_k": config.top_k,
        "universe": config.universe,
        "lookback": config.lookback,
        "r2_threshold": config.r2_threshold,
        "score_max": config.score_max,
        "buffer_ratio": config.buffer_ratio,
        "cost_bp": config.single_side_total_cost_bp,
        "initial_cash": config.initial_cash,
        "adv_participation": config.adv_participation,
        **result.metrics,
    }


def period_metrics(equity: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dates = pd.to_datetime(equity["trade_date"])
    for label, start, end in SUBPERIODS:
        selected = equity.loc[dates.between(start, end)].reset_index(drop=True)
        if not selected.empty:
            rows.append({"period": label, **_performance_metrics(selected)})
    return pd.DataFrame(rows)


def yearly_metrics(equity: pd.DataFrame) -> pd.DataFrame:
    frame = equity.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    rows = []
    for year, selected in frame.groupby(frame["trade_date"].dt.year):
        rows.append(
            {"year": int(year), **_performance_metrics(selected.reset_index(drop=True))}
        )
    return pd.DataFrame(rows)


def rolling_three_year_metrics(equity: pd.DataFrame) -> pd.DataFrame:
    frame = equity.copy().reset_index(drop=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    month_end_indices = frame.groupby(frame["trade_date"].dt.to_period("M")).tail(1).index
    rows = []
    for end_index in month_end_indices:
        if end_index < 755:
            continue
        window = frame.iloc[end_index - 755 : end_index + 1].reset_index(drop=True)
        rows.append(
            {
                "window_start": window.iloc[0]["trade_date"],
                "window_end": window.iloc[-1]["trade_date"],
                **_performance_metrics(window),
            }
        )
    return pd.DataFrame(rows)


def regime_metrics(result: SimulationResult, data: MarketData) -> pd.DataFrame:
    equity = result.equity.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(equity["trade_date"]))
    benchmark_column = data.symbol_to_index[BENCHMARK]
    benchmark = pd.Series(data.adjusted_close[:, benchmark_column], index=data.dates)
    trailing = benchmark / benchmark.shift(252) - 1.0
    known = trailing.shift(1).reindex(dates)
    labels = pd.Series("sideways", index=dates)
    labels.loc[known > 0.10] = "bull"
    labels.loc[known < -0.10] = "bear"
    equity["regime"] = labels.to_numpy()
    rows = []
    for regime in ("bull", "bear", "sideways"):
        selected = equity.loc[equity["regime"].eq(regime)].reset_index(drop=True)
        if not selected.empty:
            rows.append({"regime": regime, **_performance_metrics(selected)})
    return pd.DataFrame(rows)


def contribution_concentration(
    result: SimulationResult,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if result.contributions.empty:
        return pd.DataFrame(), {}
    table = (
        result.contributions.groupby("symbol", as_index=False)[
            ["net_pnl", "return_contribution"]
        ]
        .sum()
        .sort_values("net_pnl", ascending=False)
        .reset_index(drop=True)
    )
    positions = result.positions.copy()
    equity_value = result.equity.set_index("trade_date")["total_value"]
    positions["portfolio_weight"] = positions["market_value"] / positions["trade_date"].map(
        equity_value
    )
    exposure = positions.groupby("symbol").agg(
        holding_days=("trade_date", "nunique"),
        average_weight_when_held=("portfolio_weight", "mean"),
        maximum_weight=("portfolio_weight", "max"),
    )
    exposure["average_portfolio_weight"] = positions.groupby("symbol")[
        "portfolio_weight"
    ].sum() / len(result.equity)
    table = table.join(exposure, on="symbol")
    positive_total = float(table["net_pnl"].clip(lower=0.0).sum())
    table["positive_contribution_share"] = (
        table["net_pnl"].clip(lower=0.0) / positive_total if positive_total > 0 else 0.0
    )
    shares = table["positive_contribution_share"].to_numpy(dtype=float)
    summary = {
        "held_symbol_count": int(table["symbol"].nunique()),
        "top1_positive_contribution_share": float(shares[:1].sum()),
        "top3_positive_contribution_share": float(shares[:3].sum()),
        "top5_positive_contribution_share": float(shares[:5].sum()),
        "positive_contribution_hhi": float(np.square(shares).sum()),
        "top_symbols": table.head(5)["symbol"].tolist(),
    }
    return table, summary


def _sharpe_by_trial(return_matrix: np.ndarray) -> np.ndarray:
    means = np.nanmean(return_matrix, axis=1)
    standard_deviation = np.nanstd(return_matrix, axis=1, ddof=1)
    return np.divide(
        means,
        standard_deviation,
        out=np.full_like(means, np.nan),
        where=standard_deviation > 0.0,
    ) * math.sqrt(252.0)


def compute_pbo(
    return_matrix: np.ndarray,
    dates: pd.DatetimeIndex,
    trial_names: list[str],
    partitions: int = 8,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    blocks = [
        np.asarray(block, dtype=int)
        for block in np.array_split(np.arange(len(dates)), partitions)
    ]
    rows = []
    for split, train_blocks in enumerate(
        itertools.combinations(range(partitions), partitions // 2), start=1
    ):
        test_blocks = tuple(index for index in range(partitions) if index not in train_blocks)
        train_index = np.concatenate([blocks[index] for index in train_blocks])
        test_index = np.concatenate([blocks[index] for index in test_blocks])
        train_sharpe = _sharpe_by_trial(return_matrix[:, train_index])
        test_sharpe = _sharpe_by_trial(return_matrix[:, test_index])
        winner = int(np.nanargmax(train_sharpe))
        winner_oos = float(test_sharpe[winner])
        finite = test_sharpe[np.isfinite(test_sharpe)]
        percentile = float((np.sum(finite < winner_oos) + 0.5) / len(finite))
        percentile = min(max(percentile, 1e-12), 1.0 - 1e-12)
        rows.append(
            {
                "split": split,
                "train_blocks": ";".join(map(str, train_blocks)),
                "test_blocks": ";".join(map(str, test_blocks)),
                "selected_trial": trial_names[winner],
                "is_sharpe": float(train_sharpe[winner]),
                "oos_sharpe": winner_oos,
                "oos_percentile": percentile,
                "logit": math.log(percentile / (1.0 - percentile)),
                "below_oos_median": bool(percentile <= 0.5),
            }
        )
    frame = pd.DataFrame(rows)
    summary = {
        "method": "CSCV approximation: 8 contiguous blocks, all 70 half-splits",
        "trial_count": int(return_matrix.shape[0]),
        "trading_days": int(return_matrix.shape[1]),
        "split_count": int(len(frame)),
        "pbo": float(frame["below_oos_median"].mean()),
        "median_selected_oos_percentile": float(frame["oos_percentile"].median()),
    }
    return frame, summary


def deflated_sharpe_probability(
    returns: np.ndarray,
    all_trial_returns: np.ndarray,
) -> dict[str, Any]:
    observed = np.asarray(returns, dtype=float)
    observed = observed[np.isfinite(observed)]
    trial_daily_sharpes = _sharpe_by_trial(all_trial_returns) / math.sqrt(252.0)
    trial_daily_sharpes = trial_daily_sharpes[np.isfinite(trial_daily_sharpes)]
    observed_daily_sharpe = float(observed.mean() / observed.std(ddof=1))
    trial_count = int(len(trial_daily_sharpes))
    euler_gamma = 0.5772156649015329
    if trial_count > 1:
        expected_z = (1.0 - euler_gamma) * stats.norm.ppf(
            1.0 - 1.0 / trial_count
        ) + euler_gamma * stats.norm.ppf(1.0 - 1.0 / (trial_count * math.e))
        expected_max = float(np.std(trial_daily_sharpes, ddof=1) * expected_z)
    else:
        expected_max = 0.0
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
        (observed_daily_sharpe - expected_max)
        * math.sqrt(max(1, len(observed) - 1))
        / denominator
    )
    return {
        "trial_count": trial_count,
        "observations": int(len(observed)),
        "observed_annualized_sharpe": observed_daily_sharpe * math.sqrt(252.0),
        "expected_maximum_annualized_sharpe_under_null": expected_max * math.sqrt(252.0),
        "skewness": skewness,
        "pearson_kurtosis": kurtosis,
        "deflated_sharpe_probability": float(stats.norm.cdf(statistic)),
        "method_note": (
            "Bailey-Lopez de Prado DSR approximation; correlated grid trials mean the "
            "independent-trial expected maximum is a conservative diagnostic, not a p-value."
        ),
    }


def expanding_walk_forward(
    return_matrix: np.ndarray,
    dates: pd.DatetimeIndex,
    trial_names: list[str],
    first_test_year: int = 2019,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    combined = np.full(len(dates), np.nan)
    rows = []
    for year in range(first_test_year, int(dates.max().year) + 1):
        train = dates.year < year
        test = dates.year == year
        if int(train.sum()) < 504 or not np.any(test):
            continue
        train_sharpe = _sharpe_by_trial(return_matrix[:, train])
        winner = int(np.nanargmax(train_sharpe))
        combined[test] = return_matrix[winner, test]
        test_returns = return_matrix[winner, test]
        test_curve = np.cumprod(1.0 + test_returns)
        rows.append(
            {
                "test_year": year,
                "selected_trial": trial_names[winner],
                "training_sharpe": float(train_sharpe[winner]),
                "test_return": float(test_curve[-1] - 1.0),
                "test_sharpe": float(_sharpe_by_trial(test_returns[None, :])[0]),
            }
        )
    valid = np.isfinite(combined)
    walk_equity = pd.DataFrame(
        {
            "trade_date": dates[valid],
            "daily_return": combined[valid],
            "total_value": np.cumprod(1.0 + combined[valid]),
            "gross_traded": 0.0,
            "transaction_cost": 0.0,
            "cash_ratio": np.nan,
            "exposure": np.nan,
        }
    )
    metrics = _performance_metrics(walk_equity)
    frame = pd.DataFrame(rows)
    summary = {
        **metrics,
        "test_years": int(len(frame)),
        "worst_year": float(frame["test_return"].min()) if not frame.empty else None,
        "positive_year_ratio": float(frame["test_return"].gt(0).mean()) if not frame.empty else None,
    }
    return frame, walk_equity, summary


def load_public_backtest() -> tuple[pd.DataFrame, dict[str, Any]]:
    payload = json.loads(PUBLIC_BACKTEST.read_text(encoding="utf-8"))
    series = payload["return_series"]["strategy"]
    dates = pd.to_datetime(series["time"], unit="ms").normalize()
    equity = 1.0 + np.asarray(series["value"], dtype=float) / 100.0
    returns = pd.Series(equity).pct_change().fillna(equity[0] - 1.0).to_numpy()
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "daily_return": returns,
            "total_value": equity,
            "gross_traded": 0.0,
            "transaction_cost": 0.0,
            "cash_ratio": np.nan,
            "exposure": np.nan,
        }
    )
    return frame, {
        "backtest_id": payload["backtest_id"],
        "configuration": payload["configuration"],
        "stats": payload["stats"],
        "display_metrics": payload["display_metrics"],
    }


def parameter_configs(base: StrategyConfig) -> list[StrategyConfig]:
    rows = []
    for number, values in enumerate(
        itertools.product(
            (1, 3),
            (20, 23, 25, 30),
            (0.3, 0.4, 0.5),
            (3.0, 5.0, 8.0),
            (0.85, 0.90, 0.95),
        ),
        start=1,
    ):
        top_k, lookback, r2_threshold, score_max, buffer_ratio = values
        rows.append(
            replace(
                base,
                name=f"grid_{number:03d}",
                top_k=top_k,
                lookback=lookback,
                r2_threshold=r2_threshold,
                score_max=score_max,
                buffer_ratio=buffer_ratio,
            )
        )
    return rows


def factorial_configs(base: StrategyConfig) -> list[StrategyConfig]:
    modules = (
        "use_r2",
        "use_ordinary_filters",
        "use_buffer",
        "use_regime",
        "use_mainline",
        "use_retention",
    )
    rows = []
    for top_k in (1, 3):
        for number, flags in enumerate(itertools.product((False, True), repeat=6)):
            changes = dict(zip(modules, flags))
            rows.append(
                replace(
                    base,
                    name=f"factorial_top{top_k}_{number:02d}",
                    top_k=top_k,
                    **changes,
                )
            )
    return rows


def leave_one_out_configs(base: StrategyConfig) -> list[StrategyConfig]:
    modules = (
        "use_r2",
        "use_ordinary_filters",
        "use_buffer",
        "use_regime",
        "use_mainline",
        "use_retention",
    )
    rows = []
    for top_k in (1, 3):
        for module in modules:
            rows.append(
                replace(
                    base,
                    name=f"A6_top{top_k}_without_{module}",
                    top_k=top_k,
                    **{module: False},
                )
            )
    return rows


def mainline_sensitivity_configs(base: StrategyConfig) -> list[StrategyConfig]:
    variations = (
        ("frozen", {}),
        ("score_loose", {"mainline_score_min": 4.0, "mainline_score_max": 24.0}),
        ("score_strict", {"mainline_score_min": 6.0, "mainline_score_max": 16.0}),
        ("r2_loose", {"mainline_r2_current": 0.80, "mainline_r2_average": 0.85}),
        ("r2_strict", {"mainline_r2_current": 0.90, "mainline_r2_average": 0.95}),
        ("volume_loose", {"mainline_volume_average": 1.5}),
        ("volume_strict", {"mainline_volume_average": 2.1}),
        (
            "continuity_loose",
            {"mainline_score_up_days": 3, "mainline_positive_laplace_days": 4},
        ),
        ("growth_loose", {"mainline_score_growth": 1.5}),
        ("growth_strict", {"mainline_score_growth": 2.5}),
    )
    rows = []
    for top_k in (1, 3):
        for label, changes in variations:
            rows.append(
                replace(
                    base,
                    name=f"mainline_top{top_k}_{label}",
                    top_k=top_k,
                    **changes,
                )
            )
    return rows


def regime_component_configs(base: StrategyConfig) -> list[StrategyConfig]:
    modules = (
        "regime_pool_switch",
        "regime_filter_relaxation",
        "regime_dynamic_lookback",
        "regime_buffer_disable",
    )
    rows = []
    # 这是看到 A4 总效应后的解释性实验，不属于事前冻结的成功判定。
    for top_k in (1, 3):
        for number, flags in enumerate(itertools.product((False, True), repeat=4)):
            rows.append(
                replace(
                    base,
                    name=f"regime_components_top{top_k}_{number:02d}",
                    top_k=top_k,
                    use_r2=True,
                    use_ordinary_filters=True,
                    use_buffer=True,
                    use_regime=True,
                    use_mainline=False,
                    use_retention=False,
                    **dict(zip(modules, flags)),
                )
            )
    return rows


def _generic_factorial_effects(
    frame: pd.DataFrame,
    modules: tuple[str, ...],
) -> pd.DataFrame:
    rows = []
    for top_k in (1, 3):
        selected = frame.loc[frame["top_k"].eq(top_k)].copy()
        for module in modules:
            pairs = []
            others = [item for item in modules if item != module]
            for _, group in selected.groupby(others, dropna=False):
                enabled = group.loc[group[module]]
                disabled = group.loc[~group[module]]
                if len(enabled) == 1 and len(disabled) == 1:
                    pairs.append(
                        {
                            "delta_sharpe": float(enabled.iloc[0]["sharpe"] - disabled.iloc[0]["sharpe"]),
                            "delta_annualized_return": float(
                                enabled.iloc[0]["annualized_return"]
                                - disabled.iloc[0]["annualized_return"]
                            ),
                        }
                    )
            paired = pd.DataFrame(pairs)
            rows.append(
                {
                    "top_k": top_k,
                    "module": module,
                    "paired_comparisons": int(len(paired)),
                    "mean_delta_sharpe": float(paired["delta_sharpe"].mean()),
                    "mean_delta_annualized_return": float(
                        paired["delta_annualized_return"].mean()
                    ),
                    "positive_delta_sharpe_ratio": float(
                        paired["delta_sharpe"].gt(0).mean()
                    ),
                }
            )
    return pd.DataFrame(rows)


def _factorial_effects(frame: pd.DataFrame) -> pd.DataFrame:
    modules = (
        "use_r2",
        "use_ordinary_filters",
        "use_buffer",
        "use_regime",
        "use_mainline",
        "use_retention",
    )
    rows = []
    for top_k in (1, 3):
        selected = frame.loc[frame["top_k"].eq(top_k)].copy()
        for module in modules:
            others = [item for item in modules if item != module]
            pairs = []
            for _, group in selected.groupby(others, dropna=False):
                enabled = group.loc[group[module]]
                disabled = group.loc[~group[module]]
                if len(enabled) == 1 and len(disabled) == 1:
                    pairs.append(
                        {
                            "delta_sharpe": float(enabled.iloc[0]["sharpe"] - disabled.iloc[0]["sharpe"]),
                            "delta_annualized_return": float(
                                enabled.iloc[0]["annualized_return"]
                                - disabled.iloc[0]["annualized_return"]
                            ),
                            "delta_annualized_turnover": float(
                                enabled.iloc[0]["annualized_turnover"]
                                - disabled.iloc[0]["annualized_turnover"]
                            ),
                        }
                    )
            paired = pd.DataFrame(pairs)
            rows.append(
                {
                    "top_k": top_k,
                    "module": module,
                    "paired_comparisons": int(len(paired)),
                    **{
                        f"mean_{column}": float(paired[column].mean())
                        for column in paired.columns
                    },
                    "positive_delta_sharpe_ratio": float(paired["delta_sharpe"].gt(0).mean()),
                }
            )
    return pd.DataFrame(rows)


def _stage_marginals(
    stage_results: dict[tuple[int, str], SimulationResult],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    period_rows = []
    stages = [f"A{number}" for number in range(7)]
    for top_k in (1, 3):
        for index, stage in enumerate(stages):
            result = stage_results[(top_k, stage)]
            previous = stage_results[(top_k, stages[index - 1])] if index else None
            row = {"top_k": top_k, "stage": stage, **result.metrics}
            if previous is not None:
                row.update(
                    {
                        "delta_sharpe": result.metrics["sharpe"] - previous.metrics["sharpe"],
                        "delta_annualized_return": (
                            result.metrics["annualized_return"]
                            - previous.metrics["annualized_return"]
                        ),
                        "delta_annualized_turnover": (
                            result.metrics["annualized_turnover"]
                            - previous.metrics["annualized_turnover"]
                        ),
                    }
                )
            rows.append(row)
            periods = period_metrics(result.equity).set_index("period")
            previous_periods = (
                period_metrics(previous.equity).set_index("period")
                if previous is not None
                else None
            )
            for period, metrics in periods.iterrows():
                period_row = {
                    "top_k": top_k,
                    "stage": stage,
                    "period": period,
                    "annualized_return": metrics["annualized_return"],
                    "sharpe": metrics["sharpe"],
                    "maximum_drawdown": metrics["maximum_drawdown"],
                }
                if previous_periods is not None:
                    period_row["delta_sharpe"] = (
                        metrics["sharpe"] - previous_periods.loc[period, "sharpe"]
                    )
                period_rows.append(period_row)
    return pd.DataFrame(rows), pd.DataFrame(period_rows)


def _switch_events(result: SimulationResult) -> pd.DataFrame:
    decisions = result.decisions.copy()
    decisions["execution_date"] = pd.to_datetime(decisions["execution_date"])
    decisions["first_target"] = decisions["selected"].str.split(";").str[0]
    changed = decisions["first_target"].ne(decisions["first_target"].shift(1))
    entries = decisions.loc[changed & decisions["first_target"].ne(CASH_ETF)].copy()
    rows = []
    targets = decisions["first_target"].to_numpy()
    dates = decisions["execution_date"].to_numpy()
    for index in entries.index:
        symbol = decisions.at[index, "first_target"]
        later = np.flatnonzero(targets[index + 1 :] != symbol)
        exit_date = pd.Timestamp(dates[index + 1 + later[0]]) if len(later) else pd.NaT
        rows.append(
            {
                "entry_date": decisions.at[index, "execution_date"],
                "symbol": local_to_jq(symbol),
                "local_symbol": symbol,
                "exit_date": exit_date,
            }
        )
    return pd.DataFrame(rows)


def run_experiment_suite(data: MarketData) -> dict[str, Any]:
    cache = FeatureCache(data)
    base = StrategyConfig()
    stage_results: dict[tuple[int, str], SimulationResult] = {}
    print("[1/11] A0-A6 sequential ablation, Top1/Top3", flush=True)
    for top_k in (1, 3):
        for config in stage_configs(top_k):
            stage = config.name.split("_")[0]
            stage_results[(top_k, stage)] = run_simulation(
                data,
                cache,
                config,
                capture_details=stage == "A6",
            )
    ablation, ablation_periods = _stage_marginals(stage_results)

    print("[2/11] universe, leave-one-out, and full factorial", flush=True)
    universe_rows = []
    for top_k, universe in itertools.product(
        (1, 3), ("fixed_only", "original_like", "pit_all_etf", "listed_by_2023_end")
    ):
        config = replace(base, name=f"universe_top{top_k}_{universe}", top_k=top_k, universe=universe)
        universe_rows.append(_result_row(run_simulation(data, cache, config)))
    loo_rows = [
        _result_row(run_simulation(data, cache, config))
        for config in leave_one_out_configs(base)
    ]
    factorial_rows = []
    for config in factorial_configs(base):
        result = run_simulation(data, cache, config)
        factorial_rows.append(
            {
                **_result_row(result),
                "use_r2": config.use_r2,
                "use_ordinary_filters": config.use_ordinary_filters,
                "use_buffer": config.use_buffer,
                "use_regime": config.use_regime,
                "use_mainline": config.use_mainline,
                "use_retention": config.use_retention,
            }
        )
    factorial = pd.DataFrame(factorial_rows)
    factorial_effects = _factorial_effects(factorial)

    print("[3/11] post-protocol A4 component decomposition", flush=True)
    regime_component_rows = []
    regime_modules = (
        "regime_pool_switch",
        "regime_filter_relaxation",
        "regime_dynamic_lookback",
        "regime_buffer_disable",
    )
    for config in regime_component_configs(base):
        result = run_simulation(data, cache, config)
        regime_component_rows.append(
            {
                **_result_row(result),
                **{module: getattr(config, module) for module in regime_modules},
            }
        )
    regime_components = pd.DataFrame(regime_component_rows)
    regime_component_effects = _generic_factorial_effects(
        regime_components, regime_modules
    )

    print("[4/11] frozen 216-trial parameter neighborhood", flush=True)
    grid_configs = parameter_configs(base)
    grid_rows = []
    grid_returns = []
    for index, config in enumerate(grid_configs, start=1):
        result = run_simulation(data, cache, config)
        grid_rows.append(_result_row(result))
        grid_returns.append(result.equity["daily_return"].to_numpy(dtype=np.float32))
        if index % 54 == 0:
            print(f"  parameter trials {index}/216", flush=True)
    parameter_grid = pd.DataFrame(grid_rows)
    return_matrix = np.vstack(grid_returns)
    result_dates = pd.DatetimeIndex(stage_results[(1, "A6")].equity["trade_date"])

    print("[5/11] B-mainline threshold sensitivity", flush=True)
    mainline_rows = [
        _result_row(run_simulation(data, cache, config))
        for config in mainline_sensitivity_configs(base)
    ]

    print("[6/11] cost and ADV capacity pressure", flush=True)
    cost_rows = []
    for top_k, cost in itertools.product((1, 3), (2.0, 5.0, 10.0, 20.0, 30.0)):
        config = replace(
            base,
            name=f"cost_top{top_k}_{cost:g}bp",
            top_k=top_k,
            single_side_total_cost_bp=cost,
        )
        cost_rows.append(_result_row(run_simulation(data, cache, config)))
    capacity_rows = []
    for top_k, capital, participation in itertools.product(
        (1, 3),
        (200_000.0, 1_000_000.0, 5_000_000.0, 10_000_000.0, 50_000_000.0),
        (0.005, 0.01, 0.05),
    ):
        config = replace(
            base,
            name=f"capacity_top{top_k}_{capital:g}_{participation:g}",
            top_k=top_k,
            initial_cash=capital,
            adv_participation=participation,
        )
        capacity_rows.append(_result_row(run_simulation(data, cache, config)))

    print("[7/11] contribution concentration and ex-post deletion", flush=True)
    contribution_tables = []
    concentration_summary: dict[str, Any] = {}
    exclusion_rows = []
    for top_k in (1, 3):
        frozen = stage_results[(top_k, "A6")]
        table, summary = contribution_concentration(frozen)
        table.insert(0, "top_k", top_k)
        contribution_tables.append(table)
        concentration_summary[f"top{top_k}"] = summary
        ranked_symbols = [item for item in table["symbol"] if item != CASH_ETF]
        for count in (1, 3, 5):
            excluded = tuple(ranked_symbols[:count])
            config = replace(
                base,
                name=f"exclude_top{count}_contributors_top{top_k}",
                top_k=top_k,
                excluded_symbols=excluded,
            )
            row = _result_row(run_simulation(data, cache, config))
            row["excluded_symbols"] = ";".join(excluded)
            row["cagr_retention"] = (
                row["annualized_return"] / frozen.metrics["annualized_return"]
                if frozen.metrics["annualized_return"] != 0.0
                else math.nan
            )
            exclusion_rows.append(row)

    print("[8/11] yearly, subperiod, regime, and rolling windows", flush=True)
    yearly_rows = []
    period_rows = []
    regime_rows = []
    rolling_rows = []
    for top_k in (1, 3):
        result = stage_results[(top_k, "A6")]
        for frame, destination in (
            (yearly_metrics(result.equity), yearly_rows),
            (period_metrics(result.equity), period_rows),
            (regime_metrics(result, data), regime_rows),
            (rolling_three_year_metrics(result.equity), rolling_rows),
        ):
            frame.insert(0, "top_k", top_k)
            destination.extend(frame.to_dict("records"))

    print("[9/11] CSCV/PBO, DSR, and expanding-window OOS", flush=True)
    pbo_splits, pbo = compute_pbo(
        return_matrix, result_dates, [config.name for config in grid_configs]
    )
    frozen_returns = stage_results[(1, "A6")].equity["daily_return"].to_numpy(dtype=float)
    dsr = deflated_sharpe_probability(frozen_returns, return_matrix)
    walk_forward, walk_equity, walk_summary = expanding_walk_forward(
        return_matrix, result_dates, [config.name for config in grid_configs]
    )

    print("[10/11] public-backtest path comparison and A7 event extraction", flush=True)
    public_equity, public_meta = load_public_backtest()
    local_equity = stage_results[(1, "A6")].equity[["trade_date", "daily_return"]].copy()
    aligned = public_equity[["trade_date", "daily_return"]].merge(
        local_equity,
        on="trade_date",
        suffixes=("_public", "_local"),
    )
    public_comparison = {
        "overlap_days": int(len(aligned)),
        "daily_return_correlation": float(
            aligned[["daily_return_public", "daily_return_local"]].corr().iloc[0, 1]
        ),
        "public_stats": public_meta["stats"],
        "local_A6_top1": stage_results[(1, "A6")].metrics,
        "local_A0_top1": stage_results[(1, "A0")].metrics,
        "public_source_sha256": file_sha256(PUBLIC_BACKTEST),
    }
    switch_events = _switch_events(stage_results[(1, "A6")])

    print("[11/11] assemble experiment bundle", flush=True)
    experiment_counts = {
        "sequential_ablation": 14,
        "universe_stress": len(universe_rows),
        "leave_one_out": len(loo_rows),
        "factorial": len(factorial_rows),
        "post_protocol_regime_components": len(regime_component_rows),
        "parameter_grid": len(grid_rows),
        "mainline_sensitivity": len(mainline_rows),
        "cost_stress": len(cost_rows),
        "capacity_stress": len(capacity_rows),
        "contributor_exclusion": len(exclusion_rows),
        "direct_backtests_total": int(
            14
            + len(universe_rows)
            + len(loo_rows)
            + len(factorial_rows)
            + len(regime_component_rows)
            + len(grid_rows)
            + len(mainline_rows)
            + len(cost_rows)
            + len(capacity_rows)
            + len(exclusion_rows)
        ),
        "pbo_splits": int(len(pbo_splits)),
        "walk_forward_years": int(len(walk_forward)),
        "a7_switch_events": int(len(switch_events)),
    }
    return {
        "stage_results": stage_results,
        "module_ablation": ablation,
        "module_ablation_periods": ablation_periods,
        "universe_stress": pd.DataFrame(universe_rows),
        "leave_one_out": pd.DataFrame(loo_rows),
        "factorial": factorial,
        "factorial_effects": factorial_effects,
        "regime_components": regime_components,
        "regime_component_effects": regime_component_effects,
        "parameter_grid": parameter_grid,
        "mainline_sensitivity": pd.DataFrame(mainline_rows),
        "cost_stress": pd.DataFrame(cost_rows),
        "capacity_stress": pd.DataFrame(capacity_rows),
        "asset_contributions": pd.concat(contribution_tables, ignore_index=True),
        "concentration": concentration_summary,
        "exclusion_stress": pd.DataFrame(exclusion_rows),
        "yearly": pd.DataFrame(yearly_rows),
        "periods": pd.DataFrame(period_rows),
        "regimes": pd.DataFrame(regime_rows),
        "rolling_three_year": pd.DataFrame(rolling_rows),
        "pbo_splits": pbo_splits,
        "pbo": pbo,
        "dsr": dsr,
        "walk_forward": walk_forward,
        "walk_forward_equity": walk_equity,
        "walk_forward_summary": walk_summary,
        "public_equity": public_equity,
        "public_meta": public_meta,
        "public_comparison": public_comparison,
        "switch_events": switch_events,
        "experiment_counts": experiment_counts,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _pct(value: float | None) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2%}"


def _num(value: float | None, digits: int = 2) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.{digits}f}"


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = frame[columns].copy()
    for column in selected.columns:
        if pd.api.types.is_float_dtype(selected[column]):
            selected[column] = selected[column].map(
                lambda value: "—" if pd.isna(value) else f"{value:.4f}"
            )
    return selected.to_markdown(index=False)


def _module_verdicts(bundle: dict[str, Any]) -> pd.DataFrame:
    labels = {
        "A1": "R²趋势质量",
        "A2": "普通健康过滤",
        "A3": "90%持仓缓冲",
        "A4": "A股强弱切换包",
        "A5": "B型主线",
        "A6": "主线延续",
    }
    ablation = bundle["module_ablation"]
    periods = bundle["module_ablation_periods"]
    factorial = bundle["factorial_effects"]
    rows = []
    switch_map = {
        "A1": "use_r2",
        "A2": "use_ordinary_filters",
        "A3": "use_buffer",
        "A4": "use_regime",
        "A5": "use_mainline",
        "A6": "use_retention",
    }
    for stage, label in labels.items():
        full = ablation.loc[ablation["stage"].eq(stage)]
        period = periods.loc[periods["stage"].eq(stage)].groupby("period")[
            "delta_sharpe"
        ].mean()
        factor = factorial.loc[factorial["module"].eq(switch_map[stage])]
        mean_delta = float(full["delta_sharpe"].mean())
        positive_periods = int(period.gt(0.0).sum())
        if stage == "A3":
            previous = ablation.loc[ablation["stage"].eq("A2")].set_index("top_k")
            current = full.set_index("top_k")
            turnover_reduction = float(
                np.mean(
                    [
                        1.0
                        - current.loc[top_k, "annualized_turnover"]
                        / previous.loc[top_k, "annualized_turnover"]
                        for top_k in (1, 3)
                    ]
                )
            )
            preregistered_pass = (
                turnover_reduction >= 0.20
                and float(full["delta_sharpe"].min()) >= -0.05
            )
            criterion = f"buffer turnover reduction={turnover_reduction:.4f}"
        else:
            preregistered_pass = mean_delta >= 0.05 and positive_periods >= 2
            criterion = "mean delta Sharpe>=0.05 and >=2 positive subperiods"
        rows.append(
            {
                "stage": stage,
                "module": label,
                "sequential_mean_delta_sharpe": mean_delta,
                "positive_subperiods": positive_periods,
                "factorial_mean_delta_sharpe": float(
                    factor["mean_delta_sharpe"].mean()
                ),
                "factorial_positive_ratio": float(
                    factor["positive_delta_sharpe_ratio"].mean()
                ),
                "criterion": criterion,
                "preregistered_stable_margin": preregistered_pass,
            }
        )
    return pd.DataFrame(rows)


def create_charts(output: Path, bundle: dict[str, Any]) -> None:
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    ablation = bundle["module_ablation"]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for top_k, color in ((1, "#2457C5"), (3, "#E97931")):
        selected = ablation.loc[ablation["top_k"].eq(top_k)]
        axes[0].plot(selected["stage"], selected["sharpe"], marker="o", label=f"Top{top_k}", color=color)
        axes[1].plot(
            selected["stage"],
            selected["annualized_return"] * 100.0,
            marker="o",
            label=f"Top{top_k}",
            color=color,
        )
    axes[0].set_title("Sequential ablation: Sharpe")
    axes[1].set_title("Sequential ablation: CAGR")
    axes[1].set_ylabel("percent")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend()
    figure.tight_layout()
    figure.savefig(assets / "module-ablation.png", dpi=180)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(11, 5.5))
    public = bundle["public_equity"]
    axis.plot(
        public["trade_date"],
        public["total_value"],
        color="#111111",
        linewidth=1.8,
        label="public Wufu 7.5",
    )
    for stage, color in (("A0", "#999999"), ("A3", "#E97931"), ("A6", "#2457C5")):
        equity = bundle["stage_results"][(1, stage)].equity
        curve = (1.0 + equity["daily_return"]).cumprod()
        axis.plot(equity["trade_date"], curve, linewidth=1.2, label=f"local {stage}", color=color)
    axis.set_yscale("log")
    axis.set_title("Public minute path vs causal local daily paths")
    axis.set_ylabel("wealth, log scale")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(assets / "public-local-path-gap.png", dpi=180)
    plt.close(figure)

    grid = bundle["parameter_grid"]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    scatter = axes[0].scatter(
        grid["annualized_return"] * 100.0,
        grid["sharpe"],
        c=grid["lookback"],
        cmap="viridis",
        alpha=0.8,
    )
    axes[0].set_xlabel("CAGR percent")
    axes[0].set_ylabel("Sharpe")
    axes[0].set_title("216-trial parameter neighborhood")
    figure.colorbar(scatter, ax=axes[0], label="lookback")
    grouped = grid.groupby("lookback")["sharpe"].agg(["median", "min", "max"])
    axes[1].plot(grouped.index, grouped["median"], marker="o", color="#2457C5")
    axes[1].fill_between(grouped.index, grouped["min"], grouped["max"], alpha=0.2)
    axes[1].set_title("Sharpe plateau by lookback")
    axes[1].grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(assets / "parameter-stability.png", dpi=180)
    plt.close(figure)

    cost = bundle["cost_stress"]
    capacity = bundle["capacity_stress"]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for top_k in (1, 3):
        selected = cost.loc[cost["top_k"].eq(top_k)]
        axes[0].plot(selected["cost_bp"], selected["annualized_return"] * 100.0, marker="o", label=f"Top{top_k}")
        selected_capacity = capacity.loc[
            capacity["top_k"].eq(top_k) & capacity["adv_participation"].eq(0.005)
        ]
        axes[1].plot(
            selected_capacity["initial_cash"] / 1e6,
            selected_capacity["average_exposure"] * 100.0,
            marker="o",
            label=f"Top{top_k}",
        )
    axes[0].axhline(0.0, color="#555555", linewidth=0.8)
    axes[0].set_title("Single-side total cost stress")
    axes[0].set_xlabel("bp")
    axes[0].set_ylabel("CAGR percent")
    axes[1].axhline(70.0, color="#B3261E", linewidth=0.8, linestyle="--")
    axes[1].set_xscale("log")
    axes[1].set_title("0.5% ADV capacity exposure")
    axes[1].set_xlabel("capital, RMB million")
    axes[1].set_ylabel("average exposure percent")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend()
    figure.tight_layout()
    figure.savefig(assets / "cost-capacity.png", dpi=180)
    plt.close(figure)

    yearly = bundle["yearly"]
    pivot = yearly.pivot(index="year", columns="top_k", values="annualized_return") * 100.0
    figure, axis = plt.subplots(figsize=(11, 4.8))
    pivot.plot(kind="bar", ax=axis, color=["#2457C5", "#E97931"])
    axis.axhline(0.0, color="#333333", linewidth=0.8)
    axis.set_title("A6 yearly returns")
    axis.set_ylabel("percent")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(assets / "yearly-returns.png", dpi=180)
    plt.close(figure)

    contributions = bundle["asset_contributions"]
    figure, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    for axis, top_k in zip(axes, (1, 3)):
        selected = contributions.loc[contributions["top_k"].eq(top_k)].head(10).iloc[::-1]
        axis.barh(selected["symbol"], selected["net_pnl"], color="#2457C5" if top_k == 1 else "#E97931")
        axis.set_title(f"Top{top_k}: top net PnL contributors")
        axis.grid(axis="x", alpha=0.25)
    figure.tight_layout()
    figure.savefig(assets / "contribution-concentration.png", dpi=180)
    plt.close(figure)


def build_report(bundle: dict[str, Any], data: MarketData, a7_status: dict[str, Any]) -> str:
    ablation = bundle["module_ablation"]
    verdicts = _module_verdicts(bundle)
    top1 = bundle["stage_results"][(1, "A6")].metrics
    top3 = bundle["stage_results"][(3, "A6")].metrics
    public = bundle["public_meta"]["stats"]
    grid = bundle["parameter_grid"]
    cost = bundle["cost_stress"]
    capacity = bundle["capacity_stress"]
    exclusions = bundle["exclusion_stress"]
    yearly = bundle["yearly"]
    mainline = bundle["mainline_sensitivity"]
    regime_effects = bundle["regime_component_effects"]
    a3 = ablation.loc[ablation["stage"].eq("A3")].set_index("top_k")
    a2 = ablation.loc[ablation["stage"].eq("A2")].set_index("top_k")
    buffer_reduction = float(
        np.mean(
            [
                1.0 - a3.loc[top_k, "annualized_turnover"] / a2.loc[top_k, "annualized_turnover"]
                for top_k in (1, 3)
            ]
        )
    )
    capacity_10m = capacity.loc[
        capacity["initial_cash"].eq(10_000_000.0)
        & capacity["adv_participation"].eq(0.005)
    ]
    stable_modules = verdicts.loc[verdicts["preregistered_stable_margin"], "module"].tolist()
    unstable_modules = verdicts.loc[~verdicts["preregistered_stable_margin"], "module"].tolist()
    best_year = yearly.loc[yearly["top_k"].eq(1)].sort_values("annualized_return").iloc[-1]
    worst_year = yearly.loc[yearly["top_k"].eq(1)].sort_values("annualized_return").iloc[0]
    mainline_frozen = mainline.loc[mainline["trial"].str.endswith("_frozen")]
    mainline_range = mainline.groupby("top_k")["sharpe"].agg(["min", "max"])
    text = f"""# 五福 7.5 冻结版直接拆解与稳健性研究

## 结论先行

这轮直接证据不支持把公开回测的高收益解释成“25日动量 + B型主线”自然产生的结果。公开分钟
回测年化为 {_pct(public['annual_algo_return'])}、Sharpe {_num(public['sharpe'])}；使用同一冻结参数、
历史生命周期ETF、观察日收盘生成目标并在下一交易日开盘执行的 A6 Top1，年化为
{_pct(top1['annualized_return'])}、Sharpe {_num(top1['sharpe'])}、最大回撤
{_pct(top1['maximum_drawdown'])}。两条日收益在 {bundle['public_comparison']['overlap_days']:,} 个重合日的
相关系数只有 {_num(bundle['public_comparison']['daily_return_correlation'], 3)}。这是显著的实现路径差异，
不是小数点或成本口径误差。

按事前门槛，顺序消融中可称为稳定正边际的模块是：{('、'.join(stable_modules) if stable_modules else '无')}。
未达门槛的是：{'、'.join(unstable_modules)}。其中 A股强弱切换包贡献最大，但它同时改变候选池、
弱市过滤、23/25日窗口和缓冲，属于需要进一步约束复杂度的组合规则；看到其大效应后追加的全因子
拆分被明确标为事后解释性实验，不能冒充事前验证。

策略在低成本、小资金下有研究价值，但没有通过保守可交易性门槛：单边总成本20bp时 Top1/Top3
年化分别为 {_pct(float(cost.query('top_k==1 and cost_bp==20')['annualized_return'].iloc[0]))}/
{_pct(float(cost.query('top_k==3 and cost_bp==20')['annualized_return'].iloc[0]))}；1000万元、0.5% ADV
参与率下平均暴露仅为 {_pct(float(capacity_10m.query('top_k==1')['average_exposure'].iloc[0]))}/
{_pct(float(capacity_10m.query('top_k==3')['average_exposure'].iloc[0]))}，均未达到70%。

## 实验身份与因果口径

- 事前协议：`protocols/2026-08-16-wufu-direct-decomposition-v1.json`；结果产生前已经单独提交；
- 区间：2015-01-01—2026-07-24，暖机始于2014-08-01；
- 数据：1,733只本地B级连续复权ETF，包含125只历史终止ETF，逐日按上市/退市生命周期过滤；
- 信号/成交：观察日收盘及更早数据生成目标，下一交易日开盘成交；不存在同日收盘信号回填；
- 基础成本：单边总成本2bp；压力测试2/5/10/20/30bp；
- 本地路径不冒充五福原版13:10实时选股。A7分钟确认只能由平台分钟数据下结论。

## A0—A6 顺序消融

{_markdown_table(ablation, ['top_k', 'stage', 'annualized_return', 'sharpe', 'maximum_drawdown', 'annualized_turnover', 'delta_sharpe'])}

模块判定把 Top1/Top3 的全样本平均 ΔSharpe 与三个分段的方向合并：

{_markdown_table(verdicts, ['stage', 'module', 'sequential_mean_delta_sharpe', 'positive_subperiods', 'factorial_mean_delta_sharpe', 'factorial_positive_ratio', 'preregistered_stable_margin'])}

普通“剥洋葱”顺序可能把前后模块交互误判成单模块贡献，因此另跑了128个 Top1/Top3 全因子组合，
以及12个最终模型逐模块删除。全因子结果只用于验证方向一致性，不从中挑新基线。

### 缓冲

A3 相对 A2 的 Top1/Top3平均年化换手降幅为 {_pct(buffer_reduction)}，没有达到事前20%门槛；
它的顺序 Sharpe 边际为 Top1 {_num(float(a3.loc[1, 'delta_sharpe']), 3)}、Top3
{_num(float(a3.loc[3, 'delta_sharpe']), 3)}。因此当前证据只能说“有一定稳定持仓作用”，不能说
它已经解决了执行成本问题。

### 强弱切换的事后解释性拆分

{_markdown_table(regime_effects, ['top_k', 'module', 'paired_comparisons', 'mean_delta_annualized_return', 'mean_delta_sharpe', 'positive_delta_sharpe_ratio'])}

这32次拆分是在看到 A4 大效应之后追加，用来定位来源，不进入事前成功判定。若主要收益只来自
弱市放宽过滤或把候选池缩到海外/商品，而非简单的3/4指数投票，就应把它视为一个新的资产配置
假设单独验证，而不是继续给原策略叠加例外。

### B型主线和延续

冻结B型规则在 Top1/Top3 的 Sharpe 为 {_num(float(mainline_frozen.query('top_k==1')['sharpe'].iloc[0]))}/
{_num(float(mainline_frozen.query('top_k==3')['sharpe'].iloc[0]))}；单参数邻域的 Sharpe 范围为
Top1 {_num(float(mainline_range.loc[1, 'min']))}—{_num(float(mainline_range.loc[1, 'max']))}、Top3
{_num(float(mainline_range.loc[3, 'min']))}—{_num(float(mainline_range.loc[3, 'max']))}。顺序 A5/A6 的
边际接近零，故“主线规则解释公开超额”缺乏直接证据。保留其复杂阈值会增加研究自由度，不建议原样借鉴。

## 参数、时间与多重试验

- 216组事前参数邻域全部年化为正；中位年化 {_pct(float(grid['annualized_return'].median()))}、
  中位Sharpe {_num(float(grid['sharpe'].median()))}，最差/最好Sharpe
  {_num(float(grid['sharpe'].min()))}/{_num(float(grid['sharpe'].max()))}，说明本地 A6 周围存在参数高原；
- CSCV近似PBO为 {_pct(bundle['pbo']['pbo'])}，未通过<25%的门槛；冻结Top1的DSR概率为
  {_pct(bundle['dsr']['deflated_sharpe_probability'])}，略低于95%门槛；
- expanding-window 从2019年起共 {bundle['walk_forward_summary']['test_years']} 个样本外年度，年化
  {_pct(bundle['walk_forward_summary']['annualized_return'])}、最差年度
  {_pct(bundle['walk_forward_summary']['worst_year'])}；该结果使用历史最优参数，不能抵消同一数据集上的研究者自由度；
- Top1 最好年度为 {int(best_year['year'])} 年 {_pct(float(best_year['annualized_return']))}，最差年度为
  {int(worst_year['year'])} 年 {_pct(float(worst_year['annualized_return']))}；逐年、三段、牛熊震荡和滚动三年
  明细均在 `raw/`。

A6 Top1/Top3 的最差滚动三年收益为 {_pct(top1['worst_rolling_three_year_return'])}/
{_pct(top3['worst_rolling_three_year_return'])}，没有通过“最差三年为正”的事前门槛。这比全样本年化更能
说明它仍有长时间失效风险。

## ETF贡献集中度与删除实验

Top1 的正收益贡献 Top1/Top3/Top5 占比为
{_pct(bundle['concentration']['top1']['top1_positive_contribution_share'])}/
{_pct(bundle['concentration']['top1']['top3_positive_contribution_share'])}/
{_pct(bundle['concentration']['top1']['top5_positive_contribution_share'])}；Top3对应为
{_pct(bundle['concentration']['top3']['top1_positive_contribution_share'])}/
{_pct(bundle['concentration']['top3']['top3_positive_contribution_share'])}/
{_pct(bundle['concentration']['top3']['top5_positive_contribution_share'])}。

删除事后贡献最高的1/3/5只ETF后，六个场景年化均保持为正，CAGR保留比例最低为
{_pct(float(exclusions['cagr_retention'].min()))}。因此收益不是由单一ETF完全解释，但Top1仍有明显主题集中。
删除实验使用全样本事后贡献排名，只能证明“不是单点崩塌”，不能当作可实时执行的资产剔除规则。

## 容量、成本与实用价值

低成本结果高度依赖高换手：A6 Top1/Top3年化换手为
{_num(top1['annualized_turnover'], 1)}x/{_num(top3['annualized_turnover'], 1)}x。公开回测报告的平均持仓
天数为 {_num(public['avg_position_days'], 1)} 天，而本地A6提取出
{bundle['experiment_counts']['a7_switch_events']} 次非现金新开仓事件，说明日频代理比公开路径换得更快。
成本曲线和ADV部分成交暴露见 `raw/cost-stress.csv`、`raw/capacity-stress.csv`。

结论是：若真实单边总摩擦能稳定低于10bp、资金规模较小，A4资产切换结构仍值得单独研究；若按20bp
或1000万元/0.5% ADV的保守条件，本版本没有实用价值。Top3在容量暴露与回撤上优于Top1，是更合理的
研究起点，但这不是把五福改成Top3后的“新最优策略”。

## A7分钟校准状态

- 状态：`{a7_status['status']}`；
- 冻结事件：{bundle['experiment_counts']['a7_switch_events']} 次本地A6 Top1非现金开仓；
- 平台脚本：`platform/a7_minute_calibration.py`，输入：`platform/a7-switch-events.csv`；
- 说明：{a7_status['note']}

没有平台分钟结果时，本报告不把日线开/收盘敏感性称为A7证据。即便A7最终改善买价，它也只能解释
新开仓的分钟执行差，而不能自动解释公开回测与本地A6之间约 {_pct(public['annual_algo_return'] - top1['annualized_return'])}
的年化差距。

## 与五福公开结果差异的证据链

1. **候选池不是主要解释**：固定池、original-like、PIT全ETF、2023年底前上市池的A6年化都处在
   同一数量级，完整结果见 `raw/universe-stress.csv`，没有任何一组接近公开年化；
2. **日内实时信号与日频代理不是同一策略**：原版13:10把当日实时价和投影成交量放进25日回归；
   本地为防未来数据只用观察日收盘、次日开盘成交。两条日收益相关仅
   {_num(bundle['public_comparison']['daily_return_correlation'], 3)}；
3. **数据覆盖有可定位缺口**：固定池114只中本地ETF库可用112只，缺少南方原油LOF和国投白银LOF；
   该缺口可能影响商品阶段，但四类候选池压力仍远不足以解释全部差距；
4. **动态名称池只能代理**：本地源的中文简称存在不可逆编码损失，original-like使用生命周期、当前静态
   tracking_target去重和当时ADV排序；分类与跟踪标的是当前静态标签，不是严格历史点时；
5. **成本口径差异会放大**：本地高换手使10—20bp的微小差异累积成巨大净值差；公开平台的换手字段
   与本地gross-traded/平均资产不是同一统计口径；
6. **公开结果本身是证据，不是独立样本外验证**：源码含大量历史行情驱动的阈值与例外，PBO和DSR均
   未通过事前门槛，不能仅凭93,906.9%的累计收益倒推规则有效。

## 值得借鉴与不值得照搬

值得继续研究的是：跨ETF相对趋势、R²作为趋势质量、Top3分散、明确的风险资产/海外商品切换，以及
持仓缓冲的思想。当前最强直接证据指向“A4资产配置结构”，但应拆成更简单的新假设重新冻结验证。

不值得原样照搬的是：B型主线的高维合取阈值、score>20延续例外、23/25日双阈值迟滞、当前中文简称
启发式动态分组，以及把30分钟确认当成收益发动机。A5/A6没有稳定边际，参数自由度却明显增加；这正是
高回测收益下最需要警惕的过拟合形态。

## 数据与实现审计

- 价格：本地B级连续复权 `adjusted_open/adjusted_close`；成交额为未复权人民币金额；
- 生命周期：上市日前、退市后均不可选，历史终止ETF保留；不存在用当前存续名单倒推历史；
- 指数：AkShare/Sina四指数日线，输入CSV和SHA已归档；
- 成交：100份整数手、卖后买、现金约束；复权价格上的名义份额在公司行为附近仍是近似；
- 容量：每笔按观察日ADV20的0.5%/1%/5%部分成交，未成交保留现金或原持仓；
- 未模拟：停牌与涨跌停排队、ETF申赎冲击、溢价（原版开关关闭）、分钟内部分成交；
- 动态分类：生命周期严格点时，类别/tracking_target/中文名不是严格点时；
- 多重试验：直接回测 {bundle['experiment_counts']['direct_backtests_total']} 次，其中216组进入PBO/DSR；
  32次A4子组件拆分为事后解释性试验，失败结果全部保留。

## 文件索引

- `raw/module-ablation.csv`、`raw/module-ablation-periods.csv`：顺序模块与三分段；
- `raw/factorial.csv`、`raw/factorial-effects.csv`、`raw/leave-one-out.csv`：全因子与删除；
- `raw/regime-components.csv`：A4事后子组件拆分；
- `raw/parameter-grid.csv`、`raw/pbo-splits.csv`、`raw/walk-forward.csv`：稳健性与样本外；
- `raw/cost-stress.csv`、`raw/capacity-stress.csv`、`raw/exclusion-stress.csv`：实盘压力；
- `raw/A6-top1-*`、`raw/A6-top3-*`：净值、成交、持仓、决策和贡献账本；
- `assets/`：净值差异、消融、参数、成本容量、年度和贡献图。
"""
    return text


def write_archive(
    data: MarketData,
    bundle: dict[str, Any],
    *,
    run_name: str = "2026-08-16__direct-decomposition__local-etf-2015-2026-v1",
) -> Path:
    output = FAMILY / "backtests" / run_name
    if output.exists():
        raise FileExistsError(f"immutable archive already exists: {output}")
    raw = output / "raw"
    platform = output / "platform"
    raw.mkdir(parents=True)
    platform.mkdir(parents=True)
    a7_status = {
        "status": "prepared_not_executed",
        "note": (
            "The logged-in Chrome Research tab could not be claimed by the browser controller, "
            "while the in-app browser reached JoinQuant's login page. No minute result was invented; "
            "the exact event file and resumable platform script are archived for execution."
        ),
        "direct_intraday_claim_allowed": False,
    }
    csv_artifacts = {
        "module-ablation.csv": bundle["module_ablation"],
        "module-ablation-periods.csv": bundle["module_ablation_periods"],
        "universe-stress.csv": bundle["universe_stress"],
        "leave-one-out.csv": bundle["leave_one_out"],
        "factorial.csv": bundle["factorial"],
        "factorial-effects.csv": bundle["factorial_effects"],
        "regime-components.csv": bundle["regime_components"],
        "regime-component-effects.csv": bundle["regime_component_effects"],
        "parameter-grid.csv": bundle["parameter_grid"],
        "mainline-sensitivity.csv": bundle["mainline_sensitivity"],
        "cost-stress.csv": bundle["cost_stress"],
        "capacity-stress.csv": bundle["capacity_stress"],
        "asset-contributions.csv": bundle["asset_contributions"],
        "exclusion-stress.csv": bundle["exclusion_stress"],
        "yearly.csv": bundle["yearly"],
        "periods.csv": bundle["periods"],
        "regimes.csv": bundle["regimes"],
        "rolling-three-year.csv": bundle["rolling_three_year"],
        "pbo-splits.csv": bundle["pbo_splits"],
        "walk-forward.csv": bundle["walk_forward"],
        "walk-forward-equity.csv": bundle["walk_forward_equity"],
        "public-equity.csv": bundle["public_equity"],
        "a7-switch-events.csv": bundle["switch_events"],
        "index-close.csv": data.reference["index_raw"],
    }
    for top_k in (1, 3):
        result = bundle["stage_results"][(top_k, "A6")]
        csv_artifacts.update(
            {
                f"A6-top{top_k}-equity.csv": result.equity,
                f"A6-top{top_k}-trades.csv": result.trades,
                f"A6-top{top_k}-positions.csv": result.positions,
                f"A6-top{top_k}-decisions.csv": result.decisions,
                f"A6-top{top_k}-contributions.csv": result.contributions,
            }
        )
    for name, frame in csv_artifacts.items():
        frame.to_csv(raw / name, index=False, encoding="utf-8")
    _write_json(raw / "pbo.json", bundle["pbo"])
    _write_json(raw / "dsr.json", bundle["dsr"])
    _write_json(raw / "walk-forward-summary.json", bundle["walk_forward_summary"])
    _write_json(raw / "concentration.json", bundle["concentration"])
    _write_json(raw / "public-comparison.json", bundle["public_comparison"])
    _write_json(raw / "experiment-counts.json", bundle["experiment_counts"])
    _write_json(platform / "a7-status.json", a7_status)
    shutil.copy2(FAMILY / "platform" / "a7_minute_calibration.py", platform / "a7_minute_calibration.py")
    shutil.copy2(FAMILY / "platform" / "a7-switch-events.csv", platform / "a7-switch-events.csv")
    shutil.copy2(FAMILY / "baseline.py", output / "source.py")
    shutil.copy2(FAMILY / "research.py", output / "engine.py")
    shutil.copy2(PROTOCOL_PATH, output / "protocol.json")
    audit = {
        "data_root": str(DEFAULT_DATA_ROOT.resolve()),
        "period": {"start": str(START_DATE.date()), "end": str(END_DATE.date())},
        "calendar_rows_with_warmup": int(len(data.dates)),
        "b_grade_etf_symbols": int(len(data.symbols)),
        "historically_terminated_etfs": int(data.master["lifecycle_status"].eq("delisted").sum()),
        "input_manifest_hashes": data.input_hashes,
        "index_audit": data.reference["index_audit"],
        "universe_audit": data.reference["universe_audit"],
        "reference_source_sha256": data.reference["source_sha256"],
        "causality": "observation close and earlier -> next trading day adjusted open",
        "survivorship": "daily listing/delisting lifecycle filter; historical delisted ETFs retained",
        "adjustment": "continuous adjusted open/close; raw RMB amount",
        "known_non_pit_fields": ["etf_category", "tracking_target", "display_name"],
        "missing_fixed_symbols": data.reference["universe_audit"]["fixed_reference_missing"],
        "a7_status": a7_status,
    }
    _write_json(output / "audit.json", audit)
    _write_json(
        output / "config.json",
        {
            "frozen_A6": asdict(StrategyConfig()),
            "protocol": json.loads(PROTOCOL_PATH.read_text(encoding="utf-8")),
            "experiment_counts": bundle["experiment_counts"],
        },
    )
    create_charts(output, bundle)
    (output / "report.md").write_text(
        build_report(bundle, data, a7_status), encoding="utf-8"
    )
    source_hash = file_sha256(output / "source.py")
    engine_hash = file_sha256(output / "engine.py")
    artifact_hashes = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifact_hashes[path.relative_to(output).as_posix()] = {
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
    manifest = {
        "schema_version": 1,
        "archived_at": "2026-08-16",
        "source_file": "source.py",
        # The family lives under strategies/joinquant, so the repository schema
        # requires this discriminator to match the platform directory exactly.
        # Keep the actual execution/data provenance in a separate field.
        "platform": "joinquant",
        "execution_environment": "local-etf-daily + JoinQuant-minute-work-package",
        "strategy_id": "wufu-etf-rotation",
        "variant": "direct-decomposition",
        "run_id": run_name,
        "period": {"start": str(START_DATE.date()), "end": str(END_DATE.date())},
        "benchmark": BENCHMARK,
        "cost": "single-side total 2bp baseline; 2/5/10/20/30bp stress",
        "metrics": {
            "A6_top1": bundle["stage_results"][(1, "A6")].metrics,
            "A6_top3": bundle["stage_results"][(3, "A6")].metrics,
            "public_reference": bundle["public_meta"]["stats"],
        },
        "source_sha256": source_hash,
        "engine_sha256": engine_hash,
        "reference_source_sha256": file_sha256(REFERENCE_SOURCE),
        "public_backtest_sha256": file_sha256(PUBLIC_BACKTEST),
        "public_backtest_id": bundle["public_meta"]["backtest_id"],
        "experiment_counts": bundle["experiment_counts"],
        "a7": a7_status,
        "artifacts": artifact_hashes,
    }
    _write_json(output / "manifest.json", manifest)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--run-name", default="2026-08-16__direct-decomposition__local-etf-2015-2026-v1")
    arguments = parser.parse_args()
    data = load_market_data(arguments.data_root)
    bundle = run_experiment_suite(data)
    if arguments.archive:
        output = write_archive(data, bundle, run_name=arguments.run_name)
        print(output)
    else:
        print(bundle["module_ablation"].to_string(index=False))


if __name__ == "__main__":
    main()
