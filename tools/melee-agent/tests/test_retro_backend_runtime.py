import json
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _stub_backend_mwcc_command(monkeypatch, retro, command: str | None = None) -> None:
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda *_args, **_kwargs: command
        or "build/compilers/GC/1.2.5n/mwcceppc.exe -c src/melee/test/unit.c -o unit.o",
    )


def _add_internal_colorgraph_entries(entries: dict) -> None:
    for index, key in enumerate(
        (
            "colorgraph_select_start",
            "colorgraph_candidates_ready",
            "colorgraph_assign_volatile",
            "colorgraph_assign_nonvolatile",
            "colorgraph_spill",
        ),
        start=100,
    ):
        entries[key] = {
            "va": 0x4CE000 + index,
            "confidence": "manual-disassembly-confirmed",
            "provenance": "fixture",
        }


def _write_valid_backend_map(table_dir: Path) -> None:
    from tools.mwcc_retro import struct_map

    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
        "backend_reader": {
            "complete": True,
            "event_families": list(struct_map.REQUIRED_BACKEND_READER_FAMILIES),
        },
    }
    _add_internal_colorgraph_entries(table["entries"])
    (table_dir / "gc_125n.json").write_text(json.dumps(table) + "\n")


def _write_partial_backend_ig_table(table_dir: Path) -> None:
    from tools.mwcc_retro import struct_map

    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
        "backend_reader": {
            "complete": False,
            "event_families": ["function_start", "backend_marker"],
            "partial_event_families": [
                "function_start",
                "backend_marker",
                "regclass",
                "node",
                "edge",
                "coalesce_mapping",
                "coalesce_mapping_empty",
                "simplify_order",
                "select_order",
                "color_decision",
            ],
        },
    }
    _add_internal_colorgraph_entries(table["entries"])
    (table_dir / "gc_125n.json").write_text(json.dumps(table) + "\n")


def _write_partial_backend_pcode_table(table_dir: Path) -> None:
    from tools.mwcc_retro import struct_map

    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
        "backend_reader": {
            "complete": False,
            "event_families": ["function_start", "backend_marker"],
            "partial_pcode_event_families": [
                "function_start",
                "backend_marker",
                "block",
                "pcode_instruction",
            ],
        },
    }
    _add_internal_colorgraph_entries(table["entries"])
    (table_dir / "gc_125n.json").write_text(json.dumps(table) + "\n")


def _valid_ig_snapshot_payload(function: str = "test_fn") -> dict:
    return {
        "schema_version": "mwcc-retro-backend-ig-snapshot.v1",
        "requested_function": function,
        "requested_function_matched": True,
        "classes_seen": [{"class_id": 0, "class_name": "gpr", "nodes": 2}],
        "errors": [],
    }


def _valid_ig_snapshot_events(function: str = "test_fn") -> str:
    return "\n".join(
        [
            json.dumps({"event": "function_start", "name": function}),
            json.dumps({"event": "backend_marker", "name": "codegen_start"}),
            json.dumps(
                {
                    "event": "regclass",
                    "class_name": "gpr",
                    "class_id": 0,
                    "registers": {
                        "physical_count": 32,
                        "allocatable": [3, 4],
                        "initial_volatile": [3, 4],
                        "reserved": [0, 1, 2],
                        "fixed": [],
                        "precolored": [],
                        "nonvolatile_dispense_order": [],
                        "model_boundary": [],
                    },
                    "non_allocatable_state": {"status": "model-boundary"},
                }
            ),
            json.dumps(
                {
                    "event": "node",
                    "class_name": "gpr",
                    "class_id": 0,
                    "ig_id": 0,
                }
            ),
            json.dumps(
                {
                    "event": "node",
                    "class_name": "gpr",
                    "class_id": 0,
                    "ig_id": 1,
                }
            ),
            json.dumps(
                {
                    "event": "coalesce_mapping_empty",
                    "class_name": "gpr",
                    "class_id": 0,
                    "confidence": "observed",
                    "provenance": "retail_ignode_no_coalesced_aliases",
                    "source_stage": "colorgraph",
                }
            ),
            json.dumps(
                {
                    "event": "edge",
                    "class_name": "gpr",
                    "class_id": 0,
                    "a": 0,
                    "b": 1,
                }
            ),
            json.dumps(
                {
                    "event": "simplify_order",
                    "class_name": "gpr",
                    "class_id": 0,
                    "order": [1, 0],
                    "source_stage": "colorgraph_head_after_simplifygraph",
                    "provenance": "colorgraph_head",
                }
            ),
            json.dumps(
                {
                    "event": "select_order",
                    "class_name": "gpr",
                    "class_id": 0,
                    "order": [1, 0],
                    "source_stage": "colorgraph_head_after_simplifygraph",
                    "provenance": "colorgraph_head",
                }
            ),
            "",
        ]
    )


def _valid_color_decision_event() -> dict:
    return {
        "event": "color_decision",
        "class_name": "gpr",
        "class_id": 0,
        "id": "gpr-c0",
        "ig_id": 1,
        "iter": 0,
        "assigned_phys": 30,
        "node_state_before_select": {
            "status": "unavailable",
            "reason": "retail-post-colorgraph-only",
        },
        "reserved_or_precolored_filtered": [],
        "available_phys_ordered": [],
        "blocked_candidates": [
            {
                "phys": 31,
                "reason": "interferer-assigned-phys",
                "holder_ig_id": 0,
                "holder_assigned_phys": 31,
                "provenance": "retail-post-colorgraph-interference",
            }
        ],
        "blocked_by": [{"ig_id": 0, "phys": 31}],
        "candidate_phys_ordered": [30],
        "chosen_source": "observed-retail-assignment",
        "tie_rule": "unavailable-retail-post-colorgraph",
        "decision_rule": "retail-post-colorgraph-observed-assignment",
        "confidence": "observed-partial",
        "provenance": "retail-colorgraph-return",
        "source_stage": "colorgraph_return",
    }


def _valid_internal_colorgraph_decision_event() -> dict:
    event = _valid_color_decision_event()
    event.update(
        {
            "id": "gpr-i0",
            "assigned_phys": 0,
            "available_phys_ordered": [0, 3, 4],
            "candidate_phys_ordered": [0, 3, 4],
            "chosen_source": "volatile_pool",
            "volatile_pool_before": [0, 3, 4],
            "volatile_pool_after": [3, 4],
            "nonvolatile_dispense_before": {"next": None, "remaining": []},
            "nonvolatile_dispense_after": {"consumed": None, "remaining": []},
            "tie_rule": "first_volatile_available",
            "node_state_before_select": {
                "precolored": False,
                "coalesced": False,
                "spill_marked": False,
                "rematerialized": False,
            },
            "confidence": "observed-internal",
            "provenance": "retail-colorgraph-internal",
            "source_stage": "colorgraph",
        }
    )
    return event


def _valid_colorgraph_decision_events(function: str = "test_fn") -> str:
    return "\n".join(
        [
            json.dumps({"event": "function_start", "name": function}),
            json.dumps(_valid_internal_colorgraph_decision_event()),
            "",
        ]
    )


