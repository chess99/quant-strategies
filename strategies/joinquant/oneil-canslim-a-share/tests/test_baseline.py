from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "baseline.py"


class LazyCurrentData(dict):
    """Only ``mapping[key]`` materializes a JoinQuant-style snapshot."""

    def __init__(self, snapshots):
        super().__init__()
        self.snapshots = snapshots

    def __missing__(self, key):
        snapshot = self.snapshots[key]
        self[key] = snapshot
        return snapshot


def load_strategy():
    spec = importlib.util.spec_from_file_location("oneil_canslim_quant", STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_quarterly_history():
    return pd.DataFrame(
        [
            {
                "code": "000001.XSHE",
                "statDate": "2024-03-31",
                "adjusted_profit": 10.0,
                "np_parent_company_owners": 11.0,
                "total_operating_revenue": 100.0,
                "basic_eps": 1.0,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2024-06-30",
                "adjusted_profit": 15.0,
                "np_parent_company_owners": 16.0,
                "total_operating_revenue": 120.0,
                "basic_eps": 1.5,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2024-09-30",
                "adjusted_profit": 20.0,
                "np_parent_company_owners": 22.0,
                "total_operating_revenue": 140.0,
                "basic_eps": 2.0,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2024-12-31",
                "adjusted_profit": 25.0,
                "np_parent_company_owners": 27.0,
                "total_operating_revenue": 160.0,
                "basic_eps": 2.5,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2025-03-31",
                "adjusted_profit": 15.0,
                "np_parent_company_owners": 16.0,
                "total_operating_revenue": 130.0,
                "basic_eps": 1.5,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2025-06-30",
                "adjusted_profit": 23.0,
                "np_parent_company_owners": 25.0,
                "total_operating_revenue": 155.0,
                "basic_eps": 2.3,
            },
        ]
    )


def make_annual_history():
    return pd.DataFrame(
        [
            {
                "code": "000001.XSHE",
                "statDate": "2021-12-31",
                "adjusted_profit": 10.0,
                "np_parent_company_owners": 11.0,
                "total_operating_revenue": 100.0,
                "basic_eps": 1.0,
                "roe": 18.0,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2022-12-31",
                "adjusted_profit": 13.0,
                "np_parent_company_owners": 14.0,
                "total_operating_revenue": 125.0,
                "basic_eps": 1.3,
                "roe": 18.5,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2023-12-31",
                "adjusted_profit": 17.0,
                "np_parent_company_owners": 18.0,
                "total_operating_revenue": 155.0,
                "basic_eps": 1.7,
                "roe": 19.0,
            },
            {
                "code": "000001.XSHE",
                "statDate": "2024-12-31",
                "adjusted_profit": 22.0,
                "np_parent_company_owners": 23.0,
                "total_operating_revenue": 195.0,
                "basic_eps": 2.2,
                "roe": 20.0,
            },
        ]
    )


def make_price_frame(
    *,
    final_close=102.0,
    final_high=103.0,
    final_volume=150.0,
    include_breakout=True,
):
    count = 130
    times = pd.date_range("2025-01-01", periods=count, freq="B")
    close = np.linspace(75.0, 95.0, count)
    high = close + 1.0
    low = close - 1.0
    volume = np.full(count, 100.0)

    # A controlled 13-week base: 20% depth, tightening into a 100 pivot.
    close[-66:-45] = np.linspace(100.0, 81.0, 21)
    close[-45:-21] = np.linspace(82.0, 98.0, 24)
    close[-21:-1] = np.linspace(95.0, 99.0, 20)
    high[-66:-1] = np.minimum(close[-66:-1] + 1.0, 100.0)
    low[-66:-1] = close[-66:-1] - 1.0
    volume[-11:-1] = 80.0

    if include_breakout:
        close[-1] = final_close
        high[-1] = final_high
        low[-1] = min(final_close - 1.0, 100.0)
        volume[-1] = final_volume
    else:
        close[-1] = 98.5
        high[-1] = 99.0
        low[-1] = 97.5
        volume[-1] = 80.0

    return pd.DataFrame(
        {
            "time": times,
            "code": ["000001.XSHE"] * count,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
            "money": volume * close * 10000.0,
        }
    )


def make_confirmed_market():
    times = pd.date_range("2025-01-01", periods=100, freq="B")
    close = list(np.linspace(110.0, 90.0, 70))
    volume = [100.0] * 70
    low = [value - 0.5 for value in close]

    # Day 1 rally attempt followed by a valid day-4 follow-through.
    tail_close = [91.0, 91.4, 91.8, 93.6]
    tail_volume = [95.0, 96.0, 97.0, 130.0]
    close.extend(tail_close)
    volume.extend(tail_volume)
    low.extend([89.8, 90.8, 91.0, 91.5])

    while len(close) < 100:
        close.append(close[-1] * 1.001)
        volume.append(100.0)
        low.append(close[-1] - 0.5)

    return pd.DataFrame(
        {
            "time": times,
            "code": ["000001.XSHG"] * len(times),
            "close": close,
            "high": np.asarray(close) + 0.5,
            "low": low,
            "volume": volume,
            "money": np.asarray(volume) * np.asarray(close),
        }
    )


def test_strategy_source_is_joinquant_legacy_compatible_and_self_contained():
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "from __future__ import annotations" not in source
    assert "from **future** import annotations" not in source
    assert "strict=" not in source
    assert "import trading_os" not in source
    assert "current_data.get(" not in source
    unqualified = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"all", "any", "sum"}
    ]
    assert unqualified == []


