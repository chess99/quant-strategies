"""冻结 h18 候选池后，比较直接买入与逐日新高突破入场的事件收益。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


ENTRY_SIGNALS = {
    "direct": "h18-control",
    "new-high-20": "h20",
    "new-high-55": "h21",
    "new-high-55-volume-1.4": "h22",
}
HORIZONS = (5, 20, 60, 120)


class DirectQlibReader:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.features_dir = self.root / "features"
        values = [
            line.strip()
            for line in (self.root / "calendars" / "day.txt").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        self.calendar = pd.DatetimeIndex(pd.to_datetime(values)).normalize()

    def feature(self, symbol: str, field: str) -> pd.Series:
        path = self.features_dir / symbol.lower() / f"{field.lower()}.day.bin"
        if not path.is_file():
            return pd.Series(dtype="float32")
        payload = np.fromfile(path, dtype="<f4")
        if payload.size < 2 or not np.isfinite(payload[0]):
            return pd.Series(dtype="float32")
        start = int(payload[0])
        values = payload[1:]
        return pd.Series(values, index=self.calendar[start : start + len(values)])

    def prices(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                field: self.feature(symbol, field).reindex(self.calendar)
                for field in ("open", "high", "close", "volume")
            },
            index=self.calendar,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_signal_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """计算只使用信号日及此前信息的突破条件；枢轴与均量均排除信号日。"""
    frame = prices.sort_index().copy()
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    frame["pivot_20"] = high.shift(1).rolling(20, min_periods=20).max()
    frame["pivot_55"] = high.shift(1).rolling(55, min_periods=55).max()
    frame["volume_mean_50"] = volume.shift(1).rolling(50, min_periods=40).mean()
    frame["relative_volume_50"] = volume / frame["volume_mean_50"].replace(0, np.nan)
    frame["new_high_20"] = close.gt(frame["pivot_20"])
    frame["new_high_55"] = close.gt(frame["pivot_55"])
    frame["new_high_55_volume_1_4"] = frame["new_high_55"] & frame[
        "relative_volume_50"
    ].ge(1.4)
    return frame


def first_entry_in_window(
    signals: pd.DataFrame,
    signal_name: str,
    observation_date,
    next_refresh_date,
):
    """返回首次信号后的下一交易日；不允许旧候选跨到下一次候选刷新日。"""
    observation = pd.Timestamp(observation_date).normalize()
    next_refresh = pd.Timestamp(next_refresh_date).normalize()
    eligible = signals.index[
        (signals.index >= observation)
        & (signals.index < next_refresh)
        & signals[signal_name].fillna(False).to_numpy()
    ]
    for signal_date in eligible:
        location = signals.index.get_indexer([signal_date])[0]
        if location < 0 or location + 1 >= len(signals.index):
            continue
        entry_date = signals.index[location + 1]
        if entry_date < next_refresh:
            return entry_date
    return None


def event_outcomes(
    prices: pd.DataFrame,
    benchmark: pd.DataFrame,
    entry_date,
    horizons=HORIZONS,
    maximum_exit_date=None,
) -> dict:
    entry = pd.Timestamp(entry_date).normalize()
    result = {"entry_date": entry}
    if entry not in prices.index or entry not in benchmark.index:
        return result
    asset_open = pd.to_numeric(pd.Series([prices.at[entry, "open"]]), errors="coerce").iloc[0]
    benchmark_open = pd.to_numeric(
        pd.Series([benchmark.at[entry, "open"]]), errors="coerce"
    ).iloc[0]
    entry_location = prices.index.get_loc(entry)
    benchmark_location = benchmark.index.get_loc(entry)
    maximum_exit = (
        pd.Timestamp(maximum_exit_date).normalize()
        if maximum_exit_date is not None
        else None
    )
    for horizon in horizons:
        asset_exit_location = entry_location + int(horizon) - 1
        benchmark_exit_location = benchmark_location + int(horizon) - 1
        asset_return = np.nan
        benchmark_return = np.nan
        if (
            asset_exit_location < len(prices.index)
            and benchmark_exit_location < len(benchmark.index)
        ):
            asset_exit_date = prices.index[asset_exit_location]
            benchmark_exit_date = benchmark.index[benchmark_exit_location]
            if (
                (maximum_exit is None or asset_exit_date <= maximum_exit)
                and benchmark_exit_date == asset_exit_date
                and np.isfinite(asset_open)
                and asset_open > 0
                and np.isfinite(benchmark_open)
                and benchmark_open > 0
            ):
                asset_close = prices.iloc[asset_exit_location]["close"]
                benchmark_close = benchmark.iloc[benchmark_exit_location]["close"]
                if np.isfinite(asset_close) and np.isfinite(benchmark_close):
                    asset_return = float(asset_close / asset_open - 1.0)
                    benchmark_return = float(benchmark_close / benchmark_open - 1.0)
        result[f"return_{horizon}"] = asset_return
        result[f"benchmark_return_{horizon}"] = benchmark_return
        result[f"excess_return_{horizon}"] = asset_return - benchmark_return
    return result


def load_frozen_selections(paths, model="quality-growth-momentum") -> pd.DataFrame:
    frames = []
    for path in paths:
        frame = pd.read_csv(path, parse_dates=["trade_date", "observation_date"])
        frames.append(frame[frame["model"].eq(model)].copy())
    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(["trade_date", "symbol"]).sort_values(
        ["trade_date", "rank", "symbol"]
    )
    return result.reset_index(drop=True)


def _next_refresh_map(selections: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict:
    trade_dates = pd.DatetimeIndex(selections["trade_date"].unique()).sort_values()
    mapping = {trade_dates[i]: trade_dates[i + 1] for i in range(len(trade_dates) - 1)}
    final = trade_dates[-1]
    target = final + pd.offsets.MonthBegin(1)
    location = calendar.searchsorted(target, side="left")
    mapping[final] = calendar[location]
    return mapping


def build_events(selections: pd.DataFrame, reader: DirectQlibReader, benchmark_symbol: str):
    benchmark = reader.prices(benchmark_symbol)
    refresh_map = _next_refresh_map(selections, reader.calendar)
    records = []
    total = len(selections)
    scanned = 0
    for symbol, symbol_rows in selections.groupby("symbol", sort=True):
        prices = reader.prices(symbol)
        signals = compute_signal_frame(prices)
        for row in symbol_rows.itertuples(index=False):
            scanned += 1
            if scanned == 1 or scanned % 500 == 0 or scanned == total:
                print(f"事件扫描 {scanned}/{total}", flush=True)
            next_refresh = refresh_map[pd.Timestamp(row.trade_date)]
            maximum_exit = pd.Timestamp("2017-12-31")
            period = "development"
            if pd.Timestamp(row.trade_date).year >= 2018:
                maximum_exit = pd.Timestamp("2021-12-31")
                period = "selection-validation"
            entries = {"direct": pd.Timestamp(row.trade_date)}
            for label, signal_name in (
                ("new-high-20", "new_high_20"),
                ("new-high-55", "new_high_55"),
                ("new-high-55-volume-1.4", "new_high_55_volume_1_4"),
            ):
                entries[label] = first_entry_in_window(
                    signals,
                    signal_name,
                    row.observation_date,
                    next_refresh,
                )
            for entry_rule, entry_date in entries.items():
                if entry_date is None:
                    continue
                outcomes = event_outcomes(
                    prices,
                    benchmark,
                    entry_date,
                    maximum_exit_date=maximum_exit,
                )
                if not np.isfinite(outcomes.get("return_5", np.nan)):
                    continue
                records.append(
                    {
                        "experiment_id": ENTRY_SIGNALS[entry_rule],
                        "entry_rule": entry_rule,
                        "period": period,
                        "symbol": symbol,
                        "candidate_trade_date": row.trade_date,
                        "observation_date": row.observation_date,
                        "candidate_rank": row.rank,
                        **outcomes,
                    }
                )
    return pd.DataFrame(records)


def summarize_events(events: pd.DataFrame, selections: pd.DataFrame) -> pd.DataFrame:
    direct_counts = {
        "development": int((selections["trade_date"].dt.year <= 2017).sum()),
        "selection-validation": int((selections["trade_date"].dt.year >= 2018).sum()),
        "full": len(selections),
    }
    rows = []
    for period in ("development", "selection-validation", "full"):
        period_events = events if period == "full" else events[events["period"].eq(period)]
        for entry_rule, group in period_events.groupby("entry_rule", sort=True):
            for horizon in HORIZONS:
                return_column = f"return_{horizon}"
                excess_column = f"excess_return_{horizon}"
                valid = group.dropna(subset=[return_column, excess_column])
                if valid.empty:
                    continue
                monthly_excess = valid.groupby("candidate_trade_date")[excess_column].mean()
                rows.append(
                    {
                        "period": period,
                        "entry_rule": entry_rule,
                        "experiment_id": ENTRY_SIGNALS[entry_rule],
                        "horizon": horizon,
                        "events": len(valid),
                        "coverage": len(group) / max(direct_counts[period], 1),
                        "mean_return": valid[return_column].mean(),
                        "median_return": valid[return_column].median(),
                        "positive_return_ratio": valid[return_column].gt(0).mean(),
                        "mean_excess_return": valid[excess_column].mean(),
                        "median_excess_return": valid[excess_column].median(),
                        "positive_excess_ratio": valid[excess_column].gt(0).mean(),
                        "p05_excess_return": valid[excess_column].quantile(0.05),
                        "mean_monthly_equal_weight_excess": monthly_excess.mean(),
                    }
                )
    return pd.DataFrame(rows)


def archive(args, selections, events, summary) -> Path:
    result_dir = Path(args.result_dir)
    if result_dir.exists():
        raise FileExistsError(f"不可覆盖已有实验：{result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    selections.to_csv(raw_dir / "frozen-selections.csv", index=False)
    events.to_csv(raw_dir / "events.csv", index=False)
    summary.to_csv(raw_dir / "summary.csv", index=False)
    source = Path(__file__).resolve()
    shutil.copy2(source, result_dir / "source.py")
    manifest = {
        "schema_version": 1,
        "study": "oneil-canslim-a-share-rebuild",
        "stage": "entry-event-study",
        "candidate_model": "h18 quality-growth-momentum",
        "period": "2010-01-01/2021-12-31",
        "entry_rules": ENTRY_SIGNALS,
        "horizons": list(HORIZONS),
        "execution": "signal close; next-session open; pivot and volume mean exclude signal day",
        "source_file": "source.py",
        "source_sha256": sha256_file(result_dir / "source.py"),
        "selection_inputs": [
            {"path": str(Path(path).resolve()), "sha256": sha256_file(Path(path))}
            for path in args.selections
        ],
        "qlib_dir": str(Path(args.qlib_dir).resolve()),
        "limitations": [
            "events are candidate-month observations and are not statistically independent",
            "event returns do not include trading costs; portfolio experiments are required before promotion",
            "historical ST and exact price-limit states remain unavailable",
            "2018-2021 entry validation follows prior selection-model research and is not a pristine final holdout",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    focus = summary[
        summary["period"].isin(["development", "selection-validation"])
        & summary["horizon"].isin([60, 120])
    ]
    lines = [
        "# h18 候选池入场事件研究",
        "",
        "候选池和排名完全冻结，只比较入场时点。所有枢轴与均量都排除信号日，信号出现后",
        "下一交易日开盘进入；事件收益尚未扣交易成本，不能直接当作组合回测结果。",
        "",
        "| 阶段 | 入场 | 期限 | 事件数 | 覆盖 | 平均超额 | 中位超额 | 正超额 | 5%尾部 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in focus.itertuples(index=False):
        lines.append(
            f"| {row.period} | {row.entry_rule} | {row.horizon} | {row.events} | "
            f"{row.coverage:.1%} | {row.mean_excess_return:.2%} | "
            f"{row.median_excess_return:.2%} | {row.positive_excess_ratio:.1%} | "
            f"{row.p05_excess_return:.2%} |"
        )
    (result_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result_dir


def parse_args():
    base = Path(__file__).resolve().parent / "results"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qlib-dir", type=Path, default=Path("D:/code/_open-source/_data/qlib/cn_data")
    )
    parser.add_argument("--benchmark", default="SH000905")
    parser.add_argument(
        "--selections",
        nargs="+",
        type=Path,
        default=[
            base
            / "2026-07-27__selection-alpha__quality-backward-confirmation-v4"
            / "raw"
            / "selections.csv",
            base
            / "2026-07-27__selection-alpha__quality-acceleration-v3"
            / "raw"
            / "selections.csv",
        ],
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=base / "2026-07-27__entry-event-study__h18-v1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selections = load_frozen_selections(args.selections)
    print(f"冻结候选月记录 {len(selections)} 条", flush=True)
    reader = DirectQlibReader(args.qlib_dir)
    events = build_events(selections, reader, args.benchmark)
    summary = summarize_events(events, selections)
    result = archive(args, selections, events, summary)
    print(f"事件研究归档：{result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
