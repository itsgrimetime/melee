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
melee-agent opseq <comma,separated,opcodes>
```

### Find undecompiled candidates

```bash
melee-agent opseq -candidates <comma,separated,opcodes>
```

## Examples

### Basic opcode pattern

```bash
# Find functions with beq,mr,bl sequence
melee-agent opseq beq,mr,bl
```

Output shows asm file location and corresponding source file:
```
build/GALE01/asm/melee/ft/chara/ftSeak/ftSk_SpecialS.s:1048 src/melee/ft/chara/ftSeak/ftSk_SpecialS.c:586
```

### Finding floating-point patterns

```bash
# Functions that load float, compare, and branch
melee-agent opseq lfs,fcmpo,bge
```

### Finding loop patterns

```bash
# Functions with counter increment and compare
melee-agent opseq addi,cmpwi,blt
```

## Common Use Cases

### Stuck on a function?

1. Extract a distinctive opcode sequence from the target asm:
   ```bash
   melee-agent extract get <func_name>  # Look at the asm output
   ```

2. Find similar already-matched functions:
   ```bash
   melee-agent opseq <pattern>
   ```

3. Read the decompiled source for inspiration on structure

### Finding related unmatched functions

When you've successfully matched one function, find similar unmatched ones:
```bash
melee-agent opseq -candidates <pattern_from_matched_func>
```

## Gap-tolerant patterns

Tokens are comma-separated. Between landmarks you can insert a **bounded gap** to
tolerate scheduler/register noise. Quote the pattern — `*`, `?`, and `{}` are
shell metacharacters:

```bash
melee-agent opseq 'lfs,*{0..3},fsubs,bne'   # up to 3 instructions between lfs and fsubs
melee-agent opseq 'cmplwi,*,bne'            # bare * = up to --gap-cap (default 6)
melee-agent opseq 'mtctr,?,bctr'            # ? = exactly one instruction
```

Rules: bounds use `..` (not a comma); the upper bound is capped at 32; a pattern
must begin and end with a real opcode (no leading/trailing gap). Results are
ranked tightest-match-first.

## Derive a pattern from a function (`--like`)

Stop hand-authoring. Point `--like` at a function (optionally a line range) and
opseq derives an editable, gap-tolerant pattern — keeping control-flow anchors
(loops/returns/switches) plus the rarest distinctive ops, gapping out filler:

```bash
melee-agent opseq --like fn_80247510
melee-agent opseq --like fn_80247510:512-540   # just the stuck region (see note)
melee-agent opseq --like fn_80247510 --with-operands     # also bind register-reuse
```

The optional `:start-end` range is **`.s` file line numbers** — the same
coordinate opseq prints in its results (`path.s:LINE`), not instruction
addresses.

Flags: `--gap-cap N` (bare `*` width, default 6), `--slack N` (derive tolerance,
default 2), `--max-landmarks N` (default 12), `--with-operands`. The derived
pattern is printed so you can tweak it and re-run it manually.

Note: `--with-operands` is significantly more expensive to match (it adds
register-reuse constraints); on large functions prefer a `:start-end` range, or
the search budget will skip the largest bodies with a warning.

## Tips

- Shorter patterns (3-4 opcodes) give more results
- Longer patterns (5-6 opcodes) are more specific
- Always single-quote patterns that contain `*`, `?`, or `{}` so the shell does
  not expand them: `melee-agent opseq 'lfs,*{0..3},fsubs'`.
- `melee-agent opseq` runs `tools/table-typer` from the current checkout and
  falls back to `go run` when the helper binary is not built.
- The tool searches `build/GALE01/asm/melee/` for asm files
- Results include line numbers for quick navigation
