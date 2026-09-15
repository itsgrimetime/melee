# tools/melee-agent/tests/backtest/test_build_corpus.py
from src.backtest.build_corpus import build_corpus, build_corpus_from_commits

REPORT = {"units": [{"name": "main/melee/gr/gricemt",
                     "functions": [{"name": "grIceMt_801F9ACC", "fuzzy_match_percent": 100.0}]}]}
DIFF = ("diff --git a/src/melee/gr/gricemt.c b/src/melee/gr/gricemt.c\n"
        "--- a/src/melee/gr/gricemt.c\n+++ b/src/melee/gr/gricemt.c\n"
        "@@ -1,2 +1,2 @@\n-    int x = f();\n+    u8 x = f();\n")

def make_git(c_sha):
    def run(args):
        k = " ".join(args)
        if k.startswith("log --pretty=%H -S"):
            return c_sha + "\n"
        if k.startswith("rev-parse"):
            return "13ccea114000\n"
        if k.startswith("log -1 --pretty=%an"):
            return "Some Contributor\n"
        if k.startswith("show"):
            return DIFF
        raise AssertionError(k)
    return run

def test_emits_case_when_flip_verifies():
    # ndl==0 at C, ndl>0 at C~1 -> verified
    def score_flip(fn, sha):
        return (100.0, 0) if sha.startswith("3ce0722cd") else (99.98, 4)
    cases = build_corpus(functions=["grIceMt_801F9ACC"], report=REPORT,
                         git_runner=make_git("3ce0722cd000"),
                         patterns=[], score_flip=score_flip)
    assert len(cases) == 1
    c = cases[0]
    assert c.lever_class == "retype" and c.provenance == "held_out"
    assert c.author == "other" and c.baseline_ndl == 4 and c.target_ndl_is_zero

def test_drops_case_when_flip_does_not_verify():
    # ndl>0 at C as well -> the in-function hunk is NOT the lever (confound) -> dropped
    def score_flip(fn, sha):
        return (99.0, 5)
    cases = build_corpus(functions=["grIceMt_801F9ACC"], report=REPORT,
                         git_runner=make_git("3ce0722cd000"),
                         patterns=[], score_flip=score_flip)
    assert cases == []


# ---------------------------------------------------------------------------
# build_corpus_from_commits tests
# ---------------------------------------------------------------------------

TRIPLES = [{"function": "grIceMt_801F9ACC", "c_sha": "3ce0722cd000",
             "cprev_sha": "13ccea114000", "file": "src/melee/gr/gricemt.c",
             "added": 1, "removed": 1, "shape": "tweak"}]


def make_git_for_commits(c_sha):
    def run(args):
        k = " ".join(args)
        if k.startswith("log -1 --pretty=%an"):
            return "Some Contributor\n"
        if k.startswith("show"):
            return DIFF
        raise AssertionError(k)
    return run


def test_build_corpus_from_commits_emits_valid_flip():
    """score_flip returns ndl==0 at C and ndl>0 at C~1 → one Case emitted."""
    def score_flip(fn, sha):
        return (100.0, 0) if sha == "3ce0722cd000" else (99.0, 4)

    cases = build_corpus_from_commits(
        triples=TRIPLES,
        git_runner=make_git_for_commits("3ce0722cd000"),
        patterns=[],
        score_flip=score_flip,
    )
    assert len(cases) == 1
    c = cases[0]
    assert c.function == "grIceMt_801F9ACC"
    assert c.unit == "main/melee/gr/gricemt"
    assert c.file == "src/melee/gr/gricemt.c"
    assert c.lever_class == "retype"
    assert c.provenance == "held_out"
    assert c.target_ndl_is_zero
    assert c.baseline_ndl == 4
    assert c.author == "other"


def test_build_corpus_from_commits_drops_when_c_ndl_nonzero():
    """score_flip returns ndl>0 at C → structural confound gate drops the case."""
    def score_flip(fn, sha):
        return (99.0, 5)

    cases = build_corpus_from_commits(
        triples=TRIPLES,
        git_runner=make_git_for_commits("3ce0722cd000"),
        patterns=[],
        score_flip=score_flip,
    )
    assert cases == []


def test_build_corpus_from_commits_skips_unscorable_candidate():
    """A candidate whose score_flip raises (fn absent from report.json — a parsed helper
    symbol, or a stub_to_def at C~1) is SKIPPED, not allowed to abort the whole batch."""
    from src.backtest.build_corpus import build_corpus_from_commits

    def gr(args):
        k = " ".join(args)
        if k.startswith("show"):
            return "@@\n-    int x = f();\n+    u8 x = f();\n"
        if k.startswith("log -1"):
            return "Some Contributor\n"
        return ""

    triples = [
        {"function": "good_fn", "c_sha": "a" * 40, "cprev_sha": "b" * 40, "file": "src/melee/gr/g.c"},
        {"function": "bad_fn", "c_sha": "c" * 40, "cprev_sha": "d" * 40, "file": "src/melee/gr/h.c"},
    ]

    def score_flip(fn, sha):
        if fn == "bad_fn":
            raise RuntimeError("could not find function bad_fn in report.json")
        return (100.0, 0) if sha.startswith("a") else (99.0, 4)

    cases = build_corpus_from_commits(triples=triples, git_runner=gr, patterns=[], score_flip=score_flip)
    assert [c.function for c in cases] == ["good_fn"]  # bad_fn skipped without crashing
