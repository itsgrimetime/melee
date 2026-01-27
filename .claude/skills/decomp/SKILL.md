---
name: decomp
description: Match decompiled C code to original PowerPC assembly for Super Smash Bros Melee using the local workflow. Edit source files directly and use tools/checkdiff.py to view diffs. Invoked with /decomp <function_name> or automatically when working on decompilation tasks.
---

# Melee Decompilation Matching (Local Workflow)

You are an expert at matching C source code to PowerPC assembly for the Melee decompilation project. Your goal is to achieve byte-for-byte identical compilation output.

## Session State Tracking

**Track your session state throughout the session.** After every context reset or when resuming work, remember:

- **Active function**: (the one you're working on)
- **Source file**: (the file you're editing)
- **Current match %**: (your progress)

## Workflow Overview

The local workflow is simpler and faster than the remote decomp.me workflow:

1. **Find function** to work on
2. **Get first-pass decompilation** with `tools/decomp.py`
3. **Edit source file** directly in `src/melee/`
4. **Check diff** with `tools/checkdiff.py <function_name>`
5. **Iterate** until matched (or close enough)
6. **Commit** your changes

## CRITICAL: Think Like a Developer, Not Like the ASM

**The biggest trap in decompilation is trying to literally recreate the assembly in C.**

Complex ASM patterns are almost always **compiler optimizations** of simple source code. Developers write natural, maintainable code - they don't manually unroll loops or write bizarre pointer arithmetic.

### The Developer's Code vs. The Compiler's Output

| You see in ASM | You might try | What developer actually wrote |
|----------------|---------------|-------------------------------|
| 8 manual stores + `bdnz` loop | Partially-unrolled loop with goto | Simple `for (i = 0; i < 10; i++)` loop |
| Complex `slwi`/`add` sequence | Pointer arithmetic with shifts | Array indexing: `data->field[i]` |
| `subfic`/`adde` pair | Two's complement tricks | Simple `abs(x)` or `ABS()` macro |
| Interleaved loads/stores | Hand-optimized access pattern | Sequential field assignments |

### Ask These Questions First

Before attempting exotic tricks to match ASM:

1. **"What is this function actually doing?"** - Name it, describe its purpose
2. **"How would a developer write this naturally?"** - Simple loops, clear conditions
3. **"Could this complex pattern be a compiler optimization?"** - Usually yes!

### Real Example: mnDiagram2_InitUserData

**What the ASM showed:**
- 8 manual NULL stores (partial unroll)
- `subfic r0, r4, 8` / `mtctr r0` / `bdnz` loop for remaining 2 iterations
- Looked like developer wrote a partially-unrolled loop

**Failed attempts (stuck at 95.6%):**
- Manual unrolling with explicit stores: 82.2%
- goto-based loop pattern: 93.0%
- Pointer countdown loop: 82.2%
- Various pragma attempts: no improvement

**What actually matched (100%):**
```c
int i;  // KEY: int, not s32!
for (i = 0; i < 10; i++) {
    data->row_labels[i] = NULL;
    data->row_values[i] = NULL;
    data->row_icons[i] = NULL;
}
```

**The insight:** The developer wrote a simple for loop. MWCC's optimizer partially unrolled it. The "complex" ASM was generated, not authored.

### MWCC Loop Unrolling: `int` vs `s32`

MWCC treats loop counter types differently:

- `int i` - May trigger different unrolling heuristics
- `s32 i` - `s32` is typedef'd to `long`, which MWCC handles differently

**If a simple loop doesn't match, try changing `s32 i` to `int i`** (or vice versa). This is a known MWCC quirk that affects loop optimization decisions.

### Signs You're Trapped in ASM-Literal Mode

- You're writing pointer arithmetic instead of array indexing
- You're manually unrolling loops to match iteration counts
- You're adding goto statements to match branch targets
- You're trying increasingly exotic tricks while match % plateaus
- The code looks nothing like what a developer would write

### How to Escape

1. **Step back** - Delete your complex attempts
2. **Write the simplest possible code** that implements the function's purpose
3. **Try type variations** - `int` vs `s32`, `f32` vs `float`
4. **Check similar matched functions** - Use `/opseq` to find comparable code
5. **Only add complexity if simple doesn't work** - and question why

## Step 1: Choose a Function

**If user specifies a function:** Skip to Step 2.

**Otherwise:** Find a good candidate using the build report:

```bash
# Build first to generate report
python configure.py && ninja

# Query the report for unmatched functions
python3 << 'EOF'
import json
with open('build/GALE01/report.json') as f:
    data = json.load(f)
for unit in data.get('units', []):
    for func in unit.get('functions', []):
        pct = func.get('fuzzy_match_percent', 0)
        if 50 < pct < 100:  # Good candidates: partially matched
            print(f"{func['name']}: {pct:.1f}%")
EOF
```

**Quick wins:** Functions at 80-99% are often just register allocation or small type issues.

## Step 2: Get First-Pass Decompilation

Use local m2c for the initial decompilation:

```bash
# Basic usage
python tools/decomp.py <function_name> --no-copy

# With formatting
python tools/decomp.py <function_name> --no-copy -f  # clang-format
```

**Module-specific flags** dramatically improve output quality:

| Module | Recommended Flags |
|--------|-------------------|
| `it_*` (items) | `--union-field Item_ItemVars:<item_type>` |
| `ft_*` (fighters) | `--void-var-type fp:FighterData` |
| Callbacks | `--void` (if return type unknown) |

**Example for item functions:**
```bash
python tools/decomp.py --no-copy it_802E1C4C -- \
  --union-field Item_ItemVars:linkarrow \
  --void-field-type Article.x4_specialAttributes:itLinkArrowAttributes
```

## Step 3: Edit the Source File

Find and edit the source file directly:

```bash
# Find where the function lives
grep -rn "function_name" src/melee/

# Or use the build report to find the file
python3 -c "
import json
with open('build/GALE01/report.json') as f:
    for unit in json.load(f).get('units', []):
        for func in unit.get('functions', []):
            if func.get('name') == 'function_name':
                print(unit.get('name'))
"
```

Edit the `.c` file in `src/melee/<module>/<file>.c`.

**Important:**
- If the function already exists (stub or partial), update it in place
- If the function doesn't exist, add it to the appropriate location
- Include any file-local structs the function needs

## Step 4: Check the Diff

Use `tools/checkdiff.py` to see how your code compares to the target:

```bash
python tools/checkdiff.py <function_name>
```

This will:
1. Build the affected object file
2. Show a side-by-side diff (EXPECTED on left, CURRENT on right)
3. Report whether it matches and the current match percentage

**Output interpretation:**
- `--- MATCH: function_name matches! ---` - You're done!
- Each line shows function-relative offset (`+000:`, `+004:`, etc.)
- Lines marked with `-` are in EXPECTED only (missing from your code)
- Lines marked with `+` are in CURRENT only (extra in your code)
- Use offsets to identify where mismatches occur and verify branch targets

**Common diff patterns:**
- Register differences (`r3` vs `r4`) - reorder variable declarations
- Extra `frsp` instructions - use `f32` instead of `float`
- Extra `extsb`/`extsh` - check signedness of variables
- Different branch targets - control flow structure differs

## Step 5: Iterate

Make changes to your code and re-run checkdiff:

```bash
# Quick iteration cycle
python tools/checkdiff.py <function_name>
```

### CRITICAL: Structure First, Registers Last

**Do NOT try to fix register differences until the instruction sequence matches.**

Register allocation is highly dynamic - it changes based on:
- Variable declaration order
- Control flow structure
- Which variables are live at each point
- Inlining decisions

**The right approach:**
1. First, get the **instruction sequence** correct (same opcodes in same order)
2. Then, get the **control flow** correct (branches, loops, conditions)
3. Only **after** structure matches, fix register allocation by reordering declarations

**Why this matters:** Trying to fix registers early leads to a "local maximum" - you might hit 85% by shuffling declarations, but you'll be stuck there because the underlying structure is wrong. When you fix the structure, registers often "fall into place" automatically.

**Signs you're chasing registers too early:**
- You're reordering the same declarations back and forth
- Match % oscillates but doesn't improve
- The diff shows different instructions, not just different registers

### CRITICAL: Match % Can Drop When You're on the Right Track

**Do NOT revert a change just because match % dropped - if the structure became MORE correct, keep it.**

Fuzzy match % measures instruction similarity, but it doesn't understand semantics. A structurally correct version can score LOWER than an incorrect one.

**Example:** If target has `bl some_func` (function call) but your code inlines it:
- Inlined version: 85% match (wrong structure, but instructions happen to be similar)
- With `#pragma dont_inline`: 60% match (correct `bl` instruction, but rest needs work)

**The 60% version is BETTER** - it has the right structure. You can improve from there. The 85% version is a dead end.

**When to accept a match % drop:**
- You fixed a `bl` (function call) that was being inlined
- You fixed a loop structure (do-while vs while vs for)
- You fixed control flow (if/else ordering, switch vs if-chain)
- You added correct `#pragma` directives

**When to revert:**
- The diff shows MORE wrong instructions, not just different ones
- You introduced new structural problems
- The change was purely speculative with no reasoning

**Rule of thumb:** If you can explain WHY the change makes the code structurally correct (e.g., "now it has the right function call" or "now the loop matches"), keep it even if match % dropped.

### Common Fixes (in priority order)

| Priority | Symptom | Fix |
|----------|---------|-----|
| 1st | Different/extra/missing instructions | Fix types, casts, operators |
| 2nd | Different control flow | Restructure if/else, use switch, change loop style |
| 3rd | Extra conversion instructions | Fix types: `int`→`s32`, `float`→`f32` |
| 4th | Loop unrolling mismatch | Try `int i` vs `s32 i` for loop counter |
| 5th | Function not inlining | Check if called function should be static |
| **Last** | Register allocation wrong | Reorder variable declarations |

**Register allocation tip:** Once structure matches, registers are allocated in declaration order. If you need `r31` for variable `foo`, declare `foo` first.

**Loop counter tip:** MWCC treats `int` and `s32` (typedef'd to `long`) differently for loop optimization. If a simple loop shows partial unrolling in the ASM, try switching between `int i` and `s32 i`.

### WARNING: PAD_STACK is Usually Wrong

**Do NOT reach for `PAD_STACK` as a first solution for stack size mismatches.**

`PAD_STACK(n)` is a "fakematch" - it forces the stack size to match but doesn't represent real code. It should be a **last resort**, not a quick fix.

**When you see a stack size mismatch, first investigate:**
1. **Missing inline function** - An 8-byte difference often means a missing inline
2. **Missing local variables** - The original code may have variables you haven't declared
3. **Missing compound expression temps** - Complex expressions create temporaries
4. **Wrong types** - `Vec3` vs `float[3]` allocate differently

**Before using PAD_STACK, ask yourself:**
- Have I looked for inline functions that should be called here?
- Have I compared my variable declarations to similar matched functions?
- Have I checked if there are unused variables in the original? (retail asserts, etc.)

**When PAD_STACK is acceptable:**
- You've exhausted other options and can't find the real cause
- The function is otherwise 100% matched
- No pointers are passed to stack data (which would cause UB)

**When PAD_STACK is harmful:**
- When the function passes pointers to stack variables - the padding location matters
- When it masks a real structural problem you should fix

**Stack allocation note:** Stack increases in 8-byte increments (64-bit aligned). An 8-byte mismatch strongly suggests a missing inline or variable, not just "padding needed."

## Step 5b: Try Simpler First (Before Getting Clever)

**Before trying complex tricks, check if simpler approaches work!**

Many mismatches are solved by *removing* complexity, not adding it. The compiler often generates identical code for simple constructs.

### Simplicity Checklist

Before attempting clever solutions like manual pointer arithmetic or forced instruction patterns, try:

1. **Use array indexing instead of pointer arithmetic**
   ```c
   // BAD: Complex pointer arithmetic
   base = (Type*) ((u8*) base + 4);
   base->field[0] = value;

   // GOOD: Simple array indexing (often compiles identically!)
   data->field[i] = value;
   ```

2. **Check for wrapper functions**
   ```bash
   melee-agent patterns wrapper "user_data"
   melee-agent patterns wrapper "jobj->child"
   ```
   Common wrappers:
   - `gobj->user_data` → `HSD_GObjGetUserData(gobj)`
   - `jobj->child` → `HSD_JObjGetChild(jobj)`
   - `jobj->parent` → `HSD_JObjGetParent(jobj)`

3. **Check for anti-patterns in your code**
   ```bash
   melee-agent patterns check src/melee/mn/myfile.c
   melee-agent patterns anti-pattern list
   ```

4. **Find similar matched functions**
   ```bash
   melee-agent patterns similar <function_name>
   ```

### Real Example: mnDiagram2_ClearStatRows

**What we tried (97% → 99%, but stuck):**
```c
// Attempt 1: Pointer arithmetic with always [0]
base = (Diagram2*) ((u8*) base + 4);
base->row_labels[0] = NULL;

// Attempt 2: Force slwi with inline (i << 2)
HSD_SisLib(((Diagram2*) ((u8*) data + (i << 2)))->row_labels[0]);
```

**What actually worked (100% match):**
```c
// Simple array indexing!
for (i = 0; i < 10; i++) {
    data->row_labels[i] = NULL;
}
```

**Lesson:** The "clever" pointer arithmetic was a local maximum. The simple approach compiled to identical assembly.

### When to Get Clever

Only try complex techniques after:
1. Simple array indexing doesn't work
2. Wrapper functions don't exist or don't help
3. You've checked matched similar functions for patterns
4. You've searched the mismatch-db for known solutions

## Step 6: Getting Unstuck

**Don't spin on the same mismatch!** After 2-3 failed attempts at the same issue, use these skills to find patterns and solutions:

### Use `/mismatch-db` for Known Patterns
```bash
# Search for patterns matching your issue
/mismatch-db search "frsp"           # Extra float conversion
/mismatch-db search "register"       # Register allocation
/mismatch-db search "branch"         # Control flow differences

# Check anti-patterns (overcomplicated code)
melee-agent mismatch list -c anti-pattern
```

### Use `/discord-knowledge` for Historical Context
The Discord knowledge base contains 6+ years of matching tricks:
```bash
/discord-knowledge search "stwu stack"   # Stack frame issues
/discord-knowledge search "inline"       # Inlining problems
/discord-knowledge search "volatile"     # Volatile tricks
```

### Use `/opseq` to Find Similar Functions
If stuck, find already-matched functions with similar opcode patterns:
```bash
/opseq <function_name>    # Find functions with similar assembly
```
Then read those matched functions to see how they solved similar issues.

### Use `/ppc-ref` for Instruction Details
When you don't understand what an instruction does:
```bash
/ppc-ref rlwinm    # Look up rotate/mask instruction
/ppc-ref fctiwz    # Float to integer conversion
```

## Step 7: Know When to Stop

- **Match achieved:** Diff shows no differences
- **Good enough:** 95%+ match with only minor differences
- **Time limit:** Don't spend more than 10-15 minutes on one function

Any improvement is valuable - commit partial progress rather than discarding work.

## Step 7: Commit

After matching (or making progress):

```bash
# Verify build passes
python configure.py && ninja

# Check the diff
git diff

# Commit with descriptive message
git add src/melee/<module>/<file>.c
git commit -m "<module>: match <function_name>"
```

**Commit message patterns:**
- `mn: match mnDiagram_80241B4C` - for 100% match
- `ft: improve ftCo_800D7268 to 95%` - for partial progress
- `lb: first-pass lbColl_80008440` - for new decompilation

## CRITICAL: Commit Requirements

Before committing, ensure:

1. **No merge conflict markers** - Files must not contain `<<<<<<<`, `=======`, or `>>>>>>>` markers

2. **No naming regressions** - Don't change english names to address-based names

3. **No pointer arithmetic** - Use struct access, not `((u8*)ptr)[offset]`

4. **Build passes** - Run `python configure.py && ninja`

## Human Readability

Matching is not just about 100% - the code should be readable:

### Function Names

Rename `fn_XXXXXXXX` when purpose is clear:
```c
// Keep address-based name if purpose unclear
fn_80022120(data, row, col, &r, &g, &b, &a);

// Rename when purpose is obvious from the code
lbRefract_ReadTexCoordRGBA8(data, row, col, &r, &g, &b, &a);
```

### Variable Names

Use descriptive names:
```c
// Before
s32 temp_r3 = gobj->user_data;
f32 var_f1 = fp->x2C;

// After
FighterData* fp = gobj->user_data;
f32 facing_dir = fp->facing_direction;
```

### Struct Field Access

**Never use pointer arithmetic:**
```c
// BAD
if (((u8*)&lbl_80472D28)[0x116] == 1) {

// GOOD
if (lbl_80472D28.x116 == 1) {
```

## Type Reference

Common types in Melee:
- `s8`, `s16`, `s32` - signed integers
- `u8`, `u16`, `u32` - unsigned integers
- `f32`, `f64` - floats (use these, not `float`/`double`)
- `BOOL` - boolean (actually s32)
- `HSD_GObj*` - game object pointer
- `Fighter*` or `FighterData*` - fighter state pointer
- `Vec3` - 3D vector struct

## PowerPC / MWCC Reference

### Calling Convention
- Integer args: r3, r4, r5, r6, r7, r8, r9, r10
- Float args: f1, f2, f3, f4, f5, f6, f7, f8
- Return: r3 (int/ptr) or f1 (float)

### Register Allocation
- Registers allocated in variable declaration order
- Loop counters often use CTR register
- Callee-saved: r14-r31, f14-f31

### Compiler Flags
```
-O4,p -nodefaults -fp hard -Cpp_exceptions off -enum int -fp_contract on -inline auto
```

## Known Type Issues

Some header types are incorrect. Common workarounds:

| Field | Declared | Actual | Workaround |
|-------|----------|--------|------------|
| `fp->dmg.x1894` | `int` | `HSD_GObj*` | `((HSD_GObj*)fp->dmg.x1894)` |
| `fp->dmg.x1898` | `int` | `float` | `(*(float*)&fp->dmg.x1898)` |

## Quick Struct Lookup

```bash
melee-agent struct offset 0x1898              # What field is at offset?
melee-agent struct show dmg --offset 0x1890   # Show fields near offset
melee-agent struct issues                     # Known type issues
```

## Example Session

```bash
# User: /decomp mnDiagram_80241B4C

# Step 1: Get initial decompilation
python tools/decomp.py mnDiagram_80241B4C --no-copy -f

# Step 2: Find the source file
grep -rn "mnDiagram_80241B4C" src/melee/
# → src/melee/mn/mndiagram.c

# Step 3: Edit the source file with the decompiled code
# (use your editor to modify src/melee/mn/mndiagram.c)

# Step 4: Check the diff
python tools/checkdiff.py mnDiagram_80241B4C
# Shows: MISMATCH with register differences

# Step 5: Iterate - reorder declarations, fix types
# (edit src/melee/mn/mndiagram.c)

python tools/checkdiff.py mnDiagram_80241B4C
# Shows: --- MATCH: mnDiagram_80241B4C matches! ---

# Step 6: Commit
python configure.py && ninja
git add src/melee/mn/mndiagram.c
git commit -m "mn: match mnDiagram_80241B4C"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Function not found in report | Build first: `python configure.py && ninja` |
| Undefined type in code | Check includes, add if needed |
| Register allocation off | Reorder variable declarations |
| Extra conversion instructions | Fix types (`s32`, `f32`, etc.) |
| Different control flow | Try if/else vs switch, restructure conditions |
| Build fails | Use `/decomp-fixup` skill for header issues |

## What NOT to Do

1. **Don't use the remote server workflow** for routine matching - local is faster
2. **Don't spend >15 minutes on one function** - commit progress and move on
3. **Don't use pointer arithmetic** - define proper structs instead
4. **Don't ignore type mismatches** - they cause subtle bugs
5. **Don't forget to verify the build** before committing

## Integration with Other Skills

**Proactively use these skills - don't wait until you're completely stuck!**

### Before Writing Complex Code
Use the patterns tool to check for simpler approaches:
```bash
melee-agent patterns wrapper "field_name"   # Find wrapper functions
melee-agent patterns similar <function>      # Find similar matched code
melee-agent patterns check <file>            # Check for anti-patterns
melee-agent patterns anti-pattern list       # Show known anti-patterns
```

### When Stuck on Matching
- `/mismatch-db` - Search database of known mismatch patterns and fixes (includes anti-patterns!)
- `/discord-knowledge` - Search 6+ years of Discord for compiler tricks and techniques
- `/opseq` - Find similar already-matched functions by opcode patterns
- `/ppc-ref` - Look up PowerPC instruction documentation
- `/ghidra` - Get Ghidra's decompilation for a second opinion, find callers/callees

### Build & Header Issues
- `/decomp-fixup` - Fix build failures after matching (header/caller issues)

### After Matching
- `/understand` - Document and name functions, structs, and fields

### Alternative Workflow
- `/decomp-remote` - Use decomp.me server for context inspection, scratch history

**Pro tip:** The mismatch-db and discord-knowledge skills contain solutions to hundreds of common issues. If you've tried the same fix twice and it didn't work, search for the pattern - someone has likely solved it before.
