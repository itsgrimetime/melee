"""Tests for node-set split request parsing and candidate scoring."""
from __future__ import annotations

from pathlib import Path
import re

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


_STACK_ARRAY_SOURCE = (
    "typedef struct Entry {\n"
    "    /* +0 */ int pad0;\n"
    "    /* +4 */ int pad4;\n"
    "    /* +8 */ int x8;\n"
    "    /* +C */ int xC;\n"
    "} Entry;\n"
    "void fn_test(int k, int i) {\n"
    "    Entry entries[25];\n"
    "    Entry* base;\n"
    "    Entry* ptr;\n"
    "    int out;\n"
    "    ptr = entries;\n"
    "    base = ptr;\n"
    "    out = entries[k].x8;\n"
    "    out = entries[k].xC;\n"
    "    use(base, out);\n"
    "}\n"
)


def _stack_array_delta() -> dict:
    return {
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 40,
                "current_register": "r40",
                "desired_registers": ["r25"],
                "source": {
                    "kind": "implicit-temp",
                    "expression": "addi r40,r1,entries",
                },
            },
            {
                "target_ig": 45,
                "current_register": "r45",
                "desired_registers": ["r12"],
                "source": {
                    "kind": "load/store-address",
                    "expression": "lwz r45,8(r40)",
                    "base_virtual": 40,
                    "field_offset": 8,
                },
            },
            {
                "target_ig": 46,
                "current_register": "r46",
                "desired_registers": ["r11"],
                "source": {
                    "kind": "load/store-address",
                    "expression": "lwz r46,12(r40)",
                    "base_virtual": 40,
                    "field_offset": 12,
                },
            },
        ],
    }


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
    assert req.blocked_reason is None
    assert req.source_expression == "entries[i].stat_value"
    assert req.source_type == "int"
    assert req.source_kind == "field-load"


def test_request_from_node_set_delta_enriches_pcode_load_chain_to_source() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "struct HSD_GObj {\n"
        "    /* +00 */ int pad0;\n"
        "    /* +2C */ void* user_data;\n"
        "};\n"
        "struct Diagram2 {\n"
        "    /* 0x46 */ u8 selected_fighter_idx;\n"
        "    /* 0x47 */ u8 selected_name_idx;\n"
        "    /* 0x48 */ u8 is_name_mode;\n"
        "};\n"
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Diagram2 Diagram2;\n"
        "extern HSD_GObj* gGlobalObj;\n"
        "void fn_test(void) {\n"
        "    Diagram2* data2;\n"
        "    u8 x48;\n"
        "    data2 = gGlobalObj->user_data;\n"
        "    x48 = data2->is_name_mode;\n"
        "    use(x48);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r28",
                "desired_registers": ["r27"],
                "source": {
                    "kind": "load/store-address",
                    "expression": "lbz r36,72(r58)",
                    "base_virtual": 58,
                    "field_offset": 72,
                    "confidence": "pcode-first-def",
                },
            },
            {
                "target_ig": 58,
                "current_register": "r28",
                "desired_registers": ["r29"],
                "source": {
                    "kind": "load/store-address",
                    "expression": "lwz r58,44(r106)",
                    "base_virtual": 106,
                    "field_offset": 44,
                    "confidence": "pcode-first-def",
                },
            },
        ],
    }

    reqs = requests_from_node_set_delta(
        delta,
        source_text=source,
        include_introducible=True,
    )

    by_ig = {req.target_ig: req for req in reqs}
    assert by_ig[58].source_expression == "gGlobalObj->user_data"
    assert by_ig[58].source_type == "Diagram2*"
    assert by_ig[58].source_kind == "field-load"
    assert node_set_split.is_node_set_request_introducible(by_ig[58]) is True
    assert by_ig[36].source_expression == "data2->is_name_mode"
    assert by_ig[36].source_type == "u8"
    assert by_ig[36].source_kind == "field-load"
    assert node_set_split.is_node_set_request_introducible(by_ig[36]) is True

    patches = generate_node_set_introduce_binding_patches(
        source,
        "fn_test",
        by_ig[36],
        max_bind_sites=1,
        max_read_sites=1,
    )
    assert patches
    assert "data2->is_name_mode" in patches[0].hunk


def test_request_from_node_set_delta_enriches_pcode_chain_from_existing_field_load() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "struct HSD_GObj {\n"
        "    /* +00 */ int pad0;\n"
        "    /* +2C */ void* user_data;\n"
        "};\n"
        "struct Diagram2 {\n"
        "    /* 0x46 */ u8 selected_fighter_idx;\n"
        "    /* 0x47 */ u8 selected_name_idx;\n"
        "    /* 0x48 */ u8 is_name_mode;\n"
        "};\n"
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Diagram2 Diagram2;\n"
        "extern HSD_GObj* gGlobalObj;\n"
        "void fn_test(void) {\n"
        "    Diagram2* data;\n"
        "    Diagram2* data2;\n"
        "    u8 x48;\n"
        "    data = gGlobalObj->user_data;\n"
        "    if (other()) {\n"
        "        data2 = gGlobalObj->user_data;\n"
        "        x48 = data2->is_name_mode;\n"
        "    }\n"
        "    use(data->is_name_mode);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r28",
                "desired_registers": ["r30"],
                "source": {
                    "kind": "load/store-address",
                    "expression": "lbz r36,72(r58)",
                    "base_virtual": 58,
                    "field_offset": 72,
                    "confidence": "pcode-first-def",
                },
            },
            {
                "target_ig": 58,
                "current_register": "r28",
                "desired_registers": ["r29"],
                "source": {
                    "kind": "field-load",
                    "expression": "gGlobalObj->user_data",
                    "type": "void*",
                    "base_var": "gGlobalObj",
                    "field_offset": 44,
                    "field_name": "user_data",
                    "confidence": "source-span",
                },
            },
        ],
    }

    reqs = requests_from_node_set_delta(
        delta,
        source_text=source,
        include_introducible=True,
    )

    by_ig = {req.target_ig: req for req in reqs}
    assert by_ig[36].source_expression == "data2->is_name_mode"
    assert by_ig[36].source_type == "u8"
    assert by_ig[36].source_kind == "field-load"
    assert node_set_split.is_node_set_request_introducible(by_ig[36]) is True

    patches = generate_node_set_introduce_binding_patches(
        source,
        "fn_test",
        by_ig[36],
        max_bind_sites=1,
        max_read_sites=1,
    )
    assert patches
    assert "data2->is_name_mode" in patches[0].hunk


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


def test_request_from_node_set_delta_allows_simple_typed_cast_binding() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(int col) {\n"
        "    f32 out;\n"
        "    out = (f32) col;\n"
        "    use(out);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 46,
            "desired_registers": ["f26"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "(f32) col",
                "type": "f32",
                "introduce_binding": True,
            },
        }],
    }

    req = request_from_node_set_delta(delta, source_text=source)

    assert req is not None
    assert req.target_ig == 46
    assert req.source_expression == "(f32) col"
    assert req.source_type == "f32"
    assert node_set_split.is_node_set_request_introducible(req) is True


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


def test_request_from_node_set_delta_enriches_stack_array_base_addi() -> None:
    reqs = requests_from_node_set_delta(
        _stack_array_delta(),
        source_text=_STACK_ARRAY_SOURCE,
        include_introducible=True,
        max_requests=0,
    )
    by_ig = {req.target_ig: req for req in reqs}

    assert set(by_ig) == {40, 45, 46}
    assert by_ig[40].source_kind == "stack-array-base"
    assert by_ig[40].source_expression == "entries"
    assert by_ig[40].source_type == "Entry*"
    assert by_ig[40].var_name is None
    assert node_set_split.is_node_set_request_introducible(by_ig[40]) is True
    assert by_ig[45].source_expression == "entries[k].x8"
    assert by_ig[45].source_type == "int"
    assert by_ig[46].source_expression == "entries[k].xC"
    assert by_ig[46].source_type == "int"


