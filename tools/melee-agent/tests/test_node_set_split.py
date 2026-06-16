"""Tests for node-set split request parsing and candidate scoring."""
from __future__ import annotations

import pytest

import src.mwcc_debug.node_set_split as node_set_split
from src.mwcc_debug import tiebreak as tb
from src.mwcc_debug.colorgraph_parser import ColorgraphDecision, ColorgraphSection
from src.mwcc_debug.node_set_split import (
    NodeSetSplitRequest,
    annotate_target_color_select_order_leads,
    derive_target_color_select_order_leads,
    evaluate_coupled_node_set_split_signature,
    evaluate_node_set_split_signature,
    generate_coupled_node_set_split_patches,
    generate_node_set_introduce_binding_patches,
    generate_node_set_split_patches,
    request_from_node_set_delta,
    requests_from_node_set_delta,
    summarize_node_set_split_scores,
)
from src.mwcc_debug.simplify_search import BaselineSignature
from src.mwcc_debug.source_shape import CandidatePatch, CandidateScore


def _signature(
    *,
    assigned_regs: frozenset[tuple[int, int]],
    spill_set: frozenset[int] = frozenset(),
) -> BaselineSignature:
    return BaselineSignature(
        interference_edges=frozenset(),
        coalesce_mappings=frozenset(),
        spill_set=spill_set,
        simplify_order=(40,),
        assigned_regs=assigned_regs,
    )


def test_request_from_node_set_delta_extracts_simple_source_name() -> None:
    delta = {
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [
            {
                "target_ig": 33,
                "current_register": "f31",
                "desired_registers": ["f30"],
                "source": {"name": "holder", "expression": "holder"},
            }
        ],
    }

    req = request_from_node_set_delta(delta)

    assert req is not None
    assert req.function == "fn_test"
    assert req.class_id == 1
    assert req.target_ig == 33
    assert req.current_reg == "f31"
    assert req.target_reg == "f30"
    assert req.var_name == "holder"
    assert req.blocked_reason is None


def test_request_from_node_set_delta_accepts_solve_coloring_json_wrapper() -> None:
    payload = {
        "function": "fn_test",
        "class_id": 1,
        "exit_code": 3,
        "reason": "force-phys collision",
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "fn_test",
            "class_id": 1,
            "missing_virtuals": [
                {
                    "target_ig": 33,
                    "current_register": "f31",
                    "desired_registers": ["f30"],
                    "source": {"name": "holder", "expression": "holder"},
                }
            ],
        },
    }

    req = request_from_node_set_delta(payload)

    assert req is not None
    assert req.function == "fn_test"
    assert req.class_id == 1
    assert req.target_ig == 33
    assert req.current_reg == "f31"
    assert req.target_reg == "f30"
    assert req.var_name == "holder"
    assert req.blocked_reason is None


def test_request_from_node_set_delta_target_filter_selects_requested_bindable() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 10,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {
                    "name": "stat_value",
                    "expression": "entries[i].stat_value",
                },
            },
            {
                "target_ig": 12,
                "current_register": "r30",
                "desired_registers": ["r28"],
                "source": {"name": "holder", "expression": "holder"},
            },
            {
                "target_ig": 13,
                "current_register": "r31",
                "desired_registers": ["r26"],
                "source": {"name": "other", "expression": "other"},
            },
        ],
    }

    default_req = request_from_node_set_delta(delta)
    filtered_req = request_from_node_set_delta(delta, target_ig=13)

    assert default_req is not None
    assert default_req.target_ig == 12
    assert default_req.var_name == "holder"
    assert filtered_req is not None
    assert filtered_req.target_ig == 13
    assert filtered_req.current_reg == "r31"
    assert filtered_req.target_reg == "r26"
    assert filtered_req.var_name == "other"


def test_request_from_node_set_delta_does_not_bind_field_expression_name() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 42,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {
                    "name": "stat_value",
                    "expression": "entries[i].stat_value",
                },
            }
        ],
    }

    req = request_from_node_set_delta(delta)

    assert req is not None
    assert req.target_ig == 42
    assert req.var_name is None
    assert req.blocked_reason is not None
    assert "bindable" in req.blocked_reason


def test_request_from_node_set_delta_records_introducible_field_expression() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    use(out);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "current_register": "r29",
            "desired_registers": ["r27"],
            "source": {
                "kind": "field-load",
                "expression": "entries[i].stat_value",
            },
        }],
    }

    req = request_from_node_set_delta(delta, source_text=source)

    assert req is not None
    assert req.var_name is None
    assert req.blocked_reason is not None
    assert req.source_expression == "entries[i].stat_value"
    assert req.source_type == "int"
    assert req.source_kind == "field-load"


def test_request_from_node_set_delta_prefers_introducible_after_blocked_entry() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    use(out);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 41,
                "desired_registers": ["r28"],
                "source": {
                    "kind": "call-result",
                    "expression": "get_value(entries[i].stat_value)",
                },
            },
            {
                "target_ig": 42,
                "desired_registers": ["r27"],
                "source": {
                    "kind": "field-load",
                    "expression": "entries[i].stat_value",
                },
            },
        ],
    }

    default_req = request_from_node_set_delta(delta, source_text=source)
    filtered_req = request_from_node_set_delta(
        delta,
        target_ig=41,
        source_text=source,
    )

    assert default_req is not None
    assert default_req.target_ig == 42
    assert default_req.source_expression == "entries[i].stat_value"
    assert filtered_req is not None
    assert filtered_req.target_ig == 41
    assert filtered_req.source_type is None


