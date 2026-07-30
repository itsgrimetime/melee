import json
import sqlite3
import zlib

import pytest
from tools.mwcc_retro import semantic_memo as semantic_memo_module
from tools.mwcc_retro.semantic_memo import (
    DependencyMemoEntry,
    InMemoryReadableGlobalEffectMemoStore,
    ReadableGlobalEffectKey,
    SemanticMemoStoreError,
    SqliteReadableGlobalEffectMemoStore,
)


def readable_key(
    context: tuple[tuple[int, int, int], ...] = (
        (0x401000, 0x402000, 0x403000),
    ),
) -> ReadableGlobalEffectKey:
    return ReadableGlobalEffectKey(
        call_target=0x401000,
        slot=0x580000,
        field_path=(4, 0),
        exact_call_contexts=context,
        summary_fact_signature=(10, 20, 30, 40, 50, 60),
        control_flow_revision=7,
    )


def test_equal_dependency_tuples_are_interned():
    store = InMemoryReadableGlobalEffectMemoStore()
    first_dependencies = (("function", 0x401000, "a" * 64),)
    second_dependencies = tuple(list(first_dependencies))
    store.put(
        readable_key(),
        DependencyMemoEntry(
            "b" * 64,
            first_dependencies,
            (frozenset({1}), "one"),
        ),
    )
    store.put(
        readable_key(((0x401000, 0x402001, 0x403000),)),
        DependencyMemoEntry(
            "b" * 64,
            second_dependencies,
            None,
        ),
    )

    first = store.get(readable_key())
    second = store.get(
        readable_key(((0x401000, 0x402001, 0x403000),))
    )
    assert first is not None and second is not None
    assert first.dependencies is second.dependencies
    assert len(store.dependency_pool) == 1


def test_return_filters_are_distinct_memo_keys():
    store = InMemoryReadableGlobalEffectMemoStore()
    unfiltered = readable_key()
    nonzero = ReadableGlobalEffectKey(
        call_target=unfiltered.call_target,
        slot=unfiltered.slot,
        field_path=unfiltered.field_path,
        exact_call_contexts=unfiltered.exact_call_contexts,
        summary_fact_signature=unfiltered.summary_fact_signature,
        control_flow_revision=unfiltered.control_flow_revision,
        require_nonzero_return=True,
    )
    store.put(unfiltered, finite_entry())
    store.put(
        nonzero,
        DependencyMemoEntry(
            "b" * 64,
            finite_entry().dependencies,
            (frozenset({2}), "nonzero"),
        ),
    )

    assert store.get(unfiltered) != store.get(nonzero)
    assert len(store) == 2


def test_unequal_dependency_tuples_remain_distinct():
    store = InMemoryReadableGlobalEffectMemoStore()
    store.put(
        readable_key(),
        DependencyMemoEntry(
            "b" * 64,
            (("function", 0x401000, "a" * 64),),
            None,
        ),
    )
    store.put(
        readable_key(((0x401000, 0x402001, 0x403000),)),
        DependencyMemoEntry(
            "b" * 64,
            (("function", 0x401000, "c" * 64),),
            None,
        ),
    )

    assert len(store.dependency_pool) == 2


def finite_entry(
    *,
    fingerprint: str = "a" * 64,
) -> DependencyMemoEntry:
    return DependencyMemoEntry(
        "b" * 64,
        (("function", 0x401000, fingerprint),),
        (frozenset({1, 7}), "preserved;proof"),
    )


def test_sqlite_store_round_trips_and_reopens(tmp_path):
    path = tmp_path / "readable-global.sqlite3"
    entry = finite_entry()
    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
        lru_entries=1,
    ) as store:
        store.put(readable_key(), entry)
        assert store.get(readable_key()) == entry

    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
        lru_entries=1,
    ) as reopened:
        assert reopened.get(readable_key()) == entry


def test_sqlite_store_normalizes_dependencies_and_recovers_after_lru_eviction(
    tmp_path,
):
    path = tmp_path / "readable-global.sqlite3"
    second_key = readable_key(((0x401000, 0x402001, 0x403000),))
    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
        lru_entries=1,
    ) as store:
        store.put(readable_key(), finite_entry())
        store.put(
            second_key,
            DependencyMemoEntry(
                "b" * 64,
                tuple(list(finite_entry().dependencies)),
                None,
            ),
        )
        assert len(store.lru) == 1
        assert store.get(readable_key()) == finite_entry()
        assert store.get(second_key) is not None
        assert store.get(second_key).result is None

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM dependencies"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM memo"
        ).fetchone()[0] == 2
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("metadata_key", "metadata_value", "error"),
    (
        (
            "schema",
            "wrong-schema",
            "metadata",
        ),
        (
            "image_sha256",
            "c" * 64,
            "compiler SHA",
        ),
        (
            "analysis_semantics",
            "readable-global-effect-v999",
            "semantics",
        ),
    ),
)
def test_sqlite_store_rejects_wrong_metadata(
    tmp_path,
    metadata_key,
    metadata_value,
    error,
):
    path = tmp_path / "readable-global.sqlite3"
    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
    ):
        pass
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = ?",
            (metadata_value, metadata_key),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SemanticMemoStoreError, match=error):
        SqliteReadableGlobalEffectMemoStore(
            path,
            image_sha256="b" * 64,
        )


