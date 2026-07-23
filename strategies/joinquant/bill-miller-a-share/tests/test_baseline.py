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
    """Mimic JoinQuant's mapping where only ``mapping[key]`` materializes data."""

    def __init__(self, snapshots):
        super().__init__()
        self.snapshots = snapshots

    def __missing__(self, key):
        snapshot = self.snapshots[key]
        self[key] = snapshot
        return snapshot


def load_strategy():
    spec = importlib.util.spec_from_file_location("bill_miller_quant", STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_strategy_source_avoids_joinquant_legacy_runtime_features():
    source = STRATEGY_PATH.read_text(encoding="utf-8")

    assert "from __future__ import annotations" not in source
    assert "from **future** import annotations" not in source
    assert "strict=" not in source
    assert 'groupby("industry", dropna=' not in source


def test_strategy_qualifies_builtins_shadowed_by_jqdata():
    tree = ast.parse(STRATEGY_PATH.read_text(encoding="utf-8"))
    unqualified = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"all", "any", "sum"}
    ]

    assert unqualified == []


def test_safe_ratios_and_growth_reject_economically_invalid_denominators():
    strategy = load_strategy()

    assert strategy.safe_divide(10.0, 2.0) == 5.0
    assert math.isnan(strategy.safe_divide(10.0, 0.0))
    assert math.isnan(strategy.safe_divide(10.0, np.nan))
    assert strategy.simple_growth(120.0, 100.0) == 0.2
    assert math.isnan(strategy.simple_growth(120.0, -100.0))
    assert round(strategy.compound_growth(121.0, 100.0, 2), 6) == 0.1


def test_percentile_score_handles_outliers_ties_and_small_samples():
    strategy = load_strategy()
    values = pd.Series([1.0, 2.0, 3.0, 1000.0, np.nan], index=list("abcde"))

    clipped = strategy.winsorize_series(values, lower=0.0, upper=0.75)
    assert clipped.loc["d"] == 3.0
    scores = strategy.percentile_score(clipped, min_count=3)
    assert scores.loc["c"] == scores.loc["d"]
    assert scores.loc["a"] < scores.loc["b"] < scores.loc["c"]
    assert math.isnan(scores.loc["e"])
    assert strategy.percentile_score(pd.Series([1.0, 2.0]), min_count=3).isna().all()


def test_build_company_features_derives_cash_flow_returns_and_balance_sheet_risk():
    strategy = load_strategy()
    unit = 1e8
    history = pd.DataFrame(
        [
            {
                "statDate": "2022-12-31",
                "cash_equivalents": 20.0 * unit,
                "total_assets": 200.0 * unit,
                "total_liability": 100.0 * unit,
                "total_owner_equities": 100.0 * unit,
                "paidin_capital": 10.0 * unit,
                "account_receivable": 20.0 * unit,
                "inventories": 10.0 * unit,
                "shortterm_loan": 20.0 * unit,
                "longterm_loan": 20.0 * unit,
                "bonds_payable": 0.0,
                "good_will": 4.0 * unit,
                "net_operate_cash_flow": 16.0 * unit,
                "fix_intan_other_asset_acqui_cash": 6.0 * unit,
                "total_operating_revenue": 100.0 * unit,
                "operating_profit": 12.0 * unit,
                "np_parent_company_owners": 10.0 * unit,
                "adjusted_profit": 9.0 * unit,
                "roe": 10.0,
                "roa": 5.0,
                "gross_profit_margin": 30.0,
            },
            {
                "statDate": "2023-12-31",
                "cash_equivalents": 23.0 * unit,
                "total_assets": 220.0 * unit,
                "total_liability": 108.0 * unit,
                "total_owner_equities": 112.0 * unit,
                "paidin_capital": 10.0 * unit,
                "account_receivable": 21.0 * unit,
                "inventories": 10.5 * unit,
                "shortterm_loan": 18.0 * unit,
                "longterm_loan": 18.0 * unit,
                "bonds_payable": 0.0,
                "good_will": 4.0 * unit,
                "net_operate_cash_flow": 18.0 * unit,
                "fix_intan_other_asset_acqui_cash": 6.0 * unit,
                "total_operating_revenue": 110.0 * unit,
                "operating_profit": 14.0 * unit,
                "np_parent_company_owners": 11.0 * unit,
                "adjusted_profit": 10.5 * unit,
                "roe": 10.4,
                "roa": 5.1,
                "gross_profit_margin": 31.0,
            },
            {
                "statDate": "2024-12-31",
                "cash_equivalents": 28.0 * unit,
                "total_assets": 245.0 * unit,
                "total_liability": 115.0 * unit,
                "total_owner_equities": 130.0 * unit,
                "paidin_capital": 10.0 * unit,
                "account_receivable": 22.0 * unit,
                "inventories": 11.0 * unit,
                "shortterm_loan": 16.0 * unit,
                "longterm_loan": 16.0 * unit,
                "bonds_payable": 0.0,
                "good_will": 4.0 * unit,
                "net_operate_cash_flow": 22.0 * unit,
                "fix_intan_other_asset_acqui_cash": 7.0 * unit,
                "total_operating_revenue": 121.0 * unit,
                "operating_profit": 17.0 * unit,
                "np_parent_company_owners": 13.0 * unit,
                "adjusted_profit": 12.5 * unit,
                "roe": 11.0,
                "roa": 5.5,
                "gross_profit_margin": 32.0,
            },
        ]
    )
    features = strategy.build_company_features(
        history,
        {
            "code": "000001.XSHE",
            "market_cap": 150.0,
            "pe_ratio": 12.0,
            "pb_ratio": 1.2,
            "ps_ratio": 1.0,
            "pcf_ratio": 8.0,
        },
        {
            "return_12m": -0.2,
            "volatility_12m": 0.25,
            "max_drawdown_12m": -0.35,
            "average_money_20d": 5e7,
        },
        industry="制造业",
        is_financial=False,
    )

    assert features is not None
    assert features["code"] == "000001.XSHE"
    assert features["latest_fcf"] == 15.0 * unit
    assert round(features["fcf_yield"], 4) == 0.1
    assert round(features["revenue_cagr"], 4) == 0.1
    assert features["fcf_positive_ratio"] == 1.0
    assert round(features["net_debt_ratio"], 4) == round((32.0 - 28.0) / 130.0, 4)
    assert features["contrarian_signal"] > 0


