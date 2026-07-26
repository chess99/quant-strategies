"""同步东方财富历史日估值。"""

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

from quant_research.data.store import ResearchDataStore  # noqa: E402
from quant_research.data.valuation import sync_valuation  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="同步本地历史估值")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--symbols-from",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil/financials.parquet"),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = sorted(pd.read_parquet(args.symbols_from)["symbol"].dropna().unique())
    if args.limit:
        symbols = symbols[: args.limit]
    store = ResearchDataStore(args.data_root)
    data, manifest, failures = sync_valuation(
        store,
        symbols,
        workers=args.workers,
        refresh=args.refresh,
    )
    print(
        json.dumps(
            {
                "requested_symbols": len(symbols),
                "stored_symbols": int(data["symbol"].nunique()),
                "rows": len(data),
                "date_range": manifest.date_range,
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
