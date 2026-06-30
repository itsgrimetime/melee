"""
Part 5: floating-point matching patterns from agent analysis.

Discovered by surveying lb_00F9.c, groldkongo.c, mncharsel.c, it_2725.c,
lbrefract.c, ftCo_0A01.c, and the MSL math headers.
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
        id="float-promotion-via-f64-cast",
        name="Explicit `(f64)` cast forces f64-precision intermediate (no early `frsp`)",
        description=(
            "Adding `(f64)` to one operand of an f32 expression keeps the "
            "multiply/add in f64 registers, avoiding an early `frsp` "
            "(round-to-single-precision). The compiler defers `frsp` to the "
            "final `(f32)` cast. Used when math involves f64 constants like "
            "M_PI/M_TAU where intermediate precision matters."
        ),
        root_cause=(
            "Without the cast, MWCC rounds each sub-expression to f32 as "
            "soon as possible. With `(f64)` on one operand, the whole "
            "expression stays in f64 until the final cast. Different "
            "rounding produces different bits at the end."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "fmul", "actual": "fmuls"},
                description="Target uses f64 multiply; your code uses f32",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "lfd", "actual": "lfs"},
                description="Target loads f64 constant from .rodata; your code loads f32",
            ),
            Signal(
                type="extra_instruction",
                data={"opcode": "frsp", "context": "premature rounding"},
                description="Extra frsp in your code before final cast",
            ),
        ],
        examples=[
            Example(
                function="lb_00F9.c stiff angle",
                context="lb_00F9.c — single (f64) cast keeps the multiply in f64",
                after=(
                    "// Cast forces f64 intermediate, frsp only at final (f32):\n"
                    "result = stiff_angle * (f32) (1.0 - (f64) (cur->desc.unk_4C * desc->pos.x));\n"
                    "// And:\n"
                    "result = (f32) (0.1 + (f64) collider->radius);\n"
                ),
            ),
            Example(
                function="groldkongo.c angle wrap",
                context="groldkongo.c:435 — wrap angle by M_TAU in f64",
                after=(
                    "angle = (f32) ((f64) temp_f2 - M_TAU);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target uses `fmul`/`fadd` (f64) but your code uses "
                    "`fmuls`/`fadds` (f32), add `(f64)` cast to one operand of "
                    "the expression. Wrap the whole computation in a final "
                    "`(f32)` cast."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Mostly applies to expressions involving M_PI/M_TAU/other "
                    "f64 constants from <math.h>. The constants are f64 in "
                    "the header, so the calculation should stay in f64."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["fmul", "fmuls", "fadd", "fadds", "frsp"],
        categories=["float", "type"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lb_00F9.c stiff angle calculations"),
                ProvenanceEntry(function="groldkongo.c angle wrap"),
            ],
        ),
    ),
    Pattern(
        id="f64-literal-no-f-suffix-rodata",
        name="f64 literal (no `f` suffix) drives `lfd` from .rodata instead of immediate",
        description=(
            "A bare floating-point literal like `3.141592653589793` (no `f` "
            "suffix) is f64 and gets placed in .rodata, loaded via `lfd`. "
            "Adding the `f` suffix (`3.14f`) creates an f32 immediate or "
            ".rodata f32 entry. When target shows `lfd` for a constant, the "
            "C source must use bare (or `f64`/`double`) literal."
        ),
        root_cause=(
            "C standard: bare floating literal is `double` (f64). Suffix `f` "
            "makes it `float` (f32). MWCC places f64 literals in .rodata as "
            "8-byte entries, loaded via `lfd`. f32 literals use `lfs` or are "
            "inlined as immediates."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lfd", "actual": "lfs"},
                description="f64 load expected; your code uses f32 load",
            ),
        ],
        examples=[
            Example(
                function="mncharsel.c angle base",
                context=(
                    "mncharsel.c — declares `f64 base_a` and assigns it from "
                    "bare f64 literal, then casts to f32 at the end."
                ),
                after=(
                    "f64 base_a;\n"
                    "if (dy < 0.0f) {\n"
                    "    base_a = 0.0;\n"
                    "} else {\n"
                    "    base_a = 3.141592653589793;  // bare = f64\n"
                    "}\n"
                    "angle = (f32) (base_a + atanf(dx / dy));\n"
                ),
            ),
            Example(
                function="groldkongo.c M_PI_2 add",
                context="groldkongo.c:558 — explicit f64 add via bare literal",
                after=(
                    "result = (f32) (1.5707963267948966 + (f64) temp_r31->gv.arwing.xDC);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target loads a float constant via `lfd` (f64 load), "
                    "the C source must use a bare floating literal "
                    "(`3.14159`, not `3.14159f`). Combine with `(f64)` casts "
                    "or `f64`/`double` local variables to keep the math in "
                    "f64 width."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lfd", "lfs"],
        categories=["float", "type", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mncharsel.c angle math"),
                ProvenanceEntry(function="groldkongo.c arwing math"),
            ],
        ),
        related_patterns=["float-promotion-via-f64-cast"],
    ),
    Pattern(
        id="static-const-f64-named-rodata",
        name="`static const f64 name = 0.5;` for named .rodata constant",
        description=(
            "Declaring a TU-scope `static const f64` (or `double`) variable "
            "puts the constant in .data/.rodata under a NAMED symbol, "
            "accessed via `@sda21` relocations. Different from bare literals "
            "which produce anonymous .rodata entries. Use when target loads "
            "a 0.5 or 3.0 constant via a named symbol relocation."
        ),
        root_cause=(
            "MWCC places named static const f64 variables into the SDA "
            "section (similar to .sdata for small writable globals, but "
            "read-only). Anonymous literals go to .rodata (general). The "
            "relocation type differs: named → `@sda21`, anonymous → "
            "`@rtoc`/`@l`/`@ha` pair."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "@sda21 reloc", "actual": "@rtoc reloc"},
                description="Named SDA constant vs anonymous .rodata",
            ),
        ],
        examples=[
            Example(
                function="it_2725.c half constant",
                context=(
                    "it_2725.c — declares `static const f64 it_804DC7F8 = 0.5f;` "
                    "at file scope and uses it via SDA relocation."
                ),
                after=(
                    "static const f64 it_804DC7F8 = 0.5f;\n"
                    "\n"
                    "void func(void)\n"
                    "{\n"
                    "    f32 r = HSD_Randf() - it_804DC7F8;  // lfd via @sda21\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target loads a constant 0.5/3.0/etc. via "
                    "`lfd fX, name@sda21(r13)` with a NAMED symbol, declare "
                    "`static const f64 name = 0.5f;` at file scope. The name "
                    "must match what's in symbols.txt."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lfd"],
        categories=["float", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="it_2725 file-scope constant"),
            ],
        ),
        related_patterns=["newton-raphson-sqrt-inline"],
    ),
    Pattern(
        id="fnmsubs-explicit-intrinsic",
        name="Use `__fnmsubs(a, b, c)` intrinsic for fused negate-multiply-subtract",
        description=(
            "MWCC's `__fnmsubs` intrinsic produces a single `fnmsubs` "
            "instruction. Writing it as `c - a*b` (or `-(a*b - c)`) MAY "
            "compile to the same single instruction, but sometimes MWCC "
            "emits separate `fmuls` + `fsubs`. Use the explicit intrinsic "
            "to force the fused form."
        ),
        root_cause=(
            "MWCC's instruction fusion is heuristic — context-dependent. "
            "Source-level `c - a*b` may or may not fuse. The intrinsic from "
            "`MetroTRK/intrinsics.h` (`__fnmadds`, `__fnmsubs`, `__fmadds`, "
            "`__fmsubs`) explicitly requests the fused instruction."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "fnmsubs", "actual": "fmuls"},
                description="Single fused instruction expected; got separate mul+sub",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["fmuls", "fsubs"]},
                description="Unfused mul+sub instead of fused fnmsubs",
            ),
        ],
        examples=[
            Example(
                function="lbrefract.c lookup",
                context=(
                    "lbrefract.c:903 — explicit intrinsic forces fused codegen"
                ),
                after=(
                    "result = __fnmsubs(result, lookup_ptr[7], offset_33) +\n"
                    "         __fnmsubs(result, lookup_ptr[13], offset_39);\n"
                ),
                before=(
                    "// Source-level may not fuse:\n"
                    "result = (offset_33 - result * lookup_ptr[7]) +\n"
                    "         (offset_39 - result * lookup_ptr[13]);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows `fnmsubs`/`fmsubs`/`fnmadds`/`fmadds` "
                    "but your code emits separate multiply+add/sub, replace "
                    "with the explicit intrinsic from `MetroTRK/intrinsics.h`."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Intrinsic signatures: "
                    "`__fmadds(a, b, c)` → a*b + c, "
                    "`__fmsubs(a, b, c)` → a*b - c, "
                    "`__fnmadds(a, b, c)` → -(a*b + c), "
                    "`__fnmsubs(a, b, c)` → -(a*b - c) = c - a*b."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["fnmsubs", "fmsubs", "fnmadds", "fmadds"],
        categories=["float"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbrefract lookup math"),
            ],
        ),
        related_patterns=["newton-raphson-sqrt-inline"],
    ),
    Pattern(
        id="float-to-int-cast-fctiwz-stack-roundtrip",
        name="Float-to-int cast emits `fctiwz` + 8-byte stack roundtrip + `lwz`",
        description=(
            "Any `(s32) f`, `(int) f`, or int-returning expression involving "
            "a float (like `return 127.0F * cosf(angle)`) emits "
            "`fctiwz f0, fN` + `stfd f0, OFFSET(r1)` + `lwz rN, OFFSET+4(r1)`. "
            "The +4 offset is because PPC stores the 32-bit int in the LOW "
            "word of the f64 stack slot. This pattern always consumes 8 "
            "bytes of stack."
        ),
        root_cause=(
            "PPC has no direct float-to-int register move. `fctiwz` writes "
            "the result to an FP register as f64 (with the int in the low "
            "32 bits). To get it into a GPR, you must store to memory and "
            "load. The 8-byte alignment requirement makes this consume "
            "8 bytes of stack even for a 4-byte int."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["fctiwz", "stfd", "lwz"]},
                description="Float-to-int conversion via stack",
            ),
            Signal(
                type="offset_delta",
                data={"register": "r1", "delta": 8},
                description="Stack frame +8 bytes per float-to-int cast",
            ),
        ],
        examples=[
            Example(
                function="angle_x_units (ftCo_0A01.c)",
                context=(
                    "Returns int from float expression. The conversion adds "
                    "8 bytes to the helper's stack frame."
                ),
                after=(
                    "static inline int angle_x_units(float angle)\n"
                    "{\n"
                    "    return 127.0F * cosf(angle);\n"
                    "    // fctiwz f0, fN\n"
                    "    // stfd f0, OFFSET(r1)   ; 8-byte slot\n"
                    "    // lwz r3, OFFSET+4(r1)  ; low word of f64 slot\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Don't try register tricks for float-to-int casts. The "
                    "stack roundtrip is mandatory. If your stack frame is "
                    "off by 8 bytes, check whether you're missing or have an "
                    "extra `(int) <float>` cast somewhere."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Stack alignment matters: the `stfd` must land on an "
                    "8-byte-aligned offset. Your frame layout must reserve "
                    "the slot accordingly."
                ),
            ),
        ],
        opcodes=["fctiwz", "stfd", "lwz"],
        categories=["float", "type", "stack"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="angle_x_units"),
            ],
        ),
    ),
    Pattern(
        id="fsel-from-ternary-float-select",
        name="Ternary float-select compiles to `fsel`",
        description=(
            "`a > 0.0f ? x : y` compiles to a single `fsel` (float-select) "
            "instruction when both `x` and `y` are already in fp registers. "
            "If you wrote `if (a > 0) result = x; else result = y;` explicitly, "
            "MWCC may emit a branch instead of `fsel`."
        ),
        root_cause=(
            "MWCC recognizes the ternary-with-fp-select pattern and emits "
            "the branchless `fsel`. If-else with explicit assignments may "
            "or may not get the same optimization depending on surrounding "
            "context."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "fsel", "actual": "<branch + assignment>"},
                description="Branchless fsel vs branch-and-assign",
            ),
        ],
        examples=[
            Example(
                function="generic float clamp",
                before=(
                    "// If-else may emit branch:\n"
                    "if (x > 0.0f) {\n"
                    "    result = a;\n"
                    "} else {\n"
                    "    result = b;\n"
                    "}\n"
                ),
                after=(
                    "// Ternary forces fsel:\n"
                    "result = (x > 0.0f) ? a : b;\n"
                ),
            ),
            Example(
                function="inlineB0 clamp helper (ftCo_0A01.c)",
                context="Chained ternary for triple-condition clamp",
                after=(
                    "static inline float inlineB0(s8 val, float a, float b)\n"
                    "{\n"
                    "    float ret = val > 0 ? val / a : val / b;\n"
                    "    return ret > +1.0 ? +1.0F\n"
                    "         : ret < -1.0 ? -1.0F\n"
                    "         : ret;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows `fsel` but your code branches: rewrite "
                    "as a ternary `cond ? a : b`. The expression's operands "
                    "should be plain values or simple sub-expressions (not "
                    "function calls with side effects)."
                ),
                success_rate=0.8,
            ),
            Fix(
                description=(
                    "Chain ternaries for `clamp(x, lo, hi)` style: "
                    "`x > hi ? hi : x < lo ? lo : x`. Each level emits its "
                    "own `fsel`."
                ),
                success_rate=0.75,
            ),
        ],
        opcodes=["fsel"],
        categories=["float", "branch", "control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="inlineB0 (ftCo_0A01)"),
            ],
        ),
        related_patterns=["static-inline-helper-numeric-idiom"],
    ),
    Pattern(
        id="fnabs-for-negate-abs",
        name="`fnabs` for `-fabs(x)` (negative absolute value)",
        description=(
            "PowerPC has a `fnabs` instruction (float-negative-absolute-value) "
            "that produces `-|x|` in one instruction. MWCC emits it for "
            "expressions like `-fabsf(x)` or `x > 0 ? -x : x`. If the target "
            "shows `fnabs` but your code uses `fabs`+`fneg`, rewrite to make "
            "the negation explicit."
        ),
        root_cause=(
            "`fnabs rD, rS` sets bit 0 (sign bit) regardless of input sign. "
            "Cheap one-instruction primitive. MWCC recognizes "
            "`-fabsf(x)` and emits this directly. Other forms may take two "
            "instructions."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "fnabs", "actual": "fabs"},
                description="Single negate-abs vs two-instruction abs+negate",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "// Both produce fnabs:\n"
                    "result = -fabsf(x);\n"
                    "// Or:\n"
                    "result = (x > 0) ? -x : x;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `fnabs`, write `-fabsf(x)` in C. "
                    "Don't manually negate after `fabs`."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["fnabs", "fabs", "fneg"],
        categories=["float"],
        provenance=Provenance(),
        related_patterns=["abs-fabs-macro-usage"],
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