def test_stack_array_field_offset_rejects_ambiguous_source_occurrences() -> None:
    ambiguous_source = _STACK_ARRAY_SOURCE.replace(
        "    use(base, out);\n",
        "    out = entries[i].xC;\n"
        "    use(base, out);\n",
    )

    req = request_from_node_set_delta(
        _stack_array_delta(),
        target_ig=46,
        source_text=ambiguous_source,
    )

    assert req is not None
    assert req.source_expression == "lwz r46,12(r40)"
    assert req.source_type is None
    assert req.blocked_reason is not None


def test_generate_node_set_stack_array_base_temp_patches_are_bounded_and_near_zero_shape() -> None:
    req = requests_from_node_set_delta(
        _stack_array_delta(),
        source_text=_STACK_ARRAY_SOURCE,
        include_introducible=True,
        max_requests=1,
    )[0]

    patches = generate_node_set_introduce_binding_patches(
        _STACK_ARRAY_SOURCE,
        "fn_test",
        req,
        max_bind_sites=2,
        max_candidates=2,
    )

    assert 0 < len(patches) <= 2
    assert all(
        patch.candidate_id.startswith("node-split-stack-array-base-")
        for patch in patches
    )
    candidate_text = "\n".join(patch.patched_source for patch in patches)
    assert "Entry* entries_base_bind_40_0;" in candidate_text
    assert "entries_base_bind_40_0 = entries;" in candidate_text
    assert "ptr = entries_base_bind_40_0;" in candidate_text
    assert "PAD_STACK" not in candidate_text
    assert "();" not in candidate_text
    assert "void fn_test" in candidate_text


def test_generate_coupled_node_set_split_composes_stack_array_base_and_field_loads() -> None:
    reqs = requests_from_node_set_delta(
        _stack_array_delta(),
        source_text=_STACK_ARRAY_SOURCE,
        include_introducible=True,
        max_requests=0,
    )

    patches = generate_coupled_node_set_split_patches(
        _STACK_ARRAY_SOURCE,
        "fn_test",
        reqs,
        max_read_sites=2,
        max_per_ig=3,
        max_candidates=6,
    )

    assert patches
    assert patches[0].candidate_id.startswith(
        "node-split-coupled-ig40+ig45+ig46-"
    )
    candidate_text = patches[0].patched_source
    assert "entries_base_bind_40_0" in candidate_text
    assert "entries[k].x8" in candidate_text
    assert "x8_bind_45_0" in candidate_text
    assert "xC_bind_46_0" in candidate_text


