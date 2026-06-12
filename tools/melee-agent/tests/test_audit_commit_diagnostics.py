"""Audit regression tests for src/commit/diagnostics.py.

BUG 5 [HIGH]: normalize_signature did not strip parameter names for pointer
params ('*'/'&' between type and name), so semantically-identical pointer decls
were reported as a FALSE 'header signature mismatch' by compare_signatures.
"""

from src.commit.diagnostics import compare_signatures, normalize_signature


class TestPointerParamNormalization:
    """BUG 5: pointer parameter names / '*' placement must normalize away."""

    def test_pointer_star_placement_matches(self):
        """'HSD_GObj* gobj' vs 'HSD_GObj *gobj' are identical -> match True."""
        result = compare_signatures(
            "void f(HSD_GObj* gobj)", "void f(HSD_GObj *gobj)"
        )
        assert result["match"] is True

    def test_pointer_name_diff_matches(self):
        """'HSD_GObj* gobj' vs 'HSD_GObj* g' differ only in param name -> match True."""
        result = compare_signatures(
            "void f(HSD_GObj* gobj)", "void f(HSD_GObj* g)"
        )
        assert result["match"] is True

    def test_pointer_normalizes_identically(self):
        """Both '*' placements normalize to the same canonical string."""
        a = normalize_signature("void f(HSD_GObj* gobj)")
        b = normalize_signature("void f(HSD_GObj *gobj)")
        c = normalize_signature("void f(HSD_GObj* g)")
        assert a == b == c

    # --- OVER-CORRECTION GUARDS -------------------------------------------

    def test_different_pointer_type_mismatches(self):
        """Different underlying type must still NOT match (no over-trigger)."""
        result = compare_signatures(
            "void f(HSD_GObj* g)", "void f(Item* g)"
        )
        assert result["match"] is False

    def test_different_arity_mismatches(self):
        """Different parameter count must still NOT match."""
        result = compare_signatures(
            "void f(int x)", "void f(int x, int y)"
        )
        assert result["match"] is False

    def test_nonpointer_baseline_matches(self):
        """Non-pointer param-name-only difference still matches (unchanged)."""
        result = compare_signatures("void f(int x)", "void f(int y)")
        assert result["match"] is True
