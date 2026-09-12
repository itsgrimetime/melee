from pathlib import Path

from src.search.solver.realize import load_catalog

# tools/melee-agent/tests/search/solver/test_catalog_dir.py
# parents: [0]=solver [1]=search [2]=tests [3]=tools/melee-agent [4]=tools [5]=<WT>
CATALOG_DIR = (Path(__file__).resolve().parents[5]
               / "docs" / "superpowers" / "lever-catalog")


def test_tracked_catalog_dir_resolves():
    assert CATALOG_DIR.is_dir(), f"D0 catalog dir missing: {CATALOG_DIR}"


def test_tracked_catalog_loads_with_priority_order():
    cat = load_catalog(CATALOG_DIR)
    assert cat["node-add"][0]["lever"] == "alias"
    assert all(e["tier"] == "a" for e in cat["node-add"])
    assert cat["edge-add"][0]["tier"] == "b"
    assert cat["edge-remove"][0]["tier"] == "b"
    assert cat["order"][0]["tier"] == "c"
