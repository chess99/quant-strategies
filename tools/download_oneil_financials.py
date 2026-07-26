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
DEFAULT_RESEARCH_DATA_ROOT = Path("D:/code/_open-source/_data/quant-research")
FINANCIAL_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
INDUSTRY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
ALL_A_BOARDS = {"main", "chinext", "star", "beijing"}


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


def load_or_fetch_symbol(symbol, raw_dir, engine, seed_raw_dirs=()):
    path = raw_dir / f"{symbol.lower()}.json.gz"
    if path.is_file():
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return symbol, json.load(handle), "output"
    for seed_raw_dir in seed_raw_dirs:
        seed_path = Path(seed_raw_dir) / path.name
        if seed_path.is_file():
            with gzip.open(seed_path, "rt", encoding="utf-8") as handle:
                return symbol, json.load(handle), "seed"
    rows = fetch_symbol(engine.eastmoney_code(symbol))
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False)
    return symbol, rows, "network"


def select_all_a_universe(security_master, start_date, end_date):
    """从证券主表选择区间内真实 A 股，显式排除指数和基金代码。"""
    frame = security_master.copy()
    required = {"symbol", "asset_type", "board", "start_date", "end_date"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"security master is missing columns: {sorted(missing)}")
    frame["symbol"] = frame["symbol"].astype("string").str.upper()
    frame["start_date"] = pd.to_datetime(frame["start_date"], errors="coerce")
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    mask = (
        frame["asset_type"].eq("stock")
        & frame["board"].isin(ALL_A_BOARDS)
        & frame["start_date"].le(end)
        & frame["end_date"].ge(start)
        & frame["symbol"].str.fullmatch(r"(?:SH|SZ|BJ)\d{6}", na=False)
    )
    return sorted(frame.loc[mask, "symbol"].drop_duplicates().tolist())


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
    parser.add_argument(
        "--universe",
        choices=("historical-csi300-csi500", "all-a"),
        default="historical-csi300-csi500",
    )
    parser.add_argument(
        "--security-master",
        type=Path,
        default=DEFAULT_RESEARCH_DATA_ROOT / "normalized" / "security_master" / "data.parquet",
    )
    parser.add_argument(
        "--seed-raw-dir",
        action="append",
        type=Path,
        default=[],
        help="可重复指定只读种子缓存目录；命中后不复制到输出目录。",
    )
    parser.add_argument(
        "--skip-industry",
        action="store_true",
        help="不下载当前行业快照；全A历史研究通常应使用此项避免误用当前行业。",
    )
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    return parser


def main():
    args = build_parser().parse_args()
    engine = load_engine()
    common = engine.load_common_engine()
    data = common.QlibBinDataPortal(args.qlib_dir)
    if args.universe == "all-a":
        security_master = pd.read_parquet(args.security_master)
        universe = select_all_a_universe(
            security_master, args.start_date, args.end_date
        )
    else:
        universe = data.symbols_during(
            engine.DEFAULT_MARKETS, args.start_date, args.end_date
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    payloads = {}
    failures = {}
    cache_sources = {"output": 0, "seed": 0, "network": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                load_or_fetch_symbol,
                symbol,
                raw_dir,
                engine,
                tuple(args.seed_raw_dir),
            ): symbol
            for symbol in universe
        }
        for number, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                _, rows, cache_source = future.result()
                payloads[symbol] = rows
                cache_sources[cache_source] += 1
            except Exception as exc:
                failures[symbol] = str(exc)
            if number % 50 == 0 or number == len(futures):
                print(
                    f"财务下载：{number}/{len(futures)}，"
                    f"成功 {len(payloads)}，失败 {len(failures)}，"
                    f"输出缓存 {cache_sources['output']}，种子缓存 {cache_sources['seed']}，"
                    f"网络 {cache_sources['network']}",
                    flush=True,
                )

    financials = normalize_financials(payloads, engine)
    financials.to_parquet(args.output_dir / "financials.parquet", index=False)
    industries = pd.DataFrame()
    if not args.skip_industry:
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
        "universe_mode": args.universe,
        "security_master": str(args.security_master.resolve()) if args.universe == "all-a" else None,
        "universe_symbols": len(universe),
        "successful_symbols": len(payloads),
        "failed_symbols": failures,
        "cache_sources": cache_sources,
        "financial_rows": len(financials),
        "industry_rows": len(industries),
        "notes": [
            "NOTICE_DATE controls point-in-time visibility.",
            "Latest available historical revision may be backfilled.",
            (
                "Current industry snapshot was intentionally skipped."
                if args.skip_industry
                else "Industry is a current classification proxy."
            ),
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