def test_point_in_time_boundaries_are_explicit_in_platform_source():
    source = STRATEGY_PATH.read_text(encoding="utf-8")

    assert 'get_all_securities(["stock"], date=observation_date)' in source
    assert "watch_date=observation_date" in source
    assert "get_industry(batch, date=observation_date)" in source
    assert "end_date=observation_date" in source
    assert 'set_option("avoid_future_data", True)' in source


def test_fundamental_source_uses_accounting_eps_not_paidin_capital_as_share_count():
    source = STRATEGY_PATH.read_text(encoding="utf-8")

    assert "income.basic_eps" in source
    assert "balance.paidin_capital" not in source


def test_safe_growth_rejects_zero_negative_and_missing_bases():
    strategy = load_strategy()

    assert strategy.safe_growth(125.0, 100.0) == 0.25
    assert math.isnan(strategy.safe_growth(10.0, 0.0))
    assert math.isnan(strategy.safe_growth(10.0, -2.0))
    assert math.isnan(strategy.safe_growth(np.nan, 10.0))


def test_joinquant_single_quarter_history_is_not_differenced_a_second_time():
    strategy = load_strategy()

    quarterly = strategy.prepare_quarterly_frame(make_quarterly_history())
    q2_2024 = quarterly.loc[
        quarterly["statDate"] == pd.Timestamp("2024-06-30")
    ].iloc[0]
    q4_2024 = quarterly.loc[
        quarterly["statDate"] == pd.Timestamp("2024-12-31")
    ].iloc[0]
    q2_2025 = quarterly.loc[
        quarterly["statDate"] == pd.Timestamp("2025-06-30")
    ].iloc[0]

    assert q2_2024["adjusted_profit"] == 15.0
    assert q2_2024["total_operating_revenue"] == 120.0
    assert q4_2024["adjusted_profit"] == 25.0
    assert q4_2024["total_operating_revenue"] == 160.0
    assert q2_2025["adjusted_profit"] == 23.0
    assert q2_2025["total_operating_revenue"] == 155.0


def test_missing_adjacent_quarter_does_not_break_same_quarter_year_on_year_alignment():
    strategy = load_strategy()
    incomplete = make_quarterly_history().loc[
        lambda frame: frame["statDate"] != "2024-03-31"
    ]

    features = strategy.build_fundamental_features(
        "000001.XSHE",
        incomplete,
        make_annual_history(),
    )

    assert features is not None
    assert round(features["current_eps_growth"], 6) == round(2.3 / 1.5 - 1.0, 6)
    assert math.isnan(features["eps_growth_acceleration"])


def test_fundamental_features_measure_current_and_annual_per_share_growth():
    strategy = load_strategy()

    features = strategy.build_fundamental_features(
        "000001.XSHE",
        make_quarterly_history(),
        make_annual_history(),
    )

    assert features is not None
    assert round(features["current_eps_growth"], 6) == round(2.3 / 1.5 - 1.0, 6)
    assert round(features["core_profit_growth"], 6) == round(23.0 / 15.0 - 1.0, 6)
    assert round(features["current_sales_growth"], 6) == round(155.0 / 120.0 - 1.0, 6)
    assert features["eps_growth_acceleration"] > 0
    assert round(features["annual_eps_cagr"], 6) == round((2.2 / 1.0) ** (1 / 3) - 1, 6)
    assert features["annual_eps_increasing"]
    assert features["roe"] == 0.20


