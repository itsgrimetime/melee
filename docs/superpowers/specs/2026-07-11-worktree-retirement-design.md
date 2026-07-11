# Conservative Agent Worktree Retirement

**Date:** 2026-07-11  
**Status:** Approved design  
**Issue:** Melee tooling issue #1234

## Problem

Completed agent worktrees accumulate after their tasks finish. A July 11 audit
found 20 clean, branch-backed, idle worktrees created in roughly one day using
3.97 GiB. Shared immutable assets reduce many individual worktrees to about
120-135 MiB, but do not address the creation rate, so retained worktrees still
grow by roughly 4 GiB per day.

The existing `tools/workflow/cleanup-stale.sh` is not a safe lifecycle tool. It
uses the timestamp of the worktree's HEAD commit as an age proxy, which can
predate creation or fail to reflect recent builds. Its `--apply` option only
prints commands. The Python worktree doctor already establishes the desired
operator experience for ignored artifacts: a read-only report, a dry-run plan,
machine-readable JSON, explicit apply, and revalidation before mutation. Whole
worktree retirement needs the same shape, with additional Git and process
guards.

## Goals

- Report every registered worktree and explain why it is or is not retirable.
- Preview an exact whole-worktree retirement plan without modifying anything.
- Apply only a freshly revalidated plan after an explicit `--apply` flag.
- Reclaim clean, idle, conventionally named agent worktrees at a steady-state
  rate comparable to their roughly 4 GiB/day creation rate.
- Preserve every branch and commit. Retirement removes only the linked
  worktree checkout and its ignored outputs.
- Fail closed for active, dirty, detached, PR, WIP, locked, prunable, primary,
  current, malformed, or uncertain worktrees.
- Measure actual worktree activity instead of HEAD commit age.
- Provide stable human-readable and JSON output suitable for later scheduling.

## Non-goals

- Deleting branches, refs, commits, or remote state.
- Force-removing dirty, detached, broken, missing, or locked worktrees.
- Running `git worktree prune` or directly deleting Git administrative data.
- Replacing the existing artifact cleanup commands for `build/` and `.cache/`.
- Automatically installing a scheduler or integrating with a particular agent
  host's completion hooks in this change.
- Determining task completion or open-PR status through a network service.
- Retiring manually managed worktrees outside recognized agent roots.
- Providing an absolute guarantee against a new process starting after the
  final process snapshot. Eliminating that last race requires an agent-runner
  lease protocol and is a possible follow-up.

## Alternatives

### Extend `cleanup-stale.sh`

This is the smallest surface change, but shell is a poor fit for structured
porcelain parsing, stable JSON, process inspection, descriptor-bound filesystem
walking, identity comparison, and repeated TOCTOU revalidation. It would also
make the existing misleading `--apply` behavior harder to change safely.

### Require completion hooks or markers

A coordinator-written completion marker provides the strongest evidence that a
task has ended. It cannot reclaim the existing backlog, however, and requires
every agent host to honor a new protocol. It also does not replace dirty,
process, branch, and filesystem safety checks. A marker may be added later as
an additional eligibility signal.

### Add a Python worktree retirement lifecycle

This is the selected approach. Add a focused
`tools/worktree_doctor/worktrees.py` module and dispatch it beside the existing
`artifacts` and `assets` commands. It can reuse the established report/dry-run/
apply vocabulary while implementing worktree-specific classification and
revalidation. It works for the current backlog without external coordination.

## Command-line interface

```text
python tools/worktree-doctor.py worktrees report [--min-idle-hours HOURS] [--json]
python tools/worktree-doctor.py worktrees retire [--min-idle-hours HOURS] [--json]
python tools/worktree-doctor.py worktrees retire --apply [--min-idle-hours HOURS] [--json]
```

The default `--min-idle-hours` is `24`. Negative and non-finite values are
argument errors.

