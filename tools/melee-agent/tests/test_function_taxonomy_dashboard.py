from __future__ import annotations

from copy import deepcopy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
LEGACY_FRAME_COMPATIBILITY = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy_frame_compatibility.json").read_text(
        encoding="utf-8"
    )
)
ROUTING_FACET_COMPATIBILITY = json.loads(
    (Path(__file__).parent / "fixtures" / "routing_facets_compatibility.json").read_text(
        encoding="utf-8"
    )
)
SEMANTIC_DELTA_COMPATIBILITY = json.loads(
    (Path(__file__).parent / "fixtures" / "semantic_delta_compatibility.json").read_text(
        encoding="utf-8"
    )
)
ROOT_CAUSE_COMPATIBILITY = json.loads(
    (Path(__file__).parent / "fixtures" / "root_cause_compatibility.json").read_text(
        encoding="utf-8"
    )
)
ROUTING_CASES_BY_NAME = {
    case["name"]: case for case in ROUTING_FACET_COMPATIBILITY
}
SEMANTIC_DELTA_FIELDS = (
    "semantic_delta_families",
    "opcode_edit_direction",
    "normalized_trigger_signature_status",
    "normalized_trigger_signature",
    "normalized_trigger_family",
    "normalized_trigger_cluster_size",
)
ROOT_CAUSE_FIELDS = ("root_cause_keys", "max_root_cause_impact")


def assert_no_deprecated_frame_keys(value: object) -> None:
    if isinstance(value, dict):
        assert "closability_tier" not in value
        assert "frame_closability_tier" not in value
        for nested in value.values():
            assert_no_deprecated_frame_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_deprecated_frame_keys(nested)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "case", ROUTING_FACET_COMPATIBILITY, ids=lambda case: case["name"]
)
def test_python_routing_facet_compatibility(case: dict[str, object]) -> None:
    from tools.function_taxonomy_schema import normalize_routing_record

    normalized = normalize_routing_record(case["input"])
    assert {key: normalized[key] for key in case["expected"]} == case["expected"]
    assert normalize_routing_record(normalized) == normalized


def test_secondary_register_evidence_never_steals_data_primary_route() -> None:
    from tools.function_taxonomy_schema import normalize_routing_record

    row = ROUTING_CASES_BY_NAME["bss-generated-probe-keeps-data-route"]["input"]
    normalized = normalize_routing_record(row)
    assert normalized["primary_intervention"] == "bss-anchor-analysis"
    assert "register-only-delta" in normalized["secondary_signals"]


def test_producer_mode_reprojects_stale_facets() -> None:
    from tools.function_taxonomy_schema import normalize_routing_record

    row = dict(ROUTING_CASES_BY_NAME["struct-unresolved"]["input"])
    row.update(
        primary_intervention="data-symbol-modeling",
        secondary_signals=["relocation-only-residual"],
        evidence_stage="observed",
        blocker_families=["relocation-support"],
    )
    normalized = normalize_routing_record(row, preserve_existing=False)
    assert normalized["primary_intervention"] == "struct-layout-inference"
    assert normalized["evidence_stage"] == "blocked"
    assert normalized["blocker_families"] == ["struct-inference"]


def test_function_name_does_not_affect_routing_facets() -> None:
    from tools.function_taxonomy_schema import normalize_routing_record

    row = ROUTING_CASES_BY_NAME["frame-checkdiff-needs-attribution"]["input"]
    first = normalize_routing_record({**row, "function": "frame_register_allocator_magic"})
    second = normalize_routing_record({**row, "function": "plain_name"})
    keys = (
        "primary_intervention",
        "secondary_signals",
        "evidence_stage",
        "blocker_families",
    )
    assert {key: first[key] for key in keys} == {key: second[key] for key in keys}


@pytest.mark.parametrize(
    "case", SEMANTIC_DELTA_COMPATIBILITY, ids=lambda case: case["name"]
)
def test_python_semantic_delta_compatibility(case: dict[str, object]) -> None:
    from tools.function_taxonomy_schema import normalize_semantic_delta_record

    original = deepcopy(case["input"])
    normalized = normalize_semantic_delta_record(case["input"])
    assert {
        key: normalized[key] for key in case["expected"]
    } == case["expected"]
    assert normalize_semantic_delta_record(normalized) == normalized
    assert case["input"] == original
    if case["name"] == "legacy-v3-opcode-signature-remains-nonsemantic":
        assert all(key not in normalized for key in SEMANTIC_DELTA_FIELDS)


def test_semantic_delta_compatibility_ignores_function_and_reason_text() -> None:
    from tools.function_taxonomy_schema import normalize_semantic_delta_record

    semantic = deepcopy(SEMANTIC_DELTA_COMPATIBILITY[0]["input"])
    first = normalize_semantic_delta_record(
        {**semantic, "function": "issue_123", "reasons": ["task 456"]}
    )
    second = normalize_semantic_delta_record(
        {**semantic, "function": "plain_name", "reasons": ["unrelated"]}
    )

    assert {key: first[key] for key in SEMANTIC_DELTA_FIELDS} == {
        key: second[key] for key in SEMANTIC_DELTA_FIELDS
    }


@pytest.mark.parametrize(
    "case", ROOT_CAUSE_COMPATIBILITY, ids=lambda case: case["name"]
)
def test_python_root_cause_compatibility(case: dict[str, object]) -> None:
    from tools.function_taxonomy_schema import normalize_root_cause_record

    original = deepcopy(case["input"])
    normalized = normalize_root_cause_record(case["input"])
    assert {key: normalized[key] for key in case["expected"]} == case["expected"]
    assert normalize_root_cause_record(normalized) == normalized
    assert case["input"] == original
    if case["name"] == "legacy-v4-row-remains-root-cause-free":
        assert all(key not in normalized for key in ROOT_CAUSE_FIELDS)


def test_root_cause_compatibility_ignores_function_and_reason_text() -> None:
    from tools.function_taxonomy_schema import normalize_root_cause_record

    row = deepcopy(ROOT_CAUSE_COMPATIBILITY[0]["input"])
    first = normalize_root_cause_record(
        {**row, "function": "issue_123", "reasons": ["task 456"]}
    )
    second = normalize_root_cause_record(
        {**row, "function": "plain_name", "reasons": ["unrelated"]}
    )

    assert {key: first[key] for key in ROOT_CAUSE_FIELDS} == {
        key: second[key] for key in ROOT_CAUSE_FIELDS
    }


def write_minimal_taxonomy_dir(path: Path) -> None:
    path.mkdir()
    write_jsonl(
        path / "taxonomy.records.jsonl",
        [
            {
                "function": "ftDemo_80000000",
                "match_percent": 99.5,
                "work_bucket": "signature-call-type",
                "primary": "signature-type-mismatch",
            },
            {
                "function": "ftMatched_80000040",
                "match_percent": 100.0,
                "work_bucket": "register-allocator",
                "primary": "operand-register-or-offset",
            },
        ],
    )
    write_jsonl(path / "checkdiff-errors.jsonl", [{"function": "bad"}])
    write_jsonl(path / "report-only-nonextract-backed.jsonl", [{"function": "report"}])
    write_jsonl(path / "db-completed-extract-backed-non100.jsonl", [{"function": "done"}])
    queues = path / "queues"
    queues.mkdir()
    (queues / "signature-call-type.tsv").write_text(
        "match_percent\tfunction\n99.5\tftDemo_80000000\n98.0\tftOther\n",
        encoding="utf-8",
    )


