# Large Function Checkpoint

Use this before editing a large state machine, menu flow, asset loader, or any
function where repeated local rewrites are likely to hide the real source shape.

## Required Context

- **callers/callees**: list direct callers and callees with `melee-agent ghidra xrefs`, `rg`, or extracted ASM.
- **data layout**: inspect structs, statics, nearby symbols, BSS adjacency, and `.sdata` with `tools/symbol-layout-analyzer.py`.
- **asset loads**: identify archive loads, joint/material/tree access, text/glyph tables, and resource IDs before naming locals.
- **varargs lists**: inventory `OSReport`, `OSPanic`, `__assert`, and `HSD_ASSERT` calls because they affect stack layout.
- **intended behavior**: summarize what the function does in plain source terms before matching assembly details.

## Minimum Note

Before the first serious rewrite, create an attempt note:

```bash
melee-agent attempts record <func> --match <pct> --outcome neutral \
  --note "checkpoint: callers/callees, data layout, asset loads, varargs lists, intended behavior reviewed"
```

## Gather Evidence Before Grinding

If the checkpoint reveals unresolved data or signature uncertainty, do not grind
register allocation against incomplete information. Record what is blocking
progress and build evidence from a smaller caller/callee or neighboring data
symbol, then return to this function once the data layout or signature is
clearer. The function stays workable — source exists for every function; this is
about investigation order, not giving up.
