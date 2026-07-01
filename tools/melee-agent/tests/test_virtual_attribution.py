"""Tests for virtual-register source/interference attribution."""

from __future__ import annotations

import json
import pathlib
import subprocess
import textwrap

from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug.source_field_attribution import (
    build_source_field_context,
    source_for_field_offset,
)
from src.mwcc_debug.virtual_attribution import explain_virtuals

CLI_CWD = pathlib.Path(__file__).parent.parent
runner = CliRunner()


PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    AFTER INSTRUCTION SELECTION
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r50,r3
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
        stw r40,16(r32)
    B1: Succ={} Pred={} Labels={}
        lwz r43,24(r32)
        add r44,r43,r33
    AFTER REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r31,12(r3)
        add r30,r31,r4
        stw r30,16(r3)
    B1: Succ={} Pred={} Labels={}
        lwz r29,24(r3)
        add r28,r29,r4
    SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 33 2 2 0x00
        1 37 1 1 0x00
        2 40 1 1 0x00
        3 43 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=4)
      iter ig_idx phys degree nIntfr flags
        0 33 r4 2 2 0x00
          interferers: 43=r29
        1 37 r31 1 1 0x00
          interferers: 40=r30
        2 40 r30 1 1 0x00
          interferers: 37=r31
        3 43 r29 1 1 0x00
          interferers: 33=r4
""")


SOURCE = textwrap.dedent("""\
    typedef struct Obj {
        int xC;
        int x10;
        int x18;
    } Obj;

    void fn_80000000(Obj* obj, int extra) {
        int temp;
        temp = obj->xC + extra;
        obj->x10 = temp;
        sink(obj->x18 + extra);
    }
