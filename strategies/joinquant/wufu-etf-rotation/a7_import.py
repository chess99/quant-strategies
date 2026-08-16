"""归档已在聚宽完成的五福 A7 分钟配对校准摘要。

逐事件结果仍保存在带哈希的聚宽 Research ZIP 中。本脚本校验本地输入，按事件数聚合
三个连续分段，并生成一个独立、不可变的 A7 归档；它不会改写既有 A0—A6 归档。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


FAMILY = Path(__file__).resolve().parent
DEFAULT_RUN_FILE = FAMILY / "platform" / "a7-platform-run.json"
DEFAULT_BASE_ARCHIVE = (
    FAMILY
    / "backtests"
    / "2026-08-16__direct-decomposition__local-etf-2015-2026-v1"
)
DEFAULT_RUN_NAME = "2026-08-16__a7-minute-calibration__joinquant-2015-2026-v1"
CHECK_TIMES = ("13:10", "13:40", "14:10", "14:40", "14:55")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_platform_run(path: Path = DEFAULT_RUN_FILE) -> dict[str, Any]:
    """读取冻结平台输出，并校验会影响 A7 口径的本地文件。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("platform") != "joinquant":
        raise ValueError("A7 platform run must be JoinQuant")
    segments = payload.get("segments", [])
    if len(segments) != 3:
        raise ValueError("A7 platform run must contain exactly three frozen segments")

    event_path = FAMILY / "platform" / payload["input"]["event_file"]
    if sha256_file(event_path) != payload["input"]["event_file_sha256"]:
        raise ValueError("A7 switch-event input hash mismatch")
    compatible_script = FAMILY / "platform" / "a7_minute_calibration.py"
    if sha256_file(compatible_script) != payload["input"][
        "repository_compatible_script_sha256"
    ]:
        raise ValueError("repository-compatible A7 script hash mismatch")
    return payload


def aggregate_segments(
    payload: dict[str, Any], *, base_trading_days: int
) -> dict[str, Any]:
    """按有效事件数聚合三段，而不是错误地对三个分段等权平均。"""
    segments = payload["segments"]
    requested = sum(int(item["requested_events"]) for item in segments)
    valid = sum(int(item["valid_events"]) for item in segments)
    if requested != int(payload["input"]["event_rows"]):
        raise ValueError("segment requested-event count does not match frozen input")
    if valid <= 0 or base_trading_days <= 0:
        raise ValueError("A7 requires valid events and positive base trading days")
    for item in segments:
        count_sum = sum(int(value) for value in item["confirmation_counts"].values())
        if count_sum != int(item["valid_events"]):
            raise ValueError(f"confirmation counts do not sum in {item['suffix']}")

    counts = {
        clock: sum(int(item["confirmation_counts"].get(clock, 0)) for item in segments)
        for clock in CHECK_TIMES
    }

    def weighted(field: str) -> float:
        return sum(
            float(item[field]) * int(item["valid_events"]) for item in segments
        ) / valid

    relative_wealth = 1.0
    for item in segments:
        relative_wealth *= 1.0 + float(item["relative_wealth_from_entry_only"])
    relative_wealth -= 1.0
    relative_annualized = (
        (1.0 + relative_wealth) ** (252.0 / float(base_trading_days)) - 1.0
    )
    return {
        "status": "completed_on_joinquant",
        "method": payload["method"],
        "requested_events": requested,
        "valid_events": valid,
        "valid_ratio": valid / requested,
        "confirmation_counts": counts,
        "confirmation_ratios": {
            clock: counts[clock] / valid for clock in CHECK_TIMES
        },
        "forced_1455_ratio": counts["14:55"] / valid,
        "mean_entry_edge_bp": weighted("mean_entry_edge_bp"),
        "segment_medians_entry_edge_bp": [
            float(item["median_entry_edge_bp"]) for item in segments
        ],
        "positive_entry_edge_ratio": weighted("positive_entry_edge_ratio"),
        "paired_trade_return_delta": weighted("paired_trade_return_delta"),
        "relative_wealth_from_entry_only": relative_wealth,
        "relative_annualized_from_entry_only": relative_annualized,
        "base_trading_days": int(base_trading_days),
        "event_level_distribution_available_locally": False,
        "remote_results_zip_sha256": payload["remote_artifact"]["sha256"],
        "limitations": payload["limitations"],
    }


