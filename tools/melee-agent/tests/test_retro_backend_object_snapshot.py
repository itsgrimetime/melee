import inspect
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import (  # noqa: E402
    backend_object_snapshot,
    backend_onepass_trace_hook,
)

OBJECT_OFFSETS = backend_object_snapshot.ObjObjectOffsets(0x0A, 0x0E, 0x02, 0x2A)


def test_snapshot_objobject_reads_validated_offsets_once_and_is_immutable() -> None:
    u32 = {0x120A: 0x2200, 0x120E: 0x3200}
    s32 = {0x3202: 4}
    reads: list[tuple[str, int]] = []

    def read_u32(addr: int) -> int:
        reads.append(("u32", addr))
        return u32[addr]

    def read_s32(addr: int) -> int:
        reads.append(("s32", addr))
        return s32[addr]

    snapshot = backend_object_snapshot.snapshot_objobject(
        ptr=0x1200,
        stage="colorgraph_return",
        lifecycle_sequence=8,
        generation=3,
        read_u32=read_u32,
        read_s32=read_s32,
        offsets=OBJECT_OFFSETS,
    )

    assert dict(snapshot) == {
        "stage": "colorgraph_return",
        "runtime_address": 0x1200,
        "allocation_generation": 3,
        "lifecycle_sequence_at_capture": 8,
        "name_record_pointer": 0x2200,
        "type_pointer": 0x3200,
        "type_size": 4,
        "readable": True,
    }
    assert reads == [("u32", 0x120A), ("u32", 0x120E), ("s32", 0x3202)]
    with pytest.raises(TypeError):
        snapshot["type_size"] = 8  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        OBJECT_OFFSETS.type_size = 4  # type: ignore[misc]


def test_snapshot_objobject_returns_controlled_unreadable_record() -> None:
    def read_u32(addr: int) -> int:
        if addr == 0x120A:
            return 0x2200
        raise OSError("unmapped")

    snapshot = backend_object_snapshot.snapshot_objobject(
        ptr=0x1200,
        stage="final_scheduler",
        lifecycle_sequence=-1,
        generation=1,
        read_u32=read_u32,
        read_s32=lambda _addr: 4,
        offsets=OBJECT_OFFSETS,
    )

    assert dict(snapshot) == {
        "stage": "final_scheduler",
        "runtime_address": 0x1200,
        "allocation_generation": 1,
        "lifecycle_sequence_at_capture": -1,
        "name_record_pointer": 0x2200,
        "type_pointer": None,
        "type_size": 0,
        "readable": False,
    }


def test_snapshot_objobject_never_leaks_malformed_type_size() -> None:
    snapshot = backend_object_snapshot.snapshot_objobject(
        ptr=0x1200,
        stage="colorgraph_return",
        lifecycle_sequence=0,
        generation=1,
        read_u32=lambda addr: {0x120A: 0x2200, 0x120E: 0x3200}[addr],
        read_s32=lambda _addr: -4,
        offsets=OBJECT_OFFSETS,
    )

    assert snapshot["readable"] is False
    assert snapshot["type_size"] == 0


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"ptr": 0}, "ptr must be a positive integer"),
        ({"ptr": True}, "ptr must be a positive integer"),
        ({"generation": None}, "generation must be a positive integer"),
        ({"generation": 0}, "generation must be a positive integer"),
        ({"lifecycle_sequence": -2}, "lifecycle_sequence must be at least -1"),
        ({"stage": "allocator"}, "unsupported ObjObject snapshot stage"),
    ],
)
def test_snapshot_objobject_rejects_malformed_identity_without_reading(
    overrides: dict[str, object], match: str
) -> None:
    reads: list[int] = []
    kwargs = {
        "ptr": 0x1200,
        "stage": "colorgraph_return",
        "lifecycle_sequence": 0,
        "generation": 1,
        "read_u32": lambda addr: reads.append(addr) or 0,
        "read_s32": lambda addr: reads.append(addr) or 0,
        "offsets": OBJECT_OFFSETS,
    }
    kwargs.update(overrides)

    with pytest.raises(ValueError, match=match):
        backend_object_snapshot.snapshot_objobject(**kwargs)  # type: ignore[arg-type]
    assert reads == []


