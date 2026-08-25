"""Local event-study and parameter-screening helpers for ETF flow dislocation.

Input panel columns:
date, code, open, close, money, shares
Optional exported PIT fields: start_date, end_date, traced_index_code, traced_index_name, domestic_equity

All features are computed from each observation date and earlier. Forward returns are
only labels for research; they are never fed back into the signal.
"""

from dataclasses import dataclass, asdict
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SignalConfig:
    flow_threshold: float = -0.05
    return_threshold: float = -0.08
    drawdown_threshold: float = -0.12
    reversal_threshold: float = 0.00
    require_above_ma5: bool = True


def load_panel(path):
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path)
    required = {"date", "code", "open", "close", "money", "shares"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("missing panel columns: %s" % sorted(missing))
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["code", "date"]).reset_index(drop=True)
    return frame


def add_features(panel):
    frame = panel.copy().sort_values(["code", "date"]).reset_index(drop=True)
    grouped = frame.groupby("code", group_keys=False)

    frame["flow20"] = grouped["shares"].pct_change(20)
    frame["ret20"] = grouped["close"].pct_change(20)
    frame["reversal3"] = grouped["close"].pct_change(3)

    rolling_max = (
        grouped["close"]
        .rolling(61, min_periods=61)
        .max()
        .reset_index(level=0, drop=True)
    )
    rolling_ma5 = (
        grouped["close"]
        .rolling(5, min_periods=5)
        .mean()
        .reset_index(level=0, drop=True)
    )
    frame["drawdown60"] = frame["close"] / rolling_max - 1.0
    frame["above_ma5"] = frame["close"] >= rolling_ma5

    daily_ret = grouped["close"].pct_change()
    frame["vol20"] = (
        daily_ret.groupby(frame["code"])
        .rolling(20, min_periods=20)
        .std()
        .reset_index(level=0, drop=True)
        * np.sqrt(252.0)
    )
    frame["adv20"] = (
        grouped["money"]
        .rolling(20, min_periods=15)
        .mean()
        .reset_index(level=0, drop=True)
    )

    for horizon in (5, 10, 20, 40):
        future = grouped["close"].shift(-horizon)
        frame["fwd_%dd" % horizon] = future / frame["close"] - 1.0

    return frame


def mark_weekly_observations(features):
    frame = features.copy()
    iso = frame["date"].dt.isocalendar()
    frame["_week"] = iso["year"].astype(str) + "-" + iso["week"].astype(str)
    last_dates = frame.groupby(["code", "_week"])["date"].transform("max")
    frame["weekly_observation"] = frame["date"].eq(last_dates)
    return frame.drop(columns=["_week"])


def prepare_universe(features, min_listing_calendar_days=240):
    """Apply lifecycle, exported PIT exposure flags, and same-index deduplication."""
    frame = features.copy()
    if "start_date" in frame.columns:
        start = pd.to_datetime(frame["start_date"], errors="coerce")
        age_days = (frame["date"] - start).dt.days
        frame = frame[age_days >= min_listing_calendar_days].copy()
    if "domestic_equity" in frame.columns:
        normalized = (
            frame["domestic_equity"]
            .astype(str)
            .str.lower()
            .isin({"true", "1", "yes"})
        )
        frame = frame[normalized].copy()
    if "traced_index_code" in frame.columns:
        valid = frame["traced_index_code"].notna()
        keyed = frame[valid].copy()
        unkeyed = frame[~valid].copy()
        if not keyed.empty:
            keyed = keyed.sort_values(
                ["date", "traced_index_code", "adv20", "code"],
                ascending=[True, True, False, True],
            )
            keyed = keyed.drop_duplicates(
                ["date", "traced_index_code"], keep="first"
            )
        frame = pd.concat([keyed, unkeyed], ignore_index=True)
        frame = frame.sort_values(["code", "date"]).reset_index(drop=True)
    return frame


