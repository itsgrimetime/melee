"""Tests for bounded, evidence-only live probe selection (Task 9)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

from tools.mwcc_retro.backend_live_probe_selection import (  # noqa: E402
    IncompleteSelectionError,
    PreflightLimits,
    discover_live_probe_candidates,
    select_live_probe_set,
    summarize_live_probe_features,
    validate_live_probe_selection,
    validate_live_probe_union,
    write_live_probe_selection,
)


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _runtime(*, hits: list[str], events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "validated",
        "compiler_executable_sha256": "a" * 64,
        "proof_id": "proof-1",
        "proof_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "expected_site_ids": ["emit", "mutation", "rewrite"],
        "installed_site_ids": ["emit", "mutation", "rewrite"],
        "hit_site_ids": hits,
        "lifecycle_events": [],
        "pcode_events": events,
        "event_cap": 8192,
        "dropped_events": 0,
        "truncated": False,
        "errors": [],
        "capabilities": [],
    }


def _write_probe_pair(root: Path, *, source: str = "src/test.c", function: str = "fn") -> Path:
    map_dir = root / "map"
    pcode_dir = root / "pcode"
    map_dir.mkdir(parents=True)
    pcode_dir.mkdir(parents=True)
    runtime_events = [
        {
            "event": "operand_rewrite",
            "pcode_event_sequence": 0,
            "instrumented_site_id": "rewrite",
            "pcode_id": "pc-1",
            "operand_lineage_id": "ol-1",
            "class_id": 1,
            "class_name": "fpr",
            "virtual_kind": "f",
            "virtual": 3,
            "ig_id": 3,
            "allocated_physical": 2,
        },
        {
            "event": "pcode_mutation",
            "pcode_event_sequence": 1,
            "instrumented_site_id": "mutation",
            "mutation_kind": "spill",
            "inputs": [{"pcode_id": "pc-1"}],
            "outputs": [{"pcode_id": "pc-2"}],
        },
    ]
    map_payload = {
        "schema_version": "mwcc-retro-backend-map-probe.v1",
        "requested_function": function,
        "requested_function_matched": True,
        "errors": [],
        "events": [
            {
                "sequence": 4,
                "stage": "final_scheduler",
                "frame_state": {
                    "locals": {
                        "objects_sample": [
                            {
                                "object": 0x1200,
                                "name": "counter",
                                "stack_offset": -8,
                                "size": 4,
                            }
                        ]
                    }
                },
                "ig_object_bindings": [
                    {
                        "event_id": "map:4:ig:1",
                        "objobject_ptr": 0x1200,
                        "class_id": 0,
                        "virtual_kind": "r",
                        "virtual": 1,
                        "ig_id": 1,
                    },
                    {
                        "event_id": "map:4:ig:2",
                        "objobject_ptr": 0x1200,
                        "class_id": 0,
                        "virtual_kind": "r",
                        "virtual": 2,
                        "ig_id": 2,
                    },
                ],
            }
        ],
        "runtime_instrumentation": _runtime(
            hits=["mutation", "rewrite"], events=runtime_events
        ),
    }
    pcode_payload = {
        "schema_version": "mwcc-retro-backend-pcode-snapshot.v1",
        "requested_function": function,
        "requested_function_matched": True,
        "errors": [],
        "runtime_instrumentation": _runtime(
            hits=["mutation", "rewrite"], events=runtime_events
        ),
    }
    (map_dir / "backend-map-probe.json").write_bytes(_canonical(map_payload))
    (pcode_dir / "backend-pcode-snapshot.json").write_bytes(
        _canonical(pcode_payload)
    )
    out = root / "backend-live-features.v1.json"
    summarize_live_probe_features(
        map_dir, pcode_dir, out, source=source, function=function
    )
    return out


def test_preflight_limits_are_positive_and_canonical() -> None:
    limits = PreflightLimits(129, 257, 129)
    assert limits.to_dict() == {
        "max_candidates": 129,
        "max_compile_attempts": 257,
        "max_outputs": 129,
    }
    with pytest.raises(ValueError, match="positive"):
        PreflightLimits(0, 1, 1)


def test_discovery_uses_matched_numeric_report_order_and_stays_below_cap(
    tmp_path: Path,
) -> None:
    report = {
        "units": [
            {
                "metadata": {"source_path": "src/z.c"},
                "functions": [
                    {
                        "name": "late",
                        "size": 20,
                        "fuzzy_match_percent": 100.0,
                        "metadata": {"virtual_address": 0x80002000},
                    },
                    {
                        "name": "unmatched",
                        "size": 4,
                        "fuzzy_match_percent": 99.9,
                        "metadata": {"virtual_address": 0x80000001},
                    },
                ],
            },
            {
                "metadata": {"source_path": "src/a.c"},
                "functions": [
                    {
                        "name": "early",
                        "size": 12,
                        "fuzzy_match_percent": 100.0,
                        "metadata": {"virtual_address": 0x80001000},
                    }
                ],
            },
        ]
    }
    (tmp_path / "build" / "GALE01").mkdir(parents=True)
    (tmp_path / "build" / "GALE01" / "report.json").write_text(
        json.dumps(report)
    )
    for path in (tmp_path / "src" / "a.c", tmp_path / "src" / "z.c"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("void f(void) {}\n")

    rows = discover_live_probe_candidates(
        tmp_path, PreflightLimits(3, 7, 3)
    )

    assert len(rows) == 2 < 3
    assert rows[0]["function"] == "mnDiagram_DrawFighterHeaders"
    assert rows[1]["function"] == "early"
    assert rows[1]["address"] == 0x80001000
    assert all(row["function"] != "unmatched" for row in rows)


def test_summary_derives_only_cited_observed_rows(tmp_path: Path) -> None:
    out = _write_probe_pair(tmp_path)
    payload = json.loads(out.read_text())

    assert payload["schema_version"] == "mwcc-retro-live-features.v1"
    assert payload["named_local_identities"][0]["event_id"].startswith("map:")
    assert payload["named_local_identities"][0]["name"] == "counter"
    binding = payload["address_taken_multi_virtual_bindings"][0]
    assert binding["objobject_ptr"] == 0x1200
    assert binding["virtuals"] == [1, 2]
    assert len(binding["event_ids"]) == 2
    assert payload["fpr_allocation_events"][0]["event_id"] == "pcode:0"
    assert payload["spill_events"][0]["event_id"] == "pcode:1"
    assert payload["trace_identity"] == {
        "source": "src/test.c",
        "function": "fn",
        "compiler_executable_sha256": "a" * 64,
        "proof_id": "proof-1",
        "proof_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
    }


def test_summary_rejects_unvalidated_or_disagreeing_live_rows(tmp_path: Path) -> None:
    out = _write_probe_pair(tmp_path)
    payload_path = tmp_path / "pcode" / "backend-pcode-snapshot.json"
    payload = json.loads(payload_path.read_text())
    payload["runtime_instrumentation"]["truncated"] = True
    payload_path.write_bytes(_canonical(payload))
    with pytest.raises(ValueError, match="truncated"):
        summarize_live_probe_features(
            tmp_path / "map", tmp_path / "pcode", out,
            source="src/test.c", function="fn",
        )


def test_selection_requires_all_four_categories_and_binds_exact_summaries(
    tmp_path: Path,
) -> None:
    paths: list[Path] = [
        _write_probe_pair(
            tmp_path / "0000",
            source="src/melee/mn/mndiagram.c",
            function="mnDiagram_DrawFighterHeaders",
        )
    ]
    for index in range(1, 4):
        paths.append(_write_probe_pair(tmp_path / f"{index:04d}", function=f"fn{index}"))
    candidate = {"schema_version": "candidate", "value": 1}

    payload = select_live_probe_set(paths, candidate)

    assert [row["category"] for row in payload["probes"]] == [
        "complex-control",
        "named-local",
        "address-taken-multi-virtual",
        "fpr-and-spill",
    ]
    assert payload["probes"][0]["function"] == "mnDiagram_DrawFighterHeaders"
    assert len(payload["feature_summary_sha256s"]) == 4
    assert payload["candidate_table_sha256"] == hashlib.sha256(
        json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    selection_path = tmp_path / "selection.json"
    write_live_probe_selection(payload, selection_path)
    assert validate_live_probe_selection(
        json.loads(selection_path.read_text()),
        preflight_root=tmp_path,
        candidate_table=candidate,
    ) == ()

    paths[0].write_text("{}\n")
    assert "feature summary SHA-256 mismatch" in "\n".join(
        validate_live_probe_selection(
            payload, preflight_root=tmp_path, candidate_table=candidate
        )
    )


def test_selection_rejects_feature_claim_without_event_ids(tmp_path: Path) -> None:
    complex_path = _write_probe_pair(
        tmp_path / "0000",
        source="src/melee/mn/mndiagram.c",
        function="mnDiagram_DrawFighterHeaders",
    )
    path = _write_probe_pair(tmp_path / "0001", function="named")
    payload = json.loads(path.read_text())
    payload["named_local_identities"][0].pop("event_id")
    path.write_bytes(_canonical(payload))
    with pytest.raises(IncompleteSelectionError, match="named-local"):
        select_live_probe_set([complex_path, path], {"candidate": True})


def test_union_requires_exact_installs_per_run_per_run_hits_and_full_union(
    tmp_path: Path,
) -> None:
    candidate = {
        "instrumentation_proofs": [{"proof_id": "proof-1", "proof_sha256": "b" * 64}],
        "backend_reader": {
            "pcode_instrumentation": {
                "compiler_executable_sha256": "a" * 64,
                "proof_id": "proof-1",
                "proof_sha256": "b" * 64,
                "operand_rewrite_site_ids": ["rewrite"],
                "operand_mutation_site_ids": ["mutation"],
                "code_emission_site_ids": ["emit"],
            }
        },
    }
    probes = []
    for index, function in enumerate(("a", "b", "c", "d")):
        probes.append({"source": f"src/{function}.c", "function": function})
        for probe_name in ("probe-backend-map", "probe-backend-pcode"):
            run = tmp_path / function / probe_name
            run.mkdir(parents=True)
            payload = {
                "runtime_instrumentation": _runtime(
                    hits=["rewrite", "mutation"] + (["emit"] if index == 0 else []),
                    events=[],
                )
            }
            filename = (
                "backend-map-probe.json"
                if probe_name.endswith("map")
                else "backend-pcode-snapshot.json"
            )
            (run / filename).write_bytes(_canonical(payload))
    manifest = {
        "compiler_executable_sha256": "a" * 64,
        "proof_id": "proof-1",
        "sites": [
            {"site_id": "rewrite", "hit_policy": "per-run"},
            {"site_id": "mutation", "hit_policy": "probe-union"},
            {"site_id": "emit", "hit_policy": "probe-union"},
        ],
    }
    selection = {"probes": probes}

    result = validate_live_probe_union(selection, tmp_path, manifest, candidate)

    assert result["errors"] == []
    assert result["union_hit_site_ids"] == ["emit", "mutation", "rewrite"]
    assert len(result["runs"]) == 4

    broken = tmp_path / "d" / "probe-backend-pcode" / "backend-pcode-snapshot.json"
    payload = json.loads(broken.read_text())
    payload["runtime_instrumentation"]["installed_site_ids"].remove("emit")
    broken.write_bytes(_canonical(payload))
    assert "installed site inventory differs" in "\n".join(
        validate_live_probe_union(selection, tmp_path, manifest, candidate)["errors"]
    )