def test_generate_node_set_introduce_binding_handles_non_ascii_prefix_owner_split() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "/* owner prefix \u2192 */\n"
        "void fn_test(u8* dst) {\n"
        "u8* owner;\n"
        "owner = dst;\n"
        "use(owner);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 44,
            "current_register": "r24",
            "desired_registers": ["r25"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "dst",
                "type": "u8*",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches
    candidate_text = "\n".join(patch.patched_source for patch in patches)
    assert "u8* dst_bind_44_0;" in candidate_text
    assert "dst_bind_44_0 = dst;" in candidate_text
    assert "owner = dst_bind_44_0;" in candidate_text


def test_generate_node_set_introduce_binding_handles_owner_call_argument() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void* jobj, f32 x_spacing, f32 col_offset, int i) {\n"
        "    HSD_JObjSetTranslateX(jobj, (x_spacing * (f32) i) + col_offset);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 38,
            "current_register": "f28",
            "desired_registers": ["f29"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "col_offset",
                "type": "f32",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches
    bind_only = next(
        patch for patch in patches
        if patch.candidate_id.endswith("-bind-site0")
    )
    assert "f32 col_offset_bind_38_0;" in bind_only.patched_source
    assert "col_offset_bind_38_0 = col_offset;" in bind_only.patched_source
    assert (
        "HSD_JObjSetTranslateX(jobj, (x_spacing * (f32) i) + "
        "col_offset_bind_38_0);"
    ) in bind_only.patched_source
    assert bind_only.patched_source.index(
        "col_offset_bind_38_0 = col_offset;"
    ) < bind_only.patched_source.index("HSD_JObjSetTranslateX")


def test_generate_node_set_introduce_binding_rewrites_call_argument_not_callee() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(f32 col_offset) {\n"
        "    col_offset(col_offset);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 38,
            "current_register": "f28",
            "desired_registers": ["f29"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "col_offset",
                "type": "f32",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches
    bind_only = next(
        patch for patch in patches
        if patch.candidate_id.endswith("-bind-site0")
    )
    assert "col_offset(col_offset_bind_38_0);" in bind_only.patched_source
    assert "col_offset_bind_38_0(col_offset)" not in bind_only.patched_source


def test_generate_node_set_introduce_binding_rejects_non_synthetic_call_argument() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    use(entries[i].stat_value);\n"
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
                "type": "int",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches == []


@pytest.mark.parametrize(
    "source",
    [
        (
            "typedef float f32;\n"
            "void fn_test(void* jobj, f32 col_offset) {\n"
            "    HSD_JObjSetTranslateX(jobj, mutates_state(), col_offset);\n"
            "}\n"
        ),
        (
            "typedef float f32;\n"
            "void fn_test(void* jobj, f32 col_offset) {\n"
            "    HSD_JObjSetTranslateX(jobj, col_offset, col_offset = 1.0f);\n"
            "}\n"
        ),
    ],
)
def test_generate_node_set_introduce_binding_rejects_side_effect_call_argument(
    source: str,
) -> None:
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 38,
            "current_register": "f28",
            "desired_registers": ["f29"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "col_offset",
                "type": "f32",
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches == []


def test_generate_coupled_composes_draw_owner_call_arguments() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void* jobj, f32 col_offset, f32 row_offset) {\n"
        "    DrawCell(jobj, col_offset, row_offset - 0.4f);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [
            {
                "target_ig": 38,
                "current_register": "f28",
                "desired_registers": ["f29"],
                "source": {
                    "kind": "synthetic-owner-split",
                    "expression": "col_offset",
                    "type": "f32",
                },
            },
            {
                "target_ig": 46,
                "current_register": "f0",
                "desired_registers": ["f26"],
                "source": {
                    "kind": "synthetic-owner-split",
                    "expression": "row_offset - 0.4f",
                    "type": "f32",
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
        patch.candidate_id.startswith("node-split-coupled-ig38+ig46-")
        for patch in patches
    )
    candidate_text = "\n".join(patch.patched_source for patch in patches)
    assert "col_offset_bind_38_0" in candidate_text
    assert "row_offset_bind_46_0" in candidate_text


def test_generate_node_set_introduce_binding_patches_can_skip_recursive_combos(
    monkeypatch,
) -> None:
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

    def fail_combo_generation(*_args, **_kwargs):
        raise AssertionError("recursive combo generation should be disabled")

    monkeypatch.setattr(
        node_set_split,
        "_append_combo_patches",
        fail_combo_generation,
    )

    patches = generate_node_set_introduce_binding_patches(
        source,
        "fn_test",
        req,
        max_bind_sites=1,
        max_read_sites=1,
        include_split_combos=False,
    )

    assert patches
    assert patches[0].candidate_id.endswith("-bind-site0")


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


def test_node_set_split_rejects_split_local_used_outside_decl_block() -> None:
    valid_source = (
        "void fn_test(int j) {\n"
        "    if (j != 0) {\n"
        "        int j_split_34_0;\n"
        "        j_split_34_0 = j;\n"
        "        use(j_split_34_0);\n"
        "    }\n"
        "}\n"
    )
    invalid_source = (
        "void fn_test(int j) {\n"
        "    if (j != 0) {\n"
        "        int j_split_34_0;\n"
        "        j_split_34_0 = j;\n"
        "    }\n"
        "    use(j_split_34_0);\n"
        "}\n"
    )

    assert node_set_split._synthetic_local_uses_within_decl_scope(
        valid_source, "j_split_34_0"
    )
    assert not node_set_split._synthetic_local_uses_within_decl_scope(
        invalid_source, "j_split_34_0"
    )


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


def test_generate_node_set_split_patches_emits_bounded_combo_candidates() -> None:
    source = (
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 y_spacing;\n"
        "    f32 col;\n"
        "    f32 tmp;\n"
        "    f32 other;\n"
        "    f32 out;\n"
        "    tmp = y_offset * rowf;\n"
        "    other = y_spacing * col;\n"
        "    out = y_offset * rowf - 0.4f;\n"
        "    use(other, out);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        1,
        33,
        target_reg="f28",
        var_name="out",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )
    combo_patches = [
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-combo-out-ig33-")
    ]

    assert 0 < len(combo_patches) <= 24
    assert len({patch.candidate_id for patch in combo_patches}) == len(combo_patches)
    assert len({patch.patched_source for patch in combo_patches}) == len(combo_patches)
    assert all(
        re.search(r"-c\d+-[0-9a-f]{6}$", patch.candidate_id)
        for patch in combo_patches
    )
    assert any(
        "prologue-reorder+assignment-chain+operand-alias"
        in patch.candidate_id
        for patch in combo_patches
    )
    for patch in combo_patches:
        match = re.search(
            r"node-split-combo-out-ig33-(?P<chain>.+)-c\d+-[0-9a-f]{6}$",
            patch.candidate_id,
        )
        assert match is not None
        families = match.group("chain").split("+")
        assert len(families) == len(set(families))


def test_generate_node_set_split_patches_keeps_existing_patches_when_combo_fails(
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

    def raise_combo_error(*_args, **_kwargs):
        raise RuntimeError("forced combo failure")

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split._generate_node_set_family_patches",
        raise_combo_error,
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
        candidate_id.startswith("node-split-combo-holder-ig40-")
        for candidate_id in ids
    )


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


def test_generate_node_set_split_decl_order_handles_utf8_prefix_offsets() -> None:
    source = (
        "// non-ascii — before function\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
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
        function="mnDiagram_SortNamesByKOs",
        class_id=0,
        target_ig=40,
        current_reg="r31",
        target_reg="r30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "mnDiagram_SortNamesByKOs", req, max_read_sites=0
    )
    decl_order_patches = [
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-decl-order-holder-ig40-")
    ]

    assert decl_order_patches
    assert any(
        patch.patched_source.count("int first;") == 1
        and patch.patched_source.count("int holder;") == 1
        and patch.patched_source.count("int out;") == 1
        and patch.patched_source.index("int holder;")
        < patch.patched_source.index("int first;")
        and "source_rejection_reason" not in patch.metadata
        for patch in decl_order_patches
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


def test_generate_node_set_split_patches_rejects_duplicate_decl_order_source(
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

    def duplicate_holder_decl(*_args, **_kwargs):
        return source.replace(
            "    int holder;\n",
            "    int holder;\n    int holder;\n",
            1,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.reorder_decls_in_function_scope",
        duplicate_holder_decl,
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=0
    )
    decl_order_patches = [
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-decl-order-holder-ig40-")
    ]

    assert decl_order_patches
    assert all(patch.patched_source == source for patch in decl_order_patches)
    assert all(
        patch.metadata.get("source_rejection_reason")
        == "duplicate local declaration(s) after decl-order rewrite: holder"
        for patch in decl_order_patches
    )


def test_generate_node_set_split_patches_respects_max_candidates(
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

    def fail_late_family(*_args, **_kwargs):
        raise AssertionError("bounded node-set generation must stop at budget")

    monkeypatch.setattr(
        node_set_split,
        "_append_decl_order_patches",
        fail_late_family,
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
        include_combos=False,
        max_candidates=1,
    )

    assert len(patches) == 1


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


def test_summarize_node_set_split_scores_surfaces_wrong_register_residuals() -> None:
    req = NodeSetSplitRequest("fn_test", 1, 33, target_reg="f28", var_name="x")
    patches = [CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0")]
    score = CandidateScore(
        "c0",
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
        [{
            "score": score,
            "source_retained": "/tmp/c0.c",
            "objective": {
                "status": "wrong-register",
                "class_id": 1,
                "target_ig": 33,
                "target_reg": "f28",
                "target_reg_num": 28,
                "assigned_reg": 26,
                "source_path": "/tmp/c0.c",
                "target_score": {
                    "matched": 4,
                    "targeted": 6,
                    "virtuals": {
                        "32": {"expected": 28, "actual": 25, "matched": False},
                        "46": {"expected": 26, "actual": 1, "matched": False},
                    },
                },
            },
        }],
        threshold=1.0,
    )

    row = summary["candidates"][0]
    assert row["source_retained"] == "/tmp/c0.c"
    assert row["target_ig"] == 33
    assert row["target_reg"] == "f28"
    assert row["target_reg_num"] == 28
    assert row["achieved_reg"] == 26
    assert row["achieved_register"] == "f26"
    assert row["target_score"]["matched"] == 4
    assert row["target_score"]["virtuals"]["46"]["actual"] == 1


def test_generated_pointer_walk_local_rewrites_initializer_from_base_expr() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "extern struct Demo { u8 sorted_names[0x78]; } mnDiagram_804A076C;\n"
        "void fn_test(void) {\n"
        "    int i;\n"
        "    u8* dst = mnDiagram_804A076C.sorted_names;\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        for (i = 0; i < 4; i++, ll_probe_iter_0++) {\n"
        "            *ll_probe_iter_0 = (u8) i;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        34,
        current_reg="r28",
        target_reg="r27",
        var_name="ll_probe_iter_0",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_candidates=1,
    )

    assert patches
    patch = patches[0]
    assert patch.candidate_id.startswith(
        "node-split-generated-pointer-walk-base-ll_probe_iter_0-ig34"
    )
    assert "ll_probe_iter_0 = mnDiagram_804A076C.sorted_names;" in patch.patched_source
    assert patch.metadata["kind"] == "generated-pointer-walk-initializer"


def test_generated_pointer_walk_local_uses_source_payload_for_direct_initializer() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "extern struct Demo { u8 sorted_names[0x78]; } mnDiagram_804A076C;\n"
        "void fn_test(void) {\n"
        "    int i;\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = mnDiagram_804A076C.sorted_names;\n"
        "        for (i = 0; i < 4; i++, ll_probe_iter_0++) {\n"
        "            *ll_probe_iter_0 = (u8) i;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        34,
        current_reg="r28",
        target_reg="r27",
        var_name="ll_probe_iter_0",
        source_expression="mnDiagram_804A076C.sorted_names",
        source_type="u8*",
        source_kind="generated-pointer-walk-local",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_candidates=1,
    )

    assert patches
    patch = patches[0]
    assert patch.candidate_id.startswith(
        "node-split-generated-pointer-walk-source-ll_probe_iter_0-ig34"
    )
    assert "u8* ll_probe_iter_0_source_34_0 = mnDiagram_804A076C.sorted_names;" in patch.patched_source
    assert "ll_probe_iter_0 = ll_probe_iter_0_source_34_0;" in patch.patched_source
    assert patch.metadata["kind"] == "generated-pointer-walk-source-binding"


def test_node_set_wrong_register_rows_include_force_phys_target_score() -> None:
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        34,
        current_reg="r28",
        target_reg="r27",
        var_name="ll_probe_iter_0",
    )
    baseline = _signature(assigned_regs=frozenset({(34, 28), (44, 3)}))
    candidate = _signature(assigned_regs=frozenset({(34, 28), (44, 3)}))
    objective = evaluate_node_set_split_signature(
        baseline,
        candidate,
        req,
        force_phys={34: 27, 44: 25},
    )
    score = CandidateScore(
        "c0",
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
        [CandidatePatch("c0", "src0", "c0", ((0, 0),))],
        [{"score": score, "objective": objective, "source_retained": "/tmp/c0.c"}],
        threshold=1.0,
    )

    row = summary["candidates"][0]
    assert row["objective_status"] == "wrong-register"
    assert row["target_score"]["virtuals"]["34"] == {
        "expected": 27,
        "actual": 28,
        "hit": False,
        "matched": False,
        "distance": 1,
    }
    assert row["target_score"]["virtuals"]["44"]["actual"] == 3
    assert row["target_score"]["virtuals"]["44"]["distance"] == 22


def test_summarize_node_set_split_scores_surfaces_realized_source_handoff() -> None:
    req = NodeSetSplitRequest("fn_test", 1, 38, target_reg="f29", var_name="x")
    patches = [CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0")]
    score = CandidateScore(
        "c0",
        compile_ok=True,
        checkdiff_pct=99.7,
        checkdiff_delta=1.2,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="scored",
    )

    summary = summarize_node_set_split_scores(
        "fn_test",
        req,
        patches,
        [{
            "score": score,
            "source_retained": "/tmp/realized-c0.c",
            "source_hunk": "@@ realized\n- old\n+ new",
            "objective": {
                "status": "realized",
                "class_id": 1,
                "target_ig": 38,
                "target_reg": "f29",
                "target_reg_num": 29,
                "assigned_reg": 29,
                "source_path": "/tmp/realized-c0.c",
                "source_hunk": "@@ realized\n- old\n+ new",
            },
        }],
        threshold=1.0,
    )

    row = summary["candidates"][0]
    assert summary["status"] == "improved"
    assert row["source_retained"] == "/tmp/realized-c0.c"
    assert row["objective"]["source_path"] == "/tmp/realized-c0.c"
    assert row["source_hunk"] == "@@ realized\n- old\n+ new"
    assert row["source_hunks"] == [{
        "hunk_id": "c0",
        "unified_diff": "@@ realized\n- old\n+ new",
    }]
    assert row["objective"]["source_hunk"] == "@@ realized\n- old\n+ new"


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
        resume_command="melee-agent debug solve node-set-split --remote",
    )

    assert summary["status"] == "exhausted"
    assert summary["stop_condition"]["kind"] == "candidate-limit"
    assert (
        summary["stop_condition"]["resume_command"]
        == "melee-agent debug solve node-set-split --remote"
    )
    assert summary["exhaustive"] is False
    assert summary["candidate_limit"] == 1
    assert summary["generated_count"] == 3
    assert summary["scored_count"] == 1
    assert summary["evaluated_count"] == 1
    assert summary["checkdiff_scored_count"] == 0
    assert summary["pending_count"] == 2
    assert summary["omitted_count"] == 2
    assert "rerun" in " ".join(summary["next_steps"])
    assert "melee-agent debug solve node-set-split --remote" in summary["next_steps"]


def test_node_set_rows_preserve_expression_score_from_objective() -> None:
    req = NodeSetSplitRequest("fn_test", 1, 40, target_reg="f28", var_name="holder")
    patches = [
        CandidatePatch("one", "source 1", "one", ((0, 0),), hunk="@@ one"),
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
        [{
            "score": score,
            "objective": {
                "status": "wrong-register",
                "expression_score": {"matched": 1, "targeted": 2},
            },
        }],
        threshold=1.0,
    )

    assert summary["candidates"][0]["expression_score"] == {
        "matched": 1,
        "targeted": 2,
    }


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


def test_requests_from_node_set_delta_owner_split_simple_expression_is_introducible() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 44,
                "current_register": "r24",
                "desired_registers": ["r25"],
                "source": {
                    "kind": "synthetic-owner-split",
                    "expression": "dst",
                    "type": "u8*",
                },
            },
            {
                "target_ig": 45,
                "current_register": "r26",
                "desired_registers": ["r27"],
                "source": {
                    "kind": "local",
                    "expression": "src",
                    "type": "u8*",
                    "introduce_binding": True,
                },
            },
        ],
    }

    reqs = requests_from_node_set_delta(
        delta,
        include_introducible=True,
        max_requests=0,
    )

    assert [req.target_ig for req in reqs] == [44, 45]
    assert [req.var_name for req in reqs] == [None, None]
    assert [req.source_expression for req in reqs] == ["dst", "src"]
    assert [req.source_type for req in reqs] == ["u8*", "u8*"]
    assert node_set_split.is_node_set_request_introducible(reqs[0])
    assert node_set_split.is_node_set_request_introducible(reqs[1])


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


def test_generate_coupled_default_per_ig_cap_keeps_priority_families(
    monkeypatch,
) -> None:
    import src.mwcc_debug.node_set_split as node_set_split

    def fake_request_patches(cur_source, function, request, **_kwargs):
        legacy = [
            CandidatePatch(
                f"node-split-alias-holder-ig{request.target_ig}-use{i}",
                cur_source + f"\n/* legacy {request.target_ig} {i} */",
                "legacy",
                (),
                "",
            )
            for i in range(20)
        ]
        return legacy + [
            CandidatePatch(
                f"node-split-operand-alias-holder-ig{request.target_ig}-b0-s1-opx-o0",
                cur_source + f"\n/* priority {request.target_ig} */",
                "priority",
                (),
                "",
            )
        ]

    monkeypatch.setattr(
        node_set_split,
        "_generate_node_set_request_patches",
        fake_request_patches,
    )

    patches = generate_coupled_node_set_split_patches(
        _TWO_VAR_SOURCE,
        "fn_test",
        [NodeSetSplitRequest("fn_test", 0, 34, target_reg="r27", var_name="holder")],
        max_candidates=0,
    )

    assert any("priority 34" in patch.patched_source for patch in patches)


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


def test_node_set_split_anchors_repeated_local_to_source_scope() -> None:
    source = (
        "void fn_test(int* first, int* second) {\n"
        "    int i;\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        int j;\n"
        "        j = first[i];\n"
        "        first_use(j);\n"
        "    }\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        int j;\n"
        "        j = second[i];\n"
        "        second_use(j);\n"
        "    }\n"
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
                "source": {
                    "kind": "local",
                    "name": "j",
                    "expression": "j",
                    "source_line": 9,
                },
            }
        ],
    }

    req = request_from_node_set_delta(delta, source_text=source)
    assert req is not None
    assert req.var_name == "j"
    assert req.source_scope_path is not None

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )

    alias_lifetime = [
        patch for patch in patches
        if patch.candidate_id.startswith("node-split-alias-j-ig34")
        or patch.candidate_id.startswith("node-split-lifetime-j-ig34")
    ]
    assert alias_lifetime
    assert all("first_use(j_split_34_" not in patch.patched_source
               for patch in alias_lifetime)
    assert all("second_use(j_split_34_" in patch.patched_source
               or "j_split_sink_34_" in patch.patched_source
               for patch in alias_lifetime)


def test_node_set_split_source_line_prefers_innermost_shadowing_scope() -> None:
    source = (
        "void fn_test(int cond) {\n"
        "    int j;\n"
        "    j = 1;\n"
        "    outer_use(j);\n"
        "    if (cond) {\n"
        "        int j;\n"
        "        j = 2;\n"
        "        inner_use(j);\n"
        "    }\n"
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
                "source": {
                    "kind": "local",
                    "name": "j",
                    "expression": "j",
                    "source_line": 8,
                },
            }
        ],
    }

    req = request_from_node_set_delta(delta, source_text=source)
    assert req is not None
    assert req.source_scope_path is not None

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        req,
        max_read_sites=1,
    )

    alias_lifetime = [
        patch for patch in patches
        if patch.candidate_id.startswith("node-split-alias-j-ig34")
        or patch.candidate_id.startswith("node-split-lifetime-j-ig34")
    ]
    assert alias_lifetime
    assert all("outer_use(j_split_34_" not in patch.patched_source
               for patch in alias_lifetime)
    assert all("inner_use(j_split_34_" in patch.patched_source
               or "j_split_sink_34_" in patch.patched_source
               for patch in alias_lifetime)


