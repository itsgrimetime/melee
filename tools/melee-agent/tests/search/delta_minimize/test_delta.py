import pytest

from src.search.delta_minimize import DeltaMinimizeError
from src.search.delta_minimize.delta import (
    DeltaAtom,
    DeltaManifest,
    DeltaPatch,
    enumerate_legal_masks,
    extract_delta_manifest,
    extract_primitive_manifest,
    materialize_mask,
)


def manifest_with_independent_atoms(count):
    atoms = tuple(
        DeltaAtom(
            atom_id=f"a{i}",
            kind="expression",
            patches=(),
            summary=f"atom {i}",
        )
        for i in range(count)
    )
    return DeltaManifest(
        schema_version="delta-manifest.v1",
        function="f",
        left_hash="left",
        right_hash="right",
        atoms=atoms,
    )


def test_endpoints_are_byte_exact_and_formatting_is_one_atom():
    left = "int f(int x) {\n    return x + 1;\n}\n"
    right = "int f(int x){\n  return x + 2;\n}\n"

    manifest = extract_delta_manifest(left, right, function="f")
    masks = enumerate_legal_masks(manifest, max_candidates=64)

    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, (1 << len(manifest.atoms)) - 1) == right
    assert sum(atom.kind == "presentation-only" for atom in manifest.atoms) <= 1
    assert 0 in masks and (1 << len(manifest.atoms)) - 1 in masks


def test_primitive_expression_atoms_materialize_each_observed_hybrid_once():
    left = "int f(int x) { return (x + 1) * 3; }\n"
    right = "int f(int x) { return (x + 2) * 4; }\n"

    manifest = extract_primitive_manifest(left, right, function="f")

    assert len(manifest.atoms) == 2
    assert materialize_mask(left, manifest, 0b01) in {
        "int f(int x) { return (x + 2) * 3; }\n",
        "int f(int x) { return (x + 1) * 4; }\n",
    }
    assert len(set(enumerate_legal_masks(manifest, max_candidates=4))) == 4


def test_local_temporary_wrapper_is_one_composite_atom():
    left = """\
void use(void*, float);
void sink(int);
void f(void* header, float spacing, int i) {
    use(header, spacing * i);
    sink(i + 1);
}
"""
    right = """\
void use(void*, float);
void sink(int);
void f(void* header, float spacing, int i) {
    {
        float ll_probe_arg_0 = spacing * i;
        use(header, ll_probe_arg_0);
    }
    sink(i + 2);
}
"""

    manifest = extract_delta_manifest(left, right, function="f")
    semantic_atoms = tuple(atom for atom in manifest.atoms if atom.kind != "presentation-only")

    assert len(semantic_atoms) == 2
    wrapper = next(
        atom for atom in semantic_atoms if any("ll_probe_arg_0" in patch.right_text for patch in atom.patches)
    )
    wrapper_mask = 1 << manifest.atoms.index(wrapper)
    hybrid = materialize_mask(left, manifest, wrapper_mask)
    assert "use(header, ll_probe_arg_0);" in hybrid
    assert "sink(i + 1);" in hybrid


def test_changed_shadowed_local_name_fails_closed():
    left = """\
int f(int value) {
    {
        int temporary = 1;
        value += temporary;
    }
    return value;
}
"""
    right = """\
int f(int value) {
    int temporary = 2;
    {
        int temporary = 1;
        value += temporary;
    }
    return value + temporary;
}
"""

    with pytest.raises(DeltaMinimizeError, match="^unsupported-semantic-binding$") as exc:
        extract_delta_manifest(left, right, function="f")

    assert any(
        blocker["symbol"] == "temporary" and blocker["reason"] == "ambiguous-local-binding"
        for blocker in exc.value.details["blockers"]
    )


