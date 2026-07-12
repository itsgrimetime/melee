from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.search.delta_minimize.contracts import DeltaMinimizeError
from src.search.delta_minimize.store import (
    DeltaRunStore,
    EvidenceKey,
    ParentEvidenceKey,
    write_json_atomic,
)
from src.search.store import ArtifactStore

KEY = EvidenceKey(
    source_hash="source",
    function="draw",
    cflags_hash="cflags",
    compiler_fingerprint="mwcc-1.2.5n",
    expected_object_hash="expected",
    objective_manifest_hash="objectives",
    parser_schema_hash="parsers-v1",
    inspector_version="inspector-v1:enabled;mode=objobjects",
)
PARENT_KEY = ParentEvidenceKey(
    source_hash="source",
    function="draw",
    cflags_hash="cflags",
    compiler_fingerprint="mwcc-1.2.5n",
    expected_object_hash="expected",
    parser_schema_hash="parsers-v1",
    inspector_version="inspector-v1:enabled",
)
PROVENANCE = {
    "cflags_hash": "cflags",
    "compiler_fingerprint": "mwcc-1.2.5n",
    "expected_object_hash": "expected",
    "objective_manifest_hash": "objectives",
    "parser_schema_hash": "parsers-v1",
    "inspector_version": "inspector-v1:enabled",
}


