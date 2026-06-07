# Capability Index — Tool Discoverability Design

**Date:** 2026-06-06 (revised 2026-06-07 incorporating an independent Codex review)
**Status:** Approved (design); pending implementation plan
**Topic:** Stop agents from nearly rebuilding tools that already exist

## Problem

Agents working in this repo repeatedly get to the point of designing/building a
new tool, then discover at the last moment that an equivalent already exists.
This wastes tokens and signals a discoverability/documentation gap.

Grounded in concrete incidents from session history, not hypothetical:

- An agent spent **hours** planning an `mwcc_debug` integration (vendor fork,
  MinGW Makefile, wibo patch, wrapper scripts) before discovering mid-session
  that `RootCubed/mwcc-inspector` already existed and was strictly better.
- An agent drafted a "custom permuter scorer" design before finding
  `melee-agent debug score` already does exactly that.
- An agent planned a Ghidra cross-reference tool, then a skill-list refresh
  revealed the `/ghidra` skill was already live.
- An agent re-analyzed permuter structure-search axes that had documented
  yield-0 findings in memory.

In every costly case the capability was one `--help` or one skill refresh away.
The agents had access; they lacked the reflex to check before building.

## Root-cause analysis (ranked)

1. **Agents don't audit-first at planning time (dominant).** A behavioral gap,
   not a missing-file gap. All expensive incidents were agents in "design a new
   tool" mode that never gated on "does this exist?"
2. **Most of the surface isn't in auto-loaded context.** A fresh agent auto-sees
   CLAUDE.md (~13 of 20 skills, ~15 of 150+ CLI subcommands) and skill
   frontmatter. The entire `debug` subsystem (80+ subcommands, including the
   `debug score` that got re-proposed) is documented nowhere auto-loaded.
3. **What is surfaced is stale, which is worse than missing.** CLAUDE.md's
   command list is significantly out of date, creating false confidence that the
   ~15 listed commands are the whole inventory. At least one skill doc references
   removed commands.
4. **No single "what can I do?" entry point.** No `capabilities` command, no
   generated index. A diligent agent must union 4+ partial, disagreeing surfaces.
5. **Tools are named by implementation, not task.** `ghidra` not `find-callers`;
   `mwcc-debug` not `debug-registers`; `debug score` not "score a candidate".

## Decisions

- **Ambition: incremental, with a lightweight phase-1 nudge.** Build the
  generated, auto-loaded, queryable index + an audit-first rule **+ a soft
  build-intent nudge hook** now. The dominant cause is behavioral, so phase 1
  includes a *soft* (non-blocking) hook that injects "search existing
  capabilities first" when it detects build-intent — but the *hard, blocking*
  pre-build gate remains deferred to a measured phase 2.
  *(Codex review B1: a passive brief + a rule is too weak precisely when the
  agent is deep in design mode; a mechanical nudge is cheap and targets the
  actual failure. Accepted.)*
- **Coverage: CLI + skills only.** Generate from the `melee-agent` Typer command
  tree + `.claude/skills/*/SKILL.md`. Standalone `tools/*.py` scripts and
  superpowers skills are out of scope (but see the manifest cross-link below so
  their existing documentation is not lost).
- **Auto-load: tiered.** Auto-load only the compact group-level brief
  (≈5 KB / ~680 words, measured from the real tree); full per-command detail is
  on demand. The full `docs/CAPABILITIES.md` (≈56 KB) is **never** auto-loaded.

## Grounding facts (verified against code, incl. Codex review)

- **CLI is Typer** (`tools/melee-agent/src/cli/__init__.py:24`, root app
  `:75–79`) → the tree is introspectable, BUT with caveats that the generator
  must handle:
  - **Unregistered apps are invisible.** `claim_app`, `complete_app`,
    `workflow_app` exist (`cli/claim.py:51`, `cli/complete.py:20`,
    `cli/workflow.py:18`) but are **not** added to the root app, so a root walk
    won't see them. The generator must **warn** when it finds a
    `*_app = typer.Typer()` module unreachable from root, so the gap is visible
    rather than silent.
  - **Help-text extraction needs a fallback chain.** Some commands set no
    explicit `help=`; fall back `short_help → callback help → docstring`.
    `compilers`/`harvest` (`__init__.py:174–178`) and `layout`'s callback
    (`cli/layout.py:15–17`) are examples.
  - **Entrypoint/worktree hazard.** `python -m src.cli` from the repo root can
    import the **main checkout**, while `melee-agent` uses the worktree-resolving
    launcher (`src/launcher.py:66–80`). The generator and the `capabilities`
    command must introspect **the same tree the user invokes** — prefer the
    `melee-agent` launcher path / explicit `PYTHONPATH=tools/melee-agent`.
  - Some CLI modules have import-time side effects — introspection must import
    with `PYTHONDONTWRITEBYTECODE=1` and tolerate them.
