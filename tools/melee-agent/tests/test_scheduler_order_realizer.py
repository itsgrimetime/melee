from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.mwcc_debug.scheduler_order_realizer import (
    SchedulerOrderTarget,
    evaluate_scheduler_order_in_asm,
    parse_scheduler_order_target,
)


def _mixed_target_payload() -> dict:
    return {
        "kind": "scheduler-order-target",
        "function": "fn_80000000",
        "target_first": {
            "opcode": "mr",
            "operands_contains": "r30,r31",
            "code_offset": "0x124",
        },
        "target_second": {
            "opcode": "lfd",
            "operands_contains": "lbl_804DC000",
            "code_offset": "0x120",
        },
        "desired_order": ["target_first", "target_second"],
    }


def test_scheduler_order_target_accepts_mixed_opcode_pair() -> None:
    target = parse_scheduler_order_target(_mixed_target_payload())

    assert isinstance(target, SchedulerOrderTarget)
    assert target.function == "fn_80000000"
    assert target.target_first.opcode == "mr"
    assert target.target_second.opcode == "lfd"
    assert target.target_first.code_offset == 0x124
    assert target.target_second.code_offset == 0x120
    assert target.desired_order == ("target_first", "target_second")


def test_scheduler_order_target_accepts_json_string_and_path(tmp_path: Path) -> None:
    payload = _mixed_target_payload()
    payload["target_second"]["code_offset"] = 288
    path = tmp_path / "target.json"
    path.write_text(json.dumps(payload))

    from_string = parse_scheduler_order_target(json.dumps(payload))
    from_path = parse_scheduler_order_target(str(path))

    assert from_string.target_second.code_offset == 288
    assert from_path.target_second.code_offset == 288


def test_scheduler_order_target_defaults_desired_order_and_validates_kind() -> None:
    payload = _mixed_target_payload()
    payload.pop("desired_order")

    target = parse_scheduler_order_target(payload)

    assert target.desired_order == ("target_first", "target_second")
    with pytest.raises(ValueError, match="kind"):
        parse_scheduler_order_target({**payload, "kind": "not-scheduler"})
    with pytest.raises(ValueError, match="desired_order"):
        parse_scheduler_order_target({**payload, "desired_order": [["target_first"], "target_second"]})


def test_scheduler_order_target_requires_function_and_exactly_two_targets() -> None:
    payload = _mixed_target_payload()

    with pytest.raises(ValueError, match="function"):
        parse_scheduler_order_target({k: v for k, v in payload.items() if k != "function"})
    with pytest.raises(ValueError, match="target_second"):
        parse_scheduler_order_target({
            "kind": "scheduler-order-target",
            "function": "fn_80000000",
            "target_first": payload["target_first"],
        })


def test_scheduler_order_asm_predicate_reports_target_and_observed_order() -> None:
    target = parse_scheduler_order_target(_mixed_target_payload())
    current = [
        "<fn_80000000>:",
        "+120: cb e2 c6 20 \tlfd     f31,lbl_804DC000(r2)",
        "+124: 7f fe fb 78 \tmr      r30,r31",
    ]
    target_like = [
        "<fn_80000000>:",
        "+124: 7f fe fb 78 \tmr      r30,r31",
        "+120: cb e2 c6 20 \tlfd     f31,lbl_804DC000(r2)",
    ]

    assert evaluate_scheduler_order_in_asm(current, target).status == "observed-order"
    assert evaluate_scheduler_order_in_asm(target_like, target).status == "target-order"


def test_scheduler_order_asm_predicate_reports_missing_and_ambiguous() -> None:
    no_lfd = [
        "+124: 7f fe fb 78 \tmr      r30,r31",
        "+128: 38 00 00 00 \tli      r0,0",
    ]
    repeated = [
        "+120: cb e2 c6 20 \tlfd     f31,lbl_804DC000(r2)",
        "+124: 7f fe fb 78 \tmr      r30,r31",
        "+128: 7f fe fb 78 \tmr      r30,r31",
    ]
    target_without_offsets = parse_scheduler_order_target({
        "kind": "scheduler-order-target",
        "function": "fn_80000000",
        "target_first": {"opcode": "mr", "operands_contains": "r30,r31"},
        "target_second": {"opcode": "lfd", "operands_contains": "lbl_804DC000"},
    })

    assert evaluate_scheduler_order_in_asm(no_lfd, target_without_offsets).status == "missing"
    assert evaluate_scheduler_order_in_asm(repeated, target_without_offsets).status == "ambiguous"


def test_scheduler_order_asm_predicate_respects_explicit_desired_order() -> None:
    target = parse_scheduler_order_target({
        "kind": "scheduler-order-target",
        "function": "fn_80000000",
        "target_first": {"opcode": "mr", "operands_contains": "r30,r31"},
        "target_second": {"opcode": "lfd", "operands_contains": "lbl_804DC000"},
        "desired_order": ["target_second", "target_first"],
    })
    lines = [
        "+120: cb e2 c6 20 \tlfd     f31,lbl_804DC000(r2)",
        "+124: 7f fe fb 78 \tmr      r30,r31",
    ]

    assert evaluate_scheduler_order_in_asm(lines, target).status == "target-order"
