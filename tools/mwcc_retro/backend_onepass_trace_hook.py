"""One-pass GC/1.2.5n backend trace hook.

This hook writes a single ``backend-events.v1.jsonl`` stream for the requested
function. The full ``debug retro backend`` command uses it behind the
``backend_reader.complete`` gate; ``backend-candidate --one-pass`` reuses it for
candidate-only diagnostics.
"""


def _try_capture_pcode_stage(state, stage, capture_pcode, *, fallback_stage):
    if state["pcode_captured"]:
        return True
    try:
        capture_pcode(stage)
        return True
    except Exception as exc:  # noqa: BLE001 - later backend stages can still retry
        state["warnings"].append(
            {
                "stage": stage,
                "warning": (
                    f"PCode {stage} snapshot skipped; "
                    f"{fallback_stage} fallback will be tried: {exc}"
                ),
            }
        )
        return False


def intervene(ctx):
    import json
    import os

    from tools.mwcc_retro import backend_colorgraph_trace
    from tools.mwcc_retro import backend_frame_state
    from tools.mwcc_retro import backend_ig_snapshot
    from tools.mwcc_retro import backend_pcode_snapshot
    from tools.mwcc_retro import backend_trace_assembler

    gdb = ctx.gdb
    cad = ctx.cad
    entries = ctx.table.get("entries", {})
    out_events = ctx.out_dir + "/backend-events.v1.jsonl"
    out_summary = ctx.out_dir + "/backend-onepass-candidate.json"
    source_file = os.environ.get("RETRO_SOURCE", "")
    requested = os.environ.get("RETRO_FUNCTION", ctx.fn)

    def parse_aliases():
        try:
            values = json.loads(os.environ.get("RETRO_FUNCTION_ALIASES", "[]"))
        except Exception:  # noqa: BLE001 - malformed caller env should not kill tracing
            return []
        if not isinstance(values, list):
            return []
        result = []
        seen = set()
        for value in values:
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text or text in seen:
                continue
            result.append(text)
            seen.add(text)
        return result

    function_aliases = parse_aliases()
    match_names = {
        name
        for name in [requested, ctx.fn, *function_aliases]
        if isinstance(name, str) and name
    }

    def function_matches(info):
        return info.get("name") in match_names

    def identity_payload(matched_name):
        aliases = []
        seen = set()
        for name in [*function_aliases, matched_name]:
            if not isinstance(name, str) or not name or name in {requested, ctx.fn}:
                continue
            if name in seen:
                continue
            aliases.append(name)
            seen.add(name)
        return {
            "requested": requested,
            "canonical_name": requested,
            "symbol_name": matched_name or requested,
            "source_name": ctx.fn,
            "aliases": aliases,
            "source_file": source_file,
        }

    def entry_va(key, fallback=None):
        entry = entries.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("va"), int):
            return entry["va"]
        return fallback

    def read_s16(va):
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

    def bounded_ptr(value):
        return isinstance(value, int) and 0x600000 <= value < 0x2000000

    def bounded_code_ptr(value):
        return isinstance(value, int) and 0x400000 <= value < 0x600000

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

    try:
        cad.load_opcode_info()
        opcode_names = {
            index: info.mnemonic.lower()
            for index, info in enumerate(cad.MWCC_OPCODE_INFO)
        }
    except Exception:  # noqa: BLE001 - op names are useful but not required
        opcode_names = {}

    class_names = {0: "gpr", 1: "fpr"}
    used_vreg_keys = {0: "used_vreg_gpr", 1: "used_vreg_fpr"}
    class_reserved = {0: [1, 2], 1: []}
    volatile_regs = {0: [0] + list(range(3, 13)), 1: list(range(14))}
    nonvolatile_regs = {0: list(range(31, 12, -1)), 1: list(range(31, 13, -1))}
    internal_pcs = {
        "select_start": entry_va("colorgraph_select_start"),
        "candidates_ready": entry_va("colorgraph_candidates_ready"),
        "assign_volatile": entry_va("colorgraph_assign_volatile"),
        "assign_nonvolatile": entry_va("colorgraph_assign_nonvolatile"),
        "spill": entry_va("colorgraph_spill"),
    }
    frame_vas = {
        "arguments": entry_va("arguments", 0x58806C),
        "locals": entry_va("locals", 0x587FB8),
        "temps": entry_va("temps", 0x57FEC0),
    }
    frame_base_size_va = entry_va("frame_base_size", 0x5880CC)
    frame_call_args_size_va = entry_va("frame_call_args_size", 0x58712C)
    required = [
        "codegen_start",
        "codegen_end",
        "pcode_pass_boundary",
        "pcbasicblocks",
        "colorgraph",
        "interferencegraph",
        "used_vreg_gpr",
        "used_vreg_fpr",
        "final_scheduler",
        *[
            key
            for key in (
                "colorgraph_select_start",
                "colorgraph_candidates_ready",
                "colorgraph_assign_volatile",
                "colorgraph_assign_nonvolatile",
                "colorgraph_spill",
            )
        ],
    ]
    missing = [key for key in required if not isinstance(entry_va(key), int)]

    state = {
        "active": False,
        "matched": False,
        "function_start_emitted": False,
        "pcode_captured": False,
        "pcode_boundary_failed": False,
        "frame_captured": False,
        "captured_classes": set(),
        "pending_classes": set(),
        "return_breakpoints": [],
        "active_colorgraph": None,
        "current_decision": None,
        "class_iters": {},
        "exact_decisions_by_class": {},
        "matched_function_name": None,
        "functions_seen": [],
        "passes_seen": [],
        "classes_seen": [],
        "decisions_seen": [],
        "errors": [],
        "warnings": [],
    }

    def emit_function_start():
        if state["function_start_emitted"]:
            return
        append_event(
            {
                "event": "function_start",
                "name": requested,
                "identity": identity_payload(state.get("matched_function_name") or ctx.fn),
                "source_file": source_file,
            }
        )
        state["function_start_emitted"] = True

    def capture_pcode(stage):
        if state["pcode_captured"]:
            return
        block_head = read_u32(entry_va("pcbasicblocks"))
        events = backend_pcode_snapshot.snapshot_pcode_blocks(
            read_u32,
            read_s16,
            block_head,
            pass_id="pcode_snapshot",
            pass_name="PCode Snapshot",
            opcode_names=opcode_names,
            source_stage=stage,
        )
        for event in events:
            append_event(event)
        state["passes_seen"].append(
            {
                "pass_id": "pcode_snapshot",
                "pass_name": "PCode Snapshot",
                "source_stage": stage,
                "blocks": sum(1 for event in events if event["event"] == "block"),
                "instructions": sum(
                    1 for event in events if event["event"] == "pcode_instruction"
                ),
            }
        )
        state["pcode_captured"] = True

    def capture_frame(stage):
        if state["frame_captured"]:
            return
        try:
            event = backend_frame_state.snapshot_frame_state(
                read_u32,
                read_s32,
                read_cstr,
                list_vas=frame_vas,
                frame_base_size_va=frame_base_size_va,
                frame_call_args_size_va=frame_call_args_size_va,
                source_stage=stage,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to probe-shaped names
            state["warnings"].append(
                {"stage": stage, "warning": f"frame_state fallback: {exc}"}
            )
            probe_frame = backend_frame_state.snapshot_probe_frame_state(
                read_u32,
                read_s32,
                read_cstr,
                list_vas=frame_vas,
                frame_base_size_va=frame_base_size_va,
                frame_call_args_size_va=frame_call_args_size_va,
            )
            event = backend_trace_assembler.frame_events_from_map_probe_payload(
                {"events": [{"stage": stage, "frame_state": probe_frame}]}
            )[0]
        append_event(event)
        state["frame_captured"] = True

    def reset_for_function():
        state["active"] = True
        state["matched"] = True
        state["function_start_emitted"] = False
        state["pcode_captured"] = False
        state["pcode_boundary_failed"] = False
        state["frame_captured"] = False
        state["captured_classes"] = set()
        state["pending_classes"] = set()
        state["return_breakpoints"] = []
        state["active_colorgraph"] = None
        state["current_decision"] = None
        state["class_iters"] = {}
        state["exact_decisions_by_class"] = {}
        state["matched_function_name"] = None

    class CodegenStart(gdb.Breakpoint):
        def stop(self):
            info = current_function_name()
            state["functions_seen"].append(info)
            if function_matches(info):
                reset_for_function()
                state["matched_function_name"] = info.get("name")
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
            if (
                not state["active"]
                or state["pcode_captured"]
                or state["pcode_boundary_failed"]
            ):
                return False
            if not _try_capture_pcode_stage(
                state,
                "pcode_pass_boundary",
                capture_pcode,
                fallback_stage="final_scheduler",
            ):
                state["pcode_boundary_failed"] = True
            return False

    class Colorgraph(gdb.Breakpoint):
        def stop(self):
            if not state["active"]:
                return False
            try:
                sp = int(gdb.parse_and_eval("$esp"))
                class_id = read_u32(sp + 4)
                class_name = class_names.get(class_id)
                if class_name is None:
                    state["errors"].append(
                        {"stage": "colorgraph", "error": f"unknown rclass {class_id}"}
                    )
                    return False
                if class_id in state["captured_classes"] or class_id in state["pending_classes"]:
                    return False

                graph_global = entry_va("interferencegraph")
                used_global = entry_va(used_vreg_keys[class_id])
                graph = read_u32(graph_global)
                return_pc = read_u32(sp)
                colorgraph_head = read_u32(sp + 8)
                n_virtuals = read_s16(used_global)
                if not bounded_ptr(graph):
                    raise ValueError(f"interferencegraph value {graph:#x} is not bounded")
                if colorgraph_head != 0 and not bounded_ptr(colorgraph_head):
                    raise ValueError(f"colorgraph head value {colorgraph_head:#x} is not bounded")
                if not bounded_code_ptr(return_pc):
                    raise ValueError(f"colorgraph return pc {return_pc:#x} is not bounded")
                if n_virtuals <= 0:
                    return False

                state["pending_classes"].add(class_id)
                state["active_colorgraph"] = {
                    "class_id": class_id,
                    "class_name": class_name,
                    "graph": graph,
                    "n_virtuals": n_virtuals,
                    "return_pc": return_pc,
                }

                fired = {"done": False}

                class ColorgraphReturn(gdb.Breakpoint):
                    def stop(self):
                        if fired["done"]:
                            return False
                        fired["done"] = True
                        try:
                            events = backend_ig_snapshot.post_colorgraph_class_events(
                                read_u32,
                                read_s16,
                                graph_va=graph,
                                head_ptr=colorgraph_head,
                                n_ignodes=n_virtuals,
                                class_id=class_id,
                                class_name=class_name,
                                function_name=ctx.fn,
                            )
                            filtered = [
                                event
                                for event in events
                                if event.get("event") != "color_decision"
                            ]
                            for event in filtered:
                                append_event(event)
                            exact = state["exact_decisions_by_class"].get(class_id, [])
                            for event in exact:
                                append_event(event)
                            order = next(
                                (
                                    event.get("order", [])
                                    for event in events
                                    if event.get("event") == "select_order"
                                ),
                                [],
                            )
                            state["captured_classes"].add(class_id)
                            state["classes_seen"].append(
                                {
                                    "class_id": class_id,
                                    "class_name": class_name,
                                    "nodes": n_virtuals,
                                    "order_nodes": len(order),
                                    "exact_color_decisions": len(exact),
                                }
                            )
                        except Exception as exc:  # noqa: BLE001 - summarize in payload
                            state["errors"].append(
                                {
                                    "stage": "colorgraph_return",
                                    "class_id": class_id,
                                    "error": str(exc),
                                }
                            )
                        finally:
                            state["pending_classes"].discard(class_id)
                            if state.get("active_colorgraph", {}).get("return_pc") == return_pc:
                                state["active_colorgraph"] = None
                                state["current_decision"] = None
                        return False

                state["return_breakpoints"].append(ColorgraphReturn(f"*{return_pc:#x}"))
            except Exception as exc:  # noqa: BLE001 - summarize in payload
                if "class_id" in locals():
                    state["pending_classes"].discard(class_id)
                state["errors"].append({"stage": "colorgraph", "error": str(exc)})
            return False

    def mask_to_regs(mask, regs):
        return [phys for phys in regs if mask & (1 << phys)]

    def assigned_phys_or_none(ig_id, active):
        graph = active["graph"]
        n_ignodes = active["n_virtuals"]
        if ig_id < 0 or ig_id >= n_ignodes:
            return None
        node_ptr = read_u32(graph + ig_id * 4)
        if not bounded_ptr(node_ptr):
            return None
        flags = read_s16(node_ptr + 0x12) & 0xFF
        assigned = read_s16(node_ptr + 0x10)
        if flags & 0x04:
            return None
        if assigned < 0 or assigned >= 32:
            return None
        return assigned

    def current_blockers(active, node_ptr, available_mask, candidate_mask):
        blocked = []
        seen = set()
        array_size = read_s16(node_ptr + 0x14)
        if array_size < 0 or array_size > 2048:
            raise ValueError(f"invalid colorgraph neighbor count {array_size}")
        for index in range(array_size):
            holder = read_s16(node_ptr + 0x16 + index * 2)
            phys = assigned_phys_or_none(holder, active)
            if phys is None:
                continue
            if not (available_mask & (1 << phys)):
                continue
            if candidate_mask & (1 << phys):
                continue
            key = (holder, phys)
            if key in seen:
                continue
            seen.add(key)
            blocked.append(
                {
                    "phys": phys,
                    "reason": "interferer-assigned-phys",
                    "holder_ig_id": holder,
                    "holder_assigned_phys": phys,
                    "provenance": "colorgraph_neighbor_scan",
                }
            )
        return blocked

    def begin_decision():
        active = state.get("active_colorgraph")
        if not active:
            return
        if state.get("current_decision") is not None:
            state["errors"].append(
                {
                    "stage": "select_start",
                    "error": "new colorgraph decision started before previous decision closed",
                    "raw": state["current_decision"].get("raw", []),
                }
            )
            state["current_decision"] = None
        class_id = active["class_id"]
        class_name = active["class_name"]
        node_ptr = int(gdb.parse_and_eval("$ebx"))
        if not bounded_ptr(node_ptr):
            raise ValueError(f"colorgraph EBX node pointer {node_ptr:#x} is not bounded")
        sp = int(gdb.parse_and_eval("$esp"))
        available_mask = read_u32(sp)
        ig_id = read_s16(node_ptr + 0x0C)
        flags = read_s16(node_ptr + 0x12) & 0xFF
        if ig_id < 0 or ig_id >= active["n_virtuals"]:
            raise ValueError(
                f"colorgraph selected ig_id {ig_id} outside {active['n_virtuals']}"
            )
        iteration = state["class_iters"].get(class_id, 0)
        state["class_iters"][class_id] = iteration + 1
        decision_id = f"{class_name}-i{iteration}"
        nonvolatile_available = mask_to_regs(available_mask, nonvolatile_regs[class_id])
        start = {
            "event": "colorgraph_select_start",
            "id": decision_id,
            "class_id": class_id,
            "class_name": class_name,
            "iter": iteration,
            "ig_id": ig_id,
            "available_mask": available_mask,
            "pc": int(gdb.parse_and_eval("$pc")),
            "esp": sp,
            "ebx": node_ptr,
            "node_state_before_select": {
                "precolored": False,
                "coalesced": bool(flags & 0x04),
                "spill_marked": bool(flags & 0x01),
                "rematerialized": False,
            },
            "reserved_or_precolored_filtered": class_reserved[class_id],
            "volatile_pool_before": mask_to_regs(available_mask, volatile_regs[class_id]),
            "nonvolatile_dispense_before": {
                "next": nonvolatile_available[0] if nonvolatile_available else None,
                "remaining": nonvolatile_available,
            },
        }
        state["current_decision"] = {
            "id": decision_id,
            "node_ptr": node_ptr,
            "available_mask": available_mask,
            "raw": [start],
        }

    def capture_candidates():
        active = state.get("active_colorgraph")
        current = state.get("current_decision")
        if not active or not current:
            return
        candidate_mask = int(gdb.parse_and_eval("$eax")) & 0xFFFFFFFF
        current["raw"].append(
            {
                "event": "colorgraph_candidates_ready",
                "id": current["id"],
                "candidate_mask": candidate_mask,
                "pc": int(gdb.parse_and_eval("$pc")),
                "eax": int(gdb.parse_and_eval("$eax")) & 0xFFFFFFFF,
                "blocked_candidates": current_blockers(
                    active,
                    current["node_ptr"],
                    current["available_mask"],
                    candidate_mask,
                ),
            }
        )

    def finish_assignment(assigned_phys, chosen_source, tie_rule):
        current = state.get("current_decision")
        if not current:
            return
        class_id = state["active_colorgraph"]["class_id"]
        available_mask = current["available_mask"]
        volatile_after = mask_to_regs(available_mask, volatile_regs[class_id])
        nonvolatile_before = mask_to_regs(available_mask, nonvolatile_regs[class_id])
        nonvolatile_after = list(nonvolatile_before)
        consumed_nonvolatile = None
        if chosen_source == "volatile_pool":
            volatile_after = [phys for phys in volatile_after if phys != assigned_phys]
        elif chosen_source == "nonvolatile_dispense":
            consumed_nonvolatile = assigned_phys
            nonvolatile_after = [
                phys for phys in nonvolatile_after if phys != assigned_phys
            ]
        current["raw"].append(
            {
                "event": "colorgraph_assignment",
                "id": current["id"],
                "assigned_phys": assigned_phys,
                "pc": int(gdb.parse_and_eval("$pc")),
                "eax": int(gdb.parse_and_eval("$eax")) & 0xFFFFFFFF,
                "ecx": int(gdb.parse_and_eval("$ecx")) & 0xFFFFFFFF,
                "chosen_source": chosen_source,
                "volatile_pool_after": volatile_after,
                "nonvolatile_dispense_after": {
                    "consumed": consumed_nonvolatile,
                    "remaining": nonvolatile_after,
                },
                "tie_rule": tie_rule,
                "decision_rule": "lowest_available_or_nonvolatile_dispense",
            }
        )
        emit_current_decision()

    def finish_spill():
        current = state.get("current_decision")
        if not current:
            return
        current["raw"].append(
            {
                "event": "colorgraph_spill",
                "id": current["id"],
                "reason": "no_available_color",
            }
        )
        emit_current_decision()

    def emit_current_decision():
        current = state.get("current_decision")
        if not current:
            return
        try:
            decisions = backend_colorgraph_trace.assemble_color_decisions(current["raw"])
            for decision in decisions:
                class_id = decision["class_id"]
                state["exact_decisions_by_class"].setdefault(class_id, []).append(decision)
                state["decisions_seen"].append(
                    {
                        "class_id": decision["class_id"],
                        "class_name": decision["class_name"],
                        "ig_id": decision["ig_id"],
                        "assigned_phys": decision["assigned_phys"],
                    }
                )
        except Exception as exc:  # noqa: BLE001 - keep probing later decisions
            state["errors"].append(
                {"id": current.get("id"), "error": str(exc), "raw": current.get("raw", [])}
            )
        finally:
            state["current_decision"] = None

    class InternalColorgraphBreakpoint(gdb.Breakpoint):
        def __init__(self, name, va):
            self.name = name
            super().__init__(f"*{va:#x}")

        def stop(self):
            if not state.get("active_colorgraph"):
                return False
            try:
                if self.name == "select_start":
                    begin_decision()
                elif self.name == "candidates_ready":
                    capture_candidates()
                elif self.name == "assign_volatile":
                    finish_assignment(
                        int(gdb.parse_and_eval("$ecx")) & 0xFFFF,
                        "volatile_pool",
                        "first_volatile_available",
                    )
                elif self.name == "assign_nonvolatile":
                    finish_assignment(
                        int(gdb.parse_and_eval("$eax")) & 0xFFFF,
                        "nonvolatile_dispense",
                        "top_down_nonvolatile_dispense",
                    )
                elif self.name == "spill":
                    finish_spill()
            except Exception as exc:  # noqa: BLE001 - report and continue
                state["errors"].append({"stage": self.name, "error": str(exc)})
                if self.name in {"assign_volatile", "assign_nonvolatile", "spill"}:
                    state["current_decision"] = None
            return False

    class FinalScheduler(gdb.Breakpoint):
        def stop(self):
            if state["active"]:
                if not state["pcode_captured"]:
                    _try_capture_pcode_stage(
                        state,
                        "final_scheduler",
                        capture_pcode,
                        fallback_stage="codegen_end",
                    )
                try:
                    capture_frame("final_scheduler")
                except Exception as exc:  # noqa: BLE001 - codegen_end can still fallback
                    state["errors"].append({"stage": "final_scheduler", "error": str(exc)})
            return False

    class CodegenEnd(gdb.Breakpoint):
        def stop(self):
            if state["active"]:
                if not state["pcode_captured"]:
                    try:
                        capture_pcode("codegen_end")
                    except Exception as exc:  # noqa: BLE001 - summarize in payload
                        state["errors"].append({"stage": "codegen_end_pcode", "error": str(exc)})
                if not state["frame_captured"]:
                    try:
                        capture_frame("codegen_end")
                    except Exception as exc:  # noqa: BLE001 - summarize in payload
                        state["errors"].append({"stage": "codegen_end_frame", "error": str(exc)})
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

    if os.path.exists(out_events):
        os.remove(out_events)

    if missing:
        print("[retro] ABORT: one-pass backend candidate missing entries " + ", ".join(missing))
    else:
        CodegenStart(f"*{entry_va('codegen_start'):#x}")
        PCodeSnapshot(f"*{entry_va('pcode_pass_boundary'):#x}")
        Colorgraph(f"*{entry_va('colorgraph'):#x}")
        FinalScheduler(f"*{entry_va('final_scheduler'):#x}")
        for name, va in internal_pcs.items():
            if isinstance(va, int):
                InternalColorgraphBreakpoint(name, va)
        CodegenEnd(f"*{entry_va('codegen_end'):#x}")

    try:
        ctx.cont()
    finally:
        payload = {
            "schema_version": "mwcc-retro-backend-onepass-candidate.v1",
            "compiler": {"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            "requested_function": ctx.fn,
            "requested_function_matched": state["matched"],
            "functions_seen": state["functions_seen"],
            "passes_seen": state["passes_seen"],
            "classes_seen": state["classes_seen"],
            "decisions_seen": state["decisions_seen"],
            "internal_breakpoints": internal_pcs,
            "errors": state["errors"],
            "warnings": state["warnings"],
            "notes": [
                "One-pass retail backend event stream.",
                "Diagnostic sidecar for trace assembly and completeness checks.",
            ],
        }
        with open(out_summary, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
