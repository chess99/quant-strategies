"""显示本机数据路径和数据就绪状态。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quant_research.paths import data_home, data_path  # noqa: E402


def main() -> int:
    checks = {
        "qlib_calendar": data_path("qlib/cn_data/calendars/day.txt"),
        "qlib_instruments": data_path("qlib/cn_data/instruments/all.txt"),
        "qlib_features": data_path("qlib/cn_data/features"),
        "research_manifests": data_path("quant-research/manifests"),
        "oneil_financials": data_path("oneil/financials.parquet"),
    }
    report = {
        "data_home": str(data_home()),
        "datasets": {
            name: {"path": str(path), "present": path.exists()} for name, path in checks.items()
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
