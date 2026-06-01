from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GRICEMT_SOURCE = REPO_ROOT / "src/melee/gr/gricemt.c"


def _read_source() -> str:
    return GRICEMT_SOURCE.read_text()


def _extract_initializer(source: str, symbol: str) -> str:
    marker = f"{symbol}"
    start = source.index(marker)
    equals = source.index("=", start)
    brace = source.index("{", equals)
    depth = 0
    for idx in range(brace, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : idx + 1]
    raise AssertionError(f"could not find initializer end for {symbol}")


def test_gricemt_stage_point_table_keeps_original_data_extent() -> None:
    source = _read_source()

    assert "S16Vec3 points[195]" in source
    assert re.search(r"\bs16\s+pad\b", source)
    assert source.index("grIm_803E4544[218]") < source.index(
        "StageCallbacks grIm_803E4718"
    )
    assert source.index("grIm_803E46F8") < source.index(
        "StageCallbacks grIm_803E4718"
    )

    initializer = _extract_initializer(source, "grIm_803E40B0")
    entries = [
        tuple(int(part.strip()) for part in match.groups())
        for match in re.finditer(
            r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\}", initializer
        )
    ]

    assert len(entries) == 195
    assert entries[:5] == [
        (0, 1, 0),
        (1, 1, 0),
        (2, 1, 0),
        (3, 1, 0),
        (4, 1, 0),
    ]
    assert entries[-5:] == [
        (212, 6, 0),
        (213, 6, 0),
        (214, 6, 0),
        (215, 6, 0),
        (216, 6, 0),
    ]
    assert "grIm_803E40B0.points" in source


def test_gricemt_joint_callback_table_is_defined_with_original_extent() -> None:
    source = _read_source()
    initializer = _extract_initializer(source, "grIm_803E4544")
    values = [int(value) for value in re.findall(r"\b\d+\b", initializer)]

    assert len(values) == 218
    assert values[:16] == list(range(16))
    assert values[216] == 216
    assert values[217] == 0


def test_gricemt_assert_string_block_precedes_stage_callbacks() -> None:
    source = _read_source()
    initializer = _extract_initializer(source, "grIm_803E46F8")

    assert "char file[0xC]" in source
    assert "char field_max[0x14]" in source
    assert '"gricemt.c"' in initializer
    assert '"i<ICEMT_FIELD_MAX"' in initializer
    assert "grIm_803E46F8.file" in source
    assert "#undef HSD_ASSERT" in source
    assert '#define HSD_ASSERT(line, cond) GRICEMT_ASSERT(line, cond, #cond)' in source
    assert (
        'OSReport("%s:%d: couldn t get gobj(id=%d)\\n", grIm_803E46F8.file'
        in source
    )
    assert "block_num<=BLOCK_COLL_JOBJ_MAX" in source
    assert "HSD_ASSERT(0x7E3, coll_jobj)" in source
    assert "HSD_ASSERT(0x7E6, block_jobj)" in source
