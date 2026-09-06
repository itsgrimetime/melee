# lbSnap_8001DA5C scheduling follow-up

## Verified state (2026-09-06)

The source from merged PR3363 remains **98.14815%**, 432 bytes, with the exact 72-byte frame. Only two adjacent instructions differ: target `clrlwi r31,r25,27` at+0x108 then `addze r30,r30` at+0x10c; current order is reversed. All source probes below were reverted. This is the last function below100 in lbsnap; link the TU only after an ordinary100% compile and original DOL checksum verification.

Current goal progress this pass is a diagnostic blocker resolved by a verified workaround, not a new source match.

## Retail trace parity failure: confirmed encoding cause

Issue1499 previously blocked both preview PCode probes and the exact `debug retro backend` command. Both paths produced reference19984bytes versus emulator20000bytes. Inspection of `src/cli/debug/retro.py::_run_object_parity_for_backend` found that the reference uses wibo+sjiswrap, while the emulator runs MWCC directly.

`lbsnap.c` has one Japanese literal in another function, `lbSnap_8001DC0C`. It occupies62UTF8bytes but42ShiftJISbytes. The rounded object-size difference was an encoding artifact, not evidence that global_optimizer-off code generation differs under emulation.

Verified diagnostic workaround:

1. Preserve the unmodified TU and its ordinary compiled object.
2. In a temporary source probe, replace only the Japanese string contents with three-digit octal escapes of their ShiftJIS bytes. Keep source path, line count, flags and all C code unchanged.
3. Compile through ordinary checkdiff and compare the entire object byte-for-byte to the preserved ordinary object. They were identical:19984bytes, SHA256 `50894496c580b4f6eb3d3b39dfc3d74ab5f2be71be3c1d18cbbea30dca9e5e7c`.
4. Run `melee-agent debug retro backend src/melee/lb/lbsnap.c -f lbSnap_8001DA5C --output <diagnostic-dir>` against the ASCII surrogate. The parity gate passes and the command exits0.
5. Restore the original Japanese-source TU and verify the ordinary98.14815% baseline again.

No ASCII escapes are retained in production source. Issue1499 remains open because the tool should apply equivalent encoding consistently to the reference, parity and trace paths. Findings and workaround were appended to that issue; the claim was released.

## What the trace proves, and what it does not

The successful exact backend route emitted a target-specific PCode snapshot and42 exact GPR color decisions, including the expected r25-r31 locals. This gets past the former parity blocker. The trace has no scheduler-decision stage; many instruction operands are not rendered by the current snapshot summary. Its operand/object event sidecars explicitly report partial capture and unpromoted instrumentation capabilities. Do not describe those sidecars as a complete scheduler trace.

Next action: use this byte-identical ASCII surrogate to obtain local-optimizer/pre- and post-scheduling visibility, or compare meaningful source candidates at the captured PCode boundary. The fast patched-DLL dump still omits the function with global_optimizer off (issue1498).

## Bounded source tests

Independent statements tested in all24orders:

- `0`: src_tile = pixel_column / 4
- `1`: src_row_in_tile = src_row % 4
- `2`: src_column_in_tile = pixel_column % 4
- `3`: rgb5a3 = RGB565_TO_RGB5A3(rgb565)

No ordering improves the baseline. Keeping division/modulo order and moving RGB conversion is neutral; other permutations regress. Exact probe scores:

| Order | Match % |
|---|---:|
|0123 (baseline)|98.14815|
|0132|98.14815|
|0213|95.046295|
|0231|95.046295|
|0312|98.14815|
|0321|95.046295|
|1023|88.51852|
|1032|88.51852|
|1203|88.14815|
|1230|88.14815|
|1302|88.51852|
|1320|88.14815|
|2013|91.25|
|2031|91.25|
|2103|94.25926|
|2130|94.25926|
|2301|91.25|
|2310|94.25926|
|3012|98.14815|
|3021|95.046295|
|3102|88.51852|
|3120|88.14815|
|3201|91.25|
|3210|94.25926|


Blue-first mask initialization repeats a known rejected family (96.75926%). A separate red/green/blue channel helper is new but regresses85.07407%, adds two instructions, and keeps the72-byte frame. Both were reverted.

## Evidence

`~/.config/decomp-me/matching-evidence/lbsnap-scheduling-2026-09-06/` contains baseline/ASCII source, identical ordinary objects, all checkdiff JSONs, exact trace artifacts, failure/success logs and a recursive SHA256 manifest. No improved source commit or new PR was created in this pass.
