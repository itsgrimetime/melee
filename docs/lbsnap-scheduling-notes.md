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

Correction from the scheduler follow-up: the early default PCode snapshots are **not target-specific**. Although CodegenStart has entered lbSnap_8001DA5C, the global block list still contains the preceding lbSnap_8001D7B0: 171 instructions and a 168-byte frame, instead of the target’s 108 instructions and 72-byte frame. Issue1505 records this stale-function capture. Do not use those early snapshots to compare source candidates. The 42 color decisions are separate evidence and are not invalidated merely by this snapshot bug.

A temporary read-only hook now captures the actual target immediately before and after both scheduler calls, plus codegen end. The ASCII surrogate still passes full-object parity. These are diagnostic snapshots with raw operand fields, not a promoted complete backend trace. The fast patched-DLL dump still omits the function with global_optimizer off (issue1498).

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

## Exact scheduler decisions (follow-up)

The read-only scheduler hook uses fixed breakpoints in the retail compiler
SHA256 `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
First scheduler call/return: `0x435b79` / `0x435b7e`; final call/return:
`0x435d70` / `0x435d75`. The picker is `0x4ccdc0`, with its caller return
at `0x4ccd09`. Eligibility callback returns are observed at `0x4ccdef`
and `0x4cce36`. These addresses are compiler-version-specific.

The baseline and an early-color variant both completed with empty hook
errors, every requested stage, and byte-identical ordinary/emulated objects.
The early-color variant moves the first conversion immediately after the
first pixel load. Ordinary output remains 98.14815%.

| Stage | Baseline addze / mask order | Early-color addze / mask order |
|---|---:|---:|
| Before first scheduler | 63 / 67 | 67 / 47 |
| After first scheduler | 64 / 69 | 64 / 69 |
| Before final scheduler | 66 / 70 | 66 / 70 |
| After final scheduler | 66 / 67 | 66 / 67 |

Orders are zero-based PCode indices within each snapshot; follow the same
runtime PCode identity across stages, not an earlier `addze r30,r30` that
also exists in the function. The first scheduler sees 105 instructions;
the final scheduler sees 108 after later compiler transformations.

At first-pass cycle38, both instructions pass the CPU eligibility callback
and have zero outstanding dependencies. `addze` has ready-cycle37,
deadline30, cost14, and immediately unlocks one dependent instruction.
The blue mask has ready-cycle21, deadline29, cost15, but unlocks zero:
the subsequent OR also awaits the other color mask. The picker prioritizes
the number of newly unlocked dependents before cost, so it selects `addze`
regardless of the earlier source placement. The other mask issues at42
and the blue mask at43. This is observed in both source variants.

By final-pass cycle38, color operations have been combined. Both candidates
are eligible, overdue, cost14, and unlock one dependent. The extra opcode
class tie-break is disabled (`prealloc_mode=0`). The picker retains the first
candidate in the linked list, which is `addze`; the blue mask follows at39.
Thus simple source reorderings are erased by the first scheduler, and the
final scheduler preserves the resulting tie order. This is a measured
explanation of the current source, not proof that alternative source cannot
match. A useful next source hypothesis must alter the earlier dependency
graph or the code shape presented to scheduling.

The active model pointer was `0x574d70`, CPU-option bytes `08020000`, and
eligibility callback `0x52dfa0`. The callback is not a defined function in
the retained Ghidra project; an export produced no function, so no static
callback decompilation is claimed. Direct return observations above establish
eligibility without that missing static export.

## Additional source probes

Three earlier placements of the first conversion (after load, before source
increment, before destination quotient) were neutral. Inlining its raw
expression was 98.05556%; doing so for both pixels was 97.96296%.
A cast on the first expression remained 98.05556%. All were reverted.

The scheduler-derived source probes below were also reverted:

| Probe | Match % |
|---|---:|
|First conversion, local blue-first u16|93.87037|
|First conversion, local blue-first u32|93.87037|
|First conversion, local red-first u16|94.51852|
|Explicit field replacement u32|93.87037|
|Explicit field replacement u16|93.87037|
|Local u32 bitfield union|82.43519|
|Local u16 bitfield union|82.43519|
|XOR field replacement|87.01852|
|Red-first assignments to existing rgb5a3|94.51852|
|Blue-first assignments to existing rgb5a3|93.87037|
|Color helper output parameter|90.583336|
|Separate helper inputs for color components|98.14815|
|Masked color inputs to helper|98.14815|
|Bitfield union inside color helper|76.583336|
|Mask before shift in color helper|98.14815|
|Remainder helper, second source coordinate|86.85185|
|Remainder helper, all pixel coordinates|90.23148|
|Remainder helper output parameter|98.14815|
|Remainder helper using explicit quotient|87.57407|
|Local quotient then subtraction|87.48148|
|Embedded quotient assignment|87.48148|
|Division helper, second source coordinate|85.39815|

Bitfield unions introduced stack accesses. Separate locals introduced extra
copies and register changes. Split/masked input helpers and the remainder
output parameter reproduced the original final output. None justifies a
production source change or TU linkage.

## Capture validity and failure handling

Issue1506 records a generic custom-hook run returning exit0 after a debugger
disconnect without a completed summary. Require a completed summary, empty
errors, expected stages, and fresh object parity; exit0 or an unchanged old
object alone is insufficient.

The first picker hook used temporary return breakpoints that returned false
and accumulated duplicate events. A second version deleted a breakpoint from
inside its callback and hung macOS GDB. Both runs are invalid; their launch
logs and hook sources are retained for diagnosis. Fixed static entry/return
breakpoints avoid both failures. Successful captures are partial diagnostic
evidence; no forced compiler mutation was used for the scheduling findings.

## Evidence

`~/.config/decomp-me/matching-evidence/lbsnap-scheduling-2026-09-06/` contains baseline/ASCII source, identical ordinary objects, all checkdiff JSONs, exact trace artifacts, failure/success logs and a recursive SHA256 manifest. No improved source commit or new PR was created in this pass.

The `scheduler-pick-followup/` evidence directory adds all successful scheduler
captures, hook sources, static exports, source/checkdiff probes, and a SHA256
manifest. Failed captures retain hook/launch diagnostics without their duplicate
event streams. The final ordinary baseline is still 98.14815%.

Restored-source verification: ordinary checkdiff 98.14815%, 72-byte frame;
`python configure.py` and `ninja` completed, with `main.dol: OK`.
