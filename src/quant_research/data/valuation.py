"""东方财富历史估值数据适配。"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .store import ResearchDataStore, sha256_file


VALUATION_COLUMNS = [
    "symbol",
    "trade_date",
    "close",
    "change_percent",
    "market_cap",
    "circulating_market_cap",
    "total_shares",
    "circulating_shares",
    "pe_ttm",
    "pe_static",
    "pb",
    "peg",
    "pcf",
    "ps",
    "source",
    "quality_grade",
]

EASTMONEY_COLUMN_MAP = {
    "数据日期": "trade_date",
    "当日收盘价": "close",
    "当日涨跌幅": "change_percent",
    "总市值": "market_cap",
    "流通市值": "circulating_market_cap",
    "总股本": "total_shares",
    "流通股本": "circulating_shares",
    "PE(TTM)": "pe_ttm",
    "PE(静)": "pe_static",
    "市净率": "pb",
    "PEG值": "peg",
    "市现率": "pcf",
    "市销率": "ps",
}


def normalize_eastmoney_valuation(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ValueError(f"valuation data is empty: {symbol}")
    missing = set(EASTMONEY_COLUMN_MAP).difference(raw.columns)
    if missing:
        raise ValueError(f"valuation response is missing columns: {sorted(missing)}")
    frame = raw.rename(columns=EASTMONEY_COLUMN_MAP)[
        list(EASTMONEY_COLUMN_MAP.values())
    ].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
    for column in set(EASTMONEY_COLUMN_MAP.values()).difference({"trade_date"}):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["trade_date", "close", "market_cap"])
    frame = frame.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    frame["symbol"] = symbol.upper()
    frame["source"] = "akshare/eastmoney-stock-value"
    frame["quality_grade"] = QualityGrade.B.value
    result = frame[VALUATION_COLUMNS].reset_index(drop=True)
    validate_valuation(result)
    return result


def validate_valuation(frame: pd.DataFrame) -> None:
    missing = set(VALUATION_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"valuation data is missing columns: {sorted(missing)}")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ValueError("valuation data contains duplicate symbol/date rows")
    if (frame["market_cap"] <= 0.0).any():
        raise ValueError("market_cap must be positive")
    valid_float_caps = frame["circulating_market_cap"].dropna()
    if (valid_float_caps <= 0.0).any():
        raise ValueError("circulating_market_cap must be positive when present")


@dataclass
class EastmoneyValuationProvider:
    retries: int = 3
    retry_delay: float = 0.5

    def fetch(self, symbol: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare is required for valuation downloads") from exc
        code = symbol[2:] if symbol[:2] in {"SH", "SZ", "BJ"} else symbol
        last_error = None
        for attempt in range(self.retries):
            try:
                frame = ak.stock_value_em(symbol=code)
                if frame is None or frame.empty:
                    raise ValueError("empty response")
                return frame
            except Exception as exc:  # provider errors vary by AkShare release
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        raise RuntimeError(f"valuation download failed for {symbol}: {last_error}")


def _latest_raw_path(store: ResearchDataStore, symbol: str) -> Path | None:
    directory = store.raw_dir / "eastmoney" / "valuation"
    candidates = sorted(directory.glob(f"{symbol.lower()}__*.csv"))
    return candidates[-1] if candidates else None


def _load_or_fetch_raw(
    store: ResearchDataStore,
    provider: EastmoneyValuationProvider,
    symbol: str,
    refresh: bool,
) -> tuple[str, pd.DataFrame, bool]:
    existing = _latest_raw_path(store, symbol)
    if existing is not None and not refresh:
        return symbol, pd.read_csv(existing), False
    return symbol, provider.fetch(symbol), True


def sync_valuation(
    store: ResearchDataStore,
    symbols: list[str],
    provider: EastmoneyValuationProvider | None = None,
    workers: int = 6,
    refresh: bool = False,
) -> tuple[pd.DataFrame, DatasetManifest, dict[str, str]]:
    provider = provider or EastmoneyValuationProvider()
    symbols = sorted({str(symbol).upper() for symbol in symbols})
    normalized = []
    raw_files = []
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(_load_or_fetch_raw, store, provider, symbol, refresh): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                _, raw, fetched = future.result()
                if fetched:
                    last_date = pd.to_datetime(raw["数据日期"]).max()
                    payload_hash = hashlib.sha256(
                        raw.to_csv(index=False).encode("utf-8-sig")
                    ).hexdigest()[:12]
                    raw_files.append(
                        store.write_raw_csv(
                            "eastmoney",
                            "valuation",
                            f"{symbol.lower()}__{last_date:%Y-%m-%d}__{payload_hash}.csv",
                            raw,
                        )
                    )
                else:
                    path = _latest_raw_path(store, symbol)
                    raw_files.append(
                        {
                            "path": path.relative_to(store.root).as_posix(),
                            "bytes": path.stat().st_size,
                            "sha256": sha256_file(path),
                        }
                    )
                normalized.append(normalize_eastmoney_valuation(symbol, raw))
            except Exception as exc:
                failures[symbol] = str(exc)
    if not normalized:
        raise RuntimeError(f"no valuation symbols succeeded: {failures}")
    new_data = pd.concat(normalized, ignore_index=True)
    try:
        previous = store.read_parquet("daily_valuation")
        previous = previous[~previous["symbol"].isin(new_data["symbol"].unique())]
        data = pd.concat([previous, new_data], ignore_index=True)
    except FileNotFoundError:
        data = new_data
    data = data.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    validate_valuation(data)
    data_file = store.write_parquet("daily_valuation", data)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="daily_valuation",
        provider="akshare/eastmoney-stock-value",
        quality_grade=QualityGrade.B,
        row_count=len(data),
        columns=list(data.columns),
        data_files=[data_file],
        date_range={
            "start": data["trade_date"].min().strftime("%Y-%m-%d"),
            "end": data["trade_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=sorted(raw_files, key=lambda item: item["path"]),
        notes=[
            "历史估值由东方财富按交易日返回。",
            "历史财务修订可能回填，因此估值质量为 B。",
            f"本次请求 {len(symbols)} 只，失败 {len(failures)} 只。",
        ],
    )
    store.write_manifest(manifest)
    return data, manifest, failures
