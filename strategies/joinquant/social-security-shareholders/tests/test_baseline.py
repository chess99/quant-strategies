import ast
import importlib.util
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]
BASELINE = FAMILY / "baseline.py"
VARIANTS = {
    10: FAMILY / "variants" / "top10.py",
    20: FAMILY / "variants" / "top20.py",
    50: FAMILY / "variants" / "top50.py",
}


class LazyCurrentData(dict):
    """模拟聚宽必须通过 mapping[code] 才加载行情的惰性映射。"""

    def __init__(self, snapshots):
        super().__init__()
        self.snapshots = snapshots

    def __missing__(self, key):
        snapshot = self.snapshots[key]
        self[key] = snapshot
        return snapshot


def load_strategy(path=BASELINE):
    spec = importlib.util.spec_from_file_location(
        "social_security_shareholders_%s" % path.stem,
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_logger():
    return SimpleNamespace(
        info=lambda *args: None,
        warn=lambda *args: None,
        error=lambda *args: None,
    )


def test_platform_sources_follow_joinquant_runtime_contracts():
    for path in [BASELINE, *VARIANTS.values()]:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        unqualified = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"all", "any", "sum"}
        ]

        assert "from __future__ import annotations" not in source
        assert ".get(code)" not in source
        assert unqualified == []


def test_variants_only_change_target_count():
    baseline = BASELINE.read_text(encoding="utf-8")
    for count, path in VARIANTS.items():
        variant = path.read_text(encoding="utf-8")
        assert "TARGET_COUNT = %d" % count in variant
        assert variant.replace(
            "TARGET_COUNT = %d" % count,
            "TARGET_COUNT = 100",
        ) == baseline


def test_report_date_mapping():
    strategy = load_strategy()

    assert strategy.get_report_date(date(2024, 5, 6)) == date(2024, 3, 31)
    assert strategy.get_report_date(date(2024, 9, 2)) == date(2024, 6, 30)
    assert strategy.get_report_date(date(2024, 11, 1)) == date(2024, 9, 30)
    assert strategy.get_report_date(date(2024, 6, 3)) is None


def test_aggregate_holdings_keeps_latest_revision_then_sums_funds():
    strategy = load_strategy()
    rows = pd.DataFrame(
        [
            {
                "code": "000001.XSHE",
                "shareholder_name": "全国社保基金一零一组合",
                "share_number": 100,
                "pub_date": "2024-04-20",
            },
            {
                "code": "000001.XSHE",
                "shareholder_name": "全国社保基金一零一组合",
                "share_number": 120,
                "pub_date": "2024-04-25",
            },
            {
                "code": "000001.XSHE",
                "shareholder_name": "全国社保基金一零二组合",
                "share_number": 80,
                "pub_date": "2024-04-22",
            },
        ]
    )

    result = strategy.aggregate_holdings(rows)

    assert result.to_dict() == {"000001.XSHE": 200}


def test_rank_holdings_uses_social_security_market_value():
    strategy = load_strategy()
    holdings = pd.Series(
        {"000001.XSHE": 200, "600000.XSHG": 50, "000002.XSHE": 100}
    )
    closes = {"000001.XSHE": 10.0, "600000.XSHG": 50.0, "000002.XSHE": 30.0}

    result = strategy.rank_holdings(holdings, closes, list(holdings.index), 2)

    assert result == ["000002.XSHE", "600000.XSHG"]


def test_filter_stocks_materializes_lazy_current_data():
    strategy = load_strategy()
    strategy.log = make_logger()
    snapshot = SimpleNamespace(
        paused=False,
        is_st=False,
        name="平安银行",
        last_price=10,
        high_limit=11,
        low_limit=9,
    )
    securities = pd.DataFrame(
        {"start_date": [date(1991, 4, 3)]},
        index=["000001.XSHE"],
    )

    result = strategy.filter_stocks(
        ["000001.XSHE"],
        LazyCurrentData({"000001.XSHE": snapshot}),
        securities,
        date(2024, 5, 6),
    )

    assert result == ["000001.XSHE"]


class FakeField:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __lt__(self, other):
        return ("lt", self.name, other)

    def like(self, pattern):
        return ("like", self.name, pattern)


class FakeQuery:
    def __init__(self, fields):
        self.fields = fields
        self.conditions = ()

    def filter(self, *conditions):
        self.conditions = conditions
        return self


def test_shareholder_query_uses_report_and_publication_cutoffs(monkeypatch):
    strategy = load_strategy()
    strategy.log = make_logger()
    table = SimpleNamespace(
        code=FakeField("code"),
        shareholder_name=FakeField("shareholder_name"),
        share_number=FakeField("share_number"),
        pub_date=FakeField("pub_date"),
        end_date=FakeField("end_date"),
    )
    rows = pd.DataFrame(
        [
            {
                "code": "000001.XSHE",
                "shareholder_name": "全国社保基金一零一组合",
                "share_number": 100,
                "pub_date": "2024-04-30",
            }
        ]
    )
    captured = {}

    def fake_query(*fields):
        captured["query"] = FakeQuery(fields)
        return captured["query"]

    monkeypatch.setattr(strategy, "query", fake_query, raising=False)
    monkeypatch.setattr(
        strategy,
        "finance",
        SimpleNamespace(
            STK_SHAREHOLDER_FLOATING_TOP10=table,
            run_query=lambda query_object: rows,
        ),
        raising=False,
    )

    result = strategy.get_social_security_holdings(
        date(2024, 3, 31),
        date(2024, 5, 6),
    )

    assert result.to_dict() == {"000001.XSHE": 100}
    assert captured["query"].conditions == (
        ("eq", "end_date", date(2024, 3, 31)),
        ("lt", "pub_date", date(2024, 5, 6)),
        ("like", "shareholder_name", "%社保基金%"),
    )


