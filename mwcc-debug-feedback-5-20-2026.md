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

### Permuter cruft cleanup — observations from 80245BA4

After permuter found wins, the source accumulated patterns like:
- `u8 offset = (((((((((data->scroll_offset & 0xFFFFFFFFu) & 0xFFFFFFFFu) & ...) & 0xFFFFFFFFu);` (10× nested no-op masks)
- `mnDiagram2_GetAggregatedFighterRank(sp28, stat_type, (((u8) i) & 0xFFFFFFFF) & 0xFFFFFFFF);` (double nested no-op masks)
- `int val = (long long) (scroll + offset);` (pointless 64-bit cast then truncate)
- `unsigned long long stat_val = mnDiagram2_GetStatValue(...);` (ULL for what's clearly an int)
- `goto next; divider = mnDiagram3_804DC008;` (dead assignment AFTER unconditional goto — still affects scheduling!)
- `(1 << 14) << 11` (instead of `(1 << 25)`)
- `unsigned int new_var = i;` then `func(stat_type, new_var)` (alias-split into intermediate variable)
- `stat_type ^ 0` (XOR with 0 — identity)
- `entity & 0xFFFFFFFFFFFFFFFFu` (mask with all-1s 64-bit literal — no-op)

A reviewer reading this code thinks "this is generated garbage." Many
of these ARE load-bearing for codegen:
- 10× → 1× nested masks: harmless (10×, 1×, none all give same matching)
- BUT removing all masks: -0.26% — at least ONE mask is needed
- `(long long)` cast: load-bearing (+0.05% over int / +0.10% over no cast)
- `goto next; divider = ...`: load-bearing (-0.26% if moved before goto)
- Alias `new_var = i; f(new_var)`: load-bearing (-0.15% if removed)
- `stat_type ^ 0`: NOT load-bearing (+0.05% to remove)
- `entity & 0xFFFFFFFFFFFFFFFFu`: NOT load-bearing (same +0.05%)
- ULL `stat_val`: load-bearing (-0.10% with u32)

**Tooling idea:** a `clean-cruft` command that:
1. Identifies common patterns produced by permuter (alias-split into
   `new_varN`, nested no-op masks, dead-code-after-goto, XOR with 0,
   AND with all-1s, pointless 64-bit truncation)
2. For each one, tries removing it
3. Reports which are load-bearing (need to stay) vs purely cosmetic
   cruft (safe to remove)
4. Optionally applies the safe removals

Would save the ~20 manual `verify-perm-and-revert` cycles I just ran
to clean up a single function. The pattern catalog already names
these (`alias-split`, `widen-u8-to-u32`, etc.); a `clean-cruft`
counterpart that REVERSES would be the natural pair.

### SDA21 reloc offset normalize — game-changer for diff readability

**Severity:** low (just diff readability) but very impactful workflow.

After cherry-picking `72e8eb29a checkdiff: normalize +2 SDA21 reloc
offsets`, my 8024714C diff went from 53 hunks to 25. That's HUGE
because it lets me see real differences vs display artifacts.

Before the normalize fix, every R_PPC_EMB_SDA21 reloc with a +2 offset
from the instruction start showed up as a "hunk" even though the .o
bytes were identical. After the fix, those normalize to the
instruction's base offset on both sides.

Suggestion: this should be on by default in main without needing a
flag, since the +2 form is purely a display detail of how the assembler
emits relocs (depends on whether section base or instruction byte
offset is used). Already done — just calling it out as essential.

### `verify-with-name-magic --apply-auto` confirmed working

Used this on 8024714C and it auto-renamed both anonymous magic
constants in our .o:
- `@240 -> mnDiagram3_804DC000 (globalized)` (signed int-to-float)
- `@566 -> mnDiagram3_804DBFF0 (globalized)` (unsigned int-to-float)

Useful diagnostic to confirm the only remaining diff IS the register
cascade — but the source still can't reproduce these names naturally,
so the .o byte-distance still shows mismatch after rename. Need either
an objcopy-rename build step or an MWCC fix.

### Permuter campaign productivity observations

8-hour campaign drove the three stuck functions through these gains:

| Function | Start | End | Delta | Wins | Reverts |
|---|---|---|---|---|---|
| mnDiagram3_80245BA4 | 92.19% | 97.47% | +5.28% | 17+ permuter wins | many cruft cleanups |
| fn_802461BC | 96.31% | 96.74% | +0.43% | 1 manual + 2 permuter | many |
| mnDiagram3_8024714C | 97.96% | 98.61% | +0.65% | 4 permuter wins | many |

After ~10 hours, all three functions appear to be at their permuter
ceilings — search spaces well-explored, no real-match wins above the
+0.05% threshold from any further runs. The remaining gap to 100% for
each is dominated by:
- Anonymous magic constants (2 of them in each function) that require
  post-process .o renaming, not natural source.
- Register cascade where MWCC's ig_idx ordering puts the function
  parameter at the bottom of the chain instead of the top, leaving
  the wrong physical register selected.

The Tier 5/6 toolset (force-phys, force-coalesce) can confirm what
register assignments are *reachable*, but the C-source pattern to
produce them naturally is sometimes unknowable without compiler
modifications.

5/8 functions in this TU matched at 100%; the remaining 3 are stuck
at their structural ceilings.

Patterns that worked well:
- **Re-import baseline after each commit**: keeps permuter searching
  from the new lower-score baseline. Otherwise permuter wastes time
  on mutations of stale base.c. Restart cycle takes ~5s.
- **--keep with verify-perm**: just-apply-if-good. Avoids the cycle
  of test, decide, manually apply, regenerate.
- **`inline_fn` placeholder detection in verify-perm**: caught 2+
  real corruption attempts. Without this, those would have made it
  to commit and broken the build silently.

Patterns that DIDN'T work:
- Manually trying to replicate `inline_fn` with `static inline f32
  passthrough(f32 x) { return x; }`. Gave 0.1% but is ugly fake-matchey
  code. Reverted on user feedback.
- Moving `font_size = (font_size_b = ...)` inside if-branches. Dropped
  match 0.5% (broke chained init load-bearing dependency).
- `row_spacing = mnDiagram3_804DBFF8` reset trick that worked for
  8024714C did NOT work for fn_802461BC (different live range
  pattern).



