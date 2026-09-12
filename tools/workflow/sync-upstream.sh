#!/bin/bash
# sync-upstream.sh - Reset master to upstream/master + tooling overlay
#
# Usage: ./tools/workflow/sync-upstream.sh [--dry-run]
#
# This script:
# 1. Saves any WIP work as a patch
# 2. Resets master to upstream/master
# 3. Re-applies the tooling overlay
# 4. Optionally restores WIP work

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}DRY RUN MODE - no changes will be made${NC}"
fi

# Tooling files/directories to preserve
TOOLING_PATHS=(
    "tools/"
    ".claude/"
    "docs/"
    ".github/"
    ".vscode/"
    ".gitignore"
    "CLAUDE.md"
    "AGENTS.md"
    ".codex/"
    "decomp.yaml"
    "permuter_settings.toml"
)

apply_precommit_overlay() {
    python3 - "$REPO_ROOT/.pre-commit-config.yaml" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path


path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit("pre-commit overlay failed: upstream config is missing")

text = path.read_text(encoding="utf-8")
fork_exclude = (
    r"^(\.claude/|\.codex/|\.github/fork-only-files\.txt$|"
    r"\.github/workflows/(capabilities-drift|editorconfig|melee-agent|"
    r"style-check|taxonomy-pages)\.yml$|\.vscode/|AGENTS\.md$|CLAUDE\.md$|"
    r"decomp\.yaml$|docs/|permuter_settings\.toml$|tools/)"
)
for hook_id in ("style-check", "clang-format", "editorconfig-checker"):
    old = f"    - id: {hook_id}\n"
    new = old + f"      exclude: {fork_exclude}\n"
    if text.count(old) == 1:
        text = text.replace(old, new, 1)
    elif text.count(new) != 1:
        raise SystemExit(
            f"pre-commit overlay failed: expected one {hook_id} anchor"
        )

hook_ids = ("melee-style-check", "check-fork-files", "capabilities-drift")
present = [hook_id for hook_id in hook_ids if f"- id: {hook_id}" in text]
if len(present) == len(hook_ids):
    path.write_text(text, encoding="utf-8")
    raise SystemExit(0)
if present:
    raise SystemExit(
        "pre-commit overlay failed: found only some fork hooks: "
        + ", ".join(present)
    )

overlay = r'''

- repo: local
  hooks:
  - id: melee-style-check
    name: Melee style check
    entry: python tools/check-style.py
    language: python
    types: [c]
    pass_filenames: true
    description: >
      Checks C/H files for style violations derived from doldecomp/melee
      maintainer feedback. See docs/STYLE_GUIDE.md for details.

  - id: check-fork-files
    name: Check for fork-only files
    entry: python tools/check-fork-files.py
    language: python
    pass_filenames: false
    always_run: true
    stages: [pre-push]
    description: Blocks pushing fork-specific files to doldecomp/melee upstream

  - id: capabilities-drift
    name: capabilities index up to date
    entry: bash -c 'melee-agent capabilities generate && git diff --exit-code -- .claude/capabilities-brief.md docs/CAPABILITIES.md'
    language: system
    pass_filenames: false
    files: '^(tools/melee-agent/src/cli/|\.claude/skills/|\.claude/hooks/|\.claude/settings\.json|CLAUDE\.md|docs/agent-tool-manifest\.md)'
'''

path.write_text(text.rstrip() + overlay.rstrip() + "\n", encoding="utf-8")
PY
}

apply_configure_overlay() {
    python3 - "$REPO_ROOT/configure.py" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path


path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")


def replace_once(label: str, old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"configure.py overlay failed: expected one {label} anchor, found {count}"
        )
    text = text.replace(old, new, 1)


require_old = '''parser.add_argument(
    "--require-protos",
    dest="require_protos",
    action="store_true",
    help="require function prototypes",
)
'''
require_new = '''parser.add_argument(
    "--require-protos",
    dest="require_protos",
    action="store_true",
    default=True,
    help="require function prototypes (default: enabled)",
)
parser.add_argument(
    "--no-require-protos",
    dest="require_protos",
    action="store_false",
    help="disable function prototype requirement",
)
'''
replace_once("require-protos parser block", require_old, require_new)
replace_once("wibo tag", 'config.wibo_tag = "0.7.0"', 'config.wibo_tag = "1.0.0"')

helper = r'''def _purge_wrong_arch_wibo(config: ProjectConfig) -> None:
    """Fork-only: drop build/tools/wibo if it's wrong arch for this host.

    download_tool.py picks the correct wibo binary per platform, but once a
    binary exists at build/tools/wibo, ninja won't redownload. The wrong-arch
    binary can land there via cross-host worktree copies, stale state from a
    prior platform, or an older download_tool.py that used the legacy URL.
    Removing it lets the next build fetch a fresh one.
    """
    import sys

    wibo = config.build_dir / "tools" / "wibo"
    if not wibo.exists():
        return
    try:
        with open(wibo, "rb") as f:
            magic = f.read(4)
    except OSError:
        return
    is_macho = magic in (
        b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
        b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    )
    is_elf = magic == b"\x7fELF"
    correct = is_macho if sys.platform == "darwin" else is_elf
    if not correct:
        kind = "Mach-O" if sys.platform == "darwin" else "ELF"
        print(
            f"warning: {wibo} is wrong arch (expected {kind} for {sys.platform}); "
            "removing so it will be re-downloaded"
        )
        wibo.unlink()


'''
insert_after = '''config.progress_report_args = [
    # Marks relocations as mismatching if the target value is different
    f"--config functionRelocDiffs={args.reloc_diffs}",
]

'''
replace_once("progress report args block", insert_after, insert_after + helper)
replace_once(
    "configure generate_build call",
    '''    # Write build.ninja and objdiff.json
    generate_build(config)
''',
    '''    # Write build.ninja and objdiff.json
    _purge_wrong_arch_wibo(config)
    generate_build(config)
''',
)

path.write_text(text, encoding="utf-8")
PY
}

