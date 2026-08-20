import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest


FAMILY = Path(__file__).resolve().parents[1]
ROOT = FAMILY.parents[2]
REFERENCE = ROOT / "joinquant_archive" / "sources" / "ETF轮动策略" / "五福7.5.py"
PROTOCOL = FAMILY / "protocols" / "2026-08-16-wufu-direct-decomposition-v1.json"
V3_PROTOCOL = FAMILY / "protocols" / "2026-08-21-wufu-tradability-v3.json"


def load_research():
    path = FAMILY / "research.py"
    spec = importlib.util.spec_from_file_location("wufu_research", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_a7_import():
    path = FAMILY / "a7_import.py"
    spec = importlib.util.spec_from_file_location("wufu_a7_import", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_protocol_freezes_reference_hash_before_results():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    digest = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    assert protocol["frozen_before_results"] is True
    assert digest == protocol["reference"]["source_sha256"]
    assert [stage["id"] for stage in protocol["stages"]] == [
        "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"
    ]


def test_weighted_trend_score_distinguishes_slope_and_quality():
    research = load_research()
    smooth = np.exp(np.linspace(0.0, 0.12, 26))
    noisy = smooth.copy()
    noisy[::2] *= 1.03
    smooth_result = research.weighted_trend_metrics(smooth, 25)
    noisy_result = research.weighted_trend_metrics(noisy, 25)
    assert smooth_result[0] > 0
    assert smooth_result[1] > noisy_result[1]
    assert np.isclose(smooth_result[2], smooth_result[0] * smooth_result[1])


def test_three_of_four_regime_vote_uses_only_supplied_history():
    research = load_research()
    closes = np.array(
        [
            [10.0] * 10 + [9.0],
            [20.0] * 10 + [19.0],
            [30.0] * 10 + [29.0],
            [40.0] * 10 + [41.0],
        ]
    ).T
    assert research.is_a_share_weak(closes, 10) is True
    assert research.is_a_share_weak(closes[:, [0, 1, 3]], 10) is False


def test_v3_direct_weak_vote_does_not_inherit_a4_hysteresis():
    research = load_research()
    closes = np.full((12, 4), 10.0)
    closes[10] = [9.0, 9.0, 9.0, 11.0]
    closes[11] = [9.5, 9.5, 10.5, 10.5]
    hysteretic, _ = research._regime_arrays(closes)
    direct = research._direct_weak_array(closes)
    assert hysteretic[10] and direct[10]
    assert hysteretic[11] and not direct[11]


def test_incumbent_buffer_retains_only_close_followers():
    research = load_research()
    ranked = [("A", 2.0), ("B", 1.85), ("C", 1.5)]
    assert research.select_with_buffer(ranked, ["B"], 1, 0.9) == ["B"]
    assert research.select_with_buffer(ranked, ["C"], 1, 0.9) == ["A"]
    assert research.select_with_buffer(ranked, ["B", "C"], 3, 0.9) == ["A", "B", "C"]


def test_ordinal_rank_buffer_retains_incumbents_only_inside_frozen_width():
    research = load_research()
    ranked = [(symbol, 10.0 - index) for index, symbol in enumerate("ABCDEFG")]
    assert research.select_with_rank_buffer(ranked, ["D", "E"], 3, 2) == [
        "A",
        "D",
        "E",
    ]
    assert research.select_with_rank_buffer(ranked, ["F"], 3, 2) == ["A", "B", "C"]
    assert research.select_with_rank_buffer(ranked, ["C"], 3, 0) == ["A", "B", "C"]


def test_rebalance_schedule_is_phase_stable_and_validated():
    research = load_research()
    hits = [
        day for day in range(15) if research.is_scheduled_rebalance(day, 5, phase=2)
    ]
    assert hits == [2, 7, 12]
    with pytest.raises(ValueError, match="phase"):
        research.is_scheduled_rebalance(0, 5, phase=5)


def test_non_rebalance_days_do_not_trade_even_with_adv_partial_fills(monkeypatch):
    research = load_research()
    dates = research.pd.bdate_range("2014-12-31", periods=8)
    symbols = (research.CASH_ETF, "SH510300")
    shape = (len(dates), len(symbols))
    prices = np.full(shape, 10.0)
    booleans = np.ones(shape, dtype=bool)
    universes = {
        name: [np.arange(len(symbols), dtype=int) for _ in dates]
        for name in (
            "fixed_only",
            "original_like",
            "pit_all_etf",
            "listed_by_2023_end",
        )
    }
    data = research.MarketData(
        dates=dates,
        symbols=symbols,
        symbol_to_index={symbol: index for index, symbol in enumerate(symbols)},
        adjusted_open=prices,
        adjusted_close=prices,
        raw_open=prices,
        raw_close=prices,
        volume=np.full(shape, 10_000.0),
        amount=np.full(shape, 100_000.0),
        adv3=np.full(shape, 100_000.0),
        adv20=np.full(shape, 100_000.0),
        ma10=prices,
        volume_ratio5=np.ones(shape),
        loss_floor3=booleans,
        divergence_ok=booleans,
        laplace_slope=np.ones(shape),
        master=research.pd.DataFrame(index=range(len(symbols))),
        index_close=np.ones((len(dates), 4)),
        weak_state=np.zeros(len(dates), dtype=bool),
        weak_vote_state=np.zeros(len(dates), dtype=bool),
        choppy_state=np.zeros(len(dates), dtype=bool),
        weak_lookback=np.full(len(dates), 25),
        universes=universes,
        global_universe=universes["fixed_only"],
        reference={},
        input_hashes={},
    )
    selection_rows = []

    def fixed_target(row, holdings, market_data, cache, config):
        selection_rows.append(row)
        return ["SH510300"], {"weak": False, "choppy": False}

    monkeypatch.setattr(research, "_select_targets", fixed_target)
    config = research.StrategyConfig(
        rebalance_interval_days=3,
        rebalance_phase=0,
        single_side_total_cost_bp=0.0,
        initial_cash=10_000.0,
        adv_participation=0.01,
    )
    result = research.run_simulation(
        data,
        research.FeatureCache(data),
        config,
        start="2015-01-01",
        end="2015-01-09",
        capture_details=True,
    )
    scheduled_dates = set(
        result.decisions.loc[
            result.decisions["scheduled_rebalance"], "execution_date"
        ]
    )
    assert selection_rows == [0, 3, 6]
    assert set(result.trades["trade_date"]).issubset(scheduled_dates)
    assert result.equity.loc[
        ~result.equity["trade_date"].isin(scheduled_dates), "gross_traded"
    ].eq(0.0).all()


def test_v3_protocol_configs_match_the_frozen_primary_and_matrix():
    research = load_research()
    protocol = json.loads(V3_PROTOCOL.read_text(encoding="utf-8"))
    primary = research.tradability_v3_primary_config()
    assert protocol["frozen_before_v3_results"] is True
    assert primary.name == "T3_primary"
    assert primary.top_k == 3
    assert primary.lookback == 25
    assert primary.use_r2 is False
    assert primary.use_ordinary_filters is True
    assert primary.ordinal_rank_buffer_extra == 2
    assert primary.rebalance_interval_days == 5
    assert primary.rebalance_phase == 0
    assert primary.use_regime is True
    assert primary.regime_pool_switch is True
    assert primary.regime_filter_relaxation is False
    assert primary.regime_dynamic_lookback is False
    assert primary.regime_buffer_disable is False
    assert primary.regime_use_hysteresis is False
    assert primary.use_mainline is False
    assert primary.use_retention is False
    assert primary.single_side_total_cost_bp == 10.0

    ordered = research.tradability_v3_ordered_configs()
    assert [config.name for config in ordered] == ["T0", "T1", "T2", "T3_primary"]
    structural = research.tradability_v3_structural_configs()
    assert len(structural) == protocol["matrix"]["structural_grid"]["direct_trials"]
    assert len({config.name for config in structural}) == len(structural)


def test_mainline_rule_is_exact_dense_conjunction():
    research = load_research()
    passing = {
        "scores": [5.1, 6.0, 7.0, 8.5, 10.5],
        "r2": [0.91, 0.92, 0.93, 0.94, 0.95],
        "volume_ratio": [1.8, 1.9, 2.0, 2.1, 2.2],
        "laplace_slope": [0.01] * 5,
    }
    assert research.evaluate_mainline_history(passing)
    failing = dict(passing)
    failing["volume_ratio"] = [1.7] * 5
    assert not research.evaluate_mainline_history(failing)


def test_platform_baseline_is_parseable_and_causal():
    source = (FAMILY / "baseline.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    assert "from __future__ import annotations" not in source


def test_v3_platform_work_package_is_parseable_causal_and_scheduled():
    source = (FAMILY / "platform" / "tradability_v3_primary.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    assert "REBALANCE_INTERVAL = 5" in source
    assert "TOP_K = 3" in source
    assert "RANK_BUFFER_EXTRA = 2" in source
    assert "below >= 3" in source
    assert "from __future__ import annotations" not in source
    assert "mainline" not in source
    direct_builtins = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    ]
    assert direct_builtins == []
    assert "current_data.get(" not in source
    assert "current_data[code]" in source


def test_a7_platform_calibration_is_parseable_and_keeps_targets_fixed():
    source = (FAMILY / "platform" / "a7_minute_calibration.py").read_text(
        encoding="utf-8"
    )
    ast.parse(source)
    assert "a7-switch-events.csv" in source
    assert 'baseline_time": "13:10"' in source
    assert "target and 13:10 exit frozen" in source
    assert "from __future__ import annotations" not in source
    assert ".tail(30).to_numpy(" not in source


def test_a7_frozen_platform_summaries_aggregate_exactly():
    a7_import = load_a7_import()
    payload = a7_import.load_platform_run()
    summary = a7_import.aggregate_segments(payload, base_trading_days=2808)
    assert summary["requested_events"] == 891
    assert summary["valid_events"] == 891
    assert sum(summary["confirmation_counts"].values()) == 891
    assert summary["confirmation_counts"] == {
        "13:10": 262,
        "13:40": 142,
        "14:10": 120,
        "14:40": 94,
        "14:55": 273,
    }
    assert summary["forced_1455_ratio"] == pytest.approx(0.3063973063973064)
    assert summary["mean_entry_edge_bp"] == pytest.approx(5.058175414477158)
    assert summary["positive_entry_edge_ratio"] == pytest.approx(
        0.2716049382716049
    )
    assert summary["paired_trade_return_delta"] == pytest.approx(
        0.00044193058356293256
    )
    assert summary["relative_wealth_from_entry_only"] == pytest.approx(
        0.5286204020507015
    )
    assert summary["relative_annualized_from_entry_only"] == pytest.approx(
        0.038818588712748126
    )


def test_a7_platform_hash_validation_rejects_tampering(tmp_path):
    a7_import = load_a7_import()
    payload = json.loads(a7_import.DEFAULT_RUN_FILE.read_text(encoding="utf-8"))
    payload["input"]["repository_compatible_script_sha256"] = "0" * 64
    tampered = tmp_path / "tampered-a7-platform-run.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="script hash mismatch"):
        a7_import.load_platform_run(tampered)
