"""Verify that the locked research environment is isolated and functional."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import re
import site
import sys
import tempfile
from importlib.metadata import distributions, version as distribution_version
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROFILE = {
    "win32": "research-win-py312",
    "linux": "research-linux-py312",
    "darwin": "research-macos-arm64-py312",
}.get(sys.platform)
if PROFILE is None:
    raise RuntimeError(f"Unsupported research platform: {sys.platform}")
DEFAULT_EXPECTED = ROOT / "requirements" / f"{PROFILE}.expected.json"
DEFAULT_LOCK = ROOT / "requirements" / f"{PROFILE}.lock"

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
if sys.platform.startswith("linux"):
    # The CPU-only Linux distribution exposes the same ``xgboost`` import
    # without pulling the CUDA/NCCL runtime onto small research hosts.
    DIST_NAMES["xgboost"] = "xgboost-cpu"


def package_version(distribution: str) -> str:
    """Return the installed distribution version without importing native modules."""

    return distribution_version(DIST_NAMES.get(distribution, distribution))


def canonical_distribution_name(name: str) -> str:
    """按 Python 包索引规则统一包名，避免连字符/下划线造成假差异。"""

    return re.sub(r"[-_.]+", "-", name).lower()


def read_exact_lock(lock_path: Path) -> dict[str, str]:
    """读取只含 name==version 的可复现锁文件。"""

    pins = {}
    for raw_line in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line or " @ " in line or line.startswith("-e "):
            raise RuntimeError(f"lock contains a non-exact requirement: {line}")
        name, version = line.split("==", maxsplit=1)
        canonical = canonical_distribution_name(name)
        if not canonical or not version or canonical in pins:
            raise RuntimeError(f"lock contains an invalid or duplicate pin: {line}")
        pins[canonical] = version
    if not pins:
        raise RuntimeError(f"lock contains no exact pins: {lock_path}")
    return pins


def installed_distribution_versions() -> dict[str, str]:
    result = {}
    for distribution in distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        canonical = canonical_distribution_name(name)
        if canonical in result and result[canonical] != distribution.version:
            raise RuntimeError(f"multiple installed versions found for {canonical}")
        result[canonical] = distribution.version
    return result


def verify_lock(lock_path: Path, installed: dict[str, str] | None = None) -> dict:
    locked = read_exact_lock(lock_path)
    actual = installed if installed is not None else installed_distribution_versions()
    actual = {canonical_distribution_name(name): version for name, version in actual.items()}
    missing = sorted(set(locked).difference(actual))
    extra = sorted(set(actual).difference(locked))
    mismatches = {
        name: {"locked": locked[name], "installed": actual[name]}
        for name in sorted(set(locked).intersection(actual))
        if locked[name] != actual[name]
    }
    if missing or extra or mismatches:
        raise RuntimeError(
            "installed environment does not exactly match lock: "
            f"missing={missing}, extra={extra}, mismatches={mismatches}"
        )
    import hashlib

    return {
        "path": str(lock_path),
        "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "exact_pin_count": len(locked),
        "installed_distribution_count": len(actual),
        "matches_installed_environment": True,
    }


def verify_imports() -> dict[str, str | None]:
    """Import every top-level dependency in one process to catch DLL conflicts."""

    runtime_versions = {}
    for distribution, import_name in IMPORT_NAMES.items():
        module = importlib.import_module(import_name)
        value = getattr(module, "__version__", None)
        runtime_versions[distribution] = None if value is None else str(value)
    if sys.platform == "darwin":
        from threadpoolctl import threadpool_info

        openmp = {
            Path(item["filepath"]).resolve()
            for item in threadpool_info()
            if item["internal_api"] == "openmp"
        }
        if len(openmp) != 1:
            raise RuntimeError(
                f"Expected one shared OpenMP runtime; got {sorted(map(str, openmp))}. Rebuild the research environment."
            )
    return runtime_versions


def verify_isolation() -> dict:
    prefix = Path(sys.prefix).resolve()
    base_prefix = Path(sys.base_prefix).resolve()
    if prefix == base_prefix:
        raise RuntimeError("research interpreter is not running inside a virtual environment")
    if site.ENABLE_USER_SITE:
        raise RuntimeError("user site-packages must be disabled in the research environment")
    base_sites = {
        (base_prefix / "Lib" / "site-packages").resolve(),
        (
            base_prefix
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        ).resolve(),
    }
    leaked = [entry for entry in sys.path if Path(entry or ".").resolve() in base_sites]
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
    import qlib
    from qlib.data import D
    import talib
    import torch
    import xgboost as xgb

    with tempfile.TemporaryDirectory(prefix="quant-qlib-smoke-") as temporary:
        provider = Path(temporary)
        (provider / "calendars").mkdir()
        (provider / "instruments").mkdir()
        (provider / "features/sh600000").mkdir(parents=True)
        (provider / "calendars/day.txt").write_text(
            "2024-01-02\n2024-01-03\n2024-01-04\n2024-01-05\n"
        )
        (provider / "instruments/all.txt").write_text("SH600000\t2024-01-02\t2024-01-05\n")
        np.array([0, 1, 2, 3, 4], dtype="<f4").tofile(provider / "features/sh600000/close.day.bin")
        qlib.init(
            provider_uri=str(provider),
            region="cn",
            kernels=1,
            joblib_backend="threading",
            expression_cache=None,
            dataset_cache=None,
        )
        frame = D.features(["SH600000"], ["$close"], "2024-01-02", "2024-01-05")
        qlib_values = frame["$close"].tolist()
        if qlib_values != [1.0, 2.0, 3.0, 4.0]:
            raise RuntimeError(f"Qlib binary provider smoke test failed: {qlib_values}")

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
        n_jobs=2,
    ).fit(features, labels)
    xgboost_model = xgb.XGBClassifier(
        n_estimators=2,
        max_depth=2,
        verbosity=0,
        random_state=7,
        n_jobs=2,
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
        "qlib_binary_values": qlib_values,
        "talib_last_sma": float(sma[-1]),
        "lightgbm_predictions": lightgbm_model.predict(features).astype(int).tolist(),
        "xgboost_predictions": xgboost_model.predict(features).astype(int).tolist(),
        "cvxpy_status": problem.status,
        "cvxpy_value": float(variable.value),
        "optuna_trials": len(study.trials),
        "torch_tensor_value": tensor_value,
    }


def verify(expected_path: Path, lock_path: Path = DEFAULT_LOCK) -> dict:
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
    if expected.get("machine") and platform.machine().lower() != expected["machine"].lower():
        raise RuntimeError(
            f"machine mismatch: expected {expected['machine']}, got {platform.machine()}"
        )
    actual_architecture = platform.architecture()[0]
    if actual_architecture != expected["architecture"]:
        raise RuntimeError(
            f"architecture mismatch: expected {expected['architecture']}, got {actual_architecture}"
        )
    versions = {
        distribution: package_version(distribution) for distribution in expected["packages"]
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
    isolation = verify_isolation()
    locked = verify_lock(lock_path)
    runtime_versions = verify_imports()
    native_path = Path(sys.prefix) / "research-native-runtime.json"
    return {
        "status": "passed",
        "native_runtime": json.loads(native_path.read_text()) if native_path.is_file() else {},
        "machine": platform.machine(),
        "python": actual_python,
        "platform": sys.platform,
        "architecture": actual_architecture,
        "executable": sys.executable,
        "isolation": isolation,
        "lock": locked,
        "packages": versions,
        "runtime_import_versions": runtime_versions,
        "smoke_workloads": verify_smoke_workloads(),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = verify(args.expected.resolve(), args.lock.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
