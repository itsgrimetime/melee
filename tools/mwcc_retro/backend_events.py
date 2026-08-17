"""Normalize mwcc-retro backend events into canonical trace collections."""

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

_AREA_ORDER = {name: index for index, name in enumerate(("arguments", "locals", "temps", "spill-owned"))}
_OBJECT_STAGE_ORDER = {"colorgraph_return": 0, "final_scheduler": 1}
_PCODE_STAGE_ORDER = {"allocator_input": 0, "mutation_output": 1, "code_emission": 2}
_CLASS_ORDER = {"gpr": 0, "fpr": 1}
_ALLOCATION_STATE_ORDER = {"virtual": 0, "physical": 1, "non-allocator": 2}


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
    schema_version: str = backend_schema.SCHEMA_VERSION_V1,
) -> dict[str, Any]:
    if schema_version == backend_schema.SCHEMA_VERSION_V2:
        raise ValueError("backend trace v2 events require the proof-bearing v2 assembler")
    if schema_version != backend_schema.SCHEMA_VERSION_V1:
        raise ValueError(f"unsupported backend trace schema {schema_version!r}")
    normalizer = _Normalizer(compiler=compiler, source=source, tool_version=tool_version)
    return normalizer.normalize(events)


def _sort_rows(value: object, key) -> None:
    if not isinstance(value, list):
        return
    try:
        value.sort(key=key)
    except (KeyError, TypeError, ValueError):
        # Structural validators own malformed rows. Normalization must not turn
        # an attacker-controlled comparison failure into a producer crash.
        return


def _sort_strings(value: object, *, order: dict[str, int] | None = None) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return
    if order is None:
        value.sort()
    else:
        value.sort(key=lambda item: (order.get(item, len(order)), item))


def _canonicalize_proof(proof: object) -> None:
    if not isinstance(proof, dict):
        return
    for field in ("allocation_sites", "free_sites"):
        _sort_rows(
            proof.get(field),
            lambda row: (row["entity_kind"], row["address"], row["site_id"]),
        )
    for field in (
        "operand_rewrite_sites",
        "operand_mutation_sites",
        "code_emission_sites",
    ):
        _sort_rows(proof.get(field), lambda row: (row["address"], row["site_id"]))
    operand_rules = proof.get("operand_rules")
    _sort_rows(
        operand_rules,
        lambda row: (row["opcode_id"], row["descriptor_index"]),
    )
    if isinstance(operand_rules, list):
        for descriptor in operand_rules:
            if not isinstance(descriptor, dict):
                continue
            _sort_rows(
                descriptor.get("role_rules"),
                lambda row: (
                    row["register_flags_mask"],
                    row["register_flags_value"],
                    row["role"],
                ),
            )
            _sort_rows(
                descriptor.get("state_rules"),
                lambda row: (
                    _PCODE_STAGE_ORDER[row["capture_stage"]],
                    row["register_flags_mask"],
                    row["register_flags_value"],
                    row["register_value_min"],
                    row["register_value_max"],
                    _ALLOCATION_STATE_ORDER[row["allocation_state"]],
                ),
            )
    _sort_rows(proof.get("opcode_table"), lambda row: row["opcode_id"])


def _canonicalize_pcode_instruction(row: object) -> None:
    if not isinstance(row, dict):
        return
    snapshots = row.get("stage_snapshots")
    _sort_rows(snapshots, lambda item: _PCODE_STAGE_ORDER[item["stage"]])
    if isinstance(snapshots, list):
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            _sort_rows(
                snapshot.get("operand_lineage_inventory"),
                lambda item: item["operand_index"],
            )
            _sort_rows(
                snapshot.get("parsed_register_operands"),
                lambda item: (
                    item["operand_index"],
                    item["role"],
                    item["class_id"],
                    item["raw_arg_kind_id"],
                    item["raw_register_flags"],
                ),
            )
    ranges = row.get("code_ranges")
    _sort_rows(ranges, lambda item: (item["start"], item["end_exclusive"], item["bytes"]))
    if isinstance(ranges, list):
        for code_range in ranges:
            if not isinstance(code_range, dict):
                continue
            _sort_rows(
                code_range.get("relocations"),
                lambda item: (
                    item["offset_within_range"],
                    item["relocation_type_id"],
                    item["target_symbol_table_index"],
                    item["addend"],
                ),
            )
            _sort_rows(
                code_range.get("machine_operand_mappings"),
                lambda item: (
                    item["instruction_offset_within_range"],
                    item["machine_operand_position"],
                    item["emission_pcode_operand_index"],
                    item["operand_lineage_id"],
                ),
            )


