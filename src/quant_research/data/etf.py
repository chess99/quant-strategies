"""新浪 ETF 日线适配与规范化。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .security_master import SECURITY_MASTER_COLUMNS, validate_security_master
from .store import ResearchDataStore, sha256_file


ETF_DAILY_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "cash_dividend",
    "corporate_action_multiplier",
    "factor",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "source",
    "quality_grade",
]


@dataclass(frozen=True)
class EtfDefinition:
    symbol: str
    display_name: str

    @property
    def sina_symbol(self) -> str:
        return self.symbol.lower()


DEFAULT_ETFS = (
    EtfDefinition("SH518880", "黄金ETF"),
    EtfDefinition("SH513100", "纳指ETF"),
    EtfDefinition("SZ159915", "创业板ETF"),
    EtfDefinition("SH510180", "上证180ETF"),
)

COMMON_SHARE_MULTIPLIERS = np.array(
    [0.1, 0.2, 0.25, 1.0 / 3.0, 0.5, 2.0, 3.0, 4.0, 5.0, 10.0],
    dtype=float,
)


def _normalize_dividends(dividends: pd.DataFrame) -> pd.Series:
    if dividends is None or dividends.empty:
        return pd.Series(dtype=float)
    columns = list(dividends.columns)
    date_column = "日期" if "日期" in columns else columns[0]
    cumulative_column = "累计分红" if "累计分红" in columns else columns[1]
    frame = dividends[[date_column, cumulative_column]].copy()
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce").dt.normalize()
    frame[cumulative_column] = pd.to_numeric(
        frame[cumulative_column], errors="coerce"
    )
    frame = frame.dropna().sort_values(date_column)
    cash = frame[cumulative_column].diff()
    if not frame.empty:
        cash.iloc[0] = frame[cumulative_column].iloc[0]
    cash = cash.clip(lower=0.0)
    return pd.Series(cash.to_numpy(), index=frame[date_column], dtype=float).groupby(
        level=0
    ).sum()


def normalize_sina_etf(
    symbol: str,
    quotes: pd.DataFrame,
    dividends: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """规范化新浪原始价格，并以现金分红构造总收益调整因子。"""
    if quotes is None or quotes.empty:
        raise ValueError(f"ETF quotes are empty: {symbol}")
    symbol = symbol.upper()
    frame = quotes.copy()
    if "date" not in frame:
        raise ValueError("ETF quotes are missing date")
    frame["trade_date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column not in frame:
            if column == "amount":
                frame[column] = np.nan
            else:
                raise ValueError(f"ETF quotes are missing {column}")
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["trade_date", "open", "high", "low", "close"])
    frame = frame.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    dividend_series = _normalize_dividends(dividends)
    frame["cash_dividend"] = frame["trade_date"].map(dividend_series).fillna(0.0)

    factor = np.ones(len(frame), dtype=float)
    action_multiplier = np.ones(len(frame), dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    cash_dividends = frame["cash_dividend"].to_numpy(dtype=float)
    for index in range(1, len(frame)):
        if closes[index] <= 0.0 or closes[index - 1] <= 0.0:
            factor[index] = factor[index - 1]
            continue
        raw_ratio = closes[index] / closes[index - 1]
        if raw_ratio < 0.70 or raw_ratio > 1.30:
            adjusted_ratios = raw_ratio * COMMON_SHARE_MULTIPLIERS
            candidate_index = int(np.argmin(np.abs(adjusted_ratios - 1.0)))
            if abs(adjusted_ratios[candidate_index] - 1.0) <= 0.25:
                action_multiplier[index] = COMMON_SHARE_MULTIPLIERS[candidate_index]
        dividend_multiplier = (closes[index] + cash_dividends[index]) / closes[index]
        factor[index] = (
            factor[index - 1]
            * action_multiplier[index]
            * dividend_multiplier
        )
    frame["corporate_action_multiplier"] = action_multiplier
    frame["factor"] = factor
    for column in ("open", "high", "low", "close"):
        frame[f"adjusted_{column}"] = frame[column] * frame["factor"]
    frame["symbol"] = symbol
    frame["source"] = "akshare/sina"
    frame["quality_grade"] = QualityGrade.B.value
    result = frame[ETF_DAILY_COLUMNS].reset_index(drop=True)
    validate_etf_daily(result)
    return result


def validate_etf_daily(frame: pd.DataFrame) -> None:
    missing = set(ETF_DAILY_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"ETF daily data is missing columns: {sorted(missing)}")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ValueError("ETF daily data contains duplicate symbol/date rows")
    if (frame[["open", "high", "low", "close"]] <= 0.0).any(axis=None):
        raise ValueError("ETF daily OHLC must be positive")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("ETF daily high is inconsistent with OHLC")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("ETF daily low is inconsistent with OHLC")
    if (frame["factor"] <= 0.0).any():
        raise ValueError("ETF adjustment factor must be positive")
    adjusted_return = frame.groupby("symbol")["adjusted_close"].pct_change()
    if (adjusted_return.abs() > 0.30).any():
        row = frame.loc[adjusted_return.abs().idxmax()]
        raise ValueError(
            "ETF adjusted close contains an unexplained return above 30%: "
            f"{row['symbol']} {row['trade_date']:%Y-%m-%d}"
        )


class SinaEtfProvider:
    def fetch(self, definition: EtfDefinition) -> tuple[pd.DataFrame, pd.DataFrame]:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare is required for Sina ETF downloads") from exc
        quotes = ak.fund_etf_hist_sina(symbol=definition.sina_symbol)
        try:
            dividends = ak.fund_etf_dividend_sina(symbol=definition.sina_symbol)
        except (KeyError, IndexError, ValueError):
            dividends = pd.DataFrame(columns=["日期", "累计分红"])
        return quotes, dividends


def merge_etfs_into_security_master(
    store: ResearchDataStore,
    definitions: tuple[EtfDefinition, ...],
    bars: pd.DataFrame,
    etf_manifest_path: Path,
) -> DatasetManifest:
    master = store.read_parquet("security_master")
    definition_by_symbol = {item.symbol: item for item in definitions}
    additions = []
    for symbol, group in bars.groupby("symbol"):
        definition = definition_by_symbol[symbol]
        additions.append(
            {
                "symbol": symbol,
                "exchange": "XSHG" if symbol.startswith("SH") else "XSHE",
                "asset_type": "etf",
                "board": "etf",
                "start_date": group["trade_date"].min(),
                "end_date": group["trade_date"].max(),
                "display_name": definition.display_name,
                "quality_grade": QualityGrade.B.value,
                "source": "akshare/sina",
            }
        )
    master = master[~master["symbol"].isin(definition_by_symbol)].copy()
    master = pd.concat(
        [master, pd.DataFrame(additions, columns=SECURITY_MASTER_COLUMNS)],
        ignore_index=True,
    ).sort_values("symbol")
    validate_security_master(master)
    data_file = store.write_parquet("security_master", master.reset_index(drop=True))
    previous = store.read_manifest("security_master")
    manifest = DatasetManifest(
        schema_version=2,
        dataset="security_master",
        provider="qlib-community-cn + akshare/sina",
        quality_grade=QualityGrade.B,
        row_count=len(master),
        columns=list(master.columns),
        data_files=[data_file],
        date_range={
            "start": pd.to_datetime(master["start_date"]).min().strftime("%Y-%m-%d"),
            "end": pd.to_datetime(master["end_date"]).max().strftime("%Y-%m-%d"),
        },
        source_files=previous.get("source_files", [])
        + [
            {
                "path": str(etf_manifest_path),
                "bytes": etf_manifest_path.stat().st_size,
                "sha256": sha256_file(etf_manifest_path),
            }
        ],
        notes=previous.get("notes", [])
        + ["已合并首次 ETF 日线验收使用的四只资产。"],
    )
    store.write_manifest(manifest)
    return manifest


def sync_sina_etfs(
    store: ResearchDataStore,
    definitions: tuple[EtfDefinition, ...] = DEFAULT_ETFS,
    provider: SinaEtfProvider | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    provider = provider or SinaEtfProvider()
    normalized = []
    raw_files = []
    for definition in definitions:
        quotes, dividends = provider.fetch(definition)
        raw_files.append(
            store.write_raw_csv(
                "sina",
                "etf_daily",
                (
                    f"{definition.symbol.lower()}__quotes__"
                    f"{pd.to_datetime(quotes['date']).max():%Y-%m-%d}.csv"
                ),
                quotes,
            )
        )
        raw_files.append(
            store.write_raw_csv(
                "sina",
                "etf_daily",
                (
                    f"{definition.symbol.lower()}__dividends__"
                    f"{pd.Timestamp.today():%Y-%m-%d}.csv"
                ),
                dividends,
            )
        )
        normalized.append(normalize_sina_etf(definition.symbol, quotes, dividends))
    bars = pd.concat(normalized, ignore_index=True).sort_values(
        ["symbol", "trade_date"]
    )
    data_file = store.write_parquet("etf_daily", bars.reset_index(drop=True))
    manifest = DatasetManifest(
        schema_version=1,
        dataset="etf_daily",
        provider="akshare/sina",
        quality_grade=QualityGrade.B,
        row_count=len(bars),
        columns=list(bars.columns),
        data_files=[data_file],
        date_range={
            "start": bars["trade_date"].min().strftime("%Y-%m-%d"),
            "end": bars["trade_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=raw_files,
        notes=[
            "新浪 ETF 日行情是原始价格。",
            "总收益调整因子由累计现金分红和可识别的常见份额拆分/合并倍率推导。",
            "调整后单日绝对收益超过 30% 时拒绝数据，整体质量为 B。",
        ],
    )
    etf_manifest_path = store.write_manifest(manifest)
    merge_etfs_into_security_master(store, definitions, bars, etf_manifest_path)
    return bars.reset_index(drop=True), manifest
