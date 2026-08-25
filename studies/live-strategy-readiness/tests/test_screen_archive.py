import csv
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "screen_archive.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_screen_archive", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_analyze_source_extracts_execution_and_research_risk_features():
    code = """
from jqdata import *

def initialize(context):
    set_option('use_real_price', True)
    set_slippage(FixedSlippage(0))
    run_daily(trade, time='14:55')

def trade(context):
    stocks = get_index_stocks('000300.XSHG')
    bars = get_price(stocks, end_date=context.current_dt, frequency='1m')
    if bars is not None:
        order_target_value(stocks[0], context.portfolio.total_value)
"""

    features = MODULE.analyze_source(code)

    assert features["uses_real_price"] is True
    assert features["avoids_future_data"] is False
    assert features["uses_zero_slippage"] is True
    assert features["uses_minute_data"] is True
    assert features["uses_index_membership"] is True
    assert features["undated_index_membership_risk"] is True
    assert features["order_call_count"] == 1
    assert features["branch_count"] >= 1


def test_natural_oos_marks_current_source_snapshot_as_non_strict_grade_c():
    result = MODULE.natural_oos_fields(
        {
            "post_time": "2024-06-16 18:35:14",
            "end_date": "2024-06-01",
        },
        source_vintage_predates_oos=False,
        as_of=date(2026, 8, 25),
    )

    assert result["oos_integrity_grade"] == "C"
    assert result["backtest_to_post_days"] == 15
    assert result["post_publication_days"] == 800
    assert result["natural_oos_eligible"] is True
    assert result["strict_natural_oos"] is False


def test_build_lineages_groups_shared_posts_and_near_duplicate_sources():
    records = [
        {
            "item_id": "a",
            "primary_url": "https://www.joinquant.com/post/1",
            "author": "alpha",
            "source_hash": "hash-a",
            "source_tokens": {"def", "initialize", "order", "stock", "value"},
            "core_function_hashes": {"core-a"},
        },
        {
            "item_id": "b",
            "primary_url": "https://www.joinquant.com/post/1",
            "author": "alpha",
            "source_hash": "hash-b",
            "source_tokens": {"def", "initialize", "order", "stock", "cash"},
            "core_function_hashes": {"core-a"},
        },
        {
            "item_id": "c",
            "primary_url": "https://www.joinquant.com/post/2",
            "author": "beta",
            "source_hash": "hash-c",
            "source_tokens": {"machine", "learning", "pipeline"},
            "core_function_hashes": {"core-c"},
        },
    ]

    lineages = MODULE.build_lineages(records)

    by_id = {row["item_id"]: row for row in lineages}
    assert by_id["a"]["lineage_id"] == by_id["b"]["lineage_id"]
    assert by_id["a"]["lineage_id"] != by_id["c"]["lineage_id"]
    assert by_id["a"]["shared_post"] is True
    assert by_id["a"]["relation"] in {"shared-post", "near-duplicate"}


def test_generate_screening_writes_all_preregistered_tables(tmp_path):
    archive_data = tmp_path / "data"
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "screening"
    archive_data.mkdir()
    source_dir.mkdir()

    rows = [
        {
            "local_category": "sample",
            "local_file": "sample/one.txt",
            "local_strategy_name": "低风险中等收益策略",
            "primary_url": "https://www.joinquant.com/post/1",
            "canonical_url": "https://www.joinquant.com/view/community/detail/one",
            "status": "ok",
            "post_title": "sample one",
            "author": "alpha",
            "post_time": "2024-06-16 18:35:14",
            "start_date": "2018-01-01",
            "end_date": "2024-06-01",
            "base_capital": 1000000,
            "frequency_code": "day",
            "annual_return_percent": 12.0,
            "max_drawdown_percent": 10.0,
            "sharpe": 1.0,
            "sortino": 1.5,
            "turnover_rate_percent": 20.0,
            "win_count": 10,
            "lose_count": 5,
            "trading_days": 1500,
        },
        {
            "local_category": "sample",
            "local_file": "sample/two.txt",
            "local_strategy_name": "intraday",
            "primary_url": "https://www.joinquant.com/post/2",
            "canonical_url": "https://www.joinquant.com/view/community/detail/two",
            "status": "post_without_backtest",
            "post_title": "sample two",
            "author": "beta",
            "post_time": "2025-01-01 00:00:00",
        },
    ]
    with (archive_data / "summary.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    (source_dir / "sample").mkdir()
    (source_dir / "sample" / "one.py").write_text(
        "set_option('use_real_price', True)\nset_option('avoid_future_data', True)\n",
        encoding="utf-8",
    )
    (source_dir / "sample" / "two.py").write_text(
        "def initialize(context):\n    pass\n",
        encoding="utf-8",
    )
    manifest_rows = [
        {
            "archive_path": "sample/one.py",
            "strategy_name": "低风险中等收益策略",
            "archive_sha256": "hash-one",
            "python3_ast_parse": True,
            "primary_url": "https://www.joinquant.com/post/1",
        },
        {
            "archive_path": "sample/two.py",
            "strategy_name": "intraday",
            "archive_sha256": "hash-two",
            "python3_ast_parse": True,
            "primary_url": "https://www.joinquant.com/post/2",
        },
    ]
    with (source_dir / "manifest.jsonl").open("w", encoding="utf-8") as handle:
        for row in manifest_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    result = MODULE.generate_screening(
        summary_path=archive_data / "summary.jsonl",
        manifest_path=source_dir / "manifest.jsonl",
        sources_root=source_dir,
        output_dir=output_dir,
        as_of=date(2026, 8, 25),
        shortlist_size=10,
    )

    assert result["archive_items"] == 2
    assert result["public_backtests"] == 1
    expected = {
        "archive-universe.csv",
        "strategy-lineage.csv",
        "natural-oos.csv",
        "candidate-shortlist.csv",
    }
    assert {path.name for path in output_dir.iterdir()} == expected

    with (output_dir / "candidate-shortlist.csv").open(
        newline="", encoding="utf-8-sig"
    ) as handle:
        shortlist = list(csv.DictReader(handle))
    assert shortlist[0]["strategy_name"] == "低风险中等收益策略"
    assert shortlist[0]["seed_priority"] == "P0"


def test_committed_stage_zero_outputs_cover_archive_and_deduplicate_shortlist():
    screening_dir = Path(__file__).resolve().parents[1] / "screening"

    def read_csv(name):
        with (screening_dir / name).open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    universe = read_csv("archive-universe.csv")
    lineages = read_csv("strategy-lineage.csv")
    natural_oos = read_csv("natural-oos.csv")
    shortlist = read_csv("candidate-shortlist.csv")

    assert len(universe) == 593
    assert sum(row["archive_status"] == "ok" for row in universe) == 503
    assert all(row["source_present"] == "true" for row in universe)
    assert len(lineages) == 593
    assert len({row["lineage_id"] for row in lineages}) == 445
    assert sum(row["natural_oos_eligible"] == "true" for row in natural_oos) == 415
    assert not any(row["strict_natural_oos"] == "true" for row in natural_oos)
    assert len(shortlist) == 50
    assert len({row["lineage_id"] for row in shortlist}) == 50
    assert {row["seed_label"] for row in shortlist if row["seed_priority"] == "P0"} == {
        "低风险中等收益",
        "多品种 ETF 动量 + EPO",
        "白马股攻防",
    }
