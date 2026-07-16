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
