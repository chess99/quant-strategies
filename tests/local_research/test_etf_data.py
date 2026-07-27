import pandas as pd
import pytest

from quant_research.data.etf import normalize_sina_etf, validate_etf_daily


def test_sina_etf_normalization_builds_total_return_factor_from_dividend():
    quotes = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 9.1, 9.4],
            "high": [10.2, 9.4, 9.7],
            "low": [9.8, 9.0, 9.3],
            "close": [10.0, 9.2, 9.6],
            "volume": [1000, 1200, 900],
            "amount": [10000, 11100, 8600],
        }
    )
    dividends = pd.DataFrame(
        {"日期": ["2024-01-03"], "累计分红": [1.0]}
    )

    frame = normalize_sina_etf("SH510300", quotes, dividends)

    assert frame["cash_dividend"].tolist() == [0.0, 1.0, 0.0]
    assert frame.loc[1, "adjusted_close"] / frame.loc[0, "adjusted_close"] == (
        pytest.approx((9.2 + 1.0) / 10.0)
    )
    assert frame.loc[2, "factor"] == pytest.approx(frame.loc[1, "factor"])


def test_sina_etf_normalization_repairs_common_share_split():
    quotes = pd.DataFrame(
        {
            "date": ["2022-01-13", "2022-01-14"],
            "open": [5.1, 1.0],
            "high": [5.2, 1.03],
            "low": [5.0, 0.99],
            "close": [5.15, 1.01],
            "volume": [1000, 5000],
            "amount": [5100, 5050],
        }
    )

    frame = normalize_sina_etf("SH513100", quotes)

    assert frame.loc[1, "corporate_action_multiplier"] == pytest.approx(5.0)
    assert frame.loc[1, "adjusted_close"] / frame.loc[0, "adjusted_close"] == (
        pytest.approx(1.01 * 5.0 / 5.15)
    )


def test_sina_etf_normalization_repairs_three_for_two_share_split():
    quotes = pd.DataFrame(
        {
            "date": ["2021-09-10", "2021-09-13"],
            "open": [1.497, 1.045],
            "high": [1.575, 1.048],
            "low": [1.490, 0.997],
            "close": [1.561, 1.001],
            "volume": [44399602, 89485300],
            "amount": [68120731, 90288000],
        }
    )

    frame = normalize_sina_etf("SZ159813", quotes)

    assert frame.loc[1, "corporate_action_multiplier"] == pytest.approx(1.5)
    assert frame.loc[1, "adjusted_close"] / frame.loc[0, "adjusted_close"] == (
        pytest.approx(1.001 * 1.5 / 1.561)
    )


def test_sina_etf_normalization_rejects_duplicate_or_broken_ohlc():
    frame = pd.DataFrame(
        {
            "symbol": ["SH510300", "SH510300"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "open": [10.0, 10.0],
            "high": [9.0, 9.0],
            "low": [8.0, 8.0],
            "close": [10.0, 10.0],
            "volume": [1.0, 1.0],
            "amount": [1.0, 1.0],
            "cash_dividend": [0.0, 0.0],
            "corporate_action_multiplier": [1.0, 1.0],
            "factor": [1.0, 1.0],
            "adjusted_open": [10.0, 10.0],
            "adjusted_high": [9.0, 9.0],
            "adjusted_low": [8.0, 8.0],
            "adjusted_close": [10.0, 10.0],
            "source": ["fixture", "fixture"],
            "quality_grade": ["B", "B"],
        }
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_etf_daily(frame)
