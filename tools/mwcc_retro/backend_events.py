"""Normalize mwcc-retro backend JSONL events into backend trace v1."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tools.mwcc_retro import backend_schema

ALLOCATOR_EVENTS = {
    "node",
    "edge",
    "coalesce_mapping",
    "coalesce_mapping_empty",
    "simplify_order",
    "select_order",
    "color_decision",
}


def load_events(path: str | Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"event line {line_no} invalid JSON: {exc.msg}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"event line {line_no} must be an object")
        events.append(event)
    return events


def normalize_events(
    events: list[dict[str, Any]],
    *,
    compiler: dict[str, Any],
    source: dict[str, Any],
    tool_version: str,
) -> dict[str, Any]:
    normalizer = _Normalizer(compiler=compiler, source=source, tool_version=tool_version)
    return normalizer.normalize(events)


class _Normalizer:
    def __init__(
        self,
        *,
        compiler: dict[str, Any],
        source: dict[str, Any],
        tool_version: str,
    ) -> None:
        self.compiler = copy.deepcopy(compiler)
        self.source = copy.deepcopy(source)
        self.tool_version = tool_version
        self.function = _default_function(self.source)
        self.classes_by_name: dict[str, dict[str, Any]] = {}
        self.classes_by_id: dict[int, dict[str, Any]] = {}
        self.passes_by_id: dict[str, dict[str, Any]] = {}
        self.nodes_by_class: dict[int, dict[int, dict[str, Any]]] = {}

    def normalize(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        for event in events:
            self._apply(event)

        self._finalize_coalesce()
        self._sort_pcode_passes()
        trace = {
            "schema_version": backend_schema.SCHEMA_VERSION,
            "tool_version": self.tool_version,
            "compiler": self.compiler,
            "source": self.source,
            "functions": [self.function],
            "struct_map": {
                "schema_version": backend_schema.STRUCT_MAP_SCHEMA_VERSION,
                "entries": [],
            },
        }
        errors = backend_schema.validate_backend_trace(trace)
        if errors:
            if any("missing regalloc classes" in error for error in errors):
                raise ValueError("backend trace has no allocator classes")
            raise ValueError("backend trace failed validation: " + "; ".join(errors))
        return trace

    def _apply(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "function_start":
            self._apply_function_start(event)
        elif kind == "block":
            self._apply_block(event)
        elif kind == "pcode_instruction":
            self._apply_pcode_instruction(event)
        elif kind == "regclass":
            self._apply_regclass(event)
        elif kind == "frame_state":
            self._apply_frame_state(event)
        elif kind == "backend_marker":
            return
        elif kind in ALLOCATOR_EVENTS:
            cls = self._require_class(event, str(kind))
            if kind == "node":
                self._apply_node(cls, event)
            elif kind == "edge":
                self._apply_edge(cls, event)
            elif kind == "coalesce_mapping":
                self._apply_coalesce_mapping(cls, event)
            elif kind == "coalesce_mapping_empty":
                return
            elif kind == "simplify_order":
                self._apply_order(cls, event, "simplify_order")
            elif kind == "select_order":
                self._apply_order(cls, event, "select_order")
            elif kind == "color_decision":
                self._apply_color_decision(cls, event)
        else:
            raise ValueError(f"unknown backend event {kind!r}")

    def _apply_function_start(self, event: dict[str, Any]) -> None:
        name = event.get("name")
        if name is not None:
            self.function["name"] = name

        identity = copy.deepcopy(event.get("identity") or {})
        if not identity:
            identity = self.function["identity"]
        else:
            identity.setdefault("requested", name or self.source.get("function"))
            identity.setdefault("canonical_name", name or self.source.get("function"))
            identity.setdefault("symbol_name", identity.get("canonical_name"))
            identity.setdefault("source_name", identity.get("canonical_name"))
            identity.setdefault("aliases", [])
            identity.setdefault("source_file", self.source.get("tu"))
        self.function["identity"] = identity

    def _apply_block(self, event: dict[str, Any]) -> None:
        self.function["blocks"].append(
            {
                "id": event["id"],
                "order": event["order"],
                "succ": list(event.get("succ", [])),
                "pred": list(event.get("pred", [])),
                "labels": list(event.get("labels", [])),
            }
        )

    def _apply_pcode_instruction(self, event: dict[str, Any]) -> None:
        pass_id = event.get("pass_id", "before_register_coloring")
        pcode_pass = self.passes_by_id.get(pass_id)
        if pcode_pass is None:
            pcode_pass = {
                "id": pass_id,
                "name": event.get("pass_name", pass_id),
                "instructions": [],
            }
            self.passes_by_id[pass_id] = pcode_pass
            self.function["pcode"]["passes"].append(pcode_pass)

        instruction = {
            "id": event["id"],
            "block_id": event["block_id"],
            "order": event["order"],
            "opcode": event["opcode"],
            "operands": event.get("operands", ""),
            "normalized": event.get("normalized", ""),
        }
        for field in (
            "opcode_id",
            "arg_count",
            "pcode_id",
            "runtime_address",
            "allocation_generation",
            "lifecycle_sequence_at_capture",
            "source_stage",
            "operand_lineage_inventory",
            "retail_pcode",
        ):
            if field in event:
                instruction[field] = copy.deepcopy(event[field])
        pcode_pass["instructions"].append(instruction)

    def _apply_regclass(self, event: dict[str, Any]) -> None:
        class_id = event["class_id"]
        class_name = event["class_name"]
        if class_name in self.classes_by_name or class_id in self.classes_by_id:
            raise ValueError(f"duplicate regclass for {class_name}")

        cls = {
            "class_id": class_id,
            "class_name": class_name,
            "registers": copy.deepcopy(event["registers"]),
            "nodes": [],
            "edges": [],
            "coalesce": {"mappings": []},
            "non_allocatable_state": copy.deepcopy(
                event.get(
                    "non_allocatable_state",
                    {
                        "status": "model-boundary",
                        "notes": ["CR/LR/CTR not modeled in v1 allocator facts"],
                    },
                )
            ),
            "simplify_order": [],
            "select_order": [],
            "color_decisions": [],
        }
        self.function["regalloc"]["classes"].append(cls)
        self.classes_by_name[class_name] = cls
        self.classes_by_id[class_id] = cls
        self.nodes_by_class[id(cls)] = {}

    def _apply_node(self, cls: dict[str, Any], event: dict[str, Any]) -> None:
        node = {
            "ig_id": event["ig_id"],
            "virtual": copy.deepcopy(event["virtual"]),
            "first_def": copy.deepcopy(event["first_def"]),
            "source_attribution": copy.deepcopy(event["source_attribution"]),
            "live": copy.deepcopy(event["live"]),
            "degree": event.get("degree", 0),
            "flags": list(event.get("flags", [])),
            "coalesce": copy.deepcopy(
                event.get("coalesce", {"root_ig_id": event["ig_id"], "aliases": []})
            ),
            "simplify_order": event.get("simplify_order"),
            "select_order": event.get("select_order"),
            "assigned_phys": event.get("assigned_phys"),
            "spill": copy.deepcopy(event.get("spill", {"spilled": False, "reason": None})),
            "color_status": event.get("color_status", "uncolored"),
            "coalesced_into": event.get("coalesced_into"),
            "color_decision_ref": event.get("color_decision_ref"),
        }
        cls["nodes"].append(node)
        self.nodes_by_class[id(cls)][node["ig_id"]] = node

    def _apply_edge(self, cls: dict[str, Any], event: dict[str, Any]) -> None:
        cls["edges"].append(
            {
                "a": event["a"],
                "b": event["b"],
                "kind": event.get("kind", "interference"),
                "confidence": event.get("confidence", "observed"),
                "provenance": event.get("provenance", "interferencegraph"),
            }
        )

    def _apply_coalesce_mapping(self, cls: dict[str, Any], event: dict[str, Any]) -> None:
        mapping = {
            "alias": event["alias"],
            "root": event["root"],
            "root_phys": event.get("root_phys"),
            "confidence": event.get("confidence", "observed"),
            "provenance": event.get("provenance", "coalesce_alias"),
        }
        cls["coalesce"]["mappings"].append(mapping)

    def _apply_order(self, cls: dict[str, Any], event: dict[str, Any], field: str) -> None:
        order = list(event.get("order", []))
        cls[field] = order
        node_field = "simplify_order" if field == "simplify_order" else "select_order"
        nodes = self.nodes_by_class[id(cls)]
        for index, ig_id in enumerate(order):
            if ig_id in nodes:
                nodes[ig_id][node_field] = index

    def _apply_color_decision(self, cls: dict[str, Any], event: dict[str, Any]) -> None:
        decision = {
            key: copy.deepcopy(value)
            for key, value in event.items()
            if key not in {"event", "class_id", "class_name"}
        }
        cls["color_decisions"].append(decision)

        node = self.nodes_by_class[id(cls)].get(decision.get("ig_id"))
        if node is not None:
            node["assigned_phys"] = decision.get("assigned_phys")
            if decision.get("assigned_phys") is None and decision.get("spill", {}).get("spilled"):
                node["color_status"] = "spilled"
                node["spill"] = copy.deepcopy(decision["spill"])
            else:
                node["color_status"] = "colored"
            node["coalesced_into"] = None
            node["color_decision_ref"] = decision.get("id")

    def _apply_frame_state(self, event: dict[str, Any]) -> None:
        self.function["frame"] = {
            "base_size_bytes": event["base_size_bytes"],
            "call_args_size_bytes": event["call_args_size_bytes"],
            "objects": copy.deepcopy(event.get("objects", [])),
            "source_stage": event.get("source_stage", ""),
            "provenance": event.get("provenance", "frame_state"),
        }

    def _require_class(self, event: dict[str, Any], kind: str) -> dict[str, Any]:
        class_name = event.get("class_name")
        class_id = event.get("class_id")
        cls_by_name = self.classes_by_name.get(class_name) if class_name is not None else None
        cls_by_id = self.classes_by_id.get(class_id) if class_id is not None else None

        if class_name is not None and cls_by_name is None:
            raise ValueError(f"regclass must precede {kind}")
        if class_id is not None and cls_by_id is None:
            raise ValueError(f"regclass must precede {kind}")
        if cls_by_name is not None and cls_by_id is not None and cls_by_name is not cls_by_id:
            raise ValueError("class_name and class_id refer to different classes")
        if cls_by_name is not None:
            return cls_by_name
        if cls_by_id is not None:
            return cls_by_id
        raise ValueError(f"regclass must precede {kind}")

    def _finalize_coalesce(self) -> None:
        for cls in self.function["regalloc"]["classes"]:
            nodes = self.nodes_by_class[id(cls)]
            for mapping in cls["coalesce"]["mappings"]:
                alias = nodes.get(mapping["alias"])
                root = nodes.get(mapping["root"])
                if alias is None or root is None:
                    continue
                alias["coalesced_into"] = root["ig_id"]
                inherited_phys = mapping.get("root_phys")
                if inherited_phys is None:
                    inherited_phys = root.get("assigned_phys")
                alias["assigned_phys"] = inherited_phys
                alias["color_decision_ref"] = None
                alias["simplify_order"] = None
                alias["select_order"] = None
                alias["coalesce"]["root_ig_id"] = root["ig_id"]
                if inherited_phys is not None:
                    alias["color_status"] = "coalesced_alias"

                root["coalesce"].setdefault("aliases", [])
                if alias["ig_id"] not in root["coalesce"]["aliases"]:
                    root["coalesce"]["aliases"].append(alias["ig_id"])

    def _sort_pcode_passes(self) -> None:
        self.function["blocks"].sort(key=lambda block: block["order"])
        for pcode_pass in self.function["pcode"]["passes"]:
            pcode_pass["instructions"].sort(key=lambda inst: inst["order"])


def _default_function(source: dict[str, Any]) -> dict[str, Any]:
    name = source.get("function", "<unknown>")
    source_file = source.get("tu")
    return {
        "name": name,
        "identity": {
            "requested": name,
            "canonical_name": name,
            "symbol_name": name,
            "source_name": name,
            "aliases": [],
            "source_file": source_file,
        },
        "blocks": [],
        "pcode": {
            "passes": [],
            "instruction_identity_note": "instruction ids are stable only within this trace",
        },
        "regalloc": {
            "classes": [],
        },
    }