def test_snapshot_objobject_contains_no_compiler_accessor_or_callback() -> None:
    source = inspect.getsource(backend_object_snapshot)

    assert "0x4C1720" not in source
    assert "cad." not in source
    assert "gdb." not in source


def test_onepass_object_capture_has_no_layout_or_va_fallback_literals() -> None:
    source = inspect.getsource(backend_onepass_trace_hook)

    for literal in ("0x58806C", "0x587FB8", "0x57FEC0", "0x5880CC", "0x58712C"):
        assert literal not in source
    assert 'entry_va("arguments",' not in source
    assert 'entry_va("locals",' not in source
    assert 'entry_va("temps",' not in source


def test_hook_samples_lifecycle_sequence_once_from_stopped_process() -> None:
    class Lifecycle:
        def __init__(self) -> None:
            self.calls = 0

        def sequence_at_stop(self) -> int:
            self.calls += 1
            return 9

        def generation(self, kind: str, ptr: int) -> int | None:
            return 2 if (kind, ptr) == ("objobject", 0x1200) else None

    lifecycle = Lifecycle()

    inputs = backend_onepass_trace_hook._stopped_lifecycle_inputs(lifecycle)

    assert inputs["lifecycle_sequence"] == 9
    assert inputs["generation_for"]("objobject", 0x1200) == 2
    assert lifecycle.calls == 1


@pytest.mark.parametrize("sequence", [None, True, -2])
def test_hook_rejects_missing_or_malformed_stopped_generation_sequence(sequence) -> None:
    class Lifecycle:
        def sequence_at_stop(self):
            return sequence

        def generation(self, _kind: str, _ptr: int) -> int:
            return 1

    with pytest.raises(ValueError, match="lifecycle sequence"):
        backend_onepass_trace_hook._stopped_lifecycle_inputs(Lifecycle())


def test_hook_canonicalizes_object_events_without_promoting_capability() -> None:
    snapshot = {
        "event": "objobject_snapshot",
        "stage": "colorgraph_return",
        "runtime_address": 0x1200,
        "allocation_generation": 1,
        "lifecycle_sequence_at_capture": 0,
        "name_record_pointer": 0x2200,
        "type_pointer": 0x3200,
        "type_size": 4,
        "readable": True,
    }
    binding_1 = {
        "event": "object_virtual_binding",
        "objobject_ptr": 0x1200,
        "allocation_generation": 1,
        "class_id": 0,
        "virtual_kind": "r",
        "virtual": 2,
        "ig_id": 2,
        "ignode_runtime_address": 0x2020,
    }
    binding_0 = {**binding_1, "virtual": 1, "ig_id": 1, "ignode_runtime_address": 0x2010}

    normalized = backend_onepass_trace_hook._canonical_object_events([binding_1, snapshot, binding_0, dict(snapshot)])

    assert [row["event"] for row in normalized] == [
        "objobject_snapshot",
        "object_virtual_binding",
        "object_virtual_binding",
    ]
    assert [row.get("virtual") for row in normalized[1:]] == [1, 2]
    assert backend_onepass_trace_hook._object_capture_status(
        normalized, errors=["reader failed"], cap_reached=True
    ) == {
        "status": "partial",
        "events_seen": 3,
        "cap_reached": True,
        "errors": ["reader failed"],
        "capabilities": [],
    }

    with pytest.raises(ValueError, match="duplicate object capture event"):
        backend_onepass_trace_hook._canonical_object_events([binding_0, dict(binding_0)])