def _canonicalize_lineage_event(row: object) -> None:
    if not isinstance(row, dict):
        return
    for side in ("inputs", "outputs"):
        states = row.get(side)
        _sort_rows(
            states,
            lambda item: (
                item["pcode_id"],
                item["runtime_address"],
                item["allocation_generation"],
            ),
        )
        if not isinstance(states, list):
            continue
        for state in states:
            if not isinstance(state, dict):
                continue
            operands = state.get("operands")
            _sort_rows(operands, lambda item: item["operand_index"])
            if isinstance(operands, list):
                for operand in operands:
                    if isinstance(operand, dict):
                        _sort_strings(operand.get("parent_lineage_ids"))


def canonicalize_v2_object_bindings(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a detached Phase-1 object-binding payload in normative array order."""

    normalized = copy.deepcopy(payload)
    _canonicalize_proof(normalized.get("lifetime_proof"))
    _sort_rows(normalized.get("lifecycle_events"), lambda row: row["sequence"])

    objects = normalized.get("objects")
    _sort_rows(objects, lambda row: (row["runtime_address"], row["allocation_generation"]))
    if isinstance(objects, list):
        for row in objects:
            if not isinstance(row, dict):
                continue
            _sort_strings(row.get("areas"), order=_AREA_ORDER)
            _sort_rows(
                row.get("stage_snapshots"),
                lambda item: _OBJECT_STAGE_ORDER[item["stage"]],
            )

    _sort_rows(
        normalized.get("virtual_bindings"),
        lambda row: (
            row["object_id"],
            row["class_id"],
            row["virtual_kind"],
            row["virtual"],
            row["ig_id"],
            row["ignode_runtime_address"],
        ),
    )
    frame_bindings = normalized.get("frame_bindings")
    _sort_rows(
        frame_bindings,
        lambda row: (
            row["object_id"],
            _AREA_ORDER[row["area"]],
            row["list_node_runtime_address"],
            row["final_r1_offset"],
        ),
    )
    if isinstance(frame_bindings, list):
        for row in frame_bindings:
            if isinstance(row, dict):
                _sort_strings(row.get("provenance"))

    instructions = normalized.get("pcode_instructions")
    _sort_rows(
        instructions,
        lambda row: (row["runtime_address"], row["allocation_generation"]),
    )
    if isinstance(instructions, list):
        for row in instructions:
            _canonicalize_pcode_instruction(row)

    _sort_rows(
        normalized.get("pcode_occurrences"),
        lambda row: (row["pcode_event_sequence"], row["pcode_id"], row["operand_index"]),
    )
    lineage = normalized.get("pcode_operand_lineage_events")
    _sort_rows(lineage, lambda row: row["pcode_event_sequence"])
    if isinstance(lineage, list):
        for row in lineage:
            _canonicalize_lineage_event(row)

    coverage = normalized.get("coverage")
    if isinstance(coverage, dict):
        _sort_strings(coverage.get("frame_areas"), order=_AREA_ORDER)
        _sort_strings(coverage.get("ig_classes"), order=_CLASS_ORDER)
        _sort_strings(coverage.get("errors"))
        lifetime = coverage.get("lifetime_identity")
        if isinstance(lifetime, dict):
            _sort_strings(lifetime.get("errors"))
        pcode = coverage.get("pcode_instrumentation")
        if isinstance(pcode, dict):
            _sort_strings(pcode.get("errors"))
    return normalized


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
