"""可恢复的全市场 ETF 主表、日线和元数据同步。"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .etf import ETF_DAILY_COLUMNS, normalize_sina_etf
from .etf_universe import (
    build_etf_candidates,
    build_etf_master,
    normalize_current_etf_lists,
    summarize_etf_coverage,
    symbol_for_etf_code,
)
from .store import ResearchDataStore, sha256_file


@dataclass(frozen=True)
class EtfSourceSnapshot:
    current: pd.DataFrame
    fund_names: pd.DataFrame
    sse_history: pd.DataFrame
    termination_announcements: pd.DataFrame
    source_files: list[dict]
    source_end: pd.Timestamp


@dataclass(frozen=True)
class EtfDownload:
    symbol: str
    quotes: pd.DataFrame | None
    dividends: pd.DataFrame | None
    profile: pd.DataFrame | None
    quote_error: str | None = None
    dividend_error: str | None = None
    profile_error: str | None = None


def _retry(
    operation: Callable[[], pd.DataFrame],
    *,
    attempts: int,
    initial_delay: float = 0.5,
) -> pd.DataFrame:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - status captures provider failures
            error = exc
            if attempt + 1 < attempts:
                time.sleep(initial_delay * (2**attempt))
    assert error is not None
    raise error


def _write_immutable_snapshot(
    store: ResearchDataStore,
    provider: str,
    dataset: str,
    filename: str,
    frame: pd.DataFrame,
) -> dict:
    """同名上游快照变化时保留旧文件，并用内容哈希保存新版本。"""

    try:
        return store.write_raw_csv(provider, dataset, filename, frame)
    except FileExistsError:
        payload = frame.to_csv(index=False).encode("utf-8-sig")
        digest = hashlib.sha256(payload).hexdigest()
        path = Path(filename)
        versioned = f"{path.stem}__sha256-{digest[:16]}{path.suffix}"
        return store.write_raw_csv(provider, dataset, versioned, frame)


def normalize_eastmoney_etf_profile(symbol: str, raw: pd.DataFrame) -> dict:
    if raw is None or raw.empty:
        raise ValueError(f"ETF profile is empty: {symbol}")
    row = raw.iloc[0]
    inception_text = str(row.get("成立日期/规模", ""))
    matched = pd.Series([inception_text]).str.extract(
        r"(?P<year>\d{4})年(?P<month>\d{2})月(?P<day>\d{2})日"
    )
    if matched.isna().any(axis=None):
        inception = pd.NaT
    else:
        inception = pd.to_datetime(
            f"{matched.loc[0, 'year']}-{matched.loc[0, 'month']}-"
            f"{matched.loc[0, 'day']}"
        )
    return {
        "symbol": symbol,
        "fund_full_name": row.get("基金全称"),
        "reported_fund_type": row.get("基金类型"),
        "inception_date": inception,
        "tracking_target": row.get("跟踪标的"),
        "profile_status": "success",
        "profile_error": None,
    }


def _month_end_sessions(calendar: pd.Series, start: str, end: pd.Timestamp) -> list[pd.Timestamp]:
    sessions = pd.to_datetime(calendar, errors="coerce").dropna()
    sessions = sessions[(sessions >= pd.Timestamp(start)) & (sessions <= end)]
    if sessions.empty:
        return []
    frame = pd.DataFrame({"session": sessions})
    return (
        frame.groupby(frame["session"].dt.to_period("M"))["session"]
        .max()
        .sort_values()
        .tolist()
    )


def _official_current_rows(
    sse: pd.DataFrame | None,
    szse: pd.DataFrame | None,
    *,
    source_end: pd.Timestamp,
) -> pd.DataFrame:
    records = []
    if sse is not None and not sse.empty:
        for payload in sse.to_dict("records"):
            records.append(
                {
                    "symbol": symbol_for_etf_code(payload["基金代码"]),
                    "display_name": payload.get("基金简称"),
                    "expected_active": True,
                    "in_sina": False,
                    "in_ths": False,
                    "latest_trade_date": source_end,
                    "reported_fund_type": payload.get("ETF类型"),
                }
            )
    if szse is not None and not szse.empty:
        for payload in szse.to_dict("records"):
            if str(payload.get("基金类别", "")).upper() != "ETF":
                continue
            records.append(
                {
                    "symbol": symbol_for_etf_code(payload["基金代码"]),
                    "display_name": payload.get("基金简称"),
                    "expected_active": True,
                    "in_sina": False,
                    "in_ths": False,
                    "latest_trade_date": source_end,
                    "reported_fund_type": payload.get("投资类别"),
                }
            )
    return pd.DataFrame(records)


def _merge_current_lists(current: pd.DataFrame, official: pd.DataFrame) -> pd.DataFrame:
    if official.empty:
        return current
    combined = pd.concat([current, official], ignore_index=True)
    records = []
    for symbol, group in combined.groupby("symbol", sort=True):
        records.append(
            {
                "symbol": symbol,
                "display_name": next(
                    (
                        value
                        for value in group["display_name"]
                        if pd.notna(value) and str(value).strip()
                    ),
                    None,
                ),
                "expected_active": bool(group["expected_active"].fillna(False).any()),
                "in_sina": bool(group["in_sina"].fillna(False).any()),
                "in_ths": bool(group["in_ths"].fillna(False).any()),
                "latest_trade_date": pd.to_datetime(
                    group["latest_trade_date"], errors="coerce"
                ).max(),
                "reported_fund_type": next(
                    (
                        value
                        for value in group["reported_fund_type"]
                        if pd.notna(value) and str(value).strip()
                    ),
                    None,
                ),
            }
        )
    return pd.DataFrame(records)


class AkshareEtfProvider:
    def __init__(self) -> None:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare is required for ETF synchronization") from exc
        self.ak = ak

    def current_sina(self) -> pd.DataFrame:
        return self.ak.fund_etf_category_sina("ETF基金")

    def current_ths(self) -> pd.DataFrame:
        return self.ak.fund_etf_spot_ths()

    def fund_names(self) -> pd.DataFrame:
        return self.ak.fund_name_em()

    def current_sse(self, source_end: pd.Timestamp) -> pd.DataFrame:
        return self.ak.fund_etf_scale_sse(source_end.strftime("%Y%m%d"))

    def current_szse(self) -> pd.DataFrame:
        return self.ak.fund_etf_scale_szse()

    def sse_snapshot(self, date: pd.Timestamp) -> pd.DataFrame:
        return self.ak.fund_etf_scale_sse(date.strftime("%Y%m%d"))

    def termination_announcements(
        self,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> pd.DataFrame:
        return self.ak.stock_zh_a_disclosure_report_cninfo(
            symbol="",
            market="基金",
            keyword="终止上市",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )

    def quotes(self, symbol: str) -> pd.DataFrame:
        return self.ak.fund_etf_hist_sina(symbol.lower())

    def dividends(self, symbol: str) -> pd.DataFrame:
        return self.ak.fund_etf_dividend_sina(symbol.lower())

    def profile(self, symbol: str) -> pd.DataFrame:
        return self.ak.fund_overview_em(symbol[2:])


def collect_etf_source_snapshot(
    store: ResearchDataStore,
    calendar: pd.Series,
    *,
    provider: AkshareEtfProvider | None = None,
    history_start: str = "2012-01-01",
    termination_start: str = "2005-01-01",
    termination_year_span: int = 4,
    attempts: int = 3,
) -> EtfSourceSnapshot:
    """下载当前交叉列表、上交所历史快照和巨潮终止上市公告。"""

    provider = provider or AkshareEtfProvider()
    current_sina = _retry(provider.current_sina, attempts=attempts)
    current_ths = _retry(provider.current_ths, attempts=attempts)
    fund_names = _retry(provider.fund_names, attempts=attempts)
    ths_dates = pd.to_datetime(
        current_ths.get("最新-交易日"), errors="coerce"
    ).dropna()
    latest_ths = ths_dates.mode().max() if not ths_dates.empty else pd.NaT
    source_end = max(
        pd.to_datetime(calendar).max().normalize(),
        latest_ths.normalize() if pd.notna(latest_ths) else pd.Timestamp.min,
    )
    try:
        current_sse = _retry(
            lambda: provider.current_sse(source_end), attempts=attempts
        )
    except Exception:  # noqa: BLE001 - the latest official snapshot is cross-check only
        current_sse = pd.DataFrame()
    try:
        current_szse = _retry(provider.current_szse, attempts=attempts)
    except Exception:  # noqa: BLE001 - current quote lists remain available
        current_szse = pd.DataFrame()

    source_files = [
        _write_immutable_snapshot(
            store,
            "sina",
            "etf_universe",
            f"current__{source_end:%Y-%m-%d}.csv",
            current_sina,
        ),
        _write_immutable_snapshot(
            store,
            "ths",
            "etf_universe",
            f"current__{source_end:%Y-%m-%d}.csv",
            current_ths,
        ),
        _write_immutable_snapshot(
            store,
            "eastmoney",
            "etf_universe",
            f"fund_names__{source_end:%Y-%m-%d}.csv",
            fund_names,
        ),
    ]
    if not current_sse.empty:
        source_files.append(
            _write_immutable_snapshot(
                store,
                "sse",
                "etf_universe",
                f"current__{source_end:%Y-%m-%d}.csv",
                current_sse,
            )
        )
    if not current_szse.empty:
        source_files.append(
            _write_immutable_snapshot(
                store,
                "szse",
                "etf_universe",
                f"current__{source_end:%Y-%m-%d}.csv",
                current_szse,
            )
        )

    history_frames = []
    for date in _month_end_sessions(calendar, history_start, source_end):
        cached_path = (
            store.raw_dir
            / "sse"
            / "etf_universe_history"
            / f"{date:%Y-%m-%d}.csv"
        )
        if cached_path.is_file():
            frame = pd.read_csv(cached_path, encoding="utf-8-sig")
        else:
            try:
                frame = _retry(
                    lambda selected=date: provider.sse_snapshot(selected),
                    attempts=attempts,
                )
            except Exception:  # noqa: BLE001 - old unavailable dates are explicit
                continue
        if frame.empty:
            continue
        frame = frame.copy()
        frame["requested_snapshot_date"] = date
        frame["candidate_source"] = "sse-history"
        history_frames.append(frame)
        if cached_path.is_file():
            source_files.append(
                {
                    "path": cached_path.relative_to(store.root).as_posix(),
                    "bytes": cached_path.stat().st_size,
                    "sha256": sha256_file(cached_path),
                }
            )
        else:
            source_files.append(
                _write_immutable_snapshot(
                    store,
                    "sse",
                    "etf_universe_history",
                    f"{date:%Y-%m-%d}.csv",
                    frame,
                )
            )
    sse_history = (
        pd.concat(history_frames, ignore_index=True)
        if history_frames
        else pd.DataFrame()
    )
    if termination_year_span < 1:
        raise ValueError("termination_year_span must be positive")
    termination_frames = []
    start_year = pd.Timestamp(termination_start).year
    for first_year in range(start_year, source_end.year + 1, termination_year_span):
        start_date = pd.Timestamp(f"{first_year}-01-01")
        end_year = min(first_year + termination_year_span - 1, source_end.year)
        end_date = min(pd.Timestamp(f"{end_year}-12-31"), source_end)
        cached_path = (
            store.raw_dir
            / "cninfo"
            / "etf_termination"
            / f"{start_date:%Y-%m-%d}__{end_date:%Y-%m-%d}.csv"
        )
        if cached_path.is_file():
            frame = pd.read_csv(cached_path, encoding="utf-8-sig")
        else:
            frame = _retry(
                lambda selected_start=start_date, selected_end=end_date: (
                    provider.termination_announcements(
                        selected_start,
                        selected_end,
                    )
                ),
                attempts=attempts,
            )
        if not frame.empty:
            termination_frames.append(frame)
        if cached_path.is_file():
            source_files.append(
                {
                    "path": cached_path.relative_to(store.root).as_posix(),
                    "bytes": cached_path.stat().st_size,
                    "sha256": sha256_file(cached_path),
                }
            )
        else:
            source_files.append(
                _write_immutable_snapshot(
                    store,
                    "cninfo",
                    "etf_termination",
                    f"{start_date:%Y-%m-%d}__{end_date:%Y-%m-%d}.csv",
                    frame,
                )
            )
    termination_announcements = (
        pd.concat(termination_frames, ignore_index=True)
        .drop_duplicates(["代码", "公告标题", "公告时间"])
        .reset_index(drop=True)
        if termination_frames
        else pd.DataFrame()
    )
    current = normalize_current_etf_lists(current_sina, current_ths)
    official = _official_current_rows(
        current_sse, current_szse, source_end=source_end
    )
    current = _merge_current_lists(current, official)
    return EtfSourceSnapshot(
        current=current,
        fund_names=fund_names,
        sse_history=sse_history,
        termination_announcements=termination_announcements,
        source_files=source_files,
        source_end=source_end,
    )


def write_etf_candidates(
    store: ResearchDataStore,
    snapshot: EtfSourceSnapshot,
) -> tuple[pd.DataFrame, DatasetManifest]:
    candidates = build_etf_candidates(
        snapshot.current,
        snapshot.fund_names,
        snapshot.sse_history,
        snapshot.termination_announcements,
    )
    data_file = store.write_parquet("etf_candidates", candidates)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="etf_candidates",
        provider="SSE + SZSE + CNINFO + Sina + THS + Eastmoney",
        quality_grade=QualityGrade.B,
        row_count=len(candidates),
        columns=list(candidates.columns),
        data_files=[data_file],
        date_range={"end": snapshot.source_end.strftime("%Y-%m-%d")},
        source_files=snapshot.source_files,
        primary_key=["symbol"],
        coverage={
            "expected_active": int(candidates["expected_active"].sum()),
            "historical_sse_symbols": int(
                candidates["seen_in_historical_exchange_snapshot"].sum()
            ),
            "cninfo_termination_symbols": int(
                candidates["seen_in_termination_announcement"].sum()
            ),
            "candidate_count": int(len(candidates)),
        },
        limitations=[
            "上交所历史池来自2012年以来逐月官方规模快照。",
            "沪深终止上市候选来自巨潮基金公告2005年至观察日的完整关键词分页；逐只行情决定实际交易区间。",
            "未正式上市或仅预留代码的候选保持C级，禁止进入历史可交易池。",
        ],
        checks={
            "allows_unverified_candidates": True,
            "historical_sources_cover_both_exchanges": bool(
                candidates["seen_in_termination_announcement"].any()
            ),
        },
    )
    store.write_manifest(manifest)
    return candidates, manifest


def _download_symbol(
    provider: AkshareEtfProvider,
    symbol: str,
    attempts: int,
) -> EtfDownload:
    try:
        quotes = _retry(lambda: provider.quotes(symbol), attempts=attempts)
        quote_error = None
    except Exception as exc:  # noqa: BLE001
        quotes = None
        quote_error = f"{type(exc).__name__}: {exc}"
    try:
        dividends = _retry(lambda: provider.dividends(symbol), attempts=attempts)
        dividend_error = None
    except Exception as exc:  # noqa: BLE001
        dividends = pd.DataFrame()
        dividend_error = f"{type(exc).__name__}: {exc}"
    try:
        profile = _retry(lambda: provider.profile(symbol), attempts=attempts)
        profile_error = None
    except Exception as exc:  # noqa: BLE001
        profile = None
        profile_error = f"{type(exc).__name__}: {exc}"
    return EtfDownload(
        symbol=symbol,
        quotes=quotes,
        dividends=dividends,
        profile=profile,
        quote_error=quote_error,
        dividend_error=dividend_error,
        profile_error=profile_error,
    )


def _status_path(store: ResearchDataStore) -> Path:
    return store.normalized_path("etf_sync_status")


def _load_existing_status(store: ResearchDataStore) -> pd.DataFrame:
    path = _status_path(store)
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _load_existing_profiles(store: ResearchDataStore) -> pd.DataFrame:
    path = store.normalized_path("etf_profiles")
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _artifact_for_symbol(store: ResearchDataStore, symbol: str) -> dict | None:
    path = store.normalized_path(
        "etf_daily", f"symbol={symbol}/data.parquet"
    )
    if not path.is_file():
        return None
    return {
        "path": path.relative_to(store.root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "partition_values": {"symbol": symbol},
    }


def sync_etf_daily(
    store: ResearchDataStore,
    candidates: pd.DataFrame,
    *,
    provider: AkshareEtfProvider | None = None,
    workers: int = 8,
    attempts: int = 3,
    resume: bool = True,
    checkpoint_every: int = 25,
) -> tuple[pd.DataFrame, pd.DataFrame, DatasetManifest]:
    """逐只下载并立刻落盘；状态表使长任务可断点续跑。"""

    provider = provider or AkshareEtfProvider()
    existing_status = _load_existing_status(store) if resume else pd.DataFrame()
    existing_profiles = _load_existing_profiles(store) if resume else pd.DataFrame()
    completed = set()
    completed_profiles = (
        set(
            existing_profiles.loc[
                existing_profiles["profile_status"] == "success", "symbol"
            ]
        )
        if not existing_profiles.empty
        else set()
    )
    if not existing_status.empty:
        for row in existing_status.itertuples(index=False):
            if row.status in {"success", "empty"} and row.symbol in completed_profiles:
                completed.add(row.symbol)
    symbols = [
        symbol
        for symbol in candidates["symbol"].astype(str)
        if symbol not in completed
    ]
    status_records = (
        existing_status.to_dict("records") if not existing_status.empty else []
    )
    profile_records = (
        existing_profiles.to_dict("records") if not existing_profiles.empty else []
    )

    def checkpoint() -> None:
        statuses = (
            pd.DataFrame(status_records)
            .drop_duplicates("symbol", keep="last")
            .sort_values("symbol")
            .reset_index(drop=True)
        )
        profiles = (
            pd.DataFrame(profile_records)
            .drop_duplicates("symbol", keep="last")
            .sort_values("symbol")
            .reset_index(drop=True)
        )
        if not statuses.empty:
            store.write_parquet("etf_sync_status", statuses)
        if not profiles.empty:
            store.write_parquet("etf_profiles", profiles)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(_download_symbol, provider, symbol, attempts): symbol
            for symbol in symbols
        }
        for index, future in enumerate(as_completed(futures), start=1):
            download = future.result()
            symbol = download.symbol
            quote_error = download.quote_error
            normalized = None
            quote_artifact = None
            dividend_artifact = None
            if download.quotes is not None and not download.quotes.empty:
                try:
                    quote_artifact = store.write_raw_csv(
                        "sina",
                        "etf_daily_full",
                        (
                            f"{symbol.lower()}__quotes__"
                            f"{pd.to_datetime(download.quotes['date']).max():%Y-%m-%d}.csv"
                        ),
                        download.quotes,
                    )
                    if download.dividends is not None:
                        dividend_artifact = store.write_raw_csv(
                            "sina",
                            "etf_daily_full",
                            f"{symbol.lower()}__dividends__"
                            f"{pd.Timestamp.today():%Y-%m-%d}.csv",
                            download.dividends,
                        )
                    normalized = normalize_sina_etf(
                        symbol, download.quotes, download.dividends
                    )
                    store.write_parquet(
                        "etf_daily",
                        normalized,
                        filename=f"symbol={symbol}/data.parquet",
                    )
                    status = "success"
                except Exception as exc:  # noqa: BLE001
                    quote_error = f"{type(exc).__name__}: {exc}"
                    status = "failed"
            elif download.quotes is not None:
                status = "empty"
            else:
                status = "failed"

            if download.profile is not None and not download.profile.empty:
                try:
                    profile_artifact = store.write_raw_csv(
                        "eastmoney",
                        "etf_profiles",
                        f"{symbol.lower()}__{pd.Timestamp.today():%Y-%m-%d}.csv",
                        download.profile,
                    )
                    profile_record = normalize_eastmoney_etf_profile(
                        symbol, download.profile
                    )
                    profile_record["profile_raw_path"] = profile_artifact["path"]
                    profile_record["profile_raw_bytes"] = profile_artifact["bytes"]
                    profile_record["profile_raw_sha256"] = profile_artifact["sha256"]
                    profile_records.append(profile_record)
                except Exception as exc:  # noqa: BLE001
                    profile_records.append(
                        {
                            "symbol": symbol,
                            "profile_status": "failed",
                            "profile_error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            else:
                profile_records.append(
                    {
                        "symbol": symbol,
                        "profile_status": (
                            "empty"
                            if download.profile is not None
                            else "failed"
                        ),
                        "profile_error": download.profile_error,
                    }
                )
            status_records.append(
                {
                    "symbol": symbol,
                    "status": status,
                    "first_trade_date": (
                        normalized["trade_date"].min()
                        if normalized is not None
                        else pd.NaT
                    ),
                    "last_trade_date": (
                        normalized["trade_date"].max()
                        if normalized is not None
                        else pd.NaT
                    ),
                    "row_count": len(normalized) if normalized is not None else 0,
                    "error": quote_error,
                    "dividend_status": (
                        "failed"
                        if download.dividend_error
                        else (
                            "success"
                            if download.dividends is not None
                            and not download.dividends.empty
                            else "empty"
                        )
                    ),
                    "dividend_error": download.dividend_error,
                    "quote_raw_path": (
                        quote_artifact["path"] if quote_artifact else None
                    ),
                    "dividend_raw_path": (
                        dividend_artifact["path"] if dividend_artifact else None
                    ),
                }
            )
            if index % checkpoint_every == 0:
                checkpoint()
    checkpoint()

    statuses = _load_existing_status(store)
    profiles = _load_existing_profiles(store)
    artifacts = []
    raw_artifacts = []
    for symbol in statuses.loc[statuses["status"] == "success", "symbol"]:
        artifact = _artifact_for_symbol(store, symbol)
        if artifact is not None:
            artifacts.append(artifact)
    for raw_path in pd.concat(
        [
            statuses.get("quote_raw_path", pd.Series(dtype=str)),
            statuses.get("dividend_raw_path", pd.Series(dtype=str)),
        ],
        ignore_index=True,
    ).dropna():
        path = store.root / str(raw_path)
        if path.is_file():
            raw_artifacts.append(
                {
                    "path": str(raw_path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    successful = statuses[statuses["status"] == "success"]
    failures = [
        {
            "symbol": row.symbol,
            "status": row.status,
            "error": row.error,
        }
        for row in statuses.itertuples(index=False)
        if row.status != "success"
    ]
    manifest = DatasetManifest(
        schema_version=2,
        dataset="etf_daily",
        provider="akshare/sina",
        quality_grade=QualityGrade.B,
        row_count=int(successful["row_count"].sum()),
        columns=ETF_DAILY_COLUMNS,
        data_files=artifacts,
        source_files=raw_artifacts,
        date_range=(
            {
                "start": pd.to_datetime(successful["first_trade_date"])
                .min()
                .strftime("%Y-%m-%d"),
                "end": pd.to_datetime(successful["last_trade_date"])
                .max()
                .strftime("%Y-%m-%d"),
            }
            if not successful.empty
            else None
        ),
        primary_key=["symbol", "trade_date"],
        date_fields={"trade_date": "交易日"},
        partitioning={"style": "hive", "columns": ["symbol"]},
        coverage={
            "candidate_count": int(len(candidates)),
            "attempted_count": int(len(statuses)),
            "successful_symbols": int((statuses["status"] == "success").sum()),
            "empty_symbols": int((statuses["status"] == "empty").sum()),
            "failed_symbols": int((statuses["status"] == "failed").sum()),
        },
        failures=failures,
        limitations=[
            "新浪提供原始行情，不提供权威份额拆并因子；常见倍率由价格跳变识别。",
            "现金分红来自新浪累计分红表；分红接口失败的证券在逐只状态表中显式记录。",
        ],
        checks={
            "partition_files": len(artifacts),
            "duplicate_status_symbols": int(statuses["symbol"].duplicated().sum()),
        },
    )
    store.write_manifest(manifest)
    profile_file = {
        "path": store.normalized_path("etf_profiles").relative_to(store.root).as_posix(),
        "bytes": store.normalized_path("etf_profiles").stat().st_size,
        "sha256": sha256_file(store.normalized_path("etf_profiles")),
    }
    profile_sources = []
    for row in profiles.itertuples(index=False):
        raw_path = getattr(row, "profile_raw_path", None)
        if pd.isna(raw_path) or not raw_path:
            matches = sorted(
                (
                    store.raw_dir
                    / "eastmoney"
                    / "etf_profiles"
                ).glob(f"{row.symbol.lower()}__*.csv")
            )
            raw_path = (
                matches[-1].relative_to(store.root).as_posix() if matches else None
            )
        if not raw_path:
            continue
        path = store.root / str(raw_path)
        if path.is_file():
            profile_sources.append(
                {
                    "path": str(raw_path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    profile_manifest = DatasetManifest(
        schema_version=1,
        dataset="etf_profiles",
        provider="akshare/eastmoney",
        quality_grade=QualityGrade.B,
        row_count=len(profiles),
        columns=list(profiles.columns),
        data_files=[profile_file],
        source_files=profile_sources,
        primary_key=["symbol"],
        date_fields={"inception_date": "基金成立日期"},
        coverage={
            "candidate_count": int(len(candidates)),
            "successful_profiles": int(
                (profiles["profile_status"] == "success").sum()
            ),
            "failed_profiles": int(
                (profiles["profile_status"] != "success").sum()
            ),
        },
        failures=[
            {
                "symbol": row.symbol,
                "status": row.profile_status,
                "error": row.profile_error,
            }
            for row in profiles.itertuples(index=False)
            if row.profile_status != "success"
        ],
        checks={"allows_unverified_candidates": True},
    )
    store.write_manifest(profile_manifest)
    return statuses, profiles, manifest


def finalize_etf_master(
    store: ResearchDataStore,
    candidates: pd.DataFrame,
    statuses: pd.DataFrame,
    profiles: pd.DataFrame,
    *,
    source_end: pd.Timestamp,
    candidate_manifest: DatasetManifest | dict,
) -> tuple[pd.DataFrame, DatasetManifest, Path]:
    master = build_etf_master(
        candidates,
        profiles,
        statuses,
        source_end=source_end,
    )
    data_file = store.write_parquet("etf_master", master)
    coverage = summarize_etf_coverage(master)
    yearly = []
    successful = master[master["bar_status"] == "success"].copy()
    if not successful.empty:
        first_year = int(successful["first_trade_date"].dt.year.min())
        last_year = int(successful["last_trade_date"].dt.year.max())
        for year in range(first_year, last_year + 1):
            year_end = pd.Timestamp(f"{year}-12-31")
            alive = (
                successful["first_trade_date"].le(year_end)
                & successful["last_trade_date"].ge(pd.Timestamp(f"{year}-01-01"))
            )
            yearly.append({"year": year, "etf_count": int(alive.sum())})
    coverage["yearly_etf_count"] = yearly
    coverage["survivorship_bias"] = {
        "historical_success_not_current": int(
            (
                ~master["expected_active"]
                & master["bar_status"].eq("success")
            ).sum()
        ),
        "warning": (
            "仅使用当前 expected_active 池回测历史会遗漏已终止产品，"
            "必须按 listing_date/delisting_date 构造观察日股票池。"
        ),
    }
    report_path = store.write_json_report("etf_coverage", coverage)
    candidate_payload = (
        candidate_manifest.to_dict()
        if isinstance(candidate_manifest, DatasetManifest)
        else candidate_manifest
    )
    candidate_path = store.manifest_path("etf_candidates")
    daily_path = store.manifest_path("etf_daily")
    profile_path = store.manifest_path("etf_profiles")
    manifest = DatasetManifest(
        schema_version=1,
        dataset="etf_master",
        provider="SSE + SZSE + CNINFO + Sina + THS + Eastmoney",
        quality_grade=QualityGrade.worst(master["quality_grade"]),
        row_count=len(master),
        columns=list(master.columns),
        data_files=[data_file],
        date_range={
            "start": pd.to_datetime(master["first_trade_date"], errors="coerce")
            .min()
            .strftime("%Y-%m-%d"),
            "end": source_end.strftime("%Y-%m-%d"),
        },
        source_files=[
            {
                "path": str(candidate_path),
                "bytes": candidate_path.stat().st_size,
                "sha256": sha256_file(candidate_path),
            },
            {
                "path": str(daily_path),
                "bytes": daily_path.stat().st_size,
                "sha256": sha256_file(daily_path),
            },
            {
                "path": str(profile_path),
                "bytes": profile_path.stat().st_size,
                "sha256": sha256_file(profile_path),
            },
        ],
        primary_key=["symbol"],
        date_fields={
            "listing_date": "首个可验证交易日",
            "delisting_date": "最后可验证交易日；当前活跃为空",
        },
        coverage=coverage,
        failures=[
            {
                "symbol": row.symbol,
                "status": row.bar_status,
                "error": row.bar_error,
            }
            for row in master.itertuples(index=False)
            if row.bar_status != "success"
        ],
        limitations=list(candidate_payload.get("limitations", [])),
        checks={
            "allows_unverified_candidates": True,
            "current_coverage_target": 0.95,
            "current_coverage_passed": coverage["current_coverage_ratio"] >= 0.95,
            "duplicate_symbols": int(master["symbol"].duplicated().sum()),
            "future_listing_dates": int(
                (
                    pd.to_datetime(master["listing_date"], errors="coerce")
                    > source_end
                ).sum()
            ),
        },
    )
    store.write_manifest(manifest)
    return master, manifest, report_path


def print_sync_summary(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