def test_classification_and_vetoes_distinguish_three_company_models():
    strategy = load_strategy()
    base = {
        "latest_revenue": 100.0,
        "latest_profit": 10.0,
        "latest_fcf": 8.0,
        "revenue_cagr": 0.1,
        "gross_margin": 30.0,
        "gross_margin_change": 1.0,
        "cash_runway_years": np.inf,
        "liability_ratio": 0.45,
        "fcf_positive_ratio": 1.0,
        "latest_cfo": 12.0,
        "cfo_positive_ratio": 1.0,
        "deterioration_count": 0,
        "accounting_gap_streak": 0,
        "feature_coverage": 1.0,
        "total_assets": 200.0,
        "total_liability": 90.0,
    }

    assert strategy.classify_model({**base, "is_financial": True}) == strategy.MODEL_FINANCIAL
    assert strategy.classify_model({**base, "is_financial": False}) == strategy.MODEL_GENERAL
    growth = {
        **base,
        "is_financial": False,
        "latest_profit": -5.0,
        "latest_fcf": -6.0,
        "cash_runway_years": 2.0,
    }
    assert strategy.classify_model(growth) == strategy.MODEL_GROWTH
    assert strategy.risk_veto_reasons(growth) == []
    assert "cash_runway" in strategy.risk_veto_reasons(
        {**growth, "cash_runway_years": 1.0}
    )
    assert "insolvent" in strategy.risk_veto_reasons(
        {**base, "total_assets": 100.0, "total_liability": 101.0}
    )


