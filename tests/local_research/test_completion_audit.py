import hashlib
import json
from pathlib import Path

from quant_research.completion_audit import audit_archive_contracts


def write_archive(
    root: Path,
    relative: str,
    *,
    source: str | None = "print('ok')\n",
    extra: dict | None = None,
) -> Path:
    directory = root / relative
    directory.mkdir(parents=True)
    (directory / "report.md").write_text("# report\n", encoding="utf-8")
    manifest = {"schema_version": 1}
    if source is not None:
        source_path = directory / "source.py"
        source_path.write_text(source, encoding="utf-8")
        manifest["source_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest.update(extra or {})
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_archive_audit_accepts_hash_valid_complete_archive(tmp_path):
    write_archive(tmp_path, "studies/example/results/complete")

    report = audit_archive_contracts(tmp_path)

    assert report["status"] == "passed"
    assert report["manifests"] == 1
    assert report["remediated_original_archives"] == []


def test_archive_audit_maps_addendum_without_mutating_original(tmp_path):
    original = write_archive(
        tmp_path,
        "studies/example/results/original",
        source=None,
    )
    engine = original / "engine.py"
    engine.write_text("print('engine')\n", encoding="utf-8")
    engine_hash = hashlib.sha256(engine.read_bytes()).hexdigest()
    write_archive(
        tmp_path,
        "studies/example/results/addendum",
        extra={
            "archive_type": "reproducibility_entrypoint_addendum",
            "original_archive": "studies/example/results/original",
            "original_engine_sha256": engine_hash,
        },
    )

    report = audit_archive_contracts(tmp_path)

    assert report["status"] == "passed"
    assert report["remediated_original_archives"] == ["studies/example/results/original"]


def test_archive_audit_rejects_missing_or_hash_drift(tmp_path):
    missing = write_archive(
        tmp_path,
        "studies/example/results/missing",
        source=None,
    )
    drifted = write_archive(tmp_path, "studies/example/results/drifted")
    (drifted / "source.py").write_text("changed\n", encoding="utf-8")
    (missing / "report.md").unlink()

    report = audit_archive_contracts(tmp_path)

    assert report["status"] == "failed"
    assert report["missing_report"] == ["studies/example/results/missing"]
    assert report["missing_source_without_addendum"] == ["studies/example/results/missing"]
    assert report["source_hash_mismatches"] == ["studies/example/results/drifted"]
