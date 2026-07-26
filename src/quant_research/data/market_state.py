"""从 Qlib 日线推导停牌和日频可交易状态。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .store import ResearchDataStore, sha256_file


MARKET_STATE_COLUMNS = [
    "symbol",
    "trade_date",
    "paused",
    "is_st",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "previous_raw_close",
    "high_limit",
    "low_limit",
    "one_price",
    "buy_blocked",
    "sell_blocked",
    "status_quality",
    "st_quality",
    "limit_quality",
    "source",
]


def price_limit_rate(board: str, date, is_st=False) -> float:
    date = pd.Timestamp(date).normalize()
    if is_st is True:
        return 0.05
    if board == "beijing":
        return 0.30
    if board == "star":
        return 0.20
    if board == "chinext" and date >= pd.Timestamp("2020-08-24"):
        return 0.20
    return 0.10


def round_price_limit(value: pd.Series | np.ndarray) -> np.ndarray:
    values = np.asarray(value, dtype=float)
    return np.floor(values * 100.0 + 0.5) / 100.0


def build_market_state(
    features: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    security_master: pd.DataFrame,
    symbols: list[str],
) -> pd.DataFrame:
    required = {"symbol", "trade_date", "open", "high", "low", "close", "volume", "factor"}
    missing = required.difference(features.columns)
    if missing:
        raise ValueError(f"market features are missing columns: {sorted(missing)}")
    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    features = features.copy()
    features["trade_date"] = pd.to_datetime(features["trade_date"]).dt.normalize()
    features_by_symbol = {
        symbol: group.set_index("trade_date").sort_index()
        for symbol, group in features.groupby("symbol", sort=False)
    }
    master = security_master.set_index("symbol")
    rows = []
    for symbol in sorted(set(symbols)):
        if symbol not in master.index:
            continue
        security = master.loc[symbol]
        active_dates = calendar[
            (calendar >= pd.Timestamp(security["start_date"]))
            & (calendar <= pd.Timestamp(security["end_date"]))
        ]
        if active_dates.empty:
            continue
        group = features_by_symbol.get(symbol)
        if group is None:
            group = pd.DataFrame(columns=features.columns).set_index("trade_date")
        group = group.reindex(active_dates)
        factor = pd.to_numeric(group["factor"], errors="coerce")
        result = pd.DataFrame(index=active_dates)
        result["symbol"] = symbol
        result["trade_date"] = active_dates
        for field in ("open", "high", "low", "close"):
            result[f"raw_{field}"] = pd.to_numeric(
                group[field], errors="coerce"
            ).to_numpy() / factor.to_numpy()
        volume = pd.to_numeric(group["volume"], errors="coerce")
        result["paused"] = (
            result[["raw_open", "raw_high", "raw_low", "raw_close"]]
            .isna()
            .any(axis=1)
            | volume.fillna(0.0).le(0.0).to_numpy()
        )
        previous_close = result["raw_close"].ffill().shift(1)
        result["previous_raw_close"] = previous_close
        rate = np.array(
            [price_limit_rate(str(security["board"]), date) for date in active_dates]
        )
        result["high_limit"] = round_price_limit(previous_close * (1.0 + rate))
        result["low_limit"] = round_price_limit(previous_close * (1.0 - rate))
        result.loc[previous_close.isna(), ["high_limit", "low_limit"]] = np.nan
        result["is_st"] = pd.array([pd.NA] * len(result), dtype="boolean")
        result["one_price"] = (
            result[["raw_open", "raw_high", "raw_low", "raw_close"]]
            .nunique(axis=1, dropna=False)
            .eq(1)
            & ~result["paused"]
        )
        result["buy_blocked"] = result["paused"] | (
            result["raw_open"] >= result["high_limit"] - 0.001
        )
        result["sell_blocked"] = result["paused"] | (
            result["raw_open"] <= result["low_limit"] + 0.001
        )
        result["status_quality"] = QualityGrade.B.value
        result["st_quality"] = QualityGrade.C.value
        result["limit_quality"] = QualityGrade.C.value
        result["source"] = "qlib-community-cn/derived"
        rows.append(result.reset_index(drop=True))
    if not rows:
        raise ValueError("market state has no active securities")
    output = pd.concat(rows, ignore_index=True)[MARKET_STATE_COLUMNS]
    validate_market_state(output)
    return output


def validate_market_state(frame: pd.DataFrame) -> None:
    missing = set(MARKET_STATE_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"market state is missing columns: {sorted(missing)}")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ValueError("market state contains duplicate symbol/date rows")
    invalid_limits = frame.dropna(subset=["high_limit", "low_limit"])
    if (invalid_limits["high_limit"] <= invalid_limits["low_limit"]).any():
        raise ValueError("market state contains inverted price limits")


def save_market_state(
    store: ResearchDataStore,
    frame: pd.DataFrame,
    qlib_dir: Path,
    requested_symbols: int,
) -> DatasetManifest:
    data_file = store.write_parquet("daily_market_state", frame)
    calendar_file = qlib_dir / "calendars" / "day.txt"
    manifest = DatasetManifest(
        schema_version=1,
        dataset="daily_market_state",
        provider="qlib-community-cn/derived",
        quality_grade=QualityGrade.C,
        row_count=len(frame),
        columns=list(frame.columns),
        data_files=[data_file],
        date_range={
            "start": frame["trade_date"].min().strftime("%Y-%m-%d"),
            "end": frame["trade_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=[
            {
                "path": str(calendar_file),
                "bytes": calendar_file.stat().st_size,
                "sha256": sha256_file(calendar_file),
            }
        ],
        notes=[
            f"请求 {requested_symbols} 只证券。",
            "停牌由有效上市区间内缺少 OHLC 或成交量为零推导，质量 B。",
            "历史 ST 数据尚不可用，is_st 保持未知，质量 C。",
            "涨跌停按板块和日期规则、非 ST 假设推导，质量 C。",
        ],
    )
    store.write_manifest(manifest)
    return manifest
