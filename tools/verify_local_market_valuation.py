"""生成全市场估值与历史交易状态验收报告。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.market_verification import (  # noqa: E402
    build_market_valuation_verification,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验收市场状态与估值数据")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--minimum-valuation-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-known-st-ratio", type=float, default=0.95)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_market_valuation_verification(
        ResearchDataStore(args.data_root),
        minimum_current_valuation_coverage=args.minimum_valuation_coverage,
        minimum_known_st_ratio=args.minimum_known_st_ratio,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
