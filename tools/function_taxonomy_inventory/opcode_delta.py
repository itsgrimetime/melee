"""Stable, evidence-only opcode deltas derived from checkdiff payloads."""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from itertools import zip_longest
import json
import re

from tools.function_taxonomy_schema import SEMANTIC_DELTA_FAMILY_ORDER


MAX_DOMINANT_OPCODE_PAIRS = 3

_COMMENT_PREFIX = re.compile(r"^/\*.*?\*/\s*")
_ADDRESS_PREFIX = re.compile(r"^(?:\+?[0-9a-fA-F]+|0x[0-9a-fA-F]+):\s*")
_MACHINE_CODE_PREFIX = re.compile(r"^(?:[0-9a-fA-F]{2}\s+){4}")
_LABEL_PREFIX = re.compile(r"^(?:<[^>]+>|[^\s:]+):")
_OPCODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*")

_ADDRESS_CONSTANT_OPCODES = {"add", "addi", "addis", "la", "li", "lis", "mr"}
_INTEGER_WIDTH_OPCODES = {
    "clrlwi",
    "clrrwi",
    "extsb",
    "extsh",
    "extsw",
    "mulli",
    "rlwimi",
    "rlwinm",
    "slw",
    "slwi",
    "srawi",
    "srw",
    "srwi",
    "xoris",
}
_FLOAT_MEMORY_OPCODES = {
    "lfs",
    "lfsu",
    "lfsx",
    "lfsux",
    "lfd",
    "lfdu",
    "lfdx",
    "lfdux",
    "stfs",
    "stfsu",
    "stfsx",
    "stfsux",
    "stfd",
    "stfdu",
    "stfdx",
    "stfdux",
}
_INTEGER_MEMORY_OPCODES = {
    "lbz",
    "lbzu",
    "lbzx",
    "lbzux",
    "lhz",
    "lhzu",
    "lhzx",
    "lhzux",
    "lha",
    "lhau",
    "lhax",
    "lhaux",
    "lwz",
    "lwzu",
    "lwzx",
    "lwzux",
    "stb",
    "stbu",
    "stbx",
    "stbux",
    "sth",
    "sthu",
    "sthx",
    "sthux",
    "stw",
    "stwu",
    "stwx",
    "stwux",
}
_INDEXED_UPDATE_MEMORY_OPCODES = {
    opcode
    for opcode in _INTEGER_MEMORY_OPCODES | _FLOAT_MEMORY_OPCODES
    if opcode.endswith(("u", "x", "ux"))
}
_FRAME_SAVE_OPCODES = {"stwu", "lmw", "stmw", "mflr", "mtlr"}
_BRANCH_REGISTER_OPCODES = {"mtctr", "mfctr", "mtlr", "mflr"}
_TRIGGER_LINE_LABEL = {1: "one-line", 2: "two-line", 3: "three-line"}


def _asm_lines(value: object, side: str) -> tuple[list[str] | None, str | None]:
    if value is None:
        return None, f"missing-{side}-asm"
    if isinstance(value, str):
        return value.splitlines(), None
    if isinstance(value, (list, tuple)) and all(isinstance(line, str) for line in value):
        return list(value), None
    return None, f"invalid-{side}-asm"


def _opcode_from_checkdiff_line(line: str) -> str | None:
    text = line.strip()
    text = _COMMENT_PREFIX.sub("", text).strip()
    text = _ADDRESS_PREFIX.sub("", text).strip()
    text = _MACHINE_CODE_PREFIX.sub("", text).strip()
    if not text or _LABEL_PREFIX.match(text):
        return None
    token = _OPCODE.match(text)
    if token is None:
        return None
    opcode = token.group(0).lower()
    if opcode.startswith("r_ppc_") or opcode.startswith("."):
        return None
    return opcode


def _normalized_opcodes(lines: list[str]) -> list[str]:
    return [opcode for line in lines if (opcode := _opcode_from_checkdiff_line(line))]


def _delta_pairs(expected: list[str], current: list[str]) -> list[tuple[str | None, str | None]]:
    pairs: list[tuple[str | None, str | None]] = []
    matcher = SequenceMatcher(None, expected, current, autojunk=False)
    for tag, expected_start, expected_end, current_start, current_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        pairs.extend(
            zip_longest(
                expected[expected_start:expected_end],
                current[current_start:current_end],
                fillvalue=None,
            )
        )
    return pairs


def _pair_sort_key(pair: tuple[str | None, str | None]) -> tuple[str, str]:
    return (pair[0] or "", pair[1] or "")


def _opcode_alignment(
    target_asm: object, current_asm: object
) -> tuple[str, list[tuple[str | None, str | None]]]:
    target_lines, target_status = _asm_lines(target_asm, "target")
    if target_status is not None:
        return target_status, []
    current_lines, current_status = _asm_lines(current_asm, "current")
    if current_status is not None:
        return current_status, []

    expected = _normalized_opcodes(target_lines or [])
    current = _normalized_opcodes(current_lines or [])
    if not expected and not current:
        return "empty-normalized-opcode-stream", []
    pairs = _delta_pairs(expected, current)
    if not pairs:
        return "no-opcode-delta", []
    return "available", pairs


