import importlib.util
import json
import sys
from pathlib import Path


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "summarize_formal_candidates.py"
SPEC = importlib.util.spec_from_file_location("summarize_formal_candidates", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_formal_candidate_mapping_points_only_to_immutable_manifests():
    for candidate_id, manifests in (
        ("lazy-etf-regime-switch", [MODULE.LAZY_ARCHIVE / "manifest.json"]),
        ("profitable-small-cap-a-share", [MODULE.PROFIT_ARCHIVE / "manifest.json"]),
        (
            "wufu-etf-rotation",
            [MODULE.WUFU_PARENT / "manifest.json", MODULE.WUFU_ARCHIVE / "manifest.json"],
        ),
    ):
        protocol = MODULE.provenance_protocol(
            candidate_id, manifests, evidence_rule="test"
        )
        assert protocol["no_new_parameter_selection"] is True
        assert all(len(item["sha256"]) == 64 for item in protocol["source_manifests"])


def test_committed_formal_candidate_scorecards_do_not_overpromote():
    for candidate_id in (
        "lazy-etf-regime-switch",
        "profitable-small-cap-a-share",
        "wufu-etf-rotation",
    ):
        path = STUDY_DIR / "results" / candidate_id / "live-readiness-scorecard.json"
        scorecard = json.loads(path.read_text(encoding="utf-8"))
        assert scorecard["candidate_id"] == candidate_id
        assert scorecard["status"] == "R1"
        assert scorecard["strict_natural_oos"] is False
