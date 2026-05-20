# MWCC Debug Tooling Feedback — 2026-05-20

8-hour matching campaign on `src/melee/mn/mndiagram3.c`. Live notes on
tooling friction, gaps, and ideas. Will be amended throughout.

## Starting state

| Function | Match% | Notes |
|---|---|---|
| fn_802461BC | 96.31% | refactored, structural ceiling |
| mnDiagram3_80245BA4 | 92.19% | `ceiling` says PROBABLE CEILING, 6-rank cascade off |
| mnDiagram3_8024714C | 97.96% | refactored, 2-rank cascade off |
| mnDiagram3_80246D40 | 100% match=True | done |
| fn_80246E04 | 100% match=True | done |
| mnDiagram3_80246F2C | 100% match=True | done |
| fn_80246E64 | 100% fuzzy | relocation-annotation offset only |
| mnDiagram3_80247008 | 100% fuzzy | relocation-annotation offset only |

## Tooling observations

### `verify-with-name-magic` suggests wrong symbol for int-to-float magic

**Severity:** medium — produces incorrect suggestion that requires manual
investigation to discover.

**Symptom:** For `mndiagram3.c`, the tool suggested:

```
@244  0x4330000080000000  signed int-to-float bias → s32=mnDiagram3_804DBFF0
@570  0x4330000000000000  unsigned int-to-float bias → u32=mnDiagram3_804DBFF8
```

But the actual `.sdata2` contents of the production .o have:

| address | bytes | meaning |
|---|---|---|
| `804DBFF0` (f64) | `43 30 00 00 00 00 00 00` | **UNSIGNED** magic |
| `804DBFF8` (f32) | `40 d0 00 00` | 6.5 (a regular float) |
| `804DC000` (f64) | `43 30 00 00 80 00 00 00` | **SIGNED** magic |

So the correct mapping is:
- s32 → `mnDiagram3_804DC000`
- u32 → `mnDiagram3_804DBFF0`

