import pytest

from src.search.delta_minimize import DeltaMinimizeError
from src.search.delta_minimize.delta import (
    DeltaAtom,
    DeltaManifest,
    DeltaPatch,
    enumerate_legal_masks,
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

    manifest = extract_primitive_manifest(left, right, function="f")
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


def test_unsupported_top_level_anchor_fails_closed():
    with pytest.raises(DeltaMinimizeError, match="unsupported-delta-anchor"):
        extract_primitive_manifest("/* left */\n", "/* right */\n", function="f")


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
