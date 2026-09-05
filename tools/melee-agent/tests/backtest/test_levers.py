# tools/melee-agent/tests/backtest/test_levers.py
from src.backtest.levers import classify_lever
from src.backtest.types import LEVER_CLASSES

def test_retype_detected():
    d = "@@\n-    int mode = get();\n+    u8 mode = get();\n"
    assert classify_lever(d) == "retype"

def test_literal_vs_named_detected():
    d = "@@\n-    foo(name_str);\n+    foo(0.0f);\n"
    assert classify_lever(d) == "literal_vs_named"

def test_unknown_is_other():
    assert classify_lever("@@\n-    a();\n+    b();\n") == "other"

def test_always_in_vocabulary():
    assert classify_lever("@@\n+x\n") in LEVER_CLASSES