def collapse_signal_episodes(features, event_mask, cooldown_calendar_days=28):
    """Keep only the first weekly signal in each same-ETF shock episode."""
    mask = pd.Series(event_mask, index=features.index).fillna(False).astype(bool)
    keep = pd.Series(False, index=features.index, dtype=bool)
    candidates = features.loc[mask, ["code", "date"]].sort_values(["code", "date"])
    for code, group in candidates.groupby("code", sort=False):
        last_date = None
        for index, row in group.iterrows():
            current = pd.Timestamp(row["date"])
            if last_date is None or (current - last_date).days >= cooldown_calendar_days:
                keep.loc[index] = True
                last_date = current
    return keep


def apply_signal(features, config):
    signal = (
        (features["flow20"] <= config.flow_threshold)
        & (features["ret20"] <= config.return_threshold)
        & (features["drawdown60"] <= config.drawdown_threshold)
        & (features["reversal3"] >= config.reversal_threshold)
    )
    if config.require_above_ma5:
        signal = signal & features["above_ma5"].fillna(False)
    return signal.fillna(False)


def event_study(panel, config=SignalConfig(), min_adv20=30_000_000):
    features = prepare_universe(add_features(panel))
    features = mark_weekly_observations(features)
    signal = apply_signal(features, config)
    liquid_weekly = features["weekly_observation"] & (features["adv20"] >= min_adv20)
    raw_mask = liquid_weekly & signal
    mask = collapse_signal_episodes(features, raw_mask)
    events = features.loc[mask].copy()
    control = features.loc[liquid_weekly].copy()

    rows = []
    for horizon in (5, 10, 20, 40):
        column = "fwd_%dd" % horizon
        sample = events[column].dropna()
        unconditional = control[column].dropna()
        event_mean = float(sample.mean()) if len(sample) else np.nan
        unconditional_mean = float(unconditional.mean()) if len(unconditional) else np.nan
        rows.append(
            {
                "horizon_days": horizon,
                "events": int(sample.size),
                "mean_forward_return": event_mean,
                "median_forward_return": float(sample.median()) if len(sample) else np.nan,
                "positive_ratio": float((sample > 0).mean()) if len(sample) else np.nan,
                "unconditional_observations": int(unconditional.size),
                "unconditional_mean_return": unconditional_mean,
                "incremental_mean_return": (
                    event_mean - unconditional_mean
                    if np.isfinite(event_mean) and np.isfinite(unconditional_mean)
                    else np.nan
                ),
            }
        )
    return events, pd.DataFrame(rows)


def parameter_grid():
    return [
        SignalConfig(flow, ret, dd, reversal, above)
        for flow, ret, dd, reversal, above in product(
            (-0.03, -0.05, -0.08, -0.12),
            (-0.04, -0.08, -0.12),
            (-0.10, -0.15, -0.20),
            (-0.02, 0.00, 0.02),
            (False, True),
        )
    ]


def screen_grid(panel, min_events=30, min_adv20=30_000_000):
    features = mark_weekly_observations(prepare_universe(add_features(panel)))
    rows = []
    for config in parameter_grid():
        signal = apply_signal(features, config)
        raw_mask = (
            features["weekly_observation"]
            & signal
            & (features["adv20"] >= min_adv20)
        )
        events = features.loc[collapse_signal_episodes(features, raw_mask)]
        sample = events["fwd_20d"].dropna()
        row = asdict(config)
        row.update(
            {
                "events": int(sample.size),
                "mean_fwd_20d": float(sample.mean()) if len(sample) else np.nan,
                "median_fwd_20d": float(sample.median()) if len(sample) else np.nan,
                "positive_ratio_20d": float((sample > 0).mean()) if len(sample) else np.nan,
                "enough_events": bool(sample.size >= min_events),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def run(panel_path, output_dir):
    panel = load_panel(panel_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    events, summary = event_study(panel)
    grid = screen_grid(panel)

    events.to_csv(output / "events.csv", index=False)
    summary.to_csv(output / "event_summary.csv", index=False)
    grid.to_csv(output / "parameter_grid.csv", index=False)
    return events, summary, grid


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("panel")
    parser.add_argument("output")
    args = parser.parse_args()
    run(args.panel, args.output)