The tool appears to match magic value → named symbol by address-order
within the section, but the unsigned magic happens to come first in
this TU's layout. Either parse the symbol's actual bytes from the
production .o's `.sdata2` to get the right mapping, or document the
ambiguity in the suggestion ("could be any of these symbols with the
matching bytes — verify with objdump -s -j .sdata2").

Workaround: dump `.sdata2` with `powerpc-eabi-objdump -s -j .sdata2
<target.o>` and read which 8-byte block contains which magic.

### `verify-perm` permuter-macro leak (`inline_fn` placeholder)

**Severity:** high — silently breaks the build.

When `verify-perm --keep` applied permuter winner
`output-1615-1` to fn_802461BC, the resulting source had three lines
in `mnDiagram3_8024714C` (a sibling function in the same TU, NOT the
target) like:

```c
if (!(inline_fn(popup_jobj) & 0x02000000))
```

where the original was:

```c
if (!(popup_jobj->flags & 0x02000000))
```

`inline_fn` is a placeholder name used inside decomp-permuter's
randomizer (per `decomp-permuter/src/randomizer.py:2344`,
`get_noncolliding_name(ast, "inline_fn")`). It should NEVER reach the
real source — it's an internal AST placeholder that the permuter
resolves before scoring. But verify-perm appears to take the
candidate's raw source verbatim and copy regions into the real file
that haven't had this name resolved.

The leak is silent — `verify-perm` reports `Delta: +0.54%` and exits
0. The next `ninja` build catches it as "function has no prototype",
but the corrupted file has already been committed by then.

Suggestion: `verify-perm` should grep for `inline_fn` (and similar
permuter-internal names) in the candidate and abort with a clear
message before writing.

Workaround: run `git diff --check` or `grep inline_fn <file>` after
each verify-perm before committing.

The 3-way merge check (great feature!) caught a *different* class of
issue (conflicts with manual edits), but missed this one because
`inline_fn` appears only in regions outside the function being
permuted — so it doesn't show up as a conflict.

### `verify-perm` silently reverts manual fixes

**Severity:** medium.

`verify-perm --keep` writes the permuter candidate's `source.c` over
the real source. But the permuter candidate has the **pre-mutation**
text, plus its mutations. Any manual fixes I made between when the
permuter staging was created and when verify-perm runs get silently
dropped.

Concrete example: I applied `u8 limit` → `int limit` manually (+0.26%
win), committed. Later, an unrelated permuter run found a mutation
elsewhere in the function. `verify-perm --keep` applied the winner
but used the **stale** `base.c` text underneath, reverting my limit
type back to `u8`. The function still matched at the new improved
level (because the winner's gain compensated for the lost manual fix),
so I didn't notice for several commits. Only on re-checking the diff
later did I realize the int limit change was gone and re-applying it
gained another +0.26%.

Suggestions:
- `verify-perm` could 3-way merge the candidate's source against the
  current real source (taking the candidate's *changes* as a diff
  rather than its full text).
- Or: warn loudly when verify-perm would revert lines that differ from
  the base.c — "this candidate overwrites N lines you changed since
  import; re-import baseline?"
- Or: a `--diff-only` mode that applies just the textual delta from
  candidate vs base.c, leaving everything else alone.

### Long-running permuter (`debug permute`) friction

**Severity:** low — usability issue.

When piping permuter through `tail -N`, all intermediate output is
buffered until the pipe closes. Since `permuter.py` never exits naturally,
no live progress is visible. Workaround: omit `tail` and read the
captured file directly via `Read` / `grep`.

Could the `debug permute` wrapper auto-disable buffering or stream
through PTY by default? Otherwise document this clearly in the help.

### Type-change wins on mnDiagram3_80245BA4

Found `u8 limit` → `unsigned int limit` → `int limit` gives +0.13% then
another +0.13% (signed cmpw matches expected). Doesn't show up in any
of the diagnostic tools (`ceiling`, `stuck`, `suggest-casts`,
`enumerate-decl-orders`). The widen-u8-to-u32 pattern would catch the
first hop but not the second (signed vs unsigned). Could the cast
linter (`suggest-casts`) detect that `cmplwi` (unsigned) is being
emitted where the expected has `cmpw` (signed), and recommend changing
the operand's signedness?

### HSD_ASSERT override pattern: tooling could detect and suggest

The `#undef`+`#define HSD_ASSERT` override before `<baselib/jobj.h>`
include is a well-known matching trick (per `MEMORY.md`
"HSD_ASSERT macro override"), but no diagnostic tool surfaces it.
For functions where the .o has anonymous `@N` strings of values
"jobj.h\0" or "jobj\0", the `stuck` / `ceiling` command could detect
this and print:

> Anonymous assert strings in .sdata. Try adding before jobj.h
> include:
>   #include <baselib/debug.h>
>   #undef HSD_ASSERT
>   #define HSD_ASSERT(line, cond) \
>       ((cond) ? ((void) 0) : __assert(<file_sym>, line, <fn_sym>))

`<file_sym>` and `<fn_sym>` are guessable from the named char[]
extern declarations in the function's `*.static.h`.

### Named SDA2 magic constants — not reachable from C source

Setting `f64 mnDiagram3_804DC000 = 4503601774854144.0;` as a global
definition does NOT cause MWCC to reuse this symbol for the int-to-float
intrinsic. The intrinsic always emits an anonymous `@N` symbol with
the same bytes, even when a named symbol with identical bytes exists
in the same TU.

This is the heart of the "anonymous magic constant" matching blocker.
Production .o has all 8 .sdata2 floats as named globals; our .o has
the 6 non-magic floats as **externs from another TU** and the 2 magic
ones as **anonymous locals**.

The verify-with-name-magic post-process .o rename is the only path I
found; there's no source-level workaround.

Workflow idea: a `--objcopy-rename-magic` mode in the build system
that runs name-magic on each .o post-compile would essentially make
this class of mismatch invisible. Worth considering as a build step,
even if it doesn't help "matching .text production" specifically.


