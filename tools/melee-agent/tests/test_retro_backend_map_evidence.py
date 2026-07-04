import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro.backend_map_evidence import classify_probe_evidence  # noqa: E402

PROMOTABLE_FROM_LIVE_PROBE = {
    "codegen_start",
    "codegen_end",
    "pcbasicblocks",
    "interference_matrix",
    "coalesce_alias",
    "interferencegraph",
    "n_ignodes",
    "build_interference_matrix",
    "real_coalesce",
    "build_adjacency_vectors",
    "simplifygraph",
    "colorgraph",
}

NOT_PROMOTABLE_FROM_CURRENT_PROBE = {
    "pcode_pass_boundary",
    "backend_block_list",
    "used_vreg_gpr",
    "used_vreg_fpr",
    "frame_locals",
    "final_scheduler",
}


def _fixture_payload():
    candidates = {
        "codegen_start": 0x4351C0,
        "codegen_end": 0x435DB9,
        "build_interference_matrix": 0x531290,
        "real_coalesce": 0x530E00,
        "build_adjacency_vectors": 0x530C00,
        "simplifygraph": 0x4CE400,
        "colorgraph": 0x4CE2D0,
    }

    def globals_sample(**overrides):
        sample = {
            "pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C},
            "interference_matrix": {"va": 0x583088, "u32": 0x6501FC},
            "coalesce_alias": {"va": 0x58308C, "u32": 0x650254},
            "interferencegraph": {"va": 0x587E3C, "u32": 0x65029C},
            "n_ignodes": {"va": 0x587190, "u32": 4},
        }
        sample.update(overrides)
        return sample

    ig_sample = [
        {
            "slot": 0,
            "ptr": 0x65036C,
            "next": 0x6503C4,
            "ig_idx": 0,
            "degree": 2,
            "assignedReg": -1,
            "flags": 0,
            "arraySize": 2,
            "neighbors_sample": [1, 2],
        },
        {
            "slot": 1,
            "ptr": 0x6503C4,
            "next": 0,
            "ig_idx": 1,
            "degree": 1,
            "assignedReg": -1,
            "flags": 8,
            "arraySize": 1,
            "neighbors_sample": [0],
        },
    ]

    events = [
        {
            "stage": "codegen_start",
            "pc": candidates["codegen_start"],
            "globals": globals_sample(
                pcbasicblocks={"va": 0x587C74, "u32": 0},
                interference_matrix={"va": 0x583088, "u32": 0},
                coalesce_alias={"va": 0x58308C, "u32": 0},
                interferencegraph={"va": 0x587E3C, "u32": 0},
                n_ignodes={"va": 0x587190, "u32": 0},
            ),
        },
        {
            "stage": "build_interference_matrix",
            "pc": candidates["build_interference_matrix"],
            "globals": globals_sample(interference_matrix={"va": 0x583088, "u32": 0}),
        },
        {
            "stage": "real_coalesce",
            "pc": candidates["real_coalesce"],
            "globals": globals_sample(coalesce_alias={"va": 0x58308C, "u32": 0}),
        },
        {
            "stage": "build_adjacency_vectors",
            "pc": candidates["build_adjacency_vectors"],
            "globals": globals_sample(interferencegraph={"va": 0x587E3C, "u32": 0}),
        },
        {
            "stage": "simplifygraph",
            "pc": candidates["simplifygraph"],
            "globals": globals_sample(),
            "ig_sample": ig_sample,
        },
        {
            "stage": "colorgraph",
            "pc": candidates["colorgraph"],
            "globals": globals_sample(),
            "ig_sample": ig_sample,
        },
        {
            "stage": "codegen_end",
            "pc": candidates["codegen_end"],
            "globals": globals_sample(),
            "ig_sample": ig_sample,
        },
    ]
    return {
        "schema_version": "mwcc-retro-backend-map-probe.v1",
        "requested_function": "test_fn",
        "requested_function_matched": True,
        "errors": [],
        "candidates": candidates,
        "globals": {
            "pcbasicblocks": 0x587C74,
            "interference_matrix": 0x583088,
            "coalesce_alias": 0x58308C,
            "interferencegraph": 0x587E3C,
            "n_ignodes": 0x587190,
        },
        "events": events,
    }


