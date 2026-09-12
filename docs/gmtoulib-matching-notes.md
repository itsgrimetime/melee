# Tournament bracket callback checkpoint — 2026-09-06

`fn_8018B090` remains **99.94527%**, 1553 instructions / 6212 bytes, with the
exact **208-byte frame**. The other 48 functions in `gmtoulib.c` match. The
current source includes the improvements merged in upstream PR3358; former
PR3372 was closed. Do not mark this TU Matching until the residual is solved
and the original linked DOL verifies.

The callback advances tournament bracket animation states. Its two remaining
regions have matching instruction sequences:

- Case 23, offsets `+0x764`–`+0x820`: the loop counter needs r26 and the JObj
  needs r22; the current allocation reverses them (10 instruction rows).
- Case 33, offsets `+0x1218`–`+0x1228`: the slot stride needs r6 and the
  coordinate address/load needs r3; current code uses r3 and r5 (5 rows).

The source is byte-identical to the earlier c016 baseline archived under
`~/.config/decomp-me/matching-evidence/gmtoulib-2026-09-06/continuation-register-source/`.
Its completed lifetime report can therefore be reused. Counter IG51 and JObj
IG100 (coalesced with IG168) select at positions 593 and 554. The stride IG489
selects at 186 before coordinate IG487/486 at 188/189. Source attribution
incorrectly calls the counter `t5`; use the actual instructions to identify
roles. The prior forced map `0:51:26,0:100:22,0:489:6,0:486:3,0:487:3` removes
the 15 instruction differences, but is diagnostic evidence, not a source match.

## Additional ordinary source probes

All candidates were reverted. Detailed sources and checkdiff reports are in
the evidence archive accompanying this checkpoint.

| Source change | Result | Frame |
| --- | ---: | ---: |
| Store coordinate through existing k or i before the slot assignment | 99.93239%, 18 register rows | 208 |
| Store coordinate through local ent before the slot assignment | 99.85061%, 18 register rows | 216 |
| Group both coordinate stores in an entry-pointer or array/index helper | 99.93239%, 18 register rows | 208 |
| Group both stores in a slot-pointer helper | 98.73728%, 281 register rows | 200 |
| Slide loop as do/while with preincrement | 99.94527%, neutral | 208 |
| Slide loop as while with tail increment | 99.94527%, neutral | 208 |
| Slide for-loop with increment in its body | 99.94527%, neutral | 208 |
| Slide loop as do/while with separate tail increment | 99.94527%, neutral | 208 |
| Reuse existing X setter, Y setter, or both in case 33 | 99.76819%, 70 register rows | 208 |

Earlier c016 experiments already cover setter wrappers, scoped and reused
counters, whole-state helpers, coordinate pointers/types, single-store/getter
helpers, and embedded pointer assignments. Do not restart those families
without new evidence. The retained source has not changed in this pass.

## Permuter baseline fidelity

Use the branch-local CLI via `PYTHONPATH="$PWD/tools/melee-agent"` when
bootstrapping Linkable TUs. This branch contains the extraction fix a95d06faa4;
the installed shared-master CLI does not yet include it (issue1465).

The standalone imported baseline scores 780: 15 real register differences,
34 assertion-line immediates, and 107 relocation-name differences. Its copied
header inlines contain assertions for `<stdin>` at lines 9932, 10210, and
10228. These extra `li` differences are not evidence of another allocator
problem.

The existing `debug permute setup-simplify-order-scorer --source-file` command
provides full-TU candidate transplantation and production Ninja flags. Keep
that compile wrapper, use the ordinary retail compiler through
`MWCC_DEBUG_COMPILER`, and restore ordinary byte scoring when allocator IDs
are not stable across mutations. With original headers, the baseline scores
610: the same 15 register rows plus 107 relocation names, with no assertion
immediate, stack, branch, insertion, or deletion differences.