def test_structural_wrapper_delimiters_are_one_composite_atom():
    left = """\
void use(int);
void f(int value) {
    int i;
    for (i = 0; i < 2; i++) {
        if (value > i) {
            use(value);
        }
    }
}
"""
    right = """\
void use(int);
void f(int value) {
    {
        int i;
        for (i = 0; i < 2; i++) {
            if (value > i) {
                use(value + 1);
            }
        }
    }
}
"""

    manifest = extract_delta_manifest(left, right, function="f")
    semantic_atoms = tuple(atom for atom in manifest.atoms if atom.kind != "presentation-only")

    assert len(semantic_atoms) == 2
    wrapper = next(
        atom
        for atom in semantic_atoms
        if any("{" in patch.right_text or "}" in patch.right_text for patch in atom.patches)
    )
    wrapper_text = "".join(patch.right_text for patch in wrapper.patches)
    assert "{" in wrapper_text and "}" in wrapper_text
    hybrid = materialize_mask(left, manifest, 1 << manifest.atoms.index(wrapper))
    assert "use(value);" in hybrid
    assert "{\n        int i;" in hybrid
    assert hybrid.rstrip().endswith("    }\n}")
    assert hybrid.count("{") == hybrid.count("}")


def test_budget_fails_before_returning_partial_masks():
    manifest = manifest_with_independent_atoms(7)

    with pytest.raises(DeltaMinimizeError, match="candidate-budget-exceeded") as exc:
        enumerate_legal_masks(manifest, max_candidates=64)

    assert exc.value.details["required"] == 128


def test_atom_ceiling_is_checked_before_enumeration():
    manifest = manifest_with_independent_atoms(21)

    with pytest.raises(DeltaMinimizeError, match="atom-space-too-large") as exc:
        enumerate_legal_masks(manifest, max_candidates=1 << 21)

    assert exc.value.details == {"atom_count": 21}


def test_dependencies_are_counted_exactly_in_deterministic_mask_order():
    base = manifest_with_independent_atoms(2)
    dependent = DeltaAtom(
        atom_id="a1",
        kind="expression",
        patches=(),
        requires=("a0",),
    )
    manifest = DeltaManifest(
        schema_version=base.schema_version,
        function=base.function,
        left_hash=base.left_hash,
        right_hash=base.right_hash,
        atoms=(base.atoms[0], dependent),
    )

    assert enumerate_legal_masks(manifest, max_candidates=3) == (0b00, 0b01, 0b11)


def test_missing_dependency_id_fails_closed():
    atom = DeltaAtom(
        atom_id="a0",
        kind="expression",
        patches=(),
        requires=("missing",),
    )
    manifest = DeltaManifest("delta-manifest.v1", "f", "left", "right", (atom,))

    with pytest.raises(DeltaMinimizeError, match="invalid-delta-dependency"):
        enumerate_legal_masks(manifest, max_candidates=2)


def test_invalid_mask_and_changed_anchor_fail_closed():
    patch = DeltaPatch(0, 1, "x", 0, 1, "y", "expression", "f:identifier")
    atom = DeltaAtom("a0", "expression", (patch,))
    manifest = DeltaManifest("delta-manifest.v1", "f", "left", "right", (atom,))

    with pytest.raises(DeltaMinimizeError, match="invalid-delta-mask"):
        materialize_mask("x", manifest, 0b10)
    with pytest.raises(DeltaMinimizeError, match="invalid-materialized-anchor"):
        materialize_mask("z", manifest, 0b01)


def test_primitive_top_level_comment_is_classified_as_unowned_presentation():
    manifest = extract_primitive_manifest("/* left */\n", "/* right */\n", function="f")

    assert len(manifest.atoms) == 1
    assert manifest.atoms[0].kind == "presentation-only"
    assert manifest.atoms[0].affected_functions == ()


def test_sound_overlapping_replacements_merge_into_one_atom(monkeypatch):
    left = "int f(void) { return 100; }\n"
    right = "int f(void) { return 210; }\n"

    class OverlappingMatcher:
        def __init__(self, *args, **kwargs):
            pass

        def get_opcodes(self):
            return (
                ("equal", 0, 21, 0, 21),
                ("replace", 21, 23, 21, 23),
                ("replace", 22, 24, 22, 24),
                ("equal", 24, len(left), 24, len(right)),
            )

    monkeypatch.setattr("src.search.delta_minimize.delta.SequenceMatcher", OverlappingMatcher)
    manifest = extract_primitive_manifest(left, right, function="f")

    assert len(manifest.atoms) == 1
    assert materialize_mask(left, manifest, 1) == right


