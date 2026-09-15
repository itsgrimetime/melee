---
name: mwcc-inspect
description: Inspect MWCC's internal IR (ENodes, ObjObjects, Statements) for a Melee TU by running RootCubed/mwcc-inspector on a remote Windows host. Use when stuck on register-allocation cascades or other last-mile matching issues that mismatch-db, opseq, ghidra, and discord-knowledge haven't explained — this is the next tool to reach for, not the first.
---

# MWCC Inspector (remote Windows)

Runs [`RootCubed/mwcc-inspector`](https://github.com/RootCubed/mwcc-inspector) against our 1.2.5n compiler on a remote Windows host (default: `nzxt-local`) and pulls the IR dump back locally. The inspector uses the Windows Debug Engine (`dbgeng.dll`) to attach to `mwcceppc.exe` and snapshot compiler-internal data structures at a per-function breakpoint.

## When to use this

| Situation | Should I use mwcc-inspect? |
|-----------|-----|
| First look at a function | No — start with `tools/checkdiff.py` and m2c |
| Asm diff doesn't match — figure out why | Try `/mismatch-db` and `/opseq` first |
| Known pattern from Discord | Try `/discord-knowledge` first |
| Need callers / xrefs | Use `/ghidra` |
| Register-cascade stalled at >95% match | **Yes** — this is what the tool is for |
| Compiler making allocation decisions we don't understand | **Yes** |
| Want to compare IR between target-equivalent and current code | **Yes** |
| Stack-frame mismatches, SDA relocations | No — the inspector sees the front-end (IR), not the linker stage |

The inspector dumps the compiler's *front-end* view (parsed expression trees, variable objects with internal addresses, statement IR) at a specific breakpoint near the end of each function's compilation. It does **not** dump the back-end (register allocation, basic-block CFG, scheduling) — those come from looking at the actual generated asm.

## What you get

For each function in the TU, the dump contains three sections:

1. **STATEMENTS (IR)** — the parsed statement tree with full ENode expansion. Each assignment, branch, call, and label is rendered as a tree of `EASS`, `EAND`, `EOBJREF`, `EINDIRECT`, `EINTCONST`, `EFUNCCALL`, etc. Variables in expressions reference their `ObjObject @ <address>`.

2. **LOCAL VARIABLES (first appearance order, with ObjObject addresses)** — the order in which the compiler first encountered each variable while parsing. This often correlates with internal numbering used by later passes.

3. **LOCAL VARIABLES (sorted by ObjObject address)** — the same variables sorted by the compiler-internal pointer used to track them. This ordering can reveal allocator hints (variables at lower addresses sometimes get earlier register assignments).

## Setup (one-time)

The skill assumes:
- SSH access to a Windows host via `ssh nzxt-local` (configurable via `MWCC_INSPECT_HOST`)
- The melee fork cloned at `C:\Users\mikes\code\melee` on that host (override with `MWCC_INSPECT_REMOTE_DIR`)
- `mwcc-inspector` built at the default path (override with `MWCC_INSPECT_CLI`). Pre-built binaries: https://github.com/RootCubed/mwcc-inspector/releases — use the **GC 1.0** zip, which the author confirms in `MwccInspectorCLI/Program.cs` handles `GC/1.2.5` as well

On first use, the remote needs the GameCube 1.2.5n compiler under `build/compilers/`. The wrapper does **not** auto-bootstrap — if missing, run once on the remote:

```
ssh nzxt-local 'C:\devkitPro\msys2\usr\bin\bash.exe -c "cd /c/Users/mikes/code/melee && python tools/download_tool.py compilers build/compilers --tag 20251118"'
```

## Usage

Run the wrapper from the active matcher worktree. If either
`tools/workflow/mwcc-inspect.sh` or
`tools/workflow/mwcc-inspect-supervisor.sh` is missing or stale, repair the
pair before inspecting:

```bash
python tools/worktree-doctor.py --fix
```

```bash
tools/workflow/mwcc-inspect.sh <path/to/source.c>
```

Example:

```bash
tools/workflow/mwcc-inspect.sh src/melee/lb/lbarq.c
# → build/mwcc_inspect/lbarq.txt
```

The wrapper:
1. Computes the mwcc compile command via local `ninja -t commands`
2. Strips the macOS-side `wine`/`wibo`/`sjiswrap` prefix (mwcceppc runs natively on Windows)
3. Resolves an exact commit and creates an invocation-private repository under the authenticated remote job directory; it never checks out the shared remote working tree
4. Applies uploaded candidate source and header overlays, then runs the inspector with private source/include/output roots and the same mwcc args
5. Writes the structured dump to `build/mwcc_inspect/<basename>.txt`

Clean committed repository sources use the exact local `HEAD`. Uploaded or
uncommitted candidates are overlaid on the selected exact ref together with
regular TU-local `*.h`/`*.inc` files from the active matcher worktree. Regular
candidate-adjacent headers are explicit overrides and take highest precedence.
This means candidate source/header bundles can be inspected without first
committing them.

Each run has a unique invocation ID. Simultaneous IDs may safely select
different refs because their repositories, cancellation, and output publication
are isolated and exact-ID scoped.

### Useful env-var overrides

| Var | Default | What |
|-----|---------|------|
| `MWCC_INSPECT_HOST` | `nzxt-local` | SSH alias |
| `MWCC_INSPECT_REMOTE_REF` | local HEAD | Git ref the remote checks out |
| `MWCC_INSPECT_REMOTE_DIR` | `/c/Users/mikes/code/melee` | Remote melee path |
| `MWCC_INSPECT_CLI` | GC 1.0 Debug build | Inspector exe path |
| `MWCC_INSPECT_REMOTE_BASH` | `C:\devkitPro\msys2\usr\bin\bash.exe` | Remote bash to use (default ssh shell is cmd.exe) |

## Workflow: register-cascade investigation

When stuck on a register-allocation cascade (e.g. expected `r25=platform_pass, r24=stay_airborne`, actual `r24=platform_pass, r25=stay_airborne`):

1. Dump the IR of your current best attempt:
   ```bash
   tools/workflow/mwcc-inspect.sh src/melee/<module>/<file>.c
   ```

2. Open `build/mwcc_inspect/<file>.txt`, locate the function's `LOCAL VARIABLES (sorted by ObjObject address)` section.

3. Note the address ordering of the swapped variables. The compiler likely allocates registers in roughly object-address order for variables in the same scope.

4. Modify your C to nudge the ordering (e.g. reorder declarations, introduce / remove intermediate variables, change initialization order).

5. Re-run from the same matcher worktree. Compare the new ObjObject ordering. Iterate until the order matches what would produce the target register assignment.

This is the workflow the upstream README around `mpColl_80046904` documents.

## Output sample

```
================================================================================
FUNCTION: lbArq_80014ABC
  Type: function(struct lbArqNode* arg0)[returns unsigned int]

STATEMENTS (IR):
--------------------------------------------------------------------------------
:0         Return [arg0]->state
  [EINDIRECT] [arg0]->state
    [EBITFIELD] [arg0]->state
      [EADD] [arg0] + 4
        [EINDIRECT] [arg0]
          [EOBJREF] arg0
            -> ObjObject @ 0x007AF1C8: arg0 (DataType: DLOCAL, Type: struct lbArqNode*)

LOCAL VARIABLES (sorted by ObjObject address):
--------------------------------------------------------------------------------
  [0] 0x007AF1C8  arg0
================================================================================
```

## Limitations

- **Front-end only.** Doesn't show register coloring, basic-block CFG, or pass progression. For those, look at the asm diff from `tools/checkdiff.py`.
- **Per-function snapshot.** The breakpoint fires near end-of-function compilation. Earlier passes' intermediate state isn't visible.
- **No insight into linker decisions.** SDA relocations, stack-frame layout, multi-TU concerns all happen later.
- **Compiler-internal addresses are not stable across runs.** ObjObject addresses are arbitrary heap pointers from the compiler's own allocator. The *ordering* and *relative offsets* are what matter, not the absolute values.
- **Exact base ref.** Every run starts from one exact commit in its private repository. Candidate and TU-local source/header overlays are the only uncommitted inputs.
- **Same-SID security boundary.** Private job ACLs protect against other Windows users, but processes running as the same Windows SID remain within the trusted threat model. This is not a general multi-user sandbox.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ERROR_FILE_NOT_FOUND` from inspector | The remote is missing the compiler. Run the bootstrap command from "Setup". |
| `command not found: bash.exe` | The remote's bash path differs. Set `MWCC_INSPECT_REMOTE_BASH`. |
| `not a valid mwcc version` | The inspector binary you're using doesn't have a build-date entry for 1.2.5n. Use the GC 1.0 release zip, not 1.3.2 or 3.0. |
| Dump shows wrong source | Inspect the wrapper's printed exact ref, invocation ID, and private job/repository diagnostics. Confirm the command was launched from the intended matcher worktree and repair the workflow pair with `python tools/worktree-doctor.py --fix`; do not manually check out the shared remote tree. |
| Inspector hangs | The breakpoint VA may be off (rare with GC 1.0 build + 1.2.5n compiler). Check `Detected mwcc version` line — should say `GC/1.2.5`. |

## See also

- Upstream tool: https://github.com/RootCubed/mwcc-inspector
- Original investigation notes (macOS PoC that we abandoned): branch refs to `mwcc_debug/*` commits
- For when you've identified the IR shape you want, the standard register-tweaking patterns: `/mismatch-db`
