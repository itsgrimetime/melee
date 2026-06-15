"""Tests for the ranked_cursor_iv transform family (transform_corpus.ranked_cursor_iv)."""
from __future__ import annotations

import pytest

from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    generate_transform_probes,
    plan_transform_experiments,
)
from src.search.directed.transform_probe_adapter import transform_probe_key
from src.mwcc_debug.source_shape import CandidatePatch


def _ranked_cursor_iv_source() -> str:
    return (
        "typedef unsigned long long u64;\n"
        "typedef unsigned char u8;\n"
        "typedef struct Entry { u8 name; u64 value; } Entry;\n"
        "u8 target(u8 rank) {\n"
        "    Entry entries[25];\n"
        "    u64 baseVal;\n"
        "    Entry* base;\n"
        "    Entry* ptr;\n"
        "    Entry* curr;\n"
        "    int i;\n"
        "    int k;\n"
        "    int maxIdx;\n"
        "    int neg1;\n"
        "    base = entries;\n"
        "    i = 0;\n"
        "    neg1 = -1;\n"
        "    do {\n"
        "        k = i + 1;\n"
        "        curr = &entries[k];\n"
        "        maxIdx = i;\n"
        "        baseVal = base->value;\n"
        "        while (k < 25) {\n"
        "            if (curr->value != (u64) neg1) {\n"
        "                if (curr->value > entries[maxIdx].value ||\n"
        "                    baseVal == (u64) neg1)\n"
        "                {\n"
        "                    maxIdx = k;\n"
        "                }\n"
        "            }\n"
        "            curr++;\n"
        "            k++;\n"
        "        }\n"
        "        base++;\n"
        "        i++;\n"
        "    } while (i < 25);\n"
        "    ptr = &entries[rank];\n"
        "    if (ptr->value == (u64) -1) {\n"
        "        return 25;\n"
        "    }\n"
        "    return entries[rank].name;\n"
        "}\n"
    )


def test_ranked_cursor_iv_unification_materializes_value_and_return_probes() -> None:
    probes = generate_transform_probes(
        _ranked_cursor_iv_source(),
        function="target",
        unit="melee/mn/mndiagram2",
        force_phys={},
        families=("ranked_cursor_iv_unification",),
        max_per_family=4,
    )

    ranked = [
        probe for probe in probes
        if probe.family_id == "ranked_cursor_iv_unification"
    ]
    assert [probe.mutator_key for probe in ranked] == [
        "unify_ranked_cursor_value_accumulator",
        "reuse_rank_pointer_return_field",
    ]
    assert "curr->value > baseVal ||" in ranked[0].candidate_text
    assert "                    if (baseVal != (u64) neg1) {\n" in ranked[0].candidate_text
    assert "                        baseVal = curr->value;\n" in ranked[0].candidate_text
    assert "return ptr->name;" in ranked[1].candidate_text


def test_ranked_cursor_iv_unification_materializes_return_after_value_probe_lands() -> None:
    source = _ranked_cursor_iv_source().replace(
        "                if (curr->value > entries[maxIdx].value ||\n"
        "                    baseVal == (u64) neg1)\n"
        "                {\n"
        "                    maxIdx = k;\n"
        "                }\n",
        "                if (curr->value > baseVal ||\n"
        "                    baseVal == (u64) neg1)\n"
        "                {\n"
        "                    maxIdx = k;\n"
        "                    if (baseVal != (u64) neg1) {\n"
        "                        baseVal = curr->value;\n"
        "                    }\n"
        "                }\n",
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/mn/mndiagram2",
        force_phys={},
        families=("ranked_cursor_iv_unification",),
        max_per_family=4,
    )

    ranked = [
        probe for probe in probes
        if probe.family_id == "ranked_cursor_iv_unification"
    ]
    assert [probe.mutator_key for probe in ranked] == [
        "reuse_rank_pointer_return_field",
    ]
    assert "return ptr->name;" in ranked[0].candidate_text


