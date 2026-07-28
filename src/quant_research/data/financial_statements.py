"""全市场东方财富三表与主要指标的公告日约束数据集。"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .security_lifecycle import clip_to_security_lifecycle
from .store import ResearchDataStore, sha256_file


EASTMONEY_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
KEY_FIELDS = [
    "SECUCODE",
    "REPORT_DATE",
    "NOTICE_DATE",
    "UPDATE_DATE",
    "REPORT_TYPE",
]


@dataclass(frozen=True)
class StatementSpec:
    report: str
    style: str
    fields: tuple[str, ...]


STATEMENT_SPECS = {
    "balance": StatementSpec(
        "RPT_F10_FINANCE_GBALANCE",
        "F10_FINANCE_GBALANCE",
        (
            "TOTAL_ASSETS",
            "TOTAL_LIABILITIES",
            "TOTAL_EQUITY",
            "MONETARYFUNDS",
            "INVENTORY",
            "ACCOUNTS_RECE",
            "NOTE_ACCOUNTS_RECE",
            "GOODWILL",
            "SHORT_LOAN",
            "LONG_LOAN",
            "NONCURRENT_LIAB_1YEAR",
            "BOND_PAYABLE",
        ),
    ),
    "income": StatementSpec(
        "RPT_F10_FINANCE_GINCOME",
        "APP_F10_GINCOME",
        (
            "TOTAL_OPERATE_INCOME",
            "OPERATE_INCOME",
            "OPERATE_COST",
            "OPERATE_PROFIT",
            "NETPROFIT",
            "PARENT_NETPROFIT",
            "DEDUCT_PARENT_NETPROFIT",
            "BASIC_EPS",
        ),
    ),
    "cashflow": StatementSpec(
        "RPT_F10_FINANCE_GCASHFLOW",
        "APP_F10_GCASHFLOW",
        ("NETCASH_OPERATE", "CONSTRUCT_LONG_ASSET"),
    ),
    "indicator": StatementSpec(
        "RPT_F10_FINANCE_MAINFINADATA",
        "APP_F10_MAINFINADATA",
        ("ROEJQ", "ZZCJLL", "XSMLL", "XSJLL", "EPSJB", "PER_EBIT"),
    ),
}


FIELD_MAP = {
    "TOTAL_ASSETS": "total_assets",
    "TOTAL_LIABILITIES": "total_liabilities",
    "TOTAL_EQUITY": "total_equity",
    "MONETARYFUNDS": "cash",
    "INVENTORY": "inventory",
    "ACCOUNTS_RECE": "accounts_receivable",
    "NOTE_ACCOUNTS_RECE": "notes_and_accounts_receivable",
    "GOODWILL": "goodwill",
    "SHORT_LOAN": "short_borrowing",
    "LONG_LOAN": "long_borrowing",
    "NONCURRENT_LIAB_1YEAR": "current_portion_noncurrent_liability",
    "BOND_PAYABLE": "bonds_payable",
    "TOTAL_OPERATE_INCOME": "revenue",
    "OPERATE_INCOME": "operating_revenue",
    "OPERATE_COST": "operating_cost",
    "OPERATE_PROFIT": "operating_profit",
    "NETPROFIT": "net_profit",
    "PARENT_NETPROFIT": "parent_net_profit",
    "DEDUCT_PARENT_NETPROFIT": "deducted_parent_net_profit",
    "BASIC_EPS": "basic_eps",
    "NETCASH_OPERATE": "operating_cash_flow",
    "CONSTRUCT_LONG_ASSET": "capital_expenditure",
    "ROEJQ": "roe",
    "ZZCJLL": "roa",
    "XSMLL": "gross_margin",
    "XSJLL": "net_margin",
    "EPSJB": "indicator_basic_eps",
    "PER_EBIT": "ebit_per_share",
}


FINANCIAL_COLUMNS = [
    "symbol",
    "report_date",
    "notice_date",
    "update_date",
    "report_type",
    "fiscal_year",
    "fiscal_quarter",
    "is_annual",
    "revision_sequence",
    "revenue",
    "operating_revenue",
    "operating_cost",
    "operating_profit",
    "net_profit",
    "parent_net_profit",
    "deducted_parent_net_profit",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "cash",
    "inventory",
    "accounts_receivable",
    "notes_and_accounts_receivable",
    "goodwill",
    "short_borrowing",
    "long_borrowing",
    "current_portion_noncurrent_liability",
    "bonds_payable",
    "interest_bearing_debt",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
    "ebit",
    "basic_eps",
    "roe",
    "roa",
    "gross_margin",
    "net_margin",
    "quarter_revenue",
    "quarter_operating_revenue",
    "quarter_operating_cost",
    "quarter_operating_profit",
    "quarter_net_profit",
    "quarter_parent_net_profit",
    "quarter_deducted_parent_net_profit",
    "quarter_operating_cash_flow",
    "quarter_capital_expenditure",
    "quarter_free_cash_flow",
    "quarter_ebit",
    "quarter_roe",
    "quarter_roa",
    "quarter_gross_margin",
    "quarter_net_margin",
    "source",
    "quality_grade",
]

REPORT_QUARTERS = {"一季报": 1, "中报": 2, "三季报": 3, "年报": 4}
NUMERIC_COLUMNS = set(FINANCIAL_COLUMNS).difference(
    {
        "symbol",
        "report_date",
        "notice_date",
        "update_date",
        "report_type",
        "fiscal_year",
        "fiscal_quarter",
        "is_annual",
        "revision_sequence",
        "source",
        "quality_grade",
    }
)

CUMULATIVE_TO_QUARTER = {
    "revenue": "quarter_revenue",
    "operating_revenue": "quarter_operating_revenue",
    "operating_cost": "quarter_operating_cost",
    "operating_profit": "quarter_operating_profit",
    "net_profit": "quarter_net_profit",
    "parent_net_profit": "quarter_parent_net_profit",
    "deducted_parent_net_profit": "quarter_deducted_parent_net_profit",
    "operating_cash_flow": "quarter_operating_cash_flow",
    "capital_expenditure": "quarter_capital_expenditure",
}


def eastmoney_symbol(symbol: str) -> str:
    symbol = str(symbol).upper()
    exchange = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(symbol[:2])
    if exchange is None or len(symbol) != 8 or not symbol[2:].isdigit():
        raise ValueError(f"unsupported local symbol: {symbol}")
    return f"{symbol[2:]}.{exchange}"


def _normalize_table(rows: list[dict], spec: StatementSpec) -> pd.DataFrame:
    columns = [*KEY_FIELDS, *spec.fields]
    if not rows:
        return pd.DataFrame(columns=["report_date", "notice_date", "update_date", "report_type"])
    frame = pd.DataFrame(rows)
    for column in columns:
        if column not in frame:
            frame[column] = np.nan
    frame = frame[columns].rename(
        columns={
            "REPORT_DATE": "report_date",
            "NOTICE_DATE": "notice_date",
            "UPDATE_DATE": "update_date",
            "REPORT_TYPE": "report_type",
            **FIELD_MAP,
        }
    )
    for column in ("report_date", "notice_date", "update_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["report_date", "notice_date"])
    frame = frame[frame["notice_date"].ge(frame["report_date"])]
    for column in set(frame.columns).intersection(FIELD_MAP.values()):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.sort_values(["report_date", "notice_date", "update_date"])
        .drop_duplicates(["report_date", "notice_date"], keep="last")
        .reset_index(drop=True)
    )


def _previous_fiscal_quarter(year: int, quarter: int) -> tuple[int, int]:
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def _derive_single_quarter_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """把公开源的年内累计流量转成聚宽 ``date=`` 查询使用的单季度口径。"""

    result = frame.copy()
    for target in CUMULATIVE_TO_QUARTER.values():
        result[target] = np.nan
    for column in (
        "quarter_free_cash_flow",
        "quarter_ebit",
        "quarter_roe",
        "quarter_roa",
        "quarter_gross_margin",
        "quarter_net_margin",
    ):
        result[column] = np.nan

    ordered = result.sort_values(["report_date", "notice_date"])
    for index, row in ordered.iterrows():
        fiscal_year = int(row["fiscal_year"])
        fiscal_quarter = int(row["fiscal_quarter"])
        previous_year, previous_quarter = _previous_fiscal_quarter(
            fiscal_year, fiscal_quarter
        )
        previous = ordered[
            ordered["fiscal_year"].eq(previous_year)
            & ordered["fiscal_quarter"].eq(previous_quarter)
            & ordered["notice_date"].le(row["notice_date"])
        ]
        previous_row = (
            previous.sort_values(["report_date", "notice_date"]).iloc[-1]
            if not previous.empty
            else None
        )
        for cumulative, target in CUMULATIVE_TO_QUARTER.items():
            current_value = row[cumulative]
            if pd.isna(current_value):
                continue
            if fiscal_quarter == 1:
                result.at[index, target] = current_value
            elif previous_row is not None and pd.notna(previous_row[cumulative]):
                result.at[index, target] = current_value - previous_row[cumulative]

        quarter_revenue = result.at[index, "quarter_operating_revenue"]
        quarter_cost = result.at[index, "quarter_operating_cost"]
        quarter_profit = result.at[index, "quarter_net_profit"]
        quarter_parent_profit = result.at[index, "quarter_parent_net_profit"]
        if pd.notna(quarter_revenue) and quarter_revenue > 0:
            if pd.notna(quarter_cost):
                result.at[index, "quarter_gross_margin"] = (
                    (quarter_revenue - quarter_cost) / quarter_revenue * 100.0
                )
            if pd.notna(quarter_profit):
                result.at[index, "quarter_net_margin"] = (
                    quarter_profit / quarter_revenue * 100.0
                )
        if previous_row is not None:
            previous_assets = previous_row["total_assets"]
            if (
                pd.notna(quarter_profit)
                and pd.notna(previous_assets)
                and pd.notna(row["total_assets"])
                and previous_assets + row["total_assets"] > 0
            ):
                result.at[index, "quarter_roa"] = (
                    quarter_profit * 2.0 / (previous_assets + row["total_assets"]) * 100.0
                )
            previous_equity = previous_row["total_equity"]
            if (
                pd.notna(quarter_parent_profit)
                and pd.notna(previous_equity)
                and pd.notna(row["total_equity"])
                and previous_equity + row["total_equity"] > 0
            ):
                result.at[index, "quarter_roe"] = (
                    quarter_parent_profit
                    * 2.0
                    / (previous_equity + row["total_equity"])
                    * 100.0
                )
        elif fiscal_quarter == 1:
            result.at[index, "quarter_roa"] = row["roa"]
            result.at[index, "quarter_roe"] = row["roe"]
        if fiscal_quarter == 1:
            if pd.isna(result.at[index, "quarter_gross_margin"]):
                result.at[index, "quarter_gross_margin"] = row["gross_margin"]
            if pd.isna(result.at[index, "quarter_net_margin"]):
                result.at[index, "quarter_net_margin"] = row["net_margin"]

    result["quarter_free_cash_flow"] = (
        result["quarter_operating_cash_flow"] - result["quarter_capital_expenditure"]
    )
    result["quarter_ebit"] = result["quarter_operating_profit"]
    return result


def normalize_financial_statements(
    symbol: str,
    raw_tables: dict[str, list[dict]],
) -> pd.DataFrame:
    """合并四张表，并在每个公告/修订事件点构造当时可见的完整记录。"""

    normalized = {
        name: _normalize_table(raw_tables.get(name, []), spec)
        for name, spec in STATEMENT_SPECS.items()
    }
    events = pd.concat(
        [
            frame[["report_date", "notice_date"]]
            for frame in normalized.values()
            if not frame.empty
        ],
        ignore_index=True,
    ) if any(not frame.empty for frame in normalized.values()) else pd.DataFrame()
    if events.empty:
        return pd.DataFrame(columns=FINANCIAL_COLUMNS)
    events = events.drop_duplicates().sort_values(["report_date", "notice_date"])
    rows_by_report: dict[str, dict[pd.Timestamp, list[dict[str, Any]]]] = {}
    for name, table in normalized.items():
        grouped_rows: dict[pd.Timestamp, list[dict[str, Any]]] = {}
        for row in table.sort_values(
            ["report_date", "notice_date", "update_date"]
        ).to_dict("records"):
            grouped_rows.setdefault(row["report_date"], []).append(row)
        rows_by_report[name] = grouped_rows
    records = []
    for report_date, report_events in events.groupby("report_date", sort=True):
        event_dates = report_events["notice_date"].sort_values().tolist()
        table_rows = {
            name: rows_by_report[name].get(report_date, [])
            for name in STATEMENT_SPECS
        }
        positions = {name: 0 for name in table_rows}
        visible: dict[str, dict[str, Any]] = {}
        for notice_date in event_dates:
            for name, rows in table_rows.items():
                position = positions[name]
                while position < len(rows) and rows[position]["notice_date"] <= notice_date:
                    visible[name] = rows[position]
                    position += 1
                positions[name] = position
            record: dict[str, Any] = {
                "symbol": str(symbol).upper(),
                "report_date": report_date,
                "notice_date": notice_date,
            }
            for name in STATEMENT_SPECS:
                row = visible.get(name, {})
                for key, value in row.items():
                    if key in {"report_date", "notice_date"} or pd.isna(value):
                        continue
                    record[key] = value
            records.append(record)
    frame = pd.DataFrame(records)
    for column in NUMERIC_COLUMNS | {"indicator_basic_eps", "ebit_per_share"}:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["basic_eps"] = frame["basic_eps"].fillna(frame["indicator_basic_eps"])
    debt_columns = [
        "short_borrowing",
        "long_borrowing",
        "current_portion_noncurrent_liability",
        "bonds_payable",
    ]
    frame["interest_bearing_debt"] = frame[debt_columns].sum(
        axis=1, min_count=1
    )
    frame["free_cash_flow"] = frame["operating_cash_flow"] - frame["capital_expenditure"]
    frame["ebit"] = frame["operating_profit"]
    derived_gross_margin = (
        (frame["revenue"] - frame["operating_cost"]) / frame["revenue"] * 100.0
    ).where(frame["revenue"].gt(0))
    derived_net_margin = (
        frame["net_profit"] / frame["revenue"] * 100.0
    ).where(frame["revenue"].gt(0))
    frame["gross_margin"] = frame["gross_margin"].fillna(derived_gross_margin)
    frame["net_margin"] = frame["net_margin"].fillna(derived_net_margin)
    derived_roe = (
        frame["parent_net_profit"] / frame["total_equity"] * 100.0
    ).where(frame["total_equity"].gt(0))
    derived_roa = (
        frame["net_profit"] / frame["total_assets"] * 100.0
    ).where(frame["total_assets"].gt(0))
    frame["roe"] = frame["roe"].fillna(derived_roe)
    frame["roa"] = frame["roa"].fillna(derived_roa)
    frame["report_type"] = frame.get("report_type", pd.Series(index=frame.index, dtype="string"))
    inferred_quarter = frame["report_date"].dt.quarter
    frame["fiscal_quarter"] = frame["report_type"].map(REPORT_QUARTERS).fillna(inferred_quarter)
    frame["fiscal_quarter"] = frame["fiscal_quarter"].astype("int8")
    frame["fiscal_year"] = frame["report_date"].dt.year.astype("int16")
    frame["is_annual"] = frame["fiscal_quarter"].eq(4)
    frame["revision_sequence"] = frame.groupby("report_date").cumcount().astype("int16") + 1
    frame = _derive_single_quarter_fields(frame)
    if "update_date" not in frame:
        frame["update_date"] = frame["notice_date"]
    frame["update_date"] = pd.to_datetime(frame["update_date"], errors="coerce").fillna(
        frame["notice_date"]
    )
    frame["source"] = "eastmoney/securities-financial-statements"
    frame["quality_grade"] = QualityGrade.B.value
    result = frame.reindex(columns=FINANCIAL_COLUMNS).sort_values(
        ["symbol", "report_date", "notice_date"]
    )
    validate_financial_statements(result)
    return result.reset_index(drop=True)


def validate_financial_statements(frame: pd.DataFrame) -> None:
    missing = set(FINANCIAL_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"financial statements are missing columns: {sorted(missing)}")
    if frame.duplicated(["symbol", "report_date", "notice_date"]).any():
        raise ValueError("financial statements contain duplicate PIT rows")
    if frame["notice_date"].lt(frame["report_date"]).any():
        raise ValueError("financial statements contain notice dates before report dates")
    if frame["quality_grade"].ne(QualityGrade.B.value).any():
        raise ValueError("financial statement revisions must remain quality B")


def latest_financials_asof(
    frame: pd.DataFrame,
    observation_date,
    symbols: list[str] | None = None,
    annual_only: bool = False,
) -> pd.DataFrame:
    date = pd.Timestamp(observation_date).normalize()
    visible = frame[pd.to_datetime(frame["notice_date"]).le(date)].copy()
    if symbols is not None:
        visible = visible[visible["symbol"].isin({item.upper() for item in symbols})]
    if annual_only:
        visible = visible[visible["is_annual"]]
    return (
        visible.sort_values(["symbol", "report_date", "notice_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
        .sort_values("symbol")
        .reset_index(drop=True)
    )


@dataclass
class EastmoneyFinancialStatementProvider:
    retries: int = 4
    retry_delay: float = 0.6
    timeout: float = 45.0

    def fetch_table(self, provider_symbol: str, table: str) -> list[dict]:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required for financial downloads") from exc
        spec = STATEMENT_SPECS[table]
        fields = ",".join([*KEY_FIELDS, *spec.fields])
        last_error = None
        for attempt in range(self.retries):
            try:
                response = requests.get(
                    EASTMONEY_URL,
                    params={
                        "type": spec.report,
                        "sty": fields,
                        "filter": f'(SECUCODE="{provider_symbol}")',
                        "p": 1,
                        "ps": 200,
                        "sr": -1,
                        "st": "REPORT_DATE",
                        "source": "HSF10",
                        "client": "PC",
                    },
                    headers={"User-Agent": "Mozilla/5.0 quant-research/1.0"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("success"):
                    message = str(payload.get("message") or "")
                    if message in {"返回数据为空", "暂无数据", "no data"}:
                        return []
                    raise RuntimeError(message or "provider returned failure")
                result = payload.get("result") or {}
                rows = list(result.get("data") or [])
                pages = int(result.get("pages") or 1)
                for page in range(2, pages + 1):
                    page_response = requests.get(
                        EASTMONEY_URL,
                        params={
                            "type": spec.report,
                            "sty": fields,
                            "filter": f'(SECUCODE="{provider_symbol}")',
                            "p": page,
                            "ps": 200,
                            "sr": -1,
                            "st": "REPORT_DATE",
                            "source": "HSF10",
                            "client": "PC",
                        },
                        headers={"User-Agent": "Mozilla/5.0 quant-research/1.0"},
                        timeout=self.timeout,
                    )
                    page_response.raise_for_status()
                    page_payload = page_response.json()
                    if not page_payload.get("success"):
                        message = str(page_payload.get("message") or "")
                        if message in {"返回数据为空", "暂无数据", "no data"}:
                            break
                        raise RuntimeError(message or "page failure")
                    rows.extend(((page_payload.get("result") or {}).get("data") or []))
                return rows
            except Exception as exc:  # noqa: BLE001 - provider failures vary
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        raise RuntimeError(f"{table} download failed for {provider_symbol}: {last_error}")

    def fetch(self, symbol: str) -> dict[str, list[dict]]:
        provider_symbol = eastmoney_symbol(symbol)
        return {
            table: self.fetch_table(provider_symbol, table)
            for table in STATEMENT_SPECS
        }


def _raw_path(store: ResearchDataStore, table: str, symbol: str) -> Path:
    return store.raw_dir / "eastmoney" / "financial-statements" / table / f"{symbol}.json.gz"


@lru_cache(maxsize=None)
def _raw_directory_index(directory: str) -> dict[str, Path]:
    grouped: dict[str, list[Path]] = {}
    for path in Path(directory).glob("*.json.gz"):
        symbol = path.name.removesuffix(".json.gz").split("__", 1)[0]
        grouped.setdefault(symbol, []).append(path)
    return {
        symbol: max(paths, key=lambda item: item.stat().st_mtime_ns)
        for symbol, paths in grouped.items()
    }


def _latest_raw_path(store: ResearchDataStore, table: str, symbol: str) -> Path | None:
    canonical = _raw_path(store, table, symbol)
    return _raw_directory_index(str(canonical.parent.resolve())).get(symbol)


def _load_cached_raw(store: ResearchDataStore, symbol: str) -> dict[str, list[dict]] | None:
    payload = {}
    for table in STATEMENT_SPECS:
        path = _latest_raw_path(store, table, symbol)
        if path is None:
            return None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload[table] = json.load(handle)["rows"]
    return payload


def _persist_raw(
    store: ResearchDataStore,
    symbol: str,
    provider_symbol: str,
    tables: dict[str, list[dict]],
) -> list[dict]:
    store.initialize()
    artifacts = []
    for table, rows in tables.items():
        target = _raw_path(store, table, symbol)
        target.parent.mkdir(parents=True, exist_ok=True)
        wrapper = {
            "provider": "eastmoney/securities-api",
            "symbol": symbol,
            "provider_symbol": provider_symbol,
            "table": table,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "rows": rows,
        }
        payload = (json.dumps(wrapper, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        compressed = gzip.compress(payload, mtime=0)
        expected_hash = hashlib.sha256(compressed).hexdigest()
        if target.exists() and sha256_file(target) != expected_hash:
            target = target.with_name(f"{symbol}__{expected_hash[:12]}.json.gz")
        if not target.exists():
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            os.close(handle)
            temporary = Path(temporary_name)
            try:
                temporary.write_bytes(compressed)
                temporary.replace(target)
            finally:
                if temporary.exists():
                    temporary.unlink()
        artifacts.append(
            {
                "path": target.relative_to(store.root).as_posix(),
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
                "symbol": symbol,
                "table": table,
                "row_count": len(rows),
            }
        )
    return artifacts


def _status_path(store: ResearchDataStore) -> Path:
    return store.normalized_path("financial_statement_sync_status")


def _checkpoint_status(store: ResearchDataStore, records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    frame = (
        frame.sort_values("completed_at")
        .drop_duplicates("symbol", keep="last")
        .sort_values("symbol")
        .reset_index(drop=True)
    )
    store.write_parquet("financial_statement_sync_status", frame)
    return frame


def audit_financial_field_coverage(
    store: ResearchDataStore,
    artifacts: list[dict],
    active_symbols: set[str],
) -> dict:
    """逐分区统计字段覆盖，避免把整套全市场财务一次读入内存。"""

    numeric_fields = sorted(NUMERIC_COLUMNS)
    non_null_rows = {field: 0 for field in numeric_fields}
    symbols_with_any = {field: 0 for field in numeric_fields}
    active_latest_non_null = {field: 0 for field in numeric_fields}
    total_rows = 0
    audited_symbols = 0
    failures = []
    for artifact in artifacts:
        symbol = (artifact.get("partition_values") or {}).get("symbol")
        try:
            frame = pd.read_parquet(
                store.root / artifact["path"],
                columns=["report_date", "notice_date", *numeric_fields],
            )
            total_rows += len(frame)
            audited_symbols += 1
            for field in numeric_fields:
                count = int(frame[field].notna().sum())
                non_null_rows[field] += count
                symbols_with_any[field] += int(count > 0)
            if symbol in active_symbols and not frame.empty:
                latest = frame.sort_values(["report_date", "notice_date"]).iloc[-1]
                for field in numeric_fields:
                    active_latest_non_null[field] += int(pd.notna(latest[field]))
        except Exception as exc:  # pragma: no cover - real partition audit evidence
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    active_count = len(active_symbols)
    return {
        "audited_symbols": audited_symbols,
        "audited_rows": total_rows,
        "partition_failures": failures,
        "fields": {
            field: {
                "non_null_rows": non_null_rows[field],
                "row_coverage_ratio": (
                    non_null_rows[field] / total_rows if total_rows else 0.0
                ),
                "symbols_with_any": symbols_with_any[field],
                "symbol_coverage_ratio": (
                    symbols_with_any[field] / audited_symbols if audited_symbols else 0.0
                ),
                "current_latest_non_null": active_latest_non_null[field],
                "current_latest_coverage_ratio": (
                    active_latest_non_null[field] / active_count if active_count else 0.0
                ),
            }
            for field in numeric_fields
        },
    }


def _download_symbol(
    store: ResearchDataStore,
    provider: EastmoneyFinancialStatementProvider,
    symbol: str,
    canonical_symbol: str,
    refresh: bool,
) -> tuple[str, str, dict[str, list[dict]], list[dict]]:
    if not refresh:
        cached = _load_cached_raw(store, symbol)
        if cached is not None:
            artifacts = [
                {
                    "path": _latest_raw_path(store, table, symbol).relative_to(store.root).as_posix(),
                    "bytes": _latest_raw_path(store, table, symbol).stat().st_size,
                    "sha256": sha256_file(_latest_raw_path(store, table, symbol)),
                    "symbol": symbol,
                    "table": table,
                    "row_count": len(rows),
                }
                for table, rows in cached.items()
            ]
            return symbol, symbol, cached, artifacts
    tables = provider.fetch(symbol)
    provider_local_symbol = symbol
    if not any(tables.values()) and canonical_symbol != symbol:
        tables = provider.fetch(canonical_symbol)
        provider_local_symbol = canonical_symbol
    artifacts = _persist_raw(
        store,
        symbol,
        eastmoney_symbol(provider_local_symbol),
        tables,
    )
    return symbol, provider_local_symbol, tables, artifacts


def sync_financial_statement_partitions(
    store: ResearchDataStore,
    securities: pd.DataFrame,
    *,
    provider: EastmoneyFinancialStatementProvider | None = None,
    workers: int = 12,
    refresh: bool = False,
    resume: bool = True,
    checkpoint_every: int = 25,
) -> tuple[pd.DataFrame, DatasetManifest]:
    """为全量历史 A 股构建按证券分区的财报数据与逐证券状态。"""

    required = {"symbol", "canonical_symbol", "asset_type", "active_at_source_end"}
    missing = required.difference(securities.columns)
    if missing:
        raise ValueError(f"security master is missing columns: {sorted(missing)}")
    universe = securities[securities["asset_type"].eq("stock")].copy()
    universe["symbol"] = universe["symbol"].astype(str).str.upper()
    universe["canonical_symbol"] = universe["canonical_symbol"].fillna(
        universe["symbol"]
    ).astype(str).str.upper()
    universe = universe.drop_duplicates("symbol").sort_values("symbol")
    provider = provider or EastmoneyFinancialStatementProvider()
    if not refresh:
        for table in STATEMENT_SPECS:
            _raw_directory_index(
                str(_raw_path(store, table, "__index__").parent.resolve())
            )
    existing = (
        pd.read_parquet(_status_path(store))
        if resume and _status_path(store).is_file()
        else pd.DataFrame()
    )
    completed = (
        set(existing.loc[existing["status"].isin(["success", "empty"]), "symbol"])
        if not existing.empty and not refresh
        else set()
    )
    records = existing.to_dict("records") if not existing.empty else []
    pending = universe[~universe["symbol"].isin(completed)]
    raw_inventory = []
    successful_artifacts = []
    for row in records:
        if row.get("status") == "success" and row.get("artifact_path"):
            successful_artifacts.append(
                {
                    "path": row["artifact_path"],
                    "bytes": int(row["artifact_bytes"]),
                    "sha256": row["artifact_sha256"],
                    "partition_values": {"symbol": row["symbol"]},
                }
            )
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _download_symbol,
                store,
                provider,
                row.symbol,
                row.canonical_symbol,
                refresh,
            ): row
            for row in pending.itertuples(index=False)
        }
        processed = 0
        for future in as_completed(futures):
            security = futures[future]
            processed += 1
            base = {
                "symbol": security.symbol,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                _, provider_symbol, tables, raw_artifacts = future.result()
                raw_inventory.extend(raw_artifacts)
                normalized = normalize_financial_statements(security.symbol, tables)
                normalized = clip_to_security_lifecycle(
                    normalized,
                    pd.Series(security._asdict()),
                    date_column="report_date",
                )
                table_counts = {name: len(rows) for name, rows in tables.items()}
                raw_artifacts_json = json.dumps(raw_artifacts, ensure_ascii=False, sort_keys=True)
                if normalized.empty:
                    records.append(
                        {
                            **base,
                            "status": "empty",
                            "provider_symbol": provider_symbol,
                            "row_count": 0,
                            "core_complete": False,
                            "table_counts": json.dumps(table_counts, sort_keys=True),
                            "raw_artifacts": raw_artifacts_json,
                            "error": "no statement rows inside the security lifecycle",
                        }
                    )
                else:
                    artifact = store.write_parquet(
                        "fundamentals_pit",
                        normalized,
                        filename=f"symbol={security.symbol}/data.parquet",
                    )
                    core_complete = all(table_counts.get(name, 0) > 0 for name in (
                        "balance", "income", "cashflow"
                    ))
                    records.append(
                        {
                            **base,
                            "status": "success",
                            "provider_symbol": provider_symbol,
                            "row_count": len(normalized),
                            "start": normalized["notice_date"].min(),
                            "end": normalized["notice_date"].max(),
                            "core_complete": core_complete,
                            "table_counts": json.dumps(table_counts, sort_keys=True),
                            "raw_artifacts": raw_artifacts_json,
                            "artifact_path": artifact["path"],
                            "artifact_bytes": artifact["bytes"],
                            "artifact_sha256": artifact["sha256"],
                            "error": None,
                        }
                    )
                    successful_artifacts.append(
                        {**artifact, "partition_values": {"symbol": security.symbol}}
                    )
            except Exception as exc:  # noqa: BLE001 - every provider failure is evidence
                records.append(
                    {
                        **base,
                        "status": "failed",
                        "row_count": 0,
                        "core_complete": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            if processed % checkpoint_every == 0:
                _checkpoint_status(store, records)
                print(
                    f"financial statements: {processed}/{len(pending)} pending symbols",
                    flush=True,
                )
    statuses = _checkpoint_status(store, records)
    statuses = statuses[statuses["symbol"].isin(set(universe["symbol"]))].copy()
    successes = statuses[statuses["status"].eq("success")]
    active = set(universe.loc[universe["active_at_source_end"].astype(bool), "symbol"])
    core_symbols = set(successes.loc[successes["core_complete"].astype(bool), "symbol"])
    current_core_covered = len(active & core_symbols)
    status_inventory = []
    for value in statuses.get("raw_artifacts", pd.Series(dtype="string")).dropna():
        status_inventory.extend(json.loads(value))
    raw_inventory = list(
        {
            (item["symbol"], item["table"], item["path"]): item
            for item in [*raw_inventory, *status_inventory]
        }.values()
    )
    raw_inventory_path = store.write_json_report(
        "financial-statements-raw-inventory",
        {"schema_version": 1, "artifacts": raw_inventory},
    )
    status_artifact = {
        "path": _status_path(store).relative_to(store.root).as_posix(),
        "bytes": _status_path(store).stat().st_size,
        "sha256": sha256_file(_status_path(store)),
    }
    inventory_artifact = {
        "path": raw_inventory_path.relative_to(store.root).as_posix(),
        "bytes": raw_inventory_path.stat().st_size,
        "sha256": sha256_file(raw_inventory_path),
    }
    successful_artifacts = list(
        {
            item["partition_values"]["symbol"]: item for item in successful_artifacts
        }.values()
    )
    field_coverage = audit_financial_field_coverage(
        store,
        successful_artifacts,
        active,
    )
    manifest = DatasetManifest(
        schema_version=2,
        dataset="fundamentals_pit",
        provider="eastmoney/securities-financial-statements",
        quality_grade=QualityGrade.B,
        row_count=int(successes["row_count"].sum()),
        columns=FINANCIAL_COLUMNS,
        data_files=successful_artifacts,
        date_range={
            "start": pd.to_datetime(successes["start"]).min().strftime("%Y-%m-%d"),
            "end": pd.to_datetime(successes["end"]).max().strftime("%Y-%m-%d"),
        },
        source_files=[inventory_artifact, status_artifact],
        primary_key=["symbol", "report_date", "notice_date"],
        date_fields={
            "report_date": "财务报告期末",
            "notice_date": "该版本首次可见的公告日",
            "update_date": "数据商记录的更新日",
        },
        partitioning={"style": "hive", "columns": ["symbol"]},
        coverage={
            "historical_stock_universe": len(universe),
            "successful_symbols": len(successes),
            "empty_symbols": int(statuses["status"].eq("empty").sum()),
            "failed_symbols": int(statuses["status"].eq("failed").sum()),
            "current_expected": len(active),
            "current_core_covered": current_core_covered,
            "current_core_coverage_ratio": current_core_covered / len(active) if active else 0.0,
            "field_coverage": field_coverage,
        },
        failures=[
            {"symbol": row.symbol, "status": row.status, "error": row.error}
            for row in statuses.itertuples(index=False)
            if row.status != "success"
        ],
        limitations=[
            "东方财富可能把后来修订值回填到旧公告记录，整体质量固定为 B。",
            "ROE、ROA、毛利率和净利率优先使用主要指标表，缺失时由三表期末值近似派生。",
            "EBIT 以营业利润作为公开免费源下的代理口径。",
        ],
        checks={
            "all_historical_symbols_have_status": len(statuses) == len(universe),
            "duplicate_status_symbols": int(statuses["symbol"].duplicated().sum()),
            "field_partition_audit_failures": len(field_coverage["partition_failures"]),
            "current_core_coverage_target": 0.95,
            "current_core_coverage_passed": (
                current_core_covered / len(active) >= 0.95 if active else False
            ),
        },
    )
    store.write_manifest(manifest)
    store.write_json_report(
        "financial-statements-coverage",
        {
            "schema_version": 1,
            "dataset": "fundamentals_pit",
            "manifest": manifest.to_dict(),
            "status_counts": statuses["status"].value_counts().sort_index().to_dict(),
            "failures": manifest.failures,
        },
    )
    return statuses, manifest