The campaign's retained `full-unit.c` snapshot isolates it from ordinary
source experiments. Its two `PERM_RANDOMIZE` regions cover only the affected
slide loop and coordinate-store block. It uses one worker in this worktree;
the shared decomp-permuter checkout supplies runtime code only.

Issue1513 records that `dtk-objdump` cannot find a name-magic reference for
temporary candidate objects. Relocation noise must remain separate from
instruction differences, and any saved candidate still needs ordinary
real-TU verification. Mismatch DB entry:
`standalone-inline-assert-context-drift`.

The bounded search completed **534 iterations**, including 79 compile errors,
with best score **610**, equal to the baseline. No improved output was saved.
The planned interrupt exited cleanly; no campaign processes remain.

## Diagnostic limitations

A repeated large-function lifetime-pressure request consumed 125 seconds
without output and was interrupted; issue1508 has this additional repro.
The same-source older report remains usable. The retail frontend trace
timed out after 120 seconds before producing optimizer passes (issue1512).
Neither failure provides a verdict about matchability.

Other known limitations remain relevant: solve-coloring issue1504 tests an
unrelated order hint and reports an unsupported unreachable verdict; the debug
simplify logger mistakes a coalesce-root flag for a spill (issue1503).
Numeric IG IDs must be re-established after source changes.

## Retail allocator result and new source lead

The separate `debug retro backend --verify-debug` capture **completed** on
the restored full TU. Comparison reports 3466 equal fields, 77 retail-only
fields, and 519 differences, all missing debug `simplify_order` entries.
There are no observed color disagreements in the compared fields. The
allocator evidence is usable; the separate PCode operand-history capture
remains partial and is not a full pipeline proof.

The retail decisions expose an additional dependency omitted by the simple
mutual-interference explanation:

1. JObj IG100 selects r26 at iteration 554. The reusable pool includes
   r31 through r23; r22 has not yet been introduced.
2. Case-33 X-setter JObj IG83, coalesced with IG167, first dispenses r22 at
   iteration 568. Its existing candidates are all blocked.
3. Loop counter IG51 reuses r22 at iteration 593, after IG100 holds r26.

Both IG100 and IG51 are colored and unspilled. This supports a source
investigation of allocation order across switch regions, not just shortening
one of the two local lifetimes. The three case-33 helper-reuse probes above
tested this lead and regressed; they do not establish a C fix. The earlier
coordinate stride result is also confirmed: IG489 takes r3 before the
coordinate address/load nodes select r5.

Mismatch DB entry `late-nonvolatile-pool-expansion` records this as an
**unsolved observation**. The source remains 99.94527% and the TU Linkable.

## Persistence and verification

The [evidence manifest](matching-evidence/gmtoulib/2026-09-06-retail-order/manifest.json)
indexes candidate sources, ordinary diffs, retail decisions, the baseline
dump, campaign configuration/log, and tool-failure records. The accompanying
archive is committed in the local fork. A matching checkpoint is also stored
in project memory and the shared attempts ledger.

Final ordinary checkdiff reproduces 99.94527%, 15 register rows, and the
208-byte frame. Configure/build passes and the linked DOL equals the original;
because this TU remains Linkable, that DOL result does not validate the
unmatched callback body. No source candidate was retained and no bracket PR
was opened. Open PRs and thread 01a0749c-030f-73b1-abae-0aeb453a792b were checked
before and during the pass; their active source files were not edited.

After this checkpoint, upstream **f6c322a352 (PR3380)** was merged locally as
29d902e92c. The lbsnap match is now included and linked. The fresh full build
passes its original DOL SHA-1 check and byte comparison: **19819 / 19828
functions match, 1124 / 1130 TUs link**. The post-upstream build log and hash
are included beside the archive. Bracket source is unchanged. Its claim was
released after stopping all jobs; the next independently claimed target is
`fn_803B6820` in `hsd_3B5C.c`. PR3377 and the other thread operate on the
separate `hsd_3B34.c` encoder file.
