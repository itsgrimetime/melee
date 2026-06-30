"""
Add inline-trick mismatch patterns to the local mismatch-db.

These patterns are derived from analyzing upstream/master commits where
`static inline` was the key technique for producing 100% matches.

Run: python tools/add_inline_patterns.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "melee-agent" / "src"))

from mismatch_db.models import (
    Example,
    Fix,
    Pattern,
    PatternDB,
    Provenance,
    ProvenanceEntry,
    Signal,
)
from mismatch_db.schema import init_db, DEFAULT_DB_PATH


PATTERNS = [
    Pattern(
        id="static-inline-dontinline-wrapper",
        name="`*_dontinline` / `*_no_inline` static inline shim",
        description=(
            "MWCC's `-inline auto` would otherwise auto-inline a same-TU "
            "function at the call site, producing wrong stack frame, register "
            "allocation, and inlined codegen. Wrapping the call through a "
            "`static inline X_dontinline(args) { X(args); }` thunk makes MWCC "
            "inline only the thunk (one level) and emit a real `bl` to the "
            "outer function. Variants include `_dontinline`, `_no_inline`, and "
            "`_inhibit` suffixes."
        ),
        root_cause=(
            "MWCC's auto-inline heuristic inlines small same-TU functions at "
            "call sites that the original code did not inline. The thunk forces "
            "MWCC to emit a normal `bl` to the wrapped function because the "
            "thunk body is what gets inlined, not the wrapped function."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl", "actual": "<inlined body>"},
                description=(
                    "Target shows `bl <function>` but your code has the function body inlined"
                ),
            ),
            Signal(
                type="extra_instruction",
                data={"opcode": "<many>", "context": "function body inlined where bl expected"},
                description="Multiple extra instructions where a single `bl` is expected",
            ),
        ],
        examples=[
            Example(
                function="ftCo_800A0508_dontinline",
                context=(
                    "Shim for ftCo_800A0508 inside ftCo_0A01.c. Six similar shims "
                    "exist in this file: 800A0508, 800A20A0, 800A80E4, IsAlly, "
                    "800A5294, 800AABC8, 800B0760."
                ),
                before=(
                    "// Direct call gets auto-inlined by MWCC -inline auto:\n"
                    "ftCo_800A0508(fp);\n"
                ),
                after=(
                    "static inline void ftCo_800A0508_dontinline(Fighter* fp)\n"
                    "{\n"
                    "    ftCo_800A0508(fp);\n"
                    "}\n"
                    "// Call site:\n"
                    "ftCo_800A0508_dontinline(fp);\n"
                ),
            ),
            Example(
                function="it_8029FE64_no_inline",
                context="itlinkboomerang.c shim with `_no_inline` suffix",
                before="it_8029FE64(gobj, 0);",
                after=(
                    "static inline void it_8029FE64_no_inline(Item_GObj* gobj, s32 i)\n"
                    "{\n"
                    "    it_8029FE64(gobj, i);\n"
                    "}\n"
                ),
            ),
            Example(
                function="mpCollEnd_inline",
                context=(
                    "mpcoll.c uses the same shim pattern with comment "
                    "`// inhibit inlining` and a different naming convention."
                ),
                after=(
                    "static inline void mpCollEnd_inline(CollData* coll, int line_id,\n"
                    "                                    bool arg2, float dy)\n"
                    "{\n"
                    "    // inhibit inlining\n"
                    "    mpColl_80043268(coll, line_id, arg2, dy);\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Wrap the direct call in a same-TU `static inline` shim "
                    "whose body is only the call. Name with `_dontinline`, "
                    "`_no_inline`, or `_inhibit` suffix to document intent. "
                    "Use when target shows `bl X` but MWCC keeps inlining `X`."
                ),
                before=(
                    "void caller(Args* a)\n"
                    "{\n"
                    "    helper(a);  // Auto-inlined by MWCC\n"
                    "}\n"
                ),
                after=(
                    "static inline void helper_dontinline(Args* a) { helper(a); }\n"
                    "\n"
                    "void caller(Args* a)\n"
                    "{\n"
                    "    helper_dontinline(a);  // emits real `bl helper`\n"
                    "}\n"
                ),
                success_rate=0.9,
            ),
            Fix(
                description=(
                    "Alternative: use `#pragma dont_inline on/reset` around the "
                    "helper function definition. WARNING: `dont_inline` blocks "
                    "inlining IN BOTH DIRECTIONS — the function won't be "
                    "inlined by callers AND won't inline its own callees "
                    "(static inline from headers). Use only when the wrapped "
                    "function does not itself call HSD inline helpers."
                ),
                before="static void helper(Args* a) { ... }",
                after=(
                    "#pragma dont_inline on\n"
                    "static void helper(Args* a) { ... }\n"
                    "#pragma dont_inline reset\n"
                ),
                success_rate=0.7,
            ),
            Fix(
                description=(
                    "Alternative: `#pragma auto_inline off/on` around the helper "
                    "function. This prevents auto-inline at callers but the "
                    "function CAN still inline its own callees (HSD inline "
                    "helpers). Use when the wrapped function calls HSD "
                    "JObjSet* inlines."
                ),
                before="static void helper(Args* a) { ... HSD_JObjSetTranslateX(...); }",
                after=(
                    "#pragma auto_inline off\n"
                    "static void helper(Args* a) { ... HSD_JObjSetTranslateX(...); }\n"
                    "#pragma auto_inline on\n"
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["bl"],
        categories=["inline", "calling-conv", "register"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftCo_800A0508", pr="https://github.com/doldecomp/melee/pull/1869"),
                ProvenanceEntry(function="mpCollEnd", scratch=""),
                ProvenanceEntry(function="it_8029FE64", scratch=""),
            ],
        ),
        related_patterns=["inline-vs-non-inline-function", "extra-register-move"],
        notes=(
            "MWCC has two independent settings: `-inline auto` (compiler flag) "
            "enables/disables auto-inlining globally; `#pragma auto_inline` "
            "and `#pragma dont_inline` toggle it per-function. The shim trick "
            "is purely source-level and works regardless of pragma state."
        ),
    ),
    Pattern(
        id="static-inline-function-body-split",
        name="Split function body into `_inline0`, `_inline1` helpers",
        description=(
            "When a single function won't match because of register allocation, "
            "load scheduling, or stack frame issues, split its body into "
            "multiple `static inline` helper functions named `<func>_inline0`, "
            "`<func>_inline1`, etc. Each helper isolates a chunk of work, "
            "constraining MWCC's register/load scheduling to a smaller scope."
        ),
        root_cause=(
            "The original code was likely written using macros or already-inlined "
            "helpers. Splitting into named static inlines re-creates that "
            "boundary, locking in register reuse, spill ordering, and stack "
            "layout. This also reduces the outer function's stack frame because "
            "helper locals live in the helper's scope."
        ),
        signals=[
            Signal(
                type="offset_delta",
                data={"register": "r1", "delta": None},
                description="Stack frame too large; outer function spills too many locals",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "lwz", "..."]},
                description="Adjacent blocks of similar instructions appear duplicated in expected",
            ),
        ],
        examples=[
            Example(
                function="ftCo_800A1CC4",
                context=(
                    "ftCo_0A01.c splits 800A1CC4 into two helpers: `_inline0` "
                    "(per-iteration predicate) and `_inline1` (side-effect store "
                    "block). Each is called twice inside the outer loop."
                ),
                before=(
                    "static void ftCo_800A1CC4(Fighter* fp, ftCo_803C6594_t* var_r29)\n"
                    "{\n"
                    "    // 60 lines of mixed predicate + store logic\n"
                    "}\n"
                ),
                after=(
                    "static inline bool ftCo_800A1CC4_inline0(Fighter* fp, ftCo_803C6594_t* var_r29,\n"
                    "                                         mp_UnkStruct0* temp_r3) { ... }\n"
                    "\n"
                    "static inline void ftCo_800A1CC4_inline1(Fighter* fp, float x, float y) { ... }\n"
                    "\n"
                    "static void ftCo_800A1CC4(Fighter* fp, ftCo_803C6594_t* var_r29)\n"
                    "{\n"
                    "    if (ftCo_800A1CC4_inline0(...)) { ftCo_800A1CC4_inline1(...); }\n"
                    "    // ...\n"
                    "}\n"
                ),
            ),
            Example(
                function="gm_801721EC",
                context=(
                    "gm_16F1.c splits a nested-loop search into four helpers: "
                    "`_1` (inner predicate), `_2` (inner-loop wrapper), `_3` "
                    "(second predicate), `_4` (second loop)."
                ),
                after=(
                    "static inline bool gm_801721EC_1(u32 i) { return ...; }\n"
                    "static inline bool gm_801721EC_2(void) {\n"
                    "    s32 i;\n"
                    "    for (i = 0; i < 0x42; i++)\n"
                    "        if (gm_801721EC_1(i)) return true;\n"
                    "    return false;\n"
                    "}\n"
                    "static inline bool gm_801721EC_3(u32 j) { return ...; }\n"
                    "static inline bool gm_801721EC_4(void) {\n"
                    "    s32 j;\n"
                    "    for (j = 0; j < 0x125; j++)\n"
                    "        if (gm_801721EC_3(j)) return true;\n"
                    "    return false;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Identify repeated or self-contained blocks in the outer "
                    "function and extract each into a `static inline` helper "
                    "named `<outer>_inline0`, `_inline1`, etc. Pass only the "
                    "locals the block needs. Re-run checkdiff after each split."
                ),
                success_rate=0.7,
            ),
            Fix(
                description=(
                    "When the same predicate is checked twice (once for control "
                    "flow, once with side effects), extract the predicate as "
                    "`_inline0` and the side effect as `_inline1`. This is the "
                    "permuter-style match."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=[],
        categories=["inline", "register", "stack", "control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftCo_800A1CC4"),
                ProvenanceEntry(function="gm_801721EC"),
            ],
        ),
        related_patterns=["static-inline-dontinline-wrapper"],
        notes=(
            "Often discovered by running decomp.me permuter, which generates "
            "split-helper variants. If permuter gets a 99% with split helpers, "
            "commit the split rather than fight register allocation directly."
        ),
    ),
    Pattern(
        id="static-inline-m2c-goto-preservation",
        name="Preserve m2c goto-style control flow inside a static inline",
        description=(
            "When m2c produces irreducible control flow with `goto block_N` and "
            "`loop_N` labels, restructuring as for/while loops in C produces "
            "wrong branch ordering and fall-through patterns. Keeping the goto "
            "soup inside a `static inline` helper isolates it while keeping the "
            "outer function readable."
        ),
        root_cause=(
            "The original assembly has irreducible basic-block structure "
            "(forward gotos out of nested switches/ifs, multi-entry loops). "
            "Structured C can't reproduce this. m2c's goto output is "
            "byte-for-byte equivalent to the asm but ugly. Wrapping it in an "
            "inline isolates the ugliness and forces MWCC to emit the gotos "
            "verbatim."
        ),
        signals=[
            Signal(
                type="branch_polarity",
                data={"expected": "any", "actual": "any", "context": "forward branches reordered"},
                description="Branches go to wrong block addresses; fall-through patterns differ",
            ),
        ],
        examples=[
            Example(
                function="inlineL0",
                context=(
                    "ftCo_0A01.c: `inlineL0` keeps m2c's raw goto labels "
                    "(`goto loop_8`, `goto block_3`, `goto block_7`, etc.) "
                    "verbatim. Called once from ftCo_800A2718."
                ),
                after=(
                    "static inline bool inlineL0(mp_UnkStruct0* arg0)\n"
                    "{\n"
                    "    Item_GObj* cur;\n"
                    "    s32 temp_cr0_eq;\n"
                    "    s32 var_r0;\n"
                    "    Item* cur_ip;\n"
                    "    cur = HSD_GObj_Entities->items;\n"
                    "    goto loop_8;\n"
                    "block_3:\n"
                    "    cur_ip = GET_ITEM(cur);\n"
                    "    if (it_8026C1B4(cur) == 0) {\n"
                    "        goto block_7;\n"
                    "    }\n"
                    "    if (!ftCo_800A5944(cur_ip)) goto block_7;\n"
                    "    if (arg0 != mpIsland_8005AB54(cur_ip->x378_itemColl.floor.index))\n"
                    "        goto block_7;\n"
                    "    return 1;\n"
                    "block_7:\n"
                    "    cur = cur->next;\n"
                    "loop_8:\n"
                    "    if (cur != NULL) goto block_3;\n"
                    "    return 0;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Run m2c on the function. If output has multiple goto labels "
                    "that aren't easily restructurable, copy the m2c output "
                    "verbatim into a `static inline` helper. Rename the labels "
                    "if needed but keep the goto structure. Call the inline from "
                    "the outer function."
                ),
                success_rate=0.6,
            ),
            Fix(
                description=(
                    "Avoid this pattern unless restructured C produces wrong "
                    "branch ordering. Most loops should be expressed as `for` or "
                    "`while`. Only fall back to gotos for truly irreducible CFGs."
                ),
            ),
        ],
        opcodes=["b", "beq", "bne", "blt", "bgt"],
        categories=["inline", "control-flow", "branch"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftCo_800A2718"),
            ],
        ),
        related_patterns=["static-inline-function-body-split"],
    ),
    Pattern(
        id="static-inline-bool-explicit-true-false-return",
        name="`if (cond) return true; else return false;` inline wrapper",
        description=(
            "Writing `return (cond)` directly produces `rlwinm`/`cntlzw` "
            "codegen, but the original asm uses a `cmpwi`/`li r3,1`/`li r3,0` "
            "branch-and-load-immediate sequence. Wrap the test in a "
            "`static inline bool` helper with explicit `if/else return true/false` "
            "to force the branch form."
        ),
        root_cause=(
            "MWCC's codegen for `return <bool-expr>` depends on the expression "
            "shape. A flag test like `return (x & MASK)` becomes `rlwinm` plus "
            "a `cntlzw`/`xor` to produce 0/1. The original code was written as "
            "`if (cond) return true; else return false;`, which MWCC compiles "
            "to `cmpwi`/branch/`li 0`/`li 1`. The two forms produce different "
            "bytes but identical behavior."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "cmpwi", "actual": "rlwinm"},
                description="Expected a branch test; actual uses bit-extract",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "li", "actual": "cntlzw"},
                description="Expected explicit 1/0 load; actual uses count-leading-zero trick",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["cmpwi", "bne", "li", "b", "li"]},
                description="Classic 5-instruction bool-with-branch sequence",
            ),
        ],
        examples=[
            Example(
                function="inlineC0",
                context="ftCo_800A3498 wraps a wall-collision flag test",
                before=(
                    "// Direct return: generates rlwinm/cntlzw\n"
                    "bool ftCo_800A3498(Fighter* fp)\n"
                    "{\n"
                    "    return (fp->coll_data.env_flags & Collide_WallMask) != 0;\n"
                    "}\n"
                ),
                after=(
                    "static inline bool inlineC0(Fighter* fp)\n"
                    "{\n"
                    "    if (fp->coll_data.env_flags & Collide_WallMask) {\n"
                    "        return true;\n"
                    "    } else {\n"
                    "        return false;\n"
                    "    }\n"
                    "}\n"
                ),
            ),
            Example(
                function="samus_grapple_fighter_compare",
                context="itsamusgrapple.c — 4-value motion-id comparison",
                after=(
                    "static inline bool samus_grapple_fighter_compare(FtMotionId id)\n"
                    "{\n"
                    "    if ((id == 0x165) || (id == 0x166) || (id == 0xD4) || (id == 0xD6)) {\n"
                    "        return true;\n"
                    "    }\n"
                    "    return false;\n"
                    "}\n"
                ),
            ),
            Example(
                function="cam_bound",
                context="camera.c — single comparison wrapped for matching",
                after=(
                    "static inline bool cam_bound(float x)\n"
                    "{\n"
                    "    return x > 0.65f || x < 0.35f;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When you see `rlwinm`/`cntlzw` in your code but the target "
                    "has `cmpwi`/`li`/`b`/`li` sequence, rewrite the return as "
                    "explicit `if (cond) return true; else return false;`. If "
                    "the test is used multiple times, extract it as a "
                    "`static inline bool` helper."
                ),
                before="return (fp->flags & MASK) != 0;",
                after=(
                    "if (fp->flags & MASK) {\n"
                    "    return true;\n"
                    "} else {\n"
                    "    return false;\n"
                    "}\n"
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["cmpwi", "li", "rlwinm", "cntlzw"],
        categories=["inline", "branch", "control-flow", "type"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftCo_800A3498"),
                ProvenanceEntry(function="cam_bound"),
            ],
        ),
        related_patterns=["branch-polarity-null-check"],
    ),
    Pattern(
        id="newton-raphson-sqrt-inline",
        name="Newton-Raphson sqrt inline matching MWCC's sqrtf codegen",
        description=(
            "MWCC inlines `sqrtf` as 3 Newton-Raphson iterations over "
            "`__frsqrte` (reciprocal square root estimate). The original Melee "
            "code called `sqrtf` from a math header that MWCC inlined; the "
            "decomp must replicate that body. Two main forms: helper function "
            "with stack dummy + `volatile f32 y`, or inlined directly at the "
            "call site."
        ),
        root_cause=(
            "MWCC's CW1.2.5n doesn't have a sqrt opcode; it generates 3 NR "
            "iterations of `e = 0.5 * e * (3.0 - e*e*x)` from `__frsqrte(x)`. "
            "The volatile `y` forces an `stfs`/`lfs` pair on the stack between "
            "the last multiply and the return. The `u8 _[N] = {0}` stack dummy "
            "tunes the helper's stack frame size to absorb stack the caller "
            "would otherwise have needed."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["frsqrte", "fmul", "fmsubs", "fmul", "fnmsubs", "fmul"]},
                description=(
                    "Run of `frsqrte` followed by alternating `fmul`/`fmsubs` "
                    "(positive form) or `fnmsubs` (negated form) for 3 iterations"
                ),
            ),
            Signal(
                type="extra_instruction",
                data={"opcode": "stfs", "context": "stack temp for volatile result"},
                description="Extra `stfs` to stack + `lfs` from stack for the volatile",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "fmuls", "actual": "<missing>"},
                description="Missing fmuls sequence when sqrtf is left as a call",
            ),
        ],
        examples=[
            Example(
                function="lbShadow_Sqrtf",
                context=(
                    "lbshadow.c (commit 85c48bed1, PR #2501). Helper variant "
                    "with `static const f64` constants, `u8 _[0x38]` stack "
                    "dummy, and `volatile f32 y`. PAD_STACK(0x48) was reduced "
                    "to PAD_STACK(0x10) because the 0x38 dummy absorbs 56 bytes."
                ),
                after=(
                    "static inline f32 lbShadow_Sqrtf(f32 x)\n"
                    "{\n"
                    "    static const f64 half = 0.5F;\n"
                    "    static const f64 three = 3.0F;\n"
                    "    u8 _[0x38] = { 0 };\n"
                    "    volatile f32 y;\n"
                    "\n"
                    "    if (x > 0.0f) {\n"
                    "        f64 guess = __frsqrte((f64) x);\n"
                    "        guess = half * guess * (three - guess * guess * x);\n"
                    "        guess = half * guess * (three - guess * guess * x);\n"
                    "        guess = half * guess * (three - guess * guess * x);\n"
                    "        y = (f32) (x * guess);\n"
                    "        return y;\n"
                    "    }\n"
                    "    return x;\n"
                    "}\n"
                ),
            ),
            Example(
                function="my_sqrtf",
                context=(
                    "itlinkboomerang.c, itsamusbomb.c, ftMasterHand/* etc. "
                    "Smaller stack dummy (u8 _[4]). Use when the caller's "
                    "PAD_STACK is minimal."
                ),
                after=(
                    "static inline float my_sqrtf(float x)\n"
                    "{\n"
                    "    static const double _half = .5;\n"
                    "    static const double _three = 3.0;\n"
                    "    u8 _[4] = { 0 };\n"
                    "    volatile float y;\n"
                    "    if (x > 0) {\n"
                    "        double guess = __frsqrte((double) x);\n"
                    "        guess = _half * guess * (_three - guess * guess * x);\n"
                    "        guess = _half * guess * (_three - guess * guess * x);\n"
                    "        guess = _half * guess * (_three - guess * guess * x);\n"
                    "        y = (float) (x * guess);\n"
                    "        return y;\n"
                    "    }\n"
                    "    return x;\n"
                    "}\n"
                ),
            ),
            Example(
                function="lbBgFlash_Inlined",
                context=(
                    "lbbgflash.c, lbrefract.c, lbcollision.c, gr/grkongo.c, "
                    "gm/gm_1832.c, ty/toy.c. Inlined directly at the callsite "
                    "with no helper. Uses the *negated* form "
                    "`e * -((x*e*e) - 3.0)` which compiles to `fnmsubs`."
                ),
                after=(
                    "// Inlined directly — no helper function:\n"
                    "if (dist_sq > 0.0f) {\n"
                    "    f64 e = __frsqrte(dist_sq);\n"
                    "    e = 0.5 * e * -(((f64) dist_sq * (e * e)) - 3.0);\n"
                    "    e = 0.5 * e * -(((f64) dist_sq * (e * e)) - 3.0);\n"
                    "    e = 0.5 * e * -(((f64) dist_sq * (e * e)) - 3.0);\n"
                    "    sp18 = (f32) ((f64) dist_sq * e);\n"
                    "    dist_sq = sp18;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If the target shows `frsqrte` + 3 NR iterations, replace "
                    "your `sqrtf(x)` call with the inline body. Choose: helper "
                    "function (multiple callsites in the function) vs inlined "
                    "directly (single callsite, fused with surrounding fp expr)."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Stack dummy `u8 _[N]` sizing: start with N=4. If target's "
                    "stack frame is larger than yours by K bytes, set N=K (or "
                    "K rounded to 8). If your stack frame is too large, reduce "
                    "PAD_STACK by K. The 0x38 (56-byte) dummy in lbshadow "
                    "absorbed a 0x38 of PAD_STACK from the caller."
                ),
                success_rate=0.7,
            ),
            Fix(
                description=(
                    "Use positive form `0.5 * e * (3.0 - e*e*x)` for `fmsubs`, "
                    "negated form `0.5 * e * -((e*e*x) - 3.0)` for `fnmsubs`. "
                    "Match whichever your target has."
                ),
                success_rate=0.9,
            ),
            Fix(
                description=(
                    "`volatile f32 y` is required when the asm has an "
                    "`stfs`/`lfs` round-trip on the stack between the last "
                    "multiply and the return. Omit if the result is consumed "
                    "directly without a stack temp."
                ),
                success_rate=0.8,
            ),
            Fix(
                description=(
                    "`static const f64 half/three` vs plain `double` literals: "
                    "use `static const f64` when target shows `lfd @RTOC,X(rN)` "
                    "(loads from .rodata). Plain literals can compile to f32 "
                    "immediates which compile differently."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["frsqrte", "fmul", "fmsubs", "fnmsubs", "fmadds", "stfs", "lfs"],
        categories=["inline", "float", "stack"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbShadow_8000F38C", pr="https://github.com/doldecomp/melee/pull/2501"),
                ProvenanceEntry(function="my_sqrtf"),
            ],
        ),
        related_patterns=["incorrect-stack-size"],
        notes=(
            "Found in 25+ files. See lb/lbshadow.c, lb/lbbgflash.c, "
            "lb/lbrefract.c, lb/lbcollision.c, gr/grkongo.c, gm/gm_1832.c, "
            "ty/toy.c (inlined). And it/items/itlinkboomerang.c, "
            "itsamusbomb.c, itmasterhandlaser.c, itdrmariopill.c, "
            "ft/chara/ftMasterHand/*, ftCrazyHand/ftCh_Init.c, "
            "ftSeak/ftSk_SpecialHi.c, ftZelda/ftZd_SpecialHi.c (helper)."
        ),
    ),
    Pattern(
        id="hsd-inline-file-local-asserts",
        name="HSD_JObj inline reimplementation with file-local extern char strings",
        description=(
            "Calling HSD_JObjSet*/Get* inlines from baselib/jobj.h emits "
            "anonymous `@N`-style relocations for the `__FILE__` and condition "
            "strings inside HSD_ASSERT. These never match the target's "
            "relocation table, which references named global symbols. Fix by "
            "reimplementing the JObj inline locally and pointing __assert at "
            "file-local extern char symbols sized to be SDA-eligible."
        ),
        root_cause=(
            "HSD_ASSERT(line, cond) expands to "
            "`((cond) ? ((void) 0) : __assert(__FILE__, line, #cond))`. The "
            "`__FILE__` (`\"jobj.h\"`) and stringified `cond` end up as "
            "anonymous compiler-internal labels in your object's .rodata, "
            "producing relocations that don't exist in the target. Naming the "
            "strings as `static char` / `extern char` arrays at file scope "
            "gives them stable symbols that match the target."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "addis"},
                description=(
                    "When string is >8 bytes (non-SDA): your code uses single "
                    "`lwz r13,@SDA` but target uses `addis`+`lwz` pair from .data"
                ),
            ),
            Signal(
                type="extra_instruction",
                data={"opcode": "@N", "context": "anonymous string relocation"},
                description="Relocation table has anonymous @N labels for asserts",
            ),
        ],
        examples=[
            Example(
                function="ftKb_JObjSetScale",
                context=(
                    "ftKb_SpecialNNs.c — Variant B (file-local extern char). "
                    "Strings declared once at file scope and reused across all "
                    "reimplemented inlines. Sizes ≤8 bytes so they land in "
                    ".sdata and get R_PPC_EMB_SDA21 relocations."
                ),
                after=(
                    "extern char ftKb_Init_804D3DD0[7];  // \"jobj.h\\0\" (SDA-eligible)\n"
                    "extern char ftKb_Init_804D3DD8[5];  // \"jobj\\0\"\n"
                    "extern char ftKb_Init_804D3DE0[6];  // \"scale\\0\"\n"
                    "\n"
                    "static inline void ftKb_JObjSetScale(HSD_JObj* jobj, Vec3* scale)\n"
                    "{\n"
                    "    (jobj)  ? ((void) 0) : __assert(ftKb_Init_804D3DD0, 0x2F8, ftKb_Init_804D3DD8);\n"
                    "    (scale) ? ((void) 0) : __assert(ftKb_Init_804D3DD0, 0x2F9, ftKb_Init_804D3DE0);\n"
                    "    jobj->scale = *scale;\n"
                    "    if (!(jobj->flags & JOBJ_MTX_INDEP_SRT)) {\n"
                    "        if (jobj != NULL && !ftKb_JObjMtxIsDirty(jobj)) {\n"
                    "            HSD_JObjSetMtxDirtySub(jobj);\n"
                    "        }\n"
                    "    }\n"
                    "}\n"
                ),
            ),
            Example(
                function="Toy_JObjSetTranslateX",
                context="toy.c — defines strings inline before each inline group",
                after=(
                    "static char un_804D5A64[] = \"jobj.h\";  // 7 bytes - SDA\n"
                    "static char un_804D5A6C[] = \"jobj\";    // 5 bytes - SDA\n"
                    "\n"
                    "static inline void Toy_JObjSetTranslateX(HSD_JObj* jobj, f32 x)\n"
                    "{\n"
                    "    (jobj) ? ((void) 0) : __assert(un_804D5A64, 0x3A4, un_804D5A6C);\n"
                    "    jobj->translate.x = x;\n"
                    "    if (!(jobj->flags & JOBJ_MTX_INDEP_SRT)) {\n"
                    "        Toy_JObjSetMtxDirty(jobj);\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "1. Check symbols.txt for existing extern char symbols at "
                    "the expected addresses (look for size 5-7 in .sdata). "
                    "2. Declare them: `extern char NAME_ADDR[N];` where N is "
                    "size from symbols.txt (≤8 keeps them SDA). "
                    "3. Reimplement the HSD inline locally and use __assert "
                    "directly with the file-local symbols. "
                    "4. Reimplement HSD_JObjMtxIsDirty locally too (the "
                    "HSD_JObjSetMtxDirty macro calls it and triggers another assert)."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "DO NOT try `#undef HSD_ASSERT` / `#define HSD_ASSERT` to "
                    "redirect. MWCC parses inline function bodies at include "
                    "time, so the macro override at the call site has no "
                    "effect on already-included inlines."
                ),
            ),
            Fix(
                description=(
                    "Size matters for SDA eligibility. <=8 bytes -> .sdata -> "
                    "R_PPC_EMB_SDA21. >8 bytes -> .data -> "
                    "R_PPC_ADDR16_HA + R_PPC_ADDR16_LO pair. Match the "
                    "relocation type to symbols.txt."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["lwz", "addis"],
        categories=["inline", "data-layout", "calling-conv"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftKb_JObjSetScale"),
                ProvenanceEntry(function="Toy_JObjSetTranslateX"),
                ProvenanceEntry(function="mnDiagram_JObjSetTranslateY"),
            ],
        ),
        related_patterns=[
            "fake-hsd-inline-with-literal-string-macro",
            "base-relative-string-addressing-assertions",
        ],
        notes=(
            "Variant B used in: ftKb_SpecialNNs.c, mndiagram.static.h, "
            "mndiagram2.static.h, mndiagram3.static.h, toy.c. Symbols.txt "
            "string sizes: 'jobj.h\\0'=7, 'jobj\\0'=5, 'scale\\0'=6, "
            "'rotate\\0'=7. Functions commonly reimplemented: "
            "HSD_JObjSetTranslate/X/Y/Z, HSD_JObjSetRotation/X/Y/Z, "
            "HSD_JObjSetScale/X/Y/Z, HSD_JObjGetRotation, "
            "HSD_JObjAddTranslationY/Rotation*."
        ),
    ),
    Pattern(
        id="fake-hsd-inline-with-literal-string-macro",
        name="`fake_HSD_ASSERT` macro + `Fake_HSD_JObj*` inline reimplementation",
        description=(
            "Quick variant of HSD inline reimplementation: instead of file-"
            "local extern char strings, use a `fake_HSD_ASSERT` macro that "
            "expands to `__assert(\"jobj.h\", line, #cond)`. The literal "
            "strings get deduplicated by the linker into a single global pool. "
            "Faster to write than Variant B but only matches when target's "
            "relocations point at the linker's deduplicated pool."
        ),
        root_cause=(
            "Same as Variant B (file-local extern char) — anonymous HSD_ASSERT "
            "relocations don't match. This variant uses a private macro to "
            "spell the strings literally; the linker dedupes identical "
            "literals across TUs."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "addis"},
                description="String relocations differ between your code and target",
            ),
        ],
        examples=[
            Example(
                function="FakeHSD_JObjSetRotation",
                context=(
                    "lbbgflash.c (commit 53a4a90f2, PR #2313). Uses "
                    "`fake_HSD_ASSERT` macro to make all asserts share the "
                    "same literal `\"jobj.h\"` string."
                ),
                after=(
                    "#define fake_HSD_ASSERT(line, cond)                          \\\n"
                    "    ((cond) ? ((void) 0) : __assert(\"jobj.h\", line, #cond))\n"
                    "\n"
                    "static inline void FakeHSD_JObjSetRotation(HSD_JObj* jobj, Quaternion* rotate)\n"
                    "{\n"
                    "    fake_HSD_ASSERT(618, jobj);\n"
                    "    fake_HSD_ASSERT(619, rotate);\n"
                    "    jobj->rotate = *rotate;\n"
                    "    if (!(jobj->flags & JOBJ_MTX_INDEP_SRT)) {\n"
                    "        HSD_JObjSetMtxDirty(jobj);\n"
                    "    }\n"
                    "}\n"
                ),
            ),
            Example(
                function="fake_HSD_JObjAddTranslationY",
                context=(
                    "itlinkbomb.c — variant that calls ftCo_800C6AFC (a "
                    "non-HSD dirty-flag path) instead of HSD_JObjSetMtxDirtySub"
                ),
                after=(
                    "static inline void fake_HSD_JObjAddTranslationY(HSD_JObj* jobj, float y)\n"
                    "{\n"
                    "    HSD_ASSERT(1114, jobj);\n"
                    "    jobj->translate.y += y;\n"
                    "    if (!(jobj->flags & JOBJ_MTX_INDEP_SRT)) {\n"
                    "        ftCo_800C6AFC(jobj);\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Define a private `fake_HSD_ASSERT(line, cond)` macro that "
                    "expands to `__assert(\"jobj.h\", line, #cond)`. Reimplement "
                    "each HSD inline locally as `FakeHSD_JObjSet*` using this "
                    "macro. Use when the target's relocation points at the "
                    "linker's deduplicated literal pool, not at a TU-local string."
                ),
                success_rate=0.7,
            ),
            Fix(
                description=(
                    "If literal-string-pool form doesn't match, switch to "
                    "Variant B (file-local extern char) — see "
                    "hsd-inline-file-local-asserts."
                ),
            ),
        ],
        opcodes=["lwz", "addis"],
        categories=["inline", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbBgFlash_80021A18", pr="https://github.com/doldecomp/melee/pull/2313"),
            ],
        ),
        related_patterns=["hsd-inline-file-local-asserts"],
        notes=(
            "Used in: lbbgflash.c, gmregtyfall.static.h, itbombhei.static.h, "
            "itkyasarin.c, itlinkarrow.c, itlinkbomb.c, grcastle.c, "
            "grcorneria.c, ft_0C31.c. Note: `inline` (no `static`) is used in "
            ".static.h shared headers; `static inline` for TU-local."
        ),
    ),
    Pattern(
        id="static-inline-counting-loop-wrapper",
        name="Wrap counting/iteration loop in static inline",
        description=(
            "When a counting loop (`for (i=0; i<N; i++) if (cond) count++`) "
            "won't match, wrap the entire loop in a `static inline` helper "
            "function. The inline forces specific register allocation and "
            "instruction sequencing — particularly the `li r30,0`/`addi r31,r30,0` "
            "zero-copy pattern and tight callee-saved register usage."
        ),
        root_cause=(
            "MWCC has internal heuristics for loop optimization that differ "
            "based on context. When the loop is at function scope, MWCC may "
            "constant-propagate `i = count` (when count starts at 0) into "
            "`li`/`li` separate immediates. Wrapping in `static inline` "
            "introduces a data dependency through the inline's locals, forcing "
            "the compiler to materialize the zero in one register and copy it."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "addi", "actual": "li"},
                description="Target has `addi rX,rY,0` (register copy); your code has `li rX,0`",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["li", "addi", "..."]},
                description="`li r30,0` followed by `addi r31,r30,0` (copy zero)",
            ),
        ],
        examples=[
            Example(
                function="mnEvent_8024CE74",
                context=(
                    "Matched 99.4% -> 100% by wrapping the counting loop in "
                    "`mnName_CountValidNames` style static inline. Removing "
                    "PAD_STACK was needed because the inline changed the "
                    "stack frame."
                ),
                before=(
                    "s32 mnEvent_8024CE74(void)\n"
                    "{\n"
                    "    s32 count = 0;\n"
                    "    s32 i;\n"
                    "    for (i = 0; i < N; i++) {\n"
                    "        if (cond(i)) count++;\n"
                    "    }\n"
                    "    return count;\n"
                    "}\n"
                ),
                after=(
                    "static inline s32 count_helper(void)\n"
                    "{\n"
                    "    s32 i;\n"
                    "    s32 count;\n"
                    "    count = 0;\n"
                    "    for (i = 0; i < N; i++) {\n"
                    "        if (cond(i)) count++;\n"
                    "    }\n"
                    "    return count;\n"
                    "}\n"
                    "\n"
                    "s32 mnEvent_8024CE74(void)\n"
                    "{\n"
                    "    return count_helper();\n"
                    "}\n"
                ),
            ),
            Example(
                function="mnCount_8025035C_inline",
                context=(
                    "mncount.c — boolean counting loop checking if any "
                    "fighter has nonzero play_time"
                ),
                after=(
                    "static inline bool mnCount_8025035C_inline(void)\n"
                    "{\n"
                    "    s32 i;\n"
                    "    for (i = 0; i < 25; i++) {\n"
                    "        if (GetPersistentFighterData(i)->play_time != 0) {\n"
                    "            return false;\n"
                    "        }\n"
                    "    }\n"
                    "    return true;\n"
                    "}\n"
                ),
            ),
            Example(
                function="IsNameListFull",
                context="mnname.c — wraps the IsNameValid counting loop",
                after=(
                    "static inline s32 mnName_CountValidNames(void)\n"
                    "{\n"
                    "    s32 i;\n"
                    "    s32 count = 0;\n"
                    "    for (i = 0; i < 0x20; i++) {\n"
                    "        if (IsNameValid((u8) i)) count++;\n"
                    "    }\n"
                    "    return count;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Move the counting/iteration loop into a `static inline` "
                    "helper that returns the result. Declare locals in the "
                    "order the target expects (counter first usually). Remove "
                    "PAD_STACK from the outer function — the inline changes "
                    "stack frame requirements."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Declaration order matters: declare `i` first (lower "
                    "register), `count` second (higher register). The compiler "
                    "honors declaration order for callee-saved register "
                    "assignment."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["addi", "li", "or", "stw"],
        categories=["inline", "loop", "register", "stack"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnEvent_8024CE74"),
                ProvenanceEntry(function="IsNameListFull"),
            ],
        ),
        related_patterns=["loop-variable-copy-pattern-addi-rx-ry-0-instead-of-li"],
        notes=(
            "Use when a simple counting loop won't match. Variants in "
            "mncount.c, mnname.c, gm_16F1.c, ftCo_0A01.c (numerous). The "
            "trick is independent of what the loop does — the magic is the "
            "inline boundary forcing the data dependency."
        ),
    ),
    Pattern(
        id="static-inline-table-preload",
        name="Pre-load pointer table into local array inside static inline",
        description=(
            "When iterating over a small fixed-size array of pointers, copy "
            "each pointer into a local array first, then iterate. The pre-load "
            "forces MWCC to emit a specific load schedule (e.g. all loads "
            "first, then all comparisons) that matches the target."
        ),
        root_cause=(
            "MWCC's load scheduling depends on how the data is accessed. "
            "`if (table[i]->field == x)` inside a loop may produce interleaved "
            "loads/compares. Pre-loading into a local array forces the loads "
            "to a known position (often at the top of the inline), giving "
            "stable codegen."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "lwz", "lwz", "lwz", "lwz", "lwz"]},
                description="Sequence of 6+ consecutive loads (the table preload)",
            ),
        ],
        examples=[
            Example(
                function="mnName_FindAnimLoop",
                context=(
                    "mnname.c — copies a 6-element AnimLoopSettings pointer "
                    "table into a local array, then iterates with frame "
                    "comparisons. Used by mnName_80238964/A04."
                ),
                after=(
                    "static inline AnimLoopSettings*\n"
                    "mnName_FindAnimLoop(AnimLoopSettings** tableBase, f32 frame)\n"
                    "{\n"
                    "    AnimLoopSettings* table[6];\n"
                    "    char* msg;\n"
                    "    s32 i;\n"
                    "\n"
                    "    table[0] = tableBase[0];\n"
                    "    table[1] = tableBase[1];\n"
                    "    table[2] = tableBase[2];\n"
                    "    table[3] = tableBase[3];\n"
                    "    table[4] = tableBase[4];\n"
                    "    table[5] = tableBase[5];\n"
                    "\n"
                    "    for (i = 0; i < 6; i++) {\n"
                    "        if (table[i]->start_frame <= frame && frame <= table[i]->end_frame) {\n"
                    "            return table[i];\n"
                    "        }\n"
                    "    }\n"
                    "    msg = \"But AnimFrame!!!\\n\";\n"
                    "    HSD_ASSERTREPORT(0x3DC, NULL, msg);\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When the target shows a long run of sequential loads "
                    "before the loop body, copy the table entries into a "
                    "local fixed-size array first. The array size must be "
                    "compile-time constant. Wrap in `static inline`."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lwz", "stw"],
        categories=["inline", "loop", "register", "stack"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnName_80238964"),
            ],
        ),
        related_patterns=["static-inline-counting-loop-wrapper"],
    ),
    Pattern(
        id="static-inline-dual-pointer-cleanup",
        name="Dual-pointer pattern in static inline for cleanup loops",
        description=(
            "When a cleanup loop checks `array[i]` for NULL, calls a function "
            "with it, then sets it NULL, MWCC may generate the wrong load "
            "schedule when written with a single pointer. Use two identical "
            "pointers: one for checks/stores, one for calls. Often wrapped in "
            "a `static inline` helper."
        ),
        root_cause=(
            "MWCC schedules loads based on which pointer expression appears in "
            "which context. With a single `data` pointer used for check, call, "
            "and store, MWCC may collapse loads. Splitting into `ptr = data` "
            "(same value, different binding) forces separate load paths for "
            "the check side and the call side."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "<missing>"},
                description="Extra loads in target that your code optimized away",
            ),
        ],
        examples=[
            Example(
                function="mnDiagram2_ClearStatRows",
                context=(
                    "Canonical pattern, 100% match. Two pointers initialized to "
                    "same value: `ptr = data = gobj->user_data`. Check with "
                    "`data->array[i]`, call with `ptr->array[i]`, NULL-store "
                    "with `data->array[i]`."
                ),
                after=(
                    "void mnDiagram2_ClearStatRows(HSD_GObj* gobj)\n"
                    "{\n"
                    "    Diagram2* ptr;\n"
                    "    Diagram2* data;\n"
                    "    s32 i;\n"
                    "    ptr = data = gobj->user_data;  // dual init\n"
                    "    for (i = 0; i < 4; i++) {\n"
                    "        if (data->row_gobjs[i] != NULL) {\n"
                    "            HSD_GObjDelete(ptr->row_gobjs[i]);\n"
                    "            data->row_gobjs[i] = NULL;\n"
                    "        }\n"
                    "    }\n"
                    "}\n"
                ),
            ),
            Example(
                function="fn_8024E1B4",
                context=(
                    "Improved from 50.9% -> 100% by combining dual-pointer "
                    "pattern with a root variable. Variable order: "
                    "`HSD_JObj* root = gobj->hsd_obj` before data assignment "
                    "forces correct load order."
                ),
                after=(
                    "void fn_8024E1B4(HSD_GObj* gobj)\n"
                    "{\n"
                    "    HSD_JObj* root = gobj->hsd_obj;  // load order forcer\n"
                    "    Diagram2* ptr;\n"
                    "    Diagram2* data;\n"
                    "    ptr = data = gobj->user_data;\n"
                    "    // ... dual-pointer cleanup loop ...\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Add a second pointer (`ptr`) initialized to the same "
                    "value as `data`. Use `data` for checks and stores, `ptr` "
                    "for function-call arguments. This forces MWCC to generate "
                    "separate load paths."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Pair with a 'root' variable: `T* root = parent->child` "
                    "declared before the dual pointers. This forces an early "
                    "load of `parent->child` that matches the target's first "
                    "instruction."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["lwz", "stw"],
        categories=["inline", "loop", "struct", "register"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnDiagram2_ClearStatRows"),
                ProvenanceEntry(function="fn_8024E1B4"),
            ],
        ),
    ),
    Pattern(
        id="static-inline-helper-numeric-idiom",
        name="Small numeric helper inline for repeated arithmetic idioms",
        description=(
            "When the same numeric expression appears multiple times in a "
            "function (`127.0F * cosf(x)`, `val/a` with clamp, etc.), "
            "extracting it into a small `static inline` helper produces "
            "identical codegen at each callsite. Direct inline expressions "
            "may compile differently depending on surrounding context, "
            "breaking the byte-for-byte match."
        ),
        root_cause=(
            "MWCC's expression-tree optimization is context-sensitive. The "
            "same `127.0F * cosf(x)` may produce different fp temp scheduling "
            "depending on what comes before/after. A `static inline` helper "
            "creates an isolated expression context, forcing identical codegen "
            "at every callsite."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["fmul", "fctiwz", "stfd", "lwz"]},
                description="Common float-to-int conversion sequence",
            ),
        ],
        examples=[
            Example(
                function="angle_x_units",
                context=(
                    "ftCo_0A01.c — `static inline int angle_x_units(float angle) "
                    "{ return 127.0F * cosf(angle); }` used 8 times in "
                    "ftCo_800A8EB0."
                ),
                after=(
                    "static inline int angle_x_units(float angle)\n"
                    "{\n"
                    "    return 127.0F * cosf(angle);\n"
                    "}\n"
                    "\n"
                    "static inline int angle_y_units(float angle)\n"
                    "{\n"
                    "    return 127.0F * sinf(angle);\n"
                    "}\n"
                ),
            ),
            Example(
                function="inlineB0",
                context=(
                    "ftCo_0A01.c — ternary clamp helper. Used by ftCo_800A1874, "
                    "_1994, _1A24 for lstickY/cstickX/Y conversions."
                ),
                after=(
                    "static inline float inlineB0(s8 val, float a, float b)\n"
                    "{\n"
                    "    float ret = val > 0 ? val / a : val / b;\n"
                    "    return ret > +1.0 ? +1.0F : ret < -1.0 ? -1.0F : ret;\n"
                    "}\n"
                ),
            ),
            Example(
                function="it_link_lerp",
                context="itlinkhookshot.c — generic lerp helper",
                after=(
                    "static inline f32 it_link_lerp(f32 a, f32 b, f32 t)\n"
                    "{\n"
                    "    return t * a + (1.0F - t) * b;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When you see the same numeric expression appearing "
                    "multiple times in a function and your code matches in "
                    "some callsites but not others, extract the expression "
                    "as a `static inline` helper. This forces uniform codegen."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["fmul", "fctiwz", "fmadd", "fmadds", "fnabs"],
        categories=["inline", "float"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftCo_800A8EB0"),
                ProvenanceEntry(function="ftCo_800A1874"),
            ],
        ),
    ),
    Pattern(
        id="static-inline-typed-overload-pair",
        name="Near-identical `static inline` helpers typed for different entity kinds",
        description=(
            "When a function iterates over fighters and a structurally identical "
            "function iterates over items, do NOT factor them into a single "
            "void-pointer helper. Keep two near-identical `static inline` "
            "copies with different parameter types. The original code likely "
            "did the same, and unifying them changes register/load codegen."
        ),
        root_cause=(
            "MWCC's codegen for `Fighter*` vs `Item*` parameters can differ "
            "based on field offsets and struct layouts. A unified helper using "
            "`void*` casts produces different loads than the typed versions. "
            "Keeping two copies preserves matching at the cost of duplication."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "<different offset>"},
                description="Loads use struct-specific offsets that a generic helper would lose",
            ),
        ],
        examples=[
            Example(
                function="ftCo_800A2170 vs ftCo_800A2170_it",
                context=(
                    "ftCo_0A01.c — same function shape, one takes "
                    "`(Fighter*, Fighter*)`, other takes `(Fighter*, Item*)`. "
                    "Both check ground/air state and mpIsland equality."
                ),
                after=(
                    "// Fighter-fighter version (real function):\n"
                    "bool ftCo_800A2170(Fighter* fp0, Fighter* fp1) { ... }\n"
                    "\n"
                    "// Fighter-item version (inline helper):\n"
                    "static inline bool ftCo_800A2170_it(Fighter* fp, Item* ip)\n"
                    "{\n"
                    "    mp_UnkStruct0* data;\n"
                    "    if (fp->ground_or_air == GA_Air) return false;\n"
                    "    if (ip->ground_or_air == GA_Air) return false;\n"
                    "    data = mpIsland_8005AB54(fp->coll_data.floor.index);\n"
                    "    if (data == NULL) return false;\n"
                    "    if (mpIsland_8005AB54(ip->x378_itemColl.floor.index) == data)\n"
                    "        return true;\n"
                    "    return false;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If you have two near-identical iteration helpers for "
                    "different entity types, keep them as separate "
                    "`static inline` functions with different parameter types. "
                    "Suffix the helper with `_ft`, `_it`, etc. to document intent."
                ),
                success_rate=0.8,
            ),
            Fix(
                description=(
                    "Resist the urge to unify with `void*` or generic helpers. "
                    "Matching trumps DRY in decomp."
                ),
            ),
        ],
        opcodes=["lwz", "lhz"],
        categories=["inline", "struct"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftCo_800A2170"),
            ],
        ),
    ),
]


def main():
    db_path = DEFAULT_DB_PATH
    conn = init_db(db_path)
    db = PatternDB(conn)

    inserted = 0
    updated = 0
    skipped = 0

    for pattern in PATTERNS:
        existing = db.get(pattern.id)
        if existing is not None:
            print(f"  EXISTS: {pattern.id} — deleting and re-inserting (refreshes content)")
            # Delete existing and re-insert with fresh content
            conn.execute("DELETE FROM patterns WHERE id = ?", (pattern.id,))
            conn.execute("DELETE FROM pattern_signals WHERE pattern_id = ?", (pattern.id,))
            conn.commit()
            db.insert(pattern)
            updated += 1
        else:
            db.insert(pattern)
            print(f"  ADDED:  {pattern.id}")
            inserted += 1

    print()
    print(f"Inserted: {inserted}")
    print(f"Updated:  {updated}")
    print(f"Skipped:  {skipped}")
    print(f"Total patterns in DB now: {len(db.list_all())}")


if __name__ == "__main__":
    main()
