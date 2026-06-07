# Melee Decompilation Project

Reverse-engineering Super Smash Bros. Melee (GameCube) to matching C code using a self-hosted decomp.me instance.

## Architecture

```
melee/
├── src/melee/              # Decompiled C source files
├── include/melee/          # Header files
├── config/GALE01/          # Build config and symbols
├── build/                  # Build output (asm, obj files)
├── tools/                  # Build tools (ninja, dtk)
├── .claude/skills/         # Claude Code skills for decompilation
└── docs/                   # Documentation
```

## Key Files

| Location | Purpose |
|----------|---------|
| `~/.config/decomp-me/agent_state.db` | SQLite database (primary state storage) |
| `~/.config/decomp-me/` | Persistent config (cookies, tokens) |
| `config/GALE01/symbols.txt` | Symbol definitions |
| `src/melee/` | Decompiled C source |
| `include/melee/` | Header files |

## CLI Commands

All operations via `python -m src.cli` or `melee-agent`:

```bash
# Scratch operations (primary workflow)
melee-agent scratch compile <slug> --stdin --diff  # Compile from stdin (use with heredoc)
melee-agent scratch compile <slug> -s <file>       # Compile from file
melee-agent scratch compile <slug> -r              # Compile with refreshed context
melee-agent scratch get <slug> --diff              # Show current diff
melee-agent scratch get <slug> --context           # Show scratch context
melee-agent scratch get <slug> --grep "pattern"   # Search context
melee-agent scratch update-context <slug>          # Rebuild context from repo headers
melee-agent scratch decompile <slug>               # Re-run m2c decompiler

# Function discovery
melee-agent extract list --max-match 0.50  # Find unmatched functions
melee-agent extract list --module mn       # Filter by module
melee-agent extract get <func>             # Get ASM + metadata
melee-agent extract get <func> --create-scratch  # Create scratch (preferred)

# Type/struct helpers
melee-agent struct offset 0x1898           # What field is at offset?
melee-agent struct show dmg --offset 0x1890  # Show fields near offset
melee-agent struct issues                  # Show known type issues

# Mismatch pattern database
melee-agent mismatch search "pattern"      # Search known patterns
melee-agent mismatch list                  # List all patterns

# Stub management
melee-agent stub check <func>         # Check if stub exists
melee-agent stub add <func>           # Add missing stub marker

# Tool issue reporting (bugs, feature requests, papercuts, blockers)
melee-agent issue report "short summary" --tool mwcc-debug --kind bug --function <func>
melee-agent issue list --status open
melee-agent issue list --available          # only unclaimed open issues (grab one of these)
melee-agent issue show <id>
melee-agent issue claim <id>                # claim before working it; fails if already claimed
melee-agent issue release <id>              # give a claim back without resolving
melee-agent issue resolve <id> --note "fixed in <commit-or-summary>"  # also clears the claim
```

## Tooling Feedback

Agents are highly encouraged to report tooling bugs, hangs, papercuts,
missing affordances, and feature requests as soon as they encounter them.
Use the shared issue queue in `~/.config/decomp-me/agent_state.db`:

```bash
melee-agent issue report "mwcc-debug local dump hung after COLORGRAPH DECISIONS" \
  --tool mwcc-debug --kind bug --function fn_80247510 \
  --body "Command, observed output, timeout, and what this blocked"
```

Before starting work on an issue, run `melee-agent issue claim <id>` so other
parallel agents skip it; there is no auto-expiry, so if an agent abandons a
claim, recover it with `melee-agent issue release <id> --force` (or
`melee-agent issue claim <id> --force` to take it over directly).

If a `melee-agent` command exits with an error through the wrapped entrypoint,
it prints a copyable `melee-agent issue report ...` command. If a command
hangs, interrupt it and report the hang manually with the command, tool,
function, worktree, and any last visible output. Prefer reporting over silently
working around repeated failures; tooling agents use this queue to fix issues
and mark them resolved so matching agents know when to retry.

## Environment

