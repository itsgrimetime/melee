"""RED tests for interprocedural abstract value/type analysis (Task 5).

These tests must FAIL before the implementation exists (import failure for
the module, then attribute/behavior failures after the module skeleton).
"""

from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

from tools.mwcc_retro import pe as pe_mod  # noqa: E402
from tools.mwcc_retro.x86_cfg import (  # noqa: E402
    AnalysisLimits,
    UnresolvedControlTarget,
    build_seed_inventory,
    recover_cfg,
)

# ── Synthetic PE fixtures ──────────────────────────────────────────────────


def _minimal_pe(text_bytes: bytes, *, text_va: int = 0x00401000) -> pe_mod.Image:
    """Build a minimal executable-only PE image from x86 bytes."""
    text_size = ((len(text_bytes) + 0xFFF) // 0x1000) * 0x1000
    rdata_va = text_va + text_size
    data = bytearray(text_size + 0x1000)
    data[:len(text_bytes)] = text_bytes

    return pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, text_size, text_size, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, text_size, 0x1000, 0x1000, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + text_size),),
    )


def _recover(image: pe_mod.Image) -> tuple:
    """Recover CFG from a minimal image."""
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        AnalysisLimits.for_image(image),
    )
    return image, cfg


def _limits(image: pe_mod.Image) -> AnalysisLimits:
    return AnalysisLimits.for_image(image)


# ── Lattice tests ──────────────────────────────────────────────────────────


def test_abstract_value_import():
    """Module must exist and export the four required frozen types."""
    from tools.mwcc_retro.backend_abstract_values import (  # noqa: F401
        AbstractValue,
        AnalysisResult,
        FunctionSummary,
        MachineState,
        analyze_values,
    )


def test_exact_value_join_is_idempotent():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    a = AbstractValue(kind="exact", values=frozenset({42}))
    assert a.join(a) == a


def test_exact_join_exact_yields_finite():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    a = AbstractValue(kind="exact", values=frozenset({10}))
    b = AbstractValue(kind="exact", values=frozenset({20}))
    joined = a.join(b)
    assert joined.kind == "finite"
    assert joined.values == frozenset({10, 20})


def test_bottom_join_other_is_other():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    bottom = AbstractValue(kind="bottom")
    exact = AbstractValue(kind="exact", values=frozenset({7}))
    assert bottom.join(exact) == exact
    assert exact.join(bottom) == exact


def test_unknown_join_anything_is_unknown():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    unknown = AbstractValue(kind="unknown")
    exact = AbstractValue(kind="exact", values=frozenset({1}))
    assert unknown.join(exact).kind == "unknown"
    assert exact.join(unknown).kind == "unknown"


def test_incompatible_known_origins_join_as_symbolic_runtime_choice():
    """Known path values are dynamic, not epistemically unknown."""
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    pointer = AbstractValue(
        kind="pointer", pointer_type="objobject", pointer_base=1
    )
    exact = AbstractValue(kind="exact", values=frozenset({7}))
    joined = pointer.join(exact)
    assert joined.kind == "symbolic"
    assert "choice" in joined.affine_symbol


