"""使用 Qlib 日线构建停牌和涨跌停近似状态。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.market_state import (  # noqa: E402
    build_market_state,
    save_market_state,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="构建本地日频市场状态")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--qlib-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument(
        "--symbols-from",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil/financials.parquet"),
    )
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    import qlib
    from qlib.data import D

    symbols = sorted(pd.read_parquet(args.symbols_from)["symbol"].dropna().unique())
    if args.limit:
        symbols = symbols[: args.limit]
    qlib.init(
        provider_uri=str(args.qlib_dir),
        region="cn",
        kernels=4,
        joblib_backend="threading",
    )
    prefix = "$"
    fields = [
        prefix + "open",
        prefix + "high",
        prefix + "low",
        prefix + "close",
        prefix + "volume",
        prefix + "factor",
    ]
    features = D.features(
        symbols,
        fields,
        start_time=args.start,
        end_time=args.end,
        freq="day",
    ).reset_index()
    features.columns = [column.removeprefix("$") for column in features.columns]
    features.rename(columns={"instrument": "symbol", "datetime": "trade_date"}, inplace=True)
    calendar = pd.DatetimeIndex(D.calendar(args.start, args.end, freq="day"))
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    state = build_market_state(features, calendar, master, symbols)
    manifest = save_market_state(store, state, args.qlib_dir, len(symbols))
    print(
        json.dumps(
            {
                "symbols": int(state["symbol"].nunique()),
                "rows": len(state),
                "date_range": manifest.date_range,
                "paused_rows": int(state["paused"].sum()),
                "one_price_rows": int(state["one_price"].sum()),
                "quality_grade": manifest.quality_grade.value,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
