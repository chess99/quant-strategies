"""抽样交叉核验历史停牌、ST、涨跌停、一字板和买卖阻塞。"""

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
    build_market_state_crosscheck,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="交叉核验历史市场状态")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--qlib-root",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument("--sample-per-board", type=int, default=64)
    parser.add_argument("--minimum-paused-agreement", type=float, default=0.98)
    parser.add_argument("--minimum-st-agreement", type=float, default=0.99)
    parser.add_argument(
        "--minimum-limit-bound-agreement", type=float, default=0.995
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_market_state_crosscheck(
        ResearchDataStore(args.data_root),
        qlib_root=args.qlib_root,
        sample_per_board=args.sample_per_board,
        minimum_paused_agreement=args.minimum_paused_agreement,
        minimum_st_agreement=args.minimum_st_agreement,
        minimum_limit_bound_agreement=args.minimum_limit_bound_agreement,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
