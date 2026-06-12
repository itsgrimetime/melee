"""
Additional inline patterns - part 2.

Adds patterns for #pragma-based inline inhibition and a few more variants.
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
        id="pragma-dont-inline-block",
        name="`#pragma dont_inline on/reset` around function definitions",
        description=(
            "Compiler-directed alternative to `_dontinline` shims. Wrap a "
            "block of function definitions with `#pragma push` / "
            "`#pragma dont_inline on` ... `#pragma dont_inline reset` / "
            "`#pragma pop`. Functions defined inside the block will not be "
            "inlined by their callers AND will not inline their own callees. "
            "Best for small leaf functions that don't call HSD inline helpers."
        ),
        root_cause=(
            "MWCC's `-inline auto` would inline small same-TU functions. The "
            "`dont_inline` pragma disables auto-inlining for functions defined "
            "within its scope. CRUCIAL: this also disables the function from "
            "inlining ITS callees, so HSD_JObjSet* helpers (defined as "
            "`static inline` in baselib headers) won't be inlined either."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl", "actual": "<inlined body>"},
                description="Target has `bl func` but your code inlined `func`",
            ),
        ],
        examples=[
            Example(
                function="grHomeRun_8021C82C_noinline",
                context=(
                    "grhomerun.c — uses both pragma AND a `_noinline` shim. "
                    "The pragma wraps the shim definition; callers use the "
                    "shim. This is belt-and-suspenders."
                ),
                after=(
                    "#pragma push\n"
                    "#pragma dont_inline on\n"
                    "HSD_GObj* grHomeRun_8021C82C_noinline(int gobj_id);\n"
                    "\n"
                    "HSD_GObj* grHomeRun_8021C82C_noinline(int gobj_id)\n"
                    "{\n"
                    "    return grHomeRun_8021C82C(gobj_id);\n"
                    "}\n"
                    "#pragma dont_inline reset\n"
                    "#pragma pop\n"
                    "\n"
                    "HSD_GObj* grHomeRun_8021C82C(int gobj_id) { ... }\n"
                ),
            ),
            Example(
                function="grStadium_801D42B8",
                context="grpstadium.c — wraps the function being protected from inlining",
                after=(
                    "#pragma push\n"
                    "#pragma dont_inline on\n"
                    "bool grStadium_801D42B8(void)\n"
                    "{\n"
                    "    // ... function body ...\n"
                    "}\n"
                    "#pragma dont_inline reset\n"
                    "#pragma pop\n"
                ),
            ),
            Example(
                function="pl_800386D8",
                context=(
                    "plbonus.c — applied to small leaf functions returning "
                    "single array fields. These tiny functions would otherwise "
                    "auto-inline at every call site."
                ),
                after=(
                    "#pragma push\n"
                    "#pragma dont_inline on\n"
                    "unsigned int pl_800386D8(plActionStats* arg0, ssize_t arg1)\n"
                    "{\n"
                    "    return arg0->by_attack_hi[arg1];\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Wrap the function definition with "
                    "`#pragma push` / `#pragma dont_inline on` at top and "
                    "`#pragma dont_inline reset` / `#pragma pop` at bottom. "
                    "Use only when the function does NOT call HSD inline "
                    "helpers — `dont_inline` blocks BOTH directions."
                ),
                success_rate=0.8,
            ),
            Fix(
                description=(
                    "If function calls HSD inline helpers, use "
                    "`#pragma auto_inline off/on` instead. That blocks callers "
                    "from inlining the function, but the function can still "
                    "inline its own callees (HSD helpers)."
                ),
                before=(
                    "#pragma dont_inline on\n"
                    "void wrapper(HSD_JObj* jobj) {\n"
                    "    HSD_JObjSetTranslateX(jobj, 0);  // NOT inlined - bad!\n"
                    "}\n"
                ),
                after=(
                    "#pragma auto_inline off\n"
                    "void wrapper(HSD_JObj* jobj) {\n"
                    "    HSD_JObjSetTranslateX(jobj, 0);  // properly inlined\n"
                    "}\n"
                    "#pragma auto_inline on\n"
                ),
                success_rate=0.85,
            ),
            Fix(
                description=(
                    "Combine pragma WITH the `_dontinline` shim for extra "
                    "safety: pragma around the shim definition, callers use "
                    "the shim. Used by grhomerun.c when both inhibitions are "
                    "needed."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["bl"],
        categories=["inline", "calling-conv"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="grHomeRun_8021C82C"),
                ProvenanceEntry(function="grStadium_801D42B8"),
                ProvenanceEntry(function="pl_800386D8"),
            ],
        ),
        related_patterns=["static-inline-dontinline-wrapper", "pragma-auto-inline-off"],
        notes=(
            "Used in: vi1202.c, plbonus.c, grpstadium.c, grhomerun.c, "
            "granime.c, grcorneria.c, groldpupupu.c, grcastle.c, "
            "mncharsel.c, mnmain.c, mninfo.c, mnitemsw.c, mnstagesw.c, "
            "mndiagram.c, mngallery.c, mnnamenew.c, mnsnap.c, lb_0192.c, "
            "lbcardgame.c, lbaudio_ax.c."
        ),
    ),
    Pattern(
        id="pragma-auto-inline-off",
        name="`#pragma auto_inline off/on` for functions calling HSD inlines",
        description=(
            "Variant of `#pragma dont_inline` that only blocks callers from "
            "inlining this function — the function CAN still inline its own "
            "callees (e.g., HSD_JObjSet* helpers from baselib headers). Use "
            "when the function being protected calls HSD inline helpers."
        ),
        root_cause=(
            "`#pragma dont_inline` is bidirectional (blocks both ways). When a "
            "function calls HSD inline helpers, dont_inline prevents those "
            "helpers from inlining, causing extra `bl HSD_*` calls. "
            "`auto_inline off` only blocks the outer direction."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<HSD inline body>", "actual": "bl HSD_JObjSetTranslate"},
                description="HSD helpers showing as `bl` calls instead of inlined",
            ),
        ],
        examples=[
            Example(
                function="mnEvent_8024D4E0",
                context=(
                    "mnevent.c — D4E0 calls HSD_JObjSetTranslate inline. "
                    "Used `auto_inline off` because `dont_inline` was breaking "
                    "the inline expansion of HSD_JObjSetTranslate."
                ),
                after=(
                    "#pragma auto_inline off\n"
                    "void mnEvent_8024D4E0(args)\n"
                    "{\n"
                    "    HSD_JObjSetTranslate(jobj, &pos);  // properly inlined\n"
                    "}\n"
                    "#pragma auto_inline on\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use `#pragma auto_inline off` ... `#pragma auto_inline on` "
                    "around the function whose CALLERS should not inline it. "
                    "Choose this over `dont_inline` when the function calls "
                    "HSD_JObjSet* or other inline helpers."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["bl"],
        categories=["inline", "calling-conv"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnEvent_8024D4E0"),
            ],
        ),
        related_patterns=["pragma-dont-inline-block"],
        notes=(
            "Key distinction documented in MEMORY.md: "
            "dont_inline = block both directions (no inlining IN or OUT). "
            "auto_inline off = block only the OUT direction (function still "
            "inlines its callees, but callers can't inline it)."
        ),
    ),
    Pattern(
        id="static-inline-hsd-loadjoint-helper",
        name="Tiny static inline wrappers around HSD library functions",
        description=(
            "Wrap a single call like `HSD_JObjLoadJoint(attrs->jointN)` in a "
            "named `static inline` helper. Often used when the same library "
            "call appears multiple times with similar (but not identical) "
            "arguments — a parameterized helper documents intent and forces "
            "uniform codegen at each call site."
        ),
        root_cause=(
            "Same as static-inline-helper-numeric-idiom but for library calls. "
            "Uniform codegen across call sites is the goal. Without the "
            "helper, MWCC may schedule the surrounding instructions differently "
            "at each site."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "lwz", "bl"]},
                description="Load attr pointer, load joint id, call library func",
            ),
        ],
        examples=[
            Example(
                function="it_link_get_joint",
                context=(
                    "itlinkhookshot.c — two parameterized variants based on "
                    "iteration parity. Could be unified but the original code "
                    "kept them split."
                ),
                after=(
                    "static inline HSD_JObj* it_link_get_joint(Item* arg0, s32 var_r31)\n"
                    "{\n"
                    "    itLinkHookshotAttributes* temp_r3_4 =\n"
                    "        arg0->xC4_article_data->x4_specialAttributes;\n"
                    "    if ((var_r31 % 2) != 0) {\n"
                    "        return HSD_JObjLoadJoint(temp_r3_4->x54);\n"
                    "    } else {\n"
                    "        return HSD_JObjLoadJoint(temp_r3_4->x58);\n"
                    "    }\n"
                    "}\n"
                ),
            ),
            Example(
                function="it_802BE65C_LoadString",
                context=(
                    "itnessyoyo.c — two near-identical helpers for two joint "
                    "fields. Kept as separate inlines rather than unified."
                ),
                after=(
                    "static inline HSD_JObj* it_802BE65C_LoadString(Item* ip)\n"
                    "{\n"
                    "    itYoyoAttributes* attrs = ip->xC4_article_data->x4_specialAttributes;\n"
                    "    return HSD_JObjLoadJoint(attrs->x50_string_joint);\n"
                    "}\n"
                    "\n"
                    "static inline HSD_JObj* it_802BE65C_LoadYoyo(Item* ip)\n"
                    "{\n"
                    "    itYoyoAttributes* attrs = ip->xC4_article_data->x4_specialAttributes;\n"
                    "    return HSD_JObjLoadJoint(attrs->x54_yoyo_joint);\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When a library call appears multiple times with similar "
                    "structure, extract each as a named `static inline` "
                    "helper. Keep variants separate rather than parameterizing "
                    "everything — matching beats DRY."
                ),
                success_rate=0.65,
            ),
        ],
        opcodes=["bl", "lwz"],
        categories=["inline", "struct"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="it_link_get_joint"),
                ProvenanceEntry(function="it_802BE65C_LoadString"),
            ],
        ),
        related_patterns=["static-inline-typed-overload-pair"],
    ),
    Pattern(
        id="static-inline-volatile-stack-spill",
        name="`volatile` local for forced stack spill inside static inline",
        description=(
            "When the target asm shows an `stfs`/`lfs` (or `stw`/`lwz`) "
            "round-trip on the stack between a computation and a return, "
            "declare the result as `volatile` inside a `static inline` "
            "helper. This forces MWCC to spill the value to stack and reload, "
            "matching the target."
        ),
        root_cause=(
            "MWCC normally keeps intermediate fp results in registers when "
            "possible. `volatile` forces a memory store followed by a memory "
            "load. The original code (or the inlined library function) "
            "likely used `volatile` for the same reason."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "stfs", "context": "round-trip via stack"},
                description="`stfs sp+N; lfs sp+N` pattern around a value",
            ),
            Signal(
                type="extra_instruction",
                data={"opcode": "stw", "context": "round-trip via stack"},
                description="`stw sp+N; lwz sp+N` pattern around a value",
            ),
        ],
        examples=[
            Example(
                function="my_sqrtf",
                context=(
                    "Newton-Raphson sqrt helpers in itlinkboomerang.c, "
                    "lbshadow.c, etc. use `volatile f32 y` to force a stack "
                    "spill of the final result."
                ),
                after=(
                    "static inline f32 my_sqrtf(f32 x)\n"
                    "{\n"
                    "    volatile f32 y;\n"
                    "    // ... NR iterations ...\n"
                    "    y = (f32) (x * guess);\n"
                    "    return y;\n"
                    "}\n"
                ),
            ),
            Example(
                function="_sqrtfItem (vf32)",
                context=(
                    "it_26B1.c uses a `vf32` typedef (volatile f32) for the same effect"
                ),
                after=(
                    "typedef volatile f32 vf32;\n"
                    "\n"
                    "static inline float _sqrtfItem(float x)\n"
                    "{\n"
                    "    // ...\n"
                    "    vf32 y;\n"
                    "    y = x * guess;\n"
                    "    return y;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows an unnecessary `stfs`/`lfs` pair on the "
                    "stack between a computation and its use, declare the "
                    "intermediate as `volatile`. Often inside a `static inline` "
                    "helper to localize the effect."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["stfs", "lfs", "stw", "lwz"],
        categories=["inline", "float", "stack"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="my_sqrtf"),
            ],
        ),
        related_patterns=["newton-raphson-sqrt-inline"],
    ),
    Pattern(
        id="static-inline-stack-dummy-array",
        name="`u8 _[N] = {0}` stack dummy inside static inline",
        description=(
            "An uninitialized-looking `u8 _[N] = { 0 };` array declared at the "
            "top of a `static inline` helper adds N bytes to its stack frame. "
            "Used to absorb stack the caller's PAD_STACK would otherwise need "
            "— moving stack from caller into the inline keeps the inline's "
            "frame size and the caller's frame size aligned with the target."
        ),
        root_cause=(
            "When you pull function body code into a `static inline` helper, "
            "stack-allocated locals move with it. But if the caller's target "
            "stack frame includes space the helper's locals don't fully "
            "occupy, the difference becomes a mismatch. A dummy `u8 _[N]` "
            "absorbs the gap. The leading `_` documents that the array is "
            "intentionally unused."
        ),
        signals=[
            Signal(
                type="offset_delta",
                data={"register": "r1", "delta": None},
                description="Stack frame in helper differs from target by exact N bytes",
            ),
        ],
        examples=[
            Example(
                function="lbShadow_Sqrtf",
                context=(
                    "lbshadow.c — `u8 _[0x38] = { 0 };` absorbs 56 bytes "
                    "from the caller's PAD_STACK(0x48), reducing the caller "
                    "pad to PAD_STACK(0x10)."
                ),
                after=(
                    "static inline f32 lbShadow_Sqrtf(f32 x)\n"
                    "{\n"
                    "    u8 _[0x38] = { 0 };  // absorbs 56 bytes from caller\n"
                    "    volatile f32 y;\n"
                    "    // ...\n"
                    "}\n"
                ),
            ),
            Example(
                function="my_sqrtf (variants)",
                context=(
                    "Different N values for different callers: N=4 in "
                    "itlinkboomerang.c, N=12 in itnessyoyo.c, N=0x38 in "
                    "lbshadow.c. Choose N to match the target's stack arithmetic."
                ),
                after=(
                    "// N=4: small caller\n"
                    "u8 _[4] = { 0 };\n"
                    "// N=12: medium caller\n"
                    "u8 _[12] = { 0 };\n"
                    "// N=0x38: large caller pad\n"
                    "u8 _[0x38] = { 0 };\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If your stack frame is K bytes too small after extracting "
                    "code into an inline, add `u8 _[K] = {0};` at the top of "
                    "the inline. If too large, reduce the inline's own locals "
                    "or shrink an existing dummy."
                ),
                success_rate=0.8,
            ),
            Fix(
                description=(
                    "Alternative: use `int _ = 0;` (single u32 dummy) for a "
                    "4-byte gap. Sometimes a single int or a struct of u32s "
                    "matches the target's spill ordering better than a u8 array."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["stwu", "lwz"],
        categories=["inline", "stack"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbShadow_Sqrtf"),
                ProvenanceEntry(function="my_sqrtf"),
            ],
        ),
        related_patterns=["newton-raphson-sqrt-inline", "incorrect-stack-size"],
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
