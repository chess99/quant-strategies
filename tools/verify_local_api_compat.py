"""生成迭代4统一接口机器验收报告。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.api_compat_verification import (  # noqa: E402
    build_api_compat_verification,
)


def main() -> int:
    report = build_api_compat_verification(ROOT)
    target = ROOT / "docs" / "local-research" / "api-compat-verification.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
