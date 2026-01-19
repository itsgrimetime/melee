---
name: mismatch-db
description: Knowledge base for common assembly mismatches. Use to interpret diffs when matching functions.
---

# Common Causes for Match Failure

A catalog of common reasons why compiled C code doesn't match target assembly. Use this when debugging diffs from decomp.me scratches.

## Incorrect Stack Size

The target assembly calls `stwu` with a different offset, affecting many downstream `r1` accesses.

### Example diff
```diff
@@ -1,41 +1,41 @@ function_name
 0x000000: mflr r0
 0x000004: stw r0 0x4(r1)
-0x000008: stwu r1 -0x28(r1)
+0x000008: stwu r1 -0x20(r1)
-0x00000c: stw r31 0x24(r1)
+0x00000c: stw r31 0x1c(r1)
-0x000010: stw r30 0x20(r1)
+0x000010: stw r30 0x18(r1)
```

### Supporting evidence
- The `stwu r1` instruction at function start uses wrong offset
- The `addi r1 r1` instruction at function end uses wrong immediate
- All `r1` offsets are shifted by the same amount

### Root cause
The stack is too large or too small. Extra local variables, or missing ones.

### Fix
- If stack is too large: reuse variables, combine declarations
- If stack is too small: use the `PAD_STACK` macro after final stack variable

```c
Item* ip = GET_ITEM(gobj);
HSD_GObj* go = it_8027236C(gobj);
PAD_STACK(8);  // Add padding to match stack size
```

---

## Copying Structs Field-by-Field

The diff shows loads/stores that differ in type: target uses `lwz`/`stw`, your code uses `lfs`/`stfs`.

### Example diff
```diff
-0x000008: lwz r5 0x4(r3)
+0x000008: lwz r3 0x4(r3)
-0x00000c: lwz r3 0x4(r5)
+0x00000c: lfs f0 0x4(r3)
-0x000010: lwz r0 0x8(r5)
+0x000010: stfs f0 0x0(r4)
-0x000014: stw r3 0x0(r4)
+0x000014: lfs f0 0x8(r3)
```

### Supporting evidence
- Multiple assignments in a row with sequential offsets
- Code involving `Vec3` or other small structs
- `lfs`/`stfs` vs `lwz`/`stw` mismatch

### Root cause
When copying an entire struct, the compiler copies word-by-word without regard to field types. m2c generates field-by-field copies that use type-appropriate instructions.

### Fix
Assign the entire struct in one expression:

```diff
-pos->x = attrs->x4.x;
-pos->y = attrs->x4.y;
-pos->z = attrs->x4.z;
+*pos = attrs->x4;
```

---

## Wrong Loop Increment Order

Register allocation differs when loop increment happens in different places.

### Example diff
```diff
-0x000024: addi r30 r30 1
-0x000028: cmpwi r30 10
+0x000024: cmpwi r30 10
+0x000028: addi r30 r30 1
```

### Root cause
The loop counter increment is happening before/after the comparison differently than expected.

### Fix
Try moving the increment:
```diff
-for (i = 0; i < 10; i++) {
+for (i = 0; i < 10; ++i) {
```
Or restructure as a while loop with explicit increment placement.

---

## Inline vs Non-Inline Function

Extra `bl` (branch and link) instructions appear, or function body is unexpectedly inlined.

### Supporting evidence
- Unexpected `bl` to a function that should be inlined
- Or: function body appears inline when it should be a call

### Root cause
Compiler inlining decisions differ. Small functions may be inlined with `-O4,p -inline auto`.

### Fix
- For unwanted inlining: move function to separate translation unit
- For missing inlining: ensure function is `static inline` or in header

---

## Ternary vs If-Else

Different branch patterns for conditional assignments.

### Example
```c
// May compile differently:
x = (cond) ? a : b;
// vs
if (cond) x = a; else x = b;
```

### Fix
Try both forms. Sometimes `? :` produces tighter code, sometimes `if/else` does.

---

## Float Comparison Sign

`fcmpo` vs `fcmpu` or wrong comparison register.

### Root cause
Float comparisons with different signedness or comparison modes.

### Fix
Check if comparison involves potential NaN values. Try `>=` vs `>` or signed vs unsigned comparison.

---

## ABS/FABS Macro Usage

Manual absolute value check vs macro.

### Example diff
Target uses fewer instructions for absolute value.

### Fix
Use the `ABS` or `FABS` macro:
```diff
-if (val < 0.0f) val = -val;
+val = ABS(val);
```

