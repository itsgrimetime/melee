"""Tests for the coalesce-suggestion IR facts layer."""

from __future__ import annotations

from src.mwcc_debug.coalesce_ir_facts import IrFacts, VirtualFacts


def test_virtual_facts_dataclass_shape() -> None:
    """VirtualFacts captures the fields the pattern checkers need."""
    vf = VirtualFacts(
        virtual=53,
        first_def=None,
        use_sites=[],
        use_sites_truncated=False,
        is_param=False,
        is_phys=False,
    )
    assert vf.virtual == 53
    assert vf.use_sites == []
    assert vf.use_sites_truncated is False


def test_ir_facts_dataclass_shape() -> None:
    """IrFacts has the expected top-level fields including cg_section."""
    facts = IrFacts(
        function_name="test_fn",
        pre_pass=None,  # type: ignore[arg-type]
        by_virtual={},
        bindings=[],
        basis=None,
        cg_section=None,
    )
    assert facts.function_name == "test_fn"
    assert facts.by_virtual == {}
    assert facts.cg_section is None
