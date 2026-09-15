from src.inline_leverage.store import InlineLeverageStore
from src.inline_leverage.types import LeverageRecord


def _record(**overrides) -> LeverageRecord:
    data = {
        "run_id": "r1",
        "function": "fnA",
        "unit": "u.c",
        "inline_name": "helper",
        "def_location": "tu",
        "def_file": "u.c:10",
        "is_static": True,
        "n_call_sites": 1,
        "baseline_pct": 100.0,
        "deinlined_pct": 99.0,
        "delta_fuzzy": 1.0,
        "baseline_ndl": 0,
        "deinlined_ndl": 2,
        "delta_struct": 2,
        "verdict": "lever",
        "expansion_form": "value_expr",
        "shape_return": "scalar",
        "shape_body": "single_return_expr",
        "shape_args": ["plain_id"],
        "n_statements": 1,
        "error": None,
    }
    data.update(overrides)
    return LeverageRecord(**data)


def test_insert_and_read_back(tmp_path) -> None:
    store = InlineLeverageStore(tmp_path / "inline.db")
    store.ensure_schema()

    store.insert(_record())

    rows = store.records("r1")
    assert len(rows) == 1
    assert rows[0]["verdict"] == "lever"
    assert rows[0]["shape_args"] == '["plain_id"]'


def test_seen_cache_is_keyed_by_tu_hash(tmp_path) -> None:
    store = InlineLeverageStore(tmp_path / "inline.db")
    store.ensure_schema()

    assert not store.seen("hash-a", "fnA", "helper")
    store.mark_seen("hash-a", "fnA", "helper")

    assert store.seen("hash-a", "fnA", "helper")
    assert not store.seen("hash-b", "fnA", "helper")
