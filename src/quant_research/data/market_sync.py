"""全市场真实涨跌停与日频交易状态的可恢复构建。"""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .market_reference import (
    DELISTING_EVENT_COLUMNS,
    OFFICIAL_STATUS_COLUMNS,
    PRICE_LIMIT_COLUMNS,
    RISK_WARNING_EVENT_COLUMNS,
    ST_NAME_EVENT_COLUMNS,
    apply_st_name_events,
    derive_delisting_events_from_market_history,
    normalize_delisting_events,
    normalize_risk_warning_events,
    normalize_dolthub_baostock_status,
    normalize_dolthub_price_limits,
    normalize_eastmoney_title_name_events,
    normalize_szse_st_name_events,
)
from .market_state import MARKET_STATE_COLUMNS, apply_market_reference, build_market_state
from .security_lifecycle import clip_to_security_lifecycle
from .store import ResearchDataStore, sha256_file


QLIB_MARKET_FIELDS = ("open", "high", "low", "close", "volume", "factor")
EASTMONEY_RISK_NOTICE_ENDPOINT = (
    "https://np-anotice-stock.eastmoney.com/api/security/ann"
)


def dolt_snapshot_commit(dolt_exe: Path, repository: Path) -> str:
    result = subprocess.run(
        [str(dolt_exe), "log", "-n", "1", "--oneline"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    plain_output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    first_line = next(
        (line.strip() for line in plain_output.splitlines() if line.strip()),
        "",
    )
    if not first_line:
        raise RuntimeError("Dolt repository did not return a commit")
    return first_line.split()[0]


def export_dolt_price_limits(
    store: ResearchDataStore,
    *,
    dolt_exe: Path,
    repository: Path,
    refresh: bool = False,
) -> tuple[Path, str]:
    """从固定 Dolt 快照导出按证券排序的原始 CSV。"""

    commit = dolt_snapshot_commit(dolt_exe, repository)
    target = (
        store.raw_dir
        / "dolthub"
        / "investment_data"
        / commit
        / "final_a_stock_limit.csv"
    )
    if target.is_file() and not refresh:
        return target, commit
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".final_a_stock_limit.",
        suffix=".csv.tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    query = (
        "SELECT tradedate,symbol,pre_close,up_limit,down_limit "
        "FROM final_a_stock_limit ORDER BY symbol,tradedate"
    )
    try:
        with temporary.open("wb") as output:
            subprocess.run(
                [str(dolt_exe), "sql", "-r", "csv", "-q", query],
                cwd=repository,
                check=True,
                stdout=output,
            )
        with temporary.open("rb") as handle:
            header = handle.readline().decode("utf-8-sig").strip()
        if header != "tradedate,symbol,pre_close,up_limit,down_limit":
            raise RuntimeError(f"unexpected Dolt CSV header: {header!r}")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target, commit


def export_dolt_baostock_status(
    store: ResearchDataStore,
    *,
    dolt_exe: Path,
    repository: Path,
    refresh: bool = False,
) -> tuple[Path, str]:
    """导出带显式 ``tradestatus``/``is_st`` 的 Baostock 历史快照。"""

    commit = dolt_snapshot_commit(dolt_exe, repository)
    target = (
        store.raw_dir
        / "dolthub"
        / "investment_data"
        / commit
        / "bao_a_stock_eod_info_status.csv"
    )
    if target.is_file() and not refresh:
        return target, commit
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".bao_a_stock_eod_info_status.",
        suffix=".csv.tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    query = (
        "SELECT tradedate,symbol,tradestatus,is_st "
        "FROM bao_a_stock_eod_info ORDER BY symbol,tradedate"
    )
    try:
        with temporary.open("wb") as output:
            subprocess.run(
                [str(dolt_exe), "sql", "-r", "csv", "-q", query],
                cwd=repository,
                check=True,
                stdout=output,
            )
        with temporary.open("rb") as handle:
            header = handle.readline().decode("utf-8-sig").strip()
        if header != "tradedate,symbol,tradestatus,is_st":
            raise RuntimeError(f"unexpected Dolt status CSV header: {header!r}")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target, commit