def test_node_set_split_unscoped_repeated_local_skips_broad_families() -> None:
    source = (
        "void fn_test(int* first, int* second) {\n"
        "    int i;\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        int j;\n"
        "        j = first[i];\n"
        "        first_use(j);\n"
        "    }\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        int j;\n"
        "        j = second[i];\n"
        "        second_use(j);\n"
        "    }\n"
        "}\n"
    )
    request = NodeSetSplitRequest(
        "fn_test",
        0,
        34,
        current_reg="r24",
        target_reg="r27",
        var_name="j",
    )

    patches = generate_node_set_split_patches(
        source,
        "fn_test",
        request,
        max_read_sites=1,
    )

    assert patches
    assert all(
        patch.candidate_id.startswith("node-split-alias-j-ig34")
        or patch.candidate_id.startswith("node-split-lifetime-j-ig34")
        for patch in patches
    )
    assert all(
        not (
            "first_use(j_split_34_" in patch.patched_source
            and "second_use(j_split_34_" in patch.patched_source
        )
        for patch in patches
    )


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


def test_generate_coupled_composes_non_ascii_local_and_owner_split() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "/* owner prefix \u2192 */\n"
        "void fn_test(u8* dst, u8* src) {\n"
        "u8* holder;\n"
        "u8* owner;\n"
        "holder = src;\n"
        "owner = dst;\n"
        "use(owner, holder);\n"
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
                    "kind": "synthetic-owner-split",
                    "expression": "dst",
                    "type": "u8*",
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
        max_candidates=0,
    )

    assert patches
    assert all(
        patch.candidate_id.startswith("node-split-coupled-ig34+ig44-")
        for patch in patches
    )
    assert any("holder_split_34_0" in patch.patched_source for patch in patches)
    assert any("dst_bind_44_0" in patch.patched_source for patch in patches)


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


