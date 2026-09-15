import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_colorgraph_trace  # noqa: E402


def _mask(regs: list[int]) -> int:
    value = 0
    for reg in regs:
        value |= 1 << reg
    return value


def _select_start(decision_id: str = "gpr-c0") -> dict[str, object]:
    return {
        "event": "colorgraph_select_start",
        "id": decision_id,
        "class_id": 0,
        "class_name": "gpr",
        "iter": 0,
        "ig_id": 32,
        "available_mask": _mask([3]),
        "node_state_before_select": {
            "precolored": False,
            "coalesced": False,
            "spill_marked": False,
            "rematerialized": False,
        },
        "reserved_or_precolored_filtered": [0, 1, 2],
        "volatile_pool_before": [3],
        "nonvolatile_dispense_before": {"next": None, "remaining": []},
    }


def _candidates_ready(decision_id: str = "gpr-c0") -> dict[str, object]:
    return {
        "event": "colorgraph_candidates_ready",
        "id": decision_id,
        "candidate_mask": _mask([3]),
        "blocked_candidates": [],
    }


def _assignment(decision_id: str = "gpr-c0") -> dict[str, object]:
    return {
        "event": "colorgraph_assignment",
        "id": decision_id,
        "assigned_phys": 3,
        "chosen_source": "volatile_pool",
        "volatile_pool_after": [],
        "nonvolatile_dispense_after": {"next": None, "remaining": []},
        "tie_rule": "first_volatile_available",
        "decision_rule": "lowest_available_or_nonvolatile_dispense",
    }


def test_assemble_internal_colorgraph_events_emits_complete_color_decision() -> None:
    raw = [
        {
            "event": "colorgraph_select_start",
            "id": "gpr-c0",
            "class_id": 0,
            "class_name": "gpr",
            "iter": 0,
            "ig_id": 32,
            "available_mask": _mask([0, 3, 4, 5]),
            "node_state_before_select": {
                "precolored": False,
                "coalesced": False,
                "spill_marked": False,
                "rematerialized": False,
            },
            "reserved_or_precolored_filtered": [1, 2],
            "volatile_pool_before": [0, 3, 4, 5],
            "nonvolatile_dispense_before": {"next": 31, "remaining": [31, 30, 29]},
        },
        {
            "event": "colorgraph_candidates_ready",
            "id": "gpr-c0",
            "candidate_mask": _mask([0, 4, 5]),
            "blocked_candidates": [
                {
                    "phys": 3,
                    "reason": "interferer-assigned-phys",
                    "holder_ig_id": 33,
                    "holder_assigned_phys": 3,
                    "provenance": "colorgraph_neighbor_scan",
                }
            ],
        },
        {
            "event": "colorgraph_assignment",
            "id": "gpr-c0",
            "assigned_phys": 0,
            "chosen_source": "volatile_pool",
            "volatile_pool_after": [3, 4, 5],
            "nonvolatile_dispense_after": {"consumed": None, "remaining": [31, 30, 29]},
            "tie_rule": "first_volatile_available",
            "decision_rule": "lowest_available_or_nonvolatile_dispense",
        },
    ]

    [decision] = backend_colorgraph_trace.assemble_color_decisions(raw)

    assert decision == {
        "event": "color_decision",
        "class_id": 0,
        "class_name": "gpr",
        "id": "gpr-c0",
        "ig_id": 32,
        "iter": 0,
        "assigned_phys": 0,
        "node_state_before_select": {
            "precolored": False,
            "coalesced": False,
            "spill_marked": False,
            "rematerialized": False,
        },
        "reserved_or_precolored_filtered": [1, 2],
        "available_phys_ordered": [0, 3, 4, 5],
        "blocked_candidates": [
            {
                "phys": 3,
                "reason": "interferer-assigned-phys",
                "holder_ig_id": 33,
                "holder_assigned_phys": 3,
                "provenance": "colorgraph_neighbor_scan",
            }
        ],
        "candidate_phys_ordered": [0, 4, 5],
        "chosen_source": "volatile_pool",
        "volatile_pool_before": [0, 3, 4, 5],
        "volatile_pool_after": [3, 4, 5],
        "nonvolatile_dispense_before": {"next": 31, "remaining": [31, 30, 29]},
        "nonvolatile_dispense_after": {"consumed": None, "remaining": [31, 30, 29]},
        "tie_rule": "first_volatile_available",
        "blocked_by": [{"ig_id": 33, "phys": 3}],
        "decision_rule": "lowest_available_or_nonvolatile_dispense",
        "confidence": "observed-internal",
        "provenance": "retail-colorgraph-internal",
        "source_stage": "colorgraph",
    }