def test_unmergeable_overlap_fails_extraction(monkeypatch):
    left = "int f(void) { return 100; }\n"
    right = "int f(void) { return 210; }\n"

    class OverlappingMatcher:
        def __init__(self, *args, **kwargs):
            pass

        def get_opcodes(self):
            return (
                ("equal", 0, 21, 0, 21),
                ("replace", 21, 23, 21, 23),
                ("replace", 22, 24, 23, 25),
                ("equal", 24, len(left), 25, len(right)),
            )

    monkeypatch.setattr("src.search.delta_minimize.delta.SequenceMatcher", OverlappingMatcher)
    with pytest.raises(DeltaMinimizeError, match="unmergeable-overlapping-delta"):
        extract_primitive_manifest(left, right, function="f")


def test_target_scope_uses_real_lexical_owners_and_projects_unrelated_edit():
    left = """\
int unrelated(void) { s32 value = 1; return value; }
static int leaf(int x) { return x + 1; }
static int helper(int x) { return leaf(x) + 2; }
int target(int x) { return helper(x) + 3; }
"""
    right = """\
int unrelated(void) { int value = 1; return value; }
static int leaf(int x) { return x + 10; }
static int helper(int x) { return leaf(x) + 20; }
int target(int x) { return helper(x) + 30; }
"""

    manifest = extract_delta_manifest(left, right, function="target")
    full_mask = (1 << len(manifest.atoms)) - 1
    scoped_right = materialize_mask(left, manifest, full_mask)

    assert manifest.function == "target"
    assert len(manifest.atoms) == 3
    assert {name for atom in manifest.atoms for name in atom.affected_functions} == {
        "leaf",
        "helper",
        "target",
    }
    assert all(
        patch.anchor_symbol.startswith(tuple(atom.affected_functions))
        for atom in manifest.atoms
        for patch in atom.patches
    )
    assert enumerate_legal_masks(manifest, max_candidates=8) == tuple(range(8))
    assert materialize_mask(left, manifest, 0) == left
    assert "s32 value = 1" in scoped_right
    assert "return x + 10" in scoped_right
    assert "return leaf(x) + 20" in scoped_right
    assert "return helper(x) + 30" in scoped_right
    assert manifest.right_hash != manifest.scoped_right_hash
    assert len(manifest.excluded_atom_ids) == 1


def test_target_scope_unions_one_sided_call_reachability_and_walks_callees_only():
    left = """\
static int leaf(int x) { return x + 1; }
static int helper(int x) { return leaf(x) + 2; }
int target(int x) { return x + 3; }
int inbound(int x) { return target(x) + 4; }
"""
    right = """\
static int leaf(int x) { return x + 10; }
static int helper(int x) { return leaf(x) + 20; }
int target(int x) { return helper(x) + 30; }
int inbound(int x) { return target(x) + 40; }
"""

    manifest = extract_delta_manifest(left, right, function="target")
    scoped_right = materialize_mask(left, manifest, (1 << len(manifest.atoms)) - 1)

    assert {name for atom in manifest.atoms for name in atom.affected_functions} == {
        "leaf",
        "helper",
        "target",
    }
    assert "return target(x) + 4" in scoped_right
    assert "return helper(x) + 30" in scoped_right


@pytest.mark.parametrize(
    ("left", "right", "side", "reason"),
    [
        ("int other(void) { return 0; }\n", "int target(void) { return 0; }\n", "left", "missing-target-definition"),
        ("int target(void) { return 0; }\n", "int other(void) { return 0; }\n", "right", "missing-target-definition"),
        (
            "int target(void) { return 0; }\nint target(void) { return 1; }\n",
            "int target(void) { return 0; }\n",
            "left",
            "duplicate-target-definition",
        ),
        (
            "int target(void) { return 0; }\n",
            "int target(void) { return 0; }\nint target(void) { return 1; }\n",
            "right",
            "duplicate-target-definition",
        ),
    ],
)
def test_target_scope_requires_one_definition_per_parent(left, right, side, reason):
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-delta-scope$") as exc:
        extract_delta_manifest(left, right, function="target")

    assert exc.value.details == {
        "target": "target",
        "side": side,
        "definition_count": 0 if reason.startswith("missing") else 2,
        "reason": reason,
    }


