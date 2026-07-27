"""聚宽源码日频查询形式的静态覆盖审计。"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path


API_SPECS = {
    "get_price": {
        "max_positional": 5,
        "keywords": {
            "security", "start_date", "end_date", "frequency", "fields",
            "skip_paused", "fq", "count", "panel", "fill_paused",
        },
    },
    "attribute_history": {
        "max_positional": 5,
        "keywords": {"security", "count", "unit", "fields", "skip_paused", "fq", "df"},
    },
    "history": {
        "max_positional": 4,
        "keywords": {"count", "unit", "field", "security_list", "df", "skip_paused", "fq"},
    },
    "get_all_securities": {"max_positional": 2, "keywords": {"types", "date"}},
    "get_index_stocks": {"max_positional": 2, "keywords": {"index_symbol", "date"}},
    "get_current_data": {"max_positional": 0, "keywords": set()},
    "get_fundamentals": {
        "max_positional": 2,
        "keywords": {"symbols", "fields", "date", "statDate"},
    },
    "get_industry": {"max_positional": 2, "keywords": {"symbols", "date"}},
}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _classification(name: str, node: ast.Call) -> tuple[str, str | None]:
    spec = API_SPECS[name]
    keywords = {item.arg for item in node.keywords if item.arg}
    unknown = keywords - spec["keywords"]
    if unknown or len(node.args) > spec["max_positional"]:
        return "migration_required", "unsupported_signature"
    if name == "get_fundamentals":
        return "migration_required", "query_dsl_to_explicit_symbols_fields"
    if name == "get_price" and any(
        item.arg == "panel" and isinstance(item.value, ast.Constant) and item.value.value is True
        for item in node.keywords
    ):
        return "migration_required", "pandas_panel_removed"
    return "supported", None


def audit_joinquant_api_usage(root: Path | str) -> dict:
    root = Path(root)
    files = sorted(root.rglob("*.py"))
    syntax_errors = []
    api_calls = Counter()
    api_files = defaultdict(set)
    classifications = Counter()
    reasons = Counter()
    signatures = Counter()
    unsupported = Counter()
    parsed = 0
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except SyntaxError as exc:
            syntax_errors.append(
                {"path": path.relative_to(root).as_posix(), "line": exc.lineno, "message": exc.msg}
            )
            continue
        parsed += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name in API_SPECS:
                classification, reason = _classification(name, node)
                api_calls[name] += 1
                api_files[name].add(path)
                classifications[classification] += 1
                if reason:
                    reasons[reason] += 1
                keyword_key = ",".join(sorted(item.arg or "**" for item in node.keywords))
                signatures[(name, len(node.args), keyword_key, classification)] += 1
            elif name and (name.startswith("get_") or name in {"history", "attribute_history"}):
                unsupported[name] += 1
    apis = {}
    for name in API_SPECS:
        total = api_calls[name]
        migration = sum(
            count
            for (api, _, _, classification), count in signatures.items()
            if api == name and classification == "migration_required"
        )
        apis[name] = {
            "calls": total,
            "files": len(api_files[name]),
            "supported_calls": total - migration,
            "migration_required_calls": migration,
        }
    return {
        "schema_version": 1,
        "scope": str(root.resolve()),
        "files": {"total": len(files), "parsed": parsed, "syntax_errors": len(syntax_errors)},
        "target_calls": sum(api_calls.values()),
        "classification_counts": dict(sorted(classifications.items())),
        "classification_reasons": dict(sorted(reasons.items())),
        "apis": apis,
        "signatures": [
            {
                "api": api,
                "positional": positional,
                "keywords": keywords.split(",") if keywords else [],
                "classification": classification,
                "calls": count,
            }
            for (api, positional, keywords, classification), count in sorted(
                signatures.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "unsupported_api_calls": dict(sorted(unsupported.items())),
        "syntax_errors": syntax_errors,
        "query_dsl_migration": {
            "status": "explicit_migration_required",
            "replacement": "get_fundamentals(symbols, fields=[...], date=observation_date)",
            "silent_fallback": False,
        },
    }
