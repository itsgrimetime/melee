# lblanguage documentation trial

Trial date: 2026-09-07 (America/Los_Angeles).
Checkout baseline: `01c5c5a754`, initially clean, detached HEAD.
Target: `src/melee/lb/lblanguage.c` (eight functions).
Representative claim: `lbLang_SetLanguageSetting`.

This is a workflow evaluation and unfinished investigation, not accepted game
documentation. No game-source comments, identifiers, or types were changed.
Human validation: pending; observations below were collected by Codex.

## Why this TU

The TU is small and already named, so it tests whether the skill can improve a
reader's understanding without manufacturing renames. Two families of accessors
have similar names, and the setters have different return types. That provides a
concrete API contract to investigate and a possible menu-based contrasting test.
The many predicate callers make whole-TU semantic coverage substantially larger
than the implementation's line count suggests.

## Claim ledger

| Candidate claim (unvalidated) | Static anchors | Required test | Status |
|---|---|---|---|
| `GetLanguageSetting` reflects distribution selection, distinct from the menu language | `gmmain.c` prints `# Distribution` for this getter and `# Language` for `GetSavedLanguage`; `gmMainLib_8015FBA4` passes 1 or 0 to both setters according to the `/usa.ini` lookup; `mnLanguage_8024BFE0` calls only `SetSavedLanguage` | From a known GALE01 language menu, record both resolved bytes and visible text; select the other language and confirm; repeat in the opposite direction. Establish which storage changes and connect the UI transition to the setter. | Not runtime-validated; no rename or purpose comment accepted |
| `SetLanguageSetting` rejects values outside 0..1 but returns the supplied argument rather than the stored value | `lblanguage.c` has a guarded assignment followed by `return language`; header defines `LANG_COUNT` after JP and US | Execute the actual game function with -1, 0, 1, 2 from known storage states. Capture input, return register, and storage before/after. Do not replace execution with a host-language model. | Not executed; no return-contract documentation accepted |
| `SetSavedLanguage` is distinct from performing a memory-card save | Separate calls in `mnLanguage_8024BFE0`; setter body only calls `gmMainLib_8015CC58` and assigns a byte | Observe setter and storage/card effects separately under controlled conditions; scope wording to what instrumentation can establish | Name alone is insufficient; persistence claim withheld |

Static review included the whole TU and header, the storage accessor chain in
`gmmain_lib.c`, relevant structs in `gm/types.h`, startup setter calls, the complete
`mnlanguage.c` module, sound-test setter use, and repository-wide identifier xrefs.
This is not a completed review of every predicate consumer. Callback references
must be included in any later whole-TU investigation.

## Tool audit and observed runtime facts

`melee-agent capabilities search runtime` and `... search dolphin` both returned
no capability. The discovery gap is recorded as local tooling issue #1566. The existing module nevertheless exists at
`tools/melee-agent/src/dolphin_debug/`, and this command worked from the checkout:

```sh
python -m src.dolphin_debug.cli --help
```

Reading `launcher.py` showed that its default configuration directory is the
normal Dolphin profile and `launch()` invokes `configure_gdb_stub()`. For this
trial, Dolphin was launched directly with an isolated profile using options
confirmed by its own `--help`:

```sh
/Users/mike/Applications/Dolphin-Debug.app/Contents/MacOS/Dolphin \
  --user=/tmp/melee-document-lblanguage \
  --exec=/Users/mike/Downloads/ssbm_v1.02_original.iso \
  --config=Dolphin.Core.GDBPort=-1 \
  --config=Dolphin.Core.SIDevice0=6
```

The window identified Dolphin 2509, JITARM64 SC, Metal, HLE, and GALE01. The
visible game screen asked whether to create game data on the empty memory card.
No normal user profile was used. The trial did not establish ISO identity by
hashing the entire image; the source DOL hash is recorded separately below.

Memory observations, made using the existing CLI:

