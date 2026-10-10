# Melee Stockfish portability catalogue

Fork checklist, inspected 2026-10-09. This is an inventory and preliminary
triage, not an approved patch plan. Game source was not changed. No new native
runtime, Dolphin, or matching build validation was performed for this inventory.
Names and behavior asserted by port comments remain claims to reproduce before
using them in decomp documentation.

## Scope and provenance

The port pins Melee `d567c22dfc61161bfad4a50f210ca46e6c11ef88` (2026-09-07).
The decomp checkout audited for this inventory was detached at `4c2cb1842cca22551c9e77f8c66f111e61da55f8`
(2026-09-15). The cached `upstream/master` inspected here is
`79b13a32467f7c4f91d6f831f0b9f891b7fb1146` (2026-10-08). That cached ref is
not a live GitHub status check. The SDK moved from `extern/dolphin` in the port's
pin to `libs/dolphin` here; retain current upstream names and declarations.

Three committed port snapshots were inspected, including work not merged into
the main checkout:

| Snapshot | Commit | Patch selection |
| --- | --- | --- |
| `melee-stockfish`, `main` | `a23a7530cacbc6ae22a03035c56fdd30da060d76` | 98 baseline + 213 natural-start/Slippi patches = 311 |
| `codex/lane-1-runtime-m0`, integration worktree | `f7bea165fd47811ce13b31981150be279db7e0b9` | 98 baseline + 213 natural-start/Slippi patches = 311; 2 additional patch files unselected |
| `codex/parity-hungry-firefox`, arithmetic follow-up | `7ce9bd7213ba1d4064f130e029985bedce350944` | 98 baseline + 210 natural-start/Slippi patches = 308; 3 additional patch files unselected |

Across those snapshots there are **335 distinct numbered patch paths**, plus
`native/source/fd_dat_adapter/core-repair.patch`: **336 patch artifacts**.
These are not 336 independent bugs. Many add copied original functions, asset
providers, instrumentation, or incremental admissions of previously missing
code. Twenty-one main-snapshot patches are removed in the integration snapshot;
two more are retained on disk but deselected. Patch `2042` also changes content.
The appendix accounts for every artifact and its selection status.

Supporting build/provider code was inspected too: `patch_build.py/json`,
`startup_build.py`, `legacy_build.py`, `dat_graphs.py`, `graph.py`,
`graph_schemas.py`, `native/host/`, the integration `bulk_*` providers, and the
port's `docs/native-tasks.md` and `docs/native-upstream-reuse.md`.
Archived AOT experiments, unrelated external repositories, and every historical
version of an already indexed patch are outside this inventory. The legacy
overlay builder largely duplicates the numbered baseline and is not counted
as a second set of fixes.

Checkboxes track **triage**. Checked means a structurally equivalent fix was
found here or in the cached upstream source; it does not claim new runtime or
human validation. Unchecked means a decision or investigation remains. Patch
numbers below link into the appendix. References to "here", "this checkout"
and "cached upstream" describe the recorded audit snapshots above.

## Suggested first investigations

Start with S01/S02 (particle count and callback declarations), S04 (Fox blaster
effect pointers), S05/S06 (command storage and stride), and S09/S10 (global
layout assumptions and projection-matrix type). S14/S15 are another coherent
callback/control-flow task. Each needs a current-upstream overlap check before
implementation. Keep the scope to one type path or abstraction per change.

## Already covered, wholly or in the stated part

