"""审计 588000 连续信号价与历史真实执行价是否存在复权差异。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE_PATH = Path(__file__).resolve()
STUDY_DIR = SOURCE_PATH.parent
RESULTS_DIR = STUDY_DIR / "results"
ENGINE_PATH = STUDY_DIR / "run_study.py"
ARCHIVE_PREFIX = "2026-09-02__execution-price-audit__tencent-raw-qfq-2020-2026"


def _load_engine():
    spec = importlib.util.spec_from_file_location("star50_execution_price_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载科创 50 研究行情模块")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


engine = _load_engine()


def _normalize_tencent_rows(rows) -> pd.DataFrame:
    frame = pd.DataFrame(
        [row[:6] for row in rows],
        columns=["date", "open", "close", "high", "low", "volume"],
    )
    if frame.empty:
        raise ValueError("腾讯行情没有返回日线")
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    for field in ("open", "high", "low", "close", "volume"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
    return frame.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def fetch_tencent_raw(end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    batch_start = pd.Timestamp("2020-11-01")
    while batch_start <= end:
        batch_end = min(batch_start + pd.DateOffset(years=2) - pd.Timedelta(days=1), end)
        payload = engine._fetch_json(
            "https://web.ifzq.gtimg.cn/appstock/app/kline/kline",
            {
                "param": (
                    f"sh588000,day,{batch_start:%Y-%m-%d},{batch_end:%Y-%m-%d},640"
                )
            },
        )
        rows.extend(payload.get("data", {}).get("sh588000", {}).get("day", []))
        batch_start = batch_end + pd.Timedelta(days=1)
    latest = engine._fetch_json(
        "https://web.ifzq.gtimg.cn/appstock/app/kline/kline",
        {
            "param": "sh588000,day,,,30",
            "_": str(pd.Timestamp.now(tz="UTC").value),
        },
    )
    rows.extend(latest.get("data", {}).get("sh588000", {}).get("day", []))
    return _normalize_tencent_rows(rows).loc[lambda frame: frame["date"].le(end)]


def fetch_tencent_qfq(end: pd.Timestamp) -> pd.DataFrame:
    return _normalize_tencent_rows(engine._fetch_tencent_qfq(end).to_numpy().tolist())


def compare_prices(qfq: pd.DataFrame, raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = {"date", "open", "high", "low", "close", "volume"}
    for name, frame in (("qfq", qfq), ("raw", raw)):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{name} 缺少字段：{sorted(missing)}")
    left = qfq.copy()
    right = raw.copy()
    left["date"] = pd.to_datetime(left["date"]).dt.normalize()
    right["date"] = pd.to_datetime(right["date"]).dt.normalize()
    merged = left.merge(
        right,
        on="date",
        how="inner",
        suffixes=("_qfq", "_raw"),
        validate="one_to_one",
    ).sort_values("date")
    relative_columns = []
    for field in ("open", "high", "low", "close"):
        qfq_value = pd.to_numeric(merged[f"{field}_qfq"], errors="raise")
        raw_value = pd.to_numeric(merged[f"{field}_raw"], errors="raise")
        column = f"{field}_relative_error"
        merged[column] = (qfq_value - raw_value).abs() / raw_value.abs().replace(0.0, np.nan)
        relative_columns.append(column)
    merged["maximum_ohlc_relative_error"] = merged[relative_columns].max(axis=1)
    merged["exact_ohlc_match"] = merged["maximum_ohlc_relative_error"].le(1e-12)
    summary = {
        "qfq_sessions": len(left),
        "raw_sessions": len(right),
        "common_sessions": len(merged),
        "exact_match_sessions": int(merged["exact_ohlc_match"].sum()),
        "maximum_ohlc_relative_error": float(
            merged["maximum_ohlc_relative_error"].max()
        ),
        "qfq_only_sessions": int(len(left) - len(merged)),
        "raw_only_sessions": int(len(right) - len(merged)),
        "start": merged["date"].min().strftime("%Y-%m-%d"),
        "end": merged["date"].max().strftime("%Y-%m-%d"),
    }
    return merged, summary


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(value, path: Path) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_report(summary: dict, supersedes: str | None = None) -> str:
    exact = summary["exact_match_sessions"] == summary["common_sessions"]
    lines = [
            "# 科创 50 ETF 信号价与执行价口径审计",
            "",
            "## 结论",
            "",
            f"比较 {summary['start']} 至 {summary['end']} 的腾讯前复权与原始交易 OHLC，",
            f"共同交易日 {summary['common_sessions']:,} 个，逐日完全一致 "
            f"{summary['exact_match_sessions']:,} 个，最大相对差异 "
            f"{summary['maximum_ohlc_relative_error']:.4%}。",
    ]
    if supersedes:
        lines.extend(
            [
                "",
                "## 更正关系",
                "",
                f"本归档取代 `{supersedes}`。旧归档把无日期尾窗的两位小数临时行情覆盖到",
                "三位小数历史行，制造了并不存在的复权差异，并据此输出了矛盾结论。",
            ]
        )
    lines.append("")
    if exact:
        lines.extend(
            [
                "因此这段历史中使用前复权价格模拟整数手、成交金额和最低佣金没有产生价格口径",
                "偏差。本结论只覆盖已归档日期；未来发生分红或份额相关公司行为时，仍必须使用",
                "连续复权价计算信号、使用当时真实未复权价格生成订单和现金账本。",
            ]
        )
    else:
        lines.extend(
            [
                "前复权与原始执行价不能视为完全一致。在定位公司行为、精度或缓存口径之前，",
                "不得用前复权价直接生成整数手订单、成交金额或现金账本。",
            ]
        )
    lines.extend(
        [
            "",
            "本审计不修改任何策略、参数或门槛，也不提供新的 Alpha 证据。",
            "",
        ]
    )
    return "\n".join(lines)


def archive_result(
    qfq: pd.DataFrame,
    raw: pd.DataFrame,
    comparison: pd.DataFrame,
    summary: dict,
    version: int = 1,
    supersedes: str | None = None,
) -> Path:
    if not isinstance(version, int) or version < 1:
        raise ValueError("归档版本必须是正整数")
    if version > 1 and not supersedes:
        raise ValueError("更正版归档必须声明 supersedes")
    archive_name = f"{ARCHIVE_PREFIX}-v{version}"
    destination = RESULTS_DIR / archive_name
    if destination.exists():
        raise FileExistsError(f"不可覆盖既有归档：{archive_name}")
    raw_dir = destination / "raw"
    raw_dir.mkdir(parents=True)
    qfq.to_csv(raw_dir / "tencent-qfq.csv", index=False)
    raw.to_csv(raw_dir / "tencent-raw.csv", index=False)
    comparison.to_csv(raw_dir / "price-comparison.csv", index=False)
    _write_json(summary, raw_dir / "summary.json")
    shutil.copy2(SOURCE_PATH, destination / "source.py")
    shutil.copy2(ENGINE_PATH, destination / "engine.py")
    (destination / "report.md").write_text(
        build_report(summary, supersedes=supersedes),
        encoding="utf-8",
    )
    artifact_paths = sorted(
        path for path in destination.rglob("*") if path.is_file() and path.name != "manifest.json"
    )
    artifacts = {
        path.relative_to(destination).as_posix(): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in artifact_paths
    }
    manifest = {
        "schema_version": 1,
        "study_id": "star50-execution-price-audit",
        "archived_at": "2026-09-02",
        "symbol": engine.SYMBOL,
        "evidence_class": "execution data engineering audit; no alpha evidence",
        "revision": version,
        "supersedes": supersedes,
        "summary": summary,
        "source_file": "source.py",
        "source_sha256": _sha256(destination / "source.py"),
        "artifacts": artifacts,
    }
    _write_json(manifest, destination / "manifest.json")
    return destination


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default="2026-09-02")
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument("--supersedes", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    end = pd.Timestamp(args.end_date).normalize()
    qfq = fetch_tencent_qfq(end)
    raw = fetch_tencent_raw(end)
    comparison, summary = compare_prices(qfq, raw)
    destination = archive_result(
        qfq,
        raw,
        comparison,
        summary,
        version=args.version,
        supersedes=args.supersedes,
    )
    print(build_report(summary, supersedes=args.supersedes))
    print(f"归档完成：{destination.relative_to(STUDY_DIR).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
