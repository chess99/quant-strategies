"""Export point-in-time inputs for ETF flow dislocation research from JoinQuant/JQData.

Run in JoinQuant Research or a local authenticated JQData environment.
Outputs raw inputs only; no future-return labels or parameter selection happen here.
"""

from pathlib import Path
from datetime import datetime

import pandas as pd
from jqdata import *
from jqdata import finance


START = "2015-01-01"
END = "2026-07-31"
OUTPUT = Path("exports/etf-flow-dislocation-inputs")


def _date(value):
    return pd.Timestamp(value).date()


def _query_all(q, page_size=3000, max_pages=20000):
    runner = getattr(finance, "run_offset_query", None)
    if callable(runner):
        frame = runner(q)
        return pd.DataFrame() if frame is None else frame.reset_index(drop=True)

    rows = []
    offset = 0
    for _ in range(max_pages):
        page = finance.run_query(q.limit(page_size).offset(offset))
        if page is None or page.empty:
            break
        rows.append(page)
        if len(page) < page_size:
            break
        offset += page_size
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def export_master_and_tracking(start, end):
    master = get_all_securities(["etf"], date=None).reset_index()
    master = master.rename(columns={"index": "code"})
    master.to_csv(OUTPUT / "etf_master.csv", index=False)

    q = query(
        finance.FUND_INVEST_TARGET.code,
        finance.FUND_INVEST_TARGET.pub_date,
        finance.FUND_INVEST_TARGET.start_date,
        finance.FUND_INVEST_TARGET.end_date,
        finance.FUND_INVEST_TARGET.traced_index_name,
        finance.FUND_INVEST_TARGET.traced_index_code,
    ).filter(
        finance.FUND_INVEST_TARGET.pub_date <= _date(end),
        finance.FUND_INVEST_TARGET.start_date <= _date(end),
    )
    tracking = _query_all(q)
    tracking.to_csv(OUTPUT / "fund_invest_target.csv", index=False)
    return master, tracking


def candidate_codes(master, tracking, start, end):
    if tracking.empty:
        return []
    codes = set(tracking["code"].dropna().astype(str))
    master = master[master["code"].isin(codes)].copy()
    master["start_date"] = pd.to_datetime(master["start_date"], errors="coerce")
    master["end_date"] = pd.to_datetime(master["end_date"], errors="coerce")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    master = master[
        (master["start_date"] <= end_ts)
        & ((master["end_date"].isna()) | (master["end_date"] >= start_ts))
    ]
    return sorted(master["code"].astype(str).unique())


def export_prices(codes, start, end):
    pieces = []
    for offset in range(0, len(codes), 100):
        batch = codes[offset:offset + 100]
        frame = get_price(
            batch,
            start_date=start,
            end_date=end,
            frequency="daily",
            fields=["open", "close", "money"],
            panel=False,
            skip_paused=True,
            fq="pre",
        )
        if frame is None or frame.empty:
            continue
        if "code" not in frame.columns and len(batch) == 1:
            frame = frame.copy()
            frame["code"] = batch[0]
        pieces.append(frame)
    prices = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    prices.to_csv(OUTPUT / "etf_daily.csv", index=False)
    return prices


def export_shares(codes, start, end):
    pieces = []
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    for year in range(start_ts.year, end_ts.year + 1):
        left = max(start_ts, pd.Timestamp("%04d-01-01" % year))
        right = min(end_ts, pd.Timestamp("%04d-12-31" % year))
        for offset in range(0, len(codes), 60):
            batch = codes[offset:offset + 60]
            q = query(
                finance.FUND_SHARE_DAILY.code,
                finance.FUND_SHARE_DAILY.date,
                finance.FUND_SHARE_DAILY.shares,
            ).filter(
                finance.FUND_SHARE_DAILY.code.in_(batch),
                finance.FUND_SHARE_DAILY.date >= left.date(),
                finance.FUND_SHARE_DAILY.date <= right.date(),
            )
            frame = _query_all(q)
            if frame is not None and not frame.empty:
                pieces.append(frame)
    shares = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    shares.to_csv(OUTPUT / "fund_share_daily.csv", index=False)
    return shares