def test_generate_node_set_introduce_binding_patches_splits_field_expression() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    use(out);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "current_register": "r29",
            "desired_registers": ["r27"],
            "source": {
                "kind": "field-load",
                "expression": "entries[i].stat_value",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches
    assert patches[0].candidate_id.startswith(
        "node-split-introduce-binding-ig42-"
    )
    candidate_text = "\n".join(patch.patched_source for patch in patches)
    assert "int stat_value_bind_42_0;" in candidate_text
    assert "stat_value_bind_42_0 = entries[i].stat_value;" in candidate_text
    assert "out = stat_value_bind_42_0;" in candidate_text
    assert "stat_value_bind_42_0_split_42_0" in candidate_text
    assert all("@@" in patch.hunk for patch in patches)
    assert all(patch.touched_ranges == ((0, len(source)),) for patch in patches)


def test_generate_node_set_introduce_binding_patches_handles_initialized_declaration() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int out = entries[i].stat_value;\n"
        "    use(out);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "desired_registers": ["r27"],
            "source": {
                "kind": "field-load",
                "expression": "entries[i].stat_value",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    bind_only = next(
        patch for patch in patches
        if patch.candidate_id.endswith("-bind-site0")
    )
    assert "int stat_value_bind_42_0 = entries[i].stat_value;" in (
        bind_only.patched_source
    )
    assert "int out = stat_value_bind_42_0;" in bind_only.patched_source


def test_generate_node_set_introduce_binding_patches_handles_address_cursor() -> None:
    source = (
        "typedef struct NameEntry NameEntry;\n"
        "void fn_test(NameEntry* sorted_names, int i) {\n"
        "    NameEntry* cursor;\n"
        "    cursor = &sorted_names[i];\n"
        "    use(cursor);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 44,
            "desired_registers": ["r25"],
            "source": {
                "kind": "field-load",
                "expression": "&sorted_names[i]",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    candidate_text = "\n".join(patch.patched_source for patch in patches)
    assert "NameEntry* sorted_names_bind_44_0;" in candidate_text
    assert "sorted_names_bind_44_0 = &sorted_names[i];" in candidate_text
    assert "cursor = sorted_names_bind_44_0;" in candidate_text


def test_generate_node_set_introduce_binding_patches_handles_fpr_expression() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 x_spacing;\n"
        "    f32 col_offset;\n"
        "    f32 digit_offset;\n"
        "    digit_offset = x_spacing + col_offset;\n"
        "    use(digit_offset);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 33,
            "desired_registers": ["f28"],
            "source": {
                "kind": "fpr-temp",
                "expression": "x_spacing + col_offset",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    candidate_text = "\n".join(patch.patched_source for patch in patches)
    assert "f32 x_spacing_bind_33_0;" in candidate_text
    assert "x_spacing_bind_33_0 = x_spacing + col_offset;" in candidate_text
    assert "digit_offset = x_spacing_bind_33_0;" in candidate_text


@pytest.mark.parametrize(
    "source_expression, source_text",
    [
        (
            "entries[i].stat_value",
            (
                "typedef struct Entry { int stat_value; } Entry;\n"
                "void fn_test(Entry* entries, int i) {\n"
                "    entries[i].stat_value = 1;\n"
                "}\n"
            ),
        ),
        (
            "get_value(i)",
            (
                "void fn_test(int i) {\n"
                "    int out;\n"
                "    out = get_value(i);\n"
                "}\n"
            ),
        ),
        (
            "i++",
            (
                "void fn_test(int i) {\n"
                "    int out;\n"
                "    out = i++;\n"
                "}\n"
            ),
        ),
        (
            "entries[i].stat_value",
            (
                "typedef struct Entry { int stat_value; } Entry;\n"
                "void fn_test(Entry* entries, int i) {\n"
                "    use(entries[i].stat_value);\n"
                "}\n"
            ),
        ),
        (
            "entries[i].stat_value",
            (
                "typedef struct Entry { int stat_value; } Entry;\n"
                "void fn_test(Entry* entries, int i, int guard) {\n"
                "    int out;\n"
                "    out = guard || entries[i].stat_value;\n"
                "}\n"
            ),
        ),
        (
            "entries[i].stat_value",
            (
                "typedef struct Entry { int stat_value; } Entry;\n"
                "void fn_test(Entry* entries, int i, int guard) {\n"
                "    int out;\n"
                "    out = guard ? entries[i].stat_value : 0;\n"
                "}\n"
            ),
        ),
        (
            "entries[i].stat_value",
            (
                "typedef struct Entry { int stat_value; } Entry;\n"
                "void fn_test(Entry* entries, int i, int guard) {\n"
                "    int out;\n"
                "    if (guard) { out = entries[i].stat_value; }\n"
                "}\n"
            ),
        ),
    ],
)
def test_generate_node_set_introduce_binding_patches_rejects_unsafe_sources(
    source_expression: str,
    source_text: str,
) -> None:
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "desired_registers": ["r27"],
            "source": {
                "kind": "field-load",
                "expression": source_expression,
                "type": "int",
            },
        }],
    }, source_text=source_text)

    patches = generate_node_set_introduce_binding_patches(
        source_text, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches == []


def test_generate_node_set_split_patches_emits_alias_and_lifetime_candidates() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    int out;\n"
        "    holder = make();\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=2
    )

    ids = {patch.candidate_id for patch in patches}
    assert "node-split-alias-holder-ig40-use0" in ids
    assert "node-split-lifetime-holder-ig40-use0" in ids
    assert len({patch.patched_source for patch in patches}) == len(patches)
    assert all("@@" in patch.hunk for patch in patches)


def test_node_set_patch_order_prioritizes_new_families_before_high_volume_legacy() -> None:
    source = "void fn_test(void) { int x; }\n"
    patches = [
        CandidatePatch(f"node-split-alias-holder-ig40-use{i}", source, "old alias", ((0, 0),))
        for i in range(8)
    ] + [
        CandidatePatch("node-split-prologue-reorder-holder-ig40-b0-s10", source + "/*a*/", "new reorder", ((0, 0),)),
        CandidatePatch("node-split-assignment-chain-holder-ig40-b0-s20-o0", source + "/*b*/", "new chain", ((0, 0),)),
        CandidatePatch("node-split-operand-alias-holder-ig40-b0-s30-o0", source + "/*c*/", "new alias", ((0, 0),)),
        CandidatePatch("node-split-block-scope-holder-ig40-b0-s40-w2", source + "/*d*/", "new scope", ((0, 0),)),
        CandidatePatch("node-split-combo-holder-ig40-prologue-reorder+operand-alias-c0-a1b2c3", source + "/*e*/", "combo", ((0, 0),)),
    ]

    ordered = node_set_split._order_node_set_patches_for_search(patches)
    first_families = [
        node_set_split._node_set_candidate_family(patch.candidate_id)
        for patch in ordered[:5]
    ]

    assert first_families == [
        "combo",
        "prologue-reorder",
        "assignment-chain",
        "operand-alias",
        "block-scope",
    ]


def test_node_set_simple_assignment_records_require_immediate_block_and_safe_rhs() -> None:
    source = (
        "void fn_test(void) {\n"
        "    f32 a;\n"
        "    f32 b;\n"
        "    f32 c;\n"
        "    a = b;\n"
        "    {\n"
        "        b = c;\n"
        "    }\n"
        "    c = call(a);\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=1)

    by_lhs = {record.lhs: record for record in records}
    assert by_lhs["a"].block_id == 0
    assert by_lhs["b"].block_id != by_lhs["a"].block_id
    assert "c" not in by_lhs


def test_node_set_simple_assignment_records_extracts_mndiagram_style_fpr_prologue() -> None:
    source = (
        "typedef float f32;\n"
        "typedef unsigned char u8;\n"
        "typedef signed int s32;\n"
        "typedef struct Diagram { void* jobj; } Diagram;\n"
        "void fn_test(Diagram* arg0, u8 arg1, u8 arg2) {\n"
        "    Diagram* data;\n"
        "    void* jobj;\n"
        "    s32 digit_count;\n"
        "    f32 x_spacing;\n"
        "    f32 y_spacing;\n"
        "    f32 y_offset;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    u8 col = arg1;\n"
        "    u8 row = arg2;\n"
        "\n"
        "    data = arg0->jobj;\n"
        "    jobj = make_jobj(data);\n"
        "    digit_count = get_digit_count();\n"
        "    x_spacing = 0.5f;\n"
        "    y_spacing = 2.0f;\n"
        "    y_offset = 3.0f;\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    row_offset = y_offset * (f32) row;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "\n"
        "    if (digit_count != 0) {\n"
        "        use(jobj, row_offset_adj);\n"
        "    }\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(
        source, "fn_test", class_id=1
    )

    by_lhs = {record.lhs: record for record in records}
    assert "col_offset" in by_lhs
    assert "row_offset" in by_lhs
    assert "row_offset_adj" in by_lhs
    assert "row_offset" in by_lhs["row_offset_adj"].reads


def test_node_set_simple_assignment_records_rejects_out_of_scope_inner_local_read() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    {\n"
        "        int b;\n"
        "    }\n"
        "    a = b;\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=0)

    assert records == []


def test_node_set_simple_assignment_records_rejects_else_block_local_after_scope_exit() -> None:
    source = (
        "void fn_test(int cond) {\n"
        "    int a;\n"
        "    if (cond) {\n"
        "    } else {\n"
        "        int b;\n"
        "    }\n"
        "    a = b;\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=0)

    assert records == []


def test_node_set_simple_assignment_records_skips_else_block_assignments() -> None:
    source = (
        "void fn_test(int cond) {\n"
        "    int a;\n"
        "    int b;\n"
        "    if (cond) {\n"
        "        a = b;\n"
        "    } else {\n"
        "        b = a;\n"
        "    }\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=0)

    assert records == []


def test_node_set_simple_assignment_records_rejects_multiline_assignment() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    a =\n"
        "        b;\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=0)

    assert records == []


def test_node_set_simple_assignment_records_rejects_unsafe_initialized_declaration() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int* p;\n"
        "    int a = *p;\n"
        "    int b;\n"
        "    b = a;\n"
        "}\n"
    )

    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=0)

    assert records == []


@pytest.mark.parametrize(
    "source",
    [
        "void fn_test(void) { int a; int b; switch (a) { case 0: b = a; } }\n",
        "void fn_test(void) { int a; int b; a = b; /* preserve order */ b = a; }\n",
        "void fn_test(void) { int a; int b; a = (b, 1); b = a; }\n",
        "void fn_test(void) { int a; int b; a = b ? 1 : 2; b = a; }\n",
        "void fn_test(void) { int a; int b; a = b && 1; b = a; }\n",
        "void fn_test(void) { volatile int a; int b; a = b; b = a; }\n",
        "void fn_test(void) { int a; int b; take(&a); b = a; }\n",
        "void fn_test(void) { int a; int b; a++; b = a; }\n",
        "void fn_test(void) { int a; int b[2]; a = b[0]; b[1] = a; }\n",
        "void fn_test(void) { int a; int* p; a = *p; use(a); }\n",
        "void fn_test(void) { int a; int b; a += b; b = a; }\n",
    ],
)
def test_node_set_simple_assignment_records_reject_spec_unsafe_regions(source: str) -> None:
    records = node_set_split._simple_assignment_records(source, "fn_test", class_id=0)

    assert records == []


def test_generate_node_set_split_patches_emits_decl_order_candidates() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int first;\n"
        "    int holder;\n"
        "    int out;\n"
        "    first = make();\n"
        "    holder = first + 1;\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    ids = {patch.candidate_id for patch in patches}
    assert "node-split-alias-holder-ig40-use0" in ids
    assert "node-split-lifetime-holder-ig40-use0" in ids
    assert any(
        candidate_id.startswith("node-split-decl-order-holder-ig40-")
        for candidate_id in ids
    )
    assert any(
        patch.patched_source.index("int holder;")
        < patch.patched_source.index("int first;")
        for patch in patches
        if patch.candidate_id.startswith("node-split-decl-order-holder-ig40-")
    )


def test_generate_node_set_split_patches_keeps_decl_order_that_moves_target() -> None:
    source = (
        "void fn_test(void) {\n"
        "    float other;\n"
        "    int holder;\n"
        "    int scratch;\n"
        "    holder = make();\n"
        "    scratch = holder + 1;\n"
        "    other = scratch;\n"
        "    use(other, holder, scratch);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    decl_order_patches = [
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-decl-order-holder-ig40-")
    ]
    assert any(
        patch.patched_source.index("int holder;")
        < patch.patched_source.index("int scratch;")
        < patch.patched_source.index("float other;")
        for patch in decl_order_patches
    )


def test_generate_node_set_split_patches_skips_decl_order_initializer_dependency() -> None:
    source = (
        "void fn_test(HSD_GObj* gobj) {\n"
        "    Item* ip = GET_ITEM(gobj);\n"
        "    Attrs* attr = ip->attrs;\n"
        "    int scratch;\n"
        "    scratch = attr->x0;\n"
        "    use(ip, attr, scratch);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="attr",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    decl_order_patches = [
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-decl-order-attr-ig40-")
    ]

    assert decl_order_patches
    for patch in decl_order_patches:
        assert patch.patched_source.index("Item* ip = GET_ITEM(gobj);") < (
            patch.patched_source.index("Attrs* attr = ip->attrs;")
        )


def test_generate_node_set_split_patches_keeps_aliases_when_decl_order_fails(
    monkeypatch,
) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    int out;\n"
        "    holder = make();\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    def raise_decl_scope_error(*_args, **_kwargs):
        raise RuntimeError("tree-sitter unavailable")

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.get_decl_names_by_scope",
        raise_decl_scope_error,
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    ids = {patch.candidate_id for patch in patches}
    assert "node-split-alias-holder-ig40-use0" in ids
    assert "node-split-lifetime-holder-ig40-use0" in ids
    assert not any(
        candidate_id.startswith("node-split-decl-order-holder-ig40-")
        for candidate_id in ids
    )


def test_generate_node_set_split_patches_emits_per_loop_rename_candidate() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int i;\n"
        "    int j;\n"
        "    int holder;\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        holder = make(i);\n"
        "        use(holder);\n"
        "    }\n"
        "    for (j = 0; j < 2; j++) {\n"
        "        holder = make(j);\n"
        "        use(holder);\n"
        "    }\n"
        "    holder = 0;\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    patch = next(
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-loop-rename-holder-ig40-")
    )

    assert "int holder_loop_40_0;\n" in patch.patched_source
    assert "int holder_loop_40_1;\n" in patch.patched_source
    assert (
        "for (i = 0; i < 2; i++) {\n"
        "        holder_loop_40_0 = make(i);\n"
        "        use(holder_loop_40_0);\n"
        "    }\n"
    ) in patch.patched_source
    assert (
        "for (j = 0; j < 2; j++) {\n"
        "        holder_loop_40_1 = make(j);\n"
        "        use(holder_loop_40_1);\n"
        "    }\n"
    ) in patch.patched_source
    assert "    holder = 0;\n" in patch.patched_source


def test_generate_node_set_split_patches_emits_per_loop_rename_candidate_for_while_loops() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int i;\n"
        "    int j;\n"
        "    int holder;\n"
        "    while (i < 2) {\n"
        "        holder = make(i);\n"
        "        use(holder);\n"
        "        i++;\n"
        "    }\n"
        "    while (j < 2) {\n"
        "        holder = make(j);\n"
        "        use(holder);\n"
        "        j++;\n"
        "    }\n"
        "    holder = 0;\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    patch = next(
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-loop-rename-holder-ig40-")
    )

    assert "int holder_loop_40_0;\n" in patch.patched_source
    assert "int holder_loop_40_1;\n" in patch.patched_source
    assert (
        "while (i < 2) {\n"
        "        holder_loop_40_0 = make(i);\n"
        "        use(holder_loop_40_0);\n"
        "        i++;\n"
        "    }\n"
    ) in patch.patched_source
    assert (
        "while (j < 2) {\n"
        "        holder_loop_40_1 = make(j);\n"
        "        use(holder_loop_40_1);\n"
        "        j++;\n"
        "    }\n"
    ) in patch.patched_source
    assert "    holder = 0;\n" in patch.patched_source


def test_generate_node_set_split_patches_emits_reassoc_candidate() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int idx;\n"
        "    int base;\n"
        "    int holder;\n"
        "    holder = idx + base;\n"
        "    use(holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    patch = next(
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-reassoc-holder-ig40-")
    )

    assert "    holder = base + idx;\n" in patch.patched_source
    assert "    use(holder);\n" in patch.patched_source