def test_assemble_internal_colorgraph_events_uses_nonvolatile_candidates_when_mask_empty() -> None:
    raw = [
        {
            "event": "colorgraph_select_start",
            "id": "gpr-c0",
            "class_id": 0,
            "class_name": "gpr",
            "iter": 0,
            "ig_id": 32,
            "available_mask": 0,
            "node_state_before_select": {
                "precolored": False,
                "coalesced": False,
                "spill_marked": False,
                "rematerialized": False,
            },
            "reserved_or_precolored_filtered": [1, 2],
            "volatile_pool_before": [],
            "nonvolatile_dispense_before": {"next": 31, "remaining": [31, 30, 29]},
        },
        {
            "event": "colorgraph_candidates_ready",
            "id": "gpr-c0",
            "candidate_mask": 0,
            "blocked_candidates": [],
        },
        {
            "event": "colorgraph_assignment",
            "id": "gpr-c0",
            "assigned_phys": 31,
            "chosen_source": "nonvolatile_dispense",
            "volatile_pool_after": [],
            "nonvolatile_dispense_after": {"consumed": 31, "remaining": [30, 29]},
            "tie_rule": "top_down_nonvolatile_dispense",
            "decision_rule": "lowest_available_or_nonvolatile_dispense",
        },
    ]

    [decision] = backend_colorgraph_trace.assemble_color_decisions(raw)

    assert decision["candidate_phys_ordered"] == [31, 30, 29]
    assert decision["assigned_phys"] == 31
    assert decision["chosen_source"] == "nonvolatile_dispense"


def test_assemble_internal_colorgraph_events_keeps_nonvolatile_assignment_when_pool_state_is_partial() -> None:
    raw = [
        {
            "event": "colorgraph_select_start",
            "id": "gpr-c0",
            "class_id": 0,
            "class_name": "gpr",
            "iter": 0,
            "ig_id": 41,
            "available_mask": _mask([0, 3, 4]),
            "node_state_before_select": {
                "precolored": False,
                "coalesced": False,
                "spill_marked": False,
                "rematerialized": False,
            },
            "reserved_or_precolored_filtered": [1, 2],
            "volatile_pool_before": [0, 3, 4],
            "nonvolatile_dispense_before": {"next": None, "remaining": []},
        },
        {
            "event": "colorgraph_candidates_ready",
            "id": "gpr-c0",
            "candidate_mask": 0,
            "blocked_candidates": [
                {
                    "phys": 0,
                    "reason": "interferer-assigned-phys",
                    "holder_ig_id": 0,
                    "holder_assigned_phys": 0,
                    "provenance": "colorgraph_neighbor_scan",
                }
            ],
        },
        {
            "event": "colorgraph_assignment",
            "id": "gpr-c0",
            "assigned_phys": 31,
            "chosen_source": "nonvolatile_dispense",
            "volatile_pool_after": [0, 3, 4],
            "nonvolatile_dispense_after": {"consumed": 31, "remaining": []},
            "tie_rule": "top_down_nonvolatile_dispense",
            "decision_rule": "lowest_available_or_nonvolatile_dispense",
        },
    ]

    [decision] = backend_colorgraph_trace.assemble_color_decisions(raw)

    assert decision["candidate_phys_ordered"] == [31]
    assert decision["assigned_phys"] == 31
    assert decision["blocked_by"] == [{"ig_id": 0, "phys": 0}]


def test_assemble_internal_colorgraph_events_handles_spill_terminal() -> None:
    raw = [
        {
            "event": "colorgraph_select_start",
            "id": "gpr-c0",
            "class_id": 0,
            "class_name": "gpr",
            "iter": 0,
            "ig_id": 32,
            "available_mask": 0,
            "node_state_before_select": {
                "precolored": False,
                "coalesced": False,
                "spill_marked": False,
                "rematerialized": False,
            },
            "reserved_or_precolored_filtered": [0, 1, 2],
            "volatile_pool_before": [],
            "nonvolatile_dispense_before": {"next": None, "remaining": []},
        },
        {
            "event": "colorgraph_candidates_ready",
            "id": "gpr-c0",
            "candidate_mask": 0,
            "blocked_candidates": [],
        },
        {
            "event": "colorgraph_spill",
            "id": "gpr-c0",
            "reason": "no_available_color",
        },
    ]

    [decision] = backend_colorgraph_trace.assemble_color_decisions(raw)

    assert decision["assigned_phys"] is None
    assert decision["candidate_phys_ordered"] == []
    assert decision["chosen_source"] == "spill"
    assert decision["decision_rule"] == "spill_no_available_color"
    assert decision["spill"] == {"spilled": True, "reason": "no_available_color"}


def test_assemble_internal_colorgraph_events_rejects_incomplete_decision() -> None:
    with pytest.raises(ValueError, match="missing colorgraph_candidates_ready"):
        backend_colorgraph_trace.assemble_color_decisions([_select_start()])


def test_assemble_internal_colorgraph_events_rejects_terminal_before_candidates() -> None:
    with pytest.raises(
        ValueError,
        match="colorgraph_assignment before colorgraph_candidates_ready gpr-c0",
    ):
        backend_colorgraph_trace.assemble_color_decisions(
            [_select_start(), _assignment()]
        )


def test_assemble_internal_colorgraph_events_rejects_candidates_after_terminal() -> None:
    with pytest.raises(
        ValueError,
        match="colorgraph_candidates_ready after terminal colorgraph event gpr-c0",
    ):
        backend_colorgraph_trace.assemble_color_decisions(
            [_select_start(), _candidates_ready(), _assignment(), _candidates_ready()]
        )