def test_null_and_image_pointer_lattice_values_are_concrete():
    """Null remains finite while mapped address use becomes an image pointer."""
    text = bytes.fromhex(
        "b8 00 00 00 00"  # mov eax, 0
        "bb 00 20 40 00"  # mov ebx, 0x402000
        "89 03"  # mov [ebx], eax
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.kind == "null"
    assert summary.return_value.is_exact
    assert summary.return_value.exact_value == 0
    write = result.writes_at(0x0040100A)[0]
    assert write.base.pointer_type == "image"
    assert write.base.pointer_base == 0x00402000


# ── Transfer function tests ────────────────────────────────────────────────


def test_mov_imm_produces_exact_value():
    """``mov eax, 0x2A`` → EAX = exact 42."""
    text = bytes.fromhex("b8 2a 00 00 00 c3")
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.is_exact
    assert summary.return_value.exact_value == 42


def test_affine_pcode_allocation_survives_wrapper_call():
    """Affine value ``0x28 + 0x0C * arg_count`` must survive a wrapper call.

    Pattern:
        push arg_count      ; [ESP+4] = N
        call alloc_wrapper  ; wrapper forwards to allocator
        ...
    alloc_wrapper:
        mov eax, [esp+4]    ; load arg_count
        imul eax, eax, 0xC  ; eax = N * 12
        add eax, 0x28       ; eax = 0x28 + 0x0C * N
        push eax
        call actual_alloc
        ret
    """
    text = bytes.fromhex(
        # Wrapper at 0x441F80:
        "8b 44 24 04"  # mov eax, [esp+4]
        "6b c0 0c"  # imul eax, eax, 0xC
        "83 c0 28"  # add eax, 0x28
        "50"  # push eax
        "e8 10 00 00 00"  # call 0x441FA0
        "83 c4 04"  # add esp, 4
        "c3"
        # padding to 0x441FA0
        "90 90 90 90 90 90 90 90 90 90 90 90"
        # arena allocator fixture entry at 0x441FA0:
        "c3"
    )
    image = _minimal_pe(text, text_va=0x00441F80)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    call = result.call_at(0x00441F8B)
    assert call.target == 0x00441FA0
    assert call.argument(0).affine == (0x28, 0x0C, "arg0")
    assert call.return_value.pointer_type == "arena-allocation"
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.allocations[0].size.affine == (0x28, 0x0C, "arg0")


def test_three_operand_imul_uses_the_explicit_source():
    """``imul dst, src, imm`` must not read the old destination value."""
    text = bytes.fromhex(
        "8b 44 24 04"  # mov eax, [esp+4]
        "6b c8 0c"  # imul ecx, eax, 0xC
        "83 c1 28"  # add ecx, 0x28
        "51"  # push ecx
        "e8 10 00 00 00"  # call 0x441FA0
        "83 c4 04"  # add esp, 4
        "c3"
        "90 90 90 90 90 90 90 90 90 90 90 90"
        "c3"
    )
    image = _minimal_pe(text, text_va=0x00441F80)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert result.call_at(0x00441F8B).argument(0).affine == (0x28, 0x0C, "arg0")


def test_affine_shift_and_signed_immediate_add_are_preserved():
    """Address-style shifts and negative immediate adds remain affine."""
    text = bytes.fromhex(
        "8b 44 24 04"  # mov eax, [esp+4]
        "c1 e0 04"  # shl eax, 4
        "83 c0 fc"  # add eax, -4
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.affine == (-4, 16, "arg0")


def test_audited_list_count_helper_has_symbolic_summary():
    """The exact ObjObject walk remains symbolic rather than widening unknown."""
    text = bytes.fromhex(
        "8b 44 24 04"  # mov eax, [esp+4]
        "50"  # push eax
        "e8 16 00 00 00"  # call 0x4BC7B0
        "83 c4 04"  # add esp, 4
        "c3"
        "90 90 90 90 90 90 90 90 90 90 90 90"
        "90 90 90 90 90 90"
        "c3"
    )
    image = _minimal_pe(text, text_va=0x004BC790)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    returned = result.call_at(0x004BC795).return_value
    assert returned.kind == "affine"
    assert returned.affine == (
        0,
        1,
        "objobject-pcode-extra-operand-count[0x0+1*arg0]",
    )


def test_relevant_unknown_is_blocker():
    """An unsupported instruction on a proof-relevant slice blocks proof_ready."""
    text = bytes.fromhex(
        "e8 1b 00 00 00"  # call PCode constructor at 0x4A2660
        "89 18"  # mov [eax], ebx (unknown value to typed PCode)
        "c3"
        "90 90 90 90 90 90 90 90 90 90 90 90"
        "90 90 90 90 90 90 90 90 90 90 90 90"
        "c3"  # 0x4A2660
    )
    image = _minimal_pe(text, text_va=0x004A2640)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert not result.proof_ready
    assert result.unresolved[0].reason == "unknown-value-affects-pcode-store"
    write = result.writes_at(0x004A2645)[0]
    assert write.base.pointer_type == "pcode"


def test_origin_bound_call_result_is_symbolic_not_epistemically_unknown():
    """A concrete call site supplies provenance even when its value is dynamic."""
    text = bytes.fromhex(
        "e8 3b 00 00 00"  # call unmodelled helper at 0x4A2680
        "89 c3"  # mov ebx, eax
        "e8 14 00 00 00"  # call PCode constructor at 0x4A2660
        "89 58 16"  # mov [eax+0x16], ebx
        "c3"
        "90 90 90 90 90 90 90 90 90 90 90 90 90 90 90 90"
        "c3"  # constructor
        "90 90 90 90 90 90 90 90 90 90 90 90 90 90 90 90"
        "90 90 90 90 90 90 90 90 90 90 90 90 90 90 90"
        "c3"  # helper
    )
    image = _minimal_pe(text, text_va=0x004A2640)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    write = result.writes_at(0x004A264C)[0]
    assert write.value.kind == "symbolic"
    assert "call-return" in write.value.affine_symbol
    assert result.proof_ready


def test_bitwise_transform_of_dynamic_typed_read_retains_symbolic_origin():
    text = bytes.fromhex(
        "e8 1b 00 00 00"  # call PCode constructor at 0x4A2660
        "8b 58 16"  # mov ebx, [eax+0x16]
        "83 cb 40"  # or ebx, 0x40
        "89 58 16"  # mov [eax+0x16], ebx
        "c3"
        "90 90 90 90 90 90 90 90 90 90 90 90 90 90 90 90 90"
        "c3"
    )
    image = _minimal_pe(text, text_va=0x004A2640)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    write = result.writes_at(0x004A264B)[0]
    assert write.value.kind == "symbolic"
    assert "or(" in write.value.affine_symbol
    assert result.proof_ready


def test_unknown_allocation_size_is_blocker():
    """An unknown value may not silently enter an arena allocation fact."""
    text = bytes.fromhex(
        "50"  # push eax (unknown)
        "e8 1a 00 00 00"  # call arena allocator at 0x441FA0
        "c3"
        "90 90 90 90 90 90 90 90 90 90 90 90"
        "90 90 90 90 90 90 90 90 90 90 90 90 90"
        "c3"
    )
    image = _minimal_pe(text, text_va=0x00441F80)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert not result.proof_ready
    assert result.unresolved == (
        result.unresolved[0],
    )
    assert result.unresolved[0].reason == "unknown-value-affects-allocation-size"
    assert result.unresolved[0].address == 0x00441F81


def test_deterministic_summary_ordering():
    """Two identical analyses must produce identical result hashes."""
    text = bytes.fromhex("b8 2a 00 00 00 c3")
    image_a = _minimal_pe(text)
    image_b = _minimal_pe(text)
    _, cfg_a = _recover(image_a)
    _, cfg_b = _recover(image_b)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result_a = analyze_values(image_a, cfg_a, cfg_a.control_targets, (), _limits(image_a))
    result_b = analyze_values(image_b, cfg_b, cfg_b.control_targets, (), _limits(image_b))
    assert result_a == result_b


def test_loop_scc_converges_to_fixed_point():
    """A simple loop should reach a fixed point without divergence."""
    # Entry: mov ecx, 5; loop: dec ecx; jnz loop; ret
    text = bytes.fromhex(
        "b9 05 00 00 00"  # mov ecx, 5
        "49"  # dec ecx     <-- loop target
        "75 fd"  # jnz -3 (back to dec ecx)
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert result.proof_ready


def test_recursive_symbolic_return_summary_converges():
    """Recursive runtime expressions use a stable call-site identity."""
    text = bytes.fromhex(
        "e8 fb ff ff ff"  # call 0x401000 (self)
        "83 c8 01"  # or eax, 1
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    limits = replace(_limits(image), max_summary_iterations=4)
    result = analyze_values(image, cfg, cfg.control_targets, (), limits)
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.kind == "symbolic"
    assert "call-return" in summary.return_value.affine_symbol


def test_direct_immediate_push_recovers_argument_when_esp_join_is_unknown():
    """A local stack-depth merge must not hide a literal call argument."""
    text = bytes.fromhex(
        "85 c0"  # test eax, eax
        "74 04"  # je alternate
        "6a 7f"  # push 0x7f (make the incoming stack depths disagree)
        "eb 01"  # jmp join
        "90"  # alternate
        "6a 36"  # join: push 0x36
        "e8 10 00 00 00"  # call 0x441fa0
        "c3"
        + "90 " * 15
        + "c3"
    )
    image = _minimal_pe(text, text_va=0x00441F80)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert result.call_at(0x00441F8B).argument(0).exact_value == 0x36


def test_known_stack_output_helper_marks_pointed_local_symbolic():
    """Reviewed out-parameters materialize runtime values in stack locals."""
    text = bytes.fromhex(
        "83 ec 04"  # sub esp, 4
        "8d 04 24"  # lea eax, [esp]
        "50"  # push output pointer (arg2)
        "6a 00"  # push 0 (arg1)
        "6a 00"  # push 0 (arg0)
        "e8 20 00 00 00"  # call 0x4c7730
        "83 c4 0c"  # add esp, 12
        "8b 04 24"  # mov eax, [esp]
        "83 c4 04"  # add esp, 4
        "c3"
        + "90 " * 22
        + "c3"
    )
    image = _minimal_pe(text, text_va=0x004C7700)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.kind == "symbolic"
    assert "call-output" in summary.return_value.affine_symbol


def test_rep_stosb_records_typed_bulk_initialization():
    text = bytes.fromhex(
        "e8 1b 00 00 00"  # call PCode constructor at 0x4a2660
        "89 c7"  # mov edi, eax
        "31 c0"  # xor eax, eax
        "b9 28 00 00 00"  # mov ecx, 0x28
        "f3 aa"  # rep stosb
        "c3"
        + "90 " * 15
        + "c3"
    )
    image = _minimal_pe(text, text_va=0x004A2640)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    write = result.writes_at(0x004A264E)[0]
    assert write.base.pointer_type == "pcode"
    assert write.operation == "rep stosb count=finite{0x28}"
    assert result.proof_ready


def test_unmaterialized_stack_read_has_exact_symbolic_origin():
    text = bytes.fromhex(
        "83 ec 04"  # sub esp, 4
        "8b 04 24"  # mov eax, [esp]
        "83 c4 04"  # add esp, 4
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.kind == "symbolic"
    assert "stack-memory" in summary.return_value.affine_symbol


def test_dereference_of_dynamic_unknown_address_has_read_site_origin():
    text = bytes.fromhex(
        "8b 43 04"  # mov eax, [ebx+4]
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.kind == "symbolic"
    assert "unknown-address" in summary.return_value.affine_symbol


def test_movsd_records_typed_pcode_copy():
    text = bytes.fromhex(
        "e8 1b 00 00 00"  # call PCode constructor at 0x4a2660
        "89 c6"  # mov esi, eax
        "e8 14 00 00 00"  # call PCode constructor at 0x4a2660
        "89 c7"  # mov edi, eax
        "a5"  # movsd
        "c3"
        + "90 " * 16
        + "c3"
    )
    image = _minimal_pe(text, text_va=0x004A2640)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    write = result.writes_at(0x004A264E)[0]
    assert write.base.pointer_type == "pcode"
    assert write.value.kind == "affine"
    assert write.operation == "movsd count=finite{0x1}"
    assert result.proof_ready


@pytest.mark.parametrize("predicate", ("83 fb 00", "85 db"))
def test_cmp_and_test_do_not_reuse_stale_zero_provenance(predicate: str):
    """An unknown predicate must retain both paths after an earlier flag write."""
    text = bytes.fromhex(
        "31 c0"  # xor eax, eax (known zero flags)
        f"{predicate}"  # cmp ebx,0 / test ebx,ebx (unknown predicate)
        "75 06"  # jne alternate
        "b8 01 00 00 00"  # mov eax, 1
        "c3"
        "b8 02 00 00 00"  # alternate: mov eax, 2
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.values == frozenset({1, 2})


def test_cap_hit_raises_hard_error():
    """Reaching a configured cap must raise AnalysisLimitError."""
    text = bytes.fromhex("b8 2a 00 00 00 c3")
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values
    from tools.mwcc_retro.x86_cfg import AnalysisLimitError, AnalysisLimits

    tiny = AnalysisLimits(
        max_instructions=10,
        max_blocks=10,
        max_edges=80,
        max_scc_iterations=0,  # impossible
        max_summary_iterations=10,
    )
    with pytest.raises(AnalysisLimitError):
        analyze_values(image, cfg, cfg.control_targets, (), tiny)


def test_lossless_control_target_import():
    """Task 4 finite internal edges must be preserved in the result."""
    text = bytes.fromhex("b8 2a 00 00 00 c3")
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    blocker = UnresolvedControlTarget(
        address=0x00401005,
        kind="fixture-indirect-flow",
        detail="must survive Task 5",
    )
    control = replace(cfg.control_targets, unresolved=(blocker,))
    result = analyze_values(image, cfg, control, (), _limits(image))
    assert result.finite_internal_edges == control.finite_internal_edges
    assert result.terminal_external_edges == control.terminal_external_edges
    assert result.external_escapes == control.external_escapes
    assert result.unresolved == (
        result.unresolved[0],
    )
    assert result.unresolved[0].address == blocker.address
    assert result.unresolved[0].origin == blocker.detail
    assert not result.proof_ready


def test_typed_pointer_origin_is_preserved_across_mov():
    """A typed pointer's origin must survive register-to-register moves."""
    text = bytes.fromhex(
        "e8 1b 00 00 00"  # call PCode constructor at 0x4A2660
        "89 c3"  # mov ebx, eax
        "89 d8"  # mov eax, ebx
        "c3"
        "90 90 90 90 90 90 90 90 90 90 90 90"
        "90 90 90 90 90 90 90 90 90 90"
        "c3"
    )
    image = _minimal_pe(text, text_va=0x004A2640)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.pointer_type == "pcode"
    assert summary.return_value.allocation_site == 0x004A2640


def test_stack_argument_preserved_through_call():
    """A cdecl stack argument must be tracked through a call sequence."""
    text = bytes.fromhex(
        "6a 2a"  # push 42
        "e8 01 00 00 00"  # call callee at 0x401008
        "c3"
        # callee:
        "8b 44 24 04"  # mov eax, [esp+4]  ; arg
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    call = result.call_at(0x00401002)
    assert call.argument(0).exact_value == 42
    assert call.return_value.exact_value == 42
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.exact_value == 42


def test_global_read_produces_exact_value():
    """Reading from a statically-addressed global constant yields exact value."""
    text = bytes.fromhex(
        "a1 00 20 40 00"  # mov eax, [0x402000]
        "c3"
    )
    image = _minimal_pe(text)
    # The rdata section at offset text_size is zero-filled by _minimal_pe,
    # so [0x402000] = 0.  The test verifies the analysis completes.
    _, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.is_exact
    assert summary.return_value.exact_value == 0


def test_loop_call_facts_are_emitted_from_final_states_only():
    """Transient worklist states must not poison a final call-site join."""
    text = bytes.fromhex(
        "bb 03 00 00 00"  # mov ebx, 3
        "53"  # loop: push ebx
        "e8 15 00 00 00"  # call 0x441FA0
        "83 c4 04"  # add esp, 4
        "4b"  # dec ebx
        "75 f4"  # jne loop
        "c3"  # ret
        "90 90 90 90 90 90 90 90 90 90 90 90 90 90"
        "c3"  # allocator fixture
    )
    image = _minimal_pe(text, text_va=0x00441F80)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    paths = result.call_paths_at(0x00441F86)
    assert len(paths) == 1
    assert paths[0].argument(0).values == frozenset({1, 2, 3})


def test_task5_alias_write_certificate_exposes_unmodelled_store():
    """Every accepted memory destination remains an explicit obligation."""
    image = _minimal_pe(bytes.fromhex("87 03 c3"))  # xchg [ebx], eax; ret
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.alias_write_closure
    assert certificate is not None
    assert [(row.address, row.operand_index) for row in certificate.sites] == [
        (image.entrypoint, 0),
    ]
    assert certificate.sites[0].disposition == "unmodelled-store"
    assert certificate.sites[0].instruction_bytes_hex == "8703"
    assert certificate.gaps[0].kind == "unmodelled-memory-write"
    assert certificate.high_water_marks == (
        ("memory_write_facts", 0),
        ("memory_write_operands", 1),
        ("unresolved_write_operands", 1),
    )


def test_task5_alias_write_certificate_exposes_unknown_base_store():
    image = _minimal_pe(bytes.fromhex("89 03 c3"))  # mov [ebx], eax; ret
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.alias_write_closure
    assert certificate is not None
    assert certificate.sites[0].disposition == "possibly-aliasing-unknown-base"
    assert certificate.gaps[0].kind == "possibly-aliasing-memory-write"
    assert certificate.sites[0].facts[0].base.is_unknown


@pytest.mark.parametrize(
    ("instruction_hex", "mnemonic"),
    (
        ("ab", "stosd"),
        ("66ab", "stosw"),
        ("a4", "movsb"),
        ("66a5", "movsw"),
        ("0f9400", "sete"),
        ("f718", "neg"),
        ("f710", "not"),
        ("1118", "adc"),
        ("1918", "sbb"),
        ("dd1c24", "fstp"),
        ("df742404", "fbstp"),
        ("d93c24", "fnstcw"),
    ),
)
def test_task5_models_every_retail_memory_store_family(
    instruction_hex, mnemonic
):
    image = _minimal_pe(bytes.fromhex(instruction_hex + "c3"))
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.alias_write_closure
    assert certificate is not None
    site = next(row for row in certificate.sites if row.address == image.entrypoint)
    assert site.facts
    assert site.facts[0].operation.startswith(mnemonic)
    assert site.disposition != "unmodelled-store"


def test_task5_alias_write_certificate_proves_stack_store_disjoint():
    image = _minimal_pe(bytes.fromhex("89 04 24 c3"))  # mov [esp], eax; ret
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.alias_write_closure
    assert certificate is not None
    assert len(certificate.sites) == 1
    assert certificate.sites[0].disposition == "proved-stack-disjoint"
    assert certificate.sites[0].facts[0].base.pointer_type == "stack"
    assert not certificate.gaps


def test_task5_moves_static_storage_effect_to_lifecycle_certificate():
    image = _minimal_pe(bytes.fromhex("a3 00 20 40 00 c3"))
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    alias = result.alias_write_closure
    lifecycle = result.lifecycle_effect_closure
    assert alias is not None and lifecycle is not None
    assert alias.sites[0].disposition == "proved-image-storage-disjoint"
    assert not alias.gaps
    assert not lifecycle.gaps
    assert [row.kind for row in lifecycle.semantic_evidence] == [
        "static-storage-write"
    ]


def test_task5_lifecycle_certificate_covers_every_internal_helper_call():
    image = _minimal_pe(
        bytes.fromhex(
            "e8 01 00 00 00"  # call callee
            "c3"
            "c3"  # callee
        )
    )
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.lifecycle_effect_closure
    assert certificate is not None
    assert [(row.address, row.target) for row in certificate.sites] == [
        (image.entrypoint, image.entrypoint + 6),
    ]
    assert certificate.sites[0].disposition == "internal-summary-no-effects"
    assert certificate.sites[0].summary_entries == (image.entrypoint + 6,)
    assert not certificate.gaps


def test_task5_final_emission_certificate_retains_candidate_and_precise_gaps():
    image = _minimal_pe(
        bytes.fromhex(
            "e8 06 00 00 00"  # call callee
            "a3 00 20 40 00"  # mov [0x402000], eax
            "c3"
            "b8 78 56 34 12"  # callee: mov eax, 0x12345678
            "c3"
        )
    )
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.final_emission_closure
    assert certificate is not None
    assert len(certificate.return_write_flows) == 1
    flow = certificate.return_write_flows[0]
    assert flow.call_address == image.entrypoint
    assert flow.write_addresses == (image.entrypoint + 5,)
    assert {row.kind for row in certificate.gaps} == {
        "missing-typed-pcode-encoder-flow",
        "missing-pseudo-op-disposition-evidence",
        "missing-emitted-range-relocation-evidence",
        "missing-machine-field-derivation-evidence",
    }


def _out_parameter_fixture(*, include_unknown_caller: bool = False):
    """One helper writes through arg0; its caller passes an exact stack slot."""

    helper_offset = 0x30
    text = bytearray()
    text += bytes.fromhex("83ec04")  # sub esp, 4
    text += bytes.fromhex("8d0424")  # lea eax, [esp]
    text += bytes.fromhex("50")  # push eax
    call_offset = len(text)
    text += b"\xe8\0\0\0\0"
    text += bytes.fromhex("83c404")  # pop helper argument
    if include_unknown_caller:
        text += bytes.fromhex("53")  # push ebx (unconstrained)
        second_call_offset = len(text)
        text += b"\xe8\0\0\0\0"
        text += bytes.fromhex("83c404")
    text += bytes.fromhex("8b0424")  # mov eax, [esp]
    text += bytes.fromhex("83c404c3")
    text += b"\x90" * (helper_offset - len(text))
    text += bytes.fromhex("8b442404")  # helper: mov eax, [esp + 4]
    helper_write_offset = len(text)
    text += bytes.fromhex("c7002a000000")  # mov dword ptr [eax], 42
    text += b"\xc3"
    text[call_offset + 1 : call_offset + 5] = struct.pack(
        "<i", helper_offset - (call_offset + 5)
    )
    if include_unknown_caller:
        text[second_call_offset + 1 : second_call_offset + 5] = struct.pack(
            "<i", helper_offset - (second_call_offset + 5)
        )
    return bytes(text), helper_write_offset


def test_internal_helper_output_effect_is_applied_transitively_to_caller_stack():
    from tools.mwcc_retro.backend_abstract_values import analyze_values

    payload, _helper_write = _out_parameter_fixture()
    image, cfg = _recover(_minimal_pe(payload))
    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))

    summary = result.summary_at(image.entrypoint)
    assert summary is not None
    assert summary.return_value.exact_value == 42


def test_formal_store_is_disjoint_when_every_incoming_path_is_exact_stack():
    from tools.mwcc_retro.backend_abstract_values import analyze_values

    payload, helper_write = _out_parameter_fixture()
    image, cfg = _recover(_minimal_pe(payload))
    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.alias_write_closure
    assert certificate is not None

    site = next(
        row
        for row in certificate.sites
        if row.address == image.entrypoint + helper_write
    )
    assert site.disposition == "proved-stack-disjoint"
    assert not certificate.gaps


def test_formal_store_still_blocks_when_one_incoming_path_is_unknown():
    from tools.mwcc_retro.backend_abstract_values import analyze_values

    payload, helper_write = _out_parameter_fixture(include_unknown_caller=True)
    image, cfg = _recover(_minimal_pe(payload))
    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.alias_write_closure
    assert certificate is not None

    site = next(
        row
        for row in certificate.sites
        if row.address == image.entrypoint + helper_write
    )
    assert site.disposition == "possibly-aliasing-unknown-base"
    assert any(
        row.address == site.address and row.kind == "possibly-aliasing-memory-write"
        for row in certificate.gaps
    )


def test_unknown_stack_bookkeeping_is_not_itself_a_relevant_value_blocker():
    from tools.mwcc_retro.backend_abstract_values import analyze_values

    # mov esp, eax destroys the local stack coordinate.  The following push is
    # irrelevant because no proof-relevant call/store consumes it.
    image, cfg = _recover(_minimal_pe(bytes.fromhex("89c450c3")))
    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))

    assert not any(row.reason == "push-with-unknown-esp" for row in result.unresolved)
    assert result.proof_ready


def test_final_emission_derives_range_relocation_and_machine_dependencies():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        CallFact,
        MemoryWriteFact,
        PseudoOpDispositionEvidence,
        ValueDependency,
        derive_final_emission_closure,
    )

    pcode = AbstractValue(
        kind="pointer", pointer_type="pcode", pointer_base=0x9000
    )
    machine_dependency = ValueDependency(
        kind="memory-read",
        address=0x220,
        width=2,
        pointer_type="pcode",
        pointer_offset=0x1E,
        origin="typed operand payload read",
    )
    encoded = AbstractValue(
        kind="symbolic",
        affine_symbol="encoded-word",
        origin="encoder-return",
        dependencies=(machine_dependency,),
    )
    relocation_value = AbstractValue(
        kind="symbolic",
        affine_symbol="relocation-symbol",
        origin="encoder-out-parameter",
        dependencies=(
            ValueDependency(
                kind="helper-output",
                address=0x100,
                source_address=0x228,
                width=4,
                pointer_type="stack",
                pointer_offset=-8,
                origin="encoder relocation output",
            ),
            ValueDependency(
                kind="helper-output",
                address=0x100,
                source_address=0x22C,
                width=4,
                pointer_type="stack",
                pointer_offset=-4,
                origin="encoder relocation symbol output",
            ),
        ),
    )
    calls = (
        CallFact(0x100, 0x200, 0x80, (pcode,), encoded),
        CallFact(
            0x120,
            0x300,
            0x80,
            (relocation_value, relocation_value, relocation_value),
            AbstractValue(),
        ),
    )
    writes = (
        MemoryWriteFact(
            0x110,
            0x80,
            4,
            AbstractValue(
                kind="symbolic",
                affine_symbol="code-buffer+offset",
                origin="bounded output cursor",
            ),
            0,
            encoded,
            "mov",
        ),
    )

    certificate = derive_final_emission_closure(
        compiler_sha256="a" * 64,
        cfg_instruction_hash="b" * 64,
        calls=calls,
        memory_writes=writes,
        limits=AnalysisLimits(max_instructions=10, max_blocks=10, max_edges=10),
        pseudo_op_dispositions=(
            PseudoOpDispositionEvidence(
                opcode_ids=(466, 467),
                classification="removed-before-final-walker",
                walker_address=0x80,
                disposition_sites=(0x90,),
                provenance=("exhaustive synthetic list transition",),
            ),
        ),
    )

    assert {row.kind for row in certificate.semantic_evidence} == {
        "encode-one-final-pcode",
        "encoder-result-buffer-write",
        "emitted-code-range",
        "final-pcode-walker",
        "operand-to-machine-field-derivation",
        "per-pcode-encoder-call",
        "pseudo-op-disposition",
        "relocation-record-consumer",
    }
    assert not certificate.gaps


def test_multiple_typed_encoder_targets_block_singular_emission_claim():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        CallFact,
        MemoryWriteFact,
        ValueDependency,
        derive_final_emission_closure,
    )

    pcode = AbstractValue(kind="pointer", pointer_type="pcode")
    dependency = ValueDependency(
        kind="memory-read",
        address=0x220,
        width=2,
        pointer_type="pcode",
        pointer_offset=0x14,
    )
    first = AbstractValue(kind="symbolic", affine_symbol="one", dependencies=(dependency,))
    second = AbstractValue(kind="symbolic", affine_symbol="two", dependencies=(dependency,))
    calls = (
        CallFact(0x100, 0x200, 0x80, (pcode,), first),
        CallFact(0x140, 0x240, 0x80, (pcode,), second),
    )
    writes = tuple(
        MemoryWriteFact(
            address,
            0x80,
            4,
            AbstractValue(kind="symbolic", affine_symbol=f"buffer-{address:x}"),
            0,
            value,
            "mov",
        )
        for address, value in ((0x110, first), (0x150, second))
    )

    certificate = derive_final_emission_closure(
        compiler_sha256="a" * 64,
        cfg_instruction_hash="b" * 64,
        calls=calls,
        memory_writes=writes,
        limits=AnalysisLimits(max_instructions=10, max_blocks=10, max_edges=10),
    )

    assert any(
        row.kind == "multiple-typed-pcode-encoder-targets"
        for row in certificate.gaps
    )


def test_conditional_helper_store_is_not_applied_as_a_must_effect():
    from tools.mwcc_retro.backend_abstract_values import analyze_values

    helper_offset = 0x30
    text = bytearray()
    text += bytes.fromhex("83ec04")  # reserve output slot
    text += bytes.fromhex("8d0424")  # eax = &slot
    text += bytes.fromhex("6a00")  # arg1 selects the no-write path
    text += bytes.fromhex("50")  # arg0 = &slot
    call_offset = len(text)
    text += b"\xe8\0\0\0\0"
    text += bytes.fromhex("83c408")
    text += bytes.fromhex("8b0424")
    text += bytes.fromhex("83c404c3")
    text += b"\x90" * (helper_offset - len(text))
    text += bytes.fromhex("8b442404")  # eax = arg0
    text += bytes.fromhex("837c240800")  # cmp arg1, 0
    text += bytes.fromhex("7406")  # skip the store on one path
    helper_write = len(text)
    text += bytes.fromhex("c7002a000000")
    text += b"\xc3"
    text[call_offset + 1 : call_offset + 5] = struct.pack(
        "<i", helper_offset - (call_offset + 5)
    )

    image, cfg = _recover(_minimal_pe(bytes(text)))
    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    helper = result.summary_at(image.entrypoint + helper_offset)
    caller = result.summary_at(image.entrypoint)

    assert helper is not None and caller is not None
    assert image.entrypoint + helper_write not in helper.must_write_sites
    assert caller.return_value.exact_value is None


def test_helper_effect_certificate_records_transitive_storage_site():
    from tools.mwcc_retro.backend_abstract_values import analyze_values

    payload, helper_write = _out_parameter_fixture()
    image, cfg = _recover(_minimal_pe(payload))
    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    certificate = result.lifecycle_effect_closure
    assert certificate is not None

    helper_site = next(
        row for row in certificate.sites if row.address == image.entrypoint + 7
    )
    assert helper_site.disposition == "internal-summary-effects"
    assert image.entrypoint + helper_write in helper_site.typed_write_sites
    assert any(
        row.kind == "helper-transitive-effects"
        and row.address == image.entrypoint + 7
        for row in certificate.semantic_evidence
    )


def test_value_dependency_shape_and_canonical_order_fail_closed():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        PseudoOpDispositionEvidence,
        ValueDependency,
    )

    with pytest.raises(ValueError, match="unknown value dependency kind"):
        ValueDependency(kind="wildcard", address=1, width=1)
    with pytest.raises(ValueError, match="requires a source address"):
        ValueDependency(kind="helper-output", address=1, width=1)
    first = ValueDependency(kind="memory-read", address=1, width=1)
    second = ValueDependency(kind="memory-read", address=2, width=1)
    with pytest.raises(TypeError, match="dependencies must be tuple"):
        AbstractValue(dependencies=[first])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="canonically ordered"):
        AbstractValue(dependencies=(second, first))
    with pytest.raises(ValueError, match="must be unique"):
        AbstractValue(dependencies=(first, first))
    with pytest.raises(ValueError, match="exactly IDs 466 and 467"):
        PseudoOpDispositionEvidence(
            opcode_ids=(466,),
            classification="removed-before-final-walker",
            walker_address=1,
            disposition_sites=(2,),
            provenance=("fixture",),
        )
