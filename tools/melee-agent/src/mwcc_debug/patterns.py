"""Catalog of recurring MWCC source-mutation patterns.

Curated from the matching agent's `mwcc-debug-permuter-session-findings`
doc — these are the small family of source mutations that permuter
keeps rediscovering across stuck functions. Surface as named entries
so `debug guide` can suggest them by name and `debug pattern-catalog`
can dump them for reference.

Each pattern is rules-of-thumb, not a guarantee. Use them as
mutation hypotheses to try, not as authoritative fixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MutationPattern:
    """One named mutation pattern with motivating example + when-to-try."""

    name: str  # kebab-case identifier
    title: str  # human-readable title
    summary: str  # one-paragraph description
    when_to_try: str  # heuristic — when to consider this pattern
    example_before: str  # C source snippet before mutation
    example_after: str  # C source snippet after mutation
    mechanism: str  # one-paragraph "why does this work in MWCC terms?"
    # Categories the pattern addresses — used to surface from guide.py
    # by matching against suggestion categories (see guidance.py:Suggestion).
    addresses: tuple[str, ...] = ()


PATTERNS: dict[str, MutationPattern] = {
    "alias-split": MutationPattern(
        name="alias-split",
        title="Alias-into-fresh-local to split a live range",
        summary=(
            "Create a fresh local variable assigned from an existing "
            "variable shortly before the existing variable's last use. "
            "MWCC materializes the alias as a new virtual register with a "
            "shorter live range, leaving the original to continue its "
            "natural lifetime for its other uses."
        ),
        when_to_try=(
            "When a long-lived callee-save virtual is blocking other "
            "virtuals from getting their target physical. Especially "
            "useful if the variable is used in many places but only ONE "
            "of those uses needs to coincide with another virtual's life."
        ),
        example_before=(
            "mnVibration_802480B4((HSD_JObj*) var_r26, var_r24, 1);"
        ),
        example_after=(
            "new_var = var_r24;\n"
            "// ... some intervening code ...\n"
            "mnVibration_802480B4((HSD_JObj*) var_r26, new_var, 1);"
        ),
        mechanism=(
            "The assignment `new_var = var_r24` forces MWCC to copy the "
            "value into a fresh virtual at that point. The new virtual "
            "lives from the assignment to the call (a few instructions), "
            "while the original keeps its full lifetime. The IG sees one "
            "fewer long-lived callee-save virtual at the contested "
            "junction, so the allocator packs the rest tighter."
        ),
        addresses=("interference", "rank"),
    ),
    "widen-u8-to-u32": MutationPattern(
        name="widen-u8-to-u32",
        title="Widen u8 → u32 to eliminate implicit promotion masks",
        summary=(
            "Change a u8 variable to u32 when it's used in many u8 "
            "expressions. MWCC inserts a clrlwi (or rlwinm) at every u8 "
            "use to mask to 8 bits; widening to u32 removes those masks "
            "and the virtuals they hold."
        ),
        when_to_try=(
            "When a function has clrlwi/rlwinm masks at unexpected "
            "places in the expected ASM, and a u8 variable is implicated "
            "in those uses. Easy to detect by grepping the post-coloring "
            "ASM for `rlwinm rN,rN,0,24,31`."
        ),
        example_before=(
            "u8 var_r23;\n"
            "var_r23 = foo();\n"
            "bar(var_r23 + 1);"
        ),
        example_after=(
            "u32 var_r23;\n"
            "var_r23 = foo();\n"
            "bar(var_r23 + 1);"
        ),
        mechanism=(
            "C requires integer promotions on arithmetic operands. "
            "MWCC emits a mask at each u8 use to honor that. The masked "
            "result lives in a virtual; widening to u32 elides the mask, "
            "freeing the virtual and often dropping a callee-save "
            "requirement."
        ),
        addresses=("spill", "interference"),
    ),
    "shrink-s32-to-u8": MutationPattern(
        name="shrink-s32-to-u8",
        title="Shrink s32 → u8 for value-bounded variables",
        summary=(
            "Mirror of `widen-u8-to-u32`. When a variable's actual value "
            "range is 0..0xFF but it's declared s32, MWCC may keep it in "
            "a callee-save with full 32-bit arithmetic. Switching to u8 "
            "collapses unnecessary 32-bit work."
        ),
        when_to_try=(
            "When the expected ASM has clrlwi/extsb instructions you "
            "can't produce, and an s32 variable in source is actually "
            "value-bounded to a byte range. Look for variables that get "
            "the result of `lbz` / are passed to byte-taking helpers."
        ),
        example_before=(
            "s32 name_idx;\n"
            "name_idx = some_lookup();  // returns 0..0xFF"
        ),
        example_after=(
            "u8 name_idx;\n"
            "name_idx = some_lookup();"
        ),
        mechanism=(
            "MWCC tracks variable types and chooses load/store widths "
            "accordingly. A u8 variable forces byte-width memory access "
            "and proper sign/zero-extension at use, matching the expected "
            "ASM's lbz / extsb pattern."
        ),
        addresses=("interference", "spill"),
    ),
    "drop-variadic-cast": MutationPattern(
        name="drop-variadic-cast",
        title="Drop explicit (f32) cast on variadic argument",
        summary=(
            "Remove an explicit `(f32)` cast on an argument to a variadic "
            "function when the expected ASM doesn't show an int-to-float "
            "conversion. The cast forces the conversion (and a magic "
            "constant load); without it, the value passes as-is."
        ),
        when_to_try=(
            "When a variadic call's expected ASM is missing an int-to-"
            "float `fcfid` / magic-constant load that the source's cast "
            "would emit. Also look for an unwanted anonymous `@N` sdata2 "
            "relocation that disappears when the cast is removed."
        ),
        example_before=(
            "lb_80011E24(jobj, &panel_jobj, 2, -1, (f32) rumble_setting);"
        ),
        example_after=(
            "lb_80011E24(jobj, &panel_jobj, 2, -1, rumble_setting);"
        ),
        mechanism=(
            "Variadic args promote according to default argument "
            "promotion rules: integer types stay integer (after int "
            "promotion), float types become double. An explicit `(f32)` "
            "cast triggers int→float→double conversion, emitting a magic "
            "0x4330000080000000 constant load. Removing the cast keeps "
            "the value as an integer that the callee can interpret."
        ),
        addresses=("interference",),  # eliminating cast frees a virtual
    ),
    "subexpr-extract": MutationPattern(
        name="subexpr-extract",
        title="Extract a subexpression into a named local",
        summary=(
            "Pull a complex sub-computation out into a named local "
            "variable. MWCC's FP scheduler can then treat it as a single "
            "computed value, versus computing it inline and possibly "
            "re-computing or scheduling it differently."
        ),
        when_to_try=(
            "When a function has a complex expression (especially with "
            "multiple function calls or floating-point operations) and "
            "the expected ASM shows a different scheduling pattern than "
            "what the inline form produces."
        ),
        example_before=(
            "HSD_JObjSetTranslateY(cursor_jobj,\n"
            "  (HSD_JObjGetTranslationY(data->jobjs[18])\n"
            "   - HSD_JObjGetTranslationY(data->jobjs[17])) *\n"
            "  (f32) data->x0[1] +\n"
            "  HSD_JObjGetTranslationY(data->jobjs[17]));"
        ),
        example_after=(
            "dy = HSD_JObjGetTranslationY(data->jobjs[18])\n"
            "   - HSD_JObjGetTranslationY(data->jobjs[17]);\n"
            "HSD_JObjSetTranslateY(cursor_jobj,\n"
            "  dy * (f32) data->x0[1] +\n"
            "  HSD_JObjGetTranslationY(data->jobjs[17]));"
        ),
        mechanism=(
            "Naming the intermediate as a local commits MWCC to computing "
            "it once and keeping it in a single virtual register. Inline "
            "expressions are subject to common-subexpression elimination "
            "and scheduling that may diverge from the expected ASM."
        ),
        addresses=("rank",),
    ),
    "decl-order": MutationPattern(
        name="decl-order",
        title="Reorder local variable declarations",
        summary=(
            "Move a local variable's declaration to a different position "
            "in the function's declaration list. Despite looking purely "
            "cosmetic, this changes MWCC's virtual-number assignment, "
            "which changes IGNode array indexing, simplification order, "
            "and ultimately coloring choices."
        ),
        when_to_try=(
            "When a virtual has the right life range and no direct "
            "interference blocker for its target physical, but the "
            "allocator still picks a wrong physical. This usually means "
            "the simplification iteration order put it at a lower-priority "
            "slot. Run `debug enumerate-decl-orders <fn>` to brute-force "
            "the small search space."
        ),
        example_before=(
            "void mnVibration_80248644(HSD_GObj* arg0)\n"
            "{\n"
            "    MnVibrationData* ptr2;\n"
            "    MnVibrationData* data;\n"
            "    s32 i;\n"
            "    HSD_JObj* jobj17;\n"
            "    HSD_JObj* child;\n"
            "    s32 j;\n"
            "    s32 name_idx;"
        ),
        example_after=(
            "void mnVibration_80248644(HSD_GObj* arg0)\n"
            "{\n"
            "    s32 j;          // moved to first\n"
            "    MnVibrationData* ptr2;\n"
            "    MnVibrationData* data;\n"
            "    s32 i;\n"
            "    HSD_JObj* jobj17;\n"
            "    HSD_JObj* child;\n"
            "    s32 name_idx;"
        ),
        mechanism=(
            "MWCC assigns virtual register numbers in declaration order: "
            "parse → symbol table → ENode allocation → IGNode allocation. "
            "The IG is indexed by virtual number, and `simplifygraph` "
            "iterates the IG array; reordering changes which nodes get "
            "popped first onto the simplification stack, which changes "
            "the coloring order. A 5-step chain — easy to miss from "
            "live-range analysis alone."
        ),
        addresses=("rank",),
    ),
    "param-iter-ceiling": MutationPattern(
        name="param-iter-ceiling",
        title="Parameter loses to local in IG iteration order (CEILING)",
        summary=(
            "MWCC simplifygraph iterates the IG by DESCENDING ig_idx. "
            "Parameters get LOW ig_idx (32, 33, 34 — first allocated by "
            "the symbol table), while locals declared in the function "
            "body get HIGHER ig_idx (35+). So locals are colored FIRST "
            "and grab the top callee-saves (r31, r30, r29) via top-down "
            "dispense. By the time a parameter is colored, it's stuck "
            "with whatever's left. This is a STRUCTURAL CEILING — there "
            "is no known C-source pattern that pushes a parameter's "
            "ig_idx above a local's without changing the emitted .text."
        ),
        when_to_try=(
            "DON'T try to fix it from C source. Recognize the signature "
            "and escalate to Tier 6 (force-phys for hypothesis testing; "
            "potentially a coalescenodes hook for production matching). "
            "Signature: (a) parameter virtual (ig_idx 32-34) is at the "
            "wrong physical, (b) the desired physical is held by a local "
            "virtual with higher ig_idx, (c) no direct interference "
            "between them, (d) force-phys with the desired mapping "
            "produces the target .text, (e) enumerate-decl-orders finds "
            "no win because locals' relative order doesn't change "
            "parameters' ig_idx."
        ),
        example_before=(
            "// Parameter gobj is virtual r32 (ig_idx 32)\n"
            "// Local jobj is virtual r33 (ig_idx 33)\n"
            "// Local i is virtual r34 (ig_idx 34)\n"
            "// Coloring order (descending ig_idx): i → jobj → gobj\n"
            "// Top-down dispense: i=r31, jobj=r30, gobj=r29\n"
            "// But target wants gobj=r31 — UNREACHABLE from C source\n"
            "void fn(HSD_GObj* gobj) {\n"
            "    HSD_JObj* jobj;\n"
            "    s32 i;\n"
            "    // ...\n"
            "}"
        ),
        example_after=(
            "// No source-level fix exists.\n"
            "// Things tried that DON'T work:\n"
            "//   - Aliases: `HSD_GObj* g = gobj;` coalesces away\n"
            "//   - volatile locals: changes emitted code\n"
            "//   - Address-of-parameter: forces stack frame growth\n"
            "//   - Decl-reorder: doesn't change parameter ig_idx\n"
            "// Confirm the target IS reachable via:\n"
            "//   melee-agent debug pcdump src/... --force-phys '32:31,...'\n"
            "// If force-phys matches: document as Tier 6 case, move on."
        ),
        mechanism=(
            "The IG node array is indexed by virtual number. Parameters "
            "are assigned virtuals before any local declaration is "
            "processed (they're added during function-signature parsing), "
            "so they occupy the LOWEST virtual indices. simplifygraph "
            "iterates this array from high index to low when building "
            "the simplification stack, so high-index nodes are pushed "
            "LAST and popped FIRST. The first virtuals popped get first "
            "claim on the workingMask, and when workingMask is exhausted "
            "(all caller-saves taken by interferers), they trigger "
            "obtain_nonvolatile_register which dispenses r31, then r30, "
            "etc. By the time the parameter's virtual is popped, the "
            "high callee-saves are already taken by earlier dispenses. "
            "No C-source reorder fixes this because parameter ig_idx is "
            "fixed by C semantics (parameter list comes before locals)."
        ),
        addresses=("rank", "param-iter-ceiling"),
    ),
    "chained-init": MutationPattern(
        name="chained-init",
        title="Chained init: `var_a = (var_b = 0);`",
        summary=(
            "Combine two zero-initializations into one chained "
            "assignment expression. MWCC can recognize the second `0` "
            "doesn't need its own virtual register."
        ),
        when_to_try=(
            "When two adjacent locals both get initialized to the same "
            "value (most often 0) and the expected ASM has only one "
            "`li rN, 0` for both. Easy to identify by counting the `li 0` "
            "instructions in expected vs actual."
        ),
        example_before=(
            "var_a = 0;\n"
            "var_b = 0;"
        ),
        example_after=(
            "var_a = (var_b = 0);"
        ),
        mechanism=(
            "The chained-assignment expression evaluates `var_b = 0` to "
            "the value `0`, then assigns that result to `var_a`. MWCC "
            "stores the literal `0` once and reads from the var_b "
            "virtual instead of materializing a new constant load. Saves "
            "one virtual."
        ),
        addresses=("interference", "spill"),
    ),
}


def get_pattern(name: str) -> Optional[MutationPattern]:
    """Look up a pattern by name. Returns None if not found."""
    return PATTERNS.get(name)


def patterns_for_category(category: str) -> list[MutationPattern]:
    """Return all patterns that address the given suggestion category.

    `category` should be one of the values from guidance.py:Suggestion
    (e.g. "interference", "spill", "rank"). Patterns can address
    multiple categories.
    """
    return [p for p in PATTERNS.values() if category in p.addresses]


def list_patterns() -> list[MutationPattern]:
    """Return all patterns in catalog order (insertion order matches
    the original findings doc's pattern numbering)."""
    return list(PATTERNS.values())