`report` inspects all registered worktrees and emits their classification. It
does not create a plan. `retire` performs the same inspection and emits the
eligible worktrees as a dry-run plan. `retire --apply` acquires the retirement
lock, builds the plan, and revalidates each candidate immediately before normal
Git removal.

There is deliberately no `--force`, branch-deletion option, detached-worktree
override, or broad filesystem scan option. Whole-worktree retirement considers
only entries registered in the current repository's `git worktree list
--porcelain -z` output.

Exit behavior is part of the CLI contract:

- `0`: inspection completed; for apply, every planned candidate was removed.
  An ineligible worktree in the report is normal and does not change the exit
  status.
- `1`: a global operational failure was found during preflight, before apply
  began. Apply performs no removals in this case.
- `2`: apply began and a candidate failed, or a global failure was first found
  after an earlier removal. A late global failure stops all remaining work and
  emits the prior removals, unattempted plan entries, and top-level error.
- Argument errors retain `argparse`'s exit status `2` and usage on stderr;
  therefore callers distinguish an argument error from a partial apply by
  whether a versioned result was emitted on stdout.

## Classification and data model

The implementation should use immutable records analogous to the artifact
lifecycle:

- `WorktreeRecord`: reported path, canonical path, device/inode identity, HEAD,
  branch, porcelain flags, estimated disk bytes, activity timestamp, dirty
  state, ignored-path inventory, active process IDs, optional merge information,
  eligibility, and skip reasons.
- `WorktreeReport`: repository metadata, thresholds, and all records.
- `RetirementPlan`: eligible candidate identities and estimated bytes.
- `RetirementSkip`: path and stable reason.
- `RetirementResult`: planned, removed, skipped, and reclaimed-byte totals.

The JSON contract is schema version 1:

```json
{
  "schema_version": 1,
  "resource": "worktrees",
  "mode": "apply",
  "thresholds": {
    "min_idle_hours": 24
  },
  "repository": {
    "root": "/Users/mike/code/melee",
    "common_git_dir": "/Users/mike/code/melee/.git",
    "current_worktree": "/Users/mike/code/melee"
  },
  "worktrees": [
    {
      "path": "/Users/mike/.codex/worktrees/abcd/melee",
      "head": "0123456789abcdef",
      "branch": "codex/example",
      "estimated_disk_bytes": 134217728,
      "last_activity": 1783810000.0,
      "idle_seconds": 90000.0,
      "dirty": false,
      "active_pids": [],
      "merged_into_master": null,
      "ignored_path_count": 584,
      "unapproved_ignored_paths": [],
      "eligible": true,
      "skip_reasons": []
    }
  ],
  "planned": [
    {
      "path": "/Users/mike/.codex/worktrees/abcd/melee",
      "branch": "codex/example",
      "head": "0123456789abcdef",
      "estimated_disk_bytes": 134217728,
      "last_activity": 1783810000.0
    },
    {
      "path": "/Users/mike/.codex/worktrees/efgh/melee",
      "branch": "codex/changed",
      "head": "fedcba9876543210",
      "estimated_disk_bytes": 67108864,
      "last_activity": 1783800000.0
    }
  ],
  "removed": [
    {
      "path": "/Users/mike/.codex/worktrees/abcd/melee",
      "branch": "codex/example",
      "head": "0123456789abcdef",
      "branch_head_after": "0123456789abcdef",
      "estimated_reclaimed_bytes": 134217728
    }
  ],
  "skipped": [
    {
      "path": "/Users/mike/.codex/worktrees/efgh/melee",
      "branch": "codex/changed",
      "head": "fedcba9876543210",
      "phase": "revalidate",
      "reason": "changed-during-retirement"
    }
  ],
  "errors": [],
  "summary": {
    "eligible_count": 2,
    "estimated_planned_bytes": 201326592,
    "removed_count": 1,
    "estimated_reclaimed_bytes": 134217728
  }
}
```

`mode` is `report`, `dry-run`, or `apply`. In `report` mode, `planned`,
`removed`, and `skipped` are always empty even when eligible worktrees exist.
In `dry-run`, `planned` contains one object for each eligible record while
`removed` and `skipped` are empty. In `apply`, `planned` is the initial plan,
`removed` contains successful removals, and `skipped` contains only candidates
from that plan which failed revalidation or removal. Ineligible records remain
represented solely in `worktrees[].skip_reasons`; they are not duplicated in
top-level `skipped`. `errors` is always present. It is empty after a complete
inspection and contains global failures as exact `{reason: string, detail:
string}` objects. A global failure always leaves `planned` empty if it happens
before planning and leaves `removed` empty when it happens before apply begins.

The exact top-level object element schemas are:

```text
planned: {path: string, branch: string, head: string,
          estimated_disk_bytes: integer, last_activity: number}