- **The session hook injects context only in the remote branch.**
  `.claude/hooks/session-startup.sh:50–53` exits before the `additionalContext`
  block when `CLAUDE_CODE_REMOTE != "true"`; remote JSON at `:101–109`,
  registered in `.claude/settings.json:3–10`. Auto-loading the brief everywhere
  requires emitting `additionalContext` **unconditionally**, merged with the
  remote notice into one JSON. **The injected string MUST be JSON-escaped** — a
  raw `cat` of Markdown into a JSON string is fragile (quotes/backticks/newlines
  break it).
- **Skill frontmatter is NOT reliable.** 3 of 19 skills have no YAML frontmatter
  and start with an `# H1` heading: `.claude/skills/prepare-pr/SKILL.md:1`,
  `.claude/skills/sync-upstream/SKILL.md:1`, `.claude/skills/workflow/SKILL.md:1`
  (verified directly). These are exactly the PR/sync/workflow skills agents most
  need — a naive frontmatter parser would silently drop them. The generator MUST
  fall back to `H1 title` + `first non-heading prose paragraph`.
- **`docs/agent-tool-manifest.md` exists** with inbound refs
  (`docs/agent-decomp-improvement-checklist.md:124–126`,
  `docs/parallel-agent-workflow.md:172–175`) and documents standalone
  scripts/setup paths that are **out of this spec's scope**. Therefore **do not
  delete/absorb it** — cross-link instead (see Component 3).
- **No `capabilities` command exists today** → no naming collision.
- **CI/pre-commit are narrowly scoped.** `melee-agent.yml:5–11` triggers only on
  `tools/melee-agent/**`; `build.yml:30–34` sparse-checkout omits `.claude` and
  `docs`; the pre-commit hook (`tools/pre-commit-hook.sh:37–42`) only inspects
  staged C/H files. The drift guard needs its own triggers/checkout (Component 7).

## Components

### 1. `melee-agent capabilities` command
`tools/melee-agent/src/cli/capabilities.py`, registered as `capabilities_app`.

- `capabilities search <task>` — **live** introspection of the root Typer app
  (groups → commands; help via the `short_help → callback → docstring` fallback)
  + `.claude/skills/*/SKILL.md` metadata (frontmatter, else H1+prose fallback).
  Rank by keyword match + the curated task-alias map (Component 2). Output:
  `name — one-liner — how to invoke`. Always fresh.
- `capabilities show [group]` — live full detail for a group (or everything).
- `capabilities generate` — write the generated artifacts (Component 3). Emits a
  **warning** listing any `*_app` Typer modules not reachable from root.
- Introspection runs under the worktree-correct tree (launcher path /
  `PYTHONPATH=tools/melee-agent`, `PYTHONDONTWRITEBYTECODE=1`).
- **No-match wording** (Codex C): "No existing capability found via indexed
  search; check the nearest `--help` group and relevant docs before building."
  Never assert a capability "doesn't exist," and never say "it may be safe to
  build" (too permissive).

### 2. Task-alias map
Small hand-maintained table (in-repo) mapping task intent → **in-scope**
capability id, bridging the implementation-vs-task naming gap. Seeds use CLI
commands + skills only (Codex B3 — no standalone-script targets):
- `find callers` / `cross reference` → `ghidra` skill, `commit check-callers`
- `debug registers` / `register allocation` → `mwcc-debug`, `mwcc-inspect`
- `score candidate` / `scorer` → `debug score`
- `per-file progress` / `per-file stats` → `extract files`
- `find similar functions` → `opseq` skill, `patterns similar`, `debug search`

Aliases that would point at standalone scripts (e.g. `compare_branch`,
`diff_changes`) are intentionally **omitted**; "diff two report.json"-style needs
are covered by the manifest cross-link, not the alias map. Every alias target is
**validated by a test** that it resolves to a real CLI path or skill name.