def segment_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in payload["segments"]:
        row = {key: value for key, value in item.items() if key != "confirmation_counts"}
        row.update(
            {
                f"confirmation_{clock.replace(':', '')}": item[
                    "confirmation_counts"
                ].get(clock, 0)
                for clock in CHECK_TIMES
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def create_chart(path: Path, payload: dict[str, Any], summary: dict[str, Any]) -> None:
    segments = payload["segments"]
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    counts = summary["confirmation_counts"]
    axes[0].bar(CHECK_TIMES, [counts[clock] for clock in CHECK_TIMES], color="#2f69bf")
    axes[0].set_title("A7 confirmation time: 891 events")
    axes[0].set_ylabel("events")

    labels = [item["suffix"] for item in segments] + ["aggregate"]
    edges = [float(item["mean_entry_edge_bp"]) for item in segments] + [
        summary["mean_entry_edge_bp"]
    ]
    colors = ["#d95f02" if value < 0 else "#1b9e77" for value in edges]
    axes[1].bar(labels, edges, color=colors)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Entry-price edge vs 13:10")
    axes[1].set_ylabel("basis points")

    wealth = [
        100.0 * float(item["relative_wealth_from_entry_only"]) for item in segments
    ] + [100.0 * summary["relative_wealth_from_entry_only"]]
    axes[2].bar(labels, wealth, color="#7570b3")
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_title("Paired entry-only relative wealth")
    axes[2].set_ylabel("percent")
    figure.suptitle("Wufu A7 minute-timing calibration (frozen targets and exits)")
    figure.tight_layout()
    figure.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def build_report(
    payload: dict[str, Any],
    summary: dict[str, Any],
    base_manifest: dict[str, Any],
) -> str:
    public_cagr = float(base_manifest["metrics"]["public_reference"]["annual_algo_return"])
    local_cagr = float(base_manifest["metrics"]["A6_top1"]["annualized_return"])
    cagr_gap = public_cagr - local_cagr
    rough_gap_scale = summary["relative_annualized_from_entry_only"] / cagr_gap
    counts = summary["confirmation_counts"]
    remote = payload["remote_artifact"]
    return f"""# 五福 7.5 A7 分钟择时配对校准

## 结论

A7 冻结了 {summary['valid_events']} 个本地 A6 Top1 开仓标的、开仓日和退出价格，只替换买入分钟。
相对每笔都在 13:10 买入，A7 平均取得 **{summary['mean_entry_edge_bp']:.2f}bp** 的买价优势；三个
连续分段按原顺序复合后的入场端相对财富为 **{summary['relative_wealth_from_entry_only']:.2%}**，
按本地基线 {summary['base_trading_days']} 个交易日折算约 **{summary['relative_annualized_from_entry_only']:.2%}/年**。

这是一个小幅正边际，但不是公开五福高收益的主要发动机。公开年化与本地 A6 Top1 年化的差距为
{cagr_gap:.2%}；A7 入场价优势的相对年化量级约为该差距的 {rough_gap_scale:.1%}。两种收益口径
不能严格相加，这一比例只用于比较数量级。

A7 也没有通过事前定义的完整成功门槛：虽然三个分段中有两个平均边际为正，但配对实验没有重建
完整组合净值和成交后 Sharpe，因此不能声称“改善成交后 Sharpe”。当前证据只支持把 A7 保留为
待进一步仿真的执行优化候选。

## 执行分布

| 时间 | 事件数 | 占比 |
|---|---:|---:|
| 13:10 | {counts['13:10']} | {counts['13:10']/summary['valid_events']:.2%} |
| 13:40 | {counts['13:40']} | {counts['13:40']/summary['valid_events']:.2%} |
| 14:10 | {counts['14:10']} | {counts['14:10']/summary['valid_events']:.2%} |
| 14:40 | {counts['14:40']} | {counts['14:40']/summary['valid_events']:.2%} |
| 14:55 强制 | {counts['14:55']} | {summary['forced_1455_ratio']:.2%} |

- 有效分钟数据：{summary['valid_events']}/{summary['requested_events']}，覆盖率 100%；
- 平均单笔配对收益差：{summary['paired_trade_return_delta']:.4%}；
- 买价优于 13:10 的事件占比：{summary['positive_entry_edge_ratio']:.2%}；
- 三个分段的买价优势中位数均为 0bp，说明均值优势并非普遍发生；
- 第一段均值为 -0.59bp，第二、三段为 +8.04bp/+7.81bp，边际存在时间不稳定性。

## 因果口径

A7 只替换买入分钟：13:10、13:40、14:10、14:40 依次检查原版 30 分钟加权斜率和 R²；
未通过则 14:55 强制买入。ETF、开仓日和退出日完全冻结，退出统一使用 13:10 分钟价格。
因此它回答的是“同一笔已经决定的交易，延迟买入是否更便宜”，不是重新运行原版 13:10 实时选股，
也不是完整组合 Sharpe 回测。

## 平台证据与限制

- 平台：JoinQuant Research / Python 3；运行日期：{payload['run_date']}；
- 输入事件 SHA-256：`{payload['input']['event_file_sha256']}`；
- 聚宽实际执行脚本 SHA-256：`{payload['input']['executed_script_sha256']}`；
- 远端逐事件结果包：`{remote['file']}`，SHA-256：`{remote['sha256']}`；
- 远端包包含三段逐事件 CSV 和三段摘要 JSON，但浏览器下载通道持续超时，逐事件 ZIP 未复制进本地仓库；
- 本归档保留精确的三段平台摘要，可独立复核加权、计数和复合财富，但不能在本地重做逐事件显著性检验；
- 未模拟停牌、涨跌停排队、部分成交、组合现金路径，以及延迟买入导致的成交机会损失。

所以 A7 可以保留为执行层优化候选，但当前证据不支持把它解释成公开 83.87% 年化的主要来源，
更不支持据此继续增加盘中例外规则。
"""


def write_archive(
    payload: dict[str, Any],
    *,
    run_name: str = DEFAULT_RUN_NAME,
    base_archive: Path = DEFAULT_BASE_ARCHIVE,
) -> Path:
    base_manifest_path = base_archive / "manifest.json"
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    summary = aggregate_segments(
        payload,
        base_trading_days=int(base_manifest["metrics"]["A6_top1"]["trading_days"]),
    )
    output = FAMILY / "backtests" / run_name
    if output.exists():
        raise FileExistsError(f"immutable archive already exists: {output}")
    raw = output / "raw"
    assets = output / "assets"
    raw.mkdir(parents=True)
    assets.mkdir()

    source = FAMILY / "platform" / "a7_minute_calibration.py"
    events = FAMILY / "platform" / payload["input"]["event_file"]
    shutil.copy2(source, output / "source.py")
    shutil.copy2(events, raw / "a7-switch-events.csv")
    write_json(raw / "a7-platform-run.json", payload)
    segment_frame(payload).to_csv(
        raw / "a7-segment-summaries.csv", index=False, encoding="utf-8"
    )
    write_json(raw / "a7-summary.json", summary)
    write_json(
        output / "config.json",
        {
            "check_times": list(CHECK_TIMES[:-1]),
            "force_time": CHECK_TIMES[-1],
            "trend_slope_pct_threshold": 0.001,
            "trend_r_squared_threshold": 0.3,
            "trend_window_minutes": 30,
            "target_and_exit": "frozen local A6 Top1 target; exit at 13:10",
            "base_archive": base_archive.name,
        },
    )
    create_chart(assets / "a7-minute-calibration.png", payload, summary)
    (output / "report.md").write_text(
        build_report(payload, summary, base_manifest), encoding="utf-8"
    )

    artifact_hashes: dict[str, dict[str, Any]] = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifact_hashes[path.relative_to(output).as_posix()] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
    manifest = {
        "schema_version": 1,
        "archived_at": payload["run_date"],
        "platform": "joinquant",
        "strategy_id": "wufu-etf-rotation",
        "variant": "a7-minute-calibration",
        "run_id": run_name,
        "source_file": "source.py",
        "source_sha256": sha256_file(output / "source.py"),
        "period": base_manifest["period"],
        "metrics": {"A7": summary},
        "base_archive": base_archive.name,
        "base_manifest_sha256": sha256_file(base_manifest_path),
        "joinquant_notebook_url": payload["research_notebook"]["url"],
        "remote_results_zip_sha256": payload["remote_artifact"]["sha256"],
        "event_level_results_local": False,
        "artifacts": artifact_hashes,
    }
    write_json(output / "manifest.json", manifest)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-file", type=Path, default=DEFAULT_RUN_FILE)
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    arguments = parser.parse_args()
    payload = load_platform_run(arguments.run_file)
    output = write_archive(payload, run_name=arguments.run_name)
    print(output)


if __name__ == "__main__":
    main()
