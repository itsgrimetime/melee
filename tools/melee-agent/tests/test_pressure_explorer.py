"""Tests for lifetime/layout pressure-delta attribution."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.cli import debug as debug_cli
from src.mwcc_debug.pressure_explorer import (
    PressureDelta,
    compare_pressure_signatures,
    generate_frame_directed_probes,
    generate_lifetime_layout_probes,
    generate_source_lifetime_probes,
    pressure_signature_from_pcdump,
    scan_frame_local_dematerialization_probes,
)

runner = CliRunner()


BASELINE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x08 SPILLED
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 1 1 0x00
          interferers: 40=r26
        1 40 r26 1 1 0x00
          interferers: 37=r25
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-56(r1)
        stfd f31,48(r1)
        stmw r25,24(r1)
        blr
""")


CANDIDATE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 0 0 0x00
          interferers:
        1 40 r25 0 0 0x00
          interferers:
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-48(r1)
        stmw r26,24(r1)
        blr
""")


SOURCE = textwrap.dedent("""\
    void fn_80000000(int flag, int x) {
        int i;
        int temp = x + 1;
        int result;
        int late;
        result = temp;
        sink(temp);
        late = temp + flag;
        sink(late);
        for (i = 0; i < 3; i++) {
            if (flag && result) {
                sink(result + i, x + flag);
            }
        }
    }
""")


def test_pressure_delta_reports_frame_saved_spill_and_interference() -> None:
    baseline = pressure_signature_from_pcdump(
        BASELINE,
        "fn_80000000",
        pairs=[(37, 40)],
    )
    candidate = pressure_signature_from_pcdump(
        CANDIDATE,
        "fn_80000000",
        pairs=[(37, 40)],
    )

    delta = compare_pressure_signatures(baseline, candidate)

    assert baseline.frame_size == 56
    assert candidate.frame_size == 48
    assert delta.frame_delta == -8
    assert delta.saved_removed == ("f31", "r25")
    assert delta.spill_removed == (37,)
    assert delta.interference_removed == ((37, 40),)
    assert delta.target_pairs[0].before.colorgraph_interference is True
    assert delta.target_pairs[0].after.colorgraph_interference is False


def test_pressure_signature_reports_spilled_markers_across_simplify_classes() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        SIMPLIFY GRAPH (class=1, n_colors=29, n_class_regs=45)
          iter ig_idx degree arraySize flags notes
            0 37 1 1 0x08 SPILLED
            1 40 1 1 0x08 SPILLED
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=0)
          iter ig_idx phys degree nIntfr flags
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            blr
    """)

    signature = pressure_signature_from_pcdump(pcdump, "fn_80000000", class_id=0)

    assert signature.spill_set == (37, 40)


def test_pressure_signature_rejects_missing_function() -> None:
    missing = BASELINE.replace("Starting function fn_80000000", "Starting function other")

    try:
        pressure_signature_from_pcdump(missing, "fn_80000000")
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing function should be rejected")


def test_generate_lifetime_layout_probes_includes_core_operator_families() -> None:
    probes = generate_lifetime_layout_probes(SOURCE, "fn_80000000", max_probes=30)
    operators = {probe.operator for probe in probes}

    assert "temp-introduction" in operators
    assert "temp-removal" in operators
    assert "type-width" in operators
    assert "declaration-use-distance" in operators
    assert "early-guard-return" in operators
    assert "block-scope" in operators
    assert "loop-init" in operators
    assert "condition-nesting" in operators
    assert "call-argument-tempization" in operators
    assert all("fn_80000000" in probe.source_text for probe in probes)


def _for_condition_line(source: str) -> str:
    return next(line for line in source.splitlines() if line.strip().startswith("for ("))


