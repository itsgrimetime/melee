from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

from src.mwcc_debug.causal_diff.bundles import ValidatedBundle
from src.mwcc_debug.causal_diff.inspect_adapter import adapt_inspector
from src.mwcc_debug.causal_diff.models import Confidence, FrontierBundleManifest
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore
from src.mwcc_debug.inspect_parser import parse_inspect_function

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "causal_diff" / "inspect"
FIXTURE = FIXTURE_DIR / "paired_excerpt.txt"
UNKNOWN_FIXTURE = FIXTURE_DIR / "unknown_syntax.txt"


def _bundle(inspector: Path, *, function: str) -> ValidatedBundle:
    inspector_digest = hashlib.sha256(inspector.read_bytes()).hexdigest()
    digest = "a" * 64
    compile_id = "b" * 64
    manifest = FrontierBundleManifest.model_validate(
        {
            "schema_version": "causal-frontier-bundle.v1",
            "label": "paired",
            "function": function,
            "compile": {
                "id": compile_id,
                "compiler": "mwcc_233_163n",
                "target_build": "GALE01",
                "flags_digest": digest,
                "environment_digest": digest,
                "source_digest": digest,
                "expected_assembly_digest": digest,
            },
            "artifacts": {
                "source": {"path": "candidate.c", "sha256": digest},
                "checkdiff": {"path": "checkdiff.json", "sha256": digest},
                "backend": [
                    {
                        "path": "backend.txt",
                        "sha256": digest,
                        "format": "mwcc-debug-pcdump",
                        "capabilities": (),
                    }
                ],
                "inspector": {"path": inspector.name, "sha256": inspector_digest},
            },
            "producer_versions": {"mwcc_inspect": "mwcc-inspect-text.v1"},
        }
    )
    return ValidatedBundle(
        manifest_path=inspector.parent / "bundle.json",
        manifest=manifest,
        label="paired",
        compile_id=compile_id,
        artifact_paths=MappingProxyType({"inspector": inspector}),
    )


def test_parse_nested_assignment_and_objobject_ownership() -> None:
    text = FIXTURE.read_text()
    fn = parse_inspect_function(text, "mnDiagram_DrawFighterHeaders")
    assert fn is not None
    assignment = next(node for node in fn.enodes if node.opcode == "EASS" and "fighter_id" in node.expression)
    referenced = {fn.objobjects[address].name for address in assignment.referenced_object_addresses}
    assert referenced == {"fighter_id", "@1863"}
    assert fn.objobjects["0x00FEC850"].first_appearance_order == 19
    assert fn.objobjects["0x00FEC850"].address_order == 36
    assert assignment.raw_start < assignment.raw_end
    fighter = fn.objobjects["0x00FEC850"]
    object_span = text.encode()[fighter.raw_start : fighter.raw_end]
    assert b"[19] 0x00FEC850  fighter_id" in object_span
    assert b"[36] 0x00FEC850  fighter_id" in object_span


def test_tree_parents_and_statement_spans_are_preserved() -> None:
    raw = FIXTURE.read_bytes()
    fn = parse_inspect_function(raw.decode(), "mnDiagram_DrawFighterHeaders")
    assert fn is not None
    assert len(fn.statements) == 1
    statement = fn.statements[0]
    root = next(node for node in fn.enodes if node.node_id == statement.root_enode_id)
    fighter_assignment = next(
        node for node in fn.enodes if node.opcode == "EASS" and node.expression == "[fighter_id] = [@1863]"
    )
    fighter_ref = next(
        node
        for node in fn.enodes
        if node.opcode == "EOBJREF" and node.expression == "fighter_id" and node.parent_id is not None
    )
    assert root.parent_id is None
    assert fighter_assignment.depth > root.depth
    assert fighter_ref.parent_id is not None
    assert raw[statement.raw_start : statement.raw_end].startswith(b":16542312")
    assert raw[fighter_assignment.raw_start : fighter_assignment.raw_end].startswith(b"[EASS]")


