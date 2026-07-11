"""Read-only orchestration for causal frontier comparison."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .alignment import align_anchor, build_role_comparisons
from .asm_adapter import adapt_checkdiff
from .backend_adapter import adapt_backends
from .bundles import ValidatedBundle, load_bundle, validate_bundle_pair, validate_capability_union
from .differ import diff_frontiers
from .effects import derive_effects
from .frame_adapter import adapt_frame
from .graph import FrontierGraph, build_frontier_graph
from .inference import CausalDiffReport, build_report
from .inspect_adapter import adapt_inspector
from .source_adapter import adapt_source
from .store import EvidenceStore, InMemoryEvidenceStore


@dataclass(frozen=True, slots=True)
class CausalDiffOptions:
    function: str
    frontiers: tuple[tuple[str, Path], tuple[str, Path]]
    retail_offset: int
    assertions: tuple[str, ...] = ()
    evidence_depth: int = 4


def _load_and_validate_pair(
    options: CausalDiffOptions,
) -> tuple[ValidatedBundle, ValidatedBundle]:
    if len(options.frontiers) != 2:
        raise ValueError("causal diff requires exactly two frontiers")
    bundles = tuple(load_bundle(path, cli_label=label, function=options.function) for label, path in options.frontiers)
    return validate_bundle_pair(bundles[0], bundles[1])


def run_causal_diff(
    options: CausalDiffOptions,
    *,
    store_factory: Callable[[], EvidenceStore] = InMemoryEvidenceStore,
) -> CausalDiffReport:
    """Build a causal report exclusively from caller-supplied artifacts."""

    if options.retail_offset < 0:
        raise ValueError("retail offset must be nonnegative")
    if not 1 <= options.evidence_depth <= 8:
        raise ValueError("evidence depth must be between 1 and 8")

    bundles = _load_and_validate_pair(options)
    store = store_factory()
    graphs: list[FrontierGraph] = []
    for bundle in bundles:
        checkdiff = adapt_checkdiff(bundle)
        backend = adapt_backends(bundle)
        inspector = adapt_inspector(bundle)
        frame = adapt_frame(bundle, checkdiff, backend)
        source = adapt_source(bundle)
        validate_capability_union(
            bundle,
            backend.result.verified_capabilities | inspector.verified_capabilities,
        )
        graphs.append(
            build_frontier_graph(
                bundle,
                store,
                checkdiff,
                backend,
                inspector,
                frame,
                source,
            )
        )

    graph_pair = (graphs[0], graphs[1])
    alignment = align_anchor(graph_pair, options.retail_offset, options.assertions)
    comparisons = build_role_comparisons(alignment, graph_pair)
    effects = derive_effects(alignment, graph_pair)
    deltas = diff_frontiers(graph_pair, comparisons)
    all_comparisons = comparisons + deltas
    store.add_comparisons(all_comparisons)
    return build_report(
        graph_pair,
        effects,
        all_comparisons,
        evidence_depth=options.evidence_depth,
    )


__all__ = ["CausalDiffOptions", "run_causal_diff"]