```sh
python -m src.dolphin_debug.cli read 0x804D3EE0 -n 4
# 80 45 A6 C0
python -m src.dolphin_debug.cli read 0x8045A6C0 -n 4
# 01 00 00 00
python -m src.dolphin_debug.cli read 0x8015CC58 -n 16
# 80 6D 88 40 38 63 1C B0 4E 80 00 20 1C 03 00 AC
python -m src.dolphin_debug.cli read 0x8045C386 -n 1
# 01
python -m src.dolphin_debug.cli read 0x8000AE18 -n 64
# 7C0802A6 2C030000 90010004 9421FFE8
# 93E10014 41800018 2C030002 40800010
# 547F063E 48151E1D 9BE30016 8001001C
# 83E10014 38210018 7C0803A6 4E800020
```

The symbol configuration identifies the pointer at `0x804D3EE0` and the function
at `0x8015CC58`. The loaded accessor contains `addi r3,r3,0x1CB0`, and the setter
contains `stb r31,0x16(r3)`: with the observed pointer, this resolves to
`0x8045C386`. This is a structural address connection, not evidence that menu
selection changes that byte or that it persists to a card.

Input attempts through the configured keyboard mapping did not produce a
reliably captured transition to the language menu. Captures alternated between
the startup prompt and black frames. The cause was not diagnosed. Do not infer
input delivery, a language change, emulator failure, or a successful save from
these captures. No memory writes or function-invocation tests were performed.

Next runtime work: establish reliable input delivery and settled-frame capture
in the isolated profile, then run the paired menu test. For the setter boundary
contract, audit the existing GDB client/daemon and validate register decoding and
stop behavior before extending it to controlled invocation. JIT breakpoint
limitations documented by the debug skill remain unresolved in this trial.

## Build baseline

The doctor found the original DOL and report missing locally. `--fix` repaired
prerequisites and began a report build; tool downloads stalled without useful
progress. The report build was interrupted and the checkout was configured to
use already-installed compiler tools as read-only dependencies:

```sh
python configure.py \
  --binutils /Users/mike/code/melee/build/binutils \
  --compilers /Users/mike/code/melee/build/compilers \
  --wrapper /Users/mike/code/melee/build/tools/wibo \
  --sjiswrap /Users/mike/code/melee/build/tools/sjiswrap.exe \
  --objdiff /Users/mike/code/melee/build/tools/objdiff-cli \
  --reloc-diffs all
ninja
```

All build commands execute in the trial worktree. The shared checkout is only a
tool dependency source. Expected DOL SHA-1 from `config/GALE01/config.yml`:
`08e0bf20134dfcb260699671004527b2d6bb1a45`.

Build result: `ninja` succeeded and its SHA-1 check passed. A separate `shasum`
confirmed `08e0bf20134dfcb260699671004527b2d6bb1a45` for both original and rebuilt
DOLs. The fresh strict report gives `main/melee/lb/lblanguage` 316/316 code bytes,
8/8 functions, and its sole `.text` section at 100%; the unit is complete.

The checkout-wide report is **not** uniformly 100%: matched code 3,752,308 /
3,882,032 bytes (96.65835%), matched data 1,211,112 / 1,211,168 bytes (99.99538%),
matched functions 19,669 / 19,828, complete code 3,620,688 bytes (93.26786%),
complete data 1,142,957 bytes (94.368164%), complete units 1,111 / 1,129,
fuzzy match 99.97803%. These are baseline findings, not a regression introduced
by this trial. They require reconciliation before claiming a globally 100%
source build; the expected DOL alone does not establish that. No matching
campaign was started. No game inputs to the build were edited, so this trial
has no source-change before/after comparison to certify.

`quick_validate.py` accepts the revised skill, and `git diff --check` passes.
The isolated Dolphin process was terminated and the function claim released
without marking documentation complete. The retained changes are the skill
and this trial record only; runtime artifacts remain outside version control.

## Skill corrections demonstrated by the trial

