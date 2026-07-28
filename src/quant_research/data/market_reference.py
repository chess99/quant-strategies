"""DoltHub 多源市场状态与真实涨跌停价适配。"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .contracts import QualityGrade


PRICE_LIMIT_COLUMNS = [
    "symbol",
    "trade_date",
    "previous_raw_close",
    "high_limit",
    "low_limit",
    "is_st",
    "st_quality",
    "limit_quality",
    "st_source",
    "limit_source",
]

OFFICIAL_STATUS_COLUMNS = [
    "symbol",
    "trade_date",
    "paused",
    "is_st",
    "status_quality",
    "st_quality",
    "status_source",
    "st_source",
]

ST_NAME_EVENT_COLUMNS = [
    "symbol",
    "effective_from",
    "display_name",
    "is_st",
    "st_quality",
    "st_source",
]

RISK_WARNING_EVENT_COLUMNS = [
    "symbol",
    "effective_from",
    "is_st",
    "st_quality",
    "st_source",
    "evidence_title",
    "evidence_art_code",
]

DELISTING_EVENT_COLUMNS = [
    "symbol",
    "effective_from",
    "is_delisting",
    "quality_grade",
    "source",
    "evidence_title",
    "evidence_art_code",
]


def _round_half_up(values) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    return np.floor(array * 100.0 + 0.5) / 100.0


def _matches_band(
    previous_close: pd.Series,
    upper: pd.Series,
    lower: pd.Series,
    rate: float,
) -> pd.Series:
    expected_upper = _round_half_up(previous_close * (1.0 + rate))
    expected_lower = _round_half_up(previous_close * (1.0 - rate))
    return (
        np.isclose(upper, expected_upper, atol=0.011, rtol=0.0)
        & np.isclose(lower, expected_lower, atol=0.011, rtol=0.0)
    )


def infer_st_from_price_limits(frame: pd.DataFrame) -> pd.Series:
    """从真实上下限反推 ST；注册制板块同限价时保持未知。"""

    previous = pd.to_numeric(frame["previous_raw_close"], errors="coerce")
    upper = pd.to_numeric(frame["high_limit"], errors="coerce")
    lower = pd.to_numeric(frame["low_limit"], errors="coerce")
    symbols = frame["symbol"].astype(str).str.upper()
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    is_star = symbols.str.match(r"SH68[89]\d{3}")
    is_chinext = symbols.str.match(r"SZ30[01]\d{3}")
    is_beijing = symbols.str.startswith("BJ")
    main_board = ~(is_star | is_chinext | is_beijing)
    legacy_chinext = is_chinext & dates.lt(pd.Timestamp("2020-08-24"))
    st_distinguishable = main_board | legacy_chinext
    valid = previous.gt(0.0) & upper.notna() & lower.notna()
    st = valid & st_distinguishable & _matches_band(previous, upper, lower, 0.05)
    recognized_non_st = valid & st_distinguishable & (
        _matches_band(previous, upper, lower, 0.10)
        | (
            np.isclose(
                upper,
                _round_half_up(previous * 1.44),
                atol=0.011,
                rtol=0.0,
            )
            & np.isclose(
                lower,
                _round_half_up(previous * 0.64),
                atol=0.011,
                rtol=0.0,
            )
        )
    )
    result = pd.Series(pd.array([pd.NA] * len(frame), dtype="boolean"), index=frame.index)
    result.loc[st] = True
    result.loc[recognized_non_st] = False
    return result


def normalize_dolthub_price_limits(raw: pd.DataFrame) -> pd.DataFrame:
    """规范化 ``final_a_stock_limit`` 的多源校正结果。"""

    aliases = {
        "tradedate": "trade_date",
        "pre_close": "previous_raw_close",
        "up_limit": "high_limit",
        "down_limit": "low_limit",
    }
    frame = raw.rename(columns=aliases).copy()
    required = {
        "symbol",
        "trade_date",
        "previous_raw_close",
        "high_limit",
        "low_limit",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"price-limit response is missing columns: {sorted(missing)}")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="coerce"
    ).dt.normalize()
    for column in ("previous_raw_close", "high_limit", "low_limit"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(
        subset=[
            "symbol",
            "trade_date",
            "previous_raw_close",
            "high_limit",
            "low_limit",
        ]
    )
    frame = frame[
        frame["previous_raw_close"].gt(0.0)
        & frame["high_limit"].gt(frame["low_limit"])
    ]
    frame = frame.sort_values(["symbol", "trade_date"]).drop_duplicates(
        ["symbol", "trade_date"], keep="last"
    )
    frame["is_st"] = infer_st_from_price_limits(frame)
    recognized = frame["is_st"].notna()
    frame["st_quality"] = np.where(
        recognized, QualityGrade.B.value, QualityGrade.C.value
    )
    frame["limit_quality"] = QualityGrade.B.value
    frame["st_source"] = np.where(
        recognized, "dolthub/final-a-stock-limit-inferred", None
    )
    frame["limit_source"] = "dolthub/final-a-stock-limit"
    result = frame[PRICE_LIMIT_COLUMNS].reset_index(drop=True)
    validate_price_limits(result)
    return result


def validate_price_limits(frame: pd.DataFrame) -> None:
    missing = set(PRICE_LIMIT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"price-limit data is missing columns: {sorted(missing)}")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ValueError("price-limit data contains duplicate symbol/date rows")
    if (frame["high_limit"] <= frame["low_limit"]).any():
        raise ValueError("price-limit data contains inverted limits")


def normalize_dolthub_baostock_status(raw: pd.DataFrame) -> pd.DataFrame:
    """规范化 Dolt 快照中的 Baostock 逐日交易状态与显式 ST。"""

    frame = raw.rename(columns={"tradedate": "trade_date"}).copy()
    required = {"symbol", "trade_date", "tradestatus", "is_st"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Baostock status is missing columns: {sorted(missing)}")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="coerce"
    ).dt.normalize()
    trade_status = pd.to_numeric(frame["tradestatus"], errors="coerce")
    st = pd.to_numeric(frame["is_st"], errors="coerce")
    frame["paused"] = pd.array(
        np.where(trade_status.notna(), trade_status.eq(0), pd.NA),
        dtype="boolean",
    )
    frame["is_st"] = pd.array(
        np.where(st.notna(), st.eq(1), pd.NA),
        dtype="boolean",
    )
    frame = frame.dropna(subset=["symbol", "trade_date"]).sort_values(
        ["symbol", "trade_date"]
    )
    frame = frame.drop_duplicates(["symbol", "trade_date"], keep="last")
    frame["status_quality"] = np.where(
        frame["paused"].notna(), QualityGrade.B.value, QualityGrade.C.value
    )
    frame["st_quality"] = np.where(
        frame["is_st"].notna(), QualityGrade.B.value, QualityGrade.C.value
    )
    frame["status_source"] = "dolthub/baostock-tradestatus"
    frame["st_source"] = "dolthub/baostock-is-st"
    return frame[OFFICIAL_STATUS_COLUMNS].reset_index(drop=True)


def _name_is_st(value) -> bool:
    return "ST" in str(value).upper()


def _risk_name_from_eastmoney_title(title: str, stock_code: str) -> str | None:
    parts = re.split(r"[:：]", str(title).strip(), maxsplit=2)
    if not parts:
        return None
    candidate = parts[0].strip()
    if candidate == str(stock_code).zfill(6):
        if len(parts) < 2:
            return None
        candidate = parts[1].strip()
        for marker in ("股票", "关于", "风险", "20"):
            position = candidate.find(marker, 2)
            if position >= 0:
                candidate = candidate[:position].strip()
    upper = candidate.upper()
    if not (
        upper.startswith("*ST")
        or upper.startswith("ST")
        or candidate.startswith("退市")
        or candidate.endswith("退")
    ):
        return None
    if len(candidate) > 16 or any(char.isspace() for char in candidate):
        return None
    return candidate


def normalize_eastmoney_title_name_events(
    notices: pd.DataFrame,
    security_master: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """从发行人公告标题前缀恢复上交所/北交所历史风险简称。"""

    required = {"stock_code", "notice_date", "title", "art_code"}
    missing = required.difference(notices.columns)
    if missing:
        raise ValueError(f"risk notices are missing columns: {sorted(missing)}")
    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    master = security_master[security_master["asset_type"].eq("stock")].copy()
    records = []
    for notice in notices.to_dict("records"):
        code = str(notice["stock_code"]).zfill(6)
        display_name = _risk_name_from_eastmoney_title(notice["title"], code)
        if display_name is None:
            continue
        notice_date = pd.Timestamp(notice["notice_date"]).normalize()
        position = calendar.searchsorted(notice_date, side="right")
        if position >= len(calendar):
            continue
        candidates = master[master["symbol"].astype(str).str[2:].eq(code)]
        candidates = candidates[~candidates["symbol"].astype(str).str.startswith("SZ")]
        if {"start_date", "end_date"}.issubset(candidates.columns):
            candidates = candidates[
                pd.to_datetime(candidates["start_date"]).le(notice_date)
                & pd.to_datetime(candidates["end_date"]).ge(notice_date)
            ]
        for symbol in candidates["symbol"].astype(str):
            records.append(
                {
                    "symbol": symbol,
                    "effective_from": calendar[position],
                    "display_name": display_name,
                    "is_st": _name_is_st(display_name),
                    "st_quality": QualityGrade.B.value,
                    "st_source": "eastmoney/issuer-title-name-prefix",
                }
            )
    if not records:
        return pd.DataFrame(columns=ST_NAME_EVENT_COLUMNS)
    frame = pd.DataFrame(records).sort_values(["symbol", "effective_from"])
    frame = frame.drop_duplicates(["symbol", "effective_from"], keep="last")
    frame["is_st"] = pd.array(frame["is_st"], dtype="boolean")
    return frame[ST_NAME_EVENT_COLUMNS].reset_index(drop=True)


def normalize_delisting_events(
    notices: pd.DataFrame,
    security_master: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """把退市整理期公告转换为下一交易日可见的点时事件。"""

    required = {"stock_code", "notice_date", "short_name", "title", "art_code"}
    missing = required.difference(notices.columns)
    if missing:
        raise ValueError(f"delisting notices are missing columns: {sorted(missing)}")
    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    master = security_master[security_master["asset_type"].eq("stock")].copy()
    if "start_date" in master:
        master["start_date"] = pd.to_datetime(master["start_date"]).dt.normalize()
    if "end_date" in master:
        master["end_date"] = pd.to_datetime(master["end_date"]).dt.normalize()
    records = []
    for notice in notices.to_dict("records"):
        short_name = "" if pd.isna(notice["short_name"]) else str(notice["short_name"])
        title = "" if pd.isna(notice["title"]) else str(notice["title"])
        if "退" not in short_name and "进入退市整理期" not in title:
            continue
        notice_date = pd.Timestamp(notice["notice_date"]).normalize()
        position = calendar.searchsorted(notice_date, side="right")
        if position >= len(calendar):
            continue
        effective_from = calendar[position]
        code = str(notice["stock_code"]).zfill(6)
        candidates = master[master["symbol"].astype(str).str[2:].eq(code)]
        if {"start_date", "end_date"}.issubset(candidates.columns):
            candidates = candidates[
                candidates["start_date"].le(notice_date)
                & candidates["end_date"].ge(notice_date)
            ]
        for symbol in candidates["symbol"].astype(str):
            records.append(
                {
                    "symbol": symbol,
                    "effective_from": effective_from,
                    "is_delisting": True,
                    "quality_grade": QualityGrade.B.value,
                    "source": "eastmoney/issuer-delisting-announcement",
                    "evidence_title": title,
                    "evidence_art_code": str(notice["art_code"]),
                }
            )
    if not records:
        return pd.DataFrame(columns=DELISTING_EVENT_COLUMNS)
    frame = pd.DataFrame(records).sort_values(
        ["symbol", "effective_from", "evidence_art_code"]
    )
    frame = frame.drop_duplicates("symbol", keep="first")
    return frame[DELISTING_EVENT_COLUMNS].reset_index(drop=True)


def derive_delisting_events_from_market_history(
    security_master: pd.DataFrame,
    market_history: pd.DataFrame,
) -> pd.DataFrame:
    """按退市整理期交易日规则，从实际交易区间恢复简称带退的生效日。"""

    required_master = {"symbol", "asset_type", "display_name", "end_date"}
    missing_master = required_master.difference(security_master.columns)
    if missing_master:
        raise ValueError(
            f"security master fields are missing: {sorted(missing_master)}"
        )
    required_history = {"symbol", "trade_date", "paused", "raw_close"}
    missing_history = required_history.difference(market_history.columns)
    if missing_history:
        raise ValueError(
            f"market history fields are missing: {sorted(missing_history)}"
        )
    master = security_master[
        security_master["asset_type"].eq("stock")
        & security_master["display_name"].fillna("").str.contains("退")
    ].copy()
    master["end_date"] = pd.to_datetime(master["end_date"]).dt.normalize()
    history = market_history.copy()
    history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.normalize()
    history = history[
        history["paused"].eq(False) & pd.to_numeric(history["raw_close"], errors="coerce").notna()
    ]
    records = []
    for row in master.itertuples(index=False):
        sessions = (
            history[
                history["symbol"].eq(row.symbol)
                & history["trade_date"].le(row.end_date)
            ]["trade_date"]
            .drop_duplicates()
            .sort_values()
        )
        period_sessions = 30 if row.end_date <= pd.Timestamp("2020-12-31") else 15
        if len(sessions) < period_sessions:
            continue
        effective_from = sessions.iloc[-period_sessions]
        records.append(
            {
                "symbol": str(row.symbol),
                "effective_from": effective_from,
                "is_delisting": True,
                "quality_grade": QualityGrade.B.value,
                "source": "exchange-rule/derived-delisting-trading-period",
                "evidence_title": f"按退市整理期 {period_sessions} 个交易日规则恢复",
                "evidence_art_code": None,
            }
        )
    if not records:
        return pd.DataFrame(columns=DELISTING_EVENT_COLUMNS)
    return (
        pd.DataFrame(records)[DELISTING_EVENT_COLUMNS]
        .sort_values(["symbol", "effective_from"])
        .reset_index(drop=True)
    )


def normalize_szse_st_name_events(
    raw: pd.DataFrame,
    security_master: pd.DataFrame,
) -> pd.DataFrame:
    """把深交所官方简称变更表转换成可按观察日回放的 ST 事件。"""

    required = {"变更日期", "证券代码", "变更前简称", "变更后简称"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"SZSE name changes are missing columns: {sorted(missing)}")
    changes = raw[list(required)].copy()
    changes["symbol"] = (
        "SZ" + changes["证券代码"].astype(str).str.extract(r"(\d+)")[0].str.zfill(6)
    )
    changes["effective_from"] = pd.to_datetime(
        changes["变更日期"], errors="coerce"
    ).dt.normalize()
    changes = changes.dropna(subset=["symbol", "effective_from"]).sort_values(
        ["symbol", "effective_from"]
    )
    master = security_master[
        (security_master["asset_type"] == "stock")
        & (security_master["exchange"] == "XSHE")
    ].copy()
    records = []
    for row in master.itertuples(index=False):
        symbol = str(row.symbol)
        group = changes[changes["symbol"] == symbol]
        listing_date = pd.Timestamp(row.listing_date).normalize()
        if not group.empty:
            baseline_name = group.iloc[0]["变更前简称"]
        else:
            baseline_name = row.display_name
        if pd.notna(baseline_name):
            records.append(
                {
                    "symbol": symbol,
                    "effective_from": listing_date,
                    "display_name": str(baseline_name),
                }
            )
        for change in group.to_dict("records"):
            if change["effective_from"] < listing_date:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "effective_from": change["effective_from"],
                    "display_name": str(change["变更后简称"]),
                }
            )
    frame = pd.DataFrame(records)
    frame = frame.sort_values(["symbol", "effective_from"]).drop_duplicates(
        ["symbol", "effective_from"], keep="last"
    )
    frame["is_st"] = pd.array(frame["display_name"].map(_name_is_st), dtype="boolean")
    frame["st_quality"] = QualityGrade.A.value
    frame["st_source"] = "szse/official-name-change"
    return frame[ST_NAME_EVENT_COLUMNS].reset_index(drop=True)


def apply_st_name_events(
    state: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.DataFrame:
    """按有效日期把官方简称中的 ST 状态覆盖到逐日市场状态。"""

    if events is None or events.empty:
        return state
    symbols = set(state["symbol"].astype(str))
    relevant = events[events["symbol"].isin(symbols)].copy()
    if relevant.empty:
        return state
    pieces = []
    for symbol, group in state.groupby("symbol", sort=False):
        symbol_events = relevant[relevant["symbol"] == symbol].sort_values(
            "effective_from"
        )
        if symbol_events.empty:
            pieces.append(group)
            continue
        merged = pd.merge_asof(
            group.sort_values("trade_date"),
            symbol_events[
                ["effective_from", "is_st", "st_quality", "st_source"]
            ],
            left_on="trade_date",
            right_on="effective_from",
            direction="backward",
            suffixes=("", "_event"),
        )
        available = merged["is_st_event"].notna()
        merged.loc[available, "is_st"] = merged.loc[
            available, "is_st_event"
        ].astype(bool)
        merged.loc[available, "st_quality"] = merged.loc[
            available, "st_quality_event"
        ]
        merged.loc[available, "st_source"] = merged.loc[
            available, "st_source_event"
        ]
        pieces.append(merged[state.columns])
    result = pd.concat(pieces, ignore_index=True)
    result["is_st"] = pd.array(result["is_st"], dtype="boolean")
    return result


def classify_risk_warning_title(title: str) -> bool | None:
    """把发行人公告标题分类为实施/延续或撤销风险警示。"""

    text = str(title)
    if "申请撤销" in text or "可能" in text:
        return None
    revoke = "撤销" in text and "风险警示" in text
    continuing = (
        "继续实施其他风险警示" in text
        or "继续被实施其他风险警示" in text
        or "被实施其他风险警示" in text
    )
    implementation = (
        ("被实施" in text or "实施其他风险警示" in text)
        and "风险警示" in text
    )
    if revoke:
        return True if continuing else False
    if implementation:
        return True
    return None


def normalize_risk_warning_events(
    notices: pd.DataFrame,
    security_master: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    baselines: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """把发行人风险警示公告转换为下一交易日生效的 ST 事件。"""

    required = {"stock_code", "notice_date", "title", "art_code"}
    missing = required.difference(notices.columns)
    if missing:
        raise ValueError(f"risk notices are missing columns: {sorted(missing)}")
    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    master = security_master[security_master["asset_type"] == "stock"].copy()
    code_to_symbols: dict[str, list[str]] = {}
    for symbol in master["symbol"].astype(str):
        code_to_symbols.setdefault(symbol[2:], []).append(symbol)
    records = []
    baseline_dates: dict[str, pd.Timestamp] = {}
    if baselines is not None and not baselines.empty:
        for row in baselines.to_dict("records"):
            symbol = str(row["symbol"])
            effective_from = pd.Timestamp(row["effective_from"]).normalize()
            baseline_dates[symbol] = effective_from
            records.append(
                {
                    "symbol": symbol,
                    "effective_from": effective_from,
                    "is_st": bool(row["is_st"]),
                    "st_quality": str(row.get("st_quality", QualityGrade.B.value)),
                    "st_source": str(
                        row.get(
                            "st_source",
                            "dolthub/baostock-carry-forward-with-announcements",
                        )
                    ),
                    "evidence_title": row.get("evidence_title"),
                    "evidence_art_code": row.get("evidence_art_code"),
                    "_priority": 0,
                }
            )
    for notice in notices.to_dict("records"):
        is_st = classify_risk_warning_title(notice["title"])
        if is_st is None:
            continue
        notice_date = pd.Timestamp(notice["notice_date"]).normalize()
        position = calendar.searchsorted(notice_date, side="right")
        if position >= len(calendar):
            continue
        effective = calendar[position]
        for symbol in code_to_symbols.get(str(notice["stock_code"]).zfill(6), []):
            if symbol in baseline_dates and effective < baseline_dates[symbol]:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "effective_from": effective,
                    "is_st": is_st,
                    "st_quality": QualityGrade.B.value,
                    "st_source": "eastmoney/issuer-risk-warning-announcement",
                    "evidence_title": str(notice["title"]),
                    "evidence_art_code": str(notice["art_code"]),
                    "_priority": 1,
                }
            )
    if not records:
        raise ValueError("risk-warning notices produced no ST events")
    frame = pd.DataFrame(records)
    frame["is_st"] = pd.array(frame["is_st"], dtype="boolean")
    frame = frame.sort_values(
        ["symbol", "effective_from", "_priority"], kind="stable"
    ).drop_duplicates(
        ["symbol", "effective_from"], keep="last"
    )
    return frame[RISK_WARNING_EVENT_COLUMNS].reset_index(drop=True)
