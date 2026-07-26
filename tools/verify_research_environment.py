"""Verify that the locked research environment is isolated and functional."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import site
import sys
from importlib.metadata import version as distribution_version
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTED = ROOT / "requirements" / "research-win-py312.expected.json"

IMPORT_NAMES = {
    "akshare": "akshare",
    "cvxpy": "cvxpy",
    "lightgbm": "lightgbm",
    "numpy": "numpy",
    "optuna": "optuna",
    "pandas": "pandas",
    "pyarrow": "pyarrow",
    "qlib": "qlib",
    "scikit-learn": "sklearn",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
    "TA-Lib": "talib",
    "torch": "torch",
    "xgboost": "xgboost",
}
DIST_NAMES = {
    "qlib": "pyqlib",
}


def package_version(distribution: str) -> str:
    """Return the installed distribution version without importing native modules."""

    return distribution_version(DIST_NAMES.get(distribution, distribution))


def verify_imports() -> dict[str, str | None]:
    """Import every top-level dependency in one process to catch DLL conflicts."""

    runtime_versions = {}
    for distribution, import_name in IMPORT_NAMES.items():
        module = importlib.import_module(import_name)
        value = getattr(module, "__version__", None)
        runtime_versions[distribution] = None if value is None else str(value)
    return runtime_versions


def verify_isolation() -> dict:
    prefix = Path(sys.prefix).resolve()
    base_prefix = Path(sys.base_prefix).resolve()
    if prefix == base_prefix:
        raise RuntimeError("research interpreter is not running inside a virtual environment")
    if site.ENABLE_USER_SITE:
        raise RuntimeError("user site-packages must be disabled in the research environment")
    base_site = (base_prefix / "Lib" / "site-packages").resolve()
    leaked = [
        entry
        for entry in sys.path
        if Path(entry or ".").resolve() == base_site
    ]
    if leaked:
        raise RuntimeError(f"base site-packages leaked into the environment: {leaked}")
    return {
        "prefix": str(prefix),
        "base_prefix": str(base_prefix),
        "base_site_packages_leaked": False,
        "user_site_enabled": bool(site.ENABLE_USER_SITE),
    }


def verify_smoke_workloads() -> dict:
    import cvxpy as cp
    import lightgbm as lgb
    import optuna
    import talib
    import torch
    import xgboost as xgb

    values = np.array([1.0, 2.0, 3.0, 4.0], dtype=float)
    sma = talib.SMA(values, timeperiod=2)
    if not np.isclose(sma[-1], 3.5):
        raise RuntimeError("TA-Lib SMA smoke test failed")

    features = np.array([[0.0], [1.0], [2.0], [3.0]], dtype=float)
    labels = np.array([0, 0, 1, 1], dtype=int)
    lightgbm_model = lgb.LGBMClassifier(
        n_estimators=2,
        max_depth=2,
        verbosity=-1,
        random_state=7,
    ).fit(features, labels)
    xgboost_model = xgb.XGBClassifier(
        n_estimators=2,
        max_depth=2,
        verbosity=0,
        random_state=7,
    ).fit(features, labels)

    variable = cp.Variable()
    problem = cp.Problem(cp.Minimize(cp.square(variable - 2.0)))
    problem.solve()
    if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}:
        raise RuntimeError(f"CVXPY smoke test failed: {problem.status}")

    study = optuna.create_study(direction="minimize")
    study.optimize(lambda trial: trial.suggest_float("x", -1.0, 1.0) ** 2, n_trials=1)
    tensor_value = float((torch.tensor([1.0, 2.0]) ** 2).sum().item())

    return {
        "talib_last_sma": float(sma[-1]),
        "lightgbm_predictions": lightgbm_model.predict(features).astype(int).tolist(),
        "xgboost_predictions": xgboost_model.predict(features).astype(int).tolist(),
        "cvxpy_status": problem.status,
        "cvxpy_value": float(variable.value),
        "optuna_trials": len(study.trials),
        "torch_tensor_value": tensor_value,
    }


def verify(expected_path: Path) -> dict:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual_python = platform.python_version()
    if actual_python != expected["python"]:
        raise RuntimeError(
            f"Python version mismatch: expected {expected['python']}, got {actual_python}"
        )
    if sys.platform != expected["platform"]:
        raise RuntimeError(
            f"platform mismatch: expected {expected['platform']}, got {sys.platform}"
        )
    actual_architecture = platform.architecture()[0]
    if actual_architecture != expected["architecture"]:
        raise RuntimeError(
            f"architecture mismatch: expected {expected['architecture']}, "
            f"got {actual_architecture}"
        )
    versions = {
        distribution: package_version(distribution)
        for distribution in expected["packages"]
    }
    mismatches = {
        distribution: {
            "expected": expected["packages"][distribution],
            "actual": actual,
        }
        for distribution, actual in versions.items()
        if actual != expected["packages"][distribution]
    }
    if mismatches:
        raise RuntimeError(f"package version mismatch: {mismatches}")
    return {
        "status": "passed",
        "python": actual_python,
        "platform": sys.platform,
        "architecture": actual_architecture,
        "executable": sys.executable,
        "isolation": verify_isolation(),
        "packages": versions,
        "runtime_import_versions": verify_imports(),
        "smoke_workloads": verify_smoke_workloads(),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = verify(args.expected.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
