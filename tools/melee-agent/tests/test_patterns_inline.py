"""Tests for inline candidate pattern detection."""

from src.cli.patterns import find_inline_candidates


def candidate_types(path):
    return {candidate["type"] for candidate in find_inline_candidates(path)}


def test_inline_candidates_flag_direct_jobj_child_access(tmp_path):
    source = tmp_path / "file.c"
    source.write_text(
        """
void f(HSD_JObj* jobj) {
    HSD_JObj* a = jobj->child;
    HSD_JObj* b = jobj->child;
    HSD_JObj* c = jobj->child;
}
"""
    )

    assert "jobj-direct-child-access" in candidate_types(source)


def test_inline_candidates_flag_pad_stack_heavy_function(tmp_path):
    source = tmp_path / "file.c"
    source.write_text(
        """
void f(void) {
    PAD_STACK(16);
    PAD_STACK(24);
}
"""
    )

    assert "pad-stack-heavy" in candidate_types(source)


def test_inline_candidates_flag_axis_setter_clusters(tmp_path):
    source = tmp_path / "file.c"
    source.write_text(
        """
void f(HSD_JObj* jobj) {
    HSD_JObjSetTranslateX(jobj, 1.0f);
    HSD_JObjSetTranslateY(jobj, 2.0f);
    HSD_JObjSetTranslateZ(jobj, 3.0f);
}
"""
    )

    assert "axis-setter-cluster" in candidate_types(source)


def test_inline_candidates_flag_repeated_varargs_calls(tmp_path):
    source = tmp_path / "file.c"
    source.write_text(
        """
void f(void) {
    OSReport("a %d", 1);
    OSReport("b %d", 2);
    OSReport("c %d", 3);
}
"""
    )

    assert "varargs-helper-cluster" in candidate_types(source)


def test_inline_candidates_flag_local_helper_call_clusters(tmp_path):
    source = tmp_path / "file.c"
    source.write_text(
        """
static void helper(int arg)
{
}

void f(void) {
    helper(1);
    helper(2);
    helper(3);
}
"""
    )

    assert "local-helper-call-cluster" in candidate_types(source)