| Old workflow decision | Documentation workflow correction |
|---|---|
| Static code and strings suffice for a purpose/name | They populate a claim ledger and motivate falsifiable runtime tests |
| A matched function has verified behavior | Matching proves binary identity; semantic interpretation needs separate evidence |
| Add `@brief` and parameter comments to C/headers | Follow upstream `.dox` placement and write only useful, validated claims |
| `ninja` success is the validation gate | Require clean baseline, expected DOL hash, local metrics, and strict relocation comparison |
| Finish by committing everything and marking documented | Stage intended files only; record evidence/review status and leave blocked claims incomplete |
| Small file means analyze/document everything | Start with one claim; account for caller coverage and runtime setup cost |
| Tool search/skill commands are sufficient instructions | Inspect actual tool behavior, profile isolation, and observation reliability |

The skill revision is complete independently of the target's documentation.
The TU remains an unfinished investigation with human confirmation pending.

## Second pass: executable contract and Dolphin integration (2026-09-07)

Baseline revision `f1a85224b2`, initially clean, in worktree `662f/melee`.
This pass continues the same TU with one claim: `lbLang_SetLanguageSetting`
accepts 0/1 for storage and returns its argument even when rejected. Human
confirmation remains pending. Codex performed the following runtime tests.

### Reproduction and observation

Run from the active checkout, explicitly importing its tooling:

```sh
PYTHONPATH="$PWD/tools/melee-agent" python tools/dolphin-lblanguage-contract.py \
  --dolphin /Users/mike/Applications/Dolphin-Debug.app/Contents/MacOS/Dolphin \
  --iso /Users/mike/Downloads/ssbm_v1.02_original.iso
```

The harness launches Dolphin 2509 in interpreter mode with a fresh temporary
profile and a dedicated GDB port. It tests at the initial GDB stop
`T0f40:8000522c;01:81566550;`, before normal gameplay. It checks `GALE01` in
memory and the exact loaded 28 setter bytes:
`2c0300004d8000202c0300024c800020808d8840986400004e800020`.
The original DOL SHA-1 is `08e0bf20134dfcb260699671004527b2d6bb1a45`.
The ISO as a whole was not hashed; the experiment identifies the executed
function by its bytes rather than assuming that the filename proves identity.

The configured pointer `0x804D3EE0` resolved to `0x8045A6C0`. The setter's
`lwz r4,-0x77c0(r13)` and `stb r3,0(r4)` connect this storage to the symbol.
The harness sets r13 to `0x804DB6A0`, r3 to the test input, LR to the original
stopped PC, and PC to `0x8000AD98`. It single-steps at most eight times per case,
checks stop replies and PCs, and observes r3 and the byte on return. This is a
controlled API invocation, not an observation of a naturally occurring caller.

| Input (each tested from stored 0 and stored 1) | Stored result | Returned r3 |
|---|---|---|
| -2147483648 | Initial value retained | 0x80000000 |
| -1 | Initial value retained | 0xFFFFFFFF |
| 0 | 0 | 0 |
| 1 | 1 | 1 |
| 2 | Initial value retained | 2 |
| 2147483647 | Initial value retained | 0x7FFFFFFF |

All 12 cases passed. Negative inputs took PCs `AD98, AD9C, 8000522C`;
inputs >=2 took `AD98, AD9C, ADA0, ADA4, 8000522C`; accepted inputs visited
all seven setter instructions then returned to `8000522C` (short PCs have
prefix `8000`). The harness verified restoration of the byte and r3, r4, r13,
PC, CR, and LR, then terminated only its owned emulator. No code was patched.
The first run's JSON was retained locally at `/tmp/melee-lblanguage-contract.json`;
the harness emits the same evidence schema for a reviewer to reproduce.

Static coverage for this claim: the complete TU/header, the `language` byte at
struct offset zero in `gm/types.h`, and both repository references in
`gmMainLib_8015FBA4` (inputs 1/0, unused return). The setter has no callees.
Boundary observations plus its verified comparison instructions support the
contract; twelve examples alone are not exhaustive integer-domain testing.
No language-menu, distribution, or persistence interpretation is promoted.

### Integration findings