@pytest.mark.parametrize("type_name", ["float", "f32", "double", "f64"])
def test_generate_node_set_split_patches_emits_typed_fpr_reassoc_candidate(
    type_name: str,
) -> None:
    source = (
        "void fn_test(void) {\n"
        f"    {type_name} a;\n"
        f"    {type_name} b;\n"
        f"    {type_name} holder;\n"
        "    holder = a + b;\n"
        "    use(holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=1,
        target_ig=40,
        current_reg="f31",
        target_reg="f30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    patch = next(
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-reassoc-holder-ig40-")
    )

    assert "    holder = b + a;\n" in patch.patched_source


def test_generate_node_set_split_patches_emits_prologue_reorder_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    f32 y_offset;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset;\n"
        "    f32 col;\n"
        "    f32 rowf;\n"
        "    col_offset = y_spacing * col;\n"
        "    row_offset = y_offset * rowf;\n"
        "    use(col_offset, row_offset);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test", 1, 33, target_reg="f28", var_name="row_offset"
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith(
            "node-split-prologue-reorder-row_offset-ig33-"
        )
    )

    assert patch.patched_source.index(
        "row_offset = y_offset * rowf;"
    ) < patch.patched_source.index("col_offset = y_spacing * col;")


def test_generate_node_set_split_patches_prologue_reorder_scans_neighboring_assignments_for_request_var(
) -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    f32 y_offset;\n"
        "    f32 col;\n"
        "    f32 rowf;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    col_offset = y_spacing * col;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test", 1, 33, target_reg="f28", var_name="row_offset_adj"
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith(
            "node-split-prologue-reorder-row_offset_adj-ig33-"
        )
    )

    assert patch.patched_source.index(
        "row_offset = y_offset * rowf;"
    ) < patch.patched_source.index("col_offset = y_spacing * col;")


def test_generate_node_set_split_patches_emits_assignment_chain_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = y_offset * rowf - 0.4f;\n"
        "    use(row_offset_adj);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test", 1, 33, target_reg="f28", var_name="row_offset_adj"
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith(
            "node-split-assignment-chain-row_offset_adj-ig33-"
        )
    )

    assert "row_offset_adj = row_offset - 0.4f;" in patch.patched_source


def test_generate_node_set_split_patches_emits_operand_alias_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    f32 col;\n"
        "    f32 col_offset;\n"
        "    col_offset = y_spacing * col;\n"
        "    use(col_offset);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        1,
        33,
        target_reg="f28",
        var_name="col_offset",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith(
            "node-split-operand-alias-col_offset-ig33-"
        )
    )

    assert "f32 y_spacing_alias_33_0;" in patch.patched_source
    assert "y_spacing_alias_33_0 = y_spacing;" in patch.patched_source
    assert "col_offset = y_spacing_alias_33_0 * col;" in patch.patched_source


def test_generate_node_set_split_patches_operand_alias_rejects_mixed_declaration_statement_block(
) -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_spacing;\n"
        "    use(y_spacing);\n"
        "    f32 col_offset;\n"
        "    col_offset = y_spacing;\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        1,
        33,
        target_reg="f28",
        var_name="col_offset",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )

    assert not any(
        p.candidate_id.startswith(
            "node-split-operand-alias-col_offset-ig33-"
        )
        for p in patches
    )


def test_generate_node_set_split_patches_operand_alias_handles_pointer_operands(
) -> None:
    source = (
        "typedef struct Entry Entry;\n"
        "void fn_test(Entry* cursor) {\n"
        "    Entry* holder;\n"
        "    holder = cursor;\n"
        "    use(holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith(
            "node-split-operand-alias-holder-ig40-"
        )
    )

    assert "Entry* cursor_alias_40_0;" in patch.patched_source
    assert "cursor_alias_40_0 = cursor;" in patch.patched_source
    assert "holder = cursor_alias_40_0;" in patch.patched_source


def test_generate_node_set_split_patches_operand_alias_preserves_pointer_pointee_const(
) -> None:
    source = (
        "typedef struct Entry Entry;\n"
        "void fn_test(const Entry* cursor) {\n"
        "    const Entry* holder;\n"
        "    holder = cursor;\n"
        "    use(holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith(
            "node-split-operand-alias-holder-ig40-"
        )
    )

    assert "const Entry* cursor_alias_40_0;" in patch.patched_source
    assert "    Entry* cursor_alias_40_0;" not in patch.patched_source


def test_generate_node_set_split_patches_operand_alias_strips_top_level_pointer_const(
) -> None:
    source = (
        "typedef struct Entry Entry;\n"
        "void fn_test(Entry* const cursor) {\n"
        "    Entry* holder;\n"
        "    holder = cursor;\n"
        "    use(holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith(
            "node-split-operand-alias-holder-ig40-"
        )
    )

    assert "Entry* cursor_alias_40_0;" in patch.patched_source
    assert "Entry* const cursor_alias_40_0;" not in patch.patched_source