def build_price_limit_partitions(
    store: ResearchDataStore,
    raw_csv: Path,
    *,
    commit: str,
    chunk_rows: int = 250_000,
) -> DatasetManifest:
    """把按证券排序的原始 CSV 流式转换成逐证券 Parquet。"""

    artifacts = []
    pending = pd.DataFrame()
    total_rows = 0
    symbols = 0
    known_st_rows = 0
    st_rows = 0
    first_date = pd.NaT
    last_date = pd.NaT
    master = store.read_parquet("security_master")
    known_symbols = set(
        master.loc[master["asset_type"] == "stock", "symbol"].astype(str)
    )
    unknown_symbols = set()

    def write_groups(frame: pd.DataFrame) -> None:
        nonlocal total_rows, symbols, known_st_rows, st_rows, first_date, last_date
        if frame.empty:
            return
        for symbol, group in frame.groupby("symbol", sort=False):
            if symbol.upper() not in known_symbols:
                unknown_symbols.add(symbol.upper())
                continue
            normalized = normalize_dolthub_price_limits(group)
            if normalized.empty:
                continue
            artifact = store.write_parquet(
                "daily_price_limit",
                normalized,
                filename=f"symbol={symbol.upper()}/data.parquet",
            )
            artifact["partition_values"] = {"symbol": symbol.upper()}
            artifacts.append(artifact)
            total_rows += len(normalized)
            symbols += 1
            known_st_rows += int(normalized["is_st"].notna().sum())
            st_rows += int(normalized["is_st"].fillna(False).sum())
            group_start = normalized["trade_date"].min()
            group_end = normalized["trade_date"].max()
            first_date = (
                group_start if pd.isna(first_date) else min(first_date, group_start)
            )
            last_date = group_end if pd.isna(last_date) else max(last_date, group_end)

    for chunk in pd.read_csv(raw_csv, chunksize=chunk_rows):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper()
        combined = pd.concat([pending, chunk], ignore_index=True)
        last_symbol = combined["symbol"].iloc[-1]
        complete = combined[combined["symbol"] != last_symbol]
        pending = combined[combined["symbol"] == last_symbol].copy()
        write_groups(complete)
    write_groups(pending)
    if not artifacts:
        raise RuntimeError("Dolt price-limit export produced no valid partitions")
    source = {
        "path": str(raw_csv),
        "bytes": raw_csv.stat().st_size,
        "sha256": sha256_file(raw_csv),
        "dolt_commit": commit,
    }
    manifest = DatasetManifest(
        schema_version=1,
        dataset="daily_price_limit",
        provider="dolthub/chenditc-investment-data",
        quality_grade=QualityGrade.B,
        row_count=total_rows,
        columns=PRICE_LIMIT_COLUMNS,
        data_files=artifacts,
        date_range={
            "start": first_date.strftime("%Y-%m-%d"),
            "end": last_date.strftime("%Y-%m-%d"),
        },
        source_files=[source],
        primary_key=["symbol", "trade_date"],
        date_fields={"trade_date": "交易日"},
        partitioning={"style": "hive", "columns": ["symbol"]},
        coverage={
            "symbols": symbols,
            "known_st_rows": known_st_rows,
            "st_rows": st_rows,
            "known_st_ratio": known_st_rows / total_rows,
            "target_symbols": len(known_symbols),
            "unknown_source_symbols": sorted(unknown_symbols),
        },
        limitations=[
            "涨跌停价来自公开众包库的 Tushare、Baostock 与高质量静态源合并结果，质量为 B。",
            "is_st 由真实 5% 上下限反推；重新上市等特殊限价无法识别时保持未知。",
        ],
        checks={
            "partition_files": len(artifacts),
            "source_commit": commit,
        },
    )
    store.write_manifest(manifest)
    return manifest


def build_official_status_partitions(
    store: ResearchDataStore,
    raw_csv: Path,
    *,
    commit: str,
    chunk_rows: int = 250_000,
) -> DatasetManifest:
    """把显式 ST/交易状态流式转换为逐证券 Parquet。"""

    master = store.read_parquet("security_master")
    lifecycle = master.set_index("symbol")
    known_symbols = set(
        master.loc[master["asset_type"] == "stock", "symbol"].astype(str)
    )
    artifacts = []
    pending = pd.DataFrame()
    total_rows = 0
    symbols = 0
    st_rows = 0
    paused_rows = 0
    first_date = pd.NaT
    last_date = pd.NaT
    unknown_symbols = set()

    def write_groups(frame: pd.DataFrame) -> None:
        nonlocal total_rows, symbols, st_rows, paused_rows, first_date, last_date
        if frame.empty:
            return
        for symbol, group in frame.groupby("symbol", sort=False):
            symbol = symbol.upper()
            if symbol not in known_symbols:
                unknown_symbols.add(symbol)
                continue
            normalized = normalize_dolthub_baostock_status(group)
            normalized = clip_to_security_lifecycle(
                normalized,
                lifecycle.loc[symbol],
                date_column="trade_date",
            )
            if normalized.empty:
                continue
            artifact = store.write_parquet(
                "daily_official_status",
                normalized,
                filename=f"symbol={symbol}/data.parquet",
            )
            artifact["partition_values"] = {"symbol": symbol}
            artifacts.append(artifact)
            total_rows += len(normalized)
            symbols += 1
            st_rows += int(normalized["is_st"].fillna(False).sum())
            paused_rows += int(normalized["paused"].fillna(False).sum())
            group_start = normalized["trade_date"].min()
            group_end = normalized["trade_date"].max()
            first_date = (
                group_start if pd.isna(first_date) else min(first_date, group_start)
            )
            last_date = group_end if pd.isna(last_date) else max(last_date, group_end)

    for chunk in pd.read_csv(raw_csv, chunksize=chunk_rows):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper()
        combined = pd.concat([pending, chunk], ignore_index=True)
        last_symbol = combined["symbol"].iloc[-1]
        complete = combined[combined["symbol"] != last_symbol]
        pending = combined[combined["symbol"] == last_symbol].copy()
        write_groups(complete)
    write_groups(pending)
    if not artifacts:
        raise RuntimeError("Dolt Baostock export produced no valid partitions")
    manifest = DatasetManifest(
        schema_version=1,
        dataset="daily_official_status",
        provider="dolthub/chenditc-investment-data/baostock",
        quality_grade=QualityGrade.B,
        row_count=total_rows,
        columns=OFFICIAL_STATUS_COLUMNS,
        data_files=artifacts,
        date_range={
            "start": first_date.strftime("%Y-%m-%d"),
            "end": last_date.strftime("%Y-%m-%d"),
        },
        source_files=[
            {
                "path": str(raw_csv),
                "bytes": raw_csv.stat().st_size,
                "sha256": sha256_file(raw_csv),
                "dolt_commit": commit,
            }
        ],
        primary_key=["symbol", "trade_date"],
        date_fields={"trade_date": "交易日"},
        partitioning={"style": "hive", "columns": ["symbol"]},
        coverage={
            "symbols": symbols,
            "target_symbols": len(known_symbols),
            "st_rows": st_rows,
            "paused_rows": paused_rows,
            "unknown_source_symbols": sorted(unknown_symbols),
        },
        limitations=[
            "Baostock 显式状态在当前 Dolt 快照中截止 2023-06-09；其后由其他来源或未知值承接。",
            "公开源经固定 Dolt commit 冻结，质量为 B。",
        ],
        checks={"partition_files": len(artifacts), "source_commit": commit},
    )
    store.write_manifest(manifest)
    return manifest


