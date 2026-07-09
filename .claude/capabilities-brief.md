# melee-agent capabilities (auto-generated — DO NOT EDIT; run `melee-agent capabilities generate`)

Before building any tool/script/command, run `melee-agent capabilities search <task>`.

## CLI command groups (`melee-agent <group> --help`)
- analytics: errors, export, functions, sessions, summary, trends
- attempts: list, record, show
- audit: discover-prs, duplicates, net-new, recover-matches
- backtest: build-corpus, calibrate, close-sandbox, discover, escalation, judge-input, open-sandbox, pending-judge, report, run, set-advisory, set-agent, status
- capabilities: generate, search, show
- claim: add, list, release
- commit: apply, check-callers, format
- compilers: (direct)
- complete: document, list, mark
- debug: coalesce-search, diff-schedule, dump, inspect, intervene, measure, mutate, permute, retro, search, select-order-search, solve, suggest, target, util
- docker: down, status, up
- extract: files, get, list
- ghidra: cache-build, decompile, func, setup, status, strings, xrefs
- harvest: (direct)
- hook: install, uninstall, validate
- issue: campaign-report, claim, list, note, release, report, resolve, show
- layout: audit
- mismatch: add, backfill, get, init, list, m2c, migrate, opcode, record-success, review, rm, search, show, stats
- opseq: (direct)
- patterns: anti-pattern, anti-patterns, api, check, inlines, similar, wrapper, wrappers
- pr: check, describe, feedback, link, link-batch, list, status, unlink
- scratch: compile, create, decompile, get, recover-best, search, search-context, sync-from-repo, update, update-context
- setup: dol, status
- state: agents, cleanup, diff-remotes, export, history, populate-addresses, prs, rebuild, refresh-prs, stale, status, sync-report, urls, validate
- struct: callback, issues, offset, show, verify
- stub: add, check, list
- sync: auth, clear, dedup, fetch, find-duplicates, fix-ownership, list, production, slugs, status, validate
- transform-corpus: mine

## Common task shortcuts
- register allocation: `melee-agent debug inspect lifetime-pressure`, `/mwcc-debug`, `/mwcc-inspect`
- score candidate: `melee-agent debug target score-source`, `melee-agent debug target score-dump`
- find callers: `/ghidra`, `melee-agent commit check-callers`
- transform corpus pressure coalesce select order: `melee-agent debug mutate lifetime-layout`, `melee-agent debug coalesce-search`, `melee-agent debug select-order-search`

## Skills (invoke `/<name>`)
- backfill-analysis — Analyze matched functions to discover mismatch patterns. Use when backfilling the mismatch-db from git history.
- collect-for-pr — Collect pending worktree commits into a PR for review. Use this skill when subdirectory worktrees have accumulated 4-7+ commits that should be batched together and submitted for review. Invoked with /collect-for-pr or automatically when monitoring worktree status.
- decomp — Use when decompiling or matching Super Smash Bros. Melee functions in this repo, especially when iterating on C source against assembly diffs.
- decomp-fixup — Fix build issues for matched functions in the Melee decompilation project. Use this skill when builds are failing due to header mismatches, signature issues, or caller updates needed after a function has been matched. Invoked with /decomp-fixup [function_name] or automatically when diagnosing build failures.
- decomp-remote — Match decompiled C code using the remote decomp.me server workflow. Use this skill when you want to iterate on a scratch using the remote server. For most tasks, prefer /decomp which uses the faster local workflow.
- discord-knowledge — Search Discord knowledge base for decompilation patterns, compiler tricks, and historical context. Use when stuck on matching or need background on a technique.
- first-pass-decomp — Generate initial C code from assembly using local m2c. Use this skill to get first-pass decompilations for unmatched functions before manual refinement.
- fresh-eyes — Use when a Melee match is stuck or plateaued (especially >=95%), has accumulated a long string of tool-extension issues, or has been called a ceiling / banked / unreachable / exhausted / "below the source" — or when mwcc-debug/solve/force-phys are giving diminishing returns.
- ghidra — Use cached Ghidra-derived xrefs and string lookups (fast SQLite queries) for cross-reference discovery and string-based naming. Also offers live Ghidra decompile as a heavy fallback. Use when finding callers across the whole binary or naming functions from debug strings.
- item-decomp — Conventions and domain knowledge for item-related code in Melee. Use when decompiling item functions (it_* prefix).
- melee-debug — [EXPERIMENTAL] Debug Melee in Dolphin emulator. Breakpoints are unreliable with JIT mode. Use for memory inspection only until stability improves.
- mismatch-db — Knowledge base for common assembly mismatches. Use to interpret diffs when matching functions.
- mwcc-debug — Dump MWCC's internal codegen passes (BEFORE/AFTER REGISTER COLORING, instruction scheduling, etc.) for a Melee TU. Runs locally on macOS (via wibo+Zig-built DLL) by default, or on a remote Windows host as a fallback. Use when stuck on register-allocation cascades or other last-mile matching issues; complement to mwcc-inspect (which shows front-end IR / ENodes / ObjObjects).
- mwcc-inspect — Inspect MWCC's internal IR (ENodes, ObjObjects, Statements) for a Melee TU by running RootCubed/mwcc-inspector on a remote Windows host. Use when stuck on register-allocation cascades or other last-mile matching issues that mismatch-db, opseq, ghidra, and discord-knowledge haven't explained — this is the next tool to reach for, not the first.
- mwcc-retro — Dump retail MWCC GC/1.2.5n front-end IRO and exact backend/regalloc traces via retrowin32+gdb. Use when you need optimizer pass visibility, retail PCode/allocator facts, or retail-vs-debug-DLL fidelity after lighter matching tools and mwcc-debug.
- opseq — Find functions by opcode sequence patterns. Use when stuck on a function and want to find similar already-decompiled code for reference.
- ppc-ref — Look up PowerPC instruction set documentation. Use when you need to understand what a specific instruction does, its operands, or behavior.
- prepare-pr — Use this skill when the user wants to prepare decomp work for an upstream PR.
- sync-upstream — Use this skill when the user wants to sync their fork with the upstream doldecomp/melee repository.
- understand — Document and name functions, structs, and fields in Melee decompilation. Use for improving readability, discovering function purposes, and naming unknown fields. Invoked with /understand <target> where target is a function, file, or struct name.
- workflow — Use this skill to manage git branches and prepare changes for upstream PRs.
