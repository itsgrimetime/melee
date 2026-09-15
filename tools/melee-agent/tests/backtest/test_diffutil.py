from src.backtest.diffutil import diff_stats, is_small_singular

DIFF = """diff --git a/src/melee/gr/gricemt.c b/src/melee/gr/gricemt.c
--- a/src/melee/gr/gricemt.c
+++ b/src/melee/gr/gricemt.c
@@ -10,3 +10,3 @@ void f(void) {
-    int x = 1;
+    u8 x = 1;
"""

def test_diff_stats():
    s = diff_stats(DIFF)
    assert s == {"added": 1, "removed": 1, "hunks": 1, "files": 1}

def test_is_small_singular_true():
    assert is_small_singular(DIFF) is True

def test_is_small_singular_false_when_too_big():
    big = DIFF + "".join(f"+line{i}\n" for i in range(40))
    assert is_small_singular(big) is False
