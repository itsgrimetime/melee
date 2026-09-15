# tools/melee-agent/src/backtest/levers.py
from __future__ import annotations

import re

from .types import LEVER_CLASSES

_TYPE_TOKENS = r"(?:u8|s8|u16|s16|u32|s32|int|unsigned|char|short|long|float|double|bool)"
# (added_line, removed_line) pair predicates, evaluated against the union of changed lines.
_RETYPE = re.compile(rf"^[+-]\s*{_TYPE_TOKENS}\b")
_FLOAT_LIT = re.compile(r"[-+]?\d+\.\d+f?\b")
_DECL_INIT = re.compile(r"^\+\s*\w[\w ]*\b\w+\s*=")


def classify_lever(diff: str) -> str:
    added = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    changed = added + removed

    # retype: same identifier reappears with a different leading type token
    if any(_RETYPE.match(l) for l in added) and any(_RETYPE.match(l) for l in removed):
        return "retype"
    # literal_vs_named: a named identifier arg replaced by a numeric/float literal (or vice versa)
    if any(_FLOAT_LIT.search(l) for l in added) != any(_FLOAT_LIT.search(l) for l in removed):
        return "literal_vs_named"
    # hoist_to_local / embedded_assign_temp: a new local decl-with-initializer appears
    if any(_DECL_INIT.match(l) for l in added) and not removed:
        return "hoist_to_local"
    if "for (" in " ".join(added) and "for (" in " ".join(removed):
        # counter rename / count-down heuristic
        if any("--" in l for l in added) or any("--" in l for l in removed):
            return "count_down_or_compare_reuse"
    if any("inline" in l for l in changed):
        return "inline_arg_or_schedule"
    if any(re.search(r"->\s*\w+|\.\w+\s*=", l) for l in added) and any("struct" in l for l in changed):
        return "struct_overlay"
    result = "other"
    assert result in LEVER_CLASSES
    return result