def test_generate_node_set_split_patches_operand_alias_rejects_internal_pointer_const(
) -> None:
    source = (
        "typedef struct Entry Entry;\n"
        "void fn_test(Entry* const* cursor) {\n"
        "    Entry* const* holder;\n"
        "    holder = cursor;\n"
        "    use(holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )

    assert not any(
        p.candidate_id.startswith(
            "node-split-operand-alias-holder-ig40-"
        )
        for p in patches
    )


def test_generate_node_set_split_patches_operand_alias_rewrites_one_repeated_operand(
) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int value;\n"
        "    int out;\n"
        "    out = value + value;\n"
        "    use(out);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="out",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    alias_patches = [
        p
        for p in patches
        if p.candidate_id.startswith("node-split-operand-alias-out-ig40-")
    ]

    assert len(alias_patches) == 2
    assert "out = value_alias_40_0 + value;" in alias_patches[0].patched_source
    assert "out = value + value_alias_40_1;" in alias_patches[1].patched_source
    assert "out = value_alias_40_0 + value_alias_40_0;" not in (
        alias_patches[0].patched_source
    )


def test_generate_node_set_split_patches_operand_alias_uses_unique_alias_name(
) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int value;\n"
        "    int value_alias_40_0;\n"
        "    int out;\n"
        "    out = value;\n"
        "    use(out, value_alias_40_0);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="out",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith("node-split-operand-alias-out-ig40-")
    )

    assert "int value_alias_40_0_1;" in patch.patched_source
    assert "value_alias_40_0_1 = value;" in patch.patched_source
    assert "out = value_alias_40_0_1;" in patch.patched_source


def test_generate_node_set_split_patches_operand_alias_rejects_shadowed_operand_name(
) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int value;\n"
        "    int out;\n"
        "    {\n"
        "        int value;\n"
        "        use(value);\n"
        "    }\n"
        "    out = value;\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="out",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )

    assert not any(
        p.candidate_id.startswith("node-split-operand-alias-out-ig40-")
        for p in patches
    )


def test_generate_node_set_split_patches_operand_alias_rejects_same_line_target(
) -> None:
    source = "void fn_test(void) { int value; int out; out = value; use(out); }\n"
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="out",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )

    assert not any(
        p.candidate_id.startswith("node-split-operand-alias-out-ig40-")
        for p in patches
    )


def test_generate_node_set_split_patches_keeps_existing_patches_when_operand_alias_fails(
    monkeypatch,
) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    int out;\n"
        "    holder = make();\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r30",
        var_name="holder",
    )

    def raise_operand_alias_error(*_args, **_kwargs):
        raise RuntimeError("forced operand-alias failure")

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split._node_set_unique_scalar_bindings",
        raise_operand_alias_error,
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    ids = {patch.candidate_id for patch in patches}

    assert "node-split-alias-holder-ig40-use0" in ids
    assert "node-split-lifetime-holder-ig40-use0" in ids
    assert not any(
        candidate_id.startswith("node-split-operand-alias-holder-ig40-")
        for candidate_id in ids
    )


@pytest.mark.parametrize(
    "source",
    [
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; y_offset = 1.0f; out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; double rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "void fn_test(void) { int a; unsigned int b; int tmp; int out; "
            "tmp = a + b; out = a + b + 1; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; if (rowf) { y_offset = 1.0f; } "
            "out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 tmp; f32 out; "
            "row_offset = y_offset * rowf; tmp = (y_offset = 1.0f); "
            "out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 tmp; f32 out; "
            "row_offset = y_offset * rowf; tmp = ++y_offset; "
            "out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; { f32 y_offset; use(y_offset); } "
            "out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; if (rowf) { f32 y_offset; use(y_offset); } "
            "out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; (y_offset) = 1.0f; "
            "out = y_offset * rowf - 0.4f; }\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void) { f32 y_offset; f32 rowf; f32 row_offset; f32 out; "
            "row_offset = y_offset * rowf; (y_offset)++; "
            "out = y_offset * rowf - 0.4f; }\n"
        ),
    ],
)
def test_generate_node_set_split_patches_assignment_chain_rejects_unsafe_rewrites(
    source: str,
) -> None:
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="out")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-assignment-chain-out-ig33-")
        for p in patches
    )


def test_generate_node_set_split_patches_assignment_chain_rejects_gpr_signedness_mix() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    unsigned int b;\n"
        "    int tmp;\n"
        "    int out;\n"
        "    tmp = a + b;\n"
        "    out = a + b + 1;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="out")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-assignment-chain-out-ig40-")
        for p in patches
    )


def test_generate_node_set_split_patches_assignment_chain_rejects_subtraction_boundary() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    int c;\n"
        "    int tmp;\n"
        "    int out;\n"
        "    tmp = a + b;\n"
        "    out = c - a + b;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="out")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-assignment-chain-out-ig40-")
        for p in patches
    )


def test_generate_node_set_split_patches_assignment_chain_rejects_additive_regrouping() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 a;\n"
        "    f32 b;\n"
        "    f32 c;\n"
        "    f32 tmp;\n"
        "    f32 out;\n"
        "    tmp = a + b;\n"
        "    out = c + a + b;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 40, target_reg="f30", var_name="out")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-assignment-chain-out-ig40-")
        for p in patches
    )


@pytest.mark.parametrize(
    "operator",
    ["<<", "<"],
)
def test_generate_node_set_split_patches_assignment_chain_rejects_precedence_sensitive_operators(
    operator: str,
) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    int tmp;\n"
        "    int out;\n"
        f"    tmp = a {operator} b;\n"
        f"    out = a {operator} b + 1;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="out")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-assignment-chain-out-ig40-")
        for p in patches
    )


def test_generate_node_set_split_patches_emits_block_scope_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 a;\n"
        "    f32 b;\n"
        "    f32 c;\n"
        "    a = b;\n"
        "    c = a;\n"
        "    use(c);\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="a")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )
    patch = next(
        p
        for p in patches
        if p.candidate_id.startswith("node-split-block-scope-a-ig33-")
    )

    assert "{\n    a = b;\n    c = a;\n}" in patch.patched_source


def test_generate_node_set_split_patches_reorder_and_scope_reject_mixed_statement_lines() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int x;\n"
        "    int a;\n"
        "    int b;\n"
        "    int c;\n"
        "    x = call(); a = b;\n"
        "    c = a;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="a")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-prologue-reorder-a-ig40-")
        for p in patches
    )
    assert not any(
        p.candidate_id.startswith("node-split-block-scope-a-ig40-")
        for p in patches
    )


def test_generate_node_set_split_patches_reorder_and_scope_reject_trailing_same_line_statement() -> None:
    source = (
        "void fn_test(void) {\n"
        "    int x;\n"
        "    int a;\n"
        "    int b;\n"
        "    int c;\n"
        "    a = b; x = call();\n"
        "    c = a;\n"
        "}\n"
    )
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="a")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-prologue-reorder-a-ig40-")
        for p in patches
    )
    assert not any(
        p.candidate_id.startswith("node-split-block-scope-a-ig40-")
        for p in patches
    )


@pytest.mark.parametrize(
    "source",
    [
        "void fn_test(void) { int a; int b; a = b; if (a) { b = a; } }\n",
        "void fn_test(void) { int a; int b; a = call(); b = a; }\n",
        "void fn_test(void) { int a; int b; a = obj.x; b = a; }\n",
        "void fn_test(void) { int a; int b; a = b; label: b = a; }\n",
        "void fn_test(void) { int a; int b; a = b; #if 0\n b = a;\n#endif\n }\n",
    ],
)
def test_generate_node_set_split_patches_reorder_and_scope_reject_unsafe_regions(
    source: str,
) -> None:
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="a")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        p.candidate_id.startswith("node-split-prologue-reorder-a-ig40-")
        for p in patches
    )
    assert not any(
        p.candidate_id.startswith("node-split-block-scope-a-ig40-")
        for p in patches
    )


def test_generate_node_set_split_patches_prologue_reorder_rejects_adjacent_dependency() -> None:
    source = "void fn_test(void) { int a; int b; a = b; b = a; }\n"
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="a")

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        patch.candidate_id.startswith("node-split-prologue-reorder-a-ig40-")
        for patch in patches
    )


@pytest.mark.parametrize(
    "source",
    [
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 holder;\n"
            "    holder = a + 1;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 holder;\n"
            "    holder = a + 1.0f;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    int b;\n"
            "    f32 holder;\n"
            "    holder = a + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    holder = (f32) a + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    holder = get(a) + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    struct Pair { f32 x; } p;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    holder = p.x + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 c;\n"
            "    f32 holder;\n"
            "    holder = a + b + c;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    {\n"
            "        f32 holder;\n"
            "        holder = a + b;\n"
            "    }\n"
            "    holder = a + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
    ],
)
def test_generate_node_set_split_patches_fpr_reassoc_rejects_unsafe_sources(
    source: str,
) -> None:
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=1,
        target_ig=40,
        current_reg="f31",
        target_reg="f30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        patch.candidate_id.startswith("node-split-reassoc-holder-ig40-")
        for patch in patches
    )