- [x] **A01 — Fixed-width SDK integers and pointer-width integer typedefs.**
  [0001](#patch-0001) changes `s32/u32` from `long` to `int` and
  `intptr_t/uintptr_t` to compiler-width types. This worktree and cached upstream
  already select the target spelling for MWCC and the host spelling otherwise
  in `libs/dolphin/include/dolphin/types.h` and `src/MSL/stddef.h`.

- [x] **A02 — HSD object IDs can contain native pointers.**
  [0001](#patch-0001), [0009](#patch-0009), [0010](#patch-0010),
  [0011](#patch-0011), [0024](#patch-0024) widen keys, descriptor IDs and callers.
  Already handled here by `HSD_IDKey` with a `MUST_MATCH` representation;
  do not replace that domain type with the port's raw `uintptr_t` spelling.

- [x] **A03 — Fighter data pointer declarations.**
  [0001](#patch-0001) and the legacy overlays change `FtSFX.x1C` to `FtSFXArr*`
  and `ftData.x54` to `int*`. Both declarations are already fixed here; cached
  upstream also annotates the `x54` extent.

- [x] **A04 — CaptureWait must access the actual Fighter layout.**
  [0064](#patch-0064) removes `FighterOverlay` and raw common-data offsets in
  favor of `mv.co.capturewait`, `grab_timer`, `victim_gobj` and declared fields.
  Equivalent field access is already present here and in cached upstream.

- [x] **A05 — Allocator heap addresses have pointer width.**
  [0001](#patch-0001)/[0005](#patch-0005) widen `objheap.top/curr`, alignment
  masks and arithmetic. Cached upstream has pointer-width heap fields; this
  older worktree still has `u32` fields. Reuse the upstream allocator change,
  keeping the host pool/lease wrappers in N01 outside the decomp.

- [x] **A06 — Motion metadata's pointer-bearing `x14`.**
  [0001](#patch-0001) widens the slot. Cached upstream already declares
  pointer-width `x14` in the relevant motion layouts. The port's numeric cache
  keys versus native addresses still need the domain audit in B03.

- [x] **A07 — Effect parameter table and animation queue access.**
  [3400](#patch-3400) replaces `efLib_AnimQueue + 0x10` with `efLib_ParamTable`,
  replaces `u32*` queue indexing with pointer indexing, and removes pointer
  narrowing from existence checks. Cached upstream's cleaned effect code
  already uses the actual table and typed queue. Some improvements are also in
  this checkout. Audit remaining host-sensitive allocation sizes separately.

- [x] **A08 — Six result-player records and their actual contents.**
  [0001](#patch-0001) changes `kills[4]` plus padding to six entries and makes
  `MatchEnd.x44C` six records with the byte and integer arrays exposed.
  Cached upstream already has `kills[GM_MAX_PLAYERS]`, six records, and the
  `x0[0x101]`/`x104[0x101]` members. The patch also changes a result header `x0` from `UNK_T` to `u32`;
  current `MatchEnd.x0` is a fixed-width `u32`. The byte/word bitfield
  changes remain B01 follow-ups.

- [x] **A09 — Ground color overlay and material-script pointer types.**
  [1220](#patch-1220)/[3501](#patch-3501) add storage for a widened
  `ColorOverlay`, remove the `gp + 0x40` access and type the script argument.
  Cached upstream already has `Ground.color_overlay`, field access, a typed
  `grMaterial_801C9604` argument and `HSD_IDKey` callers. Do not import the
  port's conditional union or duplicate declaration over that layout.

- [x] **A10 — HUD state, material-animation records and joint traversal.**
  [0071](#patch-0071)/[1151](#patch-1151) replace fixed-offset HUD overlays,
  reinterpretation of material animation as joint animation, and GObj-shaped
  traversal of JObjs. Cached upstream uses `IfDamageState`, material-animation
  pointers and a typed JObj helper. Other HUD clearing/owner changes still
  need review under S13/N11; this does not certify all of patch 1151.

- [x] **A11 — Generator list head and iteration cursor are pointers.**
  [0043](#patch-0043)/[3400](#patch-3400) replace integer storage/casts for
  `hsd_804D78F4/F8`. Cached upstream uses `HSD_SList*` and `HSD_Generator*`.
  Its callback globals remain integer-typed: see S02.

- [x] **A12 — Native DAT opaque-reference identity and missing-pointer checks.**
  [core-repair](#patch-core-repair) records opaque native identities and reports
  missing relocated pointers instead of silently omitting null mismatches.
  Both changes are present in cached upstream `tools/dat-cli/native/src/archive.c`.
  Retire the isolated old-core repair when repinning; avoid another loader fix.

- [x] **A13 — Sound-mode service prototypes use fixed-width words.**
  [0001](#patch-0001) changes `OSGetSoundMode`/`OSSetSoundMode` from
  `unsigned long` to `u32`. This worktree and cached upstream already use `u32`
  in `libs/dolphin/include/dolphin/os/OSRtc.h`. Reuse those declarations instead
  of applying the port's old header overlay.

- [x] **A14 — Particle creation arguments are actual pointers.**
  [0001](#patch-0001)/[0042](#patch-0042)/[0043](#patch-0043) widen
  `hsd_80398F0C`'s command-list and generator arguments and callers.
  Cached upstream goes further and declares `u8*` and `HSD_Generator*` arguments.
  Reuse that type path instead of importing pointer-width integer parameters;
  command words and numeric flags remain fixed-width.

## Source corrections worth investigating

- [ ] **S01 — Particle texture-group counts declared as pointers.**
  [1214](#patch-1214) makes `psFormGroupArray[65]` an `s32` count array, replacing
  writes through `(s32*)` and pointer-null initialization. The old declaration
  remains in cached upstream. Audit every read/write and archive header, then
  test bank initialization and indexing with LP64 storage.

- [ ] **S02 — Particle callbacks stored in `u32` globals.**
  [3400](#patch-3400) types `hsd_804D78E8` as a generator/matrix callback and
  `hsd_804D78EC` as a generator callback, updating declarations and calls.
  Cached upstream still casts integer globals to those function pointers.
  Check all registrations and callback ABIs before choosing shared typedefs.

- [ ] **S04 — Fox blaster's effect ring stores returned effect pointers.**
  [1252](#patch-1252)/[3112](#patch-3112) widen `foxblaster.xDE4[6]` and the
  `efSync_Spawn` assignments, including the Kirby-Fox caller. Cached upstream
  still has `s32` elements. Trace destruction, nulling, aliases and adjacent
  ring fields; determine the concrete pointee before accepting `uintptr_t`.

- [ ] **S05 — Command loop frames mix counters and pointers.**
  [0057](#patch-0057) removes `((u32*) info)[loop_count + 3]` and manipulates
  `event_return` through fields. That slot also holds an integer loop count.
  The port still casts integers to pointers. Design truthful loop-frame storage
  or an accessor; verify nested loops, returns and target codegen. Cached
  upstream retains the word-indexed implementation.

- [ ] **S06 — Temporary command arrays assume four-byte cells.**
  [1300](#patch-1300) changes `u32 cmd_words[3]` to `union CmdUnion[3]` in
  the fighter effect handlers and copies named members instead of byte offsets.
  Cached upstream retains the `u32` arrays. Test the sound/effect paths against
  both layouts; do not carry host-only initialization into matching source
  without proving identical stack and instruction output.

- [ ] **S07 — Operand decoding bypasses declared command members.**
  [0044](#patch-0044) replaces the fixed-offset `spawn_hitbox_skip.xF_b4` view
  with `cmd->u[3].create_hitbox_3.ignore_thrown_fighters`;
  [0061](#patch-0061) replaces `((u16*) cmd->u)[1] & 0x1FFF` with the item
  damage member; [1300](#patch-1300) replaces halfword effect-ID decoding.
  These remain candidates in cached upstream. Confirm command layouts and
  read semantics; resolve compiler-sensitive source forms with match evidence.

- [ ] **S08 — Collision-line stride and pointer arithmetic.**
  [0001](#patch-0001) replaces `(int) groundCollLine + offset` casts and
  `flags_base[id * 2]` with host-width arithmetic and declared `.flags` access.
  Cached upstream has already cleaned the narrowing path, but still contains
  the `flags_base[id * 2]` indexing. Prefer typed indexing after tracing the
  helper contracts. Keep the separate connectivity behavior change in N09.

- [ ] **S09 — Synthetic structs assume neighboring globals are one object.**
  [0042](#patch-0042) replaces `ParticleData*` over particle globals with their
  actual declarations; [0089](#patch-0089) removes `CameraStaticData*` over
  `cm_803BCB18` in favor of `cm_803BCB64`; [2004](#patch-2004) removes
  `lbRefract_DataLayout*` over `texture_mtx` in favor of `imagedesc0`.
  All three patterns remain in cached upstream (some symbols are renamed).
  Trace target addresses and each access; use declared globals or an accurate
  source aggregate, then measure each function's match separately.

- [ ] **S10 — Projection output uses a 3×4 matrix declaration.**
  [0056](#patch-0056) changes `lbVector_WorldToScreen`'s `Mtx projMtx` to
  `Mtx44`. Cached upstream still declares `Mtx`, then calls perspective/ortho
  constructors. Reproduce the storage-size problem with the actual native SDK
  implementations, and test target frame/layout effects before changing it.

- [ ] **S11 — Bone collision records contain a pointer hidden in padding.**
  [0058](#patch-0058) replaces the local fixed-offset bone record with explicit
  offset/radius/JObj/position/index members. Cached upstream retains padded
  storage. Verify against the canonical fighter collision record, every use
  and DAT layout; prefer reusing that type over independently naming fields.

- [ ] **S12 — Star-death common-data reads alias across scalar members.**
  [0052](#patch-0052) substitutes `source_common_data_star_words` for an `s32*`
  rooted at `p_ftCommonData->x504`. Subsequent offsets include float values.
  Cached upstream still uses this view. Check the generated host data and all
  accessed slots; replace cross-member indexing with declared fields where
  supported. Do not upstream a detached five-word fixture array.

- [ ] **S13 — Hardcoded allocation/clear sizes follow target layouts.**
  [3400](#patch-3400) uses `sizeof(HSD_psAppSRT)` instead of `0xA4`;
  [1151](#patch-1151) clears the HUD prefix with `offsetof(HudIndex, unk258)`
  instead of `0x258`. Audit the remaining constructors in the native slices
  for equivalent fixed-size assumptions. Verify whether each operation covers
  a complete object, a genuine prefix, or serialized target storage.

- [ ] **S14 — Stage animation callbacks lose pointer arguments.**
  [3500](#patch-3500) separates `AOBJ_ARG_AV/AOV/AOTV` pointer calls from
  their `AU/AOU/AOTU` integer counterparts and types `fn_801C82E8`'s arguments
  as `HSD_AObj*`/`HSD_AObj**`. Cached upstream still loads pointer arguments
  through `int*` and has integer callback parameters. Audit all dispatch
  variants and registrations; avoid importing the complete port cast switch
  until callback type compatibility is checked.

- [ ] **S15 — A pointer modified between setjmp and longjmp needs scrutiny.**
  [3501](#patch-3501) makes the stage animation search result and callback
  destination volatile after [3500](#patch-3500) replaces the target jump ABI.
  Cached upstream has an ordinary `HSD_AObj* sp14`. Reproduce under optimized
  host compilation; separate a C lifetime/control-flow correction from the
  Darwin jump-buffer implementation in B05.

- [ ] **S16 — Inline linkage and include resolution.**
  [3400](#patch-3400)/[1151](#patch-1151) use `static inline` for local effect
  and HUD helpers. Many 00xx patches qualify headers because exported/sliced
  translation units lose their original source-directory lookup. Check modern
  C linkage issues against intact current units; do not upstream the export
  tool's header-alias map or mechanically rewrite every include.

## Abstractions and cross-platform policy

- [ ] **B01 — Endian-sensitive bitfields and whole-word views.**
  [0001](#patch-0001) reverses `FighterPart`/result bitfield declarations;
  [0081](#patch-0081) decodes `Struct2070` with masks;
  [1235](#patch-1235) replaces byte bitfields with a word-sized declaration
  for `StageCallbacks`. Command/colour providers also decode bitfields.
  Audit byte flags, numeric words, union views, and serialized inputs together.
  Prefer shared masks/accessors or a designed representation over accumulating
  unrelated little-endian declarations.

- [ ] **B02 — Command and color streams have different native strides.**
  [1302](#patch-1302) uses `sizeof(CmdUnion) / sizeof(ColorOverlay_x8_t)`
  to step color streams, with assertions about the overlapping `CommandInfo`
  and `ColorOverlay` prefixes. `bulk_fox_commands.py` materializes one host
  command cell per retail word and preserves interior aliases. Decide whether
  the decomp needs a common command-cell abstraction; keep DAT relocation and
  host graph allocation outside gameplay source.

- [ ] **B03 — Animation banks and cache keys mix address domains.**
  [0019](#patch-0019), [0068](#patch-0068), [1226](#patch-1226),
  [1240](#patch-1240), [3504](#patch-3504) adapt motion metadata, ARAM/DAT
  loading, host command pointers and per-fighter caches. Trace numeric guest
  addresses, offsets, IDs and native pointers independently. Introduce only
  a reusable domain boundary in the decomp; keep loading/resolution in the port.

- [ ] **B04 — Explicit PPC floating-point behavior.**
  [0003](#patch-0003), [0004](#patch-0004), [0012](#patch-0012),
  [0013](#patch-0013), [0047](#patch-0047)–[0049](#patch-0049),
  [0051](#patch-0051), [0055](#patch-0055), [0056](#patch-0056),
  [0058](#patch-0058)–[0060](#patch-0060), [0063](#patch-0063),
  [0066](#patch-0066), [0067](#patch-0067) insert fused operations in animation,
  geometry, damage/knockback, shield, reflector turn and quaternion arithmetic.
  [0022](#patch-0022)/[0041](#patch-0041) supply paired-single matrix/vector
  sequences and reciprocal/reciprocal-square-root estimate tables;
  [0001](#patch-0001) routes placeholder square roots to them.
  Preserve operand order, intermediate rounding, special values and signed
  zero in a compatibility boundary. A generic host `sqrt` or global contraction
  flag is not an equivalent implementation. Keep implementations in the port;
  investigate a small reusable decomp interface only when needed.

- [ ] **B05 — MSL varargs and jump buffers are target ABI objects.**
  [0011](#patch-0011), [3401](#patch-3401),
  `bulk_particle_va.h`, [3500](#patch-3500) use host varargs, proper copying
  and a Darwin ARM64 jump buffer. Copied effect/archive functions do likewise.
  Consider a compiler-specific header boundary usable by native compilers;
  keep `int[48]` jump storage and host runtime linkage in the port. Maintain
  coherent `va_list` types in definitions and every prototype.

- [ ] **B06 — Target layout assertions and host compilation contract.**
  [1202](#patch-1202) adds LP64 offsets for `ToyED8Data`; the builder uses
  `-nostdinc`, `-fno-short-enums`, `-fno-strict-aliasing`, `-fwrapv`,
  `-ffp-contract=off` and `-fno-fast-math`. Cached upstream already gates size
  and offset assertions with `MUST_MATCH`/`LINT`. Audit which assertions express
  target layout versus semantic invariants; review disabled checks before
  concluding that a native compile validates a layout.

- [ ] **B07 — Reuse upstream native DAT tooling and accurate source types.**
  [0007](#patch-0007), [0008](#patch-0008), [1207](#patch-1207),
  [2005](#patch-2005), [2006](#patch-2006), [3000](#patch-3000),
  [3101](#patch-3101) and the graph/provider modules adapt archives, stage
  materials, effect tables, motion banks, public roots and aliases to host
  structures. The port's pin predates current native DAT codegen/annotations.
  Reuse them before proposing duplicate layouts or annotations, preserving
  scalar widths, array strides, shared identity and selected union variants.
  Confirm any residual type defect against current source and real archive data.

## Port implementation or gameplay-modification work to retain externally

- [ ] **N01 — Host allocation and instrumentation.**
  [0005](#patch-0005), [0021](#patch-0021), [0031](#patch-0031),
  [1000](#patch-1000)–[1002](#patch-1002): aligned pools, object leases,
  memory poisoning/seeding, counters, probes and failure wrappers. Extract only
  the address/size source corrections; this allocator infrastructure stays native.

- [ ] **N02 — Headless output policy.**
  [0023](#patch-0023)–[0029](#patch-0029), [0038](#patch-0038),
  older 111x/113x/114x audio/rumble/shadow patches, [1150](#patch-1150),
  [2042](#patch-2042), [3505](#patch-3505): presentation traps, no-ops,
  omitted GX links, audio playback, rumble, lighting and shadows. The integration
  snapshot replaces many per-call admissions with unconditional output no-ops.
  Keep those implementations external; preserve gameplay/RNG work in HUD,
  camera, effects and particles rather than classifying whole modules as output.

- [ ] **N03 — Copied functions, symbol substitution and restricted providers.**
  Most 0014–0020, 0032–0041, 0050/0054/0062/0068–0088,
  1110–1127, 1203–1209 and 2xxx/31xx patches add original-source slices,
  fixture globals, fail-fast stubs or routing macros. Bulk 3500–3506 restores
  whole units and retires selected providers. Missing host coverage is not a
  decomp defect. Check the extracted body for a specific type/layout problem
  before proposing source work; do not import the copied native modules.

- [ ] **N04 — Console services and simulation entry points.**
  [0006](#patch-0006), [0088](#patch-0088), [1003](#patch-1003),
  [1208](#patch-1208), [1230](#patch-1230), [2000](#patch-2000),
  [2002](#patch-2002), [2008](#patch-2008), `native/host/startup_runtime.c`:
  controller injection, scheduler observation, OS/cache/device/disc service
  replacements, fixed bus clock and natural startup API. Any decomp work should
  supply an interface only; hardware/runtime implementations stay native.

- [ ] **N05 — Asset materialization and host archive dispatch.**
  Generated DAT graphs, command/motion descriptors, costume/effect/item banks,
  inline retail tables and public-symbol dispatch are host loader work.
  [1207](#patch-1207) hooks `HSD_ArchiveGetPublicAddress` for native archives.
  Keep adapters and generated assets external, even when their missing types
  motivate a narrow source/annotation fix under B07.

- [ ] **N06 — Fox–Fox FD domain restrictions.**
  [3001](#patch-3001), [3002](#patch-3002), [3103](#patch-3103),
  [3503](#patch-3503), [3505](#patch-3505) constrain random items, stage/character
  factories and unsupported branches. These are simulator coverage choices;
  do not upstream aborts, FD-only tables or deleted non-Fox behavior.

- [ ] **N07 — Slippi/UCF and replay-format behavior.**
  `slippi/0001`–`0006` add input history/UCF hooks, online physics, L-cancel
  recording, independent rule flags and FD background/RNG profiles. Recording
  patches 1213/1217 and `native/host/startup_recording.c` add capture integration.
  These are deliberate gameplay/mod/capture changes relative to GALE01, not
  portability source fixes. Keep them in the simulator.

- [ ] **N08 — Historical RNG ordering workarounds.**
  [0002](#patch-0002), [0043](#patch-0043), [0075](#patch-0075) contain trace,
  permutation, replay and selected-generator/effect ordering machinery.
  [3400](#patch-3400) removes the selected-generator and throw/dash special
  handling when whole effects run. Inventory remaining call sites before
  interpreting a historical parity result; these are not upstream RNG fixes.

- [ ] **N09 — Collision connectivity and detached blend-loop workarounds.**
  [0001](#patch-0001) replaces a neighbor-exists test with an endpoint-distance
  test; [0045](#patch-0045) sets `AOBJ_LOOP` on a detached blend JObj during
  animation. The legacy builder describes the latter as compensation for host
  traversal. These change source behavior, unlike pure width corrections.
  Reproduce the root cause and prove retail equivalence before considering
  any decomp change; do not import either workaround as-is.

- [ ] **N10 — Special effect-ID rerouting.**
  [0065](#patch-0065) special-cases effect `0x704` to spawn `0x407` on a fighter
  joint and return early. Treat it as a native routing workaround until the
  original bank/dispatch behavior is reproduced. Keep out of a type-fix PR.

- [ ] **N11 — Bootstrap state, owner substitution and restored lifecycle.**
  Frame-110 camera/state restoration, fixed respawn markers, copied player/GM
  owners and selected result/HUD services occur throughout 0068–0089/20xx.
  [1151](#patch-1151) also changes a HUD GM-owner accessor.
  [3507](#patch-3507)–[3509](#patch-3509) bind natural GameEnd, restore the
  wireframe selector and real respawn path. These are fixes to incomplete port
  providers; use them as evidence leads, not changes to intact original logic.

- [ ] **N12 — Observation APIs and serialized snapshots.**
  [0090](#patch-0090)–[0094](#patch-0094), probes across native slices, and
  result serializers expose native fields/pointers and produce comparison
  records. Keep ctypes/API/export details and guest-byte serialization outside
  the decomp. Add a source accessor only if it serves a real shared interface.

## New or unresolved divergences

- [ ] **W01 — Signed zero has not been resolved as a decomp defect.**
  Main's task log D146 reports recorded knockback Y `+0` versus native `-0`
  at Favorable145 and eight other listed replay stops. It also reports that
  retail `fnmsubs` agrees with native, with a comparison decision pending.
  Preserve that distinction; changing source arithmetic to satisfy the recorder
  is not justified. This audit did not rerun those comparisons.

- [ ] **W02 — Fire Fox deceleration follow-up is separate WIP.**
  [1311](#patch-1311), committed at `7ce9bd72`, changes
  `ftFx_SpecialAirHi_Phys` to explicit fused negative multiply/subtract forms.
  D159 names Hungry4413, port 0, action 356 and self-Y words
  `3f9c14f9`/`3f9c14fa`. The patch file is not selected by that snapshot's
  standard startup list. Review its dedicated controls/results and final
  integration before claiming the discrepancy is fixed; classify with B04.

- [ ] **W03 — Offscreen rule selection in a copied fighter body.**
  [1310](#patch-1310) switches `ftSlippi_Enabled` to
  `ftSlippi_OnlinePhysics` in `src/native/constructor_tail.c`. The whole-source
  Slippi hook already has that distinction. This is a port-copy drift fix,
  linked to the integration's offscreen damage work, not an upstream gameplay fix.

- [ ] **W04 — Keep coverage stops and input delivery failures distinct.**
  Main's task log also retains D1 (historical frame-110 shield geometry) and
  D2 (requested versus recorded controller delivery). Many historical fixes
  merely remove named unsupported-code stops. Neither fixture delivery errors
  nor code not yet ported establish an inaccurate decomp declaration or behavior.

## Before retaining a decomp change

- [ ] Check current upstream and maintainer work for the specific candidate;
  the cached-ref comparisons above are only a starting point.
- [ ] Reproduce the native compile/layout/runtime failure on current source,
  following the value through all producers, consumers, casts and stored fields.
- [ ] For a behavioral claim, record a falsifiable GALE01 Dolphin comparison,
  setup/inputs, contrasting case, observation and static-to-runtime connection.
  Cite existing port reports as existing reports until independently reproduced.
- [ ] Establish a clean target baseline, build from this worktree, and retain
  the expected GALE01 DOL hash and every affected object/section/relocation,
  code/data/function and linked match metric without regression.
- [ ] Test the relevant optimized ARM64 path and plausible type alternatives;
  use `MUST_MATCH` only for truthful representations that require target spelling.
- [ ] Keep each accepted change narrow and state human review as pending until
  it occurs. Keep this fork catalogue, native adapters, generated assets and
  scratch results out of upstream commits.

## Complete patch index

Each row is a patch artifact, not an independent bug or an implementation task.
`B` = selected baseline; `N` = selected natural-start/Slippi addition;
`U` = present but unselected; `—` = absent from that snapshot; `adapter` =
the separate old-DAT-core repair. Columns correspond to the exact commits above.
The index preserves the exact patch filenames. Targets are the patched export
paths, so `src/native/*` usually denotes a copied provider rather than a source
file that exists in this decomp. Retrieve each immutable patch from a clone of
[melee-stockfish](https://github.com/itsgrimetime/melee-stockfish) containing the
recorded commits, using the commit for the desired snapshot column:

```sh
git -C /path/to/melee-stockfish show <recorded-commit>:native/patches/<patch-path>
```

The Slippi rows include the `slippi/` directory in their patch path. The separate
DAT repair uses `native/source/fd_dat_adapter/core-repair.patch` instead.
The three audited commits were not available on Stockfish's GitHub remote when
this catalogue was prepared for the fork; these references require a clone that
contains those local commits.

### 0000–0034: base types, animation, allocation and model loaders

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-0001"></a>`0001-host-types-and-layout.patch` | B | B | B | `src/placeholder.h`, `src/MSL/stddef.h`, `extern/dolphin/include/dolphin/types.h`, `extern/dolphin/include/dolphin/os/OSRtc.h`, `src/sysdolphin/baselib/objalloc.h`, `src/sysdolphin/baselib/id.h`, `src/sysdolphin/baselib/aobj.h`, `src/sysdolphin/baselib/particle.h`, `src/sysdolphin/baselib/jobj.h`, `src/melee/ft/types.h`, `src/melee/mp/mplib.c`, `src/melee/gm/types.h` |
| <a id="patch-0002"></a>`0002-random.patch` | B | B | B | `src/native/random.c` |
| <a id="patch-0003"></a>`0003-fobj.patch` | B | B | B | `src/sysdolphin/baselib/fobj.c` |
| <a id="patch-0004"></a>`0004-spline.patch` | B | B | B | `src/sysdolphin/baselib/spline.c` |
| <a id="patch-0005"></a>`0005-objalloc.patch` | B | B | B | `src/sysdolphin/baselib/objalloc.c` |
| <a id="patch-0006"></a>`0006-gmmain.patch` | B | B | B | `src/melee/gm/gmmain.c` |
| <a id="patch-0007"></a>`0007-animation.patch` | B | B | B | `src/native/animation.c` |
| <a id="patch-0008"></a>`0008-archive-probe.patch` | B | B | B | `src/native/archive_probe.c` |
| <a id="patch-0009"></a>`0009-jobj.patch` | B | B | B | `src/sysdolphin/baselib/jobj.c` |
| <a id="patch-0010"></a>`0010-id.patch` | B | B | B | `src/sysdolphin/baselib/id.c` |
| <a id="patch-0011"></a>`0011-aobj.patch` | B | B | B | `src/sysdolphin/baselib/aobj.c` |
| <a id="patch-0012"></a>`0012-mtx.patch` | B | B | B | `src/sysdolphin/baselib/mtx.c` |
| <a id="patch-0013"></a>`0013-trigf.patch` | B | B | B | `src/MSL/trigf.c` |
| <a id="patch-0014"></a>`0014-joints.patch` | B | B | B | `src/native/joints.c` |
| <a id="patch-0015"></a>`0015-premodel.patch` | B | B | B | `src/native/premodel.c` |
| <a id="patch-0016"></a>`0016-effects.patch` | B | B | B | `src/native/effects.c` |
| <a id="patch-0017"></a>`0017-costume.patch` | B | B | B | `src/native/costume.c` |
| <a id="patch-0018"></a>`0018-attachment.patch` | B | B | B | `src/native/attachment.c` |
| <a id="patch-0019"></a>`0019-bank.patch` | B | B | B | `src/native/bank.c` |
| <a id="patch-0020"></a>`0020-parts.patch` | B | B | B | `src/native/parts.c` |
| <a id="patch-0021"></a>`0021-class.patch` | B | B | B | `src/sysdolphin/baselib/class.c` |
| <a id="patch-0022"></a>`0022-joint-boundary.patch` | B | B | B | `src/native/joint_boundary.c` |
| <a id="patch-0023"></a>`0023-dobj.patch` | B | B | B | `src/sysdolphin/baselib/dobj.c` |
| <a id="patch-0024"></a>`0024-pobj.patch` | B | B | B | `src/sysdolphin/baselib/pobj.c` |
| <a id="patch-0025"></a>`0025-mobj.patch` | B | B | B | `src/sysdolphin/baselib/mobj.c` |
| <a id="patch-0026"></a>`0026-tobj.patch` | B | B | B | `src/sysdolphin/baselib/tobj.c` |
| <a id="patch-0027"></a>`0027-texp.patch` | B | B | B | `src/sysdolphin/baselib/texp.c` |
| <a id="patch-0028"></a>`0028-texpdag.patch` | B | B | B | `src/sysdolphin/baselib/texpdag.c` |
| <a id="patch-0029"></a>`0029-tev.patch` | B | B | B | `src/sysdolphin/baselib/tev.c` |
| <a id="patch-0030"></a>`0030-full-layout.patch` | B | B | B | `src/native/full_layout.c` |
| <a id="patch-0031"></a>`0031-full-objects.patch` | B | B | B | `src/native/full_objects.c` |
| <a id="patch-0032"></a>`0032-setup.patch` | B | B | B | `src/native/setup.c` |
| <a id="patch-0033"></a>`0033-costume-animation.patch` | B | B | B | `src/native/costume_animation.c` |
| <a id="patch-0034"></a>`0034-metal.patch` | B | B | B | `src/native/metal.c` |

### 0035–0068: fighter, camera, collision and command code

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-0035"></a>`0035-constructor-fox-state.patch` | B | B | B | `src/native/constructor_fox_state.c` |
| <a id="patch-0036"></a>`0036-constructor-stage.patch` | B | B | B | `src/native/constructor_stage.c` |
| <a id="patch-0037"></a>`0037-constructor-camera-quake.patch` | B | B | B | `src/native/constructor_camera_quake.c` |
| <a id="patch-0038"></a>`0038-constructor-cobj.patch` | B | B | B | `src/sysdolphin/baselib/cobj.c` |
| <a id="patch-0039"></a>`0039-constructor-camera-lookat.patch` | B | B | B | `src/native/constructor_camera_lookat.c` |
| <a id="patch-0040"></a>`0040-constructor-camera-gxproject.patch` | B | B | B | `src/native/constructor_camera_gxproject.c` |
| <a id="patch-0041"></a>`0041-constructor-camera-mtxsr.patch` | B | B | B | `src/native/constructor_camera_mtxsr.c` |
| <a id="patch-0042"></a>`0042-particle.patch` | B | B | B | `src/sysdolphin/baselib/particle.c` |
| <a id="patch-0043"></a>`0043-generator.patch` | B | B | B | `src/sysdolphin/baselib/generator.c` |
| <a id="patch-0044"></a>`0044-constructor-ftaction.patch` | B | B | B | `src/melee/ft/ftaction.c` |
| <a id="patch-0045"></a>`0045-ftanim.patch` | B | B | B | `src/melee/ft/ftanim.c` |
| <a id="patch-0046"></a>`0046-constructor-ftcolanim.patch` | B | B | B | `src/melee/ft/ftcolanim.c` |
| <a id="patch-0047"></a>`0047-constructor-ftcoll.patch` | B | B | B | `src/melee/ft/ftcoll.c` |
| <a id="patch-0048"></a>`0048-constructor-lbtrigf.patch` | B | B | B | `src/melee/lb/lbtrigf.c` |
| <a id="patch-0049"></a>`0049-ftcommon.patch` | B | B | B | `src/melee/ft/ftcommon.c` |
| <a id="patch-0050"></a>`0050-constructor-ft-08A1.patch` | B | B | B | `src/melee/ft/ft_08A1.c` |
| <a id="patch-0051"></a>`0051-ftfoxspeciallw.patch` | B | B | B | `src/melee/ft/kinds/ftFox/ftfoxspeciallw.c` |
| <a id="patch-0052"></a>`0052-constructor-ft-0D31.patch` | B | B | B | `src/melee/ft/ft_0D31.c` |
| <a id="patch-0053"></a>`0053-constructor-ft-0D4D.patch` | B | B | B | `src/melee/ft/ft_0D4D.c` |
| <a id="patch-0054"></a>`0054-constructor-ftswing.patch` | B | B | B | `src/native/constructor_ftswing.c` |
| <a id="patch-0055"></a>`0055-constructor-mpcoll.patch` | B | B | B | `src/melee/mp/mpcoll.c` |
| <a id="patch-0056"></a>`0056-lbvector.patch` | B | B | B | `src/melee/lb/lbvector.c` |
| <a id="patch-0057"></a>`0057-lbcommand.patch` | B | B | B | `src/melee/lb/lbcommand.c` |
| <a id="patch-0058"></a>`0058-constructor-lb-00F9.patch` | B | B | B | `src/melee/lb/lb_00F9.c` |
| <a id="patch-0059"></a>`0059-constructor-lb-020A.patch` | B | B | B | `src/melee/lb/lb_020A.c` |
| <a id="patch-0060"></a>`0060-lb-00B0.patch` | B | B | B | `src/melee/lb/lb_00B0.c` |
| <a id="patch-0061"></a>`0061-constructor-itanimlist.patch` | B | B | B | `src/melee/it/itanimlist.c` |
| <a id="patch-0062"></a>`0062-item-support.patch` | B | B | B | `src/native/item_support.c` |
| <a id="patch-0063"></a>`0063-constructor-ftCo-Guard.patch` | B | B | B | `src/melee/ft/kinds/ftCommon/ftCo_Guard.c` |
| <a id="patch-0064"></a>`0064-ftCo-CaptureWait.patch` | B | B | B | `src/melee/ft/kinds/ftCommon/ftCo_CaptureWait.c` |
| <a id="patch-0065"></a>`0065-ftCo-09F7.patch` | B | B | B | `src/melee/ft/kinds/ftCommon/ftCo_09F7.c` |
| <a id="patch-0066"></a>`0066-constructor-ftCo-Damage.patch` | B | B | B | `src/melee/ft/kinds/ftCommon/ftCo_Damage.c` |
| <a id="patch-0067"></a>`0067-quatlib.patch` | B | B | B | `src/sysdolphin/baselib/quatlib.c` |
| <a id="patch-0068"></a>`0068-constructor-tail.patch` | B | B | B | `src/native/constructor_tail.c` |

### 0069–0094: match, stock loss, results and observers

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-0069"></a>`0069-match-clock.patch` | B | B | B | `src/native/match_clock.c` |
| <a id="patch-0070"></a>`0070-match-status.patch` | B | B | B | `src/native/match_status.c` |
| <a id="patch-0071"></a>`0071-stock-loss-hud.patch` | B | B | B | `src/native/stock_loss_hud.c` |
| <a id="patch-0072"></a>`0072-stock-loss-support.patch` | B | B | B | `src/native/stock_loss_support.c` |
| <a id="patch-0073"></a>`0073-stock-loss-mode.patch` | B | B | B | `src/native/stock_loss_mode.c` |
| <a id="patch-0074"></a>`0074-stock-loss-player.patch` | B | B | B | `src/native/stock_loss_player.c` |
| <a id="patch-0075"></a>`0075-particle-boundary.patch` | B | B | B | `src/native/particle_boundary.c` |
| <a id="patch-0076"></a>`0076-stock-loss-terminal.patch` | B | B | B | `src/native/stock_loss_terminal.c` |
| <a id="patch-0077"></a>`0077-result-statistics.patch` | B | B | B | `src/native/result_statistics.c` |
| <a id="patch-0078"></a>`0078-result-bonus-producer.patch` | B | B | B | `src/native/result_bonus_producer.c` |
| <a id="patch-0079"></a>`0079-result-bonus-decision.patch` | B | B | B | `src/native/result_bonus_decision.c` |
| <a id="patch-0080"></a>`0080-result-attack-reset.patch` | B | B | B | `src/native/result_attack_reset.c` |
| <a id="patch-0081"></a>`0081-ft-0892.patch` | B | B | B | `src/melee/ft/ft_0892.c` |
| <a id="patch-0082"></a>`0082-result-controller.patch` | B | B | B | `src/native/result_controller.c` |
| <a id="patch-0083"></a>`0083-result-magnifier.patch` | B | B | B | `src/native/result_magnifier.c` |
| <a id="patch-0084"></a>`0084-result-persistent.patch` | B | B | B | `src/native/result_persistent.c` |
| <a id="patch-0085"></a>`0085-result-character-map.patch` | B | B | B | `src/native/result_character_map.c` |
| <a id="patch-0086"></a>`0086-result-trick-reader.patch` | B | B | B | `src/native/result_trick_reader.c` |
| <a id="patch-0087"></a>`0087-result-arrow-audio.patch` | B | B | B | `src/native/result_arrow_audio.c` |
| <a id="patch-0088"></a>`0088-kernel.patch` | B | B | B | `src/native/kernel.c` |
| <a id="patch-0089"></a>`0089-constructor-camera.patch` | B | B | B | `src/melee/cm/camera.c` |
| <a id="patch-0090"></a>`0090-smash-attr-observer.patch` | B | B | B | `src/native/smash_attr_observer.c` |
| <a id="patch-0091"></a>`0091-aerial-command-observation-v1.patch` | B | B | B | `src/native/aerial_command_observation_v1.c` |
| <a id="patch-0092"></a>`0092-ground-input-observation-v1.patch` | B | B | B | `src/native/ground_input_observation_v1.c` |
| <a id="patch-0093"></a>`0093-walk-operand-observation-v1.patch` | B | B | B | `src/native/walk_operand_observation_v1.c` |
| <a id="patch-0094"></a>`0094-capture-observer.patch` | B | B | B | `src/native/capture_observer.c` |

### 1000–1142: host services and selected startup/output providers

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-1000"></a>`1000-host.patch` | B | B | B | `src/native/host.c` |
| <a id="patch-1001"></a>`1001-premodel-host.patch` | B | B | B | `src/native/premodel_host.c` |
| <a id="patch-1002"></a>`1002-effect-host.patch` | B | B | B | `src/native/effect_host.c` |
| <a id="patch-1003"></a>`1003-constructor-unported.patch` | B | B | B | `src/native/constructor_unported.c` |
| <a id="patch-1110"></a>`1110-fighter-startup-data.patch` | N | N | N | `src/native/startup_fighter_data.c` |
| <a id="patch-1111"></a>`1111-fighter-startup-callbacks.patch` | N | N | N | `src/native/startup_fighter_callbacks.c` |
| <a id="patch-1112"></a>`1112-player-attack-instance-reset.patch` | N | N | N | `src/native/constructor_tail.c` |
| <a id="patch-1113"></a>`1113-startup-audio-bank-boundary.patch` | N | — | — | `src/native/startup_audio.c` |
| <a id="patch-1114"></a>`1114-reached-fighter-shadow-setup.patch` | N | — | — | `src/native/startup_fighter_callbacks.c` |
| <a id="patch-1115"></a>`1115-reached-fighter-input-reset.patch` | N | N | N | `src/native/startup_fighter_callbacks.c` |
| <a id="patch-1116"></a>`1116-reached-crowd-startup.patch` | N | N | N | `src/native/startup_crowd.c` |
| <a id="patch-1117"></a>`1117-reached-background-flash-startup.patch` | N | — | — | `src/native/startup_bgflash.c` |
| <a id="patch-1118"></a>`1118-reached-music-output-boundary.patch` | N | — | — | `src/native/startup_audio.c` |
| <a id="patch-1119"></a>`1119-reached-per-frame-audio-boundary.patch` | N | — | — | `src/native/startup_audio.c` |
| <a id="patch-1120"></a>`1120-reached-background-flash-callback.patch` | N | — | — | `src/native/startup_bgflash.c` |
| <a id="patch-1121"></a>`1121-reached-crowd-gasp-counter.patch` | N | N | N | `src/native/startup_crowd.c` |
| <a id="patch-1122"></a>`1122-reached-crowd-fighter-proximity.patch` | N | N | N | `src/native/startup_crowd.c` |
| <a id="patch-1123"></a>`1123-reached-shadow-render-prefix.patch` | N | N | N | `src/native/startup_fighter_callbacks.c` |
| <a id="patch-1124"></a>`1124-reached-common-fighter-light-owner.patch` | N | N | N | `src/native/startup_fighter_data.c` |
| <a id="patch-1125"></a>`1125-reached-model-visibility.patch` | N | N | N | `src/native/startup_fighter_callbacks.c` |
| <a id="patch-1126"></a>`1126-reached-entry-sfx-request.patch` | N | — | — | `src/native/startup_audio.c` |
| <a id="patch-1127"></a>`1127-reached-blue-fox-costume.patch` | N | N | N | `src/native/costume.c` |
| <a id="patch-1130"></a>`1130-reached-landing-rumble-output.patch` | N | — | — | `src/melee/lb/lb_013B.c`, `src/native/startup_rumble.c` |
| <a id="patch-1131"></a>`1131-reached-command-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1132"></a>`1132-reached-special-loop-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1133"></a>`1133-reached-movement-shine-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1134"></a>`1134-reached-airn-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1135"></a>`1135-reached-damage-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1136"></a>`1136-reached-native-stale-weight-owner.patch` | N | N | N | `src/native/premodel.c` |
| <a id="patch-1137"></a>`1137-reached-animation-command-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1138"></a>`1138-reached-catch-wait-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1139"></a>`1139-reached-flowery-damage-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1140"></a>`1140-reached-hit-processing-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1141"></a>`1141-reached-saved-command-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |
| <a id="patch-1142"></a>`1142-reached-unfortunate-hit-rumble-output.patch` | N | — | — | `src/native/startup_rumble.c` |

### 1150–1311: output replacements, startup routing and whole Fox commands

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-1150"></a>`1150-output-only-noops.patch` | — | N | N | `src/melee/lb/lb_013B.c`, `src/sysdolphin/baselib/rumble.c`, `src/native/startup_fighter_callbacks.c`, `src/native/startup_audio.c`, `src/native/startup_rumble.c`, `src/native/startup_bgflash.c`, `src/native/startup_ground_lights.c` |
| <a id="patch-1151"></a>`1151-bulk-hud-gameplay.patch` | — | N | N | `src/melee/if/ifstatus.c`, `src/melee/if/if_2F72.c` |
| <a id="patch-1200"></a>`1200-startup-slippi-include-context.patch` | N | N | N | `src/melee/ft/kinds/ftCommon/ftCo_Guard.c`, `src/melee/ft/kinds/ftCommon/ftCo_Damage.c`, `src/melee/ft/ft_0D31.c` |
| <a id="patch-1202"></a>`1202-startup-host-layout-checks.patch` | N | N | N | `src/melee/ty/types.h` |
| <a id="patch-1203"></a>`1203-startup-original-provider-selection.patch` | N | N | N | `src/native/constructor_unported.c`, `src/native/constructor_tail.c`, `src/native/premodel.c` |
| <a id="patch-1204"></a>`1204-startup-player-aliases.patch` | N | N | N | `src/native/stock_loss_player.c` |
| <a id="patch-1205"></a>`1205-startup-data-and-slippi-bridge.patch` | N | N | N | `src/native/premodel.c`, `src/native/constructor_tail.c` |
| <a id="patch-1206"></a>`1206-startup-refraction-and-player-selection.patch` | N | N | N | `src/native/constructor_unported.c`, `src/native/attachment.c`, `src/native/stock_loss_player.c` |
| <a id="patch-1207"></a>`1207-startup-typed-archive-dispatch.patch` | N | N | N | `src/native/premodel.c`, `src/sysdolphin/baselib/archive.c` |
| <a id="patch-1208"></a>`1208-startup-device-provider-selection.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1209"></a>`1209-startup-final-provider-selection.patch` | N | N | N | `src/native/match_clock.c`, `src/native/stock_loss_player.c` |
| <a id="patch-1210"></a>`1210-startup-camera-provider-selection.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1211"></a>`1211-startup-native-cache-coherence.patch` | N | N | N | `src/native/full_objects.c` |
| <a id="patch-1212"></a>`1212-startup-fresh-effect-archives.patch` | N | N | N | `src/native/premodel.c` |
| <a id="patch-1213"></a>`1213-startup-post-frame-recording.patch` | N | N | N | `src/native/constructor_tail.c` |
| <a id="patch-1214"></a>`1214-startup-particle-count-layout.patch` | N | N | N | `src/sysdolphin/baselib/particle.c`, `src/sysdolphin/baselib/particle.h` |
| <a id="patch-1215"></a>`1215-startup-scene-mode-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1216"></a>`1216-startup-item-rule-query.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1217"></a>`1217-startup-frame-start-recording.patch` | N | N | N | `src/native/startup_scene.c` |
| <a id="patch-1218"></a>`1218-startup-ground-scale-query.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1219"></a>`1219-startup-collision-island-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1220"></a>`1220-startup-ground-material-layout.patch` | N | N | N | `src/melee/gr/types.h` |
| <a id="patch-1221"></a>`1221-startup-ground-material-provider.patch` | N | N | N | `src/native/startup_stage_boundaries.c` |
| <a id="patch-1222"></a>`1222-startup-collision-island-update-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1223"></a>`1223-startup-ground-locator-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1224"></a>`1224-startup-common-material-data.patch` | N | N | N | `src/native/premodel.c` |
| <a id="patch-1225"></a>`1225-startup-original-costume-request.patch` | N | N | N | `src/native/costume.c` |
| <a id="patch-1226"></a>`1226-startup-original-animation-bank-request.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1227"></a>`1227-startup-fighter-input-reset-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1228"></a>`1228-startup-existing-timer-reset.patch` | N | N | N | `src/native/stock_loss_terminal.c` |
| <a id="patch-1229"></a>`1229-startup-unlock-query-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1230"></a>`1230-startup-natural-kernel-input.patch` | N | N | N | `src/native/kernel.c` |
| <a id="patch-1231"></a>`1231-startup-original-loop-flags.patch` | N | N | N | `src/native/constructor_tail.c` |
| <a id="patch-1232"></a>`1232-startup-corpus-costume-archives.patch` | N | N | N | `src/native/costume.c` |
| <a id="patch-1233"></a>`1233-startup-original-entry-action-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1234"></a>`1234-startup-original-shadow-render-provider.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1235"></a>`1235-startup-stage-callback-flag-layout.patch` | N | N | N | `src/melee/gr/types.h` |
| <a id="patch-1236"></a>`1236-startup-original-robj-request-provider.patch` | N | N | N | `src/native/constructor_unported.c`, `src/native/joint_boundary.c` |
| <a id="patch-1237"></a>`1237-startup-common-light-selector-provider.patch` | N | N | N | `src/native/startup_fighter_data.c` |
| <a id="patch-1238"></a>`1238-startup-native-entry-reset-command.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1239"></a>`1239-startup-original-entry-start-callbacks.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1240"></a>`1240-startup-native-entry-motion-cache.patch` | N | N | N | `src/native/constructor_tail.c` |
| <a id="patch-1241"></a>`1241-startup-original-entry-effect-queue.patch` | N | N | N | `src/native/constructor_tail.c` |
| <a id="patch-1242"></a>`1242-startup-original-entry-end-callbacks.patch` | N | N | N | `src/native/constructor_unported.c` |
| <a id="patch-1243"></a>`1243-startup-native-fall-reset-command.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1244"></a>`1244-startup-native-landing-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1245"></a>`1245-startup-native-walk-slow-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1246"></a>`1246-startup-native-knee-bend-reset.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1247"></a>`1247-startup-reached-command-streams.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1248"></a>`1248-startup-special-n-loop-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1249"></a>`1249-startup-reached-movement-special-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1250"></a>`1250-startup-air-loop-aerial-commands.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1251"></a>`1251-startup-native-landing-fall-special-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1252"></a>`1252-startup-fox-blaster-effect-pointers.patch` | N | N | N | `src/melee/it/itCharItems.h` |
| <a id="patch-1253"></a>`1253-startup-native-damage-air2-reset.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1254"></a>`1254-startup-reached-hit-landing-effect-routing.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-1255"></a>`1255-startup-native-special-n-end-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1256"></a>`1256-startup-native-run-brake-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1257"></a>`1257-startup-native-ottotto-dair-catch-commands.patch` | N | N | N | `src/native/constructor_tail.c`, `src/native/bank.c` |
| <a id="patch-1258"></a>`1258-startup-reached-guard-run-shine-routing.patch` | N | N | N | `src/native/startup_entry_effect.c`, `src/native/constructor_tail.c` |
| <a id="patch-1259"></a>`1259-startup-reached-shine-run-brake-routing.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-1260"></a>`1260-startup-native-reached-transition-commands.patch` | N | N | N | `src/native/bank.c`, `src/native/constructor_tail.c` |
| <a id="patch-1261"></a>`1261-startup-native-d2-side-b-command.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1262"></a>`1262-startup-native-followup-commands.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1263"></a>`1263-startup-reached-loop-collision-teardown-routing.patch` | N | N | N | `src/native/startup_entry_effect.c`, `src/native/constructor_tail.c` |
| <a id="patch-1264"></a>`1264-startup-native-reached-attack-commands.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1265"></a>`1265-startup-reached-attached-catch-effect-routing.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-1266"></a>`1266-startup-native-reached-continuation-commands.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1267"></a>`1267-startup-native-guard-damage-command.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1268"></a>`1268-startup-native-hungry-damage-n2-reset.patch` | N | N | N | `src/native/bank.c`, `src/native/constructor_tail.c` |
| <a id="patch-1269"></a>`1269-startup-native-grab-air-loop-commands.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1270"></a>`1270-startup-native-capture-wait-command.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1271"></a>`1271-startup-reached-guard-damage-effect-routing.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-1272"></a>`1272-startup-native-escape-n-commands.patch` | N | N | N | `src/native/bank.c`, `src/native/constructor_tail.c` |
| <a id="patch-1273"></a>`1273-startup-native-reached-action-commands.patch` | N | N | N | `src/native/bank.c`, `src/native/constructor_tail.c` |
| <a id="patch-1274"></a>`1274-startup-reached-hit-colour17-routing.patch` | N | U | U | `src/melee/ft/ftcolanim.c` |
| <a id="patch-1275"></a>`1275-startup-native-down-damage-commands.patch` | N | N | N | `src/native/bank.c` |
| <a id="patch-1276"></a>`1276-startup-native-throw-victim-commands.patch` | — | N | N | `src/native/bank.c` |
| <a id="patch-1277"></a>`1277-startup-reached-down-bound-effect-routing.patch` | — | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-1278"></a>`1278-startup-native-special-s-commands.patch` | — | N | N | `src/native/bank.c` |
| <a id="patch-1279"></a>`1279-startup-native-smash-guard-landing-commands.patch` | — | N | N | `src/native/bank.c` |
| <a id="patch-1300"></a>`1300-bulk-fox-command-cell-layout.patch` | — | N | N | `src/melee/ft/ftaction.c` |
| <a id="patch-1301"></a>`1301-bulk-fighter-colour-unit.patch` | — | N | N | `src/native/bulk_fox_colours_ftcolanim.c` |
| <a id="patch-1302"></a>`1302-bulk-fighter-colour-interpreter.patch` | — | N | N | `src/native/bulk_fox_colours_lb.c` |
| <a id="patch-1310"></a>`1310-hungry-console-offscreen-selector.patch` | — | N | — | `src/native/constructor_tail.c` |
| <a id="patch-1311"></a>`1311-hungry-firefox-fused-deceleration.patch` | — | — | U | `src/melee/ft/kinds/ftFox/ftfoxspecialhi.c` |

### 2000–2064: scene, stage and natural fighter entry

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-2000"></a>`2000-vs-scene-entry.patch` | N | N | N | `src/native/startup_scene.c` |
| <a id="patch-2001"></a>`2001-original-fighter-create.patch` | N | N | N | `src/native/startup_fighter.c` |
| <a id="patch-2002"></a>`2002-retail-scene-services.patch` | N | N | N | `src/native/startup_scene_services.c` |
| <a id="patch-2003"></a>`2003-fd-stage-entry.patch` | N | N | N | `src/native/startup_stage.c` |
| <a id="patch-2004"></a>`2004-refraction-host-global.patch` | N | N | N | `src/melee/lb/lbrefract.c` |
| <a id="patch-2005"></a>`2005-fd-ground-load.patch` | N | N | N | `src/native/startup_ground.c` |
| <a id="patch-2006"></a>`2006-stage-material-descriptors.patch` | N | N | N | `src/melee/gr/grdatfiles.c` |
| <a id="patch-2007"></a>`2007-stage-startup-boundaries.patch` | N | N | N | `src/native/startup_stage_boundaries.c` |
| <a id="patch-2008"></a>`2008-native-startup-bus-clock.patch` | N | N | N | `extern/dolphin/include/dolphin/os.h` |
| <a id="patch-2009"></a>`2009-original-camera-loader.patch` | N | N | N | `src/native/startup_camera.c` |
| <a id="patch-2010"></a>`2010-original-mode-query.patch` | N | N | N | `src/native/startup_scene_services.c` |
| <a id="patch-2011"></a>`2011-original-collision-islands.patch` | N | N | N | `src/native/startup_collision_islands.c` |
| <a id="patch-2012"></a>`2012-fd-fog-display-boundary.patch` | N | N | N | `src/native/startup_stage_boundaries.c` |
| <a id="patch-2013"></a>`2013-fd-light-display-boundary.patch` | N | N | N | `src/native/startup_stage_boundaries.c` |
| <a id="patch-2014"></a>`2014-original-fd-stage-object.patch` | N | N | N | `src/native/startup_ground_objects.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2015"></a>`2015-original-fd-animation-setup.patch` | N | N | N | `src/native/startup_stage_boundaries.c`, `src/native/startup_ground_animation.c` |
| <a id="patch-2016"></a>`2016-original-fd-animation-flags.patch` | N | N | N | `src/native/startup_ground_animation.c`, `src/native/startup_ground_animation_flags.c` |
| <a id="patch-2017"></a>`2017-original-fd-collision-binding.patch` | N | N | N | `src/native/startup_stage.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2018"></a>`2018-original-collision-island-update.patch` | N | N | N | `src/native/startup_collision_islands.c` |
| <a id="patch-2019"></a>`2019-original-fd-material-class.patch` | N | N | N | `src/native/startup_ground_material_class.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2020"></a>`2020-original-fd-animation-selection.patch` | N | N | N | `src/native/startup_ground_animation_select.c`, `src/native/startup_stage_boundaries.c`, `src/native/startup_ground_animation_flags.c` |
| <a id="patch-2021"></a>`2021-original-fd-single-joint-animation.patch` | N | N | N | `src/native/startup_ground_animation_select.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2022"></a>`2022-original-fd-animation-clear-loop.patch` | N | N | N | `src/native/startup_ground_animation_select.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2023"></a>`2023-reached-fd-indexed-animation-view.patch` | N | N | N | `src/native/startup_ground_animation_select.c` |
| <a id="patch-2024"></a>`2024-original-fd-startup-indexed-views.patch` | N | N | N | `src/native/startup_ground_animation_select.c` |
| <a id="patch-2025"></a>`2025-original-ground-event-list.patch` | N | N | N | `src/native/startup_stage_boundaries.c` |
| <a id="patch-2026"></a>`2026-original-fd-camera-range.patch` | N | N | N | `src/native/startup_stage_boundaries.c`, `src/native/startup_ground_camera.c` |
| <a id="patch-2027"></a>`2027-original-fd-blast-range.patch` | N | N | N | `src/native/startup_stage_boundaries.c`, `src/native/startup_ground_camera.c` |
| <a id="patch-2028"></a>`2028-fd-pause-hint-display-boundary.patch` | N | N | N | `src/native/startup_pause.c` |
| <a id="patch-2029"></a>`2029-original-hud-startup.patch` | N | N | N | `src/native/startup_hud.c` |
| <a id="patch-2030"></a>`2030-slippi-all-character-unlock-query.patch` | N | N | N | `src/native/startup_music.c` |
| <a id="patch-2031"></a>`2031-original-vs-scene-frame.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c` |
| <a id="patch-2032"></a>`2032-original-vs-disabled-cpu-spawn.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c`, `src/native/startup_scene_services.c` |
| <a id="patch-2033"></a>`2033-original-fighter-match-countdown.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c`, `src/native/startup_scene_services.c` |
| <a id="patch-2034"></a>`2034-original-match-outcome-resolver.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c` |
| <a id="patch-2035"></a>`2035-original-ffa-outcome-reader.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c` |
| <a id="patch-2036"></a>`2036-original-stage-outcome-flags.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2037"></a>`2037-original-vs-pause-dispatcher.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c` |
| <a id="patch-2038"></a>`2038-original-vs-singles-stock-sharing-return.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c` |
| <a id="patch-2039"></a>`2039-original-ground-material-overlay-update.patch` | N | N | N | `src/native/startup_stage_boundaries.c` |
| <a id="patch-2040"></a>`2040-original-natural-fighter-entry-callbacks.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2041"></a>`2041-original-ground-collision-joint-update.patch` | N | N | N | `src/native/startup_stage.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2042"></a>`2042-original-fd-stage-light-owner.patch` | N | N | N | `src/native/startup_stage.c`; **changed version** |
| <a id="patch-2043"></a>`2043-original-common-stage-light-selector.patch` | N | — | — | `src/native/startup_ground_lights.c` |
| <a id="patch-2044"></a>`2044-original-common-light-position-interest-scaling.patch` | N | — | — | `src/native/startup_ground_lights.c` |
| <a id="patch-2045"></a>`2045-original-natural-entry-start-transition.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2046"></a>`2046-original-entry-sfx-service-binding.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2047"></a>`2047-original-entry-start-iasa.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2048"></a>`2048-original-entry-start-physics.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2049"></a>`2049-original-entry-start-collision.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2050"></a>`2050-original-entry-accessory-callback.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2051"></a>`2051-original-entry-start-animation.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2052"></a>`2052-original-entry-end-transition.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2053"></a>`2053-original-entry-end-iasa.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2054"></a>`2054-original-entry-end-physics.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2055"></a>`2055-original-entry-end-collision.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2056"></a>`2056-original-entry-end-accessory.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2057"></a>`2057-original-entry-end-animation.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2058"></a>`2058-original-entry-end-exit-binding.patch` | N | N | N | `src/native/startup_fighter_entry.c` |
| <a id="patch-2059"></a>`2059-original-natural-stage-start.patch` | N | N | N | `src/native/startup_stage.c`, `src/native/startup_ground.c`, `src/native/match_clock.c` |
| <a id="patch-2060"></a>`2060-original-fd-stage-generator-start.patch` | N | N | N | `src/native/match_clock.c`, `src/native/startup_stage_boundaries.c` |
| <a id="patch-2061"></a>`2061-original-fd-ground-start-callback.patch` | N | N | N | `src/native/startup_ground.c` |
| <a id="patch-2062"></a>`2062-original-fd-generator-frame.patch` | N | N | N | `src/native/match_clock.c` |
| <a id="patch-2063"></a>`2063-natural-fox-special-dispatch.patch` | N | N | N | `src/native/startup_fighter.c` |
| <a id="patch-2064"></a>`2064-original-vs-pauser-query.patch` | N | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c`, `src/native/stock_loss_mode.c`, `src/native/startup_scene_pauser.c` |

### 3000–3133: items, effects and particles

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-3000"></a>`3000-items-typed-data-load.patch` | N | N | N | `src/melee/it/iteffect.c` |
| <a id="patch-3001"></a>`3001-items-off-spawner.patch` | N | N | N | `src/melee/it/itspawn.c` |
| <a id="patch-3002"></a>`3002-items-fox-domain.patch` | N | N | N | `src/melee/it/item.c`, `src/melee/it/it_26B1.c` |
| <a id="patch-3100"></a>`3100-original-effects-initialization.patch` | N | N | N | `src/native/startup_effects.c` |
| <a id="patch-3101"></a>`3101-common-effects-bank-loader.patch` | N | N | N | `src/native/startup_effect_banks.c`, `src/native/effects.c` |
| <a id="patch-3102"></a>`3102-fd-particle-bank.patch` | N | N | N | `src/native/startup_effect_banks.c` |
| <a id="patch-3103"></a>`3103-fd-random-article-registration.patch` | N | N | N | `src/melee/it/it_26B1.c` |
| <a id="patch-3104"></a>`3104-fd-bank30-registration.patch` | N | N | N | `src/native/startup_effect_banks.c` |
| <a id="patch-3105"></a>`3105-original-stage-particle-callback.patch` | N | N | N | `src/native/startup_stage_particles.c` |
| <a id="patch-3106"></a>`3106-original-robj-animation-request.patch` | N | N | N | `src/native/startup_robj_request.c` |
| <a id="patch-3107"></a>`3107-entry-colour-animation.patch` | N | N | N | `src/melee/ft/ftcolanim.c` |
| <a id="patch-3108"></a>`3108-original-entry-effect.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-3109"></a>`3109-original-landing-effect.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-3110"></a>`3110-original-dash-jump-effects.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-3111"></a>`3111-original-specialn-loop-effect.patch` | N | N | N | `src/native/startup_entry_effect.c` |
| <a id="patch-3112"></a>`3112-original-fox-shot-effect.patch` | N | N | N | `src/native/startup_entry_effect.c`, `src/melee/it/kinds/itfoxblaster.c` |
| <a id="patch-3113"></a>`3113-original-hit-spark-effect.patch` | N | N | N | `src/native/startup_hit_effect.c` |
| <a id="patch-3114"></a>`3114-original-landing-fall-special-particle.patch` | N | N | N | `src/native/startup_landing_particle.c` |
| <a id="patch-3115"></a>`3115-original-guard-on-effect.patch` | N | N | N | `src/native/startup_guard_effect.c` |
| <a id="patch-3116"></a>`3116-original-run-facing-particle.patch` | N | N | N | `src/native/startup_run_particle.c` |
| <a id="patch-3117"></a>`3117-original-shine-effect.patch` | N | N | N | `src/native/startup_shine_effect.c` |
| <a id="patch-3118"></a>`3118-original-extra-hit-facing-particle.patch` | N | N | N | `src/native/startup_run_particle.c` |
| <a id="patch-3119"></a>`3119-original-shine-start-particle.patch` | N | N | N | `src/native/startup_shine_particle.c` |
| <a id="patch-3120"></a>`3120-original-fox-shine-character-effect.patch` | N | N | N | `src/native/startup_shine_character_effect.c` |
| <a id="patch-3121"></a>`3121-original-owned-effect-teardown.patch` | N | N | N | `src/native/startup_effect_teardown.c` |
| <a id="patch-3122"></a>`3122-original-fox-shine-loop-effect.patch` | N | N | N | `src/native/startup_shine_loop_effect.c` |
| <a id="patch-3123"></a>`3123-original-electric-collision-particle.patch` | N | N | N | `src/native/startup_collision_effect.c` |
| <a id="patch-3124"></a>`3124-original-attached-collision-particle.patch` | N | N | N | `src/native/startup_attached_particle.c` |
| <a id="patch-3125"></a>`3125-original-aerial-jump-particle.patch` | N | N | N | `src/native/startup_aerial_jump_particle.c` |
| <a id="patch-3126"></a>`3126-original-dash-attack-effect.patch` | N | N | N | `src/native/startup_dash_attack_effect.c` |
| <a id="patch-3127"></a>`3127-original-catch-wait-effect.patch` | N | N | N | `src/native/startup_catch_effect.c` |
| <a id="patch-3128"></a>`3128-original-shield-contact-particle.patch` | N | N | N | `src/native/startup_shield_contact_particle.c` |
| <a id="patch-3129"></a>`3129-original-d2-particle-160.patch` | N | N | N | `src/native/startup_d2_particle160.c` |
| <a id="patch-3130"></a>`3130-original-guard-damage-effect.patch` | N | N | N | `src/native/startup_guard_damage_effect.c` |
| <a id="patch-3131"></a>`3131-original-guard-hold-effect.patch` | N | N | N | `src/native/startup_guard_hold_effect.c` |
| <a id="patch-3132"></a>`3132-original-hit-colour17.patch` | N | U | U | `src/native/startup_hit_colour.c` |
| <a id="patch-3133"></a>`3133-original-down-bound-effect.patch` | — | N | N | `src/native/startup_down_bound_effect.c` |

### 3400–3509: whole-unit native integration

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-3400"></a>`3400-bulk-effects-native-layout.patch` | — | N | N | `src/melee/ef/eflib.c`, `src/melee/ef/efasync.c`, `src/melee/ef/efsync.c`, `src/melee/ef/efalt.c`, `src/sysdolphin/baselib/generator.c`, `src/sysdolphin/baselib/particle.c`, `src/sysdolphin/baselib/particle.h` |
| <a id="patch-3401"></a>`3401-bulk-effects-native-varargs.patch` | — | N | N | `src/melee/ef/efalt.c` |
| <a id="patch-3500"></a>`3500-bulk-fd-animation-unit.patch` | — | N | N | `src/melee/gr/granime.c`, `src/native/startup_stage_boundaries.c`, `src/native/startup_ground_animation.c`, `src/native/startup_ground_animation_select.c` |
| <a id="patch-3501"></a>`3501-bulk-fd-material-unit.patch` | — | N | N | `src/melee/gr/grmaterial.c`, `src/melee/gr/grmaterial.h`, `src/melee/gr/grlast.c`, `src/native/startup_stage_boundaries.c`, `src/melee/gr/granime.c` |
| <a id="patch-3502"></a>`3502-bulk-effect-shared-provider-selection.patch` | — | N | N | `src/native/constructor_tail.c`, `src/native/startup_fighter_data.c`, `src/native/constructor_unported.c` |
| <a id="patch-3503"></a>`3503-bulk-fd-library-unit.patch` | — | N | N | `src/native/startup_stage_boundaries.c`, `src/native/constructor_unported.c`, `src/melee/gr/grlib.c` |
| <a id="patch-3504"></a>`3504-bulk-fox-shared-provider-selection.patch` | — | N | N | `src/native/constructor_tail.c`, `src/native/constructor_unported.c`, `src/native/bank.c`, `src/native/costume.c`, `src/native/result_bonus_producer.c` |
| <a id="patch-3505"></a>`3505-bulk-fd-ground-units.patch` | — | N | N | `src/melee/gr/ground.c`, `src/melee/gr/grdisplay.c`, `src/sysdolphin/baselib/fog.c`, `src/native/startup_ground.c`, `src/native/startup_fighter_data.c`, `src/native/result_magnifier.c`, `src/native/constructor_stage.c`, `src/native/match_clock.c`, `src/native/constructor_unported.c`, `src/native/startup_stage_boundaries.c`, `src/native/constructor_tail.c` |
| <a id="patch-3506"></a>`3506-bulk-fox-colour-binding.patch` | — | N | N | `src/native/premodel.c` |
| <a id="patch-3507"></a>`3507-natural-game-end-binding.patch` | — | N | N | `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c` |
| <a id="patch-3508"></a>`3508-original-wireframe-selector.patch` | — | N | — | `src/native/constructor_tail.c` |
| <a id="patch-3509"></a>`3509-original-natural-respawn.patch` | — | N | — | `src/native/constructor_tail.c`, `src/native/constructor_unported.c`, `src/native/startup_scene.c`, `src/native/startup_scene_frame_boundaries.c`, `src/native/startup_respawn.c` |

### Slippi/UCF modifications

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-slippi-0001"></a>`slippi/0001-ucf84-input-history.patch` | N | N | N | `src/melee/ft/forward.h`, `src/melee/ft/ftslippi.c`, `src/melee/ft/ftslippi.h` |
| <a id="patch-slippi-0002"></a>`slippi/0002-ucf84-gameplay-hooks.patch` | N | N | N | `src/melee/ft/fighter.c`, `src/melee/ft/kinds/ftCommon/ftCo_Damage.c`, `src/melee/ft/kinds/ftCommon/ftCo_DamageFall.c`, `src/melee/ft/kinds/ftCommon/ftCo_Escape.c`, `src/melee/ft/kinds/ftCommon/ftCo_Guard.c`, `src/melee/ft/kinds/ftCommon/ftCo_Pass.c`, `src/melee/ft/kinds/ftCommon/ftCo_SquatRv.c`, `src/melee/ft/kinds/ftCommon/ftCo_Turn.c` |
| <a id="patch-slippi-0003"></a>`slippi/0003-slippi-online-gameplay.patch` | N | N | N | `src/melee/ft/fighter.c`, `src/melee/ft/ft_0D31.c`, `src/melee/ft/ftdrawcommon.c`, `src/melee/ft/kinds/ftCommon/types.h`, `src/melee/gm/gm_16AE.c`, `src/melee/gr/grlast.c`, `src/melee/gr/ground.c` |
| <a id="patch-slippi-0004"></a>`slippi/0004-slippi-recording-l-cancel.patch` | N | N | N | `src/melee/ft/fighter.c`, `src/melee/ft/kinds/ftCommon/ftCo_LandingAir.c`, `src/melee/ft/types.h` |
| <a id="patch-slippi-0005"></a>`slippi/0005-slippi-profile-rules.patch` | N | N | N | `src/melee/ft/fighter.c`, `src/melee/ft/ft_0D31.c`, `src/melee/ft/ftdrawcommon.c`, `src/melee/ft/ftslippi.c`, `src/melee/ft/ftslippi.h`, `src/melee/gr/grlast.c` |
| <a id="patch-slippi-0006"></a>`slippi/0006-slippi-disabled-fd-background.patch` | N | N | N | `src/melee/ft/ftslippi.c`, `src/melee/ft/ftslippi.h`, `src/melee/gr/grlast.c` |

### Separate DAT loader repair

| Patch | Main | Integration | Fire Fox | Export targets |
| --- | --- | --- | --- | --- |
| <a id="patch-core-repair"></a>`core-repair.patch` | adapter | adapter | adapter | `tools/dat-cli/native/src/archive.c` |
