from tools.mwcc_retro.semantic_memo import (
    DependencyMemoEntry,
    InMemoryReadableGlobalEffectMemoStore,
    ReadableGlobalEffectKey,
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