def test_node_set_split_stack_array_base_terminal_proof_when_no_candidate_hits_targets() -> None:
    reqs = [
        NodeSetSplitRequest(
            "fn_test",
            0,
            40,
            target_reg="r25",
            source_expression="entries",
            source_type="Entry*",
            source_kind="stack-array-base",
        ),
        NodeSetSplitRequest(
            "fn_test",
            0,
            45,
            target_reg="r12",
            source_expression="entries[k].x8",
            source_type="int",
            source_kind="field-load",
        ),
        NodeSetSplitRequest(
            "fn_test",
            0,
            46,
            target_reg="r11",
            source_expression="entries[k].xC",
            source_type="int",
            source_kind="field-load",
        ),
    ]
    aggregate = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r25+r12+r11",
        source_kind="stack-array-base",
    )
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    target_score = {
        "hits": 0,
        "targeted": 3,
        "virtuals": {
            "40": {"expected": 25, "actual": 24, "hit": False},
            "45": {"expected": 12, "actual": 10, "hit": False},
            "46": {"expected": 11, "actual": 9, "hit": False},
        },
    }
    scored = [
        {
            "score": CandidateScore(
                "c0",
                compile_ok=True,
                checkdiff_pct=None,
                checkdiff_delta=None,
                pcdump_score_delta=None,
                diagnostics_path=None,
                status="objective-failed",
            ),
            "objective": {
                "status": "wrong-register",
                "target_score": target_score,
                "source_hunks": [{"hunk_id": "c0", "unified_diff": "@@ c0"}],
                "source_path": "/tmp/c0.c",
                "pcdump_path": "/tmp/c0.pcdump.txt",
            },
        },
        {
            "score": CandidateScore(
                "c1",
                compile_ok=True,
                checkdiff_pct=None,
                checkdiff_delta=None,
                pcdump_score_delta=None,
                diagnostics_path=None,
                status="objective-failed",
            ),
            "objective": {
                "status": "wrong-register",
                "target_score": target_score,
            },
        },
    ]

    summary = summarize_node_set_split_scores(
        "fn_test",
        aggregate,
        patches,
        scored,
        threshold=1.0,
        coupled_requests=reqs,
    )

    assert summary["terminal_reason"] == "stack-array-base-targets-not-realized"
    proof = summary["terminal_proof"]
    assert proof["target_registers"] == {"40": "r25", "45": "r12", "46": "r11"}
    assert proof["generated_count"] == 2
    assert proof["evaluated_count"] == 2
    assert proof["candidates"][0]["target_score"] == target_score
    assert proof["candidates"][0]["source_retained"] == "/tmp/c0.c"
    assert proof["candidates"][0]["pcdump_path"] == "/tmp/c0.pcdump.txt"
    assert proof["candidates"][0]["assigned_registers"] == {
        "40": "r24",
        "45": "r10",
        "46": "r9",
    }


def test_stack_array_base_terminal_proof_requires_evaluated_candidate() -> None:
    request = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r25",
        source_expression="entries",
        source_type="Entry*",
        source_kind="stack-array-base",
    )

    summary = summarize_node_set_split_scores(
        "fn_test",
        request,
        [],
        [],
        threshold=1.0,
    )

    assert summary["status"] == "blocked"
    assert summary["generated_count"] == 0
    assert summary["terminal_reason"] is None
    assert "terminal_proof" not in summary