def test_unreachable_one_sided_function_is_excluded_without_global_pairing():
    left = "int target(void) { return 1; }\n"
    right = "int target(void) { return 1; }\nint unrelated(void) { return 2; }\n"

    manifest = extract_delta_manifest(left, right, function="target")

    assert manifest.atoms == ()
    assert enumerate_legal_masks(manifest, max_candidates=1) == (0,)
    assert materialize_mask(left, manifest, 0) == left
    assert manifest.scoped_right_hash == manifest.left_hash
    assert manifest.right_hash != manifest.left_hash
    assert manifest.excluded_atom_ids


def test_unowned_global_semantic_delta_fails_closed():
    left = "int global = 1;\nint target(void) { return 0; }\n"
    right = "int global = 2;\nint target(void) { return 0; }\n"

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-delta-scope$") as exc:
        extract_delta_manifest(left, right, function="target")

    assert exc.value.details["target"] == "target"
    assert exc.value.details["side"] == "both"
    assert exc.value.details["reason"] == "unowned-semantic-delta"


def test_unowned_top_level_presentation_is_excluded_and_left_text_preserved():
    left = "/* left */\n\nint target(void) { return 0; }\n"
    right = "/* right */\n\n\nint target(void) { return 0; }\n"

    manifest = extract_delta_manifest(left, right, function="target")

    assert manifest.atoms == ()
    assert materialize_mask(left, manifest, 0) == left
    assert manifest.excluded_atom_ids


@pytest.mark.parametrize("direction", ("insert", "delete"))
def test_one_sided_reachable_helper_is_searchable(direction):
    without = "int target(int x) { return x; }\n"
    with_helper = "static int helper(int x) { return x + 1; }\nint target(int x) { return helper(x); }\n"
    left, right = (without, with_helper) if direction == "insert" else (with_helper, without)

    manifest = extract_delta_manifest(left, right, function="target")
    masks = enumerate_legal_masks(manifest, max_candidates=2)
    candidates = tuple(materialize_mask(left, manifest, mask) for mask in masks)

    assert "helper" in {name for atom in manifest.atoms for name in atom.affected_functions}
    assert masks == (0, 1)
    assert candidates == (left, right)
    assert manifest.excluded_atom_ids == ()


@pytest.mark.parametrize("direction", ("insert", "delete"))
def test_one_sided_reachable_helper_couples_separated_prototype(direction):
    without = "int marker;\nint target(int x) { return x; }\n"
    with_helper = """\
static int helper(int x);
int marker;
static int helper(int x) { return x + 1; }
int target(int x) { return helper(x); }
"""
    left, right = (without, with_helper) if direction == "insert" else (with_helper, without)

    manifest = extract_delta_manifest(left, right, function="target")
    masks = enumerate_legal_masks(manifest, max_candidates=2)

    assert masks == (0, 1)
    assert tuple(materialize_mask(left, manifest, mask) for mask in masks) == (left, right)
    assert manifest.atoms[0].affected_functions == ("helper", "target")


def test_unreachable_one_sided_function_deletion_is_excluded():
    left = "int target(void) { return 1; }\nint unrelated(void) { return 2; }\n"
    right = "int target(void) { return 1; }\n"

    manifest = extract_delta_manifest(left, right, function="target")

    assert manifest.atoms == ()
    assert materialize_mask(left, manifest, 0) == left
    assert manifest.excluded_atom_ids


@pytest.mark.parametrize(
    ("left", "right", "needle"),
    [
        (
            "int target(int x) { return x; }\n",
            "int target(int x) { int y = 1; return x + y; }\n",
            "int y = 1",
        ),
        (
            "int target(int x) { return x; }\n",
            "int target(int x) { return x; /* end */ }\n",
            "/* end */",
        ),
    ],
)
def test_insertions_at_reachable_function_boundaries_are_owned(left, right, needle):
    manifest = extract_delta_manifest(left, right, function="target")

    assert all(atom.affected_functions == ("target",) for atom in manifest.atoms)
    assert needle in materialize_mask(left, manifest, (1 << len(manifest.atoms)) - 1)


