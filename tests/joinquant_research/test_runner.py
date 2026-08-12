import ast
import builtins
import importlib.util
import json
import sys
import types
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "runners" / "joinquant-research" / "research_runner.py"
ACCEPTANCE_PATH = (
    ROOT
    / "runners"
    / "joinquant-research"
    / "examples"
    / "platform_acceptance_20260812.py"
)


class FakeJoinQuantData:
    def __init__(self, trade_days, bars, st=None):
        self.trade_days = [pd.Timestamp(day).date() for day in trade_days]
        self.bars = {
            (code, pd.Timestamp(day).date()): values
            for (code, day), values in bars.items()
        }
        self.st = st or {}

    def get_all_trade_days(self):
        return list(self.trade_days)

    def get_price(
        self,
        code,
        count=None,
        end_date=None,
        frequency=None,
        fields=None,
        skip_paused=None,
        panel=None,
        fq=None,
    ):
        del count, frequency, fields, skip_paused, panel, fq
        day = pd.Timestamp(end_date).date()
        values = self.bars.get((code, day))
        if values is None:
            return pd.DataFrame()
        return pd.DataFrame([values], index=[pd.Timestamp(day)])

    def get_extras(self, name, code, start_date=None, end_date=None, df=None):
        del name, end_date, df
        day = pd.Timestamp(start_date).date()
        codes = code if isinstance(code, list) else [code]
        return pd.DataFrame(
            {
                item: [bool(self.st.get((item, day), False))]
                for item in codes
            }
        )


def load_runner(fake, platform_builtins=False):
    module = types.ModuleType("jqdata")
    module.get_all_trade_days = fake.get_all_trade_days
    module.get_extras = fake.get_extras
    if not platform_builtins:
        module.get_price = fake.get_price
    old = sys.modules.get("jqdata")
    missing = object()
    old_builtins = {}
    if platform_builtins:
        for name in ("get_price", "get_extras"):
            old_builtins[name] = getattr(builtins, name, missing)
        builtins.get_price = fake.get_price
        builtins.get_extras = fake.get_extras
    sys.modules["jqdata"] = module
    try:
        name = "joinquant_research_runner_{}".format(id(fake))
        spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        return loaded
    finally:
        if old is None:
            sys.modules.pop("jqdata", None)
        else:
            sys.modules["jqdata"] = old
        if platform_builtins:
            for name, value in old_builtins.items():
                if value is missing:
                    delattr(builtins, name)
                else:
                    setattr(builtins, name, value)


@pytest.fixture
def market():
    days = ["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-08", "2024-02-01"]
    bars = {}
    for day, open_price, close_price in [
        ("2024-01-02", 10.0, 11.0),
        ("2024-01-03", 12.0, 12.0),
        ("2024-01-08", 12.0, 12.5),
        ("2024-02-01", 13.0, 13.0),
    ]:
        bars[("000001.XSHE", day)] = {
            "open": open_price,
            "close": close_price,
            "high_limit": open_price * 1.1,
            "low_limit": open_price * 0.9,
            "paused": False,
            "volume": 1_000_000,
        }
    return FakeJoinQuantData(days, bars)


def test_platform_file_is_old_runtime_compatible_and_self_contained():
    text = RUNNER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)

    assert "from __future__ import annotations" not in text
    assert "from quant_research" not in text
    assert "zip(" not in text or "strict=" not in text
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"sum", "all", "any"}


def test_platform_acceptance_example_is_deterministic():
    text = ACCEPTANCE_PATH.read_text(encoding="utf-8")

    assert "get_price" not in text
    assert 'FIRST_ASSET = "510300.XSHG"' in text
    assert 'SECOND_ASSET = "510500.XSHG"' in text
    assert "unexpected trade sequence" in text
    assert "acceptance test must finish with no positions" in text
    assert "JOINQUANT_RESEARCH_RUNNER_ACCEPTANCE_OK" in text


def test_platform_python3_builtin_data_api_is_supported(market):
    runner = load_runner(market, platform_builtins=True)

    assert runner.get_price.__self__ is market
    assert runner.get_extras.__self__ is market
    assert runner.get_all_trade_days.__self__ is market


