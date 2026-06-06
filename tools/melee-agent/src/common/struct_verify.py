# src/common/struct_verify.py
"""Aggregation and confidence logic for struct offset discrepancy findings.

Pure module — no I/O. Takes per-function findings (field, current offset,
expected offset) and aggregates them by field, computing confidence and
flagging conflicts.
"""
from __future__ import annotations

from collections import defaultdict


def aggregate(findings: list[dict]) -> list[dict]:
    """Aggregate per-function offset discrepancy findings by field.

    Each finding is a dict with keys:
        function (str): the function where the discrepancy was observed
        field (str): field path (e.g. "RST", "components[0].predDC")
        current (int): the current (wrong) displacement in our build
        expected (int): the expected (target) displacement
        ref_field (str | None, optional): field that the EXPECTED offset maps to
            in the layout, if known. When this differs from ``field`` the
            discrepancy may be a deliberate different-field access rather than a
            simple offset shift (see design §6); such aggregates are flagged
            ``ambiguous``.

    Returns a list of aggregated dicts sorted by current offset:
        field (str)
        current (int): the observed offset in our build
        expected (int | None): agreed expected offset (None if conflict)
        expecteds (list[int]): all distinct expected values seen
        n_functions (int): number of distinct functions that observed this
        functions (list[str]): sorted list of those function names
        conflict (bool): True when multiple distinct expected values
        confidence (str): "high" when >=2 functions agree and no conflict, else "low"
        ambiguous (bool): True when any contributing finding's ``ref_field`` is a
            known field that differs from ``field`` (default False)
    """
    by_field: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_field[f["field"]].append(f)

    out = []
    for field, items in by_field.items():
        expecteds = sorted({it["expected"] for it in items})
        current = items[0]["current"]
        conflict = len(expecteds) > 1
        n = len({it["function"] for it in items})
        confidence = "high" if (n >= 2 and not conflict) else "low"
        # Ambiguous when the expected offset maps to a DIFFERENT known field:
        # could be a deliberate different-field access, not an offset shift.
        ambiguous = any(
            it.get("ref_field") is not None and it["ref_field"] != field
            for it in items
        )
        out.append({
            "field": field,
            "current": current,
            "expected": expecteds[0] if not conflict else None,
            "expecteds": expecteds,
            "n_functions": n,
            "functions": sorted({it["function"] for it in items}),
            "conflict": conflict,
            "confidence": confidence,
            "ambiguous": ambiguous,
        })

    return sorted(out, key=lambda a: a["current"])
