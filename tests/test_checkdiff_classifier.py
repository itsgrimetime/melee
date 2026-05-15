"""Tests for checkdiff classification heuristics."""

import importlib.util
import sys
from pathlib import Path


def load_checkdiff():
    path = Path(__file__).parents[1] / "tools" / "checkdiff.py"
    spec = importlib.util.spec_from_file_location("checkdiff", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classifier_flags_call_shape_as_signature_type_mismatch():
    checkdiff = load_checkdiff()
    ref_lines = [
        "80000000: bl SomeFunc",
        "80000004: cmpwi r3, 0",
        "80000008: blr",
    ]
    our_lines = [
        "80000000: li r3, 0",
        "80000004: blr",
    ]

    result = checkdiff.classify_asm_diff(ref_lines, our_lines)

    assert result["primary"] == "signature-type-mismatch"
