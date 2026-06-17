from __future__ import annotations

import textwrap

import pytest

from src.search.directed.window_order_source import (
    generate_window_order_source_probes,
)


def test_window_order_probe_hoists_unique_source_local() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int guard;
            int dst_iter;
            idx = seed;
            guard = seed;
            dst_iter = idx;
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 34,
            "order_move": ["before", 43],
            "move_distance": 5,
            "perturbed_reg": 25,
        }],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 8},
        },
        max_probes=4,
    )
    if not probes:
        pytest.skip("tree-sitter unavailable")

    probe = probes[0]
    assert probe.operator == "window-order-source-steering"
    assert probe.provenance["kind"] == "window-order-fallback-source-move"
    assert probe.provenance["lead"]["target_ig"] == 34
    assert probe.provenance["moved_local"] == "dst_iter"
    assert probe.source_text.index("dst_iter = idx;") < probe.source_text.index(
        "guard = seed;"
    )


def test_window_order_probe_sinks_unique_source_local() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int idx;
            int guard;
            int dst_iter;
            idx = seed;
            dst_iter = idx;
            guard = seed;
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{
            "target_ig": 34,
            "order_move": ["after", 43],
            "move_distance": 3,
            "perturbed_reg": 25,
        }],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 7},
        },
        max_probes=4,
    )
    if not probes:
        pytest.skip("tree-sitter unavailable")

    assert probes[0].source_text.index("guard = seed;") < probes[0].source_text.index(
        "dst_iter = idx;"
    )


def test_window_order_probe_requires_source_attribution() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={},
    )

    assert probes == []


def test_window_order_probe_skips_ambiguous_source_local() -> None:
    source = textwrap.dedent("""\
        void fn(int seed)
        {
            int dst_iter;
            dst_iter = seed;
            if (seed != 0) {
                dst_iter = seed;
            }
        }
    """)

    probes = generate_window_order_source_probes(
        source,
        function="fn",
        fallback_leads=[{"target_ig": 34, "order_move": ["before", 43]}],
        source_attributions={
            34: {"kind": "local", "name": "dst_iter", "source_line": 4},
        },
    )
    if probes:
        pytest.fail("ambiguous source attribution produced a source probe")