The local decomp.me server URL is **auto-detected** by probing candidate URLs in order:
1. `nzxt-discord.local` (home network)
2. `10.200.0.1` (WireGuard VPN)
3. `localhost:8000` (local dev)

Override with environment variables if needed:
```bash
DECOMP_API_BASE=http://custom-server      # Override auto-detection
DECOMP_AGENT_ID=agent-1                   # Optional: manual agent isolation
```

## Workflow

1. **Find function**: `extract list` or user-specified
2. **Create scratch**: `extract get <func> --create-scratch`
3. **Read source**: Check `src/melee/` for existing code + context
4. **Iterate**: Use heredoc pattern to compile:
   ```bash
   cat << 'EOF' | melee-agent scratch compile <slug> --stdin --diff
   void func(s32 arg0) {
       // your code here
   }
   EOF
   ```
5. **Commit to repo**: Edit source files directly (`.c` and `.h` files)
6. **Verify**: `python configure.py && ninja` to confirm build passes

## Git Workflow (Fork Management)

This is a fork of `doldecomp/melee` with additional tooling. The workflow keeps decomp work separate from fork tooling.

### Branch Structure
```
upstream/master ─────────────────────────► (canonical doldecomp/melee)
      │
      └── master (upstream + 1 tooling commit)
              │
              └── decomp work here
                        │
                        └── pr/* branches (fresh from upstream, for PRs)
```

### Key Principles
1. **Master = upstream + tooling**: Always exactly one commit ahead of upstream
2. **Decomp on master**: Work directly on master, commit freely
3. **PR branches are fresh**: Created from `upstream/master`, not `master`
4. **Reset, don't rebase**: After PR merges, reset master (saves WIP as patch)

### Workflow Scripts

```bash
# Check current status (branches, pending changes, recommendations)
./tools/workflow/status.sh

# Sync master with upstream (after PR merges or to get new changes)
./tools/workflow/sync-upstream.sh

# Create clean PR branch from decomp changes
./tools/workflow/create-pr.sh <branch-name>

# Update existing PR branch with changes from master (without switching)
./tools/workflow/update-pr.sh <pr-branch> [--amend]

# Create worktree for longer PR iteration (has symlinked tooling)
./tools/workflow/pr-worktree.sh create <pr-branch>
```

### Common Operations

**After finishing decomp work, prepare PR:**
```bash
./tools/workflow/status.sh              # Check what's ready
./tools/workflow/create-pr.sh my-module # Create PR branch
git push origin pr/my-module            # Push for review
```

**PR description hygiene:**

Do not mention fork-only tooling in upstream PR descriptions. Keep PR text
upstream-visible: describe matched/improved functions, source structure,
types, data layout, and verification. Do not mention local attempts DB,
attempt ledgers, `melee-agent`, `tools/checkdiff.py`, worktree doctor output,
Discord archive searches, or agent process notes. Convert local notes into
reviewable facts, for example "Several remaining functions in this file are
left unmatched" instead of "Remaining functions are documented in the local
attempts DB."

**After your PR is merged upstream:**
```bash
./tools/workflow/sync-upstream.sh       # Reset master to upstream + tooling
git branch -D pr/my-module              # Delete merged PR branch
```

**Iterating on PR after feedback:**
```bash
# Option A: Quick updates (stay on master with tooling)
# Make fixes on master, then apply to PR branch
./tools/workflow/update-pr.sh pr/my-module
git push origin pr/my-module --force-with-lease

# Option B: Longer iteration (dedicated worktree with tooling)
./tools/workflow/pr-worktree.sh create pr/my-module
cd ../melee-pr
# Work directly on PR branch with full tooling access
# Commit and push as normal
```

## Skills

### Git Workflow
- `/workflow` - General workflow management (status, branch organization)
- `/prepare-pr` - Step-by-step PR preparation from decomp changes
- `/sync-upstream` - Guided upstream synchronization after PR merges