def test_calendar_schedule_uses_actual_first_and_last_trade_days(market):
    runner = load_runner(market)
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 8), date(2024, 2, 1)]

    assert runner.scheduled_trade_days(days, "weekly", "first") == {
        date(2024, 1, 2),
        date(2024, 1, 8),
        date(2024, 2, 1),
    }
    assert runner.scheduled_trade_days(days, "weekly", "last") == {
        date(2024, 1, 3),
        date(2024, 1, 8),
        date(2024, 2, 1),
    }
    assert runner.scheduled_trade_days(days, "monthly", "first") == {
        date(2024, 1, 2),
        date(2024, 2, 1),
    }


def test_runner_uses_previous_trade_day_and_sells_before_buying(market):
    runner = load_runner(market)
    observations = []

    def targets(context):
        observations.append(context.observation_date)
        if context.current_date == date(2024, 1, 2):
            return {"000001.XSHE": 0.5}
        return {}

    config = runner.RunnerConfig(
        start_date="2024-01-02",
        end_date="2024-01-03",
        initial_cash=100_000,
        frequency="daily",
        buy_commission=0,
        sell_commission=0,
        minimum_commission=0,
        stamp_tax=0,
    )
    result = runner.ResearchRunner(config, targets).run()

    assert observations == [date(2023, 12, 29), date(2024, 1, 2)]
    filled = [order for order in result.orders if order["status"] == "filled"]
    assert [(order["side"], order["amount"]) for order in filled] == [
        ("buy", 5000),
        ("sell", 5000),
    ]
    assert result.equity[-1]["total_value"] == pytest.approx(110_000)
    assert result.positions[-1]["positions"] == {}


def test_lot_rounding_costs_and_limit_rejections(market):
    runner = load_runner(market)
    config = runner.RunnerConfig(
        start_date="2024-01-02",
        end_date="2024-01-02",
        initial_cash=10_050,
        frequency="daily",
        buy_commission=0.001,
        minimum_commission=5,
        stamp_tax=0,
    )
    result = runner.ResearchRunner(
        config, lambda context: {"000001.XSHE": 1.0}
    ).run()

    filled = [order for order in result.orders if order["status"] == "filled"]
    assert len(filled) == 1
    assert filled[0]["amount"] == 1000
    assert filled[0]["fees"] == pytest.approx(10)
    assert result.equity[-1]["cash"] == pytest.approx(40)

    blocked_bars = dict(market.bars)
    blocked_bars[("000001.XSHE", date(2024, 1, 2))] = {
        **blocked_bars[("000001.XSHE", date(2024, 1, 2))],
        "high_limit": 10.0,
    }
    blocked = FakeJoinQuantData(market.trade_days, blocked_bars)
    blocked_runner = load_runner(blocked)
    blocked_result = blocked_runner.ResearchRunner(
        blocked_runner.RunnerConfig(
            start_date="2024-01-02",
            end_date="2024-01-02",
            initial_cash=100_000,
        ),
        lambda context: {"000001.XSHE": 1.0},
    ).run()
    assert blocked_result.orders[0]["status"] == "rejected"
    assert blocked_result.orders[0]["reason"] == "high_limit"


def test_etf_buy_skips_stock_only_st_query(market):
    bars = {
        ("510300.XSHG", date(2024, 1, 2)): {
            "open": 3.0,
            "close": 3.0,
            "high_limit": 3.3,
            "low_limit": 2.7,
            "paused": False,
            "volume": 1_000_000,
        }
    }

    class EtfMarket(FakeJoinQuantData):
        def get_extras(self, name, code, start_date=None, end_date=None, df=None):
            raise ValueError("is_st only accepts stocks")

    etf_market = EtfMarket(market.trade_days[:2], bars)
    runner = load_runner(etf_market)
    result = runner.ResearchRunner(
        runner.RunnerConfig(
            start_date="2024-01-02",
            end_date="2024-01-02",
            initial_cash=100_000,
        ),
        lambda context: {"510300.XSHG": 1.0},
    ).run()

    assert result.orders[0]["status"] in {"filled", "partial"}
    assert result.orders[0]["code"] == "510300.XSHG"
    assert result.warnings == []