def _valid_colorgraph_trace_payload(function: str = "test_fn") -> dict:
    return {
        "schema_version": "mwcc-retro-backend-colorgraph-trace.v1",
        "requested_function": function,
        "requested_function_matched": True,
        "decisions_seen": [{"class_id": 0, "class_name": "gpr", "ig_id": 33}],
        "internal_breakpoints": {
            "select_start": 0x4CE331,
            "candidates_ready": 0x4CE370,
            "assign_volatile": 0x4CE381,
            "assign_nonvolatile": 0x4CE3BF,
            "spill": 0x4CE3D3,
        },
        "errors": [],
    }


def _valid_ig_snapshot_events_with_color_decision(function: str = "test_fn") -> str:
    return _valid_ig_snapshot_events(function) + json.dumps(_valid_color_decision_event()) + "\n"


def _valid_alias_mapping_ig_snapshot_events(function: str = "test_fn") -> str:
    return "\n".join(
        line
        for line in _valid_ig_snapshot_events(function).splitlines()
        if '"coalesce_mapping_empty"' not in line
    ).replace(
        json.dumps(
            {
                "event": "edge",
                "class_name": "gpr",
                "class_id": 0,
                "a": 0,
                "b": 1,
            }
        ),
        json.dumps(
            {
                "event": "coalesce_mapping",
                "class_name": "gpr",
                "class_id": 0,
                "alias": 1,
                "root": 0,
                "root_phys": None,
                "confidence": "observed",
                "provenance": "retail_ignode_coalesced_away",
                "source_stage": "colorgraph",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event": "edge",
                "class_name": "gpr",
                "class_id": 0,
                "a": 0,
                "b": 1,
            }
        ),
    ) + "\n"


def _run_ig_snapshot_with_events(monkeypatch, tmp_path, events: str) -> None:
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(events)
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    retro._launch_backend_ig_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )


def _ig_snapshot_events_without_orders(function: str = "test_fn") -> str:
    return "\n".join(
        line
        for line in _valid_ig_snapshot_events(function).splitlines()
        if '"simplify_order"' not in line and '"select_order"' not in line
    ) + "\n"


def _valid_edge_free_ig_snapshot_events(function: str = "test_fn") -> str:
    return "\n".join(
        line for line in _valid_ig_snapshot_events(function).splitlines() if '"edge"' not in line
    ) + "\n"


def _valid_empty_order_ig_snapshot_events(function: str = "test_fn") -> str:
    return "\n".join(
        line.replace('"order": [1, 0]', '"order": []')
        if '"simplify_order"' in line or '"select_order"' in line
        else line
        for line in _valid_ig_snapshot_events(function).splitlines()
    ) + "\n"


def _valid_pcode_snapshot_payload(function: str = "test_fn") -> dict:
    return {
        "schema_version": "mwcc-retro-backend-pcode-snapshot.v1",
        "requested_function": function,
        "requested_function_matched": True,
        "passes_seen": [
            {
                "pass_id": "pcode_snapshot",
                "pass_name": "PCode Snapshot",
                "blocks": 1,
                "instructions": 1,
            }
        ],
        "errors": [],
    }


def _valid_pcode_snapshot_events(function: str = "test_fn") -> str:
    return "\n".join(
        [
            json.dumps({"event": "function_start", "name": function}),
            json.dumps({"event": "backend_marker", "name": "pcode_pass_boundary"}),
            json.dumps(
                {
                    "event": "block",
                    "id": "B0",
                    "order": 0,
                    "succ": [],
                    "pred": [],
                    "labels": [],
                }
            ),
            json.dumps(
                {
                    "event": "pcode_instruction",
                    "pass_id": "pcode_snapshot",
                    "pass_name": "PCode Snapshot",
                    "id": "p0",
                    "block_id": "B0",
                    "order": 0,
                    "opcode": "mr",
                    "operands": "",
                    "normalized": "mr",
                }
            ),
            "",
        ]
    )


def test_run_backend_trace_invokes_parity_before_launcher(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    )
    trace = json.loads(fixture.read_text())
    calls = []
    _stub_backend_mwcc_command(monkeypatch, retro)

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: calls.append("parity") or {"matched": True},
    )
    monkeypatch.setattr(
        retro,
        "_launch_backend_events",
        lambda **kw: calls.append("launch") or tmp_path / "events.jsonl",
    )
    monkeypatch.setattr(
        retro.backend_events, "load_events", lambda path: calls.append("load") or []
    )
    monkeypatch.setattr(
        retro.backend_events,
        "normalize_events",
        lambda *args, **kw: calls.append("normalize") or trace,
    )

    outcome = retro._run_backend_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        verify_debug=False,
        melee_root=Path.cwd(),
    )
    assert outcome.exit_code == 0
    assert outcome.trace == trace
    assert calls == ["parity", "launch", "load", "normalize"]


def test_run_backend_trace_hashes_mwcc_command_for_source_metadata(monkeypatch, tmp_path):
    import hashlib

    import src.cli.debug.retro as retro

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    )
    trace = json.loads(fixture.read_text())
    command = (
        "build/compilers/GC/1.2.5n/mwcceppc.exe -O4,p -proc gekko "
        "-c src/melee/test/unit.c -o build/GALE01/src/melee/test/unit.o"
    )
    seen = {}

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: {"matched": True},
    )
    monkeypatch.setattr(
        retro,
        "_launch_backend_events",
        lambda **kw: tmp_path / "events.jsonl",
    )
    monkeypatch.setattr(retro, "_ninja_cmd_for_unit", lambda *_args, **_kw: command)
    monkeypatch.setattr(retro.backend_events, "load_events", lambda path: [])

    def fake_normalize_events(*args, **kwargs):
        seen["source"] = kwargs["source"]
        return trace

    monkeypatch.setattr(retro.backend_events, "normalize_events", fake_normalize_events)

    retro._run_backend_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        verify_debug=False,
        melee_root=Path.cwd(),
    )

    assert seen["source"]["mwcc_command"] == command
    assert seen["source"]["mwcc_command_hash"] == (
        "sha256:" + hashlib.sha256(command.encode()).hexdigest()
    )


def test_run_backend_trace_verify_debug_compares_against_mwcc_debug(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    )
    trace = json.loads(fixture.read_text())
    report = {
        "schema_version": "mwcc-retro-backend-fidelity.v1",
        "summary": {"equal": 1, "retail_only": 0, "debug_only": 0, "different": 0, "not_comparable": 0},
    }
    calls = []
    _stub_backend_mwcc_command(monkeypatch, retro)

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: calls.append("parity") or {"matched": True},
    )
    monkeypatch.setattr(
        retro,
        "_launch_backend_events",
        lambda **kw: calls.append("launch") or tmp_path / "events.jsonl",
    )
    monkeypatch.setattr(
        retro.backend_events, "load_events", lambda path: calls.append("load") or []
    )
    monkeypatch.setattr(
        retro.backend_events,
        "normalize_events",
        lambda *args, **kw: calls.append("normalize") or trace,
    )
    monkeypatch.setattr(
        retro,
        "_compare_backend_trace_with_debug_pcdump",
        lambda **kw: calls.append(("compare", kw["fn"])) or report,
    )

    outcome = retro._run_backend_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        verify_debug=True,
        melee_root=Path.cwd(),
    )

    assert outcome.exit_code == 0
    assert outcome.trace == trace
    assert outcome.fidelity == report
    assert calls == ["parity", "launch", "load", "normalize", ("compare", "test_fn")]


