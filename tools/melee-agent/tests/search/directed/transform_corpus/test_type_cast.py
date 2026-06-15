"""Tests for the type_cast transform family (transform_corpus.type_cast)."""
from __future__ import annotations

import pytest

from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    generate_transform_probes,
    plan_transform_experiments,
)
from src.search.directed.transform_probe_adapter import transform_probe_key
from src.mwcc_debug.source_shape import CandidatePatch


def _type_cast_compatibility_probes(source: str, *, max_per_family: int = 3):
    return generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=(
            "redundant_pointer_cast_elision",
            "callback_cast_elision",
            "vector_alias_type_shape",
        ),
        max_per_family=max_per_family,
    )


def test_generate_transform_probes_materializes_type_cast_compatibility_mutators() -> None:
    source = (
        "typedef float f32;\n"
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
        "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
        "void use_gobj(HSD_GObj* gobj);\n"
        "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
        "void callback(HSD_GObj* gobj);\n"
        "void target(void) {\n"
        "    HSD_GObj* gobj;\n"
        "    HSD_GObj* alias;\n"
        "    Point3d pos;\n"
        "    use_gobj((HSD_GObj*) gobj);\n"
        "    alias = (HSD_GObj*) gobj;\n"
        "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
        "    consume_vec(pos);\n"
        "}\n"
    )

    probes = _type_cast_compatibility_probes(source, max_per_family=3)

    pointer_probes = [
        probe for probe in probes
        if probe.family_id == "redundant_pointer_cast_elision"
    ]
    assert len(pointer_probes) == 2
    assert all(
        probe.mutator_key == "elide_redundant_pointer_cast"
        for probe in pointer_probes
    )
    assert any("    use_gobj(gobj);\n" in probe.candidate_text for probe in pointer_probes)
    assert any("    alias = gobj;\n" in probe.candidate_text for probe in pointer_probes)
    assert {probe.payload["proof_source"] for probe in pointer_probes} == {
        "source-local-pointer-compatibility"
    }

    callback = next(
        probe for probe in probes if probe.family_id == "callback_cast_elision"
    )
    assert callback.mutator_key == "elide_callback_cast"
    assert "    register_cb(gobj, callback);\n" in callback.candidate_text
    assert callback.payload["callee"] == "register_cb"
    assert callback.payload["arg_index"] == 1
    assert callback.payload["proof_source"] == "source-local-callback-signature"

    vector = next(
        probe for probe in probes if probe.family_id == "vector_alias_type_shape"
    )
    assert vector.mutator_key == "rewrite_vector_alias_type"
    assert "    Vec3 pos;\n" in vector.candidate_text
    assert "void target(Vec3" not in vector.candidate_text
    assert vector.payload["from_type"] == "Point3d"
    assert vector.payload["to_type"] == "Vec3"
    assert vector.payload["proof_source"] == "source-local-identical-struct-alias"


def test_callback_cast_elision_accepts_source_local_function_pointer_typedef() -> None:
    source = (
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef void (*ItemCallback)(HSD_GObj* gobj);\n"
        "void register_cb(HSD_GObj* gobj, ItemCallback cb);\n"
        "void callback(HSD_GObj* gobj);\n"
        "void target(void) {\n"
        "    HSD_GObj* gobj;\n"
        "    register_cb(gobj, (ItemCallback) callback);\n"
        "}\n"
    )

    probes = _type_cast_compatibility_probes(source, max_per_family=2)

    callback = next(
        probe for probe in probes if probe.family_id == "callback_cast_elision"
    )
    assert callback.mutator_key == "elide_callback_cast"
    assert "    register_cb(gobj, callback);\n" in callback.candidate_text
    assert callback.payload["cast_type"] == "ItemCallback"
    assert callback.payload["proof_source"] == "source-local-callback-signature"