def collect_szse_st_name_events(
    store: ResearchDataStore,
) -> tuple[pd.DataFrame, DatasetManifest]:
    """下载深交所官方简称变更并固化完整观察日事件。"""

    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("akshare is required for SZSE name changes") from exc
    raw = ak.stock_info_sz_change_name(symbol="简称变更")
    source_end = pd.to_datetime(raw["变更日期"], errors="coerce").max()
    source = store.write_raw_csv(
        "szse",
        "stock_name_changes",
        f"short-name-changes__{source_end:%Y-%m-%d}.csv",
        raw,
    )
    master = store.read_parquet("security_master")
    events = normalize_szse_st_name_events(raw, master)
    data_file = store.write_parquet("st_name_events", events)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="st_name_events",
        provider="SZSE official name changes",
        quality_grade=QualityGrade.A,
        row_count=len(events),
        columns=ST_NAME_EVENT_COLUMNS,
        data_files=[data_file],
        date_range={
            "start": events["effective_from"].min().strftime("%Y-%m-%d"),
            "end": source_end.strftime("%Y-%m-%d"),
        },
        source_files=[source],
        primary_key=["symbol", "effective_from"],
        date_fields={"effective_from": "证券简称生效日"},
        coverage={
            "symbols": int(events["symbol"].nunique()),
            "st_events": int(events["is_st"].sum()),
        },
        limitations=[
            "本表覆盖深交所股票；上交所与北交所仍由 Baostock、真实限价或未知值处理。"
        ],
        checks={
            "duplicate_events": int(
                events.duplicated(["symbol", "effective_from"]).sum()
            )
        },
    )
    store.write_manifest(manifest)
    return events, manifest


@dataclass
class EastmoneyRiskNoticeProvider:
    """东方财富风险提示公告分页下载器。"""

    endpoint: str = EASTMONEY_RISK_NOTICE_ENDPOINT
    timeout: float = 30.0
    retries: int = 3

    def fetch_page(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        page_index: int,
        page_size: int = 100,
    ) -> dict:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required for risk notices") from exc
        params = {
            "sr": "-1",
            "page_size": str(page_size),
            "page_index": str(page_index),
            "ann_type": "A",
            "client_source": "web",
            "f_node": "3",
            "s_node": "0",
            "begin_time": pd.Timestamp(start).strftime("%Y-%m-%d"),
            "end_time": pd.Timestamp(end).strftime("%Y-%m-%d"),
        }
        last_error = None
        for attempt in range(self.retries):
            try:
                response = requests.get(
                    self.endpoint,
                    params=params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("success") != 1 or not isinstance(
                    payload.get("data"), dict
                ):
                    raise ValueError(
                        f"Eastmoney risk notice API error: {payload.get('error')}"
                    )
                return payload["data"]
            except Exception as exc:  # noqa: BLE001 - bounded provider retry
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(
            f"risk notice page failed: {start:%Y-%m-%d}..{end:%Y-%m-%d} "
            f"page={page_index}: {last_error}"
        )


def _expand_risk_notice_page(payload: dict) -> list[dict]:
    rows = []
    for notice in payload.get("list") or []:
        for code in notice.get("codes") or []:
            rows.append(
                {
                    "art_code": notice.get("art_code"),
                    "stock_code": str(code.get("stock_code", "")).zfill(6),
                    "short_name": code.get("short_name"),
                    "notice_date": notice.get("notice_date"),
                    "title": notice.get("title_ch") or notice.get("title"),
                    "display_time": notice.get("display_time"),
                    "market_code": code.get("market_code"),
                }
            )
    return rows


def download_eastmoney_risk_notices(
    start,
    end,
    *,
    provider: EastmoneyRiskNoticeProvider | None = None,
    workers: int = 12,
) -> tuple[pd.DataFrame, dict]:
    """按自然季度拆分下载，避免东财大区间限流和 50,000 条总量上限。"""

    provider = provider or EastmoneyRiskNoticeProvider()
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    if start > end:
        raise ValueError("risk notice start must not be after end")
    periods = []
    period_start = start
    while period_start <= end:
        quarter_end = period_start.to_period("Q").end_time.normalize()
        period_end = min(end, quarter_end)
        periods.append((period_start, period_end))
        period_start = period_end + pd.Timedelta(days=1)

    rows = []
    expected_hits = 0
    page_jobs = []
    period_checks = []
    for period_start, period_end in periods:
        first = provider.fetch_page(period_start, period_end, 1)
        hits = int(first.get("total_hits") or 0)
        expected_hits += hits
        rows.extend(_expand_risk_notice_page(first))
        pages = (hits + 99) // 100
        period_checks.append(
            {
                "start": period_start.strftime("%Y-%m-%d"),
                "end": period_end.strftime("%Y-%m-%d"),
                "total_hits": hits,
                "pages": pages,
            }
        )
        page_jobs.extend(
            (period_start, period_end, page_index)
            for page_index in range(2, pages + 1)
        )
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(provider.fetch_page, period_start, period_end, page): (
                period_start,
                page,
            )
            for period_start, period_end, page in page_jobs
        }
        for future in as_completed(futures):
            rows.extend(_expand_risk_notice_page(future.result()))
    frame = pd.DataFrame(rows)
    if frame.empty and expected_hits:
        raise RuntimeError("Eastmoney returned hits but no risk-notice rows")
    if not frame.empty:
        frame["notice_date"] = pd.to_datetime(
            frame["notice_date"], errors="coerce"
        ).dt.normalize()
        frame = (
            frame.dropna(subset=["art_code", "stock_code", "notice_date", "title"])
            .sort_values(["notice_date", "art_code", "stock_code"])
            .drop_duplicates(["art_code", "stock_code"], keep="last")
            .reset_index(drop=True)
        )
    received_announcements = int(frame["art_code"].nunique()) if not frame.empty else 0
    if received_announcements != expected_hits:
        raise RuntimeError(
            "Eastmoney risk-notice pagination is incomplete: "
            f"expected={expected_hits}, received={received_announcements}"
        )
    return frame, {
        "expected_announcements": expected_hits,
        "received_announcements": received_announcements,
        "expanded_security_rows": len(frame),
        "periods": period_checks,
    }