def test_stack_array_base_terminal_proof_requires_target_score() -> None:
    request = NodeSetSplitRequest(
        "fn_test",
        0,
        40,
        target_reg="r25",
        source_expression="entries",
        source_type="Entry*",
        source_kind="stack-array-base",
    )
    patches = [CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0")]
    scored = [{
        "score": CandidateScore(
            "c0",
            compile_ok=False,
            checkdiff_pct=None,
            checkdiff_delta=None,
            pcdump_score_delta=None,
            diagnostics_path=None,
            status="compile-failed",
        ),
        "objective": {"status": "compile-failed"},
    }]

    summary = summarize_node_set_split_scores(
        "fn_test",
        request,
        patches,
        scored,
        threshold=1.0,
    )

    assert summary["generated_count"] == 1
    assert summary["evaluated_count"] == 1
    assert summary["terminal_reason"] is None
    assert "terminal_proof" not in summary


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


def test_summarize_all_wrong_register_emits_case_c_order_repair_handoff(
    tmp_path: Path,
) -> None:
    retained_pcdump = tmp_path / "retained.pcdump.txt"
    retained_pcdump.write_text(
        "Starting function mnDiagram_DrawCellNumber\n"
        "COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)\n"
        "  iter ig_idx phys degree nIntfr flags\n"
        "    0 46 r0 0 0 0x00\n"
        "      interferers:\n"
        "    1 33 r26 0 0 0x00\n"
        "      interferers:\n",
        encoding="utf-8",
    )
    req = NodeSetSplitRequest(
        "mnDiagram_DrawCellNumber",
        1,
        46,
        current_reg="f0",
        target_reg="f26",
        var_name="col_cast_owner_fpr",
    )
    patches = [CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0")]
    score = CandidateScore(
        "c0",
        compile_ok=True,
        checkdiff_pct=None,
        checkdiff_delta=None,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="objective-failed",
    )

    summary = summarize_node_set_split_scores(
        "mnDiagram_DrawCellNumber",
        req,
        patches,
        [{
            "score": score,
            "source_retained": "/tmp/retained.c",
            "objective": {
                "status": "wrong-register",
                "function": "mnDiagram_DrawCellNumber",
                "class_id": 1,
                "target_ig": 46,
                "target_reg": "f26",
                "target_reg_num": 26,
                "assigned_reg": 0,
                "source_path": "/tmp/retained.c",
                "pcdump_path": str(retained_pcdump),
                "target_score": {
                    "matched": 4,
                    "targeted": 6,
                    "virtuals": {
                        "32": {"expected": 28, "actual": 25, "matched": False},
                        "33": {"expected": 26, "actual": 26, "matched": True},
                        "38": {"expected": 29, "actual": 29, "matched": True},
                        "39": {"expected": 29, "actual": 29, "matched": True},
                        "40": {"expected": 29, "actual": 29, "matched": True},
                        "46": {"expected": 26, "actual": 0, "matched": False},
                    },
                },
            },
        }],
        threshold=1.0,
    )

    handoff = summary["case_c_order_repair"]
    assert handoff["kind"] == "fpr-pcode-temp-case-c-order-repair"
    assert handoff["terminal_evidence"] == "all-wrong-register"
    assert handoff["function"] == "mnDiagram_DrawCellNumber"
    assert handoff["source_file"] == "/tmp/retained.c"
    assert handoff["pcdump"] == str(retained_pcdump)
    assert handoff["force_phys"] == "32:28,33:26,38:29,39:29,40:29,46:26"
    assert handoff["target_order"] == "r33<r46"
    assert handoff["target_score"]["matched"] == 4
    command_text = "\n".join(route["command"] for route in handoff["routes"])
    first_divergence = handoff["routes"][0]["command"]
    select_order_route = next(
        route for route in handoff["routes"]
        if route["kind"] == "retained-source-select-order-repair"
    )
    assert "debug inspect first-divergence" in first_divergence
    assert str(retained_pcdump) in first_divergence
    assert "--json" not in first_divergence
    assert "--class 1" in select_order_route["command"]
    assert "debug mutate simplify-order" not in command_text
    assert "debug permute setup-simplify-order-scorer" in command_text
    assert "debug search plan-transforms" in command_text
    assert "--source-file /tmp/retained.c" in command_text
    assert "--force-phys 32:28,33:26,38:29,39:29,40:29,46:26" in command_text
    assert "--target 'r33<r46'" in command_text
    assert "<TARGET_ORDER_FROM_FIRST_DIVERGENCE>" not in command_text
    assert any("Case-C order repair" in step for step in summary["next_steps"])


def test_summarize_node_set_split_reports_global_renumbering_cascade() -> None:
    req = NodeSetSplitRequest(
        "fn_test",
        0,
        34,
        target_reg="r27",
        var_name="state",
    )
    patches = [CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0")]
    score = CandidateScore(
        "c0",
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
        [{
            "score": score,
            "objective": {
                "status": "wrong-register",
                "target_score": {
                    "matched": 0,
                    "targeted": 3,
                    "renumbered": 3,
                    "virtuals": {
                        "23": {
                            "expected": 27,
                            "candidate_virtual": 22,
                            "actual": 25,
                            "renumbered": True,
                        },
                        "30": {
                            "expected": 25,
                            "candidate_virtual": 29,
                            "actual": 26,
                            "renumbered": True,
                        },
                        "31": {
                            "expected": 26,
                            "candidate_virtual": 30,
                            "actual": 27,
                            "renumbered": True,
                        },
                    },
                },
            },
        }],
        threshold=1.0,
    )

    cascade = summary["global_renumbering_cascade"]
    assert cascade["kind"] == "node-deletion-global-renumbering-cascade"
    assert cascade["renumbered_count"] == 3
    assert cascade["source_model_layer_dimension_id"] == (
        "node-deletion-virtual-renumbering-cascade"
    )
    assert cascade["sample"][0]["baseline_virtual"] == 23
    assert summary["terminal_proof"]["kind"] == (
        "node-deletion-global-renumbering-cascade"
    )
    assert "global virtual renumbering cascade" in " ".join(summary["next_steps"])
    assert "source-level" in cascade["next_handoff"]


def test_summarize_wrong_register_compile_failed_mix_marks_terminal() -> None:
    req = NodeSetSplitRequest("fn_test", 0, 34, target_reg="r27", var_name="holder")
    patches = [
        CandidatePatch("c0", "src0", "c0", ((0, 0),), hunk="@@ c0"),
        CandidatePatch("c1", "src1", "c1", ((0, 0),), hunk="@@ c1"),
    ]
    wrong_score = CandidateScore(
        "c0",
        compile_ok=True,
        checkdiff_pct=None,
        checkdiff_delta=None,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="objective-failed",
    )
    failed_score = CandidateScore(
        "c1",
        compile_ok=False,
        checkdiff_pct=None,
        checkdiff_delta=None,
        pcdump_score_delta=None,
        diagnostics_path="/tmp/c1.c",
        status="compile-failed",
    )

    summary = summarize_node_set_split_scores(
        "fn_test",
        req,
        patches,
        [
            {"score": wrong_score, "objective": {"status": "wrong-register"}},
            {
                "score": failed_score,
                "objective": {
                    "status": "compile-failed",
                    "source_path": "/tmp/c1.c",
                },
            },
        ],
        threshold=1.0,
    )

    assert summary["wrong_register_exhausted"] is False
    assert summary["wrong_register_or_compile_failed_exhausted"] is True
    assert summary["terminal_reason"] == "wrong-register-or-compile-failed"
    assert "do not rerun node-set-split" in " ".join(summary["next_steps"])


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
    assert summary["wrong_register_exhausted"] is False
    assert summary["terminal_reason"] is None
    assert summary["stop_condition"]["kind"] == "candidate-limit"
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
    assert "--remote" in result.output
    assert "--remote-fallback" in result.output
    assert "--remote-host" in result.output
    assert "--remote-script" in result.output
    assert "--remote-branch" in result.output
    assert "--remote-no-pull" in result.output
    assert "--resume-summary" in result.output
    assert "--output" in result.output
    assert "--retain-generated" in result.output


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
    assert summary["stop_condition"]["kind"] == "no-coupled-probes"
    assert len(summary["coupled_requests"]) == 1
    assert summary["shared_source_var"] is None
    classification = summary["in_place_recolor"]
    assert classification["status"] == "insufficient-source-bindings"
    assert classification["terminal"] is False
    assert classification["target_igs"] == [34]


def test_cli_node_set_split_orders_priority_families_before_candidate_cap(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
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

    def fake_generate(source, function, request, **_kwargs):
        legacy = [
            CandidatePatch(
                f"node-split-alias-holder-ig40-use{i}",
                source + f"\n/* legacy {i} */",
                "legacy",
                (),
                "",
            )
            for i in range(8)
        ]
        return legacy + [
            CandidatePatch(
                "node-split-operand-alias-holder-ig40-b0-s1-opx-o0",
                source + "\n/* priority */",
                "priority",
                (),
                "",
            )
        ]

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 31)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_baseline_pct",
        lambda **_kwargs: (50.0, None),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature_and_pcdump",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 29)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_steering_children",
        lambda *args, **kwargs: [],
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "40",
        "--target-reg",
        "r30",
        "--var",
        "holder",
        "--source-file",
        str(source_file),
        "--max-candidates",
        "2",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    summary = _json.loads(result.output)
    candidate_ids = [row["candidate_id"] for row in summary["candidates"]]
    assert candidate_ids == [
        "node-split-operand-alias-holder-ig40-b0-s1-opx-o0",
        "node-split-alias-holder-ig40-use0",
    ]


def test_cli_node_set_split_wrong_register_retains_candidate_pcdump(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
        "void fn_test(void) {\n"
        "    float holder;\n"
        "    holder = makef();\n"
        "    usef(holder);\n"
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

    def fake_generate(source, function, request, **_kwargs):
        return [
            CandidatePatch(
                "retained-wrong-register",
                source + "\n/* wrong register retained */\n",
                "wrong register retained",
                (),
                "",
            )
        ]

    pcdump_text = "candidate pcdump for retained-wrong-register\nCOLORGRAPH\n"

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(46, 1)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_baseline_pct",
        lambda **_kwargs: (50.0, None),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature_and_pcdump",
        lambda *args, **kwargs: (
            _signature(assigned_regs=frozenset({(46, 0)})),
            pcdump_text,
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_steering_children",
        lambda *args, **kwargs: [],
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "46",
        "--target-reg",
        "f26",
        "--var",
        "holder",
        "--class",
        "fpr",
        "--source-file",
        str(source_file),
        "--max-candidates",
        "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    summary = _json.loads(result.output)
    row = summary["candidates"][0]
    pcdump_path = Path(row["pcdump_path"])
    assert pcdump_path.exists()
    assert pcdump_path.read_text(encoding="utf-8") == pcdump_text
    assert row["objective"]["pcdump_path"] == str(pcdump_path)
    assert "case_c_order_repair" not in summary
    assert summary["stop_condition"]["kind"] == "candidate-limit"
    assert summary["stop_condition"]["resume_command"]


def test_cli_node_set_split_target_hit_spill_retains_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
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

    def fake_generate(source, function, request, **_kwargs):
        return [
            CandidatePatch(
                "retained-target-hit-spill",
                source + "\n/* target hit but spill */\n",
                "target hit but spill",
                (),
                "",
            )
        ]

    pcdump_text = "candidate pcdump for retained-target-hit-spill\nCOLORGRAPH\n"

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 28)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_baseline_pct",
        lambda **_kwargs: (50.0, None),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature_and_pcdump",
        lambda *args, **kwargs: (
            _signature(
                assigned_regs=frozenset({(40, 30)}),
                spill_set=frozenset({99}),
            ),
            pcdump_text,
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_steering_children",
        lambda *args, **kwargs: [],
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "40",
        "--target-reg",
        "r30",
        "--var",
        "holder",
        "--source-file",
        str(source_file),
        "--max-candidates",
        "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    summary = _json.loads(result.output)
    row = summary["candidates"][0]
    assert row["objective_status"] == "spill-regression"
    assert row["target_score"]["hits"] == 1
    source_path = Path(row["source_retained"])
    pcdump_path = Path(row["pcdump_path"])
    assert source_path.exists()
    assert source_path.read_text(encoding="utf-8").endswith(
        "/* target hit but spill */\n"
    )
    assert pcdump_path.exists()
    assert pcdump_path.read_text(encoding="utf-8") == pcdump_text
    assert row["objective"]["source_path"] == str(source_path)
    assert row["objective"]["pcdump_path"] == str(pcdump_path)


def test_generated_pointer_walk_local_blocker_maps_iter_to_base_and_counter() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void fn_test(u8* dst, u8 temp) {\n"
        "    int i;\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        for (i = 0; i < 4; i++, ll_probe_iter_0++) {\n"
        "            *ll_probe_iter_0 = temp;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    request = NodeSetSplitRequest(
        function="fn_test",
        class_id=0,
        target_ig=34,
        current_reg="r25",
        target_reg="r27",
        var_name="ll_probe_iter_0",
    )

    blocker = node_set_split._generated_pointer_walk_local_blocker(
        source,
        "fn_test",
        request,
    )

    assert blocker is not None
    assert blocker["kind"] == "generated-pointer-walk-local-no-read-sites"
    assert blocker["var_name"] == "ll_probe_iter_0"
    assert blocker["declared"] is True
    assert blocker["mapped_base"] == "dst"
    assert blocker["candidate_fallback_vars"] == ["dst", "i"]


def test_cli_node_set_split_generated_pointer_walk_local_reports_terminal_blocker(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split_module

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
        "typedef unsigned char u8;\n"
        "void fn_test(u8* dst, u8 temp) {\n"
        "    int i;\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        for (i = 0; i < 4; i++, ll_probe_iter_0++) {\n"
        "            *ll_probe_iter_0 = temp;\n"
        "        }\n"
        "    }\n"
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

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split_module,
        "generate_node_set_split_patches",
        lambda *args, **kwargs: [],
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "34",
        "--current-reg",
        "r25",
        "--target-reg",
        "r27",
        "--var",
        "ll_probe_iter_0",
        "--source-file",
        str(source_file),
        "--json",
    ])

    assert result.exit_code == 3, result.output
    summary = _json.loads(result.output)
    assert summary["status"] == "blocked"
    assert summary["stop_condition"]["kind"] == "no-source-probes"
    assert (
        summary["blocked_reason"]
        == "generated pointer-walk local ll_probe_iter_0 has no safe read-site source candidates"
    )
    blocker = summary["source_attribution_blocker"]
    assert blocker["kind"] == "generated-pointer-walk-local-no-read-sites"
    assert blocker["declared"] is True
    assert blocker["mapped_base"] == "dst"
    assert blocker["candidate_fallback_vars"] == ["dst", "i"]
    assert any("--var dst" in step for step in summary["next_steps"])


def test_cli_node_set_split_single_ig_generation_budget_emits_json(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
        "typedef float f32;\n"
        "void fn_test(void* jobj, f32 x_spacing, f32 col_offset, int i) {\n"
        "    HSD_JObjSetTranslateX(jobj, (x_spacing * (f32) i) + col_offset);\n"
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
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 38,
            "current_register": "f28",
            "desired_registers": ["f29"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "col_offset",
                "type": "f32",
            },
        }],
    }), encoding="utf-8")

    now = {"value": 100.0}
    received_deadlines: list[float | None] = []

    def fake_monotonic() -> float:
        return now["value"]

    def fake_generate(source, function, request, **kwargs):
        deadline = kwargs.get("deadline")
        received_deadlines.append(deadline)
        if deadline is None:
            raise AssertionError(
                "single-ig node-set generation must receive the global deadline"
            )
        now["value"] = deadline + 0.01
        return [
            CandidatePatch(
                "node-split-generated-before-budget",
                source + "\n/* generated before budget exhausted */\n",
                "generated before budget exhausted",
                (),
                "",
            )
        ]

    def fail_compile(*_args, **_kwargs):
        raise AssertionError("budget-exhausted generation must not compile")

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(cli_debug.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_introduce_binding_patches",
        fake_generate,
    )
    monkeypatch.setattr(cli_debug, "_node_set_split_compile_signature", fail_compile)
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_source_baseline_pct",
        fail_compile,
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--node-set-delta",
        str(delta),
        "--source-file",
        str(source_file),
        "--budget",
        "0.01",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    assert received_deadlines == [100.01]
    summary = _json.loads(result.output)
    assert summary["status"] == "exhausted"
    assert summary["generated_count"] == 1
    assert summary["scored_count"] == 0
    assert summary["pending_count"] == 1
    assert summary["stop_condition"]["kind"] == "budget-exhausted"
    assert summary["stop_condition"]["budget_seconds"] == 0.01


