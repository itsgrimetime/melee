"""
Sample pattern entries for the mismatch database.

These are derived from:
1. The existing mismatch-db markdown document
2. Patterns discovered from git history analysis
"""

from .models import Example, Fix, Pattern, Provenance, ProvenanceEntry, Signal

SAMPLE_PATTERNS = [
    # From existing mismatch-db
    Pattern(
        id="incorrect-stack-size",
        name="Incorrect Stack Size",
        description="The target assembly calls `stwu` with a different offset, affecting many downstream `r1` accesses.",
        root_cause="The stack is too large or too small. Extra local variables, or missing ones.",
        signals=[
            Signal(
                type="offset_delta",
                data={"register": "r1", "delta": None},
                description="All r1 offsets are shifted by the same amount",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "stwu", "actual": "stwu"},
                description="stwu r1 instruction at function start uses wrong offset",
            ),
        ],
        examples=[
            Example(
                function="generic",
                diff="""\
-0x000008: stwu r1 -0x28(r1)
+0x000008: stwu r1 -0x20(r1)
-0x00000c: stw r31 0x24(r1)
+0x00000c: stw r31 0x1c(r1)""",
                context="Stack frame size mismatch",
            ),
        ],
        fixes=[
            Fix(
                description="If stack is too large: reuse variables, combine declarations",
            ),
            Fix(
                description="If stack is too small: use PAD_STACK macro",
                before="""\
Item* ip = GET_ITEM(gobj);
HSD_GObj* go = it_8027236C(gobj);""",
                after="""\
Item* ip = GET_ITEM(gobj);
HSD_GObj* go = it_8027236C(gobj);
PAD_STACK(8);  // Add padding to match stack size""",
            ),
        ],
        opcodes=["stwu", "stw", "addi"],
        categories=["stack"],
    ),
    Pattern(
        id="struct-field-copy",
        name="Copying Structs Field-by-Field",
        description="The diff shows loads/stores that differ in type: target uses `lwz`/`stw`, your code uses `lfs`/`stfs`.",
        root_cause="When copying an entire struct, the compiler copies word-by-word without regard to field types. m2c generates field-by-field copies that use type-appropriate instructions.",
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "lfs"},
                description="Integer load vs float load",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "stw", "actual": "stfs"},
                description="Integer store vs float store",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "lwz", "stw", "stw"]},
                description="Sequential word loads/stores at adjacent offsets",
            ),
        ],
        examples=[
            Example(
                function="generic",
                diff="""\
-0x000008: lwz r5 0x4(r3)
+0x000008: lfs f0 0x4(r3)
-0x00000c: lwz r3 0x4(r5)
+0x00000c: stfs f0 0x0(r4)""",
                context="Vec3 position copy",
                before="""\
pos->x = attrs->x4.x;
pos->y = attrs->x4.y;
pos->z = attrs->x4.z;""",
                after="""\
*pos = attrs->x4;""",
            ),
        ],
        fixes=[
            Fix(
                description="Assign the entire struct in one expression",
                before="""\
pos->x = attrs->x4.x;
pos->y = attrs->x4.y;
pos->z = attrs->x4.z;""",
                after="""\
*pos = attrs->x4;""",
                success_rate=0.9,
            ),
        ],
        opcodes=["lwz", "stw", "lfs", "stfs"],
        categories=["struct", "type"],
        notes="Common with Vec3 and other small struct types.",
    ),
    Pattern(
        id="branch-polarity-null-check",
        name="Branch Polarity (beq vs bne) with NULL Checks",
        description="The branch instruction has wrong polarity - `beq` when expected `bne`, or vice versa.",
        root_cause="Direct comparisons like `if (ptr != NULL)` may generate different branch polarity than the original code which used inline functions with early-return NULL checks.",
        signals=[
            Signal(
                type="branch_polarity",
                data={"expected": "bne", "actual": "beq", "context": "NULL check"},
                description="Branch if NOT null to load case",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "bne", "actual": "beq"},
            ),
        ],
        examples=[
            Example(
                function="generic",
                diff="""\
-0x000010: bne 0x24    ; branch if NOT null to load case
+0x000010: beq 0x24    ; branch if null (wrong polarity)""",
                context="NULL check before field access",
            ),
        ],
        fixes=[
            Fix(
                description="Use inline functions with NULL-check-and-return pattern",
                before="""\
if (jobj != NULL) {
    new_jobj = jobj->child;
}""",
                after="""\
static inline HSD_JObj* jobj_child(HSD_JObj* jobj) {
    if (jobj == NULL) {
        return NULL;
    }
    return jobj->child;
}
// Usage:
if (jobj_child(parent)) {
    new_jobj = jobj_child(parent);
}""",
            ),
        ],
        opcodes=["beq", "bne", "cmplwi"],
        categories=["branch", "inline"],
        related_patterns=["extra-register-move"],
    ),
    Pattern(
        id="extra-register-move",
        name="Extra Register Move (mr) After Inline Return",
        description="An extra `mr rX, r0` instruction appears when assigning inline function result to a variable.",
        root_cause="Inline functions return their value in r0/r3, which then gets copied to the destination. The original code used direct assignment patterns that load/store directly to the target register.",
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "mr", "context": "after inline return"},
                description="Extra move from r0 to target register",
            ),
        ],
        examples=[
            Example(
                function="generic",
                diff="""\
-0x000050: lwz r4, 0xC(r4)     ; load directly into r4
+0x000050: lwz r0, 0xC(r4)     ; load into r0
+0x000054: mr r4, r0           ; then move to r4""",
                context="Assignment from inline function",
                before="""\
parent = jobj_parent(parent);""",
                after="""\
if (parent == NULL) {
    parent = NULL;
} else {
    parent = parent->parent;
}""",
            ),
        ],
        fixes=[
            Fix(
                description="Replace inline function calls with explicit if-else for direct assignment",
                before="parent = jobj_parent(parent);",
                after="""\
if (parent == NULL) {
    parent = NULL;
} else {
    parent = parent->parent;
}""",
            ),
        ],
        opcodes=["mr", "lwz"],
        categories=["inline", "register"],
        related_patterns=["branch-polarity-null-check", "callee-saved-register-order"],
        notes="Trade-off: This may affect register allocation order (see callee-saved-register-order).",
    ),
    # From git history analysis
    Pattern(
        id="u8-parameter-mask-clrlwi",
        name="u8 Parameter Mask for clrlwi",
        description="A u8 parameter needs explicit `& 0xFF` masking to generate the correct `clrlwi` instruction.",
        root_cause="Even though the parameter is already u8, the compiler may not generate clrlwi without an explicit mask. This is a MWCC quirk.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["clrlwi"]},
                description="clrlwi instruction expected but not generated",
            ),
        ],
        examples=[
            Example(
                function="GetNameTotalKOs",
                context="mn/mndiagram.c",
                before="""\
u8 idx = field_index;""",
                after="""\
u8 idx = (u8)(field_index & 0xFF);""",
            ),
            Example(
                function="GetFighterTotalKOs",
                context="mn/mndiagram.c",
                before="""\
u8 idx = field_index;""",
                after="""\
u8 idx = (u8)(field_index & 0xFF);""",
            ),
        ],
        fixes=[
            Fix(
                description="Add explicit & 0xFF mask even for u8 parameters",
                before="u8 idx = field_index;",
                after="u8 idx = (u8)(field_index & 0xFF);",
                success_rate=0.95,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="GetNameTotalKOs", date="2025-12-31"),
                ProvenanceEntry(function="GetFighterTotalKOs", date="2025-12-31"),
            ],
        ),
        opcodes=["clrlwi"],
        categories=["type"],
    ),
    Pattern(
        id="loop-unrolling-array-copy",
        name="Loop Unrolling → Array Assignment",
        description="The compiler unrolls struct/array copy loops. m2c produces explicit M2C_STRUCT_COPY calls or manual pointer arithmetic.",
        root_cause="MWCC's optimizer unrolls small loops, especially for struct copies. The actual code uses clean array indexing rather than pointer arithmetic.",
        signals=[
            Signal(
                type="m2c_artifact",
                data={"artifact": "M2C_STRUCT_COPY"},
                description="m2c produces repeated struct copy calls",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "lwz", "stw", "stw"]},
                description="Repeated load-store pairs at sequential offsets",
            ),
        ],
        examples=[
            Example(
                function="lbColl_CopyHitCapsule",
                context="lb/lbcollision.c - HitVictim array copy",
                before="""\
M2C_STRUCT_COPY(dst, src, 8);
M2C_STRUCT_COPY(dst, src, 8);
// ... repeated 16 times""",
                after="""\
HitVictim* sv1 = src->victims_1;
HitVictim* dv1 = dst->victims_1;
for (i = 0; i < ARRAY_SIZE(src->victims_1); i++) {
    dv1[i] = sv1[i];
}""",
            ),
        ],
        fixes=[
            Fix(
                description="Replace unrolled copies with for loop and array indexing",
                before="""\
M2C_STRUCT_COPY(dst, src, 8);
M2C_STRUCT_COPY(dst, src, 8);
// repeated""",
                after="""\
for (i = 0; i < ARRAY_SIZE(arr); i++) {
    dst[i] = src[i];
}""",
                success_rate=0.8,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbColl_CopyHitCapsule"),
            ],
        ),
        opcodes=["lwz", "stw"],
        categories=["loop", "struct"],
    ),
    Pattern(
        id="local-function-type-declaration",
        name="Local Function Type Declaration",
        description="A function call generates wrong calling convention or register usage. Local declaration with specific types fixes it.",
        root_cause="The global declaration may have a different signature than what the caller expects. A local declaration with the exact types can influence code generation.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["bl"]},
                description="Function call with wrong parameter passing",
            ),
        ],
        examples=[
            Example(
                function="GetNameTotalKOs",
                context="mn/mndiagram.c",
                before="""\
// Uses global GetNameText declaration
if (GetNameText(i) != 0) {""",
                after="""\
char* GetNameText_u8(u8);
#define GetNameText GetNameText_u8
// ... code using GetNameText ...
#undef GetNameText""",
            ),
        ],
        fixes=[
            Fix(
                description="Add local function declaration with specific types, use #define wrapper",
                before="""\
// Uses global declaration
fn(param);""",
                after="""\
RetType fn_specific(SpecificType);
#define fn fn_specific
fn(param);
#undef fn""",
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="GetNameTotalKOs", date="2025-12-31"),
            ],
        ),
        categories=["calling-conv", "type"],
    ),
    Pattern(
        id="ternary-vs-if-else",
        name="Ternary vs If-Else",
        description="Different branch patterns for conditional assignments. Ternary and if-else may compile differently.",
        root_cause="The compiler generates different code for ternary operators vs if-else blocks, even for equivalent logic.",
        signals=[
            Signal(
                type="branch_polarity",
                data={"expected": None, "actual": None, "context": "conditional assignment"},
                description="Branch pattern differs from expected",
            ),
        ],
        fixes=[
            Fix(
                description="Try both ternary and if-else forms",
                before="""\
x = (cond) ? a : b;""",
                after="""\
if (cond) x = a; else x = b;""",
            ),
            Fix(
                description="Or vice versa",
                before="""\
if (cond) x = a; else x = b;""",
                after="""\
x = (cond) ? a : b;""",
            ),
        ],
        categories=["control-flow", "branch"],
        notes="Sometimes `? :` produces tighter code, sometimes `if/else` does. Trial and error required.",
    ),
    Pattern(
        id="abs-fabs-macro",
        name="ABS/FABS Macro Usage",
        description="Manual absolute value check generates more instructions than the ABS/FABS macro.",
        root_cause="The ABS/FABS macros are optimized for the target compiler and generate fewer instructions.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["fcmpo", "ble", "fneg"]},
                description="Manual float absolute value pattern",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before="""\
if (val < 0.0f) val = -val;""",
                after="""\
val = ABS(val);""",
            ),
        ],
        fixes=[
            Fix(
                description="Use ABS or FABS macro instead of manual check",
                before="if (val < 0.0f) val = -val;",
                after="val = ABS(val);",
                success_rate=0.9,
            ),
        ],
        opcodes=["fcmpo", "fneg", "fabs"],
        categories=["float"],
    ),
    Pattern(
        id="variadic-va-list-offset",
        name="Variadic Function va_list Offset",
        description="The `va_list` structure is stored at the wrong stack offset.",
        root_cause="MWCC places `va_list` at a specific stack offset based on local variable layout. Declaration order affects placement.",
        signals=[
            Signal(
                type="offset_delta",
                data={"register": "r1", "delta": 4},
                description="va_list storage offset mismatch",
            ),
        ],
        examples=[
            Example(
                function="generic",
                diff="""\
-0x000074: stw r0, 0x74(r1)    ; va_list at expected offset
+0x000074: stw r0, 0x70(r1)    ; va_list 4 bytes too early""",
                context="Variadic function with va_list",
            ),
        ],
        fixes=[
            Fix(
                description="Add padding variable before va_list declaration",
                before="""\
int my_variadic_func(int arg0, ...) {
    va_list ap;
    va_start(ap, arg0);""",
                after="""\
int my_variadic_func(int arg0, ...) {
    va_list ap;
    s32 _unused;  // Padding to shift va_list offset
    _unused = 0;
    (void) _unused;
    va_start(ap, arg0);""",
            ),
        ],
        opcodes=["stw"],
        categories=["stack", "calling-conv"],
    ),
    Pattern(
        id="callee-saved-register-order",
        name="Callee-Saved Register Allocation Order (r27-r31)",
        description="Registers r27-r31 are allocated to different variables than expected.",
        root_cause="MWCC allocates callee-saved registers based on variable usage patterns and declaration order.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["mr", "addi", "li"]},
                description="Register moves with wrong register numbers",
            ),
        ],
        examples=[
            Example(
                function="generic",
                diff="""\
-0x000010: mr. r29, r3    ; root in r29
-0x000014: addi r30, r4   ; output in r30
+0x000010: mr. r30, r3    ; root in r30 (wrong!)
+0x000014: addi r31, r4   ; output in r31 (wrong!)""",
                context="Variable-to-register assignment",
            ),
        ],
        fixes=[
            Fix(
                description="Reorder variable declarations - variables declared/used later get higher register numbers",
                before="""\
s32 count;        // was early, got r29
s32 prev_idx;
Type* parent;""",
                after="""\
s32 prev_idx;
Type* parent;
s32 count;        // moved to end, now gets r31""",
            ),
        ],
        opcodes=["mr", "stw", "lwz"],
        categories=["register"],
        related_patterns=["extra-register-move"],
        notes="Often trial-and-error. The goal is to make variables that should be in higher registers (r31, r30) be declared or first-used later.",
    ),
    # ==========================================================================
    # ANTI-PATTERNS: Overcomplicated code that should be simpler
    # ==========================================================================
    Pattern(
        id="pointer-arithmetic-for-array",
        name="Pointer Arithmetic Instead of Array Indexing",
        description="Using pointer arithmetic like ((Type*)((u8*)ptr + (i << 2)))->field[0] when simple array indexing works.",
        root_cause="When iterating over array elements, the natural array[i] syntax often compiles identically to manual pointer arithmetic. The compiler handles the offset calculation internally.",
        signals=[
            Signal(
                type="code_smell",
                data={"pattern": "((u8*) ptr + (i << N))"},
                description="Manual pointer arithmetic with bit shift for indexing",
            ),
        ],
        examples=[
            Example(
                function="mnDiagram2_ClearStatRows",
                context="mn/mndiagram2.c - discovered 2026-01-24",
                before="""\
do {
    if (base->row_labels[0] != NULL) {
        HSD_SisLib_803A5CC4(ptr->row_labels[0]);
        base->row_labels[0] = NULL;
    }
    i++;
    base = (Diagram2*) ((u8*) base + 4);
    ptr = (Diagram2*) ((u8*) ptr + 4);
} while (i < 10);""",
                after="""\
for (i = 0; i < 10; i++) {
    if (data->row_labels[i] != NULL) {
        HSD_SisLib_803A5CC4(ptr->row_labels[i]);
        data->row_labels[i] = NULL;
    }
}""",
            ),
        ],
        fixes=[
            Fix(
                description="Replace pointer arithmetic with direct array indexing",
                before="""\
base = (Diagram2*) ((u8*) base + 4);
base->row_labels[0] = NULL;""",
                after="""\
data->row_labels[i] = NULL;  // Use array index directly""",
                success_rate=0.95,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnDiagram2_ClearStatRows", date="2026-01-24"),
            ],
            helped_match=[
                ProvenanceEntry(function="mnDiagram2_ClearStatRows", date="2026-01-24"),
            ],
        ),
        opcodes=["slwi", "add", "lwz", "stw"],
        categories=["anti-pattern", "array", "simplification"],
        notes="This was a 97% -> 100% fix. The 'clever' pointer arithmetic produced worse results than simple array[i].",
    ),
    Pattern(
        id="manual-null-check-vs-wrapper",
        name="Manual Null Check Instead of Wrapper Function",
        description="Using verbose null-check-then-access pattern when a wrapper function exists.",
        root_cause="Many HSD/baselib functions have wrapper functions that handle null checks internally. Using these produces cleaner, more idiomatic code that often matches better.",
        signals=[
            Signal(
                type="code_smell",
                data={"pattern": "tmp = x; if (tmp == NULL) tmp = NULL; else tmp = tmp->field"},
                description="Verbose null check cascade",
            ),
        ],
        examples=[
            Example(
                function="mnDiagram2_ClearStatRows",
                context="mn/mndiagram2.c - discovered 2026-01-24",
                before="""\
tmp = data->icon_parent;
if (tmp == NULL) {
    tmp = NULL;
} else {
    tmp = ((JObjContainer*) tmp)->jobj;
}
jobj = tmp;
if (jobj != NULL) {
    HSD_JObjRemoveAll(jobj);
}""",
                after="""\
jobj = HSD_JObjGetChild(data->icon_parent);
if (jobj != NULL) {
    HSD_JObjRemoveAll(jobj);
}""",
            ),
        ],
        fixes=[
            Fix(
                description="Replace manual null-check-and-access with wrapper function",
                before="""\
tmp = ptr;
if (tmp == NULL) tmp = NULL;
else tmp = tmp->child;
result = tmp;""",
                after="""\
result = HSD_JObjGetChild(ptr);""",
                success_rate=0.9,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnDiagram2_ClearStatRows", date="2026-01-24"),
            ],
        ),
        opcodes=["cmplwi", "beq", "lwz"],
        categories=["anti-pattern", "inline", "simplification"],
        notes="Common wrappers: HSD_GObjGetUserData, HSD_JObjGetChild, HSD_JObjGetSibling, HSD_JObjGetParent. Check baselib/*.h for available wrappers.",
    ),
    Pattern(
        id="direct-field-vs-wrapper",
        name="Direct Field Access Instead of Getter Function",
        description="Using gobj->user_data directly when HSD_GObjGetUserData(gobj) exists and is idiomatic.",
        root_cause="The codebase often uses getter functions consistently. While direct access may work, using the getter produces more idiomatic code that matches common patterns.",
        signals=[
            Signal(
                type="code_smell",
                data={"pattern": "gobj->user_data"},
                description="Direct user_data access instead of getter",
            ),
        ],
        examples=[
            Example(
                function="mnDiagram2_ClearStatRows",
                context="mn/mndiagram2.c",
                before="""\
data = gobj->user_data;""",
                after="""\
data = (Diagram2*) HSD_GObjGetUserData(gobj);""",
            ),
        ],
        fixes=[
            Fix(
                description="Use getter function instead of direct field access",
                before="data = gobj->user_data;",
                after="data = HSD_GObjGetUserData(gobj);",
                success_rate=0.85,
            ),
        ],
        opcodes=["lwz"],
        categories=["anti-pattern", "simplification"],
        notes="Run 'melee-agent patterns wrapper <field>' to find available wrapper functions. Currently 84+ uses of HSD_GObjGetUserData in matched code.",
    ),
    Pattern(
        id="slwi-inside-call-vs-simple",
        name="Forcing slwi Generation with Inline Expressions",
        description="Trying to force specific instruction emission by putting expressions inside function calls, when simpler code works.",
        root_cause="Attempts to force slwi (shift left) generation by using expressions like (i << 2) inside function call arguments. Usually unnecessary - simple array indexing achieves the same result.",
        signals=[
            Signal(
                type="code_smell",
                data={"pattern": "func(((Type*)((u8*)ptr + (i << 2)))->field)"},
                description="Complex expression inside function call to force instruction",
            ),
        ],
        examples=[
            Example(
                function="mnDiagram2_ClearStatRows",
                context="mn/mndiagram2.c - attempted but rejected 2026-01-24",
                before="""\
// Attempt to force slwi emission - OVERLY COMPLEX
HSD_SisLib_803A5CC4(((Diagram2*) ((u8*) data + (i << 2)))->row_labels[0]);""",
                after="""\
// Simple and correct
HSD_SisLib_803A5CC4(ptr->row_labels[i]);""",
            ),
        ],
        fixes=[
            Fix(
                description="Use simple array indexing instead of forcing instruction generation",
                before="func(((Type*)((u8*)ptr + (i << 2)))->field[0]);",
                after="func(ptr->field[i]);",
                success_rate=0.95,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="mnDiagram2_ClearStatRows", date="2026-01-24"),
            ],
        ),
        opcodes=["slwi", "add"],
        categories=["anti-pattern", "simplification"],
        notes="This is a 'local maximum' trap - the complex expression may get you to 99% but can't reach 100%. Step back and try the simple approach.",
    ),
]


def load_samples(db) -> None:
    """Load all sample patterns into the database."""
    for pattern in SAMPLE_PATTERNS:
        try:
            db.insert(pattern)
            print(f"  Inserted: {pattern.id}")
        except Exception as e:
            print(f"  Skipped {pattern.id}: {e}")