def test_hook_keeps_later_identical_cross_class_snapshot_and_resets_between_runs() -> None:
    first = {
        "event": "objobject_snapshot",
        "stage": "colorgraph_return",
        "runtime_address": 0x1200,
        "allocation_generation": 1,
        "lifecycle_sequence_at_capture": 3,
        "name_record_pointer": 0x2200,
        "type_pointer": 0x3200,
        "type_size": 4,
        "readable": True,
    }
    later = {**first, "lifecycle_sequence_at_capture": 8}

    assert backend_onepass_trace_hook._canonical_object_events([later, first]) == [later]
    assert backend_onepass_trace_hook._canonical_object_events([first]) == [first]
    with pytest.raises(ValueError, match="conflicting ObjObject snapshots"):
        backend_onepass_trace_hook._canonical_object_events([first, {**later, "type_size": 8}])

    state = {"object_events": [later]}
    backend_onepass_trace_hook._reset_object_capture_state(state)
    state["object_events"].append(first)
    assert backend_onepass_trace_hook._canonical_object_events(state["object_events"]) == [first]


def test_hook_retains_partial_exception_facts_and_marks_capture_partial() -> None:
    fact = {
        "event": "object_virtual_binding",
        "objobject_ptr": 0x1200,
        "allocation_generation": 1,
        "class_id": 0,
        "virtual_kind": "r",
        "virtual": 1,
        "ig_id": 1,
        "ignode_runtime_address": 0x2010,
    }
    error = backend_object_snapshot.PartialObjectCaptureError("late read", [fact])
    state = {"object_events": [], "errors": []}

    backend_onepass_trace_hook._retain_partial_object_facts(state, error, stage="colorgraph_return")

    assert state["object_events"] == [fact]
    assert state["errors"] == [
        {
            "stage": "colorgraph_return",
            "error": "late read",
            "object_capture_partial": True,
        }
    ]


def test_atomic_sidecar_is_deterministic_and_marks_partial(tmp_path) -> None:
    path = tmp_path / "backend-object-events.v1.json"
    events = [
        {
            "event": "object_virtual_binding",
            "objobject_ptr": 0x1200,
            "allocation_generation": 1,
            "class_id": 0,
            "virtual_kind": "r",
            "virtual": 1,
            "ig_id": 1,
            "ignode_runtime_address": 0x2010,
        }
    ]
    status = backend_onepass_trace_hook._object_capture_status(events, errors=["late read"], cap_reached=False)

    backend_onepass_trace_hook._publish_object_sidecar(path, events, status)
    first = path.read_bytes()
    backend_onepass_trace_hook._publish_object_sidecar(path, events, status)

    assert path.read_bytes() == first
    assert json.loads(first) == {
        "schema_version": "mwcc-retro-object-events.v1",
        "capture_status": status,
        "events": events,
        "publication_complete": True,
    }


def test_atomic_sidecar_replace_failure_preserves_previous_valid_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "backend-object-events.v1.json"
    path.write_text('{"previous":"valid"}\n')
    previous = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(backend_onepass_trace_hook.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        backend_onepass_trace_hook._publish_object_sidecar(
            path,
            [],
            backend_onepass_trace_hook._object_capture_status([], errors=["partial"], cap_reached=False),
        )

    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_sidecar_write_failure_preserves_previous_valid_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "backend-object-events.v1.json"
    path.write_text('{"previous":"valid"}\n')
    previous = path.read_bytes()
    temporary = tmp_path / ".backend-object-events.v1.json.failed.tmp"

    class FailingStream:
        name = str(temporary)

        def __enter__(self):
            temporary.write_bytes(b"partial")
            return self

        def __exit__(self, *_args):
            return False

        def write(self, _data):
            raise OSError("write failed")

    monkeypatch.setattr(
        backend_onepass_trace_hook.tempfile,
        "NamedTemporaryFile",
        lambda **_kwargs: FailingStream(),
    )
    with pytest.raises(OSError, match="write failed"):
        backend_onepass_trace_hook._publish_object_sidecar(
            path,
            [],
            backend_onepass_trace_hook._object_capture_status([], errors=["partial"], cap_reached=False),
        )

    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]