def write_manifest_taxonomy_dir(path: Path) -> None:
    path.mkdir()
    write_jsonl(
        path / "taxonomy.records.jsonl",
        [
            {
                "function": "backend_fn",
                "match_percent": 99.5,
                "match_tier": ">=99%",
                "work_bucket": "backend-ceiling",
                "primary": "backend-ceiling",
                "source_actionability": "backend-ceiling",
            },
            {
                "function": "normalized_fn",
                "match_percent": 98.0,
                "match_tier": "97-99%",
                "work_bucket": "register-allocator",
                "primary": "normalized-structural-match",
                "source_actionability": "pcdump-proof-needed",
                "frame_evidence": "checkdiff-only",
                "frame_probe_status": "materializable",
                "frame_match_relevance": "unknown",
            },
            {
                "function": "near_fn",
                "match_percent": 97.5,
                "match_tier": "97-99%",
                "work_bucket": "normalized-structural-near-match",
                "primary": "normalized-structural-near-match",
                "source_actionability": "normalized-structural-triage",
                "frame_evidence": "pcdump-attributed",
                "frame_probe_status": "probe-inconclusive",
                "frame_match_relevance": "match-neutral",
            },
            {
                "function": "future_fn",
                "match_percent": 91.0,
                "match_tier": "future-tier",
                "work_bucket": "future-bucket",
                "primary": "future-primary",
                "source_actionability": "future-actionability",
                "frame_evidence": "future-evidence",
                "frame_probe_status": "future-status",
                "frame_match_relevance": "future-relevance",
            },
        ],
    )
    for filename in (
        "checkdiff-errors.jsonl",
        "report-only-nonextract-backed.jsonl",
        "db-completed-extract-backed-non100.jsonl",
    ):
        write_jsonl(path / filename, [])
    queues = path / "queues"
    queues.mkdir()
    for filename in (
        "data-symbol-relocation.tsv",
        "data-symbol-relocation.no-name-magic-candidate.tsv",
        "normalized-structural-near-match.tsv",
        "backend-ceiling.tsv",
        "checkdiff-errors.tsv",
        "future-specialized.tsv",
    ):
        (queues / filename).write_text("function\n", encoding="utf-8")


CONTROL_FLOW_HINT_KINDS = [
    "branch-idiom",
    "call-hoist",
    "pointer-walk-indexed-shape",
    "concurrent-buffer-lifetime",
    "loop-peel-unroll",
    "missing-extra-call-layer",
]
CONTROL_FLOW_QUEUE_PREFIX = "structural-reconstruction.control-flow-shape"


def write_control_flow_taxonomy_dir_data() -> dict:
    return {
        "function": "control_fn",
        "match_percent": 99.0,
        "match_tier": ">=99%",
        "work_bucket": "structural-reconstruction",
        "subcategory": "branch-or-control-flow-shape",
        "primary": "control-flow-source-shape",
        "source_actionability": "structural-rebuild",
        "control_flow_shape_analysis_status": "heuristic-hints",
        "control_flow_shape_hint_kinds": ["branch-idiom", "loop-peel-unroll"],
        "control_flow_shape_hints": [
            {
                "rank": 1,
                "kind": "branch-idiom",
                "confidence": 0.86,
                "operator": "bool-condition-spelling",
                "recommendation": "write an explicit if/else",
                "evidence": {"target_branch_lines": ["cmpwi r3, 0"]},
                "source_materialization": {
                    "status": "materializable",
                    "probe_count": 1,
                    "terminal_proof": {"terminal_blocker": "kept-for-detail"},
                },
            }
        ],
        "control_flow_shape_source_preflight_status": "materializable",
        "control_flow_shape_source_preflight_reason": "one bounded source probe",
        "control_flow_shape_generated_probe_count": 1,
        "control_flow_shape_blockers": ["terminal-sibling"],
        "control_flow_shape_validation_status": "not-run",
        "control_flow_shape_validated_probe_count": 0,
    }


def write_control_flow_taxonomy_dir(path: Path, *, legacy: bool = False) -> dict:
    path.mkdir()
    record = write_control_flow_taxonomy_dir_data()
    if legacy:
        for key in list(record):
            if key.startswith("control_flow_shape_"):
                del record[key]
    write_jsonl(path / "taxonomy.records.jsonl", [record])
    for filename in (
        "checkdiff-errors.jsonl",
        "report-only-nonextract-backed.jsonl",
        "db-completed-extract-backed-non100.jsonl",
    ):
        write_jsonl(path / filename, [])
    queues = path / "queues"
    queues.mkdir()
    queue_files = ["structural-reconstruction.tsv"] + [
        f"{CONTROL_FLOW_QUEUE_PREFIX}.{kind}.tsv" for kind in CONTROL_FLOW_HINT_KINDS
    ] + [
        f"{CONTROL_FLOW_QUEUE_PREFIX}.materializable.tsv",
        f"{CONTROL_FLOW_QUEUE_PREFIX}.terminal.tsv",
    ]
    for filename in queue_files:
        (queues / filename).write_text("match_percent\tfunction\n", encoding="utf-8")
    return record