| Finding | Evidence and disposition |
|---|---|
| Wrong GDB configuration section | Live `Dolphin.Core.GDBPort` launch exposed no connection during the probe; `Dolphin.General.GDBPort` connected. Local Dolphin `MainSettings.cpp` also names General. Fixed launcher enable/disable (#1567). |
| Custom profile was not passed to Dolphin | `launch()` wrote a supplied config directory but omitted `--user`; fixed argument propagation and tested it. |
| PC API was a stub | Live `p40` returned 8000522C, then 80005340 after a step, while `read_pc()` returned None. Fixed using individual register 64 (#1568). Bulk `g` returned only GPRs, so appending guessed PC offsets would be wrong. |
| Tool provenance is implicit | Doctor reports installed `src.cli` under the shared checkout. Experiments/tests explicitly set PYTHONPATH to this worktree. |
| Execution success can be overstated | Static audit: daemon step ignores stop replies; continue returns success even for None; halt sends an interrupt without consuming its stop. Open #1569. Not reported as a reproduced live halt failure. |
| Transport checks are incomplete | Active debugger receive path does not verify checksums; separate `rsp_client.py` has a different implementation. Consolidation and corrupt/fragmented-packet tests remain needed (#1569). |
| Readiness probe consumes a connection | `wait_for_gdb_ready` connects then closes; the skill describes a single accepted client. This is a static concern, not a tested reconnect result. Avoided by retaining the real client connection. |
| Reproducible game inputs/capture are missing | Earlier menu trial remains unresolved. This API experiment does not fix or validate controller delivery, settled screenshots, JIT breakpoints, or normal event traces. |

The corrected launcher was also tested live through `DolphinLauncher` itself
with an isolated profile, port 19194, and interpreter setting: GALE01, stop PC
8000522C, then a successful step to 80005340. Ten focused Python tests cover
configuration preservation, profile propagation, and PC replies including
errors. These are integration tests and must not be presented as game evidence.

### Workflow decision

Improve `/understand` in place: its scope already covers this work. A second
`/melee-document` entrypoint would duplicate the evidence gates without solving
the execution gaps. The change adds explicit tool provenance and a bounded
interpreter-contract route backed by the real experiment. The remaining tooling
work is stop-state/transport correctness, followed by reliable input and capture
for the still-unvalidated menu claim.

### Second-pass preservation and review status

Before adding `src/melee/lb/lblanguage.dox`, configured and completed a fresh
build using the explicit tool paths and `--reloc-diffs all` command recorded
above. After adding it, repeated the same configure command, `ninja`, and
`python configure.py progress`. Parsed before/after `report.json` objects were
identical in full, including every unit, section, function, and aggregate metric.
`lblanguage` remained 316/316 bytes, 8/8 functions, complete, and 100% `.text`.
Original and rebuilt DOL SHA-1 both remained
`08e0bf20134dfcb260699671004527b2d6bb1a45`. Global pre-existing discrepancies
were unchanged; this is preservation, not a claim of globally perfect metrics.
No game C, headers, or symbols changed. Doxygen is not installed here, so the
new `.dox` was checked against the adjacent documentation syntax but not rendered.

Final focused integration suite: 10 tests passed, including malformed PC data.
The final harness rerun writes `/tmp/melee-lblanguage-contract-final.json` and
also records the imported implementation path and emulator version. The runtime
record and skill are fork workflow artifacts; the `.dox` is the small game-facing
review candidate. No commit or PR was created. The contract is documented as a
validated subset, with human confirmation pending and the other TU claims open.

## Tooling follow-up

The subsequent Dolphin tooling work is recorded in
[the integration validation record](../../../../docs/dolphin-validation.md).
The stop/packet issues above describe the pre-fix implementation. The shared
transport now validates framing, retains pending runs across execution timeouts,
and fences interrupts before exposing them as confirmed stops. The setter
harness now starts with confirmed halt/fencing rather than a `?` query. Its
12 cases passed again with restoration. See the current `/melee-debug` skill
for the supported session workflow; do not repeat the older launch/input recipes
above as current operational guidance.
