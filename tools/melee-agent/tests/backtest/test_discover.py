# tools/melee-agent/tests/backtest/test_discover.py
from src.backtest.discover import classify_shape, parse_match_function, discover_match_commits

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STUB_REMOVAL_DIFF = """\
diff --git a/src/melee/mn/mnDiagram.c b/src/melee/mn/mnDiagram.c
--- a/src/melee/mn/mnDiagram.c
+++ b/src/melee/mn/mnDiagram.c
@@ -1,3 +1,10 @@
-/// #mnDiagram_Draw
+void mnDiagram_Draw(MnDiagram *diag) {
+    OSReport("draw");
+}
"""

DEF_ADD_DIFF = """\
diff --git a/src/melee/gr/grfox.c b/src/melee/gr/grfox.c
--- a/src/melee/gr/grfox.c
+++ b/src/melee/gr/grfox.c
@@ -1,0 +1,5 @@
+static void grFox_Init(GrFox *self) {
+    self->x = 0;
+    self->y = 0;
+}
"""

TWEAK_DIFF = """\
diff --git a/src/melee/gr/grfox.c b/src/melee/gr/grfox.c
--- a/src/melee/gr/grfox.c
+++ b/src/melee/gr/grfox.c
@@ -2,7 +2,7 @@
-    self->x = 1;
+    self->x = 0;
"""


# ---------------------------------------------------------------------------
# classify_shape
# ---------------------------------------------------------------------------

def test_classify_shape_stub_to_def():
    assert classify_shape(STUB_REMOVAL_DIFF) == "stub_to_def"


def test_classify_shape_new_fn():
    assert classify_shape(DEF_ADD_DIFF) == "new_fn"


def test_classify_shape_tweak():
    assert classify_shape(TWEAK_DIFF) == "tweak"


# ---------------------------------------------------------------------------
# parse_match_function
# ---------------------------------------------------------------------------

def test_parse_match_function_stub_symbol():
    assert parse_match_function(STUB_REMOVAL_DIFF) == "mnDiagram_Draw"


def test_parse_match_function_def_name():
    # DEF_ADD_DIFF has no stub marker; should fall back to the added definition
    assert parse_match_function(DEF_ADD_DIFF) == "grFox_Init"


def test_parse_match_function_none():
    # A tweak with no stub marker and no function definition added
    assert parse_match_function(TWEAK_DIFF) is None


def test_parse_match_function_no_keyword():
    # Make sure keywords are not returned as function names
    diff = """\
--- a/src/melee/foo.c
+++ b/src/melee/foo.c
+if (x) {
"""
    assert parse_match_function(diff) is None


# ---------------------------------------------------------------------------
# discover_match_commits — fake git_runner
# ---------------------------------------------------------------------------

# Canned numstat log with two commits:
#   commit A: one .c file, small, real function -> should be included
#   commit B: one .c file small, but matches sdata2_order helper -> should be skipped
NUMSTAT_LOG = """\
__C__|aabbcc1111|deadbeef00|match: grFox_Init

1\t1\tsrc/melee/gr/grfox.c
__C__|aabbcc2222|deadbeef01|match: order_sdata2_helper

3\t2\tsrc/melee/gr/grorder.c
"""

SHOW_GRFOX = DEF_ADD_DIFF  # 1 added line, 0 removed -> new_fn, function=grFox_Init

SHOW_GRORDER = """\
diff --git a/src/melee/gr/grorder.c b/src/melee/gr/grorder.c
--- a/src/melee/gr/grorder.c
+++ b/src/melee/gr/grorder.c
@@ -1,2 +1,3 @@
-static void order_sdata2_helper(void) {}
+static void order_sdata2_helper(void) {
+    doThing();
+}
"""


def make_discover_runner(numstat_out, show_map):
    """Dispatch on 'log' vs 'show' in args."""
    def run(args):
        if "log" in args:
            return numstat_out
        if "show" in args:
            # find the sha in args (it follows 'show')
            sha = args[args.index("show") + 1]
            return show_map[sha]
        raise AssertionError(f"unexpected git call: {args}")
    return run


def test_discover_match_commits_basic():
    runner = make_discover_runner(
        NUMSTAT_LOG,
        {"aabbcc1111": SHOW_GRFOX, "aabbcc2222": SHOW_GRORDER},
    )
    results = discover_match_commits(runner, limit=20, max_lines=60, scan=100)
    assert len(results) == 1
    r = results[0]
    assert r["function"] == "grFox_Init"
    assert r["c_sha"] == "aabbcc1111"
    assert r["cprev_sha"] == "deadbeef00"
    assert r["shape"] == "new_fn"
    assert r["file"] == "src/melee/gr/grfox.c"


def test_discover_match_commits_skips_sdata2_helper():
    """The second commit (order_sdata2_helper) must be skipped."""
    runner = make_discover_runner(
        NUMSTAT_LOG,
        {"aabbcc1111": SHOW_GRFOX, "aabbcc2222": SHOW_GRORDER},
    )
    results = discover_match_commits(runner, limit=20, max_lines=60, scan=100)
    fns = [r["function"] for r in results]
    assert "order_sdata2_helper" not in fns


def test_discover_match_commits_limit_respected():
    # Build a log with 5 identical small real commits
    entries = []
    show_map = {}
    for i in range(5):
        sha = f"sha{i:07d}"
        show_map[sha] = DEF_ADD_DIFF
        entries.append(f"__C__|{sha}|parent{i:07d}|match: grFox_Init\n\n1\t1\tsrc/melee/gr/grfox.c\n")
    numstat = "".join(entries)
    runner = make_discover_runner(numstat, show_map)
    results = discover_match_commits(runner, limit=3, max_lines=60, scan=100)
    assert len(results) == 3


def test_discover_match_commits_skips_over_limit_diff():
    # A commit whose added+removed > max_lines should be skipped
    big_numstat = "__C__|bigsha1|bigpar1|match: grFox_Init\n\n50\t20\tsrc/melee/gr/grfox.c\n"
    runner = make_discover_runner(big_numstat, {"bigsha1": DEF_ADD_DIFF})
    results = discover_match_commits(runner, limit=20, max_lines=60, scan=100)
    # 50+20=70 > 60 -> skipped
    assert results == []


def test_discover_match_commits_skips_multi_c_commit():
    multi_numstat = (
        "__C__|multisha|multipar|match: two files\n\n"
        "1\t1\tsrc/melee/gr/grfox.c\n"
        "1\t1\tsrc/melee/gr/grfox2.c\n"
    )
    runner = make_discover_runner(multi_numstat, {})
    results = discover_match_commits(runner, limit=20, max_lines=60, scan=100)
    assert results == []


def test_discover_match_commits_stub_to_def_shape():
    stub_numstat = "__C__|stubsha1|stubpar1|match: mnDiagram_Draw\n\n5\t2\tsrc/melee/mn/mnDiagram.c\n"
    runner = make_discover_runner(stub_numstat, {"stubsha1": STUB_REMOVAL_DIFF})
    results = discover_match_commits(runner, limit=20, max_lines=60, scan=100)
    assert len(results) == 1
    assert results[0]["shape"] == "stub_to_def"
    assert results[0]["function"] == "mnDiagram_Draw"
