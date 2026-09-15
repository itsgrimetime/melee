# Dolphin integration validation

Tests were performed by Codex on macOS with Dolphin 2509 at
`/Users/mike/Applications/Dolphin-Debug.app`. Human confirmation is pending.
These are tooling observations; they do not validate new game semantics.

## Stop handling and RSP transport

Run the regression suite from the active checkout:

```sh
PYTHONPATH="$PWD/tools/melee-agent" python -m pytest \
  tools/melee-agent/tests/test_dolphin_rsp.py \
  tools/melee-agent/tests/test_dolphin_documentation.py -q --no-cov
```

2026-09-07: 62 cases passed. They cover packet fragmentation/checksums/EOF,
command deadlines, execution timeout recovery, concurrent halt, stale replies,
reader ownership, interrupt trailers/fencing, partial steps, and CLI failures.

The live acceptance used fresh isolated profiles, dedicated ports 19201–19205,
GALE01 from the local ISO, and `Dolphin.Core.CPUCore=0`. Only the owned emulator
was terminated. No memory-engine attachment or existing emulator was used.
Observed initial PC was `8000522C`; one step reached `80005340`. A daemon
continue with a 0.01-second deadline returned failure with state `running`,
followed by a successful fenced halt and correctly aligned PC/game-ID reads.
Concurrent daemon continue/halt callers both received run 4's confirmed stop;
subsequent `p40` and `m80000000,6` returned a PC and `GALE01`, respectively.

Live testing exposed two dialect details absent from the first mock tests:
initial Ctrl-C emitted `T05…` followed by an empty packet; interrupting execution
could emit `T05…`, an empty packet, then a second `T05…` with a different PC.
The interrupt completion fence reads `p40` before releasing the pending run,
so queued stop replies cannot become the next command's result. The narrow
empty-trailer allowance ends at the next command ACK/reply. Captured sequences
are represented in the protocol regression tests. A `?` reply is not treated as
confirmed stop evidence.

The existing setter experiment also passed all 12 cases with restoration using
confirmed halt/fencing:

```sh
PYTHONPATH="$PWD/tools/melee-agent" python tools/dolphin-lblanguage-contract.py \
  --dolphin /Users/mike/Applications/Dolphin-Debug.app/Contents/MacOS/Dolphin \
  --iso /Users/mike/Downloads/ssbm_v1.02_original.iso
```

Its local result was `/tmp/melee-lblanguage-hardened.json`. It records exact
function bytes, tool import path, emulator version, tested inputs, PC paths,
storage and restoration. Its original-DOL identity check is scoped to that
contract; the protocol tests do not prove JIT breakpoint reliability.

A subsequent review added two continuous-traffic deadline cases: repeated ACKs
or duplicate stops must not extend the interrupt fence deadline. The transport
and original documentation suite now has 64 passing cases.

## Owned sessions, input, and native capture

Use the repo-local entrypoint while developing in a worktree:

```sh
export MELEE_AGENT_USE_REPO_LOCAL=1
MELEE_AGENT_PRINT_SRC_CLI=1 melee-agent
melee-agent capabilities search dolphin
melee-agent dolphin launch --session /tmp/melee-doc-example \
  --iso /path/to/GALE01.iso --dolphin /path/to/Dolphin --interpreter
```

The last command is a foreground service. Keep it alive. From separate client
processes, use the same explicit session directory:

```sh
melee-agent dolphin --session /tmp/melee-doc-example status
melee-agent dolphin --session /tmp/melee-doc-example read lbLang_SetLanguageSetting -n 28
melee-agent dolphin --session /tmp/melee-doc-example step
melee-agent dolphin --session /tmp/melee-doc-example resume
melee-agent dolphin --session /tmp/melee-doc-example input tap START --duration 0.3
melee-agent dolphin --session /tmp/melee-doc-example capture --timeout 10
melee-agent dolphin --session /tmp/melee-doc-example halt
melee-agent dolphin --session /tmp/melee-doc-example stop
```

Omit `--interpreter` to use the platform's default CPU core for interactive
exploration. The sequence above is an API example, not a deterministic menu
navigation script. Wait for and inspect the intended state before choosing the
next input. `resume` reports an issued request/running state, not a confirmed
stop. Reads during an outstanding run are busy; halt before reading.

