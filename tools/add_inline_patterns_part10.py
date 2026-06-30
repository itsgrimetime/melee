"""
Part 10: more discord-knowledge patterns about HSD macros and edge cases.
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
        id="hsd-gobjgetuserdata-cast-return-not-input",
        name="`(T*) HSD_GObjGetUserData(gobj)` — cast on return, NOT input",
        description=(
            "When extracting user_data from a gobj via "
            "`HSD_GObjGetUserData`, cast the RETURN value to the specific "
            "type, not the input. `(Fighter*) HSD_GObjGetUserData(gobj)` is "
            "correct; `(Fighter*) HSD_GObjGetUserData((HSD_GObj*) gobj)` "
            "(casting both) causes stack allocation issues."
        ),
        root_cause=(
            "Cast on input forces MWCC to materialize a temporary HSD_GObj* "
            "value in a register, then load user_data from it. Cast on "
            "return uses the existing register holding gobj directly. "
            "Different stack usage at the call site."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "stw", "context": "extra spill from input cast"},
                description="Extra stack store at GET_FIGHTER-like call",
            ),
        ],
        examples=[
            Example(
                function="canonical pattern",
                before=(
                    "// Wrong - cast on input causes stack issues:\n"
                    "Fighter* fp = (Fighter*) HSD_GObjGetUserData((HSD_GObj*) fighter_gobj);\n"
                ),
                after=(
                    "// Correct - cast only on return:\n"
                    "Fighter* fp = (Fighter*) HSD_GObjGetUserData(fighter_gobj);\n"
                    "// Or with macro:\n"
                    "Fighter* fp = GET_FIGHTER(fighter_gobj);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Never cast the INPUT to HSD_GObjGetUserData. Only cast "
                    "the return value. Same rule for GET_FIGHTER, GET_ITEM, "
                    "GET_GROUND macros — they shouldn't have casts on the "
                    "input parameter."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["stw", "lwz"],
        categories=["inline", "stack", "calling-conv"],
        provenance=Provenance(),
        notes=(
            "Discord knowledge from January 2023 — verified by Smash 64 "
            "decomp pattern."
        ),
    ),
    Pattern(
        id="get-jobj-may-be-fake-prefer-direct-access",
        name="`GET_JOBJ` macro may not be real — prefer `gobj->hsd_obj` direct access",
        description=(
            "Evidence suggests `GET_JOBJ` is not a HAL-defined macro. "
            "Direct access `gobj->hsd_obj` (with a cast if needed) sometimes "
            "matches better than the macro. Especially in functions with "
            "`HSD_JObjGetNext(HSD_JObjGetChild(...))` chains."
        ),
        root_cause=(
            "If GET_JOBJ is implemented as an inline that does the cast and "
            "load, its inlining may produce different codegen than a direct "
            "field access. The original code likely used the field access "
            "directly."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "mr", "context": "after GET_JOBJ"},
                description="Extra move from GET_JOBJ inline expansion",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// Via possibly-fake macro:\n"
                    "HSD_JObj* jobj = GET_JOBJ(gobj);\n"
                ),
                after=(
                    "// Direct access:\n"
                    "HSD_JObj* jobj = (HSD_JObj*) gobj->hsd_obj;\n"
                    "// Or for chain:\n"
                    "HSD_JObj* child = HSD_JObjGetChild(gobj->hsd_obj);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When `GET_JOBJ(gobj)` doesn't match, try direct field "
                    "access `gobj->hsd_obj` with appropriate cast. Macros "
                    "may have been added by the decomp project, not HAL."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["lwz", "mr"],
        categories=["inline", "struct"],
        provenance=Provenance(),
    ),
    Pattern(
        id="ecb-struct-shape-fighter-vs-item",
        name="`ECB` (Environmental Collision Box) struct differs: Fighter uses Vec2, Item uses f32",
        description=(
            "The ECB substruct in `CollData` has different shapes in "
            "`fighter.h` (4x Vec2 - top/bottom/left/right) vs `item.h` "
            "(4x f32 - flat values). Fighter ECBs are animated so they "
            "need 2D positions; item ECBs are simpler. Picking the wrong "
            "header's definition gives wrong field offsets."
        ),
        root_cause=(
            "Same struct name (`ECB` / `CollData_ECB`) but different "
            "internal layout between fighter and item collision data. "
            "Including the wrong header puts the same field at a different "
            "offset."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lfs 0xN(rN)", "actual": "lfs 0xM(rN)"},
                description="Field offset within ECB differs",
            ),
        ],
        examples=[
            Example(
                function="generic ECB access",
                after=(
                    "// In fighter.c:\n"
                    "#include <melee/ft/fighter.h>  // Vec2 ECB\n"
                    "fp->coll_data.ecb.top.x = ...;\n"
                    "\n"
                    "// In item code:\n"
                    "#include <melee/it/item.h>  // f32 ECB\n"
                    "ip->coll_data.ecb.top = ...;  // no .x/.y\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Include the right header for the entity type you're "
                    "working with. Fighter coll_data uses Vec2 ECB; item "
                    "uses f32 ECB. Wrong include gives wrong offsets and "
                    "type errors."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["lfs", "stfs"],
        categories=["struct", "data-layout"],
        provenance=Provenance(),
    ),
    Pattern(
        id="frank-epilogue-mtlr-addi-order-bug",
        name="Frank.py / 1.2.5n compiler workaround for epilogue `mtlr`/`addi` ordering",
        description=(
            "MWCC 1.2.5 has an epilogue scheduling bug where `mtlr` and "
            "`addi r1, r1, N` get swapped vs the expected order. Melee uses "
            "the buggy form. Frank.py post-processes the assembly to fix; "
            "or use the 1.2.5n hotfix compiler which avoids the bug. The "
            "alternative shows: `addi r1, r1, N; mtlr r0` vs expected "
            "`mtlr r0; addi r1, r1, N`."
        ),
        root_cause=(
            "Prologue/epilogue scheduling was not subject to instruction "
            "scheduling before MWCC 2.3.x. Melee relies on a 2.2.x bug "
            "that produces a specific (now-incorrect) epilogue order. "
            "Frank.py rewrites the asm; 1.2.5n (Ninji's patch) adds "
            "fSideEffects to addi r1 to keep it from being scheduled."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "addi r1", "actual": "mtlr r0"},
                description="mtlr/addi epilogue order swapped",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["addi r1, r1, N", "mtlr r0", "blr"]},
                description="Expected (Frank-ed) order",
            ),
        ],
        examples=[
            Example(
                function="generic",
                context=(
                    "Files needing Frank treatment go in `e_files.mk`. "
                    "1.2.5n compiler is the modern replacement that doesn't "
                    "need Frank."
                ),
                after=(
                    "# Expected (Melee target):     # Generated by 1.2.5 (no Frank):\n"
                    "# addi r1,r1,N                 # mtlr r0\n"
                    "# mtlr r0                      # addi r1,r1,N\n"
                    "# blr                          # blr\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If asm has the wrong epilogue order, the file needs "
                    "Frank.py post-processing OR the 1.2.5n compiler. "
                    "Add the file to `e_files.mk` if using Frank; or "
                    "configure 1.2.5n in the build."
                ),
                success_rate=0.95,
            ),
            Fix(
                description=(
                    "SDK/MSL libraries use plain 1.2.5 — do NOT add them to "
                    "e_files.mk. Only game code (which expects the swapped "
                    "order) needs the workaround."
                ),
            ),
        ],
        opcodes=["mtlr", "addi", "blr"],
        categories=["stack", "data-layout"],
        provenance=Provenance(),
        notes=(
            "Project history: $1000 bounty was considered for finding the "
            "right mwcceppc 2.2.x compiler. 1.2.5n (Ninji's patch) replicates "
            "build 167 behavior."
        ),
    ),
    Pattern(
        id="m2c-temp-rn-var-rn-naming",
        name="`temp_rN`, `var_rN`, `temp_fN` — m2c register-name locals",
        description=(
            "m2c names locals after the registers it inferred them from: "
            "`temp_r3`, `var_r29`, `temp_f1`, etc. Final matched code "
            "renames them to descriptive names. Naming alone doesn't change "
            "codegen, but it documents intent and helps reviewers."
        ),
        root_cause=(
            "m2c reverse-engineers register lifetimes into C locals. Without "
            "type/name info, it uses the register name as the variable name. "
            "Rename for readability — codegen is identical."
        ),
        signals=[],
        examples=[
            Example(
                function="generic",
                before=(
                    "// m2c output:\n"
                    "void func(int arg0) {\n"
                    "    int temp_r3;\n"
                    "    int var_r29;\n"
                    "    float temp_f1;\n"
                    "    // ...\n"
                    "}\n"
                ),
                after=(
                    "// Renamed for clarity:\n"
                    "void func(int slot) {\n"
                    "    int result;\n"
                    "    int counter;\n"
                    "    float velocity;\n"
                    "    // ...\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Replace m2c-generated `temp_rN`/`var_rN`/`temp_fN` with "
                    "descriptive names. Doesn't affect codegen but improves "
                    "code review. Do this AFTER reaching 100% match."
                ),
            ),
            Fix(
                description=(
                    "Don't rename if you're mid-fixing register allocation - "
                    "the register-suffix names are easier to map to asm."
                ),
            ),
        ],
        opcodes=[],
        categories=["control-flow"],
        provenance=Provenance(),
        notes="Style guideline, not a codegen fix.",
    ),
    Pattern(
        id="m2c-struct-copy-replace-with-assignment",
        name="`M2C_STRUCT_COPY` artifact — replace with struct assignment or memcpy",
        description=(
            "m2c emits `M2C_STRUCT_COPY(dst, src, T)` when it can't figure "
            "out struct copy intent. Replace with `*dst = *src;` (struct "
            "assignment) or `memcpy(dst, src, sizeof(T));` depending on what "
            "the target asm shows. Both compile differently — see "
            "memcpy-explicit-vs-struct-assignment-codegen."
        ),
        root_cause=(
            "M2C_STRUCT_COPY is m2c's fallback for unknown struct copies. "
            "It's a placeholder macro that doesn't exist in real C source. "
            "Must be replaced before the code can compile."
        ),
        signals=[],
        examples=[
            Example(
                function="generic",
                before=(
                    "// m2c output:\n"
                    "M2C_STRUCT_COPY(item->pos, *src, Vec3);\n"
                ),
                after=(
                    "// Replace with struct assignment:\n"
                    "item->pos = *src;\n"
                    "// or memcpy:\n"
                    "memcpy(&item->pos, src, sizeof(Vec3));\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Replace every `M2C_STRUCT_COPY(dst, src, T)` with "
                    "`*dst = *src;` (most common). If target asm shows "
                    "`bl memcpy`, use the explicit memcpy form."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=[],
        categories=["struct"],
        provenance=Provenance(),
        related_patterns=[
            "memcpy-explicit-vs-struct-assignment-codegen",
            "copying-structs-field-by-field",
        ],
    ),
    Pattern(
        id="m2c-field-replace-with-typed-access",
        name="`M2C_FIELD(ptr, type, offset)` artifact — replace with typed field access",
        description=(
            "m2c emits `M2C_FIELD(ptr, T, OFFSET)` when it doesn't know the "
            "struct's field layout. Replace by figuring out which field is "
            "at OFFSET in the struct and using normal access "
            "`ptr->field_name`. Run `melee-agent struct offset OFFSET` to "
            "look up the field."
        ),
        root_cause=(
            "M2C_FIELD is m2c's placeholder for unknown offsets into a "
            "struct. Without type info, m2c emits the raw offset. Real C "
            "needs the field name."
        ),
        signals=[],
        examples=[
            Example(
                function="generic",
                before=(
                    "// m2c output:\n"
                    "x = M2C_FIELD(fp, f32, 0x1B8);\n"
                ),
                after=(
                    "// Look up offset 0x1B8 in Fighter struct:\n"
                    "x = fp->cur_pos.x;  // or whatever lives there\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Replace `M2C_FIELD(ptr, T, OFF)` with proper field "
                    "access. Use `melee-agent struct offset 0xN` or "
                    "`melee-agent struct show <struct> --offset 0xN` to "
                    "find the field name."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=[],
        categories=["struct", "data-layout"],
        provenance=Provenance(),
    ),
    Pattern(
        id="m2c-error-unhandled-construct",
        name="`M2C_ERROR(...)` / `M2C_UNK(...)` — unhandled m2c constructs",
        description=(
            "m2c emits `M2C_ERROR(...)` when it can't translate a sequence, "
            "and `M2C_UNK(...)` for unknown intrinsics or expressions. Both "
            "must be replaced before compile. They indicate complex asm "
            "(rare opcodes, switch tables, irreducible CFG) that needs "
            "manual interpretation."
        ),
        root_cause=(
            "m2c's translation is not complete — some asm constructs lack "
            "a clean C representation. The placeholders flag where manual "
            "work is needed."
        ),
        signals=[],
        examples=[
            Example(
                function="generic",
                before=(
                    "// m2c output with M2C_ERROR:\n"
                    "result = M2C_ERROR(complex switch table);\n"
                    "// or:\n"
                    "x = M2C_UNK(intrinsic call);\n"
                ),
                after=(
                    "// Replace manually after analyzing the asm:\n"
                    "switch (idx) {\n"
                    "    case 0: result = 1; break;\n"
                    "    case 1: result = 2; break;\n"
                    "    /* ... */\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Read the original asm at the M2C_ERROR/M2C_UNK location "
                    "and reverse-engineer manually. Common cases: dense "
                    "switch tables, paired singles, custom intrinsics."
                ),
            ),
        ],
        opcodes=[],
        categories=["control-flow"],
        provenance=Provenance(),
        related_patterns=["jtbl-t-fake-typedef-for-dense-switch"],
    ),
    Pattern(
        id="paired-pointer-head-tail-list-pattern",
        name="`head`/`tail` pointer pair for queue/list traversal",
        description=(
            "Linked-list code maintaining both head and tail pointers (e.g., "
            "`HSD_GObjGXLinkHead`/`HSD_GObjGXLinkTail`) follows specific "
            "traversal patterns. Walking the list updates one while the "
            "other stays anchored. Codegen distinguishes between accessing "
            "head's next vs tail's prev — affects register usage."
        ),
        root_cause=(
            "Doubly-linked list traversal needs separate paths for forward "
            "and reverse walks. MWCC schedules loads based on which "
            "endpoint is the anchor."
        ),
        signals=[],
        examples=[
            Example(
                function="HSD_GObj GX link traversal",
                after=(
                    "// Forward walk from head:\n"
                    "HSD_GObj* cur;\n"
                    "for (cur = HSD_GObjGXLinkHead[4]; cur != NULL; cur = cur->next_gx) {\n"
                    "    /* ... */\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Match the head/tail pair pattern in source. Don't "
                    "convert to single-pointer traversal — the original code "
                    "likely maintained both for O(1) append."
                ),
            ),
        ],
        opcodes=["lwz"],
        categories=["loop", "struct"],
        provenance=Provenance(),
    ),
    Pattern(
        id="pointer-arithmetic-cast-vs-array-index",
        name="Pointer arithmetic via cast — `((u32) ptr) + N` vs `&ptr[N/sizeof]`",
        description=(
            "Some matched code uses `(u32) ptr + N` for byte-level pointer "
            "arithmetic, casting through unsigned int. Versus normal "
            "`&ptr[N/sizeof(T)]` array indexing. The cast form forces "
            "raw byte arithmetic, matching when target uses `addi rD, rS, N` "
            "directly on a pointer without multiplying."
        ),
        root_cause=(
            "Casting to u32 strips pointer type, so `+ N` becomes byte "
            "addition (not scaled by sizeof). Array indexing scales by "
            "sizeof(T). Different asm: `addi` vs `addi + slwi/mulli`."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "addi", "actual": "slwi+add"},
                description="Byte offset vs scaled index",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "// Byte arithmetic via cast:\n"
                    "T* offset = (T*) ((u32) ptr + 0x40);\n"
                    "// emits: addi r3, r3, 0x40\n"
                    "\n"
                    "// Vs array indexing (if T is u8):\n"
                    "u8* offset = &ptr[0x40];\n"
                    "// also addi but only if sizeof(T) == 1\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows `addi r,r,N` without scaling, source "
                    "may use `(u32) ptr + N` cast arithmetic. Especially "
                    "common for void* pointers or pre-typedef code."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["addi"],
        categories=["struct", "type", "data-layout"],
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