---

## Volatile Access Patterns

Extra loads/stores that seem redundant.

### Supporting evidence
- Variables being loaded multiple times when once would suffice
- Stores followed immediately by loads of same address

### Root cause
Volatile or memory-mapped accesses that must not be optimized.

### Fix
Check if the original code uses `volatile` or accesses hardware registers.

---

## Bitfield Packing

Complex bit manipulation that doesn't match.

### Supporting evidence
- Shifts, masks, and OR operations
- Accessing struct with bitfield members

### Root cause
m2c doesn't understand bitfields well and generates explicit bit manipulation.

### Fix
Replace bit arithmetic with direct bitfield access:
```diff
-flags = (flags & ~0x7) | (value & 0x7);
+obj->bitfield_0_3 = value;
```

---

## Base-Relative String Addressing (Assertions)

String literals (especially in assertions) are addressed relative to a base pointer instead of via SDA or literal pool.

### Example diff
```diff
-0x000054: lis r3, "@string"@ha
-0x000058: addi r3, r3, "@string"@l
+0x000054: addi r3, r31, 0x70
 0x000058: crclr cr1eq
 0x00005c: bl OSReport
-0x000060: lis r3, "@file"@ha
-0x000064: addi r3, r3, "@file"@l
+0x000060: addi r3, r31, 0x88
+0x000064: addi r5, r31, 0x94
```

### Supporting evidence
- `addi rX, rY, <offset>` used to load string addresses
- The base register (r31, r29, etc.) points to a static struct
- Multiple strings referenced at sequential offsets from the same base
- Common in menu code (`mn/`) with `OSReport` and `__assert` calls

### Root cause
The original compiler placed string literals in the `.data` section immediately after a static struct. It then references them relative to the base pointer already loaded for the struct.

For example, if `mnDataDel_803EF870` is a struct ending at offset 0x70, the assertion strings are at:
- Offset 0x70: `"Can't get user_data.\n"`
- Offset 0x88: `"mndatadel.c"`
- Offset 0x94: `"user_data"`

Our compiler typically places strings in `.rodata` or SDA, not adjacent to the struct.

### Finding similar matched functions
Use the `/opseq` skill to find already-matched functions with the same pattern:

```bash
cd ~/code/melee && melee-agent opseq search addi,crclr,bl,addi,addi,li,bl
```

This finds functions using the OSReport+assert pattern. Check their source to see how they achieved the match.

### Potential fixes
1. **Check already-matched functions** - Some mn/ functions like `mnlanguage.c` have this pattern matched. Study their data layout.
2. **Struct padding** - Ensure the struct size exactly matches so strings can follow at the expected offsets.
3. **Data section ordering** - The linker script may need modification to place strings correctly (rarely practical).

### Note
This pattern is often a significant blocker (~10-15% mismatch) and may require accepting a lower match percentage if the data layout cannot be controlled.

---

## Understanding Match Percentages

**CRITICAL**: The DOL SHA1 checksum **ALWAYS passes** - this is NOT evidence of function matching!

The decomp project links unmatched functions from the original ROM, so the final DOL always matches. Individual function match percentages come from comparing compiled object files.

### Authoritative Match Sources

1. **`report.json`** - The `fuzzy_match_percent` field is the ground truth
2. **decomp.me scratch** - Shows match % after compilation
3. **decomp-dev bot** - Comments on PRs with accurate percentages

### What DOL SHA1 Does NOT Tell You

```bash
ninja
# "build/GALE01/main.dol: OK" - This ALWAYS passes!
# It does NOT mean your function is 100% matched
```

### How to Verify True 100% Match

```bash
# In a worktree, use --melee-root . to read the local report.json
melee-agent extract get <function_name> --melee-root .
# Shows "Match: XX.X%" from report.json
```

A function is 100% matched ONLY when this shows `Match: 100.0%` (or very close like 99.9+).

**Note**: Without `--melee-root .`, the CLI reads from the main melee symlink, not your worktree.

---

## Variadic Function va_list Offset

The `va_list` structure is stored at the wrong stack offset, causing all vararg access to be misaligned.

### Example diff
```diff
-0x000074: stw r0, 0x74(r1)    ; va_list at expected offset
+0x000074: stw r0, 0x70(r1)    ; va_list 4 bytes too early
```

