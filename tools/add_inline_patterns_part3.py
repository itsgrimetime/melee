"""
Part 3: non-inline matching patterns from MEMORY.md and the codebase.

These are mostly tricks that don't involve `static inline` but came up
repeatedly in matched code: type tricks (int vs s32), declaration order,
fp interleaving, comparison-operand-ordering, etc.
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
        id="int-vs-s32-loop-counter",
        name="`int` vs `s32` loop counter affects MWCC unrolling heuristics",
        description=(
            "MWCC treats `int i` and `s32 i` differently for loop optimization. "
            "`s32` is a typedef for `long`, and MWCC may apply different "
            "unrolling/strength-reduction heuristics. When a simple counted "
            "loop won't match, try switching between `int i` and `s32 i`."
        ),
        root_cause=(
            "Although `s32` and `int` are both 32-bit signed, MWCC's loop "
            "optimizer keys off the spelled type. `int` may trigger "
            "different default optimizations than `long` (which is what `s32` "
            "expands to). The exact mechanism is unclear but the empirical "
            "result is well-documented in CLAUDE.md."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["cmpwi", "bge", "..."]},
                description="Simple counted loop with no unusual codegen",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "any", "actual": "any", "context": "loop body unrolled differently"},
                description="Loop unrolled by different factor than expected",
            ),
        ],
        examples=[
            Example(
                function="generic-counted-loop",
                before=(
                    "// s32 version may not match:\n"
                    "s32 i;\n"
                    "for (i = 0; i < N; i++) {\n"
                    "    array[i] = 0;\n"
                    "}\n"
                ),
                after=(
                    "// int version may match where s32 doesn't:\n"
                    "int i;\n"
                    "for (i = 0; i < N; i++) {\n"
                    "    array[i] = 0;\n"
                    "}\n"
                ),
                context="Simple counted loop; if one type doesn't match, try the other",
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If a simple counted loop won't match, swap `s32 i` for "
                    "`int i` (or vice versa). MWCC applies different loop "
                    "optimization heuristics based on the spelled type."
                ),
                success_rate=0.4,
            ),
        ],
        opcodes=[],
        categories=["loop", "type", "control-flow"],
        provenance=Provenance(),
        notes=(
            "Documented in CLAUDE.md. Empirical observation — exact MWCC "
            "mechanism unclear. Try this when other loop tricks have failed."
        ),
    ),
    Pattern(
        id="struct-assignment-16-byte-fp-interleave",
        name="Struct assignment generates `f1`/`f0` interleaved spills for 16-byte copy",
        description=(
            "When a selection-sort or shift loop copies 16-byte entries that "
            "contain f64 pairs, using `temp = *ptr; *base = temp;` (struct "
            "assignment) generates the f1/f0 interleaved pattern with stack "
            "spill (`stfd f1, sp+16` / `stfd f0, sp+24`). Using separate f64 "
            "temps for each half generates f0-only sequential loads."
        ),
        root_cause=(
            "MWCC compiles `T temp = *ptr` (with T = 16-byte struct of two "
            "f64s) as two f64 loads using both f0 and f1, spilled to stack "
            "between load and store. Separate `temp0 = ptr->d0; temp8 = "
            "ptr->d8;` uses f0 alone for both, without spills. The pattern "
            "you want depends on what the target's asm shows."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stfd", "actual": "<missing>"},
                description="Target has stfd to stack; your code uses register-only fp",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lfd", "lfd", "stfd", "stfd"]},
                description="Two paired lfd/stfd via stack spill",
            ),
        ],
        examples=[
            Example(
                function="mnDiagram2_GetRankedName (shift loop)",
                context=(
                    "Selection sort shift loop in mndiagram2.c. Stack matches "
                    "after using struct assignment; struct size (16 bytes) "
                    "naturally replaces what PAD_STACK was doing."
                ),
                before=(
                    "// Separate temps — f0-only sequential, no stack spill:\n"
                    "f64 temp0 = ptr->d0;\n"
                    "f64 temp8 = ptr->d8;\n"
                    "base->d0 = temp0;\n"
                    "base->d8 = temp8;\n"
                ),
                after=(
                    "// Struct assignment — forces f1/f0 interleave + stack spill:\n"
                    "Entry16 temp = *ptr;\n"
                    "*base = temp;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target shows `stfd f1, sp+N` / `stfd f0, sp+M` (16-byte "
                    "spill pattern), use struct assignment `temp = *ptr` "
                    "instead of split f64 temps. If target shows f0-only "
                    "sequential without stack, use separate temps."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lfd", "stfd"],
        categories=["struct", "float", "stack", "loop"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnDiagram2_GetRankedName"),
            ],
        ),
        related_patterns=["struct-field-copy", "copying-structs-field-by-field"],
    ),
    Pattern(
        id="u16-comparison-addis-nop-copy",
        name="`addis rX, rY, 0` nop-copy from `int x = lhz(...)` u16 compare",
        description=(
            "Comparing `int x = table[N]; if (x != 0xFFFF)` generates an "
            "`addis r0, r3, 0` (a 16-bit-shift no-op copy from r3 to r0) "
            "followed by `cmplwi r0, 0xFFFF`. Adding an explicit `(u16)` cast "
            "generates `clrlwi r0, r3, 16` + `cmplwi r0, 0xFFFF` instead. "
            "The `addis r0, rN, 0` is a nop-copy MWCC emits when comparing "
            "an `int` loaded by `lhz` against 0xFFFF."
        ),
        root_cause=(
            "MWCC tracks that `lhz` produces a value already zero-extended in "
            "the low 16 bits. Comparing the int directly against 0xFFFF only "
            "needs a register copy (so the original value stays clean for "
            "later use), giving the `addis rX, rY, 0` no-op. Casting to "
            "`(u16)` forces an explicit mask via `clrlwi`."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "addis", "actual": "clrlwi"},
                description="Target has nop-copy via addis; your code has clrlwi mask",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lhz", "addis", "cmplwi"]},
                description="Half-word load, nop-copy, compare-immediate",
            ),
        ],
        examples=[
            Example(
                function="mnDiagram2_CreateStatRow (iconId compare)",
                context=(
                    "mndiagram2.c — fixed by NOT casting to u16. Use `int "
                    "iconId = row->iconId; if (iconId != 0xFFFF)` instead of "
                    "`if ((u16) iconId != 0xFFFF)`."
                ),
                before=(
                    "// (u16) cast forces clrlwi:\n"
                    "if ((u16) row->iconId != 0xFFFF) { ... }\n"
                ),
                after=(
                    "// int local + no cast forces addis nop-copy:\n"
                    "int iconId = row->iconId;\n"
                    "if (iconId != 0xFFFF) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows `addis rX, rY, 0` followed by "
                    "`cmplwi rX, 0xFFFF`, comparing the result of an `lhz` "
                    "load: declare an `int` local for the value, then compare "
                    "directly against 0xFFFF without casting to u16."
                ),
                success_rate=0.9,
            ),
            Fix(
                description=(
                    "Inverse: if target shows `clrlwi`, add an explicit "
                    "`(u16)` cast to force the mask."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["addis", "clrlwi", "cmplwi", "lhz"],
        categories=["type", "branch"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnDiagram2_CreateStatRow"),
            ],
        ),
        related_patterns=["u8-parameter-mask-clrlwi"],
    ),
    Pattern(
        id="float-array-load-vs-literal-zero",
        name="Load `0.0f` from array element vs use literal",
        description=(
            "When comparing a float against 0.0, sometimes the expected asm "
            "shows a `lfs` load from an array element (or similar data "
            "address) rather than loading 0.0 from .rodata. Fix by storing "
            "the data pointer in a local and comparing against `array[idx]` "
            "where `array[idx]` happens to be 0.0."
        ),
        root_cause=(
            "The original code likely indexed into a constant array even "
            "though the loaded value was 0.0. The asm `lfs f0, OFFSET(rN)` "
            "loads from the array, not from a separate 0.0 constant. To "
            "match, you have to perform the same indexed load."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lfs", "actual": "lfs"},
                description="Both `lfs` but different addressing — array vs .rodata",
            ),
        ],
        examples=[
            Example(
                function="mnEvent (anim_speeds[1] pattern)",
                context=(
                    "mnevent.c — store `mnEvent_803EF74C` array in `f32* "
                    "anim_speeds` local and compare against `anim_speeds[1]` "
                    "instead of `0.0f`. Even though `anim_speeds[1]` is 0.0f, "
                    "the indexed load matches the expected asm."
                ),
                before=(
                    "// Literal 0.0f — loads from .rodata:\n"
                    "if (val >= 0.0f) { ... }\n"
                ),
                after=(
                    "// Array index — loads from array data:\n"
                    "f32* anim_speeds = mnEvent_803EF74C;\n"
                    "if (val >= anim_speeds[1]) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target shows `lfs f0, OFFSET(rN)` where rN points at a "
                    "data array and OFFSET corresponds to a 0.0 entry, replace "
                    "your literal `0.0f` comparison with `array[index]`. The "
                    "load address has to match exactly."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lfs"],
        categories=["float", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnEvent (anim_speeds pattern)"),
            ],
        ),
    ),
    Pattern(
        id="hsd-gobj-prototype-propagation",
        name="HSD_GObj* prototype propagation through proc callback dispatchers",
        description=(
            "When a GObj proc callback dispatches to sub-callbacks, the "
            "sub-callbacks need proper `HSD_GObj*` prototypes (not "
            "`UNK_PARAMS`/no prototype). Without proper prototypes, the "
            "compiler treats `gobj` as dead and puts unrelated globals into "
            "r3. With proper prototypes, the compiler preserves r3 for gobj "
            "passthrough, putting other args in r4+."
        ),
        root_cause=(
            "MWCC's register allocator decides r3 usage based on the callee's "
            "first parameter. Unknown prototype = compiler doesn't know to "
            "preserve r3. Known prototype with HSD_GObj* first arg = compiler "
            "keeps gobj in r3 across the call chain."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<r3=gobj>", "actual": "<r3=global>"},
                description="r3 holds wrong value at call site",
            ),
            Signal(
                type="extra_instruction",
                data={"opcode": "lwz", "context": "global loaded into r3 instead of gobj"},
                description="Extra global load preceding callback dispatch",
            ),
        ],
        examples=[
            Example(
                function="fn_80238540",
                context=(
                    "mnname.c. Sub-callbacks dispatched via switch on cmd. "
                    "Initially UNK_PARAMS prototypes caused r3 to be used "
                    "for a global. Fixed by giving each sub-callback proper "
                    "HSD_GObj* signatures."
                ),
                before=(
                    "// Sub-callbacks with unknown prototypes:\n"
                    "void cb_0(void);\n"
                    "void cb_1(void);\n"
                    "// dispatch:\n"
                    "switch (cmd) { case 0: cb_0(); break; case 1: cb_1(); break; }\n"
                    "// Compiler may put global in r3 since gobj is dead.\n"
                ),
                after=(
                    "// Sub-callbacks with proper HSD_GObj* prototypes:\n"
                    "void cb_0(HSD_GObj* gobj);\n"
                    "void cb_1(HSD_GObj* gobj);\n"
                    "// dispatch:\n"
                    "switch (cmd) { case 0: cb_0(gobj); break; case 1: cb_1(gobj); break; }\n"
                    "// Compiler keeps gobj in r3 across calls.\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Make sure every sub-callback dispatched from a proc has a "
                    "proper `HSD_GObj*` (or `Fighter_GObj*`/`Item_GObj*`) first "
                    "parameter prototype, even if the sub-callback doesn't "
                    "use gobj internally. The prototype affects the dispatch "
                    "site's register allocation."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["lwz", "mr"],
        categories=["calling-conv", "register"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="fn_80238540"),
            ],
        ),
        related_patterns=["local-function-type-declaration"],
    ),
    Pattern(
        id="clrlwi-between-u8-function-calls",
        name="Force `clrlwi` between `u8`-returning and `u8`-taking function calls",
        description=(
            "When `func_A` returns `u8` and `func_B` takes a `u8` parameter, "
            "MWCC may skip the mask because the types match. To force "
            "`clrlwi r3, rN, 24` between the calls, use an `s32` (or `int`) "
            "intermediate variable: `s32 code = func_A(); func_B((u8) code);`. "
            "The explicit cast on the `s32` generates the mask."
        ),
        root_cause=(
            "Type-equality lets MWCC elide the zero-extension between calls. "
            "An `s32` intermediate breaks the type match; the explicit `(u8)` "
            "cast on the `s32` then forces `clrlwi`."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "clrlwi", "actual": "<missing>"},
                description="Target has clrlwi r3,rN,24 between two function calls",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["bl", "clrlwi", "bl"]},
                description="Call, mask, call sequence",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// u8 -> u8 direct, no mask:\n"
                    "func_B(func_A(arg));\n"
                ),
                after=(
                    "// s32 intermediate forces clrlwi via cast:\n"
                    "s32 code = func_A(arg);\n"
                    "func_B((u8) code);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Declare an `s32` (or `int`) local to receive the result of "
                    "the u8-returning function. Cast to `(u8)` at the call site "
                    "of the u8-taking function. This forces `clrlwi r3, rN, 24` "
                    "between the calls."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["clrlwi"],
        categories=["type", "register"],
        provenance=Provenance(),
        related_patterns=["u8-parameter-mask-clrlwi"],
    ),
    Pattern(
        id="cleanup-loop-dual-zero-locals",
        name="Dual `_zero` locals to bump callee-saved count in cleanup loops",
        description=(
            "When a cleanup loop with two array fields needs `stmw r26` (6 "
            "callee-saved regs) but generates `stmw r27` (5), add two `int "
            "left_zero/right_zero` locals copied from the loop counter. MWCC "
            "treats `left_zero = i` and `right_zero = i` as data-dependent "
            "on `i`, allocating two MORE callee-saved registers. Then cast "
            "to the field's pointer type when storing NULL."
        ),
        root_cause=(
            "Literal `NULL` (= 0) stores let MWCC reuse a single zero "
            "register. Named local stores force separate registers. The "
            "data-dependency chain through `i` makes them callee-saved."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stmw r26", "actual": "stmw r27"},
                description="Expected 6 callee-saved regs, got 5",
            ),
        ],
        examples=[
            Example(
                function="fn_802523D8 (mninfo.c)",
                context="94.2% → 95.9% with this pattern",
                after=(
                    "int i;\n"
                    "int left_zero;\n"
                    "int right_zero;\n"
                    "\n"
                    "for (i = 0; i < N; i++) {\n"
                    "    left_zero = i;\n"
                    "    right_zero = i;\n"
                    "    if (left->left[i] != NULL) {\n"
                    "        HSD_SisLib_803A5CC4(right->left[i]);\n"
                    "        left->left[i] = (HSD_Text*) left_zero;   // not NULL\n"
                    "    }\n"
                    "    if (left->right[i] != NULL) {\n"
                    "        HSD_SisLib_803A5CC4(right->right[i]);\n"
                    "        left->right[i] = (HSD_Text*) right_zero; // not NULL\n"
                    "    }\n"
                    "}\n"
                ),
            ),
            Example(
                function="fn_802514D8 (mncount.c)",
                context="96.3% → 96.9% with the same pattern",
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Add `int left_zero; int right_zero;` locals at the top of "
                    "the function. Inside the loop, `left_zero = i; right_zero "
                    "= i;`. Use them in NULL stores via `(T*) left_zero` cast. "
                    "May need to bump PAD_STACK by 8 to keep frame size matching."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["stmw", "stw"],
        categories=["loop", "register", "stack"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="fn_802523D8"),
                ProvenanceEntry(function="fn_802514D8"),
                ProvenanceEntry(function="fn_80251640"),
            ],
        ),
        related_patterns=["static-inline-dual-pointer-cleanup"],
        notes=(
            "Has a plateau limitation — MWCC tends to constant-propagate "
            "i=0 into the zero assignments, generating `li r29, 0` instead "
            "of `addi r29, r28, 0`. The 95.9–96.9% range appears to be the "
            "ceiling for this pattern alone."
        ),
    ),
    Pattern(
        id="pre-loaded-root-variable-load-order",
        name="Pre-loaded root variable forces correct early load",
        description=(
            "Declare and assign a 'root' pointer variable (often "
            "`gobj->hsd_obj` or similar) BEFORE the rest of the locals. "
            "MWCC will emit a load of that pointer at the top of the "
            "function, matching the target's first instruction even if the "
            "variable isn't used until later."
        ),
        root_cause=(
            "MWCC schedules loads based on declaration AND use order. A "
            "pointer declared first but used later gets loaded early. This "
            "matches asm where the target has an early `lwz r31, 0x4(r3)` "
            "for `gobj->hsd_obj` before doing anything else."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "<other>"]},
                description="Target has `lwz` of a field at function start that your code emits later",
            ),
        ],
        examples=[
            Example(
                function="fn_8024E1B4",
                context=(
                    "Combined with dual-pointer cleanup pattern, went from "
                    "50.9% to 100%."
                ),
                after=(
                    "void fn_8024E1B4(HSD_GObj* gobj)\n"
                    "{\n"
                    "    HSD_JObj* root = gobj->hsd_obj;  // load order forcer\n"
                    "    Diagram2* ptr;\n"
                    "    Diagram2* data;\n"
                    "\n"
                    "    ptr = data = gobj->user_data;\n"
                    "    // ... rest of function uses `root` via field accesses ...\n"
                    "}\n"
                ),
            ),
            Example(
                function="lbArchive_LoadSections (archive local var)",
                context=(
                    "Using `archive = mn_804D6BB8` local var before the call "
                    "forces early register load (matching expected). See "
                    "mnSound_8024A09C (100%) for canonical pattern."
                ),
                after=(
                    "void func(args)\n"
                    "{\n"
                    "    Archive* archive = mn_804D6BB8;\n"
                    "    HSD_JObj* joint_data;\n"
                    "    HSD_JObj* base;\n"
                    "\n"
                    "    // ... use archive later ...\n"
                    "    lbArchive_LoadSections(archive, ...);\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target loads a pointer/field at function start that "
                    "your code defers, declare and assign it as the FIRST "
                    "local: `T* root = expr;`. Use it later in the function. "
                    "The declaration order forces the load to happen early."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lwz"],
        categories=["register", "loop", "control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="fn_8024E1B4"),
                ProvenanceEntry(function="lbArchive_LoadSections"),
                ProvenanceEntry(function="mnSound_8024A09C"),
            ],
        ),
        related_patterns=["static-inline-dual-pointer-cleanup"],
    ),
    Pattern(
        id="declaration-order-forces-register-allocation",
        name="Local variable declaration order forces callee-saved register allocation",
        description=(
            "MWCC honors C variable declaration order when assigning "
            "callee-saved registers r27-r31. Variables declared first get "
            "lower register numbers (r29 before r30 before r31). Reordering "
            "declarations is often the simplest fix for register-allocation "
            "mismatches."
        ),
        root_cause=(
            "MWCC's register allocator follows declaration order as a "
            "tie-breaker. When two variables have similar live ranges, the "
            "earlier-declared one gets the lower-numbered callee-saved register. "
            "This is independent of usage order."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stw r29", "actual": "stw r30"},
                description="Register numbers swapped for similar variables",
            ),
        ],
        examples=[
            Example(
                function="mnSound_8024A09C (joint_data/base order)",
                context=(
                    "Declaration order of `joint_data` and `base` locals "
                    "affects which gets r29 vs r30."
                ),
                before=(
                    "HSD_JObj* base;\n"
                    "HSD_JObj* joint_data;\n"
                    "// joint_data gets r30, base gets r29 — wrong if target has it swapped\n"
                ),
                after=(
                    "HSD_JObj* joint_data;\n"
                    "HSD_JObj* base;\n"
                    "// joint_data gets r29, base gets r30\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When register numbers are swapped between similar-lived "
                    "variables, swap their declaration order. The earlier "
                    "declaration gets the lower callee-saved register."
                ),
                success_rate=0.7,
            ),
            Fix(
                description=(
                    "If swapping declarations doesn't help, the target may use "
                    "more callee-saved registers — add a dummy local (e.g., "
                    "from cleanup-loop-dual-zero-locals pattern) to bump the "
                    "count."
                ),
            ),
        ],
        opcodes=["stmw", "stw"],
        categories=["register"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnSound_8024A09C"),
            ],
        ),
        related_patterns=[
            "callee-saved-register-allocation-order-r27-r31",
            "cleanup-loop-dual-zero-locals",
        ],
    ),
    Pattern(
        id="pad-stack-is-last-resort",
        name="`PAD_STACK` is a last resort, not a primary stack fix",
        description=(
            "Stack-size mismatches usually mean missing inlines or variables, "
            "not 'add padding'. Investigate missing inline functions, missing "
            "local variables, or type differences before using PAD_STACK. The "
            "macro adds dead bytes to the frame but doesn't fix the underlying "
            "structural mismatch."
        ),
        root_cause=(
            "The frame-size delta usually corresponds to specific spills the "
            "original code did but your code doesn't (or vice versa). Adding "
            "PAD_STACK papers over the symptom without addressing the cause; "
            "it can also mask other mismatches by aligning offsets."
        ),
        signals=[
            Signal(
                type="offset_delta",
                data={"register": "r1", "delta": None},
                description="r1 offsets all shifted by a uniform amount",
            ),
        ],
        examples=[
            Example(
                function="meta-pattern",
                before=(
                    "// Lazy fix: add PAD_STACK to absorb the difference\n"
                    "void func(void)\n"
                    "{\n"
                    "    Vec3 pos;\n"
                    "    f32 val;\n"
                    "    PAD_STACK(0x10);\n"
                    "    ...\n"
                    "}\n"
                ),
                after=(
                    "// Right fix: identify the missing inline or local\n"
                    "static inline f32 my_sqrtf(f32 x) { ... }  // adds 0x10 to frame naturally\n"
                    "\n"
                    "void func(void)\n"
                    "{\n"
                    "    Vec3 pos;\n"
                    "    f32 val;\n"
                    "    val = my_sqrtf(val);  // inlines, adds the missing frame\n"
                    "    ...\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Before adding PAD_STACK, check: "
                    "(1) Is there a missing `static inline` helper (e.g., "
                    "Newton-Raphson sqrt, sin/cos inline)? "
                    "(2) Is there a missing local (e.g., a struct copy that "
                    "needs a temp)? "
                    "(3) Are types correct (Vec3 vs f32 array)? "
                    "(4) Is there a missed library call that would have its "
                    "own stack reservation?"
                ),
                success_rate=0.8,
            ),
            Fix(
                description=(
                    "If structural fixes don't work and the frame is still "
                    "off by exactly N bytes, use PAD_STACK(N) as a last resort. "
                    "Document why in a comment."
                ),
            ),
        ],
        opcodes=["stwu", "stw"],
        categories=["stack"],
        provenance=Provenance(),
        related_patterns=[
            "incorrect-stack-size",
            "static-inline-stack-dummy-array",
            "newton-raphson-sqrt-inline",
        ],
        notes="Meta-pattern from CLAUDE.md guidance.",
    ),
    Pattern(
        id="match-percent-can-drop-with-correct-structure",
        name="Match percent can DROP when your code becomes correct",
        description=(
            "When refactoring code toward the right structure, the diff "
            "percent may temporarily DROP. Do not revert a structurally "
            "correct change just because the percent dropped. A correct `bl` "
            "(real function call) at 60% is better than incorrect inlined "
            "code at 85%. You can improve from correct structure; you cannot "
            "improve from incorrect structure that happens to align bytes."
        ),
        root_cause=(
            "Match percent measures byte-level agreement, but byte-level "
            "agreement with WRONG structure is a local optimum. The right "
            "structure (proper function calls, correct types, correct loop "
            "form) may have more byte differences initially but can be "
            "polished from. The wrong structure that's 'close' is a trap."
        ),
        signals=[],
        examples=[
            Example(
                function="meta-pattern",
                context="Refactoring observation",
                before="// Inlined math expression: 85% match, but inlining is wrong",
                after=(
                    "// Replaced with bl to real function: 60% match, but structure is right.\n"
                    "// Now we can fix register allocation, stack frame, etc. to reach 100%.\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Trust structural correctness over byte percentage. Commit "
                    "the structurally correct change even if the percent "
                    "dropped, then fix the remaining mismatches."
                ),
            ),
            Fix(
                description=(
                    "If the percent drops AND you can't see why structurally "
                    "(e.g., you just renamed a variable), revert. Naming-only "
                    "changes should not change codegen."
                ),
            ),
        ],
        opcodes=[],
        categories=["control-flow"],
        provenance=Provenance(),
        notes="Meta-pattern from CLAUDE.md guidance.",
    ),
    Pattern(
        id="sda-array-size-threshold",
        name="`extern char[N]` SDA eligibility threshold at 8 bytes",
        description=(
            "Static/extern character arrays of size ≤8 bytes are placed in "
            ".sdata and use R_PPC_EMB_SDA21 relocations (single load from "
            "r13-relative). Arrays >8 bytes go to .data and need an "
            "R_PPC_ADDR16_HA + R_PPC_ADDR16_LO pair (addis+addi/lwz). The "
            "boundary is exact: 8-byte string `\"jobj.h\\0\"` = 7 chars + "
            "terminator = 7 bytes, SDA. 9-byte string = .data."
        ),
        root_cause=(
            "MWCC follows the GameCube ABI: small objects (<=8 bytes) go to "
            ".sdata for fast access via r13. The 8-byte threshold is "
            "ABI-mandated, not configurable."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "addis"},
                description=".sdata access (single lwz from r13) vs .data (addis+lwz)",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["addis", "addi"]},
                description="Two-instruction .data load expected, your code single lwz",
            ),
        ],
        examples=[
            Example(
                function="mnEvent_803EF794 (char* -> char[])",
                context=(
                    "9-byte content string. Changed from `static char*` (4 "
                    "bytes, SDA) to `static char[]` (9 bytes, non-SDA) to "
                    "match the target's R_PPC_ADDR16_HA/LO relocations."
                ),
                before=(
                    "static char* str_warning = \"Warning :\";  // 4 bytes (pointer) - SDA\n"
                ),
                after=(
                    "static char str_warning[] = \"Warning :\";  // 9 bytes (array) - .data\n"
                ),
            ),
            Example(
                function="mnEvent_803EF7A0 (char[8] -> char[9])",
                context=(
                    "Changed from `static char str[8]` (boundary 8 bytes, SDA) "
                    "to `static char str[9]` (>8, non-SDA) to match relocations."
                ),
                before=(
                    "static char str[8] = \"jobj.h.\";  // 7 chars + null in 8-byte array - SDA\n"
                ),
                after=(
                    "static char str[9] = \"jobj.h..\";  // 8 chars + null in 9-byte array - non-SDA\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Check the target's relocation table. If you see "
                    "R_PPC_EMB_SDA21 for a string symbol, declare it as "
                    "`static char arr[N]` with N ≤ 8. If you see "
                    "R_PPC_ADDR16_HA + R_PPC_ADDR16_LO, use N > 8."
                ),
                success_rate=0.95,
            ),
            Fix(
                description=(
                    "Symbols.txt is authoritative: the section name (.sdata vs "
                    ".data) and the size tell you which form to use. Match the "
                    "size exactly."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["lwz", "addis", "addi"],
        categories=["data-layout", "calling-conv"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnEvent_803EF794"),
                ProvenanceEntry(function="mnEvent_803EF7A0"),
            ],
        ),
        related_patterns=[
            "base-relative-string-addressing-assertions",
            "hsd-inline-file-local-asserts",
        ],
    ),
    Pattern(
        id="static-char-ptr-vs-array-sda",
        name="`static char*` (pointer) vs `static char[]` (array) SDA distinction",
        description=(
            "`static char* x = \"...\"` is a 4-byte pointer variable: it lives "
            "in .sdata regardless of the string content's length. The string "
            "itself is a separate read-only object. "
            "`static char x[] = \"...\"` is an N-byte array variable: lives in "
            ".sdata only if N ≤ 8, otherwise .data. Choose which based on the "
            "symbols.txt section."
        ),
        root_cause=(
            "Pointer = always 4 bytes (always SDA). Array size = string length "
            "+ 1 (SDA-eligible based on threshold). Changing between the two "
            "changes the symbol's size AND section, which changes all "
            "relocations pointing at it."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "<different addressing>"},
                description="Section-specific loads differ",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "static char* msg = \"hello world\";  // 4-byte ptr in .sdata\n"
                ),
                after=(
                    "static char msg[] = \"hello world\";  // 12-byte array in .data\n"
                ),
                context="Pointer vs array changes both size and section",
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Check symbols.txt for the symbol's section. "
                    ".sdata with size = 4 → `static char* name = \"...\";`. "
                    ".sdata with size > 4 and ≤ 8 → `static char name[N] = \"...\";`. "
                    ".data → `static char name[] = \"...\";` with N > 8."
                ),
                success_rate=0.9,
            ),
            Fix(
                description=(
                    "Be careful changing between pointer and array — it can "
                    "trigger build-system split regeneration loops. Once "
                    "committed as one form, do not revert."
                ),
            ),
        ],
        opcodes=["lwz"],
        categories=["data-layout"],
        provenance=Provenance(),
        related_patterns=["sda-array-size-threshold"],
    ),
    Pattern(
        id="hsd-assert-second-assert-mtx-dirty-trap",
        name="Second HSD_ASSERT inside HSD_JObjSetMtxDirty macro",
        description=(
            "HSD_JObjSet* inlines call `HSD_JObjSetMtxDirty(jobj)` which "
            "expands to a macro that contains its own internal HSD_ASSERT "
            "via `HSD_JObjMtxIsDirty(jobj)`. Even if you reimplement the "
            "outer JObjSet* inline locally with file-local asserts, this "
            "second assert is still generated from baselib's macro expansion. "
            "Fix by also reimplementing `HSD_JObjMtxIsDirty` locally."
        ),
        root_cause=(
            "HSD_JObjSetMtxDirty is a macro, but it calls "
            "HSD_JObjMtxIsDirty(jobj) which is a `static inline` in baselib's "
            "jobj.h. That inline contains its own HSD_ASSERT. Reimplementing "
            "only the outer Set* function leaves the inner assert pointing at "
            "anonymous baselib strings."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<file-local string load>", "actual": "<anonymous string>"},
                description="One assert matches; the other still uses anonymous baselib strings",
            ),
        ],
        examples=[
            Example(
                function="ftKb_JObjMtxIsDirty",
                context=(
                    "ftKb_SpecialNNs.c — reimplement BOTH the outer Set* "
                    "inline AND the inner JObjMtxIsDirty inline."
                ),
                after=(
                    "extern char ftKb_Init_804D3DD0[7];  // \"jobj.h\\0\"\n"
                    "extern char ftKb_Init_804D3DD8[5];  // \"jobj\\0\"\n"
                    "\n"
                    "static inline bool ftKb_JObjMtxIsDirty(HSD_JObj* jobj)\n"
                    "{\n"
                    "    bool result;\n"
                    "    (jobj) ? ((void) 0) : __assert(ftKb_Init_804D3DD0, 0x234, ftKb_Init_804D3DD8);\n"
                    "    result = false;\n"
                    "    if (!(jobj->flags & JOBJ_USER_DEF_MTX) && (jobj->flags & JOBJ_MTX_DIRTY)) {\n"
                    "        result = true;\n"
                    "    }\n"
                    "    return result;\n"
                    "}\n"
                    "\n"
                    "static inline void ftKb_JObjSetMtxDirty(HSD_JObj* jobj)\n"
                    "{\n"
                    "    if (jobj != NULL && !ftKb_JObjMtxIsDirty(jobj)) {\n"
                    "        HSD_JObjSetMtxDirtySub(jobj);\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When reimplementing HSD_JObjSet* inlines, ALSO reimplement "
                    "`HSD_JObjMtxIsDirty` locally with the same file-local "
                    "extern char strings. Replace calls to "
                    "`HSD_JObjSetMtxDirty(jobj)` with manual "
                    "`if (jobj != NULL && !your_MtxIsDirty(jobj)) "
                    "HSD_JObjSetMtxDirtySub(jobj);`."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Note from MEMORY.md: the second assert via "
                    "HSD_JObjMtxIsDirty 'cannot be fixed without modifying "
                    "jobj.h' in some cases — that means baselib's inline body "
                    "is committed and parsed at include time. The local "
                    "reimplementation is the workaround."
                ),
            ),
        ],
        opcodes=["lwz"],
        categories=["inline", "data-layout"],
        provenance=Provenance(),
        related_patterns=[
            "hsd-inline-file-local-asserts",
            "fake-hsd-inline-with-literal-string-macro",
        ],
        notes=(
            "MEMORY.md note: `#undef`/`#define HSD_ASSERT` does NOT work for "
            "inline function bodies — MWCC parses them at include time."
        ),
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
