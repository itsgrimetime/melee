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
```

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

## Skills

- `/decomp [func]` - Full decompilation matching workflow (see `.claude/skills/decomp/SKILL.md`)
- `/decomp-fixup [func]` - Fix build issues for matched functions (headers, callers, types)

## Build

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

- Compiler: `mwcc_247_92` with `-O4,p -inline auto -nodefaults`
- Platform: `gc_wii` (GameCube/Wii PowerPC)
- Match threshold: 95%+ with only register/offset diffs is commit-ready
- Always include file-local structs in scratch source (not in headers)
- **Use CLI tools, not curl** - All API operations should go through `melee-agent` commands, not raw curl/HTTP calls
