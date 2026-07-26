"""下载冻结 h18 候选涉及证券的巨潮历史行业变更记录。"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from akshare.stock import stock_industry_cninfo as cninfo_module


COLUMN_MAP = {
    "变更日期": "change_date",
    "分类标准编码": "classification_standard_code",
    "分类标准": "classification_standard",
    "行业编码": "industry_code",
    "行业门类": "industry_section",
    "行业次类": "industry_subsection",
    "行业大类": "industry_major",
    "行业中类": "industry_middle",
}


def normalize_industry_rows(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    columns = [column for column in COLUMN_MAP if column in frame.columns]
    result = frame[columns].rename(columns=COLUMN_MAP).copy()
    for column in COLUMN_MAP.values():
        if column not in result:
            result[column] = pd.NA
    result.insert(0, "symbol", symbol)
    result["change_date"] = pd.to_datetime(result["change_date"], errors="coerce").dt.normalize()
    result = result.dropna(subset=["change_date", "classification_standard"])
    return result[["symbol", *COLUMN_MAP.values()]].reset_index(drop=True)


RAW_COLUMN_MAP = {
    "VARYDATE": "变更日期",
    "F001V": "分类标准编码",
    "F002V": "分类标准",
    "F003V": "行业编码",
    "F004V": "行业门类",
    "F005V": "行业次类",
    "F006V": "行业大类",
    "F007V": "行业中类",
}


def generate_accept_enckey():
    js_code = cninfo_module.py_mini_racer.MiniRacer()
    js_code.eval(cninfo_module._get_file_content_ths("cninfo.js"))
    return js_code.call("getResCode1")


def download_symbol(symbol: str, accept_enckey: str, retries=3):
    code = symbol[2:]
    error = None
    for attempt in range(retries):
        try:
            response = requests.post(
                "https://webapi.cninfo.com.cn/api/stock/p_stock2110",
                params={"scode": code, "sdate": "1990-01-01", "edate": "2021-12-31"},
                headers={
                    "Accept": "*/*",
                    "Accept-Enckey": accept_enckey,
                    "Origin": "https://webapi.cninfo.com.cn",
                    "Referer": "https://webapi.cninfo.com.cn/",
                    "User-Agent": "Mozilla/5.0 Chrome/120.0",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            frame = pd.DataFrame(payload.get("records") or []).rename(
                columns=RAW_COLUMN_MAP
            )
            return normalize_industry_rows(frame, symbol), None
        except Exception as exc:  # network response shapes are not stable
            error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5 * (attempt + 1))
    return pd.DataFrame(), error


def load_symbols(selection_paths):
    symbols = set()
    for path in selection_paths:
        frame = pd.read_csv(path, usecols=["model", "symbol"])
        symbols.update(frame.loc[frame["model"].eq("quality-growth-momentum"), "symbol"])
    return sorted(symbols)


def parse_args():
    base = Path(__file__).resolve().parent / "results"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selections",
        nargs="+",
        type=Path,
        default=[
            base / "2026-07-27__selection-alpha__quality-backward-confirmation-v4" / "raw" / "selections.csv",
            base / "2026-07-27__selection-alpha__quality-acceleration-v3" / "raw" / "selections.csv",
        ],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil-rebuild/cninfo-industry-history.parquet"),
    )
    parser.add_argument("--workers", type=int, default=6)
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = load_symbols(args.selections)
    frames = []
    failures = {}
    completed = 0
    accept_enckey = generate_accept_enckey()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(download_symbol, symbol, accept_enckey): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            frame, error = future.result()
            if not frame.empty:
                frames.append(frame)
            if error:
                failures[symbol] = error
            completed += 1
            if completed == 1 or completed % 100 == 0 or completed == len(symbols):
                print(f"历史行业 {completed}/{len(symbols)}，失败 {len(failures)}", flush=True)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(args.output, index=False)
    audit_path = args.output.with_suffix(".audit.json")
    audit_path.write_text(
        json.dumps(
            {
                "requested_symbols": len(symbols),
                "covered_symbols": int(result["symbol"].nunique()) if not result.empty else 0,
                "rows": len(result),
                "failures": failures,
                "source": "CNInfo p_stock2110 via AkShare",
                "query_end_date": "2021-12-31",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"行业历史写入 {args.output}，{len(result)} 行", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
