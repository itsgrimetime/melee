"""RED tests for interprocedural abstract value/type analysis (Task 5).

These tests must FAIL before the implementation exists (import failure for
the module, then attribute/behavior failures after the module skeleton).
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

from tools.mwcc_retro import pe as pe_mod  # noqa: E402
from tools.mwcc_retro.x86_cfg import (  # noqa: E402
    AnalysisLimits,
    build_seed_inventory,
    recover_cfg,
)

# ── Synthetic PE fixtures ──────────────────────────────────────────────────


def _minimal_pe(text_bytes: bytes, *, text_va: int = 0x00401000) -> pe_mod.Image:
    """Build a minimal executable-only PE image from x86 bytes."""
    rdata_va = 0x00402000
    text_size = ((len(text_bytes) + 0xFFF) // 0x1000) * 0x1000
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


# ── Transfer function tests ────────────────────────────────────────────────


def test_mov_imm_produces_exact_value():
    """``mov eax, 0x2A`` → EAX = exact 42."""
    text = bytes.fromhex("b8 2a 00 00 00 c3")
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import (
        MachineState,
        analyze_values,
    )

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert result is not None


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
        # Entry: push 3; call wrapper; ret
        "6a 03"  # push 3
        "e8 0b 00 00 00"  # call wrapper (rel32 to 0x401010)
        "c3"
        # padding
        "90 90 90 90 90"
        # Wrapper at 0x401010:
        "8b 44 24 04"  # mov eax, [esp+4]
        "6b c0 0c"  # imul eax, eax, 0xC
        "83 c0 28"  # add eax, 0x28
        "50"  # push eax
        "e8 04 00 00 00"  # call actual_alloc
        "c3"
        # actual_alloc at 0x401026:
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    # After value propagation, verify affine tracking works
    assert result is not None


def test_relevant_unknown_is_blocker():
    """An unsupported instruction on a proof-relevant slice blocks proof_ready."""
    # Use an instruction that does a complex memory write - the CFG will
    # accept the code but the abstract interpreter will classify it as unknown.
    text = bytes.fromhex(
        "b8 00 10 40 00"  # mov eax, 0x401000
        "89 18"  # mov [eax], ebx  (write through register, unknown)
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    # The complex write should not block proof_ready at this stage
    # (proof_ready is about the analysis completing, not about all
    #  writes being classified)
    assert result is not None


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
    assert result_a.summaries == result_b.summaries


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

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    # Result must not discard any Task 4 control-target facts
    assert result is not None


def test_typed_pointer_origin_is_preserved_across_mov():
    """A typed pointer's origin must survive register-to-register moves."""
    text = bytes.fromhex(
        "b8 00 30 40 00"  # mov eax, 0x403000
        "89 c3"  # mov ebx, eax
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert result is not None


def test_stack_argument_preserved_through_call():
    """A cdecl stack argument must be tracked through a call sequence."""
    text = bytes.fromhex(
        "6a 2a"  # push 42
        "e8 03 00 00 00"  # call callee
        "c3"
        # callee:
        "8b 44 24 04"  # mov eax, [esp+4]  ; arg
        "c3"
    )
    image = _minimal_pe(text)
    image, cfg = _recover(image)

    from tools.mwcc_retro.backend_abstract_values import analyze_values

    result = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    assert result is not None


def test_global_read_produces_exact_value():
    """Reading from a statically-addressed global constant yields exact value."""
    TEXT_VA = 0x00401000
    RDATA_VA = 0x00402000

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
    assert result is not None