def read_dashboard_payload(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    prefix = "window.__TAXONOMY_DASHBOARD_DATA__ = "
    assert text.startswith(prefix)
    assert text.endswith(";\n")
    return json.loads(text[len(prefix) : -2])


def test_dashboard_payload_manifest_covers_known_and_future_observed_values(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import build_dashboard_payload

    taxonomy_dir = tmp_path / "taxonomy"
    write_manifest_taxonomy_dir(taxonomy_dir)

    payload = build_dashboard_payload(taxonomy_dir)
    manifest = payload["taxonomyManifest"]

    assert manifest["schemaVersion"] == 5
    assert manifest["bucketOrder"] == [
        "signature-call-type",
        "inline-boundary",
        "structural-reconstruction",
        "normalized-structural-near-match",
        "backend-ceiling",
        "data-symbol-relocation",
        "stack-local-layout",
        "indexed-struct-pointer",
        "struct-offset-discrepancy",
        "known-small-pattern-candidate",
        "register-allocator",
        "future-bucket",
    ]
    assert manifest["primaryOrder"] == [
        "normalized-structural-match",
        "normalized-structural-near-match",
        "backend-ceiling",
        "future-primary",
    ]
    assert manifest["actionabilityOrder"] == [
        "pcdump-proof-needed",
        "normalized-structural-triage",
        "backend-ceiling",
        "future-actionability",
    ]
    assert "closabilityOrder" not in manifest
    assert "closabilityInfo" not in manifest
    assert manifest["tierOrder"] == [
        ">=99%",
        "97-99%",
        "95-97%",
        "90-95%",
        "<90%",
        "future-tier",
    ]
    assert manifest["queueFiles"] == [
        "normalized-structural-near-match.tsv",
        "backend-ceiling.tsv",
        "data-symbol-relocation.tsv",
        "data-symbol-relocation.no-name-magic-candidate.tsv",
        "checkdiff-errors.tsv",
        "future-specialized.tsv",
    ]
    assert manifest["bucketInfo"]["backend-ceiling"]["label"] == "Backend Ceiling"
    assert (
        manifest["bucketInfo"]["normalized-structural-near-match"]["label"]
        == "Normalized Structural Near Match"
    )
    assert manifest["primaryInfo"]["backend-ceiling"]["label"] == "Backend Ceiling"
    assert manifest["primaryInfo"]["normalized-structural-match"]["label"] == (
        "Normalized Structural Match"
    )
    assert manifest["primaryInfo"]["normalized-structural-near-match"]["label"] == (
        "Normalized Structural Near Match"
    )
    assert (
        manifest["actionabilityInfo"]["normalized-structural-triage"]["label"]
        == "Normalized Structural Triage"
    )
    assert manifest["bucketInfo"]["future-bucket"] == {
        "label": "Future Bucket",
        "description": "No curated bucket description is available for this observed value.",
        "focus": "Use the row evidence and next command; add curated metadata if this value becomes stable.",
        "color": "#647076",
    }
    assert manifest["primaryInfo"]["future-primary"]["label"] == "Future Primary"
    assert manifest["actionabilityInfo"]["future-actionability"]["label"] == (
        "Future Actionability"
    )


def test_manifest_curates_struct_inference_blocked_actionability() -> None:
    from tools.function_taxonomy_schema import build_dashboard_manifest

    manifest = build_dashboard_manifest(
        [
            {
                "source_actionability": "struct-inference-blocked",
                "work_bucket": "struct-offset-discrepancy",
            }
        ],
        {},
    )

    assert manifest["actionabilityOrder"] == ["struct-inference-blocked"]
    info = manifest["actionabilityInfo"]["struct-inference-blocked"]
    assert info["label"] == "Struct Inference Blocked"
    assert "resolver" in info["description"]
    assert "struct/type evidence" in info["focus"]


def test_schema_v5_manifest_orders_observed_frame_dimensions() -> None:
    from tools.function_taxonomy_schema import build_dashboard_manifest

    records = []
    evidences = [
        "checkdiff-only",
        "pcdump-attributed",
        "tool-evaluated",
        "probe-validated",
    ]
    statuses = [
        "needs-attribution",
        "materializable",
        "probe-inconclusive",
        "validated-improving",
        "terminal-no-safe-lever",
        "ceiling",
    ]
    relevance = ["match-gating-candidate", "match-neutral", "unknown"]
    for index, status in enumerate(statuses):
        records.append(
            {
                "frame_evidence": evidences[index % len(evidences)],
                "frame_probe_status": status,
                "frame_match_relevance": relevance[index % len(relevance)],
            }
        )

    manifest = build_dashboard_manifest(records, {})

    assert manifest["schemaVersion"] == 5
    assert manifest["frameEvidenceOrder"] == evidences
    assert manifest["frameProbeStatusOrder"] == statuses
    assert manifest["frameMatchRelevanceOrder"] == relevance
    assert "closabilityOrder" not in manifest
    assert "closabilityInfo" not in manifest


def test_schema_v5_manifest_orders_routing_facets() -> None:
    from tools.function_taxonomy_schema import build_dashboard_manifest

    records = [
        {
            "primary_intervention": "control-flow-reconstruction",
            "evidence_stage": "materializable",
            "secondary_signals": ["branch-idiom"],
            "blocker_families": ["unsafe-source-transform"],
        },
        {
            "primary_intervention": "backend-ceiling-review",
            "evidence_stage": "ceiling",
            "secondary_signals": [],
            "blocker_families": [],
        },
        {
            "primary_intervention": "future-intervention",
            "evidence_stage": "future-stage",
            "secondary_signals": ["future-signal"],
            "blocker_families": ["future-blocker"],
        },
    ]

    manifest = build_dashboard_manifest(records, {})

    assert manifest["schemaVersion"] == 5
    assert manifest["interventionOrder"] == [
        "control-flow-reconstruction",
        "backend-ceiling-review",
        "future-intervention",
    ]
    assert manifest["evidenceStageOrder"] == [
        "materializable",
        "ceiling",
        "future-stage",
    ]
    assert "branch-idiom" in manifest["secondarySignalOrder"]
    assert "unsafe-source-transform" in manifest["blockerFamilyOrder"]
    assert manifest["interventionInfo"]["future-intervention"]["label"] == (
        "Future Intervention"
    )


def test_schema_v5_manifest_orders_semantic_delta_facets() -> None:
    from tools.function_taxonomy_schema import build_dashboard_manifest

    records = [
        {
            "semantic_delta_families": [
                "branch-predicate-control",
                "address-constant-materialization",
            ],
            "opcode_edit_direction": "substitution",
            "normalized_trigger_family": "one-line-substitution",
        },
        {
            "semantic_delta_families": ["integer-memory-width-transfer"],
            "opcode_edit_direction": "mixed",
            "normalized_trigger_family": "three-line-mixed",
        },
        {
            "semantic_delta_families": ["future-semantic-family"],
            "opcode_edit_direction": "future-direction",
            "normalized_trigger_family": "future-trigger-family",
        },
    ]

    manifest = build_dashboard_manifest(records, {})

    assert manifest["schemaVersion"] == 5
    assert manifest["semanticDeltaFamilyOrder"] == [
        "address-constant-materialization",
        "branch-predicate-control",
        "integer-memory-width-transfer",
        "future-semantic-family",
    ]
    assert manifest["opcodeEditDirectionOrder"] == [
        "substitution",
        "mixed",
        "future-direction",
    ]
    assert manifest["normalizedTriggerFamilyOrder"] == [
        "one-line-substitution",
        "three-line-mixed",
        "future-trigger-family",
    ]
    assert manifest["semanticDeltaFamilyInfo"][
        "address-constant-materialization"
    ]["label"] == "Address / Constant Materialization"
    assert manifest["semanticDeltaFamilyInfo"]["future-semantic-family"] == {
        "label": "Future Semantic Family",
        "description": (
            "No curated semantic delta family description is available for this "
            "observed value."
        ),
        "focus": (
            "Use the row evidence and next command; add curated metadata if this "
            "value becomes stable."
        ),
    }
    assert "likely focus" in manifest["opcodeEditDirectionInfo"]["mixed"]["focus"]


def test_schema_v5_manifest_orders_root_causes_by_impact_then_key() -> None:
    from tools.function_taxonomy_schema import build_dashboard_manifest

    records = [
        {"root_cause_keys": ["bss-symbol:B", "bss-symbol:A"]},
        {"root_cause_keys": ["bss-symbol:A"]},
        {"root_cause_keys": ["future-cause:C"]},
    ]

    manifest = build_dashboard_manifest(records, {})

    assert manifest["schemaVersion"] == 5
    assert manifest["rootCauseKeyOrder"] == [
        "bss-symbol:A",
        "bss-symbol:B",
        "future-cause:C",
    ]
    assert manifest["rootCauseKeyInfo"]["bss-symbol:A"] == {
        "label": "A",
        "description": "Named BSS symbol shared by a relocation-residual cohort.",
        "focus": "Inspect all affected rows before building or applying a symbol-level fix.",
    }
    assert manifest["rootCauseKeyInfo"]["future-cause:C"]["label"] == (
        "Future Cause C"
    )


def test_dashboard_payload_normalizes_shared_semantic_delta_cases(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import build_dashboard_payload

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    rows = []
    for index, case in enumerate(SEMANTIC_DELTA_COMPATIBILITY):
        row = deepcopy(case["input"])
        row["match_percent"] = 99.0 - index
        rows.append(row)
    write_jsonl(taxonomy_dir / "taxonomy.records.jsonl", rows)

    payload = build_dashboard_payload(taxonomy_dir)

    by_function = {row["function"]: row for row in payload["records"]}
    for case in SEMANTIC_DELTA_COMPATIBILITY:
        normalized = by_function[case["input"]["function"]]
        assert {
            key: normalized[key] for key in case["expected"]
        } == case["expected"]
        if case["name"] == "legacy-v3-opcode-signature-remains-nonsemantic":
            assert all(key not in normalized for key in SEMANTIC_DELTA_FIELDS)


def test_dashboard_payload_normalizes_shared_root_cause_cases(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import build_dashboard_payload

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    rows = []
    for index, case in enumerate(ROOT_CAUSE_COMPATIBILITY):
        row = deepcopy(case["input"])
        row["match_percent"] = 99.0 - index
        rows.append(row)
    write_jsonl(taxonomy_dir / "taxonomy.records.jsonl", rows)

    payload = build_dashboard_payload(taxonomy_dir)

    by_function = {row["function"]: row for row in payload["records"]}
    for case in ROOT_CAUSE_COMPATIBILITY:
        normalized = by_function[case["input"]["function"]]
        assert {key: normalized[key] for key in case["expected"]} == case["expected"]
        if case["name"] == "legacy-v4-row-remains-root-cause-free":
            assert all(key not in normalized for key in ROOT_CAUSE_FIELDS)


def test_dashboard_payload_validation_rejects_omitted_multi_value(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import (
        build_dashboard_payload,
        validate_dashboard_payload,
    )

    taxonomy_dir = tmp_path / "taxonomy"
    write_control_flow_taxonomy_dir(taxonomy_dir)
    row = deepcopy(
        ROUTING_CASES_BY_NAME["control-materializable-with-sibling-blockers"][
            "input"
        ]
    )
    row["match_percent"] = 99.0
    write_jsonl(taxonomy_dir / "taxonomy.records.jsonl", [row])
    payload = build_dashboard_payload(taxonomy_dir)

    cases = (
        ("secondarySignalOrder", "branch-idiom"),
        ("secondarySignalInfo", "branch-idiom"),
        ("blockerFamilyOrder", "source-anchor"),
        ("blockerFamilyInfo", "source-anchor"),
    )
    for manifest_key, value in cases:
        broken = deepcopy(payload)
        if isinstance(broken["taxonomyManifest"][manifest_key], list):
            broken["taxonomyManifest"][manifest_key].remove(value)
        else:
            del broken["taxonomyManifest"][manifest_key][value]
        with pytest.raises(ValueError):
            validate_dashboard_payload(broken)


def test_dashboard_payload_normalizes_legacy_routing_facets(tmp_path: Path) -> None:
    from tools.function_taxonomy_dashboard import build_dashboard_payload

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    row = deepcopy(
        ROUTING_CASES_BY_NAME["control-materializable-with-sibling-blockers"][
            "input"
        ]
    )
    row.update(match_percent=99.0, secondary_signals="branch-idiom")
    write_jsonl(taxonomy_dir / "taxonomy.records.jsonl", [row])

    normalized = build_dashboard_payload(taxonomy_dir)["records"][0]

    assert normalized["secondary_signals"] == [
        "branch-idiom",
        "loop-peel-unroll",
    ]
    assert isinstance(normalized["blocker_families"], list)


def test_dashboard_payload_normalizes_legacy_frame_record(tmp_path: Path) -> None:
    from tools.function_taxonomy_dashboard import build_dashboard_payload

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    legacy = {
        "function": "same_frame",
        "match_percent": 99.2,
        "work_bucket": "stack-local-layout",
        "frame_cause": "stack-object-offset-shift",
        "frame_raw_verdict": "checkdiff-only",
        "frame_attribution_status": "checkdiff-only",
        "frame_closability_tier": "reorder-gated-362",
        "source_actionability": "generator-gated",
        "actionability_reason": "needs the #362 reorder lever",
        "classification": {
            "stack_slot_localizer": {
                "closability_tier": "ceiling",
                "diagnostic": {
                    "frame_closability_tier": "legacy-only",
                    "preserved_raw_marker": "keep-me",
                },
            },
        },
    }
    write_jsonl(taxonomy_dir / "taxonomy.records.jsonl", [legacy])

    payload = build_dashboard_payload(taxonomy_dir)

    normalized = payload["records"][0]
    assert normalized["frame_evidence"] == "checkdiff-only"
    assert normalized["frame_probe_status"] == "needs-attribution"
    assert normalized["frame_match_relevance"] == "match-neutral"
    assert normalized["source_actionability"] == "diagnostic-only"
    assert (
        normalized["classification"]["stack_slot_localizer"]
        ["diagnostic"]["preserved_raw_marker"]
        == "keep-me"
    )
    assert_no_deprecated_frame_keys(payload)
    assert "frame_closability_tier" not in normalized
    assert "#362" not in json.dumps(payload)
    assert "#366" not in json.dumps(payload)


def test_dashboard_payload_normalizes_shared_legacy_frame_compatibility_cases(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import build_dashboard_payload

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    write_jsonl(
        taxonomy_dir / "taxonomy.records.jsonl",
        [case["input"] for case in LEGACY_FRAME_COMPATIBILITY],
    )

    payload = build_dashboard_payload(taxonomy_dir)

    by_function = {row["function"]: row for row in payload["records"]}
    for case in LEGACY_FRAME_COMPATIBILITY:
        normalized = by_function[case["input"]["function"]]
        for key, expected in case["expected"].items():
            assert normalized[key] == expected, (case["case"], key)
        assert "frame_closability_tier" not in normalized
    serialized = json.dumps(payload)
    assert all(issue not in serialized for issue in ("#362", "#366", "#369"))
    assert "reorder-gated-" not in serialized


def test_dashboard_model_normalizes_legacy_frame_rows_and_exposes_behavior() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const rows = model.normalizeRecords([{{
        function: "sameFrame",
        frame_cause: "stack-object-offset-shift",
        frame_raw_verdict: "checkdiff-only",
        frame_attribution_status: "checkdiff-only",
        frame_closability_tier: "reorder-gated-362",
        source_actionability: "generator-gated",
        actionability_reason: "needs #362",
        classification: {{stack_slot_localizer: {{
          closability_tier: "ceiling",
          diagnostic: {{frame_closability_tier: "legacy-only", preserved_raw_marker: "keep-me"}}
        }}}}
      }}]);
      const row = rows[0];
      if (row.frame_probe_status !== "needs-attribution") throw new Error("bad status");
      if (row.frame_match_relevance !== "match-neutral") throw new Error("bad relevance");
      if (Object.hasOwn(row, "frame_closability_tier")) throw new Error("legacy leak");
      if (JSON.stringify(row).includes("closability_tier")) throw new Error("nested legacy leak");
      if (row.classification.stack_slot_localizer.diagnostic.preserved_raw_marker !== "keep-me") {{
        throw new Error("raw diagnostic lost");
      }}
      const manifest = model.resolveManifest({{schemaVersion: 1}}, rows, {{}});
      if (manifest.schemaVersion !== 5) throw new Error("bad schema");
      if (Object.hasOwn(manifest, "closabilityOrder")) throw new Error("manifest leak");
      process.stdout.write(JSON.stringify({{row, manifest}}));
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_dashboard_model_matches_shared_legacy_frame_compatibility_cases() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const cases = {json.dumps(LEGACY_FRAME_COMPATIBILITY)};
      const rows = model.normalizeRecords(cases.map((item) => item.input));
      cases.forEach((item, index) => {{
        const row = rows[index];
        Object.entries(item.expected).forEach(([key, expected]) => {{
          if (row[key] !== expected) {{
            throw new Error(`${{item.case}} ${{key}}: ${{row[key]}} !== ${{expected}}`);
          }}
        }});
        if (Object.hasOwn(row, "frame_closability_tier")) throw new Error("legacy leak");
      }});
      const serialized = JSON.stringify(rows);
      if (["#362", "#366", "#369"].some((issue) => serialized.includes(issue))) {{
        throw new Error("stale issue copy");
      }}
      if (serialized.includes("reorder-gated-")) throw new Error("legacy tier leak");
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_dashboard_model_matches_shared_routing_facet_cases() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH
    from tools.function_taxonomy_schema import normalize_routing_record

    stale = dict(ROUTING_CASES_BY_NAME["struct-unresolved"]["input"])
    stale.update(
        primary_intervention="data-symbol-modeling",
        secondary_signals=["relocation-only-residual"],
        evidence_stage="observed",
        blocker_families=["relocation-support"],
    )
    python_producer = normalize_routing_record(stale, preserve_existing=False)
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const cases = {json.dumps(ROUTING_FACET_COMPATIBILITY)};
      const keys = ["primary_intervention", "secondary_signals", "evidence_stage", "blocker_families"];
      const normalized = cases.map((item) => model.normalizeRoutingRecord(item.input));
      const projected = normalized.map((row) => Object.fromEntries(
        keys.map((key) => [key, row[key]])
      ));
      const second = normalized.map((row) => model.normalizeRoutingRecord(row));
      const secondProjected = second.map((row) => Object.fromEntries(
        keys.map((key) => [key, row[key]])
      ));
      const producer = model.normalizeRoutingRecord({json.dumps(stale)}, {{preserveExisting: false}});
      process.stdout.write(JSON.stringify({{projected, secondProjected, producer: Object.fromEntries(
        keys.map((key) => [key, producer[key]])
      )}}));
    """
    result = subprocess.run(
        ["node", "-e", script], check=True, text=True, capture_output=True
    )
    output = json.loads(result.stdout)
    expected = [case["expected"] for case in ROUTING_FACET_COMPATIBILITY]
    assert output["projected"] == expected
    assert output["secondProjected"] == expected
    assert output["producer"] == {
        key: python_producer[key]
        for key in (
            "primary_intervention",
            "secondary_signals",
            "evidence_stage",
            "blocker_families",
        )
    }


def test_dashboard_model_matches_shared_semantic_delta_cases() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH
    from tools.function_taxonomy_schema import normalize_semantic_delta_record

    expected = [
        {
            key: normalized[key]
            for key in SEMANTIC_DELTA_FIELDS
            if key in normalized
        }
        for normalized in (
            normalize_semantic_delta_record(case["input"])
            for case in SEMANTIC_DELTA_COMPATIBILITY
        )
    ]
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const cases = {json.dumps(SEMANTIC_DELTA_COMPATIBILITY)};
      const keys = {json.dumps(SEMANTIC_DELTA_FIELDS)};
      const original = JSON.stringify(cases);
      const project = (row) => Object.fromEntries(
        keys.filter((key) => Object.hasOwn(row, key)).map((key) => [key, row[key]])
      );
      const normalized = cases.map((item) => model.normalizeSemanticDeltaRecord(item.input));
      const projected = normalized.map(project);
      const secondProjected = normalized
        .map((row) => model.normalizeSemanticDeltaRecord(row)).map(project);
      const recordsProjected = model.normalizeRecords(cases.map((item) => item.input)).map(project);
      if (JSON.stringify(cases) !== original) throw new Error("caller arrays mutated");
      const ordered = model.normalizeRecords([{{
        function: "ordered",
        work_bucket: "structural-reconstruction",
        frame_cause: "stack-object-offset-shift",
        frame_closability_tier: "legacy",
        semantic_delta_families: ["integer-memory-width-transfer",
          "address-constant-materialization"]
      }}])[0];
      if (Object.hasOwn(ordered, "frame_closability_tier")
          || ordered.primary_intervention !== "manual-attribution"
          || ordered.semantic_delta_families.join(",") !==
             "address-constant-materialization,integer-memory-width-transfer") {{
        throw new Error("normalization order mismatch");
      }}
      process.stdout.write(JSON.stringify({{projected, secondProjected, recordsProjected}}));
    """
    result = subprocess.run(
        ["node", "-e", script], check=True, text=True, capture_output=True
    )
    output = json.loads(result.stdout)
    assert output["projected"] == expected
    assert output["secondProjected"] == expected
    assert output["recordsProjected"] == expected


def test_dashboard_model_matches_shared_root_cause_cases() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH
    from tools.function_taxonomy_schema import normalize_root_cause_record

    expected = [
        {
            key: normalized[key]
            for key in ROOT_CAUSE_FIELDS
            if key in normalized
        }
        for normalized in (
            normalize_root_cause_record(case["input"])
            for case in ROOT_CAUSE_COMPATIBILITY
        )
    ]
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const cases = {json.dumps(ROOT_CAUSE_COMPATIBILITY)};
      const keys = {json.dumps(ROOT_CAUSE_FIELDS)};
      const original = JSON.stringify(cases);
      const project = (row) => Object.fromEntries(
        keys.filter((key) => Object.hasOwn(row, key)).map((key) => [key, row[key]])
      );
      const normalized = cases.map((item) => model.normalizeRootCauseRecord(item.input));
      const projected = normalized.map(project);
      const secondProjected = normalized
        .map((row) => model.normalizeRootCauseRecord(row)).map(project);
      const recordsProjected = model.normalizeRecords(cases.map((item) => item.input)).map(project);
      if (JSON.stringify(cases) !== original) throw new Error("caller arrays mutated");
      process.stdout.write(JSON.stringify({{projected, secondProjected, recordsProjected}}));
    """
    result = subprocess.run(
        ["node", "-e", script], check=True, text=True, capture_output=True
    )
    output = json.loads(result.stdout)
    assert output["projected"] == expected
    assert output["secondProjected"] == expected
    assert output["recordsProjected"] == expected


def test_dashboard_model_semantic_delta_filter_search_and_detail_behavior() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    signature = (
        '{"edit_direction":"substitution","normalized_diff_lines":1,'
        '"pairs":[["mr","li"],[null,"addi"]],"version":1}'
    )
    row = {
        "semantic_delta_families": [
            "address-constant-materialization",
            "indexed-update-memory",
        ],
        "opcode_edit_direction": "substitution",
        "normalized_trigger_signature_status": "available",
        "normalized_trigger_signature": signature,
        "normalized_trigger_family": "one-line-substitution",
        "normalized_trigger_cluster_size": 3,
    }
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const row = model.normalizeSemanticDeltaRecord({json.dumps(row)});
      if (!model.matchesSemanticDeltaFilters(row, {{
        family: "indexed-update-memory",
        direction: "substitution",
        triggerFamily: "one-line-substitution"
      }})) throw new Error("expected semantic match");
      if (!model.matchesSemanticDeltaFilters(row, {{}})) {{
        throw new Error("empty filters must pass");
      }}
      if (model.matchesSemanticDeltaFilters(row, {{family: "frame-save-window"}})
          || model.matchesSemanticDeltaFilters(row, {{direction: "mixed"}})
          || model.matchesSemanticDeltaFilters(row, {{triggerFamily: "two-line-mixed"}})) {{
        throw new Error("unexpected semantic match");
      }}
      const search = model.semanticDeltaSearchText(row);
      [
        ...row.semantic_delta_families,
        row.opcode_edit_direction,
        row.normalized_trigger_signature_status,
        row.normalized_trigger_signature,
        row.normalized_trigger_family,
        String(row.normalized_trigger_cluster_size)
      ].forEach((value) => {{
        if (!search.includes(value)) throw new Error(`missing search value: ${{value}}`);
      }});
      const parsed = model.normalizedTriggerSignatureDetail(row);
      if (JSON.stringify(parsed) !== JSON.stringify({{
        version: 1,
        normalizedDiffLines: 1,
        editDirection: "substitution",
        pairs: [["mr", "li"], [null, "addi"]]
      }})) throw new Error("bad parsed trigger detail");
      const detail = model.semanticDeltaDetail(row);
      if (detail.editDirection !== "substitution"
          || detail.triggerFamily !== "one-line-substitution"
          || detail.triggerClusterSize !== 3
          || JSON.stringify(detail.triggerSignature) !== JSON.stringify(parsed)) {{
        throw new Error("bad semantic detail");
      }}
      detail.families.push("mutated");
      detail.triggerSignature.pairs[0].push("mutated");
      if (row.semantic_delta_families.includes("mutated")
          || JSON.parse(row.normalized_trigger_signature).pairs[0].includes("mutated")) {{
        throw new Error("semantic detail leaked mutable arrays");
      }}
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_dashboard_model_root_cause_filter_search_and_detail_behavior() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    row = {
        "root_cause_keys": ["bss-symbol:lbl_80472ED8", "future-cause:A"],
        "max_root_cause_impact": 3,
    }
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const row = model.normalizeRootCauseRecord({json.dumps(row)});
      if (!model.matchesRootCauseFilters(row, {{key: "bss-symbol:lbl_80472ED8"}})
          || !model.matchesRootCauseFilters(row, {{}})
          || model.matchesRootCauseFilters(row, {{key: "bss-symbol:missing"}})) {{
        throw new Error("bad root cause membership filter");
      }}
      const search = model.rootCauseSearchText(row);
      [...row.root_cause_keys, "3"].forEach((value) => {{
        if (!search.includes(value)) throw new Error(`missing search value: ${{value}}`);
      }});
      const detail = model.rootCauseDetail(row);
      if (detail.maxImpact !== 3
          || detail.keys.join(",") !== row.root_cause_keys.join(",")) {{
        throw new Error("bad root cause detail");
      }}
      detail.keys.push("mutated");
      if (row.root_cause_keys.includes("mutated")) throw new Error("mutable detail");
      if (model.rootCauseDetail({{function: "legacy"}}) !== null) {{
        throw new Error("legacy row fabricated root cause detail");
      }}
      const visible = [row, {{root_cause_keys: ["future-cause:A"]}}];
      const all = [
        row,
        {{root_cause_keys: ["bss-symbol:lbl_80472ED8"]}},
        {{root_cause_keys: ["future-cause:A", "future-cause:A"]}}
      ];
      const membership = model.rootCauseMembershipDetail(row, visible, all);
      if (JSON.stringify(membership) !== JSON.stringify([
        {{key: "bss-symbol:lbl_80472ED8", visible: 1, total: 2}},
        {{key: "future-cause:A", visible: 2, total: 2}}
      ])) {{
        throw new Error(`bad root cause visible/total membership: ${{JSON.stringify(membership)}}`);
      }}
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


@pytest.mark.parametrize(
    "signature,direction",
    [
        ("not-json", "substitution"),
        (
            '{"edit_direction":"substitution","normalized_diff_lines":1,'
            '"pairs":[["mr","li"]],"version":2}',
            "substitution",
        ),
        (
            '{"edit_direction":"substitution","normalized_diff_lines":1,'
            '"pairs":[["mr"]],"version":1}',
            "substitution",
        ),
        (
            '{"edit_direction":"substitution","normalized_diff_lines":1,'
            '"pairs":[["mr",7]],"version":1}',
            "substitution",
        ),
        (
            '{"edit_direction":"substitution","normalized_diff_lines":4,'
            '"pairs":[["mr","li"]],"version":1}',
            "substitution",
        ),
        (
            '{"edit_direction":"substitution","normalized_diff_lines":1,'
            '"pairs":[["mr","li"]],"version":1}',
            "mixed",
        ),
    ],
)
def test_dashboard_model_rejects_unsafe_normalized_trigger_signatures(
    signature: str, direction: str
) -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const row = {{
        opcode_edit_direction: {json.dumps(direction)},
        normalized_trigger_signature_status: "available",
        normalized_trigger_signature: {json.dumps(signature)}
      }};
      if (model.normalizedTriggerSignatureDetail(row) !== null) {{
        throw new Error("unsafe trigger signature accepted");
      }}
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_dashboard_model_routing_filter_search_and_detail_behavior() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    row = ROUTING_CASES_BY_NAME["control-materializable-with-sibling-blockers"][
        "input"
    ]
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const row = model.normalizeRoutingRecord({json.dumps(row)});
      row.source_actionability = "structural-rebuild";
      if (!model.matchesRoutingFilters(row, {{
        intervention: "control-flow-reconstruction",
        evidenceStage: "materializable",
        secondarySignal: "branch-idiom",
        blockerFamily: "source-anchor"
      }})) throw new Error("expected routing match");
      if (model.matchesRoutingFilters(row, {{secondarySignal: "register-only-delta"}})) {{
        throw new Error("unexpected signal match");
      }}
      const search = model.routingSearchText(row);
      [row.primary_intervention, row.evidence_stage, ...row.secondary_signals,
       ...row.blocker_families].forEach((value) => {{
        if (!search.includes(value)) throw new Error(`missing search value: ${{value}}`);
      }});
      const detail = model.routingDetail(row);
      if (detail.primaryIntervention !== row.primary_intervention
          || detail.evidenceStage !== row.evidence_stage
          || detail.rawActionability !== "structural-rebuild") {{
        throw new Error("bad routing detail");
      }}
      detail.secondarySignals.push("mutated");
      detail.blockerFamilies.push("mutated");
      if (row.secondary_signals.includes("mutated") || row.blocker_families.includes("mutated")) {{
        throw new Error("routing detail leaked mutable arrays");
      }}
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_dashboard_model_frame_filter_metric_search_and_detail_behavior() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const rows = model.normalizeRecords([
        {{function: "sameFrame", frame_cause: "stack-object-offset-shift",
          frame_evidence: "checkdiff-only", frame_probe_status: "needs-attribution",
          frame_match_relevance: "match-neutral", frame_attribution_status: "checkdiff-only"}},
        {{function: "frameSize", frame_cause: "frame-too-large",
          frame_evidence: "checkdiff-only", frame_probe_status: "needs-attribution",
          frame_match_relevance: "unknown"}},
        {{function: "validatedFrame", frame_cause: "frame-too-large",
          frame_evidence: "probe-validated", frame_probe_status: "validated-improving",
          frame_match_relevance: "unknown"}}
      ]);
      const filtered = rows.filter((row) => model.matchesFrameFilters(row, {{
        evidence: "checkdiff-only", probeStatus: "needs-attribution",
        matchRelevance: "match-neutral"
      }}));
      if (filtered.map((row) => row.function).join(",") !== "sameFrame") {{
        throw new Error("frame filters selected the wrong rows");
      }}
      const metrics = model.frameMetricCounts(rows);
      if (metrics.needsAttribution !== 2 || metrics.materializable !== 0 ||
          metrics.validatedImproving !== 1) throw new Error("bad frame metrics");
      const detail = model.frameDetail(rows[0]);
      if (detail.evidence !== "checkdiff-only" ||
          detail.probeStatus !== "needs-attribution" ||
          detail.matchRelevance !== "match-neutral") throw new Error("bad detail");
      if (!model.frameSearchText(rows[0]).includes("stack-object-offset-shift")) {{
        throw new Error("missing frame search text");
      }}
      if (model.frameSearchText(rows[0]).includes("362")) throw new Error("legacy leak");
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_generated_legacy_payload_drives_v5_frame_model_behavior(tmp_path: Path) -> None:
    from tools.function_taxonomy_dashboard import generate_dashboard

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    write_jsonl(
        taxonomy_dir / "taxonomy.records.jsonl",
        [{
            "function": "sameFrame",
            "match_percent": 99.2,
            "work_bucket": "stack-local-layout",
            "frame_cause": "stack-object-offset-shift",
            "frame_raw_verdict": "checkdiff-only",
            "frame_attribution_status": "checkdiff-only",
            "frame_closability_tier": "reorder-gated-362",
            "source_actionability": "generator-gated",
            "actionability_reason": "needs #362",
        }],
    )
    generated = generate_dashboard(taxonomy_dir)
    payload = read_dashboard_payload(generated.dashboard_data_js)

    script = f"""
      const model = require({json.dumps(str(generated.dashboard_model_js))});
      const payload = {json.dumps(payload)};
      const rows = model.normalizeRecords(payload.records);
      const manifest = model.resolveManifest(payload.taxonomyManifest, rows, payload.queueCounts);
      const filtered = rows.filter((row) => model.matchesFrameFilters(row, {{
        evidence: "checkdiff-only", probeStatus: "needs-attribution",
        matchRelevance: "match-neutral"
      }}));
      if (manifest.schemaVersion !== 5 || filtered.length !== 1) throw new Error("bad e2e result");
      if (model.frameMetricCounts(rows).needsAttribution !== 1) throw new Error("bad metric");
      if (model.frameDetail(rows[0]).probeStatus !== "needs-attribution") throw new Error("bad detail");
      if (JSON.stringify({{rows, manifest}}).includes("362")) throw new Error("legacy leak");
    """
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_dashboard_payload_validation_rejects_an_omitted_observed_value(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import (
        build_dashboard_payload,
        validate_dashboard_payload,
    )

    taxonomy_dir = tmp_path / "taxonomy"
    write_manifest_taxonomy_dir(taxonomy_dir)
    payload = build_dashboard_payload(taxonomy_dir)
    broken = deepcopy(payload)
    broken["taxonomyManifest"]["bucketOrder"].remove("future-bucket")

    with pytest.raises(ValueError, match="work_bucket.*future-bucket"):
        validate_dashboard_payload(broken)


def test_generate_dashboard_copies_template_and_embeds_taxonomy_data(tmp_path: Path) -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH, generate_dashboard

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    template = tmp_path / "template.html"
    template.write_text(
        "<!doctype html><script src=\"dashboard-data.js\"></script>"
        "<script src=\"dashboard-model.js\"></script>",
        encoding="utf-8",
    )

    result = generate_dashboard(taxonomy_dir, template_path=template)

    assert result.dashboard_html == taxonomy_dir / "dashboard.html"
    assert result.dashboard_data_js == taxonomy_dir / "dashboard-data.js"
    assert result.dashboard_model_js == taxonomy_dir / "dashboard-model.js"
    assert result.dashboard_model_js.read_text(encoding="utf-8") == (
        DEFAULT_MODEL_PATH.read_text(encoding="utf-8")
    )
    assert result.record_count == 1
    assert result.queue_count == 1
    assert result.dashboard_html.read_text(encoding="utf-8") == template.read_text(
        encoding="utf-8"
    )

    payload = read_dashboard_payload(result.dashboard_data_js)
    assert [row["function"] for row in payload["records"]] == ["ftDemo_80000000"]
    assert payload["errors"] == [{"function": "bad"}]
    assert payload["reportOnly"] == [{"function": "report"}]
    assert payload["dbCompleted"] == [{"function": "done"}]
    assert payload["queueCounts"] == {"signature-call-type.tsv": 2}


def test_generate_dashboard_reports_missing_required_inputs(tmp_path: Path) -> None:
    from tools.function_taxonomy_dashboard import generate_dashboard

    taxonomy_dir = tmp_path / "taxonomy"
    taxonomy_dir.mkdir()
    template = tmp_path / "template.html"
    template.write_text("<!doctype html>", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="taxonomy.records.jsonl"):
        generate_dashboard(taxonomy_dir, template_path=template)


def test_dashboard_model_preserves_known_order_and_appends_unknown_values() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    if shutil.which("node") is None:
        pytest.skip("node is not installed")

    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const result = model.resolveManifest(
        {{
          schemaVersion: 2,
          bucketOrder: ["known-bucket"],
          tierOrder: [">=99%"],
          primaryOrder: ["known-primary"],
          actionabilityOrder: ["known-action"],
          frameEvidenceOrder: ["known-evidence"],
          frameProbeStatusOrder: ["known-status"],
          frameMatchRelevanceOrder: ["known-relevance"],
          queueFiles: ["known.tsv"],
          bucketInfo: {{
            "known-bucket": {{
              label: "Known Bucket",
              description: "Known.",
              focus: "Known.",
              color: "#123456"
            }}
          }},
          primaryInfo: {{}},
          actionabilityInfo: {{}},
          frameEvidenceInfo: {{}},
          frameProbeStatusInfo: {{}},
          frameMatchRelevanceInfo: {{}}
        }},
        [{{
          work_bucket: "future-bucket",
          match_tier: "future-tier",
          primary: "future-primary",
          source_actionability: "future-action",
          frame_evidence: "future-evidence",
          frame_probe_status: "future-status",
          frame_match_relevance: "future-relevance"
        }}],
        {{"known.tsv": 1, "future.tsv": 2}}
      );
      process.stdout.write(JSON.stringify(result));
    """
    proc = subprocess.run(
        ["node", "-e", script],
        text=True,
        capture_output=True,
        check=True,
    )
    resolved = json.loads(proc.stdout)

    assert resolved["bucketOrder"] == ["known-bucket", "future-bucket"]
    assert resolved["tierOrder"] == [">=99%", "future-tier"]
    assert resolved["primaryOrder"] == ["known-primary", "future-primary"]
    assert resolved["actionabilityOrder"] == ["known-action", "future-action"]
    assert resolved["frameEvidenceOrder"] == ["known-evidence", "future-evidence"]
    assert resolved["frameProbeStatusOrder"] == ["known-status", "future-status"]
    assert resolved["frameMatchRelevanceOrder"] == ["known-relevance", "future-relevance"]
    assert resolved["queueFiles"] == ["known.tsv", "future.tsv"]
    assert resolved["bucketInfo"]["future-bucket"]["color"] == "#647076"
    assert resolved["primaryInfo"]["future-primary"]["label"] == "Future Primary"


def test_dashboard_model_creates_own_fallback_metadata_for_prototype_named_values() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    if shutil.which("node") is None:
        pytest.skip("node is not installed")

    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const result = model.resolveManifest(
        {{}},
        [{{
          work_bucket: "__proto__",
          match_tier: "future-tier",
          primary: "constructor",
          source_actionability: "toString",
          frame_evidence: "__proto__",
          frame_probe_status: "constructor",
          frame_match_relevance: "toString",
          root_cause_keys: ["__proto__"]
        }}],
        {{}}
      );
      const hasOwn = (object, key) =>
        Object.prototype.hasOwnProperty.call(object, key);
      for (const [info, key, label] of [
        [result.bucketInfo, "__proto__", "__proto__"],
        [result.primaryInfo, "constructor", "Constructor"],
        [result.actionabilityInfo, "toString", "ToString"],
        [result.frameEvidenceInfo, "__proto__", "__proto__"],
        [result.frameProbeStatusInfo, "constructor", "Constructor"],
        [result.frameMatchRelevanceInfo, "toString", "ToString"],
        [result.rootCauseKeyInfo, "__proto__", "__proto__"]
      ]) {{
        if (!hasOwn(info, key) || typeof info[key] !== "object") {{
          throw new Error(`missing own fallback for ${{key}}`);
        }}
        if (info[key].label !== label) {{
          throw new Error(`wrong fallback label for ${{key}}`);
        }}
        if (!info[key].description.includes("No curated")) {{
          throw new Error(`missing fallback description for ${{key}}`);
        }}
      }}
      if (result.bucketInfo.__proto__.color !== "#647076") {{
        throw new Error("missing fallback bucket color");
      }}
    """
    subprocess.run(
        ["node", "-e", script],
        text=True,
        capture_output=True,
        check=True,
    )


def test_default_dashboard_template_loads_generated_data_and_model() -> None:
    from tools.function_taxonomy_dashboard import (
        DEFAULT_TEMPLATE_PATH,
        parse_dashboard_html,
    )

    parsed = parse_dashboard_html(DEFAULT_TEMPLATE_PATH)

    assert parsed.external_scripts == ["dashboard-data.js", "dashboard-model.js"]
    assert len(parsed.inline_scripts) == 1


def test_default_dashboard_template_exposes_routing_facets() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_TEMPLATE_PATH

    text = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")
    for control_id in (
        "primaryInterventionFilter",
        "evidenceStageFilter",
        "secondarySignalFilter",
        "blockerFamilyFilter",
    ):
        assert f'id="{control_id}"' in text
    assert 'id="sourceActionabilityFilter"' not in text
    assert "dashboardModel.matchesRoutingFilters" in text
    assert "Primary intervention" in text
    assert "Secondary signals" in text
    assert "Blocker families" in text


def test_default_dashboard_template_exposes_semantic_delta_facets() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_TEMPLATE_PATH

    text = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")
    for control_id in (
        "semanticDeltaFamilyFilter",
        "opcodeEditDirectionFilter",
        "normalizedTriggerFamilyFilter",
    ):
        assert f'id="{control_id}"' in text
        assert f'$("{control_id}").value = ""' in text
    assert "dashboardModel.matchesSemanticDeltaFilters" in text
    assert "dashboardModel.semanticDeltaSearchText" in text
    assert "semanticFilters" in text
    assert "Semantic delta families" in text
    assert "Opcode edit direction" in text
    assert "Normalized trigger" in text
    assert "Trigger cluster size" in text


def test_default_dashboard_template_exposes_root_cause_filter_and_detail() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_TEMPLATE_PATH

    text = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert 'id="rootCauseKeyFilter"' in text
    assert '$("rootCauseKeyFilter").value = ""' in text
    assert "dashboardModel.matchesRootCauseFilters" in text
    assert "dashboardModel.rootCauseSearchText" in text
    assert "Shared root-cause key" in text
    assert "Shared root-cause keys" in text
    assert "Affected rows" in text
    assert "dashboardModel.rootCauseMembershipDetail" in text
    assert "visible /" in text
    assert "if (state.selected) renderDetail(state.selected);" in text


def test_generate_dashboard_preserves_control_flow_shape_diagnostics_and_queues(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import generate_dashboard

    taxonomy_dir = tmp_path / "taxonomy"
    record = write_control_flow_taxonomy_dir(taxonomy_dir)

    result = generate_dashboard(taxonomy_dir)

    payload = read_dashboard_payload(result.dashboard_data_js)
    assert payload["records"][0]["control_flow_shape_hints"] == record[
        "control_flow_shape_hints"
    ]
    assert payload["records"][0]["control_flow_shape_validation_status"] == "not-run"
    assert payload["taxonomyManifest"]["schemaVersion"] == 5
    assert payload["taxonomyManifest"]["queueFiles"] == [
        "structural-reconstruction.tsv",
        *[f"{CONTROL_FLOW_QUEUE_PREFIX}.{kind}.tsv" for kind in CONTROL_FLOW_HINT_KINDS],
        f"{CONTROL_FLOW_QUEUE_PREFIX}.materializable.tsv",
        f"{CONTROL_FLOW_QUEUE_PREFIX}.terminal.tsv",
    ]


def test_generate_dashboard_accepts_legacy_records_without_control_flow_shape_fields(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_dashboard import generate_dashboard

    taxonomy_dir = tmp_path / "taxonomy"
    write_control_flow_taxonomy_dir(taxonomy_dir, legacy=True)

    payload = read_dashboard_payload(generate_dashboard(taxonomy_dir).dashboard_data_js)
    assert payload["taxonomyManifest"]["schemaVersion"] == 5
    assert "control_flow_shape_hints" not in payload["records"][0]


def test_dashboard_model_projects_optional_control_flow_shape_diagnostics() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    record = write_control_flow_taxonomy_dir_data()
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const record = {json.dumps(record)};
      const legacy = {{ function: "legacy_fn" }};
      process.stdout.write(JSON.stringify({{
        search: model.controlFlowShapeSearchText(record),
        detail: model.controlFlowShapeDetail(record),
        legacySearch: model.controlFlowShapeSearchText(legacy),
        legacyDetail: model.controlFlowShapeDetail(legacy)
      }}));
    """
    result = json.loads(
        subprocess.run(
            ["node", "-e", script], text=True, capture_output=True, check=True
        ).stdout
    )

    assert "branch-idiom" in result["search"]
    assert "one bounded source probe" in result["search"]
    assert "terminal-sibling" in result["search"]
    assert result["detail"]["hints"] == record["control_flow_shape_hints"]
    assert result["detail"]["validationStatus"] == "not-run"
    assert result["detail"]["validatedProbeCount"] == 0
    assert result["legacySearch"] == ""
    assert result["legacyDetail"] is None


def test_dashboard_model_projects_optional_opcode_delta_signatures() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_MODEL_PATH

    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    record = {
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": (
            '{"dominant":[["addi","ori",2],["lwz","stw",1]],'
            '"first":["lwz","stw"],"version":1}'
        ),
    }
    degraded = {
        "opcode_delta_signature_status": "missing-current-asm",
        "opcode_delta_signature": "",
    }
    malformed = {
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": "{not-json}",
    }
    available_empty = {
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": "",
    }
    script = f"""
      const model = require({json.dumps(str(DEFAULT_MODEL_PATH))});
      const record = {json.dumps(record)};
      const degraded = {json.dumps(degraded)};
      const malformed = {json.dumps(malformed)};
      const availableEmpty = {json.dumps(available_empty)};
      const legacy = {{ function: "legacy_fn" }};
      process.stdout.write(JSON.stringify({{
        search: model.opcodeDeltaSignatureSearchText(record),
        detail: model.opcodeDeltaSignatureDetail(record),
        degraded: model.opcodeDeltaSignatureDetail(degraded),
        malformed: model.opcodeDeltaSignatureDetail(malformed),
        availableEmpty: model.opcodeDeltaSignatureDetail(availableEmpty),
        legacy: model.opcodeDeltaSignatureDetail(legacy)
      }}));
    """
    result = json.loads(
        subprocess.run(
            ["node", "-e", script], text=True, capture_output=True, check=True
        ).stdout
    )

    assert result["search"] == record["opcode_delta_signature"]
    assert result["detail"]["first"] == ["lwz", "stw"]
    assert result["detail"]["dominant"] == [["addi", "ori", 2], ["lwz", "stw", 1]]
    assert result["degraded"] == {
        "status": "missing-current-asm",
        "signature": "",
        "first": [],
        "dominant": [],
    }
    assert result["malformed"] is None
    assert result["availableEmpty"] is None
    assert result["legacy"] is None
