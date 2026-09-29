"""Append-only local artifact store for Intelligence Benchmark evidence.

Completed benchmark runs are published as immutable directories.  A run is
written to a private staging directory, fsynced, and atomically renamed into
place; an existing run id is never replaced.  Shadow-ledger observations are
stored as immutable, hash-chained entry files with a replaceable head pointer.

The store is intentionally local and operator-invoked.  It is not imported by
the application and never reads account-owned production research.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .intelligence_benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkContractError,
    ExecutionManifest,
    canonical_json,
    content_hash,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DuplicateArtifactError(FileExistsError):
    """Raised when an append-only id has already been published."""


class ArtifactIntegrityError(BenchmarkContractError):
    """Raised when stored bytes do not match their recorded hashes."""


def _validate_id(value: str, *, field_name: str) -> str:
    if not _SAFE_ID.fullmatch(value or "") or ".." in value:
        raise BenchmarkContractError(
            f"{field_name} must be a safe 1-128 character identifier"
        )
    return value


def _write_new_json(path: Path, value: Any) -> None:
    """Create one private JSON artifact, failing if the path already exists."""
    data = (canonical_json(value) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _replace_json(path: Path, value: Any) -> None:
    """Atomically replace a mutable pointer; immutable evidence is never passed here."""
    descriptor, temp_name = tempfile.mkstemp(prefix=".head-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write((canonical_json(value) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temp_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class PublishedRun:
    run_id: str
    path: Path
    manifest_sha256: str
    output_sha256: str
    scorecard_sha256: str
    bundle_sha256: str


@dataclass(frozen=True)
class ShadowLedgerEntry:
    sequence: int
    entry_id: str
    run_id: str
    event_type: str
    recorded_at: str
    payload: Mapping[str, Any]
    payload_sha256: str
    previous_entry_sha256: Optional[str]
    schema_version: int = BENCHMARK_SCHEMA_VERSION

    @property
    def entry_sha256(self) -> str:
        return content_hash(self)


@dataclass(frozen=True)
class VerificationReport:
    valid: bool
    checked_runs: int
    checked_ledger_entries: int
    errors: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BenchmarkArtifactStore:
    """Filesystem-backed append-only benchmark evidence store."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        self.ledger_dir = self.root / "shadow_ledger"
        self.entries_dir = self.ledger_dir / "entries"
        for path in (self.root, self.runs_dir, self.ledger_dir, self.entries_dir):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(path, 0o700)

    def publish_run(
        self,
        manifest: ExecutionManifest,
        output: Mapping[str, Any],
        scorecard: Mapping[str, Any],
    ) -> PublishedRun:
        run_id = _validate_id(manifest.run_id, field_name="run_id")
        output_sha256 = content_hash(output)
        if output_sha256 != manifest.output_sha256:
            raise ArtifactIntegrityError(
                "output bytes do not match ExecutionManifest.output_sha256"
            )
        final_dir = self.runs_dir / run_id
        if final_dir.exists():
            raise DuplicateArtifactError(f"run_id already exists: {run_id}")

        stage_dir = Path(tempfile.mkdtemp(prefix=".run-", dir=self.runs_dir))
        os.chmod(stage_dir, 0o700)
        try:
            manifest_payload = {
                "manifest": manifest,
                "manifest_sha256": manifest.manifest_sha256,
            }
            scorecard_sha256 = content_hash(scorecard)
            _write_new_json(stage_dir / "manifest.json", manifest_payload)
            _write_new_json(stage_dir / "output.json", output)
            _write_new_json(
                stage_dir / "scorecard.json",
                {"scorecard": scorecard, "scorecard_sha256": scorecard_sha256},
            )
            bundle = {
                "schema_version": BENCHMARK_SCHEMA_VERSION,
                "run_id": run_id,
                "manifest_sha256": manifest.manifest_sha256,
                "output_sha256": output_sha256,
                "scorecard_sha256": scorecard_sha256,
            }
            bundle_sha256 = content_hash(bundle)
            _write_new_json(
                stage_dir / "bundle.json",
                {"bundle": bundle, "bundle_sha256": bundle_sha256},
            )
            _fsync_directory(stage_dir)
            try:
                os.rename(stage_dir, final_dir)
            except OSError as exc:
                if final_dir.exists():
                    raise DuplicateArtifactError(
                        f"run_id already exists: {run_id}"
                    ) from exc
                raise
            _fsync_directory(self.runs_dir)
        finally:
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
        return PublishedRun(
            run_id=run_id,
            path=final_dir,
            manifest_sha256=manifest.manifest_sha256,
            output_sha256=output_sha256,
            scorecard_sha256=scorecard_sha256,
            bundle_sha256=bundle_sha256,
        )

    def append_shadow_entry(
        self,
        *, entry_id: str, run_id: str, event_type: str, recorded_at: str,
        payload: Mapping[str, Any], expected_previous_sha256: Optional[str] = None,
    ) -> ShadowLedgerEntry:
        entry_id = _validate_id(entry_id, field_name="entry_id")
        run_id = _validate_id(run_id, field_name="run_id")
        event_type = _validate_id(event_type, field_name="event_type")
        lock_path = self.ledger_dir / ".append.lock"
        lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            with os.fdopen(lock_descriptor, "r+", closefd=False) as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                head_path = self.ledger_dir / "head.json"
                head = json.loads(head_path.read_text()) if head_path.exists() else None
                previous = head["entry_sha256"] if head else None
                if expected_previous_sha256 is not None and previous != expected_previous_sha256:
                    raise ArtifactIntegrityError("shadow-ledger head changed")
                if any(self.entries_dir.glob(f"*-{entry_id}.json")):
                    raise DuplicateArtifactError(
                        f"shadow entry_id already exists: {entry_id}"
                    )
                sequence = int(head["sequence"]) + 1 if head else 1
                entry = ShadowLedgerEntry(
                    sequence=sequence,
                    entry_id=entry_id,
                    run_id=run_id,
                    event_type=event_type,
                    recorded_at=recorded_at,
                    payload=dict(payload),
                    payload_sha256=content_hash(payload),
                    previous_entry_sha256=previous,
                )
                entry_path = self.entries_dir / f"{sequence:020d}-{entry_id}.json"
                _write_new_json(
                    entry_path,
                    {"entry": entry, "entry_sha256": entry.entry_sha256},
                )
                _fsync_directory(self.entries_dir)
                _replace_json(
                    head_path,
                    {
                        "sequence": sequence,
                        "entry_id": entry_id,
                        "entry_sha256": entry.entry_sha256,
                    },
                )
                return entry
        finally:
            os.close(lock_descriptor)

    def verify(self) -> VerificationReport:
        errors = []
        checked_runs = 0
        for run_dir in sorted(path for path in self.runs_dir.iterdir() if not path.name.startswith(".")):
            if not run_dir.is_dir():
                errors.append(f"unexpected run artifact: {run_dir.name}")
                continue
            checked_runs += 1
            try:
                manifest_envelope = json.loads((run_dir / "manifest.json").read_text())
                output = json.loads((run_dir / "output.json").read_text())
                scorecard_envelope = json.loads((run_dir / "scorecard.json").read_text())
                bundle_envelope = json.loads((run_dir / "bundle.json").read_text())
                manifest = manifest_envelope["manifest"]
                if content_hash(manifest) != manifest_envelope["manifest_sha256"]:
                    errors.append(f"run {run_dir.name}: manifest hash mismatch")
                if content_hash(output) != manifest["output_sha256"]:
                    errors.append(f"run {run_dir.name}: output hash mismatch")
                if content_hash(scorecard_envelope["scorecard"]) != scorecard_envelope["scorecard_sha256"]:
                    errors.append(f"run {run_dir.name}: scorecard hash mismatch")
                if content_hash(bundle_envelope["bundle"]) != bundle_envelope["bundle_sha256"]:
                    errors.append(f"run {run_dir.name}: bundle hash mismatch")
                bundle = bundle_envelope["bundle"]
                for key, actual in (
                    ("manifest_sha256", manifest_envelope["manifest_sha256"]),
                    ("output_sha256", content_hash(output)),
                    ("scorecard_sha256", scorecard_envelope["scorecard_sha256"]),
                ):
                    if bundle[key] != actual:
                        errors.append(f"run {run_dir.name}: bundle {key} mismatch")
            except (KeyError, OSError, json.JSONDecodeError, TypeError) as exc:
                errors.append(f"run {run_dir.name}: unreadable artifact ({exc})")

        previous = None
        checked_entries = 0
        for expected_sequence, path in enumerate(sorted(self.entries_dir.glob("*.json")), 1):
            checked_entries += 1
            try:
                envelope = json.loads(path.read_text())
                entry = envelope["entry"]
                if int(entry["sequence"]) != expected_sequence:
                    errors.append(f"ledger {path.name}: non-contiguous sequence")
                if entry["previous_entry_sha256"] != previous:
                    errors.append(f"ledger {path.name}: previous hash mismatch")
                if content_hash(entry["payload"]) != entry["payload_sha256"]:
                    errors.append(f"ledger {path.name}: payload hash mismatch")
                actual_hash = content_hash(entry)
                if actual_hash != envelope["entry_sha256"]:
                    errors.append(f"ledger {path.name}: entry hash mismatch")
                previous = actual_hash
            except (KeyError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.append(f"ledger {path.name}: unreadable entry ({exc})")
        head_path = self.ledger_dir / "head.json"
        if checked_entries:
            try:
                head = json.loads(head_path.read_text())
                if head["sequence"] != checked_entries or head["entry_sha256"] != previous:
                    errors.append("shadow-ledger head does not match the final entry")
            except (KeyError, OSError, json.JSONDecodeError, TypeError) as exc:
                errors.append(f"shadow-ledger head is unreadable ({exc})")
        elif head_path.exists():
            errors.append("shadow-ledger head exists without entries")
        return VerificationReport(
            valid=not errors,
            checked_runs=checked_runs,
            checked_ledger_entries=checked_entries,
            errors=tuple(errors),
        )

