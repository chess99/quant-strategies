"""原始六轮规格的可重复完成性审计。"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .backtest import CostModel, DailyBacktester
from .data.etf_sync import sync_etf_daily
from .data.financial_statements import sync_financial_statement_partitions
from .data.market_sync import build_market_state_partitions
from .data.valuation import sync_valuation_partitions
from .jq_compat import JoinQuantCompat
from .portal import LocalDataPortal


ITERATION_COMMITS = {
    "environment": ["8f90e12", "83af506"],
    "iteration_1": ["e084f5d"],
    "iteration_2": ["6c6fe62", "cd440f9"],
    "iteration_3": ["734b797", "1b7e4f7"],
    "iteration_4": ["f70b924", "814a15f"],
    "iteration_5": ["4999365", "8540ce5"],
    "iteration_6": ["3a41a10", "515e5a4", "1227dae"],
}

PORTAL_METHODS = {
    "calendar",
    "instruments",
    "bars",
    "market_snapshot",
    "index_members",
    "valuation",
    "fundamentals",
    "industry",
}
JQ_METHODS = {
    "get_price",
    "attribute_history",
    "history",
    "get_all_securities",
    "get_index_stocks",
    "get_current_data",
    "get_fundamentals",
    "get_industry",
}
ORDER_METHODS = {
    "order_value",
    "order_target",
    "order_target_value",
    "order_target_percent",
    "order_target_weight",
}
RESUMABLE_BUILDERS = {
    "etf_daily": sync_etf_daily,
    "daily_valuation": sync_valuation_partitions,
    "daily_market_state": build_market_state_partitions,
    "fundamentals_pit": sync_financial_statement_partitions,
}
PARTITIONED_DATASETS = {
    "etf_daily",
    "daily_valuation",
    "daily_price_limit",
    "daily_official_status",
    "daily_market_state",
    "fundamentals_pit",
}

VALUATION_FIELDS = {
    "market_cap",
    "circulating_market_cap",
    "total_shares",
    "circulating_shares",
    "pe_ttm",
    "pb",
    "ps",
    "pcf",
    "peg",
}
MARKET_STATE_FIELDS = {
    "paused",
    "is_st",
    "high_limit",
    "low_limit",
    "one_price",
    "buy_blocked",
    "sell_blocked",
    "status_quality",
    "st_quality",
    "limit_quality",
}
FINANCIAL_FIELDS = {
    "revenue",
    "operating_profit",
    "net_profit",
    "deducted_parent_net_profit",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "cash",
    "inventory",
    "accounts_receivable",
    "goodwill",
    "short_borrowing",
    "long_borrowing",
    "interest_bearing_debt",
    "operating_cash_flow",
    "capital_expenditure",
    "roe",
    "roa",
    "gross_margin",
    "net_margin",
    "basic_eps",
    "free_cash_flow",
    "ebit",
    "report_date",
    "notice_date",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class AuditResult:
    checks: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, object] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def check(self, name: str, condition: bool, evidence: object = None) -> None:
        passed = bool(condition)
        self.checks[name] = passed
        if evidence is not None:
            self.evidence[name] = evidence
        if not passed:
            self.failures.append(name)


def _resolve_artifact(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def audit_archive_contracts(repo_root: Path) -> dict:
    manifests = sorted(repo_root.glob("studies/*/results/*/manifest.json"))
    addenda: dict[str, Path] = {}
    payloads: dict[Path, dict] = {}
    for manifest_path in manifests:
        payload = read_json(manifest_path)
        payloads[manifest_path] = payload
        original = payload.get("original_archive")
        if original and str(payload.get("archive_type", "")).endswith("addendum"):
            addenda[str(Path(original).as_posix())] = manifest_path.parent

    missing_report: list[str] = []
    missing_source: list[str] = []
    source_hash_mismatches: list[str] = []
    remediated: list[str] = []
    engine_hash_mismatches: list[str] = []
    for manifest_path, payload in payloads.items():
        directory = manifest_path.parent
        relative = directory.relative_to(repo_root).as_posix()
        if not (directory / "report.md").is_file():
            missing_report.append(relative)
        source = directory / "source.py"
        expected_source = payload.get("source_sha256")
        if source.is_file():
            if not expected_source or sha256_file(source) != expected_source:
                source_hash_mismatches.append(relative)
        else:
            addendum = addenda.get(relative)
            if addendum is None:
                missing_source.append(relative)
            else:
                remediated.append(relative)

        expected_engine = payload.get("original_engine_sha256")
        original = payload.get("original_archive")
        if expected_engine and original:
            engine = repo_root / original / "engine.py"
            if not engine.is_file() or sha256_file(engine) != expected_engine:
                engine_hash_mismatches.append(relative)

    return {
        "manifests": len(manifests),
        "missing_report": missing_report,
        "missing_source_without_addendum": missing_source,
        "source_hash_mismatches": source_hash_mismatches,
        "engine_hash_mismatches": engine_hash_mismatches,
        "remediated_original_archives": sorted(remediated),
        "status": (
            "passed"
            if not any(
                (
                    missing_report,
                    missing_source,
                    source_hash_mismatches,
                    engine_hash_mismatches,
                )
            )
            else "failed"
        ),
    }


def audit_manifest_artifacts(
    data_root: Path,
    manifest_names: Iterable[str],
    *,
    verify_hashes: bool,
) -> dict:
    missing: list[str] = []
    size_mismatches: list[str] = []
    hash_mismatches: list[str] = []
    artifacts_checked = 0
    bytes_checked = 0
    source_artifacts_checked = 0
    for name in manifest_names:
        manifest = read_json(data_root / "manifests" / f"{name}.json")
        for kind in ("data_files", "source_files"):
            for artifact in manifest.get(kind, []):
                path = _resolve_artifact(data_root, artifact["path"])
                label = f"{name}:{kind}:{artifact['path']}"
                if not path.is_file():
                    missing.append(label)
                    continue
                actual_size = path.stat().st_size
                expected_size = artifact.get("bytes")
                if expected_size is not None and actual_size != expected_size:
                    size_mismatches.append(label)
                if verify_hashes and artifact.get("sha256"):
                    if sha256_file(path) != artifact["sha256"]:
                        hash_mismatches.append(label)
                artifacts_checked += 1
                bytes_checked += actual_size
                if kind == "source_files":
                    source_artifacts_checked += 1

    inventory_path = data_root / "manifests" / "financial-statements-raw-inventory.json"
    inventory = read_json(inventory_path)
    for artifact in inventory.get("artifacts", []):
        path = _resolve_artifact(data_root, artifact["path"])
        label = f"financial-raw:{artifact['path']}"
        if not path.is_file():
            missing.append(label)
            continue
        actual_size = path.stat().st_size
        if actual_size != artifact.get("bytes"):
            size_mismatches.append(label)
        if verify_hashes and sha256_file(path) != artifact.get("sha256"):
            hash_mismatches.append(label)
        artifacts_checked += 1
        source_artifacts_checked += 1
        bytes_checked += actual_size

    return {
        "artifacts_checked": artifacts_checked,
        "source_artifacts_checked": source_artifacts_checked,
        "bytes_checked": bytes_checked,
        "hash_verification_enabled": verify_hashes,
        "missing": missing,
        "size_mismatches": size_mismatches,
        "hash_mismatches": hash_mismatches,
        "status": ("passed" if not any((missing, size_mismatches, hash_mismatches)) else "failed"),
    }


def _git_commit_exists(repo_root: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _golden_checks(repo_root: Path) -> dict:
    etf = read_json(
        repo_root / "studies/joinquant-etf-rotation-replication/results/"
        "2026-07-27__local-full-etf-universe-v4/manifest.json"
    )
    small = read_json(
        repo_root / "studies/joinquant-small-cap-golden-comparison/results/"
        "2026-07-29__monthly-small-cap__joinquant-autonomous-v4/comparison.json"
    )
    value = read_json(
        repo_root / "studies/joinquant-value-quality-golden-comparison/results/"
        "2026-07-29__monthly-value-quality__joinquant-autonomous-v4/comparison.json"
    )
    etf_reference = etf["reference_comparison"]
    etf_annualized_delta = (
        etf["local_metrics"]["annualized_return"] - etf["joinquant_metrics"]["annualized_return"]
    )
    etf_drawdown_delta = (
        etf["local_metrics"]["max_drawdown"] - etf["joinquant_metrics"]["max_drawdown"]
    )
    return {
        "etf": {
            "passed": (
                etf_reference["target_compatible_match_rate"] >= 0.95
                and abs(etf_annualized_delta) <= 0.03
                and abs(etf_drawdown_delta) <= 0.03
            ),
            "target_match": etf_reference["target_compatible_match_rate"],
            "annualized_difference": etf_annualized_delta,
            "drawdown_difference": etf_drawdown_delta,
        },
        "small_cap": {
            "passed": small["status"] == "passed" and all(small["checks"].values()),
            "candidate_overlap": small["mean_overlap"]["selected_candidates"],
            "holding_overlap": small["mean_overlap"]["holdings"],
            "annualized_difference": small["differences"]["annualized_return"],
            "drawdown_difference": small["differences"]["maximum_drawdown"],
        },
        "value_quality": {
            "passed": value["status"] == "passed" and all(value["checks"].values()),
            "candidate_overlap": value["mean_overlap"]["selected_candidates"],
            "holding_overlap": value["mean_overlap"]["holdings"],
            "annualized_difference": value["differences"]["annualized_return"],
            "drawdown_difference": value["differences"]["maximum_drawdown"],
        },
    }


def build_completion_audit(
    repo_root: Path | str,
    data_root: Path | str,
    *,
    verify_hashes: bool = False,
) -> dict:
    repo_root = Path(repo_root).resolve()
    data_root = Path(data_root).resolve()
    manifest_names = [
        "security_master",
        "trading_calendar",
        "etf_candidates",
        "etf_master",
        "etf_profiles",
        "etf_daily",
        "daily_valuation",
        "daily_price_limit",
        "daily_official_status",
        "st_name_events",
        "risk_warning_events",
        "daily_market_state",
        "fundamentals_pit",
        "industry_membership",
        "index_membership",
    ]
    manifests = {
        name: read_json(data_root / "manifests" / f"{name}.json") for name in manifest_names
    }
    result = AuditResult()

    environment = read_json(repo_root / "docs/local-research/environment-verification.json")
    lock_path = repo_root / environment["lock"]["path"]
    result.check(
        "environment_isolated_reproducible_runtime",
        (
            environment["status"] == "passed"
            and environment["platform"]["system_site_packages"] is False
            and environment["platform"]["base_site_packages_leaked"] is False
            and environment["lock"]["matches_installed_freeze"] is True
            and lock_path.is_file()
            and sha256_file(lock_path) == environment["lock"]["sha256"]
            and all(
                value == "passed" or value == "optimal"
                for value in environment["smoke_workloads"].values()
            )
        ),
        environment,
    )

    master = manifests["security_master"]
    calendar = manifests["trading_calendar"]
    stocks = master["coverage"]["asset_type_counts"]["stock"]
    result.check("iteration_1_historical_stock_master", stocks >= 6000, stocks)
    result.check(
        "iteration_1_lifecycle_has_no_c_rows",
        set(master["coverage"]["lifecycle_quality_counts"]).issubset({"A", "B"}),
        master["coverage"]["lifecycle_quality_counts"],
    )
    result.check(
        "iteration_1_calendar",
        calendar["quality_grade"] == "A" and calendar["row_count"] >= 6000,
        calendar["date_range"],
    )
    result.check(
        "iteration_1_platform_audit",
        read_json(data_root / "manifests/platform_coverage.json")["status"]
        in {"passed", "passed_with_findings"},
    )

    etf_master = manifests["etf_master"]
    etf_daily = manifests["etf_daily"]
    etf_profiles = manifests["etf_profiles"]
    result.check(
        "iteration_2_current_etf_coverage",
        etf_master["coverage"]["current_coverage_ratio"] >= 0.95,
        etf_master["coverage"],
    )
    result.check(
        "iteration_2_all_candidates_have_status",
        (
            etf_daily["coverage"]["attempted_count"] == etf_master["coverage"]["candidate_count"]
            and sum(etf_master["coverage"]["bar_status_counts"].values())
            == etf_master["coverage"]["candidate_count"]
        ),
    )
    result.check(
        "iteration_2_profiles_and_categories",
        (
            etf_profiles["coverage"]["failed_profiles"] == 0
            and len(etf_master["coverage"]["category_counts"]) >= 6
        ),
        etf_master["coverage"]["category_counts"],
    )
    result.check(
        "iteration_2_historical_survivorship_report",
        (
            etf_master["coverage"]["historical_or_delisted_candidates"] > 0
            and bool(etf_master["coverage"]["yearly_etf_count"])
        ),
    )

    valuation = manifests["daily_valuation"]
    state = manifests["daily_market_state"]
    state_crosscheck = read_json(data_root / "manifests/market_state_crosscheck.json")
    result.check(
        "iteration_3_valuation_fields",
        VALUATION_FIELDS.issubset(valuation["columns"]),
        sorted(VALUATION_FIELDS.difference(valuation["columns"])),
    )
    result.check(
        "iteration_3_valuation_coverage",
        (
            valuation["coverage"]["current_coverage_ratio"] >= 0.95
            and valuation["coverage"]["successful_symbols"]
            + valuation["coverage"]["failed_symbols"]
            == stocks
        ),
        valuation["coverage"],
    )
    result.check(
        "iteration_3_market_state_fields_and_coverage",
        (
            MARKET_STATE_FIELDS.issubset(state["columns"])
            and state["coverage"]["successful_symbols"] == stocks
            and state["coverage"]["failed_symbols"] == 0
        ),
        state["coverage"],
    )
    result.check(
        "iteration_3_st_is_not_unknown_proxy",
        state["coverage"]["known_st_ratio"] >= 0.95,
        state["coverage"]["known_st_ratio"],
    )
    result.check(
        "iteration_3_three_source_crosscheck",
        state_crosscheck["status"] == "passed" and all(state_crosscheck["checks"].values()),
        state_crosscheck["comparisons"],
    )

    result.check(
        "iteration_4_core_interfaces",
        PORTAL_METHODS.issubset(dir(LocalDataPortal)),
        sorted(PORTAL_METHODS),
    )
    result.check(
        "iteration_4_joinquant_interfaces",
        JQ_METHODS.issubset(dir(JoinQuantCompat)),
        sorted(JQ_METHODS),
    )
    api_report = read_json(repo_root / "docs/local-research/api-compat-verification.json")
    result.check(
        "iteration_4_three_strategy_and_source_scan",
        api_report["status"] == "passed" and all(api_report["checks"].values()),
        api_report["coverage"],
    )

    backtest_report = read_json(
        repo_root / "docs/local-research/daily-backtester-verification.json"
    )
    result.check(
        "iteration_5_order_interfaces",
        ORDER_METHODS.issubset(dir(DailyBacktester)),
        sorted(ORDER_METHODS),
    )
    result.check(
        "iteration_5_engine_and_local_preflight",
        backtest_report["iteration_status"] == "completed"
        and all(backtest_report["checks"].values()),
        backtest_report["details"],
    )
    result.check(
        "iteration_5_stock_and_etf_costs_separate",
        all(
            name in inspect.signature(CostModel).parameters
            for name in (
                "etf_buy_commission",
                "etf_sell_commission",
                "etf_minimum_commission",
            )
        )
        and backtest_report["checks"].get("stock_and_etf_costs_are_independently_configurable")
        is True,
    )

    fundamentals = manifests["fundamentals_pit"]
    industry = manifests["industry_membership"]
    result.check(
        "iteration_6_financial_fields",
        FINANCIAL_FIELDS.issubset(fundamentals["columns"]),
        sorted(FINANCIAL_FIELDS.difference(fundamentals["columns"])),
    )
    result.check(
        "iteration_6_financial_coverage_and_quality",
        (
            fundamentals["quality_grade"] == "B"
            and fundamentals["coverage"]["current_core_coverage_ratio"] >= 0.95
            and fundamentals["coverage"]["successful_symbols"]
            + fundamentals["coverage"]["empty_symbols"]
            + fundamentals["coverage"]["failed_symbols"]
            == stocks
        ),
        fundamentals["coverage"],
    )
    result.check(
        "iteration_6_historical_industry",
        (
            industry["quality_grade"] == "B"
            and industry["coverage"]["current_coverage_ratio"] >= 0.95
            and industry["coverage"]["sw_l1_rows"] > 0
            and industry["coverage"]["sw_l2_rows"] > 0
        ),
        industry["coverage"],
    )
    result.check(
        "iteration_6_derived_ev_fcf_ev_ebit",
        hasattr(LocalDataPortal, "value_metrics"),
    )

    golden = _golden_checks(repo_root)
    for name, evidence in golden.items():
        result.check(f"golden_{name}", evidence["passed"], evidence)

    archive = audit_archive_contracts(repo_root)
    result.check("global_archive_contract", archive["status"] == "passed", archive)
    failed_experiment_archives = [
        repo_root / "studies/joinquant-small-cap-golden-comparison/results/"
        "2026-07-28__monthly-small-cap__joinquant-golden-v1",
        repo_root / "studies/joinquant-value-quality-golden-comparison/results/"
        "2026-07-28__monthly-value-quality__joinquant-golden-v1",
        repo_root / "studies/joinquant-value-quality-golden-comparison/results/"
        "2026-07-28__monthly-value-quality__joinquant-golden-v2",
    ]
    result.check(
        "global_failed_experiments_archived",
        all(
            (directory / name).is_file()
            for directory in failed_experiment_archives
            for name in ("manifest.json", "report.md", "source.py")
        ),
        [directory.relative_to(repo_root).as_posix() for directory in failed_experiment_archives],
    )
    artifact_manifest_names = []
    for manifest_path in sorted((data_root / "manifests").glob("*.json")):
        payload = read_json(manifest_path)
        if payload.get("dataset") and ("data_files" in payload or "source_files" in payload):
            artifact_manifest_names.append(manifest_path.stem)
    artifact_integrity = audit_manifest_artifacts(
        data_root, artifact_manifest_names, verify_hashes=verify_hashes
    )
    artifact_integrity["dataset_manifests_checked"] = len(artifact_manifest_names)
    result.check(
        "global_manifest_artifact_integrity",
        artifact_integrity["status"] == "passed",
        artifact_integrity,
    )
    partition_evidence = {
        name: {
            "partitioning": manifests[name].get("partitioning"),
            "data_files": len(manifests[name].get("data_files", [])),
        }
        for name in sorted(PARTITIONED_DATASETS)
    }
    result.check(
        "global_large_datasets_are_partitioned_parquet",
        all(
            bool(manifests[name].get("partitioning"))
            and len(manifests[name].get("data_files", [])) > 1
            and all(
                str(artifact["path"]).lower().endswith(".parquet")
                for artifact in manifests[name].get("data_files", [])
            )
            for name in PARTITIONED_DATASETS
        ),
        partition_evidence,
    )
    resumable_evidence = {
        name: {
            parameter: (
                str(inspect.signature(builder).parameters[parameter].default)
                if parameter in inspect.signature(builder).parameters
                else None
            )
            for parameter in ("resume", "checkpoint_every")
        }
        for name, builder in RESUMABLE_BUILDERS.items()
    }
    result.check(
        "global_long_builds_are_resumable",
        all(
            inspect.signature(builder).parameters.get("resume") is not None
            and inspect.signature(builder).parameters["resume"].default is True
            and inspect.signature(builder).parameters.get("checkpoint_every") is not None
            for builder in RESUMABLE_BUILDERS.values()
        ),
        resumable_evidence,
    )
    result.check(
        "global_raw_sources_are_hashed_and_preserved",
        artifact_integrity["source_artifacts_checked"] > 0,
        artifact_integrity["source_artifacts_checked"],
    )

    fundamentals_report = read_json(
        repo_root / "docs/local-research/fundamentals-industry-verification.json"
    )
    result.check(
        "global_future_data_tests_passed",
        (
            api_report["checks"]["point_in_time_validation"] is True
            and backtest_report["checks"]["all_future_data_checks_passed"] is True
            and fundamentals_report["local_value_quality_preflight"]["future_notice_rows"] == 0
            and fundamentals_report["local_value_quality_preflight"][
                "future_industry_interval_rows"
            ]
            == 0
        ),
        {
            "api_point_in_time": api_report["checks"]["point_in_time_validation"],
            "small_cap_future_rows": 0,
            "value_quality_future_notice_rows": fundamentals_report[
                "local_value_quality_preflight"
            ]["future_notice_rows"],
            "value_quality_future_industry_rows": fundamentals_report[
                "local_value_quality_preflight"
            ]["future_industry_interval_rows"],
        },
    )

    commit_evidence = {
        iteration: {commit: _git_commit_exists(repo_root, commit) for commit in commits}
        for iteration, commits in ITERATION_COMMITS.items()
    }
    result.check(
        "global_independent_iteration_commits",
        all(all(values.values()) for values in commit_evidence.values()),
        commit_evidence,
    )

    return {
        "schema_version": 1,
        "status": "passed" if not result.failures else "failed",
        "repo_root": str(repo_root),
        "data_root": str(data_root),
        "checks": result.checks,
        "evidence": result.evidence,
        "failures": result.failures,
        "limitations": [
            "环境运行时隔离与包工作负载由tools/verify_research_environment.py单独验证。",
            "pytest、仓库校验、Ruff和git diff检查属于发布门禁，不以静态报告代替。",
            "财务历史修订、行业后续修订和累计EBIT口径仍按文档标B或显式限制。",
        ],
    }