removed: {path: string, branch: string, head: string,
          branch_head_after: string, estimated_reclaimed_bytes: integer}
skipped: {path: string, branch: string, head: string,
          phase: "revalidate"|"remove"|"verify", reason: string}
errors:  {reason: string, detail: string}
```

No fields in these objects are optional. Human output contains the same facts
and always prints branch, HEAD abbreviation, disk use, idle duration,
eligibility, and reasons. Output ordering is deterministic by canonical path;
the three result lists preserve planned path order.

### Strict worktree porcelain parsing

Invoke exactly `git worktree list --porcelain -z`. The `-z` form is mandatory:
each field is NUL-terminated and an empty field terminates a record, so paths
containing spaces, tabs, quotes, backslashes, or newlines are consumed as raw
path bytes rather than line-parsed or C-unquoted text. Decode with the
filesystem encoding and `surrogateescape` so every non-NUL path byte
round-trips into subprocess arguments.

Accept only the documented singleton fields `worktree`, `HEAD`, `branch`,
`detached`, `locked`, and `prunable`. A record must begin with exactly one
nonempty `worktree <absolute-path>` field, contain exactly one `HEAD <oid>`
field, and contain exactly one of `branch refs/heads/<name>` or bare
`detached`. `locked` and `prunable` may each occur at most once and may carry
their documented reason text. The OID must match the repository's object
format and the worktree path must be absolute. Preserve the branch suffix and
path exactly; do not split either on whitespace or newlines.

Fail the entire inspection with `worktree-porcelain-invalid` on an unknown
field, duplicate singleton, missing required field, branch plus detached,
neither branch nor detached, relative/empty path, invalid OID, a nonempty field
before `worktree`, malformed field/value separation, an unexpected empty
record, missing final record separator, trailing non-record data, or duplicate
canonical worktree path. No candidate may be removed when parsing fails. This
strictness intentionally treats a future Git porcelain extension as requiring
an explicit parser update rather than silently weakening safety.

The following stable skip reasons are part of the schema:

```text
main-worktree
current-worktree
outside-agent-roots
unrecognized-agent-branch
detached-head
branch-missing
branch-head-mismatch
protected-pr-branch
protected-pr-path
protected-wip-branch
locked-worktree
prunable-worktree
missing-directory
invalid-worktree-path
dirty-worktree
active-process
below-min-idle
clock-skew
scan-failed
status-query-failed
process-query-failed
process-query-overflow
worktree-porcelain-invalid
ignored-inventory-invalid
contains-unapproved-ignored
retained-evidence-present
asset-validation-failed
replaced-during-retirement
changed-during-retirement
git-remove-failed
branch-preservation-failed
```

## Fail-closed eligibility

A worktree is eligible only when every requirement below holds:

1. It is present in strictly parsed `git worktree list --porcelain -z` output
   and is neither locked nor
   marked prunable.
2. Its path is a real directory, not a symlink, and descriptor/path checks
   agree on its device and inode.
3. Its canonical path is beneath one of:
   `$HOME/.codex/worktrees`, `$HOME/.claude/worktrees`, or
   `<main-worktree>/.claude/worktrees`.
4. It is branch-backed, and `refs/heads/<branch>` exists and resolves to the
   reported HEAD.
5. Protected branch/path classification happens before agent-prefix
   classification. A branch beginning `pr/` yields `protected-pr-branch`; a
   branch beginning `wip/` yields `protected-wip-branch`; and a `melee-pr` or
   `pr-*` worktree component yields `protected-pr-path`, regardless of any
   other prefix or property.
6. After protected classification, the branch begins `codex/`, `claude/`, or
   `wall/`. Only otherwise unprotected branches can satisfy this requirement.
7. It is not the primary worktree and not the worktree from which the command
   is running.
8. `git --no-optional-locks status --porcelain=v2 -z
   --untracked-files=all --ignore-submodules=none` succeeds and returns empty.
   This proves only that tracked and nonignored state is clean; it does not
   establish that ignored data is disposable.
9. A separate NUL-delimited ignored-path inventory succeeds, and every ignored
   entry belongs to the explicit disposable allowlist below. Any other ignored
   path yields `contains-unapproved-ignored`.
10. Process inspection succeeds and finds no process using or naming the
   worktree.
11. Filesystem inspection succeeds and the most recent activity is at least
    the configured idle threshold old.

`merged_into_master` is nullable and informational only. It is `true` or
`false` when the local merge-base query succeeds and `null` when it is not
known; it never changes eligibility. A completed agent branch may intentionally
remain unmerged, and normal worktree removal preserves that branch and its
commits. Conversely, paused work should use the protected `wip/*` convention.

Unknown or contradictory state always adds a skip reason. The tool does not
offer overrides for these guards.

## Ignored-data inventory and disposable allowlist

Git-clean status does not protect ignored files. Before declaring a worktree
eligible, invoke exactly:

```text
git ls-files --others -i --exclude-standard -z --
```

Parse the output as NUL-terminated repository-relative path bytes using the
filesystem encoding with `surrogateescape`. Reject an unterminated stream,
empty entry, absolute path, `.`/`..` component, duplicate normalized path,
path outside the worktree, output above 32 MiB, more than 500,000 entries, or a
path that cannot be opened and type-checked without following symlinks. Such a
malformed or incomplete inventory yields `ignored-inventory-invalid` and fails
closed. Newlines and all other non-NUL bytes in valid path components are data,
not separators.

The disposable allowlist is deliberately finite and code-defined. Retained
evidence and asset validation run before this general allowlist. Subject to
those higher-priority exclusions, a path is approved only when its relative
path and entry type match one of these classes:

- entries beneath `build/` or `.cache/`, except retained-evidence roots and the
  separately validated `build/compilers` and `build/tools` asset roots;
- entries beneath a directory component named exactly `__pycache__`,
  `.pytest_cache`, `.mypy_cache`, or `htmlcov`;
- root generated files `build.ninja`, `.ninja_deps`, `.ninja_log`,
  `compile_commands.json`, `objdiff.json`, `ctx.c`, and `ctx_includes.h`;
- `tools/melee-agent/.coverage`; or
- validated shared assets under the separate rules below.

Retained evidence always overrides `build/**`. Protected roots include
`build/diagnostics`, `build/diagnostics/runs`, `build/runs`, and every
manifest-owned run/artifact root discovered from the ignored inventory.
Discovery examines every ignored regular file named `manifest.json` using a
dedicated `worktree_doctor.retained_evidence` classifier: the JSON must carry
the exact `melee-agent.mwcc-debug-artifact-run/v1` format, its run ID must match
its direct parent, and the sibling `evidence/` and `transient/` layout must pass
the artifact lifecycle's ownership rules. The artifact root is the validated
run directory's parent, so caller-supplied custom roots require no separate
registry. A manifest-like file with malformed format/layout remains unknown
ignored data and fails closed. Any ignored entry beneath a retained root yields
`retained-evidence-present`. The 30-day/10-GiB artifact-pruner contract alone
owns removal of this evidence. Retirement cannot bypass it with an idle-age
override and remains blocked until an explicit artifact-pruner apply clears
the evidence. An empty retained root does not block.

`worktree_doctor.assets.ASSET_PATHS` is carved out before `build/**`. Real
container directories at `build/compilers` and `build/tools` are permitted,
but every leaf beneath them, plus exact `tools/table-typer/table-typer`, must be
an expected symlink that passes the existing shared-cache manifest, relative
path, target identity, and no-extra-leaf validation. Any real, dangling,
unexpected, replaced, or unvalidated leaf yields `asset-validation-failed`.

`orig/GALE01/sys/main.dol` has a distinct rule: it is disposable only as a
symlink whose resolved target equals a `DOL_CANDIDATES` entry and whose opened
target device/inode equals the descriptor-opened approved candidate. A real
DOL, dangling link, merely path-matching replacement, or other target yields
`asset-validation-failed`.

Sensitive-name denial takes precedence over the allowlist: any regular file or
directory named `*.log` or `*.dump`, or beneath a component named `log`, `logs`,
`dump`, or `dumps`, is unapproved even under `build/` or `.cache/`, except the
explicitly named rebuildable root `.ninja_log`. This prevents build-local
diagnostic logs and dumps from being erased merely because their parent is a
generated-output directory.

Everything else is unapproved. In particular, real ignored content under
`orig/`, `.env`, `.venv`/environment directories, `.claude/`, `.codex/`,
diagnostic/candidate/run output, arbitrary `*.m2c` or context files, editor
history, downloaded tools, coverage other than the one exact generated path,
and logs/dumps blocks retirement. Report the total ignored-path count and all
unapproved relative paths in JSON; human output may summarize after the first
20 while retaining the full JSON list.

Bind the reviewed inventory into the retirement plan as sorted tuples of
relative path, entry kind, device, inode, size, and mtime. Apply must rerun the
same Git inventory and descriptor checks immediately before removal. A new,
missing, type-changed, identity-changed, or newly unapproved ignored entry
produces `changed-during-retirement` or `contains-unapproved-ignored` and skips
the candidate. The filesystem walk must also account for every ignored
inventory entry; disagreement between Git inventory and the walk fails closed.

## Idle-age and disk-use inspection

HEAD commit time must not contribute to idle age. It may be months old when a
worktree is newly created and says nothing about recent builds.

Walk the candidate directory using descriptor-relative operations and
`lstat`/no-follow semantics. Include the mtimes of directories, regular files,
and symlinks, but never traverse a symlink target. The worktree's activity time
is the maximum of:

- every visited entry's mtime, including the worktree's `.git` marker; and
- the linked-worktree administrative `HEAD`, `logs/HEAD`, and `index` mtimes,
  captured before the status command.

Compute estimated reclaimable disk use during the same walk as the sum of
`st_blocks * 512`, including directories and symlinks but excluding anything
reachable only through a symlink. This represents blocks removed with the
checkout; it does not claim that shared common-Git metadata is reclaimed.
Every JSON field and human label for this value uses the `estimated_` prefix;
filesystem block accounting is not an exact post-removal free-space guarantee.

Run Git status with optional locks disabled so reporting cannot refresh the
index and reset its own idle clock. A traversal error, unsupported entry,
unreadable administrative timestamp, or timestamp materially in the future
makes the candidate ineligible. A newer activity timestamp or different disk
measurement during apply revalidation is a change, not a reason to trust the
old plan.

## Active-process detection

Take a bounded process snapshot from both:

```text
lsof -nP -F pfn
ps -axo pid=,command=
```

Parse `lsof` PID and name fields so cwd and open paths can be canonicalized.
Only an `lsof` `n` field beginning with `/` is a filesystem path; ignore socket,
pipe, protocol, device-label, and other non-absolute names rather than resolving
them relative to the doctor. A process is active for a worktree when an
absolute cwd or open path is at or below the canonical worktree path. Also
conservatively treat a process command line that contains the canonical or
reported worktree path as active. Exclude the doctor process itself; its
short-lived Git/stat subprocesses must have exited before the snapshot.

Each command has a 15-second timeout, an 8 MiB stdout limit, a 1 MiB stderr
limit, and a 200,000-record limit (`lsof` fields or `ps` process rows). Read
incrementally and terminate the child on the first limit breach rather than
allowing `subprocess.run(capture_output=True)` to allocate unbounded output.
Exceeding any byte or record limit produces `process-query-overflow`; a missing
command, timeout, nonzero exit, malformed record, or permission failure
produces `process-query-failed`. Either condition is a global failure: report
emits the failure payload for diagnosis. If detected during preflight, apply
removes nothing and returns exit status 1. If first detected during
revalidation after an earlier successful removal, apply stops all remaining
work, emits its partial result and top-level error, and returns exit status 2.
Refresh the bounded process snapshot immediately before each removal.

## Apply locking, revalidation, and removal

`retire --apply` takes a nonblocking advisory lock in the common Git directory,
for example `.git/worktree-doctor-retirement.lock`. Failure to acquire the lock
is an operational error and performs no removals. This prevents two doctor
processes from retiring the same checkout concurrently.

For each planned candidate, apply mode performs a fresh inspection immediately
before removal:

1. Re-read and strictly parse `git worktree list --porcelain -z`, then locate
   the exact canonical path. Any global parse failure stops the remaining
   apply operation without further removals.
2. Reconfirm device/inode identity, directory type, HEAD, branch ref, branch
   class, main/current protection, and locked/prunable state.
3. Re-run no-optional-locks status.
4. Re-snapshot processes.
5. Re-inventory and revalidate every ignored path, retained-evidence root, and
   validated asset link, then re-walk activity and estimated disk facts.
6. Skip when the candidate is no longer eligible or any reviewed identity or
   activity fact changed.
7. Run only `git worktree remove -- <path>`, without `--force`.
8. Verify that the path is absent, the worktree is no longer registered, and
   its branch ref still exists. Record the branch's post-removal target.

The tool never invokes `rm -rf`, `git branch -d/-D`, `git update-ref`, or
`git worktree prune`. A Git removal failure leaves the candidate in place and
is reported as `git-remove-failed`. Per-candidate races or failures do not
prevent other independently revalidated candidates from being attempted.

## Compatibility

Existing `python tools/worktree-doctor.py`, `--fix`, `--banner`, `artifacts`,
and `assets` behavior remains unchanged. The new command is dispatched only
when the first argument is `worktrees`.

`tools/workflow/cleanup-stale.sh` remains non-destructive. Its current
`--apply` continues to print commands rather than execute them, avoiding a
dangerous semantic change for existing users. Its output or documentation may
point to `worktree-doctor.py worktrees report/retire`, and it may be deprecated
later after callers migrate.

The implementation may later expose an agent completion marker or scheduler,
but schema version 1 does not depend on either.

## Test strategy

Behavior and integration tests must cover:

- Porcelain parsing for branch-backed, detached, locked, prunable, missing,
  space-containing, and Unicode paths.
- Each eligibility guard independently, including recognized-root plus
  recognized-branch conjunctions.
- Primary/current, `pr/*`, `wip/*`, `melee-pr`, `pr-*`, detached, dirty, and
  active worktrees remaining ineligible regardless of age.
- Staged, unstaged, untracked, and submodule dirtiness blocking retirement.
- Strict NUL-safe ignored inventory parsing, including newlines, malformed or
  unterminated output, duplicate/traversing paths, and output/entry overflow.
- Every disposable allowlist class, plus denial precedence for logs/dumps.
- Default and manifest-discovered custom retained diagnostic evidence roots producing
  `retained-evidence-present` until the dedicated 30-day/10-GiB artifact
  pruner clears them, including a cross-feature fixture that becomes eligible
  only after that lifecycle runs.
- `build/compilers` and `build/tools` allowing real container directories but
  requiring every expected leaf to be a validated shared-cache symlink.
- `orig/GALE01/sys/main.dol` allowing only an identity-checked symlink to an
  approved `DOL_CANDIDATES` target.
- Real `orig` assets, `.env`, `.claude`/`.codex` runtime data, diagnostics,
  arbitrary coverage, logs, and dumps producing `contains-unapproved-ignored`.
- Shared asset paths being allowed only as validated symlinks, with real files
  at the same paths blocking retirement.
- A newly created checkout with an old HEAD being young, and fresh build,
  source, commit, or administrative activity resetting idle age.
- Symlinks being measured but never followed; a large external symlink target
  must not inflate reported bytes or be touched.
- Cwd, open-file, and argv process matches; process-query timeout, malformed
  output, and permission errors failing closed.
- Stable human and exact JSON report/dry-run/apply output.
- Report and dry-run issuing no removal or mutating Git/index timestamps.
- Apply revalidation when a worktree becomes dirty, active, locked, detached,
  unregistered, newer, branch-changed, HEAD-changed, or inode-replaced.
- The common-directory lock preventing concurrent apply runs.
- Normal removal of a real linked fixture worktree with ignored outputs,
  followed by verification that the branch and commit still exist.
- Git removal failure and branch-preservation verification failure reporting.
- Explicit assertions that apply never uses force removal, recursive filesystem
  deletion, branch deletion, ref mutation, or worktree pruning.

## Risks and mitigations

### “Completed” is inferred

Clean, idle, inactive, conventionally named agent branches are an operational
proxy for completed tasks. The branch remains available to recreate a worktree,
and deliberately paused work has the protected `wip/*` convention. A future
completion marker can strengthen this signal.

### PR detection is convention-based

Without a network query, an open PR on an arbitrary `codex/*` branch is not
discoverable. Protect the repository's `pr/*`, `melee-pr`, and `pr-*`
conventions and document that PR worktrees must follow them. Network-dependent
PR discovery would make cleanup less reliable and is outside this design.

### Final process-start race

A new process can theoretically enter the worktree after the last process
snapshot. Rechecking immediately before normal Git removal minimizes the
window; an agent-runner lease protocol is required to eliminate it completely.
The 24-hour idle threshold and agent/WIP/PR classification make such a late
restart unlikely.

### Filesystem traversal cost

Whole-tree activity and block measurement is more expensive than reading a
commit timestamp. Perform both in one no-follow walk, use bounded errors, and
do not inspect unregistered directories. The work is proportional to the
checkouts that the command may reclaim.

## Acceptance criteria

The issue is resolved when:

1. All three report, preview, and explicit-apply paths exist with a 24-hour
   default idle threshold and schema-versioned JSON.
2. A realistic set of old, clean, inactive `codex/*`, `claude/*`, and `wall/*`
   linked worktrees is planned and removed using normal Git removal.
3. Their branches and commits remain present after removal, including an
   unmerged branch fixture.
4. Active, dirty, detached, PR, WIP, primary, current, locked, prunable,
   missing, malformed, or uncertain worktrees are never removed.
5. Every ignored path is inventoried with NUL-safe Git output; any ignored data
   outside the explicit disposable allowlist blocks retirement, and logs/dumps
   remain protected even beneath allowed generated roots.
6. HEAD commit age alone cannot make a new or recently used worktree eligible.
7. Apply revalidation detects state and identity changes after preview and
   skips affected candidates.
8. A preflight process/porcelain failure prevents all apply removals; a global
   failure first detected after an earlier removal stops the remaining plan,
   reports partial results, and returns status 2.
9. Human output reports estimated planned and reclaimed block space, and JSON
   conforms to the documented version 1 shape.
10. Existing worktree-doctor and `cleanup-stale.sh` behavior remains compatible.
11. Tests prove no force removal, direct recursive deletion, branch deletion,
    ref mutation, or worktree pruning occurs.
