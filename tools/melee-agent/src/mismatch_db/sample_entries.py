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
    Pattern(
        id="thp-component-layout-pred-dc-padding",
        name="THP Component Layout predDC Padding",
        description="THP decoder functions address component fields and restart fields at offsets that differ from the current struct layout.",
        root_cause="The `predDC` field belongs at THP component offset +6, and restart fields live after the component array with post-component padding.",
        signals=[
            Signal(
                type="offset_delta",
                data={"register": "struct_base", "delta": None},
                description="THP component and restart-field accesses are shifted by a small fixed offset",
            ),
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lha", "sth", "lwz", "stw"]},
                description="DCT component decode reads and writes predictor/restart state at THPFileInfo component offsets",
            ),
        ],
        examples=[
            Example(
                function="__THPHuffDecodeDCTCompY",
                context="THP decoder component predictor layout",
                before="""\
typedef struct THPComponent {
    u8 quantizationTableSelector;
    u8 DCTableSelector;
    u8 ACTableSelector;
    s16 predDC;
} THPComponent;""",
                after="""\
typedef struct THPComponent {
    u8 quantizationTableSelector;
    u8 DCTableSelector;
    u8 ACTableSelector;
    u8 pad;
    s16 predDC; // component offset +6
} THPComponent;""",
            ),
            Example(
                function="__THPRestartDefinition",
                context="THP restart fields after padded component array",
            ),
        ],
        fixes=[
            Fix(
                description="Model the THP component padding explicitly so `predDC` lands at component offset +6 and restart fields follow the padded component array.",
                success_rate=1.0,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="__THPHuffDecodeDCTCompY", date="2026-05-27"),
                ProvenanceEntry(function="__THPRestartDefinition", date="2026-05-27"),
            ],
            helped_match=[
                ProvenanceEntry(function="__THPHuffDecodeDCTCompY", date="2026-05-27"),
                ProvenanceEntry(function="__THPRestartDefinition", date="2026-05-27"),
            ],
        ),
        opcodes=["lha", "sth", "lwz", "stw"],
        categories=["struct", "data-layout", "type"],
        notes="Harvested from the quick-win pass; screen for localized THP component/restart offset differences, not broad register cascades.",
    ),
    Pattern(
        id="function-pointer-cast-forces-indirect-call",
        name="Function Pointer Cast Forces Indirect Call",
        description="A direct call compiles as a load into CTR/LR and `blrl` because the source casts the callee to a function-pointer type.",
        root_cause="The function-pointer cast hides the direct callee from MWCC, forcing an indirect call sequence (`mtlr`/`blrl`) where the original source used a normal direct `bl`.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lis", "addi", "mtlr", "blrl"]},
                description="Current source materializes a function address and calls it indirectly",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl", "actual": "blrl"},
                description="Expected direct branch-and-link, current emits indirect branch-and-link",
            ),
        ],
        examples=[
            Example(
                function="fn_800D7938",
                context="Item call through an unnecessary function-pointer cast",
                before="((void (*)(HSD_GObj*)) it_80291F14)(gobj);",
                after="it_80291F14(gobj);",
            ),
        ],
        fixes=[
            Fix(
                description="Remove the function-pointer cast and call the typed callee directly. If the prototype is wrong, fix the declaration instead of casting at the call site.",
                before="((Ret (*)(Args...)) callee)(args);",
                after="callee(args);",
                success_rate=1.0,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="fn_800D7938", date="2026-05-27"),
            ],
            helped_match=[
                ProvenanceEntry(function="fn_800D7938", date="2026-05-27"),
            ],
        ),
        opcodes=["bl", "blrl", "mtlr", "lis", "addi"],
        categories=["calling-conv", "type", "control-flow"],
        notes="Accept only localized direct-vs-indirect call diffs. If register allocation differences sprawl beyond the call, treat it as compound.",
    ),
    Pattern(
        id="sparse-scratch-array-no-zero-init",
        name="Sparse Scratch Array Without Zero Initialization",
        description="A fixed-size scratch array passed to a type-dispatched consumer should be declared bare, not initialized with `= {0}`, when the target only stores selected fields.",
        root_cause="m2c often reconstructs command buffers as zero-initialized records, but MWCC emits a separate zeroing block and then overwrites fields. The original source writes only the fields required by the command type, leaving omitted fields dirty.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["stw", "stw", "bl"]},
                description="Sparse stores into a stack array immediately before a consumer call",
            ),
            Signal(
                type="code_smell",
                data={"pattern": "s32 cmd[N] = {0}"},
                description="Zero-initialized fixed-size local command buffer",
            ),
        ],
        examples=[
            Example(
                function="fn_803B0E9C",
                context="hsd_3AA7.c command buffer builder, type-dispatched through fn_803AC168",
                before="""\
s32 cmd[9] = { 0 };
cmd[0] = type;
cmd[1] = arg1;
cmd[2] = arg2;
fn_803AC168(cmd);""",
                after="""\
s32 cmd[9];
cmd[0] = type;
cmd[1] = arg1;
cmd[2] = arg2;
fn_803AC168(cmd);""",
            ),
            Example(
                function="fn_803ADF90",
                context="Same sparse scratch array class; field set varies by command type",
            ),
            Example(
                function="fn_803AD16C",
                context="Opcode similarity improved after removing zero initialization",
            ),
        ],
        fixes=[
            Fix(
                description="Drop `= {0}`, declare the fixed-size array bare, and write exactly the fields the target stores, including explicit zero stores that are present in the target.",
                before="s32 cmd[9] = { 0 };",
                after="s32 cmd[9];",
                success_rate=0.75,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="fn_803B0E9C", date="2026-06-04"),
                ProvenanceEntry(function="fn_803ADF90", date="2026-06-04"),
                ProvenanceEntry(function="fn_803AD16C", date="2026-06-04"),
            ],
        ),
        opcodes=["stw", "bl"],
        categories=["stack", "array", "source-transform"],
        notes="Use this only when checkdiff says current is larger. If expected is larger or an inline boundary dominates, removing instructions can falsely raise fuzzy match while collapsing opcode similarity.",
    ),
    Pattern(
        id="loop-field-reload-comma-assignment",
        name="Loop Field Reload Via For-Condition Comma Assignment",
        description="A struct field reloaded every loop iteration and reused in the loop body can be modeled with a for-condition comma assignment so one reload feeds both condition and body, coalescing the uses into one callee-save.",
        root_cause="Plain C that reads `state->field` in both the condition and body can make MWCC emit two reloads. Assigning a local in the for condition, such as `for (i = 0; size = state->x8, i < bound / size; i++)`, creates the target's single per-iteration reload and callee-save reuse.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "divw", "mullw", "bl"]},
                description="One field reload reused for loop bound, offset math, and callee argument",
            ),
        ],
        examples=[
            Example(
                function="fn_803ACD58",
                context="CardState loop reloads state->x8 each iteration and reuses it for CARDRead size",
                before="""\
for (i = 0; i < state->x4 / state->x8; i++) {
    offset = i * state->x8;
    CARDRead(file, dst, state->x8, offset);
}""",
                after="""\
for (i = 0; size = state->x8, i < state->x4 / size; i++) {
    offset = i * size;
    CARDRead(file, dst, size, offset);
}""",
            ),
        ],
        fixes=[
            Fix(
                description="Introduce a loop-local size variable assigned in the for-condition comma expression, then reuse that local in the condition and body.",
                success_rate=0.6,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="fn_803ACD58", date="2026-06-04"),
            ],
        ),
        opcodes=["lwz", "mullw", "divw"],
        categories=["loop", "register", "source-transform"],
        notes="This is useful when the target reloads the field once per iteration and coalesces the reload into one callee-save. Remaining differences may still be register numbering.",
    ),
    Pattern(
        id="inverse-cse-rematerialized-global-read",
        name="Inverse CSE Rematerialized Global Read",
        description="The target rematerializes or must rematerialize a non-volatile global read, while source forms that reuse the obvious local make MWCC CSE the reads and collapse distinct register roles.",
        root_cause="Some targets intentionally or incidentally reload a non-volatile global for a later array index while keeping a prior value live across a call. Natural C expressions that index by the saved local can make MWCC common-subexpression-eliminate the second read, causing a register cascade.",
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "bl", "lwz"]},
                description="A global is read, a call occurs, then the same global is read again for indexing",
            ),
        ],
        examples=[
            Example(
                function="fn_803AC168",
                context="CardState read index is kept across OSRestoreInterrupts while hsd_804D1148 indexing rematerializes the non-volatile global read",
            ),
        ],
        fixes=[
            Fix(
                description="First confirm the target really rematerializes instead of CSEing. If ordinary locals CSE the reads, try source forms that force a distinct reload; if no C lever is found, bank it as a current-tooling register ceiling rather than chasing register cascades.",
                success_rate=0.2,
            ),
        ],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="fn_803AC168", date="2026-06-04"),
            ],
        ),
        opcodes=["lwz", "bl"],
        categories=["global", "register", "ceiling"],
        notes="This is a ceiling characterization as much as a lever. It is the inverse of the usual source-rematerializes/target-CSEs mismatch.",
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


_MIGRATED_SAMPLE_PATTERN_IDS = {
    "sparse-scratch-array-no-zero-init",
    "loop-field-reload-comma-assignment",
    "inverse-cse-rematerialized-global-read",
}


def _replace_migrated_sample(db, pattern: Pattern) -> None:
    existing = db.get(pattern.id)
    if existing is not None:
        pattern.provenance.helped_match = existing.provenance.helped_match
    db.delete(pattern.id)
    db.insert(pattern)


def load_samples(db) -> None:
    """Load all sample patterns into the database."""
    for pattern in SAMPLE_PATTERNS:
        try:
            db.insert(pattern)
            print(f"  Inserted: {pattern.id}")
        except Exception as e:
            if pattern.id in _MIGRATED_SAMPLE_PATTERN_IDS:
                try:
                    _replace_migrated_sample(db, pattern)
                    print(f"  Updated: {pattern.id}")
                    continue
                except Exception as update_error:
                    print(f"  Skipped {pattern.id}: {update_error}")
                    continue
            print(f"  Skipped {pattern.id}: {e}")