def make_scoring_fixture():
    base = {
        "industry": "制造业",
        "is_financial": False,
        "latest_revenue": 100.0,
        "latest_profit": 10.0,
        "latest_fcf": 8.0,
        "latest_cfo": 12.0,
        "revenue_cagr": 0.10,
        "profit_growth": 0.10,
        "profit_stability": 1.0,
        "gross_margin": 30.0,
        "gross_margin_change": 1.0,
        "cash_conversion": 1.2,
        "fcf_positive_ratio": 1.0,
        "cfo_positive_ratio": 1.0,
        "roic_proxy": 0.12,
        "incremental_return": 0.15,
        "roe": 12.0,
        "roa": 6.0,
        "asset_turnover": 0.8,
        "share_capital_growth": 0.0,
        "net_debt_ratio": 0.1,
        "liability_ratio": 0.45,
        "ar_growth_gap": 0.0,
        "inventory_growth_gap": 0.0,
        "adjusted_profit_ratio": 0.95,
        "goodwill_ratio": 0.02,
        "cash_runway_years": 5.0,
        "cash_burn_improvement": 0.02,
        "earnings_yield": 0.08,
        "book_yield": 0.80,
        "sales_yield": 1.0,
        "roe_to_pb": 10.0,
        "contrarian_signal": 0.20,
        "total_assets": 200.0,
        "total_liability": 90.0,
        "deterioration_count": 0,
        "accounting_gap_streak": 0,
        "feature_coverage": 1.0,
        "volatility_12m": 0.25,
        "max_drawdown_12m": -0.30,
    }

    def row(code, **changes):
        return {**base, "code": code, **changes}

    return pd.DataFrame(
        [
            row(
                "GENERAL_GOOD",
                fcf_yield=0.10,
                roic_proxy=0.18,
                contrarian_signal=0.35,
            ),
            row(
                "GENERAL_WEAK",
                fcf_yield=0.02,
                roic_proxy=0.06,
                net_debt_ratio=0.8,
            ),
            row(
                "FINANCIAL_GOOD",
                is_financial=True,
                industry="银行I",
                roe_to_pb=14.0,
                roe=14.0,
            ),
            row(
                "FINANCIAL_WEAK",
                is_financial=True,
                industry="银行I",
                roe_to_pb=5.0,
                roe=6.0,
            ),
            row(
                "GROWTH_GOOD",
                latest_profit=-3.0,
                latest_fcf=-4.0,
                revenue_cagr=0.30,
                gross_margin=55.0,
                cash_runway_years=3.0,
                sales_yield=0.8,
            ),
            row(
                "GROWTH_WEAK",
                latest_profit=-5.0,
                latest_fcf=-7.0,
                revenue_cagr=0.05,
                gross_margin=20.0,
                cash_runway_years=1.6,
                sales_yield=0.2,
            ),
        ]
    )


def test_score_candidates_rewards_expectation_gap_without_making_low_pe_a_hard_filter():
    strategy = load_strategy()
    ranked = strategy.score_candidates(make_scoring_fixture(), min_group_size=2)

    assert set(ranked["model"]) == {
        strategy.MODEL_GENERAL,
        strategy.MODEL_FINANCIAL,
        strategy.MODEL_GROWTH,
    }
    good_score = ranked.loc[ranked["code"] == "GENERAL_GOOD", "score"].iloc[0]
    weak_score = ranked.loc[ranked["code"] == "GENERAL_WEAK", "score"].iloc[0]
    assert good_score > weak_score
    assert ranked.loc[ranked["code"] == "GROWTH_GOOD", "eligible"].iloc[0]
    assert ranked["score"].dropna().between(0.0, 100.0).all()


def make_ranked_fixture(count):
    return pd.DataFrame(
        {
            "code": [f"S{rank:03d}" for rank in range(1, count + 1)],
            "score": np.linspace(100.0, 50.0, count),
            "eligible": [True] * count,
            "veto_reasons": [[] for _ in range(count)],
        }
    )


def test_select_portfolio_uses_initial_top_twenty_and_later_rank_buffers():
    strategy = load_strategy()
    ranked = make_ranked_fixture(50)

    assert strategy.select_portfolio(ranked, []) == list(ranked["code"].head(20))
    selected = strategy.select_portfolio(ranked, ["S035", "S045"])
    assert "S035" in selected
    assert "S045" not in selected
    assert len(selected) <= 20
    new_codes = set(selected) - {"S035", "S045"}
    assert new_codes <= set(ranked["code"].head(15))


def test_allocate_weights_respects_single_industry_and_model_caps():
    strategy = load_strategy()
    rows = []
    for index in range(20):
        if index < 6:
            model, industry = strategy.MODEL_FINANCIAL, "银行I"
        elif index < 10:
            model, industry = strategy.MODEL_GROWTH, "软件服务"
        else:
            model, industry = strategy.MODEL_GENERAL, f"行业{index % 5}"
        rows.append(
            {
                "code": f"S{index:03d}",
                "score": 80.0,
                "downside_risk": 0.20 if index == 10 else 0.40,
                "industry": industry,
                "model": model,
            }
        )
    selected = pd.DataFrame(rows)
    weights = strategy.allocate_weights(selected)

    assert weights
    assert sum(weights.values()) <= 1.0 + 1e-9
    assert all(0.02 <= weight <= 0.08 for weight in weights.values())
    assert weights["S010"] > weights["S011"]
    for _industry, group in selected.groupby("industry"):
        assert sum(weights.get(code, 0.0) for code in group["code"]) <= 0.25 + 1e-9
    assert (
        sum(
            weights.get(row.code, 0.0)
            for row in selected.itertuples()
            if row.model == strategy.MODEL_FINANCIAL
        )
        <= 0.30 + 1e-9
    )
    assert (
        sum(
            weights.get(row.code, 0.0)
            for row in selected.itertuples()
            if row.model == strategy.MODEL_GROWTH
        )
        <= 0.20 + 1e-9
    )