def test_run_backend_map_probe_writes_static_report_and_runs_hook(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    calls = []

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: calls.append(("parity", kw)) or {"matched": True},
    )

    def fake_launch_dump(**kw):
        calls.append(("launch", kw))
        (kw["out_dir"] / "backend-map-probe.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-map-probe.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": True,
                    "errors": [],
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    outcome = retro._run_backend_map_probe(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        static_only=False,
        melee_root=REPO,
    )

    assert outcome.exit_code == 0
    assert (tmp_path / "backend-map-candidates.json").exists()
    assert (tmp_path / "backend-map-probe.json").exists()
    assert (tmp_path / "backend-map-evidence.json").exists()
    assert [name for name, _ in calls] == ["parity", "launch"]
    launch_kwargs = calls[1][1]
    assert launch_kwargs["phases"] == "backend"
    assert launch_kwargs["compiler"] == "1.2.5n"
    assert launch_kwargs["gdb_py"].endswith("backend_map_probe_hook.py")
    assert not (tmp_path / "backend-events.v1.jsonl").exists()
    assert not (tmp_path / "backend-trace.v1.json").exists()


def test_run_backend_map_probe_rejects_unmatched_or_error_payload(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kw: {"matched": True},
    )

    def fake_launch_dump(**kw):
        (kw["out_dir"] / "backend-map-probe.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-map-probe.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": False,
                    "errors": [{"stage": "colorgraph", "error": "read failed"}],
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._run_backend_map_probe(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            static_only=False,
            melee_root=REPO,
        )
    message = str(excinfo.value)
    assert "backend map probe did not observe requested function test_fn" in message
    assert "backend map probe recorded 1 error(s)" in message


def test_run_backend_map_probe_removes_stale_trace_artifacts(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    stale_files = [
        "backend-events.v1.jsonl",
        "backend-trace.v1.json",
        "backend-summary.txt",
        "regalloc-summary.txt",
        "backend-fidelity.json",
        "backend-fidelity.txt",
        "backend-source-attribution.json",
        "backend-colorgraph-decisions.v1.jsonl",
        "backend-colorgraph-trace.json",
        "backend-00-before.txt",
        "launch.log",
        "provenance.json",
        "regalloc-gpr-pass-1-all.txt",
        "variables.txt",
    ]
    for name in stale_files:
        (tmp_path / name).write_text("stale\n")
    preserved_frontend_files = [
        "frontend-00-ast-initial.txt",
        "iro-00-buildflowgraph.txt",
        "iro-summary.txt",
        "iro-trace.txt",
    ]
    for name in preserved_frontend_files:
        (tmp_path / name).write_text("frontend\n")
    (tmp_path / "backend-map-evidence.json").write_text("stale\n")

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kw: {"matched": True},
    )

    def fake_launch_dump(**kw):
        (kw["out_dir"] / "backend-map-probe.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-map-probe.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": True,
                    "errors": [],
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    retro._run_backend_map_probe(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        static_only=False,
        melee_root=REPO,
    )

    for name in stale_files:
        assert not (tmp_path / name).exists()
    for name in preserved_frontend_files:
        assert (tmp_path / name).read_text() == "frontend\n"
    assert (tmp_path / "backend-map-candidates.json").exists()
    assert (tmp_path / "backend-map-probe.json").exists()
    assert (tmp_path / "backend-map-evidence.json").exists()
    assert (tmp_path / "backend-map-evidence.json").read_text() != "stale\n"


def test_run_backend_map_probe_removes_stale_candidates_before_static_failure(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import backend_discovery

    stale = tmp_path / "backend-map-candidates.json"
    stale.write_text("stale\n")

    def fail_report(_exe):
        raise RuntimeError("static discovery failed")

    monkeypatch.setattr(
        backend_discovery,
        "build_gc125n_backend_candidate_report",
        fail_report,
    )

    with pytest.raises(RuntimeError, match="static discovery failed"):
        retro._run_backend_map_probe(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            static_only=False,
            melee_root=REPO,
        )

    assert not stale.exists()


def test_run_backend_map_probe_reports_launcher_failure(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kw: {"matched": True},
    )
    monkeypatch.setattr(
        retro,
        "_launch_dump",
        lambda **_kw: retro.DumpOutcome(exit_code=2, produced=[], missing=["hook"]),
    )

    with pytest.raises(RuntimeError) as excinfo:
        retro._run_backend_map_probe(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            static_only=False,
            melee_root=REPO,
        )
    assert "backend map probe launcher failed (exit 2)" in str(excinfo.value)
    assert "missing: hook" in str(excinfo.value)


def test_run_backend_map_probe_static_only_skips_parity_and_hook(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("parity should not run")),
    )
    monkeypatch.setattr(
        retro,
        "_launch_dump",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("launcher should not run")),
    )

    outcome = retro._run_backend_map_probe(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        static_only=True,
        melee_root=REPO,
    )

    assert outcome.exit_code == 0
    assert outcome.produced == ["static"]
    assert (tmp_path / "backend-map-candidates.json").exists()
    assert not (tmp_path / "backend-map-probe.json").exists()


def test_run_backend_ig_snapshot_runs_parity_before_launcher(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    calls = []
    summary_path = tmp_path / "backend-ig-snapshot.json"
    events_path = tmp_path / "backend-ig-snapshot-events.v1.jsonl"

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: calls.append("parity") or {"matched": True},
    )
    monkeypatch.setattr(
        retro,
        "_launch_backend_ig_snapshot",
        lambda **kw: calls.append("launch") or (summary_path, events_path),
    )

    outcome = retro._run_backend_ig_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )

    assert outcome.exit_code == 0
    assert outcome.summary_path == summary_path
    assert outcome.events_path == events_path
    assert calls == ["parity", "launch"]


def test_run_backend_candidate_trace_assembles_separate_probe_outputs(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    fixture = (
        REPO
        / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    )
    trace = json.loads(fixture.read_text())
    calls = []
    _stub_backend_mwcc_command(monkeypatch, retro)

    def fake_map(**kw):
        calls.append(("map", kw["out_dir"].name))
        out = kw["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "backend-map-probe.json").write_text(
            json.dumps({"events": [{"stage": "final_scheduler", "frame_state": trace["functions"][0]["frame"]}]})
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    def fake_pcode(**kw):
        calls.append(("pcode", kw["out_dir"].name))
        out = kw["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "backend-pcode-snapshot-events.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
        )
        return retro.BackendPcodeSnapshotOutcome(
            exit_code=0,
            summary_path=out / "backend-pcode-snapshot.json",
            events_path=out / "backend-pcode-snapshot-events.v1.jsonl",
        )

    def fake_ig(**kw):
        calls.append(("ig", kw["out_dir"].name))
        out = kw["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "backend-ig-snapshot-events.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
        )
        (out / "backend-colorgraph-decisions.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
        )
        return retro.BackendIgSnapshotOutcome(
            exit_code=0,
            summary_path=out / "backend-ig-snapshot.json",
            events_path=out / "backend-ig-snapshot-events.v1.jsonl",
        )

    monkeypatch.setattr(retro, "_run_backend_map_probe", fake_map)
    monkeypatch.setattr(retro, "_run_backend_pcode_snapshot", fake_pcode)
    monkeypatch.setattr(retro, "_run_backend_ig_snapshot", fake_ig)
    monkeypatch.setattr(
        retro.backend_trace_assembler,
        "frame_events_from_map_probe_payload",
        lambda payload: trace["functions"][0]["frame"]
        and [
            {
                "event": "frame_state",
                **trace["functions"][0]["frame"],
            }
        ],
    )
    monkeypatch.setattr(
        retro.backend_trace_assembler,
        "assemble_candidate_trace",
        lambda **_kw: trace,
    )

    outcome = retro._run_backend_candidate_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=REPO,
    )

    assert outcome.exit_code == 0
    assert outcome.trace == trace
    assert calls == [
        ("map", "map"),
        ("pcode", "pcode"),
        ("ig", "ig"),
    ]
    assert (tmp_path / "backend-trace.candidate.v1.json").exists()
    assert (tmp_path / "regalloc-summary.candidate.txt").exists()
    assert (tmp_path / "backend-summary.candidate.txt").exists()
    assert not (tmp_path / "backend-trace.v1.json").exists()


def test_run_backend_candidate_trace_one_pass_uses_single_event_stream(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    table_dir = tmp_path / "tables"
    table_dir.mkdir()
    _write_partial_backend_ig_table(table_dir)
    table_path = table_dir / "gc_125n.json"
    table = json.loads(table_path.read_text())
    table["backend_reader"]["partial_pcode_event_families"] = [
        "function_start",
        "backend_marker",
        "block",
        "pcode_instruction",
    ]
    table_path.write_text(json.dumps(table) + "\n")

    fixture_events = (
        REPO
        / "tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl"
    )
    calls = []
    _stub_backend_mwcc_command(monkeypatch, retro)

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kwargs: {"matched": True},
    )
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: table_dir)

    def fake_launch_dump(**kw):
        calls.append(kw)
        assert kw["phases"] == "backend"
        assert kw["compiler"] == "1.2.5n"
        assert kw["gdb_py"].endswith("backend_onepass_trace_hook.py")
        out = kw["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "backend-events.v1.jsonl").write_text(fixture_events.read_text())
        (out / "backend-onepass-candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": True,
                    "classes_seen": [
                        {
                            "class_id": 0,
                            "class_name": "gpr",
                            "nodes": 3,
                            "order_nodes": 2,
                            "exact_color_decisions": 2,
                        }
                    ],
                    "errors": [],
                    "warnings": [],
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    outcome = retro._run_backend_candidate_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=REPO,
        one_pass=True,
    )

    assert outcome.exit_code == 0
    assert calls
    assert outcome.trace["source"]["function"] == "test_fn"
    assert (tmp_path / "backend-events.v1.jsonl").exists()
    assert (tmp_path / "backend-trace.candidate.v1.json").exists()
    assert not (tmp_path / "backend-trace.v1.json").exists()


def test_run_backend_candidate_trace_one_pass_rejects_missing_exact_color_decisions(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    table_dir = tmp_path / "tables"
    table_dir.mkdir()
    _write_partial_backend_ig_table(table_dir)
    table_path = table_dir / "gc_125n.json"
    table = json.loads(table_path.read_text())
    table["backend_reader"]["partial_pcode_event_families"] = [
        "function_start",
        "backend_marker",
        "block",
        "pcode_instruction",
    ]
    table_path.write_text(json.dumps(table) + "\n")

    fixture_events = (
        REPO
        / "tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl"
    )

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kwargs: {"matched": True},
    )
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: table_dir)

    def fake_launch_dump(**kw):
        out = kw["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "backend-events.v1.jsonl").write_text(fixture_events.read_text())
        (out / "backend-onepass-candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": True,
                    "classes_seen": [
                        {
                            "class_id": 0,
                            "class_name": "gpr",
                            "nodes": 3,
                            "order_nodes": 2,
                            "exact_color_decisions": 1,
                        }
                    ],
                    "errors": [],
                    "warnings": [],
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(
        RuntimeError,
        match="one-pass candidate missing exact color decisions for gpr: 1/2",
    ):
        retro._run_backend_candidate_trace(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=REPO,
            one_pass=True,
        )

    assert not (tmp_path / "backend-trace.candidate.v1.json").exists()


def test_run_backend_candidate_trace_one_pass_rejects_summary_function_mismatch(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    table_dir = tmp_path / "tables"
    table_dir.mkdir()
    _write_partial_backend_ig_table(table_dir)
    table_path = table_dir / "gc_125n.json"
    table = json.loads(table_path.read_text())
    table["backend_reader"]["partial_pcode_event_families"] = [
        "function_start",
        "backend_marker",
        "block",
        "pcode_instruction",
    ]
    table_path.write_text(json.dumps(table) + "\n")

    fixture_events = (
        REPO
        / "tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl"
    )

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kwargs: {"matched": True},
    )
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: table_dir)

    def fake_launch_dump(**kw):
        out = kw["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "backend-events.v1.jsonl").write_text(fixture_events.read_text())
        (out / "backend-onepass-candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
                    "requested_function": "other_fn",
                    "requested_function_matched": True,
                    "classes_seen": [
                        {
                            "class_id": 0,
                            "class_name": "gpr",
                            "nodes": 3,
                            "order_nodes": 2,
                            "exact_color_decisions": 2,
                        }
                    ],
                    "errors": [],
                    "warnings": [],
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(
        RuntimeError,
        match="backend one-pass candidate requested_function mismatch: 'other_fn' != 'test_fn'",
    ):
        retro._run_backend_candidate_trace(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=REPO,
            one_pass=True,
        )

    assert not (tmp_path / "backend-trace.candidate.v1.json").exists()


def test_run_backend_candidate_trace_one_pass_rejects_event_function_mismatch(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    table_dir = tmp_path / "tables"
    table_dir.mkdir()
    _write_partial_backend_ig_table(table_dir)
    table_path = table_dir / "gc_125n.json"
    table = json.loads(table_path.read_text())
    table["backend_reader"]["partial_pcode_event_families"] = [
        "function_start",
        "backend_marker",
        "block",
        "pcode_instruction",
    ]
    table_path.write_text(json.dumps(table) + "\n")

    fixture_events = (
        REPO
        / "tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl"
    )

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kwargs: {"matched": True},
    )
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: table_dir)

    def fake_launch_dump(**kw):
        out = kw["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        events = [json.loads(line) for line in fixture_events.read_text().splitlines()]
        events[0]["name"] = "other_fn"
        events[0]["identity"] = {
            "requested": "other_fn",
            "canonical_name": "other_fn",
            "symbol_name": "other_fn",
            "source_name": "other_fn",
            "aliases": [],
            "source_file": "src/melee/test/unit.c",
        }
        (out / "backend-events.v1.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n"
        )
        (out / "backend-onepass-candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": True,
                    "classes_seen": [
                        {
                            "class_id": 0,
                            "class_name": "gpr",
                            "nodes": 3,
                            "order_nodes": 2,
                            "exact_color_decisions": 2,
                        }
                    ],
                    "errors": [],
                    "warnings": [],
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(
        RuntimeError,
        match="backend one-pass candidate event function_start mismatch: 'other_fn' != 'test_fn'",
    ):
        retro._run_backend_candidate_trace(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=REPO,
            one_pass=True,
        )

    assert not (tmp_path / "backend-trace.candidate.v1.json").exists()


def test_launch_backend_ig_snapshot_uses_partial_gate_and_hook(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    calls = []

    def fake_launch_dump(**kw):
        calls.append(kw)
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_ig_snapshot_events()
        )
        (out_dir / "backend-colorgraph-trace.json").write_text(
            json.dumps(_valid_colorgraph_trace_payload()) + "\n"
        )
        (out_dir / "backend-colorgraph-decisions.v1.jsonl").write_text(
            _valid_colorgraph_decision_events()
        )
        (out_dir / "launch.log").write_text("diagnostic log should be removed on success\n")
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    summary_path, events_path = retro._launch_backend_ig_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )

    assert summary_path == tmp_path / "backend-ig-snapshot.json"
    assert events_path == tmp_path / "backend-ig-snapshot-events.v1.jsonl"
    assert calls
    assert calls[0]["phases"] == "backend"
    assert calls[0]["compiler"] == "1.2.5n"
    assert calls[0]["gdb_py"].endswith("backend_ig_snapshot_hook.py")
    assert not (tmp_path / "backend-trace.v1.json").exists()
    assert not (tmp_path / "launch.log").exists()


def test_launch_backend_ig_snapshot_rejects_colorgraph_trace_errors(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_ig_snapshot_events()
        )
        payload = _valid_colorgraph_trace_payload()
        payload["errors"] = [{"id": "gpr-i0", "error": "bad raw decision"}]
        (out_dir / "backend-colorgraph-trace.json").write_text(
            json.dumps(payload) + "\n"
        )
        (out_dir / "backend-colorgraph-decisions.v1.jsonl").write_text(
            _valid_colorgraph_decision_events()
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend colorgraph trace recorded 1 error(s)" in str(excinfo.value)


def test_launch_backend_ig_snapshot_requires_internal_colorgraph_pcs(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    table = json.loads((tmp_path / "gc_125n.json").read_text())
    table["entries"].pop("colorgraph_select_start")
    (tmp_path / "gc_125n.json").write_text(json.dumps(table) + "\n")
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_launch_dump",
        lambda **_kw: (_ for _ in ()).throw(
            AssertionError("launcher should not run without internal colorgraph PCs")
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend IG snapshot requires internal colorgraph PCs" in str(excinfo.value)
    assert "missing colorgraph_select_start" in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_malformed_events(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
            '{"event":"regclass"\n'
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend IG snapshot events wrote invalid JSON on line 2" in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_wrong_function_events(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_ig_snapshot_events("other_fn")
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend IG snapshot events function_start mismatch" in str(excinfo.value)
    assert "'other_fn' != 'test_fn'" in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_duplicate_regclass_events(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        duplicate = json.dumps(
            {
                "event": "regclass",
                "class_name": "gpr",
                "class_id": 0,
                "registers": {},
            }
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_ig_snapshot_events() + duplicate + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend IG snapshot events duplicate regclass class_id 0" in str(excinfo.value)


def test_launch_backend_ig_snapshot_requires_order_events(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _ig_snapshot_events_without_orders()
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    message = str(excinfo.value)
    assert "backend IG snapshot events missing required event families" in message
    assert "select_order" in message
    assert "simplify_order" in message


def test_launch_backend_ig_snapshot_rejects_order_before_regclass(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        premature = json.dumps(
            {
                "event": "simplify_order",
                "class_name": "gpr",
                "class_id": 0,
                "order": [0],
                "source_stage": "colorgraph_head_after_simplifygraph",
                "provenance": "colorgraph_head",
            }
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
            + premature
            + "\n"
            + _valid_ig_snapshot_events()
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "simplify_order references class_id 0 before regclass" in str(excinfo.value)


@pytest.mark.parametrize(
    ("event_kind", "events_factory"),
    [
        ("node", _valid_ig_snapshot_events),
        ("edge", _valid_ig_snapshot_events),
        ("coalesce_mapping", _valid_alias_mapping_ig_snapshot_events),
        ("coalesce_mapping_empty", _valid_ig_snapshot_events),
        ("simplify_order", _valid_ig_snapshot_events),
        ("select_order", _valid_ig_snapshot_events),
        ("color_decision", _valid_ig_snapshot_events_with_color_decision),
    ],
)
def test_launch_backend_ig_snapshot_rejects_class_name_mismatch_for_allocator_events(
    monkeypatch, tmp_path, event_kind: str, events_factory
):
    lines = []
    replaced = False
    for raw_line in events_factory().splitlines():
        event = json.loads(raw_line)
        if event.get("event") == event_kind and not replaced:
            event["class_name"] = "fpr"
            replaced = True
        lines.append(json.dumps(event))
    assert replaced

    with pytest.raises(RuntimeError) as excinfo:
        _run_ig_snapshot_with_events(monkeypatch, tmp_path, "\n".join(lines) + "\n")

    message = str(excinfo.value)
    assert "class_id 0 registered as 'gpr'" in message
    assert f"{event_kind} reports class_name 'fpr'" in message


def test_launch_backend_ig_snapshot_accepts_partial_color_decisions(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_ig_snapshot_events_with_color_decision()
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    retro._launch_backend_ig_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )


def test_validate_backend_colorgraph_decision_events_accepts_internal_decisions(tmp_path):
    import src.cli.debug.retro as retro

    path = tmp_path / "backend-colorgraph-decisions.v1.jsonl"
    path.write_text(_valid_colorgraph_decision_events())

    retro._validate_backend_colorgraph_decision_events(path, fn="test_fn")


def test_validate_backend_colorgraph_trace_payload_rejects_hook_errors(tmp_path):
    import src.cli.debug.retro as retro

    path = tmp_path / "backend-colorgraph-trace.json"
    payload = _valid_colorgraph_trace_payload()
    payload["errors"] = [{"id": "gpr-i0", "error": "bad raw decision"}]
    path.write_text(json.dumps(payload) + "\n")

    with pytest.raises(RuntimeError) as excinfo:
        retro._validate_backend_colorgraph_trace_payload(path, fn="test_fn")

    assert "backend colorgraph trace recorded 1 error(s)" in str(excinfo.value)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda event: event.update({"confidence": "observed-partial"}),
            "colorgraph decision confidence must be observed-internal",
        ),
        (
            lambda event: event.update({"provenance": "retail-colorgraph-return"}),
            "colorgraph decision provenance must be retail-colorgraph-internal",
        ),
        (
            lambda event: event.update({"assigned_phys": 31}),
            "colorgraph decision candidate_phys_ordered must include assigned_phys 31",
        ),
        (
            lambda event: event["node_state_before_select"].pop("precolored"),
            "colorgraph decision node_state_before_select missing precolored",
        ),
    ],
)
def test_validate_backend_colorgraph_decision_events_rejects_malformed_internal_decisions(
    tmp_path, mutate, expected: str
):
    import src.cli.debug.retro as retro

    event = _valid_internal_colorgraph_decision_event()
    mutate(event)
    path = tmp_path / "backend-colorgraph-decisions.v1.jsonl"
    path.write_text(
        json.dumps({"event": "function_start", "name": "test_fn"})
        + "\n"
        + json.dumps(event)
        + "\n"
    )

    with pytest.raises(RuntimeError) as excinfo:
        retro._validate_backend_colorgraph_decision_events(path, fn="test_fn")

    assert expected in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_decision_before_regclass(monkeypatch, tmp_path):
    premature = json.dumps(_valid_color_decision_event())
    events = (
        '{"event":"function_start","name":"test_fn"}\n'
        + premature
        + "\n"
        + _valid_ig_snapshot_events()
    )

    with pytest.raises(RuntimeError) as excinfo:
        _run_ig_snapshot_with_events(monkeypatch, tmp_path, events)

    assert "color_decision references class_id 0 before regclass" in str(excinfo.value)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda event: event.update({"id": "gpr-c0"}),
            "backend IG snapshot events duplicate color_decision id gpr-c0 for class_id 0",
        ),
        (
            lambda event: event.update({"ig_id": 99}),
            "color_decision references missing node 99 in class_id 0",
        ),
        (
            lambda event: event["blocked_candidates"][0].update({"holder_ig_id": 99}),
            "color_decision blocked candidate references missing holder node 99 in class_id 0",
        ),
        (
            lambda event: event.pop("source_stage"),
            "color_decision missing source_stage",
        ),
        (
            lambda event: event.update({"provenance": "colorgraph-replay"}),
            "color_decision provenance must be retail-colorgraph-return",
        ),
        (
            lambda event: event.update({"confidence": "observed"}),
            "color_decision confidence must be observed-partial",
        ),
        (
            lambda event: event.update({"chosen_source": "nonvolatile_dispense"}),
            "color_decision chosen_source must be observed-retail-assignment",
        ),
        (
            lambda event: event.update({"available_phys_ordered": [31]}),
            "color_decision available_phys_ordered must be empty for partial observed facts",
        ),
        (
            lambda event: event.update({"tie_rule": "top_down_nonvolatile_dispense"}),
            "color_decision tie_rule must be unavailable-retail-post-colorgraph",
        ),
        (
            lambda event: event.update({"decision_rule": "lowest_available"}),
            "color_decision decision_rule must be retail-post-colorgraph-observed-assignment",
        ),
        (
            lambda event: event.update({"node_state_before_select": {"precolored": False}}),
            "color_decision node_state_before_select must mark retail-post-colorgraph-only",
        ),
    ],
)
def test_launch_backend_ig_snapshot_rejects_invalid_partial_color_decision(
    monkeypatch, tmp_path, mutate, expected: str
):
    second = _valid_color_decision_event()
    second["id"] = "gpr-c1"
    second["ig_id"] = 0
    mutate(second)
    events = (
        _valid_ig_snapshot_events_with_color_decision()
        + json.dumps(second)
        + "\n"
    )

    with pytest.raises(RuntimeError) as excinfo:
        _run_ig_snapshot_with_events(monkeypatch, tmp_path, events)

    assert expected in str(excinfo.value)


def test_launch_backend_ig_snapshot_accepts_alias_mapping_events(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_alias_mapping_ig_snapshot_events()
        )
        (out_dir / "launch.log").write_text("diagnostic log should be removed on success\n")
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    retro._launch_backend_ig_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )

    assert not (tmp_path / "launch.log").exists()


def test_launch_backend_ig_snapshot_rejects_self_alias_mapping(monkeypatch, tmp_path):
    events = _valid_alias_mapping_ig_snapshot_events().replace('"alias": 1', '"alias": 0', 1)

    with pytest.raises(RuntimeError) as excinfo:
        _run_ig_snapshot_with_events(monkeypatch, tmp_path, events)

    assert "coalesce_mapping self-map alias 0 root 0 in class_id 0" in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_mapping_and_empty_marker(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    empty_marker = json.dumps(
        {
            "event": "coalesce_mapping_empty",
            "class_name": "gpr",
            "class_id": 0,
            "confidence": "observed",
            "provenance": "retail_ignode_no_coalesced_aliases",
            "source_stage": "colorgraph",
        }
    )

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_alias_mapping_ig_snapshot_events() + empty_marker + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert (
        "backend IG snapshot events class_id 0 emitted both coalesce_mapping "
        "and coalesce_mapping_empty"
    ) in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_mapping_before_regclass(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        premature = json.dumps(
            {
                "event": "coalesce_mapping",
                "class_name": "gpr",
                "class_id": 0,
                "alias": 1,
                "root": 0,
                "root_phys": None,
                "confidence": "observed",
                "provenance": "retail_ignode_coalesced_away",
                "source_stage": "colorgraph",
            }
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
            + premature
            + "\n"
            + _valid_ig_snapshot_events()
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "coalesce_mapping references class_id 0 before regclass" in str(excinfo.value)


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        ('"alias": 99', "coalesce_mapping references missing alias node 99 in class_id 0"),
        ('"root": 99', "coalesce_mapping references missing root node 99 in class_id 0"),
    ],
)
def test_launch_backend_ig_snapshot_rejects_mapping_for_missing_node(
    monkeypatch, tmp_path, replacement: str, expected: str
):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        events = _valid_alias_mapping_ig_snapshot_events()
        if replacement.startswith('"alias"'):
            events = events.replace('"alias": 1', replacement, 1)
        else:
            events = events.replace('"root": 0', replacement, 1)
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(events)
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert expected in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_duplicate_alias_mapping(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    duplicate = json.dumps(
        {
            "event": "coalesce_mapping",
            "class_name": "gpr",
            "class_id": 0,
            "alias": 1,
            "root": 0,
            "root_phys": None,
            "confidence": "observed",
            "provenance": "retail_ignode_coalesced_away",
            "source_stage": "colorgraph",
        }
    )

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_alias_mapping_ig_snapshot_events() + duplicate + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend IG snapshot events duplicate coalesce_mapping alias 1 for class_id 0" in str(
        excinfo.value
    )


def test_launch_backend_ig_snapshot_rejects_order_for_missing_node(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_ig_snapshot_events().replace('"order": [1, 0]', '"order": [1, 2]', 1)
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "simplify_order references missing node 2 in class_id 0" in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_duplicate_order_event(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    duplicate = json.dumps(
        {
            "event": "select_order",
            "class_name": "gpr",
            "class_id": 0,
            "order": [1, 0],
            "source_stage": "colorgraph_head_after_simplifygraph",
            "provenance": "colorgraph_head",
        }
    )

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_ig_snapshot_events() + duplicate + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend IG snapshot events duplicate select_order for class_id 0" in str(
        excinfo.value
    )


def test_launch_backend_ig_snapshot_accepts_edge_free_graph(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_edge_free_ig_snapshot_events()
        )
        (out_dir / "launch.log").write_text("diagnostic log should be removed on success\n")
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    retro._launch_backend_ig_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )

    assert not (tmp_path / "launch.log").exists()


def test_launch_backend_ig_snapshot_accepts_empty_order_events(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_empty_order_ig_snapshot_events()
        )
        (out_dir / "launch.log").write_text("diagnostic log should be removed on success\n")
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    retro._launch_backend_ig_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )

    assert not (tmp_path / "launch.log").exists()


def test_launch_backend_ig_snapshot_rejects_edge_to_missing_node(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            _valid_edge_free_ig_snapshot_events()
            + json.dumps(
                {
                    "event": "edge",
                    "class_name": "gpr",
                    "class_id": 0,
                    "a": 0,
                    "b": 99,
                }
            )
            + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "edge references missing node 99 in class_id 0" in str(excinfo.value)


def test_launch_backend_ig_snapshot_rejects_missing_required_event_families(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_ig_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-ig-snapshot.json").write_text(
            json.dumps(_valid_ig_snapshot_payload()) + "\n"
        )
        lines = _valid_ig_snapshot_events().splitlines()
        (out_dir / "backend-ig-snapshot-events.v1.jsonl").write_text(
            "\n".join([lines[0], lines[2]]) + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    message = str(excinfo.value)
    assert "backend IG snapshot events missing required event families" in message
    assert "node" in message


def test_launch_backend_ig_snapshot_rejects_full_trace_gate_only_table(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup, struct_map

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
        "backend_reader": {
            "complete": False,
            "event_families": ["function_start", "backend_marker"],
        },
    }
    (tmp_path / "gc_125n.json").write_text(json.dumps(table) + "\n")
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_launch_dump",
        lambda **_kw: (_ for _ in ()).throw(
            AssertionError("partial IG launcher should not run without partial gate")
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_ig_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend IG snapshot requires internal colorgraph PCs and partial reader" in str(excinfo.value)
    assert "backend_reader.partial_event_families must be list" in str(excinfo.value)


def test_launch_backend_pcode_snapshot_uses_partial_gate_and_hook(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_pcode_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    calls = []

    def fake_launch_dump(**kw):
        calls.append(kw)
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-pcode-snapshot.json").write_text(
            json.dumps(_valid_pcode_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-pcode-snapshot-events.v1.jsonl").write_text(
            _valid_pcode_snapshot_events()
        )
        (out_dir / "launch.log").write_text("diagnostic log should be removed on success\n")
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    summary_path, events_path = retro._launch_backend_pcode_snapshot(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )

    assert summary_path == tmp_path / "backend-pcode-snapshot.json"
    assert events_path == tmp_path / "backend-pcode-snapshot-events.v1.jsonl"
    assert calls
    assert calls[0]["phases"] == "backend"
    assert calls[0]["compiler"] == "1.2.5n"
    assert calls[0]["gdb_py"].endswith("backend_pcode_snapshot_hook.py")
    assert not (tmp_path / "backend-trace.v1.json").exists()
    assert not (tmp_path / "launch.log").exists()


def test_launch_backend_pcode_snapshot_rejects_wrong_function_events(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_pcode_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-pcode-snapshot.json").write_text(
            json.dumps(_valid_pcode_snapshot_payload()) + "\n"
        )
        (out_dir / "backend-pcode-snapshot-events.v1.jsonl").write_text(
            _valid_pcode_snapshot_events("other_fn")
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_pcode_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend PCode snapshot events function_start mismatch" in str(excinfo.value)


def test_launch_backend_pcode_snapshot_rejects_pcode_before_block(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_partial_backend_pcode_table(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)

    def fake_launch_dump(**kw):
        out_dir = kw["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "backend-pcode-snapshot.json").write_text(
            json.dumps(_valid_pcode_snapshot_payload()) + "\n"
        )
        lines = _valid_pcode_snapshot_events().splitlines()
        (out_dir / "backend-pcode-snapshot-events.v1.jsonl").write_text(
            "\n".join([lines[0], lines[1], lines[3]]) + "\n"
        )
        return retro.DumpOutcome(exit_code=0, produced=["hook"], missing=[])

    monkeypatch.setattr(retro, "_launch_dump", fake_launch_dump)

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_pcode_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    message = str(excinfo.value)
    assert "pcode_instruction references missing block 'B0'" in message
    assert "missing required event families: block" in message


def test_launch_backend_pcode_snapshot_rejects_full_trace_gate_only_table(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro

    from tools.mwcc_retro import setup as retro_setup, struct_map

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
        "backend_reader": {
            "complete": False,
            "event_families": ["function_start", "backend_marker"],
        },
    }
    (tmp_path / "gc_125n.json").write_text(json.dumps(table) + "\n")
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_launch_dump",
        lambda **_kw: (_ for _ in ()).throw(
            AssertionError("partial PCode launcher should not run without partial gate")
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_pcode_snapshot(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert "backend PCode snapshot requires partial reader" in str(excinfo.value)
    assert "backend_reader.partial_pcode_event_families must be list" in str(excinfo.value)


def test_run_backend_trace_reports_failed_parity_detail(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **kw: {
            "matched": False,
            "reference": {
                "path": "/tmp/reference.o",
                "size": 12,
                "sha256": "a" * 64,
            },
            "retro": {
                "path": "/tmp/retro.o",
                "size": 13,
                "sha256": "b" * 64,
            },
        },
    )
    with pytest.raises(RuntimeError) as excinfo:
        retro._run_backend_trace(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            verify_debug=False,
            melee_root=Path.cwd(),
        )
    message = str(excinfo.value)
    assert "backend object parity mismatch" in message
    assert "/tmp/reference.o" in message
    assert "size=12" in message
    assert "sha256=" + ("a" * 64) in message
    assert "/tmp/retro.o" in message
    assert "size=13" in message
    assert "sha256=" + ("b" * 64) in message


def test_run_backend_trace_wraps_partial_event_stream(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    events_path = tmp_path / "backend-events.v1.jsonl"
    events_path.write_text(
        '{"event":"function_start","name":"test_fn"}\n'
        '{"event":"backend_marker","name":"codegen_start"}\n'
    )
    monkeypatch.setattr(
        retro,
        "_run_object_parity_for_backend",
        lambda **_kw: {"matched": True},
    )
    monkeypatch.setattr(
        retro,
        "_launch_backend_events",
        lambda **_kw: events_path,
    )
    _stub_backend_mwcc_command(monkeypatch, retro)

    with pytest.raises(RuntimeError) as excinfo:
        retro._run_backend_trace(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            verify_debug=False,
            melee_root=Path.cwd(),
        )

    message = str(excinfo.value)
    assert "backend event normalization failed" in message
    assert "backend trace has no allocator classes" in message


def test_run_object_parity_wraps_reference_compile_failure(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    monkeypatch.setattr(
        retro_setup,
        "ensure_for_root",
        lambda *_args, **_kwargs: SimpleNamespace(
            retrowin32_bin=tmp_path / "retrowin32"
        ),
    )
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda *_args, **_kwargs: "build/compilers/GC/1.2.5n/mwcceppc.exe -c src.c -o old.o",
    )

    def fail_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(
            7,
            cmd,
            output=b"x" * 2000 + b"\nreference stdout tail",
            stderr=b"y" * 2000 + b"\nreference stderr tail",
        )

    monkeypatch.setattr(subprocess, "run", fail_run)

    with pytest.raises(RuntimeError) as excinfo:
        retro._run_object_parity_for_backend(
            src="src/melee/test/unit.c", melee_root=tmp_path
        )
    message = str(excinfo.value)
    assert "backend object parity reference compile failed" in message
    assert "exit code: 7" in message
    assert "mwcceppc.exe" in message
    assert "reference stdout tail" in message
    assert "reference stderr tail" in message


def test_launch_backend_events_writes_launch_log_on_nonzero(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_valid_backend_map(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        assert kwargs["env"]["RETRO_SOURCE"] == "src/melee/test/unit.c"
        assert kwargs["env"]["RETRO_FUNCTION"] == "test_fn"
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        return subprocess.CompletedProcess(cmd, 7, stdout="launcher stdout\n", stderr="launcher stderr\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher failed"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    launch_log = tmp_path / "launch.log"
    log_text = launch_log.read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert "mwcc_retro_debugger.py" in log_lines[0]
    assert "--phases backend" in log_lines[0]
    assert "--compiler 1.2.5n" in log_lines[0]
    assert "--gdb-py" in log_lines[0]
    assert "backend_onepass_trace_hook.py" in log_lines[0]
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: 7"
    assert "STDOUT:" in log_text
    assert "launcher stdout" in log_text
    assert "STDERR:" in log_text
    assert "launcher stderr" in log_text
    assert not (tmp_path / "backend-events.v1.jsonl").exists()


def test_launch_backend_events_uses_onepass_hook_and_validates_summary(monkeypatch, tmp_path):
    import subprocess

    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_valid_backend_map(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        assert "--gdb-py" in cmd
        hook = Path(cmd[cmd.index("--gdb-py") + 1])
        assert hook.name == "backend_onepass_trace_hook.py"
        assert kwargs["env"]["RETRO_SOURCE"] == "src/melee/test/unit.c"
        assert kwargs["env"]["RETRO_FUNCTION"] == "test_fn"
        (tmp_path / "backend-events.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
        )
        (tmp_path / "backend-onepass-candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": True,
                    "classes_seen": [
                        {
                            "class_id": 0,
                            "class_name": "gpr",
                            "nodes": 1,
                            "order_nodes": 0,
                            "exact_color_decisions": 0,
                        }
                    ],
                    "errors": [],
                    "warnings": [],
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    events = retro._launch_backend_events(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        melee_root=Path.cwd(),
    )

    assert events == tmp_path / "backend-events.v1.jsonl"
    log_text = (tmp_path / "launch.log").read_text()
    assert "--gdb-py" in log_text
    assert "backend_onepass_trace_hook.py" in log_text
    assert not (tmp_path / "backend-onepass-candidate.json").exists()
    summary = json.loads((tmp_path / "backend-onepass-summary.json").read_text())
    assert summary["schema_version"] == "mwcc-retro-backend-onepass-summary.v1"
    assert summary["source_sidecar"] == "backend-onepass-candidate.json"
    assert not any("candidate" in note.lower() for note in summary["notes"])


def test_launch_backend_events_uses_package_scripts_with_explicit_melee_root(
    monkeypatch, tmp_path
):
    import os
    import subprocess

    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    stale_root = tmp_path / "stale-worktree"
    (stale_root / "tools" / "mwcc_retro" / "tables").mkdir(parents=True)
    (stale_root / "tools" / "mwcc_retro" / "tables" / "gc_125n.json").write_text("{}\n")
    (stale_root / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py").write_text(
        "# stale launcher\n"
    )
    out_dir = tmp_path / "out"
    _write_valid_backend_map(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        launcher = Path(cmd[1])
        assert launcher == retro._PACKAGE_REPO / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"
        table = Path(cmd[cmd.index("--table") + 1])
        assert table == tmp_path / "gc_125n.json"
        hook = Path(cmd[cmd.index("--gdb-py") + 1])
        assert hook == retro._PACKAGE_REPO / "tools" / "mwcc_retro" / "backend_onepass_trace_hook.py"
        pythonpath = kwargs["env"].get("PYTHONPATH", "").split(os.pathsep)
        assert pythonpath[0] == str(retro._PACKAGE_REPO)
        assert kwargs["cwd"] == str(stale_root)
        (out_dir / "backend-events.v1.jsonl").write_text(
            '{"event":"function_start","name":"test_fn"}\n'
        )
        (out_dir / "backend-onepass-candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
                    "requested_function": "test_fn",
                    "requested_function_matched": True,
                    "classes_seen": [
                        {
                            "class_id": 0,
                            "class_name": "gpr",
                            "nodes": 1,
                            "order_nodes": 0,
                            "exact_color_decisions": 0,
                        }
                    ],
                    "errors": [],
                    "warnings": [],
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    events = retro._launch_backend_events(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=out_dir,
        melee_root=stale_root,
    )

    assert events == out_dir / "backend-events.v1.jsonl"


def test_launch_backend_events_requires_complete_reader_gate(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup, struct_map

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
        "backend_reader": {
            "complete": False,
            "event_families": ["function_start"],
        },
    }
    (tmp_path / "gc_125n.json").write_text(json.dumps(table) + "\n")
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("launcher should not run without reader gate")
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    message = str(excinfo.value)
    assert "backend event launcher requires complete backend reader" in message
    assert "backend_reader.complete is not true" in message


def test_launch_dump_treats_abort_as_failure_even_with_stale_backend_text(
    monkeypatch, tmp_path
):
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"
        cadmic_script = tmp_path / "cadmic" / "cadmic.py"

    (tmp_path / "backend-stale.txt").write_text("stale backend\n")
    (tmp_path / "regalloc-stale.txt").write_text("stale regalloc\n")
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )
    monkeypatch.setattr(
        retro,
        "_run_with_process_group_timeout",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd,
            0,
            stdout="[retro] ABORT: backend reader capability gate failed\n",
            stderr="",
        ),
    )

    outcome = retro._launch_dump(
        src="src/melee/test/unit.c",
        fn="test_fn",
        phases="backend",
        compiler="1.2.5n",
        out_dir=tmp_path,
        table=tmp_path / "gc_125n.json",
        melee_root=Path.cwd(),
    )

    assert outcome.exit_code == 5
    assert outcome.produced == []
    assert outcome.missing == ["backend"]
    assert not (tmp_path / "backend-stale.txt").exists()
    assert not (tmp_path / "regalloc-stale.txt").exists()
    assert "[retro] ABORT: backend reader capability gate failed" in (
        tmp_path / "launch.log"
    ).read_text()


def test_launch_backend_events_deletes_partial_events_on_abort(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_valid_backend_map(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        return subprocess.CompletedProcess(cmd, 0, stdout="[retro] ABORT: missing colorgraph\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher aborted"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert not (tmp_path / "backend-events.v1.jsonl").exists()
    log_text = (tmp_path / "launch.log").read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: 0"
    assert "[retro] ABORT: missing colorgraph" in log_text


def test_launch_backend_events_writes_launch_log_on_timeout(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_valid_backend_map(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        raise subprocess.TimeoutExpired(
            cmd,
            timeout=600,
            output="timeout stdout\n",
            stderr="timeout stderr\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher timed out"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    log_text = (tmp_path / "launch.log").read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: timeout after 600s"
    assert "timeout stdout" in log_text
    assert "timeout stderr" in log_text
    assert not (tmp_path / "backend-events.v1.jsonl").exists()


def test_launch_backend_events_writes_launch_log_on_oserror(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    _write_valid_backend_map(tmp_path)
    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        raise OSError("spawn failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher failed"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    log_text = (tmp_path / "launch.log").read_text()
    log_lines = log_text.splitlines()
    assert log_lines[0].startswith("COMMAND: ")
    assert log_lines[1] == "RETRO_SOURCE: src/melee/test/unit.c"
    assert log_lines[2] == "RETRO_FUNCTION: test_fn"
    assert log_lines[3] == "EXIT: OSError: spawn failed"
    assert not (tmp_path / "backend-events.v1.jsonl").exists()
