"""
Part 6: patterns from docs/discord-knowledge/.

Distinct codegen patterns documented in 6+ years of Discord history
that aren't yet in the DB.
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
        id="bdnz-counted-loop-reverse-iteration",
        name="`bdnz` indicates `i = N; i != 0; i--` (reverse iteration)",
        description=(
            "When the target asm shows `bdnz` (branch decrement not zero), "
            "the loop condition was written as decreasing (`i = N; i != 0; "
            "i--`), not increasing (`i = 0; i < N; i++`). MWCC uses the "
            "Count Register (CTR) via `bdnz` for decrementing loops, saving "
            "an explicit compare-immediate."
        ),
        root_cause=(
            "PPC has a dedicated counter register. `mtctr N` + `bdnz` "
            "compiles a decrementing loop with no explicit comparison. "
            "MWCC only emits this for loops whose source actually "
            "decrements; forward loops compile to `cmpwi` + `bge`."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bdnz", "actual": "bge"},
                description="Counter register loop vs compare-based loop",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["mtctr", "...", "bdnz"]},
                description="mtctr loop count, body, bdnz back",
            ),
        ],
        examples=[
            Example(
                function="generic counted loop",
                before=(
                    "// Forward — uses cmpwi + bge:\n"
                    "for (i = 0; i < N; i++) { array[i] = 0; }\n"
                ),
                after=(
                    "// Reverse — uses bdnz:\n"
                    "for (i = N; i != 0; i--) {\n"
                    "    array[i - 1] = 0;  // or array[N - i]\n"
                    "}\n"
                ),
            ),
            Example(
                function="alternative reverse form",
                after=(
                    "// Also produces bdnz:\n"
                    "i = N;\n"
                    "do {\n"
                    "    /* body using i */\n"
                    "    i--;\n"
                    "} while (i != 0);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows `bdnz`, rewrite the loop in C as a "
                    "DECREMENTING loop: `for (i = N; i != 0; i--)` or "
                    "`do { ... } while (--i != 0)`. Adjust the array "
                    "indexing accordingly."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["bdnz", "mtctr"],
        categories=["loop", "control-flow"],
        provenance=Provenance(),
        related_patterns=["loop-condition-inversion-vs"],
    ),
    Pattern(
        id="xoris-r3-implicit-function-declaration",
        name="`xoris r3, r3, ...` after call = missing function declaration",
        description=(
            "An unexpected `xoris r3, r3, ...` (XOR-immediate-shifted) "
            "instruction right after a function call is a telltale sign of "
            "an IMPLICIT function declaration. The compiler assumed the "
            "function returns `int` and is converting the assumed `int` "
            "back to the actual return type. Fix by including the proper "
            "header so the prototype is visible."
        ),
        root_cause=(
            "C's implicit-int rule: undeclared functions are assumed to "
            "return `int` taking `int` args. When the actual function "
            "returns `float`/`double`/`s64`/etc., MWCC emits conversion "
            "code after the call. The conversion uses `xoris` for "
            "sign-bit manipulation or `extsh`/`extsb` for narrowing."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "xoris", "context": "post-call type conversion"},
                description="Unexpected xoris immediately after a bl",
            ),
        ],
        examples=[
            Example(
                function="generic",
                context=(
                    "Common culprits: `sqrtf`, `atan2f`, `lbVector_AngleXY`. "
                    "Forgetting `#include <math.h>` or the lbvector header "
                    "triggers this."
                ),
                before=(
                    "// Missing #include — compiler assumes sqrtf returns int:\n"
                    "f32 d = sqrtf(x);  // xoris emitted after the bl\n"
                ),
                after=(
                    "// Proper include — prototype visible, no xoris:\n"
                    "#include <math.h>\n"
                    "f32 d = sqrtf(x);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When you see unexpected `xoris` after a function call, "
                    "check that the called function is properly declared. "
                    "Add the right `#include` or extern prototype. Common "
                    "missing headers: math.h, melee/lb/lbvector.h, etc."
                ),
                success_rate=0.95,
            ),
            Fix(
                description=(
                    "Run `python tools/checkdiff.py --warnings` or build "
                    "with `-Wimplicit-function-declaration` to surface "
                    "these automatically."
                ),
            ),
        ],
        opcodes=["xoris", "bl"],
        categories=["calling-conv", "type"],
        provenance=Provenance(),
        related_patterns=["hsd-gobj-prototype-propagation"],
    ),
    Pattern(
        id="addi-vs-mr-peephole-dead-code-trick",
        name="`!gobj;` dead statement to break MWCC's `mr`/`addi` peephole",
        description=(
            "MWCC has a peephole pass that converts `addi rX, rY, 0` "
            "(register copy with explicit 0 offset) into `mr rX, rY` "
            "(register move). The reverse can be forced by inserting a "
            "dead statement like `!gobj;` (a no-op boolean expression "
            "with the variable as operand) between the assignment and the "
            "use. This breaks the peephole because the dead code isn't "
            "eliminated until after the peephole pass."
        ),
        root_cause=(
            "MWCC's `mr` vs `addi rX, rY, 0` choice is decided by a "
            "peephole optimizer that runs late. Dead code that references "
            "the value keeps the optimizer from collapsing the copy. "
            "Common workaround documented in `mwcc-debugger` research."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "addi", "actual": "mr"},
                description="Target preserves addi r,r,0; your code optimizes to mr",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// Bare assignment: mr gets emitted\n"
                    "HSD_GObj* gobj = HSD_GObj_Create(...);\n"
                    "do_something(gobj);\n"
                ),
                after=(
                    "// Dead reference prevents peephole:\n"
                    "HSD_GObj* gobj = HSD_GObj_Create(...);\n"
                    "!gobj;  // dead boolean; keeps `addi r3, r31, 0` form\n"
                    "do_something(gobj);\n"
                ),
            ),
            Example(
                function="alternative — pass directly",
                context=(
                    "Often you can avoid the issue by passing the result of "
                    "GObj_Create/LoadJoint directly into the next call, "
                    "skipping the temp."
                ),
                after=(
                    "do_something(HSD_GObj_Create(...));  // no temp, no mr/addi\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `addi rX, rY, 0` but your code has "
                    "`mr rX, rY`, insert a dead statement like `!gobj;` "
                    "or `(void) gobj;` between the assignment and use."
                ),
                success_rate=0.6,
            ),
            Fix(
                description=(
                    "Alternative: skip the temporary and pass the function "
                    "call's result directly. The peephole optimization is "
                    "context-sensitive — fewer intermediate values = less "
                    "peephole work."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["addi", "mr"],
        categories=["register"],
        provenance=Provenance(),
        related_patterns=["loop-variable-copy-pattern-addi-rx-ry-0-instead-of-li"],
        notes="Source: mwcc-debugger research, Discord knowledge base.",
    ),
    Pattern(
        id="extern-vs-literal-fcmpu-operand-order",
        name="`extern float` reverses `fcmpu` operand order vs literal `0.0f`",
        description=(
            "When comparing a float against `0.0f`, using an `extern float "
            "lbl_X = 0.0f` global produces a DIFFERENT `fcmpu` operand "
            "order than using a literal `0.0f` directly. Use the extern "
            "form when the target's fcmpu has the constant on the OTHER "
            "side from what literal would produce."
        ),
        root_cause=(
            "Literal `0.0f` is loaded into a fresh FP register at compare "
            "time. Extern float is loaded earlier via @sda21 and lives in "
            "a different register. The comparison `fcmpu cr, fA, fB` "
            "operand order reflects which register holds which value."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "fcmpu cr0, f1, f4", "actual": "fcmpu cr0, f4, f1"},
                description="fcmpu operand order swapped",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// Literal 0.0f:\n"
                    "if (0.0f == f4) { ... }  // fcmpu cr0, f0, f4 (literal loaded into f0)\n"
                ),
                after=(
                    "// Extern global declared at file scope:\n"
                    "extern float lbl_804D7AA8;  // = 0.0f in .sdata\n"
                    "\n"
                    "if (lbl_804D7AA8 == f4) { ... }  // different operand order\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When fcmpu operands are swapped vs your code, try "
                    "switching between literal `0.0f` and an extern float "
                    "global. The extern form loads the value earlier and "
                    "into a different register."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["fcmpu", "lfs"],
        categories=["float", "branch"],
        provenance=Provenance(),
        related_patterns=["float-comparison-sign", "comparison-operand-order-load-order"],
    ),
    Pattern(
        id="fcmpo-vs-fcmpu-combined-equality",
        name="`fcmpo` + `cror` for combined float comparisons; switch `==` to `<=`",
        description=(
            "When target shows `fcmpo` (ordered float compare) plus `cror` "
            "(condition register OR), the comparison combines multiple "
            "tests. A common case: `<=` test compiles to `fcmpo` + "
            "`cror eq, gt`. If you wrote `==` but target has `<=`, switch."
        ),
        root_cause=(
            "PPC's float compares set multiple bits in the condition "
            "register (lt, gt, eq, un). `fcmpo` traps on NaN; `fcmpu` "
            "doesn't. `<=` is implemented as `lt OR eq`, joining two "
            "condition bits via `cror`. `==` alone uses just the eq bit "
            "without cror."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "fcmpo", "actual": "fcmpu"},
                description="Ordered vs unordered float compare",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["fcmpo", "cror"]},
                description="Ordered compare combined with cror for <=/>=",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// == alone: fcmpu + beq (no cror)\n"
                    "if (x == 0.0f) { ... }\n"
                ),
                after=(
                    "// <= matches fcmpo + cror pattern:\n"
                    "if (x <= 0.0f) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `fcmpo` + `cror`, switch float "
                    "comparison from `==` to `<=` (or `>=`). The cror "
                    "joins two condition bits, indicating a compound test."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["fcmpo", "fcmpu", "cror"],
        categories=["float", "branch"],
        provenance=Provenance(),
        related_patterns=["float-comparison-sign"],
    ),
    Pattern(
        id="asm-disables-peephole-rest-of-file",
        name="`asm` block disables peephole for the rest of the file (MWCC 1.0-1.2.5 bug)",
        description=(
            "Using an `asm { ... }` block in MWCC 1.0-1.2.5 (Melee's "
            "compiler) silently disables peephole optimization for ALL "
            "FUNCTIONS DEFINED AFTER it in the file. This causes `bnelr` "
            "to become `bne` + `b` (separate instructions), among other "
            "regressions. Fix with `#pragma peephole on` after the asm block."
        ),
        root_cause=(
            "Bug in MWCC's flag handling: `asm` resets the peephole flag "
            "globally for the rest of the TU. The bug was fixed in 1.3.2-2.7 "
            "but Melee uses 1.2.5n. Workaround is to explicitly re-enable "
            "via pragma after every asm block."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bnelr", "actual": "bne+b"},
                description="Single peephole-merged branch-return vs separate instructions",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// peephole is ON for blahblah\n"
                    "void blahblah(void) { ... }\n"
                    "\n"
                    "// asm block disables peephole for rest of file:\n"
                    "asm void blahasmblah(void) { nop }\n"
                    "\n"
                    "// peephole is OFF for blahblah2 — bnelr becomes bne+b\n"
                    "void blahblah2(void) { ... }\n"
                ),
                after=(
                    "void blahblah(void) { ... }\n"
                    "\n"
                    "asm void blahasmblah(void) { nop }\n"
                    "\n"
                    "#pragma peephole on   // restore!\n"
                    "void blahblah2(void) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "After every `asm { ... }` block or `asm void func()` "
                    "definition in the TU, add `#pragma peephole on` to "
                    "restore the optimization for subsequent functions."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["bnelr", "blr", "bne", "b"],
        categories=["control-flow", "data-layout"],
        provenance=Provenance(),
    ),
    Pattern(
        id="crclr-6-vs-crset-6-variadic-float-marker",
        name="`crclr 6` / `crset 6` flags float-arg presence for variadic calls",
        description=(
            "PPC ABI: when calling a variadic function (like `printf`), the "
            "caller sets condition register bit 6 to indicate whether any "
            "float arguments are passed. `crset 6` = has float args, "
            "`crclr 6` = no float args. The variadic callee uses this to "
            "decide whether to save f1-f8 to stack."
        ),
        root_cause=(
            "PPC variadic ABI: float args in FPRs are not visible to "
            "`va_list` traversal unless the callee knows they're there. "
            "CR bit 6 acts as a flag from caller to callee. MWCC emits "
            "`crset 6` for any variadic call with at least one float arg, "
            "`crclr 6` for all-integer variadic calls."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "crset 6", "actual": "crclr 6"},
                description="Float-arg marker flipped",
            ),
            Signal(
                type="extra_instruction",
                data={"opcode": "crclr", "context": "variadic call prefix"},
                description="Unexpected crclr/crset around a variadic call",
            ),
        ],
        examples=[
            Example(
                function="generic OSReport call",
                before=(
                    "// No float args — emits crclr 6:\n"
                    "OSReport(\"value = %d\\n\", count);\n"
                ),
                after=(
                    "// Float arg — emits crset 6:\n"
                    "OSReport(\"value = %f\\n\", (f64) val);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If your variadic call has `crclr 6` but target has "
                    "`crset 6`, add a (possibly synthetic) float argument. "
                    "Often this means a missing `%f` format specifier with "
                    "its corresponding f64 argument."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Inverse: if target has `crclr 6` but you emit `crset 6`, "
                    "you have an extra float argument or you're passing an "
                    "int as float by accident."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["crclr", "crset"],
        categories=["calling-conv", "float"],
        provenance=Provenance(),
        related_patterns=["variadic-function-va-list-offset"],
    ),
    Pattern(
        id="volatile-prevents-inlining",
        name="`volatile` local makes a function essentially non-inlinable",
        description=(
            "A `volatile` local variable inside a function usually prevents "
            "MWCC from inlining that function into callers. Useful as a "
            "side-channel way to inhibit inlining without pragmas or shims."
        ),
        root_cause=(
            "Volatile semantics require the variable's memory accesses to "
            "happen as written, including stack allocation. Inlining the "
            "function into a caller would require preserving those access "
            "semantics in the caller's stack frame, which MWCC declines to "
            "do (conservatively)."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl func", "actual": "<inlined body>"},
                description="Function call expected but body inlined",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "static int small_func(int x) {\n"
                    "    return x * 2 + 1;  // gets auto-inlined\n"
                    "}\n"
                ),
                after=(
                    "static int small_func(int x) {\n"
                    "    volatile int y = x * 2 + 1;\n"
                    "    return y;  // not inlined\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If a small same-TU function keeps getting inlined, add "
                    "a `volatile` local to its body. Less invasive than "
                    "`#pragma dont_inline` and works even where the "
                    "`_dontinline` shim trick fails."
                ),
                success_rate=0.7,
            ),
            Fix(
                description=(
                    "Prefer `_dontinline` shim or `#pragma auto_inline off` "
                    "as primary methods — `volatile` adds the side effect "
                    "of forcing a stack spill, which may cause other "
                    "mismatches."
                ),
            ),
        ],
        opcodes=["bl"],
        categories=["inline", "calling-conv"],
        provenance=Provenance(),
        related_patterns=[
            "static-inline-dontinline-wrapper",
            "pragma-dont-inline-block",
            "static-inline-volatile-stack-spill",
        ],
    ),
    Pattern(
        id="float-bit-manipulation-hi-lo-macros",
        name="`__HI(x)` / `__LO(x)` for float-as-int bit manipulation",
        description=(
            "MWCC's MSL provides `__HI(x)` and `__LO(x)` macros to access "
            "the high and low 32 bits of an f64 (or 32 bits of f32) "
            "directly as int. Used for sign-bit flipping, exponent "
            "manipulation, and ULP-precise float ops. Compiles to "
            "`stfs`/`lwz` (or `stfd`/`lwz` for f64)."
        ),
        root_cause=(
            "The macros expand to `*(1+(int*)&x)` (high word) and "
            "`*(int*)&x` (low word). MWCC sees the address-taken and "
            "spills to stack, then reloads as int via `lwz`. The "
            "byte-level form `__HI(x) = newhi;` updates the high word "
            "directly in memory."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["stfs", "lwz"]},
                description="Float stored to stack, loaded as int",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["stfd", "lwz"]},
                description="f64 stored, high or low word loaded as int",
            ),
        ],
        examples=[
            Example(
                function="generic float bit manipulation",
                before=(
                    "// Manual bit manipulation via union — may not match:\n"
                    "union { f32 f; u32 i; } u;\n"
                    "u.f = x;\n"
                    "u.i &= 0x7FFFFFFF;\n"
                    "x = u.f;\n"
                ),
                after=(
                    "// __HI/__LO macros — direct stack roundtrip:\n"
                    "f32 x = ...;\n"
                    "__LO(x) &= 0x7FFFFFFF;  // clear sign bit\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows `stfs`+`lwz` (or `stfd`+`lwz`) "
                    "for float bit manipulation, use `__HI(x)`/`__LO(x)` "
                    "macros from MSL's math headers. Don't use union or "
                    "pointer casts."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["stfs", "stfd", "lwz"],
        categories=["float", "type", "data-layout"],
        provenance=Provenance(),
        notes=(
            "Definitions from MSL: "
            "`#define __HI(x) *(1+(int*)&x)`, "
            "`#define __LO(x) *(int*)&x`. "
            "Used in fdlibm and other portable math libraries."
        ),
    ),
    Pattern(
        id="float-args-use-fpr-not-r3",
        name="Float parameters use FPRs (f1-f13), not GPRs (r3-r10)",
        description=(
            "PPC ABI: float parameters go in f1-f13 (NOT f0). Integer "
            "parameters go in r3-r10. They DON'T mix or shift: position-"
            "based, not interleaved. Changing a parameter's type between "
            "int and float doesn't push other args to different registers, "
            "but it does change which call-site setup instructions emit."
        ),
        root_cause=(
            "PPC ABI specifies separate FPR and GPR parameter banks. "
            "Position in C signature maps to position in each bank "
            "independently. `f0` is reserved (not used for params); first "
            "float arg is `f1`, second is `f2`, etc."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stfd f1", "actual": "stw r4"},
                description="Float arg in FPR vs GPR",
            ),
        ],
        examples=[
            Example(
                function="generic",
                context=(
                    "Float position in signature doesn't affect int register "
                    "usage. `void func(int a, float b, int c)` uses "
                    "r3=a, r4=c, f1=b — c stays in r4 even though b "
                    "appears between."
                ),
                after=(
                    "// Reorganizing function signature:\n"
                    "void func(int a, float b, int c);\n"
                    "// r3 = a, f1 = b, r4 = c\n"
                    "\n"
                    "void func(int a, int c, float b);\n"
                    "// r3 = a, r4 = c, f1 = b — same register usage!\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Float parameter order doesn't affect int register "
                    "usage and vice versa. You can freely reorder them "
                    "in the signature for matching purposes if it helps "
                    "the call site."
                ),
                success_rate=0.8,
            ),
            Fix(
                description=(
                    "Remember: `f0` is NOT a parameter register. First "
                    "float arg is `f1`, not `f0`. If your code passes a "
                    "float via `f0`, the signature is wrong."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=[],
        categories=["calling-conv", "float"],
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