### 3. Generated artifacts + manifest cross-link
- `.claude/capabilities-brief.md` — the compact tier (one line per CLI group with
  its subcommand verbs + one line per skill). The human-readable source for the
  auto-load. ≈5 KB.
- `docs/CAPABILITIES.md` — full per-command/per-skill detail; the `show` target
  and browsable inventory. **Not** auto-loaded.
- **`docs/agent-tool-manifest.md` is kept, not absorbed** (Codex B3/A4). Add a
  bidirectional cross-link: the manifest points to `docs/CAPABILITIES.md` for the
  CLI+skill inventory; `CAPABILITIES.md` points to the manifest for standalone
  scripts/setup paths it deliberately doesn't cover. Existing inbound refs stay
  valid.

### 4. Session-hook change (auto-load the brief)
`.claude/hooks/session-startup.sh`: emit `additionalContext` **unconditionally**
(before the remote-only `exit 0`), injecting the brief + a one-line nudge
("Before building any tool/script/command, run `melee-agent capabilities search
<task>` — the inventory is large and your need may already exist"), merged with
the existing remote-env notice into a single JSON object.

**JSON-escaping (Codex B2):** build the JSON with a single
`python3 -c 'import json,sys; ...'` call that reads the brief file and emits a
properly-escaped object (one fast subprocess; the earlier "no Python at startup"
goal is relaxed — a millisecond `json.dumps` is acceptable). If `python3` or the
brief file is unavailable, **degrade gracefully**: skip the capabilities block
and still emit the remote notice. The hook must never exit non-zero in a way that
blocks session startup.

### 5. Soft build-intent nudge hook (phase 1; Codex B1)
A lightweight `UserPromptSubmit` (or `PreToolUse`) hook that detects build-intent
— the prompt or a tool call indicating creation of a new tool/script/CLI
command, or a Write/Edit targeting a new file under `tools/` — and **injects a
one-line reminder** to run `melee-agent capabilities search <task>` first. It is
**soft**: it adds context, it does **not** block the action. Detection is a
conservative keyword/path heuristic tuned for low false-trigger noise; misses are
acceptable (the auto-loaded brief + rule are the backstop). The **hard, blocking**
gate is explicitly *not* built here (phase 2).

### 6. Audit-first rule
Short, prominent block at the top of `CLAUDE.md` (auto-loaded) and in the
`decomp` and `workflow` skills: "Before building a new tool/script/command,
`capabilities search` first. There are 150+ CLI subcommands and 20 skills; assume
your need may already exist." Include the real cautionary examples
(mwcc-inspector, `debug score`).

### 7. Freshness guard (Codex B5)
A **dedicated** CI workflow (not piggybacked on `build.yml`/`melee-agent.yml`)
with explicit path triggers — `.claude/**`, `docs/CAPABILITIES.md`,
`docs/capabilities-brief*`, `tools/melee-agent/**`, `CLAUDE.md` — that checks out
those paths, runs `capabilities generate`, and fails on
`git diff --exit-code` of the generated artifacts. A pre-commit hook does the
same locally, scoped to the same paths (not just C/H files). Verify the generated
artifacts, the generator, and the hook edits are inside the fork-tooling overlay
that `tools/workflow/sync-upstream.sh` preserves (it preserves `.claude/`,
`docs/`, `tools/` per the script), so they are not reverted on sync — and add a
regression note tying this to the known `configure.py`-clobber class of issue.

### 8. Measurement (decision criterion for phase 2; Codex C)
- Log every `capabilities search` invocation to the **existing `audit_log`
  table** (`tools/melee-agent/src/db/schema.py`) — e.g. `action='capability_search',
  detail=<query>`. No new table (avoids YAGNI).
- Phase-2 trigger is a concrete query: rate of `capability_search` events vs. a
  manual tally of near-rebuild incidents over a window. If near-rebuilds persist
  despite the index + rule + soft nudge, build the hard blocking gate.
- Transcript-grep for the rebuild pattern is a **secondary** signal and is flagged
  UNVERIFIED as a precise metric (no fixed transcript-storage location or
  denominator); use it qualitatively, not as the primary gate.

## Data flow

```
session start ─► hook builds JSON-escaped additionalContext from capabilities-brief.md ─► injected (every session)
agent shows build-intent ─► soft nudge hook injects "capabilities search first" ─► agent runs `capabilities search X`
        ─► live result from Typer tree + SKILL.md ─► uses existing tool (no rebuild); invocation logged to audit_log
commit / CI ─► `capabilities generate` + `git diff --exit-code` over .claude+docs artifacts ─► fails on drift
```

## Error handling

- **Session start never breaks.** Single `python3` escape call with graceful
  degradation; missing brief/python3 → skip capabilities block, still emit remote
  notice; never block startup.
- **Soft nudge is non-blocking** by construction; a detection miss or false
  trigger only adds/omits one line of context.
- **Search no-match** → the reworded guidance above; never "doesn't exist."
- **Introspection failure / unreachable `*_app`** → `capabilities` warns and
  errors through the existing `ReportingTyper` path (prints a copyable
  `issue report` command); the generator surfaces unreachable apps rather than
  silently dropping them.

## Testing (expanded per Codex C)

- **Generator unit tests:** walking a known Typer-app fixture yields expected
  entries; help-text fallback chain (`short_help → callback → docstring`);
  detection + **warning** for an unregistered `*_app`; SKILL.md parsing for BOTH
  frontmatter and the H1+prose fallback (assert `prepare-pr`/`sync-upstream`/
  `workflow` are NOT dropped).
- **Alias validation:** every task-alias target resolves to a real CLI path or
  skill name.
- **Hook JSON validity:** generated `additionalContext` is valid JSON when the
  brief contains quotes, backticks, and newlines; missing-brief and missing-
  `python3` degrade paths emit valid (or no) JSON without erroring.
- **Search-relevance regression (tests the actual failures):** queries "scorer",
  "find callers", "register allocation", "per-file progress" return the right
  tool in top results; spot-check `debug score`, `ghidra`, `mwcc-inspect`.
- **Drift guard:** `capabilities generate` output is stable; the CI/pre-commit
  check fails when source changes without regeneration.
- **Worktree-safe invocation:** introspection targets the launcher-resolved tree,
  not a stray main-checkout import.

## Out of scope (YAGNI)

- The **hard, blocking** pre-build gate (deferred to a measured phase 2; phase 1
  ships only the *soft* nudge).
- Indexing standalone `tools/*.py` scripts (covered by the manifest cross-link).
- Indexing/curating the 70+ superpowers/global skills.
- Embeddings or fuzzy ranking beyond keyword + curated aliases.
- A new usage-counter DB table (reuse `audit_log`).
- Consolidating/deprecating genuinely overlapping commands the audit found
  (`scratch compile` vs `scratch update`; `extract get --create-scratch` vs
  `scratch create`; `scratch update-context` vs `scratch update`). Noted as a
  follow-up; the index surfaces them rather than resolving them.

## Open risks

- **Compact-tier token budget.** Brief ≈5 KB/session must stay clearly cheaper
  than the rebuilds it prevents; group-level granularity is chosen for this.
- **Soft-nudge efficacy is still a bet.** The nudge is mechanical but
  non-blocking; measurement (#8) exists to decide whether the hard gate is needed.
- **Unregistered Typer apps** (claim/complete/workflow) won't appear in the
  generated index; mitigated by the generator warning — follow-up is to register
  them if they are meant to be user-facing.
- **Surfacing redundancy.** Faithfully listing overlapping commands may add
  confusion; mitigated by the curated alias map pointing intent at the preferred
  tool.

## Codex review incorporation (changelog)

Independent Codex review (read-only, line-cited) resolved into this revision:
- **B1** behavioral gap → added the **soft build-intent nudge hook** to phase 1
  (Component 5); hard gate stays phase 2.
- **B2** hook JSON-escaping → defined `python3 json.dumps` escape + graceful
  degradation (Component 4); relaxed the "no Python at startup" goal.
- **B3** scope contradiction → dropped standalone-script aliases; **kept &
  cross-linked** the manifest instead of absorbing it (Components 2, 3).
- **B4** unreliable frontmatter (3 skills) → required H1+prose **fallback** and a
  test that the 3 skills aren't dropped (Components 1, Testing).
- **B5** CI drift specifics → dedicated workflow with explicit `.claude/**` +
  `docs/**` + `CLAUDE.md` triggers and its own checkout (Component 7).
- **C** → no-match rewording; worktree entrypoint guidance; alias validation
  tests; `audit_log`-based measurement with a concrete phase-2 trigger;
  softened "cannot go stale"; expanded test plan.
- **D** → full `CAPABILITIES.md` not auto-loaded (brief only); no embeddings;
  reuse `audit_log` rather than a new counter table.