def test_unknown_inspector_line_is_warning_not_edge() -> None:
    fn = parse_inspect_function(UNKNOWN_FIXTURE.read_text(), "fn_test")
    assert fn is not None
    assert fn.warnings == ("line 6: unsupported inspector syntax: [ENEWFORM] value",)
    assert all(node.opcode != "ENEWFORM" for node in fn.enodes)


def test_unknown_structural_branch_suppresses_known_descendants(tmp_path: Path) -> None:
    text = """\
FUNCTION: fn_test
STATEMENTS (IR):
--------------------------------------------------------------------------------
:42        root
  [EASS] root
    New producer branch:
      [EOBJREF] leaked
        -> ObjObject @ 0x00ABCDEF: leaked (DataType: DLOCAL, Type: int)
    [EINTCONST] 0
"""

    fn = parse_inspect_function(text, "fn_test")

    assert fn is not None
    assert fn.warnings == ("line 6: unsupported inspector syntax: New producer branch:",)
    assert {node.opcode for node in fn.enodes} == {"EASS", "EINTCONST"}
    assert "0x00ABCDEF" not in fn.objobjects
    assert all(not node.referenced_object_addresses for node in fn.enodes)

    inspector = tmp_path / "unknown-branch.txt"
    inspector.write_text(text)
    result = adapt_inspector(_bundle(inspector, function="fn_test"))
    assert all(node.attributes.get("opcode") != "EOBJREF" for node in result.nodes)
    assert all(edge.kind != "enode-references-object" for edge in result.edges)


def test_known_conditional_tree_syntax_is_parsed_without_warnings() -> None:
    text = """\
FUNCTION: fn_test
STATEMENTS (IR):
--------------------------------------------------------------------------------
:7         value
  [ECOND] value
    Condition:
      [EEQU] [left] == [right]
    True branch:
      [EINTCONST] 1
    False branch:
      [EINTCONST] 0
"""

    fn = parse_inspect_function(text, "fn_test")

    assert fn is not None
    assert fn.warnings == ()
    assert {node.opcode for node in fn.enodes} == {"ECOND", "EEQU", "EINTCONST"}


def test_unknown_local_order_row_warns_and_recovers(tmp_path: Path) -> None:
    text = """\
FUNCTION: fn_test
LOCAL VARIABLES (first appearance order, with ObjObject addresses):
--------------------------------------------------------------------------------
  [future] 0x00DEAD00  leaked
  [7] 0x00ABCDEF  kept
================================================================================
"""

    fn = parse_inspect_function(text, "fn_test")

    assert fn is not None
    assert fn.warnings == ("line 4: unsupported inspector syntax: [future] 0x00DEAD00  leaked",)
    assert "0x00DEAD00" not in fn.objobjects
    assert fn.objobjects["0x00ABCDEF"].name == "kept"
    assert fn.objobjects["0x00ABCDEF"].first_appearance_order == 7

    inspector = tmp_path / "unknown-table-row.txt"
    inspector.write_text(text)
    result = adapt_inspector(_bundle(inspector, function="fn_test"))
    assert result.warnings == fn.warnings
    assert all(node.attributes.get("address") != "0x00DEAD00" for node in result.nodes)
    assert any(node.attributes.get("address") == "0x00ABCDEF" for node in result.nodes)


