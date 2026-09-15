from __future__ import annotations

from src.mwcc_debug.local_safety import (
    LocalWiboProcess,
    allow_unsafe_local_pcdump,
    format_unsafe_processes,
    guard_local_pcdump_lane,
    parse_wibo_processes,
)


def test_parse_wibo_process_extracts_uninterruptible_particle_source() -> None:
    text = (
        "80283     1 UEs        10:27 "
        "/Users/mike/code/melee-harness/bin/wibo "
        "/Users/mike/.codex/worktrees/b639/melee/build/compilers/GC/1.2.5n/"
        "mwcceppc_debug.exe -nowraplines -cwd source -lang=c "
        "-c src/sysdolphin/baselib/particle.c "
        "-o /tmp/pcdump_local_discard_80282.o\n"
    )

    processes = parse_wibo_processes(text)

    assert len(processes) == 1
    assert processes[0].pid == 80283
    assert processes[0].stat == "UEs"
    assert processes[0].source_rel == "src/sysdolphin/baselib/particle.c"
    assert processes[0].uninterruptible is True


def test_guard_rejects_matching_uninterruptible_source() -> None:
    process = LocalWiboProcess(
        pid=80283,
        ppid=1,
        stat="UEs",
        elapsed="10:27",
        command=(
            "wibo mwcceppc_debug.exe "
            "-c src/sysdolphin/baselib/particle.c"
        ),
        source_rel="src/sysdolphin/baselib/particle.c",
    )

    result = guard_local_pcdump_lane(
        source_rel="src/sysdolphin/baselib/particle.c",
        function="hsd_80391AC8",
        processes=[process],
        allow_unsafe=False,
    )

    assert result.unsafe is True
    assert result.processes == [process]
    formatted = format_unsafe_processes(result.processes)
    assert "80283" in formatted
    assert "UEs" in formatted
    assert "src/sysdolphin/baselib/particle.c" in formatted


def test_guard_ignores_other_sources_and_interruptible_processes() -> None:
    processes = [
        LocalWiboProcess(
            pid=1,
            ppid=1,
            stat="S",
            elapsed="00:01",
            command=(
                "wibo mwcceppc_debug.exe "
                "-c src/sysdolphin/baselib/particle.c"
            ),
            source_rel="src/sysdolphin/baselib/particle.c",
        ),
        LocalWiboProcess(
            pid=2,
            ppid=1,
            stat="UE",
            elapsed="00:02",
            command="wibo mwcceppc_debug.exe -c src/melee/pl/pltrick.c",
            source_rel="src/melee/pl/pltrick.c",
        ),
    ]

    result = guard_local_pcdump_lane(
        source_rel="src/sysdolphin/baselib/particle.c",
        function="hsd_80391AC8",
        processes=processes,
        allow_unsafe=False,
    )

    assert result.unsafe is False
    assert result.processes == []


def test_allow_unsafe_accepts_legacy_and_pcdump_env_names() -> None:
    assert allow_unsafe_local_pcdump(
        {"MWCC_DEBUG_ALLOW_UNSAFE_LOCAL": "1"}
    ) is True
    assert allow_unsafe_local_pcdump(
        {"MWCC_DEBUG_ALLOW_UNSAFE_LOCAL_PCDUMP": "true"}
    ) is True
    assert allow_unsafe_local_pcdump({}) is False
