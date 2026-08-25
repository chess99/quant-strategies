"""生成可实盘策略研究阶段 0 的全量盘点、谱系和候选排序。"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import keyword
import math
import re
import tokenize
import warnings
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
DEFAULT_SUMMARY = ROOT / "joinquant_archive" / "data" / "summary.jsonl"
DEFAULT_MANIFEST = ROOT / "joinquant_archive" / "sources" / "manifest.jsonl"
DEFAULT_SOURCES = ROOT / "joinquant_archive" / "sources"
DEFAULT_OUTPUT = STUDY_DIR / "screening"
DEFAULT_AS_OF = date(2026, 8, 25)

SEED_NAMES = {
    "低风险中等收益策略": "低风险中等收益",
    "多品种etf动量轮动+epo优化": "多品种 ETF 动量 + EPO",
    "白马股攻防转换策略": "白马股攻防",
}

SOURCE_RISK_COLUMNS = (
    "uses_real_price",
    "avoids_future_data",
    "uses_zero_slippage",
    "configures_costs",
    "uses_fundamentals",
    "uses_minute_data",
    "uses_auction_data",
    "uses_limit_state",
    "uses_index_membership",
    "undated_index_membership_risk",
    "same_day_signal_execution_risk",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def normalized_source_tokens(code: str) -> set[str]:
    """返回去注释、归一化字面量后的五元 token shingle。"""
    tokens: list[str] = []
    try:
        stream = tokenize.generate_tokens(io.StringIO(code).readline)
        for token_info in stream:
            token_type = token_info.type
            value = token_info.string
            if token_type in {
                tokenize.COMMENT,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENDMARKER,
                tokenize.ENCODING,
            }:
                continue
            if token_type == tokenize.STRING:
                value = "STR"
            elif token_type == tokenize.NUMBER:
                value = "NUM"
            elif token_type == tokenize.NAME:
                value = value.lower()
                if len(value) == 1 and not keyword.iskeyword(value):
                    value = "id"
            tokens.append(value)
    except (IndentationError, SyntaxError, tokenize.TokenError):
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\s]", code.lower())

    if len(tokens) < 5:
        return set(tokens)
    return {
        hashlib.sha1("\x1f".join(tokens[index : index + 5]).encode("utf-8")).hexdigest()[:16]
        for index in range(len(tokens) - 4)
    }


class _NameNormalizer(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
        if not keyword.iskeyword(node.id):
            node.id = "id"
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:  # noqa: N802
        node.arg = "arg"
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802
        if isinstance(node.value, (str, int, float, complex)):
            node.value = type(node.value)() if not isinstance(node.value, str) else "str"
        return node


def core_function_hashes(tree: ast.AST | None) -> set[str]:
    if tree is None:
        return set()
    hashes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            copied = ast.parse(ast.unparse(node)).body[0]
        copied.name = "function"
        normalized = _NameNormalizer().visit(copied)
        ast.fix_missing_locations(normalized)
        payload = ast.dump(normalized, annotate_fields=False, include_attributes=False)
        hashes.add(hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20])
    return hashes


def _call_has_date(call: ast.Call) -> bool:
    if len(call.args) >= 2:
        return True
    return any(keyword_node.arg in {"date", "end_date"} for keyword_node in call.keywords)


def analyze_source(code: str) -> dict[str, Any]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree: ast.AST | None = ast.parse(code)
        parse_ok = True
    except SyntaxError:
        tree = None
        parse_ok = False

    calls: list[ast.Call] = []
    branches = 0
    parameters = 0
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                calls.append(node)
            elif isinstance(node, (ast.If, ast.IfExp, ast.Match, ast.Try)):
                branches += 1
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = target.id if isinstance(target, ast.Name) else ""
                    is_global_config = (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "g"
                    )
                    if name.isupper() or name.startswith(("param_", "config_")) or is_global_config:
                        parameters += 1

    names = [call_name(call) for call in calls]
    lowered = code.lower()
    order_calls = [name for name in names if name.startswith("order")]
    index_calls = [call for call in calls if call_name(call) == "get_index_stocks"]
    current_dt_price = False
    daily_close_signal = False
    minute_data = False
    zero_slippage = False
    uses_real_price = False
    avoids_future_data = False
    configures_costs = any(name in {"set_order_cost", "set_commission"} for name in names)
    for call in calls:
        name = call_name(call)
        positional = [literal_text(arg) for arg in call.args]
        keywords_map = {item.arg: literal_text(item.value) for item in call.keywords if item.arg}
        if name == "set_option" and positional:
            enabled = len(call.args) < 2 or not (
                isinstance(call.args[1], ast.Constant) and call.args[1].value is False
            )
            if positional[0] == "use_real_price" and enabled:
                uses_real_price = True
            elif positional[0] == "avoid_future_data" and enabled:
                avoids_future_data = True
        if name == "set_slippage":
            payload = ast.unparse(call) if hasattr(ast, "unparse") else ""
            zero_slippage = bool(re.search(r"(?:fixed|pricerelated)slippage\s*\(\s*0(?:\.0+)?\s*\)", payload, re.I))
        if name in {"get_price", "history", "attribute_history", "get_bars"}:
            call_payload = ast.unparse(call).lower() if hasattr(ast, "unparse") else ""
            values = [value for value in positional + list(keywords_map.values()) if value]
            minute_data = minute_data or any(re.search(r"(^|\D)(?:1|5|15|30|60)m(?:$|\D)|minute", value, re.I) for value in values)
            current_dt_price = current_dt_price or "current_dt" in call_payload
            daily_close_signal = daily_close_signal or (
                "close" in call_payload
                and not any(re.search(r"(^|\D)(?:1|5|15|30|60)m(?:$|\D)|minute", value, re.I) for value in values)
            )

    source_lines = len(code.splitlines())
    code_etf = bool(re.search(r"\betf\b|基金|场内基金|tracking_target", lowered, re.I))
    code_future = bool(re.search(r"get_dominant_future|index_futures|期货|futures", lowered, re.I))
    code_stock = bool(re.search(r"get_all_securities|get_index_stocks|get_fundamentals|股票|小市值|选股", lowered, re.I))
    if code_future:
        asset_type = "futures-or-mixed"
    elif code_etf and code_stock:
        asset_type = "stock-etf-mixed"
    elif code_etf:
        asset_type = "etf-or-fund"
    elif code_stock:
        asset_type = "a-share"
    else:
        asset_type = "unclassified"

    uses_auction = any(name in {"get_call_auction", "call_auction"} for name in names) or "集合竞价" in code
    uses_limit_state = any(marker in lowered for marker in ("high_limit", "low_limit", "涨停", "跌停"))
    scheduled_near_close = bool(re.search(r"time\s*=\s*['\"](?:14:[3-5]\d|15:0\d)", lowered))
    result = {
        "python3_ast_parse": parse_ok,
        "source_line_count": source_lines,
        "parameter_count": parameters,
        "branch_count": branches,
        "order_call_count": len(order_calls),
        "uses_real_price": uses_real_price,
        "avoids_future_data": avoids_future_data,
        "uses_zero_slippage": zero_slippage,
        "configures_costs": configures_costs,
        "uses_fundamentals": "get_fundamentals" in names,
        "uses_minute_data": minute_data,
        "uses_auction_data": uses_auction,
        "uses_limit_state": uses_limit_state,
        "uses_index_membership": bool(index_calls),
        "undated_index_membership_risk": any(not _call_has_date(call) for call in index_calls),
        "same_day_signal_execution_risk": bool(
            order_calls and (current_dt_price or (daily_close_signal and scheduled_near_close))
        ),
        "asset_type": asset_type,
        "source_tokens": normalized_source_tokens(code),
        "core_function_hashes": core_function_hashes(tree),
    }
    return result


def natural_oos_fields(
    row: dict[str, Any],
    *,
    source_vintage_predates_oos: bool,
    as_of: date,
) -> dict[str, Any]:
    post_date = parse_date(row.get("post_time"))
    backtest_end = parse_date(row.get("end_date"))
    gap = (post_date - backtest_end).days if post_date and backtest_end else None
    post_days = max(0, (as_of - post_date).days) if post_date else None
    eligible = bool(
        gap is not None
        and post_days is not None
        and 0 <= gap <= 180
        and post_days >= 365
    )
    grade = "A" if eligible and source_vintage_predates_oos else "C"
    return {
        "backtest_to_post_days": gap,
        "post_publication_days": post_days,
        "natural_oos_eligible": eligible,
        "oos_integrity_grade": grade,
        "strict_natural_oos": eligible and grade == "A",
        "source_vintage_note": (
            "source snapshot demonstrably predates OOS"
            if grade == "A"
            else "current archive source has no pre-OOS immutable timestamp"
        ),
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class DisjointSet:
    def __init__(self, keys: Iterable[str]):
        self.parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def _pair_relation(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, float, float, bool, bool]:
    source_similarity = jaccard(left.get("source_tokens", set()), right.get("source_tokens", set()))
    core_similarity = jaccard(left.get("core_function_hashes", set()), right.get("core_function_hashes", set()))
    shared_post = bool(
        left.get("primary_url")
        and left.get("primary_url") == right.get("primary_url")
    )
    shared_author = bool(left.get("author") and left.get("author") == right.get("author"))
    exact = bool(left.get("source_hash") and left.get("source_hash") == right.get("source_hash"))
    minimum_tokens = min(len(left.get("source_tokens", set())), len(right.get("source_tokens", set())))
    if exact:
        relation = "exact-source"
    elif shared_post:
        relation = "shared-post"
    elif minimum_tokens >= 20 and (source_similarity >= 0.82 or (source_similarity >= 0.55 and core_similarity >= 0.60)):
        relation = "near-duplicate"
    elif minimum_tokens >= 20 and source_similarity >= 0.65 and core_similarity >= 0.30:
        relation = "probable-variant"
    else:
        relation = "independent"
    return relation, source_similarity, core_similarity, shared_post, shared_author


def build_lineages(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dsu = DisjointSet(record["item_id"] for record in records)
    nearest: dict[str, tuple[float, str, str, float, float, bool, bool]] = {}
    cluster_relations = {"exact-source", "shared-post", "near-duplicate", "probable-variant"}
    for left_index, left in enumerate(records):
        for right in records[left_index + 1 :]:
            relation, source_sim, core_sim, shared_post, shared_author = _pair_relation(left, right)
            if relation in cluster_relations:
                dsu.union(left["item_id"], right["item_id"])
            relation_bonus = {
                "exact-source": 1.0,
                "shared-post": 0.9,
                "near-duplicate": 0.8,
                "probable-variant": 0.7,
                "independent": 0.0,
            }[relation]
            score = relation_bonus + source_sim + 0.25 * core_sim + 0.05 * shared_author
            for source, target in ((left, right), (right, left)):
                current = nearest.get(source["item_id"])
                candidate = (
                    score,
                    target["item_id"],
                    relation,
                    source_sim,
                    core_sim,
                    shared_post,
                    shared_author,
                )
                if current is None or candidate[:2] > current[:2]:
                    nearest[source["item_id"]] = candidate

    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        groups[dsu.find(record["item_id"])].append(record["item_id"])
    lineage_by_item: dict[str, str] = {}
    representative_by_item: dict[str, str] = {}
    size_by_item: dict[str, int] = {}
    for members in groups.values():
        members.sort()
        lineage_id = "L-" + hashlib.sha1("\n".join(members).encode("utf-8")).hexdigest()[:10]
        for member in members:
            lineage_by_item[member] = lineage_id
            representative_by_item[member] = members[0]
            size_by_item[member] = len(members)

    output: list[dict[str, Any]] = []
    for record in records:
        item_id = record["item_id"]
        match = nearest.get(item_id, (0.0, "", "independent", 0.0, 0.0, False, False))
        output.append(
            {
                "item_id": item_id,
                "strategy_name": record.get("strategy_name", ""),
                "primary_url": record.get("primary_url", ""),
                "author": record.get("author", ""),
                "source_hash": record.get("source_hash", ""),
                "lineage_id": lineage_by_item[item_id],
                "lineage_representative_item_id": representative_by_item[item_id],
                "lineage_size": size_by_item[item_id],
                "nearest_item_id": match[1],
                "relation": match[2],
                "source_similarity": round(match[3], 6),
                "core_function_similarity": round(match[4], 6),
                "shared_post": match[5],
                "shared_author": match[6],
            }
        )
    return sorted(output, key=lambda row: row["item_id"])


def _detail_metadata(data_root: Path, local_file: str) -> dict[str, Any]:
    detail_path = data_root / Path(local_file).with_suffix(".json")
    if not detail_path.exists():
        return {}
    try:
        payload = json.loads(detail_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    post = (payload.get("remote") or {}).get("post") or {}
    return {
        "post_modified_time": post.get("modTime"),
        "post_last_published_time": post.get("lastPubTime"),
    }


def _manifest_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        path = Path(row["archive_path"])
        index[(path.parent.as_posix(), row.get("strategy_name", ""))].append(row)
    return index


def _match_manifest(
    row: dict[str, Any],
    index: dict[tuple[str, str], list[dict[str, Any]]],
    manifest_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    key = (row.get("local_category", ""), row.get("local_strategy_name", ""))
    candidates = index.get(key, [])
    if candidates:
        return candidates[0]
    primary_url = row.get("primary_url")
    if primary_url:
        url_matches = [item for item in manifest_rows if item.get("primary_url") == primary_url]
        if len(url_matches) == 1:
            return url_matches[0]
    return None


def seed_priority(name: str, title: str) -> tuple[str, str]:
    haystack = f"{name} {title}".lower().replace(" ", "")
    for marker, label in SEED_NAMES.items():
        if marker.lower().replace(" ", "") in haystack:
            return "P0", label
    return "", ""


def _history_years(row: dict[str, Any]) -> float | None:
    start = parse_date(row.get("start_date"))
    end = parse_date(row.get("end_date"))
    if not start or not end or end < start:
        return None
    return round((end - start).days / 365.25, 3)


def build_universe(
    summary_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    sources_root: Path,
    data_root: Path,
    as_of: date,
) -> list[dict[str, Any]]:
    manifest_index = _manifest_index(manifest_rows)
    universe: list[dict[str, Any]] = []
    for summary in summary_rows:
        manifest = _match_manifest(summary, manifest_index, manifest_rows)
        source_path = sources_root / manifest["archive_path"] if manifest else None
        code = ""
        if source_path and source_path.exists():
            code = source_path.read_text(encoding="utf-8-sig", errors="replace")
        features = analyze_source(code) if code else {
            "python3_ast_parse": False,
            "source_line_count": 0,
            "parameter_count": 0,
            "branch_count": 0,
            "order_call_count": 0,
            **{column: False for column in SOURCE_RISK_COLUMNS},
            "asset_type": "missing-source",
            "source_tokens": set(),
            "core_function_hashes": set(),
        }
        item_id = str(
            summary.get("local_file")
            or (manifest.get("archive_path") if manifest else None)
            or summary.get("local_strategy_name")
        )
        priority, seed_label = seed_priority(
            str(summary.get("local_strategy_name") or ""),
            str(summary.get("post_title") or ""),
        )
        row: dict[str, Any] = {
            "item_id": item_id,
            "category": summary.get("local_category"),
            "local_file": summary.get("local_file"),
            "strategy_name": summary.get("local_strategy_name"),
            "declared_title": summary.get("local_declared_title"),
            "post_title": summary.get("post_title"),
            "author": summary.get("author") or summary.get("local_declared_author"),
            "primary_url": summary.get("primary_url"),
            "canonical_url": summary.get("canonical_url"),
            "archive_status": summary.get("status"),
            "source_archive_path": manifest.get("archive_path") if manifest else None,
            "source_hash": manifest.get("archive_sha256") if manifest else None,
            "source_original_hash": manifest.get("source_sha256") if manifest else None,
            "source_transformations": "|".join(manifest.get("transformations", [])) if manifest else "",
            "source_present": bool(source_path and source_path.exists()),
            "post_time": summary.get("post_time"),
            "backtest_start": summary.get("start_date"),
            "backtest_end": summary.get("end_date"),
            "backtest_years": _history_years(summary),
            "base_capital": summary.get("base_capital"),
            "frequency": summary.get("frequency_code"),
            "annual_return_percent": summary.get("annual_return_percent"),
            "max_drawdown_percent": summary.get("max_drawdown_percent"),
            "sharpe": summary.get("sharpe"),
            "sortino": summary.get("sortino"),
            "turnover_rate_percent": summary.get("turnover_rate_percent"),
            "trade_count": (summary.get("win_count") or 0) + (summary.get("lose_count") or 0),
            "trading_days": summary.get("trading_days"),
            "seed_priority": priority,
            "seed_label": seed_label,
            **_detail_metadata(data_root, str(summary.get("local_file") or "")),
            **natural_oos_fields(summary, source_vintage_predates_oos=False, as_of=as_of),
            **features,
        }
        universe.append(row)
    return sorted(universe, key=lambda row: row["item_id"])


def _component_scores(row: dict[str, Any], lineage_size: int) -> dict[str, float]:
    post_days = safe_float(row.get("post_publication_days")) or 0.0
    gap = safe_float(row.get("backtest_to_post_days"))
    oos = min(24.0, post_days / 365.25 * 4.0) if row.get("natural_oos_eligible") else 0.0
    if gap is not None and 0 <= gap <= 180:
        oos += max(0.0, 6.0 * (1.0 - gap / 180.0))
    history = min(12.0, (safe_float(row.get("backtest_years")) or 0.0) * 1.2)

    causal_penalties = 0.0
    if not row.get("avoids_future_data"):
        causal_penalties += 2.0
    if row.get("undated_index_membership_risk"):
        causal_penalties += 3.0
    if row.get("same_day_signal_execution_risk"):
        causal_penalties += 3.0
    causal = max(0.0, 10.0 - causal_penalties)

    if row.get("uses_minute_data") or row.get("uses_auction_data"):
        production = 1.0
        execution = 1.0
    elif row.get("asset_type") == "futures-or-mixed":
        production = 3.0
        execution = 3.0
    elif row.get("uses_fundamentals"):
        production = 6.0
        execution = 7.0
    else:
        production = 9.0
        execution = 8.0
    if row.get("uses_zero_slippage"):
        execution = max(0.0, execution - 2.0)
    if not row.get("configures_costs"):
        execution = max(0.0, execution - 1.0)

    complexity = (
        (safe_float(row.get("source_line_count")) or 0.0) / 120.0
        + (safe_float(row.get("branch_count")) or 0.0) / 20.0
        + (safe_float(row.get("parameter_count")) or 0.0) / 8.0
    )
    simplicity = max(0.0, 8.0 - complexity)
    uniqueness = 5.0 / max(1.0, math.sqrt(lineage_size))
    sharpe = safe_float(row.get("sharpe"))
    drawdown = safe_float(row.get("max_drawdown_percent"))
    risk_adjusted = 0.0
    if sharpe is not None:
        risk_adjusted += min(3.0, max(0.0, sharpe))
    if drawdown is not None:
        risk_adjusted += max(0.0, 2.0 - min(2.0, drawdown / 25.0))
    return {
        "score_natural_oos": round(oos, 4),
        "score_history": round(history, 4),
        "score_causal_repairability": round(causal, 4),
        "score_production_data": round(production, 4),
        "score_execution_feasibility": round(execution, 4),
        "score_simplicity": round(simplicity, 4),
        "score_lineage_uniqueness": round(uniqueness, 4),
        "score_risk_adjusted_tiebreaker": round(risk_adjusted, 4),
    }


def build_shortlist(
    universe: list[dict[str, Any]],
    lineages: list[dict[str, Any]],
    shortlist_size: int,
) -> list[dict[str, Any]]:
    lineage_lookup = {row["item_id"]: row for row in lineages}
    candidates: list[dict[str, Any]] = []
    for row in universe:
        if row.get("archive_status") != "ok" or not row.get("backtest_end"):
            continue
        lineage = lineage_lookup[row["item_id"]]
        components = _component_scores(row, int(lineage["lineage_size"]))
        seed_bonus = 25.0 if row.get("seed_priority") == "P0" else 0.0
        total = round(sum(components.values()) + seed_bonus, 4)
        if row.get("uses_minute_data") or row.get("uses_auction_data"):
            queue = "high-data-cost"
            action = "先审计分钟/竞价成交证据；日线结果不得晋级 R3"
        elif row.get("natural_oos_eligible"):
            queue = "natural-oos"
            action = "核验源码版本；冻结可重建原版后直接跑发布后区间，不调参"
        else:
            queue = "causal-audit"
            action = "先做源码与点时/成交规则审计，再决定是否进入深挖"
        candidates.append(
            {
                "screening_score": total,
                "lineage_id": lineage["lineage_id"],
                "lineage_size": lineage["lineage_size"],
                "strategy_name": row.get("strategy_name"),
                "item_id": row["item_id"],
                "post_title": row.get("post_title"),
                "author": row.get("author"),
                "primary_url": row.get("primary_url"),
                "source_hash": row.get("source_hash"),
                "seed_priority": row.get("seed_priority"),
                "seed_label": row.get("seed_label"),
                "research_queue": queue,
                "next_action": action,
                "asset_type": row.get("asset_type"),
                "frequency": row.get("frequency"),
                "backtest_start": row.get("backtest_start"),
                "backtest_end": row.get("backtest_end"),
                "backtest_years": row.get("backtest_years"),
                "post_time": row.get("post_time"),
                "backtest_to_post_days": row.get("backtest_to_post_days"),
                "post_publication_days": row.get("post_publication_days"),
                "natural_oos_eligible": row.get("natural_oos_eligible"),
                "oos_integrity_grade": row.get("oos_integrity_grade"),
                "annual_return_percent": row.get("annual_return_percent"),
                "max_drawdown_percent": row.get("max_drawdown_percent"),
                "sharpe": row.get("sharpe"),
                "sortino": row.get("sortino"),
                "turnover_rate_percent": row.get("turnover_rate_percent"),
                "uses_minute_data": row.get("uses_minute_data"),
                "uses_auction_data": row.get("uses_auction_data"),
                "uses_fundamentals": row.get("uses_fundamentals"),
                "undated_index_membership_risk": row.get("undated_index_membership_risk"),
                "same_day_signal_execution_risk": row.get("same_day_signal_execution_risk"),
                **components,
            }
        )

    candidates.sort(
        key=lambda row: (
            -float(row["screening_score"]),
            str(row["lineage_id"]),
            str(row["item_id"]),
        )
    )
    representatives: list[dict[str, Any]] = []
    seen_lineages: set[str] = set()
    for candidate in candidates:
        if candidate["lineage_id"] in seen_lineages:
            continue
        seen_lineages.add(candidate["lineage_id"])
        representatives.append(candidate)
        if len(representatives) >= shortlist_size:
            break
    representatives.sort(
        key=lambda row: (
            0 if row.get("seed_priority") == "P0" else 1,
            -float(row["screening_score"]),
            str(row["item_id"]),
        )
    )
    for index, row in enumerate(representatives, start=1):
        row["screening_rank"] = index
    return representatives


def _csv_value(value: Any) -> Any:
    if isinstance(value, set):
        return "|".join(sorted(value))
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen and key not in {"source_tokens", "core_function_hashes"}:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def generate_screening(
    *,
    summary_path: Path,
    manifest_path: Path,
    sources_root: Path,
    output_dir: Path,
    as_of: date,
    shortlist_size: int,
) -> dict[str, int]:
    summary_rows = read_jsonl(summary_path)
    manifest_rows = read_jsonl(manifest_path)
    universe = build_universe(
        summary_rows,
        manifest_rows,
        sources_root=sources_root,
        data_root=summary_path.parent,
        as_of=as_of,
    )
    lineages = build_lineages(universe)
    lineage_lookup = {row["item_id"]: row for row in lineages}
    universe_csv = []
    for row in universe:
        output_row = {key: value for key, value in row.items() if key not in {"source_tokens", "core_function_hashes"}}
        output_row["lineage_id"] = lineage_lookup[row["item_id"]]["lineage_id"]
        output_row["lineage_size"] = lineage_lookup[row["item_id"]]["lineage_size"]
        universe_csv.append(output_row)
    natural_oos = [
        {
            "item_id": row["item_id"],
            "strategy_name": row.get("strategy_name"),
            "post_title": row.get("post_title"),
            "author": row.get("author"),
            "primary_url": row.get("primary_url"),
            "source_hash": row.get("source_hash"),
            "source_vintage_note": row.get("source_vintage_note"),
            "backtest_start": row.get("backtest_start"),
            "backtest_end": row.get("backtest_end"),
            "post_time": row.get("post_time"),
            "post_modified_time": row.get("post_modified_time"),
            "backtest_to_post_days": row.get("backtest_to_post_days"),
            "post_publication_days": row.get("post_publication_days"),
            "natural_oos_eligible": row.get("natural_oos_eligible"),
            "oos_integrity_grade": row.get("oos_integrity_grade"),
            "strict_natural_oos": row.get("strict_natural_oos"),
            "lineage_id": lineage_lookup[row["item_id"]]["lineage_id"],
            "lineage_size": lineage_lookup[row["item_id"]]["lineage_size"],
            "seed_priority": row.get("seed_priority"),
            "seed_label": row.get("seed_label"),
        }
        for row in universe
        if row.get("post_time") or row.get("backtest_end")
    ]
    natural_oos.sort(
        key=lambda row: (
            0 if row.get("seed_priority") == "P0" else 1,
            0 if row.get("natural_oos_eligible") else 1,
            -(safe_float(row.get("post_publication_days")) or 0.0),
            str(row["item_id"]),
        )
    )
    shortlist = build_shortlist(universe, lineages, shortlist_size=shortlist_size)

    write_csv(output_dir / "archive-universe.csv", universe_csv)
    write_csv(output_dir / "strategy-lineage.csv", lineages)
    write_csv(output_dir / "natural-oos.csv", natural_oos)
    write_csv(output_dir / "candidate-shortlist.csv", shortlist, fieldnames=["screening_rank"] + [key for key in shortlist[0] if key != "screening_rank"] if shortlist else ["screening_rank"])
    return {
        "archive_items": len(universe),
        "public_backtests": sum(1 for row in universe if row.get("archive_status") == "ok"),
        "lineages": len({row["lineage_id"] for row in lineages}),
        "natural_oos_eligible": sum(1 for row in natural_oos if row.get("natural_oos_eligible")),
        "strict_natural_oos": sum(1 for row in natural_oos if row.get("strict_natural_oos")),
        "shortlist": len(shortlist),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sources-root", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--as-of", type=date.fromisoformat, default=DEFAULT_AS_OF)
    parser.add_argument("--shortlist-size", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = generate_screening(
        summary_path=args.summary,
        manifest_path=args.manifest,
        sources_root=args.sources_root,
        output_dir=args.output_dir,
        as_of=args.as_of,
        shortlist_size=args.shortlist_size,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
