import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_selection_alpha.py"
SPEC = importlib.util.spec_from_file_location("oneil_selection_alpha", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_prepare_growth_rows_never_turns_negative_base_into_growth():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "report_date": pd.to_datetime(
                ["2023-03-31", "2024-03-31", "2023-03-31", "2024-03-31"]
            ),
            "notice_date": pd.to_datetime(
                ["2023-04-20", "2024-04-20", "2023-04-20", "2024-04-20"]
            ),
            "quarter_parent_net_profit": [100.0, 150.0, -100.0, 20.0],
            "quarter_revenue": [200.0, 260.0, 200.0, 260.0],
        }
    )

    result = MODULE.prepare_growth_rows(frame).set_index(["symbol", "report_date"])

    assert result.loc[("AAA", pd.Timestamp("2024-03-31")), "profit_growth"] == 0.5
    assert result.loc[("AAA", pd.Timestamp("2024-03-31")), "revenue_growth"] == pytest.approx(0.3)
    assert np.isnan(result.loc[("BBB", pd.Timestamp("2024-03-31")), "profit_growth"])
    assert result.loc[("BBB", pd.Timestamp("2024-03-31")), "previous_profit"] == -100.0
    assert result.loc[("BBB", pd.Timestamp("2024-03-31")), "current_profit"] == 20.0
    assert result.loc[
        ("BBB", pd.Timestamp("2024-03-31")), "turnaround_improvement"
    ] == pytest.approx(1.0)
    assert result.loc[("BBB", pd.Timestamp("2024-03-31")), "growth_track"] == "emerging"
    assert result.loc[("AAA", pd.Timestamp("2024-03-31")), "growth_track"] == "established"


def test_prepare_growth_rows_requires_strict_prior_year_and_real_improvement():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "BBB", "BBB"],
            "report_date": pd.to_datetime(
                ["2022-03-31", "2024-03-31", "2025-03-31", "2023-03-31", "2024-03-31"]
            ),
            "notice_date": pd.to_datetime(
                ["2022-04-20", "2024-04-20", "2025-04-20", "2023-04-20", "2024-04-20"]
            ),
            "quarter_parent_net_profit": [-100.0, -20.0, -30.0, -50.0, -25.0],
            "quarter_revenue": [100.0, 150.0, 160.0, 100.0, 120.0],
        }
    )

    result = MODULE.prepare_growth_rows(frame).set_index(["symbol", "report_date"])

    # 2022 -> 2024 is not a valid same-quarter prior-year comparison.
    assert pd.isna(result.loc[("AAA", pd.Timestamp("2024-03-31")), "previous_profit"])
    assert pd.isna(
        result.loc[("AAA", pd.Timestamp("2024-03-31")), "turnaround_improvement"]
    )
    # Loss widening is not an emerging candidate.
    assert pd.isna(result.loc[("AAA", pd.Timestamp("2025-03-31")), "growth_track"])
    # Loss narrowing without crossing zero is a valid improvement.
    assert result.loc[("BBB", pd.Timestamp("2024-03-31")), "growth_track"] == "emerging"
    assert result.loc[
        ("BBB", pd.Timestamp("2024-03-31")), "turnaround_improvement"
    ] == pytest.approx(1.0 / 3.0)


def test_profit_growth_acceleration_requires_adjacent_fiscal_quarters():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"] * 4 + ["BBB"] * 4,
            "report_date": pd.to_datetime(
                [
                    "2023-03-31", "2023-06-30", "2024-03-31", "2024-06-30",
                    "2023-03-31", "2023-09-30", "2024-03-31", "2024-09-30",
                ]
            ),
            "notice_date": pd.to_datetime(
                [
                    "2023-04-20", "2023-08-20", "2024-04-20", "2024-08-20",
                    "2023-04-20", "2023-10-20", "2024-04-20", "2024-10-20",
                ]
            ),
            "quarter_parent_net_profit": [100, 200, 150, 250, 100, 200, 150, 300],
            "quarter_revenue": [100, 200, 150, 250, 100, 200, 150, 300],
            "annual_roe": [np.nan] * 8,
        }
    )

    result = MODULE.prepare_growth_rows(frame).set_index(["symbol", "report_date"])

    assert result.loc[
        ("AAA", pd.Timestamp("2024-06-30")), "profit_growth_acceleration"
    ] == pytest.approx(-0.25)
    assert pd.isna(
        result.loc[
            ("BBB", pd.Timestamp("2024-09-30")), "profit_growth_acceleration"
        ]
    )


