"""Lifetime proof bundle generation and publication tests (Task 7)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))


def _json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _opaque_members(marker: str) -> dict[str, bytes]:
    from tools.mwcc_retro.backend_lifetime_proof import CANONICAL_MEMBERS

    return {name: f"{marker}:{name}\n".encode() for name in CANONICAL_MEMBERS}


def _exact_inputs() -> tuple[dict[str, bytes], dict[str, object], dict[str, object]]:
    from test_retro_backend_instrumentation_proof import valid_proof_and_manifest

    proof, hooks = valid_proof_and_manifest()
    inputs = {
        "raw-pe-cfg.v1.jsonl": (
            _json(
                {
                    "record_kind": "metadata",
                    "compiler_sha256": "a" * 64,
                }
            )
            + _json(
                {
                    "record_kind": "unreachable-executable-residue-summary",
                    "accepted": True,
                    "reconciliation_sha256": "a" * 64,
                }
            )
        ),
        "raw-ghidra-crosscheck.v1.json": _json(
            {
                "compiler_sha256": "a" * 64,
                "residue_reconciliation_sha256": "a" * 64,
                "residue_conflicts": [],
                "flow_mismatches": [],
                "byte_mismatches": [],
                "unresolved_raw_addresses": [],
            }
        ),
        "backend-lifetime-sites.candidate.v1.json": _json(
            {"proof_ready": True, "unresolved": []}
        ),
        "opcode-layouts.candidate.v1.json": _json(
            {"proof_ready": True, "unresolved": []}
        ),
        "backend-lifetime-audit.v1.json": _json(
            {"proof_ready": True, "unresolved": []}
        ),
        "gc_125n_lifetime_hooks.candidate.json": _json(hooks),
        "gc_125n_lifetime_proof.candidate.json": _json(proof),
        "gc_125n.candidate.json": _json({"backend_reader": {}, "entries": {}}),
        "REPORT.md": b"# Exact proof\n",
    }
    return inputs, proof, hooks


def _structured_exact_inputs():
    from tools.mwcc_retro.backend_lifetime_proof import (
        ExactLifetimeBundleInputs,
        ExactLifetimeProofPlan,
    )

    members, proof, hooks = _exact_inputs()
    return ExactLifetimeBundleInputs(
        compiler_sha256="a" * 64,
        raw_cfg_jsonl=members["raw-pe-cfg.v1.jsonl"],
        ghidra_crosscheck_json=members["raw-ghidra-crosscheck.v1.json"],
        value_analysis={"proof_ready": True, "unresolved": []},
        lifetime_site_inventory=json.loads(
            members["backend-lifetime-sites.candidate.v1.json"]
        ),
        opcode_layout_inventory=json.loads(
            members["opcode-layouts.candidate.v1.json"]
        ),
        opcode_tables={
            "opcode_table": proof["opcode_table"],
            "operand_rules": proof["operand_rules"],
        },
        proof_plan=ExactLifetimeProofPlan(
            allocation_sites=tuple(proof["allocation_sites"]),
            free_sites=tuple(proof["free_sites"]),
            operand_rewrite_sites=tuple(proof["operand_rewrite_sites"]),
            operand_mutation_sites=tuple(proof["operand_mutation_sites"]),
            code_emission_sites=tuple(proof["code_emission_sites"]),
            hook_sites=tuple(hooks["sites"]),
        ),
        candidate_table={"backend_reader": {}, "entries": {}},
        backend_map_candidates={"compiler": "GC/1.2.5n"},
    )


def test_resolver_rejects_missing_current(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import (
        LifetimeBundleError,
        resolve_lifetime_bundle,
    )

    with pytest.raises(LifetimeBundleError, match="CURRENT pointer is missing"):
        resolve_lifetime_bundle(tmp_path)


def test_generation_publishes_nine_members_in_exact_order(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import (
        CANONICAL_MEMBERS,
        generate_lifetime_bundle,
        resolve_lifetime_bundle,
    )

    inputs, proof, hooks = _exact_inputs()
    generated = generate_lifetime_bundle(
        inputs,
        tmp_path,
        proof_ready=True,
        compiler_sha256="a" * 64,
    )
    published = resolve_lifetime_bundle(tmp_path)

    assert tuple(generated.canonical_files()) == CANONICAL_MEMBERS
    assert tuple(published.canonical_files()) == CANONICAL_MEMBERS
    assert generated.canonical_files() == published.canonical_files()
    assert generated.audit_summary["binding_validated"] is True

    candidate = json.loads(
        generated.canonical_files()["gc_125n.candidate.json"]
    )
    registry = candidate["instrumentation_proofs"]
    assert registry == [
        {
            "compiler_executable_sha256": "a" * 64,
            "promoted": True,
            "proof_id": proof["proof_id"],
            "proof_sha256": generated.proof_sha256,
        }
    ]
    gate = candidate["backend_reader"]["pcode_instrumentation"]
    assert gate["proof_sha256"] == generated.proof_sha256
    assert gate["validated"] is True


def test_generation_is_byte_identical(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs, _, _ = _exact_inputs()
    first = generate_lifetime_bundle(
        inputs, tmp_path / "first", compiler_sha256="a" * 64
    )
    second = generate_lifetime_bundle(
        dict(reversed(tuple(inputs.items()))),
        tmp_path / "second",
        compiler_sha256="a" * 64,
    )

    assert first.canonical_files() == second.canonical_files()
    assert first.proof_sha256 == second.proof_sha256
    assert first.hook_manifest_sha256 == second.hook_manifest_sha256


def test_structured_generator_constructs_all_digest_bound_members(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import (
        CANONICAL_MEMBERS,
        generate_exact_lifetime_bundle,
        resolve_lifetime_bundle,
    )
    from tools.mwcc_retro.backend_runtime_hook_manifest import (
        runtime_hook_manifest_sha256,
    )

    generated = generate_exact_lifetime_bundle(
        _structured_exact_inputs(), tmp_path
    )
    members = generated.canonical_files()

    assert tuple(members) == CANONICAL_MEMBERS
    assert members == resolve_lifetime_bundle(tmp_path).canonical_files()
    manifest = json.loads(members["gc_125n_lifetime_hooks.candidate.json"])
    proof = json.loads(members["gc_125n_lifetime_proof.candidate.json"])
    audit = json.loads(members["backend-lifetime-audit.v1.json"])
    report = members["REPORT.md"].decode()
    assert proof["runtime_hook_manifest_sha256"] == runtime_hook_manifest_sha256(
        manifest
    )
    assert audit["proof_ready"] is True
    assert generated.proof_sha256 in report
    assert generated.hook_manifest_sha256 in report


def test_structured_generator_omits_proof_when_upstream_is_unresolved(tmp_path):
    from dataclasses import replace

    from tools.mwcc_retro.backend_lifetime_proof import (
        generate_exact_lifetime_bundle,
    )

    inputs = _structured_exact_inputs()
    inputs = replace(
        inputs,
        value_analysis={
            "proof_ready": False,
            "unresolved": [{"kind": "task5-gap"}],
        },
    )
    generated = generate_exact_lifetime_bundle(inputs, tmp_path)

    assert generated.audit_summary["proof_ready"] is False
    assert "gc_125n_lifetime_proof.candidate.json" not in generated.canonical_files()
    assert not (tmp_path / "CURRENT").exists()


def _synthetic_plan_inputs():
    from tools.mwcc_retro.x86_cfg import FunctionEntry, Instruction

    instructions = (
        Instruction(0x100, 5, "e800000000", "call", "0x100"),
        Instruction(0x105, 1, "90", "nop", ""),
        Instruction(0x200, 5, "e800000000", "call", "0x200"),
        Instruction(0x205, 1, "90", "nop", ""),
        Instruction(0x300, 4, "66894102", "mov", "word ptr [ecx+2], ax"),
        Instruction(0x304, 3, "83c10c", "add", "ecx, 0xc"),
        Instruction(0x350, 7, "c7402a00000000", "mov", "dword ptr [eax+0x2a], 0"),
        Instruction(0x357, 1, "90", "nop", ""),
        Instruction(0x360, 7, "c7402a01000000", "mov", "dword ptr [eax+0x2a], 1"),
        Instruction(0x367, 1, "90", "nop", ""),
        Instruction(0x400, 1, "53", "push", "ebx"),
        Instruction(0x401, 1, "90", "nop", ""),
        Instruction(0x402, 1, "c3", "ret", ""),
        Instruction(0x500, 2, "8908", "mov", "dword ptr [eax], ecx"),
        Instruction(0x502, 1, "90", "nop", ""),
    )
    cfg = SimpleNamespace(
        instructions=instructions,
        function_entries=(FunctionEntry(0x400, True, ("test",)),),
    )
    inventory = SimpleNamespace(
        compiler_sha256="a" * 64,
        proof_ready=True,
        unresolved=(),
        allocations=(
            SimpleNamespace(
                address=0x100,
                classification="pcode",
                ownership="reachable-owned-call",
                allocator=0x441F20,
            ),
        ),
        reuses=(),
        field_writes=(),
        releases=(
            SimpleNamespace(
                address=0x200,
                classification="persistent-arena-release",
                affected_arenas=(0x441F20,),
            ),
        ),
        rewrite_sites=(
            SimpleNamespace(
                address=0x300,
                classification="pcode-field-write:operand[0].payload",
            ),
        ),
        mutation_sites=(
            SimpleNamespace(address=0x400, classification="replace-pcode"),
        ),
        emission_sites=(
            SimpleNamespace(
                address=0x500,
                classification="encoder-result-buffer-write",
            ),
        ),
    )
    return cfg, inventory


def test_exact_plan_is_derived_from_instruction_bound_site_inventory(tmp_path):
    from dataclasses import replace

    from tools.mwcc_retro.backend_lifetime_proof import (
        derive_exact_lifetime_proof_plan,
        generate_exact_lifetime_bundle,
    )

    cfg, inventory = _synthetic_plan_inputs()
    plan = derive_exact_lifetime_proof_plan(cfg, inventory)

    assert plan.unresolved == ()
    assert [row["operation"] for row in plan.hook_sites] == [
        "allocation",
        "release",
        "operand-rewrite",
        "replace",
        "final-buffer-emission",
    ]
    rewrite = next(
        row for row in plan.hook_sites if row["operation"] == "operand-rewrite"
    )
    assert rewrite["breakpoints"][0]["instruction_bytes"] == "66894102"
    assert rewrite["breakpoints"][1]["address"] == 0x304

    inputs = replace(
        _structured_exact_inputs(),
        lifetime_site_inventory={
            "compiler_sha256": "a" * 64,
            "proof_ready": True,
            "unresolved": [],
        },
        proof_plan=plan,
    )
    generated = generate_exact_lifetime_bundle(inputs, tmp_path)
    assert generated.audit_summary["proof_ready"] is True


def test_exact_plan_derives_instruction_bound_cache_release_and_acquire_hooks():
    from tools.mwcc_retro.backend_lifetime_proof import (
        derive_exact_lifetime_proof_plan,
    )

    cfg, inventory = _synthetic_plan_inputs()
    inventory.reuses = (
        SimpleNamespace(
            address=0x350,
            classification="objobject-cache-reuse-flag-write",
        ),
        SimpleNamespace(
            address=0x360,
            classification="objobject-cache-reuse-flag-write",
        ),
    )
    inventory.field_writes = (
        SimpleNamespace(
            address=0x350,
            object_type="objobject",
            field="cache-reuse-flag",
            width=4,
            operation="mov",
            value=SimpleNamespace(kind="exact", values=frozenset({0})),
        ),
        SimpleNamespace(
            address=0x360,
            object_type="objobject",
            field="cache-reuse-flag",
            width=4,
            operation="mov",
            value=SimpleNamespace(kind="exact", values=frozenset({1})),
        ),
    )

    plan = derive_exact_lifetime_proof_plan(cfg, inventory)

    assert plan.unresolved == ()
    release = next(
        row for row in plan.hook_sites if row["operation"] == "cache-release"
    )
    acquire = next(
        row for row in plan.hook_sites if row["operation"] == "cache-acquire"
    )
    assert release["family"] == "free_sites"
    assert acquire["family"] == "allocation_sites"
    for row in (release, acquire):
        assert row["pairing"] == "same-thread-instruction"
        assert row["capture_sources"] == [
            {
                "name": "entity_pointer",
                "source_kind": "effective-address",
                "phase": "before",
                "operand_index": 0,
                "register": None,
                "stack_argument_index": None,
                "byte_offset": -0x2A,
                "byte_width": 4,
            }
        ]


def test_exact_plan_blocks_cache_transition_without_exact_written_value():
    from tools.mwcc_retro.backend_lifetime_proof import (
        derive_exact_lifetime_proof_plan,
    )

    cfg, inventory = _synthetic_plan_inputs()
    inventory.reuses = (
        SimpleNamespace(
            address=0x350,
            classification="objobject-cache-reuse-flag-write",
        ),
    )
    inventory.field_writes = (
        SimpleNamespace(
            address=0x350,
            object_type="objobject",
            field="cache-reuse-flag",
            width=4,
            operation="mov",
            value=SimpleNamespace(kind="unknown", values=frozenset()),
        ),
    )

    plan = derive_exact_lifetime_proof_plan(cfg, inventory)

    assert "cache-reuse-transition-unproved:0x350" in plan.unresolved


def test_unresolved_audit_prevents_proof_and_publication(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs, _, _ = _exact_inputs()
    inputs["backend-lifetime-audit.v1.json"] = _json(
        {"proof_ready": False, "unresolved": [{"kind": "computed-target"}]}
    )
    bundle = generate_lifetime_bundle(
        inputs, tmp_path, proof_ready=True, compiler_sha256="a" * 64
    )

    assert bundle.audit_summary["proof_ready"] is False
    assert bundle.audit_summary["unresolved_inputs"]
    assert "gc_125n_lifetime_proof.candidate.json" not in bundle.canonical_files()
    assert not (tmp_path / "CURRENT").exists()


@pytest.mark.parametrize(
    ("member", "payload"),
    (
        (
            "raw-pe-cfg.v1.jsonl",
            b'{"record_kind":"unresolved-control-target","address":1}\n',
        ),
        (
            "raw-pe-cfg.v1.jsonl",
            b'{"record_kind":"unreachable-executable-residue-summary",'
            b'"accepted":false}\n',
        ),
        (
            "raw-ghidra-crosscheck.v1.json",
            _json(
                {
                    "residue_reconciliation_sha256": None,
                    "residue_conflicts": [{"address": 1}],
                    "flow_mismatches": [],
                    "byte_mismatches": [],
                    "unresolved_raw_addresses": [],
                }
            ),
        ),
        (
            "raw-ghidra-crosscheck.v1.json",
            _json(
                {
                    "residue_reconciliation_sha256": "a" * 64,
                    "residue_conflicts": [],
                    "flow_mismatches": [{"side": "ghidra-only"}],
                    "byte_mismatches": [],
                    "unresolved_raw_addresses": [],
                }
            ),
        ),
    ),
)
def test_control_and_crosscheck_blockers_prevent_publication(
    tmp_path, member, payload
):
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs, _, _ = _exact_inputs()
    inputs[member] = payload
    bundle = generate_lifetime_bundle(
        inputs, tmp_path, proof_ready=True, compiler_sha256="a" * 64
    )

    assert bundle.audit_summary["proof_ready"] is False
    assert bundle.audit_summary["unresolved_inputs"]
    assert not (tmp_path / "CURRENT").exists()


def test_raw_only_crosscheck_delta_is_reported_but_not_a_blocker(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs, _, _ = _exact_inputs()
    inputs["raw-ghidra-crosscheck.v1.json"] = _json(
        {
            "compiler_sha256": "a" * 64,
            "residue_reconciliation_sha256": "a" * 64,
            "residue_conflicts": [],
            "flow_mismatches": [{"side": "raw-only"}],
            "byte_mismatches": [],
            "unresolved_raw_addresses": [],
        }
    )
    bundle = generate_lifetime_bundle(
        inputs, tmp_path, proof_ready=True, compiler_sha256="a" * 64
    )

    assert bundle.audit_summary["proof_ready"] is True
    assert (tmp_path / "CURRENT").is_file()


def test_raw_and_crosscheck_residue_reconciliation_must_match(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs, _, _ = _exact_inputs()
    inputs["raw-pe-cfg.v1.jsonl"] = (
        _json(
            {
                "record_kind": "metadata",
                "compiler_sha256": "a" * 64,
            }
        )
        + _json(
            {
                "record_kind": "unreachable-executable-residue-summary",
                "accepted": True,
                "reconciliation_sha256": "b" * 64,
            }
        )
    )

    bundle = generate_lifetime_bundle(
        inputs, tmp_path, proof_ready=True, compiler_sha256="a" * 64
    )

    assert not bundle.audit_summary["proof_ready"]
    assert any(
        row.endswith("residue-reconciliation-binding")
        for row in bundle.audit_summary["unresolved_inputs"]
    )
    assert not (tmp_path / "CURRENT").exists()


@pytest.mark.parametrize(
    ("member", "payload"),
    (
        (
            "raw-pe-cfg.v1.jsonl",
            b'{"record_kind":"metadata","compiler_sha256":"'
            + b"b" * 64
            + b'"}\n'
            b'{"record_kind":"unreachable-executable-residue-summary",'
            b'"accepted":true}\n',
        ),
        (
            "raw-ghidra-crosscheck.v1.json",
            _json(
                {
                    "compiler_sha256": "b" * 64,
                    "residue_reconciliation_sha256": "a" * 64,
                    "residue_conflicts": [],
                    "flow_mismatches": [],
                    "byte_mismatches": [],
                    "unresolved_raw_addresses": [],
                }
            ),
        ),
    ),
)
def test_audit_artifact_compiler_binding_blocks_publication(
    tmp_path, member, payload
):
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs, _, _ = _exact_inputs()
    inputs[member] = payload
    bundle = generate_lifetime_bundle(
        inputs, tmp_path, compiler_sha256="a" * 64
    )

    assert bundle.audit_summary["proof_ready"] is False
    assert not (tmp_path / "CURRENT").exists()


@pytest.mark.parametrize(
    "missing",
    (
        "gc_125n_lifetime_proof.candidate.json",
        "gc_125n_lifetime_hooks.candidate.json",
        "gc_125n.candidate.json",
        "REPORT.md",
    ),
)
def test_ready_generation_requires_every_exact_member(tmp_path, missing):
    from tools.mwcc_retro.backend_lifetime_proof import (
        LifetimeBundleError,
        generate_lifetime_bundle,
    )

    inputs, _, _ = _exact_inputs()
    del inputs[missing]
    with pytest.raises(LifetimeBundleError, match="missing exact lifetime"):
        generate_lifetime_bundle(
            inputs, tmp_path, proof_ready=True, compiler_sha256="a" * 64
        )
    assert not (tmp_path / "CURRENT").exists()


def test_hook_tamper_fails_before_publication(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import (
        LifetimeBundleError,
        generate_lifetime_bundle,
    )

    inputs, _, hooks = _exact_inputs()
    hooks["sites"][0]["proof_address"] += 1
    inputs["gc_125n_lifetime_hooks.candidate.json"] = _json(hooks)

    with pytest.raises(LifetimeBundleError, match="runtime hook manifest"):
        generate_lifetime_bundle(inputs, tmp_path, compiler_sha256="a" * 64)
    assert not (tmp_path / "CURRENT").exists()


def test_resolver_rejects_tampered_member(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import (
        LifetimeBundleError,
        publish_lifetime_bundle,
        resolve_lifetime_bundle,
    )

    published = publish_lifetime_bundle(
        tmp_path, _opaque_members("old"), compiler_sha256="a" * 64
    )
    report_path = published.path("REPORT.md")
    report = report_path.read_bytes()
    report_path.write_bytes(bytes([report[0] ^ 1]) + report[1:])

    with pytest.raises(LifetimeBundleError, match="member hash differs: REPORT.md"):
        resolve_lifetime_bundle(tmp_path)


def test_resolver_rejects_manifest_tamper(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import (
        LifetimeBundleError,
        publish_lifetime_bundle,
        resolve_lifetime_bundle,
    )

    published = publish_lifetime_bundle(
        tmp_path, _opaque_members("old"), compiler_sha256="a" * 64
    )
    manifest = (
        tmp_path
        / "generations"
        / published.generation_name
        / "MANIFEST.json"
    )
    manifest.write_bytes(manifest.read_bytes() + b" ")

    with pytest.raises(LifetimeBundleError, match="manifest hash differs"):
        resolve_lifetime_bundle(tmp_path)


def test_resolver_binds_content_addressed_generation_name(tmp_path):
    from tools.mwcc_retro.backend_lifetime_proof import (
        LifetimeBundleError,
        publish_lifetime_bundle,
        resolve_lifetime_bundle,
    )

    published = publish_lifetime_bundle(
        tmp_path, _opaque_members("old"), compiler_sha256="a" * 64
    )
    replacement_name = "gen-" + "f" * 64
    published.generation_dir.rename(tmp_path / "generations" / replacement_name)
    current_path = tmp_path / "CURRENT"
    current = json.loads(current_path.read_bytes())
    current["generation"] = replacement_name
    current_path.write_bytes(_json(current))

    with pytest.raises(
        LifetimeBundleError, match="generation name differs from manifest hash"
    ):
        resolve_lifetime_bundle(tmp_path)


FAILURE_EVENTS = tuple(
    event
    for name in (
        "raw-pe-cfg.v1.jsonl",
        "raw-ghidra-crosscheck.v1.json",
        "backend-lifetime-sites.candidate.v1.json",
        "opcode-layouts.candidate.v1.json",
        "backend-lifetime-audit.v1.json",
        "gc_125n_lifetime_hooks.candidate.json",
        "gc_125n_lifetime_proof.candidate.json",
        "gc_125n.candidate.json",
        "REPORT.md",
    )
    for event in (f"member:{name}:write", f"member:{name}:fsync")
) + (
    "manifest:write",
    "manifest:fsync",
    "staging-directory:fsync",
    "generation:rename",
    "generations-directory:fsync",
    "current:write",
    "current:fsync",
    "current:replace",
    "output-root:fsync",
)


@pytest.mark.parametrize("failure_event", FAILURE_EVENTS)
def test_failure_restart_never_resolves_a_mixed_generation(tmp_path, failure_event):
    from tools.mwcc_retro.backend_lifetime_proof import (
        publish_lifetime_bundle,
        resolve_lifetime_bundle,
    )

    old = _opaque_members("old")
    new = _opaque_members("new")
    publish_lifetime_bundle(tmp_path, old, compiler_sha256="a" * 64)

    def fail(event: str) -> None:
        if event == failure_event:
            raise RuntimeError(event)

    with pytest.raises(RuntimeError, match=failure_event):
        publish_lifetime_bundle(
            tmp_path,
            new,
            compiler_sha256="a" * 64,
            failure_injector=fail,
        )

    visible = resolve_lifetime_bundle(tmp_path).canonical_files()
    assert visible in (old, new)
    assert len({payload.split(b":", 1)[0] for payload in visible.values()}) == 1


def test_candidate_proof_digest_is_rfc8785_not_member_byte_hash(tmp_path):
    from tools.mwcc_retro.backend_instrumentation_proof import proof_sha256
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle

    inputs, proof, _ = _exact_inputs()
    bundle = generate_lifetime_bundle(
        inputs, tmp_path, compiler_sha256="a" * 64
    )

    proof_bytes = bundle.canonical_files()[
        "gc_125n_lifetime_proof.candidate.json"
    ]
    assert bundle.proof_sha256 == proof_sha256(proof)
    assert bundle.proof_sha256 != hashlib.sha256(proof_bytes).hexdigest()