def test_missing_adjusted_profit_is_not_replaced_with_ordinary_profit():
    strategy = load_strategy()
    quarterly = make_quarterly_history()
    quarterly.loc[
        quarterly["statDate"].isin(["2024-06-30", "2025-06-30"]),
        "adjusted_profit",
    ] = np.nan

    features = strategy.build_fundamental_features(
        "000001.XSHE",
        quarterly,
        make_annual_history(),
    )

    assert math.isnan(features["core_profit_growth"])


def test_financial_report_age_is_measured_and_stale_reports_are_vetoed():
    strategy = load_strategy()
    features = strategy.build_fundamental_features(
        "000001.XSHE",
        make_quarterly_history(),
        make_annual_history(),
        observation_date=dt.date(2026, 3, 1),
    )

    assert features["current_report_age_days"] > strategy.MAX_REPORT_AGE_DAYS
    row = dict(features)
    row.update(
        {
            "rs_rating": 90.0,
            "industry_rs_rating": 90.0,
            "setup_ready": True,
            "average_money_20d": strategy.MIN_AVERAGE_MONEY,
        }
    )
    assert "stale_financials" in strategy._candidate_vetoes(row)
    row["current_report_age_days"] = np.nan
    assert "stale_financials" in strategy._candidate_vetoes(row)


def test_joinquant_roe_is_always_interpreted_as_a_percentage_field():
    strategy = load_strategy()
    annual = make_annual_history()
    annual.loc[annual["statDate"] == "2024-12-31", "roe"] = 0.92

    features = strategy.build_fundamental_features(
        "000001.XSHE",
        make_quarterly_history(),
        annual,
    )

    assert features is not None
    assert round(features["roe"], 6) == 0.0092


def test_weighted_relative_strength_emphasizes_the_latest_quarter():
    strategy = load_strategy()
    anchors = np.array([100.0, 110.0, 121.0, 133.1, 159.72])
    close = np.concatenate(
        [
            np.linspace(anchors[index], anchors[index + 1], 63, endpoint=False)
            for index in range(4)
        ]
        + [np.array([anchors[-1]])]
    )

    score = strategy.weighted_relative_strength(pd.Series(close))

    assert len(close) == 253
    assert round(score, 6) == 0.14


def test_relative_strength_is_ranked_across_the_full_liquid_universe():
    strategy = load_strategy()
    times = pd.date_range("2024-01-01", periods=253, freq="B")
    frames = []
    for code, ending in (("LEADER", 220.0), ("MIDDLE", 150.0), ("LAGGARD", 110.0)):
        close = np.linspace(100.0, ending, len(times))
        frames.append(
            pd.DataFrame(
                {
                    "time": times,
                    "code": code,
                    "close": close,
                }
            )
        )
    prices = pd.concat(frames, ignore_index=True)
    industries = {"LEADER": "行业A", "MIDDLE": "行业A", "LAGGARD": "行业B"}

    ranked = strategy.build_relative_strength_features(prices, industries)

    ratings = ranked.set_index("code")["rs_rating"]
    assert ratings["LEADER"] == 100.0
    assert ratings["LEADER"] > ratings["MIDDLE"] > ratings["LAGGARD"]
    industry_ratings = ranked.set_index("code")["industry_rs_rating"]
    assert industry_ratings["LEADER"] == industry_ratings["MIDDLE"]
    assert industry_ratings["LEADER"] > industry_ratings["LAGGARD"]


def test_price_fetch_can_request_close_only_for_full_market_ranking(monkeypatch):
    strategy = load_strategy()
    calls = []
    raw = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-14", "2026-07-15"]),
            "code": ["000001.XSHE", "000001.XSHE"],
            "close": [10.0, 11.0],
        }
    )

    def fake_get_price(*args, **kwargs):
        calls.append(kwargs)
        return raw

    monkeypatch.setattr(strategy, "get_price", fake_get_price, raising=False)
    result = strategy._fetch_price_history(
        ["000001.XSHE"],
        dt.date(2026, 7, 15),
        count=2,
        fields=["close"],
    )

    assert calls[0]["fields"] == ["close"]
    assert list(result["close"]) == [10.0, 11.0]


