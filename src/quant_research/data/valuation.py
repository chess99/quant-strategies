"""东方财富历史估值数据适配。"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .security_lifecycle import clip_to_security_lifecycle
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
    frame = frame.dropna(subset=["trade_date", "market_cap"])
    frame = frame.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    frame["symbol"] = symbol.upper()
    if "_provider_source" in raw.columns:
        sources = raw["_provider_source"].dropna().astype(str)
        source = sources.iloc[0] if not sources.empty else "unknown"
    else:
        source = "akshare/eastmoney-stock-value"
    frame["source"] = source
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


@dataclass
class HybridValuationProvider:
    """东方财富为主；北交所或失败代码回退到百度公开估值。"""

    eastmoney: EastmoneyValuationProvider | None = None

    def __post_init__(self) -> None:
        if self.eastmoney is None:
            self.eastmoney = EastmoneyValuationProvider()

    def fetch(self, symbol: str) -> pd.DataFrame:
        try:
            return self.eastmoney.fetch(symbol)
        except Exception as eastmoney_error:  # noqa: BLE001 - explicit fallback
            try:
                return self._fetch_baidu(symbol)
            except Exception as baidu_error:  # noqa: BLE001
                raise RuntimeError(
                    f"Eastmoney failed ({eastmoney_error}); "
                    f"Baidu failed ({baidu_error})"
                ) from baidu_error

    @staticmethod
    def _fetch_baidu(symbol: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare is required for valuation downloads") from exc
        fields = {
            "总市值": "总市值",
            "市盈率(TTM)": "PE(TTM)",
            "市盈率(静)": "PE(静)",
            "市净率": "市净率",
            "市现率": "市现率",
        }
        merged = None
        for indicator, target in fields.items():
            raw = ak.stock_zh_valuation_baidu(
                symbol=symbol[2:],
                indicator=indicator,
                period="全部",
            )
            if raw is None or raw.empty:
                raise ValueError(f"empty Baidu valuation: {symbol} {indicator}")
            part = raw[["date", "value"]].rename(
                columns={"date": "数据日期", "value": target}
            )
            merged = (
                part
                if merged is None
                else merged.merge(part, on="数据日期", how="outer")
            )
        assert merged is not None
        merged["总市值"] = pd.to_numeric(
            merged["总市值"], errors="coerce"
        ) * 100_000_000.0
        for column in EASTMONEY_COLUMN_MAP:
            if column not in merged:
                merged[column] = np.nan
        merged["_provider_source"] = "akshare/baidu-stock-valuation"
        return merged


def _latest_raw_path(store: ResearchDataStore, symbol: str) -> Path | None:
    candidates = []
    for provider in ("eastmoney", "baidu"):
        directory = store.raw_dir / provider / "valuation"
        candidates.extend(directory.glob(f"{symbol.lower()}__*.csv"))
    candidates = sorted(candidates)
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


def _persist_valuation_raw(
    store: ResearchDataStore,
    symbol: str,
    raw: pd.DataFrame,
    fetched: bool,
) -> dict | None:
    if not fetched:
        path = _latest_raw_path(store, symbol)
        if path is None:
            return None
        return {
            "path": path.relative_to(store.root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    last_date = pd.to_datetime(raw["数据日期"]).max()
    payload_hash = hashlib.sha256(
        raw.to_csv(index=False).encode("utf-8-sig")
    ).hexdigest()[:12]
    provider_source = (
        str(raw["_provider_source"].dropna().iloc[0])
        if "_provider_source" in raw
        and not raw["_provider_source"].dropna().empty
        else "akshare/eastmoney-stock-value"
    )
    raw_provider = "baidu" if "baidu" in provider_source.lower() else "eastmoney"
    return store.write_raw_csv(
        raw_provider,
        "valuation",
        f"{symbol.lower()}__{last_date:%Y-%m-%d}__{payload_hash}.csv",
        raw,
    )


def sync_valuation(
    store: ResearchDataStore,
    symbols: list[str],
    provider: EastmoneyValuationProvider | HybridValuationProvider | None = None,
    workers: int = 6,
    refresh: bool = False,
) -> tuple[pd.DataFrame, DatasetManifest, dict[str, str]]:
    provider = provider or HybridValuationProvider()
    symbols = sorted({str(symbol).upper() for symbol in symbols})
    master = store.read_parquet("security_master").set_index("symbol")
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
                frame = normalize_eastmoney_valuation(symbol, raw)
                if symbol in master.index:
                    frame = clip_to_security_lifecycle(
                        frame,
                        master.loc[symbol],
                        date_column="trade_date",
                    )
                if frame.empty:
                    raise ValueError(f"valuation has no rows inside lifecycle: {symbol}")
                normalized.append(frame)
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


def _valuation_status_path(store: ResearchDataStore) -> Path:
    return store.normalized_path("valuation_sync_status")


def _checkpoint_valuation_status(
    store: ResearchDataStore,
    records: list[dict],
) -> pd.DataFrame:
    frame = (
        pd.DataFrame(records)
        .drop_duplicates("symbol", keep="last")
        .sort_values("symbol")
        .reset_index(drop=True)
    )
    store.write_parquet("valuation_sync_status", frame)
    return frame


def sync_valuation_partitions(
    store: ResearchDataStore,
    symbols: list[str],
    *,
    active_symbols: set[str] | None = None,
    provider: EastmoneyValuationProvider | HybridValuationProvider | None = None,
    workers: int = 8,
    refresh: bool = False,
    resume: bool = True,
    checkpoint_every: int = 25,
) -> tuple[pd.DataFrame, DatasetManifest]:
    """逐证券同步并落盘，避免全市场估值一次驻留内存。"""

    provider = provider or HybridValuationProvider()
    symbols = sorted({str(symbol).upper() for symbol in symbols})
    master = store.read_parquet("security_master").set_index("symbol")
    active_symbols = {
        str(symbol).upper()
        for symbol in (symbols if active_symbols is None else active_symbols)
    }
    existing = (
        pd.read_parquet(_valuation_status_path(store))
        if resume and _valuation_status_path(store).is_file()
        else pd.DataFrame()
    )
    completed = (
        set(existing.loc[existing["status"] == "success", "symbol"])
        if not existing.empty and not refresh
        else set()
    )
    records = existing.to_dict("records") if not existing.empty else []
    pending = [symbol for symbol in symbols if symbol not in completed]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        pending_iterator = iter(pending)
        futures = {}
        for _ in range(max(1, workers) * 2):
            symbol = next(pending_iterator, None)
            if symbol is None:
                break
            future = executor.submit(
                _load_or_fetch_raw,
                store,
                provider,
                symbol,
                refresh,
            )
            futures[future] = symbol
        number = 0
        while futures:
            future = next(as_completed(futures))
            symbol = futures.pop(future)
            number += 1
            try:
                _, raw, fetched = future.result()
                normalized = normalize_eastmoney_valuation(symbol, raw)
                if symbol in master.index:
                    normalized = clip_to_security_lifecycle(
                        normalized,
                        master.loc[symbol],
                        date_column="trade_date",
                    )
                raw_symbol = symbol
                security = master.loc[symbol] if symbol in master.index else None
                canonical_symbol = (
                    str(security.get("canonical_symbol"))
                    if security is not None
                    and pd.notna(security.get("canonical_symbol"))
                    else symbol
                )
                if normalized.empty and canonical_symbol != symbol:
                    _, raw, fetched = _load_or_fetch_raw(
                        store,
                        provider,
                        canonical_symbol,
                        refresh,
                    )
                    raw_symbol = canonical_symbol
                    normalized = normalize_eastmoney_valuation(symbol, raw)
                    normalized = clip_to_security_lifecycle(
                        normalized,
                        security,
                        date_column="trade_date",
                    )
                if normalized.empty:
                    raise ValueError(
                        f"valuation has no rows inside lifecycle: {symbol}"
                    )
                raw_artifact = _persist_valuation_raw(
                    store,
                    raw_symbol,
                    raw,
                    fetched,
                )
                artifact = store.write_parquet(
                    "daily_valuation",
                    normalized,
                    filename=f"symbol={symbol}/data.parquet",
                )
                records.append(
                    {
                        "symbol": symbol,
                        "status": "success",
                        "row_count": len(normalized),
                        "start": normalized["trade_date"].min(),
                        "end": normalized["trade_date"].max(),
                        "artifact_path": artifact["path"],
                        "artifact_bytes": artifact["bytes"],
                        "artifact_sha256": artifact["sha256"],
                        "raw_path": (
                            raw_artifact["path"] if raw_artifact is not None else None
                        ),
                        "raw_bytes": (
                            raw_artifact["bytes"] if raw_artifact is not None else None
                        ),
                        "raw_sha256": (
                            raw_artifact["sha256"] if raw_artifact is not None else None
                        ),
                        "error": None,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - provider failures are persisted
                records.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "row_count": 0,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            if number % checkpoint_every == 0:
                _checkpoint_valuation_status(store, records)
            next_symbol = next(pending_iterator, None)
            if next_symbol is not None:
                next_future = executor.submit(
                    _load_or_fetch_raw,
                    store,
                    provider,
                    next_symbol,
                    refresh,
                )
                futures[next_future] = next_symbol
    all_statuses = _checkpoint_valuation_status(store, records)
    statuses = all_statuses[all_statuses["symbol"].isin(symbols)].copy()
    successful = statuses[statuses["status"] == "success"].copy()
    if successful.empty:
        raise RuntimeError(
            "no valuation symbols succeeded: "
            + "; ".join(
                f"{row.symbol}={row.error}"
                for row in statuses.itertuples(index=False)
            )
        )
    artifacts = [
        {
            "path": row.artifact_path,
            "bytes": int(row.artifact_bytes),
            "sha256": row.artifact_sha256,
            "partition_values": {"symbol": row.symbol},
        }
        for row in successful.itertuples(index=False)
    ]
    sources = [
        {
            "path": row.raw_path,
            "bytes": int(row.raw_bytes),
            "sha256": row.raw_sha256,
        }
        for row in successful.itertuples(index=False)
        if pd.notna(row.raw_path)
    ]
    successful_symbols = set(successful["symbol"])
    current_covered = len(successful_symbols & active_symbols)
    manifest = DatasetManifest(
        schema_version=2,
        dataset="daily_valuation",
        provider="akshare/eastmoney-stock-value + baidu-stock-valuation",
        quality_grade=QualityGrade.B,
        row_count=int(successful["row_count"].sum()),
        columns=VALUATION_COLUMNS,
        data_files=artifacts,
        date_range={
            "start": pd.to_datetime(successful["start"]).min().strftime("%Y-%m-%d"),
            "end": pd.to_datetime(successful["end"]).max().strftime("%Y-%m-%d"),
        },
        source_files=sources,
        primary_key=["symbol", "trade_date"],
        date_fields={"trade_date": "交易日"},
        partitioning={"style": "hive", "columns": ["symbol"]},
        coverage={
            "requested_symbols": len(symbols),
            "successful_symbols": int(len(successful)),
            "failed_symbols": int((statuses["status"] == "failed").sum()),
            "current_expected": len(active_symbols),
            "current_covered": current_covered,
            "current_coverage_ratio": (
                current_covered / len(active_symbols) if active_symbols else 0.0
            ),
        },
        failures=[
            {
                "symbol": row.symbol,
                "status": row.status,
                "error": row.error,
            }
            for row in statuses.itertuples(index=False)
            if row.status != "success"
        ],
        limitations=[
            "东方财富历史估值从约2018年开始，不能覆盖更早时期。",
            "历史估值可能使用后来修订的财务值重算，质量为 B 而非严格 PIT A。",
        ],
        checks={
            "partition_files": len(artifacts),
            "current_coverage_target": 0.95,
            "current_coverage_passed": (
                current_covered / len(active_symbols) >= 0.95
                if active_symbols
                else False
            ),
            "duplicate_status_symbols": int(statuses["symbol"].duplicated().sum()),
        },
    )
    store.write_manifest(manifest)
    return statuses, manifest


BAIDU_INDICATORS = {
    "market_cap": "总市值",
    "pe_ttm": "市盈率(TTM)",
    "pb": "市净率",
}


def normalize_baidu_valuation(
    symbol: str,
    indicator: str,
    raw: pd.DataFrame,
) -> pd.DataFrame:
    if indicator not in BAIDU_INDICATORS:
        raise ValueError(f"unsupported Baidu valuation indicator: {indicator}")
    if raw is None or raw.empty or not {"date", "value"}.issubset(raw.columns):
        raise ValueError(f"Baidu valuation response is invalid: {symbol} {indicator}")
    frame = raw[["date", "value"]].rename(
        columns={"date": "trade_date", "value": indicator}
    )
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="coerce"
    ).dt.normalize()
    frame[indicator] = pd.to_numeric(frame[indicator], errors="coerce")
    frame = frame.dropna().drop_duplicates("trade_date", keep="last")
    if indicator == "market_cap":
        frame[indicator] *= 100_000_000.0
    frame["symbol"] = symbol.upper()
    return frame[["symbol", "trade_date", indicator]]


def verify_valuation_with_baidu(
    store: ResearchDataStore,
    symbols: list[str],
    *,
    period: str = "近一年",
) -> dict:
    """用百度股市通抽样交叉核验最新一年市值、PE 和 PB。"""

    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("akshare is required for valuation verification") from exc
    samples = []
    failures = []
    source_files = []
    for symbol in symbols:
        try:
            eastmoney = store.read_symbol_partitions("daily_valuation", [symbol])
            merged = eastmoney[["symbol", "trade_date", *BAIDU_INDICATORS]].copy()
            for field, provider_name in BAIDU_INDICATORS.items():
                raw = ak.stock_zh_valuation_baidu(
                    symbol=symbol[2:],
                    indicator=provider_name,
                    period=period,
                )
                artifact = store.write_raw_csv(
                    "baidu",
                    "valuation_verification",
                    f"{symbol.lower()}__{field}__{pd.Timestamp.today():%Y-%m-%d}.csv",
                    raw,
                )
                source_files.append(artifact)
                normalized = normalize_baidu_valuation(symbol, field, raw)
                merged = merged.merge(
                    normalized,
                    on=["symbol", "trade_date"],
                    how="inner",
                    suffixes=("_eastmoney", "_baidu"),
                )
            if merged.empty:
                raise ValueError("no common dates across providers")
            latest = merged.sort_values("trade_date").iloc[-1]
            record = {
                "symbol": symbol,
                "trade_date": latest["trade_date"].strftime("%Y-%m-%d"),
            }
            for field in BAIDU_INDICATORS:
                left = float(latest[f"{field}_eastmoney"])
                right = float(latest[f"{field}_baidu"])
                denominator = max(abs(left), abs(right), 1e-12)
                record[f"{field}_relative_error"] = abs(left - right) / denominator
            samples.append(record)
        except Exception as exc:  # noqa: BLE001 - failures belong in verification
            failures.append(
                {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
            )
    metrics = {}
    for field in BAIDU_INDICATORS:
        values = [
            row[f"{field}_relative_error"]
            for row in samples
            if np.isfinite(row[f"{field}_relative_error"])
        ]
        metrics[field] = {
            "median_relative_error": float(np.median(values)) if values else None,
            "p95_relative_error": float(np.quantile(values, 0.95)) if values else None,
        }
    report = {
        "schema_version": 1,
        "provider": "akshare/baidu-stock-valuation",
        "requested_symbols": len(symbols),
        "successful_symbols": len(samples),
        "failed_symbols": len(failures),
        "metrics": metrics,
        "samples": samples,
        "failures": failures,
        "source_files": source_files,
        "status": (
            "passed"
            if samples
            and metrics["market_cap"]["median_relative_error"] <= 0.02
            and metrics["pb"]["median_relative_error"] <= 0.05
            else "failed"
        ),
    }
    store.write_json_report("valuation_crosscheck", report)
    return report
