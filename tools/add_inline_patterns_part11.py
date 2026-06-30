"""
Part 11: pointer/data-flow patterns from agent analysis.
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
        id="doubly-linked-unlink-symmetric-sentinel",
        name="Symmetric `prev`/`next` unlink with else-branch updating head/tail global",
        description=(
            "Doubly-linked list unlink code with two symmetric branches: "
            "`if (prev) { prev->next = next; } else { head_global = next; }` "
            "and the mirror for next/tail. The else-branch must write the "
            "global INSIDE the symmetric structure (not after both ifs) to "
            "preserve register liveness of prev/next as source operand for "
            "stw."
        ),
        root_cause=(
            "Each symmetric branch produces lwz/cmpwi/beq + stw to either "
            "struct field or sda global. Writing the global through the "
            "else-branch (inline) keeps prev/next live in the same register "
            "across the test. Pulling the global write out of the if changes "
            "register usage."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "cmpwi", "beq", "stw", "lwz", "stw"]},
                description="Symmetric branches with stw to struct or global",
            ),
        ],
        examples=[
            Example(
                function="gobjplink.c unlink",
                after=(
                    "if (gobj->prev != NULL) {\n"
                    "    gobj->prev->next = gobj->next;\n"
                    "} else {\n"
                    "    head[gobj->p_link] = gobj->next;\n"
                    "}\n"
                    "if (gobj->next != NULL) {\n"
                    "    gobj->next->prev = gobj->prev;\n"
                    "} else {\n"
                    "    tail[gobj->p_link] = gobj->prev;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use the symmetric prev/next + head/tail pattern with "
                    "the global update INSIDE the else of each branch. "
                    "Don't extract the global write out of the conditional."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["lwz", "stw", "beq"],
        categories=["struct", "loop"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="gobjplink unlink"),
                ProvenanceEntry(function="camera cleanup"),
            ],
        ),
    ),
    Pattern(
        id="save-next-before-mutating-loop",
        name="Cache `next` BEFORE body in destructive list-traversal loops",
        description=(
            "When a loop body may free/relink the current node, you must "
            "cache `next = cur->next` BEFORE the body. Standard "
            "`for (...; cur = cur->next)` (increment at top of loop) "
            "re-loads through freed memory. The cache must happen at the "
            "top of the body."
        ),
        root_cause=(
            "Loading cur->next AFTER the body operates on freed memory. "
            "MWCC's load placement follows the source order: writing the "
            "cache as the first statement in the body places the lwz at "
            "the top of the basic block, before the destructive call."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz next", "bl destroy", "mr cur,next"]},
                description="Load next first, then destroy, then advance",
            ),
        ],
        examples=[
            Example(
                function="tobj.c, sislib.c destroy loops",
                after=(
                    "HSD_Text* curr = list_head;\n"
                    "while (curr != NULL) {\n"
                    "    HSD_Text* next = curr->next;  // cache FIRST\n"
                    "    if (curr->entity != NULL) {\n"
                    "        HSD_SisLib_803A5CC4(curr);  // body may free curr\n"
                    "    }\n"
                    "    curr = next;\n"
                    "}\n"
                ),
                before=(
                    "// Wrong: for-loop increment loads through freed memory:\n"
                    "for (curr = list_head; curr != NULL; curr = curr->next) {\n"
                    "    HSD_SisLib_803A5CC4(curr);  // crash or undefined\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "In destructive traversal loops, use `while (cur != "
                    "NULL) { next = cur->next; ... ; cur = next; }`. NOT "
                    "`for (...; cur = cur->next)` which re-loads through "
                    "potentially freed memory."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["lwz", "stw", "mr"],
        categories=["loop", "struct"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="tobj cleanup loop"),
                ProvenanceEntry(function="sislib destroy"),
            ],
        ),
    ),
    Pattern(
        id="pointer-to-pointer-list-iterator",
        name="`T** entry` slot-pointer iterator for in-place splice",
        description=(
            "Walking a linked list with `T** entry = &list_head` (address "
            "of the slot, not the value) lets caller splice in-place "
            "without head special-casing. Each step is "
            "`entry = &(*entry)->next`. Generates a two-level load that "
            "won't match without the T** declaration."
        ),
        root_cause=(
            "T** keeps the address of the slot (where the pointer lives) "
            "in a register. Each iteration dereferences once to get cur, "
            "then advances entry to point at cur->next's slot. Won't be "
            "produced by single-pointer `T* cur` source."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz rCur,0(rEntry)", "lwz rNext,off(rCur)", "addi rEntry,rCur,off"]},
                description="Two-level load with addi entry-advance",
            ),
        ],
        examples=[
            Example(
                function="hash.c chain walk",
                after=(
                    "HSD_HashEntry** entry;\n"
                    "for (entry = &hash->table[idx];\n"
                    "     *entry != NULL;\n"
                    "     entry = &((*entry)->next))\n"
                    "{\n"
                    "    if (cmp((*entry)->key, key) == 0) {\n"
                    "        *out_slot = (HSD_HashEntry*) entry;  // splice point\n"
                    "        return *entry;\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use `T** entry` iterator when asm shows two-level "
                    "loads through a callee-saved register holding what "
                    "looks like 'one indirection deeper than cur'. Common "
                    "in hash tables and insertion-sorted lists."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lwz", "addi"],
        categories=["loop", "struct"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="HSD_HashEntry lookup"),
            ],
        ),
    ),
    Pattern(
        id="void-pp-double-store-with-reload",
        name="`void**` output param: NULL-store then real-store, then reload for null-check",
        description=(
            "Writing to a `void**` output parameter twice (once with NULL, "
            "once with the real value) prevents MWCC from CSE-ing the call "
            "result into the subsequent null-check register. Looks like a "
            "redundant `*p = NULL;` but it's load-bearing."
        ),
        root_cause=(
            "Without the initial NULL store, MWCC may CSE the function call "
            "result with the subsequent null-check. The explicit `*p = NULL` "
            "(visible side effect) breaks the CSE opportunity, forcing a "
            "reload through the pointer."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["li r0,0", "stw r0,0(r3)", "bl func", "stw r3,0(rOut)", "lwz", "cmplwi", "beq"]},
                description="NULL store + call + result store + reload + null check",
            ),
        ],
        examples=[
            Example(
                function="lbArchive symbol getters",
                after=(
                    "void load_symbol(HSD_Archive* archive, const char* name, void** symbol)\n"
                    "{\n"
                    "    *symbol = NULL;  // load-bearing dead store!\n"
                    "    *symbol = HSD_ArchiveGetPublicAddress(archive, name);\n"
                    "    if (*symbol == NULL) {  // reload via *symbol\n"
                    "        OSReport(\"Symbol not found: %s\\n\", name);\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If you see `li r0, 0; stw r0, 0(r3)` immediately before "
                    "a `bl` that returns a value also stored to the same "
                    "slot, the source has a deliberate `*p = NULL;` first. "
                    "Keep it — looks redundant but is load-bearing."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["stw", "li", "lwz", "cmplwi"],
        categories=["calling-conv", "struct", "register"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbArchive_GetPublicAddress"),
            ],
        ),
    ),
    Pattern(
        id="byte-pointer-cast-stride",
        name="`(T*) ((u8*) cur + sizeof(SubT))` for non-`sizeof(T)` stride",
        description=(
            "Walking a typed array at a stride that ISN'T `sizeof(T)` "
            "requires casting through `(u8*)` to do byte-level arithmetic, "
            "then casting back. Compiles to a single `addi rD, rS, N`. "
            "The equivalent `&((SubT*) cur)[1]` may NOT match — different "
            "MWCC code paths."
        ),
        root_cause=(
            "Stride must equal sizeof of indexed type for array indexing to "
            "produce a single addi. Mixing types via u8* cast bypasses the "
            "scaling, producing raw byte addition. Used in struct-overlay "
            "walks (TEV expressions, particle logs, etc.)."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "addi rD,rS,N", "actual": "slwi+add"},
                description="Byte stride via cast vs scaled index",
            ),
        ],
        examples=[
            Example(
                function="texpdag.c TEV expression walker",
                after=(
                    "// Step by sizeof(HSD_TEArg), not sizeof(HSD_TExp):\n"
                    "cur = (HSD_TExp*) ((u8*) cur + sizeof(HSD_TEArg));\n"
                    "// emits: addi rCur, rCur, sizeof(HSD_TEArg)\n"
                ),
                before=(
                    "// May NOT match - depends on sizeof relationship:\n"
                    "cur = &((HSD_TEArg*) cur)[1];\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When asm shows a single literal `addi` between "
                    "dereferences of differently-typed structures, use "
                    "`(T*) ((u8*) cur + N)` cast arithmetic. Common in "
                    "struct-overlay walks (DAGs, log entries, file blobs)."
                ),
                success_rate=0.8,
            ),
        ],
        opcodes=["addi"],
        categories=["struct", "type", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="texpdag TEV walk"),
            ],
        ),
        related_patterns=["pointer-arithmetic-cast-vs-array-index"],
    ),
    Pattern(
        id="intptr-add-in-place-relocation",
        name="`*(intptr_t*)(p + off) += base` for relocation/fixup",
        description=(
            "Loading a value at `base + offset`, adding a base address, and "
            "storing back is written as `*(intptr_t*)(p + off) += base`. "
            "Compiles to `lwzx + add + stwx` (read-modify-write through "
            "computed address). Two-statement form `v = *p; *p = v + base;` "
            "generates a redundant register copy."
        ),
        root_cause=(
            "Compound assignment `+=` through a computed address lets MWCC "
            "fuse the read-modify-write into the lwzx/stwx pair via the "
            "same index register. Splitting into separate statements gives "
            "MWCC a chance to allocate a new register for the value."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwzx", "add", "stwx"]},
                description="Indexed load, add, indexed store",
            ),
        ],
        examples=[
            Example(
                function="lbArchive relocator",
                after=(
                    "// Relocation: add base address to each offset:\n"
                    "u32* ptr = (u32*) archive->reloc_info[i].offset;\n"
                    "*(intptr_t*) (archive->data + (u32) ptr) += base_addr;\n"
                ),
                before=(
                    "// Two-statement form may emit extra mr:\n"
                    "u32 val = *(u32*) (archive->data + (u32) ptr);\n"
                    "*(u32*) (archive->data + (u32) ptr) = val + base_addr;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "For archive/DAT relocators that fix up addresses, use "
                    "`*(T*)(p + off) += base;` compound form. Don't split "
                    "into separate load and store."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lwzx", "stwx", "add"],
        categories=["struct", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbArchive relocation"),
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