def test_initialize_sets_point_in_time_options_and_baseline_count(monkeypatch):
    strategy = load_strategy()
    strategy.g = SimpleNamespace()
    options = []
    schedules = []

    class FakeSlippage:
        def __init__(self, value):
            self.value = value

    class FakeOrderCost:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        strategy,
        "set_benchmark",
        lambda code: options.append(("benchmark", code)),
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "set_option",
        lambda name, value: options.append((name, value)),
        raising=False,
    )
    monkeypatch.setattr(strategy, "set_slippage", lambda value: None, raising=False)
    monkeypatch.setattr(
        strategy,
        "set_order_cost",
        lambda value, type=None: None,
        raising=False,
    )
    monkeypatch.setattr(strategy, "FixedSlippage", FakeSlippage, raising=False)
    monkeypatch.setattr(strategy, "OrderCost", FakeOrderCost, raising=False)
    monkeypatch.setattr(
        strategy,
        "run_monthly",
        lambda func, **kwargs: schedules.append((func.__name__, kwargs)),
        raising=False,
    )

    strategy.initialize(SimpleNamespace())

    assert strategy.g.stock_count == 100
    assert options == [
        ("benchmark", "000300.XSHG"),
        ("use_real_price", True),
        ("avoid_future_data", True),
    ]
    assert [item[0] for item in schedules] == [
        "sell_before_rebalance",
        "buy_after_disclosure",
    ]


def test_calculate_targets_uses_previous_trade_day(monkeypatch):
    strategy = load_strategy()
    strategy.g = SimpleNamespace(stock_count=1)
    strategy.log = make_logger()
    holdings = pd.Series({"000001.XSHE": 200})
    securities = pd.DataFrame(
        {"start_date": [date(1991, 4, 3)]},
        index=["000001.XSHE"],
    )
    current = LazyCurrentData(
        {
            "000001.XSHE": SimpleNamespace(
                paused=False,
                is_st=False,
                name="平安银行",
                last_price=10,
                high_limit=11,
                low_limit=9,
            )
        }
    )
    calls = []

    monkeypatch.setattr(
        strategy,
        "get_social_security_holdings",
        lambda report_date, buy_date: holdings,
    )
    monkeypatch.setattr(
        strategy,
        "get_all_securities",
        lambda types, date=None: calls.append(date) or securities,
        raising=False,
    )
    monkeypatch.setattr(strategy, "get_current_data", lambda: current, raising=False)
    monkeypatch.setattr(
        strategy,
        "get_previous_closes",
        lambda codes, previous_date: calls.append(previous_date)
        or {"000001.XSHE": 10.0},
    )
    context = SimpleNamespace(
        current_dt=datetime(2024, 5, 6, 9, 31),
        previous_date=date(2024, 4, 30),
    )

    assert strategy.calculate_target_stocks(context) == ["000001.XSHE"]
    assert calls == [date(2024, 4, 30), date(2024, 4, 30)]


def test_adjust_positions_skips_target_too_small_for_one_board_lot(monkeypatch):
    strategy = load_strategy()
    strategy.log = make_logger()
    orders = []
    current = LazyCurrentData(
        {
            "000001.XSHE": SimpleNamespace(
                paused=False,
                is_st=False,
                name="高价股",
                last_price=60,
                high_limit=66,
                low_limit=54,
            ),
            "600000.XSHG": SimpleNamespace(
                paused=False,
                is_st=False,
                name="低价股",
                last_price=10,
                high_limit=11,
                low_limit=9,
            ),
        }
    )
    monkeypatch.setattr(strategy, "get_current_data", lambda: current, raising=False)
    monkeypatch.setattr(
        strategy,
        "order_target_value",
        lambda code, value: orders.append((code, value)),
        raising=False,
    )
    context = SimpleNamespace(
        portfolio=SimpleNamespace(total_value=10000, positions={})
    )

    strategy.adjust_positions(
        context,
        ["000001.XSHE", "600000.XSHG"],
    )

    assert orders == [("600000.XSHG", 5000)]


def test_adjust_positions_deducts_blocked_residual_value(monkeypatch):
    strategy = load_strategy()
    strategy.log = make_logger()
    orders = []
    current = LazyCurrentData(
        {
            "OLD.XSHE": SimpleNamespace(
                paused=True,
                is_st=False,
                name="旧仓",
                last_price=10,
                high_limit=11,
                low_limit=9,
            ),
            "000001.XSHE": SimpleNamespace(
                paused=False,
                is_st=False,
                name="目标一",
                last_price=10,
                high_limit=11,
                low_limit=9,
            ),
            "600000.XSHG": SimpleNamespace(
                paused=False,
                is_st=False,
                name="目标二",
                last_price=10,
                high_limit=11,
                low_limit=9,
            ),
        }
    )
    monkeypatch.setattr(strategy, "get_current_data", lambda: current, raising=False)
    monkeypatch.setattr(
        strategy,
        "order_target_value",
        lambda code, value: orders.append((code, value)),
        raising=False,
    )
    context = SimpleNamespace(
        portfolio=SimpleNamespace(
            total_value=10000,
            positions={"OLD.XSHE": SimpleNamespace(value=2000)},
        )
    )

    strategy.adjust_positions(context, ["000001.XSHE", "600000.XSHG"])

    assert orders == [("000001.XSHE", 4000), ("600000.XSHG", 4000)]
