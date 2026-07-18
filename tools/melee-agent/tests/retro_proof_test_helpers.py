"""Shared strict-schema helpers for synthetic retail lifetime proofs."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence


def bind_fixed_layout_schema(
    opcode_rows: Sequence[MutableMapping[str, object]],
    operand_rules: Sequence[MutableMapping[str, object]],
) -> None:
    """Bind required v1 fields for synthetic fixed/custom opcode layouts.

    These fixtures deliberately exercise non-variadic layouts.  A caller that
    needs a variadic row must spell out its exact count/tail evidence instead
    of receiving permissive defaults here.
    """

    for row in opcode_rows:
        if row.get("constructor_kind") == "generic-variadic":
            raise ValueError("variadic synthetic rows need explicit exact evidence")
        row["variadic_layout"] = None
    for row in operand_rules:
        row["descriptor_source"] = "format"
        row["role_rules"] = []