def test_cli_node_set_split_retained_source_compiles_through_real_unit(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    holder = live_make();\n"
        "    use(holder);\n"
        "}\n",
        encoding="utf-8",
    )
    retained_source = melee_root / "build" / "diagnostics" / "retained.c"
    retained_source.parent.mkdir(parents=True)
    retained_source.write_text(
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    holder = retained_make();\n"
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

    generated_sources: list[str] = []
    compile_unit_sources: list[tuple[str, str, str]] = []
    baseline_pct_calls: list[dict[str, object]] = []

    def fake_generate(source, function, request, **_kwargs):
        generated_sources.append(source)
        return [
            CandidatePatch(
                "retained-candidate",
                source + "\n/* patched retained */\n",
                "retained",
                (),
                "",
            )
        ]

    def fake_baseline_signature(path, *, label, unit_source, **_kwargs):
        compile_unit_sources.append((label, str(path), str(unit_source)))
        return _signature(assigned_regs=frozenset({(40, 31)}))

    def fake_candidate_signature(path, *, label, unit_source, **_kwargs):
        compile_unit_sources.append((label, str(path), str(unit_source)))
        assert "retained_make" in path.read_text(encoding="utf-8")
        return _signature(assigned_regs=frozenset({(40, 29)}))

    def fake_retained_baseline_pct(**kwargs):
        baseline_pct_calls.append(kwargs)
        return (61.0, None)

    def fail_direct_baseline_pct(**_kwargs):
        raise AssertionError(
            "retained --source-file must not use direct live-source baseline pct"
        )

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature",
        fake_baseline_signature,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature_and_pcdump",
        fake_candidate_signature,
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_baseline_pct",
        fail_direct_baseline_pct,
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_source_baseline_pct",
        fake_retained_baseline_pct,
        raising=False,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_steering_children",
        lambda *args, **kwargs: [],
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "40",
        "--target-reg",
        "r30",
        "--var",
        "holder",
        "--source-file",
        str(retained_source),
        "--max-candidates",
        "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    assert len(generated_sources) == 1
    assert "retained_make" in generated_sources[0]
    assert "live_make" not in generated_sources[0]
    assert compile_unit_sources[0] == (
        "baseline",
        str(retained_source),
        str(source_file),
    )
    assert compile_unit_sources[1][0] == "retained-candidate"
    assert compile_unit_sources[1][2] == str(source_file)
    assert baseline_pct_calls == [{
        "source_path": retained_source,
        "unit": "melee/mn/sample",
        "function": "fn_test",
        "melee_root": melee_root,
        "timeout": 120.0,
        "deadline": None,
        "compile_unit_source": source_file,
    }]


def test_cli_node_set_split_retained_source_scores_realized_full_unit(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
        "int live_unit_marker = 1;\n"
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    holder = live_make();\n"
        "    use(holder);\n"
        "}\n",
        encoding="utf-8",
    )
    retained_source = melee_root / "build" / "diagnostics" / "retained.c"
    retained_source.parent.mkdir(parents=True)
    retained_source.write_text(
        "int retained_unit_marker = 2;\n"
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    holder = retained_make();\n"
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

    score_calls: list[tuple[str, bool]] = []

    def fake_generate(source, function, request, **_kwargs):
        return [
            CandidatePatch(
                "retained-realized-candidate",
                source.replace("retained_make", "patched_retained_make"),
                "retained realized",
                (),
                "",
            )
        ]

    def fake_score_source(path, *, full_unit_source=False, **_kwargs):
        text = path.read_text(encoding="utf-8")
        score_calls.append((text, full_unit_source))
        return cli_debug._SourceCandidateRealScore(63.0, None)

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 31)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature_and_pcdump",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 30)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_source_baseline_pct",
        lambda **_kwargs: (60.0, None),
        raising=False,
    )
    monkeypatch.setattr(
        cli_debug,
        "_score_source_candidate_real_tree",
        fake_score_source,
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "40",
        "--target-reg",
        "r30",
        "--var",
        "holder",
        "--source-file",
        str(retained_source),
        "--max-candidates",
        "1",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    summary = _json.loads(result.output)
    assert summary["best_candidate_id"] == "retained-realized-candidate"
    assert len(score_calls) == 1
    scored_text, full_unit_source = score_calls[0]
    assert full_unit_source is True
    assert "retained_unit_marker" in scored_text
    assert "patched_retained_make" in scored_text
    assert "live_unit_marker" not in scored_text


def test_node_set_split_same_tu_compile_path_transfers_same_directory_copy(
    tmp_path,
) -> None:
    from src.cli import debug as cli_debug

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    unit_source = src_dir / "sample.c"
    original = (
        "void fn_test(void) {\n"
        "    live_call();\n"
        "}\n"
    )
    unit_source.write_text(original, encoding="utf-8")
    same_dir_copy = src_dir / "sample-retained.c"
    same_dir_copy.write_text(
        "void fn_test(void) {\n"
        "    retained_call();\n"
        "}\n",
        encoding="utf-8",
    )

    with cli_debug._node_set_split_same_tu_compile_path(
        same_dir_copy,
        function="fn_test",
        melee_root=melee_root,
        unit_source=unit_source,
    ) as compile_path:
        assert compile_path == unit_source.resolve()
        assert "retained_call" in unit_source.read_text(encoding="utf-8")

    assert unit_source.read_text(encoding="utf-8") == original


def test_cli_node_set_split_long_candidate_id_emits_json(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
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
    long_candidate_id = (
        "node-split-introduce-binding-"
        + "very-long-retained-candidate-name-" * 12
        + "tail"
    )

    def fake_generate(source, function, request, **_kwargs):
        return [
            CandidatePatch(
                long_candidate_id,
                source + "\n/* long id candidate */\n",
                "long-id",
                (),
                "",
            )
        ]

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 31)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_baseline_pct",
        lambda **_kwargs: (50.0, None),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature_and_pcdump",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 29)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_steering_children",
        lambda *args, **kwargs: [],
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "40",
        "--target-reg",
        "r30",
        "--var",
        "holder",
        "--source-file",
        str(source_file),
        "--max-candidates",
        "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    summary = _json.loads(result.output)
    assert summary["candidates"][0]["candidate_id"] == long_candidate_id
    retained = summary["candidates"][0]["objective"]["source_path"]
    assert len(Path(retained).name.encode("utf-8")) <= 255


def test_cli_node_set_split_long_candidate_id_scores_realized_candidate(
    tmp_path,
    monkeypatch,
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from src.cli import debug as cli_debug
    import src.mwcc_debug.node_set_split as node_set_split

    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source_file = src_dir / "sample.c"
    source_file.write_text(
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
    long_candidate_id = (
        "node-split-realized-"
        + "very-long-retained-candidate-name-" * 12
        + "tail"
    )
    scored_temp_names: list[str] = []

    def fake_generate(source, function, request, **_kwargs):
        return [
            CandidatePatch(
                long_candidate_id,
                source + "\n/* realized long id candidate */\n",
                "long-id",
                (),
                "@@ realized long id\n- holder = make();\n+ holder = make();",
            )
        ]

    def fake_score_source(path, *, full_unit_source=False, **_kwargs):
        scored_temp_names.append(path.name)
        return cli_debug._SourceCandidateRealScore(52.0, None)

    monkeypatch.setattr(cli_debug, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 31)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_fresh_node_set_split_baseline_pct",
        lambda **_kwargs: (50.0, None),
    )
    monkeypatch.setattr(
        cli_debug,
        "_node_set_split_compile_signature_and_pcdump",
        lambda *args, **kwargs: _signature(
            assigned_regs=frozenset({(40, 30)})
        ),
    )
    monkeypatch.setattr(
        cli_debug,
        "_score_source_candidate_real_tree",
        fake_score_source,
    )

    runner = CliRunner()
    result = runner.invoke(cli_debug.solve_app, [
        "node-set-split",
        "-f",
        "fn_test",
        "--ig",
        "40",
        "--target-reg",
        "r30",
        "--var",
        "holder",
        "--source-file",
        str(source_file),
        "--max-candidates",
        "1",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    summary = _json.loads(result.output)
    assert summary["best_candidate_id"] == long_candidate_id
    assert len(scored_temp_names) == 1
    assert len(scored_temp_names[0].encode("utf-8")) <= 255
    row = summary["candidates"][0]
    retained = Path(row["source_retained"])
    assert retained.exists()
    assert len(retained.name.encode("utf-8")) <= 255
    assert row["objective"]["source_path"] == str(retained)
    assert row["source_hunk"] == (
        "@@ realized long id\n- holder = make();\n+ holder = make();"
    )