def test_allocate_weights_keeps_cash_when_concentration_caps_prevent_full_investment():
    strategy = load_strategy()
    selected = pd.DataFrame(
        [
            {
                "code": f"S{index}",
                "score": 90.0,
                "downside_risk": 0.2,
                "industry": f"行业{index}",
                "model": strategy.MODEL_GENERAL,
            }
            for index in range(5)
        ]
    )

    weights = strategy.allocate_weights(selected)

    assert len(weights) == 5
    assert all(weight == 0.08 for weight in weights.values())
    assert round(sum(weights.values()), 8) == 0.40


def test_allocate_weights_does_not_treat_unknown_industry_as_one_sector():
    strategy = load_strategy()
    selected = pd.DataFrame(
        [
            {
                "code": f"S{index:03d}",
                "score": 80.0,
                "downside_risk": 0.2,
                "industry": "未知行业",
                "model": strategy.MODEL_GENERAL,
            }
            for index in range(20)
        ]
    )

    weights = strategy.allocate_weights(selected)

    assert len(weights) == 20
    assert round(sum(weights.values()), 8) == 1.0


def test_joinquant_boundary_helpers_are_point_in_time_and_locally_importable():
    strategy = load_strategy()
    codes = [f"S{i:04d}" for i in range(1005)]
    chunks = list(strategy._chunked(codes, 400))
    assert [len(chunk) for chunk in chunks] == [400, 400, 205]
    assert [code for chunk in chunks for code in chunk] == codes

    calls = []

    def fake_trade_days(**kwargs):
        calls.append(kwargs)
        return np.array([dt.date(2026, 7, 15), dt.date(2026, 7, 16)])

    strategy.get_trade_days = fake_trade_days
    assert strategy._previous_trade_day(dt.date(2026, 7, 16)) == dt.date(2026, 7, 15)
    assert calls == [{"end_date": dt.date(2026, 7, 16), "count": 2}]


def test_price_normalizer_accepts_joinquant_long_form_and_source_has_no_repo_import():
    strategy = load_strategy()
    raw = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-14", "2026-07-15"]),
            "code": ["000001.XSHE", "000001.XSHE"],
            "close": [10.0, 11.0],
            "money": [3e7, 4e7],
        }
    )
    normalized = strategy._normalize_price_frame(raw)
    assert list(normalized.columns) == ["time", "code", "close", "money"]
    assert normalized.iloc[-1]["close"] == 11.0
    assert "import trading_os" not in STRATEGY_PATH.read_text(encoding="utf-8")


def test_price_normalizer_preserves_an_unnamed_datetime_index():
    strategy = load_strategy()
    raw = pd.DataFrame(
        {
            "code": ["000001.XSHE", "000001.XSHE"],
            "close": [10.0, 11.0],
            "money": [3e7, 4e7],
        },
        index=pd.to_datetime(["2026-07-14", "2026-07-15"]),
    )

    normalized = strategy._normalize_price_frame(raw)

    assert normalized["time"].notna().all()
    assert normalized.iloc[-1]["time"] == pd.Timestamp("2026-07-15")


def test_financial_industry_uses_second_level_peer_group():
    strategy = load_strategy()
    company = {
        "sw_l1": {"industry_name": "非银金融I"},
        "sw_l2": {"industry_name": "证券II"},
        "jq_l1": {"industry_name": "金融指数"},
    }

    info = strategy._industry_info(company)

    assert info == {"industry": "证券II", "is_financial": True}


def test_initialize_configures_monthly_point_in_time_strategy(monkeypatch):
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
        strategy, "FixedSlippage", lambda value: ("slippage", value), raising=False
    )
    monkeypatch.setattr(
        strategy, "set_slippage", lambda value: calls.append(value), raising=False
    )
    monkeypatch.setattr(strategy, "OrderCost", lambda **kwargs: kwargs, raising=False)
    monkeypatch.setattr(
        strategy,
        "set_order_cost",
        lambda value, type: calls.append(("cost", value, type)),
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "run_monthly",
        lambda function, day, time: calls.append(("monthly", function.__name__, day, time)),
        raising=False,
    )

    strategy.initialize(SimpleNamespace())

    assert ("benchmark", "000300.XSHG") in calls
    assert ("option", "use_real_price", True) in calls
    assert ("option", "avoid_future_data", True) in calls
    assert ("slippage", 0.002) in calls
    assert ("monthly", "monthly_rebalance", 1, "10:00") in calls