### Decompilation Workflow
- `/decomp [func]` - Local decompilation workflow: edit source files directly, use `tools/checkdiff.py` for diffs (recommended)
- `/decomp-remote [func]` - Remote decomp.me server workflow: create scratches, iterate via server API
- `/decomp-fixup [func]` - Fix build issues for matched functions (headers, callers, types)
- `/first-pass-decomp [func]` - Generate initial C code from assembly using local m2c

### Getting Unstuck
**When stuck on a function, proactively use these skills to find patterns and solutions:**

- `/mismatch-db` - Search database of known assembly mismatch patterns and their fixes
- `/discord-knowledge` - Search 6+ years of Discord knowledge for compiler tricks, matching techniques, and historical context
- `/opseq` - Find similar already-matched functions by opcode sequence patterns
- `/ppc-ref` - Look up PowerPC instruction documentation
- `/ghidra` - Cross-references (callers/callees) and debug-string lookups via cached SQLite queries (sub-ms). Heavy `ghidra decompile` is also available as a second-opinion fallback.

### Documentation & Understanding
- `/understand [target]` - Document and name functions, structs, and fields after matching

**Pro tip:** Don't spin on the same mismatch for too long. After 2-3 failed attempts, use `/mismatch-db` or `/discord-knowledge` to search for known patterns. Someone has likely solved this exact issue before.

## Knowledge Base

When stuck on matching or need compiler/pattern context:
```bash
rg -i -C 5 "<keyword>" docs/discord-knowledge/
```

Key resource: `docs/discord-knowledge/DISCORD_KNOWLEDGE.md` - consolidated knowledge covering compiler patterns, matching techniques, type information, and project history (2020-2026).

## Build

In isolated worktrees, run build and checkdiff commands from the current
worktree. Do not `cd` to `/Users/mike/code/melee` from an isolated agent; that
builds the shared main checkout and can race another agent's edits. If a fresh
worktree is missing `orig/GALE01/sys/main.dol`, run
`python tools/worktree-doctor.py --fix` in that worktree before building.

```bash
python configure.py && ninja  # Build melee
```

## Context Summarization (Critical for Long Sessions)

When a session runs out of context and gets summarized, **preserve this state**:

1. **Active function being worked on** - e.g., `mnDiagram2_80243A3C`
2. **Active scratch slug** - e.g., `xYz12`
3. **Module/subdirectory** - e.g., `mn`
4. **Current match percentage** - e.g., `87.2%`

## Notes

- Compiler: `mwcc_233_163n` (GC/1.2.5n) with `-O4,p -nodefaults -proc gekko -fp hardware -Cpp_exceptions off -enum int -fp_contract on -inline auto`
- Platform: `gc_wii` (GameCube/Wii PowerPC)
- Always include file-local structs in scratch source (not in headers)
- **Use CLI tools, not curl** - All API operations should go through `melee-agent` commands, not raw curl/HTTP calls
- **Think like a developer, not like the ASM** - Developers write simple, natural code. Complex ASM patterns (partial loop unrolling, `bdnz` with manual stores) are compiler optimizations, not developer intent. Ask "why would a developer write this?" before trying exotic tricks.
- **Structure first, registers last** - Don't fix register allocation until the instruction sequence matches. Registers often "fall into place" when structure is correct; chasing registers early leads to local maxima.
- **Match % can drop when correct** - Don't revert structurally correct changes just because match % dropped. A correct `bl` (function call) at 60% is better than incorrect inlined code at 85%. You can improve from correct structure.
- **PAD_STACK is a last resort** - Stack mismatches usually mean missing inlines or variables, not "add padding." Investigate missing inline functions, local variables, or type differences before using PAD_STACK.
- **Name hidden string/data offsets** - Do not leave `OSReport`/`__assert` strings or other data references as raw `base + offset` pointer math in PR code. If the bytes live inside a nearby data blob, model the blob with a file-local struct and reference the named field, or use another direct named string/data reference that preserves matching codegen.
- **`int` vs `s32` for loop counters** - MWCC treats these differently for loop optimization. `s32` is typedef'd to `long`, and MWCC may apply different unrolling heuristics. If a simple loop doesn't match, try `int i` instead of `s32 i`.
