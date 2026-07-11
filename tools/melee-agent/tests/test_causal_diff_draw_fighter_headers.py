from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from src.mwcc_debug.causal_diff import (
    CORE_BACKEND_CAPABILITIES,
    CausalDiffOptions,
    InMemoryEvidenceStore,
    canonical_bytes,
    run_causal_diff,
)
from src.mwcc_debug.causal_diff.alignment import AbstentionReason
from src.mwcc_debug.causal_diff.inference import AnalysisStatus, VerdictStatus
from src.mwcc_debug.causal_diff.models import (
    ComparisonRecord,
    EvidenceEdge,
    EvidenceNode,
)
from src.mwcc_debug.causal_diff.render import render_json, render_text

FUNCTION = "mnDiagram_DrawFighterHeaders"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "causal_diff" / "draw_fighter_headers"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compile_id(
    *,
    compiler: str,
    target_build: str,
    flags_digest: str,
    environment_digest: str,
    source_digest: str,
) -> str:
    return _sha256(
        canonical_bytes(
            {
                "function": FUNCTION,
                "compiler": compiler,
                "target_build": target_build,
                "flags_digest": flags_digest,
                "environment_digest": environment_digest,
                "source_digest": source_digest,
            }
        )
    )


def _write_manifest(directory: Path, label: str, metadata: dict[str, object]) -> Path:
    artifact_names = {
        "source": "source.c",
        "checkdiff": "checkdiff.json",
        "inspector": "inspect.txt",
        "frame_report": "frame.json",
    }
    digests = {name: _sha256((directory / path).read_bytes()) for name, path in artifact_names.items()}
    backend_digest = _sha256((directory / "pcdump.txt").read_bytes())
    compiler = str(metadata["compiler"])
    target_build = str(metadata["target"])
    flags_digest = str(metadata["flags_sha256"])
    environment_digest = str(metadata["environment_sha256"])
    source_digest = digests["source"]
    payload = {
        "schema_version": "causal-frontier-bundle.v1",
        "label": label,
        "function": FUNCTION,
        "compile": {
            "id": _compile_id(
                compiler=compiler,
                target_build=target_build,
                flags_digest=flags_digest,
                environment_digest=environment_digest,
                source_digest=source_digest,
            ),
            "compiler": compiler,
            "target_build": target_build,
            "flags_digest": flags_digest,
            "environment_digest": environment_digest,
            "source_digest": source_digest,
            "expected_assembly_digest": metadata["fixture_expected_assembly_sha256"],
        },
        "artifacts": {
            "source": {"path": artifact_names["source"], "sha256": source_digest},
            "checkdiff": {
                "path": artifact_names["checkdiff"],
                "sha256": digests["checkdiff"],
            },
            "backend": [
                {
                    "path": "pcdump.txt",
                    "sha256": backend_digest,
                    "format": "mwcc-debug-pcdump",
                    "capabilities": sorted(CORE_BACKEND_CAPABILITIES),
                }
            ],
            "inspector": {
                "path": artifact_names["inspector"],
                "sha256": digests["inspector"],
            },
            "frame_report": {
                "path": artifact_names["frame_report"],
                "sha256": digests["frame_report"],
            },
        },
        "producer_versions": {
            "checkdiff": "checkdiff-json.v1",
            "mwcc_debug": "mwcc-debug-pcdump.v1",
            "mwcc_inspect": "mwcc-inspect-text.v1",
            "frame_report": "frame-reservations.v1",
        },
    }
    manifest = directory / "bundle.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return manifest


def materialize_manifests(tmp_path: Path) -> tuple[Path, Path]:
    metadata = json.loads((FIXTURE_ROOT / "metadata.json").read_text())
    paths: dict[str, Path] = {}
    for label in ("paired", "direct"):
        destination = tmp_path / label
        shutil.copytree(FIXTURE_ROOT / label, destination)
        paths[label] = _write_manifest(destination, label, metadata)
    return paths["paired"], paths["direct"]