def test_price_statistics_calculates_liquidity_return_volatility_and_drawdown():
    strategy = load_strategy()
    prices = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-13", "2026-07-14", "2026-07-15"]),
            "code": ["000001.XSHE"] * 3,
            "close": [10.0, 8.0, 12.0],
            "money": [2e7, 4e7, 6e7],
        }
    )

    stats = strategy._price_statistics(prices)

    row = stats.loc[stats["code"] == "000001.XSHE"].iloc[0]
    assert row["average_money_20d"] == 4e7
    assert round(row["return_12m"], 8) == 0.2
    assert round(row["max_drawdown_12m"], 8) == -0.2
    assert row["volatility_12m"] > 0


def test_fetch_universe_materializes_joinquant_lazy_current_data(monkeypatch):
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

    universe = strategy._fetch_universe(dt.date(2026, 7, 15), current_data)

    assert universe == codes
    assert set(current_data) == set(codes)


def test_tradeability_respects_pauses_and_price_limits():
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


def test_execute_targets_materializes_joinquant_lazy_current_data(monkeypatch):
    strategy = load_strategy()
    code = "000001.XSHE"
    current_data = LazyCurrentData(
        {
            code: SimpleNamespace(
                paused=False,
                is_st=False,
                name="平安银行",
                last_price=10.0,
                high_limit=11.0,
                low_limit=9.0,
            )
        }
    )
    orders = []
    monkeypatch.setattr(
        strategy,
        "order_target_value",
        lambda security, value: orders.append((security, value)),
        raising=False,
    )
    context = SimpleNamespace(
        portfolio=SimpleNamespace(positions={}, total_value=1e6)
    )

    strategy._execute_targets(context, {code: 0.08}, current_data)

    assert orders == [(code, 80000.0)]
    assert set(current_data) == {code}


def test_monthly_rebalance_leaves_pipeline_results_to_execution(monkeypatch):
    strategy = load_strategy()
    observation_date = dt.date(2026, 7, 15)
    ranked = pd.DataFrame(
        [
            {
                "code": "000001.XSHE",
                "score": 80.0,
                "eligible": True,
                "veto_reasons": [],
                "industry": "银行I",
                "model": strategy.MODEL_FINANCIAL,
                "downside_risk": 0.2,
            }
        ]
    )
    monkeypatch.setattr(strategy, "_previous_trade_day", lambda _date: observation_date)
    monkeypatch.setattr(
        strategy,
        "get_current_data",
        lambda: {"000001.XSHE": object()},
        raising=False,
    )
    monkeypatch.setattr(strategy, "_fetch_universe", lambda *_args: ["000001.XSHE"])
    monkeypatch.setattr(
        strategy,
        "_fetch_price_stats",
        lambda *_args: pd.DataFrame([{"code": "000001.XSHE", "average_money_20d": 5e7}]),
    )
    monkeypatch.setattr(strategy, "_fetch_annual_fundamentals", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(strategy, "_fetch_latest_fundamentals", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(strategy, "_fetch_valuations", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(strategy, "_fetch_industries", lambda *_args: {})
    monkeypatch.setattr(strategy, "_build_feature_frame", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(strategy, "score_candidates", lambda *_args, **_kwargs: ranked)
    monkeypatch.setattr(strategy, "select_portfolio", lambda *_args, **_kwargs: ["000001.XSHE"])
    monkeypatch.setattr(
        strategy, "allocate_weights", lambda _frame: {"000001.XSHE": 0.08}
    )
    captured = []
    monkeypatch.setattr(
        strategy,
        "_execute_targets",
        lambda context, targets, current_data: captured.append((context, targets, current_data)),
    )
    monkeypatch.setattr(
        strategy,
        "log",
        SimpleNamespace(info=lambda *_args: None, error=lambda *_args: None),
        raising=False,
    )
    context = SimpleNamespace(
        current_dt=dt.datetime(2026, 7, 16, 10, 0),
        portfolio=SimpleNamespace(positions={}, total_value=1e6),
    )

    strategy.monthly_rebalance(context)

    assert captured[0][1] == {"000001.XSHE": 0.08}
