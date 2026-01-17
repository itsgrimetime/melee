# Remote Environment Support

This document describes which agent tools work in a remote/containerized environment and how to configure them.

## Overview

The melee-agent tooling was originally designed for local development with a self-hosted decomp.me instance. Some tools require local network access or specific hardware that won't be available in a remote container (e.g., Claude Code running in the cloud).

## Quick Start for Remote Environments

Set these environment variables before running any melee-agent commands:

```bash
# REQUIRED: Point to a publicly accessible decomp.me instance
export DECOMP_API_BASE=https://your-decomp-me-instance.com

# REQUIRED for PR operations
export GITHUB_TOKEN=ghp_xxxxx

# OPTIONAL: Override auto-detected agent ID
export DECOMP_AGENT_ID=remote-agent-1
```

## Tool Compatibility Matrix

| Tool/Command | Remote Support | Notes |
|--------------|----------------|-------|
| `extract list` | ✅ Full | Reads local build artifacts |
| `extract get` | ✅ Full | Reads local build artifacts |
| `scratch create` | ⚠️ Needs Config | Requires `DECOMP_API_BASE` |
| `scratch compile` | ⚠️ Needs Config | Requires `DECOMP_API_BASE` |
| `scratch get` | ⚠️ Needs Config | Requires `DECOMP_API_BASE` |
| `scratch decompile` | ⚠️ Needs Config | Requires `DECOMP_API_BASE` |
| `claim add/release` | ✅ Full | Local SQLite operations |
| `state status` | ✅ Full | Local SQLite operations |
| `commit apply` | ✅ Full | Git operations |
| `hook validate` | ✅ Full | Local file analysis |
| `checkdiff.py` | ✅ Full | Auto-downloads dtk if needed |
| `sync production` | ❌ Not Supported | Requires browser auth for Cloudflare |
| `worktree collect` | ⚠️ Needs Auth | Requires `GITHUB_TOKEN` |
| `pr feedback` | ⚠️ Needs Auth | Requires `GITHUB_TOKEN` |

## Skill Compatibility Matrix

| Skill | Remote Support | Notes |
|-------|----------------|-------|
| `/decomp` | ⚠️ Needs Config | Core workflow; needs `DECOMP_API_BASE` |
| `/decomp-fixup` | ⚠️ Needs Config | Needs `DECOMP_API_BASE` |
| `/decomp-permuter` | ❌ Limited | Needs local permuter install + build tools |
| `/mismatch-db` | ✅ Full | Local database lookups |
| `/opseq` | ⚠️ Partial | Search works; synthesis needs MWCC/Wine |
| `/ppc-ref` | ❌ Not Supported | Requires manual PDF installation |
| `/melee-debug` | ❌ Not Supported | Requires Dolphin emulator |
| `/understand` | ✅ Full | Documentation skill |
| `/item-decomp` | ✅ Full | Documentation skill |
| `/collect-for-pr` | ⚠️ Needs Auth | Requires `GITHUB_TOKEN` |
| `/backfill-analysis` | ✅ Full | Git history analysis |

## Detailed Requirements

### decomp.me Server Access

The default configuration tries these local URLs in order:
1. `http://nzxt-discord.local` (home network)
2. `http://10.200.0.1` (WireGuard VPN)
3. `http://localhost:8000` (local dev)

For remote environments, you MUST set `DECOMP_API_BASE`:

```bash
export DECOMP_API_BASE=https://your-decomp-me-instance.com
```

**Options for decomp.me access:**

1. **Host your own decomp.me** (Recommended)
   - Deploy decomp.me to a cloud server
   - Set `DECOMP_API_BASE` to the public URL

2. **Use production decomp.me** (Limited)
   - `https://decomp.me` is protected by Cloudflare
   - Requires `cf_clearance` cookie from browser auth
   - Not practical for automated/headless environments

3. **Cloudflare Tunnel** (Advanced)
   - Run decomp.me locally
   - Expose via Cloudflare Tunnel
   - Container connects to tunnel URL

### checkdiff.py (Auto-Download Support)

The `checkdiff.py` tool now automatically downloads the required disassembler if not found:

1. First tries to find `powerpc-eabi-objdump` (devkitPPC)
2. Falls back to `dtk` (decomp-toolkit) if objdump not found
3. Auto-downloads `dtk` from GitHub releases if neither is available

Downloaded binaries are cached in `~/.cache/melee-tools/`.

You can also set the `PPC_EABI_OBJDUMP` environment variable to specify a custom objdump path.

### Build Tools

For full functionality (compilation, opseq synthesis), the container needs:

