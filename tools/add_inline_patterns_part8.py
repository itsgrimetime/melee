"""
Part 8: more discord-knowledge meta and ABI patterns.
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
        id="r2-r13-section-mapping",
        name="`r13` = .sdata/.sbss (mutable globals); `r2` = .sdata2/.sbss2 (const)",
        description=(
            "PPC ABI for GameCube: `r13` is the base of the writable small "
            "data area (.sdata, .sbss); `r2` is the base of the const small "
            "data area (.sdata2, .sbss2). When you see `lwz rX, name@sda21(rN)` "
            "with rN=r13, the symbol is mutable; with rN=r2, it's const. "
            "Removing `const static` moves data from r2 to r13."
        ),
        root_cause=(
            "MWCC follows EABI conventions: separate small-data sections for "
            "const vs mutable. The choice between r2 and r13 in the asm tells "
            "you the symbol's section, which constrains the C declaration."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz r,name@sda21(r13)", "actual": "lwz r,name@sda21(r2)"},
                description="Wrong section (mutable vs const)",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// const static -> .sdata2 (r2):\n"
                    "const static float gravity = 9.8f;\n"
                ),
                after=(
                    "// drop const -> .sdata (r13):\n"
                    "static float gravity = 9.8f;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target asm uses r13 for a symbol you declared "
                    "`const`, remove the `const` to move it to .sdata. "
                    "When target uses r2 for a symbol you declared mutable, "
                    "add `const`."
                ),
                success_rate=0.9,
            ),
            Fix(
                description=(
                    "Section allocation rules: "
                    "<=8 bytes initialized non-const -> .sdata "
                    "<=8 bytes initialized const -> .sdata2 "
                    ">8 bytes initialized -> .data or .rodata "
                    "Uninitialized -> .bss/.sbss (size dependent). "
                    "String literals are an exception: go to .data or .sdata, "
                    "not .rodata."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["lwz", "stw"],
        categories=["data-layout"],
        provenance=Provenance(),
        related_patterns=[
            "sda-array-size-threshold",
            "static-char-ptr-vs-array-sda",
        ],
    ),
    Pattern(
        id="psq-l-psq-st-not-in-function-body",
        name="Paired singles (`psq_l`, `psq_st`) appear only in prologue/SDK code",
        description=(
            "Even with `-proc gekko`, MWCC does NOT generate paired singles "
            "instructions (`psq_l`, `psq_st`) in normal function bodies. They "
            "appear only in: (1) prologue/epilogue for f64 GPR save, "
            "(2) inline asm, (3) SDK library code. If your decompiled "
            "function body has `psq_*`, you've made an error."
        ),
        root_cause=(
            "MWCC's optimizer doesn't auto-vectorize floats into paired-"
            "single ops. The instructions exist in compiler output only for "
            "well-defined ABI cases (callee-saved float register save) and "
            "explicit programmer use."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<missing>", "actual": "psq_l"},
                description="Paired singles in body where none expected",
            ),
        ],
        examples=[
            Example(
                function="diagnostic",
                context=(
                    "If you see `psq_l` or `psq_st` in a function body "
                    "(not prologue/epilogue), your codegen path is wrong. "
                    "These come from explicit intrinsics or SDK code only."
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Don't write paired-singles intrinsics in C source unless "
                    "the target asm clearly uses them in the function body. "
                    "Stick to regular f32/f64 ops; the compiler does the rest."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["psq_l", "psq_st"],
        categories=["float", "data-layout"],
        provenance=Provenance(),
        notes="Discord knowledge: MWCC does not emit psq_* in normal codegen.",
    ),
    Pattern(
        id="mid-function-block-declarations",
        name="`{}` block to declare locals mid-function (pre-C99 workaround)",
        description=(
            "MWCC requires declarations at the start of a block (pre-C99 "
            "rule). To introduce a variable mid-function, wrap the code in "
            "`{ T name; ... }`. The block scope affects register allocation: "
            "narrower live-ranges may use different (lower-numbered) "
            "callee-saved registers."
        ),
        root_cause=(
            "C89 declaration rules force locals at block start. MWCC respects "
            "this. Declaration position determines live-range start, which "
            "affects register coalescing and callee-saved assignment."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stw r29", "actual": "stw r30"},
                description="Different callee-saved register due to declaration position",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "void func(void)\n"
                    "{\n"
                    "    setup();\n"
                    "    f32 val = compute();  // ERROR: mid-function in C89\n"
                    "    use(val);\n"
                    "}\n"
                ),
                after=(
                    "void func(void)\n"
                    "{\n"
                    "    setup();\n"
                    "    {\n"
                    "        f32 val = compute();  // OK: block-scoped\n"
                    "        use(val);\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use `{ T name; ... }` blocks to introduce locals mid-"
                    "function. Block scoping limits live ranges and can "
                    "affect register allocation."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=[],
        categories=["register"],
        provenance=Provenance(),
        related_patterns=["declaration-order-forces-register-allocation"],
    ),
    Pattern(
        id="self-assignment-for-regalloc",
        name="`x = x;` self-assignment to fix register swaps",
        description=(
            "A no-op self-assignment like `fp = fp;` or `fighter_data3 = "
            "fighter_data3;` sometimes fixes register allocation mismatches. "
            "Acts as a reference that keeps the variable alive across the "
            "boundary, preventing MWCC from coalescing or eliminating the "
            "register binding."
        ),
        root_cause=(
            "Unused self-assignment is technically dead code, but MWCC's "
            "peephole pass runs before dead-code elimination in some "
            "configurations. The intermediate assignment can keep the "
            "register binding stable through other transformations."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stw r29", "actual": "stw r30"},
                description="Register swapped between similar variables",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "void func(Fighter* fp, OtherT* other)\n"
                    "{\n"
                    "    fp = fp;          // self-assignment\n"
                    "    other = other;    // also\n"
                    "    // ... rest of function ...\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When register allocation is swapped between similar "
                    "variables, try `x = x;` self-assignment on one or both. "
                    "Also useful for `rlwimi` vs `ori` differences in bitfield "
                    "operations."
                ),
                success_rate=0.5,
            ),
            Fix(
                description=(
                    "Note: this is a 'magic' trick. If it works, document "
                    "why. Don't sprinkle it everywhere."
                ),
            ),
        ],
        opcodes=[],
        categories=["register"],
        provenance=Provenance(),
        notes="Discord knowledge - sometimes the only fix for stubborn regswaps.",
    ),
    Pattern(
        id="discard-expression-statement-regalloc",
        name="Discard-statement (`var;` or `!var;`) for register allocation fix",
        description=(
            "A bare expression statement like `var;` or `!var;` (with no "
            "side effects, evaluated and discarded) acts as a register "
            "hint. MWCC reads it as 'keep this value live here'. Sometimes "
            "fixes register swaps or mr/addi peephole issues."
        ),
        root_cause=(
            "Expression-statement evaluates but discards the value. MWCC "
            "emits the load (keeping the register binding) but no store. "
            "This pinpoints where the value must be live, constraining "
            "subsequent register allocation."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "mr", "actual": "<missing>"},
                description="Register move missing where target has it",
            ),
        ],
        examples=[
            Example(
                function="callback null-check",
                after=(
                    "T* cb = obj->callback;\n"
                    "!cb;  // discard expr, but pin the load\n"
                    "if (cb != NULL) {\n"
                    "    cb(obj);\n"
                    "}\n"
                ),
            ),
            Example(
                function="alternative form",
                after=(
                    "var;  // bare reference\n"
                    "// or\n"
                    "(void) var;  // explicit discard\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When MWCC optimizes away a load you need, add a discard "
                    "statement (`var;`, `!var;`, or `(void) var;`) at the "
                    "point you want the load anchored. Works similarly to "
                    "self-assignment but with cleaner intent."
                ),
                success_rate=0.55,
            ),
        ],
        opcodes=["mr", "lwz"],
        categories=["register"],
        provenance=Provenance(),
        related_patterns=[
            "self-assignment-for-regalloc",
            "addi-vs-mr-peephole-dead-code-trick",
            "dead-callback-load-forces-null-check",
        ],
    ),
    Pattern(
        id="subfic-implies-chained-assignment",
        name="`subfic` instruction indicates `i = var = 0;` chained assignment",
        description=(
            "When the target shows a `subfic rX, rY, 0` (subtract from "
            "immediate, here equivalent to negate), the source likely uses "
            "a chained assignment like `i = var = 0;` rather than two "
            "separate `i = 0; var = 0;` statements. The chained form makes "
            "MWCC reason about the value flow differently."
        ),
        root_cause=(
            "Chained `a = b = expr` creates a value-flow dependency: "
            "`b = expr; a = b;`. MWCC may generate a negate or subtract "
            "to realize the dependency. Separate `a = expr; b = expr;` "
            "would re-evaluate `expr` for each."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "subfic", "actual": "li"},
                description="Subtract-from-immediate vs separate immediate loads",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// Separate assignments - emits two `li`:\n"
                    "i = 0;\n"
                    "var = 0;\n"
                ),
                after=(
                    "// Chained assignment - may emit subfic:\n"
                    "i = var = 0;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `subfic` where you'd expect `li 0`, try "
                    "chained assignment `a = b = 0;` instead of separate "
                    "`a = 0; b = 0;`."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["subfic", "li"],
        categories=["register"],
        provenance=Provenance(),
        notes="Discord knowledge: subfic hack for chained-zero assignment.",
    ),
    Pattern(
        id="explicit-s32-cast-changes-division",
        name="Removing `(s32)` cast on division changes generated code",
        description=(
            "Even when a variable is already `s32`, an explicit `(s32)` cast "
            "in a division expression can change the generated asm. "
            "`(s32) temp_r6 / 60` differs from `temp_r6 / 60` despite "
            "semantic equivalence. The cast triggers different "
            "intermediate-value handling."
        ),
        root_cause=(
            "MWCC's type-checker treats casts as explicit nodes in the AST "
            "even when redundant. Code generation can choose differently "
            "based on whether the cast is present. The exact mechanism "
            "depends on context."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "any", "actual": "any", "context": "division codegen"},
                description="Division-related instructions differ",
            ),
        ],
        examples=[
            Example(
                function="generic time-to-frames calc",
                before=(
                    "// With explicit cast:\n"
                    "frames = (s32) temp_r6 / 60;\n"
                ),
                after=(
                    "// Without cast (temp_r6 already s32):\n"
                    "frames = temp_r6 / 60;\n"
                ),
                context="Both compile, but produce different bytes",
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Try adding or removing redundant `(s32)`/`(u32)` casts "
                    "on division operands. MWCC treats casts as AST nodes "
                    "even when type-redundant, affecting codegen."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=["divw", "divwu", "mulhw", "mulhwu"],
        categories=["type"],
        provenance=Provenance(),
    ),
    Pattern(
        id="const-param-for-inline-matching",
        name="`const` on inline parameter helps matching",
        description=(
            "Adding `const` to an inline function's parameter "
            "(`HSD_GObj* const gobj` instead of `HSD_GObj* gobj`) can fix "
            "matching when the const-qualified version is what the inline "
            "was originally written with. The const propagates through "
            "MWCC's value-tracking, affecting load optimization."
        ),
        root_cause=(
            "MWCC's const-tracking influences value reuse and load "
            "elimination. A `T* const p` says the pointer itself won't be "
            "reassigned; this lets MWCC keep the load in a register longer. "
            "The original code may have had the const."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<one load>", "actual": "<two loads>"},
                description="Multiple loads of same pointer vs single cached load",
            ),
        ],
        examples=[
            Example(
                function="HSD_GObjGetUserData",
                before=(
                    "// Without const:\n"
                    "static inline void* HSD_GObjGetUserData(HSD_GObj* gobj) {\n"
                    "    return gobj->user_data;\n"
                    "}\n"
                ),
                after=(
                    "// With const - may match better:\n"
                    "static inline void* HSD_GObjGetUserData(HSD_GObj* const gobj) {\n"
                    "    return gobj->user_data;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If an HSD inline-style helper is close but not matching, "
                    "try adding `const` to its pointer parameter (between the "
                    "`*` and the name)."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=["lwz"],
        categories=["inline", "type"],
        provenance=Provenance(),
    ),
    Pattern(
        id="double-init-pointer-via-inline",
        name="`Fighter* fp = fp = GET_FIGHTER(gobj);` double-init for register match",
        description=(
            "A pattern like `Fighter* fp = fp = GET_FIGHTER(gobj);` (declares "
            "AND self-references AND assigns) may be required when the "
            "underlying inline does the assignment itself. The double-init "
            "preserves register moves that MWCC would otherwise elide."
        ),
        root_cause=(
            "If GET_FIGHTER is an inline that internally does an assignment, "
            "calling it from a normal declaration site coalesces away one of "
            "the moves. The double-init forces the move to stay."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "mr", "context": "after GET_FIGHTER inline"},
                description="Extra register move missing in your code",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "Fighter* fp = GET_FIGHTER(gobj);\n"
                ),
                after=(
                    "// Double-init - preserves inline's register moves:\n"
                    "Fighter* fp = fp = GET_FIGHTER(gobj);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When a GET_FIGHTER/GET_ITEM line is one register move "
                    "short of matching, try `T* x = x = GET_*(...);` double-"
                    "init. The compiler emits both the assignment and the "
                    "move."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=["mr"],
        categories=["register", "inline"],
        provenance=Provenance(),
        related_patterns=["self-assignment-for-regalloc"],
    ),
    Pattern(
        id="condition-splitting-for-match",
        name="Split compound `&&` conditions into nested ifs for matching",
        description=(
            "When a compound condition `if (a != 0 && func1() && func2())` "
            "doesn't match, try splitting into nested ifs: "
            "`if (a) { if (func1() && func2()) { ... } }`. The split "
            "changes basic-block boundaries, which can affect branch "
            "ordering and fall-through."
        ),
        root_cause=(
            "Compound `&&` creates a single decision diamond with multiple "
            "tests. Nested ifs create a hierarchy of separate diamonds. "
            "The target's basic-block structure may match one or the other "
            "more closely."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "any", "actual": "any", "context": "branch flow differs"},
                description="Branch target labels differ",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "if ((a != 0) && func1() && func2()) {\n"
                    "    /* ... */\n"
                    "}\n"
                ),
                after=(
                    "if (a) {\n"
                    "    if (func1() && func2()) {\n"
                    "        /* ... */\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When `&&` chain doesn't match, peel the leading "
                    "non-call test into a separate outer `if`. The remaining "
                    "calls stay together inside."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["beq", "bne"],
        categories=["control-flow", "branch"],
        provenance=Provenance(),
        related_patterns=["short-circuit-and-shared-exit-label"],
    ),
    Pattern(
        id="pragma-c9x-on-for-compound-literals",
        name="`#pragma c9x on` for compound literals (`(MyStruct){...}`)",
        description=(
            "MWCC 1.2.5 doesn't enable C99 features by default. `#pragma c9x "
            "on` enables compound literals like `(MyStruct){0, 1, 2, 3}` "
            "needed to match struct-temporary patterns. Place at top of "
            "file or function. Note: doesn't enable `offsetof` in 1.2.5."
        ),
        root_cause=(
            "C99 compound literals create unnamed objects of struct/array "
            "type at the point of use. MWCC supports them but only with "
            "`#pragma c9x on`. The `-lang c99` flag was added in later "
            "compiler versions; in 1.2.5 you need the pragma."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<struct temp>", "actual": "<workaround>"},
                description="Struct temp construction differs",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "#pragma c9x on\n"
                    "\n"
                    "void func(void)\n"
                    "{\n"
                    "    pass_struct((MyStruct){0, 1, 2, 3});\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If you need compound literals for struct temporaries, "
                    "add `#pragma c9x on` near the top of the .c file. "
                    "Doesn't enable `offsetof` in 1.2.5."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=[],
        categories=["data-layout", "calling-conv"],
        provenance=Provenance(),
    ),
    Pattern(
        id="vec-by-value-stack-copy",
        name="`Vec` (or `Vec3`) passed by value causes stack copy — use `Vec*`",
        description=(
            "Passing `Vec` or `Vec3` (12 bytes) by value causes unpredictable "
            "stack copies in MWCC. Functions taking `Vec` by value can be "
            "hard to match. Fix by changing the parameter to `Vec*`. Match "
            "the calling site with `&local_vec` to take address."
        ),
        root_cause=(
            "Structs >8 bytes passed by value go on the stack (PPC ABI). "
            "MWCC's copy strategy for the inbound parameter and outbound "
            "callee-frame is heuristic. Pointer-passing eliminates the "
            "ambiguity."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "stw", "context": "param-passing stack copy"},
                description="Extra stack stores at call site for Vec value pass",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "void func(Vec v) { /* ... */ }\n"
                    "// Caller: func(my_vec);  // stack copy\n"
                ),
                after=(
                    "void func(Vec* v) { /* ... */ }\n"
                    "// Caller: func(&my_vec);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Change `Vec` and `Vec3` parameters to pointers (`Vec*`, "
                    "`Vec3*`). Take address at callsites. This is the "
                    "canonical pattern in Melee's codebase for fp vectors."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["stw", "lwz"],
        categories=["calling-conv", "struct"],
        provenance=Provenance(),
    ),
    Pattern(
        id="static-fn-removed-by-inline-auto",
        name="`static` functions auto-inlined and linker-removed (keep `static` keyword)",
        description=(
            "With `-inline auto`, MWCC may inline a `static` function at "
            "every call site and then the linker drops the body entirely. "
            "This is desired behavior for true leaf helpers. Keep functions "
            "`static` if they were originally static; removing the keyword "
            "would prevent the inlining."
        ),
        root_cause=(
            "MWCC's auto-inline path is gated by `static`. A `static` function "
            "with one or few callers gets inlined. Without `static`, the "
            "function stays externally visible and is not eligible for "
            "aggressive auto-inline."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<inlined body>", "actual": "bl func"},
                description="Function not inlined where target expects inlining",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// Without static: not auto-inlined\n"
                    "void helper(int x) { /* ... */ }\n"
                ),
                after=(
                    "// With static: auto-inlined and linker-removed\n"
                    "static void helper(int x) { /* ... */ }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If the target has a function inlined but yours has a "
                    "`bl` to it, ensure the function is declared `static`. "
                    "If it's still emitting a call, also check it's defined "
                    "before its callers."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["bl"],
        categories=["inline", "calling-conv"],
        provenance=Provenance(),
    ),
    Pattern(
        id="pragma-use-lmw-stmw-on-for-mnmain",
        name="`#pragma use_lmw_stmw on` for menu files using stmw",
        description=(
            "Melee disables `lmw`/`stmw` by default (`-use_lmw_stmw off`). "
            "Menu files (notably mnmain.c) RE-ENABLE them via "
            "`#pragma use_lmw_stmw on`. This compacts the prologue/epilogue "
            "into single `stmw rN, ...` / `lmw rN, ...` instead of multiple "
            "`stw r27`, `stw r28`, etc."
        ),
        root_cause=(
            "lmw/stmw are slow on Gekko (used for code size). Most of Melee "
            "uses individual stw/lwz for callee-saved regs. Menu files were "
            "compiled with lmw/stmw enabled, probably for code size. The "
            "pragma toggles the behavior per-TU."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stmw r27", "actual": "stw r27, stw r28, stw r29, stw r30, stw r31"},
                description="Single stmw vs multiple stw",
            ),
        ],
        examples=[
            Example(
                function="generic menu file",
                after=(
                    "// At top of menu .c file:\n"
                    "#pragma use_lmw_stmw on\n"
                    "\n"
                    "void menu_func(void) { /* ... */ }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target prologue uses `stmw rN, OFFSET(r1)` and "
                    "epilogue uses `lmw rN, OFFSET(r1)`, add "
                    "`#pragma use_lmw_stmw on` at the top of the file. Used "
                    "by mnmain.c and similar."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["stmw", "lmw"],
        categories=["stack", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnmain functions"),
            ],
        ),
    ),
    Pattern(
        id="dat-attrs-getter-cast",
        name="`dat_attrs` typed getter requires correct attrs struct cast",
        description=(
            "Accessing fighter dat_attrs through a getter that returns "
            "`void*` requires casting at the call site to the specific "
            "attrs type. Wrong cast causes wrong offsets and missed loads. "
            "The getter style affects register usage: `((SpecificAttrs*) "
            "fp->dat_attrs)->field` vs an inline getter that does the cast."
        ),
        root_cause=(
            "Fighter struct's dat_attrs field is typed as `void*` to allow "
            "different attribute structs per fighter. Casting at the use "
            "site keeps the compile-time type narrow; an inline getter "
            "with the cast inside changes register allocation."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz X(rN)", "actual": "lwz Y(rN)"},
                description="Wrong field offset due to wrong cast",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "// Direct cast at use site:\n"
                    "f32 speed = ((ftLk_DatAttrs*) fp->dat_attrs)->run_speed;\n"
                ),
                before=(
                    "// Inline getter - different register usage:\n"
                    "static inline ftLk_DatAttrs* getLkAttrs(Fighter* fp) {\n"
                    "    return (ftLk_DatAttrs*) fp->dat_attrs;\n"
                    "}\n"
                    "// Use:\n"
                    "f32 speed = getLkAttrs(fp)->run_speed;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target loads from a specific offset in dat_attrs but "
                    "yours loads from a different one, check the cast. Use "
                    "the specific attrs struct, not Vec3/void/etc."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "If both casts compile but produce different bytes, "
                    "try the inline getter form vs the direct cast at use "
                    "site."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=["lwz", "lfs"],
        categories=["struct", "inline", "type"],
        provenance=Provenance(),
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
