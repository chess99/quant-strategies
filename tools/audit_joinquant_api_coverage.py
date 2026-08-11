"""扫描本地聚宽源码并生成日频兼容接口覆盖报告。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.jq_api_audit import audit_joinquant_api_usage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT / "joinquant_archive" / "sources")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "local-research" / "jq-api-coverage.json")
    args = parser.parse_args()
    report = audit_joinquant_api_usage(args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "files": report["files"],
        "target_calls": report["target_calls"],
        "classification_counts": report["classification_counts"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
