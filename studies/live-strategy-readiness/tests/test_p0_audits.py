import hashlib
import json
from pathlib import Path


STUDY_DIR = Path(__file__).resolve().parents[1]
ROOT = STUDY_DIR.parents[1]
RESULTS_DIR = STUDY_DIR / "results"

EXPECTED = {
    "low-risk-medium-return": {
        "grade": "C",
        "replay_ready": False,
        "backtest_end": "2024-06-01",
        "post_date": "2024-06-16",
    },
    "multi-asset-etf-momentum-epo": {
        "grade": "B",
        "replay_ready": True,
        "backtest_end": "2024-03-21",
        "post_date": "2024-03-23",
    },
    "white-horse-offense-defense": {
        "grade": "C",
        "replay_ready": False,
        "backtest_end": "2024-10-03",
        "post_date": "2024-10-05",
    },
}


def sha256(path):
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_p0_source_audits_freeze_current_archive_snapshots_without_overclaiming_oos():
    result_directories = {path.name for path in RESULTS_DIR.iterdir() if path.is_dir()}
    assert set(EXPECTED).issubset(result_directories)

    for candidate_id, expected in EXPECTED.items():
        candidate_dir = RESULTS_DIR / candidate_id
        protocol = json.loads((candidate_dir / "protocol.json").read_text(encoding="utf-8"))
        audit = (candidate_dir / "source-audit.md").read_text(encoding="utf-8")
        source = ROOT / protocol["frozen_source"]["path"]

        assert protocol["candidate_id"] == candidate_id
        assert protocol["status"] == "source-audit-complete"
        assert protocol["research_level"] == "R0"
        assert protocol["source_vintage"]["grade"] == expected["grade"]
        assert protocol["source_vintage"]["strict_natural_oos"] is False
        assert protocol["source_vintage"]["current_snapshot_only"] is True
        assert protocol["post_publication_replay"]["ready"] is expected["replay_ready"]
        assert protocol["public_backtest"]["end"] == expected["backtest_end"]
        assert protocol["publication"]["date"] == expected["post_date"]
        assert source.is_file()
        assert protocol["frozen_source"]["sha256"] == sha256(source)
        assert protocol["experiment_policy"]["tune_on_post_publication_window"] is False
        assert "## 事实" in audit
        assert "## 推断" in audit
        assert "## 决定" in audit


def test_only_unmodified_epo_post_is_ready_for_first_untuned_replay():
    ready = []
    for candidate_id in EXPECTED:
        protocol = json.loads(
            (RESULTS_DIR / candidate_id / "protocol.json").read_text(encoding="utf-8")
        )
        if protocol["post_publication_replay"]["ready"]:
            ready.append(candidate_id)

    assert ready == ["multi-asset-etf-momentum-epo"]
