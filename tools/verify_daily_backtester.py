"""生成迭代 5 日线撮合器机器验收报告。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest_verification import verify_daily_backtester  # noqa: E402


RESULT_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-27__monthly-small-cap__local-preflight-v3"
)
OUTPUT = ROOT / "docs" / "local-research" / "daily-backtester-verification.json"


def main():
    report = verify_daily_backtester(ROOT, RESULT_DIR)
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["local_preflight_status"] != "passed":
        raise SystemExit(1)
    print(OUTPUT)


if __name__ == "__main__":
    main()
