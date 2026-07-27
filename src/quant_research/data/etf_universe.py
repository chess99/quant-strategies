"""场内 ETF 历史候选池、证券主表与覆盖率审计。"""

from __future__ import annotations

import re
from collections.abc import Iterable

import pandas as pd

from .contracts import QualityGrade
from .security_master import SECURITY_MASTER_COLUMNS, validate_security_master


ETF_MASTER_COLUMNS = [
    "symbol",
    "code",
    "exchange",
    "display_name",
    "fund_full_name",
    "reported_fund_type",
    "etf_category",
    "tracking_target",
    "inception_date",
    "listing_date",
    "delisting_date",
    "first_trade_date",
    "last_trade_date",
    "expected_active",
    "active_at_source_end",
    "lifecycle_status",
    "in_sina",
    "in_ths",
    "seen_in_historical_exchange_snapshot",
    "seen_in_termination_announcement",
    "termination_announcement_date",
    "candidate_sources",
    "bar_status",
    "bar_row_count",
    "bar_error",
    "profile_status",
    "quality_grade",
    "source",
]

ETF_NAME_PATTERN = re.compile(r"ETF", re.IGNORECASE)
ETF_LINK_PATTERN = re.compile(r"联接|FOF", re.IGNORECASE)

_CROSS_BORDER_PATTERN = re.compile(
    r"海外|港股|港股通|恒生|H股|纳斯达克|纳指|标普|道琼斯|日经|德国|法国|"
    r"印度|沙特|东南亚|新加坡|韩国|中韩|美国|全球|QDII",
    re.IGNORECASE,
)
_COMMODITY_PATTERN = re.compile(
    r"黄金|白银|原油|豆粕|有色期货|能源化工期货|商品期货",
    re.IGNORECASE,
)
_BROAD_EQUITY_PATTERN = re.compile(
    r"沪深300|中证500|中证800|中证1000|中证2000|上证50|上证180|"
    r"深证100|创业板(?!.*行业)|科创50|科创100|科创200|A股|全指|综指|"
    r"红利|价值|成长|大盘|中盘|小盘|宽基",
    re.IGNORECASE,
)


def _first_non_empty(values: Iterable[object]) -> object | None:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return value
    return None


def symbol_for_etf_code(code: object) -> str:
    text = str(code).strip().lower()
    text = re.sub(r"^(sh|sz)", "", text)
    if not re.fullmatch(r"\d{6}", text):
        raise ValueError(f"invalid ETF code: {code!r}")
    prefix = "SZ" if text.startswith(("15", "16")) else "SH"
    return f"{prefix}{text}"


def normalize_current_etf_lists(
    sina: pd.DataFrame,
    ths: pd.DataFrame,
) -> pd.DataFrame:
    """合并两个当前列表；同花顺无最新交易日的记录不进入活跃分母。"""

    records: dict[str, dict] = {}
    if sina is not None and not sina.empty:
        for payload in sina.to_dict("records"):
            symbol = symbol_for_etf_code(payload.get("代码"))
            records[symbol] = {
                "symbol": symbol,
                "display_name": payload.get("名称"),
                "expected_active": True,
                "in_sina": True,
                "in_ths": False,
                "latest_trade_date": pd.NaT,
                "reported_fund_type": None,
            }
    if ths is not None and not ths.empty:
        for payload in ths.to_dict("records"):
            symbol = symbol_for_etf_code(payload.get("基金代码"))
            latest = pd.to_datetime(payload.get("最新-交易日"), errors="coerce")
            item = records.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "display_name": None,
                    "expected_active": False,
                    "in_sina": False,
                    "in_ths": False,
                    "latest_trade_date": pd.NaT,
                    "reported_fund_type": None,
                },
            )
            item["display_name"] = _first_non_empty(
                [item["display_name"], payload.get("基金名称")]
            )
            item["in_ths"] = True
            item["latest_trade_date"] = latest
            item["reported_fund_type"] = payload.get("基金类型")
            item["expected_active"] = bool(item["expected_active"] or pd.notna(latest))
    result = pd.DataFrame(records.values())
    if result.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "display_name",
                "expected_active",
                "in_sina",
                "in_ths",
                "latest_trade_date",
                "reported_fund_type",
            ]
        )
    result["latest_trade_date"] = pd.to_datetime(
        result["latest_trade_date"], errors="coerce"
    ).dt.normalize()
    return result.sort_values("symbol").reset_index(drop=True)


