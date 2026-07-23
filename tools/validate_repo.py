"""Validate strategy-family structure and immutable backtest metadata."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "strategies"
REQUIRED_FAMILY_PATHS = ("README.md", "strategy.toml", "baseline.py", "variants", "tests", "backtests")
REQUIRED_MANIFEST_KEYS = {
    "schema_version",
    "strategy_id",
    "variant",
    "platform",
    "archived_at",
    "source_file",
    "source_sha256",
    "period",
    "metrics",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_platform_python(path: Path, errors: list[str]) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source)
    except SyntaxError as exc:
        errors.append(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
    if "from __future__ import annotations" in source:
        errors.append(f"{path.relative_to(ROOT)}: JoinQuant runtime file uses future annotations")


def validate_backtest(family: Path, run: Path, metadata: dict, errors: list[str]) -> None:
    missing = REQUIRED_MANIFEST_KEYS - metadata.keys()
    if missing:
        errors.append(f"{run.relative_to(ROOT)}: missing manifest keys {sorted(missing)}")
        return
    if metadata["strategy_id"] != family.name:
        errors.append(f"{run.relative_to(ROOT)}: strategy_id does not match family directory")
    if metadata["platform"] != family.parent.name:
        errors.append(f"{run.relative_to(ROOT)}: platform does not match platform directory")

    report = run / "report.md"
    if not report.is_file():
        errors.append(f"{run.relative_to(ROOT)}: missing report.md")

    source = run / metadata["source_file"]
    if not source.is_file():
        errors.append(f"{run.relative_to(ROOT)}: missing source file {metadata['source_file']}")
        return
    actual_hash = sha256(source)
    if actual_hash != metadata["source_sha256"]:
        errors.append(f"{run.relative_to(ROOT)}: source_sha256 does not match source file")
    validate_platform_python(source, errors)


def validate_family(family: Path, errors: list[str]) -> None:
    for relative in REQUIRED_FAMILY_PATHS:
        if not (family / relative).exists():
            errors.append(f"{family.relative_to(ROOT)}: missing {relative}")

    manifest_path = family / "strategy.toml"
    if not manifest_path.is_file():
        return
    with manifest_path.open("rb") as handle:
        metadata = tomllib.load(handle)
    if metadata.get("id") != family.name:
        errors.append(f"{manifest_path.relative_to(ROOT)}: id must match directory name")
    if metadata.get("platform") != family.parent.name:
        errors.append(f"{manifest_path.relative_to(ROOT)}: platform must match parent directory")

    platform_files = [family / "baseline.py", *sorted((family / "variants").glob("*.py"))]
    for path in platform_files:
        if path.is_file():
            validate_platform_python(path, errors)

    for run in sorted((family / "backtests").iterdir()):
        if not run.is_dir():
            continue
        if "latest" in run.name.lower():
            errors.append(f"{run.relative_to(ROOT)}: mutable 'latest' directory is forbidden")
        run_manifest = run / "manifest.json"
        if not run_manifest.is_file():
            errors.append(f"{run.relative_to(ROOT)}: missing manifest.json")
            continue
        try:
            metadata = json.loads(run_manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{run_manifest.relative_to(ROOT)}: invalid JSON: {exc}")
            continue
        validate_backtest(family, run, metadata, errors)


def main() -> int:
    errors: list[str] = []
    families = sorted(STRATEGIES.glob("*/*"))
    families = [path for path in families if path.is_dir() and not path.name.startswith("_")]
    if not families:
        errors.append("No strategy families found")
    for family in families:
        validate_family(family, errors)

    if errors:
        print("Repository validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Repository validation passed: {len(families)} strategy family/families")
    return 0


if __name__ == "__main__":
    sys.exit(main())
