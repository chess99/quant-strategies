"""下载欧奈尔本地回测所需的东方财富历史财务缓存。"""

import argparse
import gzip
import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = (
    ROOT
    / "strategies"
    / "joinquant"
    / "oneil-canslim-a-share"
    / "local_backtest.py"
)
DEFAULT_QLIB_DIR = Path("D:/code/_open-source/_data/qlib/cn_data")
DEFAULT_OUTPUT_DIR = Path("D:/code/_open-source/_data/oneil")
FINANCIAL_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
INDUSTRY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def load_engine():
    spec = importlib.util.spec_from_file_location("oneil_local_download", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载本地回测器：{ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request_json(url, params, retries=4, timeout=30):
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success", True):
                raise RuntimeError(str(payload))
            return payload
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt * 1.5)
    raise RuntimeError(f"请求失败：{last_error}")


def fetch_symbol(code):
    payload = request_json(
        FINANCIAL_URL,
        {
            "type": "RPT_F10_FINANCE_MAINFINADATA",
            "sty": "APP_F10_MAINFINADATA",
            "quoteColumns": "",
            "filter": f'(SECUCODE="{code}")',
            "p": "1",
            "ps": "200",
            "sr": "-1",
            "st": "REPORT_DATE",
            "source": "HSF10",
            "client": "PC",
        },
    )
    result = payload.get("result") or {}
    return result.get("data") or []


def load_or_fetch_symbol(symbol, raw_dir, engine):
    path = raw_dir / f"{symbol.lower()}.json.gz"
    if path.is_file():
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return symbol, json.load(handle), True
    rows = fetch_symbol(engine.eastmoney_code(symbol))
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False)
    return symbol, rows, False


def fetch_industries(report_date="2025-12-31"):
    import akshare as ak

    frame = ak.stock_yjbb_em(date=report_date.replace("-", ""))
    return frame.to_dict("records")


def normalize_financials(payloads, engine):
    rows = []
    for symbol, payload in payloads.items():
        for item in payload:
            rows.append(
                {
                    "symbol": symbol,
                    "report_date": item.get("REPORT_DATE"),
                    "notice_date": item.get("NOTICE_DATE"),
                    "update_date": item.get("UPDATE_DATE"),
                    "report_type": item.get("REPORT_TYPE"),
                    "basic_eps": item.get("EPSJB"),
                    "adjusted_profit": item.get("KCFJCXSYJLR"),
                    "parent_net_profit": item.get("PARENTNETPROFIT"),
                    "revenue": item.get("TOTALOPERATEREVE"),
                    "roe": item.get("ROEJQ"),
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("没有下载到任何财务记录")
    frame["update_date"] = pd.to_datetime(frame["update_date"], errors="coerce")
    frame = (
        frame.sort_values(["symbol", "report_date", "update_date"])
        .drop_duplicates(["symbol", "report_date"], keep="last")
        .drop(columns=["update_date"])
    )
    return engine.cumulative_to_single_quarter(frame)


def normalize_industries(rows, universe):
    universe = set(universe)
    normalized = []
    for item in rows:
        code = item.get("股票代码") or item.get("SECURITY_CODE")
        market = item.get("TRADE_MARKET_CODE")
        if not code:
            continue
        if str(code).startswith(("4", "8", "9")):
            suffix = "BJ"
        elif str(code).startswith(("5", "6", "9")):
            suffix = "SH"
        else:
            suffix = "SZ"
        if market in {"069001001", "069001002"}:
            suffix = "SH" if market == "069001001" else "SZ"
        symbol = f"{suffix}{str(code).zfill(6)}"
        if symbol not in universe:
            continue
        normalized.append(
            {
                "symbol": symbol,
                "name": item.get("股票简称")
                or item.get("SECURITY_NAME_ABBR")
                or "",
                "industry": item.get("所处行业")
                or item.get("INDUSTRY")
                or "未知行业",
            }
        )
    result = pd.DataFrame(normalized).drop_duplicates("symbol", keep="last")
    missing = sorted(universe - set(result["symbol"])) if not result.empty else sorted(universe)
    if missing:
        result = pd.concat(
            [
                result,
                pd.DataFrame(
                    [
                        {"symbol": symbol, "name": "", "industry": "未知行业"}
                        for symbol in missing
                    ]
                ),
            ],
            ignore_index=True,
        )
    return result.sort_values("symbol").reset_index(drop=True)


def build_parser():
    parser = argparse.ArgumentParser(
        description="下载欧奈尔本地回测所需的东方财富财务缓存"
    )
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    return parser


def main():
    args = build_parser().parse_args()
    engine = load_engine()
    common = engine.load_common_engine()
    data = common.QlibBinDataPortal(args.qlib_dir)
    universe = data.symbols_during(
        engine.DEFAULT_MARKETS, args.start_date, args.end_date
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    payloads = {}
    failures = {}
    cached = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                load_or_fetch_symbol, symbol, raw_dir, engine
            ): symbol
            for symbol in universe
        }
        for number, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                _, rows, was_cached = future.result()
                payloads[symbol] = rows
                cached += int(was_cached)
            except Exception as exc:
                failures[symbol] = str(exc)
            if number % 50 == 0 or number == len(futures):
                print(
                    f"财务下载：{number}/{len(futures)}，"
                    f"成功 {len(payloads)}，失败 {len(failures)}，缓存 {cached}",
                    flush=True,
                )

    financials = normalize_financials(payloads, engine)
    financials.to_parquet(args.output_dir / "financials.parquet", index=False)
    industry_rows = fetch_industries()
    industries = normalize_industries(industry_rows, universe)
    industries.to_csv(
        args.output_dir / "industries.csv",
        index=False,
        encoding="utf-8-sig",
    )
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "Eastmoney datacenter public HTTPS API",
        "qlib_dir": str(args.qlib_dir.resolve()),
        "period": {"start": args.start_date, "end": args.end_date},
        "universe_symbols": len(universe),
        "successful_symbols": len(payloads),
        "failed_symbols": failures,
        "financial_rows": len(financials),
        "industry_rows": len(industries),
        "notes": [
            "NOTICE_DATE controls point-in-time visibility.",
            "Latest available historical revision may be backfilled.",
            "Industry is a current classification proxy.",
        ],
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"财务缓存完成：{args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
