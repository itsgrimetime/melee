"""GDB hook for `debug retro probe-backend-map`.

This file runs inside gdb via mwcc_retro_debugger.py's `--gdb-py` hook path.
It is evidence collection only: it writes backend-map-probe.json and never emits
backend-events.v1.jsonl or backend-trace.v1.json.
"""


def intervene(ctx):
    import json

    from tools.mwcc_retro import backend_frame_state

    gdb = ctx.gdb
    cad = ctx.cad
    out_path = ctx.out_dir + "/backend-map-probe.json"
    entries = ctx.table.get("entries", {})
    partial = ctx.table.get("backend_partial", {})

    def table_va(key, fallback=None):
        entry = entries.get(key) or partial.get(key) or {}
        return entry.get("va") or fallback

    candidates = {
        "codegen_start": table_va("codegen_start", 0x4351C0),
        "codegen_end": table_va("codegen_end", 0x435DB9),
        "pcode_pass_boundary": table_va("pcode_pass_boundary", table_va("pcode_traverse", 0x4C2560)),
        "build_interference_graph_wrapper": table_va("build_interference_graph_wrapper", 0x530A00),
        "dataflow_marker": table_va("dataflow_marker", 0x530A80),
        "build_interference_matrix": table_va("build_interference_matrix", 0x531290),
        "real_coalesce": table_va("real_coalesce", table_va("coalescer", 0x530E00)),
        "build_adjacency_vectors": table_va("build_adjacency_vectors", table_va("ig_builder", 0x530C00)),
        "simplifygraph": table_va("simplifygraph", 0x4CE400),
        "colorgraph": table_va("colorgraph", 0x4CE2D0),
        "final_scheduler": table_va("final_scheduler", 0x435D75),
    }
    globals_to_check = {
        "pcbasicblocks": {"va": table_va("pcbasicblocks", 0x587C74), "kind": "u32"},
        "interference_matrix": {"va": table_va("interference_matrix", 0x583088), "kind": "u32"},
        "coalesce_alias": {"va": table_va("coalesce_alias", 0x58308C), "kind": "u32"},
        "interferencegraph": {"va": table_va("interferencegraph", 0x587E3C), "kind": "u32"},
        "n_ignodes": {"va": table_va("n_ignodes", 0x587190), "kind": "u32"},
        "used_vreg_gpr": {"va": table_va("used_vreg_gpr", 0x58846E), "kind": "s16"},
        "used_vreg_fpr": {"va": table_va("used_vreg_fpr", 0x58846C), "kind": "s16"},
    }
    regclass_counter_candidates = {
        "0x588432": 0x588432,
        "0x58846a": 0x58846A,
        "0x58846c": 0x58846C,
        "0x58846e": 0x58846E,
        "0x588470": 0x588470,
        "0x588472": 0x588472,
        "0x588474": 0x588474,
        "0x58849a": 0x58849A,
    }
    frame_candidates = {
        "arguments": 0x58806C,
        "locals": 0x587FB8,
        "temps": 0x57FEC0,
        "frame_base_size": 0x5880CC,
        "frame_call_args_size": 0x58712C,
    }

    state = {
        "active": False,
        "matched": False,
        "sequence": 0,
        "events": [],
        "functions_seen": [],
        "stage_counts": {},
        "errors": [],
    }
    max_events = 128

    def read_i16(va):
        return int.from_bytes(ctx.read(va, 2), "little", signed=True)

    def read_s32(va):
        return int.from_bytes(ctx.read(va, 4), "little", signed=True)

    def read_u32(va):
        return ctx.u32(va)

    def read_cstr(va, limit=96):
        data = ctx.read(va, limit)
        end = data.find(b"\x00")
        if end >= 0:
            data = data[:end]
        return data.decode("latin-1", errors="replace")

    def read_stage_args(stage):
        sp = int(gdb.parse_and_eval("$esp"))
        try:
            if stage == "build_interference_graph_wrapper":
                return {
                    "input": read_u32(sp + 4),
                    "rclass": read_u32(sp + 8),
                    "n_virtuals": read_u32(sp + 12),
                }
            if stage in {
                "dataflow_marker",
                "build_interference_matrix",
                "real_coalesce",
            }:
                return {"rclass": read_u32(sp + 4), "n_virtuals": read_u32(sp + 8)}
            if stage == "build_adjacency_vectors":
                return {"n_virtuals": read_u32(sp + 4)}
            if stage == "simplifygraph":
                return {
                    "rclass": read_u32(sp + 4),
                    "n_colors": read_u32(sp + 8),
                    "n_class_regs": read_u32(sp + 12),
                }
            if stage == "colorgraph":
                return {"rclass": read_u32(sp + 4), "head": read_u32(sp + 8)}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        return {}

    def current_function_name():
        sp = int(gdb.parse_and_eval("$esp"))
        obj_addr = read_u32(sp + 8)
        try:
            obj = cad.MwccObject.load(obj_addr, load_linkname=False)
            return {"addr": obj_addr, "name": obj.name}
        except Exception as exc:  # noqa: BLE001 - probe should report and continue
            return {"addr": obj_addr, "error": str(exc)}

    def bounded_ptr(value):
        return isinstance(value, int) and 0x600000 <= value < 0x2000000

    def sample_blocks(snap):
        head = snap["globals"].get("pcbasicblocks", {}).get("u32", 0)
        if not bounded_ptr(head):
            return
        rows = []
        cur = head
        seen = set()
        for slot in range(8):
            if not bounded_ptr(cur) or cur in seen:
                break
            seen.add(cur)
            try:
                first = read_u32(cur + 0x14)
                last = read_u32(cur + 0x18)
                row = {
                    "slot": slot,
                    "ptr": cur,
                    "next": read_u32(cur + 0x00),
                    "blockIndex": read_u32(cur + 0x1C),
                    "firstPCode": first,
                    "lastPCode": last,
                }
                if bounded_ptr(first):
                    row["first_pcode"] = {
                        "ptr": first,
                        "next": read_u32(first + 0x00),
                        "opcode": read_i16(first + 0x14),
                        "arg_count": read_i16(first + 0x1A),
                    }
                rows.append(row)
                cur = row["next"]
            except Exception as exc:  # noqa: BLE001
                rows.append({"slot": slot, "ptr": cur, "error": str(exc)})
                break
        if rows:
            snap["block_sample"] = rows

    def sample_frame_state(snap, stage):
        if stage not in {"final_scheduler", "codegen_end"}:
            return
        try:
            snap["frame_state"] = backend_frame_state.snapshot_probe_frame_state(
                read_u32,
                read_s32,
                read_cstr,
                list_vas={
                    "arguments": frame_candidates["arguments"],
                    "locals": frame_candidates["locals"],
                    "temps": frame_candidates["temps"],
                },
                frame_base_size_va=frame_candidates["frame_base_size"],
                frame_call_args_size_va=frame_candidates["frame_call_args_size"],
            )
        except Exception as exc:  # noqa: BLE001
            snap["frame_state"] = {"error": str(exc)}

    def snapshot(stage):
        state["stage_counts"][stage] = state["stage_counts"].get(stage, 0) + 1
        if len(state["events"]) >= max_events:
            return
        snap = {
            "stage": stage,
            "pc": int(gdb.parse_and_eval("$pc")),
            "esp": int(gdb.parse_and_eval("$esp")),
            "sequence": state["sequence"],
            "globals": {},
        }
        args = read_stage_args(stage)
        if args:
            snap["stage_args"] = args
        for key, spec in globals_to_check.items():
            va = spec.get("va")
            if not isinstance(va, int):
                snap["globals"][key] = {"confidence": "unknown"}
                continue
            try:
                if spec.get("kind") == "s16":
                    snap["globals"][key] = {"va": va, "s16": read_i16(va)}
                else:
                    snap["globals"][key] = {"va": va, "u32": read_u32(va)}
            except Exception as exc:  # noqa: BLE001
                snap["globals"][key] = {"va": va, "error": str(exc)}

        counters = {}
        for label, va in regclass_counter_candidates.items():
            try:
                counters[label] = read_i16(va)
            except Exception as exc:  # noqa: BLE001
                counters[label] = {"error": str(exc)}
        snap["regclass_counter_candidates"] = counters

        graph = snap["globals"].get("interferencegraph", {}).get("u32", 0)
        n_ignodes = snap["globals"].get("n_ignodes", {}).get("u32", 0)
        if bounded_ptr(graph) and isinstance(n_ignodes, int) and 0 < n_ignodes < 2048:
            sample = []
            for idx in range(min(n_ignodes, 8)):
                try:
                    ptr = read_u32(graph + idx * 4)
                    row = {"slot": idx, "ptr": ptr}
                    if bounded_ptr(ptr):
                        array_size = read_i16(ptr + 0x14)
                        neighbors = []
                        for neighbor_idx in range(min(max(array_size, 0), 8)):
                            neighbors.append(read_i16(ptr + 0x16 + neighbor_idx * 2))
                        row.update(
                            {
                                "next": read_u32(ptr + 0x00),
                                "ig_idx": read_i16(ptr + 0x0C),
                                "degree": read_i16(ptr + 0x0E),
                                "assignedReg": read_i16(ptr + 0x10),
                                "flags": read_i16(ptr + 0x12),
                                "arraySize": array_size,
                                "neighbors_sample": neighbors,
                            }
                        )
                    sample.append(row)
                except Exception as exc:  # noqa: BLE001
                    sample.append({"slot": idx, "error": str(exc)})
            snap["ig_sample"] = sample
        sample_blocks(snap)
        sample_frame_state(snap, stage)
        state["events"].append(snap)

    class CodegenStart(gdb.Breakpoint):
        def stop(self):
            state["sequence"] += 1
            info = current_function_name()
            info["sequence"] = state["sequence"]
            state["functions_seen"].append(info)
            if info.get("name") == ctx.fn:
                state["active"] = True
                state["matched"] = True
                snapshot("codegen_start")
            else:
                state["active"] = False
            return False

    class ProbeBreakpoint(gdb.Breakpoint):
        def __init__(self, stage, va):
            self.stage = stage
            super().__init__(f"*{va:#x}")

        def stop(self):
            if state["active"]:
                try:
                    snapshot(self.stage)
                except Exception as exc:  # noqa: BLE001
                    state["errors"].append({"stage": self.stage, "error": str(exc)})
            return False

    class CodegenEnd(gdb.Breakpoint):
        def stop(self):
            if state["active"]:
                try:
                    snapshot("codegen_end")
                finally:
                    state["active"] = False
            return False

    CodegenStart(f"*{candidates['codegen_start']:#x}")
    for stage, va in candidates.items():
        if stage in {"codegen_start", "codegen_end"} or not isinstance(va, int):
            continue
        ProbeBreakpoint(stage, va)
    CodegenEnd(f"*{candidates['codegen_end']:#x}")

    try:
        ctx.cont()
    finally:
        payload = {
            "schema_version": "mwcc-retro-backend-map-probe.v1",
            "compiler": {"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            "requested_function": ctx.fn,
            "requested_function_matched": state["matched"],
            "candidates": candidates,
            "globals": {key: spec.get("va") for key, spec in globals_to_check.items()},
            "functions_seen": state["functions_seen"],
            "stage_counts": state["stage_counts"],
            "events": state["events"],
            "errors": state["errors"],
            "notes": [
                "Probe evidence is not a backend trace and does not satisfy the struct-map gate by itself.",
                "Events are scoped by ObjObject source name when readable at codegen_start.",
            ],
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