Live acceptance on 2026-09-07 used `/tmp/md-live-662f-a` (interpreter, port 57650)
and `/tmp/md-live-662f-b` (platform default, port 57686). Separate CLI processes
queried status, read the complete setter bytes by symbol, and stepped A from
`8000522C` to `80005340`. Stopping A exited its owner/emulator while B remained
connected and running. Both used GDB only, despite another unrelated Dolphin
process running on the machine. No memory-engine attachment was used.

B returned fresh native PNGs with dimensions 640x527, SHA-256, request/observation
times, and capture-quality measurements. Initial START requests during the logo
sequence did not establish a menu transition; those captures were inspected and
not misreported as menu evidence. After reaching the intro, later START requests
reached the title and main menu. Captures inspected by Codex:

| Action / observation | B profile screenshot filename |
|---|---|
| Main menu, 1-P Mode highlighted | `GALE01_2026-09-07_22-21-52.png` |
| D_DOWN tap, 0.15 host seconds; VS. Mode highlighted | `GALE01_2026-09-07_22-22-27.png` |
| D_UP tap, 0.15 host seconds; 1-P Mode highlighted again | `GALE01_2026-09-07_22-22-31.png` |

Files are retained under B's `profile/ScreenShots/GALE01/`; local JSON records
are `/tmp/melee-session-cli-captures.json` and
`/tmp/melee-session-cli-contrasts.json`. Generated images and profiles are not
committed. Human confirmation of the visual observations remains pending.

Analog controls were checked through B's own halt/read/resume sequence, without
guest memory writes. `MAIN 1 0.5` produced bytes `50 00` at `0x804C1FC4`;
returning to `MAIN 0.5 0.5` produced `00 00`. `L 0.75` produced `8C` at
`0x804C1FC8`; release-all restored `00`. Static connection: the active symbol
file places `HSD_PadMasterStatus` at `0x804C1FAC`, and `controller.h` places
stickX/stickY at +0x18/+0x19 and analogL at +0x1C. These observations validate
this mapping/transport case, not an unrestricted movement or timing claim.

A separate initial pipe/GDB probe saw D_DOWN at the first status word change
`00000000 -> 00000004 -> 00000000`. START's `0x1000` could remain visible after
0.3 host seconds of release during startup before clearing later. Inputs are
therefore explicitly reported as host requests, never frame-exact delivery.

Capture while halted failed explicitly instead of returning an old PNG. The
capture helper also supports bounded quality/predicate retries; predicate
acceptance itself is not semantic game-state validation. Its default near-black
filter measures the fraction of pixels with any RGB channel greater than 32;
at least 0.1% must pass. This is a quality policy, not a settled-state oracle,
and can intentionally reject a genuinely dark scene. Override thresholds
explicitly for such a test. Pillow is optional (`melee-agent[dolphin]`); its
absence affects capture rather than GDB/session imports. DME is optional and is
not a dependency of the owned-session route.

The final fresh session `/tmp/md-live-662f-final` recorded `Dolphin 2509`, exact
launch argv, and configuration hashes. Separate clients successfully released
all controls while stopped, received an explicit failure for stopped capture,
resumed, captured the new-profile memory-card prompt, and stopped the service.
The result is retained at `/tmp/melee-session-final-acceptance.json`.

After all three services stopped, their owned emulator PIDs no longer existed,
all three command sockets were removed, and session metadata had status
`stopped`. The 13 files in the normal Dolphin `Config` directory were SHA-256
identical to the pre-test snapshot. Session profiles and evidence remained.
`capabilities search dolphin`, `... runtime`, and `... 'controller capture'`
resolved the new command through the actual repo-local console entrypoint.
Local symbol lookup returned `lbLang_SetLanguageSetting = 0x8000AD98` without
an emulator connection.

Final regression validation: 126 tests passed across the following files (118
in the first four, plus eight capability-hook tests). Both updated skills passed
the skill validator; changed Dolphin Python modules passed Ruff, and
`git diff --check` passed.

```sh
PYTHONPATH=tools/melee-agent pytest -q --no-cov \
  tools/melee-agent/tests/test_dolphin_rsp.py \
  tools/melee-agent/tests/test_dolphin_documentation.py \
  tools/melee-agent/tests/test_dolphin_sessions.py \
  tools/melee-agent/tests/test_capabilities.py \
  tools/melee-agent/tests/test_capabilities_hooks.py
```

This tooling follow-up changes no game C, headers, or symbols; it does not claim
a new game-binary rebuild. The setter trial's preservation evidence is recorded
separately above.