def test_base_breakout_requires_pivot_proximity_and_fifty_day_volume_expansion():
    strategy = load_strategy()
    valid = strategy.detect_breakout(make_price_frame())
    quiet = strategy.detect_breakout(make_price_frame(final_volume=120.0))
    extended = strategy.detect_breakout(
        make_price_frame(final_close=106.0, final_high=107.0)
    )
    setup = strategy.analyze_base_setup(make_price_frame(include_breakout=False))

    assert valid["is_breakout"]
    assert valid["pivot"] == 100.0
    assert valid["volume_ratio"] >= 1.4
    assert not quiet["is_breakout"]
    assert "volume" in quiet["reasons"]
    assert not extended["is_breakout"]
    assert "extended" in extended["reasons"]
    assert setup["setup_ready"]
    assert 0.05 <= setup["base_depth"] <= 0.35


def test_market_state_requires_a_day_four_or_later_follow_through():
    strategy = load_strategy()

    state = strategy.classify_market_regime(make_confirmed_market())

    assert state["state"] == strategy.MARKET_CONFIRMED
    assert state["follow_through_date"] is not None
    assert state["distribution_days"] < strategy.MAX_DISTRIBUTION_DAYS


def test_five_recent_distribution_days_invalidate_a_confirmed_market():
    strategy = load_strategy()
    market = make_confirmed_market()
    next_time = market["time"].iloc[-1]
    rows = []
    close = market["close"].iloc[-1]
    volume = 100.0
    for _ in range(strategy.MAX_DISTRIBUTION_DAYS):
        next_time += pd.offsets.BDay(1)
        close *= 0.995
        volume += 10.0
        rows.append(
            {
                "time": next_time,
                "code": "000001.XSHG",
                "close": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "volume": volume,
                "money": volume * close,
            }
        )
    market = pd.concat([market, pd.DataFrame(rows)], ignore_index=True)

    state = strategy.classify_market_regime(market)

    assert state["state"] == strategy.MARKET_CORRECTION
    assert state["distribution_days"] >= strategy.MAX_DISTRIBUTION_DAYS


def test_four_distribution_days_pause_new_risk_without_declaring_a_correction():
    strategy = load_strategy()
    market = make_confirmed_market()
    next_time = market["time"].iloc[-1]
    rows = []
    close = market["close"].iloc[-1]
    volume = 100.0
    for _ in range(strategy.MAX_DISTRIBUTION_DAYS - 1):
        next_time += pd.offsets.BDay(1)
        close *= 0.995
        volume += 10.0
        rows.append(
            {
                "time": next_time,
                "code": "000001.XSHG",
                "close": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "volume": volume,
                "money": volume * close,
            }
        )
    market = pd.concat([market, pd.DataFrame(rows)], ignore_index=True)

    state = strategy.classify_market_regime(market)

    assert state["state"] == strategy.MARKET_UNDER_PRESSURE
    assert state["distribution_days"] == strategy.MAX_DISTRIBUTION_DAYS - 1


def test_market_state_fails_closed_when_price_or_volume_history_is_missing():
    strategy = load_strategy()
    short = make_confirmed_market().tail(20).copy()
    short["volume"] = np.nan

    state = strategy.classify_market_regime(short)

    assert state["state"] == strategy.MARKET_UNKNOWN

    missing_low = make_confirmed_market()
    missing_low.loc[missing_low.index[-1], "low"] = np.nan
    state = strategy.classify_market_regime(missing_low)

    assert state["state"] == strategy.MARKET_UNKNOWN


def test_candidate_scoring_uses_hard_c_a_l_and_base_gates():
    strategy = load_strategy()
    fundamentals = pd.DataFrame(
        [
            {
                "code": "GOOD",
                "current_eps_growth": 0.55,
                "core_profit_growth": 0.50,
                "current_sales_growth": 0.30,
                "eps_growth_acceleration": 0.10,
                "annual_eps_cagr": 0.30,
                "annual_eps_increasing": True,
                "roe": 0.22,
                "current_report_age_days": 90,
            },
            {
                "code": "WEAK_C",
                "current_eps_growth": 0.10,
                "core_profit_growth": 0.50,
                "current_sales_growth": 0.30,
                "eps_growth_acceleration": 0.0,
                "annual_eps_cagr": 0.30,
                "annual_eps_increasing": True,
                "roe": 0.22,
                "current_report_age_days": 90,
            },
        ]
    )
    prices = pd.DataFrame(
        [
            {
                "code": "GOOD",
                "rs_rating": 95.0,
                "industry_rs_rating": 85.0,
                "setup_ready": True,
                "base_quality": 85.0,
                "accumulation_ratio": 1.5,
                "average_money_20d": 1e8,
                "circulating_market_cap": 100.0,
            },
            {
                "code": "WEAK_C",
                "rs_rating": 95.0,
                "industry_rs_rating": 85.0,
                "setup_ready": True,
                "base_quality": 85.0,
                "accumulation_ratio": 1.5,
                "average_money_20d": 1e8,
                "circulating_market_cap": 100.0,
            },
        ]
    )

    ranked = strategy.score_candidates(fundamentals, prices)

    assert ranked.loc[ranked["code"] == "GOOD", "eligible"].iloc[0]
    weak = ranked.loc[ranked["code"] == "WEAK_C"].iloc[0]
    assert not weak["eligible"]
    assert "current_eps_growth" in weak["veto_reasons"]
    assert ranked.loc[ranked["code"] == "GOOD", "score"].iloc[0] > weak["score"]


