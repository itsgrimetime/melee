"""
Part 13: more regswap patterns from final agent batch.

From Discord mining agents 5-6 (live-range, dead-statement + callee-saved).
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
        id="extern-float-vs-literal-regalloc",
        name="`extern float` named symbol vs literal `1.0f` changes fp register allocation",
        description=(
            "Using `extern float lbl_X = 1.0f;` (a named SDA2 symbol) vs "
            "an inline literal `1.0f` perturbs MWCC's FPR allocation. The "
            "scheduler treats named externs differently for allocation "
            "timing, often shifting which FPR holds intermediates. Avoid "
            "partial-decomp with externed floats unless you're matching "
            "specific asm patterns."
        ),
        root_cause=(
            "Named extern floats load via `lfs fN, lbl@sda21(r2)` from a "
            "specific symbol; literal floats may come from the same .sdata2 "
            "section but the scheduler picks differently. Symbol identity "
            "affects timing-based decisions."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lfs fA", "actual": "lfs fB"},
                description="Same lfs but different FPR destination",
            ),
        ],
        examples=[
            Example(
                function="pik2 sysMath.cpp anti-pattern",
                before=(
                    "// Named extern - perturbs regalloc:\n"
                    "extern f32 lbl_804D98F0;  // = 1.0f\n"
                    "f32 x = some_value * lbl_804D98F0;\n"
                ),
                after=(
                    "// Inline literal - cleaner regalloc:\n"
                    "f32 x = some_value * 1.0f;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Don't extern-declare float constants unless the target "
                    "asm specifically references them by name. Use inline "
                    "literals where possible."
                ),
                success_rate=0.6,
            ),
            Fix(
                description=(
                    "If asm shows the @sda21 reference to a named extern "
                    "float, you must use the extern form. Both produce "
                    "lfs from .sdata2 but the symbol identity affects "
                    "subsequent register choices."
                ),
            ),
        ],
        opcodes=["lfs"],
        categories=["float", "register", "data-layout"],
        provenance=Provenance(),
        notes="Discord 2022-02-14 (altatwo, werewolf.zip, epochflame).",
    ),
    Pattern(
        id="pointer-implicit-vs-explicit-null-check-codegen",
        name="`if (ptr)` vs `if (ptr != NULL)` differ in inline-discard behavior",
        description=(
            "`if (ptr)` and `if (ptr != NULL)` are semantically identical "
            "but MWCC sometimes treats them differently when inlining. The "
            "implicit-bool form can be dropped entirely when the compiler "
            "proves the pointer is non-null at an inline site; the "
            "explicit `!= NULL` comparison forces the check to remain."
        ),
        root_cause=(
            "Implicit ptr-to-bool conversion is more aggressively "
            "optimized than explicit pointer-vs-integer compare. The "
            "compiler can sometimes prove `ptr` is truthy at an inline "
            "site and drop the test; explicit `!= NULL` is harder to "
            "elide."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "cmplwi", "context": "null check at inline site"},
                description="Null check appears in your code but not target",
            ),
        ],
        examples=[
            Example(
                function="werewolf.zip / .cuyler 2024-09-05",
                before=(
                    "// Explicit - check survives inline:\n"
                    "if (eye != NULL) { ... }\n"
                ),
                after=(
                    "// Implicit - check may be dropped:\n"
                    "if (eye) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target lacks a null check that your code emits, "
                    "switch from `if (ptr != NULL)` to `if (ptr)` (or "
                    "vice versa). The implicit form lets MWCC discard the "
                    "check when it can prove non-null."
                ),
                success_rate=0.55,
            ),
        ],
        opcodes=["cmplwi", "beq"],
        categories=["branch", "inline"],
        provenance=Provenance(),
        notes="Discord 2024-09-05 (werewolf.zip, .cuyler).",
    ),
    Pattern(
        id="empty-loop-init-drops-use-count",
        name="`for (; cond; incr)` (omit init) drops counter use-count by 1",
        description=(
            "Removing the init from a for-loop's first slot (when the "
            "variable is already initialized elsewhere) drops its "
            "use-count, which can shove the variable into a "
            "lower-numbered callee-saved register. Useful when two "
            "loop counters are off-by-one in regalloc."
        ),
        root_cause=(
            "MWCC's register allocator considers use-count when picking "
            "callee-saved registers. One fewer use can tip the variable "
            "into a different register slot."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stw r27", "actual": "stw r28"},
                description="Loop counter shifted by one callee-saved register",
            ),
        ],
        examples=[
            Example(
                function="gamemasterplc 2024-09-27",
                before=(
                    "s32 i = 0;\n"
                    "// some code...\n"
                    "for (i = 0; i < len1; i++) {  // 2 uses of i\n"
                    "    /* ... */\n"
                    "}\n"
                ),
                after=(
                    "s32 i = 0;\n"
                    "// some code...\n"
                    "for (; i < len1; i++) {  // 1 use of i — lower reg\n"
                    "    /* ... */\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When a loop counter is one register higher than "
                    "expected, omit the init from the for-loop's first "
                    "slot (and initialize earlier). Drops use-count by 1."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["stw"],
        categories=["loop", "register"],
        provenance=Provenance(),
        notes="Discord 2024-09-27 (gamemasterplc) - 'fixed it entirely'.",
    ),
    Pattern(
        id="dead-comparison-in-empty-if-body",
        name="`if (cond) { (void) other; }` for stubbed-debug `cmpwi` emission",
        description=(
            "To force MWCC to emit a `cmpwi`/branch pair without a real "
            "body (matching stripped-OSReport/assert artifacts), wrap a "
            "discard expression inside an if with a meaningful condition. "
            "The if test emits cmpwi+branch but the body collapses to "
            "nothing — matches retail-with-stubbed-debug-print codegen."
        ),
        root_cause=(
            "Discord debug builds often have `if (cond) OSReport(...)` "
            "blocks. Retail strips the OSReport but the if-test bytes "
            "remain. Reproducing this requires the empty-if-body with "
            "a discard to keep the cmpwi visible."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "cmpwi", "bne skip", "skip:"]},
                description="cmpwi + branch with empty body",
            ),
        ],
        examples=[
            Example(
                function="gamemasterplc + .cuyler 2024-09-27",
                after=(
                    "if (ss.sendbusy == 0) {\n"
                    "    (void) rxth;  // dead body; if-test emits cmpwi\n"
                    "}\n"
                    "// emits: lwz r0, sendbusy(r29); cmpwi r0, 0; bne skip;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has an unexplained `lwz + cmpwi + bne` "
                    "with no apparent body, the source had a debug branch "
                    "stripped. Reproduce with `if (cond) { (void) discard; }` "
                    "or `if (cond) (void) discard;`."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["cmpwi", "lwz", "bne"],
        categories=["branch", "control-flow", "register"],
        provenance=Provenance(),
        notes="Discord 2024-09-27 (gamemasterplc, .cuyler).",
    ),
    Pattern(
        id="arg-decl-order-float-vs-gpr",
        name="Reordering float vs GPR args changes load order at call sites",
        description=(
            "Reordering same-typed args is observable in codegen, but "
            "reordering ACROSS the float/integer boundary (e.g., moving "
            "an `f32 y` between two `s32` args) is functionally "
            "equivalent but changes load order at call sites. MWCC sets "
            "up args in declaration order."
        ),
        root_cause=(
            "Float and GPR arg banks are independent (f1-f13 vs r3-r10), "
            "so reordering across the boundary doesn't change WHICH "
            "register holds what — but it DOES change the order of `lfs` "
            "vs `lwz` instructions at call sites."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lfs+lwz", "actual": "lwz+lfs"},
                description="Float and int loads in different order",
            ),
        ],
        examples=[
            Example(
                function="kiwidev 2022-06-15",
                before=(
                    "// y between - emits: li r3 / lfs f1 / lwz r4\n"
                    "void func(int x, float y, int z);\n"
                ),
                after=(
                    "// y last - emits: li r3 / lwz r4 / lfs f1\n"
                    "void func(int x, int z, float y);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If a call site has lfs/lwz interleave swapped, "
                    "reorder the function's parameters across the "
                    "float/int boundary. Same-type-with-same-type "
                    "reordering is wrong, but cross-type is functionally "
                    "equivalent."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["lfs", "lwz"],
        categories=["calling-conv", "float"],
        provenance=Provenance(),
        related_patterns=["float-args-use-fpr-not-r3"],
        notes="Discord 2022-06-15 (kiwidev).",
    ),
    Pattern(
        id="comma-operator-loop-increment",
        name="`for (...; i++, p++)` fuses increments, scheduled together",
        description=(
            "Using a comma-expression in the for-loop increment slot "
            "(`i++, p++`) generates different codegen than two-statement "
            "(`i++; p++;`) bodies. Comma form lets MWCC schedule both "
            "increments together, pairing them with the loop-back branch. "
            "Matches targets where parallel pointer/counter increments "
            "are laid out side-by-side."
        ),
        root_cause=(
            "Comma-fused increments live in the same basic block as the "
            "loop-back. Separate statements may end up in different "
            "schedule positions. The comma form is cleaner for the "
            "scheduler."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["addi", "addi", "b loop_top"]},
                description="Two adjacent addi increments before branch-back",
            ),
        ],
        examples=[
            Example(
                function="kiwidev 2022-06-15 dynamicBones",
                before=(
                    "for (i = 0; i < N; i++) {\n"
                    "    /* body */\n"
                    "    p++;  // separate statement\n"
                    "}\n"
                ),
                after=(
                    "for (i = 0; i < N; i++, p++) {  // fused\n"
                    "    /* body */\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When loop's parallel increments are scheduled "
                    "together in target asm, use comma-operator in the "
                    "for-loop's increment slot: `for (...; i++, p++)`."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["addi"],
        categories=["loop", "control-flow"],
        provenance=Provenance(),
        notes="Discord 2022-06-15 (kiwidev).",
    ),
    Pattern(
        id="assignment-in-while-condition",
        name="`while ((node = node->next))` folds load into loop test",
        description=(
            "Assignment in the while-condition `while ((node = node->next))` "
            "folds the load of `next` into the loop's entry test. The "
            "first lwz happens before the conditional branch, with no "
            "separate load from `this`. Matches targets where the loop "
            "preheader loads `m_next` first."
        ),
        root_cause=(
            "Inline assignment-in-test creates a single basic block for "
            "the load+test+advance. Two-statement form (test first, "
            "advance in body) requires two separate loads."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz rN,m_next(rY)", "cmplwi", "beq exit"]},
                description="Single load+test pattern at loop entry",
            ),
        ],
        examples=[
            Example(
                function="seekyct CNode::calcNextCount 2021-12-29",
                before=(
                    "// Two loads at top - wrong:\n"
                    "while (node->m_next) {\n"
                    "    node = node->m_next;\n"
                    "    ++i;\n"
                    "}\n"
                ),
                after=(
                    "// Folded - matches:\n"
                    "while ((node = node->m_next)) {\n"
                    "    ++i;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When loop's first lwz advances the pointer (rather "
                    "than loading from `this`), use assignment-in-while-"
                    "condition: `while ((p = p->next))`."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lwz", "cmplwi"],
        categories=["loop", "branch", "struct"],
        provenance=Provenance(),
        notes="Discord 2021-12-29 (seekyct).",
    ),
    Pattern(
        id="void-cast-discard-vs-bare-expr",
        name="`(void) buf;` cast-discard for cleaner regswap intent",
        description=(
            "`(void) buf;` is a more explicit form of the dead-statement "
            "trick (vs bare `buf;` or `!buf;`). Same behavior: reduces "
            "register pressure on an unused parameter. Use the explicit "
            "cast form when a C purist's review will see the code."
        ),
        root_cause=(
            "Both `(void) buf;` and `buf;` evaluate the expression and "
            "discard. The cast form documents intent. Functionally "
            "identical for register allocation."
        ),
        signals=[],
        examples=[
            Example(
                function=".cuyler 2024-09-27",
                after=(
                    "void f(s32 a, void* buf, s32 c)\n"
                    "{\n"
                    "    (void) buf;  // never read; lowers use-count\n"
                    "    /* uses a and c only */\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Prefer `(void) var;` over bare `var;` for "
                    "code-review clarity when discarding an unused "
                    "parameter for regswap purposes."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=[],
        categories=["register"],
        provenance=Provenance(),
        related_patterns=["discard-expression-statement-regalloc"],
        notes="Discord 2024-09-27 (.cuyler).",
    ),
    # Patterns from agent 2 not in part 12
    Pattern(
        id="noprop-opt-flag-restores-mr",
        name="`-opt l=2,peep,schedule,noprop` (disable propagation) brings back `mr`",
        description=(
            "MWCC's constant-propagation pass sometimes collapses an `mr` "
            "into the propagated value. Setting `-opt level=2,peep,"
            "schedule,noprop` (disabling propagation) brings the `mr` "
            "back. Useful when one specific function in a file needs "
            "propagation off without touching peephole or scheduling."
        ),
        root_cause=(
            "Constant propagation folds known values directly into "
            "uses, removing the move that would otherwise materialize "
            "them. Disabling propagation per-function (via pragma) "
            "restores the move."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "mr", "actual": "<missing>"},
                description="Register move eliminated by propagation",
            ),
        ],
        examples=[
            Example(
                function="MP1 fix",
                after=(
                    "#pragma opt_level=2 peep,schedule,noprop\n"
                    "// function that needs prop disabled\n"
                    "#pragma opt_level\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When `mr` is collapsed by propagation, set opt level "
                    "flags to disable just propagation: `noprop`. Keeps "
                    "peephole and scheduling enabled."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["mr"],
        categories=["register"],
        provenance=Provenance(),
        notes="Discord 2022-03-27 (encounter, MP1).",
    ),
    Pattern(
        id="manual-loop-unroll-with-O4s-for-stmw",
        name="`-O4,s` + manual loop unroll to force `stmw` emission",
        description=(
            "To force `stmw` emission in a function that doesn't naturally "
            "generate one, manually unroll the loop AND set `-O4,s` for "
            "that translation unit. `-O4,s` alone usually emits `stmw` but "
            "mis-codegens loops; manual unrolling sidesteps that, getting "
            "`stmw` without breaking the loop body."
        ),
        root_cause=(
            "`-O4,s` (space optimization) emits `stmw`/`lmw` for compact "
            "prologue/epilogue. But it also mis-schedules loops. Manual "
            "unrolling removes the loop construct that triggers the "
            "mis-codegen."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stmw r27", "actual": "stw r27,r28,r29..."},
                description="Wanted stmw but got individual stw",
            ),
        ],
        examples=[
            Example(
                function="estexnt 2024-06-10 fix",
                context="Used -O4,s flag for the TU + manually unrolled the inner loop",
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target uses stmw/lmw and you can't get it, try "
                    "`-O4,s` for the TU + manually unroll any loops in "
                    "the function. -O4,s alone breaks loops."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["stmw", "lmw"],
        categories=["stack", "loop"],
        provenance=Provenance(),
        notes="Discord 2024-06-10 (estexnt).",
    ),
    Pattern(
        id="ternary-replaces-if-else-for-regswap",
        name="Rewrite if/else as ternary `cond ? a : b` to fix single residual regswap",
        description=(
            "Rewriting an if/else (or if-return X / return Y pair) as a "
            "single `cond ? a : b` ternary frequently resolves a "
            "residual register swap. Mentioned across years by multiple "
            "decomp authors. Acts opposite to ternary-float-zero-rewrite: "
            "when target asm shows a clean conditional move/select, use "
            "the ternary form."
        ),
        root_cause=(
            "Ternary collapses two value-producing paths into one "
            "expression with a predictable register destination. If/else "
            "may split paths into separate register slots. The compiler's "
            "pattern matcher picks fsel/cmov-like sequences from ternary "
            "more reliably."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "any", "actual": "any", "context": "branch shape differs"},
                description="Branch layout differs from target",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "if (cond) {\n"
                    "    result = a;\n"
                    "} else {\n"
                    "    result = b;\n"
                    "}\n"
                ),
                after=(
                    "result = cond ? a : b;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Try rewriting if/else as ternary when stuck on a "
                    "regswap. Operates differently from the float-zero "
                    "case: this is for non-float or no-zero ternaries "
                    "where the ternary form matches better."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=[],
        categories=["control-flow", "register"],
        provenance=Provenance(),
        related_patterns=["ternary-vs-if-else", "ternary-float-zero-rewrite-as-if-else"],
        notes="Discord 2023-10-01, 2025-05-18 (.cuyler, chippy).",
    ),
    Pattern(
        id="srawi-vs-srwi-via-int-cast",
        name="`(int)` cast on shift operand forces `srawi` (arith) over `srwi` (logical)",
        description=(
            "Wrapping the operand of a right shift in `(int)` forces "
            "MWCC to emit `srawi` (arithmetic, sign-preserving) instead "
            "of `srwi` (logical, zero-fill). Affects regswaps indirectly "
            "by changing the shift's downstream register flow. Distinct "
            "from `srawi-signed-shift-right` because this is about the "
            "cast forcing the choice, not the source type."
        ),
        root_cause=(
            "Even when the operand is already `s32`, the explicit `(int)` "
            "cast can tip MWCC's selector toward srawi. Especially in "
            "macros where the underlying type is unclear."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "srawi", "actual": "srwi"},
                description="Arithmetic vs logical right shift",
            ),
        ],
        examples=[
            Example(
                function="rainchus 2024-04-24",
                before=(
                    "value >> N\n"
                    "// May emit srwi if value is u32\n"
                ),
                after=(
                    "(int) value >> N\n"
                    "// Forces srawi via explicit cast\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Add `(int)` (or `(s32)`) cast around a right-shift "
                    "operand to force `srawi` over `srwi`. Useful in "
                    "macros where the underlying type is unclear."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["srawi", "srwi"],
        categories=["type", "bitfield"],
        provenance=Provenance(),
        related_patterns=["srawi-signed-shift-right"],
        notes="Discord 2024-04-24 (rainchus).",
    ),
    Pattern(
        id="remask-bitfield-at-single-use",
        name="Re-apply bitfield mask at only ONE use to fix regswap (fakematch)",
        description=(
            "For a struct bitfield (`size`) referenced multiple times, "
            "re-applying the mask at only ONE of the use sites fixes a "
            "regswap. Pattern: `if (foo->size > N) { ... fn(foo->size & "
            "MASK); ... }`. Acknowledged fakematch but works."
        ),
        root_cause=(
            "Extra `rlwinm`/`clrlwi` at one site rebalances callee-saved "
            "register usage by adding an instruction that consumes a "
            "register at a specific point in the schedule."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "rlwinm", "context": "redundant mask"},
                description="Extra mask instruction at one use site",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "if (foo->size > N) {\n"
                    "    something(foo->size);\n"
                    "    other(foo->size);\n"
                    "}\n"
                ),
                after=(
                    "if (foo->size > N) {\n"
                    "    something(foo->size & MASK);  // redundant mask\n"
                    "    other(foo->size);\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Last resort for residual regswaps near bitfield "
                    "accesses: re-apply the mask at ONE use site only. "
                    "Adds rlwinm but rebalances regalloc."
                ),
                success_rate=0.4,
            ),
        ],
        opcodes=["rlwinm", "clrlwi"],
        categories=["bitfield", "register"],
        provenance=Provenance(),
        notes="Discord 2025-11-03 (.cuyler) - 'fakematch for sure but whatever'.",
    ),
    Pattern(
        id="unused-stack-var-debug-retail-toggle",
        name="`s32 unused_stack;` local for retail-vs-debug stack frame match",
        description=(
            "Declaring an `s32 unused_stack;` (or similar) local with no "
            "other use can be the difference between matching debug vs "
            "retail builds of the same SDK function. Indicates O0 "
            "(debug) emitted an extra slot that O4 (retail) optimized "
            "out. Common in EXI/AMC code."
        ),
        root_cause=(
            "Some SDK functions have stack slots reserved for variables "
            "that exist only in debug builds. Retail builds emit the "
            "same prologue (same frame size) but never reference the "
            "slot. To match retail, declare the local but never use it."
        ),
        signals=[
            Signal(
                type="offset_delta",
                data={"register": "r1", "delta": 4},
                description="Frame is 4 bytes larger than the variables suggest",
            ),
        ],
        examples=[
            Example(
                function="EXI2_* SDK functions",
                after=(
                    "s32 EXI2_func(args)\n"
                    "{\n"
                    "    s32 unused_stack;  // debug-only slot\n"
                    "    /* function body never references unused_stack */\n"
                    "    return result;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If stack frame is 4-8 bytes larger than your locals "
                    "would justify, add `s32 unused_stack;` (or similar) "
                    "local. Compiler reserves the slot in retail too."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["stwu"],
        categories=["stack"],
        provenance=Provenance(),
        notes="Discord 2024-02-03 (revosucks).",
    ),
    Pattern(
        id="cast-to-s64-or-ulong-mask-for-sqrt-residue",
        name="`(s64)` cast or `& 0xFFFFFFFFFFFFFFFF` to fix sqrt-residue regswap",
        description=(
            "Casting an intermediate to `(s64)` or applying `& 0xFFFFFFFFFFFFFFFF` "
            "(no-op AND) around a sqrtf/inline-arithmetic result fixes a "
            "regswap involving an inline that has a long-long step. "
            "Traditional IDO 64-bit-AND trick but also works in MWCC for "
            "inline-residue regswaps."
        ),
        root_cause=(
            "The 64-bit mask forces MWCC to materialize the value as a "
            "wider type briefly, perturbing the integer-pipeline pass "
            "that follows the float computation. Changes register "
            "lifetime around the sqrt-residue."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "any", "actual": "any", "context": "around sqrt inline"},
                description="Regswap near a Newton-Raphson sqrt inline",
            ),
        ],
        examples=[
            Example(
                function="generic sqrt regswap",
                after=(
                    "// Either form fixes residue regswap:\n"
                    "result = (s64) sqrt_result;\n"
                    "// or:\n"
                    "result = sqrt_result & 0xFFFFFFFFFFFFFFFF;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "For regswaps in code following an inlined sqrt, try "
                    "casting the result through `(s64)` or no-op AND with "
                    "0xFFFFFFFFFFFFFFFF. Forces a 64-bit intermediate."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=[],
        categories=["register", "type", "float"],
        provenance=Provenance(),
        notes="Discord 2022-08-14 (jordan, altafen) - permuter-discovered.",
    ),
]


def main():
    db_path = DEFAULT_DB_PATH
    conn = init_db(db_path)
    db = PatternDB(conn)

    inserted = 0
    updated = 0

    for pattern in PATTERNS:
        existing = db.get(pattern.id)
        if existing is not None:
            print(f"  EXISTS: {pattern.id} — deleting and re-inserting")
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
    print(f"Total patterns in DB now: {len(db.list_all())}")


if __name__ == "__main__":
    main()
