"""GDB hook for partial GC/1.2.5n backend PCode/block snapshots.

This hook emits only function/backend markers plus block/PCode events into a
dedicated JSONL file. It is not a full backend trace reader.
"""


def intervene(ctx):
    import json
    import os

    from tools.mwcc_retro import (
        backend_pcode_snapshot,
        backend_runtime_instrumentation,
        struct_map,
    )

    gdb = ctx.gdb
    cad = ctx.cad
    entries = ctx.table.get("entries", {})
    out_events = ctx.out_dir + "/backend-pcode-snapshot-events.v1.jsonl"
    out_summary = ctx.out_dir + "/backend-pcode-snapshot.json"
    source_file = os.environ.get("RETRO_SOURCE", "")
    requested = os.environ.get("RETRO_FUNCTION", ctx.fn)
    runtime_bundle = backend_runtime_instrumentation.install_runtime_instrumentation(
        ctx
    )
    raw_reader = (
        ctx.read
        if not struct_map.validate_pcode_arg_capture_capability(ctx.table)
        else None
    )

    def entry_va(key):
        entry = entries.get(key)
        return entry.get("va") if isinstance(entry, dict) else None

    def read_s16(va):
        return int.from_bytes(ctx.read(va, 2), "little", signed=True)

    def read_u32(va):
        return ctx.u32(va)

    def append_event(event):
        with open(out_events, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    def current_function_name():
        sp = int(gdb.parse_and_eval("$esp"))
        obj_addr = read_u32(sp + 8)
        try:
            obj = cad.MwccObject.load(obj_addr, load_linkname=False)
            return {"addr": obj_addr, "name": obj.name}
        except Exception as exc:  # noqa: BLE001 - hook reports and continues
            return {"addr": obj_addr, "error": str(exc)}

    def emit_function_start():
        if state["function_start_emitted"]:
            return
        append_event(
            {
                "event": "function_start",
                "name": ctx.fn,
                "identity": {
                    "requested": requested,
                    "canonical_name": ctx.fn,
                    "symbol_name": ctx.fn,
                    "source_name": ctx.fn,
                    "aliases": [],
                    "source_file": source_file,
                },
                "source_file": source_file,
            }
        )
        state["function_start_emitted"] = True

    required = ["codegen_start", "codegen_end", "pcode_pass_boundary", "pcbasicblocks"]
    missing = [key for key in required if not isinstance(entry_va(key), int)]
    state = {
        "active": False,
        "matched": False,
        "captured": False,
        "function_start_emitted": False,
        "passes_seen": [],
        "functions_seen": [],
        "errors": [],
    }

    try:
        cad.load_opcode_info()
        opcode_names = {
            index: info.mnemonic.lower()
            for index, info in enumerate(cad.MWCC_OPCODE_INFO)
        }
    except Exception:  # noqa: BLE001 - op names are useful but not required
        opcode_names = {}

    def capture_snapshot(stage):
        block_head = read_u32(entry_va("pcbasicblocks"))
        append_event(
            {
                "event": "backend_marker",
                "name": stage,
                "pc": int(gdb.parse_and_eval("$pc")),
                "function": ctx.fn,
                "source_file": source_file,
            }
        )
        events = backend_pcode_snapshot.snapshot_pcode_blocks(
            read_u32,
            read_s16,
            block_head,
            pass_id="pcode_snapshot",
            pass_name="PCode Snapshot",
            opcode_names=opcode_names,
            source_stage=stage,
            read_bytes=raw_reader,
        )
        if runtime_bundle.validated:
            events = (
                backend_runtime_instrumentation.bind_pcode_snapshot_lifecycle(
                    events, runtime_bundle
                )
            )
        blocks = sum(1 for event in events if event["event"] == "block")
        instructions = sum(1 for event in events if event["event"] == "pcode_instruction")
        for event in events:
            append_event(event)
        state["passes_seen"].append(
            {
                "pass_id": "pcode_snapshot",
                "pass_name": "PCode Snapshot",
                "source_stage": stage,
                "blocks": blocks,
                "instructions": instructions,
            }
        )
        state["captured"] = True

    class CodegenStart(gdb.Breakpoint):
        def stop(self):
            info = current_function_name()
            state["functions_seen"].append(info)
            if info.get("name") == ctx.fn:
                state["active"] = True
                state["matched"] = True
                state["captured"] = False
                state["function_start_emitted"] = False
                emit_function_start()
                append_event(
                    {
                        "event": "backend_marker",
                        "name": "codegen_start",
                        "pc": int(gdb.parse_and_eval("$pc")),
                        "function": ctx.fn,
                        "source_file": source_file,
                    }
                )
            else:
                state["active"] = False
            return False

    class PCodeSnapshot(gdb.Breakpoint):
        def stop(self):
            if not state["active"] or state["captured"]:
                return False
            try:
                capture_snapshot("pcode_pass_boundary")
            except Exception as exc:  # noqa: BLE001 - summarize in payload
                state["errors"].append({"stage": "pcode_pass_boundary", "error": str(exc)})
                state["captured"] = True
            return False

    class CodegenEnd(gdb.Breakpoint):
        def stop(self):
            if state["active"]:
                if not state["captured"]:
                    try:
                        capture_snapshot("codegen_end")
                    except Exception as exc:  # noqa: BLE001 - summarize in payload
                        state["errors"].append({"stage": "codegen_end", "error": str(exc)})
                        state["captured"] = True
                else:
                    append_event(
                        {
                            "event": "backend_marker",
                            "name": "codegen_end",
                            "pc": int(gdb.parse_and_eval("$pc")),
                            "function": ctx.fn,
                            "source_file": source_file,
                        }
                    )
                state["active"] = False
            return False

    if missing:
        state["errors"].append(
            {
                "stage": "setup",
                "error": "missing table entries: " + ", ".join(missing),
            }
        )
    else:
        CodegenStart(f"*{entry_va('codegen_start'):#x}")
        PCodeSnapshot(f"*{entry_va('pcode_pass_boundary'):#x}")
        CodegenEnd(f"*{entry_va('codegen_end'):#x}")

    try:
        ctx.cont()
    finally:
        payload = {
            "schema_version": "mwcc-retro-backend-pcode-snapshot.v1",
            "compiler": {"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            "requested_function": ctx.fn,
            "requested_function_matched": state["matched"],
            "functions_seen": state["functions_seen"],
            "passes_seen": state["passes_seen"],
            "errors": state["errors"],
            "runtime_instrumentation": (
                backend_runtime_instrumentation.runtime_bundle_status(
                    runtime_bundle
                )
            ),
            "notes": [
                "Partial PCode snapshot only; does not satisfy full backend trace schema.",
                "Events are dedicated to backend-pcode-snapshot-events.v1.jsonl.",
            ],
        }
        with open(out_summary, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
