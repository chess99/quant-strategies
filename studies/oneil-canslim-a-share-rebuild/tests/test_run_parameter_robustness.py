import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_parameter_robustness.py"
SPEC = importlib.util.spec_from_file_location("oneil_parameter_robustness", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parameter_grid_changes_one_dimension_at_a_time():
    grid = MODULE.parameter_grid()
    base = grid["base"]

    assert len(grid) == 9
    for name, config in grid.items():
        changed = [key for key in base if config[key] != base[key]]
        if name == "base":
            assert changed == []
        elif name.startswith("quality-") and not name.startswith("quality-age"):
            assert changed == ["growth_weight", "momentum_weight", "quality_weight"]
        else:
            assert len(changed) == 1
        assert abs(
            config["growth_weight"]
            + config["momentum_weight"]
            + config["quality_weight"]
            - 1.0
        ) < 1e-9