def test_live_probe_fixture_classifies_only_explicit_invariants_as_promotable():
    result = classify_probe_evidence(_fixture_payload())

    assert set(result["promotable_entries"]) == PROMOTABLE_FROM_LIVE_PROBE
    for key, entry in result["promotable_entries"].items():
        assert entry["confidence"] == "live-invariant"
        assert isinstance(entry["va"], int)
        assert entry["va"] > 0

    assert set(NOT_PROMOTABLE_FROM_CURRENT_PROBE) <= set(result["blocked_entries"])
    assert "PCode" in result["blocked_structs"]
    assert "PCode" not in result["promotable_structs"]
    assert result["promotable_structs"]["IGNode"]["confidence"] == "live-invariant"
    assert result["promotable_structs"]["IGNode"]["fields"] == {
        "next": 0x00,
        "ig_idx": 0x0C,
        "degree": 0x0E,
        "assignedReg": 0x10,
        "flags": 0x12,
        "arraySize": 0x14,
        "array": 0x16,
    }


def test_unmatched_function_blocks_all_promotions():
    payload = _fixture_payload()
    payload["requested_function_matched"] = False

    result = classify_probe_evidence(payload)

    assert result["promotable_entries"] == {}
    assert result["promotable_structs"] == {}
    assert (
        result["blocked_entries"]["codegen_start"]["reason"]
        == "requested function was not matched"
    )
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "requested function was not matched"
    )


def test_payload_errors_block_all_promotions():
    payload = _fixture_payload()
    payload["errors"] = [{"stage": "simplifygraph", "error": "cannot read memory"}]

    result = classify_probe_evidence(payload)

    assert result["promotable_entries"] == {}
    assert result["promotable_structs"] == {}
    assert (
        "payload reported errors"
        in result["blocked_entries"]["codegen_start"]["reason"]
    )
    assert "payload reported errors" in result["blocked_structs"]["IGNode"]["reason"]


def test_missing_matching_stage_hit_blocks_that_candidate_only():
    payload = _fixture_payload()
    for event in payload["events"]:
        if event["stage"] == "colorgraph":
            event["pc"] = event["pc"] + 4

    result = classify_probe_evidence(payload)

    assert "colorgraph" not in result["promotable_entries"]
    assert (
        result["blocked_entries"]["colorgraph"]["reason"]
        == "missing matching stage hit"
    )
    assert "simplifygraph" in result["promotable_entries"]


def test_implausible_ig_sample_blocks_graph_evidence_and_ignode_struct():
    payload = _fixture_payload()
    for event in payload["events"]:
        if "ig_sample" in event:
            event["ig_sample"][0]["ig_idx"] = event["ig_sample"][0]["slot"] + 99
            break

    result = classify_probe_evidence(payload)

    assert "interferencegraph" not in result["promotable_entries"]
    assert "n_ignodes" not in result["promotable_entries"]
    assert "IGNode" not in result["promotable_structs"]
    assert (
        result["blocked_entries"]["interferencegraph"]["reason"]
        == "implausible IG sample"
    )
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "implausible IG sample"
    )


def test_ig_sample_neighbor_outside_live_node_count_blocks_graph_evidence():
    payload = _fixture_payload()
    for event in payload["events"]:
        if "ig_sample" in event:
            event["ig_sample"][0]["neighbors_sample"] = [100]

    result = classify_probe_evidence(payload)

    assert "interferencegraph" not in result["promotable_entries"]
    assert "n_ignodes" not in result["promotable_entries"]
    assert "IGNode" not in result["promotable_structs"]
    assert (
        result["blocked_entries"]["interferencegraph"]["reason"]
        == "implausible IG sample"
    )
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "implausible IG sample"
    )


def test_ig_sample_without_next_or_neighbors_does_not_promote_full_struct():
    payload = _fixture_payload()
    for event in payload["events"]:
        for row in event.get("ig_sample", []):
            row.pop("next", None)
            row.pop("neighbors_sample", None)

    result = classify_probe_evidence(payload)

    assert "interferencegraph" not in result["promotable_entries"]
    assert "n_ignodes" not in result["promotable_entries"]
    assert "IGNode" not in result["promotable_structs"]
    assert (
        result["blocked_structs"]["IGNode"]["reason"]
        == "IG sample missing next or inline array evidence"
    )


