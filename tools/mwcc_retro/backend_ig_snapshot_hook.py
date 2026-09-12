"""GDB hook for partial GC/1.2.5n backend interference-graph snapshots.

This hook is intentionally not the full backend trace reader.  It emits the
regclass/node/edge event families into a dedicated JSONL file so live retail
IG facts can be validated without producing ``backend-trace.v1.json``.
"""


def intervene(ctx):
    import json

    from tools.mwcc_retro import backend_colorgraph_trace
    from tools.mwcc_retro import backend_ig_snapshot

    gdb = ctx.gdb
    cad = ctx.cad
    entries = ctx.table.get("entries", {})
    out_events = ctx.out_dir + "/backend-ig-snapshot-events.v1.jsonl"
    out_summary = ctx.out_dir + "/backend-ig-snapshot.json"
    out_colorgraph_events = ctx.out_dir + "/backend-colorgraph-decisions.v1.jsonl"
    out_colorgraph_summary = ctx.out_dir + "/backend-colorgraph-trace.json"
    source_file = __import__("os").environ.get("RETRO_SOURCE", "")
    requested = __import__("os").environ.get("RETRO_FUNCTION", ctx.fn)

    def entry_va(key, fallback=None):
        entry = entries.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("va"), int):
            return entry["va"]
        return fallback

    def read_s16(va):
        return int.from_bytes(ctx.read(va, 2), "little", signed=True)

    def read_u32(va):
        return ctx.u32(va)

    def bounded_ptr(value):
        return isinstance(value, int) and 0x600000 <= value < 0x2000000

    def bounded_code_ptr(value):
        return isinstance(value, int) and 0x400000 <= value < 0x600000

    def append_event(event):
        with open(out_events, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    def append_colorgraph_event(event):
        with open(out_colorgraph_events, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    def current_function_name():
        sp = int(gdb.parse_and_eval("$esp"))
        obj_addr = read_u32(sp + 8)
        try:
            obj = cad.MwccObject.load(obj_addr, load_linkname=False)
            return {"addr": obj_addr, "name": obj.name}
        except Exception as exc:  # noqa: BLE001 - hook reports and continues
            return {"addr": obj_addr, "error": str(exc)}

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
    required = [
        "codegen_start",
        "codegen_end",
        "colorgraph",
        "interferencegraph",
        "used_vreg_gpr",
        "used_vreg_fpr",
        "colorgraph_select_start",
        "colorgraph_candidates_ready",
        "colorgraph_assign_volatile",
        "colorgraph_assign_nonvolatile",
        "colorgraph_spill",
    ]
    missing = [key for key in required if not isinstance(entry_va(key), int)]

    state = {
        "active": False,
        "matched": False,
        "function_start_emitted": False,
        "captured_classes": set(),
        "pending_classes": set(),
        "return_breakpoints": [],
        "classes_seen": [],
        "colorgraph_decisions_seen": [],
        "active_colorgraph": None,
        "current_decision": None,
        "class_iters": {},
        "functions_seen": [],
        "errors": [],
        "colorgraph_errors": [],
    }

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

    class CodegenStart(gdb.Breakpoint):
        def stop(self):
            info = current_function_name()
            state["functions_seen"].append(info)
            if info.get("name") == ctx.fn:
                state["active"] = True
                state["matched"] = True
                state["captured_classes"] = set()
                state["pending_classes"] = set()
                state["return_breakpoints"] = []
                state["active_colorgraph"] = None
                state["current_decision"] = None
                state["class_iters"] = {}
                state["function_start_emitted"] = False
                emit_function_start()
                append_colorgraph_event(
                    {
                        "event": "function_start",
                        "name": ctx.fn,
                        "source_file": source_file,
                    }
                )
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
                if class_id in state["captured_classes"]:
                    return False
                if class_id in state["pending_classes"]:
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

                # Do not delete this breakpoint inside stop(): retrowin32+gdb
                # crashes in that path (reported as melee-agent issue #1164).
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
                            for event in events:
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
                                    "color_decisions": sum(
                                        1
                                        for event in events
                                        if event.get("event") == "color_decision"
                                    ),
                                    "order_error": None,
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
            state["colorgraph_errors"].append(
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
        nonvolatile_available = mask_to_regs(
            available_mask,
            nonvolatile_regs[class_id],
        )
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
        elif assigned_phys in nonvolatile_after:
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
                append_colorgraph_event(decision)
                state["colorgraph_decisions_seen"].append(
                    {
                        "class_id": decision["class_id"],
                        "class_name": decision["class_name"],
                        "ig_id": decision["ig_id"],
                        "assigned_phys": decision["assigned_phys"],
                    }
                )
        except Exception as exc:  # noqa: BLE001 - keep probing later decisions
            state["colorgraph_errors"].append(
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
                state["colorgraph_errors"].append(
                    {"stage": self.name, "error": str(exc)}
                )
                if self.name in {"assign_volatile", "assign_nonvolatile", "spill"}:
                    state["current_decision"] = None
            return False

    class CodegenEnd(gdb.Breakpoint):
        def stop(self):
            if state["active"]:
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
        Colorgraph(f"*{entry_va('colorgraph'):#x}")
        for name, va in internal_pcs.items():
            if isinstance(va, int):
                InternalColorgraphBreakpoint(name, va)
        CodegenEnd(f"*{entry_va('codegen_end'):#x}")

    try:
        ctx.cont()
    finally:
        payload = {
            "schema_version": "mwcc-retro-backend-ig-snapshot.v1",
            "compiler": {"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            "requested_function": ctx.fn,
            "requested_function_matched": state["matched"],
            "functions_seen": state["functions_seen"],
            "classes_seen": state["classes_seen"],
            "errors": state["errors"],
            "notes": [
                "Partial IG/order/coalesce/color snapshot only; does not satisfy full backend trace schema.",
                "Events are dedicated to backend-ig-snapshot-events.v1.jsonl.",
                "Exact in-colorgraph decisions, when observed, are written to backend-colorgraph-decisions.v1.jsonl.",
            ],
        }
        with open(out_summary, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        colorgraph_payload = {
            "schema_version": "mwcc-retro-backend-colorgraph-trace.v1",
            "compiler": {"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            "requested_function": ctx.fn,
            "requested_function_matched": state["matched"],
            "decisions_seen": state["colorgraph_decisions_seen"],
            "internal_breakpoints": internal_pcs,
            "errors": state["colorgraph_errors"],
            "notes": [
                "Sidecar exact internal colorgraph decision probe.",
                "Not a complete backend-trace.v1 producer by itself.",
            ],
        }
        with open(out_colorgraph_summary, "w", encoding="utf-8") as f:
            json.dump(colorgraph_payload, f, indent=2, sort_keys=True)
            f.write("\n")
