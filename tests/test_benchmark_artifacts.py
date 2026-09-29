from __future__ import annotations

import json
import stat

import pytest

from scripts import benchmark_artifact_verify
from validation.benchmark_artifacts import (
    ArtifactIntegrityError,
    BenchmarkArtifactStore,
    DuplicateArtifactError,
)
from validation.intelligence_benchmark import (
    BenchmarkCase,
    BenchmarkContractError,
    BenchmarkProtocol,
    MarketCapTier,
    SourceSnapshot,
    build_execution_manifest,
)


OUTPUT = {"conclusion": "Evidence supports the stated thesis.", "confidence": 0.72}
SCORECARD = {"material_numerical_accuracy": 1.0, "claim_source_binding": 1.0}


def _manifest(run_id="run-001"):
    case = BenchmarkCase(
        case_id="AAPL-case", ticker="AAPL", company="Apple",
        question="What changed?", category="thesis_change",
        protocol=BenchmarkProtocol.FROZEN_HISTORICAL,
        as_of="2026-01-01T00:00:00Z",
        market_cap_tier=MarketCapTier.MEGA_LARGE,
        sector="Information Technology",
    )
    source = SourceSnapshot(
        source_id="filing", source_type="sec_filing",
        document_url="https://www.sec.gov/example",
        published_at="2025-12-31T20:00:00Z",
        retrieved_at="2026-01-01T01:00:00Z",
        content_sha256="a" * 64, authoritative=True,
    )
    return build_execution_manifest(
        case=case, output=OUTPUT, run_id=run_id,
        generated_at="2026-01-01T02:00:00Z", build_commit="abc123",
        model_id="test-model", prompt_version="v1", retrieval_version="v1",
        feature_flags={"memory": False}, sources=[source],
    )


def test_publish_run_writes_complete_verifiable_bundle(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    published = store.publish_run(_manifest(), OUTPUT, SCORECARD)
    assert published.path.is_dir()
    assert {path.name for path in published.path.iterdir()} == {
        "manifest.json", "output.json", "scorecard.json", "bundle.json",
    }
    report = store.verify()
    assert report.valid is True
    assert report.checked_runs == 1


def test_publish_rejects_output_that_does_not_match_manifest(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ArtifactIntegrityError, match="output bytes"):
        store.publish_run(_manifest(), {"different": True}, SCORECARD)
    assert list(store.runs_dir.iterdir()) == []


def test_duplicate_run_id_never_overwrites_original(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    first = store.publish_run(_manifest(), OUTPUT, SCORECARD)
    original = (first.path / "bundle.json").read_bytes()
    with pytest.raises(DuplicateArtifactError, match="already exists"):
        store.publish_run(_manifest(), OUTPUT, {"changed": True})
    assert (first.path / "bundle.json").read_bytes() == original


@pytest.mark.parametrize("unsafe", ["../escape", "a/b", "..", " white"])
def test_run_id_path_traversal_and_unsafe_names_are_rejected(tmp_path, unsafe):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    with pytest.raises(BenchmarkContractError, match="safe"):
        store.publish_run(_manifest(unsafe), OUTPUT, SCORECARD)


def test_empty_run_id_is_rejected_by_manifest_contract():
    with pytest.raises(BenchmarkContractError, match="run_id"):
        _manifest("")


def test_published_files_are_private(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    published = store.publish_run(_manifest(), OUTPUT, SCORECARD)
    for path in published.path.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_verify_detects_output_tampering(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    published = store.publish_run(_manifest(), OUTPUT, SCORECARD)
    (published.path / "output.json").write_text('{"conclusion":"tampered"}\n')
    report = store.verify()
    assert report.valid is False
    assert any("output hash mismatch" in error for error in report.errors)


def test_shadow_ledger_is_contiguous_and_hash_chained(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    first = store.append_shadow_entry(
        entry_id="event-001", run_id="run-001", event_type="analysis",
        recorded_at="2026-01-01T02:00:00Z", payload={"ticker": "AAPL"},
    )
    second = store.append_shadow_entry(
        entry_id="event-002", run_id="run-002", event_type="analysis",
        recorded_at="2026-01-02T02:00:00Z", payload={"ticker": "MSFT"},
        expected_previous_sha256=first.entry_sha256,
    )
    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_entry_sha256 == first.entry_sha256
    report = store.verify()
    assert report.valid is True
    assert report.checked_ledger_entries == 2


def test_shadow_duplicate_entry_id_is_rejected(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    kwargs = dict(
        entry_id="event-001", run_id="run-001", event_type="analysis",
        recorded_at="2026-01-01T02:00:00Z", payload={"ticker": "AAPL"},
    )
    store.append_shadow_entry(**kwargs)
    with pytest.raises(DuplicateArtifactError, match="already exists"):
        store.append_shadow_entry(**kwargs)


def test_shadow_compare_and_swap_rejects_stale_writer(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    store.append_shadow_entry(
        entry_id="event-001", run_id="run-001", event_type="analysis",
        recorded_at="2026-01-01T02:00:00Z", payload={"ticker": "AAPL"},
    )
    with pytest.raises(ArtifactIntegrityError, match="head changed"):
        store.append_shadow_entry(
            entry_id="event-002", run_id="run-002", event_type="analysis",
            recorded_at="2026-01-02T02:00:00Z", payload={"ticker": "MSFT"},
            expected_previous_sha256="0" * 64,
        )


def test_verify_detects_ledger_tampering(tmp_path):
    store = BenchmarkArtifactStore(tmp_path / "artifacts")
    store.append_shadow_entry(
        entry_id="event-001", run_id="run-001", event_type="analysis",
        recorded_at="2026-01-01T02:00:00Z", payload={"ticker": "AAPL"},
    )
    entry_path = next(store.entries_dir.glob("*.json"))
    envelope = json.loads(entry_path.read_text())
    envelope["entry"]["payload"]["ticker"] = "MSFT"
    entry_path.write_text(json.dumps(envelope))
    report = store.verify()
    assert report.valid is False
    assert any("payload hash mismatch" in error for error in report.errors)


def test_cli_reports_valid_store(tmp_path, capsys):
    root = tmp_path / "artifacts"
    BenchmarkArtifactStore(root).publish_run(_manifest(), OUTPUT, SCORECARD)
    assert benchmark_artifact_verify.main([str(root)]) == 0
    assert "integrity: PASS" in capsys.readouterr().out


def test_cli_returns_nonzero_after_tampering(tmp_path, capsys):
    root = tmp_path / "artifacts"
    published = BenchmarkArtifactStore(root).publish_run(
        _manifest(), OUTPUT, SCORECARD
    )
    (published.path / "scorecard.json").write_text("{}")
    assert benchmark_artifact_verify.main([str(root)]) == 1
    assert "integrity: FAIL" in capsys.readouterr().out
