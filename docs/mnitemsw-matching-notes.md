# mnitemsw matching results — 2026-09-06

`mnItemSw_8023453C` reached 100% in [PR #3359](https://github.com/doldecomp/melee/pull/3359),
commit `69a0d3ee58409a99d5196fcf6e5df3c23342303f`. The working-branch source commit
is `d5b6b34b34`. All ten TU functions, 7,844 code bytes, and 416 data bytes match.
The TU is `Matching`; the ordinary full build passes the original DOL SHA-1 in
both the working checkout and the clean PR checkout. Forced compiler output was
used for diagnosis only, never as this proof.

This result supersedes earlier source-ceiling or exhausted-rotation conclusions
for this function. Failed probes remain evidence about their particular source
bases, not proof that a source solution does not exist.

## The combination that worked

The retained starting point was 99.77376%, with the correct 128-byte frame and
442 instructions but 20 register-only paired differences. The change flag was
in r27 and the new cursor in r31. The desired long-lived allocation was:

| Value | Register |
| --- | --- |
| Original change flag, `arg1` | r31 |
| Animation table | r30 |
| Cursor JObj | r29 |
| Menu data | r28 |
| New cursor | r27 |
| Second flag, `arg2` | r26 |

Five source changes worked together:

1. Test the **original `arg1` parameter** in the final selection block, keeping
   it live across the function. The helper-return alias `arg1_` is still used
   earlier. The frequency helper returns its `changed` argument unchanged, so
   this preserves behavior.
2. Keep six distinct **embedded assignments in real joint-call arguments**:
   four in the old-selection branch and two in `mnItemSw_UpdateConfirmed`.
   These copies alter the coalesced call-argument neighbors without adding
   instructions. Final aliases are typed `HSD_JObj*`, with descriptive names.
3. Add one embedded **data-pointer copy at the old-selection lookup**:

   ```c
   HSD_JObj* jobj =
       mnItemSw_8023405C((lookup_data = data), old_cursor);
   ```

   Its location matters. Putting this copy at the confirmation lookup gets the
   long-lived registers right but leaves four volatile/opcode differences.
4. Make `cursor` a **`u8` declared after `data`**. This changes its owner from a
   late lowering/CSE temporary to a named local, and puts its simplify removal
   before the data pointer. Reordering the old `u32` declaration alone could
   not move a lowering temporary into the named-local band.
5. **Discard the first frequency-helper return** instead of assigning it back
   to `arg1_`. On this source, that alone restores the frame from 136 to 128
   bytes. This is a measured inline-return/frame interaction, not a universal
   eight-byte rule for identity returns.

The right-column `column_x` temporary and the direct global hovered-selection
lookup were earlier improvements and remain in the final source. The latter
comes from [PR #3358](https://github.com/doldecomp/melee/pull/3358), commit
`b9037f93afeac1509981cc64fbc428e494e2999c`; it supplied a useful missing `addi`
argument instruction even though that PR did not solve the register rotation.

## Why more pressure was worse

Read-only retail tracing and decompilation of the allocator distinguished two
regimes. Normal simplification scans ascending virtual IDs, immediately
decrementing neighbors as nodes are removed. Selection reverses that removal
order. Coalesced nodes are skipped, leaving permanent contributions to degree.
One extra such edge can keep a low-ID parameter through another scan, causing
it to select first and claim r31.

Adding too many edges stops normal simplification. The fallback uses
`spill_cost / degree`; in the captured over-pressured source, the original flag
had cost 5 and degree 33, compared with data at 35/34 and table at 25/37. The
cheap flag lost the ordering contest. Those numbers belong to that snapshot,
not to the final source; newer protected temporaries also have special handling
in the fallback, so a naive universal ratio sort is insufficient.

**The degree printed after simplification is not degree at removal.** Later
removals continue decrementing already-removed neighbors. Account for the
still-live neighbors at each scan before predicting whether a node survives.
Likewise, descending virtual ID describes selection within a removal scan,
not across nodes removed on different scans. This was the escape from the old
"the parameter can never outrank the temporary" reasoning.

The important intermediate had flag IG33/r31, cursor IG111/r30, table IG85/r29,
cursor-JObj IG42/r28, data IG41/r27, and arg2 IG34/r26. Its flag degree was 24.
Changing cursor to `u8` moved it to IG43; moving that declaration after data then
fixed the remaining long-lived rotation. **IDs are source-specific**: track the
value and its defining instruction, not an IG number copied between variants.

## Measured path through lower-scoring candidates

These are chronological source frontiers, not independent one-variable tests
against the original baseline. The evidence matrix records source/result hashes.

| Frontier | Match | Frame | What it established |
| --- | ---: | ---: | --- |
| Retained baseline | 99.77376% | 128 | Correct instruction shape; rotation remains |
| Many joint copies, original flag used at tail | 99.13122% | 136 | Excess pressure invokes fallback; flag r29 |
| Narrow copy window, confirmation data copy | 98.837105% | 136 | First unforced flag r31 |
| `u8` cursor | 98.98416% | 136 | Cursor gets a named-local owner |
| Cursor declared after data | 99.73077% | 136 | Long-lived allocation fixed |
| First helper return discarded | 99.830315% | 128 | Only four confirmation instructions differ |
| Data copy moved to old lookup | 100% | 128 | Exact ordinary function match |

Following only the highest percentage would have rejected the decisive
98.837105% frontier. The predicted flag allocation was stronger progress
evidence than the percentage until the other registers and frame were repaired.

## Failed approaches and limits worth retaining

- Broad declaration, flag-width, pointer ownership, aggregate, row-helper,
  argument-staging, and reconstruction campaigns did not solve the old baseline.
  They did not establish a source ceiling. The eventual `u8` and declaration
  fix mattered on the new pressure-window base.
- Wider lookup parameters (`u32`, `int`, `u16`) with a local byte narrowing
  changed the already-matched lookup body and did not solve the caller.
- Removing `column_x` did not eliminate the eight-byte growth and moved the
  confirmed-JObj home. Removing the first identity-return assignment did.
- The confirmation data copy left `r3`/`r4` addressing differences and `mr`
  instead of `addi`. Its earlier location was essential.
- A combined cleanup splitting embedded assignments into preceding statements
  regressed the matched source to **98.61991%**, with the frame still 128 bytes.
  This does not isolate every assignment; it establishes that the combined
  cleanup is unsafe. Renaming aliases and replacing `void*` with typed
  `HSD_JObj*` preserved 100%.
- Forced ordering/coloring and permuter proxy scores were search evidence only.
  One earlier proxy candidate used an uninitialized temporary and was rejected.
- Windows inspection worked with IPv4 SSH (`AddressFamily=inet`). Transport
  and context problems were tooling failures, not host unavailability.
  Compressed context upload plus generated includes repaired inspection.
  The issue #1240 preview remained diagnostic; the decisive allocator evidence
  came from read-only retail captures and the final ordinary build.

## A 100% object report did not establish a linkable TU

The first `Matching` build failed the DOL checksum even though the report showed
100% for every function and all data. Two pre-existing layout issues remained:

1. Both a static item-order array and a duplicate global `mnItemSw_803ED438`
   were emitted. The extra 32 bytes shifted the next TU's `mnStageSw_803ED488`
   to `0x803ED4A8`. Use the single global in the original table position and
   remove the duplicate definition at EOF.
2. The two small-BSS definitions were emitted in reverse of their original
   addresses. Declaring `mnItemSw_804D6BEC` before `mnItemSw_804D6BE8` restored
   pointer-at-offset-0 and byte-at-offset-4 layout for this TU.

`dtk dol diff config/GALE01/config.yml build/GALE01/main.elf` found the first
layout error. `dtk elf info build/GALE01/src/melee/mn/mnitemsw.o` exposed the
small-BSS offsets. After both corrections the linked DOL SHA-1 passed. Keep
body matching, symbol/address layout, and full-link validation as separate gates.

## Evidence, discovery, and reproduction

The committed evidence set is in
[`matching-evidence/mnitemsw`](matching-evidence/mnitemsw/README.md): measured
frontiers, final comparisons, and linked build logs. Source is fixed by the PR
commit above. A larger local archive with source candidates, sweep results,
scripts, pcdumps, retail snapshots, and earlier checkpoints lives under
`~/.config/decomp-me/matching-evidence/mnitemsw-2026-09-06/`. Its manifest records
SHA-256 for each file; no `/tmp` path is required to retrieve it.

Retail GC/1.2.5n compiler SHA-256:
`ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
The stock 1.2.5 image has a different hash; relevant allocator regions were
verified byte-identical before using its reader layout. Custom cost snapshots
are labeled diagnostics, not complete #1240 backend traces.

The shared mismatch DB contains `narrow-pressure-window-original-flag`,
`discarded-identity-inline-return-restores-frame`, and
`duplicate-data-and-sbss-order-block-tu-link`. The attempt ledger records 100%
and the retained source. Before repeating old sweeps:

```sh
melee-agent mismatch get narrow-pressure-window-original-flag
melee-agent mismatch get discarded-identity-inline-return-restores-frame
melee-agent mismatch get duplicate-data-and-sbss-order-block-tu-link
python tools/checkdiff.py mnItemSw_8023453C --format json --no-fingerprint
python configure.py && ninja
```

Tool feedback remains tracked separately: #1483 (doctor overwrites a local
inspector repair), #1484 (legacy simplify simulation model), #1485 (source-mode
helper loss), #1488 (candidate triage false positives), #1490 (inline splice
leaves a formal unsubstituted), and #1492 (frame inspection depends on failing
expected-ASM extraction). Intermediate diagnostic claims needed independent
validation; the final ordinary build/checksum passed.