def test_latest_annual_quality_snapshot_respects_announcement_and_age():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB"],
            "report_date": pd.to_datetime(["2022-12-31", "2023-12-31", "2021-12-31"]),
            "notice_date": pd.to_datetime(["2023-03-20", "2024-04-20", "2022-03-20"]),
            "annual_roe": [12.0, 99.0, 20.0],
        }
    )

    result = MODULE.latest_annual_quality_snapshot(
        frame, "2024-04-01", maximum_age_days=550
    )

    assert result[["symbol", "latest_annual_roe"]].to_dict("records") == [
        {"symbol": "AAA", "latest_annual_roe": 12.0}
    ]


def test_latest_growth_snapshot_respects_notice_date_and_staleness():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB"],
            "report_date": pd.to_datetime(["2023-12-31", "2024-03-31", "2023-06-30"]),
            "notice_date": pd.to_datetime(["2024-03-01", "2024-05-01", "2023-08-01"]),
            "profit_growth": [0.2, 9.0, 0.3],
            "revenue_growth": [0.1, 9.0, 0.2],
        }
    )

    result = MODULE.latest_growth_snapshot(frame, "2024-04-01", maximum_age_days=220)

    assert result["symbol"].tolist() == ["AAA"]
    assert result.loc[0, "report_date"] == pd.Timestamp("2023-12-31")
    assert result.loc[0, "notice_date"] <= pd.Timestamp("2024-04-01")


def test_model_selection_changes_only_registered_signal_dimension():
    features = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "profit_growth": [0.9, 0.7, 0.5, 0.3, 0.1],
            "revenue_growth": [0.9, 0.7, 0.5, 0.3, 0.1],
            "momentum_12_1": [0.2, 0.8, 0.7, 0.6, 0.9],
            "amount_20": [100, 100, 100, 100, 1],
        }
    )

    growth = MODULE.select_candidates(features, "pure-growth", positions=2)
    momentum = MODULE.select_candidates(features, "pure-momentum", positions=2)
    combined = MODULE.select_candidates(features, "growth-momentum", positions=2)
    intersection = MODULE.select_candidates(
        features, "huachuang-2-lite", positions=2, percentile_cutoff=0.6
    )

    assert growth["symbol"].tolist() == ["A", "B"]
    assert momentum["symbol"].tolist() == ["B", "C"]
    assert combined["symbol"].tolist() == ["B", "A"]
    assert intersection["symbol"].tolist() == ["B"]
    assert "E" not in set(pd.concat([growth, momentum, combined, intersection])["symbol"])


def test_emerging_models_and_dual_track_keep_tracks_separate():
    symbols = [f"E{i:02d}" for i in range(12)] + [f"G{i:02d}" for i in range(24)]
    tracks = ["emerging"] * 12 + ["established"] * 24
    sequence = np.arange(len(symbols), dtype=float)
    features = pd.DataFrame(
        {
            "symbol": symbols,
            "growth_track": tracks,
            "profit_growth": np.where(np.array(tracks) == "established", sequence, np.nan),
            "revenue_growth": sequence + 1.0,
            "turnaround_improvement": np.where(
                np.array(tracks) == "emerging", sequence + 1.0, np.nan
            ),
            "momentum_12_1": sequence + 2.0,
            "amount_20": np.full(len(symbols), 100.0),
        }
    )

    emerging = MODULE.select_candidates(
        features, "emerging-improvement", positions=30, liquidity_keep=1.0
    )
    emerging_momentum = MODULE.select_candidates(
        features, "emerging-momentum", positions=30, liquidity_keep=1.0
    )
    dual = MODULE.select_candidates(
        features, "dual-track-growth-momentum", positions=30, liquidity_keep=1.0
    )

    assert len(emerging) == 12
    assert set(emerging["growth_track"]) == {"emerging"}
    assert len(emerging_momentum) == 12
    assert len(dual) == 30
    assert (dual["growth_track"] == "established").sum() == 20
    assert (dual["growth_track"] == "emerging").sum() == 10
    assert dual["symbol"].is_unique