class RecordingPersistentStore:
    """Protocol-only persistent-store stand-in with canonical batch records."""

    def __init__(self) -> None:
        self._store = InMemoryEvidenceStore()
        self.batches: list[bytes] = []

    def _record(self, kind: str, records: Iterable[object]) -> tuple[object, ...]:
        batch = tuple(records)
        self.batches.append(
            canonical_bytes(
                {
                    "kind": kind,
                    "record_ids": sorted(str(record.record_id) for record in batch),
                }
            )
        )
        return batch

    def add_nodes(self, records: Iterable[EvidenceNode]) -> None:
        self._store.add_nodes(self._record("nodes", records))

    def add_edges(self, records: Iterable[EvidenceEdge]) -> None:
        self._store.add_edges(self._record("edges", records))

    def add_comparisons(self, records: Iterable[ComparisonRecord]) -> None:
        self._store.add_comparisons(self._record("comparisons", records))

    def get_node(self, record_id: str):
        return self._store.get_node(record_id)

    def get_edge(self, record_id: str):
        return self._store.get_edge(record_id)

    def neighbors(self, record_id: str, edge_kinds=None, direction="both"):
        return self._store.neighbors(record_id, edge_kinds, direction)

    def find_nodes(self, compile_id: str, node_kind=None, role_key=None):
        return self._store.find_nodes(compile_id, node_kind, role_key)

    def find_edges(self, compile_id: str, edge_kind=None, endpoint=None):
        return self._store.find_edges(compile_id, edge_kind, endpoint)

    def find_comparisons(self, analysis_id: str, relation_kind=None, endpoint=None):
        return self._store.find_comparisons(analysis_id, relation_kind, endpoint)

    def subgraph(self, roots, edge_kinds, max_depth):
        return self._store.subgraph(roots, edge_kinds, max_depth)


def run_pilot(tmp_path: Path, store_factory=InMemoryEvidenceStore):
    paired, direct = materialize_manifests(tmp_path)
    return run_causal_diff(
        CausalDiffOptions(
            function=FUNCTION,
            frontiers=(("paired", paired), ("direct", direct)),
            retail_offset=0x234,
        ),
        store_factory=store_factory,
    )


def test_draw_fighter_headers_exact_artifacts_abstain_without_backend_role_identity(
    tmp_path: Path,
) -> None:
    report = run_pilot(tmp_path)
    assert report.analysis_status is AnalysisStatus.ABSTAINED
    assert report.verdicts == ()
    assert report.effects.allocator_effects == ()
    assert {(item.operand_key, item.reason) for item in report.effects.abstentions} == {
        ("def:0", AbstentionReason.AMBIGUOUS_BACKEND_ROLE),
        ("use:0", AbstentionReason.AMBIGUOUS_BACKEND_ROLE),
    }
    assert {
        "ambiguous-backend-role:def:0",
        "ambiguous-backend-role:use:0",
    } <= set(report.missing_evidence)
    assert not any(item.status in {VerdictStatus.CAUSES, VerdictStatus.CANDIDATE_CAUSE} for item in report.verdicts)

    paired = json.loads((tmp_path / "paired" / "checkdiff.json").read_text())
    direct = json.loads((tmp_path / "direct" / "checkdiff.json").read_text())
    assert paired["current_asm"][1].endswith("addi    r22,r21,0")
    assert direct["current_asm"][1].endswith("addi    r20,r19,0")
    stack = report.effects.stack_effects[0]
    assert stack.expected_offset == 0x44
    assert {
        stack.first_label: stack.first_offset,
        stack.second_label: stack.second_offset,
    } == {"direct": 0x44, "paired": 0x48}


def test_draw_pilot_makes_no_function_or_source_specific_identity_claims(tmp_path: Path) -> None:
    report = run_pilot(tmp_path)
    assert report.effects.allocator_effects == ()
    assert all("mnDiagram_DrawFighterHeaders" not in rule.rule_id for rule in report.applied_rules)
    assert all("fighter_id" not in rule.rule_id for rule in report.applied_rules)


def test_in_memory_and_persistent_store_reports_are_byte_identical(tmp_path: Path) -> None:
    memory = run_pilot(tmp_path / "memory", store_factory=InMemoryEvidenceStore)
    persistent = run_pilot(tmp_path / "persistent", store_factory=RecordingPersistentStore)
    assert render_json(memory) == render_json(persistent)
    assert render_text(memory) == render_text(persistent)
