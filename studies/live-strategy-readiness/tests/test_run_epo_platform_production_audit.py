import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_epo_platform_production_audit.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_epo_platform", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_weight_l1_counts_missing_assets_as_zero():
    assert MODULE.weight_l1({"A": 0.6, "B": 0.4}, {"A": 0.5, "C": 0.5}) == pytest.approx(
        1.0
    )


def test_symbol_conversion_round_trips_joinquant_and_local_codes():
    for joinquant, local in (
        ("513100.XSHG", "SH513100"),
        ("159740.XSHE", "SZ159740"),
    ):
        assert MODULE.to_local_symbol(joinquant) == local
        assert MODULE.to_joinquant_symbol(local) == joinquant


def test_committed_platform_preflight_matches_all_frozen_oos_targets():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    audit = json.loads(
        (candidate / "platform-production-audit.json").read_text(encoding="utf-8")
    )
    preflight = pd.read_csv(candidate / "platform-source-preflight.csv")

    assert len(preflight) == 28
    assert preflight["targets_match_exactly"].all()
    assert preflight["target_weight_l1"].max() <= 1e-12
    assert preflight["fallback_used"].sum() == 0
    assert audit["local_source_preflight"]["status"] == "passed"
    assert all(audit["local_source_preflight"]["gates"].values())


def test_production_audit_keeps_r3_blocked_without_real_feeds_and_platform_export():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    audit = json.loads(
        (candidate / "platform-production-audit.json").read_text(encoding="utf-8")
    )
    fields = pd.read_csv(candidate / "production-field-audit.csv")

    assert audit["candidate_status_after_audit"] == "R2"
    assert audit["eligible_for_R3"] is False
    assert audit["real_joinquant_golden"]["status"] == "not-run-no-export"
    assert audit["production_data"]["qdii_asset_count"] == 2
    assert audit["production_data"]["qdii_complete_asset_count"] == 0
    qdii = fields[fields["scope"] == "qdii"]
    assert set(qdii["field"]) == set(
        audit["production_data"]["required_qdii_fields"]
    )
    assert (qdii["status"] == "missing-no-production-feed").all()


def test_platform_audit_manifest_binds_source_protocol_and_data_hashes():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    manifest = json.loads(
        (candidate / "platform-production-manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["candidate_id"] == "multi-asset-etf-momentum-epo-safe"
    assert manifest["formal_source_sha256"] == MODULE.sha256_file(MODULE.FORMAL_SOURCE)
    assert manifest["protocol_sha256"] == MODULE.sha256_file(MODULE.PROTOCOL_PATH)
    assert set(manifest["data_manifests"]) == {"etf_daily", "etf_master"}
    for item in manifest["data_manifests"].values():
        path = Path(item["path"])
        assert path.is_file()
        assert item["sha256"] == MODULE.sha256_file(path)