def build_risk_warning_baselines(
    store: ResearchDataStore,
    security_master: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    official_symbols: set[str],
) -> pd.DataFrame:
    """承接 Baostock 截止状态；无显式历史的新上市证券从上市日初始化。"""

    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    stocks = security_master[security_master["asset_type"] == "stock"]
    records = []
    for row in stocks.itertuples(index=False):
        symbol = str(row.symbol)
        if symbol in official_symbols:
            official = store.read_symbol_partitions(
                "daily_official_status", [symbol]
            ).sort_values("trade_date")
            known = official[official["is_st"].notna()]
            if known.empty:
                continue
            latest = known.iloc[-1]
            position = calendar.searchsorted(
                pd.Timestamp(latest["trade_date"]).normalize(),
                side="right",
            )
            if position >= len(calendar):
                continue
            records.append(
                {
                    "symbol": symbol,
                    "effective_from": calendar[position],
                    "is_st": bool(latest["is_st"]),
                    "st_quality": QualityGrade.B.value,
                    "st_source": (
                        "dolthub/baostock-carry-forward-with-announcements"
                    ),
                }
            )
            continue
        listing_date = pd.Timestamp(row.listing_date).normalize()
        position = calendar.searchsorted(listing_date, side="left")
        if position >= len(calendar):
            continue
        records.append(
            {
                "symbol": symbol,
                "effective_from": calendar[position],
                "is_st": False,
                "st_quality": QualityGrade.B.value,
                "st_source": "exchange-listing-initial-state",
            }
        )
    return pd.DataFrame(records)


