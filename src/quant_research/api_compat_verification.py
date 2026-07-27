"""迭代4统一接口的机器可读验收。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_api_compat_verification(repo_root: Path | str) -> dict:
    root = Path(repo_root)
    coverage_path = root / "docs" / "local-research" / "jq-api-coverage.json"
    result = (
        root
        / "studies"
        / "joinquant-api-compat-validation"
        / "results"
        / "2026-07-27__three-strategy-migration__v4"
    )
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    supported = coverage["classification_counts"].get("supported", 0)
    target_calls = coverage["target_calls"]
    direct_ratio = supported / target_calls if target_calls else 0.0
    source_matches = _sha256(result / "source.py") == manifest["source_sha256"]
    raw_matches = all(
        _sha256(result / "raw" / name) == expected
        for name, expected in manifest["raw_sha256"].items()
    )
    checks = {
        "parsed_source_files": coverage["files"]["parsed"] >= 550,
        "target_calls_profiled": target_calls >= 4_000,
        "direct_signature_coverage": direct_ratio >= 0.85,
        "query_dsl_migration_is_explicit": (
            coverage["query_dsl_migration"]["status"]
            == "explicit_migration_required"
            and not coverage["query_dsl_migration"]["silent_fallback"]
        ),
        "three_strategy_validation": manifest["status"] == "passed",
        "point_in_time_validation": manifest["checks"]["notice_dates_point_in_time"],
        "provenance_validation": manifest["checks"]["all_three_have_provenance"],
        "versioned_provenance_validation": manifest["checks"][
            "all_three_have_versioned_provenance"
        ],
        "archive_source_sha256": source_matches,
        "archive_raw_sha256": raw_matches,
    }
    return {
        "schema_version": 1,
        "iteration": 4,
        "status": "passed" if all(checks.values()) else "failed",
        "coverage": {
            "files_total": coverage["files"]["total"],
            "files_parsed": coverage["files"]["parsed"],
            "syntax_errors": coverage["files"]["syntax_errors"],
            "target_calls": target_calls,
            "supported_calls": supported,
            "migration_required_calls": coverage["classification_counts"].get(
                "migration_required", 0
            ),
            "direct_coverage_ratio": direct_ratio,
        },
        "three_strategy_archive": result.relative_to(root).as_posix(),
        "checks": checks,
        "sha256": {
            "coverage_report": _sha256(coverage_path),
            "study_manifest": _sha256(result / "manifest.json"),
            "study_source": _sha256(result / "source.py"),
        },
        "limitations": [
            "17个本地源码本身语法残缺，保留错误位置但无法做AST调用审计。",
            "481次query DSL调用需要改成显式symbols、fields和observation_date。",
            "分钟、Tick、期货和期权API不属于本轮日频兼容范围。",
        ],
    }
