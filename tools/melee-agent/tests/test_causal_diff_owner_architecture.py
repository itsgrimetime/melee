from __future__ import annotations

import ast
from pathlib import Path

from src.mwcc_debug.causal_diff import object_binding_adapter
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


def _imported_names(tree: ast.AST) -> frozenset[str]:
    return frozenset(
        alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names
    )


def _string_constants(tree: ast.AST) -> frozenset[str]:
    return frozenset(
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_downstream_modules_cannot_reconstruct_raw_owner_proof() -> None:
    for path in DOWNSTREAM_PATHS:
        tree = ast.parse(path.read_text())
        assert _imported_names(tree).isdisjoint(FORBIDDEN_IMPORTS)
        assert _string_constants(tree).isdisjoint(FORBIDDEN_EDGE_LITERALS)


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
