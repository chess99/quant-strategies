import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_holding_ablation.py"
SPEC = importlib.util.spec_from_file_location("oneil_holding_ablation", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_hard_stop_uses_previous_close_and_inclusive_eight_percent_threshold():
    assert MODULE.hard_stop_trigger(92.0, 100.0, stop_loss=0.08)
    assert MODULE.hard_stop_trigger(90.0, 100.0, stop_loss=0.08)
    assert not MODULE.hard_stop_trigger(92.01, 100.0, stop_loss=0.08)
    assert not MODULE.hard_stop_trigger(None, 100.0, stop_loss=0.08)


def test_trend_exit_requires_valid_close_below_moving_average():
    assert MODULE.trend_exit_trigger(99.0, 100.0)
    assert not MODULE.trend_exit_trigger(100.0, 100.0)
    assert not MODULE.trend_exit_trigger(float("nan"), 100.0)


def test_winner_hold_retains_trending_positions_then_fills_by_current_rank():
    selected = MODULE.winner_hold_selection(
        held_symbols=["OLD_A", "OLD_B", "OLD_C"],
        ranked_candidates=["NEW_A", "OLD_B", "NEW_B", "NEW_C"],
        trend_ok={"OLD_A": True, "OLD_B": False, "OLD_C": True},
        maximum_positions=4,
    )

    assert selected == ["OLD_A", "OLD_C", "NEW_A", "OLD_B"]
    assert len(selected) == len(set(selected))