def test_quality_and_acceleration_models_add_only_registered_rank():
    features = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "growth_track": ["established"] * 3,
            "profit_growth": [3.0, 2.0, 1.0],
            "revenue_growth": [3.0, 2.0, 1.0],
            "profit_growth_acceleration": [1.0, 3.0, 0.0],
            "latest_annual_roe": [1.0, 3.0, 2.0],
            "turnaround_improvement": [np.nan] * 3,
            "momentum_12_1": [1.0, 2.0, 3.0],
            "amount_20": [100.0] * 3,
        }
    )

    quality = MODULE.select_candidates(
        features, "quality-growth-momentum", positions=1, liquidity_keep=1.0
    )
    acceleration = MODULE.select_candidates(
        features, "growth-acceleration-momentum", positions=1, liquidity_keep=1.0
    )

    assert quality["symbol"].tolist() == ["B"]
    assert acceleration["symbol"].tolist() == ["B"]


def test_quality_model_supports_preregistered_weight_neighborhood():
    features = pd.DataFrame(
        {
            "symbol": ["GROWTH", "QUALITY"],
            "growth_track": ["established", "established"],
            "profit_growth": [2.0, 1.0],
            "revenue_growth": [2.0, 1.0],
            "latest_annual_roe": [1.0, 2.0],
            "momentum_12_1": [2.0, 1.0],
            "amount_20": [100.0, 100.0],
        }
    )

    growth_tilt = MODULE.select_candidates(
        features,
        "quality-growth-momentum",
        positions=2,
        liquidity_keep=1.0,
        growth_weight=0.375,
        momentum_weight=0.375,
        quality_weight=0.25,
    )
    quality_tilt = MODULE.select_candidates(
        features,
        "quality-growth-momentum",
        positions=2,
        liquidity_keep=1.0,
        growth_weight=0.30,
        momentum_weight=0.30,
        quality_weight=0.40,
    )

    growth_scores = growth_tilt.set_index("symbol")["quality_growth_momentum_score"]
    quality_scores = quality_tilt.set_index("symbol")["quality_growth_momentum_score"]
    assert growth_scores["GROWTH"] > growth_scores["QUALITY"]
    assert quality_scores["GROWTH"] > quality_scores["QUALITY"]
    assert (
        quality_scores["GROWTH"] - quality_scores["QUALITY"]
        < growth_scores["GROWTH"] - growth_scores["QUALITY"]
    )


def test_target_weights_enforce_five_percent_cap_and_keep_cash():
    weights = MODULE.target_weights(["A", "B", "C"], exposure=0.95, maximum_weight=0.05)

    assert weights == {"A": 0.05, "B": 0.05, "C": 0.05}
    assert sum(weights.values()) == pytest.approx(0.15)


def test_market_exposure_uses_only_observation_day_values():
    assert MODULE.market_exposure(100.0, 99.0, risk_on=0.95, risk_off=0.5) == 0.95
    assert MODULE.market_exposure(98.0, 99.0, risk_on=0.95, risk_off=0.5) == 0.5
    assert MODULE.market_exposure(np.nan, 99.0, risk_on=0.95, risk_off=0.5) == 0.5
