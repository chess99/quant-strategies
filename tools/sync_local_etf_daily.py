"""抓取并规范化本地 ETF 日线。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.etf import sync_sina_etfs  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="同步本地 ETF 日线")
    parser.add_argument("--data-root", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    bars, manifest = sync_sina_etfs(store)
    summary = {
        "data_root": str(store.root),
        "rows": len(bars),
        "symbols": bars.groupby("symbol").size().to_dict(),
        "date_range": manifest.date_range,
        "quality_grade": manifest.quality_grade.value,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