def test_ranked_cursor_iv_mutator_rejects_stale_span() -> None:
    probe = generate_transform_probes(
        _ranked_cursor_iv_source(),
        function="target",
        unit="melee/mn/mndiagram2",
        force_phys={},
        families=("ranked_cursor_iv_unification",),
        max_per_family=1,
    )[0]
    stale = _ranked_cursor_iv_source().replace(
        "curr->value > entries[maxIdx].value",
        "curr->value >= entries[maxIdx].value",
    )

    assert apply_mutator(
        probe.mutator_key,
        Anchor(probe.mutator_key, probe.span, probe.payload),
        stale,
    ) is None


@pytest.mark.parametrize(
    "source",
    (
        _ranked_cursor_iv_source().replace(
            "    Entry entries[25];\n",
            "#if 1\n    Entry entries[25];\n#endif\n",
        ),
        _ranked_cursor_iv_source().replace(
            "                    maxIdx = k;\n",
            "                    use(curr);\n                    maxIdx = k;\n",
        ),
        _ranked_cursor_iv_source().replace(
            "        base++;\n"
            "        i++;\n",
            "        use(baseVal);\n"
            "        base++;\n"
            "        i++;\n",
        ),
        _ranked_cursor_iv_source().replace(
            "typedef struct Entry { u8 name; u64 value; } Entry;\n",
            "typedef struct Entry { u8 name; u64 value; } Entry;\n"
            "Entry entries[25];\n",
        ).replace(
            "    Entry entries[25];\n",
            "",
        ),
        _ranked_cursor_iv_source().replace(
            "        baseVal = base->value;\n"
            "        while (k < 25) {\n"
            "            if (curr->value != (u64) neg1) {\n"
            "                if (curr->value > entries[maxIdx].value ||\n"
            "                    baseVal == (u64) neg1)\n"
            "                {\n"
            "                    maxIdx = k;\n"
            "                }\n"
            "            }\n"
            "            curr++;\n"
            "            k++;\n"
            "        }\n",
            "        baseVal = base->value;\n"
            "        while (k < 25) {\n"
            "            if (curr->value != (u64) neg1) {\n"
            "                if (curr->value > entries[maxIdx].value ||\n"
            "                    baseVal == (u64) neg1)\n"
            "                {\n"
            "                    maxIdx = k;\n"
            "                }\n"
            "            }\n"
            "            curr++;\n"
            "            k++;\n"
            "        }\n"
            "        baseVal = base->value;\n"
            "        while (k < 25) {\n"
            "            if (curr->value != (u64) neg1) {\n"
            "                if (curr->value > entries[maxIdx].value ||\n"
            "                    baseVal == (u64) neg1)\n"
            "                {\n"
            "                    maxIdx = k;\n"
            "                }\n"
            "            }\n"
            "            curr++;\n"
            "            k++;\n"
            "        }\n",
        ).replace(
            "    ptr = &entries[rank];\n"
            "    if (ptr->value == (u64) -1) {\n"
            "        return 25;\n"
            "    }\n"
            "    return entries[rank].name;\n",
            "    ptr = &entries[rank];\n"
            "    if (ptr->value == (u64) -1) {\n"
            "        return 25;\n"
            "    }\n"
            "    return entries[rank].name;\n"
            "    ptr = &entries[rank];\n"
            "    if (ptr->value == (u64) -1) {\n"
            "        return 25;\n"
            "    }\n"
            "    return entries[rank].name;\n",
        ),
        _ranked_cursor_iv_source().replace(
            "typedef struct Entry { u8 name; u64 value; } Entry;\n",
            "typedef struct Entry { u8 name; u64 value; } Entry;\n"
            "Entry entries[25];\n",
        ).replace(
            "    Entry entries[25];\n",
            "",
        ).replace(
            "    return entries[rank].name;\n",
            "    return entries[rank].name;\n"
            "    {\n"
            "        Entry entries[25];\n"
            "        use(entries);\n"
            "    }\n",
        ),
    ),
)
def test_ranked_cursor_iv_unification_rejects_unsafe_shapes(source: str) -> None:
    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/mn/mndiagram2",
        force_phys={},
        families=("ranked_cursor_iv_unification",),
        max_per_family=4,
    )

    assert "ranked_cursor_iv_unification" not in {probe.family_id for probe in probes}