def test_fpr_node_set_delta_materializes_mndiagram_80241e78_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(void* arg0, unsigned char col, unsigned char row, int arg3) {\n"
        "    f32 x_spacing;\n"
        "    f32 col_offset;\n"
        "    f32 digit_offset;\n"
        "    int i;\n"
        "    digit_offset = x_spacing + col_offset;\n"
        "    for (i = 0; i < arg3; i++) {\n"
        "        use(digit_offset, i);\n"
        "    }\n"
        "}\n"
    )
    delta = {
        "function": "mnDiagram_80241E78",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 33,
            "current_register": "f31",
            "desired_registers": ["f28"],
            "source": {"name": "digit_offset", "expression": "digit_offset"},
        }],
    }
    req = request_from_node_set_delta(delta, source_text=source)

    patches = generate_node_set_split_patches(
        source,
        "mnDiagram_80241E78",
        req,
        max_read_sites=1,
    )

    assert req.class_id == 1
    assert req.current_reg == "f31"
    assert req.target_reg == "f28"
    assert any(
        patch.candidate_id.startswith(
            "node-split-reassoc-digit_offset-ig33-"
        )
        for patch in patches
    )


@pytest.mark.parametrize(
    "source",
    [
        (
            "void fn_test(void) {\n"
            "    int idx;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder = make(idx) + base;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int idx;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder = (int) idx + base;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    Obj obj;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder = obj.value + base;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    Obj *obj;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder = obj->value + base;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int idx;\n"
            "    int arr[2];\n"
            "    int holder;\n"
            "    holder = arr[idx] + 1;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int idx;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder += idx + base;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int idx;\n"
            "    int base;\n"
            "    int extra;\n"
            "    int holder;\n"
            "    holder = idx + base + extra;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int *ptr;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder = *ptr + base;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int idx;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder = -idx + base;\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int idx;\n"
            "    int base;\n"
            "    int holder;\n"
            "    holder = idx++ + base;\n"
            "}\n"
        ),
    ],
)
def test_generate_node_set_split_patches_reassoc_rejects(source: str) -> None:
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        patch.candidate_id.startswith("node-split-reassoc-holder-ig40-")
        for patch in patches
    )


@pytest.mark.parametrize(
    "source",
    [
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "    use(&holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(&(holder));\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    while (holder) {\n"
            "        holder = 0;\n"
            "    }\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    do {\n"
            "        holder = 0;\n"
            "    } while (holder);\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int holder;\n"
            "    for (holder = 0; holder < 2; holder++) {\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (holder = 0; holder < 2; holder++)\n"
            "        use(holder);\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = holder + make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    use(holder);\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        use(holder);\n"
            "        holder = make(j);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int k;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        for (k = 0; k < 2; k++)\n"
            "            use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int cond;\n"
            "    int holder;\n"
            "    if (cond)\n"
            "        for (i = 0; i < 2; i++) {\n"
            "            holder = make(i);\n"
            "            use(holder);\n"
            "        }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int cond;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        if (cond)\n"
            "            use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int cond;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        if (cond) {\n"
            "            use(holder);\n"
            "        }\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    Obj obj;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        use(holder);\n"
            "        use(obj.holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "        use(obj->holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        return holder;\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "        goto holder;\n"
            "holder:\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    int i;\n"
            "    int j;\n"
            "    int holder;\n"
            "    for (i = 0; i < 2; i++) {\n"
            "        holder = make(i);\n"
            "other:\n"
            "holder:\n"
            "        use(holder);\n"
            "    }\n"
            "    for (j = 0; j < 2; j++) {\n"
            "        holder = make(j);\n"
            "        use(holder);\n"
            "    }\n"
            "}\n"
        ),
    ],
)
def test_generate_node_set_split_patches_per_loop_rename_rejects(source: str) -> None:
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        patch.candidate_id.startswith("node-split-loop-rename-holder-ig40-")
        for patch in patches
    )


def test_generate_node_set_split_patches_discards_partial_decl_order_on_failure(
    monkeypatch,
) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int first;\n"
        "    int holder;\n"
        "    int out;\n"
        "    first = make();\n"
        "    holder = first + 1;\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    from src.mwcc_debug.source_patch import reorder_decls_in_function_scope

    calls = 0

    def reorder_once_then_fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return reorder_decls_in_function_scope(*args, **kwargs)
        raise RuntimeError("late decl reorder failure")

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.reorder_decls_in_function_scope",
        reorder_once_then_fail,
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    ids = {patch.candidate_id for patch in patches}
    assert calls > 1
    assert "node-split-alias-holder-ig40-use0" in ids
    assert "node-split-lifetime-holder-ig40-use0" in ids
    assert not any(
        candidate_id.startswith("node-split-decl-order-holder-ig40-")
        for candidate_id in ids
    )


def test_evaluate_node_set_split_signature_realized_requires_target_reg_no_spills() -> None:
    baseline = _signature(assigned_regs=frozenset({(40, 31)}))
    candidate = _signature(assigned_regs=frozenset({(40, 30)}))
    req = NodeSetSplitRequest(
        "fn_test",
        1,
        40,
        current_reg="f31",
        target_reg="f30",
        var_name="holder",
    )

    result = evaluate_node_set_split_signature(baseline, candidate, req)

    assert result["status"] == "realized"
    assert result["target_reg_hit"] is True
    assert result["new_spills"] == []


def test_evaluate_node_set_split_signature_spill_regression_overrides_register_match() -> None:
    baseline = _signature(assigned_regs=frozenset({(40, 31)}))
    candidate = _signature(
        assigned_regs=frozenset({(40, 30)}),
        spill_set=frozenset({44}),
    )
    req = NodeSetSplitRequest(
        "fn_test",
        1,
        40,
        current_reg="f31",
        target_reg="f30",
        var_name="holder",
    )

    result = evaluate_node_set_split_signature(baseline, candidate, req)

    assert result["status"] == "spill-regression"
    assert result["target_reg_hit"] is True
    assert result["new_spills"] == [44]


def test_summarize_node_set_split_scores_uses_objective_and_threshold() -> None:
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="holder")
    patches = [
        CandidatePatch("bad", "bad source", "bad", ((0, 0),), hunk="@@ bad"),
        CandidatePatch("good", "good source", "good", ((0, 0),), hunk="@@ good"),
    ]
    bad_score = CandidateScore(
        "bad",
        compile_ok=True,
        checkdiff_pct=99.0,
        checkdiff_delta=5.0,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="improved",
    )
    good_score = CandidateScore(
        "good",
        compile_ok=True,
        checkdiff_pct=95.0,
        checkdiff_delta=1.0,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="scored",
    )
    scored_candidates = [
        {"score": bad_score, "objective": {"status": "wrong-register"}},
        {"score": good_score, "objective": {"status": "realized"}},
    ]

    below_threshold = summarize_node_set_split_scores(
        "fn_test", req, patches, scored_candidates, threshold=1.1
    )
    at_threshold = summarize_node_set_split_scores(
        "fn_test", req, patches, scored_candidates, threshold=1.0
    )
    blocked = summarize_node_set_split_scores(
        "fn_test", req, [], scored_candidates, threshold=1.0
    )

    assert below_threshold["status"] == "exhausted"
    assert at_threshold["status"] == "improved"
    assert at_threshold["best_candidate_id"] == "good"
    assert blocked["status"] == "blocked"


def test_summarize_node_set_split_scores_reports_candidate_limit() -> None:
    req = NodeSetSplitRequest("fn_test", 0, 40, target_reg="r30", var_name="holder")
    patches = [
        CandidatePatch("one", "source 1", "one", ((0, 0),), hunk="@@ one"),
        CandidatePatch("two", "source 2", "two", ((0, 0),), hunk="@@ two"),
        CandidatePatch("three", "source 3", "three", ((0, 0),), hunk="@@ three"),
    ]
    score = CandidateScore(
        "one",
        compile_ok=True,
        checkdiff_pct=None,
        checkdiff_delta=None,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="objective-failed",
    )

    summary = summarize_node_set_split_scores(
        "fn_test",
        req,
        patches,
        [{"score": score, "objective": {"status": "wrong-register"}}],
        threshold=1.0,
        stop_reason="candidate-limit",
        candidate_limit=1,
        budget_seconds=30.0,
        elapsed_seconds=2.5,
    )

    assert summary["status"] == "exhausted"
    assert summary["stop_condition"]["kind"] == "candidate-limit"
    assert summary["exhaustive"] is False
    assert summary["candidate_limit"] == 1
    assert summary["generated_count"] == 3
    assert summary["scored_count"] == 1
    assert summary["evaluated_count"] == 1
    assert summary["checkdiff_scored_count"] == 0
    assert summary["pending_count"] == 2
    assert summary["omitted_count"] == 2
    assert "rerun" in " ".join(summary["next_steps"])