def test_adapter_preserves_explicit_and_derived_confidence() -> None:
    result = adapt_inspector(_bundle(FIXTURE, function="mnDiagram_DrawFighterHeaders"))

    nodes_by_id = {node.record_id: node for node in result.nodes}
    object_node = next(
        node for node in result.nodes if node.kind == "objobject" and node.attributes["name"] == "fighter_id"
    )
    direct_edge = next(
        edge
        for edge in result.edges
        if edge.kind == "enode-references-object"
        and edge.target_id == object_node.record_id
        and nodes_by_id[edge.source_id].attributes["opcode"] == "EOBJREF"
    )
    ancestor_edge = next(
        edge
        for edge in result.edges
        if edge.kind == "enode-references-object"
        and edge.target_id == object_node.record_id
        and nodes_by_id[edge.source_id].attributes["opcode"] == "EASS"
        and nodes_by_id[edge.source_id].attributes["expression"] == "[fighter_id] = [@1863]"
    )
    structural_edges = tuple(edge for edge in result.edges if edge.kind in {"statement-has-enode", "enode-child"})
    assert direct_edge.producer_confidence is Confidence.OBSERVED
    assert direct_edge.adapter_confidence is Confidence.OBSERVED
    assert direct_edge.confidence is Confidence.OBSERVED
    assert ancestor_edge.adapter_confidence is Confidence.DERIVED_UNIQUE
    assert ancestor_edge.confidence is Confidence.DERIVED_UNIQUE
    assert "referenced_object_addresses" not in nodes_by_id[ancestor_edge.source_id].attributes
    assert structural_edges
    assert all(edge.confidence is Confidence.OBSERVED for edge in structural_edges)


def test_objobject_classification_is_separate_and_confidence_capped() -> None:
    bundle = _bundle(FIXTURE, function="mnDiagram_DrawFighterHeaders")
    result = adapt_inspector(bundle)
    raw_objects = {node.attributes["address"]: node for node in result.nodes if node.kind == "objobject"}
    classifications = {
        node.attributes["object_address"]: node for node in result.nodes if node.kind == "objobject-classification"
    }

    fighter = classifications["0x00FEC850"]
    assert fighter.attributes["object_class"] == "named-local"
    assert fighter.producer_confidence is Confidence.OBSERVED
    assert fighter.adapter_confidence is Confidence.DERIVED_UNIQUE
    assert fighter.confidence is Confidence.DERIVED_UNIQUE
    assert fighter.provenance.artifact_sha256 == bundle.manifest.artifacts.inspector.sha256
    assert fighter.provenance.input_record_ids == (raw_objects["0x00FEC850"].record_id,)

    table_only = classifications["0x00FEC8E0"]
    assert table_only.attributes["object_class"] == "ambiguous"
    assert table_only.producer_confidence is Confidence.OBSERVED
    assert table_only.adapter_confidence is Confidence.HEURISTIC
    assert table_only.confidence is Confidence.HEURISTIC
    assert table_only.provenance.input_record_ids == (raw_objects["0x00FEC8E0"].record_id,)
    assert all("object_class" not in node.attributes for node in raw_objects.values())
    assert all("synthetic_name" not in node.attributes for node in raw_objects.values())

    store = InMemoryEvidenceStore()
    store.add_nodes(result.nodes)
    store.add_edges(result.edges)


def test_adapter_does_not_turn_unknown_syntax_into_evidence() -> None:
    result = adapt_inspector(_bundle(UNKNOWN_FIXTURE, function="fn_test"))

    assert result.warnings == ("line 6: unsupported inspector syntax: [ENEWFORM] value",)
    assert all(node.attributes.get("opcode") != "ENEWFORM" for node in result.nodes)


def test_adapter_provenance_uses_original_crlf_byte_offsets(tmp_path: Path) -> None:
    inspector = tmp_path / "inspector.txt"
    raw = (
        b"FUNCTION: fn_test\r\n"
        b"STATEMENTS (IR):\r\n"
        b"--------------------------------------------------------------------------------\r\n"
        b":42        value\r\n"
        b"  [EASS] value\r\n"
    )
    inspector.write_bytes(raw)

    result = adapt_inspector(_bundle(inspector, function="fn_test"))

    enode = next(node for node in result.nodes if node.kind == "enode")
    start = enode.provenance.raw_start
    end = enode.provenance.raw_end
    assert start is not None
    assert end is not None
    assert raw[start:end].startswith(b"[EASS]")