def test_exit_priority_keeps_the_hard_stop_above_every_hold_exception():
    strategy = load_strategy()

    assert (
        strategy.position_exit_reason(
            current_price=92.0,
            average_cost=100.0,
            pivot=100.0,
            holding_days=10,
            close_50d_ma=90.0,
            volume_ratio=1.0,
            market_state=strategy.MARKET_CONFIRMED,
            power_hold=True,
        )
        == "hard_stop"
    )
    assert (
        strategy.position_exit_reason(
            current_price=104.0,
            average_cost=100.0,
            pivot=100.0,
            holding_days=20,
            close_50d_ma=95.0,
            volume_ratio=1.0,
            market_state=strategy.MARKET_CORRECTION,
            power_hold=True,
        )
        == "market_correction"
    )


def test_profit_taking_and_eight_week_exception_are_deterministic():
    strategy = load_strategy()
    kwargs = {
        "average_cost": 100.0,
        "pivot": 100.0,
        "holding_days": 20,
        "close_50d_ma": 105.0,
        "volume_ratio": 1.0,
        "market_state": strategy.MARKET_CONFIRMED,
    }

    assert strategy.position_exit_reason(current_price=125.0, power_hold=False, **kwargs) == (
        "profit_target"
    )
    assert strategy.position_exit_reason(current_price=125.0, power_hold=True, **kwargs) is None
    assert (
        strategy.position_exit_reason(
            current_price=96.0,
            average_cost=100.0,
            pivot=100.0,
            holding_days=5,
            close_50d_ma=90.0,
            volume_ratio=1.0,
            market_state=strategy.MARKET_CONFIRMED,
            power_hold=False,
        )
        == "failed_breakout"
    )


def test_fifty_day_break_uses_the_completed_signal_day_not_intraday_price():
    strategy = load_strategy()
    common = {
        "average_cost": 100.0,
        "pivot": 100.0,
        "holding_days": 30,
        "close_50d_ma": 100.0,
        "volume_ratio": 1.30,
        "market_state": strategy.MARKET_CONFIRMED,
        "power_hold": False,
    }

    assert (
        strategy.position_exit_reason(
            current_price=99.0,
            technical_close=101.0,
            **common,
        )
        is None
    )
    assert (
        strategy.position_exit_reason(
            current_price=101.0,
            technical_close=99.0,
            **common,
        )
        == "fifty_day_break"
    )


def test_pyramiding_only_adds_to_winners_and_never_exceeds_final_weight():
    strategy = load_strategy()

    weight, stage = strategy.pyramid_target(1, current_price=102.4, initial_price=100.0)
    assert stage == 1
    assert weight == strategy.INITIAL_POSITION_WEIGHT

    weight, stage = strategy.pyramid_target(1, current_price=102.5, initial_price=100.0)
    assert stage == 2
    assert weight == strategy.SECOND_POSITION_WEIGHT

    weight, stage = strategy.pyramid_target(2, current_price=105.0, initial_price=100.0)
    assert stage == 3
    assert weight == strategy.FINAL_POSITION_WEIGHT

    weight, stage = strategy.pyramid_target(3, current_price=150.0, initial_price=100.0)
    assert stage == 3
    assert weight == strategy.FINAL_POSITION_WEIGHT


def test_pyramiding_never_adds_above_the_pivot_buy_zone():
    strategy = load_strategy()

    weight, stage = strategy.pyramid_target(
        1,
        current_price=106.6,
        initial_price=104.0,
        pivot=100.0,
    )

    assert weight == strategy.INITIAL_POSITION_WEIGHT
    assert stage == 1