# ---------------------------------------------------------------------------
# #702 — coupled multi-ig realizer
# ---------------------------------------------------------------------------

_COUPLED_DELTA = {
    "kind": "node-set-delta",
    "function": "fn_test",
    "class_id": 0,
    "missing_virtuals": [
        {
            "target_ig": 34,
            "current_register": "r24",
            "desired_registers": ["r27"],
            "source": {"name": "holder", "expression": "holder"},
        },
        {
            "target_ig": 44,
            "current_register": "r27",
            "desired_registers": ["r25"],
            "source": {"name": "other", "expression": "other"},
        },
    ],
}

_TWO_VAR_SOURCE = (
    "void fn_test(void) {\n"
    "    int holder;\n"
    "    int other;\n"
    "    int out;\n"
    "    holder = make();\n"
    "    other = build();\n"
    "    out = holder + other;\n"
    "    use(out, holder, other);\n"
    "}\n"
)


def test_requests_from_node_set_delta_returns_all_bindable_in_order() -> None:
    reqs = requests_from_node_set_delta(_COUPLED_DELTA)

    assert [r.target_ig for r in reqs] == [34, 44]
    assert [r.var_name for r in reqs] == ["holder", "other"]
    assert [r.target_reg for r in reqs] == ["r27", "r25"]
    assert all(r.blocked_reason is None for r in reqs)
    assert all(r.class_id == 0 for r in reqs)


def test_requests_from_node_set_delta_preserves_fpr_class_and_registers() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [
            {
                "target_ig": 33,
                "current_register": "f31",
                "desired_registers": ["f28"],
                "source": {"name": "row_offset", "expression": "row_offset"},
            }
        ],
    }

    reqs = requests_from_node_set_delta(delta)

    assert len(reqs) == 1
    assert reqs[0].class_id == 1
    assert reqs[0].current_reg == "f31"
    assert reqs[0].target_reg == "f28"
    assert reqs[0].var_name == "row_offset"


def test_requests_from_node_set_delta_preserves_alternate_desired_registers() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 49,
                "current_register": "r29",
                "desired_registers": ["r25", "r26"],
                "source": {"name": "flag", "expression": "flag"},
            }
        ],
    }

    reqs = requests_from_node_set_delta(delta)

    assert len(reqs) == 1
    assert reqs[0].target_reg == "r25"
    assert reqs[0].target_regs == ("r25", "r26")


def test_requests_from_node_set_delta_dedups_by_target_ig() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {"target_ig": 34, "desired_registers": ["r27"],
             "source": {"name": "holder", "expression": "holder"}},
            {"target_ig": 34, "desired_registers": ["r26"],
             "source": {"name": "holder", "expression": "holder"}},
            {"target_ig": 44, "desired_registers": ["r25"],
             "source": {"name": "other", "expression": "other"}},
        ],
    }

    reqs = requests_from_node_set_delta(delta)

    assert [r.target_ig for r in reqs] == [34, 44]
    # first occurrence of ig34 wins (r27, not r26)
    assert reqs[0].target_reg == "r27"


def test_requests_from_node_set_delta_skips_unbindable_and_caps() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {"target_ig": 1, "desired_registers": ["r27"],
             "source": {"name": "a", "expression": "a"}},
            # field-expression name is not bindable
            {"target_ig": 2, "desired_registers": ["r26"],
             "source": {"name": "p", "expression": "p->field"}},
            {"target_ig": 3, "desired_registers": ["r25"],
             "source": {"name": "b", "expression": "b"}},
            {"target_ig": 4, "desired_registers": ["r24"],
             "source": {"name": "c", "expression": "c"}},
        ],
    }

    reqs = requests_from_node_set_delta(delta, max_requests=2)

    # ig2 dropped (unbindable field expr); capped to 2 -> [1, 3]
    assert [r.target_ig for r in reqs] == [1, 3]


def test_requests_from_node_set_delta_can_include_introducible_entries() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int holder;\n"
        "    holder = entries[i].stat_value;\n"
        "    use(holder);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {"target_ig": 1, "desired_registers": ["r27"],
             "source": {"name": "holder", "expression": "holder"}},
            {"target_ig": 2, "desired_registers": ["r26"],
             "source": {
                 "kind": "field-load",
                 "expression": "entries[i].stat_value",
             }},
            {"target_ig": 3, "desired_registers": ["r25"],
             "source": {
                 "kind": "implicit-temp",
                 "expression": "add r3,r4,r5",
             }},
        ],
    }

    reqs = requests_from_node_set_delta(
        delta,
        source_text=source,
        include_introducible=True,
        max_requests=0,
    )

    assert [r.target_ig for r in reqs] == [1, 2]
    assert reqs[0].var_name == "holder"
    assert reqs[1].var_name is None
    assert reqs[1].source_expression == "entries[i].stat_value"
    assert reqs[1].source_type == "int"


def test_requests_from_node_set_delta_rejects_unsafe_introducible_entries() -> None:
    source = (
        "void fn_test(int i) {\n"
        "    int holder;\n"
        "    holder = get_value(i);\n"
        "    use(holder);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {"target_ig": 1, "desired_registers": ["r27"],
             "source": {"name": "holder", "expression": "holder"}},
            {"target_ig": 2, "desired_registers": ["r26"],
             "source": {
                 "kind": "call-result",
                 "expression": "get_value(i)",
                 "type": "int",
             }},
        ],
    }

    reqs = requests_from_node_set_delta(
        delta,
        source_text=source,
        include_introducible=True,
        max_requests=0,
    )

    assert [r.target_ig for r in reqs] == [1]


def test_requests_from_node_set_delta_keeps_fpr_subtraction_local_in_coupled_set() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(f32 y_spacing, f32 col, f32 row_offset) {\n"
        "    f32 col_offset;\n"
        "    f32 row_offset_adj;\n"
        "    col_offset = y_spacing * col;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    sink(col_offset, row_offset_adj);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [
            {
                "target_ig": 32,
                "current_register": "f26",
                "desired_registers": ["f0"],
                "source": {
                    "kind": "local",
                    "name": "col_offset",
                    "type": "f32",
                    "expression": "y_spacing * col",
                },
            },
            {
                "target_ig": 33,
                "current_register": "f27",
                "desired_registers": ["f28"],
                "source": {
                    "kind": "local",
                    "name": "row_offset_adj",
                    "type": "f32",
                    "expression": "row_offset - 0.4f",
                },
            },
        ],
    }

    reqs = requests_from_node_set_delta(
        delta,
        source_text=source,
        include_introducible=True,
        max_requests=0,
    )

    assert [req.target_ig for req in reqs] == [32, 33]
    assert [req.var_name for req in reqs] == ["col_offset", "row_offset_adj"]
    assert [req.class_id for req in reqs] == [1, 1]
    assert [req.target_reg for req in reqs] == ["f0", "f28"]


def test_requests_from_node_set_delta_filters_undeclared_against_source() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {"target_ig": 34, "desired_registers": ["r27"],
             "source": {"name": "holder", "expression": "holder"}},
            {"target_ig": 44, "desired_registers": ["r25"],
             "source": {"name": "ghost", "expression": "ghost"}},
        ],
    }

    reqs = requests_from_node_set_delta(delta, source_text=_TWO_VAR_SOURCE)

    # ghost is not declared in fn_test -> dropped
    assert [r.target_ig for r in reqs] == [34]


def test_requests_from_node_set_delta_returns_empty_without_missing_list() -> None:
    assert requests_from_node_set_delta({"function": "fn_test"}) == []


def _coupled_reqs() -> list[NodeSetSplitRequest]:
    return [
        NodeSetSplitRequest("fn_test", 0, 34, current_reg="r24",
                            target_reg="r27", var_name="holder"),
        NodeSetSplitRequest("fn_test", 0, 44, current_reg="r27",
                            target_reg="r25", var_name="other"),
    ]


def test_generate_coupled_composes_edits_for_every_ig() -> None:
    reqs = _coupled_reqs()
    patches = generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE, "fn_test", reqs, max_read_sites=2
    )

    assert patches, "expected at least one coupled candidate"
    assert all(p.candidate_id.startswith("node-split-coupled-ig34+ig44-")
               for p in patches)
    assert all(p.patched_source != _TWO_VAR_SOURCE for p in patches)
    # at least one candidate carries an edit tagged for BOTH igs simultaneously
    assert any("_34_" in p.patched_source and "_44_" in p.patched_source
               for p in patches)
    assert all("@@" in p.hunk for p in patches)
    # dedup by final source
    assert len({p.patched_source for p in patches}) == len(patches)


def test_generate_coupled_respects_max_candidates() -> None:
    reqs = _coupled_reqs()
    patches = generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE, "fn_test", reqs, max_read_sites=2, max_candidates=2
    )
    assert len(patches) <= 2


