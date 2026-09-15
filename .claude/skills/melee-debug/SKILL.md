---
name: melee-debug
description: Launch isolated Dolphin sessions for Melee runtime investigation, inspect memory and execution stops, send controller input, and capture native screenshots. Use for runtime evidence in understand/documentation work; distinguish tested contracts from unverified game behavior.
---

# Dolphin runtime evidence

Use the active checkout's `AGENTS.md` evidence requirements. Runtime observations
validate only the claim actually tested. A screenshot, a successful input write,
and a matching DOL establish different facts.

## Use the current tooling and an owned session

The global CLI normally imports its installed checkout. From this worktree:

```sh
export MELEE_AGENT_USE_REPO_LOCAL=1
MELEE_AGENT_PRINT_SRC_CLI=1 melee-agent
melee-agent capabilities search dolphin
melee-agent dolphin --help
```

For Python APIs, use `PYTHONPATH="$PWD/tools/melee-agent"` and inspect the module's
`__file__`. Do not reinstall or modify another checkout just to run a trial.

Start a fresh session with explicit local game and emulator paths:

```sh
melee-agent dolphin launch --session /tmp/melee-doc-example \
  --iso /path/to/GALE01.iso --dolphin /path/to/Dolphin --interpreter
```

Launch is a foreground service; retain its exec session or background it in the
shell. It owns the emulator, private profile, GDB connection, and command socket.
It starts stopped. Use a new short session path for each independent run; keep
its metadata, logs, and screenshots as local evidence, outside the source patch.
Omit `--interpreter` for the platform's default CPU core when exploring menus.
The live-validated interpreter route is appropriate for bounded API experiments;
general JIT breakpoint accuracy is not implied.

Subsequent processes address that session explicitly:

```sh
melee-agent dolphin --session /tmp/melee-doc-example status
melee-agent dolphin --session /tmp/melee-doc-example read lbLang_SetLanguageSetting -n 28
melee-agent dolphin --session /tmp/melee-doc-example regs
melee-agent dolphin --session /tmp/melee-doc-example step
melee-agent dolphin --session /tmp/melee-doc-example resume
melee-agent dolphin --session /tmp/melee-doc-example halt
melee-agent dolphin --session /tmp/melee-doc-example stop
```

Never use `killall`, a stale PID file, or the normal Dolphin profile to reset a
trial. Do not auto-attach the memory engine when another emulator may be running;
it does not select this session's PID. Session RPC has no such fallback.

## Observe execution, not just command success

The tested Dolphin 2509 accepts one GDB client connection per launch, which
supports many commands. A readiness probe must retain that real connection. Closing it and
reconnecting is not a supported recovery path.

The transport reports unknown/running/stopped/disconnected state. A continue
timeout means no stop was confirmed; the pending run can still be interrupted.
Halt waits for a real stop and a PC-read barrier, including the extra empty and
duplicate stop replies observed in Dolphin 2509. Do not substitute `?` for halt:
its signal-shaped response alone does not establish that the CPU stopped.

Before an evidence-bearing experiment, verify game identity, loaded function
bytes, symbol addresses, ABI setup, and before/after observations. Check PC and
return/storage values, not merely a SIGTRAP. Use bounded steps and restoration
checks for controlled invocation. See the runnable setter contract experiment
and its limits in [the validation record](../../../docs/dolphin-validation.md).
Memory reads during a pending run return busy: halt/read/resume explicitly.

## Input and native screenshots

```sh
melee-agent dolphin --session /tmp/melee-doc-example input tap START --duration 0.3
melee-agent dolphin --session /tmp/melee-doc-example input press D_DOWN
melee-agent dolphin --session /tmp/melee-doc-example input release D_DOWN
melee-agent dolphin --session /tmp/melee-doc-example input release-all
melee-agent dolphin --session /tmp/melee-doc-example capture --timeout 10
```

Inputs use profile-local FIFOs, not focused keyboard events. The game must be
running to consume them. A tap separates press and release with a host-time
dwell and releases on failure; queued PRESS/RELEASE in one batch can disappear
before a game poll. Returned input metadata records requests, not acknowledged
consumption or exact frame timing. Test delivery with a contrasting observation.

Capture uses Dolphin's screenshot hotkey on a separate pipe. It waits for a new,
complete, decodable PNG and rejects black transition frames within a bounded
deadline. A fresh nonblack image does not establish a settled menu, correct game
state, or the effect of an input. Inspect it and connect it to the selected claim.
Use a caller predicate through the library when a test has a concrete image
acceptance condition. Keep rejected frames and timeout reasons in the record.
Dark scenes may require a different explicit quality threshold.

For a game-behavior claim, retain setup, inputs, preconditions, exact addresses,
observations, contrasting cases, and human-review status. Do not copy historical
hardcoded player/frame addresses without resolving them from the active binary.

## Limits and regression checks

See [Dolphin validation](../../../docs/dolphin-validation.md) for the measured
transport and controller cases and remaining scope limits. The tools do not
establish frame-exact controller scheduling, deterministic gameplay, or arbitrary
breakpoint/watchpoint reliability. Failures should retain actionable diagnostics;
never turn a timeout or a stale screenshot into successful evidence.