def _normalize_fund_name_candidates(fund_names: pd.DataFrame) -> pd.DataFrame:
    if fund_names is None or fund_names.empty:
        return pd.DataFrame(columns=["symbol", "display_name", "reported_fund_type"])
    frame = fund_names.copy()
    codes = frame["基金代码"].astype("string").str.zfill(6)
    names = frame["基金简称"].astype("string")
    valid = (
        codes.str.fullmatch(r"(15|5)\d{4}", na=False)
        & names.str.contains(ETF_NAME_PATTERN, na=False)
        & ~names.str.contains(ETF_LINK_PATTERN, na=False)
    )
    frame = frame.loc[valid].copy()
    frame["symbol"] = codes.loc[valid].map(symbol_for_etf_code)
    frame["display_name"] = names.loc[valid]
    frame["reported_fund_type"] = frame.get("基金类型")
    return frame[["symbol", "display_name", "reported_fund_type"]].drop_duplicates(
        "symbol", keep="last"
    )


def _normalize_historical_candidates(snapshots: pd.DataFrame) -> pd.DataFrame:
    if snapshots is None or snapshots.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "display_name",
                "reported_fund_type",
                "candidate_source",
            ]
        )
    frame = snapshots.copy()
    frame["symbol"] = frame["基金代码"].map(symbol_for_etf_code)
    frame["display_name"] = frame.get("基金简称")
    frame["reported_fund_type"] = frame.get("ETF类型")
    frame["candidate_source"] = frame.get("candidate_source", "sse-history")
    return frame[
        ["symbol", "display_name", "reported_fund_type", "candidate_source"]
    ].drop_duplicates("symbol", keep="last")


def normalize_cninfo_terminated_etfs(announcements: pd.DataFrame) -> pd.DataFrame:
    """从巨潮基金终止上市公告恢复沪深历史 ETF 候选。"""

    columns = [
        "symbol",
        "display_name",
        "termination_announcement_date",
        "termination_announcement_url",
        "candidate_source",
    ]
    if announcements is None or announcements.empty:
        return pd.DataFrame(columns=columns)
    frame = announcements.copy()
    codes = (
        frame["代码"]
        .astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )
    titles = (
        frame.get("公告标题", pd.Series(index=frame.index, dtype="object"))
        .astype("string")
        .str.replace(r"<[^>]+>", "", regex=True)
    )
    valid = codes.str.fullmatch(
        r"(?:15[89]\d{3}|5[1268]\d{4})", na=False
    ) & titles.str.contains("终止上市", na=False)
    frame = frame.loc[valid].copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame["symbol"] = codes.loc[valid].map(symbol_for_etf_code)
    frame["display_name"] = (
        frame.get("简称", pd.Series(index=frame.index, dtype="object"))
        .astype("string")
        .str.replace(r"<[^>]+>", "", regex=True)
    )
    frame["termination_announcement_date"] = pd.to_datetime(
        frame.get("公告时间"), errors="coerce"
    ).dt.normalize()
    frame["termination_announcement_url"] = frame.get("公告链接")
    frame["candidate_source"] = "cninfo-termination"
    frame = frame.sort_values(
        ["symbol", "termination_announcement_date"], na_position="first"
    )
    return frame[columns].drop_duplicates("symbol", keep="last").reset_index(
        drop=True
    )