def test_generate_coupled_stops_when_deadline_expires(monkeypatch) -> None:
    import src.mwcc_debug.node_set_split as node_set_split

    clock = {"now": 0.0}
    calls: list[int] = []

    def fake_request_patches(cur_source, function, request, **_kwargs):
        calls.append(request.target_ig)
        clock["now"] = 10.0
        return [
            CandidatePatch(
                f"single-{request.target_ig}",
                cur_source.replace("use(", f"use_{request.target_ig}("),
                "single",
                (),
                "",
            )
        ]

    monkeypatch.setattr(node_set_split.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        node_set_split,
        "_generate_node_set_request_patches",
        fake_request_patches,
    )

    patches = node_set_split.generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE,
        "fn_test",
        _coupled_reqs(),
        max_candidates=0,
        deadline=1.0,
    )

    assert patches == []
    assert calls == [34]


def test_generate_coupled_prunes_when_one_ig_has_no_edit() -> None:
    # `flag` is an unused parameter -> no single-ig edit -> whole set prunes.
    source = (
        "void fn_test(int flag) {\n"
        "    int holder;\n"
        "    int out;\n"
        "    holder = make();\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    reqs = [
        NodeSetSplitRequest("fn_test", 0, 34, target_reg="r27", var_name="holder"),
        NodeSetSplitRequest("fn_test", 0, 44, target_reg="r25", var_name="flag"),
    ]
    patches = generate_coupled_node_set_split_patches(source, "fn_test", reqs)
    assert patches == []


def test_generate_coupled_single_request_degenerates_to_single_ig() -> None:
    reqs = [NodeSetSplitRequest("fn_test", 0, 34, target_reg="r27",
                                var_name="holder")]
    patches = generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE, "fn_test", reqs, max_read_sites=2
    )
    assert patches
    assert all(p.patched_source != _TWO_VAR_SOURCE for p in patches)


def test_generate_coupled_empty_requests_returns_empty() -> None:
    assert generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE, "fn_test", []
    ) == []


def test_generate_coupled_same_var_is_safe() -> None:
    # Two requests on the SAME var: must never raise and never emit base source.
    reqs = [
        NodeSetSplitRequest("fn_test", 0, 34, target_reg="r27", var_name="holder"),
        NodeSetSplitRequest("fn_test", 0, 44, target_reg="r25", var_name="holder"),
    ]
    patches = generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE, "fn_test", reqs, max_read_sites=2
    )
    assert isinstance(patches, list)
    assert all(p.patched_source != _TWO_VAR_SOURCE for p in patches)


def test_generate_coupled_composes_bindable_and_introduced_binding() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int holder;\n"
        "    int out;\n"
        "    holder = make();\n"
        "    out = holder + entries[i].stat_value;\n"
        "    use(out, holder);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 34,
                "current_register": "r24",
                "desired_registers": ["r27"],
                "source": {"name": "holder", "expression": "holder"},
            },
            {
                "target_ig": 44,
                "current_register": "r27",
                "desired_registers": ["r25"],
                "source": {
                    "kind": "field-load",
                    "expression": "entries[i].stat_value",
                },
            },
        ],
    }
    reqs = requests_from_node_set_delta(
        delta,
        source_text=source,
        include_introducible=True,
        max_requests=0,
    )

    patches = generate_coupled_node_set_split_patches(
        source,
        "fn_test",
        reqs,
        max_read_sites=1,
        max_candidates=4,
    )

    assert patches
    assert all(
        patch.candidate_id.startswith("node-split-coupled-ig34+ig44-")
        for patch in patches
    )
    assert any("holder_split_34_0" in patch.patched_source for patch in patches)
    assert any(
        "stat_value_bind_44_0" in patch.patched_source
        for patch in patches
    )


def test_evaluate_coupled_realized_requires_all_igs_hit() -> None:
    baseline = _signature(assigned_regs=frozenset({(34, 24), (44, 27)}))
    candidate = _signature(assigned_regs=frozenset({(34, 27), (44, 25)}))

    result = evaluate_coupled_node_set_split_signature(
        baseline, candidate, _coupled_reqs()
    )

    assert result["status"] == "realized"
    assert result["target_reg_hit"] is True
    assert result["new_spills"] == []
    assert len(result["per_ig"]) == 2
    assert all(row["target_reg_hit"] for row in result["per_ig"])


def test_evaluate_coupled_wrong_register_when_one_misses() -> None:
    baseline = _signature(assigned_regs=frozenset({(34, 24), (44, 27)}))
    candidate = _signature(assigned_regs=frozenset({(34, 27), (44, 99)}))

    result = evaluate_coupled_node_set_split_signature(
        baseline, candidate, _coupled_reqs()
    )

    assert result["status"] == "wrong-register"
    assert result["target_reg_hit"] is False


def test_evaluate_coupled_accepts_any_desired_register_for_each_ig() -> None:
    baseline = _signature(assigned_regs=frozenset({(34, 24), (44, 27)}))
    candidate = _signature(assigned_regs=frozenset({(34, 27), (44, 26)}))
    reqs = [
        NodeSetSplitRequest(
            "fn_test",
            0,
            34,
            target_reg="r27",
            target_regs=("r27",),
            var_name="holder",
        ),
        NodeSetSplitRequest(
            "fn_test",
            0,
            44,
            target_reg="r25",
            target_regs=("r25", "r26"),
            var_name="other",
        ),
    ]

    result = evaluate_coupled_node_set_split_signature(baseline, candidate, reqs)

    assert result["status"] == "realized"
    assert result["target_reg_hit"] is True
    assert result["per_ig"][1]["target_reg_hit"] is True
    assert result["per_ig"][1]["target_reg_nums"] == [25, 26]


def test_evaluate_coupled_spill_regression_overrides_all_hit() -> None:
    baseline = _signature(assigned_regs=frozenset({(34, 24), (44, 27)}))
    candidate = _signature(
        assigned_regs=frozenset({(34, 27), (44, 25)}),
        spill_set=frozenset({7}),
    )

    result = evaluate_coupled_node_set_split_signature(
        baseline, candidate, _coupled_reqs()
    )

    assert result["status"] == "spill-regression"
    assert result["new_spills"] == [7]


def test_evaluate_coupled_missing_target_when_ig_absent() -> None:
    baseline = _signature(assigned_regs=frozenset({(34, 24), (44, 27)}))
    candidate = _signature(assigned_regs=frozenset({(34, 27)}))

    result = evaluate_coupled_node_set_split_signature(
        baseline, candidate, _coupled_reqs()
    )

    assert result["status"] == "missing-target"
    assert result["target_reg_hit"] is False


def test_summarize_node_set_split_scores_attaches_coupled_requests() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0")]
    score = CandidateScore(
        "c0", compile_ok=True, checkdiff_pct=None, checkdiff_delta=None,
        pcdump_score_delta=None, diagnostics_path=None, status="scored",
    )
    summary = summarize_node_set_split_scores(
        "fn_test", aggregate, patches,
        [{"score": score, "objective": {"status": "wrong-register"}}],
        threshold=1.0,
        coupled_requests=reqs,
    )

    assert [r["target_ig"] for r in summary["coupled_requests"]] == [34, 44]
    assert summary["shared_source_var"] is None


def test_summarize_node_set_split_scores_flags_shared_source_var() -> None:
    reqs = [
        NodeSetSplitRequest("fn_test", 0, 34, target_reg="r27", var_name="holder"),
        NodeSetSplitRequest("fn_test", 0, 44, target_reg="r25", var_name="holder"),
    ]
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder"
    )
    summary = summarize_node_set_split_scores(
        "fn_test", aggregate, [], [], threshold=1.0, coupled_requests=reqs
    )

    assert summary["shared_source_var"] == "holder"


def test_summarize_coupled_all_wrong_register_marks_exhaustive_terminal() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    scored = []
    for candidate_id in ("c0", "c1"):
        score = CandidateScore(
            candidate_id, compile_ok=True, checkdiff_pct=None,
            checkdiff_delta=None, pcdump_score_delta=None,
            diagnostics_path=None, status="objective-failed",
        )
        scored.append({
            "score": score,
            "objective": {
                "status": "wrong-register",
                "per_ig": [
                    {"target_ig": 34, "target_reg_num": 27, "assigned_reg": 26},
                    {"target_ig": 44, "target_reg_num": 25, "assigned_reg": 24},
                ],
            },
        })

    summary = summarize_node_set_split_scores(
        "fn_test", aggregate, patches, scored, threshold=1.0,
        coupled_requests=reqs,
    )

    assert summary["status"] == "exhausted"
    assert summary["objective_counts"] == {"wrong-register": 2}
    assert summary["wrong_register_count"] == 2
    assert summary["wrong_register_exhausted"] is True
    assert summary["terminal_reason"] == "all-wrong-register"
    next_steps = " ".join(summary["next_steps"])
    assert "do not rerun node-set-split with the same delta" in next_steps
    assert "switch to coloring-register steering" in next_steps