@pytest.mark.parametrize(
    ("case", "source", "rejected"),
    (
        (
            "missing prototype",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "incompatible pointer expression type",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "typedef struct Item Item;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    Item* item;\n"
                "    HSD_GObj* alias;\n"
                "    use_gobj((HSD_GObj*) item);\n"
                "    alias = (HSD_GObj*) item;\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "inner pointer declaration out of scope at cast site",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "typedef struct Item Item;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(Item* ptr, int cond) {\n"
                "    if (cond) {\n"
                "        HSD_GObj* ptr;\n"
                "        consume(ptr);\n"
                "    }\n"
                "    use_gobj((HSD_GObj*) ptr);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "inner pointer declaration not visible in sibling else",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "typedef struct Item Item;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(Item* ptr, int cond) {\n"
                "    if (cond) {\n"
                "        HSD_GObj* ptr;\n"
                "        consume(ptr);\n"
                "    } else {\n"
                "        use_gobj((HSD_GObj*) ptr);\n"
                "    }\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "volatile pointer expression type",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    volatile HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "volatile formal preserves argument index",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(volatile int flag, HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj, gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "callee shadowed by local function pointer",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    void (*use_gobj)(HSD_GObj*);\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "callee has active top-level function-like macro",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#define use_gobj(arg) use_gobj_impl(arg)\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "callee proof embedded in active macro replacement text",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#define DECL_USE void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "callee proof embedded in continued active macro replacement text",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#define DECL_USE " "\\\\" "\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "pointer type token has active top-level macro",
            (
                "#define HSD_GObj OtherGObj\n"
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    HSD_GObj* alias;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "    alias = (HSD_GObj*) gobj;\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "pointer type token shadowed by target-body typedef",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "typedef struct Other Other;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    typedef Other HSD_GObj;\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "pointer struct tag shadowed by target-body struct",
            (
                "struct HSD_GObj { int a; };\n"
                "void use_gobj(struct HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    struct HSD_GObj { int b; };\n"
                "    struct HSD_GObj* gobj;\n"
                "    struct HSD_GObj* alias;\n"
                "    use_gobj((struct HSD_GObj*) gobj);\n"
                "    alias = (struct HSD_GObj*) gobj;\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "expression shadowed by inner non-pointer local",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    if (ready) {\n"
                "        int gobj;\n"
                "        use_gobj((HSD_GObj*) gobj);\n"
                "    }\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "expression shadowed by initialized non-pointer local",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "int make_int(void);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    if (ready) {\n"
                "        int gobj = make_int();\n"
                "        use_gobj((HSD_GObj*) gobj);\n"
                "    }\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "expression shadowed by multi-declarator non-pointer local",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    if (ready) {\n"
                "        int other, gobj;\n"
                "        use_gobj((HSD_GObj*) gobj);\n"
                "    }\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "assignment expression shadowed by multi-declarator pointer local",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "typedef struct Item Item;\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    HSD_GObj* alias;\n"
                "    if (ready) {\n"
                "        Item* gobj, *other;\n"
                "        alias = (HSD_GObj*) gobj;\n"
                "    }\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "assignment destination has active top-level macro",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#define alias other_alias\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    HSD_GObj* alias;\n"
                "    alias = (HSD_GObj*) gobj;\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "callee proof hidden in disabled preprocessor region",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#if 0\n"
                "void use_gobj(HSD_GObj* gobj) {}\n"
                "#endif\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "expression has active top-level macro",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#define gobj other_gobj\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "varargs formal",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(const char* fmt, ...);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    use_gobj(\"%p\", (HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "preprocessor guarded cast",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "#if DEBUG\n"
                "    use_gobj((HSD_GObj*) gobj);\n"
                "#endif\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "comments and strings",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void use_gobj(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    OSReport(\"use_gobj((HSD_GObj*) gobj)\");\n"
                "    // use_gobj((HSD_GObj*) gobj);\n"
                "}\n"
            ),
            {"redundant_pointer_cast_elision"},
        ),
        (
            "callback address taken",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    register_cb(gobj, (void (*)(HSD_GObj*)) &callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback expression shadowed by local function pointer",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    void (*callback)(int);\n"
                "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback expression shadowed by multiline local function pointer",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    void (*callback)\n"
                "        (int);\n"
                "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback expression has active top-level macro",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#define callback callback_impl\n"
                "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback expression address taken elsewhere in target body",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    void* saved = &callback;\n"
                "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback formal proof embedded in active macro replacement text",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "#define DECL_CB void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback type token has active top-level macro",
            (
                "#define HSD_GObj OtherGObj\n"
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    HSD_GObj* gobj;\n"
                "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback typedef token shadowed by target-body typedef",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "typedef void (*ItemCallback)(HSD_GObj* gobj);\n"
                "typedef void (*OtherCallback)(int value);\n"
                "void register_cb(HSD_GObj* gobj, ItemCallback cb);\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    typedef OtherCallback ItemCallback;\n"
                "    HSD_GObj* gobj;\n"
                "    register_cb(gobj, (ItemCallback) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback struct tag shadowed by target-body struct via typedef cast",
            (
                "struct HSD_GObj { int a; };\n"
                "typedef void (*ItemCallback)(struct HSD_GObj* gobj);\n"
                "void register_cb(struct HSD_GObj* gobj, ItemCallback cb);\n"
                "void callback(struct HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    struct HSD_GObj { int b; };\n"
                "    struct HSD_GObj* gobj;\n"
                "    register_cb(gobj, (ItemCallback) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback struct tag shadowed by target-body struct via direct cast",
            (
                "struct HSD_GObj { int a; };\n"
                "void register_cb(struct HSD_GObj* gobj, void (*cb)(struct HSD_GObj*));\n"
                "void callback(struct HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    struct HSD_GObj { int b; };\n"
                "    struct HSD_GObj* gobj;\n"
                "    register_cb(gobj, (void (*)(struct HSD_GObj*)) callback);\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "callback table initializer",
            (
                "typedef struct HSD_GObj HSD_GObj;\n"
                "void callback(HSD_GObj* gobj);\n"
                "void target(void) {\n"
                "    static void (*table[])(HSD_GObj*) = {\n"
                "        (void (*)(HSD_GObj*)) callback,\n"
                "    };\n"
                "}\n"
            ),
            {"callback_cast_elision"},
        ),
        (
            "non-identical vector layout",
            (
                "typedef float f32;\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 w; } Point3d;\n"
                "void target(void) {\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector function parameter",
            (
                "typedef float f32;\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(Point3d* pos) {\n"
                "    consume_vec(pos);\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector replacement alias shadowed in target body",
            (
                "typedef float f32;\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    typedef int Vec3;\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector source alias shadowed in target body",
            (
                "typedef float f32;\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    typedef int Point3d;\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector alias proof embedded in active macro replacement text",
            (
                "typedef float f32;\n"
                "#define DECL_VEC typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector field type token has active top-level macro",
            (
                "#define f32 float\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector replacement alias shadowed by local variable",
            (
                "typedef float f32;\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    int Vec3;\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector replacement alias shadowed by multiline local typedef",
            (
                "typedef float f32;\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    typedef struct {\n"
                "        int x;\n"
                "    } Vec3;\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector field inside local struct definition",
            (
                "typedef float f32;\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    struct Local {\n"
                "        Point3d pos;\n"
                "    } local;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
        (
            "vector replacement alias has active top-level macro",
            (
                "typedef float f32;\n"
                "#define Vec3 OtherVec3\n"
                "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
                "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
                "void target(void) {\n"
                "    Point3d pos;\n"
                "}\n"
            ),
            {"vector_alias_type_shape"},
        ),
    ),
)
def test_type_cast_compatibility_mutators_reject_unsafe_shapes(
    case: str,
    source: str,
    rejected: set[str],
) -> None:
    probes = _type_cast_compatibility_probes(source, max_per_family=3)

    assert rejected.isdisjoint({probe.family_id for probe in probes}), case