```dockerfile
# Example Dockerfile additions
RUN apt-get update && apt-get install -y \
    wine64 \
    python3-pip \
    ninja-build

# Install devkitPPC (for objdump, assembler)
RUN wget https://github.com/devkitPro/pacman/releases/download/v1.0.2/devkitpro-pacman.amd64.deb \
    && dpkg -i devkitpro-pacman.amd64.deb \
    && dkp-pacman -Sy --noconfirm devkitPPC

# Alternative: Install wibo for faster compilation
RUN wget -O /usr/local/bin/wibo \
    https://github.com/decompals/wibo/releases/latest/download/wibo \
    && chmod +x /usr/local/bin/wibo
```

The melee repo's build system will download compilers automatically:
```bash
python configure.py
ninja  # Downloads MWCC compiler on first run
```

### State Persistence

The agent stores state in `~/.config/decomp-me/`:
- `agent_state.db` - SQLite database (claims, scratches, functions)
- `cookies_*.json` - Session cookies per agent

For persistent state across container restarts, mount this directory:
```bash
docker run -v decomp-state:/root/.config/decomp-me ...
```

### GitHub Authentication

For PR operations (`worktree collect --create-pr`, `pr feedback`):
```bash
export GITHUB_TOKEN=ghp_xxxxx
# Or configure gh CLI
gh auth login
```

## What Cannot Be Made Remote

### 1. Dolphin Emulator Debugging (`/melee-debug`)

Runtime debugging requires:
- Dolphin emulator running locally
- GDB stub connection (port 9090)
- `dolphin-memory-engine` native library
- Game ISO

This cannot be containerized in a practical way.

### 2. PowerPC Reference PDFs (`/ppc-ref`)

The PDFs are not included in the repository due to copyright/size:
- `ppc_750cl.pdf` - IBM PowerPC 750CL User's Manual
- `powerpc-cwg.pdf` - IBM Compiler Writer's Guide
- `MPC5xxUG.pdf` - CodeWarrior Targeting Manual

You must obtain these manually and place them in `.claude/skills/ppc-ref/`.

### 3. Production Sync (`melee-agent sync production`)

Syncing to `https://decomp.me` requires a Cloudflare `cf_clearance` cookie obtained by solving a browser challenge. This cannot be automated.

## Recommended Remote Setup

1. **Deploy decomp.me to cloud** (e.g., AWS, GCP, DigitalOcean)
2. **Create Docker image** with build tools (see above)
3. **Mount state volume** for persistence
4. **Set environment variables**:
   ```bash
   DECOMP_API_BASE=https://your-decomp-me.com
   GITHUB_TOKEN=ghp_xxxxx
   DECOMP_AGENT_ID=remote-agent-1
   ```
5. **Accept limitations**: No runtime debugging, no PPC reference, no production sync

## Environment Variable Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DECOMP_API_BASE` | Yes (remote) | URL of decomp.me instance |
| `DECOMP_ME_URL` | No | Alias for `DECOMP_API_BASE` |
| `DECOMP_AGENT_ID` | No | Override auto-detected agent ID |
| `DECOMP_COOKIES_FILE` | No | Custom cookies file location |
| `LOCAL_DECOMP_CANDIDATES` | No | Comma-separated list of URLs to probe |
| `GITHUB_TOKEN` | For PRs | GitHub personal access token |
| `CF_CLEARANCE` | For prod sync | Cloudflare cookie (browser auth required) |
| `DECOMP_SESSION_ID` | No | decomp.me session cookie |
| `PPC_EABI_OBJDUMP` | No | Custom path to powerpc-eabi-objdump |

## Troubleshooting

### "Could not find local decomp.me server"

Set `DECOMP_API_BASE` to a reachable URL:
```bash
export DECOMP_API_BASE=https://your-server.com
melee-agent scratch create func_name
```

### "Compilation failed" or "mwcc not found"

Ensure build tools are installed:
```bash
# Check for MWCC compiler
ls build/compilers/GC/1.2.5n/mwcceppc.exe

# Check for Wine/wibo
which wine || which wibo

# Rebuild to download tools
python configure.py && ninja
```

### State not persisting

Mount the config directory:
```bash
docker run -v decomp-state:/root/.config/decomp-me your-image
```

### GitHub operations failing

Set up authentication:
```bash
export GITHUB_TOKEN=ghp_xxxxx
# Or
gh auth login --with-token < token.txt
```

### checkdiff.py fails to download dtk

If the auto-download fails (network restrictions, proxy issues), manually download:
```bash
# Download dtk for your platform
curl -L https://github.com/encounter/decomp-toolkit/releases/download/v1.8.0/dtk-linux-x86_64 \
  -o ~/.cache/melee-tools/dtk
chmod +x ~/.cache/melee-tools/dtk
```

Or place dtk in `tools/dtk` within the repo.