""")


def test_explain_virtuals_attaches_source_and_interference() -> None:
    report = explain_virtuals(
        PCDUMP,
        "fn_80000000",
        virtuals=[37, 40, 43, 33],
        pairs=[(37, 40), (43, 33)],
        source_text=SOURCE,
        source_file="sample.c",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    assert by_virtual[37].source is not None
    assert by_virtual[37].source.expression == "obj->xC"
    assert by_virtual[37].source.source_line == 9
    assert by_virtual[37].source.base_virtual == 32
    assert by_virtual[37].live_blocks == (0,)
    assert by_virtual[37].assigned_reg == 31
    assert by_virtual[37].last_occurrence is not None
    assert by_virtual[37].last_occurrence.pass_name == "BEFORE REGISTER COLORING"

    assert by_virtual[33].source is not None
    assert by_virtual[33].source.name == "extra"
    assert by_virtual[33].source.kind == "param"

    first = report.pair_interferences[0]
    assert first.virtual == 37
    assert first.other_virtual == 40
    assert first.colorgraph_interference is True
    assert first.live_overlap is True
    assert "cannot coalesce" in first.reason
    assert "live ranges overlap" in first.reason

    second = report.pair_interferences[1]
    assert second.virtual == 43
    assert second.other_virtual == 33
    assert second.colorgraph_interference is True
    assert second.live_overlap is True


def test_explain_virtuals_ignores_colorgraph_interferer_rows_as_occurrences() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000001
        BEFORE REGISTER COLORING
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            mr r37,r33
        AFTER PEEPHOLE FORWARD
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            mr r37,r33
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
          iter ig_idx phys degree nIntfr flags
            0 45 r40 1 1 0x00
              interferers: 40=r6 45=r40 120=r-1 121=r-1
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000001",
        virtuals=[40, 45],
        source_text="void fn_80000001(void) {}\n",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    entry = by_virtual[40]
    assert entry.status == "not-found"
    assert entry.live_range is None
    assert entry.use_count == 0
    assert entry.first_occurrence is None
    assert entry.last_occurrence is None
    assert entry.source is None
    assert entry.note is not None
    assert "not found in parsed pcode passes" in entry.note

    colorgraph_only = by_virtual[45]
    assert colorgraph_only.status == "colorgraph"
    assert colorgraph_only.first_occurrence is None
    assert colorgraph_only.last_occurrence is None
    assert colorgraph_only.note is not None
    assert "no real pcode occurrence" in colorgraph_only.note


def test_explain_virtuals_collapses_call_return_copy_chain_to_source() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000002
        BEFORE GLOBAL OPTIMIZATION
        fn_80000002
        B19: Succ={B20} Pred={} Labels={}
            bl helper_fn
        B20: Succ={B33} Pred={B19} Labels={}
            mr r59,r3
            mr r43,r59
            mr r40,r43
            cmpi cr0,r43,1
        B33: Succ={} Pred={B20} Labels={}
            cmpi cr0,r40,0
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)
          iter ig_idx phys degree nIntfr flags
            0 59 r0 0 0 0x00
            1 43 r0 0 0 0x00
            2 40 r0 0 0 0x00
    """)
    source = textwrap.dedent("""\
        void fn_80000002(void* entity) {
            int result;
            int b34;
            result = helper_fn(entity);
            b34 = result;
            if (b34 == 0) {
                sink();
            }
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000002",
        virtuals=[40],
        source_text=source,
        source_file="sample.c",
    )

    source_info = report.virtuals[0].source
    assert source_info is not None
    assert source_info.kind == "call-return"
    assert source_info.confidence == "copy-chain"
    assert source_info.name == "result"
    assert source_info.expression == "helper_fn(entity)"
    assert source_info.call_symbol == "helper_fn"
    assert source_info.copy_chain == (40, 43, 59, 3)
    assert source_info.source_file == "sample.c"
    assert source_info.source_line == 4
    assert [site.opcode for site in source_info.use_sites] == ["cmpi"]


def test_explain_virtuals_classifies_ir_first_def_provenance_without_source() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000003
        BEFORE REGISTER COLORING
        fn_80000003
        B0: Succ={} Pred={} Labels={}
            add r38,r32,r33
            mr r39,r38
            lwz r44,12(r32)
        AFTER REGISTER COLORING
        fn_80000003
        B0: Succ={} Pred={} Labels={}
            add r6,r3,r4
            mr r7,r6
            lwz r8,12(r3)
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000003",
        virtuals=[38, 39, 44],
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    assert by_virtual[38].source is not None
    assert by_virtual[38].source.kind == "implicit-temp"
    assert by_virtual[38].source.confidence == "pcode-first-def"
    assert by_virtual[38].source.expression == "add r38,r32,r33"

    assert by_virtual[39].source is not None
    assert by_virtual[39].source.kind == "copy/coalesce-product"
    assert by_virtual[39].source.base_virtual == 38
    assert by_virtual[39].source.expression == "mr r39,r38"

    assert by_virtual[44].source is not None
    assert by_virtual[44].source.kind == "load/store-address"
    assert by_virtual[44].source.base_virtual == 32
    assert by_virtual[44].source.field_offset == 12


def test_explain_virtuals_classifies_fpr_load_first_def_as_field_address() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000004
        BEFORE REGISTER COLORING
        fn_80000004
        B0: Succ={} Pred={} Labels={}
            lfs f41,60(r44)
        AFTER REGISTER COLORING
        fn_80000004
        B0: Succ={} Pred={} Labels={}
            lfs f30,60(r31)
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000004",
        virtuals=[41],
        reg_class="fpr",
    )

    source_info = report.virtuals[0].source
    assert source_info is not None
    assert source_info.kind == "load/store-address"
    assert source_info.confidence == "pcode-first-def"
    assert source_info.expression == "lfs f41,60(r44)"
    assert source_info.base_virtual == 44
    assert source_info.field_offset == 60
    assert source_info.first_def is not None
    assert source_info.first_def.opcode == "lfs"


def test_explain_virtuals_resolves_chained_pcode_loads_to_typed_source() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000010
        BEFORE REGISTER COLORING
        fn_80000010
        B0: Succ={} Pred={} Labels={}
            lwz r106,gGlobalObj(r0)
            lwz r58,44(r106)
            lbz r36,72(r58)
            mr r88,r106
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=4)
          iter ig_idx phys degree nIntfr flags
            0 106 r28 0 0 0x00
            1 58 r28 0 0 0x00
            2 36 r28 0 0 0x00
            3 88 r4 0 0 0x00
    """)
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        struct HSD_GObj {
            /* +00 */ int pad0;
            /* +2C */ void* user_data;
        };
        struct Diagram2 {
            /* 0x00 */ int pad0;
            /* 0x46 */ u8 selected_fighter_idx;
            /* 0x47 */ u8 selected_name_idx;
            /* 0x48 */ u8 is_name_mode;
        };
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram2 Diagram2;
        extern HSD_GObj* gGlobalObj;

        void fn_80000010(void) {
            Diagram2* data2;
            u8 x48;
            data2 = gGlobalObj->user_data;
            x48 = data2->is_name_mode;
            sink(x48);
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000010",
        virtuals=[58, 36, 88],
        source_text=source,
        source_file="sample.c",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    user_data = by_virtual[58].source
    assert user_data is not None
    assert user_data.kind == "field-load"
    assert user_data.expression == "gGlobalObj->user_data"
    assert user_data.type == "Diagram2*"
    assert user_data.base_virtual == 106
    assert user_data.base_var == "gGlobalObj"
    assert user_data.field_name == "user_data"
    assert user_data.source_line == 19

    is_name_mode = by_virtual[36].source
    assert is_name_mode is not None
    assert is_name_mode.kind == "field-load"
    assert is_name_mode.expression == "data2->is_name_mode"
    assert is_name_mode.type == "u8"
    assert is_name_mode.base_virtual == 58
    assert is_name_mode.base_var == "data2"
    assert is_name_mode.field_name == "is_name_mode"
    assert is_name_mode.source_line == 20

    copied_global = by_virtual[88].source
    assert copied_global is not None
    assert copied_global.kind == "copy/coalesce-source"
    assert copied_global.expression == "gGlobalObj"
    assert copied_global.type == "HSD_GObj*"
    assert copied_global.copy_chain == (88, 106)


def test_source_field_attribution_ignores_locals_and_prefers_near_alias() -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        struct HSD_GObj {
            /* +00 */ int pad0;
            /* +2C */ void* user_data;
        };
        struct Diagram2 {
            /* 0x00 */ int pad0;
            /* 0x48 */ u8 is_name_mode;
        };
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram2 Diagram2;
        extern HSD_GObj* gGlobalObj;

        void fn_80000011(void) {
            Diagram2* data;
            Diagram2* data2;
            u8 x48;
            data = gGlobalObj->user_data;
            if (other()) {
                data2 = gGlobalObj->user_data;
                x48 = data2->is_name_mode;
            }
            sink(data->is_name_mode);
        }
    """)

    context = build_source_field_context(source, function="fn_80000011")

    assert "gGlobalObj" in context.global_types
    assert "data" not in context.global_types
    assert "data2" not in context.global_types
    assert "x48" not in context.global_types

    resolved = source_for_field_offset(
        context,
        base_expression="gGlobalObj->user_data",
        base_type="Diagram2*",
        offset=0x48,
    )

    assert resolved is not None
    assert resolved.expression == "data2->is_name_mode"
    assert resolved.source_line == 21


def test_source_field_attribution_refines_void_field_base_from_alias_type() -> None:
    source = textwrap.dedent("""\
        typedef unsigned char u8;
        struct HSD_GObj {
            /* +00 */ int pad0;
            /* +2C */ void* user_data;
        };
        struct Diagram2 {
            /* 0x00 */ int pad0;
            /* 0x48 */ u8 is_name_mode;
        };
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram2 Diagram2;
        extern HSD_GObj* gGlobalObj;

        void fn_80000012(void) {
            Diagram2* data;
            Diagram2* data2;
            u8 x48;
            data = gGlobalObj->user_data;
            if (other()) {
                data2 = gGlobalObj->user_data;
                x48 = data2->is_name_mode;
            }
            sink(data->is_name_mode);
        }
    """)

    context = build_source_field_context(source, function="fn_80000012")

    resolved = source_for_field_offset(
        context,
        base_expression="gGlobalObj->user_data",
        base_type="void*",
        offset=0x48,
    )

    assert resolved is not None
    assert resolved.expression == "data2->is_name_mode"
    assert resolved.type == "u8"
    assert resolved.source_line == 21


def test_source_field_attribution_resolves_nested_struct_offsets() -> None:
    source = textwrap.dedent("""\
        typedef float f32;
        typedef struct {
            f32 x, y, z;
        } Vec3, *Vec3Ptr;
        typedef struct HSD_JObj {
            /* 0x2C */ Vec3 scale;
            /* 0x38 */ Vec3 translate;
        } HSD_JObj;

        void fn_80000013(HSD_JObj* row0) {
            sink(row0);
        }
    """)

    context = build_source_field_context(source, function="fn_80000013")

    y = source_for_field_offset(
        context,
        base_expression="row0",
        base_type="HSD_JObj*",
        offset=0x3C,
    )
    z = source_for_field_offset(
        context,
        base_expression="row0",
        base_type="HSD_JObj*",
        offset=0x40,
    )

    assert y is not None
    assert y.expression == "row0->translate.y"
    assert y.field_name == "translate.y"
    assert y.type == "f32"
    assert z is not None
    assert z.expression == "row0->translate.z"
    assert z.field_name == "translate.z"
    assert z.type == "f32"


def test_source_field_attribution_resolves_nested_offsets_through_extern_include(
    tmp_path: pathlib.Path,
) -> None:
    root = tmp_path / "melee"
    source_path = root / "src" / "melee" / "mn" / "sample.c"
    jobj_path = root / "src" / "sysdolphin" / "baselib" / "jobj.h"
    mtx_path = root / "extern" / "dolphin" / "include" / "dolphin" / "mtx.h"
    source_path.parent.mkdir(parents=True)
    jobj_path.parent.mkdir(parents=True)
    mtx_path.parent.mkdir(parents=True)
    mtx_path.write_text(textwrap.dedent("""\
        typedef float f32;
        typedef struct {
            f32 x, y, z;
        } Vec, Vec3, *VecPtr, Point3d, *Point3dPtr;
    """))
    jobj_path.write_text(textwrap.dedent("""\
        #include <dolphin/mtx.h>
        typedef struct HSD_JObj {
            /* +2C */ Vec3 scale;
            /* +38 */ Vec3 translate;
        } HSD_JObj;
    """))
    source = textwrap.dedent("""\
        #include <baselib/jobj.h>
        void sample(HSD_JObj* row0) {
            sink(row0);
        }
    """)
    source_path.write_text(source)

    context = build_source_field_context(
        source,
        function="sample",
        source_file=source_path,
        melee_root=root,
    )
    resolved = source_for_field_offset(
        context,
        base_expression="row0",
        base_type="HSD_JObj*",
        offset=0x3C,
    )

    assert resolved is not None
    assert resolved.expression == "row0->translate.y"
    assert resolved.field_name == "translate.y"
    assert resolved.type == "f32"


def test_explain_virtuals_prefers_pcode_over_low_confidence_binding() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000009
        BEFORE REGISTER COLORING
        fn_80000009
        B0: Succ={} Pred={} Labels={}
            mr r32,r3
            mr r33,r4
            mr r34,r39
            addi r35,r3,0
            addi r36,r3,4
            addi r37,r3,8
            addi r38,r3,12
            addi r39,r3,16
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
          iter ig_idx phys degree nIntfr flags
            0 34 r30 0 0 0x00
    """)
    source = textwrap.dedent("""\
        void fn_80000009(void) {
            int probe_a;
            int probe_b;
            int totals;
            int dst_iter;
            sink(dst_iter);
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000009",
        virtuals=[34],
        source_text=source,
        source_file="sample.c",
    )

    source_info = report.virtuals[0].source
    assert source_info is not None
    assert source_info.kind == "copy/coalesce-product"
    assert source_info.confidence == "pcode-first-def"
    assert source_info.expression == "mr r34,r39"
    assert source_info.base_virtual == 39


def test_explain_virtuals_uses_fpr_class_for_first_def_provenance() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000004
        BEFORE REGISTER COLORING
        fn_80000004
        B0: Succ={} Pred={} Labels={}
            bl helper
            frsp f42,f1
            stfs f42,0x30(r1)
        COLORGRAPH DECISIONS (class=1, result=1, n_nodes=1)
          iter ig_idx phys degree nIntfr flags
            0 42 r6 0 0 0x00
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000004",
        virtuals=[42],
        reg_class="fpr",
    )

    entry = report.virtuals[0]
    assert entry.class_id == 1
    assert entry.assigned_reg == 6
    assert entry.first_occurrence is not None
    assert entry.first_occurrence.opcode == "frsp"
    assert entry.source is not None
    assert entry.source.kind == "fpr-temp"
    assert entry.source.expression == "frsp f42,f1"
    assert entry.source.first_def is not None
    assert entry.source.first_def.opcode == "frsp"


def test_explain_virtuals_keeps_pcode_only_fpr_virtuals_in_fpr_class() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000009
        BEFORE REGISTER COLORING
        fn_80000009
        B0: Succ={} Pred={} Labels={}
            fsubs f33,f52,f51
            fmr f1,f33
        AFTER REGISTER COLORING
        fn_80000009
        B0: Succ={} Pred={} Labels={}
            fsubs f1,f0,f2
            fmr f1,f1
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000009",
        virtuals=[33],
        reg_class="fpr",
    )

    entry = report.virtuals[0]
    assert entry.status == "pcode-only"
    assert entry.assigned_reg == 1
    assert entry.first_occurrence is not None
    assert entry.first_occurrence.opcode == "fsubs"
    assert entry.source is not None
    assert entry.source.kind == "fpr-temp"
    assert entry.source.expression == "fsubs f33,f52,f51"


def test_explain_virtuals_binds_fpr_product_to_float_local_assignment() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000005
        BEFORE REGISTER COLORING
        fn_80000005
        B0: Succ={} Pred={} Labels={}
            fmuls f33,f35,f46
            fmuls f37,f47,f50
        COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)
          iter ig_idx phys degree nIntfr flags
            0 33 r27 0 0 0x00
            1 37 r28 0 0 0x00
    """)
    source = textwrap.dedent("""\
        typedef float f32;
        void fn_80000005(f32 y_spacing, f32 col, f32 y_offset, f32 row) {
            f32 col_offset;
            f32 row_offset;
            col_offset = y_spacing * col;
            row_offset = y_offset * row;
            sink(col_offset, row_offset);
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000005",
        virtuals=[33, 37],
        source_text=source,
        source_file="sample.c",
        reg_class="fpr",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    col_offset = by_virtual[33].source
    row_offset = by_virtual[37].source
    assert col_offset is not None
    assert col_offset.kind == "local"
    assert col_offset.confidence == "fpr-expression-order"
    assert col_offset.name == "col_offset"
    assert col_offset.type == "f32"
    assert col_offset.expression == "y_spacing * col"
    assert row_offset is not None
    assert row_offset.kind == "local"
    assert row_offset.confidence == "fpr-expression-order"
    assert row_offset.name == "row_offset"
    assert row_offset.expression == "y_offset * row"


def test_explain_virtuals_binds_fpr_subtraction_to_float_local_assignment() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000006
        BEFORE REGISTER COLORING
        fn_80000006
        B0: Succ={} Pred={} Labels={}
            fsubs f36,f42,f41
            lfd f44,@192(r0)
            lfd f45,@1518(r1)
            fsubs f46,f45,f44
            fmuls f38,f35,f49
            lfs f50,@1517(r0)
            fsubs f33,f38,f50
        COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)
          iter ig_idx phys degree nIntfr flags
            0 36 r27 0 0 0x00
            1 33 r28 0 0 0x00
    """)
    source = textwrap.dedent("""\
        typedef float f32;
        void fn_80000006(f32 base, f32 y_offset, f32 row) {
            f32 y_spacing;
            f32 row_offset;
            f32 row_offset_adj;
            y_spacing = y_offset - base;
            row_offset = y_offset * row;
            row_offset_adj = row_offset - 0.4f;
            sink(y_spacing, row_offset_adj);
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000006",
        virtuals=[36, 33],
        source_text=source,
        source_file="sample.c",
        reg_class="fpr",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    first = by_virtual[36].source
    second = by_virtual[33].source
    assert first is not None
    assert first.kind == "local"
    assert first.confidence == "fpr-expression-order"
    assert first.name == "y_spacing"
    assert first.type == "f32"
    assert first.expression == "y_offset - base"
    assert second is not None
    assert second.kind == "local"
    assert second.confidence == "fpr-expression-order"
    assert second.name == "row_offset_adj"
    assert second.type == "f32"
    assert second.expression == "row_offset - 0.4f"


def test_explain_virtuals_ignores_unary_minus_for_fpr_subtraction_rank() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000007
        BEFORE REGISTER COLORING
        fn_80000007
        B0: Succ={} Pred={} Labels={}
            fsubs f33,f42,f41
        COLORGRAPH DECISIONS (class=1, result=1, n_nodes=1)
          iter ig_idx phys degree nIntfr flags
            0 33 r28 0 0 0x00
    """)
    source = textwrap.dedent("""\
        typedef float f32;
        void fn_80000007(f32 base, f32 y_offset) {
            f32 negated;
            f32 cast_negated;
            f32 delta;
            negated = -base;
            cast_negated = (f32) -base;
            delta = y_offset - base;
            sink(negated, cast_negated, delta);
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000007",
        virtuals=[33],
        source_text=source,
        source_file="sample.c",
        reg_class="fpr",
    )

    source_attr = report.virtuals[0].source
    assert source_attr is not None
    assert source_attr.kind == "local"
    assert source_attr.name == "delta"
    assert source_attr.type == "f32"
    assert source_attr.expression == "y_offset - base"


def test_explain_virtual_cli_all_reports_every_pcode_virtual(tmp_path: pathlib.Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    source = tmp_path / "sample.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-virtual",
            "-f",
            "fn_80000000",
            "--all",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert {entry["virtual"] for entry in payload["virtuals"]} == {
        32,
        33,
        37,
        40,
        43,
        44,
        50,
    }
    by_virtual = {entry["virtual"]: entry for entry in payload["virtuals"]}
    assert by_virtual[32]["source"]["name"] == "obj"
    assert by_virtual[33]["source"]["kind"] == "param"
    assert by_virtual[37]["source"]["expression"] == "obj->xC"
    assert by_virtual[43]["source"]["expression"] == "obj->x18"
    assert by_virtual[44]["source"]["kind"] == "implicit-temp"


def test_explain_virtual_cli_outputs_json(tmp_path: pathlib.Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    source = tmp_path / "sample.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-virtual",
            "-f",
            "fn_80000000",
            "--virtuals",
            "r37,r40,r43,r33",
            "--pairs",
            "r37:r40,r43:r33",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["function"] == "fn_80000000"
    assert payload["virtuals"][0]["virtual"] == 37
    assert payload["virtuals"][0]["source"]["expression"] == "obj->xC"
    assert payload["pair_interferences"][0]["colorgraph_interference"] is True
    assert "cannot coalesce" in payload["pair_interferences"][0]["reason"]


def test_explain_virtual_help_is_registered() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "inspect",
            "explain-virtual", "--help",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--virtuals" in proc.stdout
    assert "--pairs" in proc.stdout
    assert "source/interference" in proc.stdout