def _legacy_signature(pairs: list[tuple[str | None, str | None]]) -> str:
    counts = Counter(pairs)
    dominant = [
        [pair[0], pair[1], count]
        for pair, count in sorted(
            counts.items(), key=lambda item: (-item[1], *_pair_sort_key(item[0]))
        )[:MAX_DOMINANT_OPCODE_PAIRS]
    ]
    signature = json.dumps(
        {"dominant": dominant, "first": list(pairs[0]), "version": 1},
        sort_keys=True,
        separators=(",", ":"),
    )
    return signature


def _semantic_delta_families(
    pairs: list[tuple[str | None, str | None]],
) -> list[str]:
    matched: set[str] = set()
    for raw_opcode in (
        opcode for pair in pairs for opcode in pair if opcode is not None
    ):
        base_opcode = raw_opcode.removesuffix(".")
        if base_opcode in _ADDRESS_CONSTANT_OPCODES:
            matched.add("address-constant-materialization")
        if base_opcode in _INTEGER_WIDTH_OPCODES:
            matched.add("integer-width-bitfield-scale")
        if base_opcode.startswith("f") or base_opcode in _FLOAT_MEMORY_OPCODES:
            matched.add("floating-point-expression-storage")
        if (
            base_opcode.startswith(("b", "cmp", "cmpl", "fcmp", "cr"))
            or base_opcode in _BRANCH_REGISTER_OPCODES
            or raw_opcode.endswith(".")
        ):
            matched.add("branch-predicate-control")
        if base_opcode in _INDEXED_UPDATE_MEMORY_OPCODES:
            matched.add("indexed-update-memory")
        if base_opcode in _FRAME_SAVE_OPCODES:
            matched.add("frame-save-window")
        if base_opcode in _INTEGER_MEMORY_OPCODES:
            matched.add("integer-memory-width-transfer")
    if pairs and not matched:
        matched.add("other-opcode-sequence")
    return [family for family in SEMANTIC_DELTA_FAMILY_ORDER if family in matched]


def _opcode_edit_direction(
    pairs: list[tuple[str | None, str | None]],
) -> str:
    kinds = {
        "current-extra"
        if expected is None
        else "reference-extra"
        if current is None
        else "substitution"
        for expected, current in pairs
    }
    return next(iter(kinds)) if len(kinds) == 1 else "mixed"


def _trigger_fields(
    *,
    status: str,
    pairs: list[tuple[str | None, str | None]],
    direction: str,
    normalized_diff_lines: object,
) -> dict[str, object]:
    if type(normalized_diff_lines) is not int or normalized_diff_lines not in (1, 2, 3):
        return {}
    if status not in {"available", "no-opcode-delta"}:
        return {
            "normalized_trigger_signature_status": status,
            "normalized_trigger_signature": "",
            "normalized_trigger_family": "",
        }
    if not pairs:
        direction = "operand-shape-only"
    signature = json.dumps(
        {
            "edit_direction": direction,
            "normalized_diff_lines": normalized_diff_lines,
            "pairs": [list(pair) for pair in pairs],
            "version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "normalized_trigger_signature_status": "available",
        "normalized_trigger_signature": signature,
        "normalized_trigger_family": (
            f"{_TRIGGER_LINE_LABEL[normalized_diff_lines]}-{direction}"
        ),
    }


def derive_opcode_delta_evidence(
    target_asm: object,
    current_asm: object,
    *,
    normalized_diff_lines: object = None,
) -> dict[str, object]:
    """Return structured opcode-presence evidence without asserting a cause."""
    status, pairs = _opcode_alignment(target_asm, current_asm)
    signature = _legacy_signature(pairs) if status == "available" else ""
    families = _semantic_delta_families(pairs)
    direction = _opcode_edit_direction(pairs) if pairs else ""
    trigger_fields = _trigger_fields(
        status=status,
        pairs=pairs,
        direction=direction,
        normalized_diff_lines=normalized_diff_lines,
    )
    if trigger_fields and not pairs and status == "no-opcode-delta":
        direction = "operand-shape-only"
    return {
        "opcode_delta_signature_status": status,
        "opcode_delta_signature": signature,
        "semantic_delta_families": families,
        "opcode_edit_direction": direction,
        **trigger_fields,
    }


def derive_opcode_delta_signature(target_asm: object, current_asm: object) -> dict[str, str]:
    """Return v1 opcode evidence; never infer a source-level root cause."""
    evidence = derive_opcode_delta_evidence(target_asm, current_asm)
    return {
        "opcode_delta_signature_status": str(
            evidence["opcode_delta_signature_status"]
        ),
        "opcode_delta_signature": str(evidence["opcode_delta_signature"]),
    }
