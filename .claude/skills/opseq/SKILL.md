---
name: opseq
description: Find functions by opcode sequence patterns. Use when stuck on a function and want to find similar already-decompiled code for reference.
---

# Opcode Sequence Matching

Find functions that share a specific sequence of opcodes. Useful for:
- Finding already-decompiled reference functions with similar structure
- Finding undecompiled candidates that likely use the same pattern

## Usage

### Find decompiled reference functions

```bash
cd melee && ../tools/table-typer opseq <comma,separated,opcodes>
```

### Find undecompiled candidates

```bash
cd melee && ../tools/table-typer opseq -candidates <comma,separated,opcodes>
```

## Examples

### Basic opcode pattern

```bash
# Find functions with beq,mr,bl sequence
cd melee && ../tools/table-typer opseq beq,mr,bl
```

Output shows asm file location and corresponding source file:
```
build/GALE01/asm/melee/ft/chara/ftSeak/ftSk_SpecialS.s:1048 src/melee/ft/chara/ftSeak/ftSk_SpecialS.c:586
```

### Finding floating-point patterns

```bash
# Functions that load float, compare, and branch
cd melee && ../tools/table-typer opseq lfs,fcmpo,bge
```

### Finding loop patterns

```bash
# Functions with counter increment and compare
cd melee && ../tools/table-typer opseq addi,cmpwi,blt
```

## Common Use Cases

### Stuck on a function?

1. Extract a distinctive opcode sequence from the target asm:
   ```bash
   melee-agent extract get <func_name>  # Look at the asm output
   ```

2. Find similar already-matched functions:
   ```bash
   cd melee && ../tools/table-typer opseq <pattern>
   ```

3. Read the decompiled source for inspiration on structure

### Finding related unmatched functions

When you've successfully matched one function, find similar unmatched ones:
```bash
cd melee && ../tools/table-typer opseq -candidates <pattern_from_matched_func>
```

## Tips

- Shorter patterns (3-4 opcodes) give more results
- Longer patterns (5-6 opcodes) are more specific
- The tool searches `build/GALE01/asm/melee/` for asm files
- Results include line numbers for quick navigation
