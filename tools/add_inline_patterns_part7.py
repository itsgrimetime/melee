"""
Part 7: struct/array, switch/control-flow, and calling-convention patterns
from three parallel agent surveys.
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
    # ---------- struct / array ----------
    Pattern(
        id="u8-cast-base-plus-offset-store",
        name="`((u8*) &x)[N] = ...` for offset-store through opaque region",
        description=(
            "Writing through an opaque struct region by casting to `u8*` "
            "and indexing forces `addi` of base+offset then `stb`/`stw`, "
            "bypassing struct-field offset folding. Useful when the target's "
            "asm shows separate addi/store but you've already typed the field."
        ),
        root_cause=(
            "Typed struct field access folds the offset into the load/store "
            "displacement: `stw rN, OFFSET(rPTR)`. A `u8*` cast with explicit "
            "index forces `addi` to compute the address first, then a "
            "separate store with displacement 0."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["addi", "stb"]},
                description="Separate address calc + store vs folded displacement",
            ),
        ],
        examples=[
            Example(
                function="gmregclear.c, ft_0D31.c",
                before=(
                    "// Typed access — folded offset:\n"
                    "cam_gobj->gxlink_prios.field = 0;\n"
                    "// emits: stw r0, OFFSET(r3)\n"
                ),
                after=(
                    "// u8-cast — separate address calc:\n"
                    "((u8*) &cam_gobj->gxlink_prios)[0] = 0;\n"
                    "// emits: addi r4, r3, OFFSET ; stb r0, 0(r4)\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows addi+stb/stw pair for a struct field "
                    "write, cast through `u8*` and index. Useful for opaque "
                    "regions or pre-typedef code."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["addi", "stb", "stw"],
        categories=["struct", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="gmregclear cam_gobj writes"),
            ],
        ),
    ),
    Pattern(
        id="negative-array-index-shift-loop",
        name="Negative array index for backward shift loop",
        description=(
            "Insertion-sort or list-compaction code shifts elements via "
            "`array[i] = array[i-1]; array[i-1] = array[i-2]; ...`. With "
            "explicit negative indices, MWCC emits `lwz/stw rN, -K(rPTR)` "
            "with negative immediates instead of post-decrement loads. "
            "Unrolling factor (e.g., 8) emerges naturally."
        ),
        root_cause=(
            "Negative immediates fit in the 16-bit signed offset of lwz/stw. "
            "MWCC unrolls the explicit-index form because each iteration's "
            "addressing is constant relative to the iterator. Post-increment "
            "via pointer would emit different addressing modes."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz -4", "stw 0", "lwz -8", "stw -4"]},
                description="Negative immediate loads, sequential stores",
            ),
        ],
        examples=[
            Example(
                function="lbaudio_ax.c shift loop",
                after=(
                    "// Explicit negative indices, manually unrolled by 8:\n"
                    "while (n > 0) {\n"
                    "    shift_ptr[ 0] = shift_ptr[-1];\n"
                    "    shift_ptr[-1] = shift_ptr[-2];\n"
                    "    shift_ptr[-2] = shift_ptr[-3];\n"
                    "    shift_ptr[-3] = shift_ptr[-4];\n"
                    "    shift_ptr[-4] = shift_ptr[-5];\n"
                    "    shift_ptr[-5] = shift_ptr[-6];\n"
                    "    shift_ptr[-6] = shift_ptr[-7];\n"
                    "    shift_ptr[-7] = shift_ptr[-8];\n"
                    "    shift_ptr -= 8;\n"
                    "    n -= 8;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows lwz/stw with negative immediates in a "
                    "shift-loop pattern, use explicit `arr[-1]`, `arr[-2]` "
                    "indexing rather than `*--ptr` post-decrement. The "
                    "unrolling factor matches the visible repetition."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lwz", "stw"],
        categories=["struct", "loop", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbaudio_ax shift loop"),
            ],
        ),
    ),
    Pattern(
        id="memcpy-sizeof-array-type",
        name="`memcpy(dst, src, sizeof(f32[N]))` vs struct assignment",
        description=(
            "Copying a raw float triple via `memcpy(dst, src, sizeof(f32[3]))` "
            "compiles to inlined `lwz`/`stw` triples (MWCC knows the constant "
            "size). Using `*(Vec3*) dst = *(Vec3*) src;` for the same triple "
            "goes through f64 pairs because Vec3 has FP members. Choose form "
            "based on what target's asm shows."
        ),
        root_cause=(
            "`memcpy` with constant size is inlined as word stores ignoring "
            "type. Struct assignment with FP members uses fp registers and "
            "may interleave f64 pairs. Different code paths inside MWCC."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz/stw", "actual": "lfd/stfd"},
                description="Word-copy vs FP-pair copy",
            ),
        ],
        examples=[
            Example(
                function="pobj.c float triple copy",
                after=(
                    "// memcpy form — emits 3x lwz/stw word copies:\n"
                    "memcpy(dst, src, sizeof(f32[3]));\n"
                ),
                before=(
                    "// Struct assignment — may emit lfd/stfd pairs:\n"
                    "*(Vec3*) dst = *(Vec3*) src;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target copies 12 bytes via 3 word-sized lwz/stw, use "
                    "`memcpy(dst, src, sizeof(f32[3]))`. If it uses f64 lfd/"
                    "stfd, use struct assignment `*(Vec3*) dst = *(Vec3*) src;`."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lwz", "stw", "lfd", "stfd"],
        categories=["struct", "float", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="pobj float triple copy"),
            ],
        ),
        related_patterns=["struct-field-copy", "copying-structs-field-by-field"],
    ),
    Pattern(
        id="multidim-array-vs-flat-index",
        name="`arr[i][j]` vs `arr[i*N+j]` — different multiply-elimination",
        description=(
            "True 2D `[i][j]` indexing generates `mulli` for row stride + "
            "`add`. Flat indexing with explicit `i*N+j` may CSE the multiply "
            "if MWCC sees the pattern. MWCC picks differently based on inner "
            "struct size (>16 bytes triggers different code paths)."
        ),
        root_cause=(
            "C semantics: `arr[i][j]` for `T arr[M][N]` decays to "
            "`*(arr + i*N + j)` with full sizeof(T)*N stride. MWCC inserts "
            "`mulli rX, i, sizeof(T)*N` per access. Manual flat indexing "
            "lets you control whether the multiply is hoisted or per-access."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "mulli", "actual": "<missing>"},
                description="Target uses mulli per index; your code hoisted it",
            ),
        ],
        examples=[
            Example(
                function="cm/camera.c 2D arrays",
                after=(
                    "// True 2D — explicit mulli per access:\n"
                    "arr._1B0[i][j] = arr._B0[i][j];\n"
                    "// Flat — multiply may be CSEd:\n"
                    "arr._1B0[i * N + j] = arr._B0[i * N + j];\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `mulli` for stride at each access, use "
                    "true `[i][j]` 2D indexing. When target hoists the "
                    "multiply outside the loop, use flat `[i*N+j]` form."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["mulli", "add"],
        categories=["struct", "loop", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="camera 2D arrays"),
            ],
        ),
    ),
    Pattern(
        id="array-size-signed-cast-loop-bound",
        name="`(signed) ARRAY_SIZE(...)` cast forces `cmpw` signed loop bound",
        description=(
            "`ARRAY_SIZE(arr)` returns `size_t` (unsigned). When used as a "
            "loop bound, MWCC emits `cmplw` (unsigned). Adding `(signed)` or "
            "`(s32)` cast forces `cmpw` (signed) instead. Affects which "
            "branch instructions (`bge`/`blt` vs `bgeu`/`bltu`) get emitted."
        ),
        root_cause=(
            "Comparison signedness follows the wider type's signedness in "
            "C's usual arithmetic conversions. `size_t` (unsigned) wins over "
            "`int i` (signed). Casting the ARRAY_SIZE result to signed forces "
            "signed comparison."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "cmpw", "actual": "cmplw"},
                description="Signed vs unsigned loop bound compare",
            ),
        ],
        examples=[
            Example(
                function="ftaction.c, ft_07C6.c, ftanim.c",
                before=(
                    "// Unsigned compare (cmplw):\n"
                    "for (i = 0; i < ARRAY_SIZE(fp->x1614); i++) { ... }\n"
                ),
                after=(
                    "// Signed compare (cmpw):\n"
                    "for (i = 0; i < (signed) ARRAY_SIZE(fp->x1614); i++) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target shows `cmpw` (signed) for an ARRAY_SIZE loop "
                    "bound, add `(signed)` or `(s32)` cast. Without it MWCC "
                    "emits `cmplw` (unsigned) because size_t wins."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["cmpw", "cmplw"],
        categories=["loop", "type"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftaction loop bound"),
            ],
        ),
        related_patterns=["cmplwi-vs-cmpwi-implies-pointer-type"],
    ),
    Pattern(
        id="expression-in-comparison-vs-temp-load",
        name="Inline expression in comparison preserves r3; temp vars cause `mr` shuffles",
        description=(
            "Comparing a function-call's result directly preserves the "
            "primary register (r3) and emits a clean `cmpw r0, r3`. "
            "Introducing temporary variables like `char c = GetData()->field; "
            "char t = terminator; if (c == t)` adds `mr`/`lbz` reshuffles "
            "that may flip the cmpw operand order."
        ),
        root_cause=(
            "Direct comparison keeps the function-call result in its return "
            "register through the compare. Temp variables force MWCC to "
            "spill to named slots and reload, changing register usage."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "mr", "context": "after temp load"},
                description="Extra register move from temp spill",
            ),
        ],
        examples=[
            Example(
                function="mnname.c first-character check",
                before=(
                    "// Temp vars - register shuffles:\n"
                    "char c = GetPersistentNameData(slot)->namedata[0];\n"
                    "char t = mnName_StringTerminator;\n"
                    "if (c == t) { ... }\n"
                ),
                after=(
                    "// Inline expression - clean r3 compare:\n"
                    "if (GetPersistentNameData(slot)->namedata[0] == mnName_StringTerminator)\n"
                    "{\n"
                    "    /* ... */\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Inline the function call directly into the comparison "
                    "rather than spilling to a temp. The function-call result "
                    "stays in r3 through the cmpw, eliminating mr shuffles."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["mr", "cmpw"],
        categories=["register", "branch"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnname IsNameUnique"),
            ],
        ),
        related_patterns=["comparison-operand-order-load-order"],
    ),
    # ---------- switch / control-flow ----------
    Pattern(
        id="jtbl-t-fake-typedef-for-dense-switch",
        name="`jtbl_t` placeholder typedef for dense-switch jump table matching",
        description=(
            "Dense switches (<32 contiguous cases near 0) compile to jump "
            "tables: `cmplwi r3, N` + `bgt default` + `slwi r0, r3, 2` + "
            "`lwz r0, jtbl@l(r0)` + `mtctr r0` + `bctrl`. To match, declare "
            "a `jtbl_t name_ADDR = { fn0, fn1, ... };` placeholder pointing "
            "at the case bodies, then use a normal `switch` in C."
        ),
        root_cause=(
            "MWCC emits a contiguous table of function-or-block addresses "
            "in .rodata for the switch. The decompilation needs that table "
            "declared in the same shape. Standard C `switch` compiles to "
            "the same form when cases are dense and contiguous."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["cmplwi", "bgt", "slwi", "lwz", "mtctr", "bctr"]},
                description="Classic jump-table dispatch sequence",
            ),
        ],
        examples=[
            Example(
                function="ftKb_Init.c switch",
                after=(
                    "// In the .c or a static.h:\n"
                    "jtbl_t name_ADDR = { fn0, fn1, fn2, fn3, ... };\n"
                    "\n"
                    "// Use:\n"
                    "switch (i) {\n"
                    "    case 0: fn0(); break;\n"
                    "    case 1: fn1(); break;\n"
                    "    /* ... */\n"
                    "    default: dflt();\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When asm contains `mtctr` + `bctr`/`bctrl` after a "
                    "table load, the source used a dense switch. Declare a "
                    "`jtbl_t` placeholder at the address from symbols.txt "
                    "and write the switch normally."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["cmplwi", "bgt", "slwi", "lwz", "mtctr", "bctr"],
        categories=["control-flow", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="ftKb_Init dispatch"),
            ],
        ),
    ),
    Pattern(
        id="sparse-cases-if-else-cascade",
        name="Sparse switch cases compile to nested if/else cascade (not jump table)",
        description=(
            "When switch cases are sparse or non-contiguous (large gaps, "
            "non-zero based), MWCC emits an if/else cascade rather than a "
            "jump table. m2c sees this as `if (k != X) { if (k < X) { ... } }` "
            "tree. Rewrite as an actual `switch` in C — MWCC still emits "
            "the cascade form when cases are sparse, but the source is "
            "readable."
        ),
        root_cause=(
            "Jump tables require contiguous (or near-contiguous) integer "
            "case values. Sparse cases would waste table space. MWCC's "
            "threshold appears to be roughly 32 contiguous values; below "
            "that, or with gaps, it falls back to comparing each case."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["cmpwi", "beq", "cmpwi", "beq"]},
                description="Repeated compare+branch per case (no jump table)",
            ),
        ],
        examples=[
            Example(
                function="sparse switch",
                before=(
                    "// m2c output - deep nested ifs:\n"
                    "if (k != 0x1C) {\n"
                    "    if (k < 0x1C) {\n"
                    "        /* ... */\n"
                    "    }\n"
                    "}\n"
                ),
                after=(
                    "// Source switch - same asm:\n"
                    "switch (k) {\n"
                    "    case 0x4A:\n"
                    "    case 0x4B:\n"
                    "        code_B;\n"
                    "        break;\n"
                    "    case 0x8A:\n"
                    "        code_A;\n"
                    "        break;\n"
                    "    case 0x1C:\n"
                    "        code_C;\n"
                    "        break;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When m2c shows nested ifs comparing the same variable "
                    "to constants, rewrite as a sparse `switch`. The asm "
                    "stays the same but source becomes maintainable."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["cmpwi", "beq", "bne"],
        categories=["control-flow", "branch"],
        provenance=Provenance(),
    ),
    Pattern(
        id="switch-cast-s32-forces-cmpwi-signed",
        name="`switch ((s32) u8_value)` forces `cmpwi` (signed) over `cmplwi`",
        description=(
            "A `switch ((s32) arg->u8_field)` cast forces MWCC to use "
            "`cmpwi` (signed) for case comparisons. Without the cast, "
            "switch on a u8 lvalue uses `cmplwi` (unsigned). Affects which "
            "branch direction the default falls through."
        ),
        root_cause=(
            "Switch comparisons follow the controlling expression's signedness. "
            "u8 is unsigned, so without the cast MWCC uses cmplwi. The `(s32)` "
            "cast widens to signed int."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "cmpwi", "actual": "cmplwi"},
                description="Signed vs unsigned switch case compare",
            ),
        ],
        examples=[
            Example(
                function="gmregclear.c:740",
                before=(
                    "// u8 directly — emits cmplwi:\n"
                    "switch (arg1->x0.x9) { case 1: ...; case 2: ...; }\n"
                ),
                after=(
                    "// (s32) cast — emits cmpwi:\n"
                    "switch ((s32) arg1->x0.x9) { case 1: ...; case 2: ...; }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target uses `cmpwi` (signed) for switch cases on a "
                    "u8 field, cast to `(s32)` in the switch expression."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["cmpwi", "cmplwi"],
        categories=["control-flow", "type"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="gmregclear switch"),
            ],
        ),
    ),
    Pattern(
        id="assert-failure-trailing-while1",
        name="`while (1) {}` after assert/OSReport to prevent dead-code removal",
        description=(
            "After `OSReport` + `__assert` (or similar unreachable terminator), "
            "C source needs a `while (1) {}` self-loop to keep MWCC from "
            "eliminating the post-call code. This compiles to a `b .L_self` "
            "trailing the function — present in the asm but unused at runtime."
        ),
        root_cause=(
            "Functions ending in `__assert` are noreturn semantically but C "
            "compiler doesn't always know that. Without a sentinel, MWCC may "
            "elide the trailing `b`. With `while (1) {}`, the back-edge "
            "creates a definite reach into itself, blocking elimination."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["bl __assert", "b self"]},
                description="Self-loop branch trailing an assert call",
            ),
        ],
        examples=[
            Example(
                function="ground.c (multiple)",
                context="ground.c:790, 1525, 1545 — sentinel after assert",
                after=(
                    "void func(void)\n"
                    "{\n"
                    "    /* normal logic with returns */\n"
                    "\n"
                    "    OSReport(\"Bad state!\\n\");\n"
                    "    __assert(\"file.c\", 123, \"cond\");\n"
                    "    while (1) {}  // sentinel - keeps trailing b in asm\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When function ends with `__assert` and target asm has a "
                    "trailing `b` to itself, add `while (1) {}` after the "
                    "assert call. Prevents the compiler from removing the "
                    "self-branch."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["b"],
        categories=["control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="Ground_801C0FBC"),
            ],
        ),
    ),
    Pattern(
        id="do-while-vs-while-trailing-test",
        name="`do { } while (cond)` for fall-through entry; `while (cond) { }` adds test branch",
        description=(
            "`do { ... } while (cond)` falls through directly into the loop "
            "body, with a `bne`/`beq` back-branch at the bottom. "
            "`while (cond) { ... }` adds an entry-test branch at the top, "
            "plus the back-branch. Choose `do-while` when target asm shows "
            "no entry test (straight fall-through into the body)."
        ),
        root_cause=(
            "`do-while` guarantees at least one iteration, so MWCC doesn't "
            "emit an entry check. `while` requires the condition to be "
            "tested before the first iteration. Different control-flow "
            "shapes produce different asm shapes."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["...body...", "bne loop_top"]},
                description="No entry-test, just body + back-branch",
            ),
        ],
        examples=[
            Example(
                function="lb_00CE.c powf Taylor series",
                after=(
                    "// do-while form:\n"
                    "do {\n"
                    "    result *= base;\n"
                    "    i--;\n"
                    "} while (i > 0);\n"
                    "// asm: body, then `cmpwi r,0; bne loop_top`\n"
                ),
                before=(
                    "// while form:\n"
                    "while (i > 0) {\n"
                    "    result *= base;\n"
                    "    i--;\n"
                    "}\n"
                    "// asm: `b test; loop_top: body; test: cmpwi r,0; bne loop_top`\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target's loop has no entry-test branch (loop body "
                    "starts at function fall-through), use `do { ... } "
                    "while (cond)`. When there's a test branch at top, use "
                    "`while (cond) { ... }`."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["bne", "beq", "b"],
        categories=["loop", "control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="powf/expf Taylor series"),
            ],
        ),
    ),
    Pattern(
        id="early-goto-cleanup-vs-inline-return",
        name="`goto return_zero` for shared epilogue vs early-`return 0`",
        description=(
            "When the asm shows a `b` to a labeled basic block at function "
            "tail that loads 0 into r3, the source likely uses `goto "
            "return_zero;` and a label, NOT `return 0;` inline. Inline early "
            "returns create separate epilogues; goto-to-shared-tail unifies "
            "them."
        ),
        root_cause=(
            "Inline `return 0;` from a deeply nested if would create a "
            "separate `li r3, 0; blr` or branch-to-epilogue. A shared "
            "`return_zero:` label allows a single zero-load at the function "
            "tail. The choice affects basic-block ordering."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["b shared_tail", "...", "li r3, 0", "blr"]},
                description="Forward branch to a shared zero-return tail",
            ),
        ],
        examples=[
            Example(
                function="lb_00CE.c powi",
                after=(
                    "f64 powi(f64 base, int exponent)\n"
                    "{\n"
                    "    f64 result = 1.0;\n"
                    "    if (exponent < 0) {\n"
                    "        goto return_zero;  // shared tail\n"
                    "    }\n"
                    "    /* compute result */\n"
                    "    return result;\n"
                    "\n"
                    "return_zero:\n"
                    "    return 0;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When asm has a forward `b` to a labeled epilogue that "
                    "returns zero, use `goto return_zero;` from the early "
                    "exit and a `return_zero: return 0;` tail. Don't inline "
                    "the early `return 0;`."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["b", "blr", "li"],
        categories=["control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lb_00CE powi"),
            ],
        ),
        related_patterns=["static-inline-m2c-goto-preservation"],
    ),
    # ---------- calling convention ----------
    Pattern(
        id="variadic-lis-r0-fixed-param-count",
        name="`lis r0, 0xN00` in variadic prologue encodes fixed-param count",
        description=(
            "MWCC emits `lis r0, 0xN00` at the prologue of a variadic "
            "function, where N = (initial_fixed_params + 1) * 0x100. This "
            "constant is used by va_start to compute the offset to the "
            "first variadic argument. If your fixed-parameter count is "
            "wrong, this constant will be off."
        ),
        root_cause=(
            "PPC variadic ABI: va_start needs to know how many fixed "
            "parameters preceded the `...`. MWCC bakes this into the "
            "prologue as a constant. Each additional fixed param shifts "
            "the constant by 0x100."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lis r0, 0x300", "actual": "lis r0, 0x200"},
                description="Wrong fixed-param count in variadic prologue",
            ),
        ],
        examples=[
            Example(
                function="lbArchive_80016AF0",
                after=(
                    "// 2 fixed + 1 = 3 -> 0x300\n"
                    "void f(HSD_Archive* a, void** file, ...)\n"
                    "{\n"
                    "    va_list args;\n"
                    "    va_start(args, file);\n"
                    "    // ...\n"
                    "}\n"
                    "// emits: lis r0, 0x300 in prologue\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When variadic prologue's `lis r0, 0xN00` is wrong, "
                    "adjust the fixed-parameter count. Formula: "
                    "N = (count_before_ellipsis + 1) * 0x100."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["lis"],
        categories=["calling-conv"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbArchive_80016AF0"),
            ],
        ),
        related_patterns=["variadic-function-va-list-offset"],
    ),
    Pattern(
        id="va-arg-float-pointer-indirection",
        name="`va_arg(vlist, f32)` is broken in MWCC — use `*va_arg(vlist, f32*)`",
        description=(
            "MWCC's `va_arg(vlist, f32)` does not correctly advance the "
            "vlist pointer for float arguments. The working form is "
            "`*va_arg(vlist, f32*)` (pointer indirection). The vlist must "
            "have been stored as pointers, not by-value floats."
        ),
        root_cause=(
            "MWCC bug or quirk in its va_arg expansion for float types. "
            "The workaround uses pointer-typed va_arg, then dereferences. "
            "Effectively bypasses the broken float-advance code."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz + lfs", "actual": "<wrong addressing>"},
                description="Two-step pointer-then-value load vs broken direct float load",
            ),
        ],
        examples=[
            Example(
                function="efsync.c, eflib.c variadic extractors",
                before=(
                    "// Broken — wrong vlist advance:\n"
                    "f32 val = va_arg(vlist, f32);\n"
                ),
                after=(
                    "// Working — pointer indirection:\n"
                    "f32 val = *va_arg(vlist, f32*);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Always extract floats from va_list as "
                    "`*va_arg(vlist, f32*)`. Never use plain "
                    "`va_arg(vlist, f32)` — it is broken in MWCC."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["lwz", "lfs"],
        categories=["calling-conv", "float"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="efsync float extraction"),
            ],
        ),
        related_patterns=[
            "variadic-function-va-list-offset",
            "crclr-6-vs-crset-6-variadic-float-marker",
        ],
    ),
    Pattern(
        id="tail-call-b-not-blr",
        name="Tail call emits `b target` (no LR save/restore)",
        description=(
            "When a wrapper function's last action is to call another "
            "function with matching signature/stack, MWCC may emit a tail "
            "call: `b target` instead of `bl target; blr`. The wrapper has "
            "no stack frame and no LR save/restore. Match by keeping "
            "types/signature aligned with the inner call."
        ),
        root_cause=(
            "MWCC recognizes tail-call opportunities for same-signature, "
            "no-extra-work calls. The compiler replaces `bl + blr` with a "
            "direct `b`, eliminating the prologue/epilogue."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "b target", "actual": "bl target + blr"},
                description="Tail-call branch vs call+return",
            ),
        ],
        examples=[
            Example(
                function="generic wrapper",
                after=(
                    "// Tail call - emits `b helper`, no stack frame:\n"
                    "void wrapper(int a, int b)\n"
                    "{\n"
                    "    return helper(a, b);  // direct return of call\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target ends in `b target` and has no prologue/"
                    "epilogue, the source is `return helper(args);` with "
                    "matching signature. Don't add stack frame; don't "
                    "decompose into `result = helper(args); return result;`."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["b", "bl", "blr"],
        categories=["calling-conv"],
        provenance=Provenance(),
    ),
    Pattern(
        id="s64-u64-return-r3-r4-pair",
        name="64-bit return value uses r3+r4 register pair",
        description=(
            "Functions returning `s64`/`u64` (or any 8-byte type) put the "
            "result in r3 (high word) + r4 (low word). Storing into an "
            "`s64` local generates `stw r3, X(r1); stw r4, X+4(r1)`. If "
            "you declared the local as `u32`, you miss the second stw and "
            "the r4 value is lost."
        ),
        root_cause=(
            "PPC ABI: 64-bit returns use r3:r4 pair. The C type determines "
            "whether MWCC stores both words or just r3."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "stw r4", "context": "second word of 64-bit return"},
                description="Missing second stw for the low word",
            ),
        ],
        examples=[
            Example(
                function="lbcardgame.c (OSGetTime)",
                before=(
                    "// Truncated to 32-bit - loses r4:\n"
                    "u32 t = (u32) OSGetTime();\n"
                ),
                after=(
                    "// Full 64-bit - stores both r3 and r4:\n"
                    "s64 temp_r6 = OSGetTime();\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When calling functions returning 64-bit types (OSGetTime, "
                    "OSGetTick64, etc.), declare the local as `s64`/`u64`. "
                    "MWCC stores both r3 and r4. Truncating with `(u32)` "
                    "loses the low word stw."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["stw"],
        categories=["calling-conv", "type"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbcardgame OSGetTime usage"),
            ],
        ),
    ),
    Pattern(
        id="bctrl-vtable-vs-direct-bl",
        name="Indirect call via function pointer uses `bctrl`, not `bl`",
        description=(
            "Calling through a struct/class function pointer "
            "(`info->head.info_init()`) uses `lwz` + `mtctr` + `bctrl`. "
            "Calling the function directly by name uses `bl symbol`. "
            "If the target uses `bctrl`, force indirection in source even "
            "if you know the actual function — use the struct field, not "
            "the function name."
        ),
        root_cause=(
            "PPC has no direct memory-based call. Indirect calls go via "
            "the count register: `mtctr` loads the target, `bctrl` "
            "branches and links to it. `bl symbol` is a direct PC-relative "
            "call that doesn't use ctr."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bctrl", "actual": "bl"},
                description="Indirect call vs direct call",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "mtctr", "bctrl"]},
                description="Load pointer, set ctr, branch-link-via-ctr",
            ),
        ],
        examples=[
            Example(
                function="class.c, hash.c sysdolphin dispatch",
                before=(
                    "// Direct call - emits bl:\n"
                    "info_init();\n"
                ),
                after=(
                    "// Indirect via struct - emits bctrl:\n"
                    "info->head.info_init();\n"
                    "// or:\n"
                    "(*info->head.info_init)();\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `bctrl` instead of `bl <function>`, "
                    "the source called through a struct field. Even if you "
                    "know the actual function name, use the struct field "
                    "access to force the indirection."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["lwz", "mtctr", "bctrl", "bl"],
        categories=["calling-conv"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="sysdolphin class dispatch"),
            ],
        ),
        related_patterns=["dead-callback-load-forces-null-check"],
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