def test_reached_duplicate_helper_definition_fails_closed():
    source = """\
int helper(void) { return 1; }
int helper(void) { return 2; }
int target(void) { return helper(); }
"""

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-delta-scope$") as exc:
        extract_delta_manifest(source, source, function="target")

    assert exc.value.details["reason"] == "duplicate-reachable-definition"
    assert exc.value.details["symbol"] == "helper"


def test_presentation_changes_follow_lexical_scope_on_insert_and_replace():
    left = "/* top */\nint unrelated(void) { return 1; }\nint target(void) { return 2; }\n"
    right = "/* changed top */\nint unrelated(void) {  return 1; }\nint target(void) {  return 2; /* kept */ }\n"

    manifest = extract_delta_manifest(left, right, function="target")
    scoped_right = materialize_mask(left, manifest, (1 << len(manifest.atoms)) - 1)

    assert "/* top */" in scoped_right
    assert "int unrelated(void) { return 1; }" in scoped_right
    assert "/* kept */" in scoped_right
    assert all(atom.affected_functions == ("target",) for atom in manifest.atoms)


def test_parse_error_overlap_fails_with_scope_diagnostics():
    left = "int target(void) { int x = ; return 0; }\n"
    right = "int target(void) { int x = @; return 0; }\n"

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-delta-scope$") as exc:
        extract_delta_manifest(left, right, function="target")

    assert exc.value.details["target"] == "target"
    assert exc.value.details["side"] == "right"
    assert exc.value.details["candidate_owners"] == ["target"]
    assert exc.value.details["reason"] == "parse-error-overlap"


def test_primitive_spanning_target_and_unrelated_function_fails_closed(monkeypatch):
    left = "int target(void) { return 1; }\nint unrelated(void) { return 2; }\n"
    right = "int target(void) { return 3; }\nint unrelated(void) { return 4; }\n"
    start = left.index("1")
    end = left.index("2") + 1
    right_start = right.index("3")
    right_end = right.index("4") + 1

    class MixedScopeMatcher:
        def __init__(self, *args, **kwargs):
            pass

        def get_opcodes(self):
            return (
                ("equal", 0, start, 0, right_start),
                ("replace", start, end, right_start, right_end),
                ("equal", end, len(left), right_end, len(right)),
            )

    monkeypatch.setattr("src.search.delta_minimize.delta.SequenceMatcher", MixedScopeMatcher)
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-delta-scope$") as exc:
        extract_delta_manifest(left, right, function="target")

    assert exc.value.details["side"] == "left"
    assert exc.value.details["candidate_owners"] == ["target", "unrelated"]
    assert exc.value.details["reason"] == "non-unique-lexical-owner"


@pytest.mark.parametrize("direction", ("insert", "delete"))
def test_whole_top_level_comment_with_newline_is_excluded_as_presentation(direction):
    without = "int target(void) { return 0; }\n"
    with_comment = "/* retained note */\nint target(void) { return 0; }\n"
    left, right = (without, with_comment) if direction == "insert" else (with_comment, without)

    manifest = extract_delta_manifest(left, right, function="target")

    assert manifest.atoms == ()
    assert manifest.excluded_atom_ids
    assert all(atom.reason == "unowned-presentation" for atom in manifest.excluded_atoms)
    assert materialize_mask(left, manifest, 0) == left


def test_cross_boundary_target_to_global_primitive_fails_closed(monkeypatch):
    left = "int target(void) { return 1; }\nint global = 2;\n"
    right = "int target(void) { return 3; }\nint global = 4;\n"
    start = left.index("1")
    end = left.index("2") + 1
    right_start = right.index("3")
    right_end = right.index("4") + 1

    class CrossBoundaryMatcher:
        def __init__(self, *args, **kwargs):
            pass

        def get_opcodes(self):
            return (
                ("equal", 0, start, 0, right_start),
                ("replace", start, end, right_start, right_end),
                ("equal", end, len(left), right_end, len(right)),
            )

    monkeypatch.setattr("src.search.delta_minimize.delta.SequenceMatcher", CrossBoundaryMatcher)
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-delta-scope$") as exc:
        extract_delta_manifest(left, right, function="target")

    assert exc.value.details["side"] == "left"
    assert exc.value.details["candidate_owners"] == ["target"]
    assert exc.value.details["reason"] == "partial-lexical-owner-overlap"