def collect_risk_warning_events(
    store: ResearchDataStore,
    calendar: pd.DatetimeIndex,
    *,
    start="2021-11-15",
    end=None,
    workers: int = 12,
    refresh: bool = False,
    provider: EastmoneyRiskNoticeProvider | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    """固化发行人风险警示公告，并生成可逐日回放的 B 级事件。"""

    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    end = pd.Timestamp(end or calendar[-1]).normalize()
    start = pd.Timestamp(start).normalize()
    raw_pattern = (
        f"risk-notices__{start:%Y-%m-%d}__{end:%Y-%m-%d}__*.csv"
    )
    candidates = sorted(
        (store.raw_dir / "eastmoney" / "risk_warning_announcements").glob(
            raw_pattern
        )
    )
    if candidates and not refresh:
        raw_path = candidates[-1]
        notices = pd.read_csv(raw_path)
        notices["notice_date"] = pd.to_datetime(notices["notice_date"])
        download_checks = {
            "cache_reused": True,
            "received_announcements": int(notices["art_code"].nunique()),
            "expanded_security_rows": len(notices),
        }
        raw_artifact = {
            "path": raw_path.relative_to(store.root).as_posix(),
            "bytes": raw_path.stat().st_size,
            "sha256": sha256_file(raw_path),
        }
    else:
        notices, download_checks = download_eastmoney_risk_notices(
            start,
            end,
            provider=provider,
            workers=workers,
        )
        payload_hash = hashlib.sha256(
            notices.to_csv(index=False).encode("utf-8-sig")
        ).hexdigest()[:12]
        raw_artifact = store.write_raw_csv(
            "eastmoney",
            "risk_warning_announcements",
            (
                f"risk-notices__{start:%Y-%m-%d}__{end:%Y-%m-%d}"
                f"__{payload_hash}.csv"
            ),
            notices,
        )

    master = store.read_parquet("security_master")
    official_manifest = store.read_manifest("daily_official_status")
    official_symbols = {
        item["partition_values"]["symbol"]
        for item in official_manifest["data_files"]
        if "partition_values" in item
    }
    baselines = build_risk_warning_baselines(
        store,
        master,
        calendar,
        official_symbols=official_symbols,
    )
    events = normalize_risk_warning_events(
        notices,
        master,
        calendar,
        baselines=baselines,
    )
    issuer_name_events = normalize_eastmoney_title_name_events(
        notices,
        master,
        calendar,
    )
    official_name_events = store.read_parquet("st_name_events")
    official_name_events = official_name_events[
        official_name_events["st_source"].eq("szse/official-name-change")
    ].copy()
    official_name_manifest = store.read_manifest("st_name_events")
    official_name_sources = [
        source
        for source in official_name_manifest.get("source_files", [])
        if "szse" in str(source.get("path", "")).lower()
    ]
    combined_name_events = pd.concat(
        [official_name_events, issuer_name_events], ignore_index=True
    )
    combined_name_events["_quality_priority"] = combined_name_events[
        "st_quality"
    ].map({QualityGrade.B.value: 1, QualityGrade.A.value: 2}).fillna(0)
    combined_name_events = (
        combined_name_events.sort_values(
            ["symbol", "effective_from", "_quality_priority"], kind="stable"
        )
        .drop_duplicates(["symbol", "effective_from"], keep="last")
        .drop(columns="_quality_priority")
        .reset_index(drop=True)
    )
    name_data_file = store.write_parquet("st_name_events", combined_name_events)
    combined_name_manifest = DatasetManifest(
        schema_version=2,
        dataset="st_name_events",
        provider="SZSE official name changes + Eastmoney issuer title prefixes",
        quality_grade=QualityGrade.B,
        row_count=len(combined_name_events),
        columns=ST_NAME_EVENT_COLUMNS,
        data_files=[name_data_file],
        date_range={
            "start": combined_name_events["effective_from"].min().strftime(
                "%Y-%m-%d"
            ),
            "end": combined_name_events["effective_from"].max().strftime(
                "%Y-%m-%d"
            ),
        },
        source_files=[*official_name_sources, raw_artifact],
        primary_key=["symbol", "effective_from"],
        date_fields={"effective_from": "证券简称证据的下一交易日生效"},
        coverage={
            "symbols": int(combined_name_events["symbol"].nunique()),
            "official_rows": int(len(official_name_events)),
            "issuer_title_rows": int(len(issuer_name_events)),
            "st_events": int(combined_name_events["is_st"].fillna(False).sum()),
        },
        limitations=[
            "深交所简称变更为 A 级；上交所与北交所公告标题前缀为 B 级。",
            "公告标题只恢复明确以 ST、*ST、退市或退结尾的风险简称，不用下载时返回的当前简称回填历史。",
        ],
        checks={
            "duplicate_events": int(
                combined_name_events.duplicated(
                    ["symbol", "effective_from"]
                ).sum()
            ),
            "official_rows_preserved": int(
                combined_name_events["st_source"].eq(
                    "szse/official-name-change"
                ).sum()
            )
            == len(official_name_events),
        },
    )
    store.write_manifest(combined_name_manifest)
    data_file = store.write_parquet("risk_warning_events", events)
    evidence_rows = int(events["evidence_art_code"].notna().sum())
    manifest = DatasetManifest(
        schema_version=1,
        dataset="risk_warning_events",
        provider="Eastmoney issuer announcements + Baostock carry-forward",
        quality_grade=QualityGrade.B,
        row_count=len(events),
        columns=RISK_WARNING_EVENT_COLUMNS,
        data_files=[data_file],
        date_range={
            "start": events["effective_from"].min().strftime("%Y-%m-%d"),
            "end": events["effective_from"].max().strftime("%Y-%m-%d"),
        },
        source_files=[
            raw_artifact,
            {
                "path": str(store.manifest_path("daily_official_status")),
                "bytes": store.manifest_path("daily_official_status").stat().st_size,
                "sha256": sha256_file(
                    store.manifest_path("daily_official_status")
                ),
            },
        ],
        primary_key=["symbol", "effective_from"],
        date_fields={"effective_from": "下一交易日生效"},
        coverage={
            "symbols": int(events["symbol"].nunique()),
            "baseline_events": int(len(events) - evidence_rows),
            "announcement_events": evidence_rows,
            "st_on_events": int(events["is_st"].fillna(False).sum()),
        },
        limitations=[
            "公告标题按明确实施、延续和撤销措辞分类，未解析 PDF 正文，质量为 B。",
            "Baostock 截止状态只在后续公告流内延续；缺少显式历史的新上市证券按上市初始非 ST 处理。",
            "含“可能”或“申请撤销”的预告和申请不会改变状态。",
        ],
        checks={
            **download_checks,
            "duplicate_events": int(
                events.duplicated(["symbol", "effective_from"]).sum()
            ),
            "notice_start": start.strftime("%Y-%m-%d"),
            "notice_end": end.strftime("%Y-%m-%d"),
        },
    )
    store.write_manifest(manifest)
    return events, manifest


def collect_delisting_events(
    store: ResearchDataStore,
    calendar: pd.DatetimeIndex,
    *,
    start="2018-01-01",
    end=None,
    workers: int = 12,
    refresh: bool = False,
    provider: EastmoneyRiskNoticeProvider | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    """固化退市整理期公告，并生成不可向过去回填的 B 级事件。"""

    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    end = pd.Timestamp(end or calendar[-1]).normalize()
    start = pd.Timestamp(start).normalize()
    raw_pattern = f"risk-notices__{start:%Y-%m-%d}__{end:%Y-%m-%d}__*.csv"
    candidates = sorted(
        (store.raw_dir / "eastmoney" / "risk_warning_announcements").glob(
            raw_pattern
        )
    )
    if candidates and not refresh:
        raw_path = candidates[-1]
        notices = pd.read_csv(raw_path)
        notices["notice_date"] = pd.to_datetime(notices["notice_date"])
        raw_artifact = {
            "path": raw_path.relative_to(store.root).as_posix(),
            "bytes": raw_path.stat().st_size,
            "sha256": sha256_file(raw_path),
        }
        download_checks = {
            "cache_reused": True,
            "received_announcements": int(notices["art_code"].nunique()),
            "expanded_security_rows": len(notices),
        }
    else:
        notices, download_checks = download_eastmoney_risk_notices(
            start,
            end,
            provider=provider,
            workers=workers,
        )
        payload_hash = hashlib.sha256(
            notices.to_csv(index=False).encode("utf-8-sig")
        ).hexdigest()[:12]
        raw_artifact = store.write_raw_csv(
            "eastmoney",
            "risk_warning_announcements",
            (
                f"risk-notices__{start:%Y-%m-%d}__{end:%Y-%m-%d}"
                f"__{payload_hash}.csv"
            ),
            notices,
        )
    master = store.read_parquet("security_master")
    events = normalize_delisting_events(notices, master, calendar)
    if events.empty:
        raise ValueError("risk notices produced no delisting events")
    data_file = store.write_parquet("delisting_events", events)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="delisting_events",
        provider="Eastmoney issuer announcements",
        quality_grade=QualityGrade.B,
        row_count=len(events),
        columns=DELISTING_EVENT_COLUMNS,
        data_files=[data_file],
        date_range={
            "start": events["effective_from"].min().strftime("%Y-%m-%d"),
            "end": events["effective_from"].max().strftime("%Y-%m-%d"),
        },
        source_files=[raw_artifact],
        primary_key=["symbol", "effective_from"],
        date_fields={"effective_from": "公告后下一交易日生效"},
        coverage={
            "symbols": int(events["symbol"].nunique()),
            "events": len(events),
        },
        limitations=[
            "只识别公告元数据中已带退字的简称或明确进入退市整理期的标题。",
            "不使用事后退市日期回填历史；未出现公告的证券保持未知而不是假定退市。",
        ],
        checks={
            **download_checks,
            "duplicate_events": int(events.duplicated("symbol").sum()),
            "notice_start": start.strftime("%Y-%m-%d"),
            "notice_end": end.strftime("%Y-%m-%d"),
        },
    )
    store.write_manifest(manifest)
    return events, manifest


def build_delisting_events_from_local_history(
    store: ResearchDataStore,
) -> tuple[pd.DataFrame, DatasetManifest]:
    """以证券生命周期和实际交易日恢复退市整理期事件。"""

    master = store.read_parquet("security_master")
    symbols = master.loc[
        master["asset_type"].eq("stock")
        & master["display_name"].fillna("").str.contains("退"),
        "symbol",
    ].astype(str).tolist()
    history = store.read_symbol_partitions(
        "daily_market_state",
        symbols,
        columns=["symbol", "trade_date", "paused", "raw_close"],
        strict=False,
    )
    events = derive_delisting_events_from_market_history(master, history)
    if events.empty:
        raise ValueError("local market history produced no delisting events")
    data_file = store.write_parquet("delisting_events", events)
    source_files = []
    for dataset in ("security_master", "daily_market_state"):
        path = store.manifest_path(dataset)
        source_files.append(
            {
                "path": path.relative_to(store.root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    event_lifecycle = events.merge(
        master[["symbol", "end_date"]], on="symbol", how="left"
    )
    manifest = DatasetManifest(
        schema_version=1,
        dataset="delisting_events",
        provider="exchange delisting-period rules + local historical trading sessions",
        quality_grade=QualityGrade.B,
        row_count=len(events),
        columns=DELISTING_EVENT_COLUMNS,
        data_files=[data_file],
        date_range={
            "start": events["effective_from"].min().strftime("%Y-%m-%d"),
            "end": events["effective_from"].max().strftime("%Y-%m-%d"),
        },
        source_files=source_files,
        primary_key=["symbol", "effective_from"],
        date_fields={
            "effective_from": "按实际退市整理期首个交易日恢复的状态生效日"
        },
        coverage={
            "candidate_symbols": len(symbols),
            "symbols": int(events["symbol"].nunique()),
        },
        limitations=[
            "2020 年末及以前按 30 个退市整理期交易日，之后按 15 个交易日恢复。",
            "只处理证券主表终态简称含退的证券；不使用终止日提前过滤更早历史。",
        ],
        checks={
            "duplicate_events": int(events.duplicated("symbol").sum()),
            "event_after_last_trade": int(
                event_lifecycle["effective_from"].gt(
                    pd.to_datetime(event_lifecycle["end_date"])
                ).sum()
            ),
        },
    )
    store.write_manifest(manifest)
    return events, manifest


def _read_qlib_feature(path: Path) -> tuple[int, np.ndarray]:
    payload = np.fromfile(path, dtype="<f4")
    if payload.size < 1 or not np.isfinite(payload[0]):
        raise ValueError(f"invalid Qlib feature: {path}")
    start = int(payload[0])
    if not np.isclose(payload[0], start):
        raise ValueError(f"non-integral Qlib feature start index: {path}")
    return start, payload[1:]


def read_qlib_symbol_features(
    qlib_root: Path,
    symbol: str,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    directory = qlib_root / "features" / symbol.lower()
    arrays = {}
    starts = {}
    for field in QLIB_MARKET_FIELDS:
        starts[field], arrays[field] = _read_qlib_feature(
            directory / f"{field}.day.bin"
        )
    if len(set(starts.values())) != 1 or len({len(value) for value in arrays.values()}) != 1:
        raise ValueError(f"misaligned Qlib features: {symbol}")
    start = next(iter(starts.values()))
    length = len(next(iter(arrays.values())))
    if start < 0 or start + length > len(calendar):
        raise ValueError(f"Qlib feature exceeds calendar: {symbol}")
    frame = pd.DataFrame(arrays)
    frame.insert(0, "trade_date", calendar[start : start + length])
    frame.insert(0, "symbol", symbol)
    return frame


def _market_status_path(store: ResearchDataStore) -> Path:
    return store.normalized_path("market_state_sync_status")


def _checkpoint_market_status(
    store: ResearchDataStore,
    records: list[dict],
) -> pd.DataFrame:
    frame = (
        pd.DataFrame(records)
        .drop_duplicates("symbol", keep="last")
        .sort_values("symbol")
        .reset_index(drop=True)
    )
    store.write_parquet("market_state_sync_status", frame)
    return frame


def build_market_state_partitions(
    store: ResearchDataStore,
    *,
    qlib_root: Path,
    resume: bool = True,
    reuse_existing_base: bool = False,
    checkpoint_every: int = 50,
    limit: int | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    """逐证券构建完整上市区间状态，内存峰值与单只历史长度相关。"""

    master = store.read_parquet("security_master")
    stocks = master[master["asset_type"] == "stock"].sort_values("symbol")
    if limit:
        stocks = stocks.head(limit)
    calendar = pd.DatetimeIndex(
        pd.to_datetime(
            (qlib_root / "calendars" / "day.txt").read_text(
                encoding="utf-8"
            ).splitlines(),
            errors="raise",
        )
    ).normalize()
    existing = (
        pd.read_parquet(_market_status_path(store))
        if resume and _market_status_path(store).is_file()
        else pd.DataFrame()
    )
    completed = (
        set(existing.loc[existing["status"] == "success", "symbol"])
        if not existing.empty
        else set()
    )
    records = existing.to_dict("records") if not existing.empty else []
    price_manifest = store.read_manifest("daily_price_limit")
    price_limit_symbols = {
        item["partition_values"]["symbol"]
        for item in price_manifest["data_files"]
        if "partition_values" in item
    }
    try:
        official_manifest = store.read_manifest("daily_official_status")
    except FileNotFoundError:
        official_manifest = None
    official_symbols = (
        {
            item["partition_values"]["symbol"]
            for item in official_manifest["data_files"]
            if "partition_values" in item
        }
        if official_manifest
        else set()
    )
    try:
        st_name_events = store.read_parquet("st_name_events")
    except FileNotFoundError:
        st_name_events = pd.DataFrame()
    try:
        risk_warning_events = store.read_parquet("risk_warning_events")
    except FileNotFoundError:
        risk_warning_events = pd.DataFrame()

    for number, row in enumerate(stocks.itertuples(index=False), start=1):
        symbol = str(row.symbol)
        if symbol in completed:
            continue
        try:
            if reuse_existing_base:
                state = store.read_symbol_partitions(
                    "daily_market_state", [symbol]
                )
            else:
                features = read_qlib_symbol_features(qlib_root, symbol, calendar)
                base = build_market_state(
                    features,
                    calendar,
                    master[master["symbol"] == symbol],
                    [symbol],
                )
                if symbol in price_limit_symbols:
                    reference = store.read_symbol_partitions(
                        "daily_price_limit", [symbol]
                    )
                    state = apply_market_reference(base, reference)
                else:
                    state = base
                if symbol in official_symbols:
                    official = store.read_symbol_partitions(
                        "daily_official_status", [symbol]
                    )
                    state = apply_market_reference(state, official)
            if not risk_warning_events.empty:
                state = apply_st_name_events(state, risk_warning_events)
            if not st_name_events.empty and symbol.startswith("SZ"):
                state = apply_st_name_events(state, st_name_events)
            artifact = store.write_parquet(
                "daily_market_state",
                state,
                filename=f"symbol={symbol}/data.parquet",
            )
            records.append(
                {
                    "symbol": symbol,
                    "status": "success",
                    "row_count": len(state),
                    "start": state["trade_date"].min(),
                    "end": state["trade_date"].max(),
                    "paused_rows": int(state["paused"].sum()),
                    "known_st_rows": int(
                        state["st_quality"].isin(
                            [QualityGrade.A.value, QualityGrade.B.value]
                        ).sum()
                    ),
                    "st_rows": int(state["is_st"].fillna(False).sum()),
                    "exact_limit_rows": int(state["limit_quality"].eq("B").sum()),
                    "artifact_path": artifact["path"],
                    "artifact_bytes": artifact["bytes"],
                    "artifact_sha256": artifact["sha256"],
                    "error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001 - failure ledger is part of the contract
            records.append(
                {
                    "symbol": symbol,
                    "status": "failed",
                    "row_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if number % checkpoint_every == 0:
            _checkpoint_market_status(store, records)
    statuses = _checkpoint_market_status(store, records)
    successful = statuses[statuses["status"] == "success"].copy()
    artifacts = [
        {
            "path": row.artifact_path,
            "bytes": int(row.artifact_bytes),
            "sha256": row.artifact_sha256,
            "partition_values": {"symbol": row.symbol},
        }
        for row in successful.itertuples(index=False)
    ]
    total_rows = int(successful["row_count"].sum())
    known_st_rows = int(successful["known_st_rows"].sum())
    exact_limit_rows = int(successful["exact_limit_rows"].sum())
    manifest = DatasetManifest(
        schema_version=2,
        dataset="daily_market_state",
        provider="qlib-community-cn + dolthub/chenditc-investment-data",
        quality_grade=QualityGrade.C,
        row_count=total_rows,
        columns=MARKET_STATE_COLUMNS,
        data_files=artifacts,
        date_range={
            "start": pd.to_datetime(successful["start"]).min().strftime("%Y-%m-%d"),
            "end": pd.to_datetime(successful["end"]).max().strftime("%Y-%m-%d"),
        },
        source_files=[
            {
                "path": str(qlib_root / "calendars" / "day.txt"),
                "bytes": (qlib_root / "calendars" / "day.txt").stat().st_size,
                "sha256": sha256_file(qlib_root / "calendars" / "day.txt"),
            },
            {
                "path": str(store.manifest_path("daily_price_limit")),
                "bytes": store.manifest_path("daily_price_limit").stat().st_size,
                "sha256": sha256_file(store.manifest_path("daily_price_limit")),
            },
            *(
                [
                    {
                        "path": str(store.manifest_path("daily_official_status")),
                        "bytes": store.manifest_path(
                            "daily_official_status"
                        ).stat().st_size,
                        "sha256": sha256_file(
                            store.manifest_path("daily_official_status")
                        ),
                    }
                ]
                if official_manifest
                else []
            ),
            *(
                [
                    {
                        "path": str(store.manifest_path("risk_warning_events")),
                        "bytes": store.manifest_path(
                            "risk_warning_events"
                        ).stat().st_size,
                        "sha256": sha256_file(
                            store.manifest_path("risk_warning_events")
                        ),
                    }
                ]
                if not risk_warning_events.empty
                else []
            ),
            *(
                [
                    {
                        "path": str(store.manifest_path("st_name_events")),
                        "bytes": store.manifest_path("st_name_events").stat().st_size,
                        "sha256": sha256_file(
                            store.manifest_path("st_name_events")
                        ),
                    }
                ]
                if not st_name_events.empty
                else []
            ),
        ],
        primary_key=["symbol", "trade_date"],
        date_fields={"trade_date": "交易日"},
        partitioning={"style": "hive", "columns": ["symbol"]},
        coverage={
            "target_symbols": int(len(stocks)),
            "successful_symbols": int(len(successful)),
            "failed_symbols": int((statuses["status"] == "failed").sum()),
            "known_st_rows": known_st_rows,
            "known_st_ratio": known_st_rows / total_rows if total_rows else 0.0,
            "exact_limit_rows": exact_limit_rows,
            "exact_limit_ratio": exact_limit_rows / total_rows if total_rows else 0.0,
            "paused_rows": int(successful["paused_rows"].sum()),
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
            "停牌由上市区间内 Qlib 缺失 OHLC/零成交量推导，质量 B。",
            "有真实涨跌停价的交易日，限价和可识别 ST 为 B；特殊无上下限日的 ST 仍可能未知。",
            "2023-06 后的上交所与北交所 ST 由显式截止状态和发行人公告标题延续，质量 B。",
            "数据集整体按最差字段标为 C；策略可分别声明 status/st/limit 的最低质量。",
        ],
        checks={
            "partition_files": len(artifacts),
            "duplicate_status_symbols": int(statuses["symbol"].duplicated().sum()),
            "ipo_no_limit_rules": [
                "STAR first 5 sessions",
                "ChiNext registration first 5 sessions",
                "Main-board registration first 5 sessions",
                "Beijing first session",
            ],
            "base_mode": (
                "existing-full-partition-event-overlay"
                if reuse_existing_base
                else "full-source-rebuild"
            ),
        },
    )
    store.write_manifest(manifest)
    return statuses, manifest


def print_market_sync_summary(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