def test_buy_target_rounds_increment_down_to_a_hundred_share_lot():
    strategy = load_strategy()

    initial = strategy._round_buy_target_value(
        current_value=0.0,
        desired_target_value=82500.0,
        current_price=102.0,
    )
    addition = strategy._round_buy_target_value(
        current_value=initial,
        desired_target_value=120000.0,
        current_price=104.0,
    )

    assert initial == 81600.0
    assert addition == 112800.0


def test_invalid_available_cash_fails_closed():
    strategy = load_strategy()

    assert strategy._usable_cash(np.nan) == 0.0
    assert strategy._usable_cash(None) == 0.0
    assert strategy._usable_cash(-1.0) == 0.0
    assert strategy._usable_cash(1000.0) == 1000.0


def test_order_acceptance_rejects_cancelled_and_zero_amount_orders():
    strategy = load_strategy()

    assert not strategy._order_is_accepted(None)
    assert not strategy._order_is_accepted(
        SimpleNamespace(status="OrderStatus.cancelled", amount=100, filled=0)
    )
    assert not strategy._order_is_accepted(
        SimpleNamespace(status="held", amount=0, filled=0)
    )
    assert strategy._order_is_accepted(
        SimpleNamespace(status="held", amount=100, filled=0)
    )


def test_pending_target_amount_prefers_the_platform_order_quantity():
    strategy = load_strategy()

    assert (
        strategy._pending_target_amount(
            SimpleNamespace(amount=300, filled=0),
            current_amount=800,
            fallback_target_amount=1200,
        )
        == 1100
    )
    assert (
        strategy._pending_target_amount(
            object(),
            current_amount=800,
            fallback_target_amount=1200,
        )
        == 1200
    )


def test_pending_pyramid_advances_only_after_real_position_reaches_target():
    strategy = load_strategy()
    code = "000001.XSHE"
    strategy.g = SimpleNamespace(
        entry_dates={code: dt.date(2026, 7, 1)},
        entry_prices={code: 100.0},
        entry_pivots={code: 100.0},
        pyramid_stages={code: 1},
        power_hold_until={},
        pending_entries={},
        pending_pyramids={
            code: {
                "submitted_date": dt.date(2026, 7, 15),
                "next_stage": 2,
                "target_value": 110000.0,
                "target_amount": 1100,
            }
        },
    )
    positions = {
        code: SimpleNamespace(
            avg_cost=100.0,
            value=110000.0,
            total_amount=1100,
        )
    }

    strategy._sync_position_state(positions, dt.date(2026, 7, 16))

    assert strategy.g.pyramid_stages[code] == 2
    assert code not in strategy.g.pending_pyramids


def test_fetch_universe_uses_historical_membership_and_lazy_snapshots(monkeypatch):
    strategy = load_strategy()
    codes = ["000001.XSHE", "000002.XSHE"]
    securities = pd.DataFrame(
        {
            "start_date": [dt.date(1991, 4, 3), dt.date(1991, 1, 29)],
            "display_name": ["平安银行", "万科A"],
        },
        index=codes,
    )
    snapshots = {
        code: SimpleNamespace(paused=False, is_st=False, name=name)
        for code, name in zip(codes, securities["display_name"], strict=True)
    }
    current_data = LazyCurrentData(snapshots)
    monkeypatch.setattr(
        strategy,
        "get_all_securities",
        lambda *_args, **_kwargs: securities,
        raising=False,
    )

    universe = strategy._fetch_universe(
        dt.date(2026, 7, 15),
        current_data,
        min_listing_days=365,
    )

    assert universe == codes
    assert set(current_data) == set(codes)


def test_tradeability_handles_st_pauses_and_price_limits():
    strategy = load_strategy()
    normal = SimpleNamespace(
        paused=False,
        is_st=False,
        name="测试股份",
        last_price=10.0,
        high_limit=11.0,
        low_limit=9.0,
    )
    upper = SimpleNamespace(**{**vars(normal), "last_price": 11.0})
    lower = SimpleNamespace(**{**vars(normal), "last_price": 9.0})
    paused = SimpleNamespace(**{**vars(normal), "paused": True})

    assert strategy._is_buyable(normal)
    assert strategy._is_sellable(normal)
    assert not strategy._is_buyable(upper)
    assert not strategy._is_sellable(lower)
    assert not strategy._is_buyable(paused)
    assert not strategy._is_sellable(paused)


