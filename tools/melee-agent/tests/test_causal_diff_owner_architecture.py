from __future__ import annotations

import ast
from pathlib import Path

from src.mwcc_debug.causal_diff import alignment, differ, object_binding_adapter
from src.mwcc_debug.causal_diff.legacy_ownership import legacy_reachable_records
from tests.owner_certificate_fixtures import (
    graph_with_legacy_and_v2_numeric_collision,
    legacy_roots,
)

CAUSAL_DIFF = Path(__file__).resolve().parents[1] / "src" / "mwcc_debug" / "causal_diff"
DOWNSTREAM_PATHS = tuple(CAUSAL_DIFF / name for name in ("alignment.py", "differ.py", "effects.py", "inference.py"))
FORBIDDEN_IMPORTS = {
    "ObjectBindingEvidence",
    "_OBJECT_BINDING_ADAPTER_TOKEN",
    "proof_complete",
    "exact_owner_path_record",
    "owner_edge_requires_exact_v2",
    "derive_backend_frame_recommendation",
    "bilateral_source_object_records",
}
FORBIDDEN_EDGE_LITERALS = {
    "assembly-anchor-emitted-by-pcode",
    "pcode-operand-lineage",
    "pcode-operand-uses-virtual",
    "object-materializes-virtual",
    "maps-to-allocator-node",
    "object-has-stack-home",
}
REMOVED_ADAPTER_HELPERS = {
    "proof_complete",
    "exact_owner_path_record",
    "owner_edge_requires_exact_v2",
    "derive_backend_frame_recommendation",
    "bilateral_source_object_records",
}
EXPECTED_ADAPTER_EXPORTS = [
    "ObjectBindingAdapterInput",
    "ObjectBindingEvidence",
    "adapt_object_bindings",
    "emit_object_binding_evidence",
]


def _imported_names(tree: ast.AST) -> frozenset[str]:
    return frozenset(
        alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names
    )


def _string_constants(tree: ast.AST) -> frozenset[str]:
    return frozenset(
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _adapter_token_setters(tree: ast.AST) -> frozenset[str]:
    return frozenset(
        function.name
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "object"
            and node.func.attr == "__setattr__"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "_adapter_token"
            for node in ast.walk(function)
        )
    )


def _function_callers(tree: ast.AST, callee: str) -> frozenset[str]:
    return frozenset(
        function.name
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == callee
            for node in ast.walk(function)
        )
    )


def test_downstream_modules_cannot_reconstruct_raw_owner_proof() -> None:
    for path in DOWNSTREAM_PATHS:
        tree = ast.parse(path.read_text())
        assert _imported_names(tree).isdisjoint(FORBIDDEN_IMPORTS)
        assert _string_constants(tree).isdisjoint(FORBIDDEN_EDGE_LITERALS)


def test_all_partial_owner_edge_literals_remain_confined_from_downstream() -> None:
    observed = set()
    for path in DOWNSTREAM_PATHS:
        observed.update(_string_constants(ast.parse(path.read_text())))

    assert len(FORBIDDEN_EDGE_LITERALS) == 6
    assert observed.isdisjoint(FORBIDDEN_EDGE_LITERALS)


def test_legacy_owner_helpers_categorically_reject_v2_records() -> None:
    graph = graph_with_legacy_and_v2_numeric_collision()
    record_ids, edge_ids = legacy_reachable_records(graph, legacy_roots(graph))
    edges = tuple(graph.store.get_edge(record_id) for record_id in edge_ids)
    assert record_ids
    assert all(edge is not None for edge in edges)
    assert all(edge.provenance.parser != "mwcc-retro-backend-trace.v2" for edge in edges if edge is not None)
    assert not any("capture_run_id" in edge.attributes for edge in edges if edge is not None)


def test_diagnostic_adapter_exports_no_owner_proof_helpers() -> None:
    assert REMOVED_ADAPTER_HELPERS.isdisjoint(object_binding_adapter.__all__)
    assert not any(hasattr(object_binding_adapter, name) for name in REMOVED_ADAPTER_HELPERS)


def test_only_verified_bundle_adapter_sets_owner_authority_token() -> None:
    tree = ast.parse((CAUSAL_DIFF / "object_binding_adapter.py").read_text())

    assert _adapter_token_setters(tree) == {"adapt_object_bindings"}
    assert object_binding_adapter.__all__ == EXPECTED_ADAPTER_EXPORTS
    assert "_OBJECT_BINDING_ADAPTER_TOKEN" not in object_binding_adapter.__all__
    assert "emit_trusted_object_binding_evidence_for_test" not in object_binding_adapter.__all__
    assert not hasattr(
        object_binding_adapter,
        "emit_trusted_object_binding_evidence_for_test",
    )


def test_only_public_alignment_boundary_seals_owner_relations() -> None:
    tree = ast.parse((CAUSAL_DIFF / "alignment.py").read_text())

    assert _function_callers(tree, "_seal_owner_alignment_record") == {"build_role_comparisons"}
    assert not _function_callers(tree, "_seal_owner_alignment_record") & {
        "_owner_correspondence",
        "_owner_abstention",
    }
    assert "_OWNER_ALIGNMENT_AUTHORITY" not in alignment.__all__
    assert "_seal_owner_alignment_record" not in alignment.__all__


def test_only_public_differencer_boundary_seals_owner_deltas() -> None:
    tree = ast.parse((CAUSAL_DIFF / "differ.py").read_text())

    assert _function_callers(tree, "_seal_owner_delta_record") == {"diff_frontiers"}
    assert "_owner_state_deltas" not in _function_callers(
        tree,
        "_seal_owner_delta_record",
    )
    assert "_OWNER_DELTA_AUTHORITY" not in differ.__all__
    assert "_seal_owner_delta_record" not in differ.__all__