def test_summarize_coupled_all_wrong_register_emits_no_shippable_classification() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    scored = []
    for candidate_id in ("c0", "c1"):
        score = CandidateScore(
            candidate_id, compile_ok=True, checkdiff_pct=None,
            checkdiff_delta=None, pcdump_score_delta=None,
            diagnostics_path=None, status="objective-failed",
        )
        scored.append({
            "score": score,
            "objective": {"status": "wrong-register"},
        })

    summary = summarize_node_set_split_scores(
        "fn_test", aggregate, patches, scored, threshold=1.0,
        coupled_requests=reqs,
    )

    classification = summary["in_place_recolor"]
    assert classification["kind"] == "coupled-same-class-in-place-recolor"
    assert classification["status"] == "no-shippable-mutator"
    assert classification["terminal"] is True
    assert classification["function"] == "fn_test"
    assert classification["target_igs"] == [34, 44]
    assert classification["class_id"] == 0
    assert classification["evidence"]["wrong_register_count"] == 2
    assert classification["evidence"]["pending_count"] == 0
    assert "do not rerun" in classification["recommendation"]


def test_summarize_candidate_limited_wrong_register_is_not_exhaustive() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    score = CandidateScore(
        "c0", compile_ok=True, checkdiff_pct=None, checkdiff_delta=None,
        pcdump_score_delta=None, diagnostics_path=None,
        status="objective-failed",
    )

    summary = summarize_node_set_split_scores(
        "fn_test",
        aggregate,
        patches,
        [{"score": score, "objective": {"status": "wrong-register"}}],
        threshold=1.0,
        stop_reason="candidate-limit",
        candidate_limit=1,
        coupled_requests=reqs,
    )

    assert summary["objective_counts"] == {"wrong-register": 1}
    assert summary["wrong_register_count"] == 1
    assert summary["wrong_register_exhausted"] is False
    assert summary["terminal_reason"] is None


def test_summarize_coupled_candidate_limited_classification_is_incomplete() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    score = CandidateScore(
        "c0", compile_ok=True, checkdiff_pct=None,
        checkdiff_delta=None, pcdump_score_delta=None,
        diagnostics_path=None, status="objective-failed",
    )

    summary = summarize_node_set_split_scores(
        "fn_test",
        aggregate,
        patches,
        [{"score": score, "objective": {"status": "wrong-register"}}],
        threshold=1.0,
        stop_reason="candidate-limit",
        candidate_limit=1,
        coupled_requests=reqs,
    )

    classification = summary["in_place_recolor"]
    assert classification["status"] == "incomplete"
    assert classification["terminal"] is False
    assert "larger --max-candidates" in classification["recommendation"]


def test_summarize_coupled_generator_cap_classification_is_incomplete() -> None:
    reqs = _coupled_reqs()
    aggregate = NodeSetSplitRequest(
        "fn_test", 0, 34, target_reg="r27+r25", var_name="holder+other"
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    scored = []
    for candidate_id in ("c0", "c1"):
        score = CandidateScore(
            candidate_id, compile_ok=True, checkdiff_pct=None,
            checkdiff_delta=None, pcdump_score_delta=None,
            diagnostics_path=None, status="objective-failed",
        )
        scored.append({
            "score": score,
            "objective": {"status": "wrong-register"},
        })

    summary = summarize_node_set_split_scores(
        "fn_test", aggregate, patches, scored, threshold=1.0,
        candidate_limit=2,
        coupled_requests=reqs,
    )

    classification = summary["in_place_recolor"]
    assert summary["wrong_register_exhausted"] is True
    assert classification["status"] == "incomplete"
    assert classification["terminal"] is False
    assert "larger --max-candidates" in classification["recommendation"]


# ---------------------------------------------------------------------------
# #722 - target-color select-order leads after split candidates compile
# ---------------------------------------------------------------------------

_GPR_VOLATILE_BLOCKERS = [(i, i) for i in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)]


def test_derive_target_color_select_order_leads_from_tiebreak_whatif() -> None:
    # Baseline order: ig49 is selected before ig60, so it gets fresh r31.
    # If source perturbations make ig60 selected before ig49, ig49 sees ig60's
    # r31 as blocked and is forced to the requested alternate r30.
    section = ColorgraphSection(
        class_id=0,
        result=1,
        n_nodes=2,
        decisions=[
            ColorgraphDecision(
                0,
                49,
                31,
                0,
                12,
                0,
                _GPR_VOLATILE_BLOCKERS + [(60, 30)],
            ),
            ColorgraphDecision(
                1,
                60,
                30,
                0,
                12,
                0,
                _GPR_VOLATILE_BLOCKERS + [(49, 31)],
            ),
        ],
    )
    ig = tb.build_ig(section)
    request = NodeSetSplitRequest(
        "fn_test",
        0,
        49,
        target_reg="r30",
        target_regs=("r30",),
        var_name="flag",
    )

    leads = derive_target_color_select_order_leads(ig, [request])

    assert [lead.target_order for lead in leads] == [(60, 49)]
    assert leads[0].direction == "after"
    assert leads[0].assigned_reg == 31
    assert leads[0].target_reg == 30
    assert leads[0].to_dict()["target_order"] == [60, 49]


def test_annotate_target_color_select_order_leads_adds_wrong_register_guidance() -> None:
    section = ColorgraphSection(
        class_id=0,
        result=1,
        n_nodes=2,
        decisions=[
            ColorgraphDecision(
                0,
                49,
                31,
                0,
                12,
                0,
                _GPR_VOLATILE_BLOCKERS + [(60, 30)],
            ),
            ColorgraphDecision(
                1,
                60,
                30,
                0,
                12,
                0,
                _GPR_VOLATILE_BLOCKERS + [(49, 31)],
            ),
        ],
    )
    ig = tb.build_ig(section)
    request = NodeSetSplitRequest(
        "fn_test",
        0,
        49,
        target_reg="r29",
        target_regs=("r29", "r30"),
        var_name="flag",
    )

    annotated = annotate_target_color_select_order_leads(
        {"status": "wrong-register"},
        ig,
        [request],
    )

    assert annotated["target_color_select_order_leads"][0]["target_regs"] == [29, 30]
    assert annotated["target_color_select_order_leads"][0]["target_order"] == [60, 49]


# ---------------------------------------------------------------------------
# #702 — CLI --coupled smoke (no compiler / report.json required)
# ---------------------------------------------------------------------------

def _invoke_solve_node_set_split(*args: str):
    from typer.testing import CliRunner

    from src.cli import debug as cli_debug

    runner = CliRunner()
    return runner.invoke(cli_debug.solve_app, ["node-set-split", *args])


def test_cli_coupled_help_lists_flag() -> None:
    result = _invoke_solve_node_set_split("--help")
    assert result.exit_code == 0
    assert "--coupled" in result.output


def test_cli_coupled_requires_node_set_delta() -> None:
    # Early validation: --coupled without --node-set-delta exits 2 before any
    # report.json / compiler work.
    result = _invoke_solve_node_set_split("--coupled", "--function", "fn_test")
    assert result.exit_code == 2
    assert "requires --node-set-delta" in result.output


def test_requests_from_node_set_delta_handles_non_dict_payload() -> None:
    # `null` / list payloads must degrade cleanly, not raise AttributeError.
    assert requests_from_node_set_delta(None) == []
    assert requests_from_node_set_delta([1, 2, 3]) == []


def test_generate_coupled_max_candidates_zero_is_unbounded() -> None:
    # `--max-candidates 0` (candidate_limit None -> 0) must NOT re-cap at the
    # default; it is the documented exhaustive escape hatch (#702 review I-1).
    reqs = _coupled_reqs()
    capped = generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE, "fn_test", reqs, max_read_sites=2, max_candidates=3
    )
    unbounded = generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE, "fn_test", reqs, max_read_sites=2, max_candidates=0
    )
    assert len(capped) <= 3
    assert len(unbounded) > len(capped)


def test_cli_coupled_blocks_when_fewer_than_two_bindable(tmp_path, monkeypatch) -> None:
    """--coupled with a delta that has <2 bindable virtuals exits 3 with a
    blocked summary carrying coupled_requests + shared_source_var (no compiler
    needed; the check runs before any compile)."""
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    (src_dir / "sample.c").write_text(
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    holder = make();\n"
        "    use(holder);\n"
        "}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(_json.dumps({
        "units": [
            {"name": "main/melee/mn/sample", "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")

    delta = tmp_path / "delta.json"
    delta.write_text(_json.dumps({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {"target_ig": 34, "desired_registers": ["r27"],
             "source": {"name": "holder", "expression": "holder"}},
        ],
    }), encoding="utf-8")

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split", "--coupled",
        "--node-set-delta", str(delta),
        "-f", "fn_test", "--json",
    ])

    assert result.exit_code == 3, result.output
    summary = _json.loads(result.output)
    assert summary["status"] == "blocked"
    assert "coupled mode needs >=2" in (summary.get("blocked_reason") or "")
    assert len(summary["coupled_requests"]) == 1
    assert summary["shared_source_var"] is None
    classification = summary["in_place_recolor"]
    assert classification["status"] == "insufficient-source-bindings"
    assert classification["terminal"] is False
    assert classification["target_igs"] == [34]
