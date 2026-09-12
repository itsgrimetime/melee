from src.backtest.corpus import resolve_function_unit

REPORT = {"units": [
    {"name": "main/melee/gr/gricemt", "functions": [{"name": "grIceMt_801F9ACC", "fuzzy_match_percent": 100.0}]},
    {"name": "main/melee/mn/mnmain", "functions": [{"name": "other_fn", "fuzzy_match_percent": 80.0}]},
]}

def test_resolves_unit_and_file():
    assert resolve_function_unit(REPORT, "grIceMt_801F9ACC") == ("main/melee/gr/gricemt", "src/melee/gr/gricemt.c")

def test_missing_function_returns_none():
    assert resolve_function_unit(REPORT, "nope") is None
