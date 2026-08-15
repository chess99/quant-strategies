# -*- coding: utf-8 -*-
"""JoinQuant Research point-in-time golden probe for ETF Core Rotation v1."""

import hashlib
import json
import os
import shutil

import numpy as np
import pandas as pd
from jqdata import get_all_trade_days

import baseline as strategy


RUN_ID = "etf-core-pit-golden-20260816-v1"
PROBE_DATES = [
    "2014-01-03",
    "2015-06-12",
    "2015-08-21",
    "2016-01-29",
    "2018-06-29",
    "2018-12-28",
    "2020-03-20",
    "2020-07-10",
    "2021-02-19",
    "2022-04-29",
    "2022-10-28",
    "2023-12-29",
    "2024-02-02",
    "2024-09-27",
    "2025-04-03",
    "2025-12-26",
    "2026-07-24",
]


class _State(object):
    pass


class _Log(object):
    def __init__(self):
        self.messages = []

    def _append(self, level, message):
        text = "{} {}".format(level, message)
        self.messages.append(text)
        print(text)

    def info(self, message):
        self._append("INFO", message)

    def warning(self, message):
        self._append("WARNING", message)

    def error(self, message):
        self._append("ERROR", message)


class _Portfolio(object):
    def __init__(self, total_value):
        self.total_value = float(total_value)
        self.positions = {}


class _Context(object):
    def __init__(self, observation_date, total_value):
        self.previous_date = observation_date
        self.observation_date = observation_date
        self.portfolio = _Portfolio(total_value)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _configure_strategy():
    strategy.g = _State()
    strategy.log = _Log()
    g = strategy.g
    g.lookbacks = (63, 126, 252)
    g.min_positive_horizons = 2
    g.top_k = 3
    g.rank_buffer = 2
    g.corr_lookback = 60
    g.max_pair_corr = 0.90
    g.vol_lookback = 60
    g.target_portfolio_vol = 0.18
    g.max_single_risk_weight = 0.40
    g.vol_floor = 0.08
    g.min_history_bars = 253
    g.min_listing_calendar_days = 300
    g.liquidity_lookback = 20
    g.min_adv20 = 20000000
    g.min_liquidity_observations = 15
    g.max_adv_participation = 0.005
    g.min_trade_value = 2000
    g.min_weight_change = 0.03
    g.gold_etf = "518880.XSHG"
    g.defensive_bond_etfs = ["511010.XSHG", "511260.XSHG"]
    g.cash_etf = "511880.XSHG"
    g.exclude_keywords = [
        "货币", "现金", "短融", "国债", "政金债", "信用债", "债券", "转债",
        "同业存单", "城投债", "地方债", "公司债", "黄金", "白银", "原油",
        "豆粕", "商品", "纳指", "纳斯达克", "标普", "道琼斯", "日经", "德国",
        "法国", "沙特", "恒生", "港股", "香港", "中概", "H股", "海外", "中韩",
        "REIT", "Reit", "reit",
    ]
    g.last_rebalance_date = None
    g.last_universe = []
    g.last_adv20 = {}
    g.last_metrics = None
    return g


def _observations():
    calendar = pd.DatetimeIndex(pd.to_datetime(get_all_trade_days())).sort_values()
    observations = []
    for requested in PROBE_DATES:
        eligible = calendar[calendar <= pd.Timestamp(requested)]
        if len(eligible):
            observations.append((requested, pd.Timestamp(eligible[-1])))
    return observations


def _capture_tracking():
    captured = {}
    original = strategy.get_point_in_time_tracking_map

    def wrapper(codes, as_of):
        result = original(codes, as_of)
        captured[pd.Timestamp(as_of).date().isoformat()] = result
        return result

    strategy.get_point_in_time_tracking_map = wrapper
    return captured, original


def run(output_root="exports"):
    _configure_strategy()
    captured, original_tracking = _capture_tracking()
    summary_rows = []
    member_rows = []
    try:
        for requested, observation in _observations():
            print("PROBE {} -> {}".format(requested, observation.date().isoformat()))
            universe, adv20 = strategy.build_risk_universe(observation.date())
            metrics, close_matrix = strategy.compute_risk_metrics(universe, observation.date())
            if metrics is None or metrics.empty:
                ranked = pd.DataFrame()
                selected = []
                targets = strategy.build_defensive_only_weights(observation.date())
            else:
                ranked = strategy.rank_candidates(metrics)
                passed = ranked[ranked["abs_pass"]].copy()
                context = _Context(observation.date(), 1000000)
                selected = strategy.select_assets_with_buffer(context, passed, close_matrix)
                risk_weights = strategy.build_risk_weights(
                    selected, ranked, close_matrix, context, adv20
                )
                targets = strategy.add_defensive_sleeve(risk_weights, observation.date())
            tracking = captured.get(observation.date().isoformat(), {})
            summary_rows.append(
                {
                    "requested_date": requested,
                    "observation_date": observation.date().isoformat(),
                    "universe_count": len(universe),
                    "ranked_count": len(ranked),
                    "absolute_momentum_pass_count": (
                        int(ranked["abs_pass"].sum()) if not ranked.empty else 0
                    ),
                    "selected": ";".join(selected),
                    "target_weights": json.dumps(
                        targets, ensure_ascii=False, sort_keys=True
                    ),
                }
            )
            for code, row in ranked.iterrows():
                info = tracking.get(code, {})
                member_rows.append(
                    {
                        "observation_date": observation.date().isoformat(),
                        "symbol": code,
                        "tracking_code": info.get("traced_index_code", ""),
                        "tracking_name": info.get("traced_index_name", ""),
                        "adv20": float(adv20.get(code, np.nan)),
                        "r63": float(row["r63"]),
                        "r126": float(row["r126"]),
                        "r252": float(row["r252"]),
                        "vol60": float(row["vol60"]),
                        "score": float(row["score"]),
                        "abs_pass": bool(row["abs_pass"]),
                        "rank": int(row["rank"]),
                        "selected": code in selected,
                    }
                )
    finally:
        strategy.get_point_in_time_tracking_map = original_tracking

    output = os.path.join(output_root, RUN_ID)
    if os.path.exists(output):
        raise RuntimeError("refusing to overwrite {}".format(output))
    raw = os.path.join(output, "raw")
    os.makedirs(raw)
    summary = pd.DataFrame(summary_rows)
    members = pd.DataFrame(member_rows)
    summary.to_csv(os.path.join(raw, "joinquant-probe-summary.csv"), index=False)
    members.to_csv(os.path.join(raw, "joinquant-probe-members.csv"), index=False)
    with open(os.path.join(raw, "log.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(strategy.log.messages))
    manifest = {
        "schema_version": 1,
        "platform": "joinquant-research",
        "strategy_id": "etf-core-rotation",
        "variant": "pit-golden-probe",
        "run_id": RUN_ID,
        "probe_dates": len(summary_rows),
        "member_rows": len(member_rows),
        "baseline_sha256": _sha256(strategy.__file__),
        "probe_sha256": _sha256(__file__),
        "limitations": [
            "Isolated probe dates use an empty starting portfolio, so rank buffer retention is not tested.",
            "This probe validates JoinQuant Research data and target construction, not official 10:30 fills.",
        ],
    }
    with open(os.path.join(output, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    shutil.copy2(strategy.__file__, os.path.join(output, "baseline.py"))
    shutil.copy2(__file__, os.path.join(output, "source.py"))
    bundle = shutil.make_archive(output, "zip", root_dir=output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("BUNDLE {}".format(bundle))
    return summary, members, manifest, bundle


if __name__ == "__main__":
    run()
