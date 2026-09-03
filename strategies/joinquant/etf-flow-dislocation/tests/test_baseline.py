import ast
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]


def load_research():
    path = FAMILY / "research.py"
    spec = importlib.util.spec_from_file_location("etf_flow_research", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_platform_baseline_is_parseable_and_causal():
    source = (FAMILY / "baseline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    assert "from __future__ import annotations" not in source
    assert "current_data.get(" not in source
    assert "current_data[code]" in source

    forbidden = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    ]
    assert forbidden == []


def test_protocol_is_frozen_before_results_and_matches_baseline_thresholds():
    protocol = json.loads(
        (FAMILY / "protocols" / "2026-08-25-v1.json").read_text(encoding="utf-8")
    )
    source = (FAMILY / "baseline.py").read_text(encoding="utf-8")
    assert protocol["frozen_before_results"] is True
    assert protocol["research_status_at_freeze"].endswith("no_backtest_or_event_result")
    assert 'g.max_flow_20 = -0.05' in source
    assert 'g.max_return_20 = -0.08' in source
    assert 'g.max_drawdown_60 = -0.12' in source
    assert protocol["coarse_grid"]["direct_trials"] == 216


def synthetic_panel():
    dates = pd.bdate_range("2025-01-01", periods=90)
    rows = []
    for code in ("FLOW", "CALM"):
        close = np.linspace(100.0, 102.0, len(dates))
        shares = np.full(len(dates), 100.0)
        if code == "FLOW":
            close = np.full(len(dates), 100.0)
            close[-21:] = np.linspace(100.0, 76.0, 21)
            close[-4:] = [76.0, 77.0, 79.0, 81.0]
            shares[-21:] = np.linspace(100.0, 90.0, 21)
        for i, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": close[i],
                    "close": close[i],
                    "money": 100_000_000.0,
                    "shares": shares[i],
                }
            )
    return pd.DataFrame(rows)


def test_forced_outflow_event_is_detected_but_calm_asset_is_not():
    research = load_research()
    features = research.mark_weekly_observations(
        research.add_features(synthetic_panel())
    )
    signal = research.apply_signal(features, research.SignalConfig())
    tail = features.assign(signal=signal).groupby("code").tail(5)
    assert tail.loc[tail["code"] == "FLOW", "signal"].any()
    assert not tail.loc[tail["code"] == "CALM", "signal"].any()


def test_forward_returns_are_labels_not_signal_inputs():
    research = load_research()
    features = research.add_features(synthetic_panel())
    base_signal = research.apply_signal(features, research.SignalConfig())
    modified = features.copy()
    for column in ["fwd_5d", "fwd_10d", "fwd_20d", "fwd_40d"]:
        modified[column] = np.random.default_rng(7).normal(size=len(modified))
    changed_signal = research.apply_signal(modified, research.SignalConfig())
    pd.testing.assert_series_equal(base_signal, changed_signal)


def test_grid_count_matches_protocol():
    research = load_research()
    assert len(research.parameter_grid()) == 216


def test_universe_enforces_listing_age_when_exported():
    research = load_research()
    panel = synthetic_panel()
    panel["start_date"] = panel["date"].min() - pd.Timedelta(days=300)
    panel.loc[panel["code"] == "FLOW", "start_date"] = panel["date"].min()
    features = research.add_features(panel)
    filtered = research.prepare_universe(features)
    assert "FLOW" not in set(filtered["code"])
    assert "CALM" in set(filtered["code"])


def test_persistent_weekly_signal_collapses_into_one_shock_episode():
    research = load_research()
    dates = pd.date_range("2025-01-03", periods=6, freq="7D")
    features = pd.DataFrame({"date": dates, "code": ["ETF"] * len(dates)})
    mask = pd.Series([True] * len(features))
    collapsed = research.collapse_signal_episodes(features, mask, cooldown_calendar_days=28)
    kept_dates = list(features.loc[collapsed, "date"])
    assert kept_dates == [dates[0], dates[4]]


def test_same_tracking_index_deduplicates_to_highest_causal_adv():
    research = load_research()
    date = pd.Timestamp("2025-06-27")
    features = pd.DataFrame(
        [
            {"date": date, "code": "A", "adv20": 80_000_000.0, "traced_index_code": "IDX", "domestic_equity": True},
            {"date": date, "code": "B", "adv20": 120_000_000.0, "traced_index_code": "IDX", "domestic_equity": True},
        ]
    )
    filtered = research.prepare_universe(features)
    assert list(filtered["code"]) == ["B"]


def test_export_script_contains_required_pit_inputs_and_gap_limit():
    source = (FAMILY / "joinquant_export.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "finance.FUND_SHARE_DAILY" in source
    assert "finance.FUND_INVEST_TARGET" in source
    assert 'ffill(limit=10)' in source
    assert 'historically_terminated_etfs' in source