def test_stock_classification_covers_mainland_exchanges(market):
    runner = load_runner(market)

    assert runner.ResearchRunner._is_stock("000001.XSHE")
    assert runner.ResearchRunner._is_stock("600000.XSHG")
    assert runner.ResearchRunner._is_stock("430047.XBSE")
    assert runner.ResearchRunner._is_stock("920002.XBSE")
    assert not runner.ResearchRunner._is_stock("510300.XSHG")
    assert not runner.ResearchRunner._is_stock("159915.XSHE")


def test_failed_sell_does_not_release_cash_for_replacement_buy(market):
    bars = dict(market.bars)
    bars[("000001.XSHE", date(2024, 1, 3))] = {
        **bars[("000001.XSHE", date(2024, 1, 3))],
        "low_limit": 12.0,
    }
    for day in ("2024-01-02", "2024-01-03"):
        bars[("000002.XSHE", day)] = {
            "open": 10.0,
            "close": 10.0,
            "high_limit": 11.0,
            "low_limit": 9.0,
            "paused": False,
            "volume": 1_000_000,
        }
    data = FakeJoinQuantData(market.trade_days, bars)
    runner = load_runner(data)

    def targets(context):
        if context.current_date == date(2024, 1, 2):
            return {"000001.XSHE": 1.0}
        return {"000002.XSHE": 1.0}

    result = runner.ResearchRunner(
        runner.RunnerConfig(
            start_date="2024-01-02",
            end_date="2024-01-03",
            initial_cash=100_000,
            frequency="daily",
            buy_commission=0,
            sell_commission=0,
            minimum_commission=0,
            stamp_tax=0,
        ),
        targets,
    ).run()

    day_two = [order for order in result.orders if order["date"] == "2024-01-03"]
    assert [(order["side"], order["reason"]) for order in day_two] == [
        ("sell", "low_limit"),
        ("buy", "insufficient_cash"),
    ]
    assert result.positions[-1]["positions"]["000001.XSHE"]["amount"] == 10_000


def test_rejects_st_buys_and_invalid_target_weight_sum(market):
    st_market = FakeJoinQuantData(
        market.trade_days,
        market.bars,
        st={("000001.XSHE", date(2024, 1, 2)): True},
    )
    runner = load_runner(st_market)
    config = runner.RunnerConfig(
        start_date="2024-01-02",
        end_date="2024-01-02",
        initial_cash=100_000,
    )
    result = runner.ResearchRunner(
        config, lambda context: {"000001.XSHE": 1.0}
    ).run()
    assert result.orders[0]["reason"] == "st"

    with pytest.raises(ValueError, match="sum to at most 1"):
        runner.ResearchRunner(
            config, lambda context: {"000001.XSHE": 0.6, "000002.XSHE": 0.5}
        ).run()


def test_export_creates_reproducible_archive_payload(market, tmp_path):
    runner = load_runner(market)
    source = tmp_path / "strategy.py"
    source.write_text("def target_weights(context):\n    return {}\n", encoding="utf-8")
    config = runner.RunnerConfig(
        start_date="2024-01-02",
        end_date="2024-01-03",
        initial_cash=100_000,
        run_id="unit-test-v1",
    )
    result = runner.ResearchRunner(config, lambda context: {}).run()
    output = tmp_path / "result"

    manifest = result.export(
        output,
        strategy_id="example-strategy",
        variant="baseline",
        source_path=source,
    )

    expected = {
        "engine.py",
        "manifest.json",
        "report.md",
        "source.py",
        "raw/equity.csv",
        "raw/orders.csv",
        "raw/trades.csv",
        "raw/positions.csv",
    }
    actual = {
        str(path.relative_to(output)).replace("\\", "/")
        for path in output.rglob("*")
        if path.is_file()
    }
    assert expected <= actual
    saved = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest
    assert saved["platform"] == "joinquant-research"
    assert saved["source_sha256"]
    assert saved["artifacts"]["raw/equity.csv"]["sha256"]
    assert saved["metrics"]["longest_underwater_days"] >= 0
    assert (tmp_path / "result.zip").is_file()
