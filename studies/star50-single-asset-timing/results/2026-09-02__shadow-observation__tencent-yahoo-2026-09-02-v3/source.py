"""获取并不可变归档科创 50 ETF 冻结模型的未来影子观察。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pandas as pd


SOURCE_PATH = Path(__file__).resolve()
STUDY_DIR = SOURCE_PATH.parent
RESULTS_DIR = STUDY_DIR / "results"
SIGNAL_PATH = STUDY_DIR / "run_shadow_signals.py"
FREEZE_DATE = pd.Timestamp("2026-09-01")


def _load_shadow_module():
    spec = importlib.util.spec_from_file_location("star50_future_shadow_observation", SIGNAL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载冻结影子信号模块")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shadow = _load_shadow_module()
engine = shadow.engine
extension = shadow.extension


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(value, path: Path) -> None:
    path.write_text(
        json.dumps(engine._json_safe(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_report(
    frame: pd.DataFrame,
    snapshot: dict,
    supersedes: str | None = None,
    correction_note: str | None = None,
) -> str:
    observation = pd.Timestamp(snapshot["observation_date"])
    new_sessions = int((frame.index > FREEZE_DATE).sum())
    data = snapshot["data"]
    lines = [
        f"# 科创 50 ETF {observation:%Y-%m-%d} 冻结后影子观察",
        "",
        "## 证据状态",
        "",
        f"这是 2026-09-01 冻结规则后的第 {new_sessions} 个新交易日。",
        "该观察未参与参数、门槛或模型选择，不与旧历史合并重新优化；一个交易日不能支持",
        "收益、回撤或显著性结论。",
    ]
    if supersedes:
        lines.extend(
            [
                "",
                "## 更正关系",
                "",
                f"本归档取代 `{supersedes}` 作为该观察日的有效证据。旧归档保持不变。",
                correction_note
                or "旧归档没有保存最新主源、核验源和共同日期，不能独立证明最新一天已被第二源覆盖。",
            ]
        )
    lines.extend(
        [
            "",
            "## 数据质量",
            "",
            f"- 完整观察日：{snapshot['observation_date']}；",
            f"- 累计交易日：{data['sessions']:,}；",
            f"- 双源 OHLC 最大相对差异：{float(data['maximum_ohlc_relative_error']):.2%}；",
            f"- 成交量中位相对差异：{float(data['median_volume_relative_error']):.4%}；",
            f"- 最新主源/核验源/共同日期：{data['latest_primary_date']} / "
            f"{data['latest_verification_date']} / {data['latest_common_date']}。",
            "",
            "## 冻结目标",
            "",
            "| 模型 | 目标仓位 | 前一目标 | 动作 | 最近目标变化 |",
            "|---|---:|---:|---|---|",
        ]
    )
    for model in snapshot["models"]:
        lines.append(
            f"| `{model['config']}` | {float(model['target_weight']):.2%} | "
            f"{float(model['previous_target_weight']):.2%} | `{model['action']}` | "
            f"{model['last_target_change']} |"
        )
    lines.extend(
        [
            "",
            "本日两个模型均未改变目标，因此不生成新的理论调仓。后续观察继续使用完全相同的",
            "冻结源码和门槛，直到累计至少 8 个未来季度再做统计复核。",
            "",
        ]
    )
    return "\n".join(lines)


def archive_observation(
    frame: pd.DataFrame,
    snapshot: dict,
    results_dir: Path = RESULTS_DIR,
    version: int = 1,
    supersedes: str | None = None,
    correction_note: str | None = None,
) -> Path:
    if snapshot.get("status") != "shadow_only":
        raise ValueError("只有成功的冻结影子观察可以归档")
    observation = pd.Timestamp(snapshot["observation_date"]).normalize()
    if observation <= FREEZE_DATE:
        raise ValueError("影子观察必须严格位于冻结日之后")
    if snapshot.get("data", {}).get("latest_session_cross_checked") is not True:
        raise ValueError("最新交易日尚未通过第二行情源核验，不能归档为未来证据")
    if observation != pd.Timestamp(frame.index.max()).normalize():
        raise ValueError("影子观察日期与输入最后交易日不一致")
    if not isinstance(version, int) or version < 1:
        raise ValueError("归档版本必须是正整数")
    if version > 1 and not supersedes:
        raise ValueError("更正版归档必须声明 supersedes")
    new_sessions = int((frame.index > FREEZE_DATE).sum())
    name = (
        f"{observation:%Y-%m-%d}__shadow-observation__"
        f"tencent-yahoo-{observation:%Y-%m-%d}-v{version}"
    )
    destination = results_dir / name
    if destination.exists():
        raise FileExistsError(f"不可覆盖既有影子观察：{name}")
    raw = destination / "raw"
    raw.mkdir(parents=True)
    input_path = raw / "input-sh588000.csv"
    frame.reset_index().to_csv(input_path, index=False)
    _write_json(snapshot, raw / "snapshot.json")
    shutil.copy2(SOURCE_PATH, destination / "source.py")
    shutil.copy2(SIGNAL_PATH, destination / "signals.py")
    shutil.copy2(extension.SOURCE_PATH, destination / "extension.py")
    shutil.copy2(engine.SOURCE_PATH, destination / "engine.py")
    (destination / "report.md").write_text(
        build_report(
            frame,
            snapshot,
            supersedes=supersedes,
            correction_note=correction_note,
        ),
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
        "study_id": "star50-single-asset-frozen-shadow-observation",
        "archived_at": observation.strftime("%Y-%m-%d"),
        "observation_date": observation.strftime("%Y-%m-%d"),
        "symbol": engine.SYMBOL,
        "evidence_class": "frozen future shadow observation",
        "revision": version,
        "supersedes": supersedes,
        "correction_note": correction_note,
        "freeze_date": FREEZE_DATE.strftime("%Y-%m-%d"),
        "new_sessions_since_freeze": new_sessions,
        "data": {
            "input_file": "raw/input-sh588000.csv",
            "input_sha256": _sha256(input_path),
            "sessions": len(frame),
            "maximum_ohlc_relative_error": snapshot["data"][
                "maximum_ohlc_relative_error"
            ],
            "median_volume_relative_error": snapshot["data"][
                "median_volume_relative_error"
            ],
        },
        "models": [
            {
                "config": model["config"],
                "target_weight": model["target_weight"],
                "action": model["action"],
            }
            for model in snapshot["models"]
        ],
        "source_file": "source.py",
        "source_sha256": _sha256(destination / "source.py"),
        "artifacts": artifacts,
    }
    _write_json(manifest, destination / "manifest.json")
    return destination


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--input-csv", type=Path, default=None)
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument("--supersedes", default=None)
    parser.add_argument("--correction-note", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        frame = (
            engine.load_input_csv(args.input_csv)
            if args.input_csv is not None
            else engine.fetch_market_data(args.end_date)
        )
        snapshot = shadow.compute_shadow_snapshot(frame)
        destination = archive_observation(
            frame,
            snapshot,
            version=args.version,
            supersedes=args.supersedes,
            correction_note=args.correction_note,
        )
    except (KeyError, OSError, TimeoutError, ValueError, FileExistsError) as exc:
        result = {
            "schema_version": 1,
            "status": "halted",
            "stage": "archive_shadow_observation",
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "archive": None,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    result = {
        "schema_version": 1,
        "status": "archived",
        "observation_date": snapshot["observation_date"],
        "archive": destination.relative_to(STUDY_DIR).as_posix(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