def _replace_only_payload(path, table, column, payload):
    connection = sqlite3.connect(path)
    try:
        statements = {
            ("memo", "key_payload"): (
                "UPDATE memo SET key_payload = ?"
            ),
            ("memo", "result_payload"): (
                "UPDATE memo SET result_payload = ?"
            ),
            ("dependencies", "payload"): (
                "UPDATE dependencies SET payload = ?"
            ),
        }
        connection.execute(statements[(table, column)], (payload,))
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("table", "column", "payload", "error"),
    (
        (
            "memo",
            "key_payload",
            zlib.compress(b"{}", level=1),
            "key payload digest",
        ),
        (
            "memo",
            "result_payload",
            zlib.compress(
                b'{"status":"finite","values":[999],'
                b'"provenance":"bad"}',
                level=1,
            ),
            "result payload",
        ),
        (
            "memo",
            "result_payload",
            zlib.compress(
                b'{"status":"blocked","status":"finite"}',
                level=1,
            ),
            "duplicate key",
        ),
        (
            "dependencies",
            "payload",
            zlib.compress(
                json.dumps(
                    [
                        {
                            "kind": "unknown",
                            "identifier": 0x401000,
                            "fingerprint": "a" * 64,
                        }
                    ]
                ).encode(),
                level=1,
            ),
            "dependency payload",
        ),
        (
            "dependencies",
            "payload",
            b"not-zlib",
            "compressed data",
        ),
    ),
)
def test_sqlite_store_rejects_malformed_rows(
    tmp_path,
    table,
    column,
    payload,
    error,
):
    path = tmp_path / "readable-global.sqlite3"
    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
    ) as store:
        store.put(readable_key(), finite_entry())
    _replace_only_payload(path, table, column, payload)

    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
    ) as store:
        with pytest.raises(SemanticMemoStoreError, match=error):
            store.get(readable_key())


def test_sqlite_store_rejects_non_database_bytes(tmp_path):
    path = tmp_path / "readable-global.sqlite3"
    path.write_bytes(b"not a sqlite database")

    with pytest.raises(SemanticMemoStoreError, match="SQLite"):
        SqliteReadableGlobalEffectMemoStore(
            path,
            image_sha256="b" * 64,
        )


def test_sqlite_store_rejects_invalid_runtime_key_shape(tmp_path):
    path = tmp_path / "readable-global.sqlite3"
    invalid_key = ReadableGlobalEffectKey(
        call_target=True,
        slot=0x580000,
        field_path=(4, 0),
        exact_call_contexts=((0x401000, 0x402000, 0x403000),),
        summary_fact_signature=(10, 20, 30, 40, 50, 60),
        control_flow_revision=7,
    )
    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
    ) as store:
        with pytest.raises(
            SemanticMemoStoreError,
            match="invalid scalar",
        ):
            store.get(invalid_key)


def test_sqlite_store_does_not_publish_rolled_back_rows(tmp_path):
    path = tmp_path / "readable-global.sqlite3"
    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
    ):
        pass

    connection = sqlite3.connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO dependencies(dependency_sha256, payload) "
            "VALUES (?, ?)",
            ("d" * 64, zlib.compress(b"[]", level=1)),
        )
        connection.rollback()
    finally:
        connection.close()

    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
    ) as store:
        assert len(store) == 0
        assert store.get(readable_key()) is None


def test_sqlite_store_serializes_shared_dependencies_once(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "readable-global.sqlite3"
    dependency_serializations = 0
    original = semantic_memo_module._canonical_json_bytes

    def count_dependency_serializations(value):
        nonlocal dependency_serializations
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and "fingerprint" in value[0]
        ):
            dependency_serializations += 1
        return original(value)

    monkeypatch.setattr(
        semantic_memo_module,
        "_canonical_json_bytes",
        count_dependency_serializations,
    )
    second_key = readable_key(
        ((0x401000, 0x402001, 0x403000),)
    )
    with SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
        lru_entries=1,
    ) as store:
        store.put(readable_key(), finite_entry())
        store.put(
            second_key,
            DependencyMemoEntry(
                "b" * 64,
                tuple(list(finite_entry().dependencies)),
                None,
            ),
        )

    assert dependency_serializations == 1