EXCLUDE_KEYWORDS = [
    "货币", "现金", "短融", "国债", "政金债", "信用债", "债券", "转债",
    "同业存单", "黄金", "白银", "原油", "商品",
    "纳指", "纳斯达克", "标普", "道琼斯", "日经", "德国", "法国", "沙特",
    "恒生", "港股", "香港", "中概", "H股", "海外", "中韩",
    "REIT", "Reit", "reit",
]


def annotate_tracking(panel, tracking):
    panel = panel.copy()
    panel["traced_index_code"] = None
    panel["traced_index_name"] = None
    panel["domestic_equity"] = False
    if tracking is None or tracking.empty:
        return panel

    records = tracking.copy()
    for column in ("pub_date", "start_date", "end_date"):
        records[column] = pd.to_datetime(records[column], errors="coerce")
    records["effective_date"] = records[["pub_date", "start_date"]].max(axis=1)
    records = records.sort_values(["code", "effective_date", "pub_date"])

    pieces = []
    for code, group in panel.groupby("code", sort=False):
        out = group.copy()
        history = records[records["code"] == code]
        if history.empty:
            pieces.append(out)
            continue
        for _, row in history.iterrows():
            effective = row["effective_date"]
            if pd.isna(effective):
                continue
            mask = out["date"] >= effective
            if pd.notna(row["end_date"]):
                mask = mask & (out["date"] <= row["end_date"])
            traced_name = "" if pd.isna(row["traced_index_name"]) else str(row["traced_index_name"])
            eligible = not any(keyword in traced_name for keyword in EXCLUDE_KEYWORDS)
            out.loc[mask, "traced_index_code"] = row["traced_index_code"]
            out.loc[mask, "traced_index_name"] = traced_name
            out.loc[mask, "domestic_equity"] = bool(eligible)
        pieces.append(out)
    return pd.concat(pieces, ignore_index=True)


def build_panel(prices, shares, tracking, master):
    if prices.empty or shares.empty:
        return pd.DataFrame()
    px = prices.copy()
    if "time" in px.columns:
        px = px.rename(columns={"time": "date"})
    px["date"] = pd.to_datetime(px["date"]).dt.normalize()
    sh = shares.copy()
    sh["date"] = pd.to_datetime(sh["date"]).dt.normalize()
    sh["shares"] = pd.to_numeric(sh["shares"], errors="coerce")
    panel = px.merge(sh[["date", "code", "shares"]], on=["date", "code"], how="left")
    lifecycle_columns = [column for column in ("code", "start_date", "end_date") if column in master.columns]
    if "code" in lifecycle_columns and len(lifecycle_columns) > 1:
        panel = panel.merge(master[lifecycle_columns], on="code", how="left")
    panel = panel.sort_values(["code", "date"])
    panel["shares"] = panel.groupby("code")["shares"].ffill(limit=10)
    panel = annotate_tracking(panel, tracking)
    panel.to_csv(OUTPUT / "panel.csv", index=False)
    return panel


def run(start=START, end=END):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    master, tracking = export_master_and_tracking(start, end)
    codes = candidate_codes(master, tracking, start, end)
    prices = export_prices(codes, start, end)
    shares = export_shares(codes, start, end)
    panel = build_panel(prices, shares, tracking, master)

    historical_end = pd.to_datetime(master.get("end_date"), errors="coerce")
    terminated = int((historical_end < pd.Timestamp(end)).sum()) if historical_end is not None else 0
    share_dates = pd.to_datetime(shares.get("date"), errors="coerce") if not shares.empty else pd.Series(dtype="datetime64[ns]")
    summary = pd.DataFrame(
        [{
            "generated_at": datetime.now().isoformat(),
            "start": start,
            "end": end,
            "candidate_codes": len(codes),
            "historically_terminated_etfs": terminated,
            "price_rows": len(prices),
            "share_rows": len(shares),
            "share_first_date": share_dates.min() if len(share_dates) else None,
            "share_last_date": share_dates.max() if len(share_dates) else None,
            "panel_rows": len(panel),
        }]
    )
    summary.to_csv(OUTPUT / "export_summary.csv", index=False)
    return OUTPUT


if __name__ == "__main__":
    run()
