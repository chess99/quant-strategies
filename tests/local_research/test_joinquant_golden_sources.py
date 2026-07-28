import ast
import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "joinquant_strategy.py",
    ROOT
    / "studies"
    / "joinquant-value-quality-golden-comparison"
    / "joinquant_strategy.py",
]
LOCAL_SOURCES = [path.with_name("run_local.py") for path in SOURCES]
SMALL_CAP_SPEC = importlib.util.spec_from_file_location(
    "joinquant_small_cap_run_local", LOCAL_SOURCES[0]
)
SMALL_CAP_MODULE = importlib.util.module_from_spec(SMALL_CAP_SPEC)
SMALL_CAP_SPEC.loader.exec_module(SMALL_CAP_MODULE)
VALUE_QUALITY_SPEC = importlib.util.spec_from_file_location(
    "joinquant_value_quality_run_local", LOCAL_SOURCES[1]
)
VALUE_QUALITY_MODULE = importlib.util.module_from_spec(VALUE_QUALITY_SPEC)
VALUE_QUALITY_SPEC.loader.exec_module(VALUE_QUALITY_MODULE)


def _calls(tree, function_name):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function_name
    ]


@pytest.mark.parametrize("source_path", SOURCES, ids=lambda path: path.parent.name)
def test_joinquant_golden_source_is_self_contained_and_point_in_time(source_path):
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))

    assert "from __future__ import annotations" not in text
    assert "from quant_research" not in text
    assert 'set_option("avoid_future_data", True)' in text
    assert 'set_option("use_real_price", True)' in text
    assert "run_monthly(" in text
    assert "context.previous_date" in text
    assert "current[code]" in text
    assert "current.get(" not in text
    for marker in ("QR_CANDIDATES|", "QR_ORDERS|", "QR_HOLDINGS|"):
        assert marker in text
    assert "QR_ORDER|" not in text

    for function_name in ("get_all_securities", "get_fundamentals"):
        calls = _calls(tree, function_name)
        assert calls
        assert all(any(keyword.arg == "date" for keyword in call.keywords) for call in calls)

    forbidden_direct_builtins = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert not forbidden_direct_builtins
    for builtin_name in ("sum", "all", "any"):
        assert f"builtins.{builtin_name}(" in text


def test_value_quality_source_batches_expensive_platform_queries():
    source_path = SOURCES[1]
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))

    industry_calls = _calls(tree, "get_industry")
    assert industry_calls
    assert all(any(keyword.arg == "date" for keyword in call.keywords) for call in industry_calls)
    assert text.count("for batch in _chunks(codes, 300)") == 2


@pytest.mark.parametrize("source_path", SOURCES, ids=lambda path: path.parent.name)
def test_joinquant_golden_orders_set_star_market_protection_prices(source_path):
    text = source_path.read_text(encoding="utf-8")

    assert "MarketOrderStyle(current[code].low_limit)" in text
    assert "MarketOrderStyle(current[code].high_limit)" in text


@pytest.mark.parametrize("source_path", LOCAL_SOURCES, ids=lambda path: path.parent.name)
def test_local_golden_source_uses_point_in_time_names(source_path):
    text = source_path.read_text(encoding="utf-8")

    assert "build_event_cross_sections" in text
    assert '"st_name_events"' in text
    assert '"delisting_events"' in text
    assert "INITIAL_CASH = 10_000_000.0" in text
    assert "build_delisting_actions" in text
    assert r"ST|\*|退" in text
    assert 'master[["symbol", "exchange", "start_date", "end_date", "display_name"]]' not in text


def test_small_cap_external_targets_require_complete_ten_stock_schedule(tmp_path):
    path = tmp_path / "targets.csv"
    rows = []
    for date in ("2023-01-03", "2023-02-01"):
        for rank in range(1, 11):
            rows.append(
                {
                    "execution_date": date,
                    "symbol": f"SH60{rank:04d}",
                    "rank": rank,
                    "selected": True,
                }
            )
        rows.append(
            {
                "execution_date": date,
                "symbol": "SH609999",
                "rank": 11,
                "selected": False,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
    schedule = pd.DataFrame(
        {"execution_date": pd.to_datetime(["2023-01-03", "2023-02-01"])}
    )

    targets = SMALL_CAP_MODULE.load_external_targets(path, schedule)

    assert list(targets) == list(schedule["execution_date"])
    assert all(len(symbols) == 10 for symbols in targets.values())
    assert targets[pd.Timestamp("2023-01-03")][0] == "SH600001"


def test_small_cap_external_targets_reject_missing_rebalance_date(tmp_path):
    path = tmp_path / "targets.csv"
    pd.DataFrame(
        {
            "execution_date": ["2023-01-03"] * 10,
            "symbol": [f"SH60{rank:04d}" for rank in range(1, 11)],
            "rank": range(1, 11),
            "selected": [True] * 10,
        }
    ).to_csv(path, index=False)
    schedule = pd.DataFrame(
        {"execution_date": pd.to_datetime(["2023-01-03", "2023-02-01"])}
    )

    with pytest.raises(ValueError, match="rebalance dates"):
        SMALL_CAP_MODULE.load_external_targets(path, schedule)


def test_value_quality_external_targets_require_complete_twenty_stock_schedule(
    tmp_path,
):
    path = tmp_path / "targets.csv"
    rows = []
    for date in ("2023-01-03", "2023-02-01"):
        for rank in range(1, 21):
            rows.append(
                {
                    "execution_date": date,
                    "symbol": f"SH60{rank:04d}",
                    "rank": rank,
                    "selected": True,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)
    schedule = pd.DataFrame(
        {"execution_date": pd.to_datetime(["2023-01-03", "2023-02-01"])}
    )

    targets = VALUE_QUALITY_MODULE.load_external_targets(path, schedule)

    assert list(targets) == list(schedule["execution_date"])
    assert all(len(symbols) == 20 for symbols in targets.values())
    assert targets[pd.Timestamp("2023-01-03")][0] == "SH600001"
