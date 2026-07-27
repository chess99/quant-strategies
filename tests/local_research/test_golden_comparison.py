import json

from quant_research.golden_comparison import (
    load_joinquant_stats,
    parse_joinquant_small_cap_log,
)


def test_parse_joinquant_structured_log_with_prefixes():
    text = """
2020-01-02 INFO QR_CANDIDATES|2020-01-02|2019-12-31|3800|2|600000.XSHG,000001.XSHE
2020-01-02 INFO QR_ORDER|2020-01-02|target|600000.XSHG|1000|900|held
2020-01-02 INFO QR_ORDER|2020-01-02|target|000001.XSHE|none
2020-01-02 INFO QR_HOLDINGS|2020-01-02|1|600000.XSHG|1010000.5
"""

    parsed = parse_joinquant_small_cap_log(text)

    assert parsed["candidates"]["symbol"].tolist() == ["SH600000", "SZ000001"]
    assert parsed["orders"].iloc[0]["filled_shares"] == 900
    assert parsed["orders"].iloc[1]["status"] == "none"
    assert parsed["holdings"].iloc[0]["total_value"] == 1010000.5


def test_load_joinquant_stats_accepts_platform_names(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text(
        json.dumps(
            {
                "stats": {
                    "algorithm_return": 1.2,
                    "annual_algo_return": 0.3,
                    "max_drawdown": 0.2,
                    "sharpe": 1.1,
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_joinquant_stats(path) == {
        "total_return": 1.2,
        "annualized_return": 0.3,
        "maximum_drawdown": 0.2,
        "sharpe": 1.1,
    }