def test_richer_probe_promotes_used_vregs_final_scheduler_blocks_and_pcode():
    payload = _fixture_payload()
    payload["candidates"]["final_scheduler"] = 0x435D75
    payload["globals"]["used_vreg_gpr"] = 0x58846E
    payload["globals"]["used_vreg_fpr"] = 0x58846C

    block_sample = [
        {
            "slot": 0,
            "ptr": 0x62800C,
            "next": 0,
            "blockIndex": 0,
            "firstPCode": 0x650900,
            "lastPCode": 0x650930,
            "first_pcode": {
                "ptr": 0x650900,
                "next": 0,
                "opcode": 123,
                "arg_count": 2,
            },
        }
    ]
    final_globals = {
        "pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C},
        "used_vreg_gpr": {"va": 0x58846E, "s16": 4},
        "used_vreg_fpr": {"va": 0x58846C, "s16": 3},
    }
    payload["events"].append(
        {
            "stage": "final_scheduler",
            "pc": 0x435D75,
            "stage_args": {},
            "globals": final_globals,
            "block_sample": block_sample,
            "frame_state": {
                "locals": {
                    "va": 0x587FB8,
                    "head": 0x650A00,
                    "objects_sample": [
                        {
                            "node": 0x650A00,
                            "next": 0,
                            "object": 0x650B00,
                            "name": "local_x",
                            "stack_offset": -0x20,
                            "size": 4,
                        }
                    ],
                },
                "frame_base_size": {"va": 0x5880CC, "s32": 0x50},
                "frame_call_args_size": {"va": 0x58712C, "s32": 0x20},
            },
        }
    )
    payload["events"].append(
        {
            "stage": "real_coalesce",
            "pc": payload["candidates"]["real_coalesce"],
            "stage_args": {"rclass": 0, "n_virtuals": 4},
            "globals": final_globals,
        }
    )
    payload["events"].append(
        {
            "stage": "real_coalesce",
            "pc": payload["candidates"]["real_coalesce"],
            "stage_args": {"rclass": 1, "n_virtuals": 3},
            "globals": final_globals,
        }
    )

    result = classify_probe_evidence(payload)

    for key in (
        "final_scheduler",
        "backend_block_list",
        "frame_locals",
        "used_vreg_gpr",
        "used_vreg_fpr",
    ):
        assert key in result["promotable_entries"]
        assert result["promotable_entries"][key]["confidence"] == "live-invariant"
    assert result["promotable_entries"]["backend_block_list"]["va"] == 0x587C74
    assert result["promotable_entries"]["frame_locals"]["va"] == 0x587FB8
    assert result["promotable_structs"]["PCode"] == {
        "confidence": "live-invariant",
        "fields": {"next": 0x00, "opcode": 0x14, "arg_count": 0x1A},
        "evidence": "block sample proves PCode next/opcode/arg_count fields",
    }
    assert result["promotable_structs"]["PCodeBlock"] == {
        "confidence": "live-invariant",
        "fields": {"next": 0x00, "firstPCode": 0x14, "blockIndex": 0x1C},
        "evidence": "block sample proves PCodeBlock next/firstPCode/blockIndex fields",
    }


def test_empty_block_sample_does_not_promote_pcode_structs():
    payload = _fixture_payload()
    payload["events"].append(
        {
            "stage": "final_scheduler",
            "pc": 0x435D75,
            "globals": {"pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C}},
            "block_sample": [
                {
                    "slot": 0,
                    "ptr": 0x62800C,
                    "next": 0,
                    "blockIndex": 0,
                    "firstPCode": 0,
                    "lastPCode": 0,
                }
            ],
        }
    )

    result = classify_probe_evidence(payload)

    assert "PCode" not in result["promotable_structs"]
    assert "PCodeBlock" not in result["promotable_structs"]
    assert result["blocked_structs"]["PCode"]["reason"] == "missing PCode sample"
    assert result["blocked_structs"]["PCodeBlock"]["reason"] == "missing PCode sample"


def test_pcode_sample_without_next_does_not_promote_pcode_structs():
    payload = _fixture_payload()
    payload["events"].append(
        {
            "stage": "final_scheduler",
            "pc": 0x435D75,
            "globals": {"pcbasicblocks": {"va": 0x587C74, "u32": 0x62800C}},
            "block_sample": [
                {
                    "slot": 0,
                    "ptr": 0x62800C,
                    "next": 0,
                    "blockIndex": 0,
                    "firstPCode": 0x650900,
                    "lastPCode": 0x650930,
                    "first_pcode": {
                        "ptr": 0x650900,
                        "opcode": 123,
                        "arg_count": 2,
                    },
                }
            ],
        }
    )

    result = classify_probe_evidence(payload)

    assert "PCode" not in result["promotable_structs"]
    assert "PCodeBlock" not in result["promotable_structs"]
    assert result["blocked_structs"]["PCode"]["reason"] == "implausible PCode sample"
    assert (
        result["blocked_structs"]["PCodeBlock"]["reason"]
        == "implausible PCode sample"
    )