### Supporting evidence
- Function uses `va_start`, `va_arg`, `va_end`
- Stack offsets for va_list storage differ by 4 or 8 bytes
- The `__va_arg` call and surrounding code has offset mismatches

### Root cause
MWCC places `va_list` at a specific stack offset based on local variable layout. If the offset is wrong, you need to add padding variables before `va_list` in declaration order.

### Fix
Add a dummy variable before `va_list` to shift its stack position:

```c
int my_variadic_func(int arg0, ...) {
    va_list ap;
    s32 _unused;  // Padding to shift va_list offset

    _unused = 0;
    (void) _unused;  // Suppress unused warning

    va_start(ap, arg0);
    // ...
}
```

Adjust the padding size (s32 = 4 bytes, s64 = 8 bytes) until the offset matches.

---

## Branch Polarity (beq vs bne) with NULL Checks

The branch instruction has wrong polarity - `beq` when expected `bne`, or vice versa.

### Example diff
```diff
-0x000010: bne 0x24    ; branch if NOT null to load case
+0x000010: beq 0x24    ; branch if null (wrong polarity)
```

### Supporting evidence
- NULL checks on pointers before field access
- Code pattern like `if (ptr) { use ptr->field; }`
- Inverted branch direction

### Root cause
Direct comparisons like `if (ptr != NULL)` may generate different branch polarity than the original code which used inline functions with early-return NULL checks.

### Fix
Use inline functions with the NULL-check-and-return pattern:

```c
static inline HSD_JObj* jobj_child(HSD_JObj* jobj)
{
    if (jobj == NULL) {
        return NULL;
    }
    return jobj->child;
}

// Usage - this generates bne to the load case:
if (jobj_child(parent)) {
    new_jobj = jobj_child(parent);
}
```

The `if (x == NULL) return NULL; return x->field;` pattern generates:
1. `cmplwi rX, 0` - compare with NULL
2. `bne` to the load case (branch if NOT equal to NULL)
3. `li r0, 0` - NULL case returns 0
4. `lwz r0, offset(rX)` - load case

---

## Extra Register Move (mr) After Inline Return

An extra `mr rX, r0` instruction appears when assigning inline function result to a variable.

### Example diff
```diff
-0x000050: lwz r4, 0xC(r4)     ; load directly into r4
+0x000050: lwz r0, 0xC(r4)     ; load into r0
+0x000054: mr r4, r0           ; then move to r4
```

### Supporting evidence
- Assignment like `parent = get_parent(parent);` where `get_parent` is inline
- The inline function returns through r0/r3
- An extra `mr` instruction copies the return value to the target register

### Root cause
Inline functions return their value in r0 (or r3), which then gets copied to the destination. The original code used direct assignment patterns that load/store directly to the target register.

### Fix
Replace inline function calls with explicit if-else for direct assignment:

```diff
-parent = jobj_parent(parent);
+if (parent == NULL) {
+    parent = NULL;
+} else {
+    parent = parent->parent;
+}
```

This generates direct loads/stores to the target register without going through r0.

**Trade-off**: This may affect register allocation order (see next pattern).

---

## Callee-Saved Register Allocation Order (r27-r31)

Registers r27-r31 are allocated to different variables than expected.

### Example diff
```diff
-0x000010: mr. r29, r3    ; root in r29
-0x000014: addi r30, r4   ; output in r30
-0x000018: li r31, 0      ; count in r31
+0x000010: mr. r30, r3    ; root in r30 (wrong!)
+0x000014: addi r31, r4   ; output in r31 (wrong!)
+0x000018: li r29, 0      ; count in r29 (wrong!)
```

### Supporting evidence
- Same instructions but different register numbers
- Callee-saved registers (r27-r31) are rotated or swapped
- Function logic is correct but register assignment differs

### Root cause
MWCC allocates callee-saved registers based on variable usage patterns and declaration order. Changes to inline function usage or code structure can affect allocation order.

### Fix
Reorder variable declarations to match expected allocation. Variables declared/used later tend to get higher register numbers (r31 before r30 before r29):

```diff
 int my_func(Type* root, Type** output, ...) {
     va_list ap;
     s32 _unused;
-    s32 count;        // was early, got r29
     s32 prev_idx;
     Type* parent;
     s32 pos;
     s32 idx;
     Type* jobj;
     Type* new_jobj;
+    s32 count;        // moved to end, now gets r31
```

This is often trial-and-error. The goal is to make variables that should be in higher registers (r31, r30) be declared or first-used later in the function.
