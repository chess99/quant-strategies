"""复用已归档聚宽日志，创建新的本地自主选股黄金对照。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.store import sha256_file  # noqa: E402
from quant_research.golden_comparison import (  # noqa: E402
    compare_small_cap_results,
    load_joinquant_stats,
    parse_joinquant_small_cap_log,
)


STUDY_DIR = Path(__file__).resolve().parent


def build_report(comparison: dict) -> str:
    local = comparison["local_metrics"]
    jq = comparison["joinquant_metrics"]
    overlap = comparison["mean_overlap"]
    return f"""# 全市场小市值聚宽黄金对照

## 事实

- 状态：{comparison['status']}；逐项检查：{comparison['checks']}。
- 聚宽运行：{comparison['provenance']['backtest_url']}；本次只复用已归档日志，
  没有新增平台运行或额度消耗。
- 聚宽候选日志 {comparison['joinquant_candidate_dates']}/
  {comparison['expected_rebalance_dates']} 个调仓日；持仓日志
  {comparison['joinquant_holding_dates']}/{comparison['expected_rebalance_dates']} 个调仓日。
- 自主目标候选平均重合率 {overlap.get('selected_candidates', 0):.2%}；实际持仓平均重合率
  {overlap.get('holdings', 0):.2%}；下单证券平均重合率
  {overlap.get('ordered_symbols', 0):.2%}。
- 本地年化 {local['annualized_return']:.2%}，聚宽年化 {jq['annualized_return']:.2%}，
  差 {comparison['differences']['annualized_return']:+.2%}。
- 本地最大回撤 {local['maximum_drawdown']:.2%}，聚宽最大回撤
  {jq['maximum_drawdown']:.2%}，差 {comparison['differences']['maximum_drawdown']:+.2%}。

## 判定

完成要求是候选和持仓重合率均至少 80%，年化及最大回撤绝对差均不超过 3 个百分点，
且 54 个调仓日的结构化日志完整。本归档使用本地自主选股结果，不使用聚宽目标覆盖。
"""


def run(args) -> Path:
    local_dir = Path(args.local_result_dir).resolve()
    local_manifest = json.loads(
        (local_dir / "manifest.json").read_text(encoding="utf-8")
    )
    log_file = Path(args.log_file).resolve()
    stats_file = Path(args.stats_json).resolve()
    platform_source = Path(args.platform_source_file).resolve()
    prepared_source = Path(args.prepared_source_file).resolve()
    parsed = parse_joinquant_small_cap_log(
        log_file.read_text(encoding="utf-8", errors="replace")
    )
    comparison, overlaps = compare_small_cap_results(
        local_dir,
        parsed,
        load_joinquant_stats(stats_file),
    )
    comparison["checks"].update(
        {
            "initial_cash_matches_platform": float(local_manifest["initial_cash"])
            == float(args.joinquant_initial_cash),
            "platform_source_matches_prepared_strategy": sha256_file(platform_source)
            == sha256_file(prepared_source),
        }
    )
    comparison["status"] = (
        "passed" if all(comparison["checks"].values()) else "failed"
    )
    comparison["provenance"] = {
        "backtest_url": args.backtest_url,
        "joinquant_initial_cash": args.joinquant_initial_cash,
        "local_initial_cash": local_manifest["initial_cash"],
        "new_platform_run_required": False,
    }
    result_dir = STUDY_DIR / "results" / args.run_id
    if result_dir.exists():
        raise FileExistsError(f"immutable result directory already exists: {result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    shutil.copy2(log_file, raw_dir / "joinquant.log")
    shutil.copy2(stats_file, raw_dir / "joinquant-stats.json")
    parsed["candidates"].to_csv(raw_dir / "joinquant-candidates.csv", index=False)
    parsed["orders"].to_csv(raw_dir / "joinquant-orders.csv", index=False)
    parsed["holdings"].to_csv(raw_dir / "joinquant-holdings.csv", index=False)
    overlaps.to_csv(raw_dir / "overlap-by-rebalance.csv", index=False)
    comparison_path = result_dir / "comparison.json"
    comparison_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source = result_dir / "source.py"
    importer = result_dir / "importer.py"
    shutil.copy2(platform_source, source)
    shutil.copy2(Path(__file__), importer)
    raw_hashes = {
        path.name: sha256_file(path)
        for path in sorted(raw_dir.iterdir())
        if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "status": comparison["status"],
        "platform": "joinquant-vs-local",
        "study": "joinquant-small-cap-golden-comparison",
        "run_id": args.run_id,
        "period": {"start": "2019-01-02", "end": "2023-06-30"},
        "joinquant": {
            "backtest_url": args.backtest_url,
            "initial_cash": args.joinquant_initial_cash,
            "platform_source_sha256": sha256_file(platform_source),
            "prepared_source_sha256": sha256_file(prepared_source),
            "new_platform_run_required": False,
        },
        "local_result": str(local_dir.relative_to(ROOT)).replace("\\", "/"),
        "local_manifest_sha256": sha256_file(local_dir / "manifest.json"),
        "source_sha256": sha256_file(source),
        "importer_sha256": sha256_file(importer),
        "comparison_sha256": sha256_file(comparison_path),
        "raw_sha256": raw_hashes,
        "checks": comparison["checks"],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (result_dir / "report.md").write_text(
        build_report(comparison), encoding="utf-8"
    )
    if comparison["status"] != "passed":
        raise RuntimeError(f"golden comparison failed; evidence preserved at {result_dir}")
    return result_dir


def parse_args():
    parser = argparse.ArgumentParser(description="复用聚宽日志创建小市值黄金对照")
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--stats-json", type=Path, required=True)
    parser.add_argument("--platform-source-file", type=Path, required=True)
    parser.add_argument(
        "--prepared-source-file",
        type=Path,
        default=STUDY_DIR / "joinquant_strategy.py",
    )
    parser.add_argument("--backtest-url", required=True)
    parser.add_argument("--joinquant-initial-cash", type=float, required=True)
    parser.add_argument("--local-result-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    print(run(parse_args()))