def test_complete_evidence_resumes_without_runner(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    store.write_evidence(KEY, {"status": "complete", "value": 7})

    assert store.load_evidence(KEY) == {"status": "complete", "value": 7}
    envelope = json.loads(store.evidence_path(KEY).read_text())
    assert envelope["key"] == KEY.to_dict()
    assert envelope["key_digest"] == KEY.digest()


def test_evidence_key_digest_matches_the_frozen_canonical_contract() -> None:
    expected = hashlib.sha256(json.dumps(KEY.to_dict(), sort_keys=True).encode()).hexdigest()[:32]

    assert KEY.digest() == expected


def test_changed_provenance_invalidates_cache(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    store.write_evidence(KEY, {"status": "complete"})

    assert store.load_evidence(replace(KEY, compiler_fingerprint="new")) is None
    assert store.load_evidence(replace(KEY, objective_manifest_hash="new")) is None


def test_parent_key_omits_only_objective_manifest_hash(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    store.write_parent_evidence(PARENT_KEY, {"status": "complete", "side": "left"})

    assert "objective_manifest_hash" not in PARENT_KEY.to_dict()
    assert store.load_parent_evidence(PARENT_KEY)["side"] == "left"
    assert store.load_parent_evidence(replace(PARENT_KEY, cflags_hash="new")) is None


def test_full_candidate_key_requires_bound_provenance(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    candidate = SimpleNamespace(source_hash="source")
    config = SimpleNamespace(function="draw", include_objobjects=True)

    with pytest.raises(DeltaMinimizeError, match="unbound-evidence-provenance"):
        store.evidence_key(candidate, config)

    store.bind_provenance(PROVENANCE)
    assert store.evidence_key(candidate, config) == KEY


@pytest.mark.parametrize(
    "provenance",
    [
        {**PROVENANCE, "objective_manifest_hash": ""},
        {key: value for key, value in PROVENANCE.items() if key != "parser_schema_hash"},
        {**PROVENANCE, "unexpected": "value"},
    ],
)
def test_bind_provenance_rejects_incomplete_or_unknown_fields(tmp_path: Path, provenance: dict[str, str]) -> None:
    with pytest.raises(DeltaMinimizeError, match="invalid-evidence-provenance"):
        DeltaRunStore(tmp_path).bind_provenance(provenance)


def test_malformed_wrong_schema_or_incomplete_cache_is_rejected(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    store.write_evidence(KEY, {"status": "complete", "value": 1})
    path = store.evidence_path(KEY)

    path.write_text("{", encoding="utf-8")
    assert store.load_evidence(KEY) is None

    path.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")
    assert store.load_evidence(KEY) is None

    path.unlink()
    store.write_evidence(KEY, {"status": "complete", "value": 1})
    envelope = json.loads(path.read_text())
    envelope["status"] = "incomplete"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    assert store.load_evidence(KEY) is None


def test_key_and_payload_digest_tampering_is_rejected(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    store.write_evidence(KEY, {"status": "complete", "value": 1})
    path = store.evidence_path(KEY)
    envelope = json.loads(path.read_text())

    envelope["key"]["function"] = "other"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    assert store.load_evidence(KEY) is None

    path.unlink()
    store.write_evidence(KEY, {"status": "complete", "value": 1})
    envelope = json.loads(path.read_text())
    envelope["payload_digest"] = "0" * 64
    path.write_text(json.dumps(envelope), encoding="utf-8")
    assert store.load_evidence(KEY) is None


def test_content_addressed_evidence_is_idempotent_but_not_overwritable(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    first = store.write_evidence(KEY, {"status": "complete", "value": 1})

    assert store.write_evidence(KEY, {"value": 1, "status": "complete"}) == first
    with pytest.raises(DeltaMinimizeError, match="immutable-evidence-conflict"):
        store.write_evidence(KEY, {"status": "complete", "value": 2})
    assert store.load_evidence(KEY)["value"] == 1


def test_incomplete_payload_is_not_persisted(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)

    with pytest.raises(DeltaMinimizeError, match="incomplete-evidence"):
        store.write_evidence(KEY, {"status": "incomplete"})
    assert not store.evidence_path(KEY).exists()


def test_atomic_write_preserves_previous_json_and_cleans_temp_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = DeltaRunStore(tmp_path)
    store.write_result({"status": "frontier"})
    monkeypatch.setattr(
        os,
        "replace",
        lambda *_: (_ for _ in ()).throw(OSError("boom")),
    )

    with pytest.raises(OSError, match="boom"):
        store.write_result({"status": "matched"})

    assert json.loads((tmp_path / "result.json").read_text())["status"] == "frontier"
    assert list(tmp_path.glob(".result.json.*.tmp")) == []


def test_atomic_json_is_deterministic_and_fsyncs_file_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fsynced: list[int] = []
    real_fsync = os.fsync

    def record_fsync(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", record_fsync)
    path = tmp_path / "nested" / "data.json"
    write_json_atomic(path, {"z": 1, "a": {2: "two", 1: "one"}})

    assert path.read_text() == '{\n  "a": {\n    "1": "one",\n    "2": "two"\n  },\n  "z": 1\n}\n'
    assert len(fsynced) == 2


def test_store_uses_artifact_store_for_content_addressed_sources(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)

    first = store.put_source("int draw(void) { return 0; }\n")
    second = store.put_source("int draw(void) { return 0; }\n")

    assert first == second
    assert first.parent == tmp_path / "artifacts" / "sources"

    legacy = ArtifactStore(tmp_path / "artifacts")
    assert legacy.put_source("int draw(void) { return 0; }\n") == first


def test_source_write_is_atomic_durable_and_concurrency_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = DeltaRunStore(tmp_path)
    fsynced: list[int] = []
    real_fsync = os.fsync

    def record_fsync(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", record_fsync)
    source = "int draw(void) { return 0; }\n"
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(store.put_source, [source] * 8))

    assert len(set(paths)) == 1
    assert paths[0].read_text() == source
    assert len(fsynced) >= 2


def test_source_replace_failure_publishes_nothing_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = DeltaRunStore(tmp_path)
    monkeypatch.setattr(
        os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")),
    )

    with pytest.raises(OSError, match="boom"):
        store.put_source("int draw(void) { return 0; }\n")

    assert list((tmp_path / "artifacts" / "sources").glob("*.c")) == []
    assert list((tmp_path / "artifacts" / "sources").glob(".*.tmp")) == []


def test_corrupt_preexisting_source_blob_fails_closed(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    source = "int draw(void) { return 0; }\n"
    digest = hashlib.sha256(source.encode()).hexdigest()[:32]
    path = tmp_path / "artifacts" / "sources" / f"{digest}.c"
    path.write_bytes(b"wrong bytes")

    with pytest.raises(DeltaMinimizeError, match="corrupt-source-artifact"):
        store.put_source(source)

    assert path.read_bytes() == b"wrong bytes"


def test_broken_source_blob_symlink_cannot_write_outside_root(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path / "run")
    outside = tmp_path / "outside"
    outside.mkdir()
    source = "int draw(void) { return 0; }\n"
    digest = hashlib.sha256(source.encode()).hexdigest()[:32]
    path = store.root / "artifacts" / "sources" / f"{digest}.c"
    escaped = outside / "escaped.c"
    path.symlink_to(escaped)

    with pytest.raises(DeltaMinimizeError, match="unsafe-store-path"):
        store.put_source(source)

    assert not escaped.exists()
    assert path.is_symlink()


def test_symlinked_sources_directory_cannot_write_outside_root(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path / "run")
    outside = tmp_path / "outside"
    outside.mkdir()
    sources = store.root / "artifacts" / "sources"
    sources.rmdir()
    sources.symlink_to(outside, target_is_directory=True)

    with pytest.raises(DeltaMinimizeError, match="unsafe-store-path"):
        store.put_source("int draw(void) { return 0; }\n")

    assert list(outside.iterdir()) == []


def test_artifact_symlink_is_rejected_before_store_initialization_writes(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "artifacts").symlink_to(outside, target_is_directory=True)

    with pytest.raises(DeltaMinimizeError, match="unsafe-store-path"):
        DeltaRunStore(root)

    assert list(outside.iterdir()) == []


def test_broken_gitignore_symlink_is_rejected_before_store_initialization_writes(tmp_path: Path) -> None:
    root = tmp_path / "run"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = outside / "escaped.gitignore"
    (artifacts / ".gitignore").symlink_to(escaped)

    with pytest.raises(DeltaMinimizeError, match="unsafe-store-path"):
        DeltaRunStore(root)

    assert not escaped.exists()


def test_existing_permissive_gitignore_is_normalized_to_full_coverage(tmp_path: Path) -> None:
    root = tmp_path / "run"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    gitignore = artifacts / ".gitignore"
    gitignore.write_text("objects/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)

    DeltaRunStore(root)

    assert gitignore.read_bytes() == b"*\n"
    ignored = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", "artifacts/sources/candidate.c"],
        check=False,
    )
    assert ignored.returncode == 0


def test_candidate_paths_are_stable_and_reject_unsafe_ids(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)

    assert store.inspect_output_path("candidate-0001") == (tmp_path / "evidence" / "candidate-0001" / "inspect.txt")
    with pytest.raises(DeltaMinimizeError, match="invalid-candidate-id"):
        store.inspect_output_path("../escape")
    with pytest.raises(DeltaMinimizeError, match="invalid-candidate-id"):
        store.inspect_output_path("nested/id")
    assert store.inspect_output_path("a" * 255).parent.name == "a" * 255
    with pytest.raises(DeltaMinimizeError, match="invalid-candidate-id"):
        store.inspect_output_path("a" * 256)


def test_symlinked_evidence_component_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "run"
    store = DeltaRunStore(root)
    (root / "evidence").symlink_to(outside, target_is_directory=True)

    with pytest.raises(DeltaMinimizeError, match="unsafe-store-path"):
        store.inspect_output_path("candidate")
    assert store.load_evidence(KEY) is None


def test_symlinked_root_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(DeltaMinimizeError, match="unsafe-store-path"):
        DeltaRunStore(linked)


def test_color_target_is_content_addressed_and_normalizes_force_keys(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)
    target = {
        "schema_version": "delta-minimize-color-target.v1",
        "function": "draw",
        "class_id": 0,
        "baseline_dump": "/tmp/base.pcdump",
        "force_phys": {3: 29, "4": 30},
        "coalesce_preservation": True,
    }

    path = store.write_color_target(target)
    assert path.parent == tmp_path / "objective" / "color-targets"
    assert len(path.stem) == 64
    assert json.loads(path.read_text())["force_phys"] == {"3": 29, "4": 30}
    assert store.write_color_target(dict(target)) == path

    next_path = store.write_color_target({**target, "class_id": 1})
    assert next_path != path
    assert path.is_file()
    current = json.loads((tmp_path / "objective" / "color-target-current.json").read_text())
    assert current == {
        "artifact": str(next_path.relative_to(tmp_path)),
        "sha256": next_path.stem,
    }


def test_score_target_is_content_addressed_legacy_projection(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)

    path = store.write_score_target("draw", {3: 29, 4: 30})

    assert path.parent == tmp_path / "objective" / "score-targets"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "function": "draw",
        "virtuals": {"3": 29, "4": 30},
    }
    assert store.write_score_target("draw", {4: 30, 3: 29}) == path
    assert store.write_score_target("draw", {3: 28, 4: 30}) != path


def test_phase_and_result_paths_use_atomic_store_writes(tmp_path: Path) -> None:
    store = DeltaRunStore(tmp_path)

    assert store.write_objective_manifest({"schema_version": "o.v1"}) == (tmp_path / "objective-manifest.json")
    assert store.write_delta_manifest({"schema_version": "d.v1"}) == (tmp_path / "delta-manifest.json")
    assert store.write_candidates({"candidates": []}) == tmp_path / "candidates.json"
    assert store.write_result({"status": "incomplete"}) == tmp_path / "result.json"