def test_initialize_configures_weekly_research_and_daily_execution(monkeypatch):
    strategy = load_strategy()
    calls = []
    monkeypatch.setattr(
        strategy,
        "set_benchmark",
        lambda value: calls.append(("benchmark", value)),
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "set_option",
        lambda name, value: calls.append(("option", name, value)),
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "FixedSlippage",
        lambda value: ("slippage", value),
        raising=False,
    )
    monkeypatch.setattr(strategy, "set_slippage", lambda value: calls.append(value), raising=False)
    monkeypatch.setattr(strategy, "OrderCost", lambda **kwargs: kwargs, raising=False)
    monkeypatch.setattr(
        strategy,
        "set_order_cost",
        lambda value, type: calls.append(("cost", value, type)),
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "run_weekly",
        lambda function, weekday, time: calls.append(
            ("weekly", function.__name__, weekday, time)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "run_daily",
        lambda function, time: calls.append(("daily", function.__name__, time)),
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "g",
        SimpleNamespace(),
        raising=False,
    )

    strategy.initialize(SimpleNamespace())

    assert ("benchmark", strategy.BENCHMARK) in calls
    assert ("option", "use_real_price", True) in calls
    assert ("option", "avoid_future_data", True) in calls
    assert ("weekly", "refresh_watchlist", 1, "before_open") in calls
    assert ("daily", "daily_trade", "10:00") in calls
    assert strategy.g.watchlist == []
    assert strategy.g.candidate_meta == {}


def test_daily_trade_sells_first_and_does_not_assume_cash_was_released(monkeypatch):
    strategy = load_strategy()
    held = "000001.XSHE"
    candidate = "000002.XSHE"
    strategy.g = SimpleNamespace(
        watchlist=[candidate],
        candidate_meta={candidate: {"score": 90.0}},
        entry_dates={held: dt.date(2026, 7, 1)},
        entry_prices={held: 100.0},
        entry_pivots={held: 100.0},
        pyramid_stages={held: 1},
        power_hold_until={},
        market_state=strategy.MARKET_CONFIRMED,
        watchlist_date=dt.date(2026, 7, 13),
    )
    snapshots = LazyCurrentData(
        {
            held: SimpleNamespace(
                paused=False,
                is_st=False,
                name="持仓股",
                last_price=104.0,
                high_limit=110.0,
                low_limit=90.0,
            ),
            candidate: SimpleNamespace(
                paused=False,
                is_st=False,
                name="候选股",
                last_price=102.0,
                high_limit=110.0,
                low_limit=90.0,
            ),
        }
    )
    monkeypatch.setattr(
        strategy,
        "_previous_trade_day",
        lambda _date: dt.date(2026, 7, 15),
    )
    monkeypatch.setattr(strategy, "get_current_data", lambda: snapshots, raising=False)
    monkeypatch.setattr(strategy, "_fetch_price_history", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        strategy,
        "classify_market_regime",
        lambda _prices: {
            "state": strategy.MARKET_CORRECTION,
            "distribution_days": strategy.MAX_DISTRIBUTION_DAYS,
        },
    )
    orders = []
    monkeypatch.setattr(
        strategy,
        "order_target_value",
        lambda code, value: orders.append((code, value)) or object(),
        raising=False,
    )
    context = SimpleNamespace(
        current_dt=dt.datetime(2026, 7, 16, 10, 0),
        portfolio=SimpleNamespace(
            positions={held: SimpleNamespace(avg_cost=100.0, value=100000.0)},
            total_value=1e6,
            available_cash=9e5,
        ),
    )

    strategy.daily_trade(context)

    assert orders == [(held, 0)]
    assert strategy.g.pending_exits[held]["reason"] == "market_correction"
    assert candidate not in strategy.g.entry_dates


def test_blocked_exit_also_prevents_new_orders(monkeypatch):
    strategy = load_strategy()
    held = "000001.XSHE"
    candidate = "000002.XSHE"
    strategy.g = SimpleNamespace(
        watchlist=[candidate],
        candidate_meta={candidate: {"score": 90.0}},
        entry_dates={held: dt.date(2026, 7, 1)},
        entry_prices={held: 100.0},
        entry_pivots={held: 100.0},
        pyramid_stages={held: 1},
        power_hold_until={},
        market_state=strategy.MARKET_CONFIRMED,
        watchlist_date=dt.date(2026, 7, 13),
    )
    snapshots = LazyCurrentData(
        {
            held: SimpleNamespace(
                paused=False,
                is_st=False,
                name="跌停持仓",
                last_price=90.0,
                high_limit=110.0,
                low_limit=90.0,
            ),
            candidate: SimpleNamespace(
                paused=False,
                is_st=False,
                name="候选股",
                last_price=102.0,
                high_limit=110.0,
                low_limit=90.0,
            ),
        }
    )
    candidate_history = make_price_frame()
    candidate_history["code"] = candidate
    held_history = make_price_frame()
    held_history["code"] = held
    histories = pd.concat([held_history, candidate_history], ignore_index=True)
    monkeypatch.setattr(
        strategy,
        "_previous_trade_day",
        lambda _date: dt.date(2026, 7, 15),
    )
    monkeypatch.setattr(strategy, "get_current_data", lambda: snapshots, raising=False)
    monkeypatch.setattr(
        strategy,
        "_fetch_price_history",
        lambda codes, *_args, **_kwargs: (
            make_confirmed_market()
            if codes == [strategy.MARKET_INDEX]
            else histories
        ),
    )
    monkeypatch.setattr(
        strategy,
        "classify_market_regime",
        lambda _prices: {
            "state": strategy.MARKET_CONFIRMED,
            "distribution_days": 0,
        },
    )
    orders = []
    monkeypatch.setattr(
        strategy,
        "order_target_value",
        lambda code, value: orders.append((code, value)) or object(),
        raising=False,
    )
    context = SimpleNamespace(
        current_dt=dt.datetime(2026, 7, 16, 10, 0),
        portfolio=SimpleNamespace(
            positions={held: SimpleNamespace(avg_cost=100.0, value=90000.0)},
            total_value=1e6,
            available_cash=9e5,
        ),
    )

    strategy.daily_trade(context)

    assert orders == []
    assert strategy.g.pending_exits[held]["reason"] == "hard_stop"
    assert candidate not in strategy.g.entry_dates

    snapshots[held].last_price = 101.0
    context.current_dt = dt.datetime(2026, 7, 17, 10, 0)
    strategy.daily_trade(context)

    assert orders == [(held, 0)]


def test_daily_trade_enters_only_a_confirmed_breakout_inside_the_buy_zone(monkeypatch):
    strategy = load_strategy()
    candidate = "000002.XSHE"
    strategy.g = SimpleNamespace(
        watchlist=[candidate],
        candidate_meta={candidate: {"score": 92.0}},
        entry_dates={},
        entry_prices={},
        entry_pivots={},
        pyramid_stages={},
        power_hold_until={},
        market_state=strategy.MARKET_UNKNOWN,
        watchlist_date=dt.date(2026, 7, 13),
    )
    snapshots = LazyCurrentData(
        {
            candidate: SimpleNamespace(
                paused=False,
                is_st=False,
                name="候选股",
                last_price=102.0,
                high_limit=110.0,
                low_limit=90.0,
            )
        }
    )
    candidate_history = make_price_frame()
    candidate_history["code"] = candidate

    def fake_prices(codes, *_args, **_kwargs):
        if codes == [strategy.MARKET_INDEX]:
            return make_confirmed_market()
        return candidate_history

    monkeypatch.setattr(
        strategy,
        "_previous_trade_day",
        lambda _date: dt.date(2026, 7, 15),
    )
    monkeypatch.setattr(strategy, "get_current_data", lambda: snapshots, raising=False)
    monkeypatch.setattr(strategy, "_fetch_price_history", fake_prices)
    monkeypatch.setattr(
        strategy,
        "classify_market_regime",
        lambda _prices: {
            "state": strategy.MARKET_CONFIRMED,
            "distribution_days": 0,
        },
    )
    orders = []
    monkeypatch.setattr(
        strategy,
        "order_target_value",
        lambda code, value: orders.append((code, value)) or object(),
        raising=False,
    )
    context = SimpleNamespace(
        current_dt=dt.datetime(2026, 7, 16, 10, 0),
        portfolio=SimpleNamespace(
            positions={},
            total_value=1e6,
            available_cash=1e6,
        ),
    )

    strategy.daily_trade(context)

    assert orders == [(candidate, 81600.0)]
    assert candidate not in strategy.g.entry_dates
    assert strategy.g.pending_entries[candidate]["pivot"] == 100.0

    positions = {
        candidate: SimpleNamespace(
            avg_cost=101.8,
            value=81440.0,
        )
    }
    strategy._sync_position_state(positions, dt.date(2026, 7, 17))

    assert strategy.g.entry_dates[candidate] == dt.date(2026, 7, 16)
    assert strategy.g.entry_prices[candidate] == 101.8
    assert strategy.g.entry_pivots[candidate] == 100.0
    assert strategy.g.pyramid_stages[candidate] == 1
    assert candidate not in strategy.g.pending_entries