def build_etf_candidates(
    current: pd.DataFrame,
    fund_names: pd.DataFrame,
    historical_exchange_snapshots: pd.DataFrame,
    termination_announcements: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """建立候选池，保留当前、基金字典和历史交易所快照的来源证据。"""

    names = _normalize_fund_name_candidates(fund_names)
    history = _normalize_historical_candidates(historical_exchange_snapshots)
    terminated = normalize_cninfo_terminated_etfs(termination_announcements)
    symbols = sorted(
        set(current.get("symbol", pd.Series(dtype=str)).dropna())
        | set(names["symbol"])
        | set(history["symbol"])
        | set(terminated["symbol"])
    )
    current_by = current.set_index("symbol") if not current.empty else pd.DataFrame()
    names_by = names.set_index("symbol") if not names.empty else pd.DataFrame()
    history_by = history.set_index("symbol") if not history.empty else pd.DataFrame()
    terminated_by = (
        terminated.set_index("symbol") if not terminated.empty else pd.DataFrame()
    )
    records = []
    for symbol in symbols:
        current_row = (
            current_by.loc[symbol] if symbol in current_by.index else pd.Series(dtype=object)
        )
        name_row = (
            names_by.loc[symbol] if symbol in names_by.index else pd.Series(dtype=object)
        )
        history_row = (
            history_by.loc[symbol]
            if symbol in history_by.index
            else pd.Series(dtype=object)
        )
        terminated_row = (
            terminated_by.loc[symbol]
            if symbol in terminated_by.index
            else pd.Series(dtype=object)
        )
        sources = []
        if symbol in current_by.index and bool(current_row.get("in_sina", False)):
            sources.append("sina-current")
        if symbol in current_by.index and bool(current_row.get("in_ths", False)):
            sources.append("ths-current")
        if symbol in names_by.index:
            sources.append("eastmoney-fund-name")
        if symbol in history_by.index:
            sources.extend(
                str(history_row.get("candidate_source", "sse-history")).split("|")
            )
        if symbol in terminated_by.index:
            sources.append("cninfo-termination")
        records.append(
            {
                "symbol": symbol,
                "code": symbol[2:],
                "exchange": "XSHG" if symbol.startswith("SH") else "XSHE",
                "display_name": _first_non_empty(
                    [
                        current_row.get("display_name"),
                        name_row.get("display_name"),
                        history_row.get("display_name"),
                        terminated_row.get("display_name"),
                    ]
                ),
                "reported_fund_type": _first_non_empty(
                    [
                        name_row.get("reported_fund_type"),
                        current_row.get("reported_fund_type"),
                        history_row.get("reported_fund_type"),
                    ]
                ),
                "expected_active": bool(current_row.get("expected_active", False)),
                "in_sina": bool(current_row.get("in_sina", False)),
                "in_ths": bool(current_row.get("in_ths", False)),
                "seen_in_historical_exchange_snapshot": symbol in history_by.index,
                "seen_in_termination_announcement": symbol in terminated_by.index,
                "termination_announcement_date": terminated_row.get(
                    "termination_announcement_date", pd.NaT
                ),
                "candidate_sources": "|".join(dict.fromkeys(sources)),
            }
        )
    return pd.DataFrame(records).sort_values("symbol").reset_index(drop=True)


def classify_etf(fund_type: object, display_name: object, tracking_target: object) -> str:
    text_type = "" if pd.isna(fund_type) else str(fund_type)
    text = " ".join(
        "" if pd.isna(item) else str(item) for item in (display_name, tracking_target)
    )
    if "货币" in text_type or re.search(r"货币|日利|添益|保证金", text):
        return "money"
    if "固收" in text_type or "债券" in text_type or re.search(r"国债|政金债|信用债|债ETF", text):
        return "bond"
    if "海外" in text_type or _CROSS_BORDER_PATTERN.search(text):
        return "cross_border"
    if "其他" in text_type or _COMMODITY_PATTERN.search(text):
        return "commodity"
    if _BROAD_EQUITY_PATTERN.search(text):
        return "broad_equity"
    if "股票" in text_type or ETF_NAME_PATTERN.search(text):
        return "sector_equity"
    return "other"


def _profile_frame(profiles: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "fund_full_name",
        "inception_date",
        "tracking_target",
        "profile_status",
    ]
    if profiles is None or profiles.empty:
        return pd.DataFrame(columns=columns)
    frame = profiles.copy().drop_duplicates("symbol", keep="last").set_index("symbol")
    for column in columns:
        if column not in frame:
            frame[column] = None
    return frame


def _bar_status_frame(bar_status: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "status",
        "first_trade_date",
        "last_trade_date",
        "row_count",
        "error",
    ]
    if bar_status is None or bar_status.empty:
        return pd.DataFrame(columns=columns)
    frame = bar_status.copy().drop_duplicates("symbol", keep="last").set_index("symbol")
    for column in columns:
        if column not in frame:
            frame[column] = None
    return frame


def build_etf_master(
    candidates: pd.DataFrame,
    profiles: pd.DataFrame | None,
    bar_status: pd.DataFrame | None,
    *,
    source_end: pd.Timestamp,
) -> pd.DataFrame:
    """把逐只下载事实合并为可审计 ETF 主表。"""

    source_end = pd.Timestamp(source_end).normalize()
    profiles_by = _profile_frame(profiles)
    bars_by = _bar_status_frame(bar_status)
    records = []
    for row in candidates.itertuples(index=False):
        payload = row._asdict()
        symbol = payload["symbol"]
        profile = (
            profiles_by.loc[symbol]
            if symbol in profiles_by.index
            else pd.Series(dtype=object)
        )
        bars = (
            bars_by.loc[symbol] if symbol in bars_by.index else pd.Series(dtype=object)
        )
        first_trade = pd.to_datetime(bars.get("first_trade_date"), errors="coerce")
        last_trade = pd.to_datetime(bars.get("last_trade_date"), errors="coerce")
        inception = pd.to_datetime(profile.get("inception_date"), errors="coerce")
        expected_active = bool(payload.get("expected_active", False))
        status = str(bars.get("status") or "not_attempted")
        if status == "success":
            lifecycle = (
                "active"
                if expected_active and pd.notna(last_trade)
                else "delisted"
            )
        elif pd.notna(inception) and inception > source_end:
            lifecycle = "prelisting"
        elif status == "empty" and expected_active:
            lifecycle = "active_no_history"
        elif status == "empty" and not expected_active:
            lifecycle = "unverified_candidate"
        elif status in {"failed", "empty"}:
            lifecycle = "download_failed"
        else:
            lifecycle = "not_attempted"
        active = lifecycle == "active"
        grade = (
            QualityGrade.B.value
            if status == "success" and pd.notna(first_trade) and pd.notna(last_trade)
            else QualityGrade.C.value
        )
        records.append(
            {
                "symbol": symbol,
                "code": payload.get("code", symbol[2:]),
                "exchange": payload.get(
                    "exchange", "XSHG" if symbol.startswith("SH") else "XSHE"
                ),
                "display_name": payload.get("display_name"),
                "fund_full_name": profile.get("fund_full_name"),
                "reported_fund_type": payload.get("reported_fund_type"),
                "etf_category": classify_etf(
                    payload.get("reported_fund_type"),
                    payload.get("display_name"),
                    profile.get("tracking_target"),
                ),
                "tracking_target": profile.get("tracking_target"),
                "inception_date": inception,
                "listing_date": first_trade,
                "delisting_date": pd.NaT if active else last_trade,
                "first_trade_date": first_trade,
                "last_trade_date": last_trade,
                "expected_active": expected_active,
                "active_at_source_end": active,
                "lifecycle_status": lifecycle,
                "in_sina": bool(payload.get("in_sina", False)),
                "in_ths": bool(payload.get("in_ths", False)),
                "seen_in_historical_exchange_snapshot": bool(
                    payload.get("seen_in_historical_exchange_snapshot", False)
                ),
                "seen_in_termination_announcement": bool(
                    payload.get("seen_in_termination_announcement", False)
                ),
                "termination_announcement_date": pd.to_datetime(
                    payload.get("termination_announcement_date"), errors="coerce"
                ),
                "candidate_sources": payload.get("candidate_sources", ""),
                "bar_status": status,
                "bar_row_count": int(bars.get("row_count") or 0),
                "bar_error": bars.get("error"),
                "profile_status": profile.get("profile_status", "not_attempted"),
                "quality_grade": grade,
                "source": "|".join(
                    dict.fromkeys(
                        filter(
                            None,
                            [
                                payload.get("candidate_sources"),
                                "sina",
                                "ths",
                                "eastmoney",
                            ],
                        )
                    )
                ),
            }
        )
    result = pd.DataFrame(records, columns=ETF_MASTER_COLUMNS)
    validate_etf_master(result)
    return result.sort_values("symbol").reset_index(drop=True)


def validate_etf_master(frame: pd.DataFrame) -> None:
    missing = set(ETF_MASTER_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"ETF master is missing columns: {sorted(missing)}")
    if frame["symbol"].isna().any() or frame["symbol"].duplicated().any():
        raise ValueError("ETF master symbols must be present and unique")
    if not frame["symbol"].astype(str).str.fullmatch(r"(SH|SZ)\d{6}").all():
        raise ValueError("ETF master contains invalid symbols")
    if (
        pd.to_datetime(frame["first_trade_date"], errors="coerce")
        > pd.to_datetime(frame["last_trade_date"], errors="coerce")
    ).any():
        raise ValueError("ETF master contains inverted trade dates")
    invalid = set(frame["quality_grade"]).difference(item.value for item in QualityGrade)
    if invalid:
        raise ValueError(f"ETF master contains invalid quality grades: {invalid}")


def summarize_etf_coverage(master: pd.DataFrame) -> dict:
    expected = master["expected_active"].fillna(False).astype(bool)
    success = master["bar_status"].eq("success")
    current_expected = int(expected.sum())
    current_success = int((expected & success).sum())
    historical = ~expected & (
        master["first_trade_date"].notna()
        | master["lifecycle_status"].isin(["delisted", "unverified_candidate"])
    )
    return {
        "candidate_count": int(len(master)),
        "current_expected": current_expected,
        "current_with_daily_history": current_success,
        "current_coverage_ratio": (
            current_success / current_expected if current_expected else 0.0
        ),
        "historical_or_delisted_candidates": int(historical.sum()),
        "bar_status_counts": {
            str(key): int(value)
            for key, value in master["bar_status"].value_counts(dropna=False).items()
        },
        "lifecycle_status_counts": {
            str(key): int(value)
            for key, value in master["lifecycle_status"]
            .value_counts(dropna=False)
            .items()
        },
        "category_counts": {
            str(key): int(value)
            for key, value in master["etf_category"].value_counts(dropna=False).items()
        },
        "historical_source_counts": {
            "exchange_snapshot": int(
                master.get(
                    "seen_in_historical_exchange_snapshot",
                    pd.Series(False, index=master.index),
                )
                .fillna(False)
                .astype(bool)
                .sum()
            ),
            "cninfo_termination": int(
                master.get(
                    "seen_in_termination_announcement",
                    pd.Series(False, index=master.index),
                )
                .fillna(False)
                .astype(bool)
                .sum()
            ),
        },
    }


def etf_security_supplemental(
    etf_master: pd.DataFrame,
    *,
    source_end: pd.Timestamp,
) -> pd.DataFrame:
    """把有可验证生命周期的 ETF 投影到统一证券主表。"""

    source_end = pd.Timestamp(source_end).normalize()
    eligible = etf_master[
        etf_master["bar_status"].eq("success")
        | etf_master["lifecycle_status"].eq("active_no_history")
    ].copy()
    records = []
    for row in eligible.itertuples(index=False):
        active = row.lifecycle_status in {"active", "active_no_history"}
        listing_date = (
            row.first_trade_date
            if pd.notna(row.first_trade_date)
            else row.inception_date
        )
        if pd.isna(listing_date):
            continue
        end_date = (
            source_end
            if active
            else pd.Timestamp(row.last_trade_date).normalize()
        )
        records.append(
            {
                "symbol": row.symbol,
                "exchange": row.exchange,
                "asset_type": "etf",
                "board": "etf",
                "start_date": pd.Timestamp(listing_date).normalize(),
                "end_date": end_date,
                "listing_date": pd.Timestamp(listing_date).normalize(),
                "delisting_date": pd.NaT if active else end_date,
                "active_at_source_end": active,
                "canonical_symbol": row.symbol,
                "lifecycle_status": row.lifecycle_status,
                "lifecycle_quality": QualityGrade.B.value,
                "lifecycle_source": row.source,
                "display_name": row.display_name,
                "quality_grade": QualityGrade.B.value,
                "source": row.source,
            }
        )
    result = pd.DataFrame(records, columns=SECURITY_MASTER_COLUMNS)
    validate_security_master(result)
    return result.sort_values("symbol").reset_index(drop=True)