remove_stale_build_configs() {
    if [[ ! -d "$REPO_ROOT/build" ]]; then
        return
    fi
    find "$REPO_ROOT/build" -mindepth 2 -maxdepth 2 -name config.json -type f -print -delete
}

echo "=== Upstream Sync Tool ==="
echo ""

# Check we're on master or can switch to it
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "master" ]]; then
    echo -e "${YELLOW}Currently on branch: $CURRENT_BRANCH${NC}"
    echo "Will switch to master for sync"
fi

# Fetch upstream
echo "Fetching upstream..."
git fetch upstream

# Show what we're syncing
UPSTREAM_HEAD=$(git rev-parse --short upstream/master)
MASTER_HEAD=$(git rev-parse --short master)
echo ""
echo "upstream/master: $UPSTREAM_HEAD"
echo "master:          $MASTER_HEAD"
echo ""

# Check for new upstream commits
NEW_COMMITS=$(git log --oneline master..upstream/master | wc -l | tr -d ' ')
if [[ "$NEW_COMMITS" == "0" ]]; then
    echo -e "${GREEN}Master is already up to date with upstream!${NC}"
    exit 0
fi

echo "New upstream commits: $NEW_COMMITS"
git log --oneline master..upstream/master | head -10
if [[ "$NEW_COMMITS" -gt 10 ]]; then
    echo "... and $((NEW_COMMITS - 10)) more"
fi
echo ""

# Check for uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo -e "${RED}Error: You have uncommitted changes. Please commit or stash them first.${NC}"
    exit 1
fi

# Check for WIP work on master that's not in upstream
WIP_COMMITS=$(git log --oneline upstream/master..master -- src/ config/ include/ | wc -l | tr -d ' ')
if [[ "$WIP_COMMITS" -gt 0 ]]; then
    echo -e "${YELLOW}Found $WIP_COMMITS commits with src/config changes on master${NC}"
    echo "These will be saved as a patch before sync."
    echo ""

    # Create patch for src/config changes
    PATCH_FILE="/tmp/melee-wip-$(date +%Y%m%d-%H%M%S).patch"

    if [[ "$DRY_RUN" == false ]]; then
        git diff upstream/master..master -- src/ config/ include/ > "$PATCH_FILE"
        if [[ -s "$PATCH_FILE" ]]; then
            echo -e "${GREEN}WIP saved to: $PATCH_FILE${NC}"
        else
            rm "$PATCH_FILE"
            PATCH_FILE=""
        fi
    else
        echo "[DRY RUN] Would save WIP to: $PATCH_FILE"
    fi
fi

if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo "[DRY RUN] Would perform:"
    echo "  1. git checkout master"
    echo "  2. git reset --hard upstream/master"
    echo "  3. Restore fork tooling from current master"
    echo "  4. Apply fork configure.py and pre-commit overlays"
    echo "  5. Remove stale build/*/config.json"
    echo "  6. git commit -m 'restore fork tooling after upstream sync'"
    exit 0
fi

# Perform the sync
echo ""
echo "Performing sync..."

# Switch to master if needed
if [[ "$CURRENT_BRANCH" != "master" ]]; then
    git checkout master
fi

# Create backup branch
BACKUP_BRANCH="backup/master-pre-sync-$(date +%Y%m%d-%H%M%S)"
git branch "$BACKUP_BRANCH"
echo "Backup created: $BACKUP_BRANCH"

# Reset to upstream
git reset --hard upstream/master

# Reapply only the changes from the one fork tooling commit. Restoring whole
# directories would resurrect upstream files that were changed or deleted
# after the previous sync.
echo "Reapplying tooling changes..."
TOOLING_BASE=$(git merge-base upstream/master "$BACKUP_BRANCH")
if ! git diff --quiet "$TOOLING_BASE" "$BACKUP_BRANCH" -- "${TOOLING_PATHS[@]}"; then
    git diff --binary "$TOOLING_BASE" "$BACKUP_BRANCH" -- "${TOOLING_PATHS[@]}" \
        | git apply --3way --index
fi

# Recreate symlinks
ln -sf CLAUDE.md AGENTS.md 2>/dev/null || true
mkdir -p .codex && ln -sf ../.claude/skills .codex/skills 2>/dev/null || true

echo "Applying configure.py fork overlay..."
apply_configure_overlay

echo "Applying pre-commit fork overlay..."
apply_precommit_overlay

echo "Removing stale generated build configs..."
remove_stale_build_configs

# The tooling patch was applied with --index. Stage only edits to tracked files
# made by the overlays; leave unrelated untracked work alone.
git add -u
git add -f -- AGENTS.md .codex/skills
if ! git diff --cached --quiet; then
    git commit -m "restore fork tooling after upstream sync

Synced to upstream/master at $(git rev-parse --short upstream/master)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
fi

echo ""
echo -e "${GREEN}=== Sync Complete ===${NC}"
echo ""
echo "Master is now at upstream/master + tooling"
git log --oneline -3

if [[ -n "$PATCH_FILE" && -f "$PATCH_FILE" ]]; then
    echo ""
    echo -e "${YELLOW}WIP patch saved at: $PATCH_FILE${NC}"
    echo "To restore: git apply $PATCH_FILE"
fi

echo ""
echo "Backup branch: $BACKUP_BRANCH"
echo "To delete backup: git branch -D $BACKUP_BRANCH"
