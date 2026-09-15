"""
Part 4: comparison and branch patterns from agent analysis.

These were discovered by surveying mnname.c, mndiagram*.c, mnevent.c,
gm_16AE.c, and Discord knowledge archives for distinct comparison/branch
codegen tricks.
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
        id="comparison-operand-order-load-order",
        name="Comparison operand order controls load ordering and register choice",
        description=(
            "`if (A == B)` and `if (B == A)` are semantically identical but "
            "MWCC emits the load of the LEFT operand first, into a lower "
            "scratch register. When you have a register swap mismatch and one "
            "operand is a global or constant, flipping the comparison can "
            "shift the load order to match."
        ),
        root_cause=(
            "MWCC evaluates expression operands left-to-right by default. The "
            "left operand of `==` (or `!=`, `<`, etc.) is loaded first into "
            "r0/r3, then the right operand. The `cmpw rX, rY` emitted uses "
            "the same operand order as the C source."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "cmpw r0,r3", "actual": "cmpw r3,r0"},
                description="Register order in cmpw is swapped",
            ),
        ],
        examples=[
            Example(
                function="mnname.c name compare",
                context=(
                    "mnname.c:248 — putting the terminator constant on the "
                    "LEFT forces it to load into r0 first."
                ),
                before=(
                    "// Variable first, constant second:\n"
                    "if ((s8) GetPersistentNameData((u8) slot)->namedata[0] == mnName_StringTerminator) {\n"
                    "    // ...\n"
                    "}\n"
                ),
                after=(
                    "// Constant first, variable second — matches target's r0/r3 order:\n"
                    "if (mnName_StringTerminator == (s8) GetPersistentNameData((u8) slot)->namedata[0]) {\n"
                    "    // ...\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When `cmpw r0, r3` and `cmpw r3, r0` are swapped (and "
                    "one operand is a global/constant), flip the comparison's "
                    "operand order in C. The compiler emits `cmpw rL, rR` "
                    "in the same order as the C operands."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["cmpw", "cmpwi"],
        categories=["branch", "register", "control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnname IsNameUnique"),
            ],
        ),
    ),
    Pattern(
        id="extsb-cmpw-for-signed-char-compare",
        name="`extsb` + `cmpw` for signed-char comparisons (cast both sides to `s8`)",
        description=(
            "Comparing two byte values as signed produces `lbz` + `extsb r,r` "
            "(sign-extend byte) + `cmpw` (signed compare). Both operands need "
            "sign extension, even constants. Unsigned char compare uses "
            "`cmplwi` directly without `extsb`."
        ),
        root_cause=(
            "`cmpw` requires 32-bit signed operands. Bytes loaded by `lbz` "
            "are zero-extended. To get signed semantics, MWCC inserts `extsb` "
            "before the compare. The signedness is determined by both "
            "operands' types; if either is unsigned, the whole compare is "
            "unsigned."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lbz", "extsb", "cmpw"]},
                description="Load byte, sign-extend, signed compare",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "extsb", "actual": "<missing>"},
                description="Target sign-extends but your code doesn't",
            ),
        ],
        examples=[
            Example(
                function="mnname.c char compare",
                context="mnname.c — cast both sides to `s8` for signed compare",
                before=(
                    "// u8 vs u8 — uses cmplwi:\n"
                    "if (data->namedata[0] == 0xFF) { ... }\n"
                ),
                after=(
                    "// s8 vs s8 — uses extsb + cmpw:\n"
                    "if ((s8) data->namedata[0] == (s8) 0xFF) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `extsb` before a compare, cast BOTH "
                    "operands to `s8` (or `signed char`). Both sides need "
                    "the cast — casting only one still produces unsigned "
                    "codegen."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Inverse: if target has `cmplwi` (no extsb), keep the "
                    "operands as `u8` and avoid casts to signed types."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["extsb", "cmpw", "lbz"],
        categories=["type", "branch"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnname IsNameUnique"),
            ],
        ),
        related_patterns=["u8-parameter-mask-clrlwi"],
    ),
    Pattern(
        id="short-circuit-and-shared-exit-label",
        name="`&&` short-circuit chains vs nested `if` for shared exit labels",
        description=(
            "Long `if (a() && b() && c())` short-circuit chains collapse to "
            "one branch chain in asm: each `cmpwi r3, 0` + "
            "`beq <shared_label>`. Same instruction count as nested "
            "`if(a) if(b) if(c)` BUT `&&` always branches to the SAME exit "
            "label while nested ifs can have separate fall-through paths. "
            "Choose form based on whether all failures go to the same code."
        ),
        root_cause=(
            "MWCC compiles `&&` as a chain of conditional branches to a "
            "single label. Nested `if` lets each level fall through to "
            "different code. When the asm shows a single shared exit, use "
            "`&&`; when it shows distinct exits, use nested ifs."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["bl", "cmpwi", "beq", "bl", "cmpwi", "beq"]},
                description="Repeated call+test+branch to same label",
            ),
        ],
        examples=[
            Example(
                function="mnevent.c (11-call chain)",
                context=(
                    "mnevent.c:63-72 — 11 chained calls all branching to one "
                    "shared exit (`.L_8024CFF0`)."
                ),
                after=(
                    "if (init_a() && init_b() && init_c() && init_d() && init_e() &&\n"
                    "    init_f() && init_g() && init_h() && init_i() && init_j() && init_k())\n"
                    "{\n"
                    "    success();\n"
                    "} else {\n"
                    "    cleanup();\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use `&&` when ALL failure paths from the chain go to the "
                    "same code (single shared exit label in asm). Use nested "
                    "`if` when each level has a different fall-through (multiple "
                    "exits in asm)."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["beq", "bne", "cmpwi"],
        categories=["branch", "control-flow"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnEvent_8024CE74"),
            ],
        ),
    ),
    Pattern(
        id="explicit-zero-compare-vs-bang-operator",
        name="`if (x == 0)` vs `if (!x)` — same asm but match m2c style",
        description=(
            "`if (x == 0)` and `if (!x)` produce IDENTICAL asm (`cmpwi r,0` + "
            "`beq/bne`). The difference is source style: m2c emits explicit "
            "`== 0` / `!= 0`. Preserving that style avoids accidental "
            "polarity flips when refactoring."
        ),
        root_cause=(
            "Semantically equivalent. Codegen is identical. But when working "
            "with m2c output that uses `!= 0` everywhere, switching to `!` "
            "form mid-refactor risks introducing typos that flip branch "
            "polarity. Keep the m2c style verbatim."
        ),
        signals=[],
        examples=[
            Example(
                function="mnname.c sort",
                context="mnname.c:326,335,350 use explicit `== 0` style from m2c",
                after=(
                    "// m2c-style:\n"
                    "if (result == 0) {\n"
                    "    /* ... */\n"
                    "} else {\n"
                    "    goto next_iter;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When working from m2c output, preserve `== 0` / `!= 0` "
                    "comparisons rather than converting to `!` / implicit "
                    "truthy. Both forms compile identically but the explicit "
                    "form is less error-prone during refactoring."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=["cmpwi"],
        categories=["control-flow", "branch"],
        provenance=Provenance(),
        notes="Style preference, not a codegen fix.",
    ),
    Pattern(
        id="range-check-addi-negative-cmplwi",
        name="`addi rX, rY, -N` + `cmplwi` for unsigned range check",
        description=(
            "An OR-chain like `if (n == 6 || n == 7)` may compile to "
            "`addi r0, rN, -6` + `cmplwi r0, 1`, using the unsigned range "
            "trick `(u32)(n - LO) <= (HI - LO)`. If you see this asm but "
            "wrote a switch or other form, rewrite as an explicit OR-chain "
            "of equality checks."
        ),
        root_cause=(
            "MWCC recognizes small ranges and emits the subtract+unsigned-"
            "compare optimization. The trick exploits that "
            "`(u32)(n - 6) <= 1` is true iff n is 6 or 7 (and underflow for "
            "n < 6 wraps to a large u32 which fails the <= 1 test)."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["addi", "cmplwi"]},
                description="addi with negative constant followed by cmplwi",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "addi", "actual": "<multiple cmpwi>"},
                description="Single range check vs multiple equality compares",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// switch generates multiple cmpwi:\n"
                    "switch (n) {\n"
                    "    case 6:\n"
                    "    case 7:\n"
                    "        do_stuff();\n"
                    "        break;\n"
                    "}\n"
                ),
                after=(
                    "// OR-chain generates addi -6 + cmplwi 1:\n"
                    "if (n == 6 || n == 7) {\n"
                    "    do_stuff();\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When you see `addi rX, rY, -N` + `cmplwi rX, K` in the "
                    "target, rewrite the C as an OR-chain of equality checks: "
                    "`if (n == N || n == N+1 || ... || n == N+K)`. Switch "
                    "statements emit `cmpwi` (signed) per case instead."
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "For wider ranges, `(unsigned)(n - LO) <= (HI - LO)` is "
                    "the equivalent C expression that maps directly to this "
                    "asm pattern."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["addi", "cmplwi"],
        categories=["branch", "control-flow"],
        provenance=Provenance(),
    ),
    Pattern(
        id="cmplwi-vs-cmpwi-implies-pointer-type",
        name="`cmplwi r,0` implies pointer; `cmpwi r,0` implies int (diagnostic)",
        description=(
            "When the target uses `cmplwi rX, 0` (unsigned compare) for a "
            "null check, the operand is likely a pointer type. When it uses "
            "`cmpwi rX, 0` (signed), the operand is likely `int`/`s32`. "
            "Switch statements always emit `cmpwi` even on `u32` operands. "
            "Use this to infer C types from asm during decompilation."
        ),
        root_cause=(
            "MWCC picks signed/unsigned compare opcode based on the C "
            "operand's type. Pointers are technically unsigned but compared "
            "with `cmplwi`. Plain `int`/`s32` use `cmpwi`. The choice is "
            "stable across MWCC versions and a reliable type signal."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "cmplwi", "actual": "cmpwi"},
                description="Unsigned vs signed compare; operand type mismatched",
            ),
        ],
        examples=[
            Example(
                function="diagnostic",
                context=(
                    "If asm has `cmplwi r3, 0` + `beq`, the C should be "
                    "`if (ptr != NULL)` with a pointer type. If `cmpwi r3, 0`, "
                    "use `if (i != 0)` with an int type."
                ),
                after=(
                    "// cmplwi rX, 0 in target -> pointer:\n"
                    "if (ptr != NULL) { ... }\n"
                    "\n"
                    "// cmpwi rX, 0 in target -> int:\n"
                    "if (count != 0) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use the compare opcode as a type signal during initial "
                    "decomp: `cmplwi`/`cmplw` → unsigned (often pointer); "
                    "`cmpwi`/`cmpw` → signed int. Switch statements are the "
                    "exception — always `cmpwi`."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["cmplwi", "cmpwi", "cmplw", "cmpw"],
        categories=["type", "branch"],
        provenance=Provenance(),
        notes="Diagnostic pattern — useful for type inference, not a fix.",
    ),
    Pattern(
        id="dead-callback-load-forces-null-check",
        name="Dead-load callback expression to force null-check codegen position",
        description=(
            "When dispatching a callback that was assigned earlier, sometimes "
            "you need a 'dead' statement like `(void) cb_func;` or a no-op "
            "reference before the actual `if (cb_func != NULL) cb_func(...)` "
            "call. This forces MWCC to keep the `cmplwi` + `beq` null check "
            "in the expected position. Without it, MWCC may collapse "
            "compare/branch into a later schedule."
        ),
        root_cause=(
            "MWCC's scheduler may move the null check or coalesce it with "
            "the load. A dead reference to the callback pins the load "
            "position, preserving the null-check position the target expects."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "cmplwi", "beq", "mtspr", "bctrl"]},
                description="Load, null-check, then call-through-pointer",
            ),
        ],
        examples=[
            Example(
                function="itemlogic callback dispatch",
                context=(
                    "Documented in Discord (ribbanya, 2023-01-13). Used in "
                    "item state callbacks where the function pointer was "
                    "loaded earlier in the function."
                ),
                before=(
                    "// Direct dispatch may collapse the null check:\n"
                    "if (item->cb != NULL) {\n"
                    "    item->cb(item);\n"
                    "}\n"
                ),
                after=(
                    "// Dead reference forces position:\n"
                    "cb = item->cb;\n"
                    "(void) cb;  // dead load to pin position\n"
                    "// ... other code ...\n"
                    "if (cb != NULL) {\n"
                    "    cb(item);\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When the null check position doesn't match, add a dead "
                    "reference to the callback variable (`(void) cb;` or "
                    "`!cb;` as a statement) just before the actual check. "
                    "The compiler keeps the load anchored to this point."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["lwz", "cmplwi", "beq"],
        categories=["calling-conv", "branch", "register"],
        provenance=Provenance(),
        notes="Discord-knowledge pattern from 2023-01-13.",
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
