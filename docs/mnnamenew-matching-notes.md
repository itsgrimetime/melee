# GlyphVariantSetup investigation — 2026-09-06

## Verified result

`mnNameNew_GlyphVariantSetup` improved from 99.84694% to 100%. All 25 functions in `mnnamenew.c` and all 36 functions in `mnname.c` match. Both files link from C. The final `python configure.py && ninja` passes the original SHA-1 check, and `cmp orig/GALE01/sys/main.dol build/GALE01/main.dol` exits 0.

Source: [PR #3368](https://github.com/doldecomp/melee/pull/3368), upstream branch head `8a5c0bbbe9`; local matcher commits `59547b2649` and `f98fa0672e`. These are historical verification points, not a substitute for checking the current branch or PR status.

The retained source uses `GlyphVariantCount(u16 count, s32* out)` to mask the count to eight bits and write it through an output parameter. The helper is inlined; no runtime call or extra instruction remains. No forced-register instrumentation is part of the source or final build.

## Register mechanism

The baseline and masked spelling both produce 392 target instructions and the same 152-byte frame. The differences arise from the identity of the temporary that survives optimization, which changes the register allocator's selection order.

- Baseline `(s32) (u8) arg1`: two identical byte masks lower through virtual registers 113 and 54. Constant propagation changes the second mask to a copy; value numbering eliminates that copy, leaving root 113.
- `arg1 & 0xFF`: a halfword mask followed by a byte mask survive those early passes. A later peephole folds them, leaving root 54 instead.
- The output-parameter helper puts the retained count in a different inline-object position. In the matched dump, model 113 and early data 67 get r25, count 62 gets r24, and created object 59 gets r23. This is the required ordering.

Nine natural helper variants were compiled: u16/u32/s32 parameter types crossed with assignment-return, local-return, and output-parameter forms. All three output-parameter forms match; u16 is retained to agree with the existing argument type. Assignment-return forms scored 99.92092%; local-return forms scored 99.69133%.

```c
static inline void GlyphVariantCount(u16 count, s32* out)
{
    count &= 0xFF;
    *out = count;
}
```

The helper stays in the existing `MUST_MATCH` region with `inline_depth(2)`. The caller declares `s32 variant_count`, calls the helper before the loop, and compares `i < variant_count`. This proves a matching source form and its observed compiler mechanism, not the original developer's helper signature. Register and temporary numbers above belong to the saved dumps; identify values again after changing source or context.

## The four investigations

| Investigation | Result and limits |
| --- | --- |
| Retail backend plus debug verification | Retail object parity initially failed because the retail path did not apply the normal Shift-JIS wrapper to Japanese literals. A diagnostic source with equivalent CP932 octal byte escapes restored object parity. Backend comparison reported 585 equal, 72 retail-only, and zero different debug/retail facts. This supports using the debug allocator evidence for this function. The retained source keeps the original Japanese literals. |
| Paired retail frontend traces | Both baseline and masked sources were traced through 62 stages. The count expression was the only expression-shape difference after accounting for node IDs: nested casts versus AND with 255. Both were hoisted to frontend temporary `@1205` at loop discovery. Backend traces locate the subsequent early-versus-late folding difference described above. |
| Donor and opcode searches | Whole-function semantic and hashed searches, window searches, focused creation-loop windows, and opcode searches were run. High-scoring windows mostly represented generic JObj translation/assertion code. No exact structural donor emerged. Related name-entry creation/animation helpers informed the inline ownership experiment. |
| MWCC frontend inspector | Fixed generated-include transport allowed the compiler to finish and produce a 504224-byte IR dump. The recovered target section confirmed the expected argument types and distinct inline object copies; no unexpected aggregate/type explanation appeared. The wrapper still failed to publish completion and prove cleanup. The recovered IR is diagnostic evidence, not a successful end-to-end wrapper run; issue 1476 remains open. |

## Full-file linking and BSS ownership

The first 100% function/object report still failed the linked checksum: 26 bytes differed, all address relocations caused by the current-name buffer preceding four model descriptors in BSS. Declaration, storage, ordering-function, and buffer-shape probes either preserved that wrong order or changed other functions. These experiments were discarded.

The decisive evidence was in `mnName_8023AC40`: retail addresses the four shared descriptors through the `mnname.c` BSS anchor. They had been assigned to the wrong translation unit. Moving their definitions to `mnname.c` and moving the BSS split from 0x804A06F0 to 0x804A0740 restores the correct ownership and layout. It also allows direct named-field references instead of reaching past `mnName_804A06E0`.

Check ownership before repeating declaration sweeps. Generated target `.o` files reflect `splits.txt`; they cannot independently prove that an existing split is correct. The retail address calculations, neighboring consumers, and final linked checksum supplied that evidence here. Definition visibility also changed address hoisting in discarded probes, so moving a definition is not universally codegen-neutral.

Final source contains no BSS ordering function, incomplete-array workaround, additional pool pragma, or struct wrapper from those discarded probes.

The fresh upstream build also produced the exact original DOL. Its CI-style symbol comparison required updating the newly linked TU's metadata: glyph strings have three bytes plus alignment rather than a four-byte symbol size. The normal linked-ELF metadata update also records local literal names and scopes. These metadata changes are included in a second decomp commit; they do not change DOL bytes.

In this run `ninja diff` returned exit status 0 while printing `ERROR Size mismatch` lines. Read the diagnostic output as upstream CI does; a successful process exit alone was insufficient. Applying the linked symbol metadata and rerunning the build and diff cleared those errors.

## Persisted evidence and retrieval

The [tracked evidence directory](matching-evidence/mnnamenew/README.md) contains the match report, both unit reports, nine-variant results, matched allocator dump, paired-pass differences, fidelity report, and build logs. Its SHA-256 manifest records the original artifact paths. Four selected mismatch DB records are also snapshotted there as valid JSON.

The larger frontend/backend captures, candidate source files, recovered inspector IR, and wrapper-test log remain supplementary local artifacts under `build/d82d-glyph-investigation/`. The reusable findings and key evidence no longer depend on that ignored directory surviving cleanup. Reconstruct the retained C from the source commits above; use the nine-variant score table to avoid repeating losing return-helper forms.

Searchable mismatch IDs:

- `inline-count-mask-survivor-regalloc`
- `bss-owner-split-mismatch-hidden-by-object-score`
- `glyph-string-symbol-size-includes-alignment`
- `retail-parity-source-encoding-mismatch`

## Tooling follow-up

- Issue 1475 resolved: missing generated include directories are handled by the transport repair (upstream tooling commit 94f54d46c1, local cherry-pick 31dcf5bf31). A separate compressed-archive corruption test adjustment is local commit 66cf712364. These tooling commits are excluded from the decomp PR.
- Issue 1476 remains open: wrapper publication and exact-job cancellation still lack terminal cleanup proof. Live job IDs are `d82d-glyph-inspect-path-20260906` and `d82d-glyph-inspect-generated-20260906`; no broad process termination was attempted.
- Issue 1481 remains open: retail capture should handle source encoding consistently with the production Shift-JIS wrapper.
- Issue 1478 resolved for donor commands by delaying the unused text-query import in decomp-search, local commit 74cb1b2 in that repository. Its separate text-query embedding helper remains unavailable; this does not affect donor searches.
- Issue 1486 filed while persisting these notes: `mismatch get --json` used Rich formatting, inserting literal newlines into JSON strings. The snapshot uses a read-only DB query and the existing `Pattern.from_row().to_dict()` serializer. Treat issue states above as observations from this session and recheck the issue queue before relying on them.