def test_source_lifetime_for_condition_field_reload_probe() -> None:
    source = textwrap.dedent("""\
        s32 fn_803ACD58(CardState* state)
        {
            s32 i;
            s32 size;
            for (i = 0; size = state->x8, i < (0x2F + state->x24 + size) / size; i++) {
                sink(i, size);
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_803ACD58",
        max_probes=8,
    )

    by_operator = {probe.operator: probe for probe in probes}
    assert "for-condition-field-reload" in by_operator
    probe = by_operator["for-condition-field-reload"]
    assert "size = state->x8" not in _for_condition_line(probe.source_text)
    assert probe.provenance["kind"] == "for-condition-field-reload"
    assert any(row["operator"] == "for-condition-field-reload" for row in summaries)


def test_source_lifetime_repeated_helper_result_reuse_probe() -> None:
    source = textwrap.dedent("""\
        s32 fn_803AC7DC(CardState* state, s32 i)
        {
            s32 total = 0;
            s32 extra = 0;
            total += fn_803AC634(state, i);
            extra = fn_803AC634(state, i);
            return total + extra;
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_803AC7DC",
        max_probes=8,
    )

    probe = next(
        probe
        for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
    )
    assert "s32 ll_probe_helper_result_0 = (s32) fn_803AC634(state, i);" in (
        probe.source_text
    )
    assert probe.source_text.count("fn_803AC634(state, i)") == 1
    assert "total += ll_probe_helper_result_0;" in probe.source_text
    assert "extra = ll_probe_helper_result_0;" in probe.source_text
    assert probe.provenance["callee"] == "fn_803AC634"


def test_source_lifetime_repeated_helper_result_reuse_supports_seed_style_compare_update() -> None:
    source = textwrap.dedent("""\
        s32 fn_803AC7DC(CardState* state, s32 i)
        {
            s32 total = 0;
            s32 extra = 0;
            total += fn_803AC634(state, i);
            if (extra < (s32) fn_803AC634(state, i)) {
                extra = (s32) fn_803AC634(state, i);
            }
            return total + extra;
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_803AC7DC",
        max_probes=8,
    )

    probe = next(
        probe
        for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
    )
    assert "s32 ll_probe_helper_result_0 = (s32) fn_803AC634(state, i);" in (
        probe.source_text
    )
    assert "total += ll_probe_helper_result_0;" in probe.source_text
    assert "if (extra < ll_probe_helper_result_0) {" in probe.source_text
    assert "extra = ll_probe_helper_result_0;" in probe.source_text
    assert probe.source_text.count("fn_803AC634(state, i)") == 1


def test_source_lifetime_repeated_helper_result_reuse_supports_same_tu_scalar_helper() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 x)
        {
            return x + 1;
        }

        s32 fn_80000000(s32 x)
        {
            s32 total = 0;
            total += helper(x);
            total = helper(x);
            return total;
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe
        for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
    )
    assert "s32 ll_probe_helper_result_0 = helper(x);" in probe.source_text
    assert "total += ll_probe_helper_result_0;" in probe.source_text
    assert "total = ll_probe_helper_result_0;" in probe.source_text


def test_source_lifetime_repeated_helper_result_reuse_rejects_same_tu_state_reader() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(State* state)
        {
            return state->x;
        }

        s32 fn_80000000(State* state)
        {
            s32 total = 0;
            total += helper(state);
            mutate(state);
            total = helper(state);
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-supported-for-reuse",
        "same-tu-helper-reads-mutable-param",
    }


def test_source_lifetime_repeated_helper_result_reuse_rejects_same_tu_deref_reader() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32* ptr)
        {
            return *ptr;
        }

        s32 fn_80000000(s32* ptr)
        {
            s32 total = 0;
            total += helper(ptr);
            mutate(ptr);
            total = helper(ptr);
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-supported-for-reuse",
        "same-tu-helper-reads-mutable-param",
    }


def test_source_lifetime_repeated_helper_result_reuse_rejects_same_tu_offset_deref_reader() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32* ptr, s32 i)
        {
            return *(ptr + i);
        }

        s32 fn_80000000(s32* ptr, s32 i)
        {
            s32 total = 0;
            total += helper(ptr, i);
            mutate(ptr);
            total = helper(ptr, i);
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-supported-for-reuse",
        "same-tu-helper-reads-mutable-param",
    }


def test_source_lifetime_repeated_helper_result_reuse_supports_same_tu_unsigned_helper() -> None:
    source = textwrap.dedent("""\
        static inline u32 helper(u32 x)
        {
            return x;
        }

        u32 fn_80000000(u32 x)
        {
            u32 total = 0;
            total += helper(x);
            total = helper(x);
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    del summaries
    probe = next(
        probe
        for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
    )
    assert "u32 ll_probe_helper_result_0 = helper(x);" in probe.source_text
    assert "total += ll_probe_helper_result_0;" in probe.source_text
    assert "total = ll_probe_helper_result_0;" in probe.source_text


def test_source_lifetime_repeated_helper_result_reuse_supports_unsigned_int_helper() -> None:
    source = textwrap.dedent("""\
        static inline unsigned int helper(unsigned int x)
        {
            return x;
        }

        unsigned int fn_80000000(unsigned int x)
        {
            unsigned int total = 0;
            total += helper(x);
            total = helper(x);
            return total;
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe
        for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
    )
    assert "unsigned int ll_probe_helper_result_0 = helper(x);" in probe.source_text
    assert "total += ll_probe_helper_result_0;" in probe.source_text
    assert "total = ll_probe_helper_result_0;" in probe.source_text


def test_source_lifetime_repeated_helper_result_reuse_rejects_same_tu_pointer_helper() -> None:
    source = textwrap.dedent("""\
        static inline Node* helper(Node** table, s32 i)
        {
            return table[i];
        }

        Node* fn_80000000(Node** table, s32 i)
        {
            Node* left;
            Node* right;
            left = helper(table, i);
            right = helper(table, i);
            return left ? left : right;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "helper-return-type-unsafe",
        "callee-not-supported-for-reuse",
    }


def test_source_lifetime_repeated_helper_result_reuse_uses_unique_temp_name() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 ll_probe_helper_result_0;
            s32 total = 0;
            total += fn_803AC634(state, i);
            total = fn_803AC634(state, i);
            return total + ll_probe_helper_result_0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    operators = {probe.operator for probe in probes}
    if "repeated-helper-result-reuse" in operators:
        probe = next(
            probe
            for probe in probes
            if probe.operator == "repeated-helper-result-reuse"
        )
        assert "s32 ll_probe_helper_result_1 = (s32) fn_803AC634(state, i);" in (
            probe.source_text
        )
        assert "ll_probe_helper_result_0 = (s32) fn_803AC634(state, i);" not in (
            probe.source_text
        )
    else:
        blocked = [
            row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
        ]
        assert blocked
        assert blocked[0]["blocker"] is not None


def test_source_lifetime_helper_result_dematerialize_probe() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 result;
            result = fn_803AC634(state, i);
            sink(result);
            return result;
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes if probe.operator == "helper-result-dematerialize"
    )
    assert "result = fn_803AC634(state, i);" not in probe.source_text
    assert "sink(fn_803AC634(state, i));" in probe.source_text
    assert "return fn_803AC634(state, i);" in probe.source_text


def test_source_lifetime_helper_result_dematerialize_preserves_assignment_cast() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 result;
            result = (s32) fn_803AC634(state, i);
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    operators = {probe.operator for probe in probes}
    if "helper-result-dematerialize" in operators:
        probe = next(
            probe
            for probe in probes
            if probe.operator == "helper-result-dematerialize"
        )
        assert "sink((s32) fn_803AC634(state, i));" in probe.source_text
        assert "return (s32) fn_803AC634(state, i);" in probe.source_text
    else:
        blocked = [
            row for row in summaries if row["operator"] == "helper-result-dematerialize"
        ]
        assert blocked
        assert blocked[0]["blocker"] is not None


def test_source_lifetime_helper_result_dematerialize_rejects_same_tu_pointer_helper() -> None:
    source = textwrap.dedent("""\
        static inline Node* helper(Node** table, s32 i)
        {
            return table[i];
        }

        Node* fn_80000000(Node** table, s32 i)
        {
            Node* result;
            result = helper(table, i);
            i++;
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "helper-return-type-unsafe",
        "callee-not-supported-for-dematerialize",
    }


def test_source_lifetime_helper_result_dematerialize_rejects_same_tu_state_reader() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(State* state)
        {
            return state->x;
        }

        s32 fn_80000000(State* state)
        {
            s32 result;
            result = helper(state);
            mutate(state);
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-supported-for-dematerialize",
        "same-tu-helper-reads-mutable-param",
    }


def test_source_lifetime_helper_result_dematerialize_rejects_same_tu_deref_reader() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32* ptr)
        {
            return *ptr;
        }

        s32 fn_80000000(s32* ptr)
        {
            s32 result;
            result = helper(ptr);
            mutate(ptr);
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-supported-for-dematerialize",
        "same-tu-helper-reads-mutable-param",
    }


def test_source_lifetime_helper_result_dematerialize_rejects_same_tu_offset_deref_reader() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32* ptr, s32 i)
        {
            return *(ptr + i);
        }

        s32 fn_80000000(s32* ptr, s32 i)
        {
            s32 result;
            result = helper(ptr, i);
            mutate(ptr);
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-supported-for-dematerialize",
        "same-tu-helper-reads-mutable-param",
    }


def test_source_lifetime_helper_result_dematerialize_supports_unsigned_int_helper() -> None:
    source = textwrap.dedent("""\
        static inline unsigned int helper(unsigned int x)
        {
            return x;
        }

        unsigned int fn_80000000(unsigned int x)
        {
            unsigned int result;
            result = helper(x);
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    operators = {probe.operator for probe in probes}
    if "helper-result-dematerialize" in operators:
        probe = next(
            probe
            for probe in probes
            if probe.operator == "helper-result-dematerialize"
        )
        assert "sink(helper(x));" in probe.source_text
        assert "return helper(x);" in probe.source_text
    else:
        blocked = [
            row for row in summaries if row["operator"] == "helper-result-dematerialize"
        ]
        assert blocked
        assert blocked[0]["blocker"] != "helper-return-type-unsafe"


def test_source_lifetime_simple_helper_inline_body_probe() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(CardState* state, s32 i)
        {
            return state->x4C[i] + 1;
        }

        s32 fn_80000000(CardState* state, s32 i)
        {
            return helper(state, i);
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes if probe.operator == "simple-helper-inline-body"
    )
    assert "return state->x4C[i] + 1;" in probe.source_text
    assert "return helper(state, i);" not in probe.source_text


def test_source_lifetime_simple_helper_inline_body_rejects_preprocessor_guarded_call_site() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 x)
        {
            return x + 1;
        }

        s32 fn_80000000(s32 x)
        {
        #if FOO
            return helper(x);
        #endif
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "simple-helper-inline-body" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "simple-helper-inline-body"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "preprocessor-region-unsafe"


def test_source_lifetime_rejects_unsafe_helper_call_rewrites() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 a = mutating_helper(state, i);
            s32 b = mutating_helper(state, i);
            return a + b;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-read-only",
        "callee-not-supported-for-reuse",
    }


def test_source_lifetime_repeated_helper_result_reuse_stays_within_safe_region() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
            if (flag) {
                sink(fn_803AC634(state, i));
            } else {
                sink(fn_803AC634(state, i));
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "cross-statement-region"


def test_source_lifetime_repeated_helper_result_reuse_rejects_parent_and_nested_if_occurrences() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
            sink(fn_803AC634(state, i));
            if (flag) {
                sink(fn_803AC634(state, i));
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "cross-statement-region"


def test_source_lifetime_repeated_helper_result_reuse_rejects_parent_and_nested_while_occurrences() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
            sink(fn_803AC634(state, i));
            while (flag) {
                sink(fn_803AC634(state, i));
                flag = 0;
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "cross-statement-region"


def test_source_lifetime_repeated_helper_result_reuse_rejects_parent_and_nested_if_occurrences() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
            sink(fn_803AC634(state, i));
            if (flag) {
                sink(fn_803AC634(state, i));
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "cross-statement-region"


def test_source_lifetime_repeated_helper_result_reuse_rejects_parent_and_nested_while_occurrences() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
            sink(fn_803AC634(state, i));
            while (flag) {
                sink(fn_803AC634(state, i));
                flag = 0;
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "cross-statement-region"


def test_source_lifetime_repeated_helper_result_reuse_rejects_mixed_declarations() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            setup();
            sink(fn_803AC634(state, i));
            sink(fn_803AC634(state, i));
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "mixed-declaration-c89-unsafe"


def test_source_lifetime_repeated_helper_result_reuse_rejects_arg_identifier_mutation() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 total = 0;
            total += fn_803AC634(state, i);
            i++;
            total = fn_803AC634(state, i);
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "helper-arg-mutation-between-uses"


def test_source_lifetime_repeated_helper_result_reuse_rejects_member_arg_mutation() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 total = 0;
            total += fn_803AC634(state->x4C[i], i);
            state->x4C[i] = 0;
            total = fn_803AC634(state->x4C[i], i);
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "helper-arg-mutation-between-uses"


def test_source_lifetime_repeated_helper_result_reuse_rejects_descendant_member_arg_mutation() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 total = 0;
            total += fn_803AC634(state->x4C[i], i);
            state->x4C[i].x = 0;
            total = fn_803AC634(state->x4C[i], i);
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "helper-arg-mutation-between-uses"


def test_source_lifetime_simple_helper_inline_body_parenthesizes_non_atomic_actuals() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 value)
        {
            return value * 2;
        }

        s32 fn_80000000(s32 x)
        {
            return helper(x + 1);
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes if probe.operator == "simple-helper-inline-body"
    )
    assert "return (x + 1) * 2;" in probe.source_text
    assert "return x + 1 * 2;" not in probe.source_text


def test_source_lifetime_simple_helper_inline_body_substitutes_args_simultaneously() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 a, s32 b)
        {
            return a - b;
        }

        s32 fn_80000000(s32 a, s32 b)
        {
            return helper(b, a);
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes if probe.operator == "simple-helper-inline-body"
    )
    assert "return b - a;" in probe.source_text
    assert "return a - a;" not in probe.source_text


def test_source_lifetime_simple_helper_inline_body_supports_assign_then_return_local() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 x)
        {
            s32 tmp;
            tmp = x + 1;
            return tmp;
        }

        s32 fn_80000000(s32 x)
        {
            return helper(x);
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes if probe.operator == "simple-helper-inline-body"
    )
    assert "return x + 1;" in probe.source_text
    assert "return helper(x);" not in probe.source_text


def test_source_lifetime_simple_helper_inline_body_wraps_embedded_expression() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 value)
        {
            return value + 1;
        }

        s32 fn_80000000(s32 x)
        {
            return 2 * helper(x);
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes if probe.operator == "simple-helper-inline-body"
    )
    assert "return 2 * (x + 1);" in probe.source_text
    assert "return 2 * x + 1;" not in probe.source_text


def test_source_lifetime_simple_helper_inline_body_rejects_indirect_call_helper_body() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 (*cb)(s32), s32 x)
        {
            return (*cb)(x);
        }

        s32 fn_80000000(s32 (*cb)(s32), s32 x)
        {
            return helper(cb, x);
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "simple-helper-inline-body" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "simple-helper-inline-body"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "helper-body-too-complex"


def test_source_lifetime_read_only_rewrites_reject_parenthesized_indirect_call_helper_body() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(s32 (*fnptr)(s32), s32 x)
        {
            return ((fnptr))(x);
        }

        s32 fn_80000000(s32 (*fnptr)(s32), s32 x)
        {
            s32 total = 0;
            total += helper(fnptr, x);
            if (total < helper(fnptr, x)) {
                total = helper(fnptr, x);
            }
            return total;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] in {
        "callee-not-read-only",
        "callee-not-supported-for-reuse",
    }


def test_source_lifetime_repeated_helper_result_reuse_rejects_case_arm_declaration() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 kind)
        {
            switch (kind) {
            case 1:
                sink(fn_803AC634(state, i));
                sink(fn_803AC634(state, i));
                break;
            default:
                break;
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "case-arm-declaration-unsafe"


def test_source_lifetime_repeated_helper_result_reuse_allows_block_wrapped_case_arm() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 kind)
        {
            switch (kind) {
            case 1: {
                sink(fn_803AC634(state, i));
                sink(fn_803AC634(state, i));
                break;
            }
            default:
                break;
            }
            return 0;
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe
        for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
    )
    assert "case 1: {\n        s32 ll_probe_helper_result_0 = (s32) fn_803AC634(state, i);\n" in (
        probe.source_text
    )
    assert "sink(ll_probe_helper_result_0);" in probe.source_text


def test_source_lifetime_repeated_helper_result_reuse_rejects_same_line_case_label() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag) {
         switch (flag) { case 1:
            sink(fn_803AC634(state, i));
            sink(fn_803AC634(state, i));
            break;
         }
         return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "case-arm-declaration-unsafe"


def test_source_lifetime_repeated_helper_result_reuse_rejects_plain_label_declaration() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
        retry:
            sink(fn_803AC634(state, i));
            sink(fn_803AC634(state, i));
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "label-declaration-unsafe"


def test_source_lifetime_repeated_helper_result_reuse_rejects_condition_only_anchor() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            if (fn_803AC634(state, i)) {
                sink(i);
            }
            if (fn_803AC634(state, i)) {
                sink(state);
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "unsupported-call-site-shape"


def test_source_lifetime_repeated_helper_result_rejects_unsupported_later_occurrence_shape() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            sink(fn_803AC634(state, i));
            if (fn_803AC634(state, i)) {
                sink(i);
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "unsupported-call-site-shape"


def test_source_lifetime_repeated_helper_result_rejects_short_circuit_condition_occurrence() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
            if (flag && fn_803AC634(state, i)) {
                sink(fn_803AC634(state, i));
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "unsupported-call-site-shape"


def test_source_lifetime_repeated_helper_result_rejects_loop_condition_occurrence() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 extra = 0;
            while (extra < (s32) fn_803AC634(state, i)) {
                extra = (s32) fn_803AC634(state, i);
                break;
            }
            return extra;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "unsupported-call-site-shape"


def test_source_lifetime_repeated_helper_result_rejects_short_circuit_assignment_and_return() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i, s32 flag)
        {
            s32 total;
            total = flag && fn_803AC634(state, i);
            return flag && fn_803AC634(state, i);
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "unsupported-call-site-shape"


def test_source_lifetime_repeated_helper_result_reuse_rejects_same_line_condition_anchor() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i) {
         if (fn_803AC634(state, i)) sink(1);
         if (fn_803AC634(state, i)) sink(2);
         return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "unsupported-call-site-shape"


def test_source_lifetime_rejects_comma_operator_actuals() -> None:
    inline_source = textwrap.dedent("""\
        static inline s32 helper(s32 value)
        {
            return value + 1;
        }

        s32 fn_80000000(s32 x, s32 y)
        {
            return helper((x, y));
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        inline_source,
        "fn_80000000",
        max_probes=8,
    )

    assert "simple-helper-inline-body" not in {probe.operator for probe in probes}
    inline_blocked = [
        row for row in summaries if row["operator"] == "simple-helper-inline-body"
    ]
    assert inline_blocked
    assert inline_blocked[0]["blocker"] == "helper-call-args-unsafe"

    dematerialize_source = textwrap.dedent("""\
        s32 fn_80000000(s32 x, s32 y)
        {
            s32 result;
            result = fn_803AC634((x, y));
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        dematerialize_source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    demat_blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert demat_blocked
    assert demat_blocked[0]["blocker"] == "helper-call-args-unsafe"


def test_source_lifetime_helper_result_dematerialize_rejects_arg_identifier_mutation() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 result;
            result = fn_803AC634(state, i);
            i++;
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "helper-arg-mutation-between-uses"


def test_source_lifetime_helper_result_dematerialize_rejects_element_arg_mutation() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(s32* arr, s32 i)
        {
            s32 result;
            result = fn_803AC634(arr[i], i);
            arr[i] = 0;
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "helper-arg-mutation-between-uses"


def test_source_lifetime_helper_result_dematerialize_rejects_descendant_element_arg_mutation() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(Node* arr, s32 i)
        {
            s32 result;
            result = fn_803AC634(arr[i], i);
            arr[i].x = 0;
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "helper-result-dematerialize" not in {probe.operator for probe in probes}
    blocked = [
        row for row in summaries if row["operator"] == "helper-result-dematerialize"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "helper-arg-mutation-between-uses"


def test_source_lifetime_preserves_generic_lifetime_layout_fallback() -> None:
    probes, summaries = generate_source_lifetime_probes(
        SOURCE,
        "fn_80000000",
        max_probes=8,
    )

    assert "temp-introduction" in {probe.operator for probe in probes}
    assert {row["operator"] for row in summaries} == {
        "for-condition-field-reload",
        "repeated-helper-result-reuse",
        "helper-result-dematerialize",
        "simple-helper-inline-body",
    }


def test_generate_frame_directed_probes_materializes_frame_levers() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(HSD_CObj* cobj, int arg1, int arg2)
        {
            f32 far_val;
            f32 bottom;

            far_val = 2.0f;
            bottom = (f32) arg2;
            setup();
            HSD_CObjSetFar(cobj, far_val);
            HSD_CObjSetOrtho(cobj, 0.0f, bottom, 0.0f, (f32) arg1);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 152},
        target_frame={"frame_size": 144, "unused_ranges": []},
        max_probes=10,
    )
    by_operator = {probe.operator: probe for probe in probes}

    direct = by_operator["frame-direct-literal-at-final-fp-call"]
    assert "HSD_CObjSetFar(cobj, 2.0f);" in direct.source_text
    assert "far_val = 2.0f;" not in direct.source_text

    split = by_operator["frame-split-fp-const-lifetime"]
    assert "setup();\n    far_val = 2.0f;\n    HSD_CObjSetFar" in split.source_text

    scratch = by_operator["frame-magic-scratch-relocation"]
    assert (
        "HSD_CObjSetFar(cobj, far_val);\n"
        "    bottom = (f32) arg2;\n"
        "    HSD_CObjSetOrtho"
    ) in scratch.source_text


def test_temp_introduction_skips_initialized_decl_before_later_decl() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, u8 (*arg1)[2])
        {
            if (fp->x594_b4) {
                int idx = (*arg1)[1];
                FigaTree*** trees = fp->ft_data->x2C->x10;
                sink(idx, trees);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)

    assert "temp-introduction" not in {probe.operator for probe in probes}


def test_condition_nesting_skips_if_else_chain() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int kind, int flag)
        {
            bool reload;
            if (kind != 1 && kind != 2) {
                reload = false;
            } else if (!flag) {
                reload = true;
            }
            if (reload) {
                sink();
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)

    assert "condition-nesting" not in {probe.operator for probe in probes}


def test_block_scope_probe_keeps_local_uses_inside_block() -> None:
    source = textwrap.dedent("""\
        void grGreatBay_801F5460(Ground_GObj* gobj)
        {
            HSD_JObj* jobj = gobj->hsd_obj;
            Ground* gp = GET_GROUND(gobj);

            Ground_801C2ED0(jobj, gp->map_id);
            gp->xC_callback = NULL;
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "grGreatBay_801F5460",
        max_probes=20,
    )
    probe = next(probe for probe in probes if probe.operator == "block-scope")
    fn = probe.source_text

    assert "    }\n\n    Ground_801C2ED0" not in fn
    block_start = fn.index("    {\n")
    block_end = fn.rindex("    }\n}")
    assert block_start < fn.index("Ground_801C2ED0") < block_end
    assert block_start < fn.index("gp->xC_callback") < block_end


def test_block_scope_probe_does_not_duplicate_wrapped_lines() -> None:
    probes = generate_lifetime_layout_probes(SOURCE, "fn_80000000", max_probes=20)
    probe = next(probe for probe in probes if probe.operator == "block-scope")

    assert probe.source_text.count("int i;") == 1
    assert probe.source_text.count("int temp = x + 1;") == 1


def test_block_scope_probe_skips_region_that_crosses_shallower_else() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int kind, int flag)
        {
            if (kind == 0) {
                int anim_id = get_anim();
                if (anim_id == 1) {
                    sink(anim_id);
                }
            } else if (flag) {
                int anim_id = get_other_anim();
                sink(anim_id);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)

    assert "block-scope" not in {probe.operator for probe in probes}


def test_declaration_use_distance_probe_moves_plain_decl_to_first_use() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag, int x)
        {
            int late;
            int temp = x + 1;
            sink(temp);
            late = temp + flag;
            sink(late);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(
        probe for probe in probes if probe.operator == "declaration-use-distance"
    )
    fn = probe.source_text

    assert "    int late;\n    int temp = x + 1;" not in fn
    assert "    {\n        int late;\n        late = temp + flag;" in fn
    assert fn.index("int late;") > fn.index("sink(temp);")


def test_declaration_use_distance_skips_use_that_crosses_shallower_else() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int cond, int b34)
        {
            int teammate_slot;
            if (cond) {
                if (b34 == 1) {
                    teammate_slot = get_slot();
                    sink(teammate_slot);
                } else if (1) {
                    sink(0);
                }
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)

    assert "declaration-use-distance" not in {probe.operator for probe in probes}


def test_declaration_use_distance_keeps_later_uses_inside_moved_block() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            sink(flag);
            count = 0;
            if (flag) {
                count++;
            }

            if (count != 0) {
                sink(count);
            }
            done();
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(
        probe for probe in probes if probe.operator == "declaration-use-distance"
    )
    fn = probe.source_text

    assert "    }\n\n    if (count != 0)" not in fn
    block_start = fn.index("    {\n        int count;")
    block_end = fn.index("    }\n    done();")
    assert block_start < fn.index("if (count != 0)") < block_end
    assert block_start < fn.index("sink(count);") < block_end


def test_early_guard_return_probe_unwraps_top_level_if_body() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag, int index)
        {
            int x;
            if (flag && (index != 1)) {
                sink(index);
                x = index + 1;
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(probe for probe in probes if probe.operator == "early-guard-return")
    fn = probe.source_text

    assert "if (!(flag && (index != 1))) {" in fn
    assert "        return;\n    }\n    sink(index);" in fn
    assert "    if (flag && (index != 1)) {" not in fn


def test_call_arg_tempization_ignores_pointer_member_access() -> None:
    source = textwrap.dedent("""\
        void grGreatBay_801F5460(Ground_GObj* gobj)
        {
            HSD_JObj* jobj = gobj->hsd_obj;
            Ground* gp = GET_GROUND(gobj);

            Ground_801C2ED0(jobj, gp->map_id);
            gp->xC_callback = NULL;
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "grGreatBay_801F5460",
        max_probes=20,
    )

    assert "call-argument-tempization" not in {probe.operator for probe in probes}


def test_call_arg_tempization_wraps_single_argument_temp_in_block() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int x, int y)
        {
            if (x) {
                sink(x + y, y);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    probe = next(
        probe for probe in probes if probe.operator == "call-argument-tempization"
    )

    assert "int ll_probe_arg_0 = x + y;" in probe.source_text
    assert "sink(ll_probe_arg_0, y);" in probe.source_text
    assert "sink(ll_probe_arg_0);" not in probe.source_text
    assert "        {\n            int ll_probe_arg_0" in probe.source_text


def test_call_arg_tempization_preserves_float_argument_type() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(float x)
        {
            f32 y;
            y = 2.0f;
            sinkf(x + y);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes if probe.operator == "call-argument-tempization"
    )

    assert "f32 ll_probe_arg_0 = x + y;" in probe.source_text
    assert "sinkf(ll_probe_arg_0);" in probe.source_text
    assert "int ll_probe_arg_0 = x + y;" not in probe.source_text
    assert probe.provenance == {
        "kind": "call-argument-tempization",
        "call": "sinkf",
        "argument_index": 0,
        "temp_type": "f32",
    }


def test_call_arg_tempization_ignores_nested_call_in_outer_argument_list() -> None:
    source = textwrap.dedent("""\
        void AXDriver_8038BF6C(HSD_SM* v)
        {
            HSD_SynthSFXSetPitchRatio(v->vID, 0,
                                      powf(2.0F, v->x20 / 1200.0F));
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "AXDriver_8038BF6C",
        max_probes=20,
    )

    assert "call-argument-tempization" not in {probe.operator for probe in probes}


def test_frame_reservation_pad_stack_probe_inserts_requested_pad() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            float y;

            sink(flag + count, y);
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "fn_80000000",
        frame_reservation_bytes=64,
        max_probes=30,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert probe.label == "frame-reservation-pad-stack-64"
    assert "    float y;\n    PAD_STACK(64);\n\n    sink" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 64,
        "action": "insert",
    }


def test_frame_reservation_pad_stack_probe_replaces_existing_pad() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            PAD_STACK(8);
            sink(flag + count);
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "fn_80000000",
        frame_reservation_bytes=64,
        max_probes=30,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert "PAD_STACK(8)" not in probe.source_text
    assert "    PAD_STACK(64);\n    sink" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 64,
        "action": "replace",
        "previous_bytes": 8,
    }


def test_generate_frame_directed_probes_emits_pad_stack_for_too_small_frame() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            sink(flag + count);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 80},
        target_frame={"frame_size": 88},
        frame_reservation_delta=8,
        max_probes=10,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert "    PAD_STACK(8);\n    sink" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 8,
        "action": "insert",
        "delta": 8,
    }


def test_generate_frame_directed_probes_decreases_existing_pad_stack_for_too_large_frame() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            PAD_STACK(16);
            sink(flag + count);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 88},
        target_frame={"frame_size": 80},
        frame_reservation_delta=-8,
        max_probes=10,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert "PAD_STACK(16)" not in probe.source_text
    assert "    PAD_STACK(8);\n    sink" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 8,
        "action": "decrease",
        "previous_bytes": 16,
        "delta": -8,
    }


def test_generate_frame_directed_probes_removes_exact_pad_stack_for_too_large_frame() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            PAD_STACK(8);
            sink(flag + count);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 88},
        target_frame={"frame_size": 80},
        frame_reservation_delta=-8,
        max_probes=10,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert "PAD_STACK(" not in probe.source_text
    assert "    int count;\n    sink" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "action": "remove",
        "previous_bytes": 8,
        "delta": -8,
    }


def test_generate_frame_directed_probes_removes_smaller_pad_stack_for_too_large_frame() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            PAD_STACK(8);
            sink(flag + count);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 96},
        target_frame={"frame_size": 80},
        frame_reservation_delta=-16,
        max_probes=10,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-reservation-pad-stack"
    )

    assert "PAD_STACK(" not in probe.source_text
    assert probe.provenance == {
        "kind": "frame-reservation-pad-stack",
        "action": "remove",
        "previous_bytes": 8,
        "delta": -16,
    }


def test_generate_frame_directed_probes_does_not_insert_pad_stack_for_too_large_frame() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            sink(flag + count);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 88},
        target_frame={"frame_size": 80},
        frame_reservation_delta=-8,
        max_probes=10,
    )

    assert "frame-reservation-pad-stack" not in {probe.operator for probe in probes}


def test_generate_frame_directed_probes_dematerializes_initialized_one_use_local() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            sink(tmp);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 80},
        target_frame={"frame_size": 72},
        frame_reservation_delta=-8,
        max_probes=10,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-local-dematerialize"
    )

    assert "int tmp = x + 1;" not in probe.source_text
    assert "sink(((int) (x + 1)));" in probe.source_text
    assert probe.provenance == {
        "kind": "frame-local-dematerialize",
        "local": "tmp",
        "action": "inline-initialized-local",
        "expression": "x + 1",
        "cast_type": "int",
        "use_kind": "call-argument",
        "definition_lines": [3, 3],
        "use_lines": [4, 4],
    }


def test_generate_frame_directed_probes_dematerializes_adjacent_assignment_local() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int x)
        {
            int tmp;
            tmp = x + 1;
            sink(tmp);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 80},
        target_frame={"frame_size": 72},
        frame_reservation_delta=-8,
        max_probes=10,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-local-dematerialize"
    )

    assert "int tmp;" not in probe.source_text
    assert "tmp = x + 1;" not in probe.source_text
    assert "sink(((int) (x + 1)));" in probe.source_text
    assert probe.provenance["action"] == "inline-assigned-local"
    assert probe.provenance["definition_lines"] == [3, 4]
    assert probe.provenance["use_lines"] == [5, 5]


def test_generate_frame_directed_probes_dematerializes_after_non_ascii_prefix() -> None:
    source = "/* unicode prefix: π */\n" + textwrap.dedent("""\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            sink(tmp);
        }
    """)

    probes = generate_frame_directed_probes(
        source,
        "fn_80000000",
        current_frame={"frame_size": 80},
        target_frame={"frame_size": 72},
        frame_reservation_delta=-8,
        max_probes=10,
    )
    probe = next(
        probe for probe in probes if probe.operator == "frame-local-dematerialize"
    )

    assert probe.source_text.startswith("/* unicode prefix: π */")
    assert "int tmp = x + 1;" not in probe.source_text
    assert "sink(((int) (x + 1)));" in probe.source_text


@pytest.mark.parametrize(
    "source",
    [
        """\
        void fn_80000000(int x)
        {
            int tmp = helper(x);
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x++;
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            tmp = 3;
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            sink(&tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            sink(tmp);
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            if (tmp) {
                sink(x);
            }
        }
        """,
        """\
        int fn_80000000(int x)
        {
            int tmp = x + 1;
            return tmp;
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            sink(tmp, x++);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            mutate(x);
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            int other = helper(x);
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            x = 3;
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
        #if 1
            sink(tmp);
        #endif
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            {
                int tmp = x + 2;
                sink(tmp);
            }
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp = x + 1, other = x + 2;
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            static int tmp = 1;
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            volatile int tmp = x + 1;
            sink(tmp);
        }
        """,
        """\
        void fn_80000000(int x)
        {
            int tmp[1] = { x };
            sink(tmp[0]);
        }
        """,
        """\
        void fn_80000000(Vec v)
        {
            Vec tmp = v;
            sink(tmp);
        }
        """,
    ],
)
def test_generate_frame_directed_probes_rejects_unsafe_dematerialize_cases(
    source: str,
) -> None:
    probes = generate_frame_directed_probes(
        textwrap.dedent(source),
        "fn_80000000",
        current_frame={"frame_size": 80},
        target_frame={"frame_size": 72},
        frame_reservation_delta=-8,
        max_probes=20,
    )

    assert "frame-local-dematerialize" not in {probe.operator for probe in probes}


def test_frame_local_dematerialize_scan_reports_address_taken_blocker() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int line)
        {
            Vec3 normal;

            mpLineGetNormal(line, &normal);
            sink(normal.y, normal.x);
        }
    """)

    probes, status = scan_frame_local_dematerialization_probes(
        source,
        "fn_80000000",
    )

    assert probes == []
    assert status["status"] == "no-safe-semantic-lever"
    assert status["operator"] == "frame-local-dematerialize"
    assert status["blockers"] == [
        {
            "kind": "address-taken-local",
            "local": "normal",
            "type": "Vec3",
            "definition_lines": [3, 3],
            "address_use_lines": [5, 5],
            "read_lines": [6, 6],
        }
    ]
    assert "address-taken local `normal`" in status["reason"]


def test_frame_local_dematerialize_scan_reports_multi_use_blocker() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            sink(tmp);
            sink(tmp);
        }
    """)

    probes, status = scan_frame_local_dematerialization_probes(
        source,
        "fn_80000000",
    )

    assert probes == []
    assert status["status"] == "no-safe-semantic-lever"
    assert status["blockers"] == [
        {
            "kind": "multi-use-local",
            "local": "tmp",
            "type": "int",
            "definition_lines": [3, 3],
            "use_count": 2,
            "use_lines": [[4, 4], [5, 5]],
        }
    ]
    assert "multi-use local `tmp`" in status["reason"]


def test_frame_local_dematerialize_scan_reports_source_span_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int x)
        {
            int tmp = x + 1;
            sink(tmp);
        }
    """)

    def fail_scan(*args, **kwargs):
        raise RuntimeError("tree-sitter unavailable")

    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.list_statement_spans",
        fail_scan,
    )

    probes, status = scan_frame_local_dematerialization_probes(
        source,
        "fn_80000000",
    )

    assert probes == []
    assert status["status"] == "scan-error"
    assert status["operator"] == "frame-local-dematerialize"
    assert "tree-sitter unavailable" in status["reason"]


def test_call_return_compare_chain_probes_include_targeted_variants() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(void* entity, float dist, int teammate_slot)
        {
            s32 b34_result = 0;
            int b34;

            b34_result = helper_call(entity);
            b34 = b34_result;
            if (b34 == 1) {
                sink_one();
                if (teammate_slot != 6) {
                    Table* teammate_table = lookup(teammate_slot);
                    if (dist > teammate_table->xD88) {
                        teammate_table->xD88 = dist;
                    }
                }
            } else {
                if (b34 == 0) {
                    sink_zero();
                }
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=20)
    by_label = {probe.label: probe for probe in probes}

    assert {
        "call-return-compare-switch-0",
        "call-return-compare-inverted-0",
        "call-return-compare-copy-in-else-0",
        "call-return-compare-split-direct-0",
        "call-return-compare-narrow-pointer-0",
    } <= set(by_label)
    provenance = by_label["call-return-compare-switch-0"].to_dict()["provenance"]
    assert provenance == {
        "kind": "call-return-compare-chain",
        "call_symbol": "helper_call",
        "call_expression": "helper_call(entity)",
        "result_var": "b34_result",
        "compare_var": "b34",
        "compare_values": [1, 0],
        "source_line": 6,
        "source_col": 18,
    }
    switch_source = by_label["call-return-compare-switch-0"].source_text
    assert "switch (b34)" in switch_source
    assert "case 1:" in switch_source
    assert "case 0:" in switch_source

    copy_else_source = by_label["call-return-compare-copy-in-else-0"].source_text
    assert "if (b34_result == 1)" in copy_else_source
    assert "    } else {\n        b34 = b34_result;\n        if (b34 == 0)" in copy_else_source

    narrowed_source = by_label["call-return-compare-narrow-pointer-0"].source_text
    assert "            {\n                Table* teammate_table" in narrowed_source
    assert "            }\n        }\n    } else" in narrowed_source


def test_loop_init_probe_uses_c89_compatible_enclosing_block() -> None:
    probes = generate_lifetime_layout_probes(SOURCE, "fn_80000000", max_probes=20)
    probe = next(probe for probe in probes if probe.operator == "loop-init")

    assert "for (int i =" not in probe.source_text
    assert "    {\n        int i;\n        for (i = 0;" in probe.source_text


def test_declaration_order_probes_include_adjacent_swap_and_loop_counter_hoist() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag)
        {
            int count;
            int total;

            if (flag) {
                s32 i;
                for (i = 0; i < count; i++) {
                    total += i;
                }
            }
            sink(total);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    by_label = {probe.label: probe for probe in probes}

    assert "adjacent-decl-swap-0" in by_label
    assert "    int total;\n    int count;" in by_label["adjacent-decl-swap-0"].source_text

    hoist = by_label["loop-counter-hoist-before-0"].source_text
    assert "    int i;\n    int count;" in hoist
    assert "        s32 i;\n" not in hoist
    assert "        for (i = 0; i < count; i++)" in hoist

    hoist_after = by_label["loop-counter-hoist-after-0"].source_text
    assert "    int count;\n    int i;\n    int total;" in hoist_after
    assert "        s32 i;\n" not in hoist_after


def test_loop_counter_hoist_reuses_existing_function_scope_counter() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(int flag, int count)
        {
            int i;
            int total;

            if (flag) {
                s32 i;
                for (i = 0; i < count; i++) {
                    total += i;
                }
            }
            sink(total);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(probe for probe in probes if probe.label == "loop-counter-hoist-before-0")

    assert probe.source_text.count("int i;") == 1
    assert "        s32 i;\n" not in probe.source_text
    assert "        for (i = 0; i < count; i++)" in probe.source_text
    assert probe.to_dict()["provenance"]["placement"] == "reuse:function-scope"


def test_sibling_loop_counter_hoist_reuses_safe_call_loops_and_skips_indexed_loop() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree*** trees, u8* order, int anim_id)
        {
            int total;

            if (anim_id != -1) {
                s32 i;
                for (i = 0; i < fp->dynamics_num; i++) {
                    ftCo_8009CB40(fp, i, 0, 0);
                }
            }
            if (fp->x594_b4) {
                s32 i;
                for (i = 0; i < fp->dynamics_num; i++) {
                    FigaTree* tree = trees[order[i]][0];
                    ftCo_8009CB40(fp, i, 1, tree);
                }
            }
            if (anim_id == -1) {
                s32 i;
                for (i = 0; i < fp->dynamics_num; i++) {
                    ftCo_8009CB40(fp, i, 0, 0);
                }
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    probe = by_label["sibling-loop-counter-hoist-function-0"]
    assert "    int i;\n    int total;" in probe.source_text
    assert probe.source_text.count("        s32 i;\n") == 1
    assert "if (fp->x594_b4) {\n        s32 i;" in probe.source_text
    assert probe.source_text.count("for (i = 0; i < fp->dynamics_num; i++)") == 3
    assert probe.to_dict()["provenance"] == {
        "kind": "sibling-loop-counter-hoist",
        "counter": "i",
        "call_symbol": "ftCo_8009CB40",
        "loop_count": 2,
        "placement": "function-scope",
        "skipped_indexed_loops": 1,
    }


def test_loop_counter_type_probe_targets_loop_counter_not_first_local() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            int count;
            s32 i;
            for (i = 0; i < count; i++) {
                sink(i);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(probe for probe in probes if probe.label == "loop-counter-type-0")

    assert "    int count;\n    int i;" in probe.source_text
    assert "    s32 i;" not in probe.source_text


def test_indexed_pointer_loop_probes_control_base_index_address_and_bound() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(FigaTree*** base, u8* order, int count)
        {
            FigaTree*** trees = base;
            int i;
            for (i = 0; i < count; i++) {
                FigaTree* tree = trees[order[i]][0];
                apply(i, tree);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    assert "indexed-pointer-loop-bound-local-0" in by_label
    bound = by_label["indexed-pointer-loop-bound-local-0"]
    assert "    {\n        int ll_probe_loop_bound_0 = count;\n" in bound.source_text
    assert "for (i = 0; i < ll_probe_loop_bound_0; i++)" in bound.source_text

    assert "indexed-pointer-loop-index-temp-0" in by_label
    index = by_label["indexed-pointer-loop-index-temp-0"]
    assert "        int ll_probe_index_0 = order[i];\n" in index.source_text
    assert "trees[ll_probe_index_0][0]" in index.source_text

    assert "indexed-pointer-loop-base-alias-0" in by_label
    base_alias = by_label["indexed-pointer-loop-base-alias-0"]
    assert "        FigaTree*** ll_probe_base_0 = trees;\n" in base_alias.source_text
    assert "ll_probe_base_0[order[i]][0]" in base_alias.source_text

    assert "indexed-pointer-loop-address-temp-0" in by_label
    address = by_label["indexed-pointer-loop-address-temp-0"]
    assert "        FigaTree** ll_probe_addr_0 = trees[order[i]];\n" in address.source_text
    assert "FigaTree* tree = ll_probe_addr_0[0];" in address.source_text

    assert address.provenance == {
        "kind": "indexed-pointer-loop",
        "variant": "address-temp",
        "counter": "i",
        "base": "trees",
        "index_expr": "order[i]",
        "bound": "count",
    }

    struct_source = textwrap.dedent("""\
        void fn_80000001(struct FigaTree*** base, u8* order, int count)
        {
            struct FigaTree*** trees = base;
            int i;
            for (i = 0; i < count; i++) {
                struct FigaTree* tree = trees[order[i]][0];
                apply(i, tree);
            }
        }
    """)

    struct_probes = generate_lifetime_layout_probes(
        struct_source,
        "fn_80000001",
        max_probes=60,
    )
    struct_by_label = {probe.label: probe for probe in struct_probes}
    assert (
        "        struct FigaTree*** ll_probe_base_0 = trees;\n"
        in struct_by_label["indexed-pointer-loop-base-alias-0"].source_text
    )
    assert (
        "        struct FigaTree** ll_probe_addr_0 = trees[order[i]];\n"
        in struct_by_label["indexed-pointer-loop-address-temp-0"].source_text
    )


def test_indexed_struct_pointer_probe_rewrites_arrow_uses_to_direct_index() -> None:
    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
            int y;
            int z;
        } Item;

        int fn_80000000(Item* items, int i)
        {
            Item* item = &items[i];
            int x = item->x;
            int z = (*item).z;
            item->y = x + z;
            return item->y;
        }
    """)

    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert status == {
        "blocker": None,
        "reason": "source scan generated safe indexed struct pointer probes",
        "supported_candidate_count": 1,
        "rejected_candidate_count": 0,
    }
    assert [probe.operator for probe in probes] == ["indexed-struct-pointer"]
    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == probes
    rewritten = probes[0].source_text
    assert "Item* item = &items[i];" not in rewritten
    assert "int x = items[i].x;" in rewritten
    assert "int z = items[i].z;" in rewritten
    assert "items[i].y = x + z;" in rewritten
    assert "return items[i].y;" in rewritten
    provenance = probes[0].provenance
    assert provenance["kind"] == "indexed-struct-pointer"
    assert provenance["diagnostic"] == "indexed_struct_pointer_materialization"
    assert provenance["pointer"] == "item"
    assert provenance["source_lines"] == [9, 13]
    assert provenance["base_expression"] == "items"
    assert provenance["index_expression"] == "i"
    assert provenance["direct_expression"] == "items[i]"
    assert provenance["split_first_field"] is False
    assert [use["field"] for use in provenance["field_uses"]] == ["x", "z", "y", "y"]
    assert [use["syntax"] for use in provenance["field_uses"]] == [
        "arrow",
        "deref-dot",
        "arrow",
        "arrow",
    ]


def test_indexed_struct_pointer_probe_rewrites_base_plus_index_deref_dot() -> None:
    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
            int y;
        } Item;

        int fn_80000000(Item* items, int i)
        {
            Item* item = items + i;
            int x = (*item).x;
            item->y = x + 1;
            return (*item).y + x;
        }
    """)

    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    probes = generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    rewritten = probes[0].source_text
    assert "Item* item = items + i;" not in rewritten
    assert "int x = (items + i)->x;" in rewritten
    assert "(items + i)->y = x + 1;" in rewritten
    assert "return (items + i)->y + x;" in rewritten
    assert probes[0].provenance["direct_expression"] == "items + i"
    assert [use["syntax"] for use in probes[0].provenance["field_uses"]] == [
        "deref-dot",
        "arrow",
        "deref-dot",
    ]


def test_indexed_struct_pointer_probe_rewrites_double_index_address_form() -> None:
    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        int fn_80000000(Item rows[][4], int row, int col)
        {
            Item* item = &rows[row][col];
            return item->x;
        }
    """)

    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
    )

    probes = generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    rewritten = probes[0].source_text
    assert "Item* item = &rows[row][col];" not in rewritten
    assert "return rows[row][col].x;" in rewritten
    assert probes[0].provenance["base_expression"] == "rows"
    assert probes[0].provenance["index_expression"] == "row"
    assert probes[0].provenance["subindex_expression"] == "col"
    assert probes[0].provenance["direct_expression"] == "rows[row][col]"


def test_indexed_struct_pointer_probe_splits_direct_indexed_field_access() -> None:
    source = textwrap.dedent("""\
        typedef float f32;

        typedef struct Item {
            f32 x0;
            f32 x4;
            f32 x8;
        } Item;

        typedef struct Vec3 {
            f32 x;
            f32 y;
            f32 z;
        } Vec3;

        int fn_80000000(Item* items, int i)
        {
            Vec3 pos;
            pos.x += items[i].x0;
            pos.y += items[i].x4;
            pos.z += items[i].x8;
            sink(&pos);
            return 0;
        }
    """)

    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert status == {
        "blocker": None,
        "reason": "source scan generated safe indexed struct pointer probes",
        "supported_candidate_count": 1,
        "rejected_candidate_count": 0,
    }
    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == probes
    assert [probe.operator for probe in probes] == ["indexed-struct-pointer"]
    rewritten = probes[0].source_text
    assert "    f32 ll_probe_indexed_field_0;\n" in rewritten
    assert "    ll_probe_indexed_field_0 = items[i].x0;" in rewritten
    assert "pos.x += ll_probe_indexed_field_0;" in rewritten
    assert "pos.y += items[i].x4;" in rewritten
    assert "pos.z += items[i].x8;" in rewritten
    provenance = probes[0].provenance
    assert provenance["kind"] == "indexed-struct-pointer"
    assert provenance["diagnostic"] == "indexed_struct_pointer_materialization"
    assert provenance["variant"] == "direct-field-scalar-split"
    assert provenance["base_expression"] == "items"
    assert provenance["index_expression"] == "i"
    assert provenance["direct_expression"] == "items[i]"
    assert provenance["field"] == "x0"
    assert provenance["scalar_type"] == "f32"
    assert provenance["split_first_field"] is True


def test_indexed_struct_pointer_probe_rejects_escaped_or_mutated_pointer() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    cases = [
        "sink(item);",
        "item = &items[i + 1];",
        "if (item == 0) { return 0; }",
        "item++;",
        "return item[0].x;",
        "return (int) item;",
        "return item;",
        "return &item != 0;",
        "return (int) (item + 1);",
        "return &item->x != 0;",
        "return &(item->x) != 0;",
    ]

    for extra in cases:
        source = textwrap.dedent(f"""\
            typedef struct Item {{
                int x;
            }} Item;

            int fn_80000000(Item* items, int i)
            {{
                Item* item = &items[i];
                {extra}
                return item->x;
            }}
        """)

        assert generate_indexed_struct_pointer_probes(
            source,
            "fn_80000000",
            max_probes=8,
        ) == []
        probes, status = scan_indexed_struct_pointer_probes(
            source,
            "fn_80000000",
            max_probes=8,
        )
        assert probes == []
        assert status["blocker"] == "no-safe-materialized-pointer"
        assert set(status) == {
            "blocker",
            "reason",
            "supported_candidate_count",
            "rejected_candidate_count",
        }


def test_indexed_struct_pointer_probe_rejects_side_effectful_base_index_and_subindex() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
    )

    initializers = [
        "Item* item = &items[i++];",
        "Item* item = &items[i = 1];",
        "Item* item = &items[i <<= 1];",
        "Item* item = &items[i >>= 1];",
        "Item* item = &items[i, j];",
        "Item* item = &get_items()[i];",
        "Item* item = &rows[i][j++];",
        "Item* item = get_items() + i;",
    ]

    for initializer in initializers:
        source = textwrap.dedent(f"""\
            typedef struct Item {{
                int x;
            }} Item;

            int fn_80000000(Item* items, Item rows[][4], int i, int j)
            {{
                {initializer}
                return item->x;
            }}
        """)

        assert generate_indexed_struct_pointer_probes(
            source,
            "fn_80000000",
            max_probes=8,
        ) == []


def test_indexed_struct_pointer_probe_rejects_later_base_index_mutations() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    cases = [
        ("Item* item = &items[i];", "i++;"),
        ("Item* item = &items[i];", "items = other;"),
        ("Item* item = &rows[i][j];", "j += 1;"),
        ("Item* item = &items[i];", "bump(&i);"),
        ("Item* item = &items[i];", "bump(&items);"),
        ("Item* item = &rows[i][j];", "bump(&j);"),
    ]

    for initializer, mutation in cases:
        source = textwrap.dedent(f"""\
            typedef struct Item {{
                int x;
            }} Item;

            int fn_80000000(Item* items, Item* other, Item rows[][4], int i, int j)
            {{
                {initializer}
                {mutation}
                return item->x;
            }}
        """)

        assert generate_indexed_struct_pointer_probes(
            source,
            "fn_80000000",
            max_probes=8,
        ) == []
        probes, status = scan_indexed_struct_pointer_probes(
            source,
            "fn_80000000",
            max_probes=8,
        )
        assert probes == []
        assert status["blocker"] == "no-safe-materialized-pointer"
        assert status["supported_candidate_count"] == 1
        assert status["rejected_candidate_count"] == 1


def test_indexed_struct_pointer_probe_rejects_member_chain_mentions() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        typedef struct Wrapper {
            Item* item;
        } Wrapper;

        int fn_80000000(Item* items, Wrapper* wrapper, int i)
        {
            Item* item = &items[i];
            return wrapper->item->x;
        }
    """)

    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == []
    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )
    assert probes == []
    assert status["blocker"] == "no-safe-materialized-pointer"
    assert status["supported_candidate_count"] == 1
    assert status["rejected_candidate_count"] == 1


def test_indexed_struct_pointer_probe_stays_within_declaring_block() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        int fn_80000000(Item* items, Item* item, int i, int cond)
        {
            if (cond) {
                Item* item = &items[i];
                sink(item->x);
            }
            return item->x;
        }
    """)

    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert status["blocker"] is None
    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == probes
    rewritten = probes[0].source_text
    assert "Item* item = &items[i];" not in rewritten
    assert "sink(items[i].x);" in rewritten
    assert "return item->x;" in rewritten
    assert "return items[i].x;" not in rewritten


def test_indexed_struct_pointer_probe_rejects_preprocessor_regions_and_other_functions() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        int fn_80000000(Item* items, int i)
        {
        #if ENABLED
            Item* item = &items[i];
            return item->x;
        #endif
        }

        int sibling(Item* items, int i)
        {
            Item* item = &items[i];
            return item->x;
        }
    """)

    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == []
    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )
    assert probes == []
    assert status == {
        "blocker": "no-safe-materialized-pointer",
        "reason": (
            "source scan found materialized pointers, but all violated safety rules"
        ),
        "supported_candidate_count": 1,
        "rejected_candidate_count": 1,
    }
    assert generate_indexed_struct_pointer_probes(
        source,
        "missing_function",
        max_probes=8,
    ) == []
    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "missing_function",
        max_probes=8,
    )
    assert probes == []
    assert status == {
        "blocker": "indexed-struct-hint-unavailable",
        "reason": (
            "checkdiff hint could not be associated with a supported source "
            "pointer initializer"
        ),
        "supported_candidate_count": 0,
        "rejected_candidate_count": 0,
    }


def test_indexed_struct_pointer_probe_ignores_comment_and_string_mentions() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        int fn_80000000(Item* items, int i)
        {
            Item* item = &items[i];
            // item->x is mentioned in a comment, not rewritten code.
            debug("item->x");
            return 1;
        }
    """)

    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == []
    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )
    assert probes == []
    assert status == {
        "blocker": "no-safe-materialized-pointer",
        "reason": (
            "source scan found materialized pointers, but all violated safety rules"
        ),
        "supported_candidate_count": 1,
        "rejected_candidate_count": 1,
    }


def test_indexed_struct_pointer_probe_ignores_commented_out_declarations() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        int fn_80000000(Item* items, Item* actual, int i)
        {
            Item* item = actual;
            /*
            Item* item = &items[i];
            */
            return item->x;
        }
    """)

    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == []
    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )
    assert probes == []
    assert status == {
        "blocker": "indexed-struct-hint-unavailable",
        "reason": (
            "checkdiff hint could not be associated with a supported source "
            "pointer initializer"
        ),
        "supported_candidate_count": 0,
        "rejected_candidate_count": 0,
    }


def test_indexed_struct_pointer_probe_rejects_address_taken_with_comment_gap() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        int fn_80000000(Item* items, int i)
        {
            Item* item = &items[i];
            return & /* keep gap */ item->x != 0;
        }
    """)

    assert generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    ) == []
    probes, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )
    assert probes == []
    assert status["blocker"] == "no-safe-materialized-pointer"
    assert status["supported_candidate_count"] == 1
    assert status["rejected_candidate_count"] == 1


def test_indexed_struct_pointer_probe_allows_unaffected_preprocessor_regions() -> None:
    from src.mwcc_debug.pressure_explorer import (
        generate_indexed_struct_pointer_probes,
        scan_indexed_struct_pointer_probes,
    )

    source = textwrap.dedent("""\
        typedef struct Item {
            int x;
        } Item;

        int fn_80000000(Item* items, int i)
        {
        #if ENABLED
            trace();
        #endif
            Item* item = &items[i];
            return item->x;
        }
    """)

    probes = generate_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )
    assert len(probes) == 1
    assert "return items[i].x;" in probes[0].source_text
    scanned, status = scan_indexed_struct_pointer_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )
    assert scanned == probes
    assert status["blocker"] is None
    assert status["supported_candidate_count"] == 1
    assert status["rejected_candidate_count"] == 0


def test_pointer_walk_loop_probes_control_tree_index_address_and_end() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** trees)
        {
            FigaTree** tree = trees;
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree[i]);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    index = by_label["pointer-walk-loop-index-temp-0"]
    assert "        int ll_probe_index_0 = i;\n" in index.source_text
    assert "tree[ll_probe_index_0]" in index.source_text

    base = by_label["pointer-walk-loop-base-alias-0"]
    assert "        FigaTree** ll_probe_base_0 = tree;\n" in base.source_text
    assert "ll_probe_base_0[i]" in base.source_text

    address = by_label["pointer-walk-loop-address-temp-0"]
    assert "        FigaTree** ll_probe_addr_0 = tree + i;\n" in address.source_text
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_addr_0);" in address.source_text

    value = by_label["pointer-walk-loop-value-temp-0"]
    assert "        FigaTree* ll_probe_value_0 = tree[i];\n" in value.source_text
    assert "ftCo_8009CB40(fp, i, true, ll_probe_value_0);" in value.source_text

    induction = by_label["pointer-walk-loop-induction-0"]
    assert "        FigaTree** ll_probe_iter_0 = tree;\n" in induction.source_text
    assert (
        "for (i = 0; i < fp->dynamics_num; i++, ll_probe_iter_0++)"
        in induction.source_text
    )
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_iter_0);" in induction.source_text

    end_pointer = by_label["pointer-walk-loop-end-pointer-0"]
    assert (
        "        FigaTree** ll_probe_end_0 = tree + fp->dynamics_num;\n"
        in end_pointer.source_text
    )
    assert (
        "for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++)"
        in end_pointer.source_text
    )

    assert address.provenance == {
        "kind": "pointer-walk-loop",
        "variant": "address-temp",
        "counter": "i",
        "base": "tree",
        "index_expr": "i",
        "bound": "fp->dynamics_num",
    }


def test_lifetime_layout_operator_filter_applies_before_max_limit() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** trees)
        {
            FigaTree** tree = trees;
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree[i]);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(
        source,
        "fn_80000000",
        max_probes=2,
        operator_filter={"pointer-walk-loop"},
    )

    assert [probe.operator for probe in probes] == [
        "pointer-walk-loop",
        "pointer-walk-loop",
    ]
    assert [probe.label for probe in probes] == [
        "pointer-walk-loop-index-temp-0",
        "pointer-walk-loop-base-alias-0",
    ]


def test_pointer_base_call_loop_probes_index_direct_tree_argument() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** tree)
        {
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree);
            }
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=60)
    by_label = {probe.label: probe for probe in probes}

    indexed = by_label["pointer-base-call-indexed-0"]
    assert "ftCo_8009CB40(fp, i, true, tree[i]);" in indexed.source_text

    value = by_label["pointer-base-call-value-temp-0"]
    assert "        FigaTree* ll_probe_value_0 = tree[i];\n" in value.source_text
    assert "ftCo_8009CB40(fp, i, true, ll_probe_value_0);" in value.source_text

    address = by_label["pointer-base-call-address-temp-0"]
    assert "        FigaTree** ll_probe_addr_0 = tree + i;\n" in address.source_text
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_addr_0);" in address.source_text

    induction = by_label["pointer-base-call-induction-0"]
    assert "        FigaTree** ll_probe_iter_0 = tree;\n" in induction.source_text
    assert (
        "for (i = 0; i < fp->dynamics_num; i++, ll_probe_iter_0++)"
        in induction.source_text
    )
    assert "ftCo_8009CB40(fp, i, true, *ll_probe_iter_0);" in induction.source_text

    end_pointer = by_label["pointer-base-call-end-pointer-0"]
    assert "        FigaTree** ll_probe_end_0 = tree + fp->dynamics_num;\n" in (
        end_pointer.source_text
    )
    assert (
        "for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++)"
        in end_pointer.source_text
    )

    assert address.provenance == {
        "kind": "pointer-base-call-loop",
        "variant": "address-temp",
        "counter": "i",
        "base": "tree",
        "index_expr": "i",
        "bound": "fp->dynamics_num",
    }


def test_expression_shape_probe_removes_assignment_in_expression_temp() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Vec* prevPos, Vec* pos)
        {
            float avg_sum;
            float dist;

            dist = sqrtf(((prevPos->x - (avg_sum = pos->x)) * (prevPos->x - avg_sum)) +
                         ((prevPos->y - pos->y) * (prevPos->y - pos->y)));
            sink(dist);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "assignment-expression-cse-removal-0"
    )

    assert "(avg_sum = pos->x)" not in probe.source_text
    assert "prevPos->x - pos->x" in probe.source_text
    assert "prevPos->x - avg_sum" not in probe.source_text


def test_expression_shape_probe_introduces_named_distance_component_temps() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Vec* prevPos, Vec* pos)
        {
            float dist;

            dist = sqrtf(((prevPos->x - pos->x) * (prevPos->x - pos->x)) +
                         ((prevPos->y - pos->y) * (prevPos->y - pos->y)));
            sink(dist);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "distance-component-temps-0"
    )

    assert "float ll_probe_dx_0 = prevPos->x - pos->x;" in probe.source_text
    assert "float ll_probe_dy_0 = prevPos->y - pos->y;" in probe.source_text
    assert "sqrtf((ll_probe_dx_0 * ll_probe_dx_0) +" in probe.source_text
    assert "(ll_probe_dy_0 * ll_probe_dy_0)" in probe.source_text


def test_expression_shape_probe_splits_abs_branch_discriminator() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Vec* prevPos, Vec* pos)
        {
            float y_abs;

            y_abs = pos->y - prevPos->y;
            if (y_abs > 0.0f) {
                if (y_abs < 0.0f) {
                    y_abs = -y_abs;
                } else {
                    y_abs = y_abs;
                }
            }
            sink(y_abs);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "abs-branch-discriminator-split-0"
    )

    assert "float ll_probe_abs_discriminator_0;" in probe.source_text
    assert "ll_probe_abs_discriminator_0 = pos->y - prevPos->y;" in probe.source_text
    assert "y_abs = ll_probe_abs_discriminator_0;" in probe.source_text
    assert "if (ll_probe_abs_discriminator_0 > 0.0f)" in probe.source_text
    assert "if (y_abs < 0.0f)" in probe.source_text
    assert probe.provenance == {
        "kind": "abs-branch-discriminator-split",
        "value_local": "y_abs",
        "discriminator_local": "ll_probe_abs_discriminator_0",
        "expression": "pos->y - prevPos->y",
    }


def test_guard_shape_probe_rewrites_boolean_call_return_as_case0_default_switch() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Entity* entity)
        {
            if (ftLib_8008732C(entity)) {
                return;
            }
            sink(entity);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    probe = next(
        probe for probe in probes
        if probe.label == "boolean-guard-switch-0"
    )

    assert "switch (ftLib_8008732C(entity))" in probe.source_text
    assert "case 0:" in probe.source_text
    assert "break;" in probe.source_text
    assert "default:" in probe.source_text
    assert "return;" in probe.source_text
    assert "if (ftLib_8008732C(entity))" not in probe.source_text
    assert probe.provenance == {
        "kind": "boolean-guard-switch",
        "condition": "ftLib_8008732C(entity)",
    }


def test_probe_generation_skips_function_prototype_before_definition() -> None:
    source = textwrap.dedent("""\
        void fn_80000000(Entity* entity);

        void unrelated(void)
        {
            int x0;
            int x1;
            sink(x0, x1);
        }

        void fn_80000000(Entity* entity)
        {
            if (ftLib_8008732C(entity)) {
                return;
            }
            sink(entity);
        }
    """)

    probes = generate_lifetime_layout_probes(source, "fn_80000000", max_probes=30)
    labels = {probe.label for probe in probes}

    assert "boolean-guard-switch-0" in labels
    assert "adjacent-decl-swap-0" not in labels


def test_lifetime_layout_cli_compares_candidate_pcdump_json(tmp_path: pathlib.Path) -> None:
    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.txt"
    baseline.write_text(BASELINE)
    candidate.write_text(CANDIDATE)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged={baseline}",
            "--candidate",
            f"temp-introduction={candidate}",
            "--pairs",
            "r37/r40",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["function"] == "fn_80000000"
    assert payload["ranking"] == (
        "lifetime-layout pressure objective, final match percent tiebreaker"
    )
    assert payload["baseline"]["frame_size"] == 56
    variant = payload["variants"][0]
    assert variant["rank"] == 1
    assert variant["label"] == "temp-introduction"
    assert variant["operator"] == "temp-introduction"
    assert variant["delta"]["frame_delta"] == -8
    assert variant["delta"]["spill_removed"] == [37]
    assert variant["delta"]["interference_removed"] == [[37, 40]]
    assert variant["objective"]["frame_delta"] == -8
    assert variant["objective"]["target_spill_removed"] == [37]
    assert variant["objective"]["actionability"] == "improved"
    assert variant["objective"]["actionability_reasons"] == [
        "frame_reduced",
        "target_spill_removed",
        "interference_removed",
    ]
    assert variant["objective"]["match_percent"] is None
    assert variant["objective"]["opcode_shape_preserved"] is None
    assert payload["variants"][1]["rank"] == 2
    assert payload["variants"][1]["label"] == "unchanged"
    assert payload["variants"][1]["objective"]["actionability"] == "neutral"


def test_lifetime_layout_objective_keeps_untargeted_interference_neutral() -> None:
    delta = PressureDelta(
        frame_before=56,
        frame_after=56,
        frame_delta=0,
        saved_added=(),
        saved_removed=(),
        spill_added=(),
        spill_removed=(),
        interference_added=((10, 11), (12, 13)),
        interference_removed=((20, 21), (22, 23), (24, 25)),
        coalesce_added=(),
        coalesce_removed=(),
        target_pairs=(),
    )

    objective = debug_cli._score_lifetime_layout_objective(
        delta,
        target_pairs=[],
        match_percent=99.37799,
    )

    assert objective["actionability"] == "regressed"
    assert "interference_removed" not in objective["actionability_reasons"]
    assert objective["sort_key"][3] == 0.0


def test_lifetime_layout_cli_source_failure_keeps_source_path(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return BASELINE.replace("fn_80000000", "other")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"block-scope={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "malformed-source"
    assert "compiled probe pcdump omitted the target function" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "source_hunk" in variant
    assert "fn_80000000" in variant["source_hunk"]


def test_lifetime_layout_cli_rejects_source_missing_target_before_compile(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000001(void) {\n    helper();\n}\n")

    def fail_if_compiled(*args, **kwargs) -> str:
        raise AssertionError("source missing target should be rejected before compile")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fail_if_compiled,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"block-scope={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "malformed-source"
    assert "target function fn_80000000 not found in candidate source" in variant["error"]
    assert "before compile" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "fn_80000001" in variant["source_hunk"]


def test_lifetime_layout_cli_marks_dump_missing_target_as_malformed_source(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.diff_capture import CompileFailure

    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {\n}\n")

    def fake_compile(diff_input, *, function, melee_root, timeout) -> str:
        raise CompileFailure(
            side=diff_input.label,
            command=["debug", "dump", "local"],
            stdout="",
            stderr=(
                "function 'fn_80000000' not found in pcdump\n"
                "suggestions: fn_80000001"
            ),
            returncode=3,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"block-scope={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "malformed-source"
    assert "compiled probe pcdump omitted the target function" in variant["error"]
    assert "fn_80000001" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "fn_80000000" in variant["source_hunk"]


def test_lifetime_layout_json_reports_candidate_progress_and_timeout_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.diff_capture import CompileFailure

    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(diff_input, *, function, melee_root, timeout) -> str:
        raise CompileFailure(
            side=diff_input.label,
            command=["debug", "dump", "local"],
            stdout="",
            stderr="dump local timed out after 5s",
            returncode=124,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"manual:block-scope={source}",
            "--timeout",
            "5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    assert variant["status"] == "failed"
    assert variant["label"] == "manual"
    assert variant["source_retained"] == str(source)
    assert "timed out" in variant["error"]
    progress = [
        json.loads(line)
        for line in result.stderr.splitlines()
        if line.startswith("{")
    ]
    assert progress[0] == {
        "event": "lifetime-layout-candidate-start",
        "index": 1,
        "total": 1,
        "label": "manual",
        "operator": "block-scope",
        "path": str(source),
    }
    assert progress[1]["event"] == "lifetime-layout-candidate-failed"
    assert progress[1]["label"] == "manual"
    assert "timed out" in progress[1]["error"]


def test_lifetime_layout_cli_scores_source_with_match_percent_and_stack_slots(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    stack_localizer = {
        "mismatch_count": 1,
        "deltas": [4],
        "mismatches": [
            {
                "opcode": "stfs",
                "expected_offset": 0x34,
                "current_offset": 0x30,
                "delta": 4,
            }
        ],
    }

    def fake_compile(*args, **kwargs) -> str:
        return CANDIDATE

    def fake_real_score(*args, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            match_percent=99.94,
            match_percent_error=None,
            stack_slot_localizer=stack_localizer,
            stack_slot_error=None,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_source_candidate_real_tree",
        fake_real_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"temp-introduction={source}",
            "--pairs",
            "r37/r40",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["rank"] == 1
    assert variant["final_match_percent"] == 99.94
    assert variant["match_percent"] == 99.94
    assert variant["objective"]["match_percent"] == 99.94
    assert variant["source_retained"] == str(source)
    assert variant["stack_slot_localizer"] == stack_localizer
    assert variant["objective"]["stack_slot_mismatch_count"] == 1


def test_score_source_candidate_rejects_new_helper_definition_without_build(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    melee_root = tmp_path / "melee"
    target = melee_root / "src" / "melee" / "pl" / "plbonuslib.c"
    target.parent.mkdir(parents=True)
    original = textwrap.dedent("""\
        static float existing_helper(float value)
        {
            return value;
        }

        void fn_8003F654(void)
        {
            existing_helper(1.0f);
        }
    """)
    target.write_text(original)

    candidate = tmp_path / "candidate.c"
    candidate.write_text(textwrap.dedent("""\
        static float existing_helper(float value)
        {
            return value;
        }

        static inline float f654_slot_helper(float value)
        {
            return value;
        }

        void fn_8003F654(void)
        {
            f654_slot_helper(1.0f);
        }
    """))

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/pl/plbonuslib",
    )

    def fail_if_builds(*args, **kwargs):
        raise AssertionError("candidate with external helper should be rejected before build")

    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fail_if_builds)

    score = debug_cli._score_source_candidate_real_tree(
        candidate,
        function="fn_8003F654",
        melee_root=melee_root,
    )

    assert score.match_percent is None
    assert score.match_percent_error is not None
    assert "helper function(s) outside fn_8003F654" in score.match_percent_error
    assert "f654_slot_helper" in score.match_percent_error
    assert "only transfers fn_8003F654" in score.match_percent_error
    assert target.read_text() == original


def test_lifetime_layout_json_compile_probes_emits_live_candidate_paths(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE)
    source.write_text(SOURCE)

    def fake_compile(*args, **kwargs) -> str:
        return CANDIDATE

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--compile-probes",
            "--no-score-match-percent",
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    assert variant["status"] == "ok"
    assert pathlib.Path(variant["path"]).exists()


def test_lifetime_layout_compile_probes_use_same_tu_unit_source(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    melee_root = tmp_path / "melee"
    baseline = tmp_path / "baseline.txt"
    source = melee_root / "src" / "melee" / "mn" / "source.c"
    source.parent.mkdir(parents=True)
    baseline.write_text(BASELINE)
    source.write_text(SOURCE)
    calls: list[dict[str, object]] = []

    def fake_compile(diff_input, *, function, melee_root, timeout, unit_source=None) -> str:
        calls.append({"diff_input": diff_input, "unit_source": unit_source})
        return CANDIDATE

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--compile-probes",
            "--no-score-match-percent",
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls
    assert calls[0]["unit_source"] == source


def test_lifetime_layout_cli_exposes_frame_reservation_probe(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE)
    source.write_text(SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--frame-reservation-bytes",
            "64",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    probes = json.loads(result.stdout)["probes"]
    probe = next(
        probe for probe in probes
        if probe["operator"] == "frame-reservation-pad-stack"
    )
    assert probe["label"] == "frame-reservation-pad-stack-64"
    assert probe["provenance"] == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 64,
        "action": "insert",
    }


def test_lifetime_layout_cli_focuses_b4_tree_loop_probe_families(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE)
    source.write_text(textwrap.dedent("""\
        void fn_80000000(Fighter* fp, FigaTree** trees)
        {
            FigaTree** tree = trees;
            int i;
            for (i = 0; i < fp->dynamics_num; i++) {
                ftCo_8009CB40(fp, i, true, tree[i]);
            }
        }
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--focus",
            "b4-tree-loop",
            "--max-probes",
            "3",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["focus"] == "b4-tree-loop"
    assert payload["operator_filter"] == [
        "declaration-order",
        "indexed-pointer-loop",
        "loop-counter-hoist",
        "loop-counter-type",
        "pointer-base-call-loop",
        "pointer-walk-loop",
    ]
    operators = {probe["operator"] for probe in payload["probes"]}
    assert operators == {"pointer-walk-loop"}
    assert len(payload["probes"]) == 3
