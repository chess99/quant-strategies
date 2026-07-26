import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_entry_event_study.py"
SPEC = importlib.util.spec_from_file_location("oneil_entry_event_study", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_prices():
    dates = pd.bdate_range("2024-01-01", periods=80)
    high = pd.Series(np.arange(80, dtype=float) + 100.0, index=dates)
    close = high - 1.0
    volume = pd.Series(100.0, index=dates)
    # Day 60 closes above the prior high; the signal day's own high is larger and
    # must not be included in the pivot.
    close.iloc[60] = high.iloc[59] + 0.5
    high.iloc[60] = close.iloc[60] + 5.0
    volume.iloc[60] = 150.0
    return pd.DataFrame(
        {"open": close - 0.2, "high": high, "close": close, "volume": volume}
    )


def test_signal_frame_excludes_signal_day_from_pivot_and_volume_average():
    signals = MODULE.compute_signal_frame(make_prices())
    date = signals.index[60]

    assert signals.loc[date, "new_high_20"]
    assert signals.loc[date, "new_high_55"]
    assert signals.loc[date, "relative_volume_50"] == 1.5
    assert signals.loc[date, "new_high_55_volume_1_4"]


def test_first_entry_uses_next_open_and_stays_before_next_refresh():
    signals = MODULE.compute_signal_frame(make_prices())
    dates = signals.index

    entry = MODULE.first_entry_in_window(
        signals,
        signal_name="new_high_55",
        observation_date=dates[55],
        next_refresh_date=dates[70],
    )
    too_late = MODULE.first_entry_in_window(
        signals,
        signal_name="new_high_55",
        observation_date=dates[55],
        next_refresh_date=dates[61],
    )

    assert entry == dates[61]
    assert too_late is None


def test_event_outcomes_use_entry_open_and_future_session_close():
    prices = make_prices()
    benchmark = prices.copy()
    entry_date = prices.index[61]

    result = MODULE.event_outcomes(prices, benchmark, entry_date, horizons=(5,))

    expected = prices["close"].iloc[65] / prices["open"].iloc[61] - 1.0
    assert result["return_5"] == expected
    assert result["benchmark_return_5"] == expected
    assert result["excess_return_5"] == 0.0


def test_structured_base_requires_prior_runup_contraction_and_upper_handle():
    dates = pd.bdate_range("2022-01-03", periods=400)
    close = np.linspace(40.0, 100.0, 400)
    high = close + 1.0
    low = close - 1.0
    volume = np.full(400, 200.0)
    signal_location = 350
    base_start = signal_location - 65
    first = np.linspace(100.0, 86.0, 20)
    middle = np.linspace(88.0, 96.0, 25)
    last = np.linspace(96.0, 99.0, 20)
    base = np.concatenate([first, middle, last])
    close[base_start:signal_location] = base
    high[base_start:signal_location] = base + 1.0
    low[base_start:signal_location] = base - 1.0
    volume[base_start:base_start + 20] = 250.0
    volume[signal_location - 20:signal_location] = 100.0
    close[signal_location] = 101.5
    high[signal_location] = 110.0
    low[signal_location] = 100.0
    prices = pd.DataFrame(
        {"open": close - 0.2, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )

    signals = MODULE.compute_signal_frame(prices)

    assert signals.iloc[signal_location]["structured_base_breakout"]
    # The signal day's own high is not allowed to move the pivot or invalidate the buy zone.
    prices.iloc[signal_location, prices.columns.get_loc("high")] = 1_000.0
    changed = MODULE.compute_signal_frame(prices)
    assert changed.iloc[signal_location]["structured_base_breakout"]
