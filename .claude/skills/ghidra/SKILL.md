---
name: ghidra
description: Use Ghidra decompiler for cross-references, type inference, and alternative decompilation views. Complements m2c workflow. Use when you need to find callers/callees, see Ghidra's type inference, or get a second opinion on complex functions.
---

# Ghidra Integration

Ghidra provides an alternative decompiler view that complements the primary m2c workflow. It's particularly useful for:

- **Cross-references**: Find who calls a function, or what a function calls
- **Type inference**: See Ghidra's guesses at struct types and parameters
- **Second opinion**: When m2c output is confusing, Ghidra may clarify
- **String discovery**: Find debug strings and error messages in functions

## Prerequisites

Ghidra must be set up before use:

```bash
# Check status
melee-agent ghidra status
```

If not set up, follow these steps:

1. **Install Ghidra 12.0+** from https://ghidra-sre.org
2. **Set environment variable**:
   ```bash
   export GHIDRA_INSTALL_DIR=/path/to/ghidra_12.0_PUBLIC
   ```
3. **Install pyghidra**:
   ```bash
   pip install pyghidra
   ```
4. **Install GameCube loader**:
   - Download from https://github.com/Cuyler36/Ghidra-GameCube-Loader/releases
   - In Ghidra: File → Install Extensions → + → select ZIP
   - Restart Ghidra
5. **Create project** (must be done via GUI due to loader bug):
   - Open Ghidra GUI
   - File → New Project → Non-Shared Project
   - Location: `.ghidra_project/` in repo root
   - Name: `melee`
   - File → Import File → select `orig/GALE01/sys/main.dol`
   - Wait for analysis (5-10 minutes)
   - Close Ghidra
6. **Link project**:
   ```bash
   melee-agent ghidra setup
   ```

## Commands

### Decompile a Function

Get Ghidra's decompilation of a function:

```bash
melee-agent ghidra decompile 0x80243A3C
melee-agent ghidra decompile 80243A3C --raw  # No formatting
```

**When to use:**
- m2c output is confusing or incomplete
- You want to see different variable names/types
- Complex control flow needs a second opinion

### Find Cross-References

Find who calls a function (callers):

```bash
melee-agent ghidra xrefs 0x80243A3C           # Who calls this?
melee-agent ghidra xrefs 0x80243A3C --dir to  # Same (default)
```

Find what a function calls (callees):

```bash
melee-agent ghidra xrefs 0x80243A3C --dir from  # What does this call?
```

**When to use:**
- Understanding call graphs
- Finding all callers before changing a signature
- Discovering related functions

### Find Strings

Find string references in a function:

```bash
melee-agent ghidra strings 0x80243A3C
```

Search for strings by pattern:

```bash
melee-agent ghidra strings --pattern "error"
melee-agent ghidra strings --pattern "assert"
```

**When to use:**
- Finding debug messages that reveal function purpose
- Discovering error handling paths
- Understanding what a function does from its strings

### Get Function Info

Get metadata about a function:

```bash
melee-agent ghidra func 0x80243A3C
```

Shows: name, entry point, size, calling convention, return type, parameters.

**When to use:**
- Quick overview of function signature
- Checking Ghidra's inferred parameter types
- Understanding function size/complexity

## When to Use Ghidra vs m2c

| Task | Use |
|------|-----|
| Initial decompilation | m2c (`tools/decomp.py`) |
| Matching/iterating | m2c + checkdiff |
| Finding callers | Ghidra xrefs |
| Type confusion | Try both, compare |
| Debug strings | Ghidra strings |
| Call graph | Ghidra xrefs |
| Complex control flow | Try both |

## Example Workflow

When stuck on a function:

```bash
# 1. Get Ghidra's view
melee-agent ghidra decompile 0x80243A3C

# 2. Find what it calls (might reveal purpose)
melee-agent ghidra xrefs 0x80243A3C --dir from

# 3. Find who calls it (context from callers)
melee-agent ghidra xrefs 0x80243A3C

# 4. Check for debug strings
melee-agent ghidra strings 0x80243A3C
```

## Limitations

- **Slower than m2c**: Ghidra startup takes time
- **Different output**: Ghidra's C style differs from project conventions
- **Type inference varies**: Ghidra may infer different (sometimes wrong) types
- **Not for matching**: Use m2c + checkdiff for actual matching work

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "GHIDRA_INSTALL_DIR not set" | Export the environment variable |
| "pyghidra not installed" | `pip install pyghidra` |
| "No Ghidra project" | Run `melee-agent ghidra setup` after GUI import |
| "No function at address" | Run Ghidra analysis or check address |
| Slow startup | Normal - Ghidra JVM takes time to initialize |
